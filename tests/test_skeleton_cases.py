"""
Тесты каркаса по пяти постановкам (перенос tests/test_scheduler.py в pytest).

  1. DSLParser — разбор DSL каждого кейса
  2. ProblemFactory — структура Jobs / Resources
  3. ProblemState — механика пошаговой схемы (legacy) и профиля (ssgs)
  4. ObjectiveCalculator — makespan, штраф E/T, бюджет NRR, многопроектная цель
  5. solve() на синтетических инстансах в обеих схемах + сверка с чекером
  6. Реальные DSL-файлы и инстансы из data/: полное расписание или явный
     статус unsupported (Cases 3–4: группы выбора ведут к тупику в обеих схемах)

Пути относительные: тесты запускаются из чистого клона.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from schedule_checker import validate_schedule
from scheduler_skeleton import (
    DSLParser,
    ObjectiveCalculator,
    ProblemFactory,
    solve,
)

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
FULL_DSL_DIR = ROOT / "data" / "references" / "full DSL description of projects"
BRIEF_DSL_DIR = ROOT / "data" / "references" / "brief DSL description of projects"

DSL = {
    1: {
        "project_id": "PSPLIB_J30_RCPSP",
        "problem_statement": {"constraint_types": ["Precedence", "Resource Capacities"],
                              "resource_nature": "Renewable"},
        "optimization_objectives": {"primary": {"metric": "Makespan", "direction": "Minimize"}},
        "graph_meta_characteristics": {"nodes": 32, "edges": 48, "cpl": 11, "max_parallelism": 11},
    },
    2: {
        "project_id": "SINGLE_MACHINE_JIT",
        "problem_statement": {
            "problem_type": "Single-Machine Common Due Date",
            "constraint_types": {"hard": ["Single Resource Capacity"], "soft": ["Common Due Date"]},
            "resource_nature": "Renewable",
        },
        "optimization_objectives": {
            "metric": "Total Earliness/Tardiness Penalty", "direction": "Minimize",
            "secondary": {"metric": "Due Date Deviation", "direction": "Minimize",
                          "parameters": {"due_date": 106}},
        },
    },
    3: {
        "project_id": "RCPSP_MULTI_RESOURCE",
        "problem_statement": {"resource_nature": "Renewable and Non-Renewable"},
        "optimization_objectives": {
            "primary": {"metric": "Makespan", "direction": "Minimize"},
            "secondary": {"metric": "Non-Renewable Resource Consumption", "direction": "Minimize",
                          "parameters": {"budget_limit": {"NRR1": 580, "NRR2": 596}}},
        },
        "conditional_scheduling": {"enabled": True, "selection_groups_present": True,
                                   "time_precedence_present": True},
    },
    4: {
        "project_id": "CONDITIONAL_RCPSP",
        "problem_statement": {"resource_nature": "Renewable"},
        "optimization_objectives": {"primary": {"metric": "Makespan", "direction": "Minimize"}},
        "conditional_scheduling": {"enabled": True, "selection_groups_present": True,
                                   "time_precedence_present": True},
    },
    5: {
        "project_id": "RCMPSP_MULTI_PROJECT",
        "problem_statement": {"resource_nature": "Renewable"},
        "optimization_objectives": {
            "primary": {"metric": "Total Makespan (All Projects)", "direction": "Minimize"}},
    },
}

INSTANCE = {
    1: {
        "resources": [{"id": 1, "name": "R1", "capacity": 3, "type": "renewable"},
                      {"id": 2, "name": "R2", "capacity": 2, "type": "renewable"}],
        "jobs": [
            {"id": 1, "duration": 0, "predecessors": [], "successors": [2, 3], "resources_required": {}},
            {"id": 2, "duration": 3, "predecessors": [1], "successors": [4],
             "resources_required": {"1": 2, "2": 1}},
            {"id": 3, "duration": 2, "predecessors": [1], "successors": [4],
             "resources_required": {"1": 1, "2": 1}},
            {"id": 4, "duration": 0, "predecessors": [2, 3], "successors": [], "resources_required": {}},
        ],
    },
    2: {
        "resources": [{"id": 1, "name": "Machine", "capacity": 1, "type": "renewable"}],
        "jobs": [
            {"id": 1, "duration": 40, "predecessors": [], "resources_required": {"1": 1},
             "penalties": {"earliness_unit_penalty": 2, "tardiness_unit_penalty": 3}},
            {"id": 2, "duration": 50, "predecessors": [], "resources_required": {"1": 1},
             "penalties": {"earliness_unit_penalty": 1, "tardiness_unit_penalty": 4}},
            {"id": 3, "duration": 30, "predecessors": [], "resources_required": {"1": 1},
             "penalties": {"earliness_unit_penalty": 3, "tardiness_unit_penalty": 2}},
        ],
    },
    3: {
        "resources": [{"id": 1, "name": "R1", "capacity": 4, "type": "renewable"},
                      {"id": 2, "name": "NRR1", "type": "nonrenewable", "initial_stock": 100}],
        "jobs": [
            {"id": 1, "duration": 0, "predecessors": [], "successors": [2, 3],
             "resources_required": {}, "resource_consumption": {}},
            {"id": 2, "duration": 3, "predecessors": [1], "successors": [4],
             "resources_required": {"1": 2},
             "resource_consumption": {"2": {"consumption": 30, "production": 0}}},
            {"id": 3, "duration": 2, "predecessors": [1], "successors": [4],
             "resources_required": {"1": 2},
             "resource_consumption": {"2": {"consumption": 20, "production": 0}}},
            {"id": 4, "duration": 0, "predecessors": [2, 3], "successors": [],
             "resources_required": {}, "resource_consumption": {}},
        ],
    },
    4: {
        "resources": [{"id": 1, "name": "R1", "capacity": 2, "type": "renewable"}],
        "jobs": [
            {"id": 1, "duration": 0, "resources_required": {},
             "precedences": {"time_successors": [2, 3], "selection_groups": [[2, 3]]}},
            {"id": 2, "duration": 4, "resources_required": {"1": 1},
             "precedences": {"time_successors": [4], "selection_groups": []}},
            {"id": 3, "duration": 3, "resources_required": {"1": 1},
             "precedences": {"time_successors": [4], "selection_groups": []}},
            {"id": 4, "duration": 0, "resources_required": {},
             "precedences": {"time_successors": [], "selection_groups": []}},
        ],
    },
    5: {
        "resources": [{"id": 1, "name": "G1", "capacity": 4, "type": "global"}],
        "jobs": [
            {"project_id": 1, "num_activities": 4, "due_date": 20, "activities": [
                {"id": 1, "duration": 0, "resources_required": [0], "successors": [2, 3]},
                {"id": 2, "duration": 3, "resources_required": [2], "successors": [4]},
                {"id": 3, "duration": 2, "resources_required": [2], "successors": [4]},
                {"id": 4, "duration": 0, "resources_required": [0], "successors": []},
            ]},
            {"project_id": 2, "num_activities": 4, "due_date": 25, "activities": [
                {"id": 1, "duration": 0, "resources_required": [0], "successors": [2, 3]},
                {"id": 2, "duration": 4, "resources_required": [2], "successors": [4]},
                {"id": 3, "duration": 2, "resources_required": [2], "successors": [4]},
                {"id": 4, "duration": 0, "resources_required": [0], "successors": []},
            ]},
        ],
    },
}

REAL = {
    1: ("Case1_PSPLIB_j301_1.json", "Case1_DSL.json"),
    2: ("Case2_sch50.json", "Case2_DSL.json"),
    3: ("Case3_nonrenewable.json", "Case3_DSL.json"),
    4: ("Case4_renewable.json", "Case4_DSL.json"),
    5: ("Case5_mp_j90_a2_nr1.json", "Case5_DSL.json"),
}
# Cases 3–4: группы выбора в данных 4TU (альтернативные подграфы) не реализованы
# ни одной схемой каркаса: после выбора ветви потомки пропущенных работ никогда
# не становятся готовыми. Так было и в d3dadbc6 — тест на покрытие "> 0" это скрывал.
UNSUPPORTED = {3, 4}


@pytest.fixture(scope="module")
def parser():
    return DSLParser()


@pytest.fixture(scope="module")
def factory():
    return ProblemFactory()


@pytest.fixture
def dsl_file(tmp_path):
    def make(case: int) -> Path:
        p = tmp_path / f"dsl{case}.json"
        p.write_text(json.dumps(DSL[case]), encoding="utf-8")
        return p
    return make


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# DSLParser

def test_parser_case1(parser):
    m = parser.parse_dict(DSL[1])
    assert m.project_id == "PSPLIB_J30_RCPSP"
    assert m.primary_metric == "Makespan"
    assert not (m.is_single_machine or m.is_multi_project or m.has_non_renewable)
    assert "Precedence" in m.constraint_types


def test_parser_case2_flat_objective_and_merged_constraints(parser):
    m = parser.parse_dict(DSL[2])
    assert m.is_single_machine
    assert "Earliness" in m.primary_metric
    assert m.secondary_params["due_date"] == 106
    assert {"Single Resource Capacity", "Common Due Date"} <= set(m.constraint_types)


def test_parser_case3_secondary_and_conditional(parser):
    m = parser.parse_dict(DSL[3])
    assert m.has_non_renewable
    assert m.secondary_metric == "Non-Renewable Resource Consumption"
    assert m.secondary_params["budget_limit"]["NRR1"] == 580
    assert m.conditional_scheduling and m.selection_groups_present


def test_parser_case4_and_5(parser):
    assert parser.parse_dict(DSL[4]).selection_groups_present
    m5 = parser.parse_dict(DSL[5])
    assert m5.is_multi_project and "Total Makespan" in m5.primary_metric


def test_parser_summary_mentions_secondary(parser):
    s = parser.summary(parser.parse_dict(DSL[3]))
    assert "RCPSP_MULTI_RESOURCE" in s and "Non-Renewable" in s


@pytest.mark.parametrize("case", [1, 2, 3, 4, 5])
def test_real_dsl_files_parse(parser, case):
    for d in (FULL_DSL_DIR / REAL[case][1], BRIEF_DSL_DIR / f"Case{case}_DSL_for_skeleton.json"):
        assert parser.parse_file(d).project_id != "UNKNOWN", d


# ProblemFactory

def test_factory_case1_structure(parser, factory):
    s = factory.build(INSTANCE[1], parser.parse_dict(DSL[1]))
    assert len(s.jobs) == 4 and len(s.resources) == 2
    assert s.jobs[2].predecessors == [1] and s.jobs[2].duration == 3
    assert s.jobs[2].resources_required == {1: 2, 2: 1}
    assert s.resources[1].capacity == 3 and s.resources[1].r_type == "renewable"


def test_factory_case2_penalties(parser, factory):
    s = factory.build(INSTANCE[2], parser.parse_dict(DSL[2]))
    assert (s.jobs[1].earliness_penalty, s.jobs[1].tardiness_penalty) == (2, 3)


def test_factory_case3_non_renewable(parser, factory):
    s = factory.build(INSTANCE[3], parser.parse_dict(DSL[3]))
    assert s.resources[2].r_type == "non-renewable"
    assert s.resources[2].initial_stock == 100
    assert s.jobs[2].non_renewable_consumption == {2: 30}
    assert s.non_renewable_stock == {2: 100}


def test_factory_case4_selection_groups_and_time_successors(parser, factory):
    s = factory.build(INSTANCE[4], parser.parse_dict(DSL[4]))
    assert s.jobs[1].selection_groups == [[2, 3]]
    assert 4 in s.jobs[2].successors
    assert s.jobs[2].predecessors == [1]  # восстановлены из time_successors


def test_factory_case5_multi_project(parser, factory):
    s = factory.build(INSTANCE[5], parser.parse_dict(DSL[5]))
    assert len(s.jobs) == 8
    j12 = next(j for j in s.jobs.values() if j.project_id == 1 and j.local_id == 2)
    j21 = next(j for j in s.jobs.values() if j.project_id == 2 and j.local_id == 1)
    assert j12.resources_required == {1: 2}
    assert j21.id in next(j for j in s.jobs.values()
                          if j.project_id == 2 and j.local_id == 2).predecessors


# ProblemState

def test_state_legacy_mechanics(parser, factory):
    s = factory.build(INSTANCE[1], parser.parse_dict(DSL[1]))
    assert s.eligible_jobs("legacy") == [1]
    s.start_job(1, {})
    s.finish_jobs_at(0)
    assert 1 in s.completed_jobs
    assert set(s.eligible_jobs("legacy")) == {2, 3}
    s.start_job(2, {1: 2, 2: 1})
    assert s.renewable_used[1] == 2 and s.available_capacity(1) == 1
    assert s.can_allocate(s.jobs[3], {1: 1, 2: 1})
    assert not s.can_allocate(s.jobs[3], {1: 3, 2: 0})
    assert not s.can_allocate(s.jobs[3], {1: 1})  # не покрывает R2
    s.start_job(3, {1: 1, 2: 1})
    s.advance_time()
    assert s.current_time == 2 and 3 in s.completed_jobs
    assert s.renewable_used[1] == 2  # job 2 ещё идёт
    assert not s.is_done()


def test_state_ssgs_feasible_starts_and_profile(parser, factory):
    s = factory.build(INSTANCE[1], parser.parse_dict(DSL[1]))
    s.place_job(1, 0)
    s.place_job(2, 0)  # R1: 2 из 3, R2: 1 из 2 на [0, 3)
    # job 3 нужны R1=1, R2=1: помещается рядом с job 2 (t=0) и после неё (t=3)
    assert s.feasible_starts(s.jobs[3]) == [0, 3]
    s.place_job(3, 0)
    assert s.usage_at(1, 0) == 3 and s.usage_at(2, 2) == 1
    assert s.feasible_starts(s.jobs[4]) == [3]
    snap = s.snapshot()
    for key in ("current_time", "eligible_jobs", "start_times", "finish_times", "capacity"):
        assert key in snap


# ObjectiveCalculator

def test_objective_makespan(parser, factory):
    s = factory.build(INSTANCE[1], parser.parse_dict(DSL[1]))
    s.schedule = {1: 0, 2: 0, 3: 0, 4: 3}
    obj = ObjectiveCalculator.compute(s)
    assert obj["makespan"] == 3 and obj["primary"] == 3


def test_objective_et_penalty(parser, factory):
    s = factory.build(INSTANCE[2], parser.parse_dict(DSL[2]))
    s.schedule = {1: 0, 2: 40, 3: 90}
    obj = ObjectiveCalculator.compute(s)
    assert obj["primary"] == (106 - 40) * 2 + (106 - 90) * 1 + (120 - 106) * 2
    assert obj["job_details"][1]["type"] == "early"
    assert obj["job_details"][3]["type"] == "late"


def test_objective_nrr_budget(parser, factory):
    s = factory.build(INSTANCE[3], parser.parse_dict(DSL[3]))
    s.schedule = {1: 0, 2: 0, 3: 0, 4: 3}
    s.non_renewable_stock[2] = 100 - 50
    obj = ObjectiveCalculator.compute(s)
    assert obj["non_renewable_used"] == {"NRR1": 50} and obj["budget_feasible"]
    s.non_renewable_stock[2] = -500
    obj = ObjectiveCalculator.compute(s)
    assert not obj["budget_feasible"] and obj["budget_violations"]["NRR1"]["used"] == 600


def test_objective_multi_project_sum(parser, factory):
    s = factory.build(INSTANCE[5], parser.parse_dict(DSL[5]))
    for j in s.jobs.values():
        s.schedule[j.id] = 0
    obj = ObjectiveCalculator.compute(s)
    assert obj["project_makespans"] == {1: 3, 2: 4}
    assert obj["primary"] == 7 and obj["portfolio_makespan"] == 4


# solve() на синтетических инстансах

@pytest.mark.parametrize("scheme", ["ssgs", "legacy"])
@pytest.mark.parametrize("case", [1, 2, 3, 5])
def test_solve_synthetic_complete_and_checker_valid(dsl_file, case, scheme):
    res = solve(dsl_file(case), INSTANCE[case], scheme=scheme)
    assert res["status"] == "complete", res["detail"]
    assert res["invalid_select_count"] == 0 and res["allocate_violations"] == 0
    rep = validate_schedule(INSTANCE[case], res["schedule"],
                            budget_limit=DSL[case]["optimization_objectives"].get(
                                "secondary", {}).get("parameters", {}).get("budget_limit"),
                            due_date=106 if case == 2 else None)
    assert rep["status"] == "valid", rep["violations"]
    assert rep["objective"]["primary"] == res["objective"]["primary"]


def test_solve_case1_custom_select(dsl_file):
    def lpt(eligible, jobs, snap, meta):
        return max(eligible, key=lambda jid: jobs[jid].duration)
    res = solve(dsl_file(1), INSTANCE[1], select_job_fn=lpt)
    assert res["status"] == "complete" and res["objective"]["primary"] == 3


def test_solve_case2_single_machine_is_sequential(dsl_file):
    res = solve(dsl_file(2), INSTANCE[2])
    starts = sorted(res["schedule"].values())
    assert starts == [0, 30, 70]  # SPT: 30, 40, 50


@pytest.mark.parametrize("scheme", ["ssgs", "legacy"])
def test_solve_case4_branch_choice_leads_to_honest_deadlock(dsl_file, scheme):
    """Группа выбора [2, 3] у работы 1: выбрана 2, работа 3 пропущена, но работа 4
    ждёт обоих предшественников и не становится готовой. Семантика альтернативных
    ветвей в каркасе не определена — статус incomplete, а не 'OK'."""
    res = solve(dsl_file(4), INSTANCE[4], scheme=scheme)
    assert res["status"] == "incomplete" and res["reason"] == "deadlock"
    assert res["skipped"] == [3] and res["unscheduled"] == [4]
    assert res["objective"]["primary"] is None


# Реальные инстансы

@pytest.mark.parametrize("scheme", ["ssgs", "legacy"])
@pytest.mark.parametrize("case", [1, 2, 5])
def test_real_instance_complete_and_checker_valid(case, scheme):
    raw = load_json(PROCESSED_DIR / REAL[case][0])
    res = solve(FULL_DSL_DIR / REAL[case][1], raw, scheme=scheme)
    assert res["status"] == "complete", res["detail"]
    rep = validate_schedule(raw, res["schedule"])
    assert rep["status"] == "valid", rep["violations"][:3]
    assert rep["objective"]["primary"] == res["objective"]["primary"]
    assert rep["scheduled"] == rep["total"]


def test_real_case1_makespan_not_below_optimum():
    raw = load_json(PROCESSED_DIR / REAL[1][0])
    res = solve(FULL_DSL_DIR / REAL[1][1], raw)
    assert res["objective"]["primary"] >= 43  # PSPLIB j301_1 optimum


@pytest.mark.parametrize("scheme", ["ssgs", "legacy"])
@pytest.mark.parametrize("case", sorted(UNSUPPORTED))
def test_real_conditional_cases_are_reported_incomplete(case, scheme):
    """Честный статус вместо частичного 'успеха': тупик фиксируется, цель не считается."""
    raw = load_json(PROCESSED_DIR / REAL[case][0])
    res = solve(FULL_DSL_DIR / REAL[case][1], raw, scheme=scheme)
    assert res["status"] == "incomplete" and res["reason"] == "deadlock"
    assert res["objective"]["primary"] is None
    assert validate_schedule(raw, res["schedule"])["status"] != "valid"
