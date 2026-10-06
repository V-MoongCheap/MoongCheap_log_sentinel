"""SQLite 상태 저장소: 체크포인트, fingerprint 이력, 시간당 발생률, AI 호출 기록."""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from .models import Group


class State:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS fingerprints (
            fp TEXT PRIMARY KEY, category TEXT, level TEXT, logger TEXT, template TEXT,
            root_exc TEXT, app_frame TEXT, first_seen INTEGER, last_seen INTEGER,
            total_count INTEGER DEFAULT 0, issue_number INTEGER, suppressed INTEGER DEFAULT 0,
            last_comment_at INTEGER);
        CREATE TABLE IF NOT EXISTS rates (fp TEXT, bucket_ms INTEGER, per_hour REAL,
            PRIMARY KEY (fp, bucket_ms));
        CREATE TABLE IF NOT EXISTS dispatches (fp TEXT, issue_number INTEGER, at_ms INTEGER);
        """)

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))

    def get_fp(self, fp: str) -> dict | None:
        cur = self.db.execute("SELECT * FROM fingerprints WHERE fp=?", (fp,))
        row = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], row)) if row else None

    def upsert_fp(self, g: Group) -> None:
        p = g.sample
        self.db.execute("""
            INSERT INTO fingerprints (fp, category, level, logger, template, root_exc, app_frame,
                                      first_seen, last_seen, total_count)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fp) DO UPDATE SET category=excluded.category, last_seen=excluded.last_seen,
                total_count=fingerprints.total_count + excluded.total_count""",
            (g.fp, g.category, p.level, p.logger, p.template, p.root_exc, p.app_frame,
             g.first_ns // 1_000_000, g.last_ns // 1_000_000, g.count))

    def update_fp(self, fp: str, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE fingerprints SET {sets} WHERE fp=?", (*fields.values(), fp))

    def baseline_per_hour(self, fp: str, before_ms: int, days: int = 7) -> tuple[float, int]:
        """최근 N일 평균 시간당 발생 수와, 기준이 된 관측 시간(h). 발생 없는 실행 구간은 0으로 간주."""
        since = before_ms - days * 86_400_000
        total = self.db.execute("SELECT COALESCE(SUM(per_hour),0) FROM rates WHERE fp=? AND bucket_ms>=? AND bucket_ms<?",
                                (fp, since, before_ms)).fetchone()[0]
        first_run = int(self.get_meta("first_run_ms") or before_ms)
        observed_h = max(0, (before_ms - max(since, first_run)) // 3_600_000)
        return (total / observed_h if observed_h else 0.0), observed_h

    def record_rate(self, fp: str, bucket_ms: int, per_hour: float) -> None:
        self.db.execute("INSERT INTO rates VALUES (?,?,?) ON CONFLICT(fp,bucket_ms) DO UPDATE SET per_hour=excluded.per_hour",
                        (fp, bucket_ms, per_hour))

    def dispatches_last_24h(self, now_ms: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM dispatches WHERE at_ms>?", (now_ms - 86_400_000,)).fetchone()[0]

    def record_dispatch(self, fp: str, issue: int, now_ms: int) -> None:
        self.db.execute("INSERT INTO dispatches VALUES (?,?,?)", (fp, issue, now_ms))

    def prune(self, now_ms: int) -> None:
        self.db.execute("DELETE FROM rates WHERE bucket_ms < ?", (now_ms - 30 * 86_400_000,))

    def commit(self) -> None:
        self.db.commit()