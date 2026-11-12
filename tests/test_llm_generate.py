"""
Генерация В2-LLM (experiments/v2_counterexamples/llm_generate.py, ADR 0004) на подменном
клиенте: выборка пилота и основная, план вызовов с учетом маршрутизатора, копии (б)
для несработавших проектов, блоки уровней в запросе. Сеть и ключ API не нужны.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "v2_counterexamples"))

import llm_generate as lg  # noqa: E402
from test_generation import GOOD, FakeClient  # noqa: E402,F401


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return lg.load_or_make_sample(tmp_path_factory.mktemp("s") / "llm_sample.json")


def rows(sample, part):
    return [r for r in sample["instances"] if r["part"] == part]


def test_pilot_and_main_parts_use_new_seeds(sample):
    pilot, main = rows(sample, "pilot"), rows(sample, "main")
    assert len(pilot) == 12 and len(main) == 60
    assert {r["seed"] for r in pilot} == {90, 91}
    assert {r["seed"] for r in main} == {20, 21, 22, 23, 24}
    assert {(r["n_res"], r["control"]) for r in pilot + main} == {(4, "fits")}
    assert len({r["id"] for r in pilot + main}) == 72


def test_router_decisions_stored_before_generation(sample):
    for r in sample["instances"]:
        assert set(r) >= {"value", "fired", "hash"}
    isolated_control = [r for r in sample["instances"] if r["env"] == "isolated" and r["s"] == 0.0]
    assert not any(r["fired"] for r in isolated_control)


def test_sample_file_is_reused_and_checked(tmp_path):
    path = tmp_path / "llm_sample.json"
    first = lg.load_or_make_sample(path)
    assert lg.load_or_make_sample(path) == first
    data = json.loads(path.read_text(encoding="utf-8"))
    data["instances"][0]["hash"] = "0" * 16
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit):
        lg.load_or_make_sample(path)


def test_calls_only_for_b_and_fired_projects(sample):
    part = rows(sample, "pilot")
    fired = sum(r["fired"] for r in part)
    calls = lg.make_tasks(part, gens=2, routed_only=True)
    assert len(calls) == 12 * 2 + 2 * 2 * fired
    assert {t.level for t in calls if not next(r for r in part if r["id"] == t.project)["fired"]} == {"b"}


def run(tmp_path, client, sample_path, *extra):
    return lg.main(["--run", "t", "--part", "pilot", "--gens", "1", "--workers", "2",
                    "--model", "test/model", "--out", str(tmp_path / "gen"),
                    "--sample", str(sample_path), *extra], client_factory=lambda: client)


@pytest.fixture
def sample_path(tmp_path, sample):
    path = tmp_path / "llm_sample.json"
    path.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    return path


def test_dry_run_makes_no_calls(tmp_path, sample_path):
    client = FakeClient()
    out = run(tmp_path, client, sample_path, "--dry-run")
    assert client.calls == []
    assert not (tmp_path / "gen" / "t").exists()
    assert out["calls"] == out["tasks"] - out["copies"]


def test_unrouted_levels_copy_level_b(tmp_path, sample, sample_path):
    client = FakeClient()
    summary = run(tmp_path, client, sample_path)
    part = rows(sample, "pilot")
    fired = sum(r["fired"] for r in part)
    assert len(client.calls) == 12 + 2 * fired
    assert summary["ok"] == 36 and summary["copied"] == 2 * (12 - fired)
    run_dir = tmp_path / "gen" / "t"
    quiet = next(r for r in part if not r["fired"])
    b = json.loads((run_dir / f"{quiet['id']}__b__g1.json").read_text(encoding="utf-8"))
    for level in ("v", "g"):
        rec = json.loads((run_dir / f"{quiet['id']}__{level}__g1.json").read_text(encoding="utf-8"))
        assert rec["copied_from"] == "b" and rec["level"] == level
        assert rec["raw"] == b["raw"] and rec["dsl"] == b["dsl"]


def test_fired_requests_carry_level_block(tmp_path, sample, sample_path):
    client = FakeClient()
    run(tmp_path, client, sample_path)
    fired = next(r for r in rows(sample, "pilot") if r["fired"])
    run_dir = tmp_path / "gen" / "t"
    v = json.loads((run_dir / f"{fired['id']}__v__g1.json").read_text(encoding="utf-8"))
    g = json.loads((run_dir / f"{fired['id']}__g__g1.json").read_text(encoding="utf-8"))
    assert "rule_guidance" in v["dsl"] and "copied_from" not in v
    assert "project_properties" in g["dsl"]
    assert v["router"]["fired"] is True
    texts = [c["messages"][1]["content"] for c in client.calls]
    assert any("rule_guidance" in t for t in texts)
    assert any("project_properties" in t for t in texts)
    for c in client.calls:
        assert c["extra_body"] == {"cache": {"no-cache": True, "no-store": True}}


def test_retry_refreshes_copies_of_failed_b(tmp_path, sample, sample_path, monkeypatch):
    monkeypatch.setattr(lg.v1, "RETRY_PAUSE_S", 0)
    quiet = next(r for r in rows(sample, "pilot") if not r["fired"])
    # Первый запуск: все вызовы падают, копии b на несработавших проектах — тоже ошибки
    run(tmp_path, FakeClient(default=RuntimeError("403")), sample_path)
    run_dir = tmp_path / "gen" / "t"
    assert "error" in json.loads((run_dir / f"{quiet['id']}__v__g1.json").read_text(encoding="utf-8"))
    run(tmp_path, FakeClient(), sample_path, "--retry-errors")
    for level in ("v", "g"):
        rec = json.loads((run_dir / f"{quiet['id']}__{level}__g1.json").read_text(encoding="utf-8"))
        assert "error" not in rec and rec["copied_from"] == "b"


def test_run_with_other_router_texts_cannot_be_continued(tmp_path, sample_path, monkeypatch):
    run(tmp_path, FakeClient(), sample_path)
    manifest = json.loads((tmp_path / "gen" / "t" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["router_version"] == lg.router.ROUTER_VERSION
    monkeypatch.setattr(lg.router, "ROUTER_VERSION", "other")
    with pytest.raises(SystemExit):
        run(tmp_path, FakeClient(), sample_path)


def test_reasoning_limit_sent_only_when_given(tmp_path, sample_path):
    # Qwen в пилоте тратил все 16000 токенов на рассуждение
    limited = FakeClient()
    run(tmp_path, limited, sample_path, "--run", "lim", "--reasoning-max-tokens", "4000")
    assert limited.calls and all(c["extra_body"]["reasoning"] == {"max_tokens": 4000}
                                 for c in limited.calls)
    assert all("reasoning_effort" not in c for c in limited.calls)
    manifest = json.loads((tmp_path / "gen" / "lim" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["reasoning_max_tokens"] == 4000
    rec = json.loads(next((tmp_path / "gen" / "lim").glob("*__b__g1.json")).read_text(encoding="utf-8"))
    assert rec["reasoning_max_tokens"] == 4000
    default = FakeClient()
    run(tmp_path, default, sample_path, "--run", "default")
    assert default.calls and all("reasoning" not in c["extra_body"] for c in default.calls)


def test_run_with_other_reasoning_limit_cannot_be_continued(tmp_path, sample_path):
    run(tmp_path, FakeClient(), sample_path, "--reasoning-max-tokens", "4000", "--limit", "1")
    with pytest.raises(SystemExit):
        run(tmp_path, FakeClient(), sample_path, "--reasoning-max-tokens", "2000")


def test_limit_makes_at_most_n_calls(tmp_path, sample_path):
    client = FakeClient()
    run(tmp_path, client, sample_path, "--limit", "1")
    assert len(client.calls) == 1


def test_restart_does_not_repeat_calls(tmp_path, sample_path):
    run(tmp_path, FakeClient(), sample_path)
    again = FakeClient()
    run(tmp_path, again, sample_path)
    assert again.calls == []
