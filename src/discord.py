"""Discord 요약 메시지 생성과 전송 (embed 개수·길이 제한 처리)."""
from __future__ import annotations

import json
import time
from collections import Counter

import requests

from .models import CATEGORIES, Group
from .utils import fmt_ts

COLORS = {"bug": 0xE24B4A, "review": 0xEF9F27, "external": 0x378ADD, "minor": 0x888780, "expected": 0x1D9E75}


CAT_KO = {"bug": "코드 오류", "review": "검토 필요", "external": "외부 연동", "minor": "사소한 오류", "expected": "정상 흐름 급증"}


CAT_SUMMARY = {**CAT_KO, "expected": "정상 흐름"}


def discord_line(g: Group) -> str:
    marks = []
    if g.is_new: marks.append("🆕신규")
    if g.spike_ratio: marks.append(f"📈평소 {g.spike_ratio:.0f}배")
    if g.max_repeat >= 10: marks.append(f"🔁동일 메시지 {g.max_repeat}회(재처리 루프 의심)")
    marks += [n for n in g.notes if n not in ("ai-fix", "ai-analyze")]
    if "ai-fix" in g.notes: marks.append("🤖AI 수정 요청")
    if "ai-analyze" in g.notes: marks.append("🤖AI 분석 요청")
    link = f" [#{g.issue_number}]({g.issue_url})" if g.issue_number and g.issue_number > 0 else ""
    tmpl = g.sample.template.replace("`", "'")[:140]
    return f"**{g.count}회** `{g.short_logger}` {tmpl}{link}" + (f"\n　{' · '.join(marks)}" if marks else "")


def send_discord(url: str, payload: dict, dry_run: bool) -> None:
    if dry_run or not url:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for _ in range(3):
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 1)))
            continue
        r.raise_for_status()
        return


def build_discord_messages(groups: list[Group], window: tuple[int, int], unparsed: int) -> list[dict]:
    shown = [g for g in groups if g.category != "expected" or g.spike_ratio]
    counts = Counter(g.category for g in groups)
    totals = Counter()
    for g in groups:
        totals[g.category] += g.count
    summary = " · ".join(f"{CAT_SUMMARY[c]} {counts[c]}종/{totals[c]}건" for c in CATEGORIES if counts[c])
    header = (f"**로그 트리아지** {fmt_ts(window[0], False)} ~ {fmt_ts(window[1], False)}\n"
              f"{summary or '이번 구간 ERROR/WARN 없음'}" + (f"\n(파싱 실패 {unparsed}줄)" if unparsed else ""))
    embeds = []
    for cat in CATEGORIES:
        items = sorted((g for g in shown if g.category == cat), key=lambda g: -g.count)
        if not items:
            continue
        desc, chunk = "", []
        for g in items[:25]:
            line = discord_line(g) + "\n"
            if len(desc) + len(line) > 3800:
                chunk.append(desc); desc = ""
            desc += line
        if len(items) > 25:
            desc += f"… 외 {len(items) - 25}종"
        chunk.append(desc)
        for i, d in enumerate(chunk):
            embeds.append({"title": CAT_KO[cat] + (f" ({i+1})" if len(chunk) > 1 else ""),
                           "description": d, "color": COLORS[cat]})
    # Discord 제한: 메시지당 embed 10개, 총 6000자
    messages, cur, size = [], [], 0
    for e in embeds:
        esize = len(e["title"]) + len(e["description"])
        if cur and (len(cur) >= 10 or size + esize > 5500):
            messages.append({"embeds": cur}); cur, size = [], 0
        cur.append(e); size += esize
    if cur:
        messages.append({"embeds": cur})
    if messages:
        messages[0]["content"] = header
    else:
        messages = [{"content": header}]
    return messages