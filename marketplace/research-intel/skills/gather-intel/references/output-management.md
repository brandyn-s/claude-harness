# Gather-Intel Output File Management

Reference file for managing the community intelligence report. Read this file during Phase C output operations.

---

## Finding the Current Community Report

The community report uses the naming pattern `claude-code-community-intelligence*.md` in `$HOME/Documents/knowledge-base/research/` (no dash before `*` so the glob also matches the canonical first-run file `claude-code-community-intelligence.md` with no suffix). Use glob to find the most recent file matching this pattern. If multiple files exist, use the one with the latest modification time.

## Snapshots

Before modifying the cumulative community report, save a date-stamped snapshot: `$HOME/Documents/knowledge-base/research/YYYY-MM-DD-community-intelligence-snapshot.md`. This enables comparing what changed between runs and rolling back if needed.

## First Run (no existing community report)

If no community report exists, create `$HOME/Documents/knowledge-base/research/claude-code-community-intelligence.md` (no date suffix - the file is a living document, not a monthly snapshot) with sections:
- **Table of Contents**
- **Active Recommendations** - current community-backed recommendations (HIGH/MEDIUM)
- **Community Threads** - tracked convergent community patterns
- **Community Radar** - early-stage or tangential findings to monitor
- **Experiment Backlog** - queued experiments with designs
- **Archived** - stale, disproven, or graduated findings
- **Sources** - all URLs referenced, deduplicated

## Subsequent Runs

- Save snapshot first (see above)
- Append new findings to appropriate sections
- Move stale findings to Archived with reason and date
- Update Community Threads with new evidence
- Refresh Sources section with new URLs (deduplicated)
- Update Table of Contents

## Persistent Question Bank

The community report maintains an **Active Questions** section. On each run:

1. **Load existing questions** from the report's Active Questions section
2. **Present them alongside newly generated questions** in Step 4b
3. **Update confidence** after Phase B: Answered (High) / Answered (Medium) / Partial / Unanswered
4. **Archive** questions that have been Answered (High) for 2+ consecutive runs
5. **Resurface** Unanswered questions with reformulated queries

Questions persist across runs, creating a cumulative research agenda rather than starting fresh each time. Each question tracks: first asked date, current confidence, which runs addressed it, key sources found.

## Report Metadata Header

Every report update should include the canonical metadata header defined in
`references/report-templates.md`. Use that template verbatim — the
pipe-separated `Run date: YYYY-MM-DD | Claude Code version: vX.Y.Z` form is
the single source of truth and is what `gather-coordination.md` searches for
when detecting prior runs. Do not introduce a `Last updated:` variant; the
two formats previously drifted and caused dual-skill coordination to miss
prior runs.
