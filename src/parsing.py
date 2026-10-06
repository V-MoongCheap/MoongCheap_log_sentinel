"""로그 한 줄 파싱: Spring 기본 텍스트 형식과 logstash JSON 형식 지원, stack trace 분석, 메시지 템플릿화."""
from __future__ import annotations

import json
import re

from .models import ParsedLog, RawLog

SPRING_TEXT_RE = re.compile(
    r"^(?P<ts>\S+)\s+(?P<level>TRACE|DEBUG|INFO|WARN|ERROR)\s+\d+\s+---\s+"
    r"(?:\[(?P<app>[^\]]*)\]\s+)?\[\s*(?P<thread>[^\]]*)\]\s+(?P<logger>\S+)\s*:\s?(?P<msg>.*)$",
    re.S,
)


EXC_LINE_RE = re.compile(
    r"^(?:Caused by:\s*|Wrapped by:\s*)?([a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)+(?:Exception|Error|Throwable|Failure)[\w$]*)(?::\s?(.*))?$"
)


FRAME_RE = re.compile(r"^\s*at\s+([\w$.]+)\.([\w$<>]+)\(")


def normalize_template(msg: str) -> str:
    """파라미터 값을 {} 로 치환해 템플릿화 (raw_message 필드가 없을 때 사용)."""
    s = (msg or "").strip().splitlines()[0] if msg else ""
    s = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "{}", s)
    s = re.sub(r"(\w)=(\"[^\"]*\"|'[^']*'|[^,\s)\]}]+)", r"\1={}", s)
    s = re.sub(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{16,}\b", "{}", s)
    s = re.sub(r"\d+", "{}", s)
    return s[:300]


def analyze_stack(stack: str, app_package: str) -> tuple[list[str], str, str, str]:
    """예외 체인, 근본 원인, 근본 원인 메시지, 우리 코드의 첫 프레임(라인 번호 제외)을 추출."""
    chain: list[tuple[str, str]] = []
    app_frame = ""
    root_first = "Wrapped by:" in stack
    for line in stack.splitlines():
        m = EXC_LINE_RE.match(line.strip())
        if m:
            chain.append((m.group(1), (m.group(2) or "").strip()))
            continue
        if not app_frame:
            f = FRAME_RE.match(line)
            if f and f.group(1).startswith(app_package):
                app_frame = f"{f.group(1)}.{f.group(2)}"
    if not chain:
        return [], "", "", app_frame
    root = chain[0] if root_first else chain[-1]
    return [c for c, _ in chain], root[0], root[1][:300], app_frame


def parse_line(raw: RawLog, app_package: str) -> ParsedLog | None:
    line = raw.line.rstrip("\n")
    stripped = line.lstrip()
    if stripped.startswith("{"):
        try:
            j = json.loads(stripped)
        except json.JSONDecodeError:
            j = None
        if isinstance(j, dict):
            msg = str(j.get("message", ""))
            p = ParsedLog(
                level=str(j.get("level", "")).upper(),
                logger=str(j.get("logger_name") or j.get("logger") or ""),
                message=msg,
                template=(j.get("raw_message") and normalize_template(j["raw_message"])) or normalize_template(msg),
                stack=str(j.get("stack_trace", "")),
                stack_hash=str(j.get("stack_hash", "")),
                category=str(j.get("category", "")),
                git_sha=str(j.get("git_sha", "")),
            )
            if p.stack:
                p.exc_chain, p.root_exc, p.root_exc_msg, p.app_frame = analyze_stack(p.stack, app_package)
            return p

    m = SPRING_TEXT_RE.match(line)
    if not m:
        return None
    body = m.group("msg")
    first, _, rest = body.partition("\n")
    p = ParsedLog(level=m.group("level"), logger=m.group("logger"), message=first,
                  template=normalize_template(first), stack=rest)
    if rest:
        p.exc_chain, p.root_exc, p.root_exc_msg, p.app_frame = analyze_stack(rest, app_package)
    return p