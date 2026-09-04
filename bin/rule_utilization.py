#!/usr/bin/env python3
"""Rule utilization: an ambient rule is loaded in 100% of sessions; in what fraction is
its scope actually ACTIVE?

This ranks relocation candidates without needing an owning skill to exist, which is
what the first pilot run showed was the binding limitation (2 of 3 candidates had no
usable owner). The output is wasted-bytes-per-session, which is the number that decides
where to spend descope effort.

DETECTOR HONESTY IS THE WHOLE DESIGN
------------------------------------
The first version of the sibling pilot script produced a confident "KEEP-AMBIENT" from
a detector that was matching `Read` output and the rule's own recommended behaviour. So
this script carries ONLY action-shaped detectors it can defend, and every other
activity-scoped rule is reported as NO-DETECTOR rather than given a number.

  action-shaped = a tool_use NAME, a Skill invocation, or an edit to a specific path.
                  Never a word that could appear in a document the session merely read.

A rule with NO-DETECTOR is not "fine" and not "wasteful" -- it is unmeasured, and
saying so is the point.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path.home() / ".claude/projects/-Users-you"
RULES_DIR = Path.home() / ".claude/rules"
AUTHORING = "11111111-1111-1111-1111-111111111111"

WEB_TOOLS = {"WebSearch", "WebFetch"}
WEB_MCP = ("mcp__tavily__", "mcp__exa__", "mcp__firecrawl__")
AGENT_TOOLS = {"Agent", "Task", "SendMessage"}


@dataclass
class Detector:
    """An action-shaped test. Exactly one of these fields is used per rule."""
    skills: set[str] = field(default_factory=set)
    tools: set[str] = field(default_factory=set)
    tool_prefixes: tuple[str, ...] = ()
    edits_under: tuple[str, ...] = ()
    compaction: bool = False
    why: str = ""


# Only rules whose activity has an unambiguous action signature appear here.
DETECTORS: dict[str, Detector] = {
    "output-grounding": Detector(
        skills={"scout-frontier", "design-evidence-first", "deep-dive", "refine"},
        why="@scope names exactly these four skills",
    ),
    "web-search-preference": Detector(
        tools=WEB_TOOLS, tool_prefixes=WEB_MCP,
        why="a web search is a tool call, not a mention",
    ),
    "agent-delegation": Detector(
        tools=AGENT_TOOLS,
        why="delegation is an Agent/Task tool call",
    ),
    "subagent-verification": Detector(
        tools=AGENT_TOOLS,
        why="scope is 'every Agent dispatch'",
    ),
    "mcp-tool-names": Detector(
        tools={"ToolSearch"}, tool_prefixes=("mcp__",),
        why="MCP discovery is a ToolSearch or mcp__ call",
    ),
    "rule-authoring": Detector(
        edits_under=("rules/",),
        why="scope is authoring/revising a rule -> an edit under rules/",
    ),
    "transcript-over-summary": Detector(
        compaction=True, skills={"retro", "distill", "mega-distill", "capture"},
        why="scope is session-history claims / after a compaction boundary",
    ),
}

# Activity-scoped rules with no defensible action signature. Listed so the gap is
# explicit rather than silently omitted.
NO_DETECTOR = [
    ("eval-shipping-discipline", "eval / judge work"),
    ("security-critical-search-verification", "security-critical search claim"),
    ("red-team-rubric-discipline", "red-team / severity assessment"),
    ("outcome-over-verification", "reporting an outcome"),
    ("symmetric-evidentiary-burden", "audit / refutation"),
    ("compare-by-need", "comparison / worth-adopting"),
    ("reproduce-before-optimize", "empirical task w/ known reference"),
    ("api-doc-lookup", "unfamiliar API call"),
    ("bulk-data", "bulk read/write (detector refuted: matched Read output + compliant --limit)"),
]


@dataclass
class Facts:
    skills: set[str] = field(default_factory=set)
    commands: set[str] = field(default_factory=set)
    tools: Counter = field(default_factory=Counter)
    edit_paths: set[str] = field(default_factory=set)
    compacted: bool = False


def scan(path: Path) -> Facts:
    f = Facts()
    with path.open(errors="replace") as fh:
        for raw in fh:
            s = raw.strip()
            if not s.startswith("{"):
                continue
            try:
                rec = json.loads(s)
            except Exception:
                continue
            if rec.get("isCompactSummary") is True:
                f.compacted = True
            msg = rec.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and "<command-name>" in content:
                for frag in content.split("<command-name>")[1:]:
                    f.commands.add(frag.split("</command-name>")[0].strip().lstrip("/"))
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name = b.get("name") or "?"
                f.tools[name] += 1
                inp = b.get("input") or {}
                if name == "Skill":
                    sk = inp.get("skill")
                    if sk:
                        f.skills.add(str(sk))
                if name in {"Write", "Edit", "NotebookEdit"}:
                    fp = inp.get("file_path")
                    if isinstance(fp, str):
                        f.edit_paths.add(fp)
    return f


def active(f: Facts, d: Detector) -> bool:
    if d.skills & (f.skills | f.commands):
        return True
    if d.tools & set(f.tools):
        return True
    if d.tool_prefixes and any(
        t.startswith(p) for t in f.tools for p in d.tool_prefixes
    ):
        return True
    if d.edits_under and any(
        any(f"/{u}" in p for u in d.edits_under) for p in f.edit_paths
    ):
        return True
    if d.compaction and f.compacted:
        return True
    return False



def _is_path_scoped(text: str) -> bool:
    """True when a rule carries `paths:` frontmatter, so it is NOT ambient.

    Deliberately a local reimplementation rather than an import from
    hooks/rule_context_budget.py: bin/ tools run standalone from any checkout and
    must not depend on the hooks package being importable. The predicate is simple
    enough that duplication is cheaper than the coupling -- but it is asserted
    against the authoritative implementation in the test suite so the two cannot drift.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    close = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
    if close is None:
        return False
    return any(l.strip().startswith("paths:") for l in lines[1:close])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=PROJECT_DIR)
    ap.add_argument("--rules", type=Path, default=RULES_DIR)
    args = ap.parse_args()

    paths = sorted(args.dir.glob("*.jsonl"))
    if len(paths) < 100:
        print(f"FLOOR: {len(paths)} transcripts < 100", file=sys.stderr)
        return 2
    facts = {p.stem: scan(p) for p in paths}
    n = len(paths)

    # ---- validation: known-positive + known-negative on the detector machinery ----
    a = facts.get(AUTHORING)
    if a is None or not {"distill", "mega-distill"} <= a.skills:
        print("VALIDATION FAILED: cannot see the authoring session's Skill calls", file=sys.stderr)
        return 2
    assert a.compacted, "authoring session had 1 compaction boundary; detector missed it"
    never = Detector(tools={"NoSuchToolXyzzy"})
    if any(active(f, never) for f in facts.values()):
        print("VALIDATION FAILED: known-negative detector matched", file=sys.stderr)
        return 2
    print(f"transcripts: {n}    validation: known-positive OK, known-negative 0\n")

    # A PATH-SCOPED rule is NOT "loaded in 100% of sessions" -- the platform delivers
    # it only when a matching file is in play, so counting it here reports a waste
    # figure for bytes that are not being loaded. Measured defect: after
    # rule-authoring was path-scoped (#2149) it kept appearing under the
    # "loaded in 100% of sessions" heading at 6,057 B, overstating both the subset
    # total and the waste. Exclude it and say so, rather than silently dropping it.
    rows = []
    excluded_path_scoped = []
    for rule, d in DETECTORS.items():
        p = args.rules / f"{rule}.md"
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if _is_path_scoped(text):
            excluded_path_scoped.append((rule, len(p.read_bytes())))
            continue
        size = len(p.read_bytes())
        act = sum(1 for f in facts.values() if active(f, d))
        util = act / n
        wasted = size * (1 - util)
        rows.append((wasted, rule, size, act, util, d.why))

    rows.sort(reverse=True)
    print("UTILIZATION — loaded in 100% of sessions, scope active in:")
    print(f"  {'rule':28s} {'bytes':>6s} {'active':>7s} {'util':>7s} {'wasted B/session':>17s}")
    tot_size = tot_waste = 0
    for wasted, rule, size, act, util, why in rows:
        tot_size += size
        tot_waste += wasted
        print(f"  {rule:28s} {size:6d} {act:4d}/{n:3d} {util:6.1%} {wasted:17,.0f}")
    print(f"  {'':28s} {tot_size:6d} {'':8s} {'':7s} {tot_waste:17,.0f}")
    if excluded_path_scoped:
        print("\n  EXCLUDED as path-scoped (delivered on a matching file, not every session):")
        for rule, size in sorted(excluded_path_scoped, key=lambda r: -r[1]):
            print(f"    {rule:28s} {size:6d} B")
    print(f"\n  measured subset: {tot_size:,} B ambient, of which ~{tot_waste:,.0f} B is")
    print(f"  loaded into sessions whose scope never activates ({100*tot_waste/tot_size:.0f}% of the subset).")

    print(f"\nNO-DETECTOR ({len(NO_DETECTOR)} activity-scoped rules) — unmeasured, not cleared:")
    unmeasured = 0
    for rule, scope in NO_DETECTOR:
        p = args.rules / f"{rule}.md"
        if p.is_file():
            b = len(p.read_bytes())
            unmeasured += b
            print(f"  {b:6d}  {rule:38s} {scope}")
    print(f"  {unmeasured:6d}  TOTAL unmeasured activity-scoped bytes")
    print("\n  A NO-DETECTOR rule needs a behavioural A/B, not a transcript scan --")
    print("  there is no action signature to count, which is itself why relocating it")
    print("  is riskier than relocating a rule whose trigger is a tool call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
