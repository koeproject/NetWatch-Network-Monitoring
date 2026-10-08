"""CLAUDE.md §4 as a test — the same rule as ops/check-boundary.sh, so CI
enforces it even where bash is not available. Keep the two in step."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARDED = [
    "backend/app/domain",
    "backend/app/services",
    "backend/app/api",
    "backend/app/auth",
    "frontend",
]
SKIP_DIRS = {"node_modules", "dist", ".venv", "__pycache__"}

RULES = [
    ("engine name", re.compile(r"zabbix", re.IGNORECASE)),
    ("engine id", re.compile(r"(^|[^a-z0-9])(event|host|item|trigger)ids?([^a-z0-9]|$)", re.IGNORECASE)),
    ("engine id", re.compile(r"[a-z0-9](Event|Host|Item|Trigger)Ids?([^a-z]|$)")),
    ("engine field", re.compile(r"(^|[^A-Za-z0-9])([Cc]lock|ns)([^a-z0-9]|$)")),
    ("engine field", re.compile(r"[a-z0-9](Clock|Ns)([^a-z]|$)")),
]


def _files() -> list[Path]:
    found = []
    for guarded in GUARDED:
        root = REPO / guarded
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not SKIP_DIRS & set(path.relative_to(REPO).parts):
                if path.suffix != ".pyc":
                    found.append(path)
    return found


def test_guarded_paths_exist() -> None:
    assert _files(), "nothing scanned — the guarded paths moved?"


@pytest.mark.parametrize(
    "line",
    ["device_hostid = 1", "from zabbix import x", "clock = 0", "event_clock = 1",
     "clockNs = 2", "itemids = []", "problemEventId = 3"],
)
def test_rules_catch_violations(line: str) -> None:
    assert any(rule.search(line) for _, rule in RULES), line


@pytest.mark.parametrize("line", ["device_ref = 'a'", "clockwise = 1", "dns = 2", "returns = 3"])
def test_rules_allow_clean_code(line: str) -> None:
    assert not any(rule.search(line) for _, rule in RULES), line


def test_no_engine_words_in_guarded_paths() -> None:
    hits = []
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary asset
        for number, line in enumerate(text.splitlines(), start=1):
            for label, rule in RULES:
                if rule.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{number} [{label}] {line.strip()}")
    assert not hits, "\n".join(hits)
