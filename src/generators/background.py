"""
Фоновые сети В2: случайные проекты RCPSP в формате data/processed/*.json.

В фон встраиваются ловушки для правил (generators/traps/),
и он же без ловушек — контрольная группа. Поэтому параметры фона (размер, глубина,
плотность связей, RF, RS) задаются независимо от ловушки.

Работы разложены по слоям, и у каждой есть предшественник в предыдущем слое, поэтому
глубина (число работ на самом длинном по связям пути) равна числу слоев. Дуги через
несколько слоев дают работам резерв по уровням (TF); транзитивные дуги удаляются.
"""
from __future__ import annotations

import math
import random

from indicators import _peak_es_demand, earliest_starts, network_from_instance

NAME = "background"


def _check(n, n_res, layers, extra_preds, durations, rf, rs, max_demand) -> None:
    if n < 1 or n_res < 1:
        raise ValueError("нужны n >= 1 и n_res >= 1")
    if not 1 <= layers <= n:
        raise ValueError(f"число слоев должно быть от 1 до n, получено {layers}")
    if extra_preds < 0:
        raise ValueError("extra_preds — среднее число дуг, не меньше 0")
    if not 1 <= durations[0] <= durations[1]:
        raise ValueError("длительности реальных работ — целые от 1")
    if not 0 < rf <= 1:
        raise ValueError("RF должен быть в (0, 1]")
    if not 0 <= rs <= 1:
        raise ValueError("RS должен быть в [0, 1]")
    if max_demand < 1:
        raise ValueError("max_demand должен быть >= 1")


def _transitive_reduction(n: int, arcs: set) -> set:
    succ: dict[int, set[int]] = {i: set() for i in range(n)}
    for i, j in arcs:
        succ[i].add(j)
    kept = set()
    for i, j in arcs:
        stack, seen = [s for s in succ[i] if s != j], set()
        while stack:
            u = stack.pop()
            if u == j:
                break
            if u not in seen:
                seen.add(u)
                stack.extend(succ[u])
        else:
            kept.add((i, j))
    return kept


def _layered_arcs(n: int, layers: int, extra_preds: float, rng: random.Random) -> tuple[list[int], set]:
    """
    Слой каждой работы 0..n-1 (по неубыванию)
    и дуги вперед по слоям без транзитивных.
    """
    layer_of = list(range(layers)) + [rng.randrange(layers) for _ in range(n - layers)]
    layer_of.sort()                     # номера работ растут со слоем, как в PSPLIB
    by_layer: list[list[int]] = [[] for _ in range(layers)]
    for i, l in enumerate(layer_of):
        by_layer[l].append(i)
    arcs = set()
    for l in range(1, layers):
        for j in by_layer[l]:
            arcs.add((rng.choice(by_layer[l - 1]), j))      # Ровно одна короткая дуга
            # Остальные дуги длинные (через слой и больше)
            far = [i for a in range(l - 1) for i in by_layer[a]]
            k = int(extra_preds) + (rng.random() < extra_preds - int(extra_preds))
            for i in rng.sample(far, min(k, len(far))):
                arcs.add((i, j))
    # Обязательная дуга из соседнего слоя не бывает транзитивной: другого пути между
    # соседними слоями нет, поэтому глубина после редукции сохраняется
    return layer_of, _transitive_reduction(n, arcs)


def _resource_sets(n: int, n_res: int, rf: float, rng: random.Random) -> list[list[int]]:
    """
    Какие ресурсы использует каждая работа;
    в среднем rf · n_res, не меньше одного.
    """
    q = rf * n_res
    sets = []
    for _ in range(n):
        count = int(q) + (rng.random() < q - int(q))
        sets.append(sorted(rng.sample(range(n_res), min(n_res, max(1, count)))))
    # Неиспользуемый ресурс не определяет RS; заменяем им ресурс,
    # который есть у других работ, чтобы не менять число ресурсов у работы и RF
    for k in range(n_res):
        users = [i for i, s in enumerate(sets) if k in s]
        if users:
            continue
        counts = {r: sum(r in s for s in sets) for r in range(n_res)}
        donors = [(i, r) for i, s in enumerate(sets) for r in s if counts[r] > 1]
        i, r = rng.choice(donors)
        sets[i] = sorted([x for x in sets[i] if x != r] + [k])
    return sets


def background_network(n: int, n_res: int, seed: int, *, layers: int | None = None,
                       extra_preds: float = 1.2, durations: tuple[int, int] = (1, 10),
                       rf: float = 0.5, rs: float = 0.3, max_demand: int = 10) -> dict:
    """
    Случайный проект из n реальных работ и n_res возобновляемых ресурсов.

    layers — глубина сети (по умолчанию √(2n): 8 слоев при n = 30, 15 при n = 120);
    extra_preds — среднее число длинных дуг (через слой и больше) в работу сверх
    обязательной короткой; при 1.2 CNC, OS и TF в диапазонах PSPLIB J30–J120;
    RF — средняя доля ресурсов, нужных работе;
    RS — сила ресурсов по Kolisch: R_k = r_min + RS · (r_peak − r_min), где r_min —
    наибольший спрос одной работы, r_peak — пик спроса в раннем расписании без ресурсов.
    Результат детерминирован по seed.
    """
    if layers is None:
        layers = min(n, max(2, round((2 * n) ** 0.5))) if n >= 1 else 1
    _check(n, n_res, layers, extra_preds, durations, rf, rs, max_demand)
    rng = random.Random(seed)

    _, arcs = _layered_arcs(n, layers, extra_preds, rng)
    durs = [rng.randint(*durations) for _ in range(n)]
    demand = [{k + 1: rng.randint(1, max_demand) for k in ks}
              for ks in _resource_sets(n, n_res, rf, rng)]

    # id: 1 — исток, 2..n+1 — работы, n+2 — сток
    source, sink = 1, n + 2
    succ = {i: set() for i in range(1, n + 3)}
    for i, j in arcs:
        succ[i + 2].add(j + 2)
    has_pred = {j for s in succ.values() for j in s}
    for i in range(2, n + 2):
        if i not in has_pred:
            succ[source].add(i)
        if not succ[i]:
            succ[i].add(sink)
    pred = {i: set() for i in succ}
    for i, ss in succ.items():
        for j in ss:
            pred[j].add(i)

    jobs = []
    for i in range(1, n + 3):
        real = source < i < sink
        job = {"id": i, "predecessors": sorted(pred[i]), "successors": sorted(succ[i]),
               "duration": durs[i - 2] if real else 0,
               "resource_requirements": ([{"resource_id": k, "amount": a}
                                          for k, a in sorted(demand[i - 2].items())]
                                         if real else [])}
        if not real:
            job["name"] = "Supersource" if i == source else "Supersink"
        jobs.append(job)

    resources = [{"id": k, "name": f"R{k}", "capacity": 0, "type": "renewable"}
                 for k in range(1, n_res + 1)]
    inst = {
        "case_info": {"id": f"BG_n{n}_r{n_res}_s{seed}", "source": "generators.background",
                      "description": f"Синтетический RCPSP: {n} работ, {n_res} возобновляемых ресурсов",
                      "type": "RCPSP"},
        "project_goal": {"objective_function": "min_makespan"},
        "resources": resources,
        "jobs": jobs,
        "generator": {"name": NAME, "seed": seed,
                      "params": {"n": n, "n_res": n_res, "layers": layers,
                                 "extra_preds": extra_preds, "durations": list(durations),
                                 "rf": rf, "rs": rs, "max_demand": max_demand}},
    }

    # Пик раннего расписания от емкости не зависит, поэтому считаем его заранее
    net = network_from_instance(inst)
    es = earliest_starts(net)
    for r in resources:
        k = r["id"]
        r_min = max(d[k] for d in demand if k in d)
        r_peak = _peak_es_demand(net, k, es)
        # Округление половины вверх: RS получается с точностью 0.5 / (r_peak − r_min)
        r["capacity"] = r_min + math.floor(rs * (r_peak - r_min) + 0.5)
    return inst
