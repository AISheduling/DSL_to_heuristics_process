from __future__ import annotations

import json
import traceback
import types
from collections import defaultdict
from datetime import datetime
from multiprocessing import Process, Queue
from pathlib import Path

from openpyxl import Workbook

TIMEOUT_SECONDS = 30

THIS_DIR = Path(__file__).resolve().parent  # src/runners/
SRC_DIR = THIS_DIR.parent  # src/
ROOT_DIR = SRC_DIR.parent  # DSL_to_heuristics_process/

EXP_DIR = ROOT_DIR / "experiments" / "experiment text"
DATA_DIR = ROOT_DIR / "data" / "processed"
OUTPUT_DIR = ROOT_DIR / "results" / "text"

# Маппинг: стем файла результатов LLM -> файл с данными задачи
CASE_MAP = {
    "Case1_text_results": "Case1_PSPLIB_j301_1.json",
    "Case2_text_results": "Case2_sch50.json",
    "Case3_text_results": "Case3_nonrenewable.json",
    "Case4_text_results": "Case4_renewable.json",
    "Case5_text_results": "Case5_mp_j90_a2_nr1.json",
}


def find_case_key(stem: str) -> str | None:
    if stem in CASE_MAP:
        return stem
    for key in CASE_MAP:
        if stem.startswith(key):
            return key
    return None


def compile_fn(code: str):
    ns = types.ModuleType("heuristic_module")
    exec(compile(code, "<llm_heuristic>", "exec"), ns.__dict__)
    fn = getattr(ns, "solve_scheduling", None)
    if fn is None:
        raise ValueError("Функция 'solve_scheduling' не найдена в коде")
    return fn


# Запуск с таймаутом (защита от бесконечных циклов)

def _worker(code: str, jobs, resources, q: Queue):
    try:
        ns = types.ModuleType("heuristic_module")
        exec(compile(code, "<llm_heuristic>", "exec"), ns.__dict__)
        fn = getattr(ns, "solve_scheduling", None)
        if fn is None:
            q.put(("error", "Функция 'solve_scheduling' не найдена в коде"))
            return
        result = fn(jobs, resources)
        q.put(("ok", result))
    except Exception:
        q.put(("error", traceback.format_exc()))


def _run_with_timeout(code: str, jobs, resources):
    q = Queue()
    p = Process(target=_worker, args=(code, jobs, resources, q))
    p.start()
    p.join(timeout=TIMEOUT_SECONDS)
    if p.is_alive():
        p.terminate()
        p.join()
        return None
    if q.empty():
        raise RuntimeError("Процесс завершился без результата")
    status, value = q.get()
    if status == "error":
        raise RuntimeError(value)
    return value

# Извлечение метрики

PENALTY_KEYS = (
    "total_penalty", "total_earliness_tardiness_penalty",
    "penalty", "objective_value", "cost", "weighted_penalty",
)


def extract_objective(result) -> tuple[int | None, str]:
    if result is None:
        return None, "none"
    if isinstance(result, (int, float)):
        return int(result), "makespan"
    if isinstance(result, dict):
        for key in ("makespan", "total_makespan", "finish_time", "end_time"):
            if key in result and isinstance(result[key], (int, float)):
                return int(result[key]), "makespan"
        for wrapper in ("objective", "metrics"):
            obj = result.get(wrapper)
            if isinstance(obj, dict):
                for key in ("makespan", "total_makespan", "finish_time", "end_time"):
                    if key in obj and isinstance(obj[key], (int, float)):
                        return int(obj[key]), "makespan"
                for key in PENALTY_KEYS:
                    if key in obj and isinstance(obj[key], (int, float)):
                        return int(obj[key]), "penalty"
        for key in PENALTY_KEYS:
            if key in result and isinstance(result[key], (int, float)):
                return int(result[key]), "penalty"
        for key, val in result.items():
            if key.startswith("objective") and isinstance(val, (int, float)):
                return int(val), "penalty"
        schedule = result.get("schedule")
        if isinstance(schedule, dict) and schedule:
            max_val = None
            for v in schedule.values():
                if isinstance(v, (int, float)):
                    max_val = max(max_val or v, v)
                elif isinstance(v, (list, tuple)) and len(v) >= 2:
                    max_val = max(max_val or v[1], v[1])
            if max_val is not None:
                return int(max_val), "makespan"
    if isinstance(result, list):
        try:
            return (int(max(result)), "makespan") if result else (None, "none")
        except (TypeError, ValueError):
            pass
    return None, "none"


def collect_runs(exp_folder: Path) -> dict[str, list[tuple]]:
    case_runs: dict[str, list[tuple]] = defaultdict(list)

    subdirs = sorted([d for d in exp_folder.iterdir() if d.is_dir()])
    if not subdirs:
        subdirs = [exp_folder]

    for subdir in subdirs:
        result_files = [
            f for f in subdir.glob("*.json")
            if "_results" in f.stem
               and not f.stem.startswith("all_")
               and not f.stem.startswith("all_text")
        ]
        print(f"    Подпапка: {subdir.name} → найдено файлов: {len(result_files)}")
        for rfile in sorted(result_files):
            case_key = find_case_key(rfile.stem)
            if case_key is None:
                print(f"      [SKIP] Нет маппинга для '{rfile.stem}'")
                continue
            with open(rfile, encoding="utf-8") as f:
                data = json.load(f)
            runs = data.get("runs", [])
            added = sum(
                1 for run in runs
                if "error" not in run and run.get("code")
                and case_runs[case_key].append((run, subdir.name, rfile.stem)) is None
            )
            print(f"      {rfile.name}: {added} runs с кодом")

    return case_runs


def run_experiment(exp_folder: Path) -> list[dict]:
    print(f"\n  Сбор runs из: {exp_folder}")
    case_runs = collect_runs(exp_folder)

    total_runs = sum(len(v) for v in case_runs.values())
    print(f"\n  Итого кейсов: {len(case_runs)}, runs для запуска: {total_runs}")

    all_rows = []

    for case_key in sorted(case_runs):
        instance_path = DATA_DIR / CASE_MAP[case_key]
        if not instance_path.exists():
            print(f"\n  [SKIP] Файл данных не найден: {instance_path}")
            continue

        with open(instance_path, encoding="utf-8") as f:
            raw = json.load(f)
        jobs = raw.get("jobs", [])
        resources = raw.get("resources", [])

        print(f"\n  === Кейс: {case_key} → {CASE_MAP[case_key]} ===")

        for run, folder_name, file_stem in case_runs[case_key]:
            run_index = run.get("run_index")
            method = run.get("method", "N/A")
            code = run["code"]

            try:
                result = _run_with_timeout(code, jobs, resources)
                if result is None:
                    msg = f"Timeout: выполнение превысило {TIMEOUT_SECONDS} сек (вероятно бесконечный цикл)"
                    print(f"    [{folder_name}] Run {run_index}: {msg}")
                    all_rows.append({
                        "case": case_key, "folder": folder_name,
                        "run_index": run_index, "method": method,
                        "status": "timeout",
                        "makespan": None, "penalty": None, "error": msg,
                    })
                    continue
                val, kind = extract_objective(result)
                label = "penalty" if kind == "penalty" else "makespan"
                print(
                    f"    [{folder_name}] Run {run_index}: OK | {label}={val} | {method}")
                all_rows.append({
                    "case": case_key, "folder": folder_name,
                    "run_index": run_index, "method": method,
                    "status": "OK",
                    "makespan": val if kind == "makespan" else None,
                    "penalty": val if kind == "penalty" else None,
                    "error": "",
                })
            except Exception as e:
                msg = traceback.format_exc()
                print(f"    [{folder_name}] Run {run_index}: Runtime error — {e}")
                all_rows.append({
                    "case": case_key, "folder": folder_name,
                    "run_index": run_index, "method": method,
                    "status": "runtime_error",
                    "makespan": None, "penalty": None, "error": msg,
                })

    return all_rows

# Сохранение

def save_json(rows: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"JSON сохранен: {path}")


def save_excel(rows: list[dict], path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(
        ["Папка", "Кейс", "Run", "Метод", "Статус", "Makespan", "Penalty", "Ошибка"])
    for r in rows:
        ws.append([
            r.get("folder"), r.get("case"),
            r.get("run_index"), r.get("method"), r.get("status"),
            r.get("makespan"), r.get("penalty"),
            (r.get("error") or ""),
        ])
    for col in ws.columns:
        width = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(width + 2, 60)
    wb.save(path)
    print(f"Excel сохранен: {path}")


if __name__ == "__main__":
    if not EXP_DIR.exists():
        print(f"ОШИБКА: папка не найдена: {EXP_DIR}")
        raise SystemExit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"{'=' * 60}")
    print(f"Эксперимент: experiment text")
    print(f"Папка: {EXP_DIR}")

    rows = run_experiment(EXP_DIR)

    ok = [r for r in rows if r["status"] == "OK"]
    print(f"\nИтого OK: {len(ok)}/{len(rows)}")
    by_case: dict[str, list] = defaultdict(list)
    for r in ok:
        by_case[r["case"]].append(r)
    for case, case_rows in sorted(by_case.items()):
        ms = [r["makespan"] for r in case_rows if r["makespan"] is not None]
        pen = [r["penalty"] for r in case_rows if r["penalty"] is not None]
        if ms:
            print(
                f"  {case}: makespan min={min(ms)} max={max(ms)} avg={sum(ms) / len(ms):.1f}")
        if pen:
            print(
                f"  {case}: penalty  min={min(pen)} max={max(pen)} avg={sum(pen) / len(pen):.1f}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    save_json(rows, OUTPUT_DIR / f"schedule_results_{timestamp}.json")
    save_excel(rows, OUTPUT_DIR / f"schedule_results_{timestamp}.xlsx")
