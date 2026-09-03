"""PreToolUse ToolSearch hook: query telemetry + redundant-re-select advisory.

v1 (2026-05) BLOCKED 1-2 word bare-keyword queries and suggested select:/
+prefix rewrites, premised on "ToolSearch returns empty 94.5% of the time
on keyword queries."

DEMOTED to telemetry-only on 2026-06-12 by the Fable 5 recurrence
recompute:
  - Clean transcript tool_use inputs: 0/55 bare-keyword queries on this
    host (0/38 Fable 5 turns, 0/12 same-host Opus 4.8 turns) — the
    behavior the block compensated for has collapsed.
  - The strongest prior keep-evidence (16.2% bare-keyword, 2026-05-31
    part-2 reversal) was measured on THIS hook's debug log — which the
    hook itself contaminated: it logged its own unit-test fixtures
    (read / foo bar / crowdstrike) on every test-suite run. 21/21
    bare-keyword entries in this host's log were test fixtures, not
    model queries.
  - The TOOL_HINTS suggestion table had drifted (arxiv / slack / exa /
    code-search rows referenced servers no longer installed), so any
    block would have suggested misroutes.

v2 (2026-07-24) — redundant-re-select advisory (ADVISORY, never blocks):
The 2026-07-24 14d retro proposed "preload high-frequency tool schemas"
to cut the 255 ToolSearch empties (81% of friction-empties). Measurement
REFUTED the preload framing — 252/264 ToolSearch calls (95%) already use
the correct `select:` form, so it is NOT a query-formulation problem and
a PreToolUse hook cannot inject schemas anyway. But the same measurement
found the REAL lever: 53 of 252 select: calls (21%) re-select a tool whose
schema was ALREADY loaded earlier in the session — a redundant round-trip
that returns nothing new and is exactly the "empty" friction. This adds a
one-line advisory naming the already-loaded tools; it never blocks (a
re-select is harmless, just wasteful) and it dedupes per session so the
same reminder doesn't repeat.

What remains: the append-only query log guard audits consume
(~/.claude/debug/toolsearch-queries.log) — with test-vs-production
provenance: when CLAUDE_HOOK_TEST=1 (set by hooks/test-hooks/conftest.py)
neither the log write NOR the session-state write happens, keeping the
production instrument + marker clean.

Always exits 0 (never blocks).
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

SESSION_MARKER_DIR = Path.home() / ".claude" / "session-env"


def _marker_path(session_id=None):
    """Session-scoped marker tracking which tools have been select:-loaded.

    `session_id` is the hook payload's id (env vars are only a fallback).
    """
    sid = str(session_id or os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default")
    SESSION_MARKER_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_MARKER_DIR / f"toolsearch-selected-{sid[:12]}.json"


def _load_selected(p):
    if p.exists():
        try:
            return set(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _mark_selected(p, tools):
    sel = _load_selected(p)
    sel.update(tools)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from atomic_write import atomic_write
        atomic_write(p, json.dumps(list(sel)))
    except Exception:
        try:
            p.write_text(json.dumps(list(sel)), encoding="utf-8")
        except OSError:
            pass


def _select_tools(query):
    """Return the list of tool names in a `select:a,b,c` query, else []."""
    q = query.strip()
    if not q.startswith("select:"):
        return []
    body = q[len("select:"):]
    return [t.strip() for t in body.split(",") if t.strip()]


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    query = tool_input.get("query", "")
    is_test = bool(os.environ.get("CLAUDE_HOOK_TEST"))

    # Redundant-re-select advisory (production only — the marker must not be
    # polluted by test fixtures, same rationale as the telemetry log).
    if not is_test:
        tools = _select_tools(query)
        if tools:
            marker = _marker_path(data.get("session_id") or None)
            already = _load_selected(marker)
            dup = [t for t in tools if t in already]
            if dup and len(dup) == len(tools):
                # EVERY requested tool is already loaded — the whole call is redundant.
                sys.stderr.write(
                    "[toolsearch] ADVISORY: "
                    + ", ".join(dup)
                    + " already loaded this session — this select: returns nothing new. "
                    "Skip re-selecting already-loaded tools; call them directly. "
                    "(advisory only; not blocked)\n"
                )
            _mark_selected(marker, tools)

    # Telemetry log (production only).
    if not is_test:
        log_dir = Path.home() / ".claude" / "debug"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "toolsearch-queries.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()}|{query}|{tool_input.get('max_results', 5)}\n")
        except OSError:
            pass

    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
