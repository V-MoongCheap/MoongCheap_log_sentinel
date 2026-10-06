"""파이프라인 전반에서 주고받는 데이터 구조."""
from __future__ import annotations

import dataclasses
from collections import Counter

CATEGORIES = ("bug", "review", "external", "minor", "expected")


@dataclasses.dataclass
class RawLog:
    row_id: str
    ts_ns: int
    labels: dict
    line: str


@dataclasses.dataclass
class ParsedLog:
    level: str
    logger: str
    message: str
    template: str
    stack: str = ""
    stack_hash: str = ""
    category: str = ""        # 로그에 직접 붙인 category 필드(있으면 최우선)
    git_sha: str = ""
    exc_chain: list[str] = dataclasses.field(default_factory=list)
    root_exc: str = ""
    root_exc_msg: str = ""
    app_frame: str = ""


@dataclasses.dataclass
class Group:
    fp: str
    service: str
    category: str
    rule: str
    sample: ParsedLog
    count: int = 0
    first_ns: int = 0
    last_ns: int = 0
    pods: set = dataclasses.field(default_factory=set)
    messages: Counter = dataclasses.field(default_factory=Counter)
    # 실행 중 계산
    is_new: bool = False
    spike_ratio: float | None = None
    issue_number: int | None = None
    issue_url: str = ""
    notes: list[str] = dataclasses.field(default_factory=list)

    @property
    def max_repeat(self) -> int:
        return max(self.messages.values()) if self.messages else 0

    @property
    def short_logger(self) -> str:
        return self.sample.logger.rsplit(".", 1)[-1]