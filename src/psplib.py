"""
Парсер одномодовых инстансов PSPLIB (`.sm`, Kolisch & Sprecher 1997).

Выдает словарь в формате `data/processed` (как `Case1_PSPLIB_j301_1.json`), который
читают `ProblemFactory`, чекер и `indicators.py`. Многомодовые файлы и инстансы с
невозобновляемыми ресурсами не поддерживаются: `PSPLIBFormatError`.
"""
from __future__ import annotations

import re
from pathlib import Path


class PSPLIBFormatError(ValueError):
    """Файл не похож на одномодовый `.sm` PSPLIB."""


_SET_SOURCES = {"j30": "PSPLIB J30 Set", "j60": "PSPLIB J60 Set",
                "j90": "PSPLIB J90 Set", "j120": "PSPLIB J120 Set"}


def _header_int(text: str, label: str) -> int:
    m = re.search(rf"{re.escape(label)}[^:\n]*:\s*(\d+)", text)
    if not m:
        raise PSPLIBFormatError(f"нет поля '{label}'")
    return int(m.group(1))


def _section(text: str, title: str) -> list[str]:
    """Строки раздела `title:` до следующей строки из звездочек, без заголовков таблицы."""
    m = re.search(rf"^{re.escape(title)}:?\s*$(.*?)^\*+\s*$", text, re.S | re.M)
    if not m:
        raise PSPLIBFormatError(f"нет раздела '{title}'")
    return [ln for ln in m.group(1).splitlines()
            if ln.strip() and not ln.lstrip().startswith("-") and ln.strip()[0].isdigit()]


def parse_sm_text(text: str, instance_id: str, source: str = "PSPLIB") -> dict:
    text = text.replace("\r\n", "\n")
    if _header_int(text, "projects") != 1:
        raise PSPLIBFormatError("поддерживается только один проект в файле")
    n_jobs = _header_int(text, "jobs (incl. supersource/sink )")
    n_ren = _header_int(text, "- renewable")
    if _header_int(text, "- nonrenewable") or _header_int(text, "- doubly constrained"):
        raise PSPLIBFormatError("невозобновляемые ресурсы в .sm не поддерживаются")

    info = _section(text, "PROJECT INFORMATION")
    if len(info) != 1:
        raise PSPLIBFormatError("ожидалась одна строка PROJECT INFORMATION")
    _, _, _, due_date, tard_cost, _ = (int(x) for x in info[0].split())

    successors: dict[int, list[int]] = {}
    for ln in _section(text, "PRECEDENCE RELATIONS"):
        nums = [int(x) for x in ln.split()]
        job, n_modes, n_succ = nums[:3]
        if n_modes != 1:
            raise PSPLIBFormatError(f"работа {job}: {n_modes} режимов, ожидался 1")
        if len(nums) != 3 + n_succ:
            raise PSPLIBFormatError(f"работа {job}: число преемников не совпадает со списком")
        successors[job] = nums[3:]

    requests: dict[int, tuple[int, list[int]]] = {}
    for ln in _section(text, "REQUESTS/DURATIONS"):
        nums = [int(x) for x in ln.split()]
        if len(nums) != 3 + n_ren:
            raise PSPLIBFormatError(f"строка REQUESTS/DURATIONS: '{ln.strip()}'")
        requests[nums[0]] = (nums[2], nums[3:])

    avail = _section(text, "RESOURCEAVAILABILITIES")
    capacities = [int(x) for x in avail[-1].split()]
    if len(capacities) != n_ren:
        raise PSPLIBFormatError("число мощностей не совпадает с числом ресурсов")

    ids = list(range(1, n_jobs + 1))
    if sorted(successors) != ids or sorted(requests) != ids:
        raise PSPLIBFormatError(f"ожидались работы 1..{n_jobs}")

    predecessors: dict[int, list[int]] = {j: [] for j in ids}
    for j in ids:
        for s in successors[j]:
            if s not in predecessors:
                raise PSPLIBFormatError(f"работа {j}: неизвестный преемник {s}")
            predecessors[s].append(j)

    jobs = []
    for j in ids:
        duration, demand = requests[j]
        job = {"id": j, "predecessors": predecessors[j], "successors": successors[j]}
        if j == 1:
            job["name"] = "Supersource"
        elif j == n_jobs:
            job["name"] = "Supersink"
        job["duration"] = duration
        job["resource_requirements"] = [{"resource_id": k + 1, "amount": a}
                                        for k, a in enumerate(demand) if a > 0]
        jobs.append(job)

    return {
        "case_info": {
            "id": f"PSPLIB_{instance_id}",
            "source": source,
            "description": (f"Standard RCPSP with {n_jobs - 2} jobs and {n_ren} "
                            f"renewable resources (Single Mode)"),
            "type": "RCPSP",
        },
        "project_goal": {"objective_function": "min_makespan", "due_date": due_date,
                         "tardiness_unit_cost": tard_cost},
        "resources": [{"id": k + 1, "name": f"R{k + 1}", "capacity": c, "type": "renewable"}
                      for k, c in enumerate(capacities)],
        "jobs": jobs,
    }


def split_name(stem: str) -> tuple[str, int, int] | None:
    """'j3010_1' -> ('j30', 10, 1): набор, номер параметра, номер инстанса."""
    for set_name in sorted(_SET_SOURCES, key=len, reverse=True):
        m = re.fullmatch(rf"{set_name}(\d+)_(\d+)", stem)
        if m:
            return set_name, int(m.group(1)), int(m.group(2))
    return None


def parse_sm_file(path: str | Path) -> dict:
    path = Path(path)
    parts = split_name(path.stem)
    source = _SET_SOURCES[parts[0]] if parts else "PSPLIB"
    return parse_sm_text(path.read_text(encoding="utf-8"), path.stem, source)


def iter_set(directory: str | Path):
    """(имя, инстанс) для всех `.sm` каталога в порядке (параметр, номер)."""
    def key(p: Path):
        parts = split_name(p.stem)
        return parts[1:] if parts else (0, 0)
    for p in sorted(Path(directory).glob("*.sm"), key=key):
        yield p.stem, parse_sm_file(p)
