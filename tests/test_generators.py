"""
Генератор фоновых сетей В2 (src/generators/background.py): структура проекта,
соответствие заданным RF и RS, совместимость с каркасом, чекером и индикаторами.
"""
from __future__ import annotations

import pytest

from dsl_builder import build_dsl
from generators.background import background_network
from indicators import (_peak_es_demand, compute_indicators, earliest_starts,
                        network_from_instance, topological_order)
from priority_rules import RULES_V2
from schedule_checker import validate_schedule
from scheduler_skeleton import build_state, default_allocate, run_schedule

SEEDS = range(5)


def _arcs(inst: dict) -> set[tuple[int, int]]:
    return {(j["id"], s) for j in inst["jobs"] for s in j["successors"]}


def test_same_seed_gives_same_project_other_seed_differs():
    assert background_network(30, 4, seed=1) == background_network(30, 4, seed=1)
    assert background_network(30, 4, seed=1)["jobs"] != background_network(30, 4, seed=2)["jobs"]


@pytest.mark.parametrize("seed", SEEDS)
def test_structure_is_a_psplib_like_project(seed):
    inst = background_network(30, 4, seed=seed)
    jobs = {j["id"]: j for j in inst["jobs"]}
    assert sorted(jobs) == list(range(1, 33))               # 30 работ + исток и сток
    source, sink = jobs[1], jobs[32]
    for dummy in (source, sink):
        assert dummy["duration"] == 0 and dummy["resource_requirements"] == []
    assert source["predecessors"] == [] and sink["successors"] == []
    for i, j in jobs.items():
        for s in j["successors"]:
            assert i in jobs[s]["predecessors"]             # Списки связей согласованы
        for p in j["predecessors"]:
            assert i in jobs[p]["successors"]
        if i not in (1, 32):
            assert j["duration"] >= 1 and j["predecessors"] and j["successors"]
    net = network_from_instance(inst)
    assert net.n == 30


@pytest.mark.parametrize("seed", SEEDS)
def test_no_redundant_arcs(seed):
    # Транзитивная дуга i -> j (есть и другой путь i ~> j) не меняет расписаний,
    # но искажает CNC и правила по числу преемников
    inst = background_network(40, 2, seed=seed, extra_preds=1.5)
    succ = {j["id"]: j["successors"] for j in inst["jobs"]}
    for i, j in _arcs(inst):
        for other in succ[i]:
            if other == j:
                continue
            stack, seen = [other], set()
            while stack:
                u = stack.pop()
                assert u != j, f"дуга {i}->{j} избыточна"
                if u not in seen:
                    seen.add(u)
                    stack.extend(succ[u])


def test_layers_set_the_depth_of_the_network():
    inst = background_network(30, 2, seed=3, layers=6)
    net = network_from_instance(inst)
    depth: dict[int, int] = {}
    for i in topological_order(net):
        depth[i] = 1 + max((depth[p] for p in net.pred[i]), default=0)
    assert max(depth.values()) == 6


@pytest.mark.parametrize("rf,n_res", [(0.25, 4), (0.5, 4), (1.0, 4), (0.5, 2)])
def test_resource_factor_matches_target(rf, n_res):
    for seed in SEEDS:
        res = compute_indicators(background_network(30, n_res, seed=seed, rf=rf))["resource"]
        assert res["rf"] == pytest.approx(rf)


@pytest.mark.parametrize("rs", [0.2, 0.5, 0.7])
def test_resource_strength_matches_target(rs):
    for seed in SEEDS:
        inst = background_network(60, 4, seed=seed, rs=rs)
        net = network_from_instance(inst)
        es = earliest_starts(net)
        res = compute_indicators(inst)["resource"]
        for k, v in res["per_resource"].items():
            span = _peak_es_demand(net, k, es) - max(net.demand[i].get(k, 0) for i in net.activities)
            assert abs(v["rs"] - rs) <= 0.5 / span + 1e-9, (seed, k)


def test_every_resource_is_used_and_fits_every_job():
    inst = background_network(30, 4, seed=0, rf=0.25)
    capacity = {r["id"]: r["capacity"] for r in inst["resources"]}
    used = {rr["resource_id"] for j in inst["jobs"] for rr in j["resource_requirements"]}
    assert used == set(capacity)
    for j in inst["jobs"]:
        for rr in j["resource_requirements"]:
            assert 1 <= rr["amount"] <= capacity[rr["resource_id"]]


def test_generator_parameters_are_recorded():
    inst = background_network(30, 4, seed=7, rs=0.4)
    g = inst["generator"]
    assert g["name"] == "background" and g["seed"] == 7
    assert g["params"]["n"] == 30 and g["params"]["rs"] == 0.4


@pytest.mark.parametrize("rule", list(RULES_V2))
def test_rules_give_valid_schedules_on_generated_project(rule):
    inst = background_network(30, 4, seed=11)
    _, state = build_state(build_dsl(inst, "all"), inst)
    res = run_schedule(state, RULES_V2[rule], default_allocate)
    assert res["status"] == "complete" and res["invalid_select_count"] == 0
    assert validate_schedule(inst, res["schedule"])["status"] == "valid"


@pytest.mark.parametrize("kwargs", [dict(n=0, n_res=2), dict(n=30, n_res=0),
                                    dict(n=30, n_res=2, rf=0.0), dict(n=30, n_res=2, extra_preds=-1), dict(n=30, n_res=2, rf=1.5),
                                    dict(n=30, n_res=2, rs=1.2), dict(n=5, n_res=2, layers=6),
                                    dict(n=30, n_res=2, durations=(0, 5))])
def test_bad_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        background_network(seed=0, **kwargs)
