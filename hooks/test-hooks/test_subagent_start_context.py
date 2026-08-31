"""Tests for subagent-start-context.py (SubagentStart)."""
from conftest import run_hook

HOOK = "subagent-start-context.py"


def test_with_topic_load():
    """Prompt with 'Load topics:' should exit 0 without error."""
    rc, out, err = run_hook(HOOK, {
        "prompt": "Load topics: crowdstrike.md, ramp.md\nDo some work."
    })
    assert rc == 0


def test_no_topic_instruction():
    rc, out, err = run_hook(HOOK, {"prompt": "Just do some work"})
    assert rc == 0


def test_empty_prompt():
    rc, out, err = run_hook(HOOK, {"prompt": ""})
    assert rc == 0


def test_empty_input():
    rc, out, err = run_hook(HOOK, {})
    assert rc == 0

# ---------------------------------------------------------------------------
# The four tests above assert only rc == 0. They would pass with NOTHING ever
# injected -- which is exactly how a silent delivery failure survives. These pin
# the DELIVERY of the child-side reporting contract, relocated out of ambient
# rules/ on 2026-08-26 (-7,015 B) and now the hook's responsibility.
# ---------------------------------------------------------------------------
import json
from pathlib import Path

CONTRACT_MARKER = "SUBAGENT REPORTING CONTRACT"
BUDGET_NOTICE = "NOT DELIVERED"


def _context(out: str) -> str:
    """The injected additionalContext, or '' when the hook emitted nothing."""
    if not out.strip():
        return ""
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_contract_is_delivered_when_the_prompt_names_no_topics():
    """The regression this guards: the hook used to `sys.exit(0)` before building
    anything when no topics were named -- the COMMON dispatch shape. Building the
    contract below that return would have shipped it only to topic-carrying
    dispatches, a silent partial rollout."""
    rc, out, _ = run_hook(HOOK, {"prompt": "Just do some work"})
    assert rc == 0
    ctx = _context(out)
    assert CONTRACT_MARKER in ctx, "contract not delivered on a no-topics dispatch"
    assert "INSUFFICIENT_CONTEXT" in ctx
    assert "GUARD pattern=" in ctx


def test_contract_is_delivered_alongside_topics_and_comes_first():
    """Ordering matters: budget eviction takes from the END, so the contract must
    open the payload. A dropped topic leaves an actionable pointer; a dropped
    contract leaves the agent unaware there was one.

    The topic is DISCOVERED at runtime rather than hard-coded -- the hook reads the
    deployed topics dir, whose contents vary by host (recent-sessions.md, which the
    hook special-cases, does not exist on this one)."""
    topics_dir = Path.home() / ".claude" / "agent-memory" / "topics"
    small = sorted(
        (p for p in topics_dir.glob("*.md") if 0 < p.stat().st_size < 3_000),
        key=lambda p: p.stat().st_size,
    )
    if not small:
        import pytest
        pytest.skip("no small deployed topic available to pair with the contract")
    topic = small[0].name

    rc, out, _ = run_hook(HOOK, {"prompt": f"Load topics: {topic}\nDo some work."})
    assert rc == 0
    ctx = _context(out)
    assert CONTRACT_MARKER in ctx
    assert ctx.startswith("--- subagent-tool-discipline.md (REQUIRED) ---"), ctx[:120]
    topic_header = f"--- {topic} ---"
    assert topic_header in ctx, f"{topic} was not injected at all"
    assert ctx.index(CONTRACT_MARKER) < ctx.index(topic_header)


def test_over_budget_topic_is_dropped_loudly_and_the_contract_survives():
    """An over-budget injection is silently replaced by the platform with a ~2KB
    preview, so it must be refused explicitly instead. The fixture verifies its OWN
    precondition: if the chosen topic is no longer over budget, this fails loudly
    rather than passing vacuously."""
    hook_src = (Path(__file__).resolve().parents[1]
                / "subagent-start-context.py").read_text(encoding="utf-8")
    import re
    budget = int(re.search(r"INJECTION_BUDGET_CHARS\s*=\s*([\d_]+)",
                           hook_src).group(1).replace("_", ""))
    big = Path.home() / ".claude" / "agent-memory" / "topics" / "github.md"
    if not big.exists():
        import pytest
        pytest.skip("no oversized topic available to construct the known-positive")
    assert len(big.read_text(encoding="utf-8", errors="replace")) > budget, (
        "PRECONDITION GONE: the fixture topic is no longer over budget, so this test "
        "can no longer exercise eviction. Pick a larger topic."
    )

    rc, out, _ = run_hook(HOOK, {"prompt": "Load topics: github.md\nWork."})
    assert rc == 0
    ctx = _context(out)
    assert len(ctx) <= budget, (len(ctx), budget)
    assert CONTRACT_MARKER in ctx, "the contract must survive eviction"
    assert BUDGET_NOTICE in ctx, "an evicted section must say so, not vanish"
    assert "github.md" in ctx, "the notice must name the file that was dropped"
    # Never truncate a section mid-way: a partial topic reads as complete.
    assert "--- github.md ---" not in ctx, "topic was included partially"


def test_hook_survives_a_missing_contract_file():
    """Delivery is best-effort: a missing contract must not block a dispatch."""
    rc, out, _ = run_hook(HOOK, {"prompt": "Load topics: recent-sessions.md\nWork."})
    assert rc == 0
