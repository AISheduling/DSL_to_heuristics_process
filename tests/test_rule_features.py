"""
Метахарактеристики правил (src/rule_features.py): пары (h, c) со свойством F1 на ручной
ловушке и ее контролях, на проектах генератора F1 и на PSPLIB.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from generators.traps.resource_blind_slack import generate as f1
from rule_features import FEATURES, f1_pairs, rule_features
from test_reference_solver import _instance

ROOT = Path(__file__).resolve().parents[1]


def _trap(h_demand: int = 5, tail: int = 18) -> dict:
    # Пример из resource_blind_slack.md: цепочка 2 -> 3 -> 4 по 10 (спрос 6 из 10),
    # h = 5 (1, спрос h_demand) с хвостом 6, хвост — предшественник 4
    return _instance([(1, 0, 0, [2, 5]), (2, 10, 6, [3]), (3, 10, 6, [4]), (4, 10, 6, [7]),
                      (5, 1, h_demand, [6]), (6, tail, 0, [4]), (7, 0, 0, [])], capacity=10)


def test_trap_example_has_one_pair_with_its_expected_lateness():
    pairs = f1_pairs(_trap())
    assert [(p["h"], p["c"]) for p in pairs] == [(5, 2)]
    # LF_c − LF_h = 10 − 2: на столько h опоздает, если ждать конца c
    assert pairs[0]["lateness"] == 8 and pairs[0]["c_critical"]
    f = rule_features(_trap())
    assert f["f1_pairs"] == 1 and f["f1_pairs_critical"] == 1
    assert f["f1_pressure"] == pytest.approx(8 / 30)


def test_breaking_condition_2_removes_the_pair():
    # h берет 4: 4 + 6 = 10 — помещается рядом с c
    assert f1_pairs(_trap(h_demand=4)) == []
    assert rule_features(_trap(h_demand=4))["f1_pressure"] == 0.0


def test_breaking_condition_3_removes_the_pair():
    # Хвост 9: LF_h = 20 − 9 = 11 ≥ LF_c = 10
    assert f1_pairs(_trap(tail=9)) == []


def test_features_do_not_read_generator_metadata():
    inst = f1(30, 4, s=1.0, seed=0)
    stripped = {k: v for k, v in inst.items() if k != "generator"}
    assert rule_features(stripped) == rule_features(inst)
    assert set(rule_features(inst)) == set(FEATURES)


@pytest.mark.parametrize("seed", range(3))
def test_isolated_trap_projects_have_critical_pairs_and_controls_do_not(seed):
    trap = rule_features(f1(60, 4, s=1.0, seed=seed))
    k = len(f1(60, 4, s=1.0, seed=seed)["generator"]["trap"]["blocks"])
    assert trap["f1_pairs_critical"] >= k and trap["f1_pressure"] > 0
    for control in ("fits", "short_delay"):
        assert rule_features(f1(60, 4, s=0.0, seed=seed, control=control))["f1_pairs_critical"] == 0


def test_pressure_grows_with_s():
    values = [rule_features(f1(60, 4, s=s, seed=1))["f1_pressure"] for s in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert values == sorted(values) and values[0] == 0.0 < values[-1]


PSPLIB_J30 = ROOT / "data" / "psplib" / "instances" / "j30"


@pytest.mark.skipif(not PSPLIB_J30.exists(), reason="PSPLIB не скачан (data/psplib/SOURCES.md)")
def test_features_compute_on_psplib():
    from psplib import iter_set
    for _, inst in list(iter_set(PSPLIB_J30))[:5]:
        f = rule_features(inst)
        assert f["f1_pairs"] >= f["f1_pairs_critical"] >= 0 and f["f1_pressure"] >= 0
