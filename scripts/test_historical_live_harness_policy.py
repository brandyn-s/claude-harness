"""Corpus contract for frozen 2026-05-31 live-harness baselines."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECLARED_HARNESSES = (
    "deep-dive",
    "evaluate-repos",
    "gather-claude",
    "gather-intel",
    "gather-internal-intel",
    "gather-research",
    "investigate",
    "triage",
)
HARNESSES = tuple(
    name
    for name in DECLARED_HARNESSES
    if (ROOT / "skills" / name / "harness" / "run_live.py").is_file()
    and (ROOT / "skills" / name / "harness" / "results.json").is_file()
)
assert HARNESSES, "curated export contains no runnable historical harnesses"
HISTORICAL_MODEL = "claude-opus-4-8"
CURRENT_MODEL = "claude-opus-5"
COVERED_MODELS = ("claude-fable-5", "claude-mythos-5")
LIMITED_HARNESSES = {
    "deep-dive",
    "evaluate-repos",
    "gather-claude",
    "gather-intel",
    "gather-research",
}

FAKE_ANTHROPIC = r'''import json
import os
from types import SimpleNamespace


class _Messages:
    def create(self, **kwargs):
        response = SimpleNamespace()
        if os.environ.get("FAKE_RESPONSE_MODEL") != "<missing>":
            response.model = os.environ.get("FAKE_RESPONSE_MODEL", kwargs["model"])
        if os.environ.get("FAKE_STOP_REASON") != "<missing>":
            response.stop_reason = os.environ.get("FAKE_STOP_REASON", "end_turn")
        refusal = os.environ.get("FAKE_REFUSAL") == "1"
        content_type = "refusal" if refusal else "text"
        payload = {
            "answer": "verified",
            "confidence": "HIGH",
            "counterfactual": "inverted hypothesis SURVIVES",
            "decision": "ADOPT",
            "reasoning": "verified",
            "verdict": "benign",
            "timeline": "ordered",
            "ranking": ["F1"],
            "groups": [],
            "cited_urls": [],
        }
        response.content = [SimpleNamespace(
            type=content_type,
            text="```json\n" + json.dumps(payload) + "\n```",
        )]
        return response


class Anthropic:
    def __init__(self, *args, **kwargs):
        self.messages = _Messages()
'''


def _invoke(
    script: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("ANTHROPIC")
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _fake_runtime(
    skill_name: str, tmp_path: Path, *, historical: bool = False, **fake_env: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    source_harness = ROOT / "skills" / skill_name / "harness"
    copied_harness = tmp_path / skill_name / "harness"
    shutil.copytree(source_harness, copied_harness)
    fake_sdk = tmp_path / skill_name / "fake-sdk"
    fake_sdk.mkdir(parents=True)
    (fake_sdk / "anthropic.py").write_text(FAKE_ANTHROPIC, encoding="utf-8")
    # Real runs need httpx for grounding fetches and the gather harnesses fail fast
    # without it (2026-09-03). The fake runtime never grounds, so a stub that
    # refuses to fetch satisfies the pre-flight and proves nothing is fetched.
    (fake_sdk / "httpx.py").write_text(
        "def get(*args, **kwargs):\n"
        "    raise AssertionError('the fake runtime must not perform grounding fetches')\n",
        encoding="utf-8",
    )
    output = tmp_path / skill_name / "measurement.json"
    mode_args = ["--historical-reproduction"] if historical else ["--model", CURRENT_MODEL]
    args = [
        *mode_args,
        "--output",
        str(output),
        "--runs",
        "1",
        "--workers",
        "1",
    ]
    if skill_name in LIMITED_HARNESSES:
        args.extend(("--limit", "1"))
    env = {
        "ANTHROPIC_API_KEY": "test-only-fake-provider",
        "PYTHONPATH": str(fake_sdk),
        **fake_env,
    }
    return _invoke(copied_harness / "run_live.py", *args, extra_env=env), output


@pytest.mark.parametrize("skill_name", HARNESSES)
def test_live_harness_requires_explicit_historical_or_current_receipt_mode(
    skill_name: str, tmp_path: Path
) -> None:
    harness = ROOT / "skills" / skill_name / "harness"
    script = harness / "run_live.py"
    frozen = harness / "results.json"
    frozen_before = frozen.read_bytes()
    runs_before = {
        path.relative_to(harness).as_posix(): path.read_bytes()
        for path in sorted((harness / "runs").glob("*"))
        if path.is_file()
    }
    source = script.read_text(encoding="utf-8")

    assert f'HISTORICAL_MODEL = "{HISTORICAL_MODEL}"' in source
    assert not re.search(
        rf'^MODEL\s*=\s*"{re.escape(HISTORICAL_MODEL)}"', source, re.MULTILINE
    )
    for flag in ("--historical-reproduction", "--model", "--output", "--plan-only"):
        assert flag in source
    assert "--approve-covered-model-retention" in source
    assert source.count("messages.create(") + 1 == source.count("_record_runtime_response(")

    no_mode = _invoke(
        script,
        "--output",
        str(tmp_path / f"{skill_name}-no-mode.json"),
        "--plan-only",
    )
    assert no_mode.returncode == 2
    assert "--historical-reproduction" in no_mode.stderr

    current_output = tmp_path / f"{skill_name}-current.json"
    current = _invoke(
        script,
        "--model",
        CURRENT_MODEL,
        "--output",
        str(current_output),
        "--plan-only",
    )
    assert current.returncode == 0, current.stdout + current.stderr
    current_receipt = json.loads(current.stdout)
    assert current_receipt["mode"] == "current_model"
    assert current_receipt["requested_model"] == CURRENT_MODEL
    assert current_receipt["effective_model"] == "<unavailable>"
    assert current_receipt["provider"] == "<unavailable>"
    assert current_receipt["refusal_detected"] == "<unavailable>"
    assert current_receipt["truncation_detected"] == "<unavailable>"
    assert current_receipt["stop_outcomes"] == "<unavailable>"
    assert current_receipt["qualification_status"] == "UNVERIFIED"
    assert current_receipt["output_path"] == str(current_output.resolve())
    assert current_receipt["frozen_baseline"]["date"] == "2026-05-31"
    assert current_receipt["frozen_baseline"]["model"] == HISTORICAL_MODEL
    assert not current_output.exists(), "plan-only must not create measurement output"

    old_as_current = _invoke(
        script,
        "--model",
        HISTORICAL_MODEL,
        "--output",
        str(tmp_path / f"{skill_name}-mislabelled.json"),
        "--plan-only",
    )
    assert old_as_current.returncode == 2
    assert "historical" in old_as_current.stderr.lower()

    historical_output = tmp_path / f"{skill_name}-historical.json"
    historical = _invoke(
        script,
        "--historical-reproduction",
        "--output",
        str(historical_output),
        "--plan-only",
    )
    assert historical.returncode == 0, historical.stdout + historical.stderr
    historical_receipt = json.loads(historical.stdout)
    assert historical_receipt["mode"] == "historical_reproduction"
    assert historical_receipt["requested_model"] == HISTORICAL_MODEL
    assert not historical_output.exists()

    frozen_target = _invoke(
        script,
        "--historical-reproduction",
        "--output",
        str(frozen),
        "--plan-only",
    )
    assert frozen_target.returncode == 2
    assert "immutable" in frozen_target.stderr.lower()

    assert frozen.read_bytes() == frozen_before
    assert {
        path.relative_to(harness).as_posix(): path.read_bytes()
        for path in sorted((harness / "runs").glob("*"))
        if path.is_file()
    } == runs_before


@pytest.mark.parametrize("skill_name", HARNESSES)
@pytest.mark.parametrize("model", COVERED_MODELS)
def test_covered_current_models_require_explicit_retention_approval(
    skill_name: str, model: str, tmp_path: Path
) -> None:
    script = ROOT / "skills" / skill_name / "harness" / "run_live.py"
    output = tmp_path / f"{skill_name}-{model}.json"

    rejected = _invoke(
        script, "--model", model, "--output", str(output)
    )
    assert rejected.returncode == 2
    assert "30-day retention" in rejected.stderr

    approved = _invoke(
        script,
        "--model",
        model,
        "--approve-covered-model-retention",
        "--output",
        str(output),
        "--plan-only",
    )
    assert approved.returncode == 0, approved.stdout + approved.stderr
    receipt = json.loads(approved.stdout)
    assert receipt["requested_model"] == model
    assert receipt["qualification_status"] == "UNVERIFIED"
    assert receipt["covered_model_retention_required"] is True
    assert receipt["covered_model_retention_approved"] is True
    assert not output.exists()


@pytest.mark.parametrize("skill_name", HARNESSES)
@pytest.mark.parametrize("historical", (False, True))
def test_fake_qualified_runtime_writes_explicit_output_with_nested_receipt(
    skill_name: str, historical: bool, tmp_path: Path
) -> None:
    completed, output = _fake_runtime(skill_name, tmp_path, historical=historical)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.is_file(), "bounded smoke runs must write their explicit output"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "execution_receipt" not in payload
    receipt = payload["runtime_receipt"]
    expected_model = HISTORICAL_MODEL if historical else CURRENT_MODEL
    assert payload["model"] == expected_model
    assert receipt["qualification_status"] == "QUALIFIED"
    assert receipt["requested_model"] == expected_model
    assert receipt["effective_model"] == expected_model
    expected_provider = "anthropic-api" if skill_name == "deep-dive" else "anthropic"
    assert receipt["provider"] == expected_provider
    assert receipt["refusal_detected"] is False
    assert receipt["truncation_detected"] is False
    assert receipt["stop_outcomes"]["end_turn"] > 0


@pytest.mark.parametrize("skill_name", HARNESSES)
@pytest.mark.parametrize(
    ("fake_env", "failure_fragment"),
    (
        ({"FAKE_RESPONSE_MODEL": "<missing>"}, "missing effective model"),
        ({"FAKE_RESPONSE_MODEL": "claude-sonnet-5"}, "model mismatch"),
        ({"FAKE_STOP_REASON": "<missing>"}, "missing stop reason"),
        ({"FAKE_STOP_REASON": "max_tokens"}, "truncation"),
        ({"FAKE_STOP_REASON": "refusal", "FAKE_REFUSAL": "1"}, "refusal"),
        ({"FAKE_STOP_REASON": "stop_sequence"}, "invalid terminal stop outcome"),
    ),
)
def test_runtime_evidence_mutations_fail_closed_without_measurement_output(
    skill_name: str,
    fake_env: dict[str, str],
    failure_fragment: str,
    tmp_path: Path,
) -> None:
    completed, output = _fake_runtime(skill_name, tmp_path, **fake_env)
    assert completed.returncode == 2
    assert failure_fragment in completed.stderr.lower()
    assert not output.exists()
