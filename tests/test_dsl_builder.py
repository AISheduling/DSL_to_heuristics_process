"""
DSL из инстанса (src/dsl_builder.py), чтение индикаторов каркасом (DSLMeta.indicators)
и промпт эксперимента В1 (src/llm_clients/prompt_v1.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dsl_builder import COMPOSITIONS, build_dsl
from indicators import flat_indicators
from psplib import parse_sm_text
from schedule_checker import validate_schedule
from scheduler_skeleton import DSLParser, build_state, default_allocate, default_select, run_schedule

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "llm_clients"))
sys.path.insert(0, str(ROOT / "experiments" / "runners"))

import prompt_v1  # noqa: E402
import runner_common as rc  # noqa: E402

TWELVE = {"n", "cnc", "os", "sp", "ad", "la", "i5", "tf", "rf", "ru", "rs", "rc"}


@pytest.fixture(scope="module")
def j301_1() -> dict:
    return parse_sm_text((ROOT / "data" / "raw" / "1_j301_1.txt").read_text(encoding="utf-8"),
                         "j301_1", "PSPLIB J30 Set")


def test_compositions():
    assert set(COMPOSITIONS["all"]) == TWELVE
    assert COMPOSITIONS["none"] == ()
    assert set(COMPOSITIONS["network"]) == {"n", "cnc", "os", "sp", "ad", "la", "i5", "tf"}
    assert set(COMPOSITIONS["resource"]) == {"n", "rf", "ru", "rs", "rc"}


def test_all_composition_values_match_indicators(j301_1):
    dsl = build_dsl(j301_1, "all")
    values = dsl["project_indicators"]["values"]
    expected = flat_indicators(j301_1)
    assert set(values) == TWELVE
    for k, v in values.items():
        assert v == pytest.approx(expected[k], abs=5e-4), k
    assert dsl["project_indicators"]["standard"] == "guo2021-v1"


def test_none_composition_has_no_indicators(j301_1):
    assert "project_indicators" not in build_dsl(j301_1, "none")


def test_levels_differ_only_by_indicator_block(j301_1):
    # Сравнение (а) и (б) честное: остальной DSL одинаков
    full, empty = build_dsl(j301_1, "all"), build_dsl(j301_1, "none")
    full.pop("project_indicators")
    assert full == empty


def test_dsl_does_not_leak_instance_identity(j301_1):
    text = json.dumps(build_dsl(j301_1, "all"), ensure_ascii=False)
    for leak in ("j301_1", "PSPLIB", "due_date", "case_info", "bks", "makespan\": 43"):
        assert leak not in text, leak


def test_unknown_composition_rejected(j301_1):
    with pytest.raises(ValueError, match="unknown composition"):
        build_dsl(j301_1, "everything")


@pytest.mark.parametrize("composition", list(COMPOSITIONS))
def test_kernel_builds_from_dsl_dict(j301_1, composition):
    dsl = build_dsl(j301_1, composition)
    meta, state = build_state(dsl, j301_1)
    assert meta.indicators == dsl.get("project_indicators", {}).get("values", {})
    assert not (meta.is_multi_project or meta.is_single_machine or meta.has_non_renewable)
    res = run_schedule(state, default_select, default_allocate)
    assert res["status"] == "complete"
    assert validate_schedule(j301_1, res["schedule"])["status"] == "valid"


def test_spring_dsl_files_still_parse_without_indicators():
    meta = DSLParser().parse_file(ROOT / "data" / "references" / "brief DSL description of projects"
                                  / "Case1_DSL_for_skeleton.json")
    assert meta.indicators == {}
    assert meta.graph["cpl"] == 38


def test_prompt_same_for_both_levels(j301_1):
    # Системный промпт и шаблон сообщения общие; различается только подставленный DSL
    for composition in ("all", "none"):
        dsl = build_dsl(j301_1, composition)
        system, user = prompt_v1.build_messages(dsl)
        assert system == {"role": "system", "content": prompt_v1.SYSTEM_PROMPT}
        assert user["content"] == prompt_v1.USER_TEMPLATE.format(
            dsl=json.dumps(dsl, ensure_ascii=False, indent=2))


def test_prompt_has_no_spring_fields_and_describes_indicators():
    text = prompt_v1.SYSTEM_PROMPT
    for stale in ("CPL", "order_strength", "non_renewable", "selection_groups", "is_single_machine",
                  "project_id", "earliness", "parallelism"):
        assert stale not in text, stale
    for key in TWELVE:
        assert f"- {key} —" in text, key
    for name in ("select_job_fn", "allocate_fn", "feasible_starts", "meta.indicators"):
        assert name in text


def test_contract_example_runs_in_kernel(j301_1):
    # Пример ответа по контракту промпта: приоритет по индикатору rs из meta.indicators
    select_code = """
def select_job_fn(eligible_ids, jobs, snapshot, meta):
    tight = meta.indicators.get("rs", 1.0) < 0.3
    def key(j):
        demand = sum(jobs[j].resources_required.values())
        return (-demand if tight else 0, -len(jobs[j].successors), j)
    return min(eligible_ids, key=key)
"""
    allocate_code = """
def allocate_fn(job, feasible_starts, snapshot, meta):
    return feasible_starts[0]
"""
    for composition in ("all", "none"):
        dsl = build_dsl(j301_1, composition)
        meta, state = build_state(dsl, j301_1)
        res = run_schedule(state, rc._compile(select_code, "select_job_fn"),
                           rc._compile(allocate_code, "allocate_fn"))
        assert res["status"] == "complete" and res["invalid_select_count"] == 0
        assert validate_schedule(j301_1, res["schedule"])["status"] == "valid"
