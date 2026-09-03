"""PreToolUse hook: auto-load domain TOPIC context when MCP tools are called.

Maps MCP server names to topic files. On first call to each matching server in a
session, injects the topic via additionalContext so the caller gets the relevant
domain context without it sitting in the ambient system prompt.

Manifest-derived routing (2026-04-15): builds the server→topic map from
graph.json skill manifests (requires_tools → requires_topics). Falls back
to hardcoded STATIC_MAP when graph.json is unavailable. New MCP servers
automatically get topic routing when a skill manifest references them.
A declared topic that does not resolve on disk is SKIPPED rather than minted as
a route — see `_first_resolvable_topic`.

DELIVERY CAP — the binding constraint on every topic this hook injects.
Per the hooks reference (code.claude.com/docs/en/hooks, verified 2026-07-29):
"Hook output strings, including additionalContext, systemMessage, and plain
stdout, are capped at 10,000 characters. Output that exceeds this limit is saved
to a file and replaced with a preview and file path."

So a topic over ~9,550 bytes (10,000 minus this hook's label + JSON envelope,
measured at ~450B) does NOT arrive. The model receives a ~2KB preview plus a
path it has no reason to read mid-task, so the rest is silently absent. Measured
locally: firecrawl.md (8,614B) delivered whole; security.md (13,460B) stubbed.
Keep injectable topics under that budget, or split them into siblings that fit —
`/garden` Step 3b reports which ones breach it.

Rule injection was RETIRED 2026-07-29 (dead since #1011 deleted its source dir;
see the note in main()). This hook now loads topics only.

Uses a session-scoped temp file to track which topics have been loaded, so a
repeated call to the same server does not re-inject.

Output format (validated 2026-03-12):
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "..."
  }
}
"""

import json
import os
import sys
from pathlib import Path

TOPICS_DIR = Path.home() / ".claude" / "agent-memory" / "topics"
SESSION_MARKER_DIR = Path.home() / ".claude" / "session-env"
GRAPH_PATH = Path.home() / ".claude" / "manifests" / "graph.json"

# See "DELIVERY CAP" above. The platform caps hook output at 10,000 CHARACTERS;
# this hook's label + JSON envelope measured ~450, so 9,550 is the usable budget
# for section content. Enforced in main() — over-budget sections are reported as
# NOT DELIVERED rather than silently replaced by a platform preview.
INJECTION_BUDGET_CHARS = 9_550
SECTION_SEPARATOR = "\n\n---\n\n"

# The curated server→topic map. Since the manifest derivation was removed
# (see _build_server_to_topic_map), this is the ONLY source of routes.
#
# REPOINTED 2026-07-29 against the live `claude mcp list` surface. 10 of the
# previous 17 entries named a server that is not registered on this host, so
# those routes could never fire — and a route that cannot fire is
# indistinguishable from "this server has no domain context". Five curated
# SECURITY topics (crowdstrike, airlock, tenable, confluence, tailscale) were
# unreachable, i.e. the domain context for our most-used security tools never
# loaded.
#
# Root cause is the same one PR #1785 documented 25 minutes earlier from the
# other direction: the gateway servers dropped their `remote-` prefix during the
# macOS migration, and every consumer wired by STRING MATCH failed SILENTLY.
# #1785 repointed skills/ and manifests; this hook was missed, which is exactly
# the `check-before-change.md` MCP-consolidation drift class (grep EVERY
# consumer, including hook internals).
#
# VERIFY BEFORE EDITING: a prefix here must match a server in `claude mcp list`.
# `test_no_route_resolves_to_a_missing_file` catches a missing TOPIC; it cannot
# catch a missing SERVER, because that only fails at runtime by never firing.
STATIC_MAP = {
    # Gateway servers — post-migration names (no `remote-` prefix).
    "mcp__crowdstrike__": "crowdstrike.md",
    "mcp__tenable__": "tenable.md",
    "mcp__airlock__": "airlock.md",
    "mcp__msgraph__": "msgraph.md",
    "mcp__confluence__": "confluence.md",
    "mcp__tailscale__": "tailscale.md",
    "mcp__security-remix__": "security.md",
    "mcp__slack-user__": "slack.md",
    # Local stdio servers.
    "mcp__linear-server__": "linear.md",
    # Hub file, not the 43KB full topic (over the 10K delivery cap). Added
    # 2026-08-29 after a new runbook shipped into the ALREADY-DOCUMENTED
    # Python2 autoSync trap: the topic never injected because this map lacked
    # the prefix — 2 of that night's 3 rediscovered gotchas were on file.
    "mcp__azure-automation__": "azure-automation-hub.md",
    # Was "infrastructure.md" (25,914 chars): 2.7x the delivery budget, so this
    # route injected NOTHING on every netcloud call. netcloud.md fits the budget
    # and is the subject-matched topic. Ported from claude-config d6f1eddf.
    "mcp__netcloud__": "netcloud.md",
    "mcp__hologram__": "hologram.md",
    # B12/F3 tier decision (2026-06-10): 44 skill references and no topic was
    # the clearest routing gap in the B7 reachability computation.
    "mcp__firecrawl__": "firecrawl.md",
    # RETIRED 2026-07-29 — server not registered on this host, so the route
    # could never fire. Restore the line if the server returns:
    #   "mcp__ramp__": "ramp.md",                    (Ramp MCP not migrated)
    #   "mcp__prowler__": "security.md",             (prowler not migrated)
    #   "mcp__lucid-mcp__": "lucid-admin.md",        (lucid not migrated)
    #   "mcp__context7-docs__": "context7-docs.md",  (context7 not migrated)
    # Their topic files are KEPT — they are still readable and still accurate;
    # only the auto-injection trigger is gone.
}

# Module-level cache
_derived_map = None
_graph_mtime = 0


def _server_prefix(tool_ref):
    """Normalize a manifest `requires_tools` entry to its SERVER prefix.

    Manifests declare FULL TOOL NAMES (`mcp__tavily__tavily_search`), not server
    prefixes — and the old code only `rstrip("*")`ed them, so a specific tool
    name became a map key. Since `_find_topic_match` returns on the first
    `startswith` hit and dict order decides the winner, a tool-name key SHADOWS
    the correct server-level route.

    Measured 2026-07-29: `mcp__tavily__tavily_search` matched two entries —
    the tool-name key -> security.md (from a security skill that happens to list
    tavily) and the proper server key -> infrastructure.md. Dict order picked
    security.md, so a web-search call was about to receive security domain
    context. Neither topic is right for tavily; the defect is that ANY skill
    naming a tool donated its first topic to that exact tool.

    Collapsing to `mcp__<server>__` means a manifest can only ever contribute a
    SERVER-level route, which is the unit the routing model is built on. First
    writer still wins (STATIC_MAP is seeded first and is authoritative), so this
    also makes the hand-curated entries un-shadowable.

    Returns None when the reference has no server segment to extract.
    """
    body = tool_ref[len("mcp__"):].rstrip("*")
    server = body.split("__", 1)[0]
    return f"mcp__{server}__" if server else None


def _first_resolvable_topic(topics):
    """Return the first entry in `topics` that exists in TOPICS_DIR, or None.

    Accepts a bare slug (`security` -> `security.md`) because a manifest written
    that way plainly means the .md file, and dropping the route would be worse
    than normalizing. Returns None when NOTHING resolves — a route that injects
    nothing is worse than no route, because it fails silently and looks like
    "this server has no domain context" rather than "the mapping is broken".
    """
    for t in topics:
        if not t:
            continue
        for candidate in (t, f"{t}.md") if not t.endswith(".md") else (t,):
            if (TOPICS_DIR / candidate).exists():
                return candidate
    return None


def _build_server_to_topic_map():
    """Return the curated server→topic map.

    MANIFEST DERIVATION REMOVED 2026-07-29. It read every skill's
    `requires_tools` and donated that skill's `requires_topics[0]` to each named
    server. The intent — "adding a new skill with new MCP references
    automatically extends routing" — cannot work, because a skill's topics are
    context for the SKILL, not domain context for a server it happens to call.

    Measured before removal: 11 derived routes, 9 of which paired a server with
    an unrelated topic. `mcp__tavily__` (web search) had SIX donors offering
    security.md / llm-creativity-ceiling.md / architecture.md /
    infrastructure.md — whichever the graph iterated first won, so the route was
    arbitrary rather than wrong-and-fixable. `mcp__codebase-memory-mcp__` had
    nine donors and resolved to security.md. `investigate` alone donated 9
    topics across 3 servers.

    Two bugs kept this invisible. (1) Manifests list FULL TOOL NAMES, so
    `mcp__tavily__tavily_search` became a map key that shadowed the server-level
    key — and `_find_topic_match` returns on the first prefix hit, so dict order
    decided the winner. (2) A declared topic that did not exist on disk still
    minted a route, and a missing file injects nothing silently, so four routes
    on heavily-used prefixes (codebase-memory-mcp, memory-search, exa) had been
    dead rather than wrong.

    Fixing those two made the arbitrary routes LIVE, which is how the category
    error surfaced. STATIC_MAP is hand-curated, correct, and the only source
    now: 17 routes, each a deliberate server→topic pairing. Adding a server
    means adding one line there — explicit beats automatic when the automation
    has no way to be right.

    (`_first_resolvable_topic` and `_server_prefix` are retained: the audit
    scripts use them, and they document the two traps for whoever revives
    derivation with a real server→topic declaration.)
    """
    return STATIC_MAP


# Replace the old static SERVER_TO_TOPIC with a dynamic lookup
SERVER_TO_TOPIC = STATIC_MAP  # Default; _build_server_to_topic_map() called at runtime


def get_marker_path(session_id=None):
    """Session-scoped marker file to track loaded topics.

    `session_id` is the hook payload's id; Claude Code does not export it as an
    env var, so without it every session shared one marker (review 2026-09-03).
    """
    sid = str(session_id or os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default")
    SESSION_MARKER_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_MARKER_DIR / f"topics-loaded-{sid[:12]}.json"


def get_loaded_topics(marker_path):
    if marker_path.exists():
        try:
            return set(json.loads(marker_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def mark_loaded(marker_path, topic):
    loaded = get_loaded_topics(marker_path)
    loaded.add(topic)
    # Atomic write — concurrent sessions writing the same marker would
    # otherwise race and corrupt the JSON, causing get_loaded_topics() to
    # silently return an empty set on the next call (so every topic
    # reloads every invocation).
    try:
        # atomic_write lives next to this hook.
        import os
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from atomic_write import atomic_write
        atomic_write(marker_path, json.dumps(list(loaded)))
    except Exception:
        # Fall back to plain write_text if atomic_write isn't importable.
        marker_path.write_text(json.dumps(list(loaded)), encoding="utf-8")


def _find_topic_match(tool_name):
    """Return (topic_file, used_manifest, is_in_static) or (None, False, False)."""
    server_map = _build_server_to_topic_map()
    used_manifest = server_map is not STATIC_MAP
    for prefix, topic in server_map.items():
        if tool_name.startswith(prefix):
            return topic, used_manifest, prefix in STATIC_MAP
    return None, used_manifest, False



def _load_file_content(directory, filename):
    """Read filename from directory; return content or None on any failure."""
    path = directory / filename
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if not tool_name:
        sys.exit(0)

    marker_path = get_marker_path(data.get("session_id") or None)
    loaded = get_loaded_topics(marker_path)

    sections = []  # list of (label, content) to inject

    # Topic match (existing behavior)
    topic_file, used_manifest, is_in_static = _find_topic_match(tool_name)
    if topic_file:
        try:
            from manifest_metrics import log_manifest_query
            log_manifest_query(
                "auto-topic-loader", "topic_derivation",
                f"tool={tool_name[:40]} topic={topic_file} manifest={used_manifest} in_static={is_in_static}",
                used_fallback=not used_manifest,
            )
        except Exception:
            pass
        topic_marker = f"topic:{topic_file}"
        if topic_marker not in loaded:
            content = _load_file_content(TOPICS_DIR, topic_file)
            if content is not None:
                sections.append((f"Domain context for {topic_file}", content))
                mark_loaded(marker_path, topic_marker)

    # RULE INJECTION RETIRED 2026-07-29 — it had been dead since 2026-05-26 and
    # repairing it would have made things worse. Kept as a comment, not code,
    # because the reasoning is the useful part:
    #
    # The lever was real: "rule files placed in ~/.claude/agent-memory/rules/
    # load on first matching tool call rather than ambient at session start.
    # This recovers ~22K tokens of always-loaded context." Then #1011
    # ("memory audit cleanup — empty agent-memory/rules legacy dir") deleted
    # that directory, moving the three rules BACK to ambient — and nobody
    # updated RULES_DIR. Every rule injection since has read a nonexistent path,
    # returned None, and been silently skipped: 14 prefixes, 3 rules, ~2 months.
    #
    # Why NOT just repoint RULES_DIR at ~/.claude/rules/:
    #   1. All 37 rules/*.md are ALREADY ambient (platform InstructionsLoaded),
    #      so injecting them again duplicates content already in context.
    #   2. Two of the three exceed the vendor's 10,000-char hook-output cap
    #      (web-search-preference 12,815B, security-confirmations 11,871B), so
    #      the duplicate would arrive as a ~2KB stub — cost with no delivery.
    # Repointing would spend tokens to deliver a truncated copy of something
    # already present. Removal is the fix.
    #
    # To REVIVE the lever properly, the rules must first stop being ambient
    # (that is the token saving), and each must fit under ~9,550 chars after
    # the label+envelope overhead. Both are prerequisites, not details.
    #
    # Prior instance of this exact class in this same map: the dangling
    # `rules/context7*.md` entries (B7 review) pointed at files that never
    # existed and also silently no-op'd. Two instances is why the mechanism
    # goes rather than getting a third patch.

    if not sections:
        sys.exit(0)

    combined = SECTION_SEPARATOR.join(
        f"{label}:\n{content}" for label, content in sections
    )

    # DELIVERY BUDGET ENFORCEMENT. The cap is documented at the top of this file
    # and was never checked here: over-budget output is replaced by the platform
    # with a ~2KB preview plus a file path, so the topic silently does not arrive
    # and nothing says so. Measured 2026-08-15: msgraph.md is 10,067 chars, over
    # the 10,000 platform cap, and had been stubbed on every injection.
    #
    # Fail LOUD instead. Emit only whole sections that fit, and replace any that
    # do not with an explicit pointer naming the file and its size. A pointer the
    # model can act on beats a preview it cannot distinguish from the real thing.
    # Never truncate a topic mid-way: a partial topic reads as complete and is
    # worse than an honest absence (`SPLIT, NEVER TRIM`).
    if len(combined) > INJECTION_BUDGET_CHARS:
        kept: list[str] = []
        dropped: list[tuple[str, int]] = []
        used = 0
        for label, content in sections:
            piece = f"{label}:\n{content}"
            cost = len(piece) + len(SECTION_SEPARATOR)
            if used + cost <= INJECTION_BUDGET_CHARS:
                kept.append(piece)
                used += cost
            else:
                dropped.append((label, len(piece)))
        notices = [
            f"NOT DELIVERED: {label} ({size:,} chars) exceeds this hook's "
            f"{INJECTION_BUDGET_CHARS:,}-char delivery budget. Read the topic file "
            f"directly if this task needs it — it was NOT injected."
            for label, size in dropped
        ]
        combined = SECTION_SEPARATOR.join(kept + notices)

    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": combined,
        }
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)