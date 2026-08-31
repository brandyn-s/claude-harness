#!/usr/bin/env python3
"""Compliance-sampling harness — measure rule and skill-gate compliance
from real session transcripts (DECIDE item 3, 2026-06-10; B5/F7 + the
skill-improvement program's step-compliance item).

Why: rule effectiveness was the campaign's biggest unmeasured claim —
the rules layer costs ~77.7K tokens/turn and 67% of rules are prose-only
with `enforcement_coverage: none`. Skills are likewise prose contracts:
nothing verified whether mandatory gates (AskUserQuestion checkpoints)
actually fire when a skill runs. This harness turns both questions into
measurements by scanning the transcript JSONL Claude Code already writes
to ~/.claude/projects/.

It is read-only and machine-local: transcripts never leave the machine;
the output is an aggregate markdown block (dated) meant to be pasted as
an entry in AUDIT-TRACKERS/10-compliance-samples.md, so demotion/keep
decisions can cite numbers instead of judgment.

Pilot predicates (extend PREDICATES below as rules gain definitions):
  git-hygiene      sessions with a `git push` should show PR-creation
                   evidence (mcp__github__create_pull_request or
                   `gh pr create`) in the same session.
  bulk-data        MCP tool calls with limit/max_results/page_size >= 100
                   should be followed within 5 events by Bash python
                   script routing (the rule: route bulk pulls to scripts).
  web-search-pref  WebSearch usage where tavily/exa MCP search was used
                   in the same session (rule prefers MCP search).

Skill gate compliance: for every Skill-tool invocation (or
<command-name> marker), if the skill's manifest requires_tools includes
AskUserQuestion, an AskUserQuestion tool_use should appear later in the
same (main-thread) transcript. This is a proxy — it measures "the gate
had a chance to fire and did", not gate quality.

Caveats (read before citing numbers):
- Heuristic predicates over heterogeneous transcripts: treat rates as
  signals for investigation, not verdicts. A "violation" may be a
  legitimate exemption the predicate can't see.
- Sidechain (subagent) transcripts are excluded by default — gates are
  main-thread contracts. --include-sidechains to override.

Usage:
  python3 bin/compliance-sample.py                      # ~/.claude/projects
  python3 bin/compliance-sample.py --transcripts-dir D  # tests / other roots
  python3 bin/compliance-sample.py --json               # machine output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BULK_PARAM_NAMES = {"limit", "max_results", "page_size", "per_page", "perPage"}
BULK_THRESHOLD = 100
BULK_ROUTE_WINDOW = 5  # events after a bulk call in which script routing counts

COMMAND_MARKER_RE = re.compile(r"<command-name>/?([a-z0-9_-]+)</command-name>")


def iter_events(path: Path):
    """Yield (is_sidechain, tool_uses, user_text) per transcript line.

    tool_uses is a list of (name, input_dict). Tolerant of every line
    shape Claude Code writes (compact boundaries, meta lines, results):
    anything unparseable or block-free yields nothing.
    """
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            sidechain = bool(obj.get("isSidechain"))
            tool_uses = []
            user_text = ""
            msg = obj.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and obj.get("type") == "user":
                    user_text = content
                elif isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            name = block.get("name") or ""
                            inp = block.get("input")
                            tool_uses.append(
                                (name, inp if isinstance(inp, dict) else {}))
                        elif block.get("type") == "text" and obj.get("type") == "user":
                            user_text += block.get("text") or ""
            if tool_uses or user_text:
                yield sidechain, tool_uses, user_text


def _bash_command(name: str, inp: dict) -> str:
    if name == "Bash":
        cmd = inp.get("command")
        return cmd if isinstance(cmd, str) else ""
    return ""


def _is_bulk_call(name: str, inp: dict) -> bool:
    if not name.startswith("mcp__"):
        return False
    for k, v in inp.items():
        if k in BULK_PARAM_NAMES:
            try:
                if int(v) >= BULK_THRESHOLD:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _gate_bearing_skills() -> set:
    """Skills whose manifest requires_tools includes AskUserQuestion —
    the mechanical signal that the skill has a user-confirmation gate."""
    gated = set()
    for manifest in (REPO / "skills").glob("*/manifest.yaml"):
        try:
            text = manifest.read_text(encoding="utf-8")
        except OSError:
            continue
        in_block = False
        for line in text.split("\n"):
            if re.match(r"^requires_tools\s*:", line):
                in_block = True
                if "AskUserQuestion" in line:  # inline list form
                    gated.add(manifest.parent.name)
                    break
                continue
            if in_block:
                stripped = line.strip()
                if stripped.startswith("-"):
                    if "AskUserQuestion" in stripped:
                        gated.add(manifest.parent.name)
                        break
                elif stripped and not stripped.startswith("#"):
                    break
    return gated


def analyze_transcript(path: Path, include_sidechains: bool, gated_skills: set) -> dict:
    """Per-session measurements for one transcript file."""
    s = {
        "pushes": 0, "pr_evidence": False,
        "bulk_calls": 0, "bulk_routed": 0,
        "websearch_calls": 0, "mcp_search_calls": 0,
        "skill_invocations": [],   # names in order
        "ask_user_after": {},      # skill -> bool
    }
    events = []
    for sidechain, tool_uses, user_text in iter_events(path):
        if sidechain and not include_sidechains:
            continue
        events.append((tool_uses, user_text))

    pending_gate_skills = []
    for idx, (tool_uses, user_text) in enumerate(events):
        for m in COMMAND_MARKER_RE.finditer(user_text):
            name = m.group(1)
            s["skill_invocations"].append(name)
            if name in gated_skills:
                pending_gate_skills.append(name)
                s["ask_user_after"].setdefault(name, False)
        for name, inp in tool_uses:
            cmd = _bash_command(name, inp)
            if name == "Skill":
                sk = inp.get("skill") or ""
                if sk:
                    s["skill_invocations"].append(sk)
                    if sk in gated_skills:
                        pending_gate_skills.append(sk)
                        s["ask_user_after"].setdefault(sk, False)
            elif name == "AskUserQuestion":
                for sk in pending_gate_skills:
                    s["ask_user_after"][sk] = True
                pending_gate_skills = []
            elif name == "WebSearch":
                s["websearch_calls"] += 1
            elif name.startswith("mcp__") and ("tavily" in name or "exa" in name.lower()) \
                    and ("search" in name):
                s["mcp_search_calls"] += 1
            elif name == "mcp__github__create_pull_request":
                s["pr_evidence"] = True
            if cmd:
                if re.search(r"\bgit\b[^\n|;&]*\bpush\b", cmd):
                    s["pushes"] += 1
                if re.search(r"\bgh\s+pr\s+create\b", cmd):
                    s["pr_evidence"] = True
            if _is_bulk_call(name, inp):
                s["bulk_calls"] += 1
                routed = False
                for later_tools, _t in events[idx + 1: idx + 1 + BULK_ROUTE_WINDOW]:
                    for lname, linp in later_tools:
                        lcmd = _bash_command(lname, linp)
                        if "python" in lcmd:
                            routed = True
                if routed:
                    s["bulk_routed"] += 1
    return s


def aggregate(per_session: list) -> dict:
    n = len(per_session)
    push_sessions = [s for s in per_session if s["pushes"] > 0]
    bulk_total = sum(s["bulk_calls"] for s in per_session)
    skill_counts = {}
    gate_fired = {}
    gate_total = {}
    for s in per_session:
        for sk in s["skill_invocations"]:
            skill_counts[sk] = skill_counts.get(sk, 0) + 1
        for sk, fired in s["ask_user_after"].items():
            gate_total[sk] = gate_total.get(sk, 0) + 1
            if fired:
                gate_fired[sk] = gate_fired.get(sk, 0) + 1
    return {
        "sessions": n,
        "git_hygiene": {
            "push_sessions": len(push_sessions),
            "push_sessions_with_pr": sum(1 for s in push_sessions if s["pr_evidence"]),
        },
        "bulk_data": {
            "bulk_calls": bulk_total,
            "bulk_routed_to_script": sum(s["bulk_routed"] for s in per_session),
        },
        "web_search_pref": {
            "websearch_calls": sum(s["websearch_calls"] for s in per_session),
            "mcp_search_calls": sum(s["mcp_search_calls"] for s in per_session),
        },
        "skill_invocations": dict(sorted(skill_counts.items(),
                                         key=lambda kv: -kv[1])),
        "skill_gates": {
            sk: {"invocations": gate_total[sk],
                 "gate_fired": gate_fired.get(sk, 0)}
            for sk in sorted(gate_total)
        },
    }


def render_markdown(agg: dict) -> str:
    gh = agg["git_hygiene"]
    bd = agg["bulk_data"]
    ws = agg["web_search_pref"]
    lines = [
        f"## Compliance sample ({date.today().isoformat()})",
        "",
        f"Sessions scanned: {agg['sessions']}",
        "",
        "| Predicate | Measure | Value |",
        "|---|---|---|",
        f"| git-hygiene | push-sessions with PR evidence | "
        f"{gh['push_sessions_with_pr']}/{gh['push_sessions']} |",
        f"| bulk-data | bulk calls routed to script (window={BULK_ROUTE_WINDOW}) | "
        f"{bd['bulk_routed_to_script']}/{bd['bulk_calls']} |",
        f"| web-search-pref | WebSearch vs MCP search calls | "
        f"{ws['websearch_calls']} vs {ws['mcp_search_calls']} |",
        "",
        "### Skill gate compliance (AskUserQuestion-bearing skills)",
        "",
    ]
    if agg["skill_gates"]:
        lines += ["| Skill | Invocations | Gate fired |", "|---|---|---|"]
        for sk, v in agg["skill_gates"].items():
            lines.append(f"| {sk} | {v['invocations']} | {v['gate_fired']} |")
    else:
        lines.append("(no gated-skill invocations in sample)")
    top = list(agg["skill_invocations"].items())[:10]
    if top:
        lines += ["", "### Most-invoked skills (sample)", ""]
        lines += [f"- {sk}: {n}" for sk, n in top]
    lines += [
        "",
        "> Heuristic rates — signals for investigation, not verdicts. See",
        "> bin/compliance-sample.py docstring for predicate definitions.",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sample session transcripts for rule + skill-gate compliance.")
    ap.add_argument("--transcripts-dir", default=None,
                    help="Transcript root (default: ~/.claude/projects)")
    ap.add_argument("--include-sidechains", action="store_true",
                    help="Include subagent transcripts (default: main thread only)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    root = Path(args.transcripts_dir).expanduser() if args.transcripts_dir \
        else Path.home() / ".claude" / "projects"
    if not root.is_dir():
        print(f"ERROR: transcripts dir not found: {root}", file=sys.stderr)
        return 2

    transcripts = sorted(root.rglob("*.jsonl"))
    if not transcripts:
        print(f"ERROR: no .jsonl transcripts under {root}", file=sys.stderr)
        return 2

    gated = _gate_bearing_skills()
    per_session = [analyze_transcript(p, args.include_sidechains, gated)
                   for p in transcripts]
    agg = aggregate(per_session)
    if args.json:
        print(json.dumps(agg, indent=2))
    else:
        print(render_markdown(agg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
