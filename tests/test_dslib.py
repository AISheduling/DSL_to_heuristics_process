"""
Конвертер DSLIB (src/dslib.py): разбор строк Excel, проект -> инстанс RCPSP, запись .rcp.

Проверки на данных пропускаются, если DSLIB не распакован (data/dslib/SOURCES.md).
"""
from __future__ import annotations

import pytest

from dslib import DSLIBUnsupported, parse_availability, parse_demand, parse_duration_hours, scale_factor


@pytest.mark.parametrize("s,h", [("3d", 24), ("7h", 7), ("1d 4h", 12), ("1d4h", 12), ("1d 4h ", 12),
                                 ("2 days", 16), ("2,5 days", 20), ("0", 0), ("0.5h", 1)])
def test_duration(s, h):
    assert parse_duration_hours(s, 8) == h


@pytest.mark.parametrize("s", ["5", "3w", "abc", ""])
def test_duration_bad(s):
    with pytest.raises(DSLIBUnsupported):
        parse_duration_hours(s, 8)


def test_demand():
    assert parse_demand("Analyst programmer;IT Manager[0.20 #1]") == {"Analyst programmer": 1, "IT Manager": 0.2}
    assert parse_demand("Labourers[2.00 #10];Materials[10000.00F #-1];Crane") == {"Labourers": 2, "Crane": 1}
    assert parse_demand("A[1,50 #3];B[50%];A[1];") == {"A": 2.5, "B": 0.5}
    assert parse_demand("") == {}


def test_availability():
    assert parse_availability("3 Programmers") == 3
    assert parse_availability("1,5 X") == 1.5
    assert parse_availability(2) == 2
    with pytest.raises(DSLIBUnsupported):
        parse_availability("Programmers")


def test_scale():
    assert scale_factor([1, 2]) == 1
    assert scale_factor([0.2, 3]) == 10
    assert scale_factor([0.25]) == 100


def test_scale_bad():
    with pytest.raises(DSLIBUnsupported):
        scale_factor([1 / 3])


# convert_project на маленьких книгах

from dslib import convert_project  # noqa: E402

HEAD = ["ID", "Name", "WBS", "Predecessors", "Successors", "Baseline Start", "Baseline End",
        "Duration", "Resource Demand"]
RES = [("R", "Renewable", "3 R"), ("M", "Renewable", "1 M"), ("Mat", "Consumable", "100 Mat")]


def make_xlsx(path, rows, resources=RES, hours=8, sheet="Baseline Schedule", avail="Availability"):
    """
    rows: (ID, WBS, Predecessors, Duration, Resource Demand);
    None — пустая ячейка.
    """
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["General"])
    ws.append(HEAD)
    for i, wbs, pred, dur, dem in rows:
        ws.append([i, f"task {i}", wbs, pred, None, None, None, dur, dem])
    rs = wb.create_sheet("Resources")
    rs.append(["General"])
    rs.append(["ID", "Name", "Type", avail])
    for k, (name, typ, avail) in enumerate(resources, 1):
        rs.append([k, name, typ, avail])
    if hours is not None:                             # None — листа Agenda нет (C2024-02)
        ag = wb.create_sheet("Agenda")
        ag.append(["Working Hours", None])
        for h in range(24):
            ag.append([f"{h}:00 - {h + 1}:00", "Yes" if 8 <= h < 8 + hours else "No"])
    wb.save(path)
    return path


# Сводки 0 ("1") и 1 ("1.1"); листья с ID Excel 3, 7, 9, 12 -> работы 2..5
BASE = [(0, "1", None, None, None), (1, "1.1", None, None, None),
        (7, "1.1.1", None, "1d", "R[2.00 #1]"), (3, "1.1.2", "7", "4h", "R;Mat[5.00F #-1]"),
        (9, "1.2", "1", "1d 4h", "M[0.20 #1]"), (12, "1.3", "9FS", "0", None)]


def _preds(inst, rep, excel_id):
    job = {v: k for k, v in rep["excel_ids"].items()}[excel_id]
    to_excel = {k: v for k, v in rep["excel_ids"].items()}
    return {to_excel.get(p, p) for p in inst["jobs"][job - 1]["predecessors"]}


def test_summary_expansion_and_numbering(tmp_path):
    inst, rep = convert_project(make_xlsx(tmp_path / "C2099-01 X.xlsx", BASE))
    assert rep["excel_ids"] == {2: 3, 3: 7, 4: 9, 5: 12}
    assert _preds(inst, rep, 9) == {3, 7}              # Предшественник — сводка 1.1
    assert _preds(inst, rep, 3) == {7}
    assert _preds(inst, rep, 7) == {1}                 # supersource
    assert inst["jobs"][-1]["predecessors"] == [5]             # supersink после вехи
    assert inst["case_info"]["id"] == "C2099-01" and rep["summary_rows"] == 2


def test_hours_and_milestone(tmp_path):
    inst, rep = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE))
    dur = {rep["excel_ids"][j["id"]]: j["duration"] for j in inst["jobs"] if j["id"] in rep["excel_ids"]}
    assert dur == {3: 4, 7: 8, 9: 12, 12: 0} and rep["milestones"] == 1 and rep["hours_per_day"] == 8


def test_fractional_scale_and_consumable(tmp_path):
    inst, rep = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE))
    assert [(r["name"], r["capacity"]) for r in inst["resources"]] == [("R", 3), ("M", 10)]
    assert rep["scales"] == {"R": 1, "M": 10}
    job9 = inst["jobs"][3]
    assert job9["resource_requirements"] == [{"resource_id": 2, "amount": 2}]


def test_hours_per_day_from_agenda(tmp_path):
    _, rep = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE, hours=9))
    assert rep["hours_per_day"] == 9


@pytest.mark.parametrize("pred", ["7SS", "7FS+1d", "7FF", "7SF", "7FS-2w"])
def test_non_fs_rejected(tmp_path, pred):
    rows = [r if r[0] != 3 else (3, "1.1.2", pred, "4h", "R") for r in BASE]
    with pytest.raises(DSLIBUnsupported, match="связь"):
        convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", rows))


@pytest.mark.parametrize("change,reason", [
    ((7, "1.1.1", None, "1d", "R[4.00 #1]"), "спрос больше мощности"),
    ((7, "1.1.1", None, "1d", "Crane"), "ресурс не найден"),
    ((7, "1.1.1", None, None, "R"), "пустая длительность"),
])
def test_rejections(tmp_path, change, reason):
    rows = [change if r[0] == change[0] else r for r in BASE]
    with pytest.raises(DSLIBUnsupported, match=reason):
        convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", rows))


def test_no_baseline_sheet(tmp_path):
    with pytest.raises(DSLIBUnsupported, match="нет листа"):
        convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE, sheet="Baseline Schedule1"))


def test_no_renewable_demand(tmp_path):
    rows = [(i, w, p, d, None) for i, w, p, d, _ in BASE]
    with pytest.raises(DSLIBUnsupported, match="нет возобновляемых"):
        convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", rows))


def test_duplicate_id(tmp_path):
    with pytest.raises(DSLIBUnsupported, match="повтор ID"):
        convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE + [(7, "1.4", None, "1d", "R")]))


def test_root_without_wbs_and_duplicate_wbs(tmp_path):
    # Корень без WBS (как C2023-01) и две сводки с WBS "1" (как C2025-07)
    rows = [(100, None, None, None, None), (101, "1", None, None, None)] + BASE
    inst, rep = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", rows))
    assert sorted(rep["excel_ids"].values()) == [3, 7, 9, 12] and rep["summary_rows"] == 3


def test_feeds_kernel_and_checker(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "v2_counterexamples"))
    from run_rules import makespans, rule_schedules
    inst, _ = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE))
    ms = makespans(inst, rule_schedules(inst))
    assert min(ms.values()) == 24               # Цепочка 7 -> 3 -> 9: 8 + 4 + 12 ч


# Запись .rcp, конвертация каталога

from dslib import DSLIB_EXCEL, convert_all, write_rcp  # noqa: E402
from rcplib import parse_rcp_file, parse_rcp_text  # noqa: E402

needs_dslib = pytest.mark.skipif(not DSLIB_EXCEL.exists(), reason="DSLIB не распакован (data/dslib/SOURCES.md)")


def test_write_rcp_roundtrip(tmp_path):
    inst, _ = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE))
    back = parse_rcp_text(write_rcp(inst), "x")
    strip = lambda js: [(j["id"], j["duration"], sorted(j["successors"]), sorted(j["predecessors"]),
                         j["resource_requirements"]) for j in js]
    assert strip(back["jobs"]) == strip(inst["jobs"])
    assert [r["capacity"] for r in back["resources"]] == [r["capacity"] for r in inst["resources"]]


def test_convert_all(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_xlsx(src / "C2099-01 Good.xlsx", BASE)
    make_xlsx(src / "C2099-02 Bad.xlsx", [r if r[0] != 3 else (3, "1.1.2", "7SS", "4h", "R") for r in BASE])
    man = convert_all(src=src, out=tmp_path / "out", analysis=None)
    got = {p["code"]: (p["included"], p["reason"]) for p in man["projects"]}
    assert got == {"C2099-01": (True, None), "C2099-02": (False, "связь не FS без лага: 7SS")}
    assert sorted(p.name for p in (tmp_path / "out").glob("*.rcp")) == ["C2099-01.rcp"]
    assert (tmp_path / "out" / "manifest.json").exists()


@needs_dslib
def test_real_conversion(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "v2_counterexamples"))
    from run_rules import makespans, rule_schedules
    man = convert_all(out=tmp_path)
    assert len(man["projects"]) == 231
    ok = [p for p in man["projects"] if p["included"]]
    assert 40 <= len(ok) <= 53              # 53 — верхняя граница по предварительному подсчету
    for p in ok:                            # каждый .rcp читается, все правила проходят чекер
        inst = parse_rcp_file(tmp_path / f"{p['code']}.rcp")
        makespans(inst, rule_schedules(inst))


def test_clean_treats_pandas_missing_as_empty():
    # C2018-08: пустые строки в конце листа; iterrows дает в них NaT, а не NaN
    import pandas as pd
    from dslib import _clean
    assert _clean(pd.NaT) == "" and _clean(float("nan")) == "" and _clean(None) == "" and _clean(pd.NA) == ""
    assert _clean(" 1.2 ") == "1.2" and _clean(3.0) == "3.0"


def test_misspelled_availability_column(tmp_path):
    # C2023-01, C2023-05, C2025-07: заголовок 'Availibility'
    inst, _ = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE, avail="Availibility"))
    assert [r["capacity"] for r in inst["resources"]] == [3, 10]


def test_missing_agenda_defaults_to_8_hours(tmp_path):
    inst, rep = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", BASE, hours=None))
    assert rep["hours_per_day"] == 8 and rep["hours_per_day_source"] == "default"


def test_flat_project_without_wbs(tmp_path):
    # C2023-01: колонка WBS пуста у всех строк — проект плоский, корень (без длительности) пропускается
    rows = [(0, None, None, None, None), (7, None, None, "1d", "R[2.00 #1]"), (3, None, "7", "4h", "R")]
    inst, rep = convert_project(make_xlsx(tmp_path / "C2099-01.xlsx", rows))
    assert rep["excel_ids"] == {2: 3, 3: 7} and rep["summary_rows"] == 0
    assert _preds(inst, rep, 3) == {7}
