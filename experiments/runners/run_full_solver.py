"""
Прогон полного решателя (подходы Text и DSL) через единый слой раннеров.

Используется из run_heuristics_text.py и run_heuristics_dsl.py:
    python experiments/runners/run_heuristics_text.py
    python experiments/runners/run_heuristics_dsl.py

Все генерации попадают в знаменатель (generation_error — тоже строка),
таймаут общий, качество только из schedule_checker.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner_common as rc  # noqa: E402


def run_experiment(approach: str, exp_dir: Path, case_map: dict[str, int]) -> list[dict]:
    rows: list[dict] = []
    instances = {c: rc.load_json(rc.DATA_DIR / name) for c, name in rc.CASE_INSTANCES.items()}
    budgets = {c: rc.budget_limit_from_dsl(rc.FULL_DSL_DIR / f"Case{c}_DSL.json")
               for c in rc.CASE_INSTANCES}

    for subdir, rfile in rc.iter_result_files(exp_dir):
        case = rc.case_of(rfile.stem, case_map)
        if case is None:
            print(f"  [SKIP] no case mapping for '{rfile.stem}'")
            continue
        runs = rc.load_json(rfile).get("runs", [])
        print(f"\n=== {approach} | case {case} | {subdir.name}/{rfile.name}: {len(runs)} runs")
        for run in runs:
            base = {"approach": approach, "case": case, "folder": subdir.name, "file": rfile.stem,
                    "run_index": run.get("run_index"), "method": run.get("method", "N/A")}
            gen_error = rc.generation_error_row(run)
            code = run.get("code")
            if gen_error is not None or not code:
                rows.append({**base, "status": "generation_error", "primary": None,
                             "makespan": None, "violations": [],
                             "error": gen_error or "no code in run"})
                print(f"    run {base['run_index']}: generation_error")
                continue
            outcome = rc.run_full_solver(code, instances[case], budget_limit=budgets[case])
            rows.append({**base, **outcome})
            print(f"    run {base['run_index']}: {outcome['status']}"
                  + (f" | primary={outcome['primary']}" if outcome["status"] == "ok" else "")
                  + (f" | {outcome['violations']}" if outcome.get("violations") else ""))
    return rows


def main(approach: str, exp_dir: Path, output_dir: Path, case_map: dict[str, int]):
    if not exp_dir.exists():
        print(f"ERROR: folder not found: {exp_dir}")
        raise SystemExit(1)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = run_experiment(approach, exp_dir, case_map)
    print(f"\nSummary ({approach}, shares of all generations):")
    rc.print_summary(rows)
    ts = rc.timestamp()
    rc.save_json(rows, output_dir / f"schedule_results_{ts}.json")
    rc.save_excel(rows, output_dir / f"schedule_results_{ts}.xlsx")
