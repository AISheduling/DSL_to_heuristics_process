"""
Стандартные индикаторы проекта RCPSP (12 штук, как в guo2021prselection, табл. 2)
и дополнительные признаки для синтетических сценариев. Формулы и договоренности —
docs/adr/0002-project-indicators.md.

Модуль не импортирует каркас (как и schedule_checker.py): вход — инстанс в формате
data/processed. Считается только одномодовый RCPSP с возобновляемыми ресурсами.
Фиктивные работы (длительность 0 и нет спроса) исключаются; дуги к ним и от них
не учитываются.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev

STANDARD = "guo2021-v1"


class IndicatorError(ValueError):
    """Инстанс вне области применимости индикаторов."""


@dataclass
class ProjectNetwork:
    activities: list[int]                    # реальные работы, по возрастанию id
    succ: dict[int, list[int]]               # дуги между реальными работами
    pred: dict[int, list[int]]
    duration: dict[int, int]
    demand: dict[int, dict[int, int]]        # работа -> {ресурс: спрос > 0}
    capacity: dict[int, int]                 # возобновляемые ресурсы

    @property
    def n(self) -> int:
        return len(self.activities)

    @property
    def arcs(self) -> list[tuple[int, int]]:
        return [(i, j) for i in self.activities for j in self.succ[i]]


def _demand_of(job: dict) -> dict[int, int]:
    rr = job.get("resource_requirements", job.get("resources_required", []))
    if isinstance(rr, dict):
        return {int(k): int(v) for k, v in rr.items() if v}
    return {int(r["resource_id"]): int(r["amount"]) for r in rr if r.get("amount")}


def network_from_instance(instance: dict) -> ProjectNetwork:
    resources = instance.get("resources", [])
    if any(r.get("type", "renewable") != "renewable" for r in resources):
        raise IndicatorError("индикаторы определены только для возобновляемых ресурсов")
    jobs = instance.get("jobs", [])
    if jobs and "activities" in jobs[0]:
        raise IndicatorError("многопроектный инстанс: считать индикаторы по проектам")
    if any("precedences" in j or j.get("modes") for j in jobs):
        raise IndicatorError("группы выбора и многомодовые работы не поддерживаются")

    capacity = {int(r["id"]): int(r["capacity"]) for r in resources}
    by_id = {int(j["id"]): j for j in jobs}
    succ_all: dict[int, set[int]] = {i: set() for i in by_id}
    for i, j in by_id.items():
        for s in j.get("successors", []):
            succ_all[i].add(int(s))
        for p in j.get("predecessors", []):
            succ_all[int(p)].add(i)

    demand = {i: _demand_of(j) for i, j in by_id.items()}
    duration = {i: int(j.get("duration", 0)) for i, j in by_id.items()}
    real = sorted(i for i in by_id if duration[i] > 0 or demand[i])
    real_set = set(real)
    succ = {i: sorted(s for s in succ_all[i] if s in real_set) for i in real}
    pred: dict[int, list[int]] = {i: [] for i in real}
    for i in real:
        for s in succ[i]:
            pred[s].append(i)
    return ProjectNetwork(real, succ, {i: sorted(p) for i, p in pred.items()},
                          {i: duration[i] for i in real}, {i: demand[i] for i in real},
                          capacity)


# Сеть

def topological_order(net: ProjectNetwork) -> list[int]:
    indeg = {i: len(net.pred[i]) for i in net.activities}
    queue = [i for i in net.activities if indeg[i] == 0]
    order = []
    while queue:
        i = queue.pop()
        order.append(i)
        for s in net.succ[i]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(order) != net.n:
        raise IndicatorError("граф предшествования содержит цикл")
    return order


def progressive_levels(net: ProjectNetwork) -> dict[int, int]:
    """PL_i = 1 без предшественников, иначе max PL предшественника + 1."""
    pl: dict[int, int] = {}
    for i in topological_order(net):
        pl[i] = max((pl[p] + 1 for p in net.pred[i]), default=1)
    return pl


def regressive_levels(net: ProjectNetwork, m: int) -> dict[int, int]:
    """RL_i = m без преемников, иначе min RL преемника − 1."""
    rl: dict[int, int] = {}
    for i in reversed(topological_order(net)):
        rl[i] = min((rl[s] - 1 for s in net.succ[i]), default=m)
    return rl


def descendants(net: ProjectNetwork) -> dict[int, set[int]]:
    desc: dict[int, set[int]] = {}
    for i in reversed(topological_order(net)):
        d: set[int] = set()
        for s in net.succ[i]:
            d.add(s)
            d |= desc[s]
        desc[i] = d
    return desc


def network_indicators(net: ProjectNetwork) -> dict:
    n = net.n
    arcs = net.arcs
    pl = progressive_levels(net)
    m = max(pl.values(), default=0)
    width = [sum(1 for i in net.activities if pl[i] == a) for a in range(1, m + 1)]
    w1 = width[0] if width else 0

    cnc = len(arcs) / n if n else 0.0
    closure = sum(len(d) for d in descendants(net).values())
    os_ = closure / (n * (n - 1) / 2) if n > 1 else 0.0

    # I2: serial/parallel
    sp = (m - 1) / (n - 1) if n > 1 else 1.0

    # I3: activity distribution. 0 — работы распределены по уровням равномерно,
    # 1 — максимально неравномерно (так в RCPLIB, см. ADR 0002; у Vanhoucke 2008
    # шкала обратная: (alpha_max − alpha_w) / alpha_max)
    if m in (1, n):
        ad = 0.0
    else:
        w_avg = n / m
        alpha_w = sum(abs(w - w_avg) for w in width)
        alpha_max = 2 * (m - 1) * (w_avg - 1)
        ad = alpha_w / alpha_max

    # I4 (LA) и I5: короткие и длинные дуги по прогрессивным уровням
    lengths = [pl[j] - pl[i] for i, j in arcs]
    n_short = sum(1 for length in lengths if length == 1)
    d_max = sum(width[a] * width[a + 1] for a in range(m - 1))
    base = n - w1                       # минимум коротких дуг: по одной на работу вне 1-го уровня
    la = 1.0 if d_max == base else (n_short - base) / (d_max - base)
    if len(arcs) == base:
        i5 = 1.0
    else:
        weighted_long = sum((m - length - 1) / (m - 2) for length in lengths if length >= 2)
        i5 = (weighted_long + n_short - base) / (len(arcs) - base)

    # I6: topological float
    if m in (1, n):
        tf = 0.0
    else:
        rl = regressive_levels(net, m)
        tf = sum(rl[i] - pl[i] for i in net.activities) / ((m - 1) * (n - m))

    return {"n": n, "cnc": cnc, "os": os_, "sp": sp, "ad": ad, "la": la, "i5": i5, "tf": tf}


# Ресурсы

def earliest_starts(net: ProjectNetwork) -> dict[int, int]:
    es: dict[int, int] = {}
    for i in topological_order(net):
        es[i] = max((es[p] + net.duration[p] for p in net.pred[i]), default=0)
    return es


def _peak_es_demand(net: ProjectNetwork, k: int, es: dict[int, int]) -> int:
    events: dict[int, int] = {}
    for i in net.activities:
        r = net.demand[i].get(k, 0)
        if r and net.duration[i]:
            events[es[i]] = events.get(es[i], 0) + r
            events[es[i] + net.duration[i]] = events.get(es[i] + net.duration[i], 0) - r
    peak = level = 0
    for t in sorted(events):
        level += events[t]
        peak = max(peak, level)
    return peak


def resource_indicators(net: ProjectNetwork) -> dict:
    n, res = net.n, sorted(net.capacity)
    k_count = len(res)
    if not n or not k_count:
        return {"rf": None, "ru": None, "rs": None, "rc": None, "per_resource": {}}

    used = {i: sum(1 for k in res if net.demand[i].get(k, 0) > 0) for i in net.activities}
    rf = sum(used.values()) / (n * k_count)
    ru = mean(used.values())

    es = earliest_starts(net)
    per_resource = {}
    for k in res:
        reqs = [net.demand[i][k] for i in net.activities if net.demand[i].get(k, 0) > 0]
        a_k = net.capacity[k]
        if not reqs:
            per_resource[k] = {"rs": None, "rc": None}
            continue
        r_min = max(reqs)
        r_max = _peak_es_demand(net, k, es)
        rs = 1.0 if r_max == r_min else (a_k - r_min) / (r_max - r_min)
        rc = mean(reqs) / a_k
        per_resource[k] = {"rs": rs, "rc": rc}

    def avg(key):
        vals = [v[key] for v in per_resource.values() if v[key] is not None]
        return mean(vals) if vals else None

    return {"rf": rf, "ru": ru, "rs": avg("rs"), "rc": avg("rc"),
            "per_resource": per_resource}


# Дополнительные признаки (не входят в сравнение с guo2021)

def _cv(values: list[float]) -> float:
    return pstdev(values) / mean(values) if values and mean(values) else 0.0


def extended_indicators(net: ProjectNetwork, rs_per_resource: dict) -> dict:
    if not net.n:
        return {}
    total = sum(net.duration.values())
    es = earliest_starts(net)
    cpm = max(es[i] + net.duration[i] for i in net.activities)
    desc = descendants(net)
    demands = [r for i in net.activities for r in net.demand[i].values()]
    rs_vals = [v["rs"] for v in rs_per_resource.values() if v["rs"] is not None]
    return {
        "max_duration_share": max(net.duration.values()) / total if total else 0.0,
        "max_descendant_share": max(len(d) for d in desc.values()) / (net.n - 1)
        if net.n > 1 else 0.0,
        "cpm_length": cpm,
        "cpm_to_total_duration": cpm / total if total else 0.0,
        "min_rs": min(rs_vals) if rs_vals else None,
        "duration_cv": _cv(list(net.duration.values())),
        "demand_cv": _cv(demands),
    }


def compute_indicators(instance: dict) -> dict:
    net = network_from_instance(instance)
    resource = resource_indicators(net)
    return {
        "standard": STANDARD,
        "network": network_indicators(net),
        "resource": resource,
        "extended": extended_indicators(net, resource["per_resource"]),
    }


def flat_indicators(instance: dict) -> dict:
    """12 индикаторов guo2021 одним словарем (n, cnc, os, sp, ad, la, i5, tf, rf, ru, rs, rc)."""
    ind = compute_indicators(instance)
    res = {k: v for k, v in ind["resource"].items() if k != "per_resource"}
    return {**ind["network"], **res}


if __name__ == "__main__":
    # python src/indicators.py data/psplib/instances/j30 out.csv  — каталог .sm или .json
    import json
    import sys
    from pathlib import Path

    import pandas as pd

    from psplib import iter_set

    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    if any(src.glob("*.sm")):
        items = iter_set(src)
    else:
        items = ((p.stem, json.loads(p.read_text(encoding="utf-8")))
                 for p in sorted(src.glob("*.json")))
    rows = []
    for name, inst in items:
        ind = compute_indicators(inst)
        res = {k: v for k, v in ind["resource"].items() if k != "per_resource"}
        rows.append({"instance": name, **ind["network"], **res, **ind["extended"]})
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"{len(rows)} инстансов -> {out}")
