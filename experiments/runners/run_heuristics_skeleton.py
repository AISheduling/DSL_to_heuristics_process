"""
Прогон эвристик подхода Skeleton: две функции (select_job_fn, allocate_fn)
в каркасе scheduler_skeleton, результат проверяется независимым чекером.

    python experiments/runners/run_heuristics_skeleton.py [--scheme ssgs|legacy]

legacy воспроизводит пошаговую схему весенних результатов (d3dadbc6); функции
со старым контрактом allocate_fn -> dict работают только в ней.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner_common as rc  # noqa: E402

EXP_DIR = rc.ROOT_DIR / "experiments" / "experiment_skeleton"
OUTPUT_DIR = rc.ROOT_DIR / "results" / "skeleton"
CASE_MAP = {f"Case{c}_DSL_for_skeleton_results": c for c in rc.CASE_INSTANCES}


def run_experiment(scheme: str) -> list[dict]:
    rows: list[dict] = []
    instances = {c: rc.load_json(rc.DATA_DIR / name) for c, name in rc.CASE_INSTANCES.items()}
    dsl_paths = {c: rc.BRIEF_DSL_DIR / f"Case{c}_DSL_for_skeleton.json" for c in rc.CASE_INSTANCES}
    budgets = {c: rc.budget_limit_from_dsl(dsl_paths[c]) for c in rc.CASE_INSTANCES}

    for subdir, rfile in rc.iter_result_files(EXP_DIR):
        case = rc.case_of(rfile.stem, CASE_MAP)
        if case is None:
            print(f"  [SKIP] no case mapping for '{rfile.stem}'")
            continue
        runs = rc.load_json(rfile).get("runs", [])
        print(f"\n=== skeleton[{scheme}] | case {case} | {subdir.name}/{rfile.name}: {len(runs)} runs")
        for run in runs:
            base = {"approach": "skeleton", "case": case, "folder": subdir.name,
                    "file": rfile.stem, "run_index": run.get("run_index"),
                    "method": run.get("method", "N/A"), "scheme": scheme}
            gen_error = rc.generation_error_row(run)
            select_code = run.get("select_job_fn") or ""
            allocate_code = run.get("allocate_fn") or ""
            if gen_error is not None or not select_code or not allocate_code:
                rows.append({**base, "status": "generation_error", "primary": None,
                             "makespan": None, "violations": [],
                             "error": gen_error or "no select_job_fn / allocate_fn in run"})
                print(f"    run {base['run_index']}: generation_error")
                continue
            outcome = rc.run_skeleton(select_code, allocate_code, dsl_paths[case],
                                      instances[case], scheme=scheme, budget_limit=budgets[case])
            rows.append({**base, **outcome})
            extra = ""
            if outcome.get("invalid_select_count") or outcome.get("allocate_violations"):
                extra = (f" | invalid_select={outcome.get('invalid_select_count')}"
                         f" allocate_violations={outcome.get('allocate_violations')}")
            print(f"    run {base['run_index']}: {outcome['status']}"
                  + (f" | primary={outcome['primary']}" if outcome["status"] == "ok" else "")
                  + extra)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheme", choices=("ssgs", "legacy"), default="ssgs")
    args = parser.parse_args()
    if not EXP_DIR.exists():
        print(f"ERROR: folder not found: {EXP_DIR}")
        raise SystemExit(1)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = run_experiment(args.scheme)
    print(f"\nSummary (skeleton/{args.scheme}, shares of all generations):")
    rc.print_summary(rows)
    ts = rc.timestamp()
    rc.save_json(rows, OUTPUT_DIR / f"heuristics_schedule_results_{args.scheme}_{ts}.json")
    rc.save_excel(rows, OUTPUT_DIR / f"heuristics_schedule_results_{args.scheme}_{ts}.xlsx")
