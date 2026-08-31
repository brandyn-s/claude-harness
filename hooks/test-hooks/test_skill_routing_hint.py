"""Regression tests for skill-routing-hint.py routing patterns."""
import pytest
import json
from conftest import run_hook

HOOK = "skill-routing-hint.py"


def _get_skill(stdout):
    if not stdout.strip():
        return None
    try:
        msg = json.loads(stdout.strip()).get("systemMessage", "")
        if "Skill: /" in msg:
            return msg.split("Skill: /")[1].split(" ")[0]
    except (json.JSONDecodeError, IndexError):
        pass
    return None


def test_refine_improve_prompt():
    rc, out, _ = run_hook(HOOK, {"prompt": "I need to improve this prompt before running it against production"})
    assert _get_skill(out) == "refine"


def test_refine_what_am_i_missing():
    rc, out, _ = run_hook(HOOK, {"prompt": "What am I missing in this analysis request?"})
    assert _get_skill(out) == "refine"


def test_refine_before_execute():
    rc, out, _ = run_hook(HOOK, {"prompt": "Refine this before we execute the migration plan"})
    assert _get_skill(out) == "refine"


def test_refine_before_we_start():
    rc, out, _ = run_hook(HOOK, {"prompt": "Before we start the security review, what should I include?"})
    assert _get_skill(out) == "refine"


def test_refine_help_prepare():
    rc, out, _ = run_hook(HOOK, {"prompt": "Help me prepare for the deployment review meeting"})
    assert _get_skill(out) == "refine"


def test_superplan_plan_how():
    rc, out, _ = run_hook(HOOK, {"prompt": "Plan how to migrate our CrowdStrike alerts to the new API version"})
    assert _get_skill(out) == "superplan"


def test_superplan_how_should_build():
    rc, out, _ = run_hook(HOOK, {"prompt": "How should we build the new compliance dashboard?"})
    assert _get_skill(out) == "superplan"


def test_no_match_simple_query():
    rc, out, _ = run_hook(HOOK, {"prompt": "How many open CrowdStrike detections do we have right now?"})
    skill = _get_skill(out)
    assert skill not in ("refine", "brainstorm", "superplan")


def test_no_match_short_prompt():
    rc, out, _ = run_hook(HOOK, {"prompt": "yes"})
    assert _get_skill(out) is None


@pytest.mark.skip(reason="not shipped in this export: openai-monitor")
def test_openai_monitor_routes_provider_specific_health():
    _rc, out, _ = run_hook(
        HOOK,
        {"prompt": "Check OpenAI Monitor health and coverage for the previous UTC day"},
    )
    assert _get_skill(out) == "openai-monitor"


@pytest.mark.skip(reason="not shipped in this export: openai-monitor")
def test_openai_monitor_routes_platform_audit_without_fanout():
    _rc, out, _ = run_hook(
        HOOK,
        {"prompt": "Find the OpenAI Platform audit event that changed project access yesterday"},
    )
    assert _get_skill(out) == "openai-monitor"


@pytest.mark.skip(reason="not shipped in this export: enterprise-ai-monitor")
def test_enterprise_monitor_wins_for_cross_provider_health():
    _rc, out, _ = run_hook(
        HOOK,
        {"prompt": "Compare Claude Monitor and ChatGPT Monitor health for yesterday"},
    )
    assert _get_skill(out) == "enterprise-ai-monitor"


@pytest.mark.skip(reason="not shipped in this export: cc-monitor")
def test_claude_only_monitoring_stays_with_cc_monitor():
    _rc, out, _ = run_hook(
        HOOK,
        {"prompt": "Show Claude spend and usage by workspace for the previous UTC day"},
    )
    assert _get_skill(out) == "cc-monitor"


def test_openai_vendor_update_does_not_route_to_monitor():
    _rc, out, _ = run_hook(
        HOOK,
        {"prompt": "What is new in the OpenAI changelog and product updates this month?"},
    )
    assert _get_skill(out) == "gather-vendor"


def test_liveness_warning_absent_for_healthy_skill():
    """A routed skill with all its script refs present should NOT get a LIVENESS warning."""
    rc, out, _ = run_hook(
        HOOK,
        {"prompt": "Plan how to migrate our CrowdStrike alerts to the new API version"},
    )
    if out.strip():
        msg = json.loads(out.strip()).get("systemMessage", "")
        assert "LIVENESS WARNING" not in msg, (
            f"Superplan is a healthy skill; should not have liveness warning. Got: {msg}"
        )
