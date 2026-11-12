"""
Ловушки В2 (src/generators/traps/): структура проекта, переключение инварианта
ручкой s при неизменной сети, проигрыш правила на ловушке и его отсутствие в контроле.
"""
from __future__ import annotations

import pytest

from dsl_builder import build_dsl
from generators.traps.resource_blind_slack import generate as f1
from indicators import network_from_instance
from priority_rules import RULES_V2, latest_times
from reference_solver import best_known, lower_bound
from schedule_checker import validate_schedule
from scheduler_skeleton import build_state, default_allocate, run_schedule


def _jobs(inst: dict) -> dict[int, dict]:
    return {j["id"]: j for j in inst["jobs"]}


def _demand(job: dict, k: int) -> int:
    return sum(r["amount"] for r in job["resource_requirements"] if r["resource_id"] == k)


# F1: resource_blind_slack

@pytest.mark.parametrize("n", [30, 60, 120])
def test_f1_project_has_n_real_jobs_and_consistent_links(n):
    inst = f1(n, 4, s=1.0, seed=0)
    jobs = _jobs(inst)
    assert sorted(jobs) == list(range(1, n + 3))
    assert jobs[1]["predecessors"] == [] and jobs[n + 2]["successors"] == []
    for i, j in jobs.items():
        for s in j["successors"]:
            assert i in jobs[s]["predecessors"]
        for p in j["predecessors"]:
            assert i in jobs[p]["successors"]
    assert network_from_instance(inst).n == n


def test_f1_same_seed_same_project():
    assert f1(30, 4, s=0.5, seed=3) == f1(30, 4, s=0.5, seed=3)


def _blocks(inst: dict) -> list[dict]:
    return inst["generator"]["trap"]["blocks"]


def test_f1_fits_control_changes_only_demands_of_h_jobs():
    # Контроль «помещается» в той же сети: s переключает только спрос h (условие 2)
    base, trap = f1(30, 4, s=0.0, seed=1), f1(30, 4, s=1.0, seed=1)
    strip = lambda b: {k: v for k, v in b.items() if k not in ("r_h", "kind")}
    assert [strip(b) for b in _blocks(base)] == [strip(b) for b in _blocks(trap)]
    hs = {b["h"] for b in _blocks(base)}
    jb, jt = _jobs(base), _jobs(trap)
    for i in jb:
        same = {k: v for k, v in jb[i].items() if k != "resource_requirements"}
        assert same == {k: v for k, v in jt[i].items() if k != "resource_requirements"}
        if i not in hs:
            assert jb[i]["resource_requirements"] == jt[i]["resource_requirements"]
    assert base["resources"] == trap["resources"]


@pytest.mark.parametrize("s,expected", [(0.0, 0), (0.25, 1), (0.5, 2), (0.75, 2), (1.0, 3)])
def test_f1_s_sets_the_number_of_trap_blocks(s, expected):
    blocks = _blocks(f1(30, 4, s=s, seed=2))
    assert len(blocks) == 3 and sum(b["kind"] == "trap" for b in blocks) == expected


def test_f1_trap_blocks_are_nested_in_s():
    # Блоки-ловушки при меньшем s — подмножество блоков при большем: доза только растет
    active = [{b["h"] for b in _blocks(f1(60, 4, s=s, seed=0)) if b["kind"] == "trap"}
              for s in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert all(a <= b for a, b in zip(active, active[1:]))


@pytest.mark.parametrize("control", ["fits", "short_delay"])
@pytest.mark.parametrize("s", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("seed", range(4))
def test_f1_blocks_satisfy_the_property_as_inequalities(control, s, seed):
    """
    Свойство для пары (h, c): c — работа критической цепочки, доступная вместе с h
    и идущая в момент позднего старта h:
      1) LST считает c срочнее: LS_c < LS_h < LF_c;
      2) h и c не помещаются вместе: r_h + r_c > R;
      3) по срокам окончания h срочнее: LF_h < LF_c.
    Ловушка — все три; контроль нарушает ровно одно (2 или 3). Проверяем по CPM самого
    проекта, а не по записанным генератором числам.
    """
    inst = f1(60, 4, s=s, seed=seed, control=control)
    trap = inst["generator"]["trap"]
    _, state = build_state(build_dsl(inst, "none"), inst)
    t = latest_times(state.jobs)
    jobs, k, cap = state.jobs, trap["resource"], trap["capacity"]
    chain = trap["chain"]
    assert all(t["ls"][c] == t["lf"][c] - jobs[c].duration for c in chain)
    assert lower_bound(inst)["cpm"] == sum(jobs[c].duration for c in chain)   # Цепочка критическая
    for b in _blocks(inst):
        h, c = jobs[b["h"]], jobs[b["c"]]
        assert sorted(h.predecessors) == sorted(c.predecessors)               # Доступны вместе
        assert b["tail"] in jobs[b["merge"]].predecessors                     # Хвост нужен цепочке
        cond1 = t["ls"][b["c"]] < t["ls"][b["h"]] < t["lf"][b["c"]]
        cond2 = h.resources_required.get(k, 0) + c.resources_required.get(k, 0) > cap
        cond3 = t["lf"][b["h"]] < t["lf"][b["c"]]
        expected = {"trap": (True, True, True), "fits": (True, False, True),
                    "short_delay": (True, True, False)}[b["kind"]]
        assert (cond1, cond2, cond3) == expected, b
        assert b["kind"] in ("trap", control)


def test_f1_trap_parameters_are_random_not_fixed():
    # Инвариант, а не один пример: ёмкость, спросы, длительности и сдвиги меняются
    blocks = [b for seed in range(6) for b in _blocks(f1(60, 4, s=1.0, seed=seed))]
    for key in ("capacity", "r_c", "r_h", "p", "d_c", "shift"):
        assert len({b[key] for b in blocks}) >= 3, key


def test_f1_trap_resource_is_used_only_by_trap():
    inst = f1(60, 4, s=1.0, seed=0)
    trap = inst["generator"]["trap"]
    users = {j["id"] for j in inst["jobs"] if _demand(j, trap["resource"])}
    assert users == set(trap["chain"]) | {b["h"] for b in trap["blocks"]}
    tails = {b["tail"] for b in trap["blocks"]}
    assert all(not j["resource_requirements"] for j in inst["jobs"] if j["id"] in tails)


@pytest.mark.parametrize("rule", list(RULES_V2))
def test_f1_rules_give_valid_schedules(rule):
    inst = f1(30, 4, s=1.0, seed=4)
    _, state = build_state(build_dsl(inst, "all"), inst)
    res = run_schedule(state, RULES_V2[rule], default_allocate)
    assert res["status"] == "complete"
    assert validate_schedule(inst, res["schedule"])["status"] == "valid"


@pytest.mark.parametrize("bad", [dict(s=-0.1), dict(s=1.1), dict(n=8), dict(control="urgent")])
def test_f1_bad_parameters_are_rejected(bad):
    kwargs = dict(n=30, n_res=4, s=0.5, seed=0) | bad
    with pytest.raises(ValueError):
        f1(**kwargs)


def _gap(inst: dict, rule: str) -> float:
    """
    Проигрыш правила лучшему из остальных правил (SSGS), %;
    эталон для этого не нужен.
    """
    rules = {r.split("/")[0]: ms for r, ms in best_known(inst, samples=0)["rules"].items()
             if r.endswith("/ssgs")}
    return 100 * (rules[rule] / min(ms for r, ms in rules.items() if r != rule) - 1)


def _gap_to_best(inst: dict, rule: str) -> float:
    """Проигрыш правила лучшему из всех правил (SSGS), %."""
    rules = {r.split("/")[0]: ms for r, ms in best_known(inst, samples=0)["rules"].items()
             if r.endswith("/ssgs")}
    return 100 * (rules[rule] / min(rules.values()) - 1)


@pytest.mark.parametrize("rule", ["LST", "MTS"])
@pytest.mark.parametrize("n", [30, 60])
def test_f1_rule_loses_when_all_conditions_hold(rule, n):
    for seed in range(5):
        inst = f1(n, 4, s=1.0, seed=seed)
        assert _gap_to_best(inst, rule) >= 5.0
        assert _gap(inst, "LFT") <= 0.0       # LFT ловушку обходит


def _chain_delay(inst: dict, rule: str) -> int:
    """
    На сколько цепочка ловушки заканчивается позже своей длины — прямой след ловушки.
    Makespan в контроле может определять фон: цепочка всего в chain_margin раз длиннее
    лучшего расписания фона, а MTS расписывает фон хуже.
    """
    trap = inst["generator"]["trap"]
    _, state = build_state(build_dsl(inst, "none"), inst)
    sched = run_schedule(state, RULES_V2[rule], default_allocate)["schedule"]
    last = trap["chain"][-1]
    return sched[last] + state.jobs[last].duration - sum(state.jobs[c].duration for c in trap["chain"])


@pytest.mark.parametrize("rule", ["LST", "MTS"])
@pytest.mark.parametrize("control", ["fits", "short_delay"])
@pytest.mark.parametrize("n", [30, 60])
def test_f1_breaking_one_condition_removes_the_loss(rule, control, n):
    # Нарушено ровно одно условие (2 или 3) во всех блоках — цепочка не опаздывает
    # больше, чем на неизбежное: h, не помещающиеся рядом, сдвигают ее на свои p_h
    def unavoidable(inst):
        return sum(b["p"] for b in inst["generator"]["trap"]["blocks"]
                   if b["r_h"] + b["r_c"] > b["capacity"])

    for seed in range(5):
        control_inst = f1(n, 4, s=0.0, seed=seed, control=control)
        assert _chain_delay(control_inst, rule) <= unavoidable(control_inst)
        trap_inst = f1(n, 4, s=1.0, seed=seed, control=control)
        assert _chain_delay(trap_inst, rule) > unavoidable(trap_inst)


@pytest.mark.parametrize("control", ["fits", "short_delay"])
def test_f1_lst_loss_grows_with_s(control):
    mean_gap = [sum(_gap(f1(60, 4, s=s, seed=seed, control=control), "LST") for seed in range(5)) / 5
                for s in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert mean_gap == sorted(mean_gap) and mean_gap[0] < 1.0 and mean_gap[-1] > mean_gap[1] + 5


# F1: запас цепочки, вариант с общим ресурсом, целевые правила

@pytest.mark.parametrize("seed", range(4))
def test_f1_background_never_sets_the_makespan_in_control(seed):
    # Цепочка длиннее худшего расписания фона, поэтому в контроле «помещается» (h рядом с c
    # помещается, ловушки нет) срок проекта — ровно длина цепочки при любом целевом правиле
    inst = f1(60, 4, s=0.0, seed=seed, control="fits")
    length = sum(j["duration"] for j in inst["jobs"] if j["id"] in inst["generator"]["trap"]["chain"])
    for rule in ("LST", "LFT", "MTS"):
        _, state = build_state(build_dsl(inst, "none"), inst)
        assert run_schedule(state, RULES_V2[rule], default_allocate)["objective"]["primary"] == length, rule


def test_f1_target_rules_are_recorded():
    g = f1(30, 4, s=1.0, seed=0)["generator"]
    assert g["target_rules"] == ["LST", "MTS"] and g["non_target_rules"] == ["GRPW", "GP1"]


def test_f1_shared_uses_a_background_resource_and_wraps_the_background():
    inst = f1(60, 4, s=1.0, seed=0, shared=True)
    trap = inst["generator"]["trap"]
    assert len(inst["resources"]) == 4 and trap["resource"] == 1    # Без отдельного ресурса
    cap = next(r["capacity"] for r in inst["resources"] if r["id"] == 1)
    assert trap["capacity"] == cap
    jobs = _jobs(inst)
    users = {i for i, j in jobs.items() if _demand(j, 1)}
    trap_jobs = set(trap["chain"]) | {b["h"] for b in trap["blocks"]}
    assert trap_jobs <= users and users - trap_jobs                  # Ресурс общий с фоном
    # Фон идет между первой и последней работой цепочки
    first, last = trap["chain"][0], trap["chain"][-1]
    bg = [i for i in jobs if i not in trap_jobs | {b["tail"] for b in trap["blocks"]}
          | {1, max(jobs)}]
    assert all(first in jobs[i]["predecessors"] for i in bg
               if not set(jobs[i]["predecessors"]) & set(bg))
    assert all(last in jobs[i]["successors"] for i in bg
               if not set(jobs[i]["successors"]) & set(bg))


@pytest.mark.parametrize("control", ["fits", "short_delay"])
@pytest.mark.parametrize("seed", range(3))
def test_f1_shared_blocks_satisfy_the_property(control, seed):
    inst = f1(60, 4, s=0.5, seed=seed, control=control, shared=True)
    trap = inst["generator"]["trap"]
    _, state = build_state(build_dsl(inst, "none"), inst)
    t = latest_times(state.jobs)
    jobs, k, cap = state.jobs, trap["resource"], trap["capacity"]
    assert lower_bound(inst)["cpm"] == sum(jobs[c].duration for c in trap["chain"])
    for b in _blocks(inst):
        h, c = jobs[b["h"]], jobs[b["c"]]
        cond = (t["ls"][b["c"]] < t["ls"][b["h"]] < t["lf"][b["c"]],
                h.resources_required.get(k, 0) + c.resources_required.get(k, 0) > cap,
                t["lf"][b["h"]] < t["lf"][b["c"]])
        assert cond == {"trap": (True, True, True), "fits": (True, False, True),
                        "short_delay": (True, True, False)}[b["kind"]]


def test_f1_shared_mechanism_survives_but_effect_is_weaker():
    # С общим ресурсом ловушка в основном срабатывает (LST ставит h после c), но фон сам
    # тормозит цепочку, и проигрыш по makespan меньше и шумнее, чем на отдельном ресурсе
    after, total, gap0, gap1 = 0, 0, [], []
    for seed in range(10):
        inst = f1(60, 4, s=1.0, seed=seed, shared=True)
        _, state = build_state(build_dsl(inst, "none"), inst)
        sched = run_schedule(state, RULES_V2["LST"], default_allocate)["schedule"]
        for b in _blocks(inst):
            total += 1
            after += sched[b["h"]] >= sched[b["c"]] + state.jobs[b["c"]].duration
        gap1.append(_gap(inst, "LST"))
        gap0.append(_gap(f1(60, 4, s=0.0, seed=seed, shared=True), "LST"))
    assert after / total >= 0.8
    assert sum(gap1) > sum(gap0)
