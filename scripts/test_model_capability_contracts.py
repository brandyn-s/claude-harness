"""Regression contracts for active Claude model guidance.

These tests intentionally inspect only active policy surfaces. Frozen examples and
measurement fixtures may retain the model names that produced their evidence.

Model ids and per-model facts come from contracts/model-capabilities.json (through
scripts/model_contracts.py): the same source skills/api-guardrails renders and
scripts/validate-skills.py enforces, so a model rollover changes one file.
"""

import importlib.util
from pathlib import Path

from scripts import model_contracts as ids

ROOT = ids.ROOT
CONTRACT = ids.capabilities()
CURRENT = ids.current_models()
SUPERSEDED = ids.superseded_models()
LEVELS = CONTRACT["effort_levels"]


def _first(rows, predicate):
    return next(m for m in rows if predicate(m))


SAMPLING_REJECTED = _first(CURRENT, lambda m: m["sampling"] == "rejected")
SAMPLING_ALLOWED = _first(CURRENT, lambda m: m["sampling"] != "rejected")  # the older-generation control
PREFILL_REJECTED = _first(CURRENT, lambda m: not m["assistant_prefill"])
ALWAYS_THINKING = [m for m in CURRENT if m["thinking"]["adaptive"] == "always_on"]
DISABLE_CAPPED = _first(CURRENT, lambda m: m["thinking"]["disable"]["max_effort"])
ABOVE_CAP = LEVELS[LEVELS.index(DISABLE_CAPPED["thinking"]["disable"]["max_effort"]) + 1:]


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

    for model_id in ids.current_ids():
        assert model_id in text
    for contract in (
        "stop_reason",
        "stop_details",
        "fallback",
        "30-day data retention",
        "adaptive thinking",
        "output_config",
        "assistant-message prefill",
    ):
        assert contract in lower

    assert "Chain-of-thought verification" not in text
    for model_id in ids.superseded_ids():
        assert not ids.names(text, model_id), "superseded models are frozen evidence, not current guidance"


def test_names_matches_whole_model_tokens_only():
    """The superseded-id checks below must not fire on a successor that extends the id."""
    assert not ids.names("pin claude-fable-5-1 here", "claude-fable-5")
    assert not ids.names("Claude Fable 5.1 replaces it", "Fable 5")
    assert ids.names("pin claude-fable-5 here", "claude-fable-5")
    assert ids.names("ends with claude-fable-5.", "claude-fable-5")
    assert ids.names("us.anthropic.claude-fable-5[1m]", "claude-fable-5")
    assert ids.names("Fable 5 has thinking always on", "Fable 5")
    assert not ids.names("claude-opus-4-80", "claude-opus-4-8")


def test_validator_reads_its_model_facts_from_the_contract():
    """scripts/validate-skills.py used to keep its own frozensets of restricted models;
    they now derive from the contract, so the two cannot disagree."""
    validator = _load_validator()
    rows = CURRENT + SUPERSEDED

    assert validator.RESTRICTED_API_MODEL_IDS == {
        m["id"] for m in rows
        if m["sampling"] == "rejected" or not m["assistant_prefill"]
        or not m["thinking"]["manual_budget_tokens"]
    }
    assert validator.ALWAYS_THINKING_MODEL_IDS == {
        m["id"] for m in rows if m["thinking"]["adaptive"] == "always_on"
    }
    assert validator.DISABLED_THINKING_EFFORT_CAP == {
        m["id"]: m["thinking"]["disable"]["max_effort"]
        for m in rows if m["thinking"]["disable"]["allowed"] and m["thinking"]["disable"]["max_effort"]
    }
    assert SAMPLING_ALLOWED["id"] not in validator.RESTRICTED_API_MODEL_IDS


def test_validator_scopes_api_controls_to_the_effective_model(tmp_path):
    validator = _load_validator()
    current = _write_fixture_skill(
        tmp_path / "current",
        f'client.messages.create(model="{SAMPLING_REJECTED["id"]}", temperature=0.2)',
    )
    older = _write_fixture_skill(
        tmp_path / "older",
        f'client.messages.create(model="{SAMPLING_ALLOWED["id"]}", temperature=0.2)',
    )

    current_checks, current_notes = validator.score_skill(current)
    older_checks, _older_notes = validator.score_skill(older)

    assert current_checks["E1_no_deprecated_api"] is False
    assert "sampling parameters" in current_notes["E1"]
    assert older_checks["E1_no_deprecated_api"] is True


def test_validator_catches_quoted_json_current_model_controls(tmp_path):
    validator = _load_validator()
    restricted = SAMPLING_REJECTED["id"]
    cases = {
        "sampling": (
            f'{{"model":"{restricted}","temperature":0.2}}',
            "sampling parameters",
        ),
        "manual-thinking": (
            f'{{"model":"{restricted}","thinking":{{"type":"enabled"}}}}',
            "manual extended thinking",
        ),
        "capped-disabled": (
            (f'{{"model":"{DISABLE_CAPPED["id"]}","thinking":{{"type":"disabled"}},'
             f'"output_config":{{"effort":"{ABOVE_CAP[0]}"}}}}'),
            f"disabled thinking with {'/'.join(ABOVE_CAP)} effort",
        ),
        "assistant-prefill": (
            (f'{{"model":"{PREFILL_REJECTED["id"]}","messages":['
             '{"role":"user","content":"Question"},'
             '{"role":"assistant","content":"Answer:"}]}'),
            "assistant-message prefill",
        ),
    }
    for model in ALWAYS_THINKING:
        cases[f"{model['tier']}-disabled"] = (
            f'{{"model":"{model["id"]}","thinking":{{"type":"disabled"}}}}',
            f"disabled thinking on {model['display_name']}",
        )
    assert len(ALWAYS_THINKING) >= 1

    for name, (code, expected) in cases.items():
        skill = _write_fixture_skill(tmp_path / name, code)
        checks, notes = validator.score_skill(skill)
        assert checks["E1_no_deprecated_api"] is False, name
        assert expected in notes["E1"], name


def test_validator_binds_controls_to_each_anthropic_request(tmp_path):
    validator = _load_validator()
    skill = _write_fixture_skill(
        tmp_path / "separate-branches",
        f'''client.messages.create(
    model="{SAMPLING_REJECTED["id"]}",
    output_config={{"effort": "high"}},
)
client.messages.create(
    model="{SAMPLING_ALLOWED["id"]}",
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
        f'''payload = {{"model": "{SAMPLING_REJECTED["id"]}", "temperature": 0.2}}
client.messages.create(**payload)''',
    )
    reassigned_skill = _write_fixture_skill(
        tmp_path / "reassigned-model",
        f'''model = "{SAMPLING_REJECTED["id"]}"
client.messages.create(model=model, temperature=0.2)
model = "{SAMPLING_ALLOWED["id"]}"''',
    )

    for skill in (kwargs_skill, reassigned_skill):
        checks, notes = validator.score_skill(skill)
        assert checks["E1_no_deprecated_api"] is False
        assert "sampling parameters" in notes["E1"]


def test_validator_covers_superseded_model_restrictions_and_raw_http(tmp_path):
    validator = _load_validator()
    restricted = SAMPLING_REJECTED["id"]
    payload = f'payload = {{"model": "{restricted}", "temperature": 0.2}}\n'
    cases = {
        "raw-http": (
            payload + 'requests.post("https://api.anthropic.com/v1/messages", json=payload)',
            "sampling parameters",
        ),
        "composed-raw-http": (
            'base = "https://api.anthropic.com"\n' + payload + 'requests.post(base + "/v1/messages", json=payload)',
            "sampling parameters",
        ),
        "formatted-raw-http": (
            'base = "https://api.anthropic.com"\n' + payload + 'requests.post(f"{base}/v1/messages", json=payload)',
            "sampling parameters",
        ),
    }
    # Superseded rows carry the restrictions the validator still enforces for them.
    for row in SUPERSEDED:
        if row["sampling"] == "rejected":
            cases[f"{row['id']}-sampling"] = (
                f'client.messages.create(model="{row["id"]}", temperature=0.2)',
                "sampling parameters",
            )
        if not row["assistant_prefill"]:
            cases[f"{row['id']}-prefill"] = (
                f'client.messages.create(model="{row["id"]}", messages=[{{"role":"assistant","content":"Answer:"}}])',
                "assistant-message prefill",
            )
    assert len(cases) > 3, "the contract lists no superseded restrictions to cover"

    for name, (code, expected) in cases.items():
        skill = _write_fixture_skill(tmp_path / name, code)
        checks, notes = validator.score_skill(skill)
        assert checks["E1_no_deprecated_api"] is False, name
        assert expected in notes["E1"], name


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
    assert ", ".join(f"`{level}`" for level in LEVELS) in text
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
    assert ids.model_id("fable") in skill  # the default arm
    assert ids.model_id("opus") in skill  # documented refusal-fallback arm
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
        for row in SUPERSEDED:
            assert not ids.names(active, row["id"])
            assert not ids.names(active, row["display_name"].removeprefix("Claude "))
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
