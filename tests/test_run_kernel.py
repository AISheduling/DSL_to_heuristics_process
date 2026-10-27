"""
Правила приоритета (src/priority_rules.py), общее пространство имен для двух
функций LLM (runner_common.compile_pair) и прогон генераций в каркасе
(experiments/v1_pilot/run_kernel.py) на подготовленных файлах без вызовов LLM.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from dsl_builder import build_dsl
from priority_rules import RULES, latest_times
from psplib import parse_sm_text
from schedule_checker import validate_schedule
from scheduler_skeleton import build_state, default_allocate, run_schedule

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "runners"))
sys.path.insert(0, str(ROOT / "experiments" / "v1_pilot"))

import run_kernel  # noqa: E402
import runner_common as rc  # noqa: E402

SELECT_WITH_SHARED_STATE = """
_LAST = {}

def select_job_fn(eligible_ids, jobs, snapshot, meta):
    _LAST["job"] = min(eligible_ids)
    return _LAST["job"]
"""
ALLOCATE_USING_SHARED_STATE = """
def allocate_fn(job, feasible_starts, snapshot, meta):
    assert _LAST["job"] == job.id
    return feasible_starts[0]
"""


@pytest.fixture(scope="module")
def j301_1() -> dict:
    return parse_sm_text((ROOT / "data" / "raw" / "1_j301_1.txt").read_text(encoding="utf-8"),
                         "j301_1", "PSPLIB J30 Set")


# Правила приоритета

def test_latest_times_on_j301_1(j301_1):
    _, state = build_state(build_dsl(j301_1, "none"), j301_1)
    t = latest_times(state.jobs)
    sink = max(state.jobs)
    assert t["lf"][sink] == 38                         # Длина критического пути (MPM-Time)
    assert t["total_successors"][1] == len(state.jobs) - 1
    for j, job in state.jobs.items():
        assert t["ls"][j] == t["lf"][j] - job.duration
        for s in job.successors:
            assert t["lf"][j] <= t["ls"][s]


@pytest.mark.parametrize("rule", list(RULES))
def test_rules_give_valid_schedules(j301_1, rule):
    _, state = build_state(build_dsl(j301_1, "none"), j301_1)
    res = run_schedule(state, RULES[rule], default_allocate)
    assert res["status"] == "complete" and res["invalid_select_count"] == 0
    assert validate_schedule(j301_1, res["schedule"])["status"] == "valid"
    assert res["objective"]["primary"] >= 43                # Оптимум j301_1


# Общее пространство имен

def test_shared_namespace_lets_allocate_see_select_globals(j301_1):
    dsl = build_dsl(j301_1, "all")
    separate = rc.run_skeleton(SELECT_WITH_SHARED_STATE, ALLOCATE_USING_SHARED_STATE, dsl, j301_1,
                               timeout=20)
    assert separate["status"] == "runtime_error" and "_LAST" in separate["error"]
    shared = rc.run_skeleton(SELECT_WITH_SHARED_STATE, ALLOCATE_USING_SHARED_STATE, dsl, j301_1,
                             timeout=20, shared_namespace=True)
    assert shared["status"] == "ok"


# Прогон генераций

def _write_generation(run_dir: Path, name: str, set_name: str, level: str, gen: int, **fields):
    rec = {"instance": name, "set": set_name, "level": level, "gen": gen, "method": "test",
           "dsl": fields.pop("dsl"), **fields}
    (run_dir / f"{name}__{level}__g{gen}.json").write_text(json.dumps(rec, ensure_ascii=False),
                                                           encoding="utf-8")


@pytest.mark.skipif(not run_kernel.PSPLIB_INSTANCES.exists(),
                    reason="PSPLIB не скачан (data/psplib/SOURCES.md)")
def test_run_kernel_on_prepared_generations(tmp_path):
    sample = json.loads(run_kernel.SAMPLE_FILE.read_text(encoding="utf-8"))
    info = sample["instances"][0]
    from psplib import parse_sm_file
    inst = parse_sm_file(run_kernel.PSPLIB_INSTANCES / info["set"] / f"{info['name']}.sm")
    run_dir = tmp_path / "gens" / "t"
    run_dir.mkdir(parents=True)
    _write_generation(run_dir, info["name"], info["set"], "a", 1, dsl=build_dsl(inst, "all"),
                      select_job_fn=SELECT_WITH_SHARED_STATE, allocate_fn=ALLOCATE_USING_SHARED_STATE)
    _write_generation(run_dir, info["name"], info["set"], "b", 1, dsl=build_dsl(inst, "none"),
                      select_job_fn="def select_job_fn(e, j, s, m):\n    raise KeyError('boom')\n",
                      allocate_fn="def allocate_fn(j, f, s, m):\n    return f[0]\n")
    _write_generation(run_dir, info["name"], info["set"], "b", 2, dsl=build_dsl(inst, "none"),
                      error="truncated: Unterminated string")

    summary = run_kernel.main(["--run", "t", "--generations", str(tmp_path / "gens"),
                               "--out", str(tmp_path / "res")])
    rows = {(r["level"], r["gen"]): r for r in
            csv.DictReader(open(tmp_path / "res" / "t" / "runs.csv", encoding="utf-8"))}
    ok = rows[("a", "1")]
    assert ok["status"] == "ok" and int(ok["makespan"]) >= info["reference"]["bks"]
    assert float(ok["rpd_bks"]) >= 0 and float(ok["rpd_cpm"]) >= float(ok["rpd_bks"])
    assert rows[("b", "1")]["status"] == "runtime_error" and "boom" in rows[("b", "1")]["error"]
    assert rows[("b", "2")]["status"] == "generation_error"
    assert rows[("b", "2")]["generation_error"] == "truncated"

    assert summary["levels"]["a"]["valid"] == 1
    assert summary["levels"]["b"]["valid"] == 0 and summary["levels"]["b"]["runs"] == 2
    baselines = list(csv.DictReader(open(tmp_path / "res" / "t" / "baselines.csv", encoding="utf-8")))
    assert {b["rule"] for b in baselines} == {"builtin", "LFT", "LST", "MTS"}
    assert all(b["status"] == "ok" and float(b["rpd_bks"]) >= 0 for b in baselines)
