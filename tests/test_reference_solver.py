"""
Эталон для синтетических проектов В2 (src/reference_solver.py): нижняя граница,
лучшее известное решение из правил и сэмплирования, сверка с PSPLIB J30.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from dsl_builder import build_dsl
from generators.background import background_network
from priority_rules import RULES_V2
from reference_solver import best_known, lower_bound, priority_keys
from schedule_checker import validate_schedule
from scheduler_skeleton import build_state

ROOT = Path(__file__).resolve().parents[1]
PSPLIB_J30 = ROOT / "data" / "psplib" / "instances" / "j30"


def _instance(jobs: list[tuple[int, int, int, list[int]]], capacity: int) -> dict:
    """
    jobs: (id, длительность, спрос на ресурс 1, преемники);
    исток и сток — 1 и последний id.
    """
    pred: dict[int, list[int]] = {j[0]: [] for j in jobs}
    for i, _, _, succ in jobs:
        for s in succ:
            pred[s].append(i)
    return {"project_goal": {"objective_function": "min_makespan"},
            "resources": [{"id": 1, "name": "R1", "capacity": capacity, "type": "renewable"}],
            "jobs": [{"id": i, "duration": d, "predecessors": sorted(pred[i]), "successors": succ,
                      "resource_requirements": [{"resource_id": 1, "amount": r}] if r else []}
                     for i, d, r, succ in jobs]}


@pytest.fixture
def trap_f1() -> dict:
    # Ловушка F1: цепочка 2 -> 3 -> 4 (по 4, спрос 6) и работа 5 (2, спрос 5) с хвостом 6 (5).
    # 5 не совместима ни с одной работой цепочки (6 + 5 > 10), а ее резерв без ресурсов — 5
    return _instance([(1, 0, 0, [2, 5]), (2, 4, 6, [3]), (3, 4, 6, [4]), (4, 4, 6, [7]),
                      (5, 2, 5, [6]), (6, 5, 0, [7]), (7, 0, 0, [])], capacity=10)


def test_lower_bound_takes_the_larger_of_cpm_and_resource_bound():
    # Три независимые работы по 4 со спросом 6 при емкости 10: CPM 4, по ресурсу ⌈72 / 10⌉ = 8
    inst = _instance([(1, 0, 0, [2, 3, 4]), (2, 4, 6, [5]), (3, 4, 6, [5]), (4, 4, 6, [5]),
                      (5, 0, 0, [])], capacity=10)
    assert lower_bound(inst) == {"cpm": 4, "resource": 8, "lb": 8}


def test_lower_bound_of_trap(trap_f1):
    # CPM — цепочка 12; по ресурсу ⌈(3 · 4 · 6 + 2 · 5) / 10⌉ = 9
    assert lower_bound(trap_f1) == {"cpm": 12, "resource": 9, "lb": 12}


def test_lst_falls_into_trap_and_reference_finds_optimum(trap_f1):
    ref = best_known(trap_f1, samples=50, seed=0)
    assert ref["rules"]["LST/ssgs"] == 15           # LST откладывает 5 до конца цепочки
    # Оптимум 14: 5 не пересекается с цепочкой длины 12, значит makespan ≥ 12 + 2
    assert ref["makespan"] == 14
    assert validate_schedule(trap_f1, ref["schedule"])["makespan"] == 14


@pytest.mark.parametrize("seed", range(3))
def test_best_known_is_valid_and_between_lb_and_every_rule(seed):
    inst = background_network(30, 4, seed=seed)
    ref = best_known(inst, samples=100, seed=seed)
    check = validate_schedule(inst, ref["schedule"])
    assert check["status"] == "valid" and check["makespan"] == ref["makespan"]
    assert ref["lb"] == lower_bound(inst)["lb"] <= ref["makespan"]
    assert set(ref["rules"]) == {f"{r}/{s}" for r in RULES_V2 for s in ("ssgs", "psgs")}
    assert ref["makespan"] <= min(ref["rules"].values())
    assert ref["optimal"] == (ref["makespan"] == ref["lb"])
    assert ref["source"] in set(ref["rules"]) | {"sampling"}


def test_best_known_is_deterministic_by_seed():
    inst = background_network(30, 2, seed=5, rs=0.2)
    assert best_known(inst, samples=60, seed=1) == best_known(inst, samples=60, seed=1)


def test_sampling_does_not_lose_to_rules_alone():
    inst = background_network(30, 4, seed=2, rs=0.2)
    rules_only = best_known(inst, samples=0, seed=0)
    assert rules_only["source"] != "sampling"
    assert best_known(inst, samples=200, seed=0)["makespan"] <= rules_only["makespan"]


def test_priority_keys_agree_with_rule_functions():
    # PSGS ставит работы по ключу, SSGS — по функции выбора; это одно и то же правило
    inst = background_network(30, 4, seed=3)
    _, state = build_state(build_dsl(inst, "none"), inst)
    keys = priority_keys(state.jobs)
    rng = random.Random(0)
    ids = sorted(state.jobs)
    for name, select in RULES_V2.items():
        for _ in range(30):
            eligible = rng.sample(ids, rng.randint(1, 6))
            assert select(eligible, state.jobs, None, None) == min(eligible, key=keys[name]), name


@pytest.mark.skipif(not PSPLIB_J30.exists(), reason="PSPLIB не скачан (data/psplib/SOURCES.md)")
def test_reference_on_psplib_j30_is_close_to_optimum():
    # На J30 оптимумы известны: эталон без точного решателя — верхняя граница не ниже оптимума
    # и в среднем близко к нему; так видно, насколько эталон занижает RPD на синтетике
    from psplib import iter_set
    from references import load_references
    refs = load_references("j30", use_rcplib=False)
    gaps = []
    for name, inst in list(iter_set(PSPLIB_J30))[::16]:
        ref = best_known(inst, samples=200, seed=0)
        opt = refs[name]
        assert ref["lb"] <= opt.bks <= ref["makespan"], name
        gaps.append(100 * (ref["makespan"] - opt.bks) / opt.bks)
    assert sum(gaps) / len(gaps) < 3.0
