from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# DSL PARSER

@dataclass
class DSLMeta:
    project_id: str
    problem_type: str
    constraint_types: list[str]
    resource_nature: str
    execution_mode: str
    uncertainty: str
    primary_metric: str
    primary_direction: str
    secondary_metric: str | None
    secondary_direction: str | None
    secondary_params: dict
    graph: dict
    conditional_scheduling: bool
    selection_groups_present: bool
    time_precedence_present: bool
    has_non_renewable: bool
    is_multi_project: bool
    is_single_machine: bool


class DSLParser:
    def parse_file(self, path: str | Path) -> DSLMeta:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return self._parse(raw)

    def parse_dict(self, raw: dict) -> DSLMeta:
        return self._parse(raw)

    @staticmethod
    def _parse(d: dict) -> DSLMeta:
        ps = d.get("problem_statement", {})
        project_id = d.get("project_id", "UNKNOWN")

        # Тип задачи
        problem_type = ps.get("problem_type", project_id)

        # Типы ограничений
        ct = ps.get("constraint_types", [])
        if isinstance(ct, dict):
            ct = ct.get("hard", []) + ct.get("soft", [])
        constraint_types: list[str] = list(ct)

        resource_nature = ps.get("resource_nature", "Renewable")
        execution_mode = ps.get("execution_mode", "Single-Mode")
        uncertainty = ps.get("uncertainty", "Deterministic")

        # Целевые функции
        obj = d.get("optimization_objectives", {})
        primary = obj.get("primary", obj)  # Case 2 - нет вложенности primary
        primary_metric = primary.get("metric", "Makespan")
        primary_direction = primary.get("direction", "Minimize")

        secondary = obj.get("secondary", {})
        secondary_metric = secondary.get("metric") if secondary else None
        secondary_direction = secondary.get("direction") if secondary else None
        secondary_params = secondary.get("parameters", {}) if secondary else {}

        # Граф
        graph = d.get("graph_meta_characteristics", {})

        # Условное планирование
        cond = d.get("conditional_scheduling", {})
        conditional_scheduling = bool(cond.get("enabled", False))
        selection_groups_present = bool(cond.get("selection_groups_present", False))
        time_precedence_present = bool(cond.get("time_precedence_present", False))

        # Флаги
        has_non_renewable = "Non-Renewable" in resource_nature
        is_multi_project = "MULTI_PROJECT" in project_id or "RCMPSP" in project_id
        is_single_machine = "SINGLE_MACHINE" in project_id

        return DSLMeta(
            project_id=project_id,
            problem_type=problem_type,
            constraint_types=constraint_types,
            resource_nature=resource_nature,
            execution_mode=execution_mode,
            uncertainty=uncertainty,
            primary_metric=primary_metric,
            primary_direction=primary_direction,
            secondary_metric=secondary_metric,
            secondary_direction=secondary_direction,
            secondary_params=secondary_params,
            graph=graph,
            conditional_scheduling=conditional_scheduling,
            selection_groups_present=selection_groups_present,
            time_precedence_present=time_precedence_present,
            has_non_renewable=has_non_renewable,
            is_multi_project=is_multi_project,
            is_single_machine=is_single_machine,
        )

    @staticmethod
    def summary(meta: DSLMeta) -> str:
        """Для логирования"""
        lines = [
            f"Project: {meta.project_id}",
            f"Problem type: {meta.problem_type}",
            f"Constraints: {', '.join(meta.constraint_types)}",
            f"Resources: {meta.resource_nature}",
            f"Objective: {meta.primary_direction} {meta.primary_metric}",
        ]
        if meta.secondary_metric:
            lines.append(
                f"Secondary: {meta.secondary_direction} {meta.secondary_metric}"
                + (f"  params={meta.secondary_params}" if meta.secondary_params else "")
            )
        if meta.conditional_scheduling:
            lines.append(
                f"Conditional: selection_groups={meta.selection_groups_present}, "
                f"time_precedence={meta.time_precedence_present}"
            )
        if meta.is_multi_project:
            lines.append("Multi-project: YES")
        if meta.is_single_machine:
            lines.append("Single-machine: YES")
        g = meta.graph
        lines.append(
            f"Graph: nodes={g.get('nodes')}, edges={g.get('edges')}, "
            f"CPL={g.get('cpl', '?')}, max_par={g.get('max_parallelism', '?')}"
        )
        return "\n".join(lines)


# PROBLEM STATE

@dataclass
class Job:
    id: int
    duration: int
    predecessors: list[int]
    successors: list[int]
    resources_required: dict[int, int]
    earliness_penalty: int = 0
    tardiness_penalty: int = 0
    project_id: int | None = None
    non_renewable_consumption: dict[int, int] = field(default_factory=dict)
    selection_groups: list[list[int]] = field(default_factory=list)


@dataclass
class Resource:
    id: int
    name: str
    capacity: int
    r_type: str = "renewable"
    initial_stock: int = 0


@dataclass
class ProblemState:
    jobs: dict[int, Job]
    resources: dict[int, Resource]
    meta: DSLMeta

    # Изменяемое состояние
    current_time: int = 0
    schedule: dict[int, int] = field(default_factory=dict)  # job_id -> start_time
    active_jobs: dict[int, int] = field(default_factory=dict)  # job_id -> finish_time
    completed_jobs: set[int] = field(default_factory=set)
    skipped_jobs: set[int] = field(default_factory=set)  # conditional: не выбраны
    renewable_used: dict[int, int] = field(default_factory=dict)  # resource_id -> used
    non_renewable_stock: dict[int, int] = field(default_factory=dict)
    # Multi-project: словарь finish_time по project_id
    project_finish: dict[int, int] = field(default_factory=dict)

    def __post_init__(self):
        for r in self.resources.values():
            if r.r_type == "renewable" or r.r_type == "global":
                self.renewable_used[r.id] = 0
            else:
                self.non_renewable_stock[r.id] = r.initial_stock

    def available_capacity(self, resource_id: int) -> int:
        r = self.resources[resource_id]
        return r.capacity - self.renewable_used.get(resource_id, 0)

    def is_eligible(self, job_id: int) -> bool:
        """
        Работа готова к запуску:
        все предшественники выполнены, сама еще не запланирована.
        """
        if job_id in self.schedule or job_id in self.skipped_jobs:
            return False
        job = self.jobs[job_id]
        return all(p in self.completed_jobs for p in job.predecessors)

    def eligible_jobs(self) -> list[int]:
        return [jid for jid in self.jobs if self.is_eligible(jid)]

    def can_allocate(self, job: Job, allocation: dict[int, int]) -> bool:
        """Проверяет, что выделение ресурсов не превышает доступные мощности."""
        for rid, amount in allocation.items():
            if amount > self.available_capacity(rid):
                return False
        return True

    def start_job(self, job_id: int, allocation: dict[int, int]):
        job = self.jobs[job_id]
        self.schedule[job_id] = self.current_time
        finish = self.current_time + job.duration
        self.active_jobs[job_id] = finish
        for rid, amount in allocation.items():
            self.renewable_used[rid] = self.renewable_used.get(rid, 0) + amount
        # Non-renewable consumption (уменьшаем запас)
        for rid, cons in job.non_renewable_consumption.items():
            self.non_renewable_stock[rid] -= cons
        # Non-renewable production (увеличиваем запас при наличии)
        for rid, prod in job.__dict__.get("non_renewable_production", {}).items():
            self.non_renewable_stock[rid] = self.non_renewable_stock.get(rid, 0) + prod

    def finish_jobs_at(self, time: int):
        """Завершает все активные работы, которые должны закончиться в момент time."""
        done = [jid for jid, ft in self.active_jobs.items() if ft <= time]
        for jid in done:
            job = self.jobs[jid]
            # Освобождаем ресурсы
            for rid, amount in job.resources_required.items():
                self.renewable_used[rid] = max(0,
                                               self.renewable_used.get(rid, 0) - amount)
            self.completed_jobs.add(jid)
            del self.active_jobs[jid]
            # Multi-project
            if job.project_id is not None:
                prev = self.project_finish.get(job.project_id, 0)
                self.project_finish[job.project_id] = max(prev, self.schedule[
                    jid] + job.duration)

    def advance_time(self):
        """Перематываем время до ближайшего завершения активной работы."""
        if self.active_jobs:
            next_finish = min(self.active_jobs.values())
            self.current_time = next_finish
            self.finish_jobs_at(next_finish)

    def is_done(self) -> bool:
        remaining = set(self.jobs.keys()) - self.completed_jobs - self.skipped_jobs
        return len(remaining) == 0 and len(self.active_jobs) == 0

    def snapshot(self) -> dict:
        """Cнапшот для передачи в LLM-функции (без тяжелых объектов)."""
        return {
            "current_time": self.current_time,
            "completed_jobs": list(self.completed_jobs),
            "active_jobs": dict(self.active_jobs),
            "eligible_jobs": self.eligible_jobs(),
            "renewable_used": dict(self.renewable_used),
            "non_renewable_stock": dict(self.non_renewable_stock),
            "skipped_jobs": list(self.skipped_jobs),
        }


# РАСЧЕТ МЕТРИК

class ObjectiveCalculator:

    @staticmethod
    def compute(state: ProblemState) -> dict[str, Any]:
        meta = state.meta
        result: dict[str, Any] = {}

        # Makespan (Cases 1, 3, 4)
        if meta.primary_metric == "Makespan":
            makespan = max(
                (state.schedule[jid] + state.jobs[jid].duration)
                for jid in state.schedule
            ) if state.schedule else 0
            result["makespan"] = makespan
            result["primary"] = makespan

        # Total Makespan (Case 5)
        elif "Total Makespan" in meta.primary_metric:
            total = max(state.project_finish.values()) if state.project_finish else 0
            result["total_makespan"] = total
            result["project_finish_times"] = dict(state.project_finish)
            result["primary"] = total

        # Earliness / Tardiness Penalty (Case 2)
        elif "Earliness" in meta.primary_metric or "Tardiness" in meta.primary_metric:
            due_date = meta.secondary_params.get("due_date", 0)
            total_penalty = 0
            details: dict[int, dict] = {}
            for jid, job in state.jobs.items():
                if jid not in state.schedule:
                    continue
                finish = state.schedule[jid] + job.duration
                if finish < due_date:
                    penalty = (due_date - finish) * job.earliness_penalty
                    details[jid] = {"type": "early", "amount": due_date - finish,
                                    "penalty": penalty}
                elif finish > due_date:
                    penalty = (finish - due_date) * job.tardiness_penalty
                    details[jid] = {"type": "late", "amount": finish - due_date,
                                    "penalty": penalty}
                else:
                    details[jid] = {"type": "on_time", "amount": 0, "penalty": 0}
                    penalty = 0
                total_penalty += penalty
            result["total_et_penalty"] = total_penalty
            result["due_date"] = due_date
            result["job_details"] = details
            result["primary"] = total_penalty

        else:
            result["primary"] = None
            result["warning"] = f"Unknown primary metric: {meta.primary_metric}"

        # Secondary: Non-Renewable Resource Consumption (Case 3)
        if meta.secondary_metric == "Non-Renewable Resource Consumption":
            budgets = meta.secondary_params.get("budget_limit", {})
            nrr_used: dict[str, int] = {}
            for rid, stock in state.non_renewable_stock.items():
                r = state.resources.get(rid)
                if r and r.r_type == "non-renewable":
                    used = r.initial_stock - stock
                    nrr_used[r.name] = used
            result["non_renewable_used"] = nrr_used
            # feasibility check
            violations = {}
            for name, limit in budgets.items():
                used = nrr_used.get(name, 0)
                if used > limit:
                    violations[name] = {"used": used, "limit": limit,
                                        "excess": used - limit}
            result["budget_violations"] = violations
            result["budget_feasible"] = len(violations) == 0

        return result


# ФОРМИРОВАНИЕ ДАННЫХ ДЛЯ КОДА

class ProblemFactory:
    """
    Преобразует сырые данные задачи (dict) + DSLMeta в ProblemState.
    Поддерживает унифицированный формат: resources[] + jobs[].
    """

    def build(self, raw_data: dict, meta: DSLMeta) -> ProblemState:
        resources = self._parse_resources(raw_data.get("resources", []), meta)
        jobs = self._parse_jobs(raw_data.get("jobs", []), meta)
        return ProblemState(jobs=jobs, resources=resources, meta=meta)

    @staticmethod
    def _parse_resources(raw: list[dict], meta: DSLMeta) -> dict[int, Resource]:
        result = {}
        for r in raw:
            rid = r["id"]
            result[rid] = Resource(
                id=rid,
                name=r.get("name", str(rid)),
                capacity=r.get("capacity", r.get("initial_stock", 0)),
                r_type=r.get("type", "renewable"),
                initial_stock=r.get("initial_stock", r.get("capacity", 0)),
            )
        return result

    @staticmethod
    def _parse_jobs(raw: list[dict], meta: DSLMeta) -> dict[int, Job]:
        result = {}

        # Case 5: multi-project - jobs это массив проектов
        if meta.is_multi_project:
            for proj in raw:
                pid = proj.get("project_id")
                for act in proj.get("activities", []):
                    jid = act["id"]
                    rr = act.get("resources_required", [])
                    # Конвертируем список в словарь по индексу (1-based)
                    rr_dict = {i + 1: v for i, v in enumerate(rr)} if (
                        isinstance(rr, list)) \
                        else rr
                    result[jid] = Job(
                        id=jid,
                        duration=act.get("duration", 0),
                        predecessors=[],
                        successors=act.get("successors", []),
                        resources_required=rr_dict,
                        project_id=pid,
                    )
            # Восстанавливаем predecessors из successors
            for jid, job in result.items():
                for sid in job.successors:
                    if sid in result:
                        result[sid].predecessors.append(jid)
            return result

        # Стандартный формат
        for j in raw:
            jid = j.get("id")

            # Predecessors / successors
            preds = j.get("predecessors", [])
            succs = j.get("successors", [])

            # Duration
            dur = j.get("duration", 0)
            # Case 1: modes[]
            if not dur and "modes" in j:
                dur = j["modes"][0].get("duration", 0)

            # Resources
            rr = j.get("resources_required", {})
            if not rr and "modes" in j:
                rr = j["modes"][0].get("resources_required", {})
            # Нормализуем ключи к int
            rr = {int(k): v for k, v in rr.items()} if isinstance(rr, dict) else {}

            # Penalties (Case 2)
            pen = j.get("penalties", {})
            ep = pen.get("earliness_unit_penalty", 0)
            tp = pen.get("tardiness_unit_penalty", 0)

            # Non-renewable consumption (Case 3)
            # consumption уменьшает запас, production увеличивает запас
            nrc_raw = j.get("resource_consumption", {})
            nrc = {}
            nrp = {}
            for rid_str, info in nrc_raw.items():
                rid = int(rid_str)
                cons = info.get("consumption", 0)
                prod = info.get("production", 0)
                if cons > 0:
                    nrc[rid] = cons
                if prod > 0:
                    nrp[rid] = prod

            # Selection groups (Cases 3, 4)
            prec = j.get("precedences", {})
            if isinstance(prec, dict):
                time_succs = prec.get("time_successors", [])
                sel_groups = prec.get("selection_groups", [])
                # Мержим time_successors в successors
                succs = list(set(succs) | set(time_succs))
            else:
                sel_groups = []

            result[jid] = Job(
                id=jid,
                duration=dur,
                predecessors=preds,
                successors=succs,
                resources_required=rr,
                earliness_penalty=ep,
                tardiness_penalty=tp,
                non_renewable_consumption=nrc,
                selection_groups=sel_groups,
            )
            if nrp:
                result[jid].__dict__["non_renewable_production"] = nrp

        # Восстанавливаем predecessors из successors для Cases 3, 4
        has_predecessors = any(result[jid].predecessors for jid in result)
        if not has_predecessors and any(result[jid].successors for jid in result):
            for jid, job in result.items():
                for sid in job.successors:
                    if sid in result and jid not in result[sid].predecessors:
                        result[sid].predecessors.append(jid)

        return result


# ПУБЛИЧНЫЙ API

def build_state(dsl_path: str | Path, instance_data: dict) -> (
        tuple)["DSLMeta", "ProblemState"]:
    """
    Шаг 1+2: парсит DSL и строит начальное состояние задачи.
    Возвращает (meta, state) - их можно передавать в solve().

    Args:
        dsl_path: путь к JSON-файлу DSL-описания
        instance_data: словарь с полями "resources" и "jobs"
    """
    parser = DSLParser()
    meta = parser.parse_file(dsl_path)
    factory = ProblemFactory()
    state = factory.build(instance_data, meta)
    return meta, state


def run_schedule(
        state: "ProblemState",
        select_job_fn,  # (eligible_ids, jobs, snapshot, meta) -> int
        allocate_fn,  # (job, resources, snapshot, meta) -> dict[int,int]
        verbose: bool = False,
) -> dict[str, Any]:
    """
    Каркас цикла: запускает планировщик с переданными функциями выбора/выделения.
    Функции select_job_fn и allocate_fn - это то, что будет генерировать LLM.

    Serial Schedule Generation Scheme (SSGS):
      пока есть незапланированные работы:
        eligible -> select_job_fn -> allocate_fn -> start | advance_time
    """
    meta = state.meta
    iteration = 0
    max_iter = 10 * len(state.jobs) + 1000  # защита от зависания

    def log(msg):
        if verbose:
            print(msg)

    log(f"Scheduler: {meta.project_id} | jobs={len(state.jobs)} "
        f"resources={len(state.resources)}")

    while not state.is_done() and iteration < max_iter:
        iteration += 1
        eligible = state.eligible_jobs()

        if not eligible:
            if state.active_jobs:
                state.advance_time()
                log(f"  -> advance_time -> t={state.current_time}")
            else:
                log("  !! Deadlock: no eligible jobs and no active jobs")
                break
            continue

        # LLM выбирает следующую работу
        snap = state.snapshot()
        job_id = select_job_fn(eligible, state.jobs, snap, meta)
        if job_id not in eligible:
            log(f"  !! select_job returned invalid {job_id}, "
                f"fallback to first eligible")
            job_id = eligible[0]

        job = state.jobs[job_id]

        # LLM решает, сколько ресурсов выделить
        allocation = allocate_fn(job, state.resources, snap, meta)

        # feasibility check и запуск
        if state.can_allocate(job, allocation):
            state.start_job(job_id, allocation)
            log(f"  t={state.current_time:4d} | start job {job_id} "
                f"dur={job.duration} alloc={allocation}")

            # Conditional scheduling: selection_groups — это группы альтернатив.
            # Когда работа job_id завершится,
            # из каждой ее группы будет выбран один преемник.
            # При запуске job_id помечаем ее родительскую группу как "выбранную ветвь":
            # находим всех родителей, у которых job_id входит в selection_group,
            # и помечаем остальных членов той группы как skipped.
            if meta.selection_groups_present:
                # Прямая логика: selection_groups текущей работы — это её СОБСТВЕННЫЕ
                # группы выбора преемников (они активируются при завершении работы).
                # При запуске job_id ищем, в какие группы каких родителей он входит,
                # и пропускаем альтернативы в тех же группах.
                for parent_id, parent_job in state.jobs.items():
                    if parent_id not in state.completed_jobs and parent_id != job_id:
                        continue  # только завершённые родители
                    for group in parent_job.selection_groups:
                        if job_id in group:
                            for alt_id in group:
                                if alt_id != job_id and alt_id not in state.schedule and alt_id not in state.skipped_jobs:
                                    state.skipped_jobs.add(alt_id)
                                    log(f"    -> skip job {alt_id} (alt in selection group of {parent_id})")
        else:
            log(f"  t={state.current_time:4d} | job {job_id} blocked — advance_time")
            if state.active_jobs:
                state.advance_time()
            else:
                log("  !! Infeasible: no capacity and no active jobs")
                break

    # Дождаться завершения хвостовых работ
    while state.active_jobs:
        state.advance_time()

    # Считаем метрику
    calc = ObjectiveCalculator()
    objective = calc.compute(state)
    log(f"Done in {iteration} iters | primary={objective.get('primary')}")

    return {
        "schedule": dict(state.schedule),
        "objective": objective,
        "iterations": iteration,
        "final_time": state.current_time,
    }


def solve(
        dsl_path: str | Path,
        instance_data: dict,
        select_job_fn=None,
        allocate_fn=None,
        verbose: bool = False,
) -> dict[str, Any]:
    """
    Высокоуровневая точка входа.

    select_job_fn / allocate_fn — Python-функции (от LLM или заглушки).
    Если не переданы, используются встроенные эвристики по умолчанию.

    Args:
        dsl_path: путь к JSON-файлу DSL-описания
        instance_data: словарь с полями "resources" и "jobs"
        select_job_fn: функция (eligible_ids, jobs, snapshot, meta) -> int
        allocate_fn: функция (job, resources, snapshot, meta) -> dict[int,int]
        verbose: логировать ход решения
    """
    meta, state = build_state(dsl_path, instance_data)

    if verbose:
        parser = DSLParser()
        print(parser.summary(meta))
        print()

    # Встроенные эвристики - заглушки до прихода LLM-кода
    def _default_select(eligible_ids, jobs, snap, meta):
        if meta.is_single_machine:
            return min(eligible_ids, key=lambda jid: jobs[jid].duration)  # SPT
        return max(eligible_ids,
                   key=lambda jid: len(jobs[jid].successors))  # Most successors

    def _default_allocate(job, resources, snap, meta):
        return dict(job.resources_required)  # выделяем ровно то, что требует работа

    return run_schedule(
        state,
        select_job_fn=select_job_fn or _default_select,
        allocate_fn=allocate_fn or _default_allocate,
        verbose=verbose,
    )
