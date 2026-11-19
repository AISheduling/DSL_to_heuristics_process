"""Перенос триггера F1 на наборы RCPLIB (experiments/v2_counterexamples/run_benchmarks.py)."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "v2_counterexamples"))

import run_benchmarks as rb  # noqa: E402
from rcplib import RCPLIB_SETS  # noqa: E402
from priority_rules import RULES_V2  # noqa: E402

TRIG = {"LST": {"feature": "f1_pressure_free", "direction": ">", "threshold": 0.0564},
        "MTS": {"feature": "f1_pressure_free", "direction": ">", "threshold": 0.0564}}
TINY = "4 1\n5\n0 0 2 2 3\n3 2 1 4\n2 4 1 4\n0 0 0\n"          # 2 и 3 вместе не влезают
NO_RES = "3 0\n\n0 1 2\n4 1 3\n0 0\n"


@pytest.fixture
def tiny_root(tmp_path, monkeypatch):
    d = tmp_path / "inst" / "T" / "T"
    d.mkdir(parents=True)
    (d / "t1.rcp").write_text(TINY)
    (d / "t2.rcp").write_text(NO_RES)
    monkeypatch.setitem(RCPLIB_SETS, "T", ("T/T", "T"))
    return tmp_path


def test_evaluate_instance_rows(tiny_root):
    row, rules = rb.evaluate_instance("T", "t1", tiny_root / "inst/T/T/t1.rcp", None, TRIG)
    assert [r["rule"] for r in rules] == list(RULES_V2)
    assert all(r["makespan"] == 5 for r in rules)          # 2 и 3 только последовательно
    assert all(r["gap_vs_others"] == 0.0 for r in rules)
    assert row["n"] == 2 and row["n_res"] == 1 and row["cpm"] == 3
    assert row["best_rule_makespan"] == 5 and row["bks"] is None
    assert row["fired_LST"] is False and row["lost_LST"] is False


def test_zero_resource_instance(tiny_root):
    row, rules = rb.evaluate_instance("T", "t2", tiny_root / "inst/T/T/t2.rcp", None, TRIG)
    assert row["n_res"] == 0 and row["f1_pressure_free"] == 0
    assert {r["makespan"] for r in rules} == {row["cpm"]} == {4}
    assert row["fired_MTS"] is False


def test_fires_uses_threshold_and_direction():
    assert rb.fires(0.10, TRIG["LST"]) and not rb.fires(0.0, TRIG["LST"])
    assert not rb.fires(0.0564, TRIG["LST"])                     # Строго больше
    assert rb.fires(0.01, {**TRIG["LST"], "direction": "<"})


def test_lost_label_uses_delta():
    assert rb.lost(5.0) and not rb.lost(4.99)


def _row(set_name, fired, lost, value):
    return {"set": set_name, "fired_LST": fired, "lost_LST": lost, "gap_LST": 10.0 if lost else 0.0,
            "fired_MTS": False, "lost_MTS": False, "gap_MTS": 0.0, "f1_pressure_free": value,
            "n_res": 1}


def test_report_per_set_and_all():
    rows = [_row("A", True, True, 0.2), _row("A", False, False, 0.0),
            _row("B", True, False, 0.1), _row("B", False, True, 0.0)]
    rep = rb.build_report(rows)
    a, all_ = rep["sets"]["A"]["LST"], rep["sets"]["ALL"]["LST"]
    assert (a["n"], a["fired"], a["positives"], a["precision"]) == (2, 1, 1, 1.0)
    assert (all_["n"], all_["fired"], all_["positives"], all_["precision"]) == (4, 2, 2, 0.5)
    assert all_["balanced_accuracy"] == 0.5


def test_report_handles_no_positives():
    rows = [_row("A", False, False, 0.0), _row("A", False, False, 0.0)]
    rep = rb.build_report(rows)
    assert rep["sets"]["A"]["LST"]["precision"] is None
    md = rb.to_markdown(rep, TRIG)
    assert "—" in md and "0.0564" in md


def test_main_writes_outputs(tiny_root):
    trig_file = tiny_root / "triggers.json"
    trig_file.write_text(json.dumps(TRIG))
    args = ["--run", "r", "--sets", "T", "--workers", "1", "--no-references",
            "--results-dir", str(tiny_root / "res"), "--root", str(tiny_root / "inst"),
            "--triggers", str(trig_file)]
    for _ in range(2):                                           # Повтор перезаписывает
        summary = rb.main(args)
    run = tiny_root / "res" / "r"
    with (run / "bench_instances.csv").open(encoding="utf-8") as f:
        inst = list(csv.DictReader(f))
    with (run / "bench_rules.csv").open(encoding="utf-8") as f:
        rules = list(csv.DictReader(f))
    assert [r["id"] for r in inst] == ["t1", "t2"] and len(rules) == 2 * len(RULES_V2)
    cand = json.loads((run / "candidates.json").read_text(encoding="utf-8"))
    assert cand["threshold"] == 0.0564 and cand["instances"] == []
    assert json.loads((run / "bench_triggers.json").read_text(encoding="utf-8"))["sets"]["T"]
    assert "0.0564" in (run / "bench_triggers.md").read_text(encoding="utf-8")
    assert summary["instances"] == {"T": 2} and summary["fired_LST"] == {"T": 0}


def test_default_threshold_comes_from_f1_grid():
    trig = json.loads(rb.TRIGGERS.read_text(encoding="utf-8"))
    assert trig["LST"]["threshold"] == 0.05639177443290227


def test_unused_resource_does_not_break(tiny_root):
    # Второй ресурс есть в файле, но спрос на него нулевой у всех работ
    p = tiny_root / "inst/T/T/t3.rcp"
    p.write_text("4 2\n5 9\n0 0 0 2 2 3\n3 2 0 1 4\n2 4 0 1 4\n0 0 0 0\n")
    row, rules = rb.evaluate_instance("T", "t3", p, None, TRIG)
    assert row["n_res"] == 2 and {r["makespan"] for r in rules} == {5}


def test_extra_set_without_references(tmp_path):
    # DSLIB: .rcp в своем каталоге, эталонов нет
    d = tmp_path / "dslib"
    d.mkdir()
    (d / "C2099-02.rcp").write_text(TINY)
    (d / "C2099-10.rcp").write_text(NO_RES)
    trig = tmp_path / "triggers.json"
    trig.write_text(json.dumps(TRIG))
    summary = rb.main(["--run", "d", "--sets", "DSLIB", "--extra-root", str(d), "--workers", "1",
                       "--results-dir", str(tmp_path / "res"), "--triggers", str(trig)])
    with (tmp_path / "res" / "d" / "bench_instances.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(r["set"], r["id"], r["bks"]) for r in rows] == [("DSLIB", "C2099-02", ""), ("DSLIB", "C2099-10", "")]
    assert summary["instances"] == {"DSLIB": 2}


def test_default_sets_unchanged(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(rb, "load_rcplib_references", lambda s, **k: seen.setdefault(s, {}) or {})
    monkeypatch.setattr(rb, "iter_rcplib_set", lambda s, root: iter(()))
    rb.main(["--run", "x", "--workers", "1", "--results-dir", str(tmp_path)])
    assert list(seen) == list(RCPLIB_SETS) and "DSLIB" not in seen
