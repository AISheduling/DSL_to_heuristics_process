"""Хук перед коммитом: запрещенные файлы и ключи API."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hooks"))

from check_staged import check, find_secrets, forbidden_path  # noqa: E402


@pytest.mark.parametrize("path", [
    "data/psplib/instances/j30/j301_1.sm", "data/rcplib/indicators.csv",
    "experiments/v1_pilot/generations/full-haiku-2/manifest.json",
    ".env", "src/.env", "prod.env", "CLAUDE.local.md", ".claude/settings.local.json",
    ".claude/hooks/ask_before_commit.py",
])
def test_forbidden_paths(path):
    assert forbidden_path(path)


@pytest.mark.parametrize("path", [
    "data/psplib/SOURCES.md", "data/rcplib/SOURCES.md", "data/processed/Case2_sch50.json",
    "experiments/v1_pilot/results/full-haiku-2/runs.csv", "AGENTS.md", "CLAUDE.md",
    ".claude/skills/v1-run/SKILL.md",
])
def test_allowed_paths(path):
    assert not forbidden_path(path)


def test_secrets_found():
    text = ("ok = 1\n"
            "client = OpenAI(api_key='sk-" + "a1B2" * 8 + "')\n"
            "LITELLM_API_KEY=" + "q9" * 12 + "\n")
    assert find_secrets(text) == [2, 3]


@pytest.mark.parametrize("line", [
    "set LITELLM_API_KEY=your_api_key",
    'api_key = os.environ["LITELLM_API_KEY"]',
    "LITELLM_API_KEY=$LITELLM_API_KEY",
    "export LITELLM_API_KEY=<key>",
    "# sk-short",
])
def test_placeholders_not_secrets(line):
    assert find_secrets(line) == []


def test_check_reports_and_skips_binary():
    # Ключи собираются из частей, чтобы сам этот файл проходил хук
    files = {"a.py": b"KEY_API_KEY = '" + b"ab" * 13 + b"'\n", "b.xlsx": b"PK\0sk-" + b"x" * 30,
             "CLAUDE.local.md": b"# rules"}
    problems = check(list(files), files.__getitem__)
    assert problems == ["a.py:1: похоже на ключ API", "CLAUDE.local.md: файл не должен попадать в git"]


def test_tracked_files_are_clean():
    """Текущие отслеживаемые файлы хук пропускает — иначе он мешал бы каждому коммиту."""
    import subprocess
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    paths = [p for p in paths.decode().split("\0") if p]
    assert check(paths, lambda p: (root / p).read_bytes()) == []
