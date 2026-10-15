"""
Каркас планировщика RCPSP с двумя подключаемыми функциями.

LLM (или человек) пишет две функции:

    select_job_fn(eligible_ids, jobs, snapshot, meta) -> int
        выбирает следующую работу из готовых;

    allocate_fn(job, feasible_starts, snapshot, meta) -> int        (scheme="ssgs")
        выбирает время старта из списка допустимых, который построил каркас;

    allocate_fn(job, resources, snapshot, meta) -> dict[int, int]  (scheme="legacy")
        старый контракт: словарь {resource_id: amount}; сохранён только для
        воспроизведения весенних результатов (версия d3dadbc6).

Допустимость расписания обеспечивает каркас, а не сгенерированный код:
ресурсы бронируются по `job.resources_required`, предшествование и
профиль ресурсов проверяются на всём интервале работы. Нарушения контракта
функций и неполное расписание не скрываются: см. поля `status`, `reason`,
`invalid_select_count`, `allocate_violations` результата `run_schedule`.
При `strict=True` любое из них — исключение `SchedulerContractError`.

Независимая проверка готового расписания — `schedule_checker.validate_schedule`;
она не импортирует этот модуль.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCHEME_SSGS = "ssgs"
SCHEME_LEGACY = "legacy"
SCHEMES = (SCHEME_SSGS, SCHEME_LEGACY)

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"

REASON_DEADLOCK = "deadlock"
REASON_INFEASIBLE = "infeasible"
REASON_MAX_ITERATIONS = "max_iterations"

RENEWABLE = "renewable"
NON_RENEWABLE = "non-renewable"
_RESOURCE_TYPE_ALIASES = {
    "renewable": RENEWABLE,
    "global": RENEWABLE,
    "non-renewable": NON_RENEWABLE,
    "nonrenewable": NON_RENEWABLE,
    "non_renewable": NON_RENEWABLE,
}


class InstanceFormatError(ValueError):
    """Инстанс не соответствует ожидаемой схеме: ошибка диагностируется, а не глотается."""


class SchedulerContractError(RuntimeError):
    """Нарушение контракта select_job_fn / allocate_fn (только при strict=True)."""


# =============================================================================
# DSL PARSER
# =============================================================================

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
        problem_type = ps.get("problem_type", project_id)

        ct = ps.get("constraint_types", [])
        if isinstance(ct, dict):
            ct = ct.get("hard", []) + ct.get("soft", [])
        constraint_types: list[str] = list(ct)

        resource_nature = ps.get("resource_nature", "Renewable")
        execution_mode = ps.get("execution_mode", "Single-Mode")
        uncertainty = ps.get("uncertainty", "Deterministic")

        obj = d.get("optimization_objectives", {})
        primary = obj.get("primary", obj)  # Case 2 в старых DSL: без вложенности primary
        primary_metric = primary.get("metric", "Makespan")
        primary_direction = primary.get("direction", "Minimize")

        secondary = obj.get("secondary", {})
        secondary_metric = secondary.get("metric") if secondary else None
        secondary_direction = secondary.get("direction") if secondary else None
        secondary_params = secondary.get("parameters", {}) if secondary else {}

        graph = d.get("graph_meta_characteristics", {})

        cond = d.get("conditional_scheduling", {})
        conditional_scheduling = bool(cond.get("enabled", False))
        selection_groups_present = bool(cond.get("selection_groups_present", False))
        time_precedence_present = bool(cond.get("time_precedence_present", False))

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


# =============================================================================
# МОДЕЛЬ ЗАДАЧИ
# =============================================================================

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
    local_id: int | None = None  # id внутри проекта (Case 5); иначе равен id
    non_renewable_consumption: dict[int, int] = field(default_factory=dict)
    non_renewable_production: dict[int, int] = field(default_factory=dict)
    selection_groups: list[list[int]] = field(default_factory=list)


@dataclass
class Resource:
    id: int
    name: str
    capacity: int
    r_type: str = RENEWABLE  # "renewable" | "non-renewable" (после нормализации)
    initial_stock: int = 0


def multi_project_job_id(project_id: int, local_id: int, id_base: int) -> int:
    """Глобальный id работы в многопроектной задаче: project_id * id_base + local_id.

    id_base — степень десяти, большая любого локального id (для Case 5: 100).
    То же правило продублировано в schedule_checker (он не импортирует каркас).
    """
    return project_id * id_base + local_id


def multi_project_id_base(max_local_id: int) -> int:
    return 10 ** len(str(max(max_local_id, 1)))


@dataclass
class ProblemState:
    jobs: dict[int, Job]
    resources: dict[int, Resource]
    meta: DSLMeta

    # Общее состояние (обе схемы)
    schedule: dict[int, int] = field(default_factory=dict)  # job_id -> start_time
    skipped_jobs: set[int] = field(default_factory=set)  # conditional: не выбраны
    non_renewable_stock: dict[int, int] = field(default_factory=dict)
    # Профиль загрузки возобновляемых ресурсов: resource_id -> {t: used}
    profile: dict[int, dict[int, int]] = field(default_factory=dict)

    # Состояние пошаговой схемы (legacy)
    current_time: int = 0
    active_jobs: dict[int, int] = field(default_factory=dict)  # job_id -> finish_time
    completed_jobs: set[int] = field(default_factory=set)
    renewable_used: dict[int, int] = field(default_factory=dict)
    allocations: dict[int, dict[int, int]] = field(default_factory=dict)

    def __post_init__(self):
        for r in self.resources.values():
            if r.r_type == RENEWABLE:
                self.renewable_used[r.id] = 0
                self.profile[r.id] = {}
            else:
                self.non_renewable_stock[r.id] = r.initial_stock

    # --- общие запросы ---------------------------------------------------------

    def renewable_ids(self) -> list[int]:
        return [r.id for r in self.resources.values() if r.r_type == RENEWABLE]

    def finish_time(self, job_id: int) -> int:
        return self.schedule[job_id] + self.jobs[job_id].duration

    def unscheduled_jobs(self) -> list[int]:
        return [jid for jid in self.jobs
                if jid not in self.schedule and jid not in self.skipped_jobs]

    def is_eligible(self, job_id: int, scheme: str = SCHEME_SSGS) -> bool:
        """SSGS: все предшественники запланированы. Legacy: все завершены."""
        if job_id in self.schedule or job_id in self.skipped_jobs:
            return False
        done = self.schedule if scheme == SCHEME_SSGS else self.completed_jobs
        return all(p in done for p in self.jobs[job_id].predecessors)

    def eligible_jobs(self, scheme: str = SCHEME_SSGS) -> list[int]:
        return [jid for jid in self.jobs if self.is_eligible(jid, scheme)]

    def is_done(self) -> bool:
        return not self.unscheduled_jobs() and not self.active_jobs

    def horizon(self) -> int:
        return max((self.finish_time(j) for j in self.schedule), default=0)

    def nrr_feasible(self, job: Job) -> bool:
        return all(self.non_renewable_stock.get(rid, 0) >= cons
                   for rid, cons in job.non_renewable_consumption.items())

    def _consume_non_renewable(self, job: Job):
        for rid, cons in job.non_renewable_consumption.items():
            self.non_renewable_stock[rid] -= cons
        for rid, prod in job.non_renewable_production.items():
            self.non_renewable_stock[rid] = self.non_renewable_stock.get(rid, 0) + prod

    def _apply_selection_groups(self, job_id: int, log: Callable[[str], None]):
        """Запуск job_id выбирает ветвь: альтернативы из тех же групп выбора
        запланированных родителей помечаются как skipped."""
        if not self.meta.selection_groups_present:
            return
        for parent_id, parent in self.jobs.items():
            if parent_id not in self.schedule:
                continue
            for group in parent.selection_groups:
                if job_id not in group:
                    continue
                for alt in group:
                    if alt != job_id and alt not in self.schedule and alt not in self.skipped_jobs:
                        self.skipped_jobs.add(alt)
                        log(f"    -> skip job {alt} (alternative of {job_id} in group of {parent_id})")

    # --- SSGS: профиль ресурсов ------------------------------------------------

    def usage_at(self, resource_id: int, t: int) -> int:
        return self.profile[resource_id].get(t, 0)

    def fits_at(self, job: Job, start: int) -> bool:
        for rid, amount in job.resources_required.items():
            cap = self.resources[rid].capacity
            prof = self.profile[rid]
            for t in range(start, start + job.duration):
                if prof.get(t, 0) + amount > cap:
                    return False
        return True

    def earliest_precedence_start(self, job: Job) -> int:
        return max((self.finish_time(p) for p in job.predecessors), default=0)

    def feasible_starts(self, job: Job, limit: int = 10) -> list[int]:
        """Допустимые времена старта: по предшествованию и профилю ресурсов на
        всём интервале [t, t + d). Кандидаты — самое раннее время и моменты
        окончания уже запланированных работ; возвращаются первые `limit`
        подходящих. Пусто только если потребность превышает мощность."""
        for rid, amount in job.resources_required.items():
            if amount > self.resources[rid].capacity:
                return []
        es = self.earliest_precedence_start(job)
        if job.duration == 0:
            return [es]  # фиктивной работе нечего ждать
        candidates = sorted({es} | {self.finish_time(j) for j in self.schedule
                                    if self.finish_time(j) > es})
        starts = [t for t in candidates if self.fits_at(job, t)]
        if not starts:  # после окончания всех работ ресурсы свободны
            starts = [max(candidates)]
        return starts[:limit]

    def place_job(self, job_id: int, start: int, log: Callable[[str], None] = lambda m: None):
        job = self.jobs[job_id]
        self.schedule[job_id] = start
        for rid, amount in job.resources_required.items():
            prof = self.profile[rid]
            for t in range(start, start + job.duration):
                prof[t] = prof.get(t, 0) + amount
        self._consume_non_renewable(job)
        self._apply_selection_groups(job_id, log)

    # --- Legacy: пошаговая схема ------------------------------------------------

    def available_capacity(self, resource_id: int) -> int:
        r = self.resources[resource_id]
        return r.capacity - self.renewable_used.get(resource_id, 0)

    def can_allocate(self, job: Job, allocation: dict[int, int]) -> bool:
        """Выделение покрывает потребность, ссылается только на известные
        возобновляемые ресурсы, укладывается в мощности; запаса невозобновляемых
        хватает."""
        for rid, amount in allocation.items():
            if rid not in self.renewable_used or amount < 0:
                return False
            if amount > self.available_capacity(rid):
                return False
        for rid, need in job.resources_required.items():
            if allocation.get(rid, 0) < need:
                return False
        return self.nrr_feasible(job)

    def effective_allocation(self, job: Job, allocation: Any) -> tuple[dict[int, int], bool]:
        """Нормализует вывод allocate_fn: бронируется не меньше требуемого и только
        по известным ресурсам. Возвращает (выделение, было_ли_нарушение)."""
        violated = False
        effective = dict(job.resources_required)
        if not isinstance(allocation, dict):
            return effective, True
        def is_amount(x: Any) -> bool:
            return isinstance(x, int) and not isinstance(x, bool) and x >= 0

        for rid, amount in allocation.items():
            if rid not in self.renewable_used or not is_amount(amount):
                violated = True
                continue
            if amount > effective.get(rid, 0):
                effective[rid] = amount
        for rid, need in job.resources_required.items():
            given = allocation.get(rid)
            if not is_amount(given) or given < need:
                violated = True
        return effective, violated

    def start_job(self, job_id: int, allocation: dict[int, int]):
        job = self.jobs[job_id]
        effective, _ = self.effective_allocation(job, allocation)
        self.allocations[job_id] = effective
        self.active_jobs[job_id] = self.current_time + job.duration
        for rid, amount in effective.items():
            self.renewable_used[rid] = self.renewable_used.get(rid, 0) + amount
        self.place_job(job_id, self.current_time)

    def finish_jobs_at(self, time: int):
        """Завершает активные работы с окончанием не позже time; освобождает
        ровно то, что было забронировано при старте."""
        done = [jid for jid, ft in self.active_jobs.items() if ft <= time]
        for jid in done:
            for rid, amount in self.allocations.pop(jid, {}).items():
                self.renewable_used[rid] -= amount
            self.completed_jobs.add(jid)
            del self.active_jobs[jid]

    def advance_time(self):
        if self.active_jobs:
            next_finish = min(self.active_jobs.values())
            self.current_time = next_finish
            self.finish_jobs_at(next_finish)

    # --- снапшот для функций LLM ------------------------------------------------

    def snapshot(self, scheme: str = SCHEME_SSGS, eligible: list[int] | None = None) -> dict:
        base = {
            "scheme": scheme,
            "scheduled_jobs": list(self.schedule),
            "start_times": dict(self.schedule),
            "finish_times": {j: self.finish_time(j) for j in self.schedule},
            "eligible_jobs": list(eligible) if eligible is not None else self.eligible_jobs(scheme),
            "non_renewable_stock": dict(self.non_renewable_stock),
            "skipped_jobs": list(self.skipped_jobs),
            "capacity": {rid: self.resources[rid].capacity for rid in self.renewable_ids()},
        }
        if scheme == SCHEME_LEGACY:
            base.update({
                "current_time": self.current_time,
                "completed_jobs": list(self.completed_jobs),
                "active_jobs": dict(self.active_jobs),
                "renewable_used": dict(self.renewable_used),
            })
        else:
            base["current_time"] = self.horizon()
        return base


# =============================================================================
# РАСЧЁТ ЦЕЛИ
# =============================================================================

class ObjectiveCalculator:
    """Считает цель по расписанию в state. Вызывать только для полного расписания:
    по частичному значения занижены (run_schedule в этом случае отдаёт primary=None)."""

    @staticmethod
    def compute(state: ProblemState) -> dict[str, Any]:
        meta = state.meta
        result: dict[str, Any] = {}
        finish = {jid: state.finish_time(jid) for jid in state.schedule}

        if "Total Makespan" in meta.primary_metric or meta.is_multi_project:
            project_makespans: dict[int, int] = {}
            for jid, ft in finish.items():
                pid = state.jobs[jid].project_id
                project_makespans[pid] = max(project_makespans.get(pid, 0), ft)
            total = sum(project_makespans.values())
            result["project_makespans"] = project_makespans
            result["project_finish_times"] = dict(project_makespans)
            result["total_makespan"] = total  # сумма makespan проектов (README)
            result["portfolio_makespan"] = max(project_makespans.values(), default=0)
            result["primary"] = total

        elif meta.primary_metric == "Makespan":
            makespan = max(finish.values(), default=0)
            result["makespan"] = makespan
            result["primary"] = makespan

        elif "Earliness" in meta.primary_metric or "Tardiness" in meta.primary_metric:
            due_date = meta.secondary_params.get("due_date", 0)
            total_penalty = 0
            details: dict[int, dict] = {}
            for jid, ft in finish.items():
                job = state.jobs[jid]
                if ft < due_date:
                    penalty = (due_date - ft) * job.earliness_penalty
                    details[jid] = {"type": "early", "amount": due_date - ft, "penalty": penalty}
                elif ft > due_date:
                    penalty = (ft - due_date) * job.tardiness_penalty
                    details[jid] = {"type": "late", "amount": ft - due_date, "penalty": penalty}
                else:
                    penalty = 0
                    details[jid] = {"type": "on_time", "amount": 0, "penalty": 0}
                total_penalty += penalty
            result["total_et_penalty"] = total_penalty
            result["due_date"] = due_date
            result["job_details"] = details
            result["primary"] = total_penalty

        else:
            result["primary"] = None
            result["warning"] = f"Unknown primary metric: {meta.primary_metric}"

        # Невозобновляемые ресурсы: расход и бюджет (Case 3)
        nrr = [r for r in state.resources.values() if r.r_type == NON_RENEWABLE]
        if nrr:
            budgets = meta.secondary_params.get("budget_limit", {}) or {}
            nrr_used: dict[str, int] = {}
            violations: dict[str, dict] = {}
            for r in nrr:
                used = r.initial_stock - state.non_renewable_stock.get(r.id, r.initial_stock)
                nrr_used[r.name] = used
                limit = budgets.get(r.name, budgets.get(str(r.id), budgets.get(r.id, r.initial_stock)))
                if used > limit:
                    violations[r.name] = {"used": used, "limit": limit, "excess": used - limit}
            result["non_renewable_used"] = nrr_used
            result["budget_violations"] = violations
            result["budget_feasible"] = not violations

        return result


# =============================================================================
# ФОРМИРОВАНИЕ СОСТОЯНИЯ ИЗ ДАННЫХ
# =============================================================================

class ProblemFactory:
    """
    Преобразует сырые данные (dict) + DSLMeta в ProblemState.
    Любое расхождение со схемой — InstanceFormatError с указанием места.
    Поддерживаемые формы потребности в ресурсах:
      {"resources_required": {"1": 4}}                              (Cases 2–4)
      {"resource_requirements": [{"resource_id": 1, "amount": 4}]}  (Case 1, PSPLIB)
      {"resources_required": [4, 3, 0, 0, 0, 0]}                    (Case 5, по порядку ресурсов)
    """

    def build(self, raw_data: dict, meta: DSLMeta) -> ProblemState:
        if not isinstance(raw_data, dict):
            raise InstanceFormatError("instance must be a dict with 'resources' and 'jobs'")
        resources = self._parse_resources(raw_data.get("resources", []))
        if meta.is_multi_project:
            jobs = self._parse_multi_project(raw_data.get("jobs", []), resources)
        else:
            jobs = self._parse_jobs(raw_data.get("jobs", []), resources)
        self._link_precedence(jobs)
        return ProblemState(jobs=jobs, resources=resources, meta=meta)

    # --- ресурсы ---

    @staticmethod
    def _parse_resources(raw: list[dict]) -> dict[int, Resource]:
        result: dict[int, Resource] = {}
        for r in raw:
            if "id" not in r:
                raise InstanceFormatError(f"resource without id: {r}")
            rid = int(r["id"])
            if rid in result:
                raise InstanceFormatError(f"duplicate resource id {rid}")
            raw_type = str(r.get("type", RENEWABLE)).strip().lower()
            if raw_type not in _RESOURCE_TYPE_ALIASES:
                raise InstanceFormatError(
                    f"unknown resource type {r.get('type')!r} for resource {rid}; "
                    f"expected one of {sorted(_RESOURCE_TYPE_ALIASES)}")
            r_type = _RESOURCE_TYPE_ALIASES[raw_type]
            if r_type == RENEWABLE:
                if "capacity" not in r:
                    raise InstanceFormatError(f"renewable resource {rid} has no capacity")
                capacity = int(r["capacity"])
                initial_stock = 0
            else:
                if "initial_stock" not in r and "capacity" not in r:
                    raise InstanceFormatError(
                        f"non-renewable resource {rid} has neither initial_stock nor capacity")
                initial_stock = int(r.get("initial_stock", r.get("capacity")))
                capacity = initial_stock
            result[rid] = Resource(id=rid, name=str(r.get("name", rid)), capacity=capacity,
                                   r_type=r_type, initial_stock=initial_stock)
        return result

    @staticmethod
    def _parse_requirements(rr: Any, resources: dict[int, Resource], where: str) -> dict[int, int]:
        renewable_ids = [r.id for r in resources.values() if r.r_type == RENEWABLE]
        pairs: list[tuple[int, Any]] = []
        if rr is None:
            return {}
        if isinstance(rr, dict):
            pairs = [(int(k), v) for k, v in rr.items()]
        elif isinstance(rr, list):
            if rr and all(isinstance(x, dict) for x in rr):
                for x in rr:
                    if "resource_id" not in x or "amount" not in x:
                        raise InstanceFormatError(f"{where}: requirement entry {x} needs resource_id and amount")
                    pairs.append((int(x["resource_id"]), x["amount"]))
            elif all(isinstance(x, (int, float)) for x in rr):
                if len(rr) > len(renewable_ids):
                    raise InstanceFormatError(
                        f"{where}: {len(rr)} requirement values for {len(renewable_ids)} renewable resources")
                pairs = list(zip(renewable_ids, rr))
            else:
                raise InstanceFormatError(f"{where}: unsupported requirement list {rr!r}")
        else:
            raise InstanceFormatError(f"{where}: unsupported requirement value {rr!r}")

        result: dict[int, int] = {}
        for rid, amount in pairs:
            if rid not in resources:
                raise InstanceFormatError(f"{where}: requirement refers to unknown resource {rid}")
            if resources[rid].r_type != RENEWABLE:
                raise InstanceFormatError(
                    f"{where}: resources_required refers to non-renewable resource {rid}; "
                    f"use resource_consumption")
            if not isinstance(amount, (int, float)) or amount < 0 or int(amount) != amount:
                raise InstanceFormatError(f"{where}: invalid amount {amount!r} for resource {rid}")
            if amount > 0:
                result[rid] = int(amount)
        return result

    @staticmethod
    def _parse_consumption(raw: Any, resources: dict[int, Resource], where: str
                           ) -> tuple[dict[int, int], dict[int, int]]:
        cons: dict[int, int] = {}
        prod: dict[int, int] = {}
        if not raw:
            return cons, prod
        if not isinstance(raw, dict):
            raise InstanceFormatError(f"{where}: resource_consumption must be a dict")
        for rid_str, info in raw.items():
            rid = int(rid_str)
            if rid not in resources:
                raise InstanceFormatError(f"{where}: resource_consumption refers to unknown resource {rid}")
            if resources[rid].r_type != NON_RENEWABLE:
                raise InstanceFormatError(f"{where}: resource_consumption refers to renewable resource {rid}")
            if isinstance(info, dict):
                c, p = int(info.get("consumption", 0)), int(info.get("production", 0))
            else:
                c, p = int(info), 0
            if c < 0 or p < 0:
                raise InstanceFormatError(f"{where}: negative consumption/production for resource {rid}")
            if c:
                cons[rid] = c
            if p:
                prod[rid] = p
        return cons, prod

    @staticmethod
    def _duration(j: dict, where: str) -> int:
        dur = j.get("duration")
        if dur is None and "modes" in j:
            dur = j["modes"][0].get("duration", 0)
        if dur is None:
            raise InstanceFormatError(f"{where}: duration is missing")
        if not isinstance(dur, (int, float)) or dur < 0 or int(dur) != dur:
            raise InstanceFormatError(f"{where}: invalid duration {dur!r}")
        return int(dur)

    # --- работы: стандартный формат ---

    def _parse_jobs(self, raw: list[dict], resources: dict[int, Resource]) -> dict[int, Job]:
        result: dict[int, Job] = {}
        for j in raw:
            if "id" not in j:
                raise InstanceFormatError(f"job without id: {j}")
            jid = int(j["id"])
            where = f"job {jid}"
            if jid in result:
                raise InstanceFormatError(f"duplicate job id {jid}")

            rr = j.get("resources_required", j.get("resource_requirements"))
            if rr is None and "modes" in j:
                rr = j["modes"][0].get("resources_required", {})
            requirements = self._parse_requirements(rr, resources, where)
            cons, prod = self._parse_consumption(j.get("resource_consumption"), resources, where)

            pen = j.get("penalties", {}) or {}
            preds = [int(p) for p in j.get("predecessors", [])]
            succs = [int(s) for s in j.get("successors", [])]
            sel_groups: list[list[int]] = []
            prec = j.get("precedences")
            if isinstance(prec, dict):
                succs = sorted(set(succs) | {int(s) for s in prec.get("time_successors", [])})
                sel_groups = [[int(x) for x in g] for g in prec.get("selection_groups", [])]

            result[jid] = Job(
                id=jid,
                local_id=jid,
                duration=self._duration(j, where),
                predecessors=preds,
                successors=succs,
                resources_required=requirements,
                earliness_penalty=int(pen.get("earliness_unit_penalty", 0)),
                tardiness_penalty=int(pen.get("tardiness_unit_penalty", 0)),
                non_renewable_consumption=cons,
                non_renewable_production=prod,
                selection_groups=sel_groups,
            )
        return result

    # --- работы: многопроектный формат (Case 5) ---

    def _parse_multi_project(self, raw: list[dict], resources: dict[int, Resource]) -> dict[int, Job]:
        projects: list[tuple[int, list[dict]]] = []
        max_local = 0
        for proj in raw:
            if "project_id" not in proj or "activities" not in proj:
                raise InstanceFormatError(f"multi-project entry needs project_id and activities: {proj}")
            pid = int(proj["project_id"])
            acts = proj["activities"]
            for act in acts:
                if "id" not in act:
                    raise InstanceFormatError(f"project {pid}: activity without id: {act}")
                max_local = max(max_local, int(act["id"]))
            projects.append((pid, acts))
        base = multi_project_id_base(max_local)

        result: dict[int, Job] = {}
        for pid, acts in projects:
            for act in acts:
                lid = int(act["id"])
                gid = multi_project_job_id(pid, lid, base)
                where = f"project {pid} activity {lid}"
                if gid in result:
                    raise InstanceFormatError(f"{where}: duplicate activity id in project")
                requirements = self._parse_requirements(act.get("resources_required", []), resources, where)
                succs = [multi_project_job_id(pid, int(s), base) for s in act.get("successors", [])]
                preds = [multi_project_job_id(pid, int(p), base) for p in act.get("predecessors", [])]
                result[gid] = Job(
                    id=gid,
                    local_id=lid,
                    project_id=pid,
                    duration=self._duration(act, where),
                    predecessors=preds,
                    successors=succs,
                    resources_required=requirements,
                )
        return result

    # --- предшествование ---

    @staticmethod
    def _link_precedence(jobs: dict[int, Job]):
        """Предшественники и преемники согласуются в обе стороны; ссылка на
        неизвестную работу — ошибка."""
        for job in jobs.values():
            for p in job.predecessors:
                if p not in jobs:
                    raise InstanceFormatError(f"job {job.id}: predecessor refers to unknown job {p}")
            for s in job.successors:
                if s not in jobs:
                    raise InstanceFormatError(f"job {job.id}: successor refers to unknown job {s}")
            for group in job.selection_groups:
                for alt in group:
                    if alt not in jobs:
                        raise InstanceFormatError(f"job {job.id}: selection group refers to unknown job {alt}")
        for job in jobs.values():
            for s in job.successors:
                if job.id not in jobs[s].predecessors:
                    jobs[s].predecessors.append(job.id)
        for job in jobs.values():
            for p in job.predecessors:
                if job.id not in jobs[p].successors:
                    jobs[p].successors.append(job.id)


# =============================================================================
# ПУБЛИЧНЫЙ API
# =============================================================================

def build_state(dsl_path: str | Path, instance_data: dict) -> tuple[DSLMeta, ProblemState]:
    """Шаг 1+2: парсит DSL и строит начальное состояние задачи."""
    meta = DSLParser().parse_file(dsl_path)
    state = ProblemFactory().build(instance_data, meta)
    return meta, state


def default_select(eligible_ids, jobs, snap, meta):
    """Встроенное правило: SPT для одной машины, иначе Most Successors."""
    if meta.is_single_machine:
        return min(eligible_ids, key=lambda jid: jobs[jid].duration)
    return max(eligible_ids, key=lambda jid: len(jobs[jid].successors))


def default_allocate(job, feasible_starts, snap, meta):
    """Встроенное правило SSGS: самое раннее допустимое время старта."""
    return feasible_starts[0]


def default_allocate_legacy(job, resources, snap, meta):
    """Встроенное правило legacy: ровно требуемые ресурсы."""
    return dict(job.resources_required)


def run_schedule(
        state: ProblemState,
        select_job_fn: Callable,
        allocate_fn: Callable | None = None,
        verbose: bool = False,
        scheme: str = SCHEME_SSGS,
        strict: bool = False,
        max_feasible_starts: int = 10,
) -> dict[str, Any]:
    """
    Строит расписание функциями select_job_fn / allocate_fn.

    scheme="ssgs" (по умолчанию): готовы работы, у которых все предшественники
      запланированы; выбранная работа ставится в одно из допустимых времён старта
      (по предшествованию и профилю ресурсов на всём интервале), включая вставку
      раньше уже запланированных работ. allocate_fn выбирает время из
      feasible_starts; иначе берётся самое раннее и считается нарушение.
    scheme="legacy": пошаговая схема версии d3dadbc6 (старт только в текущий
      момент, готовность по завершённым предшественникам). Ресурсы бронируются
      по resources_required; вывод allocate_fn не может их уменьшить.

    Результат: schedule, objective (primary=None, если расписание неполное),
    status complete|incomplete, reason, detail, unscheduled, skipped,
    invalid_select_count, allocate_violations, iterations, final_time, scheme.
    strict=True: нарушение контракта или неполное расписание — SchedulerContractError.
    """
    if scheme not in SCHEMES:
        raise ValueError(f"unknown scheme {scheme!r}; expected one of {SCHEMES}")
    if allocate_fn is None:
        allocate_fn = default_allocate if scheme == SCHEME_SSGS else default_allocate_legacy

    meta = state.meta
    iteration = 0
    max_iter = 10 * len(state.jobs) + 1000
    invalid_select = 0
    allocate_violations = 0
    reason: str | None = None
    detail: str | None = None

    def log(msg: str):
        if verbose:
            print(msg)

    def fail(msg: str):
        if strict:
            raise SchedulerContractError(msg)
        log(f"  !! {msg}")

    def pick(eligible: list[int]) -> tuple[int, dict]:
        nonlocal invalid_select
        snap = state.snapshot(scheme, eligible)
        job_id = select_job_fn(list(eligible), state.jobs, snap, meta)
        if job_id not in eligible:
            invalid_select += 1
            fail(f"select_job_fn returned {job_id!r}, not in eligible {eligible}; using {eligible[0]}")
            job_id = eligible[0]
        return job_id, snap

    log(f"Scheduler[{scheme}]: {meta.project_id} | jobs={len(state.jobs)} "
        f"resources={len(state.resources)}")

    if scheme == SCHEME_SSGS:
        while state.unscheduled_jobs():
            iteration += 1
            if iteration > max_iter:
                reason, detail = REASON_MAX_ITERATIONS, f"more than {max_iter} iterations"
                break
            eligible = state.eligible_jobs(SCHEME_SSGS)
            if not eligible:
                reason = REASON_DEADLOCK
                detail = f"no eligible jobs; unscheduled={state.unscheduled_jobs()}"
                break
            job_id, snap = pick(eligible)
            job = state.jobs[job_id]
            if not state.nrr_feasible(job):
                reason = REASON_INFEASIBLE
                detail = (f"job {job_id} needs {job.non_renewable_consumption}, "
                          f"stock {state.non_renewable_stock}")
                break
            starts = state.feasible_starts(job, limit=max_feasible_starts)
            if not starts:
                reason = REASON_INFEASIBLE
                detail = f"job {job_id} requires {job.resources_required}, more than capacity"
                break
            chosen = allocate_fn(job, list(starts), snap, meta)
            if chosen not in starts:
                allocate_violations += 1
                fail(f"allocate_fn returned {chosen!r}, not in feasible_starts {starts}; using {starts[0]}")
                chosen = starts[0]
            state.place_job(job_id, chosen, log)
            log(f"  job {job_id:4d} start={chosen:4d} dur={job.duration} req={job.resources_required}")

    else:  # legacy
        while not state.is_done():
            iteration += 1
            if iteration > max_iter:
                reason, detail = REASON_MAX_ITERATIONS, f"more than {max_iter} iterations"
                break
            eligible = state.eligible_jobs(SCHEME_LEGACY)
            if not eligible:
                if state.active_jobs:
                    state.advance_time()
                    log(f"  -> advance_time -> t={state.current_time}")
                    continue
                reason = REASON_DEADLOCK
                detail = f"no eligible and no active jobs; unscheduled={state.unscheduled_jobs()}"
                break
            job_id, snap = pick(eligible)
            job = state.jobs[job_id]
            allocation = allocate_fn(job, state.resources, snap, meta)
            effective, violated = state.effective_allocation(job, allocation)
            if violated:
                allocate_violations += 1
                fail(f"allocate_fn returned {allocation!r} for job {job_id} "
                     f"(required {job.resources_required}); booking {effective}")
            if state.can_allocate(job, effective):
                state.start_job(job_id, effective)
                log(f"  t={state.current_time:4d} | start job {job_id} dur={job.duration} alloc={effective}")
            elif state.active_jobs:
                log(f"  t={state.current_time:4d} | job {job_id} blocked -> advance_time")
                state.advance_time()
            else:
                reason = REASON_INFEASIBLE
                detail = (f"job {job_id} cannot start at t={state.current_time}: "
                          f"alloc={effective}, stock={state.non_renewable_stock}")
                break
        while state.active_jobs:
            state.advance_time()

    unscheduled = state.unscheduled_jobs()
    status = STATUS_COMPLETE if not unscheduled and reason is None else STATUS_INCOMPLETE
    if status == STATUS_INCOMPLETE and reason is None:
        reason = REASON_DEADLOCK
    if status == STATUS_COMPLETE:
        objective = ObjectiveCalculator.compute(state)
    else:
        objective = {"primary": None, "status": STATUS_INCOMPLETE, "reason": reason}
        if strict:
            raise SchedulerContractError(f"incomplete schedule: {reason}: {detail}")

    log(f"Done in {iteration} iters | status={status} | primary={objective.get('primary')}")
    return {
        "schedule": dict(state.schedule),
        "objective": objective,
        "status": status,
        "reason": reason,
        "detail": detail,
        "unscheduled": unscheduled,
        "skipped": sorted(state.skipped_jobs),
        "invalid_select_count": invalid_select,
        "allocate_violations": allocate_violations,
        "iterations": iteration,
        "final_time": state.horizon(),
        "scheme": scheme,
    }


def solve(
        dsl_path: str | Path,
        instance_data: dict,
        select_job_fn: Callable | None = None,
        allocate_fn: Callable | None = None,
        verbose: bool = False,
        scheme: str = SCHEME_SSGS,
        strict: bool = False,
) -> dict[str, Any]:
    """build_state + run_schedule. Без функций используются встроенные правила."""
    meta, state = build_state(dsl_path, instance_data)
    if verbose:
        print(DSLParser.summary(meta))
        print()
    return run_schedule(
        state,
        select_job_fn=select_job_fn or default_select,
        allocate_fn=allocate_fn,
        verbose=verbose,
        scheme=scheme,
        strict=strict,
    )
