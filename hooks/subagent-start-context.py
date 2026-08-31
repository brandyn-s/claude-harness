"""SubagentStart hook: auto-inject topic file content into worker agents.

Reads the agent's dispatch prompt, extracts "Load topics: X.md, Y.md" pattern,
reads each topic file, and injects the concatenated content as additionalContext.
Workers get topic context automatically without needing a Read tool round-trip.

Manifest enrichment (2026-04-15): when the prompt references a skill name
(e.g., "run triage", "/triage"), reads that skill's manifest.yaml to discover
requires_topics — auto-injects topics even without "Load topics:" in the prompt.

Exit codes:
  0 = continue (with optional additionalContext)
"""

import json
import re
import sys
from pathlib import Path

TOPICS_DIR = Path.home() / ".claude" / "agent-memory" / "topics"
GRAPH_PATH = Path.home() / ".claude" / "manifests" / "graph.json"
# Child-side reporting contract, injected on every dispatch. Lives in skills/_shared/
# (a recognised rule-source location since #2148) rather than rules/, because its
# trigger is a DISPATCH, not a file path or a session start.
#
# Resolved from THIS FILE's location, not Path.home(): the hook that executes is the
# one in the checkout it was deployed into, and it must read THAT checkout's contract.
# Hard-coding ~/.claude would let a hook running from a worktree read a different
# tree's contract, and would silently deliver nothing if the two trees disagree.
# Resolving from __file__ keeps each checkout internally consistent, so during a
# deploy lag the old hook and the old ambient rule stay paired rather than crossing.
CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "skills" / "_shared"
    / "subagent-tool-discipline.md"
)

# Platform delivery cap. Over-budget hook output is silently replaced with a ~2KB
# preview plus a file path, so an unbudgeted injection DOES NOT ARRIVE and nothing
# says so (measured 2026-08-15 in auto-topic-loader.py: msgraph.md at 10,067 chars had
# been stubbed on every injection). This hook had no such check before 2026-08-26.
INJECTION_BUDGET_CHARS = 9_550
SECTION_SEPARATOR = "\n\n"

# Pattern matches "Load topics: security.md, crowdstrike.md, linear.md"
TOPIC_PATTERN = re.compile(r"Load topics?:\s*([a-zA-Z0-9_\-.,\s]+\.md)", re.IGNORECASE)

# Module-level graph cache
_graph = None
_graph_mtime = 0


def _load_graph():
    """Load graph.json, cached per process."""
    global _graph, _graph_mtime
    if not GRAPH_PATH.exists():
        return None
    mtime = GRAPH_PATH.stat().st_mtime
    if _graph is not None and mtime == _graph_mtime:
        return _graph
    try:
        with open(GRAPH_PATH, encoding="utf-8") as f:
            _graph = json.load(f)
        _graph_mtime = mtime
        return _graph
    except Exception:
        return None


def _topics_from_manifest(prompt):
    """Check if prompt references a skill name, return its requires_topics."""
    graph = _load_graph()
    if not graph:
        return []

    prompt_lower = prompt.lower()
    for comp_id, comp in graph.items():
        if comp.get("type") != "skill":
            continue
        topics = comp.get("requires_topics", [])
        if not topics:
            continue
        # Match /skill-name or "skill-name" in prompt
        if re.search(rf"(?:^|[\s/])({re.escape(comp_id)})(?:\s|$|[,.])", prompt_lower):
            return topics

    return []


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = data.get("prompt", "")
    if not prompt:
        sys.exit(0)

    filenames = []

    # Method 1: explicit "Load topics:" in prompt
    source = "none"
    match = TOPIC_PATTERN.search(prompt)
    if match:
        raw = match.group(1)
        filenames = [f.strip() for f in raw.split(",") if f.strip()]
        source = "explicit"

    # Method 2: manifest-derived topics from skill name in prompt
    if not filenames:
        filenames = _topics_from_manifest(prompt)
        if filenames:
            source = "manifest-fallback"
            try:
                from manifest_metrics import log_manifest_query
                log_manifest_query(
                    "subagent-start-context", "topic_fallback",
                    f"manifest-derived topics={filenames}",
                )
            except Exception:
                pass

    # The CHILD-SIDE REPORTING CONTRACT ships on EVERY dispatch, before any topic.
    #
    # It is built here, ABOVE the old `if not filenames: sys.exit(0)` early return,
    # because that return fires on the COMMON case: a dispatch that names no topics and
    # matches no skill manifest. Building the contract below it would have delivered it
    # only to topic-carrying dispatches — a silent partial rollout, which is the exact
    # failure class the contract itself is about.
    #
    # Relocated here 2026-08-26 from ambient rules/subagent-tool-discipline.md (-7,015 B
    # from every main session; only 45 of 438 measured sessions dispatch a subagent at
    # all). SubagentStart fires before the child's first tool call, so delivery is in
    # time by construction — unlike the parent-side siblings, which no subagent-scoped
    # event can precede. See docs/rule-reference/subagent-tool-discipline.md.
    sections: list[str] = []
    if CONTRACT_PATH.exists():
        try:
            contract = CONTRACT_PATH.read_text(encoding="utf-8").strip()
            if contract:
                sections.append(f"--- {CONTRACT_PATH.name} (REQUIRED) ---\n{contract}")
        except OSError:
            # Never block a dispatch on this read; the parent still verifies returns.
            pass

    # Read each topic file
    for fname in filenames:
        topic_path = TOPICS_DIR / fname
        if topic_path.exists():
            try:
                content = topic_path.read_text(encoding="utf-8").strip()
                sections.append(f"--- {fname} ---\n{content}")
            except Exception:
                pass

    # Also always include recent-sessions.md for episodic memory
    recent = TOPICS_DIR / "recent-sessions.md"
    if recent.exists() and "recent-sessions.md" not in filenames:
        try:
            content = recent.read_text(encoding="utf-8").strip()
            sections.append(f"--- recent-sessions.md ---\n{content}")
        except Exception:
            pass

    # DELIVERY BUDGET ENFORCEMENT. Mirrors auto-topic-loader.py: emit only whole
    # sections that fit and replace the rest with an explicit NOT DELIVERED pointer.
    # Never truncate a section — a partial topic reads as complete, which is worse than
    # an honest absence. The contract is first in `sections`, so it survives eviction:
    # a dropped topic leaves a pointer the agent can act on, while a dropped reporting
    # contract leaves the agent unaware there was one.
    if sections:
        combined = SECTION_SEPARATOR.join(sections)
        if len(combined) > INJECTION_BUDGET_CHARS:
            kept: list[str] = []
            dropped: list[tuple[str, int]] = []
            used = 0
            for piece in sections:
                cost = len(piece) + len(SECTION_SEPARATOR)
                if used + cost <= INJECTION_BUDGET_CHARS:
                    kept.append(piece)
                    used += cost
                else:
                    first = piece.split("\n", 1)[0].strip("- ").strip()
                    dropped.append((first or "section", len(piece)))
            notices = [
                f"NOT DELIVERED: {label} ({size:,} chars) exceeds this hook's "
                f"{INJECTION_BUDGET_CHARS:,}-char delivery budget. Read that file "
                f"directly if this task needs it — it was NOT injected."
                for label, size in dropped
            ]
            combined = SECTION_SEPARATOR.join(kept + notices)
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
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