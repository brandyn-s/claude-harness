# Output File Management

> **Two artifact shapes, do not confuse them.** Each run produces a **run report** with **four core sections** (see `references/report-format.md`: Baseline Health, New Findings, Research Threads, Transfer Analysis). The **cumulative knowledge-base file** `claude-code-research-intelligence.md` is a long-lived index with **eight structural buckets** (below) that the run report's contents get routed into. The 4-section run report is authored each run; the 8 cumulative buckets persist across runs. Both shapes are intentional — do not collapse one into the other.

## First run (no existing research report)

Create `$HOME/Documents/knowledge-base/research/claude-code-research-intelligence.md` with the eight cumulative buckets below. On first run, populate them from the 4-section run report as indicated in parentheses:
- **Table of Contents** (auto-generated index)
- **Architecture Component Index** — maps findings to architecture areas (built from Section 2 component tags)
- **Active Findings** — current research-backed recommendations, HIGH/MEDIUM (from run report Section 2)
- **Research Threads** — tracked convergent research directions (from run report Section 3)
- **Research Radar** — early-stage or tangential findings to monitor (LOW findings from Phase B, plus carry-overs)
- **Experiment Backlog** — queued experiments with designs (from run report Section 4 + Section 2 `[experiment]`-tagged items)
- **Archived** — superseded, retracted, or graduated findings (from run report Section 1 SUPERSEDED/RETRACTED + previous-run items aged out)
- **Citations** — all papers, URLs, and sources referenced (deduplicated union across all sections)

## Subsequent runs

- Append new findings to appropriate sections
- Move stale findings to Archived with reason
- Update Research Threads with new evidence
- Refresh citation list
- Update Table of Contents
- **Maintain a Current State index**: a compact table (finding → status → one-line currency) regenerated each run for the findings the run audited. The cumulative file is append-only and accumulates internally superseded sections (e.g., an Experiment Backlog contradicted by later dispositions); the Current State index is the one authoritative view, and Step 0/Step 1 of the next run reads it instead of reconciling historical sections.
- **Mark superseded sections in place**: when a later section supersedes an earlier one, add a one-line pointer at the TOP of the earlier section ("Superseded by <section> — see line/anchor") rather than leaving the contradiction implicit.

## Persistent Research Questions

The research report maintains an **Active Research Questions** section. On each run:

1. **Load existing questions** from the report's Active Research Questions section
2. **Present them alongside newly generated questions** in Step 3b
3. **Update confidence** after Phase B: Answered (High) / Answered (Medium) / Partial / Unanswered
4. **Archive** questions that have been Answered (High) for 2+ consecutive runs
5. **Resurface** Unanswered questions with reformulated queries

Questions persist across runs, building a cumulative research agenda. Each question tracks: first asked date, current confidence, which runs addressed it, key papers found.

## Snapshots

Before modifying the cumulative report, save a date-stamped snapshot: `$HOME/Documents/knowledge-base/research/YYYY-MM-DD-research-intelligence-snapshot.md`. This enables comparing what changed between runs and rolling back if needed.

Always maintain the Citations section as a deduplicated, chronologically sorted list of all sources referenced in the report.
