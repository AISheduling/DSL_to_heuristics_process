"""
Негативные и контрактные тесты ядра (issue #1, этап 1).

Каждый тест закрепляет один дефект ядра или одно правило контракта:
  - формат resource_requirements в Case 1 читается, ресурсы ограничивают расписание;
  - написание типа ресурса nonrenewable / non-renewable нормализуется, бюджет считается;
  - allocate_fn не может обойти потребность работы в ресурсах;
  - освобождается ровно то, что было выделено;
  - тупик и неверное выделение дают статус incomplete, а не частичный "успех";
  - id работ разных проектов (Case 5) не сталкиваются;
  - цель многопроектной задачи — сумма makespan проектов;
  - неизвестный тип ресурса и ссылка на неизвестный ресурс — диагностируемая ошибка;
  - Case 2: директивный срок согласован с сырыми данными.

Проверки допустимости здесь независимы от каркаса: они пересчитываются по
исходному инстансу, а не по полям ProblemState.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scheduler_skeleton import (
    DSLParser,
    ObjectiveCalculator,
    ProblemFactory,
    SchedulerContractError,
    run_schedule,
    solve,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
DSL_DIR = ROOT / "data" / "references" / "full DSL description of projects"
BRIEF_DSL_DIR = ROOT / "data" / "references" / "brief DSL description of projects"

CASES = {
    1: ("Case1_PSPLIB_j301_1.json", "Case1_DSL.json"),
    2: ("Case2_sch50.json", "Case2_DSL.json"),
    3: ("Case3_nonrenewable.json", "Case3_DSL.json"),
    4: ("Case4_renewable.json", "Case4_DSL.json"),
    5: ("Case5_mp_j90_a2_nr1.json", "Case5_DSL.json"),
}


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def instance(case: int) -> dict:
    return load(DATA / CASES[case][0])


def dsl_path(case: int) -> Path:
    return DSL_DIR / CASES[case][1]


# --- независимые проверки по исходному инстансу ------------------------------

def requirements_of(raw_job: dict) -> dict[int, int]:
    """Потребность работы в ресурсах по сырому JSON (оба формата)."""
    rr = raw_job.get("resources_required", raw_job.get("resource_requirements", {}))
    if isinstance(rr, dict):
        return {int(k): int(v) for k, v in rr.items()}
    if isinstance(rr, list):
        if rr and isinstance(rr[0], dict):
            return {int(x["resource_id"]): int(x["amount"]) for x in rr}
        return {i + 1: int(v) for i, v in enumerate(rr) if v}
    return {}


def assert_renewable_feasible(schedule: dict, jobs: dict, raw_resources: list[dict]):
    """Независимо считает загрузку возобновляемых ресурсов в каждый такт."""
    caps = {int(r["id"]): int(r["capacity"]) for r in raw_resources
            if r.get("type", "renewable") in ("renewable", "global")}
    horizon = max((s + jobs[j]["duration"] for j, s in schedule.items()), default=0)
    for t in range(horizon):
        used: dict[int, int] = {}
        for jid, start in schedule.items():
            job = jobs[jid]
            if start <= t < start + job["duration"]:
                for rid, amt in job["req"].items():
                    used[rid] = used.get(rid, 0) + amt
        for rid, u in used.items():
            assert u <= caps[rid], f"t={t}: resource {rid} used {u} > capacity {caps[rid]}"


def assert_precedence_feasible(schedule: dict, jobs: dict):
    for jid, start in schedule.items():
        for p in jobs[jid]["preds"]:
            assert p in schedule, f"job {jid} scheduled, predecessor {p} is not"
            assert schedule[p] + jobs[p]["duration"] <= start, \
                f"job {jid} starts at {start} before predecessor {p} finishes"


def flat_jobs_case1(raw: dict) -> dict:
    return {j["id"]: {"duration": j["duration"], "preds": list(j.get("predecessors", [])),
                      "req": requirements_of(j)} for j in raw["jobs"]}


# --- синтетические инстансы ---------------------------------------------------

def dsl_tmp(tmp_path: Path, raw: dict) -> Path:
    p = tmp_path / "dsl.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


DSL_BASE = {
    "project_id": "PSPLIB_J30_RCPSP",
    "problem_statement": {"resource_nature": "Renewable"},
    "optimization_objectives": {"primary": {"metric": "Makespan", "direction": "Minimize"}},
}

DSL_NRR = {
    "project_id": "RCPSP_MULTI_RESOURCE",
    "problem_statement": {"resource_nature": "Renewable and Non-Renewable"},
    "optimization_objectives": {
        "primary": {"metric": "Makespan", "direction": "Minimize"},
        "secondary": {"metric": "Non-Renewable Resource Consumption", "direction": "Minimize",
                      "parameters": {"budget_limit": {"NRR1": 10}}},
    },
}

DSL_MP = {
    "project_id": "RCMPSP_MULTI_PROJECT",
    "problem_statement": {"resource_nature": "Renewable"},
    "optimization_objectives": {
        "primary": {"metric": "Total Makespan (All Projects)", "direction": "Minimize"}},
}


def diamond() -> dict:
    """1 -> {2, 3} -> 4; R1 capacity 3; job2 needs 2, job3 needs 2 (не параллельно)."""
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


def two_projects_same_ids() -> dict:
    """Оба проекта используют id 1..4 — как в Case5_mp_j90_a2_nr1.json."""
    acts = [
        {"id": 1, "duration": 0, "resources_required": [0], "successors": [2, 3]},
        {"id": 2, "duration": 3, "resources_required": [2], "successors": [4]},
        {"id": 3, "duration": 2, "resources_required": [2], "successors": [4]},
        {"id": 4, "duration": 0, "resources_required": [0], "successors": []},
    ]
    return {
        "resources": [{"id": 1, "name": "G1", "capacity": 4, "type": "global"}],
        "jobs": [
            {"project_id": 1, "num_activities": 4, "due_date": 0, "activities": acts},
            {"project_id": 2, "num_activities": 4, "due_date": 0,
             "activities": json.loads(json.dumps(acts))},
        ],
    }


def nrr_instance() -> dict:
    return {
        "resources": [{"id": 1, "name": "R1", "capacity": 2, "type": "renewable"},
                      {"id": 2, "name": "NRR1", "initial_stock": 10, "type": "nonrenewable"}],
        "jobs": [{"id": 1, "duration": 1, "predecessors": [], "successors": [],
                  "resources_required": {"1": 1},
                  "resource_consumption": {"2": {"consumption": 12, "production": 0}}}],
    }


def select_first(eligible, jobs, snap, meta):
    return eligible[0]


# =============================================================================
# 1. Case 1: формат resource_requirements и ресурсные ограничения
# =============================================================================

def test_case1_list_format_of_resource_requirements_is_parsed():
    raw = instance(1)
    meta = DSLParser().parse_file(dsl_path(1))
    state = ProblemFactory().build(raw, meta)
    assert state.jobs[2].resources_required == {1: 4}


def test_case1_default_schedule_respects_capacities_and_precedence():
    raw = instance(1)
    res = solve(dsl_path(1), raw)
    jobs = flat_jobs_case1(raw)
    assert res["status"] == "complete"
    assert set(res["schedule"]) == set(jobs)
    assert_precedence_feasible(res["schedule"], jobs)
    assert_renewable_feasible(res["schedule"], jobs, raw["resources"])
    # j301_1: optimum 43; без ресурсных ограничений получилось бы 38 (CPL)
    assert res["objective"]["primary"] >= 43


# =============================================================================
# 2. Невозобновляемые ресурсы: написание типа и бюджет
# =============================================================================

def test_nonrenewable_spelling_is_normalized_on_real_case3():
    meta = DSLParser().parse_file(dsl_path(3))
    state = ProblemFactory().build(instance(3), meta)
    assert state.resources[6].r_type == "non-renewable"
    assert state.resources[7].r_type == "non-renewable"
    assert state.non_renewable_stock == {6: 580, 7: 596}


def test_budget_violation_is_reported_with_nonrenewable_spelling():
    meta = DSLParser().parse_dict(DSL_NRR)
    state = ProblemFactory().build(nrr_instance(), meta)
    state.schedule = {1: 0}
    state.completed_jobs = {1}
    state.non_renewable_stock[2] = 10 - 12
    obj = ObjectiveCalculator().compute(state)
    assert obj["non_renewable_used"] == {"NRR1": 12}
    assert obj["budget_feasible"] is False
    assert obj["budget_violations"]["NRR1"]["excess"] == 2


def test_job_exceeding_nonrenewable_stock_cannot_start():
    meta = DSLParser().parse_dict(DSL_NRR)
    state = ProblemFactory().build(nrr_instance(), meta)
    assert state.can_allocate(state.jobs[1], {1: 1}) is False
    res = run_schedule(state, select_first)
    assert res["status"] == "incomplete"
    assert res["reason"] == "infeasible"
    assert res["unscheduled"] == [1]
    assert res["objective"]["primary"] is None


# =============================================================================
# 3. Контракт allocate_fn: ресурсы бронирует каркас, функция выбирает время старта
# =============================================================================

def test_legacy_allocation_below_requirement_is_corrected_and_counted(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), diamond(), scheme="legacy",
                allocate_fn=lambda job, r, s, m: {})
    s = res["schedule"]
    assert res["status"] == "complete"
    # считается каждый вызов allocate_fn: работа 2, работа 3 (заблокирована,
    # повтор после ожидания) — 3; для работ 1 и 4 без потребности {} допустим
    assert res["allocate_violations"] == 3
    assert s[2] + 3 <= s[3] or s[3] + 2 <= s[2]  # мощности не превышены


def test_legacy_allocation_to_unknown_resource_is_counted(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), diamond(), scheme="legacy",
                allocate_fn=lambda job, r, s, m: {**job.resources_required, 99: 1})
    assert res["status"] == "complete"
    assert res["allocate_violations"] == 5  # каждый вызов, включая повтор после ожидания


def test_legacy_strict_raises_on_allocation_violation(tmp_path):
    with pytest.raises(SchedulerContractError):
        solve(dsl_tmp(tmp_path, DSL_BASE), diamond(), scheme="legacy", strict=True,
              allocate_fn=lambda job, r, s, m: {})


def test_released_capacity_equals_what_was_allocated():
    meta = DSLParser().parse_dict(DSL_BASE)
    state = ProblemFactory().build(diamond(), meta)
    state.start_job(1, {})
    state.finish_jobs_at(0)
    state.start_job(2, {1: 3})  # больше, чем требуется (2), но в пределах мощности
    assert state.available_capacity(1) == 0
    state.advance_time()
    assert state.renewable_used[1] == 0


def test_jobs_needing_the_same_capacity_do_not_overlap(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), diamond())
    s = res["schedule"]
    assert res["status"] == "complete"
    assert s[2] + 3 <= s[3] or s[3] + 2 <= s[2]
    assert res["objective"]["primary"] == 5


def test_ssgs_allocate_receives_feasible_starts_and_choice_is_honoured(tmp_path):
    seen = []

    def allocate(job, feasible_starts, snap, meta):
        seen.append((job.id, list(feasible_starts)))
        return feasible_starts[-1]

    res = solve(dsl_tmp(tmp_path, DSL_BASE), diamond(), allocate_fn=allocate)
    assert res["status"] == "complete"
    assert res["allocate_violations"] == 0
    assert all(starts and starts == sorted(starts) for _, starts in seen)
    for jid, starts in seen:
        assert res["schedule"][jid] == starts[-1]


def test_ssgs_invalid_start_is_counted_and_earliest_used(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), diamond(),
                allocate_fn=lambda job, starts, s, m: -7)
    assert res["status"] == "complete"
    assert res["allocate_violations"] == 4
    assert res["objective"]["primary"] == 5


def test_ssgs_strict_raises_on_invalid_start(tmp_path):
    with pytest.raises(SchedulerContractError):
        solve(dsl_tmp(tmp_path, DSL_BASE), diamond(), strict=True,
              allocate_fn=lambda job, starts, s, m: {})


def test_invalid_select_is_counted_not_hidden(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), diamond(),
                select_job_fn=lambda e, j, s, m: 999)
    assert res["status"] == "complete"
    assert res["invalid_select_count"] == 4
    with pytest.raises(SchedulerContractError):
        solve(dsl_tmp(tmp_path, DSL_BASE), diamond(), strict=True,
              select_job_fn=lambda e, j, s, m: 999)


def gap_instance() -> dict:
    """R1 capacity 2. Порядок выбора A(2), B(3), C(4): A[0,1) берёт 1,
    B(req 2) не помещается до t=1, C(req 1, d=1) помещается в t=0 рядом с A —
    SSGS вставляет C раньше B, пошаговая схема ставит C после B."""
    return {
        "resources": [{"id": 1, "name": "R1", "capacity": 2, "type": "renewable"}],
        "jobs": [
            {"id": 1, "duration": 0, "predecessors": [], "successors": [2, 3, 4],
             "resources_required": {}},
            {"id": 2, "duration": 1, "predecessors": [1], "successors": [5],
             "resources_required": {"1": 1}},
            {"id": 3, "duration": 2, "predecessors": [1], "successors": [5],
             "resources_required": {"1": 2}},
            {"id": 4, "duration": 1, "predecessors": [1], "successors": [5],
             "resources_required": {"1": 1}},
            {"id": 5, "duration": 0, "predecessors": [2, 3, 4], "successors": [],
             "resources_required": {}},
        ],
    }


def select_by_id(eligible, jobs, snap, meta):
    return min(eligible)


def test_ssgs_inserts_job_into_earlier_gap(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), gap_instance(), select_job_fn=select_by_id)
    assert res["status"] == "complete"
    assert res["schedule"] == {1: 0, 2: 0, 3: 1, 4: 0, 5: 3}
    assert res["objective"]["primary"] == 3


def test_legacy_scheme_does_not_insert_into_gap(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), gap_instance(), select_job_fn=select_by_id,
                scheme="legacy")
    assert res["status"] == "complete"
    assert res["schedule"][4] == 3
    assert res["objective"]["primary"] == 4


# =============================================================================
# 4. Статус результата вместо "запустилось без исключения"
# =============================================================================

def test_complete_schedule_reports_status(tmp_path):
    res = solve(dsl_tmp(tmp_path, DSL_BASE), diamond())
    assert res["status"] == "complete"
    assert res["reason"] is None
    assert res["unscheduled"] == []


def test_precedence_cycle_yields_incomplete_not_partial_success(tmp_path):
    raw = diamond()
    raw["jobs"][1]["predecessors"] = [1, 3]  # 2 ждёт 3
    raw["jobs"][2]["predecessors"] = [1, 2]  # 3 ждёт 2 — цикл
    res = solve(dsl_tmp(tmp_path, DSL_BASE), raw)
    assert res["status"] == "incomplete"
    assert res["reason"] == "deadlock"
    assert sorted(res["unscheduled"]) == [2, 3, 4]
    assert res["objective"]["primary"] is None


def test_job_larger_than_capacity_is_infeasible(tmp_path):
    raw = diamond()
    raw["jobs"][1]["resources_required"] = {"1": 5}  # мощность 3
    res = solve(dsl_tmp(tmp_path, DSL_BASE), raw)
    assert res["status"] == "incomplete"
    assert res["reason"] == "infeasible"
    assert 2 in res["unscheduled"]


# =============================================================================
# 5. Многопроектная задача
# =============================================================================

def test_multi_project_ids_do_not_collide_in_synthetic_instance():
    meta = DSLParser().parse_dict(DSL_MP)
    state = ProblemFactory().build(two_projects_same_ids(), meta)
    assert len(state.jobs) == 8
    by_project: dict = {}
    for job in state.jobs.values():
        by_project.setdefault(job.project_id, []).append(job)
    assert {pid: len(js) for pid, js in by_project.items()} == {1: 4, 2: 4}
    for job in state.jobs.values():
        for sid in job.successors:
            assert state.jobs[sid].project_id == job.project_id


def test_multi_project_real_case5_has_all_184_jobs():
    meta = DSLParser().parse_file(dsl_path(5))
    state = ProblemFactory().build(instance(5), meta)
    assert len(state.jobs) == 184


def test_multi_project_objective_is_sum_of_project_makespans():
    meta = DSLParser().parse_dict(DSL_MP)
    state = ProblemFactory().build(two_projects_same_ids(), meta)
    # проект 1: работы в t=0 -> makespan 3; проект 2: работа 2 (d=3) в t=1 -> makespan 4
    for job in state.jobs.values():
        state.schedule[job.id] = 1 if (job.project_id == 2 and job.local_id == 2) else 0
    obj = ObjectiveCalculator().compute(state)
    assert obj["project_makespans"] == {1: 3, 2: 4}
    assert obj["primary"] == 7
    assert obj["total_makespan"] == 7
    assert obj["portfolio_makespan"] == 4


# =============================================================================
# 6. Строгость парсинга
# =============================================================================

def test_unknown_resource_type_raises():
    raw = diamond()
    raw["resources"][0]["type"] = "renewbale"
    with pytest.raises(ValueError, match="resource type"):
        ProblemFactory().build(raw, DSLParser().parse_dict(DSL_BASE))


def test_requirement_of_unknown_resource_raises():
    raw = diamond()
    raw["jobs"][1]["resources_required"] = {"7": 1}
    with pytest.raises(ValueError, match="unknown resource"):
        ProblemFactory().build(raw, DSLParser().parse_dict(DSL_BASE))


def test_predecessor_outside_instance_raises():
    raw = diamond()
    raw["jobs"][1]["predecessors"] = [42]
    with pytest.raises(ValueError, match="unknown job"):
        ProblemFactory().build(raw, DSLParser().parse_dict(DSL_BASE))


# =============================================================================
# 7. Данные: Case 2 согласован с сырым файлом OR-Library
# =============================================================================

def test_case2_due_date_matches_biskup_feldmann_formula():
    raw = instance(2)
    params = raw["parameters"]
    total = sum(j["duration"] for j in raw["jobs"])
    assert params["total_duration"] == total
    assert params["common_due_date"] == math.floor(total * params["h_factor"])
    full_dsl = load(dsl_path(2))
    brief_dsl = load(BRIEF_DSL_DIR / "Case2_DSL_for_skeleton.json")
    for d in (full_dsl, brief_dsl):
        assert d["optimization_objectives"]["secondary"]["parameters"]["due_date"] \
            == params["common_due_date"]


# =============================================================================
# 8. Реальные инстансы: полное расписание, а не покрытие "> 0"
# =============================================================================

@pytest.mark.parametrize("case", [1, 2, 5])
def test_real_instance_is_scheduled_completely(case):
    raw = instance(case)
    res = solve(dsl_path(case), raw)
    assert res["status"] == "complete", res.get("detail")
    assert res["unscheduled"] == []
    assert res["objective"]["primary"] is not None
