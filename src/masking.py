"""외부(Discord, GitHub, AI)로 보내기 전 민감정보 마스킹."""
from __future__ import annotations

import re

MASK_PATTERNS = [
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "<jwt>"),
    (re.compile(r"(?i)\bbearer\s+[\w.~+/-]+=*"), "Bearer <token>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "<phone>"),
    (re.compile(r"\b\d{3}-\d{2}-\d{5}\b"), "<biz-no>"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "<card?>"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization|refresh_token|login_?id|phone|email)\s*[=:]\s*[^,\s)\]}]+"),
     r"\1=<masked>"),
]


def mask(text: str) -> str:
    for pat, repl in MASK_PATTERNS:
        text = pat.sub(repl, text)
    return text