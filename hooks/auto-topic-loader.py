"""PreToolUse hook: auto-load domain TOPIC context when MCP tools are called.

Maps MCP server names to topic files. On a call to a matching server, injects
the topic via additionalContext so the caller gets the relevant domain context
without it sitting in the ambient system prompt.

The routes are ENVIRONMENT DATA: STATIC_MAP is read from the `topic_routes.
by_tool_prefix` section of the environment catalog (hooks/_environment_catalog.py;
contracts/environment-catalog.json ships it empty, so the hook is a no-op until
the operator fills it in). Manifest-derived routing (2026-04-15) was REMOVED
2026-07-29; the catalog map is the only source of routes — see
`_build_server_to_topic_map` for why. A declared topic that does not resolve on
disk is SKIPPED rather than minted as a route — see `_first_resolvable_topic`.

DELIVERY CAP — the binding constraint on every topic this hook injects.
Per the hooks reference (code.claude.com/docs/en/hooks, verified 2026-07-29):
"Hook output strings, including additionalContext, systemMessage, and plain
stdout, are capped at 10,000 characters. Output that exceeds this limit is saved
to a file and replaced with a preview and file path."

So a payload over ~9,550 chars (10,000 minus this hook's label + JSON envelope,
measured at ~450B) does NOT arrive: the model receives a ~2KB preview plus a
path it has no reason to read mid-task. Measured locally: firecrawl.md (8,614B)
delivered whole; security.md (13,460B) stubbed.

RETRIEVAL (2026-09-04). Whole-file injection could only ever deliver a topic
that fit. From 2026-08-15 an over-budget topic produced a NOT DELIVERED pointer
and no content — the two largest routed topics (24,170 and 10,256 chars)
delivered nothing on every call, and 43 of the 98 corpus topics (44%) are over
the cap.
Now a topic at or under TOPIC_BUDGET_CHARS is injected whole. A larger one is
split on markdown headings (`split_sections`) and the payload is the SUMMARY
(a `Summary` section if present, else the title plus the first section with a
body) plus the sections whose heading/body tokens overlap the tool name and tool
input (`select_sections`: token overlap, headings weighted double, tokens found
in more than half the sections ignored as uninformative), greedily by score
under the same cap, ending with a one-line pointer to the file so the model can
Read the rest. Sections are remembered per session, so a later tool on the same
server adds only what it newly matches and an identical call is silent.

Rule injection was RETIRED 2026-07-29 (dead since #1011 deleted its source dir;
see the note in main()). This hook loads topics only.

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
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _environment_catalog import load_section

TOPICS_DIR = Path.home() / ".claude" / "agent-memory" / "topics"
SESSION_MARKER_DIR = Path.home() / ".claude" / "session-env"
GRAPH_PATH = Path.home() / ".claude" / "manifests" / "graph.json"

# See "DELIVERY CAP" above. The platform caps hook output at 10,000 CHARACTERS;
# this hook's label + JSON envelope measured ~450, so 9,550 is the ceiling for
# the whole payload. A payload over it is replaced by a pointer (never stubbed
# silently by the platform).
INJECTION_BUDGET_CHARS = 9_550

# Content budget per topic: the whole-file threshold AND the slice cap. 8,000 is
# the corpus's own soft cap for a topic file (skills/garden Step 3b auto-splits
# above 8 KB), so a topic the garden considers well-sized arrives whole and only
# files the garden would already flag get sliced. The label and pointer lines
# ride on top; test_topic_budget_leaves_headroom_for_label_and_pointer pins the
# gap to INJECTION_BUDGET_CHARS.
TOPIC_BUDGET_CHARS = 8_000

# The curated server→topic map: the `topic_routes.by_tool_prefix` section of the
# environment catalog. Since the manifest derivation was removed (see
# _build_server_to_topic_map), this is the ONLY source of routes. Topic files
# are environment content (agent-memory/topics/ ships empty), so the routes to
# them are environment data too; with an empty section no server has domain
# context and the hook is a no-op.
#
# LESSONS THE CATALOG EDITOR INHERITS (learned on the 2026-07-29 repoint
# against the live `claude mcp list` surface):
#
# * A prefix must name a REGISTERED server. 10 of the then 17 entries named a
#   server that was not registered on this host, so those routes could never
#   fire — and a route that cannot fire is indistinguishable from "this server
#   has no domain context". Five curated security topics were unreachable, i.e.
#   the domain context for the most-used security tools never loaded. Root
#   cause was the same one PR #1785 documented 25 minutes earlier from the
#   other direction: the gateway servers dropped their `remote-` prefix during
#   the macOS migration, and every consumer wired by STRING MATCH failed
#   SILENTLY. #1785 repointed skills/ and manifests; this hook was missed, which
#   is exactly the `check-before-change.md` MCP-consolidation drift class (grep
#   EVERY consumer, including hook internals).
#   `test_no_route_resolves_to_a_missing_file` catches a missing TOPIC; it
#   cannot catch a missing SERVER, because that only fails at runtime by never
#   firing. Retire the route when the server leaves; keep the topic file (it is
#   still readable and still accurate; only the auto-injection trigger is gone).
#
# * Route to a file that fits the budget. A route to a 25,914-char topic (2.7x
#   the delivery budget) injected NOTHING on every call until retrieval landed
#   (see RETRIEVAL above); a hub file is the right target for a 43 KB corpus.
#   A missing route costs real rediscovery: on 2026-08-29 a new runbook shipped
#   into an ALREADY-DOCUMENTED trap because the map lacked that server's
#   prefix — 2 of that night's 3 rediscovered gotchas were on file.
STATIC_MAP = {
    str(prefix): str(topic)
    for prefix, topic in (load_section("topic_routes").get("by_tool_prefix") or {}).items()
    if isinstance(prefix, str) and isinstance(topic, str) and prefix and topic
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
    error surfaced. STATIC_MAP (the catalog's `topic_routes.by_tool_prefix`) is
    hand-curated and the only source now: each entry a deliberate server→topic
    pairing. Adding a server means adding one line to the catalog — explicit
    beats automatic when the automation has no way to be right.

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
    """Return {topic_file: [section ids delivered this session]}; "*" = whole file.

    Markers written before 2026-09-04 were a list of "topic:<file>" strings and
    meant the whole file had been delivered; read them as such so a session
    that straddles the upgrade does not re-inject.
    """
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(raw, dict):
        return {k: [str(x) for x in v] for k, v in raw.items() if isinstance(v, list)}
    if isinstance(raw, list):
        return {e[len("topic:"):]: ["*"] for e in raw
                if isinstance(e, str) and e.startswith("topic:")}
    return {}


def mark_loaded(marker_path, topic, section_ids):
    loaded = get_loaded_topics(marker_path)
    loaded[topic] = sorted(set(loaded.get(topic, [])) | set(section_ids))
    text = json.dumps(loaded)
    # Atomic write — concurrent sessions writing the same marker would
    # otherwise race and corrupt the JSON, causing get_loaded_topics() to
    # silently return an empty dict on the next call (so every topic
    # reloads every invocation).
    try:
        # atomic_write lives next to this hook.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from atomic_write import atomic_write
        atomic_write(marker_path, text)
    except Exception:
        # Fall back to plain write_text if atomic_write isn't importable.
        marker_path.write_text(text, encoding="utf-8")


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


# ── Retrieval: split a topic into sections and pick the ones a call needs ──────

_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD = re.compile(r"[a-z0-9]+")
# Function words plus JSON/tool-name noise. Anything left is a candidate match;
# tokens common to most sections of a topic are dropped per file (see
# select_sections), which is what keeps the server's own name from matching
# every section of its topic.
_STOP = frozenset("""
the and for with this that not from are was were has have had use used using
when then than into your you can all any also but its per via non mcp tool
tools true false null none get set list new one two see only each more most
such some will does did how what which where who why here there these those
them they their our out over under about after before between because been
being both just like make made may might must need should would could still
very well yet etc
""".split())


def _tokens(text):
    """Lowercase alnum tokens, camelCase split, 3+ chars, crude plural fold."""
    out = set()
    for w in _WORD.findall(_CAMEL.sub(" ", text).lower()):
        if len(w) < 3 or w in _STOP:
            continue
        if len(w) >= 5 and w.endswith("s"):
            w = w[:-1]
        out.add(w)
    return out


class Section:
    """One heading-delimited slice of a topic file (heading line included)."""

    __slots__ = ("body_tokens", "head_tokens", "heading", "idx", "level", "text")

    def __init__(self, idx, level, heading, text):
        self.idx = idx
        self.level = level
        self.heading = heading
        self.text = text
        self.head_tokens = _tokens(heading)
        self.body_tokens = _tokens(text)

    @property
    def id(self):
        return f"{self.idx}:{self.heading[:60]}"

    @property
    def has_body(self):
        body = self.text.split("\n", 1)[1] if self.level else self.text
        return bool(body.strip())


def split_sections(text):
    """Split on ATX headings (any level); `#` lines inside code fences stay put.

    Text before the first heading becomes a level-0 section with an empty
    heading. Each section's text starts with its heading line.
    """
    sections = []
    cur, heading, level, in_fence = [], "", 0, False

    def flush():
        if cur:
            sections.append(Section(len(sections), level, heading, "\n".join(cur)))

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            flush()
            cur, heading, level = [line], m.group(2).strip(), len(m.group(1))
        else:
            cur.append(line)
    flush()
    return sections


def _summary_indices(sections):
    """A `Summary`-titled section if there is one; else the leading run of
    sections up to and including the first one with a body (typically the
    `# Title` line plus `## Critical Gotchas`)."""
    for s in sections:
        if s.level and s.heading.lower().startswith("summary"):
            return [s.idx]
    lead = []
    for s in sections:
        lead.append(s.idx)
        if s.has_body:
            break
    return lead


def _query_tokens(tool_name, tool_input):
    q = _tokens(tool_name)
    if tool_input:
        try:
            q |= _tokens(json.dumps(tool_input, ensure_ascii=False)[:4000])
        except (TypeError, ValueError):
            pass
    return q


def select_sections(sections, tool_name, tool_input, budget, already):
    """Summary first, then sections by token overlap with the call, greedily
    under `budget` chars (sections are atomic: whole or skipped). Sections whose
    id is in `already` were delivered earlier this session and are not repeated.
    Returned in file order."""
    q = _query_tokens(tool_name, tool_input)
    n = len(sections)
    if n >= 4:
        # A token present in more than half the sections says nothing about
        # WHICH section the call needs (the server name, the product name).
        q = {t for t in q if sum(t in s.body_tokens for s in sections) <= n / 2}
    summary = _summary_indices(sections)
    ranked = []
    for s in sections:
        if s.idx in summary or s.id in already:
            continue
        score = 2 * len(q & s.head_tokens) + len(q & s.body_tokens)
        if score:
            ranked.append((-score, s.idx, s))
    ranked.sort()
    candidates = [sections[i] for i in summary if sections[i].id not in already]
    candidates += [r[2] for r in ranked]
    chosen, used = [], 0
    for s in candidates:
        cost = len(s.text) + (2 if chosen else 0)  # "\n\n" joiner
        if used + cost <= budget:
            chosen.append(s)
            used += cost
    chosen.sort(key=lambda s: s.idx)
    return chosen


def build_payload(topic_file, content, tool_name, tool_input, already):
    """Return (additionalContext text, section ids delivered) or (None, set()).

    Whole file when it fits TOPIC_BUDGET_CHARS ("*" marks it delivered);
    otherwise a slice, ending with a one-line pointer that names the file and
    says what was NOT DELIVERED so the model can Read the rest.
    """
    path = TOPICS_DIR / topic_file
    label = f"Domain context for {topic_file}:"
    if len(content) <= TOPIC_BUDGET_CHARS:
        pointer = f"Topic file: {path} (delivered whole, {len(content):,} chars)."
        return f"{label}\n{content}\n\n{pointer}", {"*"}
    sections = split_sections(content)
    chosen = select_sections(sections, tool_name, tool_input, TOPIC_BUDGET_CHARS, already)
    if not chosen:
        return None, set()
    body = "\n\n".join(s.text.strip("\n") for s in chosen)
    pointer = (
        f"Topic file: {path} — {len(chosen)} of {len(sections)} sections above "
        f"({len(body):,} of {len(content):,} chars); the rest was NOT DELIVERED, "
        f"Read the file for it."
    )
    return f"{label}\n{body}\n\n{pointer}", {s.id for s in chosen}


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if not tool_name:
        sys.exit(0)

    topic_file, used_manifest, is_in_static = _find_topic_match(tool_name)
    if not topic_file:
        sys.exit(0)

    session_id = data.get("session_id") or None
    try:
        from manifest_metrics import log_manifest_query
        log_manifest_query(
            "auto-topic-loader", "topic_derivation",
            f"tool={tool_name[:40]} topic={topic_file} manifest={used_manifest} in_static={is_in_static}",
            used_fallback=not used_manifest, session_id=session_id,
        )
    except Exception:
        pass

    marker_path = get_marker_path(session_id)
    already = set(get_loaded_topics(marker_path).get(topic_file, []))
    if "*" in already:
        sys.exit(0)

    content = _load_file_content(TOPICS_DIR, topic_file)
    if content is None:
        sys.exit(0)

    payload, delivered = build_payload(
        topic_file, content, tool_name, data.get("tool_input") or {}, already)
    if not payload:
        sys.exit(0)
    mark_loaded(marker_path, topic_file, delivered)

    # RULE INJECTION RETIRED 2026-07-29 — it had been dead since 2026-05-26 and
    # repairing it would have made things worse. Kept as a comment, not code,
    # because the reasoning is the useful part:
    #
    # The mechanism was real: "rule files placed in ~/.claude/agent-memory/rules/
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
    # To REVIVE the mechanism properly, the rules must first stop being ambient
    # (that is the token saving), and each must fit under the delivery budget
    # after the label+envelope overhead. Both are prerequisites, not details.
    #
    # Prior instance of this exact class in this same map: the dangling
    # `rules/context7*.md` entries (B7 review) pointed at files that never
    # existed and also silently no-op'd. Two instances is why the mechanism
    # goes rather than getting a third patch.

    # Last-resort ceiling. By construction the payload is under it (content is
    # capped at TOPIC_BUDGET_CHARS; label + pointer fit the pinned headroom), so
    # this only fires if someone raises one constant without the other. Fail
    # LOUD with a pointer rather than let the platform stub the payload.
    if len(payload) > INJECTION_BUDGET_CHARS:
        payload = (
            f"NOT DELIVERED: Domain context for {topic_file} ({len(payload):,} chars) "
            f"exceeds this hook's {INJECTION_BUDGET_CHARS:,}-char delivery budget. "
            f"Read {TOPICS_DIR / topic_file} directly if this task needs it."
        )

    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": payload,
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
