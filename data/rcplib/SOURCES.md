# RCPLIB: источник и контрольная сумма

Индикаторы проектов и эталоны (CPM, нижние и верхние границы из литературы) 
для наборов RCPSP — Excel-файл группы OR&S (Ghent University): 
Vanhoucke, M., & Coelho, J. (2018). A tool to test and validate
algorithms for the resource-constrained project scheduling problem. Computers and
Industrial Engineering, 118, 251–265.

Страница: https://www.projectmanagement.ugent.be/research/project_scheduling/rcpsp
(также https://github.com/mariovanhoucke/RCPLIB-Resource-Constrained-Project-Library).
Файл в git не хранится, см. `.gitignore`.

| Локальный путь | URL | SHA-256 |
|---|---|---|
| `RCPLIB (Parameters and BKS).xlsx` | `https://www.projectmanagement.ugent.be/sites/default/files/datasets/RCPSP/RCPLIB%20(Parameters%20and%20BKS).xlsx` | `258c1121f9bbad6e4b45a7ab0fa1211bcc87a6b262aa4658dde163e2cef60064` |

Скачано 2026-10-26. Версия файла — 6, последнее обновление — февраль 2025 (лист `Overview`).

Что используется:
- лист `PSPLIB` (2040 строк: J30, J60, J90, J120): ключ — `SubSet` + `FileName`
  (`J30`, `j301_1.sm`); колонки индикаторов `CNC`, `OS`, `SP`, `AD`, `LA`, `I5`, `TF`,
  `RF`, `RU`, `RS`, `RC`; эталоны `CPM`, `LB-lit`, `UB-lit`;
- построчная сверка — `tests/test_indicators.py` (пропускается, если файла нет);
  результаты и исключение `j3017_4` — `docs/adr/0002-project-indicators.md`.
