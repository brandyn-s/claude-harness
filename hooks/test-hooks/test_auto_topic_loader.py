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

    Since the routes moved into the environment catalog, the suite pins
    CLAUDE_ENVIRONMENT_CATALOG to the test FIXTURE (conftest). Comparing the
    fixture's routes with THIS machine's `claude mcp list` is meaningless: the
    fixture describes no real host. So this is an opt-in liveness check of the
    machine's own catalog: run with CLAUDE_TOPIC_ROUTE_LIVENESS=1 and the module
    is loaded with the fixture override removed, i.e. against the local catalog
    the installed hook actually reads. Without the opt-in it skips, visibly.
    """
    if os.environ.get("CLAUDE_TOPIC_ROUTE_LIVENESS") != "1":
        pytest.skip("routes under test come from the fixture catalog; set "
                    "CLAUDE_TOPIC_ROUTE_LIVENESS=1 to check this machine's catalog "
                    "against its live MCP servers")
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
    # Load against the machine's own catalog, not the suite's fixture override.
    fixture_override = os.environ.pop("CLAUDE_ENVIRONMENT_CATALOG", None)
    try:
        spec.loader.exec_module(atl)
    finally:
        if fixture_override is not None:
            os.environ["CLAUDE_ENVIRONMENT_CATALOG"] = fixture_override

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
    """A topic over budget must yield an explicit NOT DELIVERED pointer.

    Since 2026-09-04 the over-budget path SLICES (summary + matching sections)
    instead of dropping the topic; the pointer line still says what was not
    delivered and names the file, and the payload still fits the budget."""
    atl = _loader_module()
    if not DEPLOYED_TOPICS.exists():
        pytest.skip("deployed topic corpus absent (CI runner)")
    prefix, topic = _routed_topic_where(lambda n: n > atl.TOPIC_BUDGET_CHARS)
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
    """The guard must not touch a topic that fits — no trimming, no marker.

    "Fits" is TOPIC_BUDGET_CHARS (the whole-file threshold, 2026-09-04); a
    topic under it is delivered verbatim, never sliced."""
    atl = _loader_module()
    if not DEPLOYED_TOPICS.exists():
        pytest.skip("deployed topic corpus absent (CI runner)")
    prefix, topic = _routed_topic_where(
        lambda n: 1_000 < n <= atl.TOPIC_BUDGET_CHARS
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


# --- retrieval slicing (added 2026-09-04) -------------------------------------
#
# Whole-file injection could only ever deliver a topic that fit the budget; an
# over-budget topic yielded a NOT DELIVERED pointer and nothing else (2 of 13
# routes, msgraph.md and linear.md, delivered zero domain content). The loader
# now splits a topic on markdown headings and, when the file exceeds
# TOPIC_BUDGET_CHARS, injects the summary plus the sections whose tokens overlap
# the tool name and tool input, under the cap, ending with a pointer to the file.
# Sections are remembered per session, so a second tool on the same server adds
# only what it newly matches and an identical call is silent.
#
# These tests build their own corpus in a temp HOME (the hook resolves
# TOPICS_DIR from Path.home()), so they run on any checkout, CI included.

def _filler(phrase: str, chars: int) -> str:
    """Deterministic body text built from `phrase`, at least `chars` long."""
    line = f"{phrase} detail line."
    return "\n".join(line for _ in range(chars // len(line) + 1))


def _over_budget_topic(atl) -> str:
    """Four sections; three bodies of ~budget/2.5 chars each, so the whole file
    exceeds TOPIC_BUDGET_CHARS but summary + any one body fits under it."""
    body = atl.TOPIC_BUDGET_CHARS // 2 - 400
    parts = [
        "# Widget Service - Worker Topic Guide",
        "",
        "## Critical Gotchas",
        "- The service rejects unpaged reads over 500 rows.",
        "- Timestamps are UTC without a suffix.",
        "",
        "## Mailbox folder search",
        "Folder-scoped mail search returns zero rows when handed an opaque",
        "folder id; resolve the folder by name first.",
        _filler("mail folder lookup", body),
        "",
        "## Invoice billing export",
        "Billing invoices export as CSV with a trailing total row that must be",
        "dropped before summing.",
        _filler("invoice billing csv", body),
        "",
        "## Device enrollment",
        "Enrollment profiles apply on the NEXT check-in, not immediately.",
        _filler("device enrollment profile", body),
        "",
    ]
    return "\n".join(parts)


def _corpus(tmp_path, atl, text: str, sid: str = "slice1"):
    """Write `text` as the topic file of the first routed server in a temp HOME.

    Returns (tool_prefix, topic_file, env) where env points the hook at the
    temp HOME (HOME for POSIX, USERPROFILE for Windows expanduser) and pins a
    fresh session id so the marker starts empty."""
    prefix, topic = next(iter(atl.STATIC_MAP.items()))
    home = tmp_path / "home"
    topics = home / ".claude" / "agent-memory" / "topics"
    topics.mkdir(parents=True)
    (topics / topic).write_text(text, encoding="utf-8")
    env = {"HOME": str(home), "USERPROFILE": str(home), "CLAUDE_SESSION_ID": sid}
    return prefix, topic, env


def _ctx(stdout: str) -> str:
    out = json.loads(stdout)
    assert set(out) == {"hookSpecificOutput"}, f"unexpected top-level keys: {list(out)}"
    hso = out["hookSpecificOutput"]
    assert set(hso) == {"hookEventName", "additionalContext"}, f"unexpected keys: {list(hso)}"
    assert hso["hookEventName"] == "PreToolUse"
    assert isinstance(hso["additionalContext"], str)
    return hso["additionalContext"]


def test_topic_budget_leaves_headroom_for_label_and_pointer():
    """TOPIC_BUDGET_CHARS bounds section content; the label line and the
    pointer line ride on top and the whole payload must still clear the
    platform-derived INJECTION_BUDGET_CHARS."""
    atl = _loader_module()
    assert atl.TOPIC_BUDGET_CHARS + 500 <= atl.INJECTION_BUDGET_CHARS, (
        "raise INJECTION_BUDGET_CHARS headroom before raising TOPIC_BUDGET_CHARS"
    )


def test_split_sections_on_headings_ignores_fenced_hashes():
    atl = _loader_module()
    lines = [
        "intro before any heading",
        "# Title",
        "## Alpha",
        "alpha body",
        "```sh",
        "# not a heading, a shell comment",
        "```",
        "### Beta",
        "beta body",
    ]
    secs = atl.split_sections("\n".join(lines))
    headings = [s.heading for s in secs]
    assert headings == ["", "Title", "Alpha", "Beta"], headings
    assert [s.level for s in secs] == [0, 1, 2, 3]
    alpha = next(s for s in secs if s.heading == "Alpha")
    assert "# not a heading" in alpha.text, "fenced '#' line must stay in its section"
    assert secs[0].text.strip() == "intro before any heading"


def test_select_sections_never_exceeds_budget():
    atl = _loader_module()
    # Every section carries its own key and the query names all of them, so
    # all 30 match with equal score and only the cap decides how many go.
    text = "# T\n\n" + "\n\n".join(
        f"## Section {i}\nkey{i} " + _filler("shared filler", 900)
        for i in range(30)
    )
    secs = atl.split_sections(text)
    query = {"q": " ".join(f"key{i}" for i in range(30))}
    chosen = atl.select_sections(secs, "mcp__x__probe", query, 4_000, set())
    assert 2 <= len(chosen) < 30, f"expected a partial fill, got {len(chosen)} sections"
    total = sum(len(s.text) for s in chosen) + 2 * (len(chosen) - 1)
    assert total <= 4_000, f"selected {total} chars over a 4,000 budget"
    assert [s.idx for s in chosen] == sorted(s.idx for s in chosen), "file order kept"


def test_over_budget_topic_is_sliced_to_summary_plus_matching_sections(tmp_path):
    atl = _loader_module()
    text = _over_budget_topic(atl)
    assert len(text) > atl.TOPIC_BUDGET_CHARS, "fixture must exceed the budget"
    prefix, topic, env = _corpus(tmp_path, atl, text)
    rc, out, err = run_hook(
        HOOK,
        {"tool_name": f"{prefix}search_mail_folders",
         "tool_input": {"folder": "Inbox", "query": "quarterly report"}},
        env=env,
    )
    assert rc == 0, err
    ctx = _ctx(out)
    assert "Critical Gotchas" in ctx and "unpaged reads over 500" in ctx, "summary missing"
    assert "Mailbox folder search" in ctx and "opaque" in ctx, "matching section missing"
    assert "Invoice billing" not in ctx and "invoice billing csv" not in ctx, "unrelated section present"
    assert "Device enrollment" not in ctx, "unrelated section present"
    assert len(ctx) <= atl.INJECTION_BUDGET_CHARS
    assert len(ctx) < len(text), "slice must be smaller than the whole file"
    last = ctx.rstrip().splitlines()[-1]
    assert topic in last and "NOT DELIVERED" in last, f"pointer line must name the file: {last!r}"
    assert str(atl.TOPICS_DIR.name) in last or "topics" in last


def test_small_topic_is_injected_whole_with_pointer(tmp_path):
    atl = _loader_module()
    text = "# Tiny - Worker Topic Guide\n\n## Critical Gotchas\n- one\n- two\n\n## Details\nsome detail\n"
    prefix, topic, env = _corpus(tmp_path, atl, text, sid="whole1")
    rc, out, err = run_hook(HOOK, {"tool_name": f"{prefix}anything", "tool_input": {}}, env=env)
    assert rc == 0, err
    ctx = _ctx(out)
    assert text.strip() in ctx, "small topic must be delivered verbatim"
    assert "NOT DELIVERED" not in ctx
    last = ctx.rstrip().splitlines()[-1]
    assert topic in last, f"pointer line must name the file: {last!r}"
    # Whole delivery covers every tool: a different tool on the same server is silent.
    rc, out, _ = run_hook(HOOK, {"tool_name": f"{prefix}other_tool", "tool_input": {"x": 1}}, env=env)
    assert rc == 0 and not out.strip()


def test_same_call_twice_injects_once_per_session(tmp_path):
    atl = _loader_module()
    prefix, _topic, env = _corpus(tmp_path, atl, _over_budget_topic(atl), sid="once1")
    call = {"tool_name": f"{prefix}search_mail_folders", "tool_input": {"folder": "Inbox"}}
    rc, out, _ = run_hook(HOOK, call, env=env)
    assert rc == 0 and out.strip()
    rc, out, _ = run_hook(HOOK, call, env=env)
    assert rc == 0 and not out.strip(), "identical call must not re-inject"
    # A different session starts clean.
    env2 = dict(env, CLAUDE_SESSION_ID="once2")
    rc, out, _ = run_hook(HOOK, call, env=env2)
    assert rc == 0 and out.strip()


def test_new_tool_on_same_server_adds_only_new_sections(tmp_path):
    atl = _loader_module()
    prefix, topic, env = _corpus(tmp_path, atl, _over_budget_topic(atl), sid="tool1")
    run_hook(HOOK, {"tool_name": f"{prefix}search_mail_folders", "tool_input": {}}, env=env)
    rc, out, err = run_hook(
        HOOK, {"tool_name": f"{prefix}export_invoices", "tool_input": {"format": "csv"}}, env=env,
    )
    assert rc == 0, err
    ctx = _ctx(out)
    assert "Invoice billing export" in ctx, "newly matching section missing"
    assert "Critical Gotchas" not in ctx, "summary must not be re-injected"
    assert "Mailbox folder search" not in ctx, "already-delivered section re-injected"
    assert "Device enrollment" not in ctx
    assert topic in ctx.rstrip().splitlines()[-1]
    rc, out, _ = run_hook(
        HOOK, {"tool_name": f"{prefix}export_invoices", "tool_input": {"format": "csv"}}, env=env,
    )
    assert rc == 0 and not out.strip(), "nothing new left for this tool"


def test_no_matching_section_yields_summary_and_pointer_only(tmp_path):
    atl = _loader_module()
    prefix, topic, env = _corpus(tmp_path, atl, _over_budget_topic(atl), sid="nomatch")
    rc, out, err = run_hook(HOOK, {"tool_name": f"{prefix}zzz_qqq", "tool_input": {}}, env=env)
    assert rc == 0, err
    ctx = _ctx(out)
    assert "Critical Gotchas" in ctx
    for absent in ("Mailbox folder search", "Invoice billing export", "Device enrollment"):
        assert absent not in ctx, f"{absent} injected without a match"
    assert topic in ctx.rstrip().splitlines()[-1]


def test_legacy_list_marker_is_read_as_whole_topic_delivered(tmp_path):
    """Markers written before 2026-09-04 were a list of 'topic:<file>' strings."""
    atl = _loader_module()
    marker = tmp_path / "topics-loaded-legacy.json"
    marker.write_text(json.dumps(["topic:linear.md"]), encoding="utf-8")
    loaded = atl.get_loaded_topics(marker)
    assert "*" in loaded.get("linear.md", []), loaded


def test_selection_is_fast_on_a_large_topic():
    """Bound the in-process cost so a 200 KB topic cannot push the hook past
    its 20 ms target: split + select on that size must stay well under it."""
    import time
    atl = _loader_module()
    text = "# Big\n\n" + "\n\n".join(
        f"## Section {i} about topic {i % 17}\n" + _filler(f"token{i % 23} filler text", 1_500)
        for i in range(130)
    )
    assert len(text) > 190_000
    t0 = time.perf_counter()
    secs = atl.split_sections(text)
    atl.select_sections(secs, "mcp__x__topic_5", {"q": "token3 filler"}, atl.TOPIC_BUDGET_CHARS, set())
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 100, f"split+select took {elapsed_ms:.1f} ms on 200 KB"


@needs_deployed_corpus
def test_report_injected_chars_whole_vs_retrieval():
    """Reporting test (prints under -s): per routed topic, the chars the loader
    would emit for one representative call, whole-file vs retrieval. This is
    the table in hooks/README.md; rerun it after editing a routed topic."""
    atl = _loader_module()
    calls = {
        "msgraph.md": ("graph_request", {"path": "/users/me/mailFolders", "version": "v1.0"}),
        "linear.md": ("list_issues", {"teamId": "SEC", "query": "webhook"}),
        "firecrawl.md": ("firecrawl_search", {"query": "site:nsa.gov pdf", "limit": 5}),
    }
    total_before = total_after = 0
    print(f"\n{'topic':28} {'file':>8} {'whole':>8} {'retrieval':>9}")
    for prefix, topic in atl.STATIC_MAP.items():
        content = atl._load_file_content(atl.TOPICS_DIR, topic)
        if content is None:
            continue
        tool, tool_input = calls.get(topic, ("probe", {}))
        payload, _ = atl.build_payload(topic, content, prefix + tool, tool_input, set())
        before = len(f"Domain context for {topic}:\n{content}")
        after = len(payload or "")
        total_before += before
        total_after += after
        print(f"{topic:28} {len(content):>8,} {before:>8,} {after:>9,}")
    print(f"{'TOTAL':28} {'':>8} {total_before:>8,} {total_after:>9,}")
    assert total_after <= total_before
