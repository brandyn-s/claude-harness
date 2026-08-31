"""Regression contracts for active Claude model guidance.

These tests intentionally inspect only active policy surfaces. Frozen examples and
measurement fixtures may retain the model names that produced their evidence.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _load_validator():
    path = ROOT / "scripts" / "validate-skills.py"
    spec = importlib.util.spec_from_file_location("validate_skills_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture_skill(path: Path, code: str) -> Path:
    path.mkdir()
    (path / "SKILL.md").write_text(
        """---
name: fixture-skill
description: "Use when reviewing a fixture. Do NOT use for production."
---

## Step 1

### Example 1

```python
"""
        + code
        + "\n```\n",
        encoding="utf-8",
    )
    return path


def test_api_guardrails_names_current_models_and_runtime_outcomes():
    text = _read("skills/api-guardrails/SKILL.md")
    lower = text.lower()

    for model_id in (
        "claude-fable-5",
        "claude-mythos-5",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
    ):
        assert model_id in text
    for contract in (
        "stop_reason",
        "stop_details",
        "fallback",
        "30-day data retention",
        "adaptive thinking",
        "output_config",
        "assistant-message prefills",
    ):
        assert contract in lower

    assert "Chain-of-thought verification" not in text
    assert "claude-opus-4-7" not in text


def test_validator_scopes_api_controls_to_the_effective_model(tmp_path):
    validator = _load_validator()
    current = _write_fixture_skill(
        tmp_path / "current",
        'client.messages.create(model="claude-opus-5", temperature=0.2)',
    )
    older = _write_fixture_skill(
        tmp_path / "older",
        'client.messages.create(model="claude-haiku-4-5", temperature=0.2)',
    )

    current_checks, current_notes = validator.score_skill(current)
    older_checks, _older_notes = validator.score_skill(older)

    assert current_checks["E1_no_deprecated_api"] is False
    assert "sampling parameters" in current_notes["E1"]
    assert older_checks["E1_no_deprecated_api"] is True


def test_validator_catches_quoted_json_current_model_controls(tmp_path):
    validator = _load_validator()
    cases = {
        "sampling": (
            '{"model":"claude-opus-5","temperature":0.2}',
            "sampling parameters",
        ),
        "manual-thinking": (
            '{"model":"claude-opus-5","thinking":{"type":"enabled"}}',
            "manual extended thinking",
        ),
        "fable-disabled": (
            '{"model":"claude-fable-5","thinking":{"type":"disabled"}}',
            "disabled thinking on Claude Fable 5",
        ),
        "opus-xhigh-disabled": (
            '{"model":"claude-opus-5","thinking":{"type":"disabled"},'
            '"output_config":{"effort":"xhigh"}}',
            "disabled thinking with xhigh/max effort",
        ),
        "mythos-disabled": (
            '{"model":"claude-mythos-5","thinking":{"type":"disabled"}}',
            "disabled thinking on Claude Mythos 5",
        ),
        "assistant-prefill": (
            '{"model":"claude-sonnet-5","messages":['
            '{"role":"user","content":"Question"},'
            '{"role":"assistant","content":"Answer:"}]}',
            "assistant-message prefill",
        ),
    }

    for name, (code, expected) in cases.items():
        skill = _write_fixture_skill(tmp_path / name, code)
        checks, notes = validator.score_skill(skill)
        assert checks["E1_no_deprecated_api"] is False
        assert expected in notes["E1"]


def test_validator_binds_controls_to_each_anthropic_request(tmp_path):
    validator = _load_validator()
    skill = _write_fixture_skill(
        tmp_path / "separate-branches",
        '''client.messages.create(
    model="claude-opus-5",
    output_config={"effort": "high"},
)
client.messages.create(
    model="claude-haiku-4-5",
    temperature=0.2,
)''',
    )

    checks, notes = validator.score_skill(skill)

    assert checks["E1_no_deprecated_api"] is True, notes.get("E1")


def test_validator_fails_closed_on_dynamic_anthropic_model_controls(tmp_path):
    validator = _load_validator()
    skill = _write_fixture_skill(
        tmp_path / "dynamic-model",
        '''client.messages.create(
    model=os.environ["ANTHROPIC_MODEL"],
    temperature=0.2,
)''',
    )

    checks, notes = validator.score_skill(skill)

    assert checks["E1_no_deprecated_api"] is False
    assert "unresolved Anthropic model" in notes["E1"]


def test_validator_expands_literal_kwargs_and_respects_assignment_order(tmp_path):
    validator = _load_validator()
    kwargs_skill = _write_fixture_skill(
        tmp_path / "kwargs-payload",
        '''payload = {"model": "claude-opus-5", "temperature": 0.2}
client.messages.create(**payload)''',
    )
    reassigned_skill = _write_fixture_skill(
        tmp_path / "reassigned-model",
        '''model = "claude-opus-5"
client.messages.create(model=model, temperature=0.2)
model = "claude-haiku-4-5"''',
    )

    for skill in (kwargs_skill, reassigned_skill):
        checks, notes = validator.score_skill(skill)
        assert checks["E1_no_deprecated_api"] is False
        assert "sampling parameters" in notes["E1"]


def test_validator_covers_supported_opus_4_restrictions_and_raw_http(tmp_path):
    validator = _load_validator()
    cases = {
        "opus-4-7": (
            'client.messages.create(model="claude-opus-4-7", temperature=0.2)',
            "sampling parameters",
        ),
        "opus-4-8-prefill": (
            'client.messages.create(model="claude-opus-4-8", '
            'messages=[{"role":"assistant","content":"Answer:"}])',
            "assistant-message prefill",
        ),
        "raw-http": (
            'payload = {"model": "claude-opus-5", "temperature": 0.2}\n'
            'requests.post("https://api.anthropic.com/v1/messages", json=payload)',
            "sampling parameters",
        ),
        "composed-raw-http": (
            'base = "https://api.anthropic.com"\n'
            'payload = {"model": "claude-opus-5", "temperature": 0.2}\n'
            'requests.post(base + "/v1/messages", json=payload)',
            "sampling parameters",
        ),
        "formatted-raw-http": (
            'base = "https://api.anthropic.com"\n'
            'payload = {"model": "claude-opus-5", "temperature": 0.2}\n'
            'requests.post(f"{base}/v1/messages", json=payload)',
            "sampling parameters",
        ),
    }

    for name, (code, expected) in cases.items():
        skill = _write_fixture_skill(tmp_path / name, code)
        checks, notes = validator.score_skill(skill)
        assert checks["E1_no_deprecated_api"] is False
        assert expected in notes["E1"]


def test_compaction_marker_requires_actionable_recovery_language(tmp_path):
    validator = _load_validator()
    skill = _write_fixture_skill(
        tmp_path / "marker-only",
        "# **Compaction continuity:** arbitrary words are not recovery",
    )
    skill_md = skill / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8") + ("\nlong body" * 5000),
        encoding="utf-8",
    )

    checks, notes = validator.score_skill(skill)

    assert checks["C1b_token_budget"] is False
    assert "missing actionable" in notes["C1b"]


def test_skill_invocation_fields_are_orthogonal_official_controls():
    text = _read("rules/skill-standards.md")

    assert "`disable-model-invocation: true`: user-only" in text
    assert "`user-invocable: false`: model-only" in text
    assert "independent controls" in text
    assert "`low`, `medium`, `high`, `xhigh`, `max`" in text
    assert "1,536-character listing cap" in text
    for field in (
        "`when_to_use`",
        "`arguments`",
        "`disallowed-tools`",
        "`background`",
        "`metadata`",
        "`license`",
    ):
        assert field in text

    assert "Official equivalent" not in text
    assert "Our custom field - hides from system prompt" not in text
    assert "Opus 4.6 only" not in text


def test_roundtable_active_contract_is_current_and_historical_evidence_is_labeled():
    skill = _read("skills/roundtable/SKILL.md")
    skill_words = " ".join(skill.split())
    manifest = _read("skills/roundtable/manifest.yaml")
    harness = _read("skills/roundtable/scripts/harness.py")
    synthesize = _read("skills/roundtable/scripts/synthesize.py")
    judge_runner = _read("skills/roundtable/scripts/jrh_harness.py")

    assert "../_shared/model-runtime-policy.md" in skill
    assert "claude-fable-5" in skill
    assert "claude-opus-5" in skill  # documented refusal-fallback arm
    assert "ROUNDTABLE_ANTHROPIC_MODEL" in skill
    assert "ROUNDTABLE_ANTHROPIC_EFFORT" in skill
    # The per-run retention env gate was retired 2026-08-19 (org 30-day
    # retention confirmed; Fable is the default arm). The skill must still
    # document the retention requirement itself.
    assert "ROUNDTABLE_COVERED_MODEL_RETENTION_APPROVED=1" not in skill
    assert "30-day data retention" in skill
    assert "stop_reason: refusal" in skill
    assert "requested and effective model" in skill_words

    for active in (skill, manifest, harness, synthesize, judge_runner):
        assert "Opus 4.8" not in active
        assert "claude-opus-4-8" not in active
        assert "Opus 4.7" not in active
        assert "grok-4.20" not in active
        assert "gpt-5.5-pro" not in active

    assert '"opus": {"in": 10.0, "out": 50.0}' in harness
    assert '"grok": {"in": 2.0, "out": 6.0}' in harness
    assert '"gpt": {"in": 5.0, "out": 30.0}' in harness
    assert "anthropic_adapter.resolve_model()" in judge_runner
    assert "2-5, default 5" in manifest

    for historical_path in (
        "skills/roundtable/references/jrh-fixture/JUDGE_CARD.md",
        "skills/roundtable/references/cost-tradeoffs.md",
        "skills/roundtable/examples/persona-skill-review.md",
    ):
        historical = _read(historical_path)
        assert "Historical evidence" in historical
