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

## Релиз RCPLIB v2.4 (наборы инстансов)

Скачано 2026-11-18 из GitHub Releases:
https://github.com/MarioVanhoucke/RCPLIB-Resource-Constrained-Project-Library/releases/tag/v2.4
(релиз от 2026-01-28; при новом релизе старый удаляется — сохраняй архив).

| Локальный путь | Источник | SHA-256 |
|---|---|---|
| `archives/RCPLIBv2.4.zip` (86 148 142 байт) | `releases/download/v2.4/RCPLIBv2.4.zip` | `11f13615f474d2396d2bb59ef87d821f2288adbb1053e1021625274f444bc2ef` |
| `release/RCPLIB (Parameters and BKS).xlsx` (из архива) | — | `70a50c42e58237ddae686bd642b9330c8af0c6a148e22cc65b00dddc5d8a658f` |

Excel из релиза новее файла выше (другая сумма); сверка в `tests/test_indicators.py`
по-прежнему идет по старому файлу в корне `data/rcplib/`.

`release/` — архив без `__MACOSX`, `.DS_Store`. `instances/<набор>/` — распакованные
вложенные архивы (служебные `._*` удалены), формат Паттерсона (`RCPSP_DataFormat.pdf`):

| Набор | Файлов `.rcp` | Работ | Ресурсов |
|---|---|---|---|
| RG30 (Set 1–5) | 1800 | 30 | 4 |
| RG300 | 480 | 300 | 4 |
| sD | 390 | 50 | 4 |
| CV | 623 | 20–30 | 1–4 |
| VNR | 1750 | 30 | 0–10 |
| DC1 / DC2 | 1800 / 720 | 10–50 / 25–100 | 4 |
| MH | 461 | 26–120 | 2–4 |
| LPP / LPSP | 80 / 81 | 1800 | 4 |

MH распакован, но в эксперименты не входит: лист MH ссылается на инстансы CV
(`mhN` — копия `cvK`, ADR 0005).

Не распакованы: `ALL/ALL.tar` (273 МБ, версии LowRU/HighRD/KeepOPT), 1kNetRes, MT, ResSet.

`survey/` — обзор 2026-11-18: `rcplib_survey.py` (разбор `.rcp` + `src/indicators.py`),
`rcplib_indicators.csv`. Сверка с листами Excel v2.4: сетевые индикаторы (n, CNC, SP, OS)
совпадают на всех 8185 инстансах (|Δ| ≤ 0,001); ресурсные (RF, RS, RC) расходятся на
RG30 (193), VNR (324), DC (144), LPSP (4) — в части случаев Excel учитывает меньше
ресурсов (`#R` < K) или ограничивает RS единицей; причина остальных не выяснена.
