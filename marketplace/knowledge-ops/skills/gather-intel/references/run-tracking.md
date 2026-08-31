# Run Tracking -- Rejection Log and Run Metrics

This reference covers the two persistent tracking mechanisms that survive across
/gather-intel runs: the **Rejection Log** (to avoid re-surfacing low-quality findings)
and the **Run Metrics** (to measure signal-to-noise and strategy efficiency over time).

Both live at the bottom of the community report file so they persist across runs.

---

# Rejection Log

Track user rejections to avoid re-surfacing similar low-quality findings on future runs.

## How it works

When the user rejects a finding during the approval step, record it here:

```
| Date | Finding summary | Rejection reason | Category |
|------|----------------|------------------|----------|
| YYYY-MM-DD | (1-line summary) | (why rejected: too speculative, not applicable, already covered, low quality) | (finding category) |
```

## Using the rejection log

In **Step 0** of each run, load the rejection log from the previous report. For each new finding in Phase B/C:
1. Compare against rejection log entries
2. If a new finding is substantially similar to a rejected finding (same topic + same category), **deprioritize** it: move to the bottom of its priority tier and tag `[previously-rejected-similar]`
3. If the user explicitly rejected a CATEGORY of findings (e.g., "skip all framework-specific findings"), apply that filter to all new findings in that category

The rejection log is append-only. It persists across runs in the report file.

---

# Run Metrics

Track efficiency metrics per run to identify which search strategies have the best signal-to-noise ratio.

## Metrics to record (append to report metadata on each run)

```
## Run Metrics -- YYYY-MM-DD
- Start time: HH:MM
- End time: HH:MM
- Web queries executed: N (Tavily: N, Exa: N, X Search: N)
- GitHub queries executed: N
- Total findings before filtering: N
- Total findings after filtering: N
- Findings approved by user: N (filled post-hoc)
- Findings rejected by user: N (filled post-hoc)
- Signal-to-noise ratio: (approved / before-filtering)
- Highest-value finding: (1-line summary)
```

## How to use

1. At the START of each run, record the start time
2. Throughout the run, increment query counters
3. At the END of Phase B, record before-filtering and after-filtering counts
4. After user approval, update approved/rejected counts and compute signal-to-noise
5. Append the metrics block to the report metadata section

Over multiple runs, compare signal-to-noise ratios to identify:
- Which search strategies produce the most actionable findings
- Whether focused runs (with arguments) are more efficient than full runs
- Whether Wave 2+ searches add sufficient value over Wave 1 alone
