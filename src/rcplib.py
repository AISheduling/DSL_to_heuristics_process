from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
RCPLIB_DIR = ROOT / "data" / "rcplib"
RCPLIB_INSTANCES = RCPLIB_DIR / "instances"
RCPLIB_RELEASE_FILE = RCPLIB_DIR / "release" / "RCPLIB (Parameters and BKS).xlsx"

# Набор -> (каталог относительно RCPLIB_INSTANCES, лист Excel). MH не входит
# его инстансы — копии CV (лист MH ссылается на cvK), иначе двойной счет.
RCPLIB_SETS: dict[str, tuple[str, str]] = {
    "RG30": ("RG30/RG30", "RG30"), "VNR": ("VNR/VNR", "VNR"), "sD": ("sD/sD", "sD"),
    "CV": ("CV/CV", "CV"), "DC1": ("DC1/DC1", "DC"), "DC2": ("DC2/DC2", "DC"),
    "RG300": ("RG300/RG300", "RG300"), "LPP": ("LPP/LPP", "LPP"), "LPSP": ("LPSP/LPSP", "LPSP"),
}


class RCPFormatError(ValueError):
    """Файл не похож на одномодовый `.rcp` в формате Паттерсона."""


def parse_rcp_text(text: str, instance_id: str, source: str = "RCPLIB") -> dict:
    """Инстанс в той же форме, что psplib.parse_sm_text; срока проекта в `.rcp` нет."""
    try:
        nums = [int(t) for t in text.split()]
    except ValueError as e:
        raise RCPFormatError(f"{instance_id}: не число ({e})") from None
    pos = 0

    def take(k: int) -> list[int]:
        nonlocal pos
        if pos + k > len(nums):
            raise RCPFormatError(f"{instance_id}: файл оборван")
        chunk = nums[pos:pos + k]
        pos += k
        return chunk

    n, n_res = take(2)
    if n < 2 or n_res < 0:
        raise RCPFormatError(f"{instance_id}: n = {n}, K = {n_res}")
    capacities = take(n_res)
    jobs = []
    for j in range(1, n + 1):
        duration, *demand = take(1 + n_res)
        succ = take(take(1)[0])
        if duration < 0 or any(a < 0 for a in demand) or any(c < 0 for c in capacities):
            raise RCPFormatError(f"{instance_id}: работа {j}: отрицательное значение")
        if any(not 1 <= s <= n for s in succ):
            raise RCPFormatError(f"{instance_id}: работа {j}: преемник вне 1..{n}")
        job = {"id": j, "predecessors": [], "successors": succ, "duration": duration,
               "resource_requirements": [{"resource_id": k + 1, "amount": a}
                                         for k, a in enumerate(demand) if a > 0]}
        if j == 1:
            job["name"] = "Supersource"
        elif j == n:
            job["name"] = "Supersink"
        jobs.append(job)
    if pos != len(nums):
        raise RCPFormatError(f"{instance_id}: лишние числа после работы {n}")
    for job in jobs:
        for s in job["successors"]:
            jobs[s - 1]["predecessors"].append(job["id"])

    return {
        "case_info": {"id": instance_id, "source": source,
                      "description": (f"Standard RCPSP with {n - 2} jobs and {n_res} "
                                      f"renewable resources (Single Mode)"),
                      "type": "RCPSP"},
        "project_goal": {"objective_function": "min_makespan"},
        "resources": [{"id": k + 1, "name": f"R{k + 1}", "capacity": c, "type": "renewable"}
                      for k, c in enumerate(capacities)],
        "jobs": jobs,
    }


def parse_rcp_file(path: str | Path, instance_id: str | None = None,
                   source: str = "RCPLIB") -> dict:
    path = Path(path)
    return parse_rcp_text(path.read_text(), instance_id or path.stem, source)


def _natural_key(inst_id: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", inst_id)]


def iter_rcplib_set(set_name: str, root: Path = RCPLIB_INSTANCES) -> Iterator[tuple[str, Path]]:
    """
    (id, путь) для `.rcp` набора;
    id — путь внутри набора без `.rcp` ('Set 1/Pat1').
    """
    directory = Path(root) / RCPLIB_SETS[set_name][0]
    items = [(p.relative_to(directory).with_suffix("").as_posix(), p)
             for p in directory.rglob("*.rcp")]
    yield from sorted(items, key=lambda it: _natural_key(it[0]))


def _excel_key(inst_id: str) -> str:
    """'Set 1/Pat1' -> 'set 1\\pat1.rcp' — так FileName записан на листах RCPLIB."""
    return inst_id.replace("/", "\\").lower() + ".rcp"


def load_rcplib_references(set_name: str, *, path: str | Path = RCPLIB_RELEASE_FILE,
                           root: Path = RCPLIB_INSTANCES) -> dict:
    """
    Эталоны набора из Excel RCPLIB: {id: Reference}. bks = UB-lit, lb = max(CPM, LB-lit).
    CPM листа сверяется с расчетом; LB > UB или инстанс без строки — ReferenceError.
    Лист DC общий для DC1 и DC2: строки чужого набора не используются.
    """
    from openpyxl import load_workbook

    from indicators import compute_indicators
    from references import Reference, ReferenceError

    wb = load_workbook(path, read_only=True)
    try:
        rows = wb[RCPLIB_SETS[set_name][1]].iter_rows(values_only=True)
        header = list(next(rows))
        col = {h: header.index(h) for h in ("FileName", "CPM", "LB-lit", "UB-lit")}
        sheet = {str(r[col["FileName"]]).lower(): r for r in rows if r[col["FileName"]] is not None}
    finally:
        wb.close()

    out = {}
    for inst_id, file in iter_rcplib_set(set_name, root):
        row = sheet.get(_excel_key(inst_id))
        if row is None:
            raise ReferenceError(f"{set_name}/{inst_id}: нет строки на листе Excel")
        cpm = compute_indicators(parse_rcp_file(file, inst_id))["extended"]["cpm_length"]
        if int(row[col["CPM"]]) != cpm:
            raise ReferenceError(f"{set_name}/{inst_id}: CPM {cpm} != Excel {row[col['CPM']]}")
        lb, ub = max(cpm, int(row[col["LB-lit"]])), int(row[col["UB-lit"]])
        if lb > ub:
            raise ReferenceError(f"{set_name}/{inst_id}: нижняя граница {lb} больше BKS {ub}")
        out[inst_id] = Reference(cpm=cpm, lb=lb, bks=ub, bks_source="rcplib", optimal=lb == ub)
    return out
