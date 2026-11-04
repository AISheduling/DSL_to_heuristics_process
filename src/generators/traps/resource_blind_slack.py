from __future__ import annotations

import math
import random

from dsl_builder import build_dsl
from generators.background import background_network
from priority_rules import RULES_V2
from scheduler_skeleton import build_state, default_allocate, run_schedule

NAME = "resource_blind_slack"
TARGET_RULES = ["LST", "MTS"]
NON_TARGET_RULES = ["GRPW", "GP1"]
CONTROLS = ("fits", "short_delay")
CAPACITY_RANGE = (6, 20)
MIN_CHAIN_DURATION = 4
MIN_BACKGROUND = 5


def trap_size(n: int) -> int:
    """Число блоков (h, хвост): один на ~10 работ проекта, не меньше двух."""
    return max(2, round(n / 10))


def _worst_rule_makespan(inst: dict) -> int:
    """
    Худший makespan фона по правилам SSGS. Цепочка должна быть длиннее: иначе у правила,
    которое плохо расписывает фон, срок проекта задает фон, и проигрыш от ловушки скрыт.
    """
    dsl = build_dsl(inst, "none")
    worst = 0
    for select in RULES_V2.values():
        _, state = build_state(dsl, inst)
        worst = max(worst, run_schedule(state, select, default_allocate)["objective"]["primary"])
    return worst


def _chain_durations(m: int, target: int, rng: random.Random, inner: bool = False) -> list[int]:
    """
    Длительности цепочки;
    сумма (при inner — без первой и последней работы) не меньше target.
    """
    span = m - 2 if inner else m
    base = target / span
    d = [max(MIN_CHAIN_DURATION, math.ceil(base * rng.uniform(0.6, 1.4))) for _ in range(m)]
    total = sum(d[1:-1]) if inner else sum(d)
    if total < target:
        factor = target / total
        d = [math.ceil(x * factor) for x in d]
    return d


def _draw_blocks(k: int, d: list[int], r_c: list[int], cap: int, rng: random.Random) -> list[dict]:
    """
    Параметры блока i для обоих вариантов (ловушка и контроль) тянутся всегда, чтобы при
    одном seed числа не зависели от s и вида контроля.
    """
    blocks = []
    for i in range(k):
        a = 2 * i
        dc, dnext, rc = d[a], d[a + 1], r_c[a]
        p = rng.randint(1, max(1, (dc - 2) // 2))
        blocks.append({
            "p": p, "d_c": dc, "r_c": rc,
            "shift_trap": rng.randint(1, dc - p - 1),
            "shift_short": rng.randint(dc - p, dc - 1),
            "r_conflict": rng.randint(cap - rc + 1, cap),
            "r_fit": rng.randint(1, cap - rc),
        })
    return blocks


def generate(n: int, n_res: int, s: float, seed: int, *, control: str = "fits",
             shared: bool = False, chain_margin: float = 1.05, **background_kwargs) -> dict:
    """
    Проект из n реальных работ: фон background_network плюс ловушка — цепочка из 2K + 1
    работ и K блоков (h, хвост), K = trap_size(n). В ⌊s·K + ½⌋ блоках выполнены все три
    условия, в остальных нарушено одно — по виду контроля control ("fits" или "short_delay").

    Блок i опирается на работу цепочки c = c_{2i−1}: у h те же предшественники, что у c,
    хвост h — предшественник c_{2i+1}; длина хвоста задает сдвиг LS_h − LS_c.
    chain_margin — во сколько раз цепочка длиннее худшего makespan фона по правилам (при shared —
    часть цепочки между первой и последней работой, внутри которой идет фон).
    shared — ловушка на ресурсе 1 фона, фон между c_1 и c_last; иначе ресурс ловушки отдельный
    (n_res + 1). Остальные параметры передаются в background_network.
    """
    if not 0 <= s <= 1:
        raise ValueError("s — сила ловушки, от 0 до 1")
    if control not in CONTROLS:
        raise ValueError(f"control — один из {CONTROLS}")
    k = trap_size(n)
    m = 2 * k + 1
    n_bg = n - m - 2 * k
    if n_bg < MIN_BACKGROUND:
        raise ValueError(f"при n = {n} на фон остается {n_bg} работ, нужно не меньше {MIN_BACKGROUND}")

    bg = background_network(n_bg, n_res, seed, **background_kwargs)
    # Свои потоки: числа ловушки не сдвигают фон, а выбор блоков-ловушек не сдвигает числа
    rng = random.Random(f"{NAME}:{seed}")
    order = list(range(k))
    random.Random(f"{NAME}:order:{seed}").shuffle(order)
    active = set(order[:math.floor(s * k + 0.5)])

    if shared:
        trap_res = 1
        cap = next(r["capacity"] for r in bg["resources"] if r["id"] == trap_res)
        if cap < 3:
            raise ValueError(f"ёмкость ресурса 1 фона {cap}: для условия 2 нужна хотя бы 3")
    else:
        trap_res = n_res + 1
        cap = rng.randint(*CAPACITY_RANGE)
    d = _chain_durations(m, math.ceil(chain_margin * _worst_rule_makespan(bg)), rng, inner=shared)
    r_c = [rng.randint(cap // 2 + 1, cap - 1) for _ in range(m)]
    drawn = _draw_blocks(k, d, r_c, cap, rng)

    old_sink = n_bg + 2
    chain = list(range(old_sink, old_sink + m))
    hs = list(range(chain[-1] + 1, chain[-1] + 1 + k))
    tails = list(range(hs[-1] + 1, hs[-1] + 1 + k))
    sink = tails[-1] + 1

    preds: dict[int, list[int]] = {c: [1] if a == 0 else [chain[a - 1]] for a, c in enumerate(chain)}
    for i, t in enumerate(tails):
        preds[chain[2 * i + 2]].append(t)
    # Общие предшественники h и c: иначе после задержки цепочки h встает в промежуток
    # перед c, и SSGS обезвреживает ловушку
    for i, h in enumerate(hs):
        preds[h] = list(preds[chain[2 * i]])

    def job(i, dur, demand=0):
        return {"id": i, "predecessors": [], "successors": [], "duration": dur,
                "resource_requirements": [{"resource_id": trap_res, "amount": demand}] if demand else []}

    new = {c: job(c, d[a], r_c[a]) for a, c in enumerate(chain)}
    blocks = []
    for i, (h, t) in enumerate(zip(hs, tails)):
        b = drawn[i]
        kind = "trap" if i in active else control
        shift = b["shift_short"] if kind == "short_delay" else b["shift_trap"]
        r_h = b["r_fit"] if kind == "fits" else b["r_conflict"]
        # Поздний старт h = LS_c + сдвиг: хвост заканчивается к позднему старту c_{2i+1}
        tail = d[2 * i] + d[2 * i + 1] - shift - b["p"]
        new[h] = job(h, b["p"], r_h)
        new[t] = job(t, tail)
        preds[t] = [h]
        blocks.append({"h": h, "tail": t, "c": chain[2 * i], "merge": chain[2 * i + 2],
                       "kind": kind, "capacity": cap, "r_c": b["r_c"], "r_h": r_h,
                       "p": b["p"], "d_c": b["d_c"], "shift": shift})
    preds[sink] = [chain[-1]]

    for i, ps in preds.items():
        for p in ps:
            if p in new:
                new[p]["successors"].append(i)
    for i, j in new.items():
        j["predecessors"] = sorted(preds[i])
        j["successors"] = sorted(j["successors"])

    bg_jobs = [j for j in bg["jobs"] if j["id"] not in (1, old_sink)]
    if shared:
        # Фон между c_1 и c_last: начинается после c_1, заканчивается до c_last
        first, last = chain[0], chain[-1]
        for j in bg_jobs:
            j["predecessors"] = [first if x == 1 else x for x in j["predecessors"]]
            j["successors"] = [last if x == old_sink else x for x in j["successors"]]
        entry = sorted(j["id"] for j in bg_jobs if first in j["predecessors"])
        exit_ = sorted(j["id"] for j in bg_jobs if last in j["successors"])
        new[first]["successors"] = sorted(new[first]["successors"] + entry)
        new[last]["predecessors"] = sorted(new[last]["predecessors"] + exit_)
        source_succ = []
    else:
        for j in bg_jobs:
            j["successors"] = [sink if x == old_sink else x for x in j["successors"]]
        source_succ = [x for x in bg["jobs"][0]["successors"] if x != old_sink]
    source = dict(bg["jobs"][0], successors=sorted(source_succ + [x for x in new if preds[x] == [1]]))
    jobs = [source] + bg_jobs
    jobs += [new[i] for i in sorted(new)]
    jobs.append({"id": sink, "predecessors": sorted({j["id"] for j in jobs if sink in j["successors"]}),
                 "successors": [], "name": "Supersink", "duration": 0, "resource_requirements": []})

    resources = bg["resources"] + ([] if shared else
                                   [{"id": trap_res, "name": f"R{trap_res}", "capacity": cap,
                                     "type": "renewable"}])
    return {
        "case_info": {"id": f"F1_n{n}_r{n_res}_s{s}_{control}{'_shared' if shared else ''}_seed{seed}",
                      "source": f"generators.traps.{NAME}",
                      "description": f"Синтетический RCPSP с ловушкой F1: {n} работ", "type": "RCPSP"},
        "project_goal": {"objective_function": "min_makespan"},
        "resources": resources,
        "jobs": jobs,
        "generator": {"name": NAME, "seed": seed, "s": s, "control": control, "shared": shared,
                      "target_rules": TARGET_RULES, "non_target_rules": NON_TARGET_RULES,
                      "params": {"n": n, "n_res": n_res, "chain_margin": chain_margin,
                                 **background_kwargs},
                      "background": bg["generator"],
                      "trap": {"resource": trap_res, "capacity": cap, "chain": chain,
                               "blocks": blocks}},
    }
