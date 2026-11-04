from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from dsl_builder import build_dsl  # noqa: E402
from indicators import flat_indicators  # noqa: E402
from make_instances import build, instance_hash  # noqa: E402
from metrics import rpd  # noqa: E402
from priority_rules import RULES_V2  # noqa: E402
from psplib import parse_sm_file  # noqa: E402
from reference_solver import best_known, lower_bound  # noqa: E402
from schedule_checker import validate_schedule  # noqa: E402
from scheduler_skeleton import build_state, default_allocate, run_schedule  # noqa: E402

MANIFEST = HERE / "instances.json"
RESULTS_DIR = HERE / "results"
V1_SAMPLE = ROOT / "experiments" / "v1_pilot" / "sample.json"
PSPLIB_INSTANCES = ROOT / "data" / "psplib" / "instances"

INDICATORS = ["n", "cnc", "os", "sp", "ad", "la", "i5", "tf", "rf", "ru", "rs", "rc"]
INSTANCE_COLUMNS = (["id", "family", "env", "n", "n_res", "s", "control", "seed", "hash",
                     "trap_blocks", "lb", "cpm", "best", "best_source", "optimal", "chain_length"]
                    + [f"ind_{k}" for k in INDICATORS])
RULE_COLUMNS = ["id", "rule", "makespan", "rpd_best", "gap_vs_others", "chain_delay", "unavoidable_delay"]
PSPLIB_COLUMNS = ["instance", "set", "rule", "makespan", "bks", "rpd_bks", "gap_vs_others"]


def rule_schedules(inst: dict) -> dict[str, dict[int, int]]:
    """Расписание каждого правила в SSGS; недопустимое расписание — ошибка, а не пропуск."""
    dsl = build_dsl(inst, "none")
    out = {}
    for name, select in RULES_V2.items():
        _, state = build_state(dsl, inst)
        out[name] = run_schedule(state, select, default_allocate)["schedule"]
    return out


def makespans(inst: dict, schedules: dict[str, dict[int, int]]) -> dict[str, int]:
    out = {}
    for name, sched in schedules.items():
        check = validate_schedule(inst, sched)
        if check["status"] != "valid":
            raise RuntimeError(f"{inst['case_info']['id']}: {name} — {check['status']}")
        out[name] = check["makespan"]
    return out


def gaps_vs_others(ms: dict[str, int]) -> dict[str, float]:
    """Проигрыш правила лучшему из остальных, %: специфичность, эталон не нужен."""
    return {r: 100 * (v / min(x for k, x in ms.items() if k != r) - 1) for r, v in ms.items()}


def evaluate(task: tuple[dict, int]) -> tuple[dict, list[dict]]:
    p, samples = task
    inst = build(p)
    h = instance_hash(inst)
    if h != p["hash"]:
        raise RuntimeError(f"{p['id']}: хэш {h} не совпадает с манифестом {p['hash']} — генератор изменился")
    trap = inst["generator"]["trap"]
    durations = {j["id"]: j["duration"] for j in inst["jobs"]}
    chain_length = sum(durations[c] for c in trap["chain"])
    last = trap["chain"][-1]
    # Неизбежная задержка цепочки: каждая h, не помещающаяся рядом с c, сдвигает ее на p_h
    unavoidable = sum(b["p"] for b in trap["blocks"] if b["r_h"] + b["r_c"] > b["capacity"])

    schedules = rule_schedules(inst)
    ms = makespans(inst, schedules)
    gaps = gaps_vs_others(ms)
    ref = best_known(inst, samples=samples, seed=p["seed"])
    lb = lower_bound(inst)
    ind = flat_indicators(inst)
    row = {k: p[k] for k in ("id", "family", "env", "n", "n_res", "s", "control", "seed", "hash")}
    row |= {"trap_blocks": sum(b["kind"] == "trap" for b in trap["blocks"]), "lb": lb["lb"],
            "cpm": lb["cpm"], "best": ref["makespan"], "best_source": ref["source"],
            "optimal": ref["optimal"], "chain_length": chain_length}
    row |= {f"ind_{k}": ind[k] for k in INDICATORS}
    rules = [{"id": p["id"], "rule": r, "makespan": ms[r],
              "rpd_best": rpd(ms[r], ref["makespan"]), "gap_vs_others": gaps[r],
              "chain_delay": schedules[r][last] + durations[last] - chain_length,
              "unavoidable_delay": unavoidable}
             for r in RULES_V2]
    return row, rules


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def run_grid(run_dir: Path, manifest: dict, samples: int, workers: int) -> dict:
    inst_path, rules_path = run_dir / "instances.csv", run_dir / "rules.csv"
    wanted = {p["id"]: p for p in manifest["instances"]}
    # Кэш: проект считается посчитанным, если совпал хэш и есть строки всех правил
    old_inst = {r["id"]: r for r in _read(inst_path)
                if r["id"] in wanted and r["hash"] == wanted[r["id"]]["hash"]}
    old_rules: dict[str, list[dict]] = {}
    for r in _read(rules_path):
        old_rules.setdefault(r["id"], []).append(r)
    done = {i for i in old_inst if len(old_rules.get(i, [])) == len(RULES_V2)}
    todo = [(p, samples) for i, p in wanted.items() if i not in done]

    started = time.time()
    new_inst, new_rules = [], []
    if todo:
        pool = Pool(workers) if workers > 1 else None
        results = pool.imap_unordered(evaluate, todo, chunksize=4) if pool else map(evaluate, todo)
        try:
            for k, (row, rules) in enumerate(results, 1):
                new_inst.append(row)
                new_rules += rules
                if k % 100 == 0 or k == len(todo):
                    print(f"  {k}/{len(todo)} ({time.time() - started:.0f} c)", flush=True)
        finally:
            if pool:
                pool.close()
                pool.join()

    order = list(wanted)
    inst_rows = {i: old_inst[i] for i in done} | {r["id"]: r for r in new_inst}
    rule_rows = {i: old_rules[i] for i in done}
    for r in new_rules:
        rule_rows.setdefault(r["id"], []).append(r)
    _write(inst_path, INSTANCE_COLUMNS, [inst_rows[i] for i in order])
    _write(rules_path, RULE_COLUMNS, [r for i in order for r in rule_rows[i]])
    return {"instances": len(order), "computed": len(todo), "cached": len(done),
            "samples": samples, "elapsed_s": round(time.time() - started, 1),
            "manifest_created": manifest["created"]}


def run_psplib(run_dir: Path, sample_file: Path = V1_SAMPLE) -> dict:
    sample = json.loads(sample_file.read_text(encoding="utf-8"))
    rows = []
    for info in sample["instances"]:
        inst = parse_sm_file(PSPLIB_INSTANCES / info["set"] / f"{info['name']}.sm")
        ms = makespans(inst, rule_schedules(inst))
        gaps = gaps_vs_others(ms)
        bks = info["reference"]["bks"]
        rows += [{"instance": info["name"], "set": info["set"], "rule": r, "makespan": ms[r],
                  "bks": bks, "rpd_bks": rpd(ms[r], bks), "gap_vs_others": gaps[r]} for r in RULES_V2]
    _write(run_dir / "psplib_rules.csv", PSPLIB_COLUMNS, rows)
    return {"psplib_instances": len(sample["instances"])}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Прогон правил на сетке В2 и на выборке PSPLIB (описание: README.md).")
    parser.add_argument("--run", required=True)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--psplib", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    run_dir = args.results_dir / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.psplib:
        summary = run_psplib(run_dir)
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        summary = run_grid(run_dir, manifest, args.samples, args.workers)
    summary_path = run_dir / "summary.json"
    old = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary_path.write_text(json.dumps(old | summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
