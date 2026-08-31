# Retrospective Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a `/retrospective` skill that analyzes session transcripts from a configurable time window and produces a metrics-rich report with narrative analysis and severity-ranked action items.

**Architecture:** Two-pass pipeline. Pass 1 is a Python script (`retro-extract.py`) that parses JSONL transcripts and outputs structured JSON. Pass 2 is the SKILL.md workflow that reads the JSON, git logs, and learning reports, then synthesizes the final report. Output goes to both terminal (summary) and file (full report).

**Tech Stack:** Python 3.12 stdlib only (json, os, glob, datetime, re, collections, argparse, pathlib). Skill is standard SKILL.md markdown.

---

### Task 1: Create the scripts directory and gitignore updates

**Files:**
- Create: `~/.claude/scripts/` (directory)
- Create: `~/.claude/retrospectives/` (directory)
- Modify: `~/.claude/.gitignore`

**Step 1: Create directories**

Run:
```bash
mkdir -p $HOME/.claude/scripts && mkdir -p $HOME/.claude/retrospectives
```

**Step 2: Add gitignore entry for retrospectives/**

Add `retrospectives/` to `~/.claude/.gitignore` after the existing `session-transcripts/` line:

```gitignore
retrospectives/
```

The `scripts/` directory should NOT be gitignored - we want the extractor script tracked.

**Step 3: Verify**

Run:
```bash
ls -d $HOME/.claude/scripts $HOME/.claude/retrospectives
```
Expected: Both directories listed.

Run:
```bash
grep retrospectives $HOME/.claude/.gitignore
```
Expected: `retrospectives/`

---

### Task 2: Write the Python extractor script

**Files:**
- Create: `~/.claude/scripts/retro-extract.py`

This is the largest deliverable. The script:
- Accepts `--window HOURS` (default 48) and optional `--focus DOMAIN`
- Scans `~/.claude/session-transcripts/*.jsonl` for files within the time window
- Parses each JSONL file line by line
- Extracts per-session metrics into a structured dict
- Computes aggregate metrics
- Writes output JSON to `~/.claude/retrospectives/extract-YYYY-MM-DD.json`

**Step 1: Write the script**

Create `~/.claude/scripts/retro-extract.py` with this content:

```python
#!/usr/bin/env python3
"""Extract metrics from Claude Code session transcripts for retrospective analysis."""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path

TRANSCRIPTS_DIR = Path.home() / ".claude" / "session-transcripts"
OUTPUT_DIR = Path.home() / ".claude" / "retrospectives"
KNOWN_REPOS = [
    "$HOME/Documents/GitHub/mcp-servers",
    "$HOME/Documents/GitHub/mcp-infra",
    "$HOME/.claude",
    "$HOME/Documents/GitHub/example-monorepo",
    "$HOME/Documents/GitHub/example-compliance-repo",
    "$HOME/Documents/GitHub/example-sbom-tool",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Extract session transcript metrics")
    parser.add_argument("--window", type=int, default=48, help="Time window in hours (default: 48)")
    parser.add_argument("--focus", type=str, default=None, help="Optional domain focus filter")
    return parser.parse_args()


def get_transcripts_in_window(hours):
    """Find all .jsonl transcript files modified within the time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    transcripts = []
    for path in sorted(glob(str(TRANSCRIPTS_DIR / "*.jsonl"))):
        # Parse timestamp from filename: YYYY-MM-DD-HH-MM-{session_id}.jsonl
        basename = os.path.basename(path)
        match = re.match(r"(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})-", basename)
        if match:
            try:
                file_time = datetime.strptime(match.group(1), "%Y-%m-%d-%H-%M").replace(tzinfo=timezone.utc)
                if file_time >= cutoff:
                    transcripts.append(path)
            except ValueError:
                continue
    return transcripts


def extract_session_metrics(filepath):
    """Parse a single JSONL transcript and extract metrics."""
    session = {
        "file": os.path.basename(filepath),
        "timestamps": [],
        "tool_calls": Counter(),
        "errors": [],
        "error_count": 0,
        "retries": 0,
        "skills_invoked": [],
        "cwds": set(),
        "user_requests": [],
        "token_usage": {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0},
    }

    prev_tool_name = None

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec_type = record.get("type")
            timestamp = record.get("timestamp")
            if timestamp:
                session["timestamps"].append(timestamp)

            # Track CWD changes
            cwd = record.get("cwd")
            if cwd:
                session["cwds"].add(cwd.replace("\\", "/"))

            if rec_type == "user":
                msg = record.get("message", {})
                content = msg.get("content")
                # Human text is a plain string; tool results are a list
                if isinstance(content, str) and content.strip():
                    session["user_requests"].append(content.strip()[:200])
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            # Check for errors in tool results
                            if block.get("is_error"):
                                err_content = block.get("content", "")
                                if isinstance(err_content, list):
                                    err_text = " ".join(
                                        b.get("text", "") for b in err_content if isinstance(b, dict)
                                    )
                                elif isinstance(err_content, str):
                                    err_text = err_content
                                else:
                                    err_text = str(err_content)
                                session["errors"].append(err_text[:300])
                                session["error_count"] += 1

            elif rec_type == "assistant":
                msg = record.get("message", {})
                content = msg.get("content", [])
                usage = msg.get("usage", {})

                # Accumulate token usage
                session["token_usage"]["input"] += usage.get("input_tokens", 0)
                session["token_usage"]["output"] += usage.get("output_tokens", 0)
                session["token_usage"]["cache_read"] += usage.get("cache_read_input_tokens", 0)
                session["token_usage"]["cache_create"] += usage.get("cache_creation_input_tokens", 0)

                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            session["tool_calls"][tool_name] += 1

                            # Detect retries (same tool called consecutively)
                            if tool_name == prev_tool_name:
                                session["retries"] += 1
                            prev_tool_name = tool_name

                            # Track skill invocations
                            if tool_name == "Skill":
                                skill_input = block.get("input", {})
                                skill_name = skill_input.get("skill", "unknown")
                                session["skills_invoked"].append(skill_name)
                        else:
                            prev_tool_name = None

    # Compute duration from timestamps
    if session["timestamps"]:
        times = []
        for ts in session["timestamps"]:
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                times.append(t)
            except (ValueError, AttributeError):
                continue
        if times:
            session["start_time"] = min(times).isoformat()
            session["end_time"] = max(times).isoformat()
            session["duration_minutes"] = round((max(times) - min(times)).total_seconds() / 60, 1)

    # Check for auto-learn report
    base = os.path.splitext(os.path.basename(filepath))[0]
    learning_report = TRANSCRIPTS_DIR / f"{base}.md"
    session["has_learning_report"] = learning_report.exists()

    # Clean up non-serializable fields
    session["cwds"] = sorted(session["cwds"])
    session["tool_calls"] = dict(session["tool_calls"])
    del session["timestamps"]

    return session


def compute_aggregates(sessions):
    """Compute aggregate metrics across all sessions."""
    total_tool_calls = sum(sum(s["tool_calls"].values()) for s in sessions)
    total_errors = sum(s["error_count"] for s in sessions)
    total_retries = sum(s["retries"] for s in sessions)
    durations = [s["duration_minutes"] for s in sessions if "duration_minutes" in s]

    # Tool usage across all sessions
    all_tools = Counter()
    for s in sessions:
        all_tools.update(s["tool_calls"])

    # All skills used
    all_skills = []
    for s in sessions:
        all_skills.extend(s["skills_invoked"])

    # All CWDs (proxy for repos touched)
    all_cwds = set()
    for s in sessions:
        all_cwds.update(s["cwds"])

    # Auto-learn coverage
    sessions_with_reports = sum(1 for s in sessions if s["has_learning_report"])

    # Token totals
    total_input = sum(s["token_usage"]["input"] for s in sessions)
    total_output = sum(s["token_usage"]["output"] for s in sessions)
    total_cache_read = sum(s["token_usage"]["cache_read"] for s in sessions)
    total_cache_create = sum(s["token_usage"]["cache_create"] for s in sessions)

    return {
        "session_count": len(sessions),
        "total_duration_minutes": round(sum(durations), 1) if durations else 0,
        "avg_duration_minutes": round(sum(durations) / len(durations), 1) if durations else 0,
        "total_tool_calls": total_tool_calls,
        "total_errors": total_errors,
        "total_retries": total_retries,
        "error_rate": round(total_errors / total_tool_calls, 4) if total_tool_calls else 0,
        "retry_rate": round(total_retries / total_tool_calls, 4) if total_tool_calls else 0,
        "first_try_success_rate": round(1 - (total_retries / total_tool_calls), 4) if total_tool_calls else 1,
        "avg_errors_per_session": round(total_errors / len(sessions), 1) if sessions else 0,
        "tool_usage_ranking": dict(all_tools.most_common(20)),
        "unique_skills_used": sorted(set(all_skills)),
        "skill_invocation_count": len(all_skills),
        "unique_cwds": sorted(all_cwds),
        "domain_spread": len(all_cwds),
        "autolearn_captured": sessions_with_reports,
        "autolearn_total": len(sessions),
        "autolearn_rate": round(sessions_with_reports / len(sessions), 2) if sessions else 0,
        "tokens": {
            "total_input": total_input,
            "total_output": total_output,
            "total_cache_read": total_cache_read,
            "total_cache_create": total_cache_create,
        },
    }


def apply_focus_filter(sessions, focus):
    """Filter sessions to those matching the focus domain keyword."""
    if not focus:
        return sessions
    focus_lower = focus.lower()
    filtered = []
    for s in sessions:
        # Match against: tool names, CWDs, user requests, skills
        haystack = " ".join([
            " ".join(s["tool_calls"].keys()),
            " ".join(s["cwds"]),
            " ".join(s["user_requests"]),
            " ".join(s["skills_invoked"]),
        ]).lower()
        if focus_lower in haystack:
            filtered.append(s)
    return filtered


def main():
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find transcripts in window
    transcripts = get_transcripts_in_window(args.window)
    if not transcripts:
        print(json.dumps({"error": f"No transcripts found in the last {args.window}h"}, indent=2))
        sys.exit(0)

    # Extract per-session metrics
    sessions = []
    for t in transcripts:
        try:
            session = extract_session_metrics(t)
            sessions.append(session)
        except Exception as e:
            print(f"Warning: Failed to parse {t}: {e}", file=sys.stderr)

    # Apply focus filter
    if args.focus:
        sessions = apply_focus_filter(sessions, args.focus)
        if not sessions:
            print(json.dumps({
                "error": f"No sessions matched focus filter '{args.focus}' in the last {args.window}h"
            }, indent=2))
            sys.exit(0)

    # Compute aggregates
    aggregates = compute_aggregates(sessions)

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.window,
        "focus_filter": args.focus,
        "aggregates": aggregates,
        "sessions": sessions,
    }

    # Write output
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / f"extract-{today}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

**Step 2: Verify the script runs without errors**

Run:
```bash
python3 $HOME/.claude/scripts/retro-extract.py --window 1
```
Expected: Either valid JSON output or `{"error": "No transcripts found in the last 1h"}`. No Python exceptions.

**Step 3: Run with actual data**

Run:
```bash
python3 $HOME/.claude/scripts/retro-extract.py --window 48
```
Expected: JSON with `aggregates` and `sessions` arrays populated. Verify `session_count > 0`, `tool_calls` has entries, `timestamps` parsed correctly.

---

### Task 3: Write the report template

**Files:**
- Create: `~/.claude/skills/retrospective/references/report-template.md`

**Step 1: Create the references directory**

Run:
```bash
mkdir -p $HOME/.claude/skills/retrospective/references
```

**Step 2: Write the template**

Create `~/.claude/skills/retrospective/references/report-template.md`:

```markdown
# Retrospective: {date_range} ({window})

## Dashboard

| Metric | Value |
|--------|-------|
| Sessions | {session_count} |
| Total duration | {total_duration}min |
| Avg session duration | {avg_duration}min |
| Total tool calls | {total_tool_calls} |
| Errors | {total_errors} ({error_rate}% error rate) |
| Retries | {total_retries} ({retry_rate}% retry rate) |
| First-try success rate | {first_try_rate}% |
| Skills invoked | {skill_count} unique ({skill_total} total) |
| Repos/dirs touched | {domain_spread} |
| Auto-learn coverage | {autolearn_captured}/{autolearn_total} ({autolearn_rate}%) |
| Tokens (input/output) | {tokens_input} / {tokens_output} |
| Cache (read/create) | {cache_read} / {cache_create} |

## Top Tools

| Tool | Calls |
|------|-------|
| {tool_1} | {count_1} |
| ... | ... |

## Session Timeline

| # | Date | Duration | First Request | Errors | Tool Calls | Skills | Auto-learn |
|---|------|----------|---------------|--------|------------|--------|------------|
| {n} | {date} | {duration}min | {request} | {errors} | {tools} | {skills} | {status} |

## What Went Well

### 1. {title}

**Evidence**: {transcript excerpts, tool call patterns}
**Metrics**: {relevant numbers from the session data}
**Why it worked**: {analysis of what made this successful}

## What Went Wrong

### 1. {title}

**Evidence**: {error messages, retry patterns, wasted loops}
**Metrics**: {error count, retry count, time spent on this issue}
**Root cause**: {analysis}
**Already captured?**: {cross-reference with auto-learn reports and topic files}

## Gap Analysis

### P1: {gap_title}

**Signal**: {what in the data revealed this gap}
**Frequency**: {how many sessions affected, how often it recurs}
**Recommendation**: {concrete action - create skill/hook/rule/memory entry}
**Effort**: {small/medium/large}

### P2: {gap_title}
...

## Trends

{If a previous retrospective file exists in ~/.claude/retrospectives/, compare:}
- Error rate: {current} vs {previous} ({delta})
- Session count: {current} vs {previous}
- New gaps identified: {count}
- Previous gaps resolved: {list}
- Recurring gaps (appeared in both): {list}

{If no previous retrospective exists:}
- First retrospective - no trend data yet. Run again in {window} for comparison.
```

---

### Task 4: Write the SKILL.md

**Files:**
- Create: `~/.claude/skills/retrospective/SKILL.md`

**Step 1: Write the skill**

Create `~/.claude/skills/retrospective/SKILL.md`:

```markdown
---
name: retrospective
description: >
  Use when reviewing what happened across recent sessions - what went well,
  what went wrong, and what gaps exist in skills, hooks, rules, or memory.
  Trigger phrases: "retrospective", "retro", "what happened", "review sessions",
  "weekly review". Do NOT use for single-session error capture (use /distill),
  memory curation (use /review-learnings), or infrastructure audits (use
  /audit-architecture).
argument-hint: "[48h] [focus-domain] - e.g. '7d security', '48h', '1w infrastructure'"
disable-model-invocation: true
---

# Retrospective

Analyze session transcripts from a configurable time window to produce a metrics-rich retrospective report with narrative analysis and severity-ranked action items.

## Step 1: Parse Arguments

Parse the argument string for time window and optional focus filter.

- Format: `{number}{h|d|w}` optionally followed by a domain keyword
- Examples: `48h`, `7d security`, `1w infrastructure`, `` (empty = 48h default)
- Convert to hours: `h` = literal, `d` = multiply by 24, `w` = multiply by 168
- If no argument provided, default to `48h` with no focus filter

## Step 2: Run the Extractor

Run the Python extractor script via Bash:

```
python3 ~/.claude/scripts/retro-extract.py --window {HOURS} [--focus {DOMAIN}]
```

This outputs structured JSON with per-session metrics and aggregates. Read the output directly from stdout.

If the script reports no transcripts found, inform the user and stop.

## Step 3: Gather Supplementary Data

In parallel, gather:

1. **Learning reports**: Read any `.md` files in `~/.claude/session-transcripts/` whose corresponding `.jsonl` falls within the time window. These contain auto-learn findings from high-friction sessions.

2. **Git activity**: Run `git log` across known repos within the time window:
   ```
   git -C {repo_path} log --oneline --shortstat --since="{hours} hours ago" 2>/dev/null
   ```
   Repos: mcp-servers, mcp-infra, ~/.claude, example-monorepo, example-compliance-repo, example-sbom-tool

3. **Previous retrospective**: Check `~/.claude/retrospectives/` for the most recent `.md` report file (not the current one being generated). If found, read it for trend comparison.

4. **Topic file changes**: Run `git -C ~/.claude log --oneline --name-only --since="{hours} hours ago" -- agent-memory/topics/` to see which topic files were updated.

## Step 4: Synthesize the Report

Using the extracted JSON, learning reports, git logs, and previous retro, synthesize the full report following the template in `references/report-template.md`.

**Analysis guidelines:**

- **What Went Well**: Look for sessions with zero errors, high tool call counts (productive), skills that fired correctly, clean git commits. Cite specific metrics.
- **What Went Wrong**: Look for high error counts, retry clusters (same tool called 3+ times in sequence), sessions with errors but no learning report (gap in auto-learn). Quote error messages.
- **Gap Analysis**: Look for patterns across sessions - same errors recurring, tools with consistently high error rates, domains with no skill coverage, sessions where the user had to repeat requests. Each gap gets a P1-P4 severity:
  - P1: Causes repeated failures across multiple sessions
  - P2: Causes friction in individual sessions
  - P3: Missing optimization or convenience
  - P4: Nice-to-have improvement

## Step 5: Write the Report File

Write the full report to:
```
~/.claude/retrospectives/YYYY-MM-DD-{window}.md
```

Where `{window}` is the original window string (e.g., `48h`, `7d`, `1w`).

## Step 6: Print Terminal Summary

Print a concise summary to the terminal:

```
RETROSPECTIVE: {date_range} ({window})

METRICS
  Sessions: {n} | Avg duration: {n}min | Total tool calls: {n}
  Errors: {n} ({n}% error rate) | Retries: {n} | Skills used: {n}
  Repos touched: {n} | Tokens: {input}in/{output}out
  Auto-learn: {n}/{n} sessions captured ({n}% coverage)

WHAT WENT WELL ({count})
  - {one-line summary per item}

WHAT WENT WRONG ({count})
  - {one-line summary per item}

GAPS ({count})
  P1: {gap + recommendation}
  P2: {gap + recommendation}
  ...

Full report: ~/.claude/retrospectives/{filename}
```

## Success Criteria

- Extractor script runs without errors and produces valid JSON
- Every finding in the report cites specific metrics (numbers, not vague claims)
- Gap analysis produces concrete action items (not "improve X" but "create hook for Y")
- Terminal summary fits in one screen (~30 lines)
- Full report follows the template structure exactly
- When a previous retro exists, trends section shows deltas

## Examples

**Example 1: Default 48h retro**
```
/retrospective
```
Runs extractor with `--window 48`, produces full report covering the last 2 days.

**Example 2: Weekly security-focused retro**
```
/retrospective 7d security
```
Runs extractor with `--window 168 --focus security`, scopes analysis to sessions involving security tools (CrowdStrike, Tenable, Airlock MCP calls).

**Example 3: Quick daily check**
```
/retrospective 24h
```
Lightweight retro covering just the last day.
```

---

### Task 5: Verify and commit

**Step 1: Verify file structure**

Run:
```bash
find $HOME/.claude/skills/retrospective -type f && find $HOME/.claude/scripts -type f
```
Expected:
```
~/.claude/skills/retrospective/SKILL.md
~/.claude/skills/retrospective/references/report-template.md
~/.claude/scripts/retro-extract.py
```

**Step 2: Verify script execution**

Run:
```bash
python3 $HOME/.claude/scripts/retro-extract.py --window 48
```
Expected: Valid JSON output with sessions and aggregates.

**Step 3: Verify gitignore**

Run:
```bash
cd $HOME/.claude && git status retrospectives/
```
Expected: `retrospectives/` does not appear in git status (gitignored).

**Step 4: Verify skill appears in Claude Code**

The skill should appear in the skill list on next session or after `/refresh`. Verify `name: retrospective` matches folder name.

**Step 5: Commit all changes**

```bash
cd $HOME/.claude
git add scripts/retro-extract.py skills/retrospective/ .gitignore docs/plans/2026-03-03-retrospective-skill-design.md docs/plans/2026-03-03-retrospective-impl-plan.md
git commit -m "feat: add /retrospective skill with two-pass transcript analysis"
```
