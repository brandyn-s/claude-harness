# Run Tracking — Rejection Log, Run Metrics, Evaluation Prompts

Operational reference for tracking skill quality and efficiency across runs.

## Rejection Log

Track user rejections to avoid re-surfacing similar low-quality findings on future runs.

### How it works

When the user rejects a finding during the approval step, record it here:

```
| Date | Finding summary | Rejection reason | Category |
|------|----------------|------------------|----------|
| YYYY-MM-DD | (1-line summary) | (why rejected: too speculative, not applicable, already covered, low quality) | (finding category) |
```

### Using the rejection log

In **Step 0** of each run, load the rejection log from the previous report. For each new finding in Phase B/C:
1. Compare against rejection log entries
2. If a new finding is substantially similar to a rejected finding (same topic + same category), **deprioritize** it: move to the bottom of its priority tier and tag `[previously-rejected-similar]`
3. If the user explicitly rejected a CATEGORY of findings (e.g., "skip all framework-specific findings"), apply that filter to all new findings in that category

The rejection log is append-only. It persists across runs in the report file.

**Absence tolerance**: if the previous report has no Rejection Log section (true for all reports written before 2026-08-22), note "rejection log: absent" and continue — do not search for it elsewhere. **Emission is mandatory**: every run's appended report section includes a Rejection Log table, even when empty, so the next run's Step 0 always finds one.

## Run Metrics

Track efficiency metrics per run to identify which search strategies have the best signal-to-noise ratio.

### Metrics to record (append to report metadata on each run)

```
## Run Metrics — YYYY-MM-DD
- Start time: HH:MM
- End time: HH:MM
- Web queries executed: N (Tavily: N, Exa: N)
- GitHub queries executed: N
- Total findings before filtering: N
- Total findings after filtering: N
- Findings approved by user: N (filled post-hoc)
- Findings rejected by user: N (filled post-hoc)
- Signal-to-noise ratio: (approved / before-filtering)
- Highest-value finding: (1-line summary)
```

### How to use

1. At the START of each run, record the start time
2. Throughout the run, increment query counters
3. At the END of Phase B, record before-filtering and after-filtering counts
4. After user approval, update approved/rejected counts and compute signal-to-noise
5. Append the metrics block to the report metadata section

Over multiple runs, compare signal-to-noise ratios to identify:
- Which search strategies produce the most actionable findings
- Whether focused runs (with arguments) are more efficient than full runs
- Whether Wave 2+ searches add sufficient value over Wave 1 alone

## Evaluation Prompts

Use these with the `scripts/run-skill-evals.py` eval harness to measure skill output quality before and after changes.

### Eval 1: Full-scope research refresh
**Prompt**: `/gather-research`
**Grade on**:
1. Were research questions decomposed before searching? (yes/no)
2. Did Wave 1 fire 8+ search calls in a single parallel message? (count)
3. Did adversarial search fire for each HIGH/MEDIUM finding? (yes/no)
4. Were convergence checks applied after Wave 2? (yes/no)
5. Did the report include all 4 sections? (yes/no)

### Eval 2: Focused area search
**Prompt**: `/gather-research agent memory`
**Grade on**:
1. Were ALL queries focused on agent memory? (yes/no)
2. Were research questions specific to memory subtopics? (count of distinct subtopics)
3. Did transfer analysis map to specific architecture files? (yes/no)

### Eval 3: Currency audit accuracy
**Prompt**: `/gather-research` (with existing report containing 10+ findings)
**Grade on**:
1. Were existing findings audited for currency before new searches? (yes/no)
2. Were SUPERSEDED/EVOLVED findings correctly identified? (count)
3. Did MISAPPLIED detection compare paper methodology to implementation? (yes/no)
