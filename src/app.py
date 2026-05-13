import io
import json
import sys
import tempfile
import types
from pathlib import Path

import streamlit as st

PROBLEM_TYPES = {
    "RCPSP (base)": "PSPLIB_J30_RCPSP",
    "Single-Machine JIT": "SINGLE_MACHINE_JIT",
    "RCPSP with non-renewable resources": "RCPSP_MULTI_RESOURCE",
    "RCPSP with conditional restrictions": "CONDITIONAL_RCPSP",
    "Multi-Project RCPSP": "RCMPSP_MULTI_PROJECT",
}

METRICS = {
    "Makespan": ("Makespan", "Minimize"),
    "Total Earliness/Tardiness Penalty": (
        "Total Earliness/Tardiness Penalty", "Minimize"),
    "Non-Renewable Resource Consumption": (
        "Non-Renewable Resource Consumption", "Minimize"),
    "Total Makespan (для Multi-Project)": ("Total Makespan (All Projects)", "Minimize"),
}

RESOURCE_NATURES = ["Renewable", "Non-Renewable", "Renewable and Non-Renewable"]
EXECUTION_MODES = ["Single-Mode", "Multi-Mode"]

HEURISTICS = {
    "Most Successors (default)": None,
    "SPT - Shortest Processing Time": "spt",
    "LPT - Longest Processing Time": "lpt",
    "MSLK - Minimum Slack": "mslk",
}

# Подсказка со структурой объектов показывается рядом с полем вставки кода
SNAPSHOT_REFERENCE = """\
# select_job(eligible_ids, jobs, snapshot, meta) -> int
#   eligible_ids : list[int]            — id работ, готовых к запуску
#   jobs         : dict[int, Job]       — все работы
#   snapshot     : dict                 — текущее состояние:
#       "current_time"      : int
#       "completed_jobs"    : list[int]
#       "active_jobs"       : dict[int, int]   # job_id -> finish_time
#       "eligible_jobs"     : list[int]
#       "renewable_used"    : dict[int, int]   # resource_id -> used
#       "non_renewable_stock": dict[int, int]
#       "skipped_jobs"      : list[int]
#   meta         : DSLMeta              — метаданные DSL:
#       .primary_metric, .primary_direction
#       .is_single_machine, .is_multi_project
#       .has_non_renewable, .conditional_scheduling
#
# Job attributes:
#   .id, .duration, .predecessors, .successors
#   .resources_required  : dict[int, int]  # resource_id -> amount
#   .earliness_penalty, .tardiness_penalty
#   .non_renewable_consumption : dict[int, int]
#
# allocate(job, resources, snapshot, meta) -> dict[int, int]
#   resources    : dict[int, Resource]
#       Resource: .id, .name, .capacity, .r_type, .initial_stock
#   Возвращает {resource_id: amount}
# ─────────────────────────────────────────────────────────────
"""

DEFAULT_CODE = """\
def select_job(eligible_ids, jobs, snapshot, meta):
    # Пример: выбираем работу с наибольшим числом преемников
    return max(eligible_ids, key=lambda jid: len(jobs[jid].successors))


def allocate(job, resources, snapshot, meta):
    # Выделяем ровно столько, сколько требует работа
    return dict(job.resources_required)
"""


# Вспомогательные функции
def compile_fn(code: str, fn_name: str):
    """
    Компилирует код и возвращает (функция, None) или (None, текст_ошибки).
    """
    mod = types.ModuleType("llm_heuristic")
    try:
        exec(compile(code, "<llm_generated>", "exec"), mod.__dict__)  # noqa: S102
    except SyntaxError as e:
        return None, f"SyntaxError в строке {e.lineno}: {e.msg}"
    except Exception as e:
        return None, f"Ошибка при компиляции: {e}"

    fn = getattr(mod, fn_name, None)
    if fn is None:
        return None, f"Функция `{fn_name}` не найдена в коде."
    return fn, None


def make_builtin_select_fn(key):
    if key == "spt":
        def fn(eligible_ids, jobs, snap, meta):
            return min(eligible_ids, key=lambda jid: jobs[jid].duration)
    elif key == "lpt":
        def fn(eligible_ids, jobs, snap, meta):
            return max(eligible_ids, key=lambda jid: jobs[jid].duration)
    elif key == "mslk":
        def fn(eligible_ids, jobs, snap, meta):
            return min(
                eligible_ids,
                key=lambda jid: jobs[jid].duration / (len(jobs[jid].successors) + 1),
            )
    else:
        fn = None
    return fn


def run_solver(dsl_tmp_path, instance_data, select_fn, allocate_fn, verbose):
    from scheduler_skeleton import solve

    log_buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = log_buf
    try:
        result = solve(
            dsl_path=dsl_tmp_path,
            instance_data=instance_data,
            select_job_fn=select_fn,
            allocate_fn=allocate_fn,
            verbose=verbose,
        )
        error = None
    except Exception as e:
        result = None
        error = str(e)
    finally:
        sys.stdout = old_stdout

    return result, log_buf.getvalue(), error


def render_results(result, instance_data, log_output, verbose):
    import pandas as pd

    st.success("Планирование завершено!")
    st.subheader("Результаты")

    obj = result.get("objective", {})
    sched = result.get("schedule", {})

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Целевая метрика", obj.get("primary", "—"))
    m2.metric("Работ в расписании", len(sched))
    m3.metric("Итераций", result.get("iterations", "?"))
    m4.metric("Финальное время", result.get("final_time", "?"))

    if "budget_feasible" in obj:
        if obj["budget_feasible"]:
            st.success("Бюджет невозобновляемых ресурсов не нарушен")
        else:
            st.warning(f"Бюджет нарушен: {obj.get('budget_violations', '?')}")

    if obj.get("secondary") is not None:
        st.info(f"Вторичная метрика: {obj['secondary']}")

    with st.expander("Расписание (job_id → start_time)", expanded=True):
        if sched:
            jobs_list = instance_data.get("jobs", [])
            jobs_dict = {j.get("id"): j for j in jobs_list if isinstance(j, dict)}

            # Таблица расписания
            df = pd.DataFrame([
                {
                    "Job ID": jid,
                    "Start Time": st_val,
                    "Duration": jobs_dict.get(jid, {}).get("duration", 0) or 0,
                    "End Time": st_val + (jobs_dict.get(jid, {}).get("duration") or 0),
                }
                for jid, st_val in sorted(sched.items(), key=lambda x: x[1])
            ])
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Диаграмма Ганта
            try:
                import altair as alt

                gantt_data = []
                for jid, start in sched.items():
                    dur = jobs_dict.get(jid, {}).get("duration", 1) or 1
                    gantt_data.append(
                        {"Job": f"Job {jid}", "Start": start, "End": start + dur}
                    )

                if gantt_data:
                    gantt_df = pd.DataFrame(gantt_data)
                    chart = (
                        alt.Chart(gantt_df)
                        .mark_bar()
                        .encode(
                            x=alt.X("Start:Q", title="Время"),
                            x2="End:Q",
                            y=alt.Y("Job:N", sort="-x", title="Работа"),
                            color=alt.Color(
                                "Start:Q",
                                scale=alt.Scale(scheme="blues"),
                                legend=None,
                            ),
                            tooltip=["Job", "Start", "End"],
                        )
                        .properties(
                            title="Диаграмма Ганта",
                            height=max(200, len(sched) * 22),
                        )
                    )
                    st.altair_chart(chart, use_container_width=True)

            except ImportError:
                st.info("Установите `altair` для отображения диаграммы Ганта.")

    with st.expander("Полный объект результата (JSON)"):
        st.json(result)

    if verbose and log_output:
        with st.expander("Лог выполнения"):
            st.code(log_output, language="text")

    st.download_button(
        label="Скачать расписание (JSON)",
        data=json.dumps(result, indent=2, ensure_ascii=False),
        file_name="schedule_result.json",
        mime="application/json",
    )


# Страница
st.set_page_config(
    page_title="RCPSP Scheduler",
    layout="wide",
)

st.title("RCPSP Scheduler")
st.caption(
    "Каркас планировщика с подключаемыми эвристиками. "
    "Выберите параметры задачи, загрузите данные и запустите решение."
)

# Блок параметров задачи

col_cfg, col_data = st.columns([1, 1], gap="large")

with col_cfg:
    st.subheader("Параметры задачи")

    problem_label = st.selectbox("Тип задачи", list(PROBLEM_TYPES.keys()))
    problem_id = PROBLEM_TYPES[problem_label]

    metric_label = st.selectbox("Целевая метрика", list(METRICS.keys()))
    primary_metric, primary_direction = METRICS[metric_label]

    resource_nature = st.selectbox("Тип ресурсов", RESOURCE_NATURES)
    execution_mode = st.selectbox("Режим выполнения", EXECUTION_MODES)

    # Опциональные флаги
    with st.expander("Дополнительные флаги"):
        conditional = st.checkbox("Условное планирование (conditional scheduling)")
        selection_groups = st.checkbox("Группы выбора (selection groups)")
        time_precedence = st.checkbox("Временные приоритеты (time precedence)")

    verbose = st.checkbox("Подробный лог выполнения", value=False)

with col_data:
    st.subheader("Данные инстанса")

    st.info(
        "Загрузите JSON-файл с данными проекта (поля `resources` и `jobs`). "
    )

    uploaded_instance = st.file_uploader(
        "Выберите файл инстанса (.json)",
        type=["json"],
        key="instance_file",
    )

    st.divider()
    st.subheader("DSL-описание (опционально)")
    st.info(
        "Если не загружен, DSL будет сформирован автоматически из "
        "выбранных параметров выше."
    )

    uploaded_dsl = st.file_uploader(
        "Выберите файл DSL (.json)",
        type=["json"],
        key="dsl_file",
    )

    # Предпросмотр загруженных данных
    if uploaded_instance:
        try:
            instance_data = json.load(uploaded_instance)
            n_jobs = len(instance_data.get("jobs", []))
            n_res = len(instance_data.get("resources", []))
            st.success(f"Файл загружен: {n_jobs} работ, {n_res} ресурсов")

            with st.expander("Предпросмотр данных (первые 3 работы)"):
                jobs_preview = instance_data.get("jobs", [])[:3]
                st.json(jobs_preview)
        except Exception as e:
            st.error(f"Ошибка чтения файла: {e}")
            instance_data = None
    else:
        instance_data = None

st.divider()
tab_builtin, tab_llm = st.tabs([
    "Встроенная эвристика",
    "Вставить код от LLM",
])

# Вкладка 1: встроенные эвристики

with tab_builtin:
    heuristic_label = st.selectbox(
        "Функция выбора задачи (select_job_fn)",
        list(HEURISTICS.keys()),
        key="builtin_heur",
    )
    heuristic_key = HEURISTICS[heuristic_label]

    if st.button("Запустить планировщик", type="primary", key="run_builtin"):
        if instance_data is None:
            st.error("Сначала загрузите файл данных инстанса.")
            st.stop()

        try:
            from scheduler_skeleton import solve, DSLParser
        except ImportError:
            st.error("Не найден `scheduler_skeleton.py` рядом с `app.py`.")
            st.stop()

        # DSL
        if uploaded_dsl:
            uploaded_dsl.seek(0)
            dsl_dict = json.load(uploaded_dsl)
        else:
            dsl_dict = {
                "project_id": problem_id,
                "problem_statement": {
                    "problem_type": problem_label,
                    "constraint_types": ["Precedence", "Resource Capacities"],
                    "resource_nature": resource_nature,
                    "execution_mode": execution_mode,
                    "uncertainty": "Deterministic",
                },
                "optimization_objectives": {
                    "primary": {"metric": primary_metric,
                                "direction": primary_direction}
                },
                "graph_meta_characteristics": {},
                "conditional_scheduling": {
                    "enabled": conditional,
                    "selection_groups_present": selection_groups,
                    "time_precedence_present": time_precedence,
                },
            }

        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(dsl_dict, tmp, ensure_ascii=False)
            dsl_tmp_path = Path(tmp.name)

        select_fn = make_builtin_select_fn(heuristic_key)

        with st.spinner("Выполняется планирование..."):
            result, log_output, error = run_solver(
                dsl_tmp_path, instance_data,
                select_fn=select_fn,
                allocate_fn=None,
                verbose=verbose,
            )

        if error:
            st.error(f"Ошибка при планировании: {error}")
            if log_output:
                with st.expander("Лог"):
                    st.code(log_output)
        else:
            render_results(result, instance_data, log_output, verbose)

# Вкладка 2: вставить код от LLM

with tab_llm:
    st.markdown(
        "Вставьте сгенерированный LLM код двух функций: "
        "**`select_job`** и **`allocate`**. "
        "Код компилируется и подставляется в каркас автоматически."
    )

    # Справка по структуре объектов
    with st.expander("Справка: какие поля доступны в функциях"):
        st.code(SNAPSHOT_REFERENCE, language="python")

    # Поле ввода кода
    user_code = st.text_area(
        "Код функций (select_job + allocate)",
        value=DEFAULT_CODE,
        height=320,
        key="llm_code_input",
        help="Вставьте Python-код двух функций. "
             "Имена должны быть select_job и allocate.",
    )

    # Кнопка проверки синтаксиса (без запуска планировщика)
    check_col, run_col = st.columns([1, 2])

    with check_col:
        if st.button("Проверить синтаксис", key="check_syntax"):
            sel_fn, err_s = compile_fn(user_code, "select_job")
            alloc_fn, err_a = compile_fn(user_code, "allocate")

            if err_s:
                st.error(f"select_job: {err_s}")
            else:
                st.success("select_job — OK")

            if err_a:
                st.warning(f"allocate: {err_a} (будет использована стандартная)")
            else:
                st.success("allocate — OK")

    with run_col:
        run_llm = st.button(
            "Запустить с этим кодом", type="primary", key="run_llm"
        )

    if run_llm:
        if instance_data is None:
            st.error("Сначала загрузите файл данных инстанса.")
            st.stop()

        try:
            from scheduler_skeleton import solve, DSLParser
        except ImportError:
            st.error("Не найден `scheduler_skeleton.py` рядом с `app.py`.")
            st.stop()

        # Компилируем select_job
        select_fn, err_s = compile_fn(user_code, "select_job")
        if err_s:
            st.error(f"Ошибка в select_job: {err_s}")
            st.stop()

        # Компилируем allocate (если нет, используем стандартную)
        allocate_fn, err_a = compile_fn(user_code, "allocate")
        if err_a:
            st.warning(f"allocate не найдена или содержит ошибку: {err_a}. "
                       f"Используется стандартная.")
            allocate_fn = None

        # DSL
        if uploaded_dsl:
            uploaded_dsl.seek(0)
            dsl_dict = json.load(uploaded_dsl)
        else:
            dsl_dict = {
                "project_id": problem_id,
                "problem_statement": {
                    "problem_type": problem_label,
                    "constraint_types": ["Precedence", "Resource Capacities"],
                    "resource_nature": resource_nature,
                    "execution_mode": execution_mode,
                    "uncertainty": "Deterministic",
                },
                "optimization_objectives": {
                    "primary": {"metric": primary_metric,
                                "direction": primary_direction}
                },
                "graph_meta_characteristics": {},
                "conditional_scheduling": {
                    "enabled": conditional,
                    "selection_groups_present": selection_groups,
                    "time_precedence_present": time_precedence,
                },
            }

        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(dsl_dict, tmp, ensure_ascii=False)
            dsl_tmp_path = Path(tmp.name)

        with st.spinner("Выполняется планирование..."):
            result, log_output, error = run_solver(
                dsl_tmp_path, instance_data,
                select_fn=select_fn,
                allocate_fn=allocate_fn,
                verbose=verbose,
            )

        if error:
            st.error(f"Ошибка при планировании: {error}")
            if log_output:
                with st.expander("Лог"):
                    st.code(log_output)
            # Показываем полный traceback для отладки кода
            import traceback

            st.expander("Подробности ошибки").code(traceback.format_exc())
        else:
            render_results(result, instance_data, log_output, verbose)
