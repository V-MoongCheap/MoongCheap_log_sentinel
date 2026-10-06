"""환경변수 기반 설정과 Loki 쿼리 조립."""
from __future__ import annotations

import dataclasses
import os

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RULES = os.path.join(PROJECT_ROOT, "resources", "rules.yaml")
DEFAULT_STATE_DB = os.path.join(PROJECT_ROOT, "data", "triage.db")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

@dataclasses.dataclass
class Config:
    grafana_url: str
    grafana_user: str
    grafana_password: str
    datasource_uid: str
    loki_query: str
    max_lines: int
    ingest_lag_sec: int
    first_run_lookback_min: int
    max_lookback_hours: int
    state_db: str
    rules_file: str
    discord_webhook: str
    github_token: str
    github_repo: str
    ai_mode: str              # off | issue | analyze | fix
    max_ai_dispatch_per_day: int
    issue_comment_interval_hours: int
    recurrence_grace_hours: int
    explore_hint: str

    @classmethod
    def from_env(cls) -> "Config":
        e = os.environ.get
        return cls(
            grafana_url=e("GRAFANA_URL", "https://grafana.moongcheap.shop").rstrip("/"),
            # 인증: GRAFANA_USER/GRAFANA_PASSWORD (basic auth)
            grafana_user=e("GRAFANA_USER", ""),
            grafana_password=e("GRAFANA_PASSWORD", ""),
            datasource_uid=e("GRAFANA_DS_UID", "P8E80F9AEF21F6940"),
            loki_query=e("LOKI_QUERY") or build_loki_query(
                namespace=e("LOKI_NAMESPACE", "moongcheap-develop"),
                app=e("LOKI_APP", "backend"),
                line_filter=e("LOKI_LINE_FILTER", '|~ "(?i)(error|warn)"'),
            ),
            max_lines=int(e("MAX_LINES", "5000")),
            ingest_lag_sec=int(e("INGEST_LAG_SEC", "60")),
            first_run_lookback_min=int(e("FIRST_RUN_LOOKBACK_MIN", "60")),
            max_lookback_hours=int(e("MAX_LOOKBACK_HOURS", "24")),
            state_db=e("STATE_DB", DEFAULT_STATE_DB),
            rules_file=e("RULES_FILE", DEFAULT_RULES),
            discord_webhook=e("DISCORD_WEBHOOK_URL", ""),
            github_token=e("GITHUB_TOKEN", ""),
            github_repo=e("GITHUB_REPO", ""),
            ai_mode=e("AI_MODE", "issue"),
            max_ai_dispatch_per_day=int(e("MAX_AI_DISPATCH_PER_DAY", "5")),
            issue_comment_interval_hours=int(e("ISSUE_COMMENT_INTERVAL_HOURS", "24")),
            recurrence_grace_hours=int(e("RECURRENCE_GRACE_HOURS", "2")),
            explore_hint=e("EXPLORE_HINT", ""),
        )


def build_loki_query(namespace: str, app: str, line_filter: str) -> str:
    """{namespace="...", app="..."} 형태의 스트림 셀렉터 + 라인 필터.
    moongcheap-backend-develop(ArgoCD 앱)의 파드는 Loki 에 namespace/app 라벨로 들어옵니다."""
    selectors = [f'namespace="{namespace}"']
    if app:
        selectors.append(f'app="{app}"')
    return "{" + ", ".join(selectors) + "} " + line_filter