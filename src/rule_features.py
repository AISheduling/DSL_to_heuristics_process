"""
Метахарактеристики, предсказывающие провал правил приоритета.

Считаются по самому проекту (работы, связи, ресурсы), без поля generator,
поэтому одинаково применимы к синтетике и к PSPLIB.

F1 «ресурсно-слепой резерв» (ломает LST и MTS): пары (h, c) несвязанных работ,
где h доступна не позже c (ES_h ≤ ES_c) и
  1) LS_c < LS_h < LF_c — по поздним стартам c срочнее;
  2) r_hk + r_ck > R_k хотя бы для одного ресурса — вместе не помещаются;
  3) LF_h < LF_c — по поздним окончаниям срочнее h.
Опоздание пары LF_c − LF_h: на столько h опоздает к своему сроку, если ждать конца c.
"""
from __future__ import annotations

from indicators import descendants, earliest_starts, network_from_instance, topological_order

FEATURES = ("f1_pairs", "f1_pairs_critical", "f1_pressure", "f1_pressure_free")


def _cpm(net) -> tuple[dict, dict, dict, dict, int]:
    es = earliest_starts(net)
    ef = {i: es[i] + net.duration[i] for i in net.activities}
    horizon = max(ef.values(), default=0)
    lf: dict[int, int] = {}
    for i in reversed(topological_order(net)):
        lf[i] = min((lf[s] - net.duration[s] for s in net.succ[i]), default=horizon)
    ls = {i: lf[i] - net.duration[i] for i in net.activities}
    return es, ef, ls, lf, horizon


def _free_share(net, es, ef, h: int, c: int, k: int) -> float:
    """
    Доля остатка ресурса k рядом с c (R_k − r_ck), не занятая другими работами в раннем
    расписании за время c. Если остаток занят, цепочку и так тормозят другие работы,
    и опоздание из-за h на срок проекта почти не влияет.
    """
    rest = net.capacity[k] - net.demand[c].get(k, 0)
    if rest <= 0 or net.duration[c] == 0:
        return 0.0
    load = 0.0
    for j in net.activities:
        if j in (h, c) or not net.demand[j].get(k):
            continue
        overlap = min(ef[j], ef[c]) - max(es[j], es[c])
        if overlap > 0:
            load += net.demand[j][k] * overlap / net.duration[c]
    return max(0.0, 1.0 - load / rest)


def f1_pairs(instance: dict) -> list[dict]:
    """Пары (h, c) со свойством F1, по возрастанию (h, c)."""
    net = network_from_instance(instance)
    es, ef, ls, lf, _ = _cpm(net)
    desc = descendants(net)
    out = []
    for h in net.activities:
        for c in net.activities:
            if h == c or c in desc[h] or h in desc[c] or es[h] > es[c]:
                continue
            if not (ls[c] < ls[h] < lf[c] and lf[h] < lf[c]):
                continue
            conflict = [k for k in net.capacity
                        if net.demand[h].get(k, 0) + net.demand[c].get(k, 0) > net.capacity[k]]
            if not conflict:
                continue
            out.append({"h": h, "c": c, "lateness": lf[c] - lf[h], "c_critical": ls[c] == es[c],
                        "free": max(_free_share(net, es, ef, h, c, k) for k in conflict)})
    return out


def rule_features(instance: dict) -> dict[str, float]:
    """
    f1_pairs — число пар со свойством F1; f1_pairs_critical — из них с c на критическом пути;
    f1_pressure — сумма по работам h наибольшего опоздания среди критических пар, деленная
    на длину критического пути; f1_pressure_free — то же, с опозданием, умноженным на долю
    свободного ресурса рядом с c.
    """
    net = network_from_instance(instance)
    horizon = _cpm(net)[4] or 1
    pairs = f1_pairs(instance)
    critical = [p for p in pairs if p["c_critical"]]
    worst: dict[int, float] = {}
    worst_free: dict[int, float] = {}
    for p in critical:
        worst[p["h"]] = max(worst.get(p["h"], 0), p["lateness"])
        worst_free[p["h"]] = max(worst_free.get(p["h"], 0.0), p["lateness"] * p["free"])
    return {"f1_pairs": len(pairs), "f1_pairs_critical": len(critical),
            "f1_pressure": sum(worst.values()) / horizon,
            "f1_pressure_free": sum(worst_free.values()) / horizon}
