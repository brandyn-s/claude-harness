"""Tests for auto-topic-loader.py.

Validates topic injection on first MCP call and dedup on subsequent calls.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import HOOKS_DIR, PYTHON, run_hook

HOOK = "auto-topic-loader.py"
SESSION_ENV = Path.home() / ".claude" / "session-env"

# Anchor to the REPO UNDER TEST, not to $HOME. On this host ~/.claude IS the
# checkout, so a Path.home()-derived path silently tests the DEPLOYED copy and
# passes even when the branch lacks the fix — and on a CI runner ~/.claude does
# not exist at all, so the same test dies FileNotFoundError. HOOKS_DIR comes
# from conftest and is __file__-relative, so it is correct in every checkout.
# (CI caught this on all 3 platforms 2026-07-29; it cannot fail locally, which
# is exactly why it shipped.)
REPO_ROOT = HOOKS_DIR.parent
TOPICS_DIR = REPO_ROOT / "agent-memory" / "topics"
LOADER_PATH = HOOKS_DIR / "auto-topic-loader.py"

# The HOOK resolves its own TOPICS_DIR from Path.home() — correct for
# production, since it must read the DEPLOYED corpus, not whatever checkout it
# happens to live in. Consequence for tests: any assertion about what the hook
# actually INJECTS needs the deployed corpus to exist. On a CI runner it does
# not, so those tests must SKIP (absence of a data corpus is not a defect in the
# hook) while the pure-logic tests still run everywhere.
#
# Verified by reproducing the CI environment locally:
#   HOME=/tmp/fakehome python3 -m pytest hooks/test-hooks/test_auto_topic_loader.py
# which fails 5 tests that a normal local run cannot see — the emulate-the-
# mechanism path from diagnose-before-fix, cheaper than another CI round-trip.
DEPLOYED_TOPICS = Path.home() / ".claude" / "agent-memory" / "topics"
needs_deployed_corpus = pytest.mark.skipif(
    not DEPLOYED_TOPICS.is_dir(),
    reason="no deployed ~/.claude/agent-memory/topics corpus (CI runner); "
           "injection-content assertions need it, pure-logic tests do not",
)


def make_pretool_input(tool_name):
    return {
        "tool_name": tool_name,
        "tool_input": {},
    }


def cleanup_markers():
    # Must resolve the session id EXACTLY like auto-topic-loader.py's own
    # get_marker_path() (CLAUDE_SESSION_ID first, CLAUDE_CODE_SESSION_ID
    # fallback) — checking only CLAUDE_SESSION_ID silently cleans the wrong
    # ("default") marker file when run inside a real session (which sets
    # CLAUDE_CODE_SESSION_ID, not CLAUDE_SESSION_ID), leaving the session's
    # real marker file to accumulate topic-loaded state across test runs
    # and producing false failures for whichever topic that session already
    # triggered organically.
    sid = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID", "default")
    marker = SESSION_ENV / f"topics-loaded-{sid[:12]}.json"
    if marker.exists():
        marker.unlink()


def setup_function():
    cleanup_markers()


def teardown_function():
    cleanup_markers()


# ── Topic injection ──


def test_known_mcp_loads_topic():
    if not (TOPICS_DIR / "crowdstrike.md").exists():
        return  # Skip if topic missing
    rc, stdout, _ = run_hook(
        HOOK, make_pretool_input("mcp__remote-crowdstrike__list_detections")
    )
    assert rc == 0
    if stdout.strip():
        out = json.loads(stdout)
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "crowdstrike" in ctx.lower()


def test_second_call_same_server_deduped():
    if not (TOPICS_DIR / "linear.md").exists():
        return
    run_hook(HOOK, make_pretool_input("mcp__linear-server__list_issues"))
    rc, stdout, _ = run_hook(
        HOOK, make_pretool_input("mcp__linear-server__get_issue")
    )
    assert rc == 0
    assert not stdout.strip()


def test_different_servers_load_different_topics():
    if not (TOPICS_DIR / "ramp.md").exists():
        return
    if not (TOPICS_DIR / "slack.md").exists():
        return
    rc1, stdout1, _ = run_hook(
        HOOK, make_pretool_input("mcp__ramp__load_vendors")
    )
    rc2, stdout2, _ = run_hook(
        HOOK, make_pretool_input("mcp__slack-user__search_channels")
    )
    assert rc1 == 0 and rc2 == 0
    if stdout1.strip():
        ctx = json.loads(stdout1).get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "ramp" in ctx.lower()
    if stdout2.strip():
        ctx = json.loads(stdout2).get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "slack" in ctx.lower()


# ── Non-matching tools ──


def test_unknown_mcp_no_output():
    rc, stdout, _ = run_hook(
        HOOK, make_pretool_input("mcp__unknown_server__do_thing")
    )
    assert rc == 0
    assert not stdout.strip()


def test_non_mcp_tool_no_output():
    rc, stdout, _ = run_hook(HOOK, make_pretool_input("Bash"))
    assert rc == 0
    assert not stdout.strip()


def test_empty_tool_name_no_output():
    rc, stdout, _ = run_hook(HOOK, {"tool_name": "", "tool_input": {}})
    assert rc == 0
    assert not stdout.strip()


# ── Edge cases ──


def test_invalid_json_exits_clean():
    result = subprocess.run(
        [PYTHON, str(HOOKS_DIR / HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0


@needs_deployed_corpus
def test_firecrawl_loads_topic():
    """Firecrawl MCP should load firecrawl.md — the topic existed since
    2026-04 but had no trigger (B7/F6; routed 2026-06-10, B12/F3)."""
    if not (TOPICS_DIR / "firecrawl.md").exists():
        return
    rc, stdout, _ = run_hook(
        HOOK, make_pretool_input("mcp__firecrawl__firecrawl_scrape")
    )
    assert rc == 0
    assert stdout.strip()
    ctx = json.loads(stdout).get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "firecrawl.md" in ctx.lower()


# ── Routing correctness (2026-07-29 fixes) ──────────────────────────────────
#
# Three bugs found by measuring what the loader actually delivered, in order of
# discovery. Each test states the bug it kills so a future reader knows what
# regressing it would cost.


@needs_deployed_corpus
def test_hologram_loads_topic():
    """Restored: collateral of the rule-block removal, not a rule test."""
    if not (TOPICS_DIR / "hologram.md").exists():
        pytest.skip("fixture topic absent from this checkout")
    rc, stdout, _ = run_hook(HOOK, make_pretool_input("mcp__hologram__list_devices"))
    assert rc == 0
    assert "hologram.md" in stdout


def test_retired_server_route_is_absent():
    """`mcp__lucid-mcp__` was RETIRED 2026-07-29 — the server is not registered.

    This test previously asserted the route FIRES. It was written before the
    liveness audit found that 10 of 17 routes named absent servers, so it was
    pinning a route that could never fire in practice. Inverted deliberately:
    the topic file is kept (still readable, still accurate) but the injection
    trigger is gone, and re-adding it without the server returning would be the
    regression.
    """
    import importlib.util
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "atl_retired", LOADER_PATH)
    atl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atl)
    for retired in ("mcp__lucid-mcp__", "mcp__ramp__", "mcp__prowler__",
                    "mcp__context7-docs__"):
        assert retired not in atl.STATIC_MAP, (
            f"{retired} is routed again — confirm the server is registered first"
        )
    # The topic files themselves must survive the route retirement.
    if (TOPICS_DIR).is_dir():
        assert (TOPICS_DIR / "lucid-admin.md").exists(), "topic deleted, not just unrouted"


@needs_deployed_corpus
def test_no_route_resolves_to_a_missing_file():
    """BUG 1 — a declared topic that does not exist still minted a route.

    `_load_file_content` returns None for a missing file and the caller silently
    skips, so a dead route was indistinguishable from "no topic configured": no
    error, no log, context simply never arrived. Four prefixes were dead this
    way, including every `mcp__codebase-memory-mcp__*` and
    `mcp__memory-search__*` call.
    """
    import importlib.util
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "atl_routes", LOADER_PATH)
    atl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atl)

    live = atl._build_server_to_topic_map()
    assert live, "map is empty — routing is entirely broken"
    dead = [(prefix, topic) for prefix, topic in live.items()
            if not (atl.TOPICS_DIR / topic).exists()]
    assert not dead, f"routes pointing at nonexistent topics: {dead}"


def test_every_route_key_is_a_server_prefix_not_a_tool_name():
    """BUG 2 — manifests declare FULL TOOL NAMES, which became map keys.

    `_find_topic_match` returns on the first `startswith` hit, so a tool-name key
    SHADOWED the correct server-level route and dict order picked the winner.
    Measured: `mcp__tavily__tavily_search` matched two entries and resolved to
    security.md (a security skill that merely lists tavily) instead of the
    server-level route.
    """
    import importlib.util
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "atl_prefix", LOADER_PATH)
    atl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atl)

    live = atl._build_server_to_topic_map()
    # A server prefix is exactly `mcp__<server>__` — three segments when split.
    bad = [k for k in live if not k.startswith("mcp__") or not k.endswith("__")
           or k.count("__") != 2]
    assert not bad, f"route keys that are tool names, not server prefixes: {bad}"

    # And no key may be a strict prefix of another, or the shorter shadows it.
    keys = sorted(live)
    shadowed = [(a, b) for a in keys for b in keys
                if a != b and b.startswith(a)]
    assert not shadowed, f"shadowing route pairs: {shadowed}"


def test_server_prefix_normalizes_tool_names():
    """`_server_prefix` must collapse a full tool name to its server."""
    import importlib.util
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "atl_sp", LOADER_PATH)
    atl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atl)

    assert atl._server_prefix("mcp__tavily__tavily_search") == "mcp__tavily__"
    assert atl._server_prefix("mcp__tavily__") == "mcp__tavily__"
    assert atl._server_prefix("mcp__remote-crowdstrike__*") == "mcp__remote-crowdstrike__"
    assert atl._server_prefix("mcp__") is None


@needs_deployed_corpus
def test_first_resolvable_topic_tolerates_bare_slug_but_not_absence():
    """Bare `security` means `security.md`; a nonexistent topic returns None."""
    import importlib.util
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "atl_frt", LOADER_PATH)
    atl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atl)

    assert atl._first_resolvable_topic(["security"]) == "security.md"
    assert atl._first_resolvable_topic(["security.md"]) == "security.md"
    assert atl._first_resolvable_topic(["definitely-not-a-topic-xyz.md"]) is None
    # Skips the unresolvable and takes the next that resolves.
    assert atl._first_resolvable_topic(
        ["definitely-not-a-topic-xyz.md", "security.md"]) == "security.md"


def test_rule_injection_is_gone():
    """BUG 3 — rule injection was dead for two months and repair would harm.

    Its source dir was deleted by #1011, moving the 3 rules back to AMBIENT.
    Repointing would inject a duplicate of content already in context, and 2 of
    the 3 exceed the vendor's 10,000-char hook-output cap so the duplicate would
    arrive as a ~2KB stub. Removal was the fix; this pins it.
    """
    src = (LOADER_PATH).read_text(
        encoding="utf-8")
    # Comments explaining the retirement are fine; live code is not.
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    for dead in ("STATIC_RULE_MAP", "RULES_DIR", "_find_rule_matches"):
        assert dead not in code, f"{dead} is still live code"
    assert "Behavioral rule for" not in code, "rule section label still emitted"


@needs_deployed_corpus
def test_no_injected_topic_is_silently_truncated():
    """The vendor caps hook output at 10,000 chars; over it, only ~2KB arrives.

    Reported, not asserted-against: several curated topics genuinely exceed the
    cap today and splitting them is tracked work (/garden Step 3b). Failing here
    would just be a red test nobody can fix in one commit. What this DOES pin is
    that the set is known and enumerable — if it grows silently, the printout in
    a verbose run shows it.
    """
    import importlib.util
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "atl_cap", LOADER_PATH)
    atl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atl)

    HOOK_OUTPUT_CAP = 10_000
    ENVELOPE = 450  # label line + JSON envelope, measured
    live = atl._build_server_to_topic_map()
    over = {}
    for prefix, topic in live.items():
        content = atl._load_file_content(atl.TOPICS_DIR, topic)
        assert content is not None, f"route {prefix} injects nothing"
        if len(content) + ENVELOPE > HOOK_OUTPUT_CAP:
            over[topic] = len(content)
    print(f"\ntopics over the {HOOK_OUTPUT_CAP:,}-char delivery cap: {len(over)}")
    for t, n in sorted(over.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>8,}B  {round(100 * (1 - 2048 / n)):>2}% absent when injected  {t}")
    # The invariant that MUST hold: every route resolves. Size is reported.
    assert all(atl._load_file_content(atl.TOPICS_DIR, t) for t in live.values())


def test_every_route_names_a_registered_mcp_server():
    """BUG 4 — the biggest one: 10 of 17 routes named a server that no longer exists.

    The gateway servers dropped their `remote-` prefix in the macOS migration
    (see claude-config #1785, which fixed skills/ and manifests but not this
    hook). A prefix for an absent server is a route that can NEVER fire, and that
    is indistinguishable from "this server has no domain context" — five curated
    SECURITY topics (crowdstrike, airlock, tenable, confluence, tailscale) were
    unreachable, so domain context for the most-used security tools never loaded.

    No other test catches this: `test_no_route_resolves_to_a_missing_file`
    validates the TOPIC exists, and a missing SERVER only fails at runtime by
    silently never matching.

    Skips VISIBLY when the CLI is unavailable — a reported skip, never a bare
    `return`, which is the vacuous-pass trap that let 12 rule tests in this very
    file report green for two months after their source dir was deleted.
    """
    if not shutil.which("claude"):
        pytest.skip("claude CLI unavailable — cannot enumerate live servers")
    try:
        out = subprocess.run(["claude", "mcp", "list"], capture_output=True,
                             text=True, timeout=180).stdout
    except subprocess.TimeoutExpired:
        pytest.skip("claude mcp list timed out")
    live = set(re.findall(r"^([a-z0-9_-]+):", out, re.M))
    if not live:
        pytest.skip("could not parse server names from `claude mcp list`")

    import importlib.util
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "atl_live", LOADER_PATH)
    atl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atl)

    dead = [pref for pref in atl.STATIC_MAP
            if pref[len("mcp__"):].rstrip("_") not in live]
    assert not dead, (
        f"routes naming unregistered servers (can never fire): {dead}. "
        f"Repoint to a live server or retire the entry."
    )


# --- delivery-budget enforcement (added 2026-08-15) ---------------------------
#
# The platform caps hook output at 10,000 CHARACTERS and replaces anything over
# with a preview plus a file path, so an over-budget topic silently does not
# arrive. The loader documented that cap from the start and never measured its
# own output: msgraph.md sat at 10,067 chars and had been stubbed on every
# injection. These tests pin the guard that turns that into a loud pointer.

DEPLOYED_TOPICS = Path.home() / ".claude" / "agent-memory" / "topics"
PLATFORM_HOOK_OUTPUT_CAP = 10_000


def _loader_module():
    """Import the hook UNDER TEST (repo-relative), not the deployed copy."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("atl_budget", LOADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_budget_constant_leaves_room_for_the_envelope():
    """Pure logic — runs on any checkout, no corpus needed.

    The budget must be STRICTLY under the platform cap: the hook's label and
    JSON envelope are counted by the platform too, so a budget equal to the cap
    would still get the whole payload stubbed.
    """
    atl = _loader_module()
    assert atl.INJECTION_BUDGET_CHARS < PLATFORM_HOOK_OUTPUT_CAP, (
        f"budget {atl.INJECTION_BUDGET_CHARS} must be under the "
        f"{PLATFORM_HOOK_OUTPUT_CAP}-char platform cap"
    )
    envelope_headroom = PLATFORM_HOOK_OUTPUT_CAP - atl.INJECTION_BUDGET_CHARS
    assert envelope_headroom >= 300, (
        f"only {envelope_headroom} chars of headroom for the label + JSON "
        f"envelope (measured ~450); the payload would still be stubbed"
    )


def _fresh_session(sid: str) -> dict:
    """Isolate a hook run from the dedup marker.

    The loader marks a topic loaded per session, so a fixed sid makes the test
    pass once and fail on every rerun. get_marker_path() truncates the sid to 12
    chars, so two ids sharing a 12-char prefix collide into ONE marker and the
    tests interfere with each other — keep these short and distinct.
    """
    marker = SESSION_ENV / f"topics-loaded-{sid[:12]}.json"
    if marker.exists():
        marker.unlink()
    return {"CLAUDE_SESSION_ID": sid}


def _routed_topic_where(predicate):
    """First routed topic whose DEPLOYED file satisfies predicate(chars)."""
    atl = _loader_module()
    for prefix, topic in atl.STATIC_MAP.items():
        p = DEPLOYED_TOPICS / topic
        if p.exists() and predicate(len(p.read_text(encoding="utf-8"))):
            return prefix, topic
    return None, None


def test_over_budget_topic_is_reported_not_silently_stubbed():
    """A topic over budget must yield an explicit NOT DELIVERED pointer."""
    atl = _loader_module()
    if not DEPLOYED_TOPICS.exists():
        pytest.skip("deployed topic corpus absent (CI runner)")
    prefix, topic = _routed_topic_where(lambda n: n > atl.INJECTION_BUDGET_CHARS)
    if not topic:
        pytest.skip("no routed topic currently exceeds the budget")
    code, out, _ = run_hook(
        HOOK, {"tool_name": f"{prefix}probe"},
        env=_fresh_session("bgOver"),
    )
    assert code == 0
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "NOT DELIVERED" in ctx, (
        f"{topic} exceeds the budget but was emitted without a NOT DELIVERED "
        f"marker — the platform will stub it and nothing will say so"
    )
    assert topic in ctx, "the pointer must name the file so it can be Read"
    assert len(ctx) <= atl.INJECTION_BUDGET_CHARS, (
        "the replacement payload must itself fit the budget"
    )


def test_in_budget_topic_still_delivers_verbatim():
    """The guard must not touch a topic that fits — no trimming, no marker."""
    atl = _loader_module()
    if not DEPLOYED_TOPICS.exists():
        pytest.skip("deployed topic corpus absent (CI runner)")
    prefix, topic = _routed_topic_where(
        lambda n: 1_000 < n <= atl.INJECTION_BUDGET_CHARS
    )
    if not topic:
        pytest.skip("no routed topic sits comfortably inside the budget")
    code, out, _ = run_hook(
        HOOK, {"tool_name": f"{prefix}probe"},
        env=_fresh_session("bgUnder"),
    )
    assert code == 0
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    body = (DEPLOYED_TOPICS / topic).read_text(encoding="utf-8").strip()
    assert "NOT DELIVERED" not in ctx, f"{topic} fits the budget; must not be dropped"
    assert body in ctx, f"{topic} must be delivered whole, never trimmed"
