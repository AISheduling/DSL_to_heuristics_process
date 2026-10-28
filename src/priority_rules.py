from __future__ import annotations

import math
from typing import Callable

_CACHE: dict[int, dict] = {}


def latest_times(jobs: dict) -> dict[str, dict[int, int]]:
    """
    Поздние старт и окончание каждой работы (CPM без ресурсов)
    и число всех преемников.
    """
    key = id(jobs)
    cached = _CACHE.get(key)
    if cached is not None and cached["jobs"] is jobs:
        return cached["times"]
    indeg = {j: len(jobs[j].predecessors) for j in jobs}
    order, stack = [], sorted((j for j in jobs if indeg[j] == 0), reverse=True)
    while stack:
        u = stack.pop()
        order.append(u)
        for v in jobs[u].successors:
            indeg[v] -= 1
            if indeg[v] == 0:
                stack.append(v)
    ef: dict[int, int] = {}
    for u in order:
        es = max((ef[p] for p in jobs[u].predecessors), default=0)
        ef[u] = es + jobs[u].duration
    horizon = max(ef.values(), default=0)
    lf: dict[int, int] = {}
    descendants: dict[int, set[int]] = {}
    for u in reversed(order):
        lf[u] = min((lf[s] - jobs[s].duration for s in jobs[u].successors), default=horizon)
        d: set[int] = set()
        for s in jobs[u].successors:
            d.add(s)
            d |= descendants[s]
        descendants[u] = d
    times = {"lf": lf, "ls": {u: lf[u] - jobs[u].duration for u in jobs},
             "total_successors": {u: len(descendants[u]) for u in jobs}}
    _CACHE.clear()
    _CACHE[key] = {"jobs": jobs, "times": times}
    return times


def lft(eligible_ids, jobs, snapshot, meta) -> int:
    lf = latest_times(jobs)["lf"]
    return min(eligible_ids, key=lambda j: (lf[j], j))


def lst(eligible_ids, jobs, snapshot, meta) -> int:
    ls = latest_times(jobs)["ls"]
    return min(eligible_ids, key=lambda j: (ls[j], j))


def mts(eligible_ids, jobs, snapshot, meta) -> int:
    ts = latest_times(jobs)["total_successors"]
    return min(eligible_ids, key=lambda j: (-ts[j], j))


_GP1_CACHE: dict[int, dict] = {}


def _normalized(values: dict[int, float]) -> dict[int, float]:
    """Деление на максимум по проекту (luo2022, §3.2.2); при максимуме 0 — нули."""
    top = max(values.values(), default=0)
    return {j: (v / top if top else 0.0) for j, v in values.items()}


def gp1_values(jobs: dict) -> dict[int, float]:
    """
    Значение правила GP1 (Luo et al., 2022, ур. 3) для каждой работы:
        ((LFT + ((LFT + (LST − GRES)) − MTS)) / (GCRWC + pos(cos(LST)))) − GRES
    Терминалы по табл. 19 статьи, нормированные делением на максимум по проекту:
    LST, LFT — поздние сроки CPM; MTS — число всех преемников; GRES = Σ_k r_ik;
    GCRWC = Σ_{j ∈ прямые преемники i} d_j · Σ_k r_jk; pos(x) = max(x, 0).
    Нормированный LST лежит в [0, 1], поэтому cos(LST) > 0, знаменатель положителен
    и защита деления не нужна.
    """
    key = id(jobs)
    cached = _GP1_CACHE.get(key)
    if cached is not None and cached["jobs"] is jobs:
        return cached["values"]
    t = latest_times(jobs)
    gres_raw = {j: sum(jobs[j].resources_required.values()) for j in jobs}
    lft_n = _normalized(t["lf"])
    lst_n = _normalized(t["ls"])
    mts_n = _normalized(t["total_successors"])
    gres = _normalized(gres_raw)
    gcrwc = _normalized({j: sum(jobs[s].duration * gres_raw[s] for s in jobs[j].successors)
                         for j in jobs})
    values = {}
    for j in jobs:
        numerator = lft_n[j] + ((lft_n[j] + (lst_n[j] - gres[j])) - mts_n[j])
        values[j] = numerator / (gcrwc[j] + max(math.cos(lst_n[j]), 0.0)) - gres[j]
    _GP1_CACHE.clear()
    _GP1_CACHE[key] = {"jobs": jobs, "values": values}
    return values


def gp1(eligible_ids, jobs, snapshot, meta) -> int:
    """Первой ставится работа с наименьшим значением GP1 (как у LFT/LST, из которых он собран)."""
    v = gp1_values(jobs)
    return min(eligible_ids, key=lambda j: (v[j], j))


RULES: dict[str, Callable] = {"LFT": lft, "LST": lst, "MTS": mts, "GP1": gp1}
