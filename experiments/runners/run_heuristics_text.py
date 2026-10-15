"""Прогон эвристик подхода Text (полный решатель solve_scheduling) через чекер."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_full_solver  # noqa: E402
import runner_common as rc  # noqa: E402

EXP_DIR = rc.ROOT_DIR / "experiments" / "experiment text"
OUTPUT_DIR = rc.ROOT_DIR / "results" / "text"
CASE_MAP = {f"Case{c}_text_results": c for c in rc.CASE_INSTANCES}

if __name__ == "__main__":
    run_full_solver.main("text", EXP_DIR, OUTPUT_DIR, CASE_MAP)
