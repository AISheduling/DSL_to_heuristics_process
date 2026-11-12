from __future__ import annotations

import argparse
import hashlib
import json
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
sys.path.insert(0, str(ROOT / "experiments" / "v1_pilot"))
sys.path.insert(0, str(HERE))

import generate as v1  # noqa: E402  (вызов LLM, кэш прокси, манифест и итог — как в В1)
import router  # noqa: E402
from make_instances import FAMILY, build, instance_hash, instance_id  # noqa: E402
from prompt_v1 import PROMPT_VERSION, build_messages  # noqa: E402

SAMPLE_FILE = HERE / "llm_sample.json"
GENERATIONS_DIR = HERE / "generations"

LEVELS = {"b": "none", "v": "verdict", "g": "property"}
ROUTED = ("v", "g")
# Выборка ADR 0004, п. 4 и 10; seed не пересекаются с f1-grid (0–19)
PARTS = {"pilot": {"seeds": (90, 91), "sizes": (30,)},
         "main": {"seeds": (20, 21, 22, 23, 24), "sizes": (30, 60)}}
ENVS = ("isolated", "shared")
STRENGTHS = (0.0, 0.5, 1.0)
N_RES = 4
CONTROL = "fits"


@dataclass(frozen=True)
class Task:
    project: str
    level: str
    gen: int

    @property
    def filename(self) -> str:
        return f"{self.project}__{self.level}__g{self.gen}.json"


def sample_rows() -> list[dict]:
    rows = []
    for part, spec in PARTS.items():
        for env in ENVS:
            for n in spec["sizes"]:
                for s in STRENGTHS:
                    for seed in spec["seeds"]:
                        p = {"family": FAMILY, "env": env, "n": n, "n_res": N_RES, "s": s,
                             "control": CONTROL, "seed": seed}
                        rows.append({"id": instance_id(p), "part": part, **p})
    return rows


def make_sample() -> dict:
    trigger = router.load_trigger()
    instances = []
    for row in sample_rows():
        inst = build(row)
        d = router.decide(inst, trigger)
        instances.append({**row, "hash": instance_hash(inst), "value": d["value"],
                          "fired": d["fired"]})
    return {"created": datetime.now().isoformat(timespec="seconds"), "family": FAMILY,
            "trigger": trigger, "size": len(instances), "instances": instances}


def load_or_make_sample(path: Path = SAMPLE_FILE) -> dict:
    """
    Выборка с решениями маршрутизатора. Если файл есть — сверяет проекты и решения с
    генератором и порогом: расхождение значит, что изменился генератор или признак.
    """
    fresh = make_sample()
    if not path.exists():
        path.write_text(json.dumps(fresh, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return fresh
    saved = json.loads(path.read_text(encoding="utf-8"))
    key = lambda r: (r["id"], r["hash"], r["fired"])  # noqa: E731
    if [key(r) for r in saved["instances"]] != [key(r) for r in fresh["instances"]] \
            or saved["trigger"] != fresh["trigger"]:
        raise SystemExit(f"{path.name}: проекты или решения маршрутизатора не совпадают с "
                         f"генератором и порогом; выборка В2-LLM меняется только через ADR 0004")
    return saved


def sample_id(sample: dict) -> str:
    text = json.dumps([(r["id"], r["hash"], r["fired"]) for r in sample["instances"]])
    return "llm_sample:" + hashlib.sha1(text.encode()).hexdigest()[:12]


def make_tasks(rows: list[dict], gens: int, routed_only: bool = False) -> list[Task]:
    """Все задачи или (routed_only) только те, где нужен вызов LLM."""
    return [Task(r["id"], level, g) for g in range(1, gens + 1) for level in LEVELS for r in rows
            if not routed_only or level == "b" or r["fired"]]


def call_llm(client, messages: list[dict], config: dict) -> dict:
    """
    Вызов как в В1 (v1.call_llm), плюс лимит скрытого рассуждения, если он задан в запуске:
    Qwen без лимита тратил все max_tokens на рассуждение.
    """
    if not config.get("reasoning_max_tokens"):
        return v1.call_llm(client, messages, config)
    response = client.chat.completions.create(
        model=config["model"], messages=messages, temperature=config["temperature"],
        max_tokens=config["max_tokens"], n=1, timeout=v1.REQUEST_TIMEOUT,
        response_format={"type": "json_object"},
        extra_body={"cache": v1.PROXY_CACHE,
                    "reasoning": {"max_tokens": config["reasoning_max_tokens"]}},
    )
    raw = response.choices[0].message.content
    out: dict[str, Any] = {"raw": raw,
                           "finish_reason": getattr(response.choices[0], "finish_reason", None),
                           "tokens": v1._tokens(response.usage)}
    out.update(v1.parse_response(raw, out["finish_reason"]))
    return out


def run_task(task: Task, row: dict, client, config: dict, run_dir: Path,
             sleep: Callable[[float], None] | None = None) -> dict:
    sleep = sleep or time.sleep
    inst = build(row)
    decision = router.decide(inst, config["trigger"])
    if decision["fired"] != row["fired"]:
        raise RuntimeError(f"{row['id']}: решение маршрутизатора расходится с выборкой")
    dsl = router.route_dsl(inst, task.level, decision)
    record: dict[str, Any] = {"project": row["id"], "level": task.level, "gen": task.gen,
                              "composition": LEVELS[task.level], "router": decision,
                              "router_version": config["router_version"],
                              "reasoning_max_tokens": config.get("reasoning_max_tokens"),
                              "model": config["model"], "temperature": config["temperature"],
                              "prompt_version": config["prompt_version"], "dsl": dsl}
    t0 = time.perf_counter()
    for attempt in range(1, v1.ATTEMPTS + 1):
        try:
            record.update(call_llm(client, build_messages(dsl), config))
            record.pop("api_error", None)
            break
        except Exception as e:  # сеть, лимиты, таймаут прокси
            record["api_error"] = f"{type(e).__name__}: {e}"
            if attempt < v1.ATTEMPTS:
                sleep(v1.RETRY_PAUSE_S * attempt)
    if "api_error" in record:
        record["error"] = f"api_error: {record.pop('api_error')}"
    record["attempts"] = attempt
    record["latency_s"] = round(time.perf_counter() - t0, 2)
    record["finished"] = datetime.now().isoformat(timespec="seconds")
    v1._write_json(run_dir / task.filename, record)
    return record


def copy_unrouted(rows: list[dict], gens: int, run_dir: Path) -> int:
    """
    На проектах без срабатывания v и g — копии b этого проекта и генерации. Копия
    перезаписывается каждый раз: после --retry-errors b мог смениться с ошибки на ответ.
    """
    copied = 0
    for r in rows:
        if r["fired"]:
            continue
        for g in range(1, gens + 1):
            src = run_dir / Task(r["id"], "b", g).filename
            if not src.exists():
                continue
            rec = json.loads(src.read_text(encoding="utf-8"))
            for level in ROUTED:
                dst = run_dir / Task(r["id"], level, g).filename
                if dst.exists() and "copied_from" not in json.loads(dst.read_text(encoding="utf-8")):
                    continue  # собственный ответ уровня не затирается
                rec.update({"level": level, "composition": LEVELS[level], "copied_from": "b"})
                v1._write_json(dst, rec)
                copied += 1
    return copied


def main(argv: list[str] | None = None, client_factory: Callable = v1.make_client) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="имя запуска: папка generations/<run>")
    p.add_argument("--part", required=True, choices=list(PARTS))
    p.add_argument("--gens", type=int, required=True, help="генераций на проект и уровень")
    p.add_argument("--model", required=True)
    p.add_argument("--temperature", type=float, default=v1.DEFAULT_TEMPERATURE)
    p.add_argument("--max-tokens", type=int, default=v1.DEFAULT_MAX_TOKENS)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--reasoning-max-tokens", type=int,
                   help="лимит скрытого рассуждения модели (reasoning.max_tokens OpenRouter); "
                        "по умолчанию не передается")
    p.add_argument("--limit", type=int, help="сделать не больше N вызовов (проба)")
    p.add_argument("--retry-errors", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="план и примеры промптов, без вызовов API")
    p.add_argument("--sample", type=Path, default=SAMPLE_FILE)
    p.add_argument("--out", type=Path, default=GENERATIONS_DIR)
    args = p.parse_args(argv)

    sample = load_or_make_sample(args.sample)
    rows = [r for r in sample["instances"] if r["part"] == args.part]
    by_id = {r["id"]: r for r in rows}
    tasks = make_tasks(rows, args.gens)
    calls = make_tasks(rows, args.gens, routed_only=True)
    run_dir = args.out / args.run
    config = {"model": args.model, "temperature": args.temperature, "max_tokens": args.max_tokens,
              "prompt_version": PROMPT_VERSION, "levels": LEVELS, "gens": args.gens,
              "part": args.part, "sample_seed": sample_id(sample), "trigger": sample["trigger"],
              "router_version": router.ROUTER_VERSION, "reasoning_max_tokens": args.reasoning_max_tokens,
              "proxy_cache": v1.PROXY_CACHE}
    todo = v1.pending(calls, run_dir, args.retry_errors) if run_dir.exists() else list(calls)
    if args.limit is not None:
        todo = todo[:args.limit]
    fired = sum(r["fired"] for r in rows)
    print(f"{args.run}: проектов {len(rows)}, сработал маршрутизатор {fired}; задач {len(tasks)}, "
          f"вызовов LLM {len(calls)}, к выполнению {len(todo)} (модель {args.model})")

    if args.dry_run:
        example = next((r for r in rows if r["fired"]), rows[0])
        inst = build(example)
        d = router.decide(inst, sample["trigger"])
        for level in LEVELS:
            msg = build_messages(router.route_dsl(inst, level, d))[1]["content"]
            print(f"\n--- {example['id']}, уровень {level}:\n{msg}")
        return {"tasks": len(tasks), "calls": len(calls), "copies": len(tasks) - len(calls),
                "todo": len(todo)}

    v1.prepare_run_dir(run_dir, config)
    saved = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["config"]
    for key in ("router_version", "reasoning_max_tokens"):
        # Тексты блоков или настройка модели изменились — генерации не смешиваются
        if saved.get(key) != config[key]:
            raise SystemExit(f"{args.run}: {key} {saved.get(key)} -> {config[key]}; "
                             f"для других настроек нужен новый --run")
    if todo:
        client = client_factory()
        lock = threading.Lock()
        finished = 0
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_task, t, by_id[t.project], client, config, run_dir): t
                       for t in todo}
            for fut in as_completed(futures):
                rec = fut.result()
                with lock:
                    finished += 1
                    status = rec.get("error") or f"ok, {rec.get('method')}"
                    print(f"  [{finished}/{len(todo)}] {futures[fut].filename}: {status} "
                          f"({rec['latency_s']} s)")
        print(f"Время: {time.perf_counter() - t0:.0f} s")
    print(f"Копий b для несработавших проектов: {copy_unrouted(rows, args.gens, run_dir)}")
    summary = v1.summarize(run_dir, tasks)
    v1._write_json(run_dir / "summary.json", {"updated": datetime.now().isoformat(timespec="seconds"),
                                              "router_fired": fired, **summary})
    print(f"Итог: {summary}")
    if summary["fast_replies"] or summary["repeated_replies"]:
        print(f"ВНИМАНИЕ: быстрых ответов {summary['fast_replies']}, повторяющихся "
              f"{summary['repeated_replies']}; проверить кэш прокси (ADR 0003, п. 7)")
    return summary


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
