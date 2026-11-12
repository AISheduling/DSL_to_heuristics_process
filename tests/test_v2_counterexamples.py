"""
Пайплайн В2 (experiments/v2_counterexamples/): манифест сетки, прогон правил с кэшем
по хэшу, проверка инварианта F1 по критериям C1–C4.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "v2_counterexamples"))

import check_invariants  # noqa: E402
import make_instances  # noqa: E402
import run_rules  # noqa: E402
from priority_rules import RULES_V2  # noqa: E402


def test_grid_has_one_project_per_seed_at_full_strength():
    rows = make_instances.grid(seeds=2)
    # на ячейку: 4 значения s × 2 контроля + s = 1 один раз
    assert len(rows) == 2 * 3 * 2 * 9 * 2
    full = [r for r in rows if r["s"] == 1.0]
    assert {r["control"] for r in full} == {"fits"}
    assert len({make_instances.instance_id(r) for r in rows}) == len(rows)


@pytest.fixture(scope="module")
def small_manifest() -> dict:
    m = make_instances.make_manifest(seeds=2)
    m["instances"] = [p for p in m["instances"] if p["n"] == 30 and p["n_res"] == 4]
    return m


def test_manifest_is_deterministic(small_manifest):
    again = make_instances.make_manifest(seeds=2)
    hashes = {p["id"]: p["hash"] for p in again["instances"]}
    assert all(hashes[p["id"]] == p["hash"] for p in small_manifest["instances"])
    assert all(p["target_rules"] == ["LST", "MTS"] for p in small_manifest["instances"])


@pytest.fixture(scope="module")
def small_run(tmp_path_factory, small_manifest) -> Path:
    run_dir = tmp_path_factory.mktemp("v2") / "small"
    run_dir.mkdir()
    summary = run_rules.run_grid(run_dir, small_manifest, samples=10, workers=1)
    assert summary["computed"] == len(small_manifest["instances"]) and summary["cached"] == 0
    return run_dir


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_run_writes_one_row_per_project_and_rule(small_run, small_manifest):
    inst, rules = _rows(small_run / "instances.csv"), _rows(small_run / "rules.csv")
    assert [r["id"] for r in inst] == [p["id"] for p in small_manifest["instances"]]
    assert len(rules) == len(inst) * len(RULES_V2)
    for r in inst:
        assert int(r["lb"]) <= int(r["best"]) and r["ind_rs"] != ""
    by_id = {}
    for r in rules:
        by_id.setdefault(r["id"], []).append(r)
    for rs in by_id.values():
        ms = {r["rule"]: int(r["makespan"]) for r in rs}
        best_other = {r["rule"]: min(v for k, v in ms.items() if k != r["rule"]) for r in rs}
        for r in rs:
            assert float(r["gap_vs_others"]) == pytest.approx(100 * (ms[r["rule"]] / best_other[r["rule"]] - 1))


def test_second_run_uses_cache(small_run, small_manifest):
    summary = run_rules.run_grid(small_run, small_manifest, samples=10, workers=1)
    assert summary["computed"] == 0 and summary["cached"] == len(small_manifest["instances"])


def test_changed_generator_is_detected(small_manifest):
    p = dict(small_manifest["instances"][0], hash="0" * 16)
    with pytest.raises(RuntimeError, match="хэш"):
        run_rules.evaluate((p, 0))


def test_report_applies_the_criteria(small_run):
    rep = check_invariants.build_report(small_run)
    assert set(rep["cells"]) == {f"{e}|30|4|{r}" for e in ("isolated", "shared") for r in ("LST", "MTS")}
    for res in rep["cells"].values():
        p = res["pass"]
        assert p["c1"] == (res["c1_median_gap"] >= check_invariants.DELTA_LOSS)
        assert p["c4"] == all(v < check_invariants.CONTROL_MAX for v in res["c4_median_gap"].values())
        assert res["confirmed"] == all(p.values())
        assert res["c2"]["p_holm"] >= res["c2"]["p_value"]
    # На отдельном ресурсе контроль чистый, а ловушка дает заметный проигрыш даже на 2 seed
    iso = rep["cells"]["isolated|30|4|LST"]
    assert iso["pass"]["c4"] and iso["c1_median_gap"] >= check_invariants.DELTA_LOSS
    md = check_invariants.to_markdown(rep)
    assert "## Критерии по ячейкам" in md and "isolated" in md


# Подбор порогов метахарактеристик (fit_triggers.py)

import fit_triggers  # noqa: E402


def test_metrics_and_stump_on_separable_data():
    x = [0.0, 0.1, 0.2, 0.8, 0.9, 1.0]
    y = [False, False, False, True, True, True]
    stump = fit_triggers.fit_stump(x, y)
    assert stump["direction"] == ">" and 0.2 < stump["threshold"] < 0.8
    assert stump["train_balanced_accuracy"] == 1.0
    m = fit_triggers.metrics([True, True, False, False], [True, False, True, False])
    assert (m["precision"], m["recall"], m["specificity"], m["balanced_accuracy"]) == (0.5, 0.5, 0.5, 0.5)
    # Обратная зависимость — порог с направлением «<»
    assert fit_triggers.fit_stump(x, [not v for v in y])["direction"] == "<"


def test_trigger_report_on_small_run(small_run, small_manifest):
    # Обучение на n = 30 из маленького прогона; проверочных проектов нет — тесты пустые
    rep = fit_triggers.build_report(small_run, small_manifest, psplib=None)
    for rule in ("LST", "MTS"):
        r = rep["rules"][rule]
        assert r["trigger"] in fit_triggers.FEATURES and r["best_indicator"].startswith("ind_")
        assert set(r["features"]) == set(fit_triggers.FEATURES) | {f"ind_{k}" for k in fit_triggers.INDICATORS}
    trig = fit_triggers.triggers(rep)
    assert set(trig) == {"LST", "MTS"} and all("explanation_ru" in t for t in trig.values())
    assert (small_run / "features.csv").exists()
