"""
Независимый чекер расписаний.

validate_schedule(instance, schedule) проверяет расписание по исходным данным
инстанса и пересчитывает цель сам. Модуль не импортирует каркас
(scheduler_skeleton) и ничего не знает о том, кто построил расписание:
один чекер для Text, DSL, Skeleton и встроенных правил.

Вход:
  instance — словарь инстанса из data/processed/*.json (resources + jobs);
  schedule — {job_key: start_time}. Для многопроектной задачи ключ —
             глобальный id (project_id * base + local_id, base = 10^len(max id)),
             кортеж (project_id, local_id) или строка "project_id:local_id".
Выход — словарь:
  status      valid | invalid | incomplete | empty
  feasible    status == "valid"
  violations  список {type, ...}: unknown_job, invalid_start, missing_job,
              precedence, renewable_capacity, non_renewable_budget, selection_group
  makespan    пересчитанный по данным (None, если расписание не valid)
  scheduled, total, skipped
  objective   primary + детали (makespan / total_makespan / total_et_penalty / NRR)

`valid` не означает `optimal`.
"""
from __future__ import annotations

from typing import Any

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_INCOMPLETE = "incomplete"
STATUS_EMPTY = "empty"

_RENEWABLE_TYPES = {"renewable", "global"}
_NON_RENEWABLE_TYPES = {"non-renewable", "nonrenewable", "non_renewable"}


class InstanceError(ValueError):
    """Инстанс нельзя разобрать: сообщение называет поле."""


# Разбор инстанса (своя реализация, без каркаса)

def _multi_project_id_base(max_local_id: int) -> int:
    return 10 ** len(str(max(max_local_id, 1)))


def _requirements(raw: Any, renewable_ids: list[int], where: str) -> dict[int, int]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        pairs = [(int(k), v) for k, v in raw.items()]
    elif isinstance(raw, list):
        if raw and all(isinstance(x, dict) for x in raw):
            pairs = [(int(x["resource_id"]), x["amount"]) for x in raw]
        elif all(isinstance(x, (int, float)) for x in raw):
            pairs = list(zip(renewable_ids, raw))
        else:
            raise InstanceError(f"{where}: unsupported requirement list {raw!r}")
    else:
        raise InstanceError(f"{where}: unsupported requirement value {raw!r}")
    result: dict[int, int] = {}
    for rid, amount in pairs:
        if rid not in renewable_ids:
            raise InstanceError(f"{where}: requirement refers to unknown renewable resource {rid}")
        amount = int(amount)
        if amount < 0:
            raise InstanceError(f"{where}: negative requirement for resource {rid}")
        if amount:
            result[rid] = amount
    return result


def parse_instance(instance: dict) -> dict[str, Any]:
    """Возвращает {resources, jobs, multi_project, id_base, due_date}.

    jobs: {gid: {id, project_id, local_id, duration, preds, succs, req, cons, prod,
                 ep, tp, groups}}
    """
    if not isinstance(instance, dict):
        raise InstanceError("instance must be a dict")
    resources: dict[int, dict] = {}
    for r in instance.get("resources", []):
        rid = int(r["id"])
        rtype = str(r.get("type", "renewable")).strip().lower()
        if rtype in _RENEWABLE_TYPES:
            resources[rid] = {"id": rid, "name": str(r.get("name", rid)), "renewable": True,
                              "capacity": int(r["capacity"]), "stock": 0}
        elif rtype in _NON_RENEWABLE_TYPES:
            stock = int(r.get("initial_stock", r.get("capacity", 0)))
            resources[rid] = {"id": rid, "name": str(r.get("name", rid)), "renewable": False,
                              "capacity": 0, "stock": stock}
        else:
            raise InstanceError(f"unknown resource type {r.get('type')!r} for resource {rid}")
    renewable_ids = [rid for rid, r in resources.items() if r["renewable"]]

    raw_jobs = instance.get("jobs", [])
    multi = bool(raw_jobs) and isinstance(raw_jobs[0], dict) and "activities" in raw_jobs[0]
    jobs: dict[int, dict] = {}
    id_base = 1

    if multi:
        max_local = max((int(a["id"]) for p in raw_jobs for a in p.get("activities", [])), default=1)
        id_base = _multi_project_id_base(max_local)
        for proj in raw_jobs:
            pid = int(proj["project_id"])
            for act in proj.get("activities", []):
                lid = int(act["id"])
                gid = pid * id_base + lid
                where = f"project {pid} activity {lid}"
                if gid in jobs:
                    raise InstanceError(f"{where}: duplicate id")
                jobs[gid] = {
                    "id": gid, "project_id": pid, "local_id": lid,
                    "duration": int(act.get("duration", 0)),
                    "preds": [pid * id_base + int(p) for p in act.get("predecessors", [])],
                    "succs": [pid * id_base + int(s) for s in act.get("successors", [])],
                    "req": _requirements(act.get("resources_required", []), renewable_ids, where),
                    "cons": {}, "prod": {}, "ep": 0, "tp": 0, "groups": [],
                }
    else:
        for j in raw_jobs:
            jid = int(j["id"])
            where = f"job {jid}"
            if jid in jobs:
                raise InstanceError(f"{where}: duplicate id")
            rr = j.get("resources_required", j.get("resource_requirements"))
            if rr is None and "modes" in j:
                rr = j["modes"][0].get("resources_required", {})
            dur = j.get("duration")
            if dur is None and "modes" in j:
                dur = j["modes"][0].get("duration", 0)
            succs = [int(s) for s in j.get("successors", [])]
            groups: list[list[int]] = []
            prec = j.get("precedences")
            if isinstance(prec, dict):
                succs = sorted(set(succs) | {int(s) for s in prec.get("time_successors", [])})
                groups = [[int(x) for x in g] for g in prec.get("selection_groups", [])]
            cons: dict[int, int] = {}
            prod: dict[int, int] = {}
            for rid_str, info in (j.get("resource_consumption") or {}).items():
                rid = int(rid_str)
                if rid not in resources or resources[rid]["renewable"]:
                    raise InstanceError(f"{where}: resource_consumption refers to non-NRR resource {rid}")
                c = int(info.get("consumption", 0)) if isinstance(info, dict) else int(info)
                p = int(info.get("production", 0)) if isinstance(info, dict) else 0
                if c:
                    cons[rid] = c
                if p:
                    prod[rid] = p
            pen = j.get("penalties") or {}
            jobs[jid] = {
                "id": jid, "project_id": None, "local_id": jid,
                "duration": int(dur or 0),
                "preds": [int(p) for p in j.get("predecessors", [])],
                "succs": succs,
                "req": _requirements(rr, renewable_ids, where),
                "cons": cons, "prod": prod,
                "ep": int(pen.get("earliness_unit_penalty", 0)),
                "tp": int(pen.get("tardiness_unit_penalty", 0)),
                "groups": groups,
            }

    for job in jobs.values():
        for x in job["preds"] + job["succs"] + [a for g in job["groups"] for a in g]:
            if x not in jobs:
                raise InstanceError(f"job {job['id']}: refers to unknown job {x}")
    for job in jobs.values():
        for s in job["succs"]:
            if job["id"] not in jobs[s]["preds"]:
                jobs[s]["preds"].append(job["id"])
    for job in jobs.values():
        for p in job["preds"]:
            if job["id"] not in jobs[p]["succs"]:
                jobs[p]["succs"].append(job["id"])

    due_date = (instance.get("parameters") or {}).get("common_due_date")
    return {"resources": resources, "jobs": jobs, "multi_project": multi,
            "id_base": id_base, "due_date": due_date}


# Нормализация ключей расписания

def _normalize_key(key: Any, parsed: dict) -> int | None:
    jobs = parsed["jobs"]
    base = parsed["id_base"]
    if isinstance(key, bool):
        return None
    if isinstance(key, tuple) and len(key) == 2:
        try:
            gid = int(key[0]) * base + int(key[1])
        except (TypeError, ValueError):
            return None
        return gid if gid in jobs else None
    if isinstance(key, str):
        if ":" in key and parsed["multi_project"]:
            pid, _, lid = key.partition(":")
            try:
                gid = int(pid) * base + int(lid)
            except ValueError:
                return None
            return gid if gid in jobs else None
        try:
            key = int(key)
        except ValueError:
            return None
    if isinstance(key, (int, float)) and int(key) == key:
        gid = int(key)
        return gid if gid in jobs else None
    return None


# Проверка

def validate_schedule(instance: dict, schedule: dict | None, *, objective: str | None = None,
                      due_date: int | None = None,
                      budget_limit: dict | None = None) -> dict[str, Any]:
    """Проверяет расписание по данным инстанса. См. описание модуля.

    objective: "makespan" (по умолчанию), "penalty" (одна машина, штрафы E/T),
      "total_makespan" (многопроектная, сумма makespan проектов); None — выбрать
      по инстансу (многопроектный формат -> total_makespan; parameters.common_due_date
      -> penalty; иначе makespan).
    due_date: переопределяет parameters.common_due_date.
    budget_limit: {resource_name: limit} поверх initial_stock (Case 3, DSL).
    """
    parsed = parse_instance(instance)
    jobs = parsed["jobs"]
    resources = parsed["resources"]
    violations: list[dict] = []

    if objective is None:
        if parsed["multi_project"]:
            objective = "total_makespan"
        elif parsed["due_date"] is not None or due_date is not None:
            objective = "penalty"
        else:
            objective = "makespan"
    if due_date is None:
        due_date = parsed["due_date"]

    report: dict[str, Any] = {
        "status": STATUS_EMPTY, "feasible": False, "violations": violations,
        "makespan": None, "scheduled": 0, "total": len(jobs), "skipped": [],
        "objective": {"primary": None, "kind": objective},
    }
    if not schedule:
        return report

    # Ключи и значения
    starts: dict[int, int] = {}
    for key, value in schedule.items():
        gid = _normalize_key(key, parsed)
        if gid is None:
            violations.append({"type": "unknown_job", "job": key})
            continue
        if gid in starts:
            violations.append({"type": "unknown_job", "job": key, "detail": "duplicate key"})
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value \
                or value < 0:
            violations.append({"type": "invalid_start", "job": gid, "start": value})
            continue
        starts[gid] = int(value)
    report["scheduled"] = len(starts)

    def finish(jid: int) -> int:
        return starts[jid] + jobs[jid]["duration"]

    # Группы выбора: из группы запланированного родителя выбрана ровно одна
    # альтернатива; остальные — законно пропущены.
    skipped: set[int] = set()
    for jid in starts:
        for group in jobs[jid]["groups"]:
            chosen = [a for a in group if a in starts]
            if len(chosen) == 1:
                skipped.update(a for a in group if a not in starts)
            elif not chosen:
                violations.append({"type": "selection_group", "job": jid, "group": group,
                                   "detail": "no alternative scheduled"})
            else:
                violations.append({"type": "selection_group", "job": jid, "group": group,
                                   "detail": f"several alternatives scheduled: {chosen}"})
    report["skipped"] = sorted(skipped)

    # Полнота
    missing = [jid for jid in jobs if jid not in starts and jid not in skipped]
    for jid in missing:
        violations.append({"type": "missing_job", "job": jid})

    # Предшествование (finish-to-start) среди запланированных работ
    for jid, start in starts.items():
        for p in jobs[jid]["preds"]:
            if p in starts and finish(p) > start:
                violations.append({"type": "precedence", "job": jid, "predecessor": p,
                                   "start": start, "predecessor_finish": finish(p)})

    # Возобновляемые ресурсы: загрузка в каждый такт
    horizon = max((finish(j) for j in starts), default=0)
    for rid, res in resources.items():
        if not res["renewable"]:
            continue
        usage = [0] * (horizon + 1)
        for jid, start in starts.items():
            amount = jobs[jid]["req"].get(rid, 0)
            if amount:
                for t in range(start, finish(jid)):
                    usage[t] += amount
        for t, used in enumerate(usage):
            if used > res["capacity"]:
                violations.append({"type": "renewable_capacity", "resource": rid, "time": t,
                                   "used": used, "capacity": res["capacity"]})
                break  # одной точки на ресурс достаточно для вердикта

    # Невозобновляемые ресурсы: нарастающий расход (потребление минус производство
    # работ, начавшихся не позже t) не выше запаса / бюджета в каждый момент старта
    nrr_used: dict[str, int] = {}
    budget_violations: dict[str, dict] = {}
    for rid, res in resources.items():
        if res["renewable"]:
            continue
        limit = res["stock"]
        if budget_limit and res["name"] in budget_limit:
            limit = min(limit, int(budget_limit[res["name"]]))
        running = 0
        worst: tuple[int, int] | None = None  # (used, time)
        for jid in sorted(starts, key=lambda j: starts[j]):
            running += jobs[jid]["cons"].get(rid, 0) - jobs[jid]["prod"].get(rid, 0)
            if running > limit and (worst is None or running > worst[0]):
                worst = (running, starts[jid])
        nrr_used[res["name"]] = running
        if worst is not None:
            used, t = worst
            budget_violations[res["name"]] = {"used": used, "limit": limit, "excess": used - limit,
                                              "time": t}
            violations.append({"type": "non_renewable_budget", "resource": rid,
                               "name": res["name"], "used": used, "limit": limit, "time": t})

    # 7. Статус и цель
    if any(v["type"] != "missing_job" for v in violations):
        report["status"] = STATUS_INVALID
    elif missing:
        report["status"] = STATUS_INCOMPLETE
    else:
        report["status"] = STATUS_VALID
        report["feasible"] = True
        report["makespan"] = horizon
        obj: dict[str, Any] = {"kind": objective, "makespan": horizon}
        if objective == "total_makespan":
            pm: dict[int, int] = {}
            for jid in starts:
                pid = jobs[jid]["project_id"]
                pm[pid] = max(pm.get(pid, 0), finish(jid))
            obj["project_makespans"] = pm
            obj["total_makespan"] = sum(pm.values())
            obj["portfolio_makespan"] = max(pm.values(), default=0)
            obj["primary"] = obj["total_makespan"]
        elif objective == "penalty":
            if due_date is None:
                raise InstanceError("penalty objective needs parameters.common_due_date or due_date=")
            total = 0
            for jid in starts:
                f = finish(jid)
                if f < due_date:
                    total += (due_date - f) * jobs[jid]["ep"]
                elif f > due_date:
                    total += (f - due_date) * jobs[jid]["tp"]
            obj["due_date"] = due_date
            obj["total_et_penalty"] = total
            obj["primary"] = total
        else:
            obj["primary"] = horizon
        if nrr_used:
            obj["non_renewable_used"] = nrr_used
            obj["budget_violations"] = budget_violations
            obj["budget_feasible"] = not budget_violations
        report["objective"] = obj
    return report
