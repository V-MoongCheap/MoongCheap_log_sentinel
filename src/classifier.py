"""rules.yaml 기반 분류와 fingerprint 계산."""
from __future__ import annotations

import hashlib
import re

import yaml

from .models import CATEGORIES, ParsedLog


class Classifier:
    def __init__(self, rules_path: str):
        with open(rules_path, encoding="utf-8") as f:
            self.conf = yaml.safe_load(f) or {}
        self.app_package = self.conf.get("app_package", "com.")
        self.category_field_map = self.conf.get("category_field_map", {})
        self.rules = []
        for r in self.conf.get("rules", []):
            if r["category"] not in CATEGORIES:
                raise ValueError(f"rule {r.get('name')}: unknown category {r['category']}")
            compiled = {k: re.compile(v) for k, v in (r.get("match") or {}).items()}
            self.rules.append((r.get("name", "?"), r["category"], compiled))
        self.defaults = self.conf.get("defaults", {})
        self.spike = self.conf.get("spike", {})
        self.repeat_threshold = int(self.conf.get("repeat_threshold", 10))

    @staticmethod
    def _match(m: dict[str, re.Pattern], p: ParsedLog) -> bool:
        for key, rx in m.items():
            if key == "level" and not rx.search(p.level): return False
            if key == "logger" and not rx.search(p.logger): return False
            if key == "template" and not rx.search(p.template): return False
            if key == "message" and not rx.search(p.message): return False
            if key == "exception" and not any(rx.search(e) for e in p.exc_chain): return False
            if key == "app_frame" and not rx.search(p.app_frame): return False
        return True

    def classify(self, p: ParsedLog) -> tuple[str, str]:
        if p.category and p.category in self.category_field_map:
            return self.category_field_map[p.category], f"field:{p.category}"
        for name, cat, m in self.rules:
            if self._match(m, p):
                return cat, name
        if p.level == "ERROR":
            return self.defaults.get("ERROR", "bug"), "default:error"
        if p.exc_chain and any(e.startswith(self.app_package) for e in p.exc_chain):
            return self.defaults.get("WARN_WITH_APP_EXCEPTION", "review"), "default:warn-app-exception"
        return self.defaults.get("WARN", "minor"), "default:warn"


def fingerprint(service: str, p: ParsedLog) -> str:
    if p.stack_hash:
        basis = [service, p.level, p.logger, p.template, p.stack_hash]
    else:
        basis = [service, p.level, p.logger, p.template, p.root_exc, p.app_frame]
    return hashlib.sha1("|".join(basis).encode()).hexdigest()[:12]