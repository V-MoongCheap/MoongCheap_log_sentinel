"""파싱된 로그를 fingerprint 별로 묶고, 과거 이력과 비교해 신규·급증을 표시."""
from __future__ import annotations

from .classifier import Classifier, fingerprint
from .masking import mask
from .models import Group, RawLog
from .parsing import parse_line
from .state import State


def aggregate(raws: list[RawLog], clf: Classifier) -> tuple[dict[str, Group], int]:
    groups: dict[str, Group] = {}
    unparsed = 0
    seen: set[str] = set()
    for raw in sorted(raws, key=lambda r: r.ts_ns):
        if raw.row_id in seen:
            continue
        seen.add(raw.row_id)
        p = parse_line(raw, clf.app_package)
        if p is None or p.level not in ("ERROR", "WARN"):
            unparsed += 1
            continue
        service = raw.labels.get("service_name") or raw.labels.get("app") or "unknown"
        fp = fingerprint(service, p)
        raw_message = p.message[:300]   # 반복 판정은 마스킹 전 원문으로 (마스킹하면 서로 다른 값이 같아 보임)
        g = groups.get(fp)
        if g is None:
            cat, rule = clf.classify(p)
            p.message, p.stack, p.root_exc_msg = mask(p.message), mask(p.stack), mask(p.root_exc_msg)
            g = groups[fp] = Group(fp, service, cat, rule, p, first_ns=raw.ts_ns)
        g.count += 1
        g.last_ns = raw.ts_ns
        if raw.labels.get("pod"):
            g.pods.add(raw.labels["pod"])
        if len(g.messages) < 500 or raw_message in g.messages:
            g.messages[raw_message] += 1   # 메모리에만 존재, 외부로 보낼 때는 반드시 mask()
    return groups, unparsed


def apply_history(groups: dict[str, Group], state: State, clf: Classifier, start_ms: int, end_ms: int) -> None:
    """신규 여부와 급증(최근 7일 평균 대비)을 계산하고, 이번 구간 발생률을 상태 DB 에 기록."""
    window_h = max((end_ms - start_ms) / 3_600_000, 1 / 60)
    bucket = end_ms - end_ms % 3_600_000
    spike_min = int(clf.spike.get("min_count", 20))
    spike_ratio = float(clf.spike.get("ratio", 5))
    spike_min_history_h = int(clf.spike.get("min_history_hours", 24))

    for g in groups.values():
        g.is_new = state.get_fp(g.fp) is None
        baseline, observed_h = state.baseline_per_hour(g.fp, bucket)
        rate = g.count / window_h
        if g.count >= spike_min and observed_h >= spike_min_history_h and rate >= spike_ratio * max(baseline, 0.5):
            g.spike_ratio = rate / max(baseline, 0.5)
        state.upsert_fp(g)
        state.record_rate(g.fp, bucket, rate)