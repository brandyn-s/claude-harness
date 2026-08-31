"""Tests for bin/effective-model.py.

Every test runs against a captured probe envelope. The real probe costs ~$2 per
invocation (96,272 cache-creation tokens for a two-token prompt), so a suite
that called it would be both slow and expensive -- and the field names it
returns are exactly what the fixtures pin.

The fixture below is a real 2026-08-29 envelope, trimmed to the fields the tool
reads.
"""
import importlib.util
import json
from pathlib import Path

BIN = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("effective_model", BIN / "effective-model.py")
assert spec and spec.loader
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)


HEALTHY = {
    "type": "result",
    "total_cost_usd": 2.118336,
    "fast_mode_state": "off",
    "modelUsage": {
        "claude-fable-5": {
            "canonicalModel": "claude-fable-5",
            "provider": "firstParty",
            "contextWindow": 1000000,
            "maxOutputTokens": 64000,
            "costUSD": 2.118336,
        }
    },
}


def test_effective_reads_real_field_names():
    got = em.effective(HEALTHY)
    assert got == [{
        "model": "claude-fable-5",
        "provider": "firstParty",
        "context_window": 1000000,
        "max_output_tokens": 64000,
        "cost_usd": 2.118336,
    }]


def test_effective_returns_every_model_not_just_one():
    """A fallback makes two models appear; collapsing to one hides the event."""
    two = json.loads(json.dumps(HEALTHY))
    two["modelUsage"]["claude-opus-5"] = {
        "canonicalModel": "claude-opus-5", "provider": "firstParty",
        "contextWindow": 1000000, "maxOutputTokens": 64000, "costUSD": 0.1,
    }
    assert {m["model"] for m in em.effective(two)} == {"claude-fable-5", "claude-opus-5"}


def test_no_findings_when_config_matches():
    cfg = {"settings_model": "claude-fable-5[1m]", "settings_fallback": None, "env": {}}
    assert em.findings(em.effective(HEALTHY), cfg) == []


def test_flags_bedrock_profile_id_on_first_party_session():
    """The motivating defect: a valid Bedrock id is an invalid first-party one."""
    cfg = {"settings_model": "us.anthropic.claude-fable-5",
           "settings_fallback": None, "env": {}}
    notes = em.findings(em.effective(HEALTHY), cfg)
    assert any("INVALID on this first-party session" in n for n in notes), notes


def test_flags_provider_prefix_in_fallback_and_env():
    cfg = {
        "settings_model": "claude-fable-5[1m]",
        "settings_fallback": ["us-gov.anthropic.claude-opus-5"],
        "env": {"settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL": "arn:aws:bedrock:x"},
    }
    notes = em.findings(em.effective(HEALTHY), cfg)
    assert any("fallbackModel[0]" in n for n in notes), notes
    assert any("ANTHROPIC_DEFAULT_OPUS_MODEL" in n for n in notes), notes


def test_detects_silent_fallback():
    """Configured one model, a different one served the request."""
    served = json.loads(json.dumps(HEALTHY))
    served["modelUsage"] = {"claude-opus-5": {
        "canonicalModel": "claude-opus-5", "provider": "firstParty",
        "contextWindow": 1000000, "maxOutputTokens": 64000, "costUSD": 1.0}}
    cfg = {"settings_model": "claude-fable-5[1m]", "settings_fallback": None, "env": {}}
    notes = em.findings(em.effective(served), cfg)
    assert any("silent fallback" in n for n in notes), notes


def test_detects_missing_1m_suffix_by_window():
    """The [1m] suffix is load-bearing; its absence shows up as the window."""
    small = json.loads(json.dumps(HEALTHY))
    small["modelUsage"]["claude-fable-5"]["contextWindow"] = 200000
    cfg = {"settings_model": "claude-fable-5", "settings_fallback": None, "env": {}}
    notes = em.findings(em.effective(small), cfg)
    assert any("load-bearing" in n for n in notes), notes


def test_empty_model_usage_is_unknown_not_clean():
    """No modelUsage must not read as a healthy result."""
    assert em.effective({"modelUsage": {}}) == []
    assert em.effective({}) == []
