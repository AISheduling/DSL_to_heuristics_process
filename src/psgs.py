"""
Параллельная схема построения расписания (PSGS) для правил приоритета.

Нужна только для сверки базовых правил со статьями, где берется лучшее из SSGS и PSGS
(luo2022, табл. 14). В эксперименте В1 бюджет — одно построение SSGS на инстанс
(ADR 0003), и PSGS там не используется.

На каждом моменте решения t (0 и моменты окончания работ) работы, все предшественники
которых закончились к t, перебираются по приоритету и ставятся в t, если хватает
остатка мощности каждого ресурса при уже идущих работах.
"""
from __future__ import annotations

from typing import Callable


def parallel_schedule(jobs: dict, capacity: dict[int, int],
                      priority: Callable[[int], tuple]) -> dict[int, int]:
    """jobs: id -> Job (duration, predecessors, resources_required); priority: меньше — раньше."""
    start: dict[int, int] = {}
    finish: dict[int, int] = {}
    t = 0
    while len(start) < len(jobs):
        active = [j for j in start if start[j] <= t < finish[j]]
        used = {k: sum(jobs[j].resources_required.get(k, 0) for j in active) for k in capacity}
        eligible = sorted((j for j in jobs if j not in start
                           and all(p in finish and finish[p] <= t for p in jobs[j].predecessors)),
                          key=priority)
        progress = True
        while progress:          # Работа длительности 0 может открыть новые работы в тот же момент
            progress = False
            for j in eligible:
                if j in start:
                    continue
                req = jobs[j].resources_required
                if all(used[k] + req.get(k, 0) <= capacity[k] for k in capacity):
                    start[j], finish[j] = t, t + jobs[j].duration
                    if jobs[j].duration:
                        for k, r in req.items():
                            used[k] = used.get(k, 0) + r
                    progress = True
            if progress:
                eligible = sorted((j for j in jobs if j not in start and all(
                    p in finish and finish[p] <= t for p in jobs[j].predecessors)), key=priority)
        later = [f for f in finish.values() if f > t]
        if not later and len(start) < len(jobs):
            raise RuntimeError("PSGS: нет допустимых работ — потребность больше мощности?")
        if later:
            t = min(later)
    return start
