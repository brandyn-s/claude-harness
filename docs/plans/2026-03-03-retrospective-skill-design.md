# Retrospective Skill Design

**Date**: 2026-03-03
**Status**: Approved

## Summary

A manual-invocation skill that analyzes session transcripts, memories, and git history from a configurable time window to produce a structured retrospective report with quantitative metrics, narrative analysis, and severity-ranked action items.

## Decisions

- **Invocation**: `/retrospective 48h`, `/retrospective 7d security` (duration + optional focus filter)
- **Default**: 48h window, no focus filter
- **Mode**: `disable-model-invocation: true` (manual only, expensive)
- **Output**: Terminal summary (concise metrics + findings) AND full report file
- **Architecture**: Two-pass pipeline (Python extractor + model synthesis)
- **Distinct from**: `/distill` (single-session errors), `/review-learnings` (memory curation), `/audit-architecture` (infra health)

## Two-Pass Pipeline

### Pass 1: Python Extractor (`~/.claude/scripts/retro-extract.py`)

Scans all JSONL transcripts in `~/.claude/session-transcripts/` within the time window. Extracts per-session:

| Metric | Source |
|--------|--------|
| Session count | transcript file count |
| Total/avg session duration | first/last message timestamps |
| Tool call counts by tool | `tool_use` content blocks |
| Error count + error messages | `tool_result` with `is_error: true` |
| Retry count | sequential duplicate tool names |
| Skills invoked | `Skill` tool calls |
| Repos touched | cwd changes, git commands |
| User request summaries | first `human` message per session |
| Auto-learn status | presence/absence of `.md` learning report |
| Lines of code changed | git log `--shortstat` within time window |

Aggregate metrics computed:
- **Efficiency**: error rate, retry rate, first-try success rate, avg errors/session
- **Coverage**: auto-learn capture rate, skill utilization, domain spread
- **Trends** (when previous retro exists): error rate delta, session count delta, gaps resolved

Output: `~/.claude/retrospectives/extract-YYYY-MM-DD.json`

If focus filter provided, metrics scoped to sessions matching that domain (tool names, repo names, user request keywords).

### Pass 2: Model Synthesis

Reads extracted JSON + git logs + learning reports + topic file git diffs. Produces:

**Terminal summary**:
```
RETROSPECTIVE: Mar 1-3, 2026 (48h)

METRICS
  Sessions: 7 | Avg duration: 42min | Total tool calls: 384
  Errors: 23 (6% error rate) | Retries: 11 | Skills used: 4
  Repos touched: 3 | Lines changed: +847/-312
  Auto-learn: 3/7 sessions captured (43% coverage)

WHAT WENT WELL (3)
  - [details...]

WHAT WENT WRONG (2)
  - [details...]

GAPS (4)
  P1: [action item]
  P2: [action item]
  ...

Full report: ~/.claude/retrospectives/2026-03-03-48h.md
```

**Full report file** (`~/.claude/retrospectives/YYYY-MM-DD-{window}.md`):
- Dashboard (expanded metrics with per-session breakdown)
- Session timeline table (date, duration, request, outcome, errors, tools)
- What Went Well sections (evidence, metrics, why it worked)
- What Went Wrong sections (evidence, metrics, root cause, already captured?)
- Gap Analysis (signal, frequency, recommendation, effort estimate)
- Trends (comparison against previous retrospective if one exists)

## File Layout

```
~/.claude/
  skills/
    retrospective/
      SKILL.md              # Skill definition + workflow
      references/
        report-template.md  # Template for the full report
  scripts/
    retro-extract.py        # Pass 1 Python extractor
  retrospectives/           # Output (gitignored)
    extract-YYYY-MM-DD.json
    YYYY-MM-DD-{window}.md
```

## Workflow Steps (SKILL.md instructs)

1. Parse args - extract time window and optional focus filter
2. Run `retro-extract.py --window {hours} [--focus {domain}]` via Bash
3. Read the output JSON
4. Read any existing learning reports (.md) from transcript dir within window
5. Run `git log --all --shortstat --since="{window}"` across known repos
6. Read previous retrospective file (if exists) for trend comparison
7. Synthesize report following template
8. Write full report to `~/.claude/retrospectives/YYYY-MM-DD-{window}.md`
9. Print terminal summary

## Scope Boundaries

**Does**: Read/analyze transcripts, compute metrics, produce narrative + action items, compare trends
**Does NOT**: Write to topic files/MEMORY.md/rules, curate memory, audit infra, auto-execute recommendations

## Dependencies

Python stdlib only (json, os, glob, datetime, re, collections). No pip installs.
`retrospectives/` directory gitignored.
