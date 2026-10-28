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
    assert {b["rule"] for b in baselines} == {"builtin", "LFT", "LST", "MTS", "GP1"}
    assert all(b["status"] == "ok" and float(b["rpd_bks"]) >= 0 for b in baselines)


# GP1 (luo2022, ур. 3) и PSGS для сверки со статьей

def test_gp1_values_by_hand():
    from types import SimpleNamespace as Job
    import math
    from priority_rules import gp1, gp1_values
    # 1 -> 2 -> 3, у 2 спрос 4, у 3 спрос 2; длительности 0, 3, 2
    jobs = {1: Job(duration=0, predecessors=[], successors=[2], resources_required={}),
            2: Job(duration=3, predecessors=[1], successors=[3], resources_required={1: 4}),
            3: Job(duration=2, predecessors=[2], successors=[], resources_required={1: 2})}
    v = gp1_values(jobs)
    # терминалы, нормированные делением на максимум по проекту
    lf = {1: 0 / 5, 2: 3 / 5, 3: 5 / 5}
    ls = {1: 0 / 3, 2: 0 / 3, 3: 3 / 3}
    mts = {1: 2 / 2, 2: 1 / 2, 3: 0 / 2}
    gres = {1: 0 / 4, 2: 4 / 4, 3: 2 / 4}
    gcrwc = {1: 12 / 12, 2: 4 / 12, 3: 0 / 12}   # d_j · Σr_j по прямым преемникам
    for j in jobs:
        expected = (lf[j] + ((lf[j] + (ls[j] - gres[j])) - mts[j])) / (gcrwc[j] + math.cos(ls[j])) - gres[j]
        assert v[j] == pytest.approx(expected), j
    assert gp1([2, 3], jobs, None, None) == min((2, 3), key=lambda j: v[j])


PSPLIB_J30 = ROOT / "data" / "psplib" / "instances" / "j30"


@pytest.mark.skipif(not PSPLIB_J30.exists(), reason="PSPLIB не скачан (data/psplib/SOURCES.md)")
def test_psgs_reproduces_luo2022_table14_for_lft_lst():
    # Лучшее из SSGS и PSGS на J30, отклонение от нижней границы: LFT 3,32 %, LST 3,42 %
    # в табл. 14 luo2022 (их тест — J30 без 96 обучающих инстансов, у нас — весь J30)
    from priority_rules import latest_times, lft, lst
    from psgs import parallel_schedule
    from references import load_references
    from metrics import rpd
    from psplib import iter_set
    refs = load_references("j30", use_rcplib=False)
    devs = {"LFT": [], "LST": []}
    for name, inst in iter_set(PSPLIB_J30):
        for rule, select, key in (("LFT", lft, "lf"), ("LST", lst, "ls")):
            _, state = build_state(build_dsl(inst, "none"), inst)
            serial = run_schedule(state, select, default_allocate)["objective"]["primary"]
            _, state = build_state(build_dsl(inst, "none"), inst)
            pr = latest_times(state.jobs)[key]
            starts = parallel_schedule(state.jobs, {k: r.capacity for k, r in state.resources.items()},
                                       lambda j, pr=pr: (pr[j], j))
            check = validate_schedule(inst, starts)
            assert check["status"] == "valid", name
            devs[rule].append(rpd(min(serial, check["makespan"]), refs[name].lb))
    assert sum(devs["LFT"]) / 480 == pytest.approx(3.32, abs=0.15)
    assert sum(devs["LST"]) / 480 == pytest.approx(3.42, abs=0.15)
