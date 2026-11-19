"""
Наборы RCPLIB (src/rcplib.py): разбор формата Паттерсона, перечень наборов, эталоны.

Проверки на данных пропускаются, если RCPLIB v2.4 не скачан (data/rcplib/SOURCES.md).
"""
from __future__ import annotations

import pytest

from indicators import flat_indicators
from rcplib import (RCPLIB_INSTANCES, RCPLIB_RELEASE_FILE, RCPLIB_SETS, RCPFormatError,
                    iter_rcplib_set, load_rcplib_references, parse_rcp_file, parse_rcp_text)
from references import Reference, ReferenceError

needs_instances = pytest.mark.skipif(not RCPLIB_INSTANCES.exists(),
                                     reason="RCPLIB v2.4 не распакован (data/rcplib/SOURCES.md)")
needs_release = pytest.mark.skipif(not (RCPLIB_INSTANCES.exists() and RCPLIB_RELEASE_FILE.exists()),
                                   reason="RCPLIB v2.4 не распакован (data/rcplib/SOURCES.md)")

# 4 работы, 1 ресурс мощностью 5: 1 -> {2, 3} -> 4
TINY = "4 1\n5\n0 0 2 2 3\n3 2 1 4\n2 4 1 4\n0 0 0\n"


def test_parse_tiny():
    inst = parse_rcp_text(TINY, "t")
    assert [j["id"] for j in inst["jobs"]] == [1, 2, 3, 4]
    assert inst["jobs"][0]["successors"] == [2, 3]
    assert inst["jobs"][3]["predecessors"] == [2, 3]
    assert inst["jobs"][1]["duration"] == 3
    assert inst["jobs"][1]["resource_requirements"] == [{"resource_id": 1, "amount": 2}]
    assert inst["jobs"][0]["resource_requirements"] == []
    assert inst["resources"] == [{"id": 1, "name": "R1", "capacity": 5, "type": "renewable"}]
    assert inst["project_goal"] == {"objective_function": "min_makespan"}
    assert inst["case_info"]["id"] == "t" and inst["case_info"]["source"] == "RCPLIB"


def test_zero_resources():
    inst = parse_rcp_text("3 0\n\n0 1 2\n4 1 3\n0 0\n", "z")
    assert inst["resources"] == []
    assert inst["jobs"][1]["duration"] == 4
    assert inst["jobs"][2]["predecessors"] == [2]


def test_zero_duration_inner_job_keeps_links():
    text = "4 1\n2\n0 0 1 2\n0 1 1 3\n5 1 1 4\n0 0 0\n"
    inst = parse_rcp_text(text, "d")
    assert inst["jobs"][1]["duration"] == 0
    assert inst["jobs"][2]["predecessors"] == [2]


@pytest.mark.parametrize("bad", [
    TINY + "7",                                # Лишнее число
    "4 1\n5\n0 0 2 2",                         # Файл оборван
    TINY.replace("2 4 1 4", "2 4 1 9"),        # Преемник вне 1..n
    TINY.replace("3 2 1 4", "-3 2 1 4"),       # Отрицательная длительность
    "4 1\n5\n0 0 2 2 x\n",                     # Не число
])
def test_bad_format(bad):
    with pytest.raises(RCPFormatError):
        parse_rcp_text(bad, "b")


def test_parse_file_default_id(tmp_path):
    p = tmp_path / "cv7.rcp"
    p.write_text(TINY)
    assert parse_rcp_file(p)["case_info"]["id"] == "cv7"


def test_iter_natural_order(tmp_path, monkeypatch):
    d = tmp_path / "X" / "X"
    (d / "Set 1").mkdir(parents=True)
    for name in ("a2.rcp", "a10.rcp", "a1.rcp", "Set 1/Pat1.rcp"):
        (d / name).write_text(TINY)
    (d / "notes.xls").write_text("")
    monkeypatch.setitem(RCPLIB_SETS, "X", ("X/X", "X"))
    ids = [i for i, _ in iter_rcplib_set("X", root=tmp_path)]
    assert ids == ["a1", "a2", "a10", "Set 1/Pat1"]  # Числа как числа, регистр не важен


def test_unknown_set():
    with pytest.raises(KeyError):
        list(iter_rcplib_set("nope"))


@needs_instances
def test_set_sizes():
    sizes = {s: sum(1 for _ in iter_rcplib_set(s)) for s in RCPLIB_SETS}
    assert sizes == {"RG30": 1800, "VNR": 1750, "sD": 390, "CV": 623, "DC1": 1800,
                     "DC2": 720, "RG300": 480, "LPP": 80, "LPSP": 81}


@needs_instances
@pytest.mark.parametrize("set_name", list(RCPLIB_SETS))
def test_instances_feed_indicators(set_name):
    for k, (inst_id, path) in enumerate(iter_rcplib_set(set_name)):
        if k == 5:
            break
        assert flat_indicators(parse_rcp_file(path, inst_id))["n"] > 0


# Эталоны из Excel. TINY: CPM = 1 -> 2 -> 4 = 3 (работа 2 длиннее работы 3).

def _workbook(path, sheet, rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["ID", "FileName", "CPM", "LB-lit", "UB-lit"])
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


@pytest.fixture
def tiny_set(tmp_path, monkeypatch):
    d = tmp_path / "inst" / "X" / "X"
    (d / "Set 1").mkdir(parents=True)
    (d / "a1.rcp").write_text(TINY)
    (d / "Set 1" / "Pat2.rcp").write_text(TINY)
    monkeypatch.setitem(RCPLIB_SETS, "X", ("X/X", "SheetX"))
    return tmp_path


def test_references_from_small_workbook(tiny_set):
    wb = _workbook(tiny_set / "b.xlsx", "SheetX",
                   [[1, "A1.rcp", 3, 4, 6], [2, r"Set 1\Pat2.rcp", 3, 2, 3], [3, "other.rcp", 9, 9, 9]])
    refs = load_rcplib_references("X", path=wb, root=tiny_set / "inst")
    assert refs == {"a1": Reference(cpm=3, lb=4, bks=6, bks_source="rcplib", optimal=False),
                    "Set 1/Pat2": Reference(cpm=3, lb=3, bks=3, bks_source="rcplib", optimal=True)}


@pytest.mark.parametrize("rows", [
    [[1, "a1.rcp", 4, 4, 6], [2, r"Set 1\Pat2.rcp", 3, 3, 3]],   # CPM не совпал с расчетом
    [[1, "a1.rcp", 3, 7, 6], [2, r"Set 1\Pat2.rcp", 3, 3, 3]],   # LB > UB
    [[1, "a1.rcp", 3, 3, 6]],                                    # Нет строки для Set 1/Pat2
])
def test_inconsistent_references_raise(tiny_set, rows):
    wb = _workbook(tiny_set / "b.xlsx", "SheetX", rows)
    with pytest.raises(ReferenceError):
        load_rcplib_references("X", path=wb, root=tiny_set / "inst")


@needs_release
@pytest.mark.parametrize("set_name", list(RCPLIB_SETS))
def test_real_references(set_name):
    # Внутри load_rcplib_references CPM сверяется с расчетом на каждом инстансе
    refs = load_rcplib_references(set_name)
    assert len(refs) == sum(1 for _ in iter_rcplib_set(set_name))
    assert all(r.cpm <= r.lb <= r.bks for r in refs.values())
