from __future__ import annotations

import math
import random
from typing import Callable

from dsl_builder import build_dsl
from indicators import earliest_starts, network_from_instance
from priority_rules import RULES_V2, gp1_values, grpw_values, latest_times
from psgs import parallel_schedule
from schedule_checker import validate_schedule
from scheduler_skeleton import build_state, default_allocate, run_schedule


def lower_bound(inst: dict) -> dict[str, int]:
    net = network_from_instance(inst)
    es = earliest_starts(net)
    cpm = max((es[i] + net.duration[i] for i in net.activities), default=0)
    work = {k: sum(net.duration[i] * net.demand[i].get(k, 0) for i in net.activities)
            for k in net.capacity}
    resource = max((math.ceil(w / net.capacity[k]) for k, w in work.items() if net.capacity[k]),
                   default=0)
    return {"cpm": cpm, "resource": resource, "lb": max(cpm, resource)}


def priority_keys(jobs: dict) -> dict[str, Callable[[int], tuple]]:
    """
    Ключи сортировки правил RULES_V2 для PSGS (меньше — раньше),
    как в функциях выбора.
    """
    t = latest_times(jobs)
    lf, ls, ts = t["lf"], t["ls"], t["total_successors"]
    gp1 = gp1_values(jobs)
    w = grpw_values(jobs)
    return {"LFT": lambda j: (lf[j], j), "LST": lambda j: (ls[j], j),
            "MTS": lambda j: (-ts[j], j), "GP1": lambda j: (gp1[j], j),
            "GRPW": lambda j: (-w[j], j)}


def _regret_sampler(rng: random.Random, alpha: float = 1.0) -> Callable:
    """
    Выбор с вероятностью ∝ (max_E LF − LF_j + 1)^alpha:
    срочные работы чаще, но не всегда.
    """
    def select(eligible_ids, jobs, snapshot, meta) -> int:
        lf = latest_times(jobs)["lf"]
        top = max(lf[j] for j in eligible_ids)
        ids = sorted(eligible_ids)
        return rng.choices(ids, weights=[(top - lf[j] + 1) ** alpha for j in ids])[0]
    return select


def _ssgs(inst: dict, dsl: dict, select: Callable) -> dict[int, int]:
    _, state = build_state(dsl, inst)
    return run_schedule(state, select, default_allocate)["schedule"]


def _makespan(inst: dict, schedule: dict[int, int]) -> int:
    check = validate_schedule(inst, schedule)
    if check["status"] != "valid":
        raise RuntimeError(f"эталон: недопустимое расписание ({check['status']}): {check['violations'][:3]}")
    return check["makespan"]


def best_known(inst: dict, *, samples: int = 500, seed: int = 0) -> dict:
    """
    Лучшее расписание из правил (SSGS и PSGS) и samples проходов сэмплирования.
    rules — makespan каждого правила по схемам ("LST/ssgs", "LST/psgs", ...);
    source — откуда лучшее (правило или "sampling"); optimal — makespan совпал с LB;
    samples_run — сколько проходов сделано (меньше samples, если LB достигнут раньше).
    """
    dsl = build_dsl(inst, "none")
    _, state = build_state(dsl, inst)
    capacity = {k: r.capacity for k, r in state.resources.items()}
    keys = priority_keys(state.jobs)

    rules: dict[str, int] = {}
    best: tuple[int, str, dict] | None = None
    for name, select in RULES_V2.items():
        for scheme, schedule in (("ssgs", _ssgs(inst, dsl, select)),
                                 ("psgs", parallel_schedule(state.jobs, capacity, keys[name]))):
            label = f"{name}/{scheme}"
            rules[label] = _makespan(inst, schedule)
            if best is None or rules[label] < best[0]:
                best = (rules[label], label, schedule)

    lb = lower_bound(inst)["lb"]
    rng = random.Random(seed)
    sampler = _regret_sampler(rng)
    done = 0
    for _ in range(samples):
        if best[0] == lb:
            break
        done += 1
        schedule = _ssgs(inst, dsl, sampler)
        ms = _makespan(inst, schedule)
        if ms < best[0]:
            best = (ms, "sampling", schedule)

    makespan, source, schedule = best
    return {"makespan": makespan, "source": source, "schedule": schedule, "lb": lb,
            "optimal": makespan == lb, "rules": rules, "samples": samples, "samples_run": done, "seed": seed}
