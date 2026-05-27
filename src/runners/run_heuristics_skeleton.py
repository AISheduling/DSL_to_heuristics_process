from __future__ import annotations

import json
import sys
import traceback
import types
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

THIS_DIR = Path(__file__).resolve().parent  # src/runners/
SRC_DIR = THIS_DIR.parent  # src/
ROOT_DIR = SRC_DIR.parent  # DSL_to_heuristics_process/

# Каркас планировщика лежит в src/
sys.path.insert(0, str(SRC_DIR))
import scheduler_skeleton as sched  # noqa: E402

EXPERIMENTS_DIR = ROOT_DIR / "experiments"
DATA_DIR = ROOT_DIR / "data" / "processed"
DSL_DIR = ROOT_DIR / "data" / "references" / "brief DSL description of projects"
OUTPUT_DIR = ROOT_DIR / "results" / "skeleton"

# Файлы с данными задач по кейсам
CASE_INSTANCES = {
    1: DATA_DIR / "Case1_PSPLIB_j301_1.json",
    2: DATA_DIR / "Case2_sch50.json",
    3: DATA_DIR / "Case3_nonrenewable.json",
    4: DATA_DIR / "Case4_renewable.json",
    5: DATA_DIR / "Case5_mp_j90_a2_nr1.json",
}

# DSL-описания для каркаса
DSL_PATHS = {
    1: DSL_DIR / "Case1_DSL_for_skeleton.json",
    2: DSL_DIR / "Case2_DSL_for_skeleton.json",
    3: DSL_DIR / "Case3_DSL_for_skeleton.json",
    4: DSL_DIR / "Case4_DSL_for_skeleton.json",
    5: DSL_DIR / "Case5_DSL_for_skeleton.json",
}


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compile_fn(code: str, fn_name: str):
    """
    Компилирует строку с кодом функции и возвращает объект функции.
    Убирает лишние импорты (from __future__ import annotations и др.),
    которые LLM иногда добавляет внутрь кода функции.
    """
    clean_lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("from __future__"):
            continue
        clean_lines.append(line)
    clean_code = "\n".join(clean_lines)

    namespace = types.ModuleType("heuristic_module")
    exec(compile(clean_code, "<llm_heuristic>", "exec"), namespace.__dict__)

    fn = getattr(namespace, fn_name, None)
    if fn is None:
        raise ValueError(f"Функция '{fn_name}' не найдена в коде:\n{clean_code[:300]}")
    return fn


def run_all(results_json: Path, dsl_path: Path, instance_path: Path,
            case_num: int) -> list[dict]:
    runs_data = load_json(results_json)
    instance_data = load_json(instance_path)
    runs = runs_data.get("runs", [])

    all_results = []

    for run in runs:
        run_index = run.get("run_index")
        method = run.get("method", "N/A")
        print(f"\n{'=' * 60}")
        print(f"Case {case_num} | Run {run_index} | Метод: {method}")

        # Пропускаем ошибочные запуски
        if "error" in run:
            print(f"  -> Пропущен (ошибка при генерации): {run['error']}")
            all_results.append({
                "case": case_num,
                "run_index": run_index,
                "method": method,
                "status": "skipped_generation_error",
                "error": run["error"],
            })
            continue

        select_job_code = run.get("select_job_fn", "")
        allocate_code = run.get("allocate_fn", "")

        # Компилируем функции
        try:
            select_job_fn = compile_fn(select_job_code, "select_job_fn")
            allocate_fn = compile_fn(allocate_code, "allocate_fn")
        except Exception as e:
            msg = f"Ошибка компиляции: {e}\n{traceback.format_exc()}"
            print(f"  -> {msg}")
            all_results.append({
                "case": case_num,
                "run_index": run_index,
                "method": method,
                "status": "compile_error",
                "error": msg,
            })
            continue

        # Строим состояние задачи
        try:
            meta, state = sched.build_state(dsl_path, instance_data)
        except Exception as e:
            msg = f"Ошибка build_state: {e}\n{traceback.format_exc()}"
            print(f"  -> {msg}")
            all_results.append({
                "case": case_num,
                "run_index": run_index,
                "method": method,
                "status": "build_state_error",
                "error": msg,
            })
            continue

        # Запускаем планировщик
        try:
            result = sched.run_schedule(
                state=state,
                select_job_fn=select_job_fn,
                allocate_fn=allocate_fn,
                verbose=False,
            )
            primary = result["objective"].get("primary")
            print(
                f"  -> OK | primary={primary} | iterations={result['iterations']} | final_time={result['final_time']}")
            all_results.append({
                "case": case_num,
                "run_index": run_index,
                "method": method,
                "status": "OK",
                "primary_objective": primary,
                "total_makespan": result["objective"].get("total_makespan"),
                "project_finish_times": result["objective"].get("project_finish_times"),
                "iterations": result["iterations"],
                "final_time": result["final_time"],
                "schedule_size": len(result["schedule"]),
            })
        except Exception as e:
            msg = f"Ошибка run_schedule: {e}\n{traceback.format_exc()}"
            print(f"  -> {msg}")
            all_results.append({
                "case": case_num,
                "run_index": run_index,
                "method": method,
                "status": "runtime_error",
                "error": msg,
            })

    return all_results


# Сохранение результатов

def save_json(results: dict, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nJSON сохранен: {path}")


def save_excel(results: list[dict], path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule Results"

    headers = [
        "Case", "Run", "Метод", "Статус",
        "Primary Objective", "Total Makespan",
        "Iterations", "Final Time", "Schedule Size",
        "Project Finish Times", "Error",
    ]
    ws.append(headers)

    for r in results:
        pft = r.get("project_finish_times")
        pft_str = json.dumps(pft, ensure_ascii=False) if pft else ""
        ws.append([
            r.get("case"),
            r.get("run_index"),
            r.get("method"),
            r.get("status"),
            r.get("primary_objective"),
            r.get("total_makespan"),
            r.get("iterations"),
            r.get("final_time"),
            r.get("schedule_size"),
            pft_str,
            r.get("error", ""),
        ])

    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)

    wb.save(path)
    print(f"Excel сохранен: {path}")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

    all_cases_results = {}
    all_rows = []

    for case_num in range(1, 6):
        exp_dir = EXPERIMENTS_DIR / f"experiment_skeleton_{case_num}_case"
        if not exp_dir.exists():
            print(f"\nПапка не найдена, пропуск: {exp_dir}")
            continue

        # Берем последнюю папку с датой
        date_dirs = sorted(d for d in exp_dir.iterdir() if d.is_dir())
        if not date_dirs:
            print(f"Нет папок с результатами в {exp_dir}")
            continue
        latest_dir = date_dirs[-1]

        # Ищем *_results.json
        result_files = [
            f for f in latest_dir.glob("*.json")
            if not f.name.startswith("all_results")
        ]
        if not result_files:
            print(f"JSON с результатами не найден в {latest_dir}")
            continue
        results_json = result_files[0]

        dsl_path = DSL_PATHS[case_num]
        instance_path = CASE_INSTANCES[case_num]

        missing = [p for p in (results_json, dsl_path, instance_path) if not p.exists()]
        if missing:
            for p in missing:
                print(f"ОШИБКА: файл не найден: {p}")
            continue

        print(f"\n{'=' * 60}")
        print(f"КЕЙС {case_num}")
        print(f"  Результаты LLM: {results_json.name}")
        print(f"  DSL:            {dsl_path.name}")
        print(f"  Instance:       {instance_path.name}")

        case_results = run_all(results_json, dsl_path, instance_path, case_num)
        all_cases_results[f"case{case_num}"] = case_results
        all_rows.extend(case_results)

        ok = [r for r in case_results if r.get("status") == "OK"]
        print(f"\nИтого Case {case_num}: {len(ok)}/{len(case_results)} успешно")
        if ok:
            best = min(ok, key=lambda r: r.get("primary_objective") or float("inf"))
            print(
                f"Лучший: Run {best['run_index']} | {best['method']} | primary={best['primary_objective']}")

    # Итоговая сводка
    print(f"\n{'=' * 60}")
    total_ok = sum(1 for r in all_rows if r.get("status") == "OK")
    print(f"ИТОГО по всем кейсам: {total_ok}/{len(all_rows)} успешно")

    # Сохранение
    out_json = OUTPUT_DIR / f"heuristics_schedule_results_{timestamp}.json"
    out_xlsx = OUTPUT_DIR / f"heuristics_schedule_results_{timestamp}.xlsx"
    save_json(all_cases_results, out_json)
    save_excel(all_rows, out_xlsx)
