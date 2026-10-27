"""
Скрипт генерации В1 (experiments/v1_pilot/generate.py) на подменном клиенте LLM:
план задач, сохранение ответов, продолжение после обрыва, ошибки API и разбора.
Сеть и ключ API не нужны; нужен скачанный PSPLIB (инстансы выборки).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "v1_pilot"))

import generate as gen  # noqa: E402

pytestmark = pytest.mark.skipif(not gen.PSPLIB_INSTANCES.exists(),
                                reason="PSPLIB не скачан (data/psplib/SOURCES.md)")

MODEL = "test/model"

GOOD = json.dumps({
    "select_job_fn": "def select_job_fn(eligible_ids, jobs, snapshot, meta):\n    return eligible_ids[0]\n",
    "allocate_fn": "def allocate_fn(job, feasible_starts, snapshot, meta):\n    return feasible_starts[0]\n",
    "method": "first eligible", "reasoning": "r", "description": "d",
})


class FakeClient:
    """chat.completions.create -> ответ из очереди replies (строка) или исключение."""

    def __init__(self, replies=None, default=GOOD):
        self.replies = list(replies or [])
        self.default = default
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else self.default
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150))


def run(tmp_path, client, *extra):
    return gen.main(["--run", "t", "--pilot-only", "--gens", "1", "--workers", "2", "--model", MODEL,
                     "--out", str(tmp_path), *extra], client_factory=lambda: client)


def test_pilot_plan_is_30_instances_x_2_levels_x_3_gens():
    tasks = gen.make_tasks(gen.load_sample(), pilot_only=True, levels=["a", "b"], gens=3)
    assert len(tasks) == 180
    assert len({t.instance for t in tasks}) == 30
    assert len({t.filename for t in tasks}) == 180
    # Сначала все задачи первой генерации, чтобы при обрыве уровни были продвинуты поровну
    assert {t.gen for t in tasks[:60]} == {1}


def test_full_plan_size():
    assert len(gen.make_tasks(gen.load_sample(), pilot_only=False, levels=["a", "b"], gens=5)) == 1080


def test_records_and_messages(tmp_path):
    client = FakeClient()
    summary = run(tmp_path, client, "--limit", "4")
    assert summary["ok"] == 4 and summary["tasks"] == 60
    files = sorted((tmp_path / "t").glob("*__g1.json"))
    assert len(files) == 4
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["select_job_fn"].startswith("def select_job_fn")
    assert "error" not in rec and rec["tokens"]["total"] == 150
    assert rec["prompt_version"] == gen.PROMPT_VERSION
    call = client.calls[0]
    assert call["model"] == MODEL and call["temperature"] == gen.DEFAULT_TEMPERATURE
    assert call["max_tokens"] == gen.DEFAULT_MAX_TOKENS == 16000
    assert call["response_format"] == {"type": "json_object"}
    # Уровень a — DSL с индикаторами, b — без
    levels = {json.loads(f.read_text(encoding="utf-8"))["level"]: json.loads(f.read_text(encoding="utf-8"))
              for f in (tmp_path / "t").glob("*.json") if f.name not in ("manifest.json", "summary.json")}
    for level, rec in levels.items():
        assert ("project_indicators" in rec["dsl"]) == (level == "a")
    manifest = json.loads((tmp_path / "t" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["model"] == MODEL


def test_resume_skips_done_tasks(tmp_path):
    run(tmp_path, FakeClient(), "--limit", "5")
    client = FakeClient()
    summary = run(tmp_path, client)
    assert len(client.calls) == 55
    assert summary["ok"] == 60 and summary["missing"] == 0


def test_resume_with_other_settings_is_refused(tmp_path):
    run(tmp_path, FakeClient(), "--limit", "1")
    with pytest.raises(SystemExit, match="настройки отличаются"):
        run(tmp_path, FakeClient(), "--temperature", "0.2")


def test_api_errors_are_retried_then_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(gen.time, "sleep", lambda s: None)
    monkeypatch.setattr(gen, "ATTEMPTS", 2)
    # первая задача: сбой, затем успех; вторая: два сбоя подряд -> ошибка
    client = FakeClient(replies=[TimeoutError("t1"), GOOD])
    run(tmp_path, client, "--limit", "1", "--workers", "1")
    client2 = FakeClient(replies=[TimeoutError("a"), TimeoutError("b")])
    summary = run(tmp_path, client2, "--limit", "1", "--workers", "1")
    assert summary["ok"] == 1 and summary["errors"] == {"api_error": 1}
    # без --retry-errors ошибочный файл не перезапрашивается
    summary = run(tmp_path, FakeClient(), "--limit", "1", "--workers", "1")
    assert summary["ok"] == 2 and summary["errors"] == {"api_error": 1}
    client4 = FakeClient()
    summary = run(tmp_path, client4, "--retry-errors", "--workers", "1")
    assert summary["errors"] == {} and summary["ok"] == 60


def test_bad_json_and_missing_functions_are_parse_errors(tmp_path):
    client = FakeClient(replies=["not json", json.dumps({"method": "x"})])
    summary = run(tmp_path, client, "--limit", "2", "--workers", "1")
    assert summary["errors"] == {"parse_error": 2}


def test_fenced_reply_with_text_around_is_parsed():
    # Anthropic через прокси отвечает ```json ... ``` несмотря на response_format
    raw = "Вот решение:\n```json\n" + GOOD + "\n```\nГотово."
    out = gen.parse_response(raw, "stop")
    assert "error" not in out
    assert out["select_job_fn"].startswith("def select_job_fn") and out["method"] == "first eligible"


def test_truncated_reply_is_reported_as_truncated():
    raw = "```json\n" + GOOD[: len(GOOD) // 2]
    assert gen.parse_response(raw, "length")["error"].startswith("truncated:")
    assert gen.parse_response(raw, "stop")["error"].startswith("parse_error:")
    assert gen.parse_response("", "length")["error"].startswith("truncated:")


def test_reasoning_tokens_recorded(tmp_path):
    client = FakeClient()

    def create(**kwargs):
        resp = FakeClient._create(client, **kwargs)
        resp.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=40)
        return resp
    client.chat.completions.create = create
    summary = run(tmp_path, client, "--limit", "2")
    assert summary["tokens"]["reasoning"] == 80
    rec = json.loads(next((tmp_path / "t").glob("*__g1.json")).read_text(encoding="utf-8"))
    assert rec["tokens"]["reasoning"] == 40


def test_truncated_errors_in_summary(tmp_path):
    client = FakeClient()

    def create(**kwargs):
        resp = FakeClient._create(client, **kwargs)
        resp.choices[0].message.content = GOOD[:40]
        resp.choices[0].finish_reason = "length"
        return resp
    client.chat.completions.create = create
    summary = run(tmp_path, client, "--limit", "2", "--workers", "1")
    assert summary["errors"] == {"truncated": 2}


def test_dry_run_makes_no_calls(tmp_path):
    def factory():
        raise AssertionError("dry-run не должен создавать клиента")
    out = gen.main(["--run", "t", "--pilot-only", "--dry-run", "--model", MODEL, "--out", str(tmp_path)],
                   client_factory=factory)
    assert out == {"tasks": 180, "todo": 180}
    assert not (tmp_path / "t").exists()


def test_model_is_required(tmp_path):
    with pytest.raises(SystemExit):
        gen.main(["--run", "t", "--pilot-only", "--dry-run", "--out", str(tmp_path)])
