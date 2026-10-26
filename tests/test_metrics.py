"""
RPD / ARPD (src/metrics.py) и выборка первого эксперимента (experiments/v1_pilot).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from metrics import arpd, rpd, summarize_rpd

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "experiments" / "v1_pilot"


def test_rpd():
    assert rpd(53, 50) == pytest.approx(6.0)
    assert rpd(50, 50) == 0
    with pytest.raises(ValueError):
        rpd(10, 0)


def test_arpd():
    assert arpd([0.0, 6.0, 3.0]) == pytest.approx(3.0)
    with pytest.raises(ValueError):
        arpd([])


def test_summarize_rpd_excludes_invalid_runs():
    s = summarize_rpd([53, None, 50, 55], [50, 50, 50, 50])
    assert s["runs"] == 4 and s["valid"] == 3
    assert s["share_valid"] == pytest.approx(0.75)
    assert s["arpd"] == pytest.approx((6 + 0 + 10) / 3)
    assert s["max_rpd"] == pytest.approx(10)
    assert s["share_at_reference"] == pytest.approx(1 / 3)


def test_summarize_rpd_all_invalid():
    s = summarize_rpd([None, None], [50, 60])
    assert s["valid"] == 0 and s["arpd"] is None


def _make_sample_module():
    sys.path.insert(0, str(SAMPLE_DIR))
    try:
        import make_sample
    finally:
        sys.path.remove(str(SAMPLE_DIR))
    return make_sample


def test_sample_choice_is_deterministic_and_stratified():
    ms = _make_sample_module()
    a, b = ms.choose(2026, 15), ms.choose(2026, 15)
    assert a == b
    assert ms.choose(1, 15) != a
    for set_name, n_params in ms.SETS.items():
        rows = [r for r in a if r[0] == set_name]
        assert [r[1] for r in rows] == list(range(1, n_params + 1))
        assert all(1 <= r[2] <= ms.INSTANCES_PER_PARAM for r in rows)
        assert sum(r[3] for r in rows) == 15


def test_committed_sample_matches_rule():
    ms = _make_sample_module()
    sample = json.loads((SAMPLE_DIR / "sample.json").read_text(encoding="utf-8"))
    chosen = ms.choose(sample["seed"], sample["pilot_size"] // len(ms.SETS))
    assert [(i["set"], i["param"], i["instance"], i["pilot"]) for i in sample["instances"]] == chosen
    assert sample["size"] == 108 and sample["pilot_size"] == 30
    for i in sample["instances"]:
        ref = i["reference"]
        assert ref["cpm"] <= ref["lb"] <= ref["bks"]
        assert set(i["indicators"]) == {"n", "cnc", "os", "sp", "ad", "la", "i5", "tf",
                                        "rf", "ru", "rs", "rc"}
