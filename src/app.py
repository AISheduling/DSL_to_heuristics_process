import json
import tempfile
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

st.set_page_config(
    page_title="RCPSP Scheduler",
    layout="wide",
)

st.title("RCPSP Scheduler")
st.caption(
    "Каркас планировщика с подключаемыми эвристиками. "
    "Выберите параметры задачи, загрузите данные и запустите решение."
)

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

    st.divider()
    st.subheader("Эвристика")

    heuristic_label = st.selectbox("Функция выбора задачи (select_job_fn)",
                                   list(HEURISTICS.keys()))
    heuristic_key = HEURISTICS[heuristic_label]

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
run_col, _ = st.columns([1, 3])

with run_col:
    run_btn = st.button("Запустить планировщик", type="primary",
                        use_container_width=True)

if run_btn:
    if instance_data is None:
        st.error("Сначала загрузите файл данных инстанса.")
        st.stop()

    if uploaded_dsl:
        try:
            uploaded_dsl.seek(0)
            dsl_dict = json.load(uploaded_dsl)
        except Exception as e:
            st.error(f"Ошибка чтения DSL-файла: {e}")
            st.stop()
    else:
        # Генерируем DSL из UI-параметров
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
                "primary": {
                    "metric": primary_metric,
                    "direction": primary_direction,
                }
            },
            "graph_meta_characteristics": {},
            "conditional_scheduling": {
                "enabled": conditional,
                "selection_groups_present": selection_groups,
                "time_precedence_present": time_precedence,
            },
        }

    # Сохраняем DSL во временный файл
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(dsl_dict, tmp, ensure_ascii=False)
        dsl_tmp_path = Path(tmp.name)

    # Подключаем планировщик
    try:
        from scheduler_skeleton import solve, DSLParser
    except ImportError:
        st.error(
            "Не найден `scheduler_skeleton.py`. "
            "Убедитесь, что он лежит рядом с `streamlit_app.py`."
        )
        st.stop()

    # Выбираем эвристику
    def make_select_fn(key):
        if key == "spt":
            def fn(eligible_ids, jobs, snap, meta):
                return min(eligible_ids, key=lambda jid: jobs[jid].duration)
        elif key == "lpt":
            def fn(eligible_ids, jobs, snap, meta):
                return max(eligible_ids, key=lambda jid: jobs[jid].duration)
        elif key == "mslk":
            def fn(eligible_ids, jobs, snap, meta):
                # MSLK: минимальный slack = duration / (successors + 1)
                return min(
                    eligible_ids,
                    key=lambda jid: jobs[jid].duration / (
                            len(jobs[jid].successors) + 1),
                )
        else:
            fn = None
        return fn


    select_fn = make_select_fn(heuristic_key)

    # Захват verbose-лога
    import io
    import sys

    log_buf = io.StringIO()

    with st.spinner("Выполняется планирование..."):
        old_stdout = sys.stdout
        sys.stdout = log_buf
        try:
            result = solve(
                dsl_path=dsl_tmp_path,
                instance_data=instance_data,
                select_job_fn=select_fn,
                verbose=verbose,
            )
            error = None
        except Exception as e:
            result = None
            error = str(e)
        finally:
            sys.stdout = old_stdout

    log_output = log_buf.getvalue()

    if error:
        st.error(f"Ошибка при планировании: {error}")
        if log_output:
            with st.expander("Лог выполнения"):
                st.code(log_output)
        st.stop()

    st.success("Планирование завершено!")
    st.subheader("Результаты")

    obj = result.get("objective", {})
    sched = result.get("schedule", {})
    iters = result.get("iterations", "?")
    final_t = result.get("final_time", "?")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Целевая метрика", obj.get("primary", "—"))
    m2.metric("Работ в расписании", len(sched))
    m3.metric("Итераций", iters)
    m4.metric("Финальное время", final_t)

    if "budget_feasible" in obj:
        if obj["budget_feasible"]:
            st.success("Бюджет невозобновляемых ресурсов не нарушен")
        else:
            st.warning(
                f"Бюджет нарушен: {obj.get('budget_violations', '?')}"
            )

    if "secondary" in obj and obj["secondary"] is not None:
        st.info(f"Вторичная метрика: {obj['secondary']}")

    # Расписание
    with st.expander("Расписание (job_id → start_time)", expanded=True):
        if sched:
            import pandas as pd

            df = pd.DataFrame(
                [
                    {
                        "Job ID": jid,
                        "Start Time": st_val,
                        "Duration": instance_data.get("jobs", [{}])[
                            min(jid - 1, len(instance_data.get("jobs", [])) - 1)
                        ].get("duration", "?")
                        if isinstance(instance_data.get("jobs"), list)
                        else "?",
                    }
                    for jid, st_val in sorted(sched.items(), key=lambda x: x[1])
                ]
            )
            st.dataframe(df, use_container_width=True)

            # Диаграмма Ганта через st.bar_chart
            try:
                import altair as alt

                gantt_data = []
                jobs_list = instance_data.get("jobs", [])
                jobs_dict = {j.get("id"): j for j in jobs_list if isinstance(j, dict)}

                for jid, start in sched.items():
                    dur = jobs_dict.get(jid, {}).get("duration", 1)
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
                        .properties(title="Диаграмма Ганта",
                                    height=max(200, len(sched) * 22))
                    )
                    st.altair_chart(chart, use_container_width=True)
            except ImportError:
                st.info("Установите `altair` для отображения диаграммы Ганта.")

    # Полный объект результата
    with st.expander("Полный объект результата (JSON)"):
        st.json(result)

    # Лог
    if verbose and log_output:
        with st.expander("Лог выполнения"):
            st.code(log_output, language="text")

    # Кнопка скачивания результата
    st.download_button(
        label="Скачать расписание (JSON)",
        data=json.dumps(result, indent=2, ensure_ascii=False),
        file_name="schedule_result.json",
        mime="application/json",
    )
