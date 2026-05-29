import json
import os
from pathlib import Path

import networkx as nx
import pandas as pd


def build_graph_from_json(filepath):
    """
    Функция для парсинга разных типов RCPSP
    и построения направленного графа NetworkX.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    G = nx.DiGraph()
    durations: dict[str, int] = {}

    case_info = data.get("case_info", {})
    case_type = case_info.get("type", os.path.basename(filepath))

    # Case 5
    if 'jobs' in data and len(data['jobs']) > 0 and 'activities' in data['jobs'][0]:
        for proj in data['jobs']:
            prefix = f"p{proj['project_id']}_"  # Чтобы узлы разных проектов не слипались
            for act in proj['activities']:
                u = prefix + str(act['id'])
                dur = act.get("duration", 0)
                durations[u] = dur
                G.add_node(u, duration=dur)
                for succ in act.get('successors', []):
                    v = prefix + str(succ)
                    G.add_edge(u, v)
        return case_type, G, durations

    # Cases 1-4
    jobs = data.get('jobs', [])
    for job in jobs:
        u = str(job['id'])

        # duration: прямое поле или первый режим (Case 1 иногда использует modes)
        dur = job.get("duration", 0)
        if not dur and "modes" in job:
            dur = job["modes"][0].get("duration", 0)
        durations[u] = dur

        G.add_node(u)

        # Ребра: три варианта структуры
        if "precedences" in job:
            # Cases 3, 4: time_successors — жесткие ребра по времени
            for succ in job["precedences"].get("time_successors", []):
                G.add_edge(u, str(succ))
            # selection_groups — альтернативные ветви,
            # НЕ добавляем как обязательные ребра

        elif "successors" in job:
            # Case 1
            for succ in job["successors"]:
                G.add_edge(u, str(succ))

        elif "predecessors" in job:
            # Case 2 (single machine): predecessors пустые -> ребер нет, граф корректен
            for pred in job["predecessors"]:
                G.add_edge(str(pred), u)

    return case_type, G, durations


def _cpl_in_time_units(G: nx.DiGraph, durations: dict[str, int]) -> tuple[int, list]:
    """
    Критический путь в единицах времени.

    Алгоритм:
      Назначаем каждому ребру (u->v) вес = duration[u].
      dag_longest_path_length суммирует веса ребер вдоль пути —
      это дает сумму длительностей всех узлов КРОМЕ последнего.
      Добавляем duration последнего узла отдельно.

    Для Case 2 (граф без ребер): нет пути длиннее одного узла ->
      возвращаем max(duration) как техническое значение, но
      это НЕ нижняя граница для E/T задачи (см. примечание в DSL).
    """
    if G.number_of_edges() == 0:
        # Граф без ребер (Case 2): нет precedence-структуры
        if durations:
            max_node = max(durations, key=lambda n: durations[n])
            return durations[max_node], [max_node]
        return 0, []

    Gw = G.copy()
    for u, v in Gw.edges():
        Gw[u][v]["weight"] = durations.get(u, 0)

    path = nx.dag_longest_path(Gw, weight="weight")
    length = nx.dag_longest_path_length(Gw, weight="weight")
    last_dur = durations.get(path[-1], 0) if path else 0
    return length + last_dur, path


# Параллелизм (временные окна)

def _temporal_parallelism(
        G: nx.DiGraph,
        durations: dict[str, int],
) -> tuple[float, int, int]:
    """
    Вычисляет параллелизм на основе временных окон [ES, EF) без учета ресурсов.

    Возвращает:
      avg_parallelism — среднее число одновременно активных работ
                         по временным слотам, где есть хоть одна активная работа.
      max_parallelism — максимальное число одновременно активных работ.
      num_topo_levels — число топологических уровней графа (глубина в ребрах).
    """
    # Топологические уровни (глубина в ребрх)
    topo_level: dict[str, int] = {}
    for u in nx.topological_sort(G):
        preds = list(G.predecessors(u))
        topo_level[u] = max((topo_level[p] + 1 for p in preds), default=0)
    num_topo_levels = max(topo_level.values(), default=0) + 1

    # Ранний старт и финиш без ресурсов
    ES: dict[str, int] = {n: 0 for n in G.nodes()}
    for u in nx.topological_sort(G):
        for v in G.successors(u):
            ES[v] = max(ES[v], ES[u] + durations.get(u, 0))
    EF = {n: ES[n] + durations.get(n, 0) for n in G.nodes()}

    # Только реальные работы (duration > 0) — фиктивные узлы исключаем
    real_nodes = [n for n in G.nodes() if durations.get(n, 0) > 0]
    if not real_nodes:
        return 0.0, 0, num_topo_levels

    max_time = max(EF[n] for n in real_nodes)

    active_counts = []
    for t in range(max_time + 1):
        cnt = sum(1 for n in real_nodes if ES[n] <= t < EF[n])
        if cnt > 0:
            active_counts.append(cnt)

    avg_par = round(sum(active_counts) / len(active_counts),
                    3) if active_counts else 0.0
    max_par = max(active_counts) if active_counts else 0
    return avg_par, max_par, num_topo_levels


def calculate_graph_metrics(G: nx.DiGraph, durations: dict[str, int],
                            per_project: bool = False,
                            project_subgraphs: list | None = None, ) -> dict:
    """
    per_project=True + project_subgraphs — для Case 5.
    """
    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()

    if num_edges == 0:
        # Single-machine без графа зависимостей: метрики, требующие ребер, не применимы.
        # CPL, relative_cpl, order_strength, num_levels_bfs, avg_parallelism,
        # max_parallelism, num_roots, num_leaves — выставляем в None (N/A в Excel).
        return {
            "nodes": num_nodes,
            "edges": 0,
            "connected_components": None,
            "avg_out_degree": 0.0,
            "density": 0.0,
            "cpl": None,
            "relative_cpl": None,
            "order_strength": None,
            "num_topo_levels": None,
            "avg_parallelism": None,
            "max_parallelism": None,
            "num_roots": None,
            "num_leaves": None,
            "note": (
                "No precedence edges (single-machine). "
                "CPL and graph-structure metrics are not applicable. "
                "Lower bound for E/T is the V-shape heuristic estimate."
            ),
        }

    # Базовые характеристики
    connected_components = nx.number_weakly_connected_components(G)
    avg_out_degree = round(num_edges / num_nodes, 3) if num_nodes else 0.0
    density = nx.density(G)

    # CPL в единицах времени (исправленный метод)
    cpl_time, _ = _cpl_in_time_units(G, durations)
    # relative_cpl: делим на число реальных работ (duration > 0),
    # исключая фиктивные Supersource/Supersink
    real_count = sum(1 for d in durations.values() if d > 0)
    relative_cpl = round(cpl_time / real_count, 4) if real_count else 0

    # Сила упорядоченности
    tc = nx.transitive_closure(G)
    os_edges = tc.number_of_edges()

    max_pairs = num_nodes * (num_nodes - 1)
    order_strength = round(os_edges / max_pairs, 4) if max_pairs > 0 else 0

    # Параллелизм
    if per_project and project_subgraphs:
        # Case 5: агрегируем по подграфам проектов
        all_avg, all_max, all_levels = [], [], []
        for sg in project_subgraphs:
            sg_dur = {n: durations.get(n, 0) for n in sg.nodes()}
            avg_p, max_p, levels = _temporal_parallelism(sg, sg_dur)
            all_avg.append(avg_p)
            all_max.append(max_p)
            all_levels.append(levels)
        avg_parallelism = round(sum(all_avg) / len(all_avg), 3) if all_avg else 0.0
        max_parallelism = max(all_max) if all_max else 0
        num_topo_levels = max(all_levels) if all_levels else 0
    else:
        avg_parallelism, max_parallelism, num_topo_levels = _temporal_parallelism(G,
                                                                                  durations)
    num_roots = sum(1 for n, d in G.in_degree() if d == 0)
    num_leaves = sum(1 for n, d in G.out_degree() if d == 0)

    return {
        "nodes": num_nodes,
        "edges": num_edges,
        "connected_components": connected_components,
        "avg_out_degree": avg_out_degree,
        "density": round(density, 4),
        "cpl": cpl_time,
        "relative_cpl": relative_cpl,
        "order_strength": order_strength,
        "num_topo_levels": num_topo_levels,
        "avg_parallelism": avg_parallelism,
        "max_parallelism": max_parallelism,
        "num_roots": num_roots,
        "num_leaves": num_leaves,
    }


if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent
    output_dir = BASE_DIR / "data" / "references" / "case_metrics.xlsx"
    data_dir = BASE_DIR / "data" / "processed"
    files = [
        (str(data_dir / "Case1_PSPLIB_j301_1.json"), False),
        (str(data_dir / "Case2_sch50.json"), False),
        (str(data_dir / "Case3_nonrenewable.json"), False),
        (str(data_dir / "Case4_renewable.json"), False),
        (str(data_dir / "Case5_mp_j90_a2_nr1.json"), True)
    ]

    all_results = []

    print(
        f"{'Кейс':<28} | {'Узлы':<5} | {'Ребра':<5} | {'CPL':<5} | "
        f"{'OS':<6} | {'AvgPar':<8} | {'MaxPar':<7} | {'Уровни':<7} | {'Корни':<6} | {'Листья':<6}"
    )
    print("-" * 80)

    for filepath, is_multiproject in files:
        if not os.path.exists(filepath):
            print(f"Файл не найден: {filepath}")
            continue

        case_type, graph, durations = build_graph_from_json(filepath)

        project_subgraphs = None
        if is_multiproject:
            components = list(nx.weakly_connected_components(graph))
            project_subgraphs = [
                graph.subgraph(c).copy() for c in components
            ]

        metrics = calculate_graph_metrics(
            graph,
            durations,
            per_project=is_multiproject,
            project_subgraphs=project_subgraphs,
        )

        row = {"Case ID": case_type, **metrics}
        all_results.append(row)


        def fmt(val, width):
            return f"{'N/A' if val is None else val:>{width}}"


        print(
            f"{case_type[:28]:<28} | "
            f"{fmt(metrics['nodes'], 5)} | "
            f"{fmt(metrics['edges'], 5)} | "
            f"{fmt(metrics['cpl'], 5)} | "
            f"{fmt(metrics['order_strength'], 6)} | "
            f"{fmt(metrics['avg_parallelism'], 8)} | "
            f"{fmt(metrics['max_parallelism'], 7)} | "
            f"{fmt(metrics['num_topo_levels'], 7)} | "
            f"{fmt(metrics['num_roots'], 6)} | "
            f"{fmt(metrics['num_leaves'], 6)}"
        )

    if all_results:
        df = pd.DataFrame(all_results)
        # Убираем служебное поле note из Excel если есть
        df = df.drop(columns=["note"], errors="ignore")
        df.to_excel(output_dir, index=False)
        print(f"\nСохранено: {output_dir}")
