"""실행 진입점: 조회 → 집계 → 이력 비교 → GitHub 이슈 → Discord 알림 → 체크포인트 저장."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from collections import Counter

import requests

from .aggregate import aggregate, apply_history
from .classifier import Classifier
from .config import Config
from .discord import build_discord_messages, send_discord
from .github_client import GitHub
from .grafana import GrafanaClient, parse_grafana_response
from .issues import handle_code_issues
from .models import RawLog
from .state import State
from .utils import KST, fmt_ts

_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
)


def parse_time_arg(s: str) -> int:
    """'2026-10-06 09:00' 또는 ISO 8601 → epoch ms. tz 미지정 시 KST 로 간주."""
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        d = None
        for fmt in _TIME_FORMATS:
            try:
                d = dt.datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if d is None:
            raise argparse.ArgumentTypeError(
                f"시각 형식을 해석할 수 없습니다: {s!r} (예: '2026-10-06 09:00')"
            )
    if d.tzinfo is None:
        d = d.replace(tzinfo=KST)
    return int(d.timestamp() * 1000)

log = logging.getLogger(__name__)


def resolve_window(cfg: Config, state: State, now_ms: int) -> tuple[int, int]:
    """마지막 체크포인트 이후부터, 수집 지연을 고려한 현재 시각 직전까지."""
    end_ms = now_ms - cfg.ingest_lag_sec * 1000
    checkpoint = state.get_meta("checkpoint_ms")
    start_ms = int(checkpoint) + 1 if checkpoint else end_ms - cfg.first_run_lookback_min * 60_000
    if end_ms - start_ms > cfg.max_lookback_hours * 3_600_000:
        log.warning("체크포인트가 너무 오래됨 → 최근 %d시간만 조회", cfg.max_lookback_hours)
        start_ms = end_ms - cfg.max_lookback_hours * 3_600_000
    return start_ms, end_ms


def load_logs(args: argparse.Namespace, cfg: Config, state: State, now_ms: int) -> tuple[list[RawLog], int, int]:
    if args.input_file:
        with open(args.input_file, encoding="utf-8") as f:
            raws = parse_grafana_response(json.load(f))
        ts = [r.ts_ns // 1_000_000 for r in raws] or [now_ms]
        return raws, min(ts), max(ts)
    if args.since is not None or args.until is not None:
        end_ms = args.until if args.until is not None else now_ms - cfg.ingest_lag_sec * 1000
        start_ms = args.since if args.since is not None else end_ms - cfg.first_run_lookback_min * 60_000
        if start_ms >= end_ms:
            raise ValueError(f"--since 는 --until 보다 이전이어야 합니다 ({start_ms} >= {end_ms})")
    else:
        start_ms, end_ms = resolve_window(cfg, state, now_ms)
    return GrafanaClient(cfg).fetch(start_ms, end_ms), start_ms, end_ms


def run(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    if args.state_db:
        cfg.state_db = args.state_db
    if not args.input_file and not (cfg.grafana_user and cfg.grafana_password and cfg.datasource_uid):
        log.error("GRAFANA_USER/GRAFANA_PASSWORD 와 GRAFANA_DS_UID 가 필요합니다")
        return 2

    clf = Classifier(cfg.rules_file)
    state = State(cfg.state_db)
    now_ms = int(time.time() * 1000)

    # 1. 조회
    raws, start_ms, end_ms = load_logs(args, cfg, state, now_ms)
    if state.get_meta("first_run_ms") is None:
        state.set_meta("first_run_ms", str(start_ms))
    log.info("쿼리: %s", cfg.loki_query)
    log.info("조회 구간 %s ~ %s, %d줄", fmt_ts(start_ms, False), fmt_ts(end_ms, False), len(raws))

    # 2. 파싱·분류·묶기, 3. 과거 이력과 비교
    groups, unparsed = aggregate(raws, clf)
    apply_history(groups, state, clf, start_ms, end_ms)

    # 4. 코드 오류 → GitHub 이슈 (+ AI 라벨)
    code_groups = [g for g in groups.values() if g.category in ("bug", "review")]
    if code_groups and cfg.ai_mode != "off":
        gh = GitHub(cfg.github_token, cfg.github_repo, args.dry_run)
        handle_code_issues(code_groups, gh, state, cfg, now_ms)

    # 5. Discord 요약 (비활성화)
    # if groups or args.always_notify:
    #     for msg in build_discord_messages(list(groups.values()), (start_ms, end_ms), unparsed):
    #         send_discord(cfg.discord_webhook, msg, args.dry_run)

    # 6. 모든 처리가 끝난 뒤에만 체크포인트 저장 (수동 구간 조회는 제외)
    manual_window = args.since is not None or args.until is not None
    if not args.input_file and not args.dry_run and not manual_window:
        state.set_meta("checkpoint_ms", str(end_ms))
    state.prune(now_ms)
    state.commit()
    log.info("완료: %d종 (%s)", len(groups), dict(Counter(g.category for g in groups.values())))
    return 0


def notify_failure(exc: Exception) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return
    try:
        requests.post(url, json={"content": f"⚠️ 로그 트리아지 실행 실패: `{type(exc).__name__}: {str(exc)[:300]}`"},
                      timeout=10)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m triage", description="Loki ERROR/WARN 로그 트리아지")
    ap.add_argument("--dry-run", action="store_true", help="Discord/GitHub 로 보내지 않고 출력만")
    ap.add_argument("--input-file", help="저장된 Grafana /api/ds/query 응답 JSON 으로 테스트")
    ap.add_argument("--state-db", help="상태 DB 경로 (기본: STATE_DB 환경변수)")
    ap.add_argument("--always-notify", action="store_true", help="로그가 없어도 Discord 에 요약 전송")
    ap.add_argument("--since", type=parse_time_arg, metavar="TIME",
                    help="조회 시작 시각 (예: '2026-10-06 09:00', tz 미지정 시 KST). "
                         "체크포인트 무시, 저장도 하지 않음")
    ap.add_argument("--until", type=parse_time_arg, metavar="TIME",
                    help="조회 종료 시각 (기본: 지금 - INGEST_LAG_SEC)")
    args = ap.parse_args()
    if args.input_file and (args.since is not None or args.until is not None):
        ap.error("--input-file 과 --since/--until 은 함께 쓸 수 없습니다")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        return run(args)
    except Exception as exc:
        log.exception("트리아지 실패")
        if not args.dry_run:
            notify_failure(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())