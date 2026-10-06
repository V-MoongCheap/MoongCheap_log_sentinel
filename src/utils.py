"""공용 유틸리티 (시간 포맷)."""
from __future__ import annotations

import datetime as dt

KST = dt.timezone(dt.timedelta(hours=9))


def fmt_ts(ns_or_ms: int, is_ns: bool = True) -> str:
    ms = ns_or_ms // 1_000_000 if is_ns else ns_or_ms
    return dt.datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d %H:%M:%S KST")