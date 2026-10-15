"""
Общий слой трёх раннеров (Text, DSL, Skeleton).

Единые статусы для всех подходов (доли считаются от всех генераций):
  generation_error  LLM не вернула код (в записи run есть "error" или нет кода)
  compile_error     код не компилируется / нет нужной функции
  runtime_error     исключение при выполнении
  timeout           превышен общий TIMEOUT_SECONDS (один для всех подходов)
  no_schedule       выполнение завершилось, но расписание из вывода не извлекается
  infeasible        чекер нашёл нарушения (предшествование, мощности, бюджет, группы)
  incomplete        расписание допустимо, но не все работы запланированы
  ok                полное допустимое расписание; качество — только из чекера

Качество (primary / makespan) берётся исключительно из schedule_checker,
а не из вывода сгенерированного кода и не из каркаса.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
import types
from collections import defaultdict
from datetime import datetime
from multiprocessing import Process, Queue
from pathlib import Path
from queue import Empty
from typing import Any

THIS_DIR = Path(__file__).resolve().parent  # experiments/runners/
ROOT_DIR = THIS_DIR.parent.parent  # DSL_to_heuristics_process/
SRC_DIR = ROOT_DIR / "src"
DATA_DIR = ROOT_DIR / "data" / "processed"
FULL_DSL_DIR = ROOT_DIR / "data" / "references" / "full DSL description of projects"
BRIEF_DSL_DIR = ROOT_DIR / "data" / "references" / "brief DSL description of projects"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from schedule_checker import validate_schedule  # noqa: E402

TIMEOUT_SECONDS = 30

STATUSES = ("generation_error", "compile_error", "runtime_error", "timeout",
            "no_schedule", "infeasible", "incomplete", "ok")

CASE_INSTANCES = {
    1: "Case1_PSPLIB_j301_1.json",
    2: "Case2_sch50.json",
    3: "Case3_nonrenewable.json",
    4: "Case4_renewable.json",
    5: "Case5_mp_j90_a2_nr1.json",
}

ROW_COLUMNS = [
    "approach", "case", "folder", "file", "run_index", "method", "status",
    "primary", "makespan", "violations", "scheduled", "total",
    "kernel_status", "reason", "invalid_select_count", "allocate_violations",
    "iterations", "scheme", "elapsed_s", "error",
]


# --- извлечение расписания из вывода полного решателя -------------------------

_START_KEYS = ("start", "start_time", "begin", "s")
_ID_KEYS = ("id", "job_id", "job", "activity", "activity_id")


def _start_of(value: Any) -> Any:
    """Время старта из значения: число, [start, end], {"start": ...}."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
        return value[0]
    if isinstance(value, dict):
        for k in _START_KEYS:
            if k in value and isinstance(value[k], (int, float)):
                return value[k]
    return None


def _key_of(key: Any) -> Any:
    if isinstance(key, str):
        if key.lstrip("-").isdigit():
            return int(key)
        return key  # "1:2" для многопроектной задачи — разберёт чекер
    return key


def _from_mapping(mapping: dict) -> dict | None:
    out = {}
    for k, v in mapping.items():
        s = _start_of(v)
        if s is None:
            return None
        out[_key_of(k)] = s
    return out or None


def _from_list(items: list) -> dict | None:
    out = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        key = next((item[k] for k in _ID_KEYS if k in item), None)
        s = next((item[k] for k in _START_KEYS if k in item), None)
        if key is None or not isinstance(s, (int, float)):
            return None
        out[_key_of(key)] = s
    return out or None


def extract_schedule(result: Any) -> dict | None:
    """Нормализует вывод solve_scheduling в {job_key: start} или None.

    Принимаются: {"schedule": {...}} / {"schedule": [...]} / {"start_times": {...}}
    и словарь {job: start} верхнего уровня. Makespan из вывода не читается никогда.
    """
    if not isinstance(result, dict) or not result:
        return None
    for key in ("schedule", "start_times", "starts", "assignments"):
        inner = result.get(key)
        if isinstance(inner, dict):
            return _from_mapping(inner)
        if isinstance(inner, list):
            return _from_list(inner)
    if all(not isinstance(v, (dict, list)) for v in result.values()):
        keys_numeric = all(isinstance(_key_of(k), int) for k in result)
        if keys_numeric:
            return _from_mapping(result)
    return None


# --- оценка через чекер -------------------------------------------------------

_CHECKER_TO_STATUS = {"valid": "ok", "incomplete": "incomplete", "invalid": "infeasible",
                      "empty": "no_schedule"}


def evaluate(instance: dict, schedule: dict | None, *, budget_limit: dict | None = None,
             objective: str | None = None) -> dict[str, Any]:
    """Статус и качество только из независимого чекера."""
    if not schedule:
        return {"status": "no_schedule", "primary": None, "makespan": None,
                "violations": [], "scheduled": 0, "total": None}
    rep = validate_schedule(instance, schedule, budget_limit=budget_limit, objective=objective)
    return {
        "status": _CHECKER_TO_STATUS[rep["status"]],
        "primary": rep["objective"].get("primary"),
        "makespan": rep["makespan"],
        "violations": sorted({v["type"] for v in rep["violations"]}),
        "violation_details": rep["violations"][:5],
        "scheduled": rep["scheduled"],
        "total": rep["total"],
    }


def budget_limit_from_dsl(dsl_path: Path | None) -> dict | None:
    if not dsl_path or not Path(dsl_path).exists():
        return None
    with open(dsl_path, encoding="utf-8") as f:
        d = json.load(f)
    sec = (d.get("optimization_objectives") or {}).get("secondary") or {}
    return (sec.get("parameters") or {}).get("budget_limit")


# --- выполнение в отдельном процессе с таймаутом -------------------------------

def _compile(code: str, fn_name: str):
    clean = "\n".join(ln for ln in code.splitlines() if not ln.strip().startswith("from __future__"))
    ns = types.ModuleType("heuristic_module")
    exec(compile(clean, f"<llm:{fn_name}>", "exec"), ns.__dict__)  # noqa: S102
    fn = getattr(ns, fn_name, None)
    if fn is None:
        raise ValueError(f"function '{fn_name}' not found in generated code")
    return fn


def _worker_full(code: str, jobs, resources, q: Queue):
    try:
        fn = _compile(code, "solve_scheduling")
    except Exception:
        q.put(("compile_error", traceback.format_exc(), None))
        return
    try:
        result = fn(jobs, resources)
    except Exception:
        q.put(("runtime_error", traceback.format_exc(), None))
        return
    schedule = extract_schedule(result)
    q.put(("done", repr(result)[:300], schedule))


def _worker_skeleton(select_code: str, allocate_code: str, dsl_path: str, instance: dict,
                     scheme: str, q: Queue):
    try:
        import scheduler_skeleton as sched
        select_fn = _compile(select_code, "select_job_fn")
        allocate_fn = _compile(allocate_code, "allocate_fn")
    except Exception:
        q.put(("compile_error", traceback.format_exc(), None))
        return
    try:
        meta, state = sched.build_state(dsl_path, instance)
        result = sched.run_schedule(state, select_fn, allocate_fn, scheme=scheme)
    except Exception:
        q.put(("runtime_error", traceback.format_exc(), None))
        return
    q.put(("done", None, result))


def _run_with_timeout(target, args: tuple, timeout: float) -> tuple[str, Any, Any]:
    q: Queue = Queue()
    p = Process(target=target, args=(*args, q))
    p.start()
    try:
        kind, info, payload = q.get(timeout=timeout)
    except Empty:
        p.terminate()
        p.join()
        return "timeout", f"exceeded {timeout} s", None
    p.join()
    return kind, info, payload


def run_full_solver(code: str, instance: dict, *, timeout: float = TIMEOUT_SECONDS,
                    budget_limit: dict | None = None, objective: str | None = None) -> dict:
    """Полный решатель (Text / DSL): компиляция, запуск с таймаутом, чекер."""
    t0 = time.perf_counter()
    kind, info, schedule = _run_with_timeout(
        _worker_full, (code, instance.get("jobs", []), instance.get("resources", [])), timeout)
    elapsed = round(time.perf_counter() - t0, 3)
    if kind != "done":
        return {"status": kind, "primary": None, "makespan": None, "violations": [],
                "error": info, "elapsed_s": elapsed}
    ev = evaluate(instance, schedule, budget_limit=budget_limit, objective=objective)
    ev.update({"error": "" if ev["status"] == "ok" else f"output: {info}", "elapsed_s": elapsed})
    return ev


def run_skeleton(select_code: str, allocate_code: str, dsl_path: str | Path, instance: dict, *,
                 timeout: float = TIMEOUT_SECONDS, scheme: str = "ssgs",
                 budget_limit: dict | None = None, objective: str | None = None) -> dict:
    """Две функции в каркасе: компиляция, run_schedule с таймаутом, чекер поверх каркаса."""
    t0 = time.perf_counter()
    kind, info, result = _run_with_timeout(
        _worker_skeleton, (select_code, allocate_code, str(dsl_path), instance, scheme), timeout)
    elapsed = round(time.perf_counter() - t0, 3)
    if kind != "done":
        return {"status": kind, "primary": None, "makespan": None, "violations": [],
                "error": info, "elapsed_s": elapsed}
    ev = evaluate(instance, result["schedule"], budget_limit=budget_limit, objective=objective)
    if result["status"] != "complete" and ev["status"] == "ok":
        ev["status"] = "incomplete"  # каркас не завершил расписание — чекеру верим, но статус честный
    ev.update({
        "kernel_status": result["status"],
        "reason": result["reason"],
        "invalid_select_count": result["invalid_select_count"],
        "allocate_violations": result["allocate_violations"],
        "iterations": result["iterations"],
        "scheme": result["scheme"],
        "error": "" if ev["status"] == "ok" else (result.get("detail") or ""),
        "elapsed_s": elapsed,
    })
    if ev["status"] == "ok" and ev["primary"] != result["objective"].get("primary"):
        ev["error"] = (f"kernel objective {result['objective'].get('primary')} != "
                       f"checker {ev['primary']}")
    return ev


# --- сбор запусков из experiments/ --------------------------------------------

def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def iter_result_files(exp_dir: Path):
    subdirs = sorted(d for d in exp_dir.iterdir() if d.is_dir()) or [exp_dir]
    for subdir in subdirs:
        for f in sorted(subdir.glob("*.json")):
            if "_results" in f.stem and not f.stem.startswith("all_"):
                yield subdir, f


def case_of(stem: str, case_map: dict[str, int]) -> int | None:
    for key, case in case_map.items():
        if stem == key or stem.startswith(key):
            return case
    return None


def generation_error_row(run: dict) -> str | None:
    """Текст ошибки генерации, если запуск не дал кода; иначе None."""
    if "error" in run:
        return str(run["error"])
    return None


# --- сводка ---------------------------------------------------------------------

def summarize(rows: list[dict]) -> dict[str, dict]:
    """Доли статусов по кейсам от всех генераций; качество — по строкам ok."""
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_case[str(r["case"])].append(r)
    out: dict[str, dict] = {}
    for case, case_rows in sorted(by_case.items()):
        counts = {s: 0 for s in STATUSES}
        for r in case_rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        vals = [r["primary"] for r in case_rows if r["status"] == "ok" and r["primary"] is not None]
        out[case] = {
            "total": len(case_rows),
            "counts": counts,
            "share_ok": counts["ok"] / len(case_rows) if case_rows else 0.0,
            "primary": ({"min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals)}
                        if vals else None),
        }
    return out


def print_summary(rows: list[dict]):
    for case, s in summarize(rows).items():
        shown = ", ".join(f"{k}={v}" for k, v in s["counts"].items() if v)
        line = f"  {case}: ok {s['counts']['ok']}/{s['total']} ({s['share_ok']:.0%}) | {shown}"
        if s["primary"]:
            p = s["primary"]
            line += f" | primary min={p['min']} max={p['max']} mean={p['mean']:.1f}"
        print(line)


# --- сохранение ------------------------------------------------------------------

def save_json(rows: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "summary": summarize(rows), "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"JSON: {path}")


def save_excel(rows: list[dict], path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(ROW_COLUMNS)
    for r in rows:
        ws.append([_cell(r.get(c)) for c in ROW_COLUMNS])
    for col in ws.columns:
        width = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(width + 2, 60)
    wb.save(path)
    print(f"Excel: {path}")


def _cell(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M")
