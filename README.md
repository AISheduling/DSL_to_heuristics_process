# RCPSP Scheduler - каркас решателя задач планирования

Каркас планировщика задач типа **RCPSP** (Resource-Constrained Project Scheduling Problem) с поддержкой подключаемых эвристик и интеграцией LLM-кода.

---

## Содержание

- [Структура проекта](#структура-проекта)
- [Поддерживаемые типы задач](#поддерживаемые-типы-задач)
- [Архитектура `scheduler_skeleton.py`](#архитектура-scheduler_skeletonpy)
- [Установка зависимостей](#установка-зависимостей)
- [Запуск веб-приложения](#запуск-веб-приложения)
- [Описание интерфейса `app.py`](#описание-интерфейса-apppy)
- [Запуск тестов](#запуск-тестов)
- [LLM-клиенты: генерация эвристик](#llm-клиенты-генерация-эвристик)
- [Runners: прогон эвристик на данных](#runners-прогон-эвристик-на-данных)
- [Ноутбуки анализа](#ноутбуки-анализа)

---

## Структура проекта

```
DSL_to_heuristics_process/
├── src/
│   ├── app.py                        # Streamlit-приложение (UI)
│   ├── scheduler_skeleton.py         # Каркас решателя (SSGS + legacy)
│   ├── schedule_checker.py           # Независимый чекер расписаний (не импортирует каркас)
│   ├── calculate_metrics.py          # Метрики графов весенних DSL (legacy, см. ADR 0002)
│   ├── indicators.py                 # 12 стандартных индикаторов проекта (guo2021) + доп. признаки
│   ├── psplib.py                     # Парсер PSPLIB .sm -> формат data/processed, файлы решений
│   ├── references.py                 # Эталоны PSPLIB: BKS, нижние границы, CPM (PSPLIB + RCPLIB)
│   ├── metrics.py                    # RPD / ARPD относительно эталона
│   ├── priority_rules.py             # Базовые правила приоритета LFT / LST / MTS / GP1 для SSGS
│   ├── psgs.py                       # Параллельная схема — только для сверки правил со статьями
│   ├── stats.py                      # Парный тест Уилкоксона, поправка Холма
│   ├── dsl_builder.py                # DSL из инстанса: составы индикаторов none / network / resource / all
│   └── llm_clients/                  # Скрипты генерации эвристик через LLM; prompt_v1.py — промпт В1
├── data/
│   ├── raw/                          # Исходные файлы (PSPLIB, OR-Library)
│   ├── processed/                    # Готовые инстансы задач (JSON)
│   ├── psplib/                       # PSPLIB J30/J60/J120 (не в git, см. SOURCES.md)
│   ├── rcplib/                       # RCPLIB: индикаторы и эталоны (не в git, см. SOURCES.md)
│   └── references/                   # DSL и текстовые описания кейсов
├── docs/
│   ├── adr/                          # Архитектурные решения (0001 — статусы, чекер, allocate_fn; 0002 — индикаторы; 0003 — протокол В1)
│   ├── literature-review/            # Обзор литературы (этап 0)
│   └── technical_report.pdf          # Технический отчет проекта
├── experiments/                      # Результаты генерации эвристик LLM
│   ├── v1_pilot/                     # Эксперимент В1: выборка, генерация, прогон в каркасе, оценка (evaluate.py)
│   └── runners/                      # Прогон эвристик: runner_common.py + три точки входа
├── tests/                            # pytest: ядро, чекер, раннеры, пять постановок
│   ├── test_kernel.py                # Негативные тесты дефектов ядра и контракта функций
│   ├── test_checker.py               # Сломанные и корректные расписания через чекер
│   ├── test_runner_common.py         # Статусы, извлечение расписания, таймаут
│   ├── test_psplib.py                # Парсер .sm: j301_1 = Case 1, отказ на чужих форматах
│   ├── test_indicators.py            # Индикаторы: ручные примеры, инварианты, guo2021, RCPLIB
│   ├── test_references.py            # Эталоны: файлы решений, CPM = MPM-Time, BKS из двух источников
│   ├── test_metrics.py               # RPD / ARPD, детерминированность выборки В1
│   ├── test_dsl_builder.py           # DSL из инстанса, DSLMeta.indicators, промпт В1
│   ├── test_generation.py            # Генерация В1 на подменном клиенте: продолжение, ошибки
│   ├── test_run_kernel.py            # Правила приоритета, общий модуль функций, прогон В1 в каркасе
│   ├── test_evaluate.py              # Уилкоксон, Холм, отчет В1 на подготовленных результатах
│   └── test_skeleton_cases.py        # Парсер, фабрика, состояние, цель, 5 постановок
├── pytest.ini
├── requirements-dev.txt
├── results/                          # Метрики прогона эвристик
├── notebooks/                        # Jupyter-ноутбуки анализа
├── .gitignore
└── requirements.txt
```

---

## Поддерживаемые типы задач

| Идентификатор | Название | Метрика |
|---|---|---|
| `PSPLIB_J30_RCPSP` | Базовый RCPSP (J30 PSPLIB) | Makespan |
| `SINGLE_MACHINE_JIT` | Одна машина, JIT (Just-in-Time) | Суммарный штраф за раннее/позднее выполнение |
| `RCPSP_MULTI_RESOURCE` | RCPSP с невозобновляемыми ресурсами | Makespan + ограничение бюджета NRR |
| `CONDITIONAL_RCPSP` | RCPSP с условными ограничениями | Makespan |
| `RCMPSP_MULTI_PROJECT` | Многопроектный RCPSP | Суммарный makespan всех проектов (`total_makespan`; максимум отдаётся как `portfolio_makespan`) |

Cases 3 и 4 (данные 4TU с группами выбора) в текущем каркасе **не поддержаны**: после выбора
ветви потомки пропущенных работ не становятся готовыми, обе схемы останавливаются с
`status="incomplete", reason="deadlock"`. Так было и в версии `d3dadbc6`. Семантику групп
выбора нужно определить отдельно (см. `docs/adr/0001-...md`).

---

## Архитектура `scheduler_skeleton.py`

### `DSLMeta` (dataclass)

Результат парсинга DSL-файла. Хранит всю метаинформацию о задаче:

```python
@dataclass
class DSLMeta:
    project_id: str              # идентификатор задачи (напр. "PSPLIB_J30_RCPSP")
    problem_type: str            # текстовое описание типа задачи
    constraint_types: list[str]  # список типов ограничений
    resource_nature: str         # "Renewable" / "Non-Renewable" / "Renewable and Non-Renewable"
    execution_mode: str          # "Single-Mode" / "Multi-Mode"
    uncertainty: str             # "Deterministic"
    primary_metric: str          # целевая метрика (напр. "Makespan")
    primary_direction: str       # "Minimize" / "Maximize"
    secondary_metric: str|None   # вторичная метрика (если есть)
    secondary_direction: str|None
    secondary_params: dict       # параметры вторичной метрики (due_date, budget_limit, …)
    graph: dict                  # характеристики графа (nodes, edges, cpl, max_parallelism)
    conditional_scheduling: bool # включено ли условное планирование
    selection_groups_present: bool
    time_precedence_present: bool
    has_non_renewable: bool      # есть ли невозобновляемые ресурсы
    is_multi_project: bool
    is_single_machine: bool
```

### `DSLParser`

Читает DSL из файла или словаря, возвращает `DSLMeta`.

```python
parser = DSLParser()
meta = parser.parse_file("data/references/Case1_DSL.json")
meta = parser.parse_dict({"project_id": "PSPLIB_J30_RCPSP", ...})
print(parser.summary(meta))  # человекочитаемый отчет
```

### `Job` (dataclass)

```python
@dataclass
class Job:
    id: int
    duration: int
    predecessors: list[int]
    successors: list[int]
    resources_required: dict[int, int]   # resource_id -> количество
    earliness_penalty: int               # штраф за раннее выполнение (Case 2)
    tardiness_penalty: int               # штраф за позднее выполнение (Case 2)
    project_id: int | None               # id проекта (Case 5)
    local_id: int | None                 # id внутри проекта; id = project_id * 10^k + local_id
    non_renewable_consumption: dict[int, int]  # потребление NRR (Case 3)
    non_renewable_production: dict[int, int]   # производство NRR (Case 3)
    selection_groups: list[list[int]]    # группы альтернатив (Cases 3, 4)
```

### `Resource` (dataclass)

```python
@dataclass
class Resource:
    id: int
    name: str
    capacity: int       # максимальная мощность (для renewable)
    r_type: str         # "renewable" | "non-renewable" (global, nonrenewable, non_renewable нормализуются)
    initial_stock: int  # начальный запас (для non-renewable)
```

### `ProblemState` (dataclass)

Изменяемое состояние задачи: расписание, профиль загрузки возобновляемых ресурсов по тактам,
запас невозобновляемых, пропущенные работы; для схемы `legacy` — ещё текущее время,
активные работы и забронированные выделения.

Ключевые методы:

| Метод | Схема | Назначение |
|---|---|---|
| `eligible_jobs(scheme)` | обе | Готовые работы: `ssgs` — все предшественники запланированы; `legacy` — завершены |
| `feasible_starts(job, limit)` | ssgs | Допустимые времена старта по предшествованию и профилю ресурсов на `[t, t+d)` |
| `place_job(job_id, start)` | ssgs | Ставит работу, обновляет профиль, запас NRR и группы выбора |
| `can_allocate(job, allocation)` | legacy | Выделение покрывает потребность, укладывается в мощности, запаса NRR хватает |
| `start_job(job_id, allocation)` | legacy | Бронирует не меньше `resources_required`, запоминает выделение |
| `finish_jobs_at(time)` / `advance_time()` | legacy | Освобождает ровно забронированное |
| `unscheduled_jobs()` / `is_done()` | обе | Незапланированные (кроме пропущенных) / всё поставлено |
| `snapshot(scheme)` | обе | Словарь для LLM-функций (см. ниже) |

### `ProblemFactory`

Строит `ProblemState` из сырых данных инстанса + `DSLMeta`. Поддерживает все 5 форматов входных данных.

```python
factory = ProblemFactory()
state = factory.build(instance_data, meta)
```

### `ObjectiveCalculator`

Вычисляет цель по **полному** расписанию (по неполному `run_schedule` отдаёт `primary=None`):

```python
objective = ObjectiveCalculator.compute(state)
# objective["primary"]             — основная метрика
# objective["makespan"]            — Cases 1, 3, 4
# objective["total_makespan"]      — Case 5: сумма makespan проектов; "portfolio_makespan" — максимум
# objective["total_et_penalty"]    — Case 2
# objective["non_renewable_used"], ["budget_violations"], ["budget_feasible"] — Case 3
```

Для публикуемых чисел используется не он, а независимый чекер (ниже).

### Публичный API

Три высокоуровневых функции для работы с каркасом:

#### `build_state(dsl_path, instance_data) -> (DSLMeta, ProblemState)`

Шаги 1 и 2: парсит DSL и строит начальное состояние.

#### `run_schedule(state, select_job_fn, allocate_fn=None, verbose=False, scheme="ssgs", strict=False) -> dict`

Строит расписание функциями выбора работы и выбора времени старта.

- `scheme="ssgs"` (по умолчанию) — стандартная Serial SGS: готовы работы, у которых все
  предшественники запланированы; выбранная работа ставится в одно из допустимых времён
  старта (по предшествованию и профилю ресурсов на всём интервале), включая вставку
  раньше уже поставленных работ.
- `scheme="legacy"` — пошаговая схема версии `d3dadbc6` (старт только в текущий момент,
  готовность по завершённым предшественникам). Оставлена для воспроизведения весенних
  результатов; ресурсы и в ней бронируются по `resources_required`.
- `strict=True` — нарушение контракта функций или неполное расписание бросают
  `SchedulerContractError`.

```python
result = run_schedule(state, select_job_fn, allocate_fn)
# result["status"]                 — "complete" | "incomplete"
# result["reason"]                 — None | "deadlock" | "infeasible" | "max_iterations"
# result["detail"], ["unscheduled"], ["skipped"]
# result["invalid_select_count"]   — сколько раз select_job_fn вернула id не из eligible
# result["allocate_violations"]    — сколько раз allocate_fn вернула недопустимое значение
# result["schedule"]               — {job_id: start_time}
# result["objective"]["primary"]   — None, если status != "complete"
# result["iterations"], ["final_time"], ["scheme"]
```

Ошибки не скрываются: невалидный `job_id` заменяется на `eligible[0]`, недопустимое
время старта — на самое раннее, но оба случая попадают в счётчики результата.

#### `solve(dsl_path, instance_data, select_job_fn=None, allocate_fn=None, verbose=False, scheme="ssgs", strict=False) -> dict`

`build_state` + `run_schedule`. Без функций используются встроенные правила
(Most Successors / SPT для одной машины; самое раннее время старта).

### Интерфейс функций для LLM

Каркас принимает две функции. Допустимость расписания обеспечивает каркас, у функций
остаются только решения: какую работу ставить следующей и в какое из допустимых времён.

```python
def select_job_fn(eligible_ids, jobs, snapshot, meta) -> int:
    """
    Выбирает следующую работу.

    eligible_ids : list[int]          — работы, у которых все предшественники запланированы
    jobs         : dict[int, Job]     — все работы задачи
    snapshot     : dict               — состояние планировщика:
        "scheduled_jobs"     : list[int]
        "start_times"        : dict[int, int]   # job_id -> start
        "finish_times"       : dict[int, int]   # job_id -> finish
        "eligible_jobs"      : list[int]
        "capacity"           : dict[int, int]   # resource_id -> мощность
        "non_renewable_stock": dict[int, int]
        "skipped_jobs"       : list[int]
        "current_time"       : int              # горизонт поставленных работ
    meta         : DSLMeta            — метаданные DSL
    """
    return max(eligible_ids, key=lambda jid: len(jobs[jid].successors))


def allocate_fn(job, feasible_starts, snapshot, meta) -> int:
    """
    Выбирает время старта из допустимых.

    feasible_starts : list[int]  — допустимые времена по возрастанию (построил каркас:
                                   предшествование + профиль ресурсов на всём интервале)
    Возвращает одно значение из feasible_starts; иначе берётся самое раннее
    и увеличивается allocate_violations.
    """
    return feasible_starts[0]
```

В схеме `legacy` действует старый контракт `allocate_fn(job, resources, snapshot, meta) -> dict[int, int]`;
выделение меньше `resources_required` или по неизвестному ресурсу считается нарушением,
каркас бронирует требуемое.

### Независимый чекер `schedule_checker.py`

Один чекер для всех подходов (Text, DSL, Skeleton, встроенные правила). Не импортирует
каркас, проверяет расписание по исходному инстансу и пересчитывает цель сам:

```python
from schedule_checker import validate_schedule

report = validate_schedule(instance_data, result["schedule"])
# report["status"]      — "valid" | "invalid" | "incomplete" | "empty"
# report["violations"]  — [{"type": "precedence" | "renewable_capacity" | "non_renewable_budget"
#                           | "missing_job" | "unknown_job" | "invalid_start" | "selection_group", ...}]
# report["makespan"], report["objective"]["primary"] — пересчитаны по данным (None, если не valid)
# report["scheduled"], report["total"], report["skipped"]
```

`valid` не означает `optimal`. Ключ работы многопроектной задачи: глобальный id
(`project_id * 10^k + local_id`), кортеж `(project_id, local_id)` или строка `"project_id:local_id"`.

---

## Установка зависимостей

```bash
git clone https://github.com/AISheduling/DSL_to_heuristics_process.git
cd DSL_to_heuristics_process
pip install -r requirements.txt
```

---

## Запуск веб-приложения

Файлы `app.py` и `scheduler_skeleton.py` должны находиться в **одной директории**.

```bash
streamlit run src/app.py
```

Приложение откроется в браузере по адресу `http://localhost:8501`.

---

## Описание интерфейса `app.py`

### Блок «Параметры задачи» (левая колонка)

Здесь настраивается вручную тип решаемой задачи:

**Тип задачи** — выбор из 5 вариантов:
- RCPSP (base) — базовый RCPSP из PSPLIB J30
- Single-Machine JIT — одна машина, минимизация штрафа за отклонение от директивного срока
- RCPSP with non-renewable resources — с невозобновляемыми ресурсами и бюджетом
- RCPSP with conditional restrictions — с группами выбора альтернативных работ
- Multi-Project RCPSP — многопроектная постановка

**Целевая метрика:**
- Makespan — минимизация длительности расписания
- Total Earliness/Tardiness Penalty — минимизация штрафа раннего/позднего выполнения
- Non-Renewable Resource Consumption — минимизация расхода NRR
- Total Makespan (для Multi-Project) — суммарный makespan по всем проектам

**Тип ресурсов:** Renewable / Non-Renewable / Renewable and Non-Renewable

**Режим выполнения:** Single-Mode / Multi-Mode

**Дополнительные флаги** (раскрывающийся блок):
- Условное планирование (conditional scheduling)
- Группы выбора (selection groups)
- Временные приоритеты (time precedence)

**Подробный лог выполнения** — включает вывод каждой итерации планировщика.

### Блок «Данные инстанса» (правая колонка)

Загрузка входных данных задачи в формате JSON. После загрузки показывается краткая сводка (число работ, число ресурсов) и предпросмотр первых трех работ.

**DSL-описание (опционально)** — если файл не загружен, DSL формируется автоматически из выбранных параметров выше.

### Вкладка «Встроенная эвристика»

Выбор одного из четырех встроенных правил приоритета:

| Эвристика                      | Описание |
|--------------------------------|---|
| Most Successors (по умолчанию) | Первой запускается работа с наибольшим числом преемников |
| SPT - Shortest Processing Time | Сначала самые короткие работы |
| LPT - Longest Processing Time  | Сначала самые длинные работы |
| MSLK - Minimum Slack           | Минимальный запас хода |

Нажмите **«Запустить планировщик»** — появятся результаты.

### Вкладка «Вставить код от LLM»

Позволяет вставить Python-код двух функций (`select_job` и `allocate`), сгенерированный языковой моделью, и запустить с ним планировщик.

- **«Проверить синтаксис»** — компилирует код без запуска, выводит OK или текст ошибки.
- **«Запустить с этим кодом»** — полный прогон планировщика с переданными функциями.
- Справка по доступным полям — кнопка «Справка: какие поля доступны в функциях».

### Результаты

После успешного запуска отображаются:

- Две метрики: значение целевой функции и число запланированных работ.
- Таблица расписания: Job ID, Start Time, Duration, End Time.
- Диаграмма Ганта.
- Полный JSON-объект результата.
- Лог выполнения (если включен verbose).
- Кнопка скачивания расписания в формате JSON.

---


## Запуск тестов

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Пути в тестах относительные, запуск из чистого клона. Что проверяется:
1. `tests/test_kernel.py` — каждый дефект ядра из issue #1 отдельным негативным тестом:
   формат `resource_requirements` Case 1, написание `nonrenewable`, бюджет NRR,
   обход ресурсов через `allocate_fn`, освобождение забронированного, тупик → `incomplete`,
   коллизии id в Case 5, строгий парсинг, согласованность срока Case 2, вставка SSGS в окно.
2. `tests/test_checker.py` — намеренно сломанные расписания отклоняются с нужной причиной,
   корректные проходят; чекер не импортирует каркас.
3. `tests/test_runner_common.py` — единые статусы, извлечение расписания из вывода полного
   решателя, таймаут, доли от всех генераций.
4. `tests/test_skeleton_cases.py` — парсер, фабрика, состояние, цель, `solve()` в обеих схемах
   на синтетических инстансах и на `data/processed/` с перепроверкой чекером; для Cases 3–4
   закреплён честный статус `incomplete`.
5. `tests/test_psplib.py` — парсер `.sm`: `j301_1` даёт в точности `Case1_PSPLIB_j301_1.json`.
6. `tests/test_indicators.py` — индикаторы на сетях, посчитанных вручную, инварианты
   (фиктивные работы, перенумерация), min/max по J30/J60/J120 против табл. 3–4 guo2021
   и построчная сверка 11 индикаторов с RCPLIB на всех 1560 инстансах. Сверки пропускаются,
   если PSPLIB или RCPLIB не скачаны (`data/psplib/SOURCES.md`, `data/rcplib/SOURCES.md`).
7. `tests/test_references.py` — файлы решений PSPLIB, CPM совпадает с MPM-Time из `.sm`,
   BKS — лучшее из PSPLIB и RCPLIB, противоречивые границы отклоняются.
8. `tests/test_metrics.py` — RPD / ARPD и выборка В1 (детерминирована, `sample.json`
   соответствует правилу отбора).
9. `tests/test_dsl_builder.py` — DSL из инстанса (составы, без утечки имени и эталонов,
   (а) и (б) различаются только блоком индикаторов), каркас читает DSL-словарь, промпт В1
   общий для обоих уровней и без полей весенних постановок.
10. `tests/test_generation.py` — генерация В1 на подменном клиенте LLM: план 30 × 2 × 3,
    продолжение после обрыва, запрет продолжать с другими настройками, ошибки API и разбора.
11. `tests/test_run_kernel.py` — правила приоритета (поздние сроки по CPM, допустимые
    расписания), общий модуль для двух функций LLM, прогон подготовленных генераций в каркасе,
    GP1 на ручном примере, сверка LFT/LST (лучшее из SSGS и PSGS) с табл. 14 luo2022 на J30.
12. `tests/test_evaluate.py` — тест Уилкоксона и поправка Холма, отчет В1 (ARPD, доля
    допустимых, сравнения, разбор по индикаторам) на подготовленных результатах.

---


## LLM-клиенты: генерация эвристик

Скрипты генерируют эвристики через LLM и сохраняют результаты в папку `experiments/`.

Требуется переменная окружения:
```bash
set LITELLM_API_KEY=your_api_key     # Windows
export LITELLM_API_KEY=your_api_key  # Linux/Mac
```

### DSL-подход

```bash
# Все кейсы
python src\llm_clients\llm_client_for_DSL_description.py

# Один кейс
python src\llm_clients\llm_client_for_DSL_description.py "data\references\full DSL description of projects\Case1_DSL.json"
```

Читает DSL из `data/references/full DSL description of projects/`.  
Сохраняет результаты в `experiments/experiments_dsl/<timestamp>/`.

### Text-подход

```bash
# Все кейсы
python src\llm_clients\llm_client_for_text_description.py

# Один кейс
python src\llm_clients\llm_client_for_text_description.py "data\references\text_description_of_projects\Case1_text.txt"
```

Читает промпты из `data/references/text_description_of_projects/`.  
Сохраняет результаты в `experiments/experiment text/<timestamp>/`.

### Skeleton-подход

```bash
python src\llm_clients\llm_client_for_generating_two_solver_functions.py
```

Читает краткие DSL из `data/references/brief DSL description of projects/`.  
Сохраняет результаты в `experiments/experiment_skeleton/<timestamp>/`.

---

## Runners: прогон эвристик на данных

После генерации эвристик запустите соответствующий runner для получения метрик.

```bash
# DSL-подход
python experiments/runners/run_heuristics_dsl.py

# Text-подход
python experiments/runners/run_heuristics_text.py

# Skeleton-подход (по умолчанию scheme=ssgs; весенние функции — только --scheme legacy)
python experiments/runners/run_heuristics_skeleton.py [--scheme ssgs|legacy]
```

Общий слой — `experiments/runners/runner_common.py`. Каждый runner:
- читает сгенерированные эвристики из соответствующей папки `experiments/`;
- запускает их на инстансах из `data/processed/` в отдельном процессе с общим таймаутом 30 с;
- проверяет расписание независимым чекером и берёт качество только из него;
- сохраняет строки и сводку в `results/dsl/`, `results/text/` или `results/skeleton/`.

Единые статусы для всех подходов, доли считаются **от всех генераций**:

| Статус | Значение |
|---|---|
| `generation_error` | LLM не вернула код |
| `compile_error` | код не компилируется или нет нужной функции |
| `runtime_error` | исключение при выполнении |
| `timeout` | превышен таймаут |
| `no_schedule` | выполнение завершилось, но расписание из вывода не извлекается |
| `infeasible` | чекер нашёл нарушения |
| `incomplete` | расписание допустимо, но не все работы запланированы |
| `ok` | полное допустимое расписание |

Для Skeleton в строку дополнительно пишутся `kernel_status`, `reason`,
`invalid_select_count`, `allocate_violations`, `scheme`.

## Данные PSPLIB и индикаторы проекта

PSPLIB J30 — отладка и настройка, J60/J120 — финальный тест. Архивы, решения и
контрольные суммы описаны в `data/psplib/SOURCES.md`; распакованные инстансы лежат в
`data/psplib/instances/<набор>/`. Формулы индикаторов и результаты сверки — в
`docs/adr/0002-project-indicators.md`.

```bash
# индикаторы набора в CSV (каталог .sm или .json формата data/processed)
python src/indicators.py data/psplib/instances/j30 j30_indicators.csv
```

```python
from psplib import parse_sm_file
from indicators import compute_indicators
inst = parse_sm_file("data/psplib/instances/j30/j301_1.sm")
compute_indicators(inst)  # {"standard", "network", "resource", "extended"}
```

### Эталоны и метрика

`src/references.py` собирает для каждого инстанса эталоны: BKS — минимум верхних границ
из файлов решений PSPLIB и RCPLIB v6 (`bks_source` — откуда), нижнюю границу — максимум
из CPM, `lb` PSPLIB и `LB-lit` RCPLIB, флаг `optimal` (LB = BKS). Без RCPLIB работает
только по файлам PSPLIB. `src/metrics.py` — RPD = 100 · (makespan − BKS) / BKS и ARPD;
прогоны без допустимого расписания в ARPD не входят и считаются отдельно
(`docs/adr/0003-v1-experiment-protocol.md`).

```python
from references import load_references
from metrics import rpd
refs = load_references("j60")           # {"j601_1": Reference(cpm, lb, bks, bks_source, optimal)}
rpd(72, refs["j601_1"].bks)
```

### Выборка первого эксперимента В1

```bash
python experiments/v1_pilot/make_sample.py   # --seed 2026 --pilot 15 по умолчанию
```

По одному инстансу на каждую комбинацию параметров ProGen (J60 — 48, J120 — 60, всего 108),
пилот — 15 случайных инстансов из каждого набора. В `experiments/v1_pilot/sample.json`
для каждого инстанса записаны эталоны и 12 индикаторов. Файл хранится в git; тест
`tests/test_metrics.py` проверяет, что он соответствует правилу отбора.

### DSL из инстанса и промпт В1

`src/dsl_builder.py` строит DSL для одномодового RCPSP прямо из инстанса, без рукописных
файлов. Составы метаданных: `none` (без индикаторов, уровень (б) В1), `all` (12 индикаторов,
уровень (а)), `network` и `resource` (для В2). Каркас принимает DSL-словарь и отдает
индикаторы функциям эвристики как `meta.indicators`. Промпт В1 — `src/llm_clients/prompt_v1.py`:
общий для обоих уровней, различается только DSL (`docs/adr/0003-v1-experiment-protocol.md`).

```python
from dsl_builder import build_dsl
from scheduler_skeleton import build_state, run_schedule, default_select, default_allocate
dsl = build_dsl(inst, "all")             # {"project_id": "RCPSP", ..., "project_indicators": {...}}
meta, state = build_state(dsl, inst)      # meta.indicators == {"n": 60, "os": 0.259, ...}
run_schedule(state, default_select, default_allocate)
```

### Генерация эвристик В1

Нужен ключ прокси LLM: переменная окружения `LITELLM_API_KEY` (в git не попадает).

```bash
# план и пример промпта без вызовов API
python experiments/v1_pilot/generate.py --run pilot-haiku --pilot-only --gens 3 --model anthropic/claude-haiku-5-5 --dry-run
# проба: 2 вызова
python experiments/v1_pilot/generate.py --run probe-haiku-2 --pilot-only --gens 3 --model anthropic/claude-haiku-5-5 --limit 2 --workers 1
# пилот: 30 инстансов x 2 уровня x 3 генерации = 180 вызовов
python experiments/v1_pilot/generate.py --run pilot-haiku --pilot-only --gens 3 --model anthropic/claude-haiku-5-5 --workers 4
```

Модель указывается обязательно (`--model`); каждой модели — свой `--run`.
Каждый ответ — отдельный файл `experiments/v1_pilot/generations/<run>/<инстанс>__<уровень>__g<k>.json`.
Повторный запуск с тем же `--run` продолжает с места обрыва; `--retry-errors`
перезапрашивает файлы с ошибкой. Настройки (модель, `temperature` 0.7, `max_tokens` 16000,
версия промпта, коммит) пишутся в `manifest.json`, итог — в `summary.json`
(`docs/adr/0003-v1-experiment-protocol.md`, п. 7).

### Прогон генераций в каркасе (шаг 5)

```bash
python experiments/v1_pilot/run_kernel.py --run pilot-haiku
```

Каждая пара функций из `generations/<run>/` запускается только на своем инстансе: одно
построение SSGS в отдельном процессе (таймаут 30 с), makespan — из независимого чекера.
Код `select_job_fn` и `allocate_fn` исполняется в одном модуле, чтобы общие объявления
(кэш, вспомогательные функции) были видны обеим функциям. На тех же инстансах считаются
базовые правила `src/priority_rules.py` (LFT, LST, MTS, GP1 из luo2022) и встроенное
правило каркаса. GP1 реализован по формуле статьи, но ее число не воспроизводит
(ADR 0003, п. 8).
Результат — `experiments/v1_pilot/results/<run>/`: `runs.csv`, `baselines.csv`, `summary.json`
(`docs/adr/0003-v1-experiment-protocol.md`, п. 8).

### Оценка (шаг 6)

```bash
python experiments/v1_pilot/evaluate.py --run pilot-haiku --price-in 0.10 --price-out 0.50 --spent-usd 0.0991
```

Доля допустимых генераций и ARPD к BKS и к CPM по уровням (а), (б) и правилам; парные
сравнения по инстансам (а)–(б), (а)–LST, (б)–LST — тест Уилкоксона с поправкой Холма и
порог δ = 0,5 п. п.; разбор по RS, OS, RF; стоимость генерации — фактическое списание
(`--spent-usd`, Spend ключа в LiteLLM за запуск) и оценка по ценам ($ за 1 млн токенов).
Прокси списывает примерно вчетверо меньше оценки по ценам ключа, поэтому основное число —
списание.
Результат — `experiments/v1_pilot/results/<run>/report.md` и `report.json`
(`docs/adr/0003-v1-experiment-protocol.md`, п. 9).

## Версии каркаса и данных

- Весенние результаты (технический отчёт, версия `d3dadbc6`) получены каркасом из коммита
  `224bf39` («improve scheduler_skeleton and runner for Cases 3-5»), который дополнял
  `77187c3`. Это та версия, что воспроизводится схемой `legacy`; её дефекты и причины
  неинтерпретируемости чисел — в `docs/adr/0001-...md` и issue #1.
- Case 2: директивный срок приведён к сырому файлу OR-Library (`sch50`, инстанс 1, `h = 0.2`):
  `Σp = 549`, `d = 109` вместо `106` (в данных, DSL и текстовом описании).

---

## Ноутбуки анализа

Ноутбуки находятся в `notebooks/2nd semester/` и читают данные напрямую из `results/` и `experiments/`.

### Анализ_метрик_экспериментов.ipynb

Сравнение генерируемых эвристик по трем подходам:
- надежность генерации (% успешных запусков)
- значения целевой функции по кейсам
- анализ ошибок
- детальный анализ по каждому кейсу с нижними границами (CPL)

### Анализ_расхода_токенов.ipynb

Анализ диалог-стоимости (prompt / completion / total tokens) по трем подходам и пяти кейсам.  
Данные загружаются автоматически из `experiments/` по относительному пути:
