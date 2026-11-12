"""
Прогон генераций В2-LLM в каркасе (experiments/v2_counterexamples/llm_run_kernel.py):
makespan из чекера, RPD к best_known, сравнение с LFT, ошибки генерации — недопустимые.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "v2_counterexamples"))

import llm_generate as lg  # noqa: E402
import llm_run_kernel as lk  # noqa: E402
import run_rules  # noqa: E402
from test_generation import GOOD  # noqa: E402

BAD_CODE = json.dumps({
    "select_job_fn": "def select_job_fn(eligible_ids, jobs, snapshot, meta):\n    return 1/0\n",
    "allocate_fn": "def allocate_fn(job, feasible_starts, snapshot, meta):\n    return feasible_starts[0]\n",
    "method": "crash", "reasoning": "r", "description": "d"})


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("k")
    sample = lg.load_or_make_sample(tmp / "llm_sample.json")
    row = next(r for r in sample["instances"] if r["part"] == "pilot" and r["fired"])
    sample = {**sample, "instances": [row]}
    (tmp / "llm_sample.json").write_text(json.dumps(sample), encoding="utf-8")
    # Эталон и правила — тем же run_rules, что и сетка f1-grid
    run_rules.main(["--run", "ref", "--manifest", str(tmp / "llm_sample.json"), "--samples", "5",
                    "--workers", "1", "--results-dir", str(tmp / "results")])
    gen_dir = tmp / "gen" / "t"
    gen_dir.mkdir(parents=True)
    inst = lg.build(row)
    d = lg.router.decide(inst, sample["trigger"])
    for level, reply in (("b", GOOD), ("v", GOOD), ("g", BAD_CODE)):
        rec = {"project": row["id"], "level": level, "gen": 1, "router": d,
               "dsl": lg.router.route_dsl(inst, level, d), **lg.v1.parse_response(reply)}
        (gen_dir / f"{row['id']}__{level}__g1.json").write_text(json.dumps(rec), encoding="utf-8")
    (gen_dir / f"{row['id']}__b__g2.json").write_text(json.dumps(
        {"project": row["id"], "level": "b", "gen": 2, "router": d, "dsl": {},
         "error": "parse_error: no JSON"}), encoding="utf-8")
    summary = lk.main(["--run", "t", "--ref", "ref", "--sample", str(tmp / "llm_sample.json"),
                       "--generations", str(tmp / "gen"), "--results-dir", str(tmp / "results")])
    runs = {(r["level"], r["gen"]): r for r in lk.read_csv(tmp / "results" / "t" / "runs.csv")}
    return row, summary, runs, tmp


def test_valid_generation_measured_against_reference(setup):
    row, _, runs, tmp = setup
    r = runs[("b", "1")]
    assert r["status"] == "ok"
    best = float(next(i for i in lk.read_csv(tmp / "results" / "ref" / "instances.csv"))["best"])
    assert float(r["best"]) == best
    assert float(r["rpd_best"]) == pytest.approx(100 * (float(r["makespan"]) - best) / best, abs=1e-4)
    assert r["fired"] == "True"


def test_runtime_and_generation_errors_are_invalid(setup):
    _, _, runs, _ = setup
    assert runs[("g", "1")]["status"] == "runtime_error"
    assert runs[("g", "1")]["makespan"] == ""
    assert runs[("b", "2")]["status"] == "generation_error"


def test_summary_counts_valid_share_by_level(setup):
    _, summary, _, _ = setup
    assert summary["levels"]["b"]["runs"] == 2 and summary["levels"]["b"]["valid"] == 1
    assert summary["levels"]["g"]["valid"] == 0


def test_not_worse_than_lft_flag(setup):
    _, _, runs, _ = setup
    r = runs[("b", "1")]
    assert r["not_worse_lft"] == str(float(r["makespan"]) <= float(r["lft"]))


def test_report_written(setup):
    _, _, _, tmp = setup
    text = (tmp / "results" / "t" / "report.md").read_text(encoding="utf-8")
    assert "допустимых" in text and "LFT" in text
