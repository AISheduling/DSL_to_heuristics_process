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
│   ├── scheduler_skeleton.py         # Каркас решателя
│   ├── calculate_metrics.py          # Вычисление метрик графов
│   └── llm_clients/                  # Скрипты генерации эвристик через LLM
├── data/
│   ├── raw/                          # Исходные файлы (PSPLIB, OR-Library)
│   ├── processed/                    # Готовые инстансы задач (JSON)
│   └── references/                   # DSL и текстовые описания кейсов
├── docs/
│   └── Технический_отчет.pdf         # Технический отчет проекта
├── experiments/                      # Результаты генерации эвристик LLM
│   └── runners/                      # Скрипты прогона эвристик на данных
├── tests/
│   └── test_scheduler.py             # Тесты юнит + интеграционные
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
| `RCMPSP_MULTI_PROJECT` | Многопроектный RCPSP | Суммарный makespan всех проектов |

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
    non_renewable_consumption: dict[int, int]  # потребление NRR (Case 3)
    selection_groups: list[list[int]]    # группы альтернатив (Cases 3, 4)
```

### `Resource` (dataclass)

```python
@dataclass
class Resource:
    id: int
    name: str
    capacity: int       # максимальная мощность (для renewable)
    r_type: str         # "renewable" / "non-renewable" / "global"
    initial_stock: int  # начальный запас (для non-renewable)
```

### `ProblemState` (dataclass)

Изменяемое состояние задачи в процессе планирования. Содержит текущее расписание, активные работы, потребление ресурсов и т.д.

Ключевые методы:

| Метод | Назначение |
|---|---|
| `eligible_jobs()` | Список работ, готовых к запуску (все предшественники выполнены) |
| `can_allocate(job, allocation)` | Проверяет, хватает ли ресурсов на запуск работы |
| `start_job(job_id, allocation)` | Запускает работу, резервирует ресурсы |
| `finish_jobs_at(time)` | Завершает активные работы, освобождает ресурсы |
| `advance_time()` | Перематывает время до ближайшего завершения работы |
| `is_done()` | Все работы выполнены или пропущены? |
| `snapshot()` | Словарь-снапшот текущего состояния для передачи в LLM-функции |

### `ProblemFactory`

Строит `ProblemState` из сырых данных инстанса + `DSLMeta`. Поддерживает все 5 форматов входных данных.

```python
factory = ProblemFactory()
state = factory.build(instance_data, meta)
```

### `ObjectiveCalculator`

Вычисляет значение целевой метрики по завершенному расписанию:

```python
calc = ObjectiveCalculator()
objective = calc.compute(state)
# objective["primary"]         — значение основной метрики
# objective["budget_feasible"] — соблюден ли бюджет NRR (Case 3)
# objective["job_details"]     — детали по каждой работе (Case 2)
```

### Публичный API

Три высокоуровневых функции для работы с каркасом:

#### `build_state(dsl_path, instance_data) -> (DSLMeta, ProblemState)`

Шаги 1 и 2: парсит DSL и строит начальное состояние.

#### `run_schedule(state, select_job_fn, allocate_fn, verbose) -> dict`

Запускает цикл планирования по схеме **SSGS** (Serial Schedule Generation Scheme). Принимает функции выбора и выделения ресурсов.

#### `solve(dsl_path, instance_data, select_job_fn, allocate_fn, verbose) -> dict`

Высокоуровневая точка входа. Объединяет `build_state` + `run_schedule`. Если функции не переданы, используются встроенные эвристики (Most Successors / SPT).

```python
from scheduler_skeleton import solve

result = solve(
    dsl_path="data/references/Case1_DSL.json",
    instance_data=instance_data,
    select_job_fn=None,
    allocate_fn=None,
    verbose=True,
)
# result["schedule"]             — dict {job_id: start_time}
# result["objective"]["primary"] — значение метрики
# result["iterations"]           — число итераций
# result["final_time"]           — время завершения
```

### Интерфейс функций для LLM

Каркас принимает две функции, которые можно реализовать вручную или сгенерировать языковой моделью:

```python
def select_job(eligible_ids, jobs, snapshot, meta) -> int:
    """
    Выбирает следующую работу для запуска.

    eligible_ids : list[int]          — id работ, готовых к запуску
    jobs         : dict[int, Job]     — все работы задачи
    snapshot     : dict               — текущее состояние планировщика:
        "current_time"       : int
        "completed_jobs"     : list[int]
        "active_jobs"        : dict[int, int]   # job_id -> finish_time
        "eligible_jobs"      : list[int]
        "renewable_used"     : dict[int, int]   # resource_id -> used
        "non_renewable_stock": dict[int, int]
        "skipped_jobs"       : list[int]
    meta         : DSLMeta            — метаданные DSL
    """
    return max(eligible_ids, key=lambda jid: len(jobs[jid].successors))


def allocate(job, resources, snapshot, meta) -> dict[int, int]:
    """
    Определяет, сколько каждого ресурса выделить работе.

    job       : Job
    resources : dict[int, Resource]
    Возвращает: {resource_id: amount}
    """
    return dict(job.resources_required)
```

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
python tests/test_scheduler.py
```

Тесты проверяют:
1. `DSLParser` - корректный разбор всех 5 DSL-кейсов
2. `ProblemFactory` - правильная структура Jobs и Resources
3. `ProblemState` - механика состояния (eligible\_jobs, advance\_time, ресурсный учет)
4. `ObjectiveCalculator` - расчет Makespan, штрафа, NRR-бюджета
5. Интеграционные тесты `solve()` - синтетические инстансы по всем кейсам
6. Smoke-тест - парсинг реальных DSL-файлов из `data/references/`

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
python src\runners\run_heuristics_dsl.py

# Text-подход
python src\runners\run_heuristics_text.py

# Skeleton-подход
python src\runners\run_heuristics_skeleton.py
```

Каждый runner:
- читает сгенерированные эвристики из соответствующей папки `experiments/`
- запускает их на инстансах из `data/processed/`
- сохраняет результаты в `results/dsl/`, `results/text/` или `results/skeleton/`

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
