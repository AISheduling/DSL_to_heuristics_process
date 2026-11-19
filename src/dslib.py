from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DSLIB_DIR = ROOT / "data" / "dslib"
DSLIB_EXCEL = DSLIB_DIR / "release" / "DSLIB 3.4" / "Excel"
DSLIB_INSTANCES = DSLIB_DIR / "instances"
DSLIB_ANALYSIS = DSLIB_DIR / "release" / "DSLIB 3.4" / "DSLIB_Analysis_Sheet.xlsx"

_NUM = r"\d+(?:[.,]\d+)?"
_FS = re.compile(r"(\d+)(?:FS)?")


class DSLIBUnsupported(ValueError):
    """Проект не переводится в RCPSP без искажений; текст — причина для манифеста."""


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_duration_hours(text: str, hours_per_day: int) -> int:
    """'3d', '7h', '1d 4h', '2,5 days', '0' -> целые часы (дробные — вверх)."""
    s = str(text).strip()
    if s == "0":
        return 0
    m = re.fullmatch(rf"(?:({_NUM})\s*d)?\s*(?:({_NUM})\s*h)?", s)
    if m and (m.group(1) or m.group(2)):
        hours = _num(m.group(1) or "0") * hours_per_day + _num(m.group(2) or "0")
        return math.ceil(hours - 1e-9)
    m = re.fullmatch(rf"({_NUM})\s*days?", s)
    if m:
        return math.ceil(_num(m.group(1)) * hours_per_day - 1e-9)
    # голое ненулевое число: единица не указана
    raise DSLIBUnsupported(f"длительность не разобрана: {s!r}")


def parse_demand(text: str) -> dict[str, float]:
    """
    'Имя;Имя[1.50 #3];Имя[50%]' -> {имя: количество};
    расходуемые ('...F') пропускаются.
    """
    out: dict[str, float] = {}
    for item in str(text).split(";"):
        item = item.strip()
        if not item:
            continue
        m = re.fullmatch(r"(.*?)\s*\[(.*)\]", item)
        if not m:
            name, qty = item, 1.0
        else:
            name, inside = m.group(1).strip(), m.group(2).strip()
            q = re.match(rf"({_NUM})\s*(%|F)?", inside)
            if not q:
                raise DSLIBUnsupported(f"спрос не разобран: {item!r}")
            if q.group(2) == "F":
                continue
            qty = _num(q.group(1)) / (100 if q.group(2) == "%" else 1)
        out[name] = out.get(name, 0.0) + qty
    return out


def parse_availability(text) -> float:
    """'3 Programmers' -> 3: мощность ресурса с листа Resources."""
    m = re.search(_NUM, str(text))
    if not m:
        raise DSLIBUnsupported(f"мощность не разобрана: {text!r}")
    return _num(m.group(0))


def scale_factor(values: list[float]) -> int:
    """Наименьший множитель 1, 10 или 100, после которого все значения целые."""
    for f in (1, 10, 100):
        if all(abs(v * f - round(v * f)) < 1e-9 for v in values):
            return f
    raise DSLIBUnsupported(f"дробь не приводится к целому множителем 100: {values}")


def _hours_per_day(xls) -> int:
    """Число рабочих часов в дне — строки 'Yes' в колонке часов листа Agenda."""
    import pandas as pd

    if "Agenda" not in xls.sheet_names:
        return 0                     # Нет листа: вызывающий берет 8 ч (стандарт ProTrack)
    ag = pd.read_excel(xls, "Agenda", header=None)
    hours = [str(v).strip() for lab, v in zip(ag[0], ag[1]) if re.fullmatch(r"\d+:\d+\s*-\s*\d+:\d+", str(lab).strip())]
    n = sum(v == "Yes" for v in hours)
    if not n:
        raise DSLIBUnsupported("в Agenda нет рабочих часов")
    return n


def _clean(v) -> str:
    """Ячейка -> строка; пустые значения pandas (NaN, NaT, NA) -> ''."""
    import pandas as pd

    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    return str(v).strip()


def convert_project(path: str | Path) -> tuple[dict, dict]:
    """
    Excel проекта DSLIB -> (инстанс в форме rcplib.parse_rcp_text, отчет).
    Работы — листья WBS; связь на сводку раскрывается на все ее листья.
    """
    import pandas as pd

    path = Path(path)
    code = path.stem.split(" ")[0]
    xls = pd.ExcelFile(path)
    if "Baseline Schedule" not in xls.sheet_names:
        raise DSLIBUnsupported("нет листа Baseline Schedule")
    text_cols = {c: str for c in ("WBS", "Predecessors", "Duration", "Resource Demand")}
    b = pd.read_excel(xls, "Baseline Schedule", header=1, dtype=text_cols)
    rows = []                                  # (excel_id, wbs, предшественники, длительность, спрос)
    seen = set()
    # Плоский проект (C2023-01): WBS пуст у всех строк — работа каждая строка с длительностью
    flat = all(_clean(w) == "" for w in b["WBS"])
    for _, r in b.iterrows():
        if _clean(r["ID"]) == "":
            continue
        eid = int(float(r["ID"]))
        wbs = _clean(r["WBS"])
        if flat:
            if _clean(r["Duration"]) == "":
                continue                       # Корень проекта
            wbs = f"#{eid}"                    # Уникальный код без дочерних
        elif wbs == "":
            continue                           # Корень проекта без WBS
        if eid in seen:
            raise DSLIBUnsupported(f"повтор ID {eid}")
        seen.add(eid)
        rows.append((eid, wbs, _clean(r["Predecessors"]), _clean(r["Duration"]),
                     _clean(r["Resource Demand"])))
    codes = [w for _, w, *_ in rows]
    is_leaf = {eid: not any(c.startswith(w + ".") for c in codes) for eid, w, *_ in rows}
    leaves_of = {eid: ([eid] if is_leaf[eid] else
                       [e for e, w2, *_ in rows if is_leaf[e] and w2.startswith(w + ".")])
                 for eid, w, *_ in rows}

    # Связи: только 'N' или 'NFS'
    preds: dict[int, set[int]] = {eid: set() for eid in leaves_of if is_leaf[eid]}
    for eid, _, pred, _, _ in rows:
        for tok in (t.strip() for t in re.split(r"[;,]", pred) if t.strip()):
            m = _FS.fullmatch(tok)
            if not m:
                raise DSLIBUnsupported(f"связь не FS без лага: {tok}")
            src = int(m.group(1))
            if src not in leaves_of:
                raise DSLIBUnsupported(f"неизвестный предшественник {src} у {eid}")
            for t in leaves_of[eid]:
                preds[t].update(s for s in leaves_of[src] if s != t)

    hpd = _hours_per_day(xls)
    hpd_source = "agenda" if hpd else "default"
    hpd = hpd or 8
    leaves = sorted(preds)
    duration, demand = {}, {}
    for eid, _, _, dur, dem in rows:
        if not is_leaf[eid]:
            continue
        if dur == "":
            raise DSLIBUnsupported(f"пустая длительность у работы {eid}")
        duration[eid] = parse_duration_hours(dur, hpd)
        demand[eid] = parse_demand(dem)

    rs = pd.read_excel(xls, "Resources", header=1)
    # В части файлов заголовок с опечаткой 'Availibility'
    avail = next((c for c in rs.columns if str(c).strip().lower().startswith("avail")), None)
    if avail is None:
        raise DSLIBUnsupported("на листе Resources нет колонки мощности")
    sheet = [(_clean(r["Name"]), _clean(r["Type"]).lower(), r[avail])
             for _, r in rs.iterrows() if _clean(r.get("Name")) != ""]
    known = {name for name, *_ in sheet}
    for eid in leaves:
        for name in demand[eid]:
            if name not in known:
                raise DSLIBUnsupported(f"ресурс не найден: {name}")
    used = [(name, parse_availability(avail)) for name, typ, avail in sheet
            if typ.startswith("renew") and any(demand[e].get(name, 0) > 0 for e in leaves)]
    if not used:
        raise DSLIBUnsupported("нет возобновляемых ресурсов со спросом")

    scales, resources = {}, []
    for k, (name, cap) in enumerate(used, 1):
        f = scale_factor([cap] + [demand[e][name] for e in leaves if name in demand[e]])
        scales[name] = f
        resources.append({"id": k, "name": name, "capacity": round(cap * f), "type": "renewable"})
        for e in leaves:
            if demand[e].get(name, 0) * f > cap * f + 1e-9:
                raise DSLIBUnsupported(f"спрос больше мощности: {name} у работы {e}")

    job_of = {eid: i + 2 for i, eid in enumerate(leaves)}
    n = len(leaves) + 2
    jobs = [{"id": 1, "name": "Supersource", "predecessors": [], "successors": [], "duration": 0,
             "resource_requirements": []}]
    for eid in leaves:
        req = [{"resource_id": r["id"], "amount": round(demand[eid][r["name"]] * scales[r["name"]])}
               for r in resources if demand[eid].get(r["name"], 0) > 0]
        jobs.append({"id": job_of[eid], "predecessors": sorted(job_of[p] for p in preds[eid]) or [1],
                     "successors": [], "duration": duration[eid], "resource_requirements": req})
    jobs.append({"id": n, "name": "Supersink", "predecessors": [], "successors": [], "duration": 0,
                 "resource_requirements": []})
    for j in jobs[1:-1]:
        for p in j["predecessors"]:
            jobs[p - 1]["successors"].append(j["id"])
    for j in jobs[1:-1]:
        if not j["successors"]:
            j["successors"].append(n)
            jobs[-1]["predecessors"].append(j["id"])
    for j in jobs:
        j["successors"].sort()

    instance = {
        "case_info": {"id": code, "source": "DSLIB",
                      "description": f"DSLIB {code}: {len(leaves)} jobs, {len(resources)} renewable resources, hours",
                      "type": "RCPSP"},
        "project_goal": {"objective_function": "min_makespan"},
        "resources": resources,
        "jobs": jobs,
    }
    report = {"code": code, "n": len(leaves), "K": len(resources), "hours_per_day": hpd, "hours_per_day_source": hpd_source, "scales": scales,
              "milestones": sum(duration[e] == 0 for e in leaves), "summary_rows": len(rows) - len(leaves),
              "excel_ids": {job_of[e]: e for e in leaves}}
    return instance, report


def write_rcp(instance: dict) -> str:
    """Инстанс -> текст в формате Паттерсона (обратно rcplib.parse_rcp_text)."""
    res = instance["resources"]
    lines = [f"{len(instance['jobs'])} {len(res)}", " ".join(str(r["capacity"]) for r in res)]
    for j in instance["jobs"]:
        dem = {r["resource_id"]: r["amount"] for r in j["resource_requirements"]}
        row = [j["duration"], *(dem.get(r["id"], 0) for r in res), len(j["successors"]), *j["successors"]]
        lines.append(" ".join(map(str, row)))
    return "\n".join(lines) + "\n"


def _analysis(path: Path | None) -> dict[str, dict]:
    """Код проекта -> сектор и допустимость базового плана с листа DSLIB анализа."""
    if path is None or not Path(path).exists():
        return {}
    import pandas as pd

    raw = pd.read_excel(path, sheet_name="DSLIB", header=None)
    h = raw.index[raw[0].astype(str).str.strip() == "Code"][0]
    a = raw.iloc[h + 1:].copy()
    a.columns = [str(c).strip() for c in raw.iloc[h]]
    out = {}
    for _, r in a.iterrows():
        conflict = _clean(r.get("Resource Conflict in Schedule"))
        out[_clean(r["Code"])] = {"sector": _clean(r.get("Sector")) or None,
                                  "baseline_feasible": {"Resource Feasible": True, "Resource Conflict": False}.get(conflict)}
    return out


def convert_all(src: Path = DSLIB_EXCEL, out: Path = DSLIB_INSTANCES,
                analysis: Path | None = DSLIB_ANALYSIS) -> dict:
    """Все книги каталога -> <код>.rcp и manifest.json с решением по каждому проекту."""
    import json
    from datetime import datetime, timezone

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    meta = _analysis(analysis)
    projects = []
    for f in sorted(Path(src).glob("*.xlsx")):
        code = f.stem.split(" ")[0]
        rec = {"code": code, "file": f.name, "included": False, "reason": None}
        try:
            inst, rep = convert_project(f)
        except DSLIBUnsupported as e:
            rec["reason"] = str(e)
        else:
            (out / f"{code}.rcp").write_text(write_rcp(inst), encoding="utf-8")
            rep.pop("excel_ids")
            rec.update(rep, included=True)
        rec.update(meta.get(code, {}))
        projects.append(rec)
    manifest = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "DSLIB v3.4", "projects": projects}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> dict:
    import argparse
    from collections import Counter

    parser = argparse.ArgumentParser(description="DSLIB -> .rcp для проектов со связями FS без лага.")
    parser.add_argument("--src", type=Path, default=DSLIB_EXCEL)
    parser.add_argument("--out", type=Path, default=DSLIB_INSTANCES)
    args = parser.parse_args(argv)
    man = convert_all(args.src, args.out)
    ok = sum(p["included"] for p in man["projects"])
    print(f"взято {ok} из {len(man['projects'])}")
    reasons = Counter(re.sub(r"[:].*", "", p["reason"]) for p in man["projects"] if not p["included"])
    for r, k in reasons.most_common():
        print(f"  {k:4} {r}")
    return man


if __name__ == "__main__":
    main()
