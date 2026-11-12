"""
Оценка В2-LLM (experiments/v2_counterexamples/llm_evaluate.py, ADR 0004 п. 8): значение
проекта — среднее RPD допустимых генераций; парный Уилкоксон по проектам, Холм на два
основных сравнения, δ = 0,5 п. п.; проекты без допустимой генерации на уровне — исключаются.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "v2_counterexamples"))

import llm_evaluate as le  # noqa: E402

COLUMNS = ["project", "env", "s", "fired", "level", "gen", "status", "rpd_best", "not_worse_lft",
           "lft", "best"]


def row(project, env, s, fired, level, gen, rpd, status="ok"):
    return {"project": project, "env": env, "s": s, "fired": fired, "level": level, "gen": gen,
            "status": status, "rpd_best": "" if status != "ok" else rpd,
            "not_worse_lft": "" if status != "ok" else rpd <= 1.0, "lft": 100, "best": 100}


@pytest.fixture
def runs_csv(tmp_path):
    rows = []
    # 8 сработавших проектов: v хуже b на ~10, g лучше b на ~4
    for i in range(8):
        env = "isolated" if i < 5 else "shared"
        p = f"P{i}"
        for gen in (1, 2):
            rows.append(row(p, env, 1.0, True, "b", gen, 10 + i + gen))
            rows.append(row(p, env, 1.0, True, "v", gen, 20 + i + gen + 0.1 * i))
            rows.append(row(p, env, 1.0, True, "g", gen, 6 + i + gen - 0.1 * i))
    # у P7 на g обе генерации недопустимы — проект выпадает из сравнения с g
    rows = [r for r in rows if not (r["project"] == "P7" and r["level"] == "g")]
    rows += [row("P7", "shared", 1.0, True, "g", 1, None, "runtime_error"),
             row("P7", "shared", 1.0, True, "g", 2, None, "generation_error")]
    # 2 несработавших: v, g — копии b
    for i in (8, 9):
        for level in "bvg":
            rows.append(row(f"P{i}", "isolated", 0.0, False, level, 1, 0.0))
    path = tmp_path / "runs.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def test_project_value_is_mean_of_valid_generations(runs_csv):
    values = le.project_values(le.read_runs(runs_csv))
    assert values[("P0", "b")] == pytest.approx(11.5)
    assert ("P7", "g") not in values


def test_primary_comparisons_on_fired_projects_with_holm(runs_csv):
    out = le.evaluate(le.read_runs(runs_csv))
    prim = out["primary"]
    assert set(prim) == {"v-b", "g-b"}
    assert prim["v-b"]["n"] == 8 and prim["v-b"]["mean_diff"] > 0
    assert prim["g-b"]["n"] == 7 and prim["g-b"]["excluded"] == 1
    assert prim["g-b"]["mean_diff"] < 0
    raw = {k: v["p_value"] for k, v in prim.items()}
    assert prim["v-b"]["p_holm"] >= raw["v-b"]
    assert max(raw.values()) <= max(v["p_holm"] for v in prim.values())


def test_verdict_needs_significance_and_delta(runs_csv):
    prim = le.evaluate(le.read_runs(runs_csv))["primary"]
    assert prim["v-b"]["verdict"] == "хуже b"
    assert prim["g-b"]["verdict"] == "лучше b"


def test_secondary_include_env_split_and_all_projects(runs_csv):
    sec = le.evaluate(le.read_runs(runs_csv))["secondary"]
    assert sec["g-v | сработавшие"]["n"] == 7
    assert sec["v-b | isolated, сработавшие"]["n"] == 5
    assert sec["v-b | все проекты"]["n"] == 10
    assert sec["v-b | все проекты"]["ties"] == 2  # Несработавшие дают нулевую разность


def test_report_written(runs_csv, tmp_path):
    le.main(["--runs", str(runs_csv), "--out", str(tmp_path)])
    text = (tmp_path / "eval.md").read_text(encoding="utf-8")
    assert "Холм" in text and "v-b" in text and "g-b" in text
    assert "| g-v, сработавшие |" in text
    assert all(line.count("|") == 10 for line in text.splitlines() if line.startswith("| g-v"))
