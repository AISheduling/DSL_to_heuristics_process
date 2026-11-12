from __future__ import annotations

import json

import pytest

import router
from dsl_builder import build_dsl
from generators.traps import resource_blind_slack as f1


def project(env: str, s: float, seed: int = 0) -> dict:
    return f1.generate(30, 4, s=s, seed=seed, control="fits", shared=env == "shared")


@pytest.fixture(scope="module")
def trigger():
    return router.load_trigger()


def test_trigger_is_f1_threshold_from_f1_grid(trigger):
    assert trigger["feature"] == "f1_pressure_free"
    assert trigger["direction"] == ">"
    assert trigger["threshold"] == pytest.approx(0.0564, abs=1e-4)


def test_router_fires_on_isolated_trap_project(trigger):
    d = router.decide(project("isolated", 1.0), trigger)
    assert d["fired"] is True
    assert d["value"] > trigger["threshold"]


def test_router_silent_on_isolated_control_project(trigger):
    d = router.decide(project("isolated", 0.0), trigger)
    assert d["fired"] is False


def test_level_b_is_v1_dsl_without_metadata(trigger):
    inst = project("isolated", 1.0)
    d = router.decide(inst, trigger)
    assert router.route_dsl(inst, "b", d) == build_dsl(inst, "none")


def test_verdict_names_avoided_rules_only_when_fired(trigger):
    inst = project("isolated", 1.0)
    dsl = router.route_dsl(inst, "v", router.decide(inst, trigger))
    assert dsl["rule_guidance"]["avoid_rules"] == ["LST", "MTS"]
    assert "project_properties" not in dsl
    assert "LFT" not in json.dumps(dsl, ensure_ascii=False)


def test_property_gives_value_without_rule_names(trigger):
    inst = project("isolated", 1.0)
    d = router.decide(inst, trigger)
    dsl = router.route_dsl(inst, "g", d)
    prop = dsl["project_properties"]["f1_pressure_free"]
    assert prop["value"] == round(d["value"], 3)
    assert prop["threshold"] == round(trigger["threshold"], 3)
    text = json.dumps(dsl, ensure_ascii=False)
    for rule in ("LST", "MTS", "LFT"):
        assert rule not in text
    assert "rule_guidance" not in dsl


def test_property_says_unambiguously_which_job_is_urgent():
    # Пилот pilot-haiku: фраза «по позднему окончанию срочнее h» читалась как «c срочнее h»,
    # и модель выбирала LST. Направление задается неравенствами, а не порядком слов.
    meaning = router.PROPERTY_MEANING
    assert "LS_c < LS_h" in meaning and "LF_h < LF_c" in meaning
    assert "срочнее h" not in meaning


@pytest.mark.parametrize("level", ["v", "g"])
def test_not_fired_levels_equal_level_b(trigger, level):
    inst = project("isolated", 0.0)
    d = router.decide(inst, trigger)
    assert router.route_dsl(inst, level, d) == router.route_dsl(inst, "b", d)


@pytest.mark.parametrize("level", ["b", "v", "g"])
def test_dsl_has_no_generator_parameters(trigger, level):
    inst = project("shared", 0.5, seed=3)
    text = json.dumps(router.route_dsl(inst, level, router.decide(inst, trigger)), ensure_ascii=False)
    for leak in ("generator", "seed", "shared", "isolated", "trap", "best"):
        assert leak not in text


@pytest.mark.parametrize("level", ["v", "g"])
def test_kernel_accepts_routed_dsl(trigger, level):
    from scheduler_skeleton import build_state, default_allocate, default_select, run_schedule
    inst = project("isolated", 1.0)
    _, state = build_state(router.route_dsl(inst, level, router.decide(inst, trigger)), inst)
    assert run_schedule(state, default_select, default_allocate)["status"] == "complete"


def test_unknown_level_rejected(trigger):
    inst = project("isolated", 0.0)
    with pytest.raises(ValueError):
        router.route_dsl(inst, "a", router.decide(inst, trigger))
