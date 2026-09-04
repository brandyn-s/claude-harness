"""The `current-anthropic-model` key is derived from the run's own vendor model list.

KEY-FREE: a fake SDK client stands in for `anthropic.Anthropic()`. Covers snapshot
capture (run_live.fetch_model_catalog), term derivation (grade.catalog_key), the
offline re-grade path (regrade.py reads the RECORDED snapshot), and the fallback to
the fixture's dated keys for records made before snapshots existed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL = Path(__file__).resolve().parent.parent
HARNESS = SKILL / "harness"
FIXTURE = json.loads((HARNESS / "fixture.json").read_text(encoding="utf-8"))
CURRENT_MODEL_QUESTION = next(q for q in FIXTURE["questions"] if q["id"] == "current-anthropic-model")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"deep_dive_{name}", HARNESS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grade = _load("grade")


class _Page:
    """Mimics the SDK page object: iterating it walks every page."""

    def __init__(self, *pages):
        self.pages = pages
        self.pages_walked = 0

    def __iter__(self):
        for page in self.pages:
            self.pages_walked += 1
            yield from page


def _model(model_id: str, display_name: str, created: str):
    return SimpleNamespace(id=model_id, display_name=display_name,
                           created_at=datetime.fromisoformat(created).replace(tzinfo=UTC))


def _fake_client(page: _Page):
    return SimpleNamespace(models=SimpleNamespace(list=lambda **_kw: page))


# Two models launched on the newest date (a paired launch), one older, one much older.
_SNAPSHOT = [
    {"id": "claude-fable-5-1", "display_name": "Claude Fable 5.1", "created_at": "2026-08-20T00:00:00+00:00"},
    {"id": "claude-mythos-5-1", "display_name": "Claude Mythos 5.1", "created_at": "2026-08-20T00:00:00+00:00"},
    {"id": "claude-opus-5", "display_name": "Claude Opus 5", "created_at": "2026-08-01T00:00:00+00:00"},
    {"id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5", "created_at": "2025-10-01T00:00:00+00:00"},
]


def test_fetch_model_catalog_walks_every_page_and_sorts_newest_first():
    runner = _load("run_live")
    page = _Page(
        [_model("claude-haiku-4-5", "Claude Haiku 4.5", "2025-10-01"),
         _model("claude-opus-5", "Claude Opus 5", "2026-08-01")],
        [_model("claude-mythos-5-1", "Claude Mythos 5.1", "2026-08-20"),
         _model("claude-fable-5-1", "Claude Fable 5.1", "2026-08-20")],
    )

    snapshot = runner.fetch_model_catalog(_fake_client(page))

    assert page.pages_walked == 2, "iteration must page through the whole list"
    assert snapshot == _SNAPSHOT, "compact fields only, ISO timestamps, newest first then id"
    assert all(set(row) == {"id", "display_name", "created_at"} for row in snapshot)


def test_fetch_model_catalog_rejects_an_empty_list():
    runner = _load("run_live")
    with pytest.raises(runner.RuntimeQualificationError, match="model list is empty"):
        runner.fetch_model_catalog(_fake_client(_Page([])))


def test_catalog_key_names_every_family_released_on_the_newest_date():
    key = grade.catalog_key(_SNAPSHOT)

    assert key["expected_terms"] == ["fable 5.1", "fable", "mythos 5.1", "mythos"]
    assert key["derived_from"] == ["claude-fable-5-1", "claude-mythos-5-1"]
    assert key["released"] == "2026-08-20"
    assert key["wrong_terms"] == [] and key["verified"] is None and key["source"] == "model-catalog"
    # "Claude" itself is never a term: every answer mentions it.
    assert all("claude" not in term for term in key["expected_terms"])


def test_catalog_key_falls_back_to_the_id_without_a_display_name_and_rejects_empty():
    assert grade.catalog_key([{"id": "claude-fable-5-1", "created_at": "2026-08-20"}])["expected_terms"] == [
        "fable 5 1", "fable"]
    with pytest.raises(ValueError, match="empty"):
        grade.catalog_key([])


def test_snapshot_grades_the_current_model_question_and_beats_the_dated_keys():
    q = CURRENT_MODEL_QUESTION
    assert q["key_source"] == "model-catalog"
    fable = "Anthropic's top tier is Claude Fable 5.1 (with Claude Mythos 5.1 for Project Glasswing)."
    opus = "The most capable family is Opus, currently Claude Opus 4.8."
    # With a snapshot the run date is irrelevant to this question: the snapshot is the key.
    for run_date in ("2026-05-31", "2026-09-04"):
        assert grade.answer_correct(q, fable, run_date=run_date, model_catalog=_SNAPSHOT) is True
        assert grade.answer_correct(q, opus, run_date=run_date, model_catalog=_SNAPSHOT) is False
    assert grade.key_for(q, "2026-09-04", _SNAPSHOT)["source"] == "model-catalog"
    assert grade.key_source(q, _SNAPSHOT) == "model-catalog"
    # A snapshot whose newest family the legacy key would reject proves the catalog path wins.
    zephyr = [{"id": "claude-zephyr-7", "display_name": "Claude Zephyr 7", "created_at": "2026-09-01"}]
    assert grade.answer_correct(q, "Zephyr 7 leads the lineup.", run_date="2026-09-04", model_catalog=zephyr) is True
    assert grade.answer_correct(q, fable, run_date="2026-09-04", model_catalog=zephyr) is False


def test_dated_keys_remain_the_fallback_for_records_without_a_snapshot():
    q = CURRENT_MODEL_QUESTION
    legacy = grade.key_for(q, "2026-09-03")
    assert legacy["legacy"] is True and legacy["verified"] is None, "the inferred second window is marked legacy"
    frozen = grade.key_for(q, "2026-05-31")
    assert frozen["verified"] == "2026-05-31" and "legacy" not in frozen
    assert grade.key_source(q) == "dated" and grade.key_source(q, None) == "dated"
    assert grade.key_source(q, []) == "dated", "an empty snapshot is no snapshot"
    fixture = {"questions": [q, {"id": "stable", "kind": "fact", "expected_terms": ["2017"], "wrong_terms": []}]}
    recs = [{"id": q["id"], "answer_text": "Claude Fable 5", "confidence": "HIGH"},
            {"id": "stable", "answer_text": "2017", "confidence": "HIGH"}]
    rows = grade.score_run(fixture, recs, run_date="2026-09-03")["rows"]
    assert [r["key_source"] for r in rows] == ["dated", "static"]
    rows = grade.score_run(fixture, recs, run_date="2026-09-03", model_catalog=_SNAPSHOT)["rows"]
    assert [r["key_source"] for r in rows] == ["model-catalog", "static"]
    # Static questions never consult the snapshot.
    assert grade.answer_correct(fixture["questions"][1], "2017", model_catalog=_SNAPSHOT) is True


def _synthetic_run(runner, tmp_path, monkeypatch, answer_for: dict[str, str], *, model_catalog):
    runner.MODEL = "claude-synthetic-9"
    runner.RESULTS = tmp_path / "out.json"
    runner.RUNS_DIR = tmp_path / "runs"
    runner.RUN_RECEIPT = {"requested_model": runner.MODEL}

    def task(arm, _system, question):
        response = SimpleNamespace(model=runner.MODEL, stop_reason="end_turn", content=[])
        runner._record_runtime_response(response)
        provenance = runner.response_trial_provenance(
            response=response, requested_model=runner.MODEL, provider=runner.PROVIDER,
            grader_config=runner.GRADER_CONFIG)
        return {"arm": arm, "id": question["id"], "answer_text": answer_for.get(question["id"], "2017"),
                "confidence": "HIGH", "counterfactual": "", "_response_provenance": [provenance]}

    monkeypatch.setattr(runner, "_one_task", task)
    # limit=7 covers questions 1-7; the only currency question among them is current-anthropic-model.
    return runner.run(n_runs=1, limit=7, workers=1, model_catalog=model_catalog)


def test_run_records_the_snapshot_and_grades_currency_from_it(tmp_path, monkeypatch):
    runner = _load("run_live")
    zephyr = [{"id": "claude-zephyr-7", "display_name": "Claude Zephyr 7", "created_at": "2026-09-01T00:00:00+00:00"},
              {"id": "claude-opus-5", "display_name": "Claude Opus 5", "created_at": "2026-08-01T00:00:00+00:00"}]

    result = _synthetic_run(runner, tmp_path, monkeypatch,
                            {"current-anthropic-model": "Zephyr 7 is the flagship family."},
                            model_catalog=zephyr)

    receipt = result["runtime_receipt"]
    assert receipt["model_catalog"] == zephyr
    assert receipt["current_model_key"]["expected_terms"] == ["zephyr 7", "zephyr"]
    assert receipt["current_model_key"]["derived_from"] == ["claude-zephyr-7"]
    # "zephyr" is accepted by no dated key: only the snapshot path can grade it correct.
    assert result["metrics"]["with_skill"]["currency_accuracy"]["mean"] == pytest.approx(1.0)
    assert result["metrics"]["baseline"]["currency_accuracy"]["mean"] == pytest.approx(1.0)
    transcripts = json.loads(next((tmp_path / "runs").glob("transcripts-*.json")).read_text(encoding="utf-8"))
    sample = json.loads(next((tmp_path / "runs").glob("sample-records-*.json")).read_text(encoding="utf-8"))
    assert transcripts["model_catalog"] == zephyr and len(transcripts["runs"]) == 1
    assert sample["model_catalog"] == zephyr and len(sample["runs"]) == 1


def _run_regrade(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HARNESS / "regrade.py"), *args],
                          capture_output=True, text=True, timeout=120, check=False)


def _records(answer: str) -> list[dict]:
    return [{"run_idx": 0, "records": [
        {"arm": arm, "id": "current-anthropic-model", "answer_text": answer, "confidence": "HIGH",
         "counterfactual": ""} for arm in ("with_skill", "baseline")]}]


def test_regrade_rederives_the_key_from_the_recorded_snapshot_offline(tmp_path):
    regrade = _load("regrade")
    zephyr = [{"id": "claude-zephyr-7", "display_name": "Claude Zephyr 7", "created_at": "2026-09-01T00:00:00+00:00"}]
    records = tmp_path / "transcripts-20260904T000000Z.json"
    records.write_text(json.dumps({"model_catalog": zephyr, "runs": _records("Zephyr 7 leads.")}), encoding="utf-8")

    runs, catalog = regrade.load_records(records)
    assert catalog == zephyr and len(runs) == 1
    out = tmp_path / "regrade.json"
    proc = _run_regrade("--records", str(records), "--run-date", "2026-09-04", "--model", "claude-zephyr-7",
                        "--output", str(out), "--sample-out", str(tmp_path / "sample.json"))
    assert proc.returncode == 0, proc.stderr
    rg = json.loads(out.read_text(encoding="utf-8"))
    assert rg["model_catalog"] == zephyr
    assert rg["current_model_key"]["expected_terms"] == ["zephyr 7", "zephyr"]
    assert rg["per_question"]["current-anthropic-model"]["key_source"] == "model-catalog"
    assert rg["per_question"]["current-anthropic-model"]["with_skill"]["correct"] == [True]
    assert json.loads((tmp_path / "sample.json").read_text(encoding="utf-8"))["model_catalog"] == zephyr


def test_regrade_of_pre_snapshot_records_uses_the_legacy_dated_key(tmp_path):
    regrade = _load("regrade")
    records = tmp_path / "sample-records-2026-09-03.json"
    records.write_text(json.dumps({"runs": _records("Claude Fable 5 tops the lineup.")}), encoding="utf-8")

    _runs, catalog = regrade.load_records(records)
    assert catalog is None
    out = tmp_path / "regrade.json"
    proc = _run_regrade("--records", str(records), "--run-date", "2026-09-03", "--model", "claude-fable-5-1",
                        "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    rg = json.loads(out.read_text(encoding="utf-8"))
    assert rg["model_catalog"] is None and rg["current_model_key"] is None
    assert rg["per_question"]["current-anthropic-model"]["key_source"] == "dated"
    assert rg["per_question"]["current-anthropic-model"]["baseline"]["correct"] == [True]
    # The committed pre-snapshot samples carry no snapshot, so their grading is untouched.
    for name in ("sample-records-2026-05-31.json", "sample-records-2026-09-03.json"):
        assert regrade.load_records(HARNESS / "runs" / name)[1] is None


_FAILING_SDK = '''
class _Models:
    def list(self, **kwargs):
        raise RuntimeError("models endpoint unavailable")


class _Messages:
    def create(self, **kwargs):
        raise AssertionError("no paid call may follow a failed model-list snapshot")


class Anthropic:
    def __init__(self, *args, **kwargs):
        self.models = _Models()
        self.messages = _Messages()
'''


def test_live_run_aborts_before_any_paid_call_when_the_model_list_fails(tmp_path):
    import shutil

    work = tmp_path / "harness"
    shutil.copytree(HARNESS, work)  # never run against the committed runs/ directory
    fake_sdk = tmp_path / "fake-sdk"
    fake_sdk.mkdir()
    (fake_sdk / "anthropic.py").write_text(_FAILING_SDK, encoding="utf-8")
    output = tmp_path / "out.json"
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ANTHROPIC")}
    env.update({"ANTHROPIC_API_KEY": "test-only-fake", "PYTHONPATH": str(fake_sdk)})
    runs_before = sorted(p.name for p in (work / "runs").iterdir())

    proc = subprocess.run(
        [sys.executable, str(work / "run_live.py"), "--model", "claude-sonnet-5",
         "--output", str(output), "--runs", "1", "--limit", "1", "--workers", "1",
         "--acknowledge-retired-fixture"],  # the snapshot happens behind the retired-fixture gate
        capture_output=True, text=True, timeout=120, env=env, cwd=str(HARNESS.parents[2]), check=False)

    assert proc.returncode == 2, proc.stderr
    assert "pass --acknowledge-retired-fixture" not in proc.stderr, "the acknowledged run must get past the fixture gate"
    assert "could not snapshot the vendor model list" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not output.exists()
    assert sorted(p.name for p in (work / "runs").iterdir()) == runs_before, "an aborted run writes no records"
