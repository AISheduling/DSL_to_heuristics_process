# В2-LLM — запуск `main-qwen`

RPD — отклонение makespan от best_known проекта, %, по допустимым генерациям. «Не хуже LFT» — доля допустимых генераций с makespan ≤ LFT на том же проекте. Уровни: b — без метаданных, v — вердикт, g — свойство (ADR 0004).

## Маршрутизатор

| окружение | s | проектов | сработал |
|---|---|---|---|
| isolated | 0.0 | 10 | 0 |
| isolated | 0.5 | 10 | 9 |
| isolated | 1.0 | 10 | 10 |
| shared | 0.0 | 10 | 4 |
| shared | 0.5 | 10 | 7 |
| shared | 1.0 | 10 | 8 |

## Проекты, где маршрутизатор сработал

| уровень | генераций | допустимых | RPD | не хуже LFT | статусы |
|---|---|---|---|---|---|
| b | 190 | 174 | 19.17 | 0.21 | {'ok': 174, 'runtime_error': 16} |
| v | 190 | 174 | 29.34 | 0.11 | {'ok': 174, 'runtime_error': 15, 'compile_error': 1} |
| g | 190 | 152 | 29.36 | 0.31 | {'ok': 152, 'runtime_error': 34, 'compile_error': 3, 'generation_error': 1} |

## Проекты, где не сработал (v и g — копии b)

| уровень | генераций | допустимых | RPD | не хуже LFT | статусы |
|---|---|---|---|---|---|
| b | 110 | 97 | 12.26 | 0.62 | {'runtime_error': 11, 'ok': 97, 'compile_error': 2} |
| v | 110 | 97 | 12.26 | 0.62 | {'runtime_error': 11, 'ok': 97, 'compile_error': 2} |
| g | 110 | 97 | 12.26 | 0.62 | {'runtime_error': 11, 'ok': 97, 'compile_error': 2} |

## По ячейкам: RPD (допустимых / генераций)

| окружение | s | b | v | g | LFT | LST |
|---|---|---|---|---|---|---|
| isolated | 0.0 | 6.67 (44/50) | 6.67 (44/50) | 6.67 (44/50) | 0.00 | 0.00 |
| isolated | 0.5 | 18.44 (46/50) | 25.65 (47/50) | 27.69 (39/50) | 0.00 | 8.54 |
| isolated | 1.0 | 28.84 (47/50) | 47.20 (44/50) | 32.96 (37/50) | 0.00 | 15.80 |
| shared | 0.0 | 12.62 (45/50) | 18.21 (45/50) | 22.87 (43/50) | 5.07 | 7.03 |
| shared | 0.5 | 11.69 (44/50) | 19.45 (45/50) | 22.75 (43/50) | 5.05 | 5.82 |
| shared | 1.0 | 20.99 (45/50) | 22.25 (46/50) | 25.51 (43/50) | 5.33 | 7.30 |

## Методы (названия из ответа модели), проекты со срабатыванием

- **b**: Minimum Slack Time (MST) + Earliest Feasible Start (EFS) — 2; Minimum Slack Time (MST) + Earliest Feasible Start — 2; Minimum Slack Time (MST) with composite tie-breaking + Earliest Feasible Start allocation — 1; LFT (Latest Finish Time) priority rule + ES (Early Start) scheduling rule — 1; LFT + Total Successors priority with Earliest Start allocation — 1; SSGS + MLFT (Minimum Late Finish Time) with MTS tiebreaker + Earliest Start — 1
- **v**: Combined ECT+GRAB Priority Rule with Earliest-Start Allocation — 1; GSD (Greatest Successor Duration) + Earliest Start — 1; CPL × Resource-Intensity Priority with Conditional Delay — 1; LFT (Latest Finish Time) priority rule with earliest feasible start allocation — 1; Weighted Total Resource Requirement of Successors (WTRRS) with Greedy Earliest Allocation — 1; Combined GRAB-SPT-Successors priority rule with resource-aware allocation — 1
- **g**: Critical-Path Priority with Non-Critical Deferral (CPND) — 1; Minimum Late Finish (MLF) with resource-pressure tiebreaking + Earliest Feasible Start — 1; Longest-Path-to-End Priority with Critical Successor Weighting (LPE-CS) — 1; LFT with Critical Path Successor Boosting (CP-SB) + Earliest Feasible Start — 1; Longest Path to Sink (LPS) priority with slack-aware delayed allocation — 1; MLFT (Minimum Late Finish Time) + Earliest Feasible Start — 1
