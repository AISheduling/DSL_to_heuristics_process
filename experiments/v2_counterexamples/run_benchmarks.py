from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from fit_triggers import DELTA_LABEL, metrics  # noqa: E402
from indicators import compute_indicators  # noqa: E402
from metrics import rpd  # noqa: E402
from rcplib import RCPLIB_INSTANCES, RCPLIB_RELEASE_FILE, RCPLIB_SETS  # noqa: E402
from rcplib import iter_rcplib_set, load_rcplib_references, parse_rcp_file  # noqa: E402
from dslib import DSLIB_INSTANCES  # noqa: E402
from rcplib import _natural_key  # noqa: E402
from rule_features import rule_features  # noqa: E402
from run_rules import gaps_vs_others, makespans, rule_schedules  # noqa: E402
from stats import spearman  # noqa: E402

TRIGGERS = HERE / "results" / "f1-grid" / "triggers.json"
# Наборы без эталонов: каталог готовых .rcp (DSLIB — src/dslib.py)
EXTRA_SETS: dict[str, Path] = {"DSLIB": DSLIB_INSTANCES}
RESULTS_DIR = HERE / "results"
TARGET_RULES = ("LST", "MTS")
FEATURE_KEYS = ("f1_pairs", "f1_pairs_critical", "f1_pressure", "f1_pressure_free")
INSTANCE_COLUMNS = (["set", "id", "n", "n_res", *FEATURE_KEYS]
                    + [f"{k}_{r}" for k in ("fired", "gap", "lost") for r in TARGET_RULES]
                    + ["best_rule_makespan", "cpm", "bks", "optimal"])
RULE_COLUMNS = ["set", "id", "rule", "makespan", "rpd_bks", "gap_vs_others"]


def fires(value: float, trigger: dict) -> bool:
    t = trigger["threshold"]
    return value > t if trigger["direction"] == ">" else value < t


def lost(gap: float) -> bool:
    return gap >= DELTA_LABEL


def evaluate_instance(set_name: str, inst_id: str, path: Path, ref, triggers: dict) -> tuple[dict, list[dict]]:
    """Строка инстанса и строки правил; ref — references.Reference или None."""
    inst = parse_rcp_file(path, inst_id)
    ind = compute_indicators(inst)
    feats = rule_features(inst)
    ms = makespans(inst, rule_schedules(inst))
    gaps = gaps_vs_others(ms)
    bks = ref.bks if ref else None
    row = {"set": set_name, "id": inst_id, "n": ind["network"]["n"], "n_res": len(inst["resources"]),
           **{k: feats[k] for k in FEATURE_KEYS},
           **{f"fired_{r}": fires(feats[triggers[r]["feature"]], triggers[r]) for r in TARGET_RULES},
           **{f"gap_{r}": gaps[r] for r in TARGET_RULES},
           **{f"lost_{r}": lost(gaps[r]) for r in TARGET_RULES},
           "best_rule_makespan": min(ms.values()), "cpm": ind["extended"]["cpm_length"],
           "bks": bks, "optimal": ref.optimal if ref else None}
    rules = [{"set": set_name, "id": inst_id, "rule": r, "makespan": m,
              "rpd_bks": rpd(m, bks) if bks else None, "gap_vs_others": gaps[r]} for r, m in ms.items()]
    return row, rules


def _job(args: tuple) -> tuple[dict, list[dict]]:
    return evaluate_instance(*args)


def build_report(instances: list[dict]) -> dict:
    """
    {'sets': {набор | 'ALL': {правило: метрики + spearman}}};
    порядок наборов — как во входе.
    """
    groups: dict[str, list[dict]] = {}
    for r in instances:
        groups.setdefault(r["set"], []).append(r)
    groups["ALL"] = instances
    out = {}
    for name, rows in groups.items():
        out[name] = {}
        for rule in TARGET_RULES:
            m = metrics([r[f"fired_{rule}"] for r in rows], [r[f"lost_{rule}"] for r in rows])
            m["spearman"] = spearman([r["f1_pressure_free"] for r in rows], [r[f"gap_{rule}"] for r in rows])
            m["no_resources"] = sum(1 for r in rows if r["n_res"] == 0)
            out[name][rule] = m
    return {"sets": out}


def _f(v, fmt="{:.2f}") -> str:
    return "—" if v is None else fmt.format(v)


def to_markdown(report: dict, triggers: dict) -> str:
    lines = ["# Перенос триггера F1 на RCPLIB (ADR 0005)", "",
             f"Метка: правило проиграло, если его makespan хуже лучшего из остальных правил "
             f"на {DELTA_LABEL} п. п. и больше. Порог — из `results/f1-grid/triggers.json`, без подбора.", ""]
    for rule in TARGET_RULES:
        t = triggers[rule]
        lines += [f"## {rule}", "", f"Триггер: `{t['feature']}` {t['direction']} {t['threshold']}", "",
                  "| набор | n | сработал | проиграл | precision | recall | specificity | BA | ρ | без ресурсов |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for name, by_rule in report["sets"].items():
            m = by_rule[rule]
            lines.append(f"| {name} | {m['n']} | {m['fired']} | {m['positives']} | {_f(m['precision'])} | "
                         f"{_f(m['recall'])} | {_f(m['specificity'])} | {_f(m['balanced_accuracy'])} | "
                         f"{_f(m['spearman']['rho'])} | {m['no_resources']} |")
        lines.append("")
    return "\n".join(lines)


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Перенос триггера F1 на наборы RCPLIB (ADR 0005).")
    parser.add_argument("--run", required=True)
    parser.add_argument("--sets", nargs="+", default=list(RCPLIB_SETS))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--root", type=Path, default=RCPLIB_INSTANCES)
    parser.add_argument("--workbook", type=Path, default=RCPLIB_RELEASE_FILE)
    parser.add_argument("--triggers", type=Path, default=TRIGGERS)
    parser.add_argument("--no-references", action="store_true", help="без BKS (для тестов)")
    parser.add_argument("--extra-root", type=Path, default=None, help="каталог .rcp для набора из EXTRA_SETS (для тестов)")
    args = parser.parse_args(argv)

    started = time.time()
    triggers = json.loads(args.triggers.read_text(encoding="utf-8"))
    jobs = []
    for set_name in args.sets:
        if set_name in EXTRA_SETS:
            files = sorted((args.extra_root or EXTRA_SETS[set_name]).glob("*.rcp"), key=lambda p: _natural_key(p.stem))
            jobs += [(set_name, p.stem, p, None, triggers) for p in files]
            continue
        refs = {} if args.no_references else load_rcplib_references(set_name, path=args.workbook, root=args.root)
        jobs += [(set_name, inst_id, path, refs.get(inst_id), triggers)
                 for inst_id, path in iter_rcplib_set(set_name, args.root)]
    if args.workers > 1:
        with Pool(args.workers) as pool:
            results = pool.map(_job, jobs, chunksize=8)
    else:
        results = [_job(j) for j in jobs]

    instances = [row for row, _ in results]
    run_dir = args.results_dir / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    _write(run_dir / "bench_instances.csv", INSTANCE_COLUMNS, instances)
    _write(run_dir / "bench_rules.csv", RULE_COLUMNS, [r for _, rules in results for r in rules])
    report = build_report(instances)
    (run_dir / "bench_triggers.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "bench_triggers.md").write_text(to_markdown(report, triggers), encoding="utf-8")

    def rel(p: Path) -> str:
        try:
            return p.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return p.as_posix()

    paths = {(s, i): p for s, i, p, _, _ in jobs}
    candidates = [{"set": r["set"], "id": r["id"], "path": rel(paths[(r["set"], r["id"])]),
                   "n": r["n"], "n_res": r["n_res"], "f1_pressure_free": r["f1_pressure_free"],
                   **{k: r[k] for k in ("gap_LST", "gap_MTS", "lost_LST", "lost_MTS", "bks", "optimal")}}
                  for r in instances if r["fired_LST"]]
    (run_dir / "candidates.json").write_text(json.dumps(
        {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "triggers_file": rel(args.triggers), "threshold": triggers["LST"]["threshold"],
         "instances": candidates}, ensure_ascii=False, indent=1), encoding="utf-8")

    summary = {"instances": {s: sum(1 for r in instances if r["set"] == s) for s in args.sets},
               "fired_LST": {s: sum(1 for r in instances if r["set"] == s and r["fired_LST"]) for s in args.sets},
               "elapsed_s": round(time.time() - started, 1)}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
