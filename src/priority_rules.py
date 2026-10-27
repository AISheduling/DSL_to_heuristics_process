from __future__ import annotations

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


RULES: dict[str, Callable] = {"LFT": lft, "LST": lst, "MTS": mts}
