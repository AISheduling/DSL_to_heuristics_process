from __future__ import annotations

from statistics import mean, median


def paired_wilcoxon(x: list[float], y: list[float]) -> dict:
    """
    x и y — значения одних и тех же инстансов;
    разность d = x − y (меньше RPD — лучше).
    """
    if len(x) != len(y):
        raise ValueError("x и y разной длины")
    d = [a - b for a, b in zip(x, y)]
    out = {
        "n": len(d),
        "mean_diff": mean(d) if d else None,
        "median_diff": median(d) if d else None,
        "x_better": sum(1 for v in d if v < 0),
        "y_better": sum(1 for v in d if v > 0),
        "ties": sum(1 for v in d if v == 0),
        "statistic": None,
        "p_value": 1.0,
    }
    if out["x_better"] + out["y_better"] > 0:
        from scipy.stats import wilcoxon

        res = wilcoxon(x, y, zero_method="wilcox", alternative="two-sided")
        out["statistic"] = float(res.statistic)
        out["p_value"] = float(res.pvalue)
    return out


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Скорректированные p-значения по Холму (монотонные, не больше 1)."""
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (key, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[key] = running
    return adjusted
