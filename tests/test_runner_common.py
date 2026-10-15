"""
Тесты общего слоя раннеров (experiments/runners/runner_common.py):
единые статусы, извлечение расписания из вывода полного решателя,
оценка через чекер, доли от всех генераций.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "runners"))

import runner_common as rc  # noqa: E402


def diamond() -> dict:
    return {
        "resources": [{"id": 1, "name": "R1", "capacity": 3, "type": "renewable"}],
        "jobs": [
            {"id": 1, "duration": 0, "predecessors": [], "successors": [2, 3],
             "resources_required": {}},
            {"id": 2, "duration": 3, "predecessors": [1], "successors": [4],
             "resources_required": {"1": 2}},
            {"id": 3, "duration": 2, "predecessors": [1], "successors": [4],
             "resources_required": {"1": 2}},
            {"id": 4, "duration": 0, "predecessors": [2, 3], "successors": [],
             "resources_required": {}},
        ],
    }


def test_status_list_is_shared_and_fixed():
    assert rc.STATUSES == ("generation_error", "compile_error", "runtime_error", "timeout",
                           "no_schedule", "infeasible", "incomplete", "ok")


@pytest.mark.parametrize("result", [
    {"schedule": {"1": 0, "2": 0, "3": 3, "4": 5}},
    {"schedule": {1: [0, 0], 2: [0, 3], 3: [3, 5], 4: [5, 5]}},
    {"schedule": {1: {"start": 0}, 2: {"start": 0, "end": 3}, 3: {"start_time": 3}, 4: {"start": 5}}},
    {"schedule": [{"id": 1, "start": 0}, {"job_id": 2, "start": 0}, {"id": 3, "start_time": 3},
                  {"job": 4, "start": 5}]},
    {1: 0, 2: 0, 3: 3, 4: 5},
    {"makespan": 5, "start_times": {1: 0, 2: 0, 3: 3, 4: 5}},
])
def test_extract_schedule_normalizes_known_shapes(result):
    assert rc.extract_schedule(result) == {1: 0, 2: 0, 3: 3, 4: 5}


@pytest.mark.parametrize("result", [None, 5, {"makespan": 5}, [], {"schedule": "abc"}, "x"])
def test_extract_schedule_returns_none_for_unknown_shapes(result):
    assert rc.extract_schedule(result) is None


def test_evaluate_uses_checker_and_maps_statuses():
    ok = rc.evaluate(diamond(), {1: 0, 2: 0, 3: 3, 4: 5})
    assert ok["status"] == "ok"
    assert ok["primary"] == 5 and ok["makespan"] == 5
    inc = rc.evaluate(diamond(), {1: 0, 2: 0})
    assert inc["status"] == "incomplete" and inc["primary"] is None
    bad = rc.evaluate(diamond(), {1: 0, 2: 0, 3: 0, 4: 3})
    assert bad["status"] == "infeasible" and bad["primary"] is None
    assert "renewable_capacity" in bad["violations"]


def test_summarize_counts_shares_from_all_generations():
    rows = [
        {"case": "c1", "status": "ok", "primary": 10},
        {"case": "c1", "status": "ok", "primary": 12},
        {"case": "c1", "status": "generation_error", "primary": None},
        {"case": "c1", "status": "infeasible", "primary": None},
        {"case": "c2", "status": "timeout", "primary": None},
    ]
    s = rc.summarize(rows)
    assert s["c1"]["total"] == 4
    assert s["c1"]["counts"]["ok"] == 2
    assert s["c1"]["counts"]["generation_error"] == 1
    assert s["c1"]["share_ok"] == 0.5
    assert s["c1"]["primary"] == {"min": 10, "max": 12, "mean": 11.0}
    assert s["c2"]["share_ok"] == 0.0
    assert s["c2"]["primary"] is None


def test_run_with_timeout_returns_timeout_status():
    code = "def solve_scheduling(jobs, resources):\n    while True:\n        pass\n"
    outcome = rc.run_full_solver(code, diamond(), timeout=1)
    assert outcome["status"] == "timeout"


def test_run_full_solver_pipeline_ok_and_errors():
    good = ("def solve_scheduling(jobs, resources):\n"
            "    return {'schedule': {1: 0, 2: 0, 3: 3, 4: 5}}\n")
    out = rc.run_full_solver(good, diamond(), timeout=10)
    assert out["status"] == "ok" and out["primary"] == 5
    out = rc.run_full_solver("def nothing(): pass", diamond(), timeout=10)
    assert out["status"] == "compile_error"
    out = rc.run_full_solver("def solve_scheduling(jobs, resources):\n    return 1/0\n",
                             diamond(), timeout=10)
    assert out["status"] == "runtime_error"
    out = rc.run_full_solver("def solve_scheduling(jobs, resources):\n    return 42\n",
                             diamond(), timeout=10)
    assert out["status"] == "no_schedule"


def test_run_skeleton_pipeline_validates_with_checker(tmp_path):
    dsl = tmp_path / "dsl.json"
    dsl.write_text('{"project_id": "PSPLIB_J30_RCPSP", "optimization_objectives": '
                   '{"primary": {"metric": "Makespan", "direction": "Minimize"}}}',
                   encoding="utf-8")
    select = "def select_job_fn(eligible_ids, jobs, snapshot, meta):\n    return min(eligible_ids)\n"
    allocate = "def allocate_fn(job, feasible_starts, snapshot, meta):\n    return feasible_starts[0]\n"
    out = rc.run_skeleton(select, allocate, dsl, diamond(), timeout=10)
    assert out["status"] == "ok" and out["primary"] == 5
    assert out["allocate_violations"] == 0 and out["invalid_select_count"] == 0
    bad_select = "def select_job_fn(eligible_ids, jobs, snapshot, meta):\n    return 999\n"
    out = rc.run_skeleton(bad_select, allocate, dsl, diamond(), timeout=10)
    assert out["status"] == "ok" and out["invalid_select_count"] == 4
    out = rc.run_skeleton("x = 1", allocate, dsl, diamond(), timeout=10)
    assert out["status"] == "compile_error"


def test_extract_schedule_accepts_top_level_project_activity_keys():
    assert rc.extract_schedule({"1:1": 0, "2:1": 3}) == {"1:1": 0, "2:1": 3}
    assert rc.extract_schedule({"makespan": 5}) is None


def test_worker_that_dies_is_runtime_error_not_timeout():
    code = "def solve_scheduling(jobs, resources):\n    import os\n    os._exit(3)\n"
    t0 = __import__("time").perf_counter()
    out = rc.run_full_solver(code, diamond(), timeout=20)
    assert out["status"] == "runtime_error"
    assert __import__("time").perf_counter() - t0 < 10
