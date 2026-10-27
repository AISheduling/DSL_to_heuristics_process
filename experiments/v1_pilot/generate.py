from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "llm_clients"))

from dsl_builder import build_dsl  # noqa: E402
from prompt_v1 import PROMPT_VERSION, build_messages  # noqa: E402
from psplib import parse_sm_file  # noqa: E402

SAMPLE_FILE = HERE / "sample.json"
GENERATIONS_DIR = HERE / "generations"
PSPLIB_INSTANCES = ROOT / "data" / "psplib" / "instances"

LEVELS = {"a": "all", "b": "none"}          # Уровень В1 -> состав DSL
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 16000                  # Включая скрытое рассуждение модели
DEFAULT_BASE_URL = "https://api.duckduck.cloud/v1"
REQUEST_TIMEOUT = 300
ATTEMPTS = 3                                # Попытки на вызов при сетевых ошибках

# Поля конфигурации, которые должны совпадать при продолжении запуска
CONFIG_KEYS = ("model", "temperature", "max_tokens", "prompt_version", "levels", "sample_seed")


@dataclass(frozen=True)
class Task:
    instance: str
    set_name: str
    level: str
    gen: int

    @property
    def filename(self) -> str:
        return f"{self.instance}__{self.level}__g{self.gen}.json"


def load_sample(path: Path = SAMPLE_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_tasks(sample: dict, *, pilot_only: bool, levels: list[str], gens: int) -> list[Task]:
    """
    Задачи в порядке «генерация, уровень, инстанс»:
    при обрыве уровни продвинуты поровну.
    """
    rows = [i for i in sample["instances"] if i["pilot"] or not pilot_only]
    return [Task(r["name"], r["set"], level, g)
            for g in range(1, gens + 1) for level in levels for r in rows]


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def prepare_run_dir(run_dir: Path, config: dict) -> None:
    """
    Создает manifest.json или проверяет,
    что продолжаемый запуск — с теми же настройками.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = run_dir / "manifest.json"
    if manifest.exists():
        old = json.loads(manifest.read_text(encoding="utf-8"))
        diff = {k: (old["config"].get(k), config[k]) for k in CONFIG_KEYS
                if old["config"].get(k) != config[k]}
        if diff:
            raise SystemExit(f"{run_dir.name}: настройки отличаются от сохраненных {diff}; "
                             f"для других настроек нужен новый --run")
        return
    _write_json(manifest, {"created": datetime.now().isoformat(timespec="seconds"),
                           "git_commit": git_commit(), "config": config})


def pending(tasks: list[Task], run_dir: Path, retry_errors: bool) -> list[Task]:
    out = []
    for t in tasks:
        path = run_dir / t.filename
        if not path.exists():
            out.append(t)
        elif retry_errors and json.loads(path.read_text(encoding="utf-8")).get("error"):
            out.append(t)
    return out


def make_client(base_url: str | None = None):
    """Клиент OpenAI-совместимого прокси; ключ — из окружения или .env."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    key = os.environ.get("LITELLM_API_KEY")
    if not key:
        raise SystemExit("Не найден LITELLM_API_KEY: задайте переменную окружения или строку "
                         "LITELLM_API_KEY=... в файле .env в корне репозитория")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=base_url or os.environ.get("LITELLM_BASE_URL",
                                                                   DEFAULT_BASE_URL))


def call_llm(client, messages: list[dict], config: dict) -> dict:
    """Один вызов: сырой ответ, токены, разобранный JSON (или ошибка разбора)."""
    response = client.chat.completions.create(
        model=config["model"], messages=messages, temperature=config["temperature"],
        max_tokens=config["max_tokens"], n=1, timeout=REQUEST_TIMEOUT,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    usage = response.usage
    out: dict[str, Any] = {
        "raw": raw,
        "finish_reason": getattr(response.choices[0], "finish_reason", None),
        "tokens": _tokens(usage),
    }
    out.update(parse_response(raw, out["finish_reason"]))
    return out


def _tokens(usage) -> dict | None:
    if not usage:
        return None
    tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens,
              "total": usage.total_tokens}
    # Скрытое рассуждение модели входит в completion; прокси может отдать его отдельно
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None) if details else None
    if reasoning is not None:
        tokens["reasoning"] = reasoning
    return tokens


RESPONSE_KEYS = ("select_job_fn", "allocate_fn", "method", "reasoning", "description")


def parse_response(raw: str | None, finish_reason: str | None = None) -> dict:
    """
    Поля ответа LLM или {"error": ...}. Ответ может прийти в markdown-ограждении
    ```json ... ``` и с текстом вокруг (так отвечает Anthropic через прокси, несмотря на
    response_format): берется первый JSON-объект текста. Обрезанный по лимиту ответ —
    ошибка truncated, а не parse_error.
    """
    text = raw or ""
    start = text.find("{")
    try:
        if start < 0:
            raise json.JSONDecodeError("no JSON object", text, 0)
        parsed, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        kind = "truncated" if finish_reason == "length" else "parse_error"
        return {"error": f"{kind}: {e}"}
    if not isinstance(parsed, dict):
        return {"error": "parse_error: JSON is not an object"}
    out = {key: parsed.get(key) for key in RESPONSE_KEYS}
    if not out["select_job_fn"] or not out["allocate_fn"]:
        kind = "truncated" if finish_reason == "length" else "parse_error"
        out["error"] = f"{kind}: no select_job_fn / allocate_fn in response"
    return out


def run_task(task: Task, client, config: dict, run_dir: Path,
             sleep: Callable[[float], None] = time.sleep) -> dict:
    instance = parse_sm_file(PSPLIB_INSTANCES / task.set_name / f"{task.instance}.sm")
    dsl = build_dsl(instance, LEVELS[task.level])
    messages = build_messages(dsl)
    record: dict[str, Any] = {"instance": task.instance, "set": task.set_name, "level": task.level,
                              "composition": LEVELS[task.level], "gen": task.gen,
                              "model": config["model"], "temperature": config["temperature"],
                              "prompt_version": config["prompt_version"], "dsl": dsl}
    t0 = time.perf_counter()
    for attempt in range(1, ATTEMPTS + 1):
        try:
            record.update(call_llm(client, messages, config))
            record.pop("api_error", None)
            break
        except Exception as e:  # сеть, лимиты, таймаут прокси
            record["api_error"] = f"{type(e).__name__}: {e}"
            if attempt < ATTEMPTS:
                sleep(5 * attempt)
    if "api_error" in record:
        record["error"] = f"api_error: {record.pop('api_error')}"
    record["attempts"] = attempt
    record["latency_s"] = round(time.perf_counter() - t0, 2)
    record["finished"] = datetime.now().isoformat(timespec="seconds")
    _write_json(run_dir / task.filename, record)
    return record


def summarize(run_dir: Path, tasks: list[Task]) -> dict:
    done, errors, tokens = 0, {}, {"prompt": 0, "completion": 0, "reasoning": 0, "total": 0}
    for t in tasks:
        path = run_dir / t.filename
        if not path.exists():
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("error"):
            kind = rec["error"].split(":")[0]
            errors[kind] = errors.get(kind, 0) + 1
        else:
            done += 1
        for k in tokens:
            tokens[k] += (rec.get("tokens") or {}).get(k) or 0
    return {"tasks": len(tasks), "ok": done, "errors": errors,
            "missing": len(tasks) - done - sum(errors.values()), "tokens": tokens}


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None, client_factory: Callable = make_client) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="имя запуска: папка generations/<run>")
    p.add_argument("--pilot-only", action="store_true", help="только инстансы пилота (30)")
    p.add_argument("--levels", nargs="+", default=list(LEVELS), choices=list(LEVELS))
    p.add_argument("--gens", type=int, default=3, help="генераций на инстанс и уровень")
    p.add_argument("--model", required=True,
                   help="имя модели в прокси, например anthropic/claude-haiku-5-5")
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument("--workers", type=int, default=8, help="параллельных запросов")
    p.add_argument("--limit", type=int, help="сделать не больше N вызовов (проба)")
    p.add_argument("--retry-errors", action="store_true", help="перезапросить файлы с ошибкой")
    p.add_argument("--dry-run", action="store_true", help="показать план и промпт, без вызовов API")
    p.add_argument("--out", type=Path, default=GENERATIONS_DIR)
    args = p.parse_args(argv)

    sample = load_sample()
    tasks = make_tasks(sample, pilot_only=args.pilot_only, levels=args.levels, gens=args.gens)
    run_dir = args.out / args.run
    config = {"model": args.model, "temperature": args.temperature, "max_tokens": args.max_tokens,
              "prompt_version": PROMPT_VERSION, "levels": {k: LEVELS[k] for k in args.levels},
              "gens": args.gens, "pilot_only": args.pilot_only, "sample_seed": sample["seed"]}
    todo = pending(tasks, run_dir, args.retry_errors) if run_dir.exists() else list(tasks)
    if args.limit is not None:
        todo = todo[:args.limit]
    print(f"{args.run}: задач {len(tasks)}, к выполнению {len(todo)} "
          f"(модель {args.model}, temperature {args.temperature}, workers {args.workers})")

    if args.dry_run:
        if tasks:
            t = tasks[0]
            inst = parse_sm_file(PSPLIB_INSTANCES / t.set_name / f"{t.instance}.sm")
            print(f"\nПример ({t.filename}):\n{build_messages(build_dsl(inst, LEVELS[t.level]))[1]['content']}")
        return {"tasks": len(tasks), "todo": len(todo)}

    prepare_run_dir(run_dir, config)
    if todo:
        client = client_factory()
        lock = threading.Lock()
        finished = 0
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_task, t, client, config, run_dir): t for t in todo}
            for fut in as_completed(futures):
                rec = fut.result()
                with lock:
                    finished += 1
                    status = rec.get("error") or f"ok, {rec.get('method')}"
                    print(f"  [{finished}/{len(todo)}] {futures[fut].filename}: {status} "
                          f"({rec['latency_s']} s)")
        print(f"Время: {time.perf_counter() - t0:.0f} s")
    summary = summarize(run_dir, tasks)
    _write_json(run_dir / "summary.json", {"updated": datetime.now().isoformat(timespec="seconds"),
                                           **summary})
    print(f"Итог: {summary}")
    return summary


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
