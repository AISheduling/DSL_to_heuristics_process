"""
Тесты независимого чекера расписаний (schedule_checker.validate_schedule).

Чекер не импортирует каркас; здесь он проверяется на намеренно сломанных
расписаниях (каждое нарушение — своя причина) и на корректных.
"""
from __future__ import annotations

import json
from pathlib import Path


import schedule_checker
from schedule_checker import validate_schedule

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"


def load(name: str) -> dict:
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


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


VALID = {1: 0, 2: 0, 3: 3, 4: 5}


def violation_types(report: dict) -> set[str]:
    return {v["type"] for v in report["violations"]}


def test_checker_does_not_import_skeleton():
    src = (ROOT / "src" / "schedule_checker.py").read_text(encoding="utf-8")
    imports = [ln for ln in src.splitlines() if ln.lstrip().startswith(("import ", "from "))]
    assert not any("scheduler_skeleton" in ln for ln in imports), imports
    assert not any("scheduler_skeleton" in str(getattr(v, "__module__", ""))
                   for v in vars(schedule_checker).values())


def test_valid_schedule_passes_and_makespan_is_recomputed():
    rep = validate_schedule(diamond(), VALID)
    assert rep["status"] == "valid"
    assert rep["feasible"] is True
    assert rep["violations"] == []
    assert rep["makespan"] == 5
    assert rep["objective"]["primary"] == 5
    assert (rep["scheduled"], rep["total"]) == (4, 4)


def test_missing_job_is_incomplete():
    sched = dict(VALID)
    del sched[3]
    rep = validate_schedule(diamond(), sched)
    assert rep["status"] == "incomplete"
    assert "missing_job" in violation_types(rep)
    assert rep["makespan"] is None


def test_unknown_job_in_schedule_is_a_violation():
    rep = validate_schedule(diamond(), {**VALID, 42: 0})
    assert rep["status"] == "invalid"
    assert "unknown_job" in violation_types(rep)


def test_precedence_violation_is_detected():
    rep = validate_schedule(diamond(), {1: 0, 2: 0, 3: 3, 4: 2})  # 4 раньше конца 3
    assert rep["status"] == "invalid"
    assert "precedence" in violation_types(rep)


def test_renewable_capacity_violation_is_detected_per_time_unit():
    rep = validate_schedule(diamond(), {1: 0, 2: 0, 3: 1, 4: 3})  # в t=1..2 нужно 4 > 3
    assert rep["status"] == "invalid"
    v = [x for x in rep["violations"] if x["type"] == "renewable_capacity"]
    assert v and v[0]["resource"] == 1 and v[0]["time"] == 1


def test_negative_or_non_integer_start_is_a_violation():
    rep = validate_schedule(diamond(), {**VALID, 2: -1})
    assert "invalid_start" in violation_types(rep)
    rep = validate_schedule(diamond(), {**VALID, 2: "0"})
    assert "invalid_start" in violation_types(rep)


def test_nonrenewable_budget_violation_is_detected():
    inst = {
        "resources": [{"id": 1, "name": "R1", "capacity": 2, "type": "renewable"},
                      {"id": 2, "name": "NRR1", "initial_stock": 10, "type": "nonrenewable"}],
        "jobs": [{"id": 1, "duration": 1, "predecessors": [], "successors": [],
                  "resources_required": {"1": 1},
                  "resource_consumption": {"2": {"consumption": 12, "production": 0}}}],
    }
    rep = validate_schedule(inst, {1: 0})
    assert rep["status"] == "invalid"
    v = [x for x in rep["violations"] if x["type"] == "non_renewable_budget"]
    assert v and v[0]["used"] == 12 and v[0]["limit"] == 10


def test_single_machine_penalty_is_recomputed_from_instance():
    inst = {
        "parameters": {"common_due_date": 10},
        "resources": [{"id": 1, "name": "Machine", "capacity": 1, "type": "renewable"}],
        "jobs": [
            {"id": 1, "duration": 4, "predecessors": [], "resources_required": {"1": 1},
             "penalties": {"earliness_unit_penalty": 2, "tardiness_unit_penalty": 3}},
            {"id": 2, "duration": 4, "predecessors": [], "resources_required": {"1": 1},
             "penalties": {"earliness_unit_penalty": 1, "tardiness_unit_penalty": 5}},
        ],
    }
    rep = validate_schedule(inst, {1: 0, 2: 4}, objective="penalty")
    assert rep["status"] == "valid"
    # job1 заканчивается в 4: early 6 * 2 = 12; job2 в 8: early 2 * 1 = 2
    assert rep["objective"]["primary"] == 14
    assert rep["objective"]["due_date"] == 10


def test_multi_project_objective_is_sum_of_project_makespans():
    acts = [
        {"id": 1, "duration": 0, "resources_required": [0], "successors": [2]},
        {"id": 2, "duration": 3, "resources_required": [1], "successors": []},
    ]
    inst = {
        "resources": [{"id": 1, "name": "G1", "capacity": 2, "type": "global"}],
        "jobs": [{"project_id": 1, "activities": acts},
                 {"project_id": 2, "activities": json.loads(json.dumps(acts))}],
    }
    rep = validate_schedule(inst, {(1, 1): 0, (1, 2): 0, (2, 1): 0, (2, 2): 1})
    assert rep["status"] == "valid"
    assert rep["objective"]["project_makespans"] == {1: 3, 2: 4}
    assert rep["objective"]["primary"] == 7
    assert rep["objective"]["portfolio_makespan"] == 4


def test_multi_project_keys_may_be_global_ids_or_strings():
    acts = [{"id": 1, "duration": 1, "resources_required": [1], "successors": []}]
    inst = {
        "resources": [{"id": 1, "name": "G1", "capacity": 2, "type": "global"}],
        "jobs": [{"project_id": 1, "activities": acts},
                 {"project_id": 2, "activities": json.loads(json.dumps(acts))}],
    }
    assert validate_schedule(inst, {11: 0, 21: 0})["status"] == "valid"
    assert validate_schedule(inst, {"1:1": 0, "2:1": 0})["status"] == "valid"
    rep = validate_schedule(inst, {1: 0})  # неоднозначный ключ
    assert rep["status"] in ("invalid", "incomplete")


def test_selection_group_alternatives_are_not_counted_as_missing():
    inst = {
        "resources": [{"id": 1, "name": "R1", "capacity": 2, "type": "renewable"}],
        "jobs": [
            {"id": 1, "duration": 0, "resources_required": {},
             "precedences": {"time_successors": [2, 3], "selection_groups": [[2, 3]]}},
            {"id": 2, "duration": 2, "resources_required": {"1": 1},
             "precedences": {"time_successors": [4], "selection_groups": []}},
            {"id": 3, "duration": 1, "resources_required": {"1": 1},
             "precedences": {"time_successors": [4], "selection_groups": []}},
            {"id": 4, "duration": 0, "resources_required": {},
             "precedences": {"time_successors": [], "selection_groups": []}},
        ],
    }
    rep = validate_schedule(inst, {1: 0, 2: 0, 4: 2})
    assert rep["status"] == "valid", rep["violations"]
    assert rep["skipped"] == [3]
    both = validate_schedule(inst, {1: 0, 2: 0, 3: 0, 4: 2})
    assert "selection_group" in violation_types(both)


def test_nonrenewable_stock_is_checked_chronologically():
    """Расход раньше производства: итог 7 <= 10, но в t=0 запас уходит в минус."""
    inst = {
        "resources": [{"id": 1, "name": "R1", "capacity": 2, "type": "renewable"},
                      {"id": 2, "name": "NRR1", "initial_stock": 10, "type": "nonrenewable"}],
        "jobs": [
            {"id": 1, "duration": 1, "predecessors": [], "resources_required": {"1": 1},
             "resource_consumption": {"2": {"consumption": 12, "production": 0}}},
            {"id": 2, "duration": 1, "predecessors": [], "resources_required": {"1": 1},
             "resource_consumption": {"2": {"consumption": 0, "production": 5}}},
        ],
    }
    early_consume = validate_schedule(inst, {1: 0, 2: 5})
    assert early_consume["status"] == "invalid"
    v = [x for x in early_consume["violations"] if x["type"] == "non_renewable_budget"]
    assert v and v[0]["time"] == 0 and v[0]["used"] == 12
    produce_first = validate_schedule(inst, {2: 0, 1: 5})
    assert produce_first["status"] == "valid"
    assert produce_first["objective"]["non_renewable_used"] == {"NRR1": 7}
