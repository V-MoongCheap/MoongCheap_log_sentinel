"""GitHub REST API 최소 클라이언트 (dry-run 지원)."""
from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)


class GitHub:
    API = "https://api.github.com"

    def __init__(self, token: str, repo: str, dry_run: bool):
        self.repo, self.dry_run = repo, dry_run
        self.enabled = bool(token and repo)
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        r = self.s.request(method, f"{self.API}/repos/{self.repo}{path}", timeout=30, **kw)
        if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
            raise RuntimeError("GitHub rate limit")
        r.raise_for_status()
        return r.json() if r.content else None

    def find_issue_by_label(self, label: str) -> dict | None:
        if not self.enabled:
            return None
        items = self._req("GET", "/issues", params={"labels": label, "state": "all", "per_page": 1})
        return items[0] if items else None

    def get_issue(self, number: int) -> dict | None:
        if not self.enabled or number <= 0:
            return None
        return self._req("GET", f"/issues/{number}")

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        if self.dry_run or not self.enabled:
            log.info("[dry-run] GitHub 이슈 생성: %s labels=%s", title, labels)
            return {"number": -1, "html_url": "(dry-run)"}
        return self._req("POST", "/issues", json={"title": title, "body": body, "labels": labels})

    def add_labels(self, number: int, labels: list[str]) -> None:
        if self.dry_run or not self.enabled or number <= 0:
            log.info("[dry-run] 이슈 #%s 라벨 추가: %s", number, labels)
            return
        self._req("POST", f"/issues/{number}/labels", json={"labels": labels})

    def comment(self, number: int, body: str) -> None:
        if self.dry_run or not self.enabled or number <= 0:
            log.info("[dry-run] 이슈 #%s 코멘트: %s", number, body.splitlines()[0])
            return
        self._req("POST", f"/issues/{number}/comments", json={"body": body})

    def reopen(self, number: int) -> None:
        if self.dry_run or not self.enabled or number <= 0:
            log.info("[dry-run] 이슈 #%s 재오픈", number)
            return
        self._req("PATCH", f"/issues/{number}", json={"state": "open"})