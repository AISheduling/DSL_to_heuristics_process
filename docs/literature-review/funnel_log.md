# Лог воронки отбора

Состояние на 2026-10-08. Критерии — в `search_protocol.md`. Систематические запросы Q1–Q6 выполнены (отбор по заголовку). Работы, не отобранные по заголовку, в лог не вносятся — их число видно в протоколе (столбцы «Найдено» и «Отобрано по заголовку»).

## Сводка

| Этап | Число работ | Комментарий |
| --- | --- | --- |
| Найдено всего | 131 | уникальные работы; по источникам: ТЗ — 23, снежный ком — 7, попутно при уточняющих поисках — 9, систематические запросы Q1–Q6 — 92 |
| Просмотрено по аннотации | 14 | остальные 117 ждут просмотра |
| Прочитано полностью | 10 | |
| Включено в ядро | 10 | A — 4, B — 3, C — 3, D — 0 |
| Исключено | 0 | пока ни одна работа не исключена |

## Включено в ядро

| Ключ | Пласт | Откуда | Карточка |
| --- | --- | --- | --- |
| luo2026llmrcpsp | B | ТЗ | cards/luo2026llmrcpsp.md |
| tian2026gpguidedllm | B | ТЗ | cards/tian2026gpguidedllm.md |
| kim2026vlcea | B | ТЗ («LLM-приоритеты в эволюционном поиске расписаний 2026»); опознана по списку литературы Luo 2026 | cards/kim2026vlcea.md |
| romeraparedes2024funsearch | A | ТЗ | cards/romeraparedes2024funsearch.md |
| liu2024eoh | A | ТЗ | cards/liu2024eoh.md |
| ye2024reevo | A | ТЗ | cards/ye2024reevo.md |
| zheng2025mctsahd | A | ТЗ | cards/zheng2025mctsahd.md |
| guo2021prselection | C | ТЗ | cards/guo2021prselection.md |
| luo2022gprcpsp | C | ТЗ | cards/luo2022gprcpsp.md |
| lopezibanez2016irace | C | ТЗ | cards/lopezibanez2016irace.md |

## Прошло аннотацию, к полному чтению

| Ключ | Пласт | Откуда | Что проверить |
| --- | --- | --- | --- |
| liu2025eohs | A | ТЗ; также Q3b | задачи (есть ли планирование); механизм выбора эвристики из набора под инстанс; бюджет baseline; выходные данные (arXiv 2025 vs AAAI 2026) |
| shi2026moh | A | ТЗ | задачи (есть ли планирование); обучение на нескольких задачах и обобщение по размерам — ось 10; бюджет двух уровней |
| gungordu2026pathwise | A | ТЗ | задачи; единица бюджета при заявке «быстрее сходится» — ось 12; проверка на разных LLM |
| wu2026refineevo | A | ТЗ; также Q3a | задачи; как измерена эффективность по токенам — ось 12; рецензирование; сравнить с PathWise |

## Найдено, ещё не просмотрено

### Из ТЗ, снежного кома и уточняющих поисков

| Работа | Предв. пласт | Откуда | Почему может быть важна |
| --- | --- | --- | --- |
| TIDE | A | ТЗ | уточнить при просмотре |
| G-LNS (arXiv 2602.08253) | A | ТЗ; также Q2a, Q4b | генеративный LNS для LLM-AHD |
| A2DEPT (arXiv 2604.24043) | A | ТЗ; также Q1b | в экспериментах есть MRCPSP |
| SimpleEvol (arXiv 2609.37172) | A | ТЗ; также Q4b | агентный цикл с минимальными априорными знаниями |
| TRACE (arXiv 2610.01887) | A | ТЗ; также Q3a | агентный дизайн эвристик для задач назначения ресурсов |
| HeuriGym | A | ТЗ | бенчмарк LLM-эвристик |
| MAP-Elites-гиперэвристики | C | ТЗ | разнообразие правил без LLM |
| SMAC (Lindauer et al. 2022) | C | ТЗ | альтернатива irace |
| InstSpecHH (arXiv 2506.00490) | D | ТЗ; также Q5a, Q5b | эвристики под подклассы инстансов + выбор LLM |
| Luo, Coelho, Song 2026 — регрессионные эвристики для RCPSP (Annals of OR) | C | снежный ком (Luo 2026) | baseline в Luo 2026; укрепит пласт C |
| Chand et al. 2018 — GP-правила для RCPSP | C | снежный ком (Luo 2022) | классический GP-baseline |
| GHPP (Duflo et al. 2019) | C | снежный ком (ReEvo, MCTS-AHD) | GP-гиперэвристика, baseline в LLM-работах |
| Yu, Gao, Li et al. 2026 — Automated scheduling heuristic generation and evaluation via LLM, LSH (IEEE) | B | снежный ком (Luo 2026); также Q3b, Q6b | LLM-эвристики для flow / job / open shop; совпадение с работой из списка Luo 2026 — сверить |
| DGEvo | B / A | снежный ком (Luo 2026) | уточнить при просмотре |
| DGA2D (Zhao et al. 2026) | A | снежный ком (Luo 2026) | в экспериментах есть RCPSP |
| HSEvo | A | снежный ком (MCTS-AHD) | baseline в MCTS-AHD |
| DSevolve (Zhou et al. 2026, arXiv 2603.27628) | B | уточняющий поиск; также Q2a, Q3a, Q6a, Q6b | гибрид: портфель правил offline + выбор online; в Scholar есть вторая версия (первый автор Huang) — свести по E6 |
| EvoDR (Qiu et al. 2026, arXiv 2601.15738) | B | уточняющий поиск; также Q2a, Q6b | LLM-эволюция правил диспетчеризации, dynamic flexible assembly flow shop; соавторы EoH (F. Liu, Q. Zhang) |
| NS4S (IJCAI 2025) | B | уточняющий поиск | job shop; проверка сгенерированного кода (VeEvo) |
| Филатова А. А. (ИТМО) — генерация эвристик для RCPSP с LLM-эволюцией | B | уточняющий поиск | та же тема, тот же университет |
| Luo, Vanhoucke, Coelho — surrogate-assisted GP для RCPSP | C | уточняющий поиск | развитие Luo 2022 |
| CEoH (arXiv 2503.03350) / LitCEoH | D | уточняющий поиск; также Q5a | абляция состава контекста: описание задачи в промпте |
| A-CEoH (arXiv 2601.19622) | D | уточняющий поиск | абляция состава контекста: код алгоритма в промпте |
| LLM-эвристики для AI planning (arXiv 2501.18784) | D | уточняющий поиск | генерация под конкретную задачу |
| R-ConstraintBench (arXiv 2508.15204) | — | уточняющий поиск; также Q1a, Q1b | вероятно, исключить по E2 (LLM решает инстанс целиком); проверить по аннотации |

### Из систематических запросов Q1–Q6

| Работа | Предв. пласт | Откуда | Почему может быть важна |
| --- | --- | --- | --- |
| Wang, Wang, Chu 2025 — Multi-agent LLMs as evolutionary optimizers for scheduling (C&IE) | B | Q1b | RCPSP j52/j102; уточнить: LLM генерирует эвристику или сама выполняет операторы над решениями |
| Zhang et al. 2025 — LLMs as Hybrid-Algorithm Experts for JSSP (IEEE) | B | Q1b; также Q6b | LLM как программист алгоритма для job shop |
| Lei, Pan 2026 — Two-Layer Automatic Algorithm Evolution Framework for JSSP (IEEE) | B | Q1b | LLM-эволюция алгоритма для job shop |
| REMoH (Forniés-Tabuenca et al. 2025, arXiv 2506.07759) | A | Q1b; также Q5a | рефлексивная эволюция многокритериальных эвристик; уточнить класс задачи |
| Huang Y. et al. 2025 — Autonomous multiobjective optimization using LLM (IEEE TEC) | A | Q1b | уточнить по аннотации, что генерирует LLM (не путать с Huang J. et al.) |
| Zhang 2026 — Work package-based project planning…, диссертация PolyU | B | Q1b | заявлен «LLM-driven heuristic optimization framework»; диссертация — проверить объём и доступность (E4/E5) |
| Li, Li 2026 — LLM-Guided Heuristic Design from Simulation Traces (arXiv 2608.09343) | B | Q2a | динамическое производство + AGV; обратная связь в виде трасс событий (карта 2) |
| Cao, Yuan, Liu 2026 — Asynchronous Agentic Framework for Dynamic Scheduling (arXiv 2605.29262) | B | Q2a; также Q6a | динамический гибкий job shop; агентный LLM; уточнить: генерирует правила или принимает решения напрямую |
| ALLSTaR (Elkael et al. 2026, IEEE) — LLM-driven scheduler generation for RAN | A | Q2b | LLM генерирует код планировщика радиосети; проверить, проходит ли I1 |
| Tian, Mei, Zhang 2026 — Surrogate-Assisted GP with Phenotypic Characterisation, DMRCPSP (arXiv 2609.14418) | C | Q3a | GP для RCPSP-варианта; те же авторы, что Tian 2026 — вероятно, их GP-baseline |
| Huang J. et al. 2026 — Automatic programming via LLMs with population self-evolution, dynamic fuzzy JSSP (arXiv 2410.22657, IEEE TFS) | B | Q3a; также Q3b, Q6a, Q6b | LLM-эволюция правил диспетчеризации |
| Semmelrock et al. 2026 — Learning to Solve and Optimize by Evolving Code (arXiv 2605.31049, IJCAI) | A | Q3a; также Q5a | эволюция кода решателя |
| Chen M. et al. 2026 — Teacher-Aware Evolution of Heuristic Programs from Learned Optimization Policies (arXiv 2605.10634) | A | Q3a | LLM-AHD с «учителем» из обученной политики |
| Planning of Heuristics (Wang et al. 2025, arXiv 2502.11422) | A | Q3a | MCTS-планирование для LLM-AHD |
| CALM (Huang et al. 2026, ICLR) | A | Q3b; также Q5b | коэволюция алгоритмов и самой LLM |
| HiFo-Prompt (Zhong et al. 2026, ICLR) | A / D | Q3b | состав промпта (hindsight / foresight) — ось 5 |
| Li, Wang et al. 2025 — LLM-assisted automatic memetic algorithm, lot-streaming hybrid job shop (IEEE) | B | Q3b | LLM-эвристика внутри меметического алгоритма |
| Chen J. et al. 2025 — LLM multi-agent framework to design algorithms for EOSSP (Engineering) | B | Q3b | мультиагентный синтез алгоритма планирования спутников |
| Chen, Li, Gao 2023 — Guided GP with attribute node activation encoding for RCPSP (SWEVO) | C | Q3b | GP для RCPSP — приоритет |
| Chen, Li, Gao 2024 — Surrogate-assisted dual-tree GP for dynamic RCMPSP (IJPR) | C | Q3b | GP для мультипроектного RCPSP — приоритет |
| Guo et al. 2024 — Improved GPHH for DFJSP with reconfigurable cells (JMS) | C | Q3b | GP-гиперэвристика |
| Zhang et al. 2024 — Automatic design of constructive heuristics, RDFGSP (C&OR) | C | Q3b | автоматический дизайн без LLM |
| Zhang et al. 2025 — SMT workshop, two-layer decomposition, I/F-Race (IJPR) | C | Q3b | дизайн эвристик через irace |
| Zeiträg, Figueira 2023 — Preference-based dispatching rules, MO job shop (J. Scheduling) | C | Q3b | GP-правила |
| Zeiträg et al. 2024 — Cooperative coevolutionary GP-HH, lot-sizing + JSS (IJPR) | C | Q3b | GP-гиперэвристика |
| Gil-Gala et al. 2023 — Ensembles of priority rules, one machine (Inf. Sciences) | C | Q3b | ансамбли правил приоритета |
| Yin et al. 2024 — GP dispatching rules for tower crane scheduling (Autom. Constr.) | C | Q3b | GP-правила |
| Xu et al. 2024 — GP vs RL for dynamic scheduling, preliminary comparison (IEEE) | C | Q3b | GP-правила |
| Xu et al. 2024 — Niching GP to learn actions for DRL, dynamic flexible scheduling (IEEE) | C | Q3b | GP + DRL |
| Xu et al. 2023 — GP for dynamic workflow scheduling in fog (IEEE) | C | Q3b | GP-правила, вычислительное планирование |
| Sun et al. 2024 — MTGP-HH for workflow scheduling in multi-clouds (IEEE) | C | Q3b | GP-правила, вычислительное планирование |
| Zhang, Yang 2025 — MTGP for satellite edge computing scheduling (FGCS) | C | Q3b | GP-правила, вычислительное планирование |
| MuEvo (Lv et al. 2026, arXiv 2608.03636) | A | Q4a; также Q4b | LLM-эволюция ансамбля эвристик в рамках селективной гиперэвристики |
| HeurAgenix (Yang et al. 2025, arXiv 2506.15196) | A | Q4a; также Q4b | двухэтапная гиперэвристика; на OpenReview есть вторая версия — свести по E6 |
| van Stein et al. 2024 — In-the-loop HPO for LLM-based AHD (arXiv 2410.16309, ACM TELO) | A | Q4a | настройка параметров внутри LLM-AHD |
| Zhao et al. 2026 — Meta-cognitive LLM-guided EA, heterogeneous hybrid flow shop with energy (IEEE conf.) | B | Q4b | LLM внутри эволюционного поиска расписаний |
| Zhao et al. 2026 — Closed-loop LLM hyperparameter control for EA, hybrid flow shop, electrolytic aluminum (Tsinghua S&T) | B | Q4b | LLM управляет параметрами (ось 3: «параметры») |
| Fang et al. 2024 — LLM in GP hyper-heuristics for dynamic microservice deployment | A / B | Q4b | гибрид LLM + GPHH, как у Tian 2026 |
| MEoH (Yao et al. 2025, AAAI) | A | Q4b | многокритериальная эволюция эвристик |
| RoCo (Xu et al. 2026, IEEE TAI) | A | Q4b | ролевая коллаборация LLM; считает вызовы и токены — ось 12 |
| Wu et al. 2025 — Efficient heuristics generation, few-shot performance predictor (ACM) | A | Q4b | снижение стоимости оценки — ось 12 |
| Zhang et al. 2024 — Importance of evolutionary search in LLM-AHD (PPSN) | A | Q4b | аналитическая работа: нужен ли поиск вообще |
| Liu et al. 2026 — Hierarchical Representations for Cross-task AHD (ICML) | A | Q4b | перенос между задачами — ось 10 |
| DGS (Wang et al. 2026, arXiv 2607.13911) — Dual-Surrogate Guided Search for AHD | A | Q4b; также Q5a | суррогаты для управления генерацией |
| ES-AHD (Lai et al. 2026, arXiv 2609.00023) | A | Q4b | эволюционная стратегия для AHD |
| RedAHD (Thach et al., OpenReview) | A | Q4b | end-to-end AHD через редукции |
| Ke et al. 2026 — Game-Theoretic Co-Evolution for LLM-Based Heuristic Discovery (arXiv 2601.22896) | A | Q4b | коэволюция |
| Qi et al. 2025 — Memetic and reflective evolution for AHD (Applied Sciences) | A | Q4b | меметика + рефлексия |
| Qian et al. — LLM-based Hyper-Heuristics for Multi-objective Optimization (OpenReview) | A | Q4b | многокритериальная гиперэвристика |
| CHH-LLM (Wu et al., SSRN) — contract-guided hybrid hyper-heuristic, TSP | A | Q4b | препринт SSRN; проверить наличие эксперимента |
| PyVRP-MEP (Malik et al. 2026, arXiv 2604.07872) | A | Q4b | метакогнитивная эволюция эвристик для HGS, VRP |
| Li et al. 2026 — LLM-driven neural–heuristic optimization for large-scale routing (IEEE) | A | Q4b | LLM-эвристики разрушения и выбора рёбер |
| Liu et al. 2023 — LLMs as Evolutionary Optimizers, LMEA (arXiv 2310.19046, CEC) | A | Q5a | LLM как оператор EA над решениями; пограничный E2 — проверить |
| Sartori et al. 2025 — LLM-Based Instance-Driven Heuristic Bias, BRKGA (arXiv 2509.09707) | D | Q5a; также Q5b (две версии — свести по E6) | LLM генерирует смещение под инстанс по его метрикам — ось 2 «online» |
| Rosin 2025 — Reasoning models generate search heuristics for open instances (arXiv 2505.23881) | D | Q5a | эвристика под конкретный открытый инстанс |
| DaSAThco (Chen, Li 2025, arXiv 2509.12602) | D | Q5a | LLM подбирает комбинации эвристик SAT под данные |
| LM-GRASP (Mezmaz, Danoy 2026, arXiv 2607.28135) | D | Q5a; также Q5b | языковая модель, обучаемая под инстанс; уточнить, LLM ли это в смысле I1 |
| Massoudi et al. 2026 — RL synthesizes reusable solvers (arXiv 2605.18374) | A | Q5a | перенос стоимости из инференса в веса — оси 2 и 12 |
| LLM4Branch (Hou et al. 2026, arXiv 2605.10401, ICML) | A | Q5a | LLM открывает политики ветвления MILP |
| RouteRepair (Ji et al. 2026, arXiv 2609.11452) | A | Q5a; также Q5b | диагностика провалов на уровне инстанса — обратная связь «контрпримеры» |
| BLADE (van Stein et al. 2025, arXiv 2504.20183) | A | Q5a | бенчмарк LLM-AAD |
| Sim, Renau, Hart 2025 — Beyond the Hype: Benchmarking LLM-Evolved Heuristics for Bin Packing (arXiv 2501.11411) | A | Q5a | критическая проверка — для теста «честный неустраивающий результат» |
| Herrmann, Pallez 2025 — In-depth Study of LLM Contributions to Bin Packing (arXiv 2510.27353, ACM TELO) | A | Q5a | переоценка заявлений FunSearch — критическая |
| DynaSchedBench (Cao, Yuan, Liu 2026, arXiv 2605.27566) | B | Q5a | бенчмарк LLM-агентов для DFJSP; проверить E2 |
| Xue et al. 2026 — Hybrid evaluation-based GP for uncertain AEOS scheduling (arXiv 2603.08447) | C | Q5a | GPHH, снижение стоимости оценки |
| Liu, Tierney 2026 — Configuring LLM-Generated Heuristics via Instance-Specific DRL | D | Q5b | настройка LLM-эвристик под инстанс; сравнение с irace — мост между пластами C и D |
| GRIMIP (Luo et al. 2026, arXiv) — instance-specific configuration of MIP solvers with LLMs | D | Q5b | LLM выбирает параметры под инстанс |
| Zhang, Liu et al. 2026 — Parallel Algorithm Portfolios via Potential-Aware Instance Generation with LLMs (arXiv 2608.06808) | A / D | Q5b | портфели + генерация инстансов |
| Sun et al. 2026 — LLM multi-agent evolution for solver code generation in JSS (Mathematics) | B | Q5b; также Q6b | мультиагентная генерация решателя для job shop |
| Cai et al. 2025 — Automatically discovering heuristics in a SAT solver with LLMs (Research Square) | A | Q5b | препринт; LLM-эвристики внутри сложного решателя |
| CSF (Zhang et al. 2026, Pattern Recognition) — curriculum-based scaffolding for heuristic evolution | A | Q5b | «скаффолдинг» — возможно, близко к нашему каркасу; проверить в первую очередь |
| Garza-Santisteban et al. 2025 — Selection HH and JSS: influence of instance size | C | Q5b | выбор эвристик по признакам инстанса для job shop |
| Wang, Liu et al. 2025 — Generalizable parallel algorithm portfolios via instance generation (IEEE) | C | Q5b | портфели без LLM; не планирование — пограничный |
| Da Ros et al. 2025 — Dynamic temperature control of SA using hyper-heuristics (ACM) | C | Q5b | управление параметрами; не планирование — пограничный |
| May et al. 2026 — LLM actor-critic dispatching rule generation for dynamic JSS (CIRP Annals) | B | Q6b | генерация правил актором + критик; кандидат на позицию ТЗ «LLM-правила для job shop 2026» |
| Huang J. et al. 2026 — Automated design of scheduling heuristics for DFJSP with evolutionary textual gradients (IJPR) | B | Q6b | «текстовые градиенты» как обратная связь — ось 5 |
| Lei et al. 2026 — Dispatching rules for dynamic hybrid flow shop via personalized multi-island reflective evolution (Tsinghua S&T) | B | Q6b | LLM-эволюция правил |
| Liao et al. 2025 — Online operator design in EO for FJSP via LLMs (arXiv 2511.16485) | B | Q6b | online-генерация операторов — ось 2 |
| Nguyen 2026 — LLM policy induction for heuristic search control, trace-driven ALNS (GECCO) | B | Q6b | правила управления поиском из трасс; JSP / FJSP |
| Ye et al. — Human-in-the-loop multi-objective manufacturing scheduling with LLM agents (SSRN) | B | Q6b | человек в цикле — ось 6; источник для снежного кома (LLM4EO, SeEvo, LSH) |
| Li et al. 2026 — LLM-assisted scheduling policy design and refinement: queueing, JSS, ride-hailing (SSRN) | B | Q6b | дизайн политик на нескольких классах задач |
| Li, Chen, Shi 2026 — Memetic algorithm with LLM for MO FJSP with variable speed (ASOC) | B | Q6b | LLM генерирует локальный поиск |
| Yu, Li, Gao, Lu 2026 — LLM-enabled optimization for assembly JSS with bin-packing (IEEE TII) | B | Q6b | уточнить роль LLM |
| ReflecSched (Cao, Yuan 2025, arXiv 2508.01724) | B | Q6b | иерархическая рефлексия для DFJSP; проверить E2 |
| CoRe (Peng et al. 2026, IEEE) — collaborative reflective LM for FJSP | B | Q6b | проверить E2: генерирует ли LLM код или расписание |
| Yan, Ji 2026 — Industrial mechanism-aware multi-agent LLMs for JSS (C&IE) | B | Q6b | мультиагентный LLM; проверить E2 |
| Johnson et al. 2026 — Multi-agent continuous decision-making for continuous DFJSP (IEEE TASE) | B | Q6b | LLM-правила в переговорах агентов; пограничная |
| Jun et al. 2026 — PLAID: fine-tuned LLM for parallel machine scheduling (Eng. Optimization) | B | Q6b | дообученная LLM выбирает работу на каждом шаге; пограничный E2 |
| Liu et al. 2026 — Learning distributed scheduling via LLM-augmented RL (AAAI) | B | Q6b | гибрид LLM + RL; на OpenReview есть вторая версия — свести по E6 |
| Zhao, Wu et al. 2026 — LLM-assisted RL with EA for hybrid flow shop (IEEE) | B | Q6b | гибрид LLM + RL + EA; пограничная |
| Yang et al. 2026 — LLM-upgraded graph RL for carbon-aware JSS (ACM) | B | Q6b | гибрид LLM + RL; пограничная |
| Zeng et al. 2025 — LLM-assisted DRL from human feedback for JSS (Machines) | B | Q6b | LLM в обучении DRL; пограничная |

## Исключено

| Работа | Этап | Причина (код критерия) |
| --- | --- | --- |
| — | — | пока нет |

## Заметки

- 2026-10-06: позиция ТЗ «LLM-приоритеты в эволюционном поиске расписаний 2026» опознана как VLCEA (Kim, Song, Kim 2026) по списку литературы Luo 2026; работа включена.
- 2026-10-06: позиция ТЗ «LLM-правила для job shop 2026» однозначно не опознана; кандидаты — DSevolve, EvoDR и May et al. 2026 (CIRP Annals; найдена в Q6b, по названию ближе всего к формулировке ТЗ). Уточнить у руководителя.
- 2026-10-06: в выдаче Q3, Q6 много работ одной группы (Gao, Li, Liu, Huang J. — HUST): Huang J. (TFS, IJPR), DSevolve, Lei et al., Yu et al. (LSH, TII). При аннотации проверить, где разные методы, а где вариации одного.
- 2026-10-06: обзоры, не отобранные по E3, но полезные для снежного кома по пласту C: Ghasemi et al. 2026 (RCPSP), Zhang, Mei et al. 2023 (GP/ML для job shop), Xu et al. 2025 (GP vs RL для job shop).
- 2026-10-08: PathWise и RefineEvo по аннотациям решают одну задачу (планирование эволюционных операторов вместо фиксированных); при чтении сравнить напрямую.