"""
Статистика (src/stats.py) и отчет (experiments/v1_pilot/evaluate.py)
на подготовленных runs.csv / baselines.csv без вызовов LLM.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from stats import holm, paired_wilcoxon

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "v1_pilot"))

import evaluate  # noqa: E402
import run_kernel  # noqa: E402


def test_wilcoxon_detects_consistent_difference():
    x = [1.0 + 0.1 * i for i in range(12)]
    y = [v + 1.0 for v in x]
    res = paired_wilcoxon(x, y)
    assert res["x_better"] == 12 and res["y_better"] == 0
    assert res["mean_diff"] == pytest.approx(-1.0)
    assert res["p_value"] < 0.01


def test_wilcoxon_all_ties_is_not_significant():
    res = paired_wilcoxon([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert res["ties"] == 3 and res["p_value"] == 1.0 and res["statistic"] is None


def test_wilcoxon_rejects_unequal_lengths():
    with pytest.raises(ValueError):
        paired_wilcoxon([1.0], [1.0, 2.0])


def test_holm():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03)        # 3 × 0.01
    assert adj["c"] == pytest.approx(0.06)        # 2 × 0.03
    assert adj["b"] == pytest.approx(0.06)        # max(1 × 0.04, 0.06) — монотонность
    assert holm({"x": 0.9, "y": 0.8}) == {"y": 1.0, "x": 1.0}


def _write(path: Path, rows: list[dict], columns: list[str]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_report_on_prepared_results(tmp_path):
    sample = json.loads(evaluate.SAMPLE_FILE.read_text(encoding="utf-8"))
    infos = sample["instances"][:6]
    runs, baselines = [], []
    for k, info in enumerate(infos):
        bks, cpm = 100, 80
        for level, makespan in (("a", 104), ("b", 102)):
            for gen in (1, 2):
                failed = level == "a" and k == 0 and gen == 2
                runs.append({"instance": info["name"], "set": info["set"], "param": info["param"],
                             "level": level, "gen": gen,
                             "status": "runtime_error" if failed else "ok",
                             "makespan": "" if failed else makespan, "bks": bks, "cpm": cpm,
                             "rpd_bks": "" if failed else (makespan - bks), "uses_indicators": "False"})
        for rule, makespan in (("LST", 103), ("LFT", 105)):
            baselines.append({"instance": info["name"], "rule": rule, "status": "ok",
                              "makespan": makespan, "bks": bks, "cpm": cpm, "rpd_bks": makespan - bks})
    run_dir = tmp_path / "res" / "t"
    run_dir.mkdir(parents=True)
    _write(run_dir / "runs.csv", runs, run_kernel.RUN_COLUMNS)
    _write(run_dir / "baselines.csv", baselines, run_kernel.BASELINE_COLUMNS)

    rep = evaluate.build_report("t", tmp_path / "res", tmp_path / "gens", evaluate.SAMPLE_FILE)
    a, b = rep["levels"]["a"], rep["levels"]["b"]
    assert a["runs"] == 12 and a["valid"] == 11 and a["statuses"] == {"ok": 11, "runtime_error": 1}
    assert a["arpd_bks"] == pytest.approx(4.0) and b["arpd_bks"] == pytest.approx(2.0)
    assert a["arpd_cpm"] == pytest.approx(30.0)
    assert rep["rules"]["LST"]["arpd_bks"] == pytest.approx(3.0)
    ab = rep["comparisons"]["a vs b"]
    assert ab["n"] == 6 and ab["mean_diff"] == pytest.approx(2.0) and ab["y_better"] == 6
    assert ab["exceeds_delta"]
    assert set(rep["comparisons"]) == {"a vs b", "a vs LST", "b vs LST"}
    assert set(rep["breakdown"]) == {"rs", "os", "rf"}
    assert sum(g["n"] for g in rep["breakdown"]["rs"].values()) == 6
    assert rep["cost"] is None
    md = evaluate.to_markdown(rep)
    assert "| a vs b | 6 |" in md and "-0.00" not in md


def test_cost_estimate_and_spent():
    summary = {"tasks": 4, "tokens": {"prompt": 1_000_000, "completion": 2_000_000}}
    c = evaluate.cost(summary, 0.10, 0.50, spent_usd=0.2)
    assert c["usd"] == pytest.approx(1.1) and c["usd_per_call"] == pytest.approx(0.275)
    assert c["spent_usd"] == 0.2 and c["spent_usd_per_call"] == pytest.approx(0.05)
    assert "spent_usd" not in evaluate.cost(summary, 0.10, 0.50)
