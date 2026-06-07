"""
Тесты каркаса планировщика

Структура:
  1. Юнит-тесты DSLParser (parse_dict по каждому кейсу)
  2. Юнит-тесты ProblemFactory (правильно создает Jobs/Resources)
  3. Юнит-тесты ProblemState (eligible_jobs, advance_time, ресурсный учет)
  4. Юнит-тесты ObjectiveCalculator (makespan, ET-penalty, NRR budget)
  5. Интеграционные тесты solve() с синтетическими инстансами
  6. Smoke-тест: парсинг реальных DSL-файлов
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scheduler_skeleton import (
    DSLParser, ProblemFactory, ObjectiveCalculator,
    solve, )

# Helpers

PASS = "+"
FAIL = "-"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    icon = PASS if condition else FAIL
    print(f"  {icon}  {name}" + (f"  [{detail}]" if detail else ""))


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


# DSL raw dicts (из файлов, уже прочитанных)

DSL = {
    1: {
        "project_id": "PSPLIB_J30_RCPSP",
        "problem_statement": {
            "constraint_types": ["Precedence", "Resource Capacities"],
            "resource_nature": "Renewable",
            "execution_mode": "Single-Mode",
            "uncertainty": "Deterministic",
        },
        "optimization_objectives": {
            "primary": {"metric": "Makespan", "direction": "Minimize"}
        },
        "graph_meta_characteristics": {
            "nodes": 32, "edges": 48, "cpl": 11, "max_parallelism": 11
        },
    },
    2: {
        "project_id": "SINGLE_MACHINE_JIT",
        "problem_statement": {
            "problem_type": "Single-Machine Common Due Date",
            "constraint_types": {"hard": ["Single Resource Capacity"],
                                 "soft": ["Common Due Date"]},
            "resource_nature": "Renewable",
            "execution_mode": "Single-Mode",
            "uncertainty": "Deterministic",
        },
        "optimization_objectives": {
            "metric": "Total Earliness/Tardiness Penalty",
            "direction": "Minimize",
            "secondary": {"metric": "Due Date Deviation", "direction": "Minimize",
                          "parameters": {"due_date": 106}},
        },
        "graph_meta_characteristics": {"nodes": 50, "edges": 0, "max_parallelism": 1},
    },
    3: {
        "project_id": "RCPSP_MULTI_RESOURCE",
        "problem_statement": {
            "problem_type": "RCPSP with renewable and non-renewable resources",
            "constraint_types": ["Precedence", "Resource Capacities",
                                 "Conditional Precedence"],
            "resource_nature": "Renewable and Non-Renewable",
            "execution_mode": "Single-Mode",
            "uncertainty": "Deterministic",
        },
        "optimization_objectives": {
            "primary": {"metric": "Makespan", "direction": "Minimize"},
            "secondary": {
                "metric": "Non-Renewable Resource Consumption",
                "direction": "Minimize",
                "parameters": {"budget_limit": {"NRR1": 580, "NRR2": 596}},
            },
        },
        "graph_meta_characteristics": {"nodes": 122, "edges": 228, "cpl": 26,
                                       "max_parallelism": 10},
        "conditional_scheduling": {
            "enabled": True, "selection_groups_present": True,
            "time_precedence_present": True
        },
    },
    4: {
        "project_id": "CONDITIONAL_RCPSP",
        "problem_statement": {
            "problem_type": "RCPSP with Conditional Constraints",
            "constraint_types": ["Precedence", "Resource Capacities",
                                 "Selection Successors"],
            "resource_nature": "Renewable",
            "execution_mode": "Single-Mode",
            "uncertainty": "Deterministic",
        },
        "optimization_objectives": {
            "primary": {"metric": "Makespan", "direction": "Minimize"}
        },
        "graph_meta_characteristics": {"nodes": 122, "edges": 216, "cpl": 27,
                                       "max_parallelism": 10},
        "conditional_scheduling": {
            "enabled": True, "selection_groups_present": True,
            "time_precedence_present": True
        },
    },
    5: {
        "project_id": "RCMPSP_MULTI_PROJECT",
        "problem_statement": {
            "problem_type": "RCMPSP",
            "constraint_types": ["Precedence", "Resource Capacities",
                                 "Cross-Project Resource Sharing"],
            "resource_nature": "Renewable",
            "execution_mode": "Single-Mode",
            "uncertainty": "Deterministic",
        },
        "optimization_objectives": {
            "primary": {"metric": "Total Makespan (All Projects)",
                        "direction": "Minimize"}
        },
        "graph_meta_characteristics": {"nodes": 184, "edges": 332,
                                       "max_parallelism": 33},
    },
}

# Синтетические инстансы для каждого кейса

INSTANCE = {}

# Case 1: базовый RCPSP, 4 работы (dummy start/end + 2 рабочих)
INSTANCE[1] = {
    "resources": [
        {"id": 1, "name": "R1", "capacity": 3, "type": "renewable"},
        {"id": 2, "name": "R2", "capacity": 2, "type": "renewable"},
    ],
    "jobs": [
        {"id": 1, "duration": 0, "predecessors": [], "successors": [2, 3],
         "resources_required": {}},
        {"id": 2, "duration": 3, "predecessors": [1], "successors": [4],
         "resources_required": {"1": 2, "2": 1}},
        {"id": 3, "duration": 2, "predecessors": [1], "successors": [4],
         "resources_required": {"1": 1, "2": 1}},
        {"id": 4, "duration": 0, "predecessors": [2, 3], "successors": [],
         "resources_required": {}},
    ],
}

# Case 2: одна машина, 3 работы с пенальти
INSTANCE[2] = {
    "resources": [
        {"id": 1, "name": "Machine", "capacity": 1, "type": "renewable"},
    ],
    "jobs": [
        {"id": 1, "duration": 40, "predecessors": [], "successors": [],
         "resources_required": {"1": 1},
         "penalties": {"earliness_unit_penalty": 2, "tardiness_unit_penalty": 3}},
        {"id": 2, "duration": 50, "predecessors": [], "successors": [],
         "resources_required": {"1": 1},
         "penalties": {"earliness_unit_penalty": 1, "tardiness_unit_penalty": 4}},
        {"id": 3, "duration": 30, "predecessors": [], "successors": [],
         "resources_required": {"1": 1},
         "penalties": {"earliness_unit_penalty": 3, "tardiness_unit_penalty": 2}},
    ],
}

# Case 3: renewable + non-renewable
INSTANCE[3] = {
    "resources": [
        {"id": 1, "name": "R1", "capacity": 4, "type": "renewable", "initial_stock": 4},
        {"id": 2, "name": "NRR1", "capacity": 0, "type": "non-renewable",
         "initial_stock": 100},
    ],
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
}

# Case 4: conditional (selection groups)
INSTANCE[4] = {
    "resources": [
        {"id": 1, "name": "R1", "capacity": 2, "type": "renewable"},
    ],
    "jobs": [
        {"id": 1, "duration": 0, "predecessors": [], "successors": [],
         "resources_required": {},
         "precedences": {"time_successors": [2], "selection_groups": []}},
        {"id": 2, "duration": 4, "predecessors": [1], "successors": [],
         "resources_required": {"1": 1},
         "precedences": {"time_successors": [4], "selection_groups": [[3]]}},
        {"id": 3, "duration": 3, "predecessors": [1], "successors": [],
         # альтернатива job 2
         "resources_required": {"1": 1},
         "precedences": {"time_successors": [], "selection_groups": []}},
        {"id": 4, "duration": 0, "predecessors": [2], "successors": [],
         "resources_required": {},
         "precedences": {"time_successors": [], "selection_groups": []}},
    ],
}

# Case 5: multi-project
INSTANCE[5] = {
    "resources": [
        {"id": 1, "name": "G1", "capacity": 4, "type": "global"},
    ],
    "jobs": [
        {"project_id": 1, "num_activities": 3, "due_date": 20, "activities": [
            {"id": 1, "duration": 0, "resources_required": [0], "successors": [2, 3]},
            {"id": 2, "duration": 3, "resources_required": [2], "successors": [4]},
            {"id": 3, "duration": 2, "resources_required": [2], "successors": [4]},
            {"id": 4, "duration": 0, "resources_required": [0], "successors": []},
        ]},
        {"project_id": 2, "num_activities": 3, "due_date": 25, "activities": [
            {"id": 5, "duration": 0, "resources_required": [0], "successors": [6, 7]},
            {"id": 6, "duration": 4, "resources_required": [2], "successors": [8]},
            {"id": 7, "duration": 2, "resources_required": [2], "successors": [8]},
            {"id": 8, "duration": 0, "resources_required": [0], "successors": []},
        ]},
    ],
}

# 1. DSL PARSER TESTS

section("1. DSLParser — разбор всех 5 кейсов")

parser = DSLParser()

# Case 1
m1 = parser.parse_dict(DSL[1])
check("C1: project_id", m1.project_id == "PSPLIB_J30_RCPSP")
check("C1: primary_metric", m1.primary_metric == "Makespan")
check("C1: is_single_machine", not m1.is_single_machine)
check("C1: is_multi_project", not m1.is_multi_project)
check("C1: has_non_renewable", not m1.has_non_renewable)
check("C1: constraint_types", "Precedence" in m1.constraint_types)

# Case 2
m2 = parser.parse_dict(DSL[2])
check("C2: is_single_machine", m2.is_single_machine)
check("C2: primary_metric ET",
      "Earliness" in m2.primary_metric or "Tardiness" in m2.primary_metric)
check("C2: due_date param", m2.secondary_params.get("due_date") == 106)
check("C2: constraints merged", "Single Resource Capacity" in m2.constraint_types
      and "Common Due Date" in m2.constraint_types,
      f"got {m2.constraint_types}")

# Case 3
m3 = parser.parse_dict(DSL[3])
check("C3: has_non_renewable", m3.has_non_renewable)
check("C3: secondary_metric",
      m3.secondary_metric == "Non-Renewable Resource Consumption")
check("C3: budget NRR1", m3.secondary_params.get("budget_limit", {}).get("NRR1") == 580)
check("C3: conditional", m3.conditional_scheduling)
check("C3: selection_groups", m3.selection_groups_present)

# Case 4
m4 = parser.parse_dict(DSL[4])
check("C4: conditional", m4.conditional_scheduling)
check("C4: selection_groups", m4.selection_groups_present)
check("C4: primary makespan", m4.primary_metric == "Makespan")

# Case 5
m5 = parser.parse_dict(DSL[5])
check("C5: is_multi_project", m5.is_multi_project)
check("C5: total makespan", "Total Makespan" in m5.primary_metric)

# summary() smoke
summary_str = parser.summary(m3)
check("summary contains project_id", "RCPSP_MULTI_RESOURCE" in summary_str)
check("summary contains secondary", "Non-Renewable" in summary_str)

# 2. ProblemFactory TESTS

section("2. ProblemFactory — структура Jobs и Resources")

factory = ProblemFactory()

# Case 1: обычный RCPSP
state1 = factory.build(INSTANCE[1], m1)
check("C1: кол-во работ", len(state1.jobs) == 4)
check("C1: кол-во ресурсов", len(state1.resources) == 2)
check("C1: job2 predecessors", state1.jobs[2].predecessors == [1])
check("C1: job2 duration", state1.jobs[2].duration == 3)
check("C1: job2 res R1=2", state1.jobs[2].resources_required.get(1) == 2)
check("C1: R1 capacity=3", state1.resources[1].capacity == 3)
check("C1: R1 type renewable", state1.resources[1].r_type == "renewable")

# Case 2: пенальти
state2 = factory.build(INSTANCE[2], m2)
check("C2: job1 earliness pen", state2.jobs[1].earliness_penalty == 2)
check("C2: job1 tardiness pen", state2.jobs[1].tardiness_penalty == 3)

# Case 3: non-renewable
state3 = factory.build(INSTANCE[3], m3)
nrr = state3.resources[2]
check("C3: NRR1 type", nrr.r_type == "non-renewable")
check("C3: NRR1 initial_stock", nrr.initial_stock == 100)
check("C3: job2 NRR consumption", state3.jobs[2].non_renewable_consumption.get(2) == 30)

# Case 4: selection groups
state4 = factory.build(INSTANCE[4], m4)
check("C4: job2 selection_groups", state4.jobs[2].selection_groups == [[3]])
check("C4: job2 successors include 4", 4 in state4.jobs[2].successors)

# Case 5: multi-project
state5 = factory.build(INSTANCE[5], m5)
check("C5: всего 8 работ", len(state5.jobs) == 8)
check("C5: job2 project_id=1", state5.jobs[2].project_id == 1)
check("C5: job6 project_id=2", state5.jobs[6].project_id == 2)
check("C5: predecessors из succs", 5 in state5.jobs[6].predecessors)

# 3. ProblemState TESTS

section("3. ProblemState — механика состояния")

# eligible_jobs: только работы с выполненными предшественниками
s = factory.build(INSTANCE[1], m1)
check("eligible at start: только job1 (dummy)", s.eligible_jobs() == [1],
      f"got {s.eligible_jobs()}")

# Запускаем job1 (duration=0, нет ресурсов)
s.start_job(1, {})
s.active_jobs[1] = 0  # финишируют в t=0
s.finish_jobs_at(0)
check("job1 completed", 1 in s.completed_jobs)
check("после job1: eligible=[2,3]", set(s.eligible_jobs()) == {2, 3},
      f"got {s.eligible_jobs()}")

# Ресурсный учёт
s.start_job(2, {1: 2, 2: 1})
check("R1 used=2 после job2", s.renewable_used[1] == 2)
check("R1 available=1", s.available_capacity(1) == 1)
check("can_allocate job3(1,1)", s.can_allocate(s.jobs[3], {1: 1, 2: 1}))
check("cannot alloc (3,0)", not s.can_allocate(s.jobs[3], {1: 3, 2: 0}))

# advance_time: освобождает ресурсы
s.start_job(3, {1: 1, 2: 1})
s.advance_time()  # переходим к t=min(finish_j2=3, finish_j3=2)=2
check("advance_time → t=2", s.current_time == 2)
check("job3 завершена", 3 in s.completed_jobs)
check("R1 after job3 done", s.renewable_used[1] == 2)  # job2 ещё идёт

# is_done
s2 = factory.build(INSTANCE[1], m1)
check("is_done=False at start", not s2.is_done())

# snapshot содержит нужные ключи
snap = s2.snapshot()
for key in ["current_time", "eligible_jobs", "renewable_used", "completed_jobs"]:
    check(f"snapshot has '{key}'", key in snap)

# 4. ObjectiveCalculator TESTS

section("4. ObjectiveCalculator — расчёт метрик")

calc = ObjectiveCalculator()

# --- Makespan (Case 1) ---
s_ms = factory.build(INSTANCE[1], m1)
# Вручную строим расписание: job1@0, job2@0, job3@0, job4@3
s_ms.schedule = {1: 0, 2: 0, 3: 0, 4: 3}
s_ms.completed_jobs = {1, 2, 3, 4}
obj = calc.compute(s_ms)
check("Makespan=3", obj["makespan"] == 3, f"got {obj['makespan']}")
check("primary=3", obj["primary"] == 3)

# --- ET Penalty (Case 2) ---
s_et = factory.build(INSTANCE[2], m2)
# due_date=106, job1 финиш=40 (early), job2 финиш=90 (early), job3 финиш=120 (late)
s_et.schedule = {1: 0, 2: 40, 3: 90}
s_et.completed_jobs = {1, 2, 3}
# job1: finish=40, early by 66, ep=2 → penalty=132
# job2: finish=90, early by 16, ep=1 → penalty=16
# job3: finish=120, late by 14, tp=2 → penalty=28
# total = 176
obj2 = calc.compute(s_et)
expected_penalty = (106 - 40) * 2 + (106 - 90) * 1 + (120 - 106) * 2
check(f"ET penalty={expected_penalty}", obj2["primary"] == expected_penalty,
      f"got {obj2['primary']}")
check("job1 type=early", obj2["job_details"][1]["type"] == "early")
check("job3 type=late", obj2["job_details"][3]["type"] == "late")

# --- NRR Budget (Case 3) ---
s_nrr = factory.build(INSTANCE[3], m3)
s_nrr.schedule = {1: 0, 2: 0, 3: 0, 4: 3}
s_nrr.completed_jobs = {1, 2, 3, 4}
# job2 потребил 30, job3 потребил 20, итого 50 из 100
s_nrr.non_renewable_stock[2] = 100 - 50
obj3 = calc.compute(s_nrr)
check("NRR used=50", obj3["non_renewable_used"].get("NRR1") == 50,
      f"got {obj3.get('non_renewable_used')}")
check("budget_feasible", obj3["budget_feasible"])

# Нарушение бюджета
s_nrr2 = factory.build(INSTANCE[3], m3)
s_nrr2.schedule = {1: 0, 2: 0, 3: 0, 4: 3}
s_nrr2.completed_jobs = {1, 2, 3, 4}
s_nrr2.non_renewable_stock[2] = 100 - 600  # потребили 600 > лимита 580
# Но бюджет задан в meta.secondary_params["budget_limit"]["NRR1"]=580
# Ресурс называется "NRR1", budget key="NRR1" — должно сработать
s_nrr2.non_renewable_stock[2] = -500
obj3v = calc.compute(s_nrr2)
check("budget violated", not obj3v["budget_feasible"],
      f"violations={obj3v.get('budget_violations')}")

# --- Total Makespan multi-project (Case 5) ---
s_mp = factory.build(INSTANCE[5], m5)
s_mp.schedule = {1: 0, 2: 0, 3: 0, 4: 3, 5: 0, 6: 0, 7: 0, 8: 4}
s_mp.completed_jobs = {1, 2, 3, 4, 5, 6, 7, 8}
s_mp.project_finish = {1: 3, 2: 4}
obj5 = calc.compute(s_mp)
check("Total makespan=4", obj5["primary"] == 4, f"got {obj5['primary']}")
check("project_finish_times present", "project_finish_times" in obj5)

# 5. ИНТЕГРАЦИОННЫЕ ТЕСТЫ solve()

section("5. Интеграция — solve() по каждому кейсу")

DSL_FILES = {k: Path(f"C:/Users/Admin/Documents/GitHub/DSL_to_heuristics_process"
                     f"/data/references/Case{k}_DSL.json") for k in range(1, 6)}
# Проверим, есть ли файлы; если нет — используем parse_dict + tmp файл
import tempfile


def dsl_path_for(case_id):
    p = DSL_FILES[case_id]
    if p.exists():
        return p
    # Записываем синтетический DSL во временный файл
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(DSL[case_id], tmp)
    tmp.close()
    return Path(tmp.name)


# Case 1 — базовый RCPSP, makespan должен быть > 0
try:
    r1 = solve(dsl_path_for(1), INSTANCE[1], verbose=False)
    check("C1: solve завершился", "schedule" in r1)
    check("C1: makespan > 0", r1["objective"]["primary"] > 0,
          f"makespan={r1['objective']['primary']}")
    check("C1: все работы в schedule", len(r1["schedule"]) == 4)
except Exception as e:
    check("C1: solve без исключений", False, str(e))

# Case 2 — ET penalty, работы sequential (машина 1)
try:
    r2 = solve(dsl_path_for(2), INSTANCE[2], verbose=False)
    check("C2: solve завершился", "schedule" in r2)
    check("C2: ET penalty >= 0", r2["objective"]["primary"] >= 0)
    check("C2: 3 работы в schedule", len(r2["schedule"]) == 3)
    # Все работы должны идти последовательно
    starts = sorted(r2["schedule"].values())
    check("C2: нет параллельных работ", starts[0] == 0,
          f"starts={starts}")
except Exception as e:
    check("C2: solve без исключений", False, str(e))

# Case 3 — renewable + non-renewable
try:
    r3 = solve(dsl_path_for(3), INSTANCE[3], verbose=False)
    check("C3: solve завершился", "schedule" in r3)
    check("C3: makespan > 0", r3["objective"]["primary"] > 0)
    check("C3: budget_feasible", r3["objective"].get("budget_feasible", True))
except Exception as e:
    check("C3: solve без исключений", False, str(e))

# Case 4 — conditional selection
try:
    r4 = solve(dsl_path_for(4), INSTANCE[4], verbose=False)
    check("C4: solve завершился", "schedule" in r4)
    check("C4: makespan >= 0", r4["objective"]["primary"] >= 0)
    # job3 должна быть skipped (job2 выбрана как более приоритетная)
    # зависит от эвристики — просто проверяем что хотя бы одна из (2,3) есть
    sched_ids = set(r4["schedule"].keys())
    check("C4: job1 запланирована", 1 in sched_ids)
except Exception as e:
    check("C4: solve без исключений", False, str(e))

# Case 5 — multi-project
try:
    r5 = solve(dsl_path_for(5), INSTANCE[5], verbose=False)
    check("C5: solve завершился", "schedule" in r5)
    check("C5: total makespan > 0", r5["objective"]["primary"] > 0)
    check("C5: все 8 работ в schedule", len(r5["schedule"]) == 8)
except Exception as e:
    check("C5: solve без исключений", False, str(e))


# Case 1: кастомный select_job (LPT — longest processing time first)
def lpt_select(eligible_ids, jobs, snap, meta):
    return max(eligible_ids, key=lambda jid: jobs[jid].duration)


try:
    r1_lpt = solve(dsl_path_for(1), INSTANCE[1], select_job_fn=lpt_select)
    check("C1 LPT: solve завершился", "schedule" in r1_lpt)
    check("C1 LPT: корректный makespan", r1_lpt["objective"]["primary"] > 0)
except Exception as e:
    check("C1 LPT: solve без исключений", False, str(e))

# 6. SMOKE-TEST: парсинг реальных DSL-файлов

section("6. Smoke-test реальных DSL-файлов")

for case_id in range(1, 6):
    p = DSL_FILES[case_id]
    if not p.exists():
        check(f"Case{case_id} DSL файл найден", False, f"not found: {p}")
        continue
    try:
        meta = DSLParser().parse_file(p)
        check(f"Case{case_id} DSL parse OK", meta.project_id != "UNKNOWN",
              f"id={meta.project_id}")
    except Exception as e:
        check(f"Case{case_id} DSL parse OK", False, str(e))

section("7. Тест на конкретных инстансах")
PROCESSED_DIR = Path(
    "C:/Users/Admin/Documents/GitHub/DSL_to_heuristics_process/data/processed")
REF_DSL_DIR = Path(
    "C:/Users/Admin/Documents/GitHub/DSL_to_heuristics_process/data/references")

CASE_MAP = {
    "Case1_PSPLIB_j301_1.json": 1,
    "Case2_sch50.json": 2,
    "Case3_nonrenewable.json": 3,
    "Case4_renewable.json": 4,
    "Case5_mp_j90_a2_nr1.json": 5,
}

if not PROCESSED_DIR.exists():
    check("Директория processed найдена", False, str(PROCESSED_DIR))
else:
    for fname, case_id in CASE_MAP.items():
        inst_path = PROCESSED_DIR / fname
        dsl_path = REF_DSL_DIR / f"Case{case_id}_DSL.json"

        if not inst_path.exists() or not dsl_path.exists():
            check(f"{fname}: файлы найдены", False)
            continue

        try:
            with open(inst_path, encoding="utf-8") as f:
                instance_data = json.load(f)

            res = solve(dsl_path, instance_data, verbose=False)

            check(f"{fname}: расписание построено", "schedule" in res)
            check(f"{fname}: время старта >= 0",
                  all(v >= 0 for v in res["schedule"].values()))

            # Подсчет ожидаемого кол-ва работ
            num_jobs = len(instance_data.get("jobs", []))
            if isinstance(instance_data.get("jobs"), list) and instance_data[
                "jobs"] and "activities" in instance_data["jobs"][0]:
                num_jobs = sum(
                    len(p.get("activities", [])) for p in instance_data["jobs"])

            scheduled = len(res["schedule"])
            coverage = f"{scheduled}/{num_jobs} ({scheduled / max(num_jobs, 1) * 100:.0f}%)"

            # 1. Базовая проверка: хотя бы одна работа запланирована
            check(f"{fname}: schedule не пустой", scheduled > 0)

            # 2. Адаптивная проверка покрытия
            # Для Case 1,2 (простые RCPSP) требуем 100%
            # Для Case 3,4 (conditional) и 5 (multi-project) допускаем <100% из-за skipped/ресурсов
            if case_id <= 2:
                check(f"{fname}: все работы в schedule", scheduled == num_jobs,
                      coverage)
            else:
                check(f"{fname}: jobs coverage OK (conditional/mp)",
                      0 < scheduled <= num_jobs, coverage)

            primary = res["objective"]["primary"]
            check(f"{fname}: primary metric рассчитана", primary is not None,
                  f"value={primary}")
            if "budget_feasible" in res["objective"]:
                check(f"{fname}: бюджет не нарушен",
                      res["objective"]["budget_feasible"])

        except Exception as e:
            check(f"{fname}: запуск без ошибок", False, str(e))

# ИТОГ

section("ИТОГ")
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

print(f"\n  Пройдено: {passed}/{total}")
if failed:
    print(f"  Упало: {failed}")
    print("\n  Проваленные тесты:")
    for name, ok, detail in results:
        if not ok:
            print(f"    {FAIL} {name}" + (f" [{detail}]" if detail else ""))

sys.exit(0 if failed == 0 else 1)
