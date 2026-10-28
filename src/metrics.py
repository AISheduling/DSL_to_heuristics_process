from __future__ import annotations

from statistics import mean


def rpd(makespan: float, reference: float) -> float:
    if reference <= 0:
        raise ValueError(f"эталон должен быть положительным, получено {reference}")
    return 100.0 * (makespan - reference) / reference


def arpd(rpds: list[float]) -> float:
    if not rpds:
        raise ValueError("ARPD по пустому списку не определен")
    return mean(rpds)


def summarize_rpd(makespans: list[float | None], references: list[float]) -> dict:
    """
    Сводка по прогонам: makespans[i] — результат прогона i (None, если допустимого полного
    расписания нет), references[i] — эталон его инстанса.
    """
    if len(makespans) != len(references):
        raise ValueError("makespans и references разной длины")
    values = [rpd(c, ref) for c, ref in zip(makespans, references) if c is not None]
    total = len(makespans)
    return {
        "runs": total,
        "valid": len(values),
        "share_valid": len(values) / total if total else 0.0,
        "arpd": arpd(values) if values else None,
        "max_rpd": max(values) if values else None,
        "share_at_reference": (sum(1 for v in values if v == 0) / len(values)) if values else None,
    }
