"""
Эталоны PSPLIB (src/references.py) и файлы решений (psplib.parse_solution_file).

Проверки на данных пропускаются, если PSPLIB / RCPLIB не скачаны
(data/psplib/SOURCES.md, data/rcplib/SOURCES.md).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from psplib import PSPLIBFormatError, instance_name, iter_set, parse_solution_file
from references import RCPLIB_FILE, ReferenceError, load_rcplib, load_references

ROOT = Path(__file__).resolve().parents[1]
PSPLIB_DIR = ROOT / "data" / "psplib"
needs_psplib = pytest.mark.skipif(not (PSPLIB_DIR / "instances").exists(),
                                  reason="PSPLIB не скачан (data/psplib/SOURCES.md)")
needs_rcplib = pytest.mark.skipif(not RCPLIB_FILE.exists(),
                                  reason="RCPLIB не скачан (data/rcplib/SOURCES.md)")

_RCPLIB_CACHE: dict = {}


def _rcplib() -> dict:
    """RCPLIB читается из Excel один раз на модуль (около 3 с)."""
    if "data" not in _RCPLIB_CACHE:
        _RCPLIB_CACHE["data"] = load_rcplib()
    return _RCPLIB_CACHE["data"]


def test_parse_solution_file_skips_headers(tmp_path):
    p = tmp_path / "x_hrs.txt"
    p.write_text("solutionlist\n===\nPar  Inst  Makespan  Date  Author\n===\n"
                 "  1     1       43 Tue May 29 2007 R. E.\n  1    10       45 x\n"
                 " 48    10       54   0.01\n", encoding="latin-1")
    assert parse_solution_file(p) == {(1, 1): 43, (1, 10): 45, (48, 10): 54}


def test_parse_solution_file_rejects_duplicates(tmp_path):
    p = tmp_path / "dup.txt"
    p.write_text("1 1 43\n1 1 44\n", encoding="latin-1")
    with pytest.raises(PSPLIBFormatError, match="повтор"):
        parse_solution_file(p)


def test_instance_name():
    assert instance_name("j30", 10, 1) == "j3010_1"
    assert instance_name("j120", 60, 10) == "j12060_10"


@needs_psplib
@pytest.mark.parametrize("fname, count", [("j30_opt", 480), ("j30_hrs", 480), ("j60_hrs", 480),
                                          ("j60_lb", 410), ("j120_hrs", 600), ("j120_lb", 184)])
def test_solution_file_counts(fname, count):
    assert len(parse_solution_file(PSPLIB_DIR / "solutions" / f"{fname}.txt")) == count


@needs_psplib
@pytest.mark.parametrize("set_name", ["j30", "j60", "j120"])
def test_cpm_equals_mpm_time_from_sm_header(set_name):
    # CPM из indicators (через references) совпадает с MPM-Time в заголовке каждого .sm
    refs = load_references(set_name, use_rcplib=False)
    for path in sorted((PSPLIB_DIR / "instances" / set_name).glob("*.sm")):
        m = re.search(r"PROJECT INFORMATION:.*?\n.*?\n\s*\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)",
                      path.read_text(encoding="utf-8"), re.S)
        assert refs[path.stem].cpm == int(m.group(1)), path.stem


@needs_psplib
def test_references_from_psplib_files_only():
    refs = load_references("j30", use_rcplib=False)
    opt = parse_solution_file(PSPLIB_DIR / "solutions" / "j30_opt.txt")
    assert len(refs) == 480
    assert all(r.optimal and r.bks == opt[(int(n[3:].split("_")[0]), int(n.split("_")[1]))]
               for n, r in refs.items())
    assert refs["j301_1"].bks == 43 and refs["j301_1"].cpm == 38


@needs_psplib
@needs_rcplib
@pytest.mark.parametrize("set_name, n, n_optimal", [("j30", 480, 480), ("j60", 480, 464),
                                                   ("j120", 600, 328)])
def test_references_with_rcplib(set_name, n, n_optimal):
    refs = load_references(set_name, rcplib=_rcplib())
    assert len(refs) == n
    assert sum(r.optimal for r in refs.values()) == n_optimal
    for name, r in refs.items():
        assert r.cpm <= r.lb <= r.bks, name
        assert r.optimal == (r.lb == r.bks)


@needs_psplib
@needs_rcplib
def test_bks_is_minimum_of_sources():
    # В RCPLIB v6 у 17 инстансов J120 UB-lit хуже, чем в hrs PSPLIB; берется лучшее
    refs = load_references("j120", rcplib=_rcplib())
    from_psplib = [n for n, r in refs.items() if r.bks_source == "psplib"]
    assert len(from_psplib) == 17
    rc = _rcplib()
    assert all(refs[n].bks < rc[n]["ub"] for n in from_psplib)


def test_contradicting_bounds_rejected(tmp_path):
    inst = tmp_path / "instances" / "j30"
    inst.mkdir(parents=True)
    (inst / "j301_1.sm").write_text((ROOT / "data" / "raw" / "1_j301_1.txt")
                                    .read_text(encoding="utf-8"), encoding="utf-8")
    sol = tmp_path / "solutions"
    sol.mkdir()
    (sol / "j30_hrs.txt").write_text("1 1 30\n", encoding="latin-1")  # меньше CPM = 38
    with pytest.raises(ReferenceError, match="больше BKS"):
        load_references("j30", psplib_dir=tmp_path, use_rcplib=False)


def test_iter_set_order_is_param_then_instance(tmp_path):
    d = tmp_path / "j30"
    d.mkdir()
    raw = (ROOT / "data" / "raw" / "1_j301_1.txt").read_text(encoding="utf-8")
    for stem in ("j3010_1", "j302_10", "j302_2"):
        (d / f"{stem}.sm").write_text(raw, encoding="utf-8")
    assert [n for n, _ in iter_set(d)] == ["j302_2", "j302_10", "j3010_1"]
