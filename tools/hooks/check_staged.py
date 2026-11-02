"""Проверка файлов перед коммитом: ключи API и файлы, которым не место в git.

Запускается из `tools/hooks/pre-commit` (подключение: `git config core.hooksPath tools/hooks`).
Без аргументов проверяет индекс git; `--all` — все отслеживаемые файлы.
Код выхода 1, если что-то найдено: коммит блокируется независимо от агента.
"""
from __future__ import annotations

import re
import subprocess
import sys
from fnmatch import fnmatch

# Пути, которые не коммитятся (AGENTS.md, «Что не попадает в git»); исключения — ALLOWED
FORBIDDEN = (
    "data/psplib/*", "data/rcplib/*",              # лицензия источников
    "experiments/v1_pilot/generations/*",          # сырые ответы LLM
    ".env", "*.env", "*/.env",
    "CLAUDE.local.md", ".claude/settings.local.json", ".claude/hooks/*",   # личное
)
ALLOWED = ("data/psplib/SOURCES.md", "data/rcplib/SOURCES.md")

# Ключ в значении; заглушки вида your_api_key, <key>, $VAR, os.environ не считаются
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\b[A-Z_]*API_KEY\s*[=:]\s*[\"']?(?!your|<|\$|%|os\.)[A-Za-z0-9_\-]{16,}"),
)


def forbidden_path(path: str) -> bool:
    return path not in ALLOWED and any(fnmatch(path, p) for p in FORBIDDEN)


def find_secrets(text: str) -> list[int]:
    """Номера строк (с 1) с похожими на ключ значениями."""
    return [i for i, line in enumerate(text.splitlines(), 1)
            if any(p.search(line) for p in SECRET_PATTERNS)]


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def check(paths: list[str], read) -> list[str]:
    problems = []
    for path in paths:
        if forbidden_path(path):
            problems.append(f"{path}: файл не должен попадать в git")
            continue
        data = read(path)
        if b"\0" in data:                          # бинарный (xlsx, pdf) — не проверяем
            continue
        for line in find_secrets(data.decode("utf-8", errors="replace")):
            problems.append(f"{path}:{line}: похоже на ключ API")
    return problems


def main(argv: list[str]) -> int:
    sys.stderr.reconfigure(encoding="utf-8")       # иначе в консоли Windows кириллица в cp1251
    if "--all" in argv:
        paths = _git("ls-files", "-z").decode().split("\0")
        read = lambda p: open(p, "rb").read()  # noqa: E731
    else:
        paths = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
        read = lambda p: _git("show", f":{p}")  # noqa: E731 — содержимое из индекса, а не с диска
    problems = check([p for p in paths if p], read)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print("Коммит заблокирован (tools/hooks/check_staged.py). Уберите файлы из индекса: "
              "git restore --staged <файл>", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
