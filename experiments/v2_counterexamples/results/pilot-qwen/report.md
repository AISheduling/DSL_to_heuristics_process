# В2-LLM — запуск `pilot-qwen`

RPD — отклонение makespan от best_known проекта, %, по допустимым генерациям. «Не хуже LFT» — доля допустимых генераций с makespan ≤ LFT на том же проекте. Уровни: b — без метаданных, v — вердикт, g — свойство (ADR 0004).

## Маршрутизатор

| окружение | s | проектов | сработал |
|---|---|---|---|
| isolated | 0.0 | 2 | 0 |
| isolated | 0.5 | 2 | 2 |
| isolated | 1.0 | 2 | 2 |
| shared | 0.0 | 2 | 0 |
| shared | 0.5 | 2 | 1 |
| shared | 1.0 | 2 | 2 |

## Проекты, где маршрутизатор сработал

| уровень | генераций | допустимых | RPD | не хуже LFT | статусы |
|---|---|---|---|---|---|
| b | 14 | 13 | 17.84 | 0.38 | {'ok': 13, 'runtime_error': 1} |
| v | 14 | 11 | 25.34 | 0.00 | {'ok': 11, 'runtime_error': 3} |
| g | 14 | 13 | 17.17 | 0.31 | {'ok': 13, 'runtime_error': 1} |

## Проекты, где не сработал (v и g — копии b)

| уровень | генераций | допустимых | RPD | не хуже LFT | статусы |
|---|---|---|---|---|---|
| b | 10 | 10 | 14.62 | 0.40 | {'ok': 10} |
| v | 10 | 10 | 14.62 | 0.40 | {'ok': 10} |
| g | 10 | 10 | 14.62 | 0.40 | {'ok': 10} |

## По ячейкам: RPD (допустимых / генераций)

| окружение | s | b | v | g | LFT | LST |
|---|---|---|---|---|---|---|
| isolated | 0.0 | 6.54 (4/4) | 6.54 (4/4) | 6.54 (4/4) | 0.00 | 0.00 |
| isolated | 0.5 | 28.80 (4/4) | 33.64 (3/4) | 18.78 (4/4) | 0.00 | 12.79 |
| isolated | 1.0 | 25.08 (4/4) | 45.19 (3/4) | 8.19 (3/4) | 0.00 | 13.78 |
| shared | 0.0 | 18.32 (4/4) | 18.32 (4/4) | 18.32 (4/4) | 6.26 | 4.49 |
| shared | 0.5 | 12.14 (4/4) | 19.46 (3/4) | 15.71 (4/4) | 4.12 | 2.46 |
| shared | 1.0 | 4.88 (3/4) | 7.67 (4/4) | 26.85 (4/4) | 3.65 | 6.07 |

## Методы (названия из ответа модели), проекты со срабатыванием

- **b**: MINSLK (Minimum Network Slack) priority rule with earliest feasible start — 1; LFT (Latest Finish Time) priority rule with MTS tiebreaker in SSGS — 1; LFT (Latest Finish Time) priority rule with earliest-start allocation — 1; Most Total Successors + Critical Path Length (MTS-CPL) с left-shift — 1; MST-LFT Priority with Resource-Reservation Allocation — 1; CPM-based LFT Priority Rule with Slack-Aware Allocation — 1
- **v**: GRASP (Greatest Resource And Successor Precedence) with duration bonus and conservative resource look-ahead allocation — 1; MINSLK (Minimum Slack) + LPT tie-breaker, Earliest Start allocation — 1; MINSLK + GRAB (priority) / MRU (allocation) — 1; MINSLK with downstream work content tiebreaker + earliest-start allocation — 1; MCS + Resource Pressure with SPT tiebreaker; Allocate: earliest start with resource-load minimization — 1; MINSLK + GRAD (Minimum Total Slack with Greatest Resource Allocation Demand tiebreaker) + Earliest Start allocation — 1
- **g**: CPM-based Critical Path Priority with Resource Conflict Minimization (CP-RCPM) — 1; LFT + LPT priority with Earliest Feasible Start — 1; Late Finish Priority with Earliest Feasible Start — 1; Minimum Dynamic Slack (MDS) priority with earliest feasible start allocation — 1; Longest Path to End + Non-Extending Allocation (LPE-NEA) — 1; Minimum Total Float Priority with Resource-Aware Delay for Non-Critical Jobs — 1
