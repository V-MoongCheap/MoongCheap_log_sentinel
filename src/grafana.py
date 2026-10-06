"""Grafana /api/ds/query 로 Loki 로그 조회 (열 단위 data frame → 행 단위 변환, 자동 분할 페이지네이션)."""
from __future__ import annotations

import json
import logging

import requests

from .config import Config
from .models import RawLog

log = logging.getLogger(__name__)


def parse_grafana_response(payload: dict) -> list[RawLog]:
    """Grafana /api/ds/query 응답(열 단위 data frame)을 행 단위로 변환."""
    result = payload.get("results", {}).get("A", {})
    if result.get("error"):
        raise RuntimeError(f"Grafana query error: {result['error']}")
    rows: list[RawLog] = []
    for frame in result.get("frames", []):
        names = [f["name"] for f in frame["schema"]["fields"]]
        cols = frame.get("data", {}).get("values", [])
        if not cols or "Line" not in names:
            continue
        idx = {n: i for i, n in enumerate(names)}
        for i in range(len(cols[idx["Line"]])):
            labels = cols[idx["labels"]][i] if "labels" in idx else {}
            if isinstance(labels, str):
                labels = json.loads(labels)
            ts_ns = int(cols[idx["tsNs"]][i]) if "tsNs" in idx else int(cols[idx["Time"]][i]) * 1_000_000
            row_id = cols[idx["id"]][i] if "id" in idx else f"{ts_ns}_{hash(cols[idx['Line']][i])}"
            rows.append(RawLog(row_id, ts_ns, labels or {}, cols[idx["Line"]][i]))
    return rows


class GrafanaClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.auth = (cfg.grafana_user, cfg.grafana_password)   # curl -u user:pass 와 동일

    def _query(self, start_ms: int, end_ms: int) -> list[RawLog]:
        body = {
            "from": str(start_ms), "to": str(end_ms),
            "queries": [{
                "refId": "A", "datasource": {"uid": self.cfg.datasource_uid},
                "expr": self.cfg.loki_query, "queryType": "range", "maxLines": self.cfg.max_lines,
            }],
        }
        r = self.s.post(f"{self.cfg.grafana_url}/api/ds/query", json=body, timeout=60)
        r.raise_for_status()
        return parse_grafana_response(r.json())

    def fetch(self, start_ms: int, end_ms: int, depth: int = 0) -> list[RawLog]:
        """maxLines 에 걸리면 구간을 반으로 나눠 다시 조회 (로그 누락 방지)."""
        rows = self._query(start_ms, end_ms)
        if len(rows) >= self.cfg.max_lines:
            if end_ms - start_ms <= 1000 or depth >= 12:
                log.warning("구간 %s~%s 에서 maxLines(%d) 초과, 일부 로그가 잘렸을 수 있음",
                            start_ms, end_ms, self.cfg.max_lines)
                return rows
            mid = (start_ms + end_ms) // 2
            return self.fetch(start_ms, mid, depth + 1) + self.fetch(mid + 1, end_ms, depth + 1)
        return rows