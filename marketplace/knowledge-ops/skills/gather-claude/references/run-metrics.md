# Run Metrics

Track efficiency metrics per run to identify which search strategies have the best signal-to-noise ratio.

## Metrics to record (append to report metadata on each run)

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

## How to use

1. At the START of each run, record the start time
2. Throughout the run, increment query counters
3. At the END of Phase B, record before-filtering and after-filtering counts
4. After user approval, update approved/rejected counts and compute signal-to-noise
5. Append the metrics block to the report metadata section

Over multiple runs, compare signal-to-noise ratios to identify:
- Which search strategies produce the most actionable findings
- Whether focused runs (with arguments) are more efficient than full runs
- Which sources (GitHub issue search, CHANGELOG parse, docs extract, Exa, Tavily) produce the highest per-query yield — SKILL.md Step 9 retired the multi-wave model, so compare per-source signal rather than per-wave

---

## The metric that actually matters: per-step SKIP RATE

Signal-to-noise measures the steps that RAN. It is silent about the steps that
didn't — which is the larger problem, because a step that doesn't run produces no
noise and no signal and therefore never shows up in any ratio.

**Measured 2026-08-02 across the 15 runs recorded in the report's Sources Log**
(count every phrasing — `skipped`, `not run`, `covered by`, `N/A`, `deferred` — not
just the literal "Skipped (logged)" line; the narrow pattern undercounts by ~2.5x):

```
runs mentioning a skip/substitution:  10 of 15  (67%)

Step 5  pain-correlated      6/15  (40%)   <- RETIRED 2026-08-02 on this evidence
Step 11b adversarial         5/15  (33%)   <- mostly legitimate: conditional, N/A
Web track (any)              5/15  (33%)
Step 8  docs/llms.txt        3/15  (20%)
Step 7/7b PR + releases      3/15  (20%)
Step 1b Watching reconcile   0/15  ( 0%)   <- the only SCRIPTED step
```

**Two classes, and only one is rot.** Step 11b's 33% is a *conditional* correctly
not firing ("N/A — no workaround retirement proposed"). Step 5, Web and Step 8 were
skipped for BUDGET, justified as "short window, area sweeps cover it." Distinguish
them before acting: killing a healthy conditional loses a real check.

**The finding.** The single step with a 0% skip rate is the single step backed by a
committed script (`reconcile_watching.py`, shipped 2026-07-23 — and before that it
was improvised differently in three consecutive runs). Everything else is prose.

> **A command runs. A paragraph is optional.**

So the skill's real size problem is not line count (538 lines, over the 500 soft
guideline but not fatally) — it is **prose instructions per run**. Each one competes
for the same execution budget, and the ones carrying a plausible escape hatch lose.

### Consequences adopted 2026-08-02

- **Step 5 deleted.** 40% skip rate, and every skip note gave the same correct
  reason. Its successor (architecture-keyword sweeps) folded into Step 4.
- **Step 12a added as a script** (`report_lifecycle.py`) covering unresolved
  qualification state, the DEFER list, adoption metric, and field/verdict
  completeness — the things that failed on 2026-08-01 precisely because they
  were prose.
- **Convert, do not add.** Before adding a responsibility to this skill, ask whether
  it can be a script invocation. If it can only be a paragraph, expect it to run
  ~70% of the time and size the claim accordingly.

### Re-measure this

Do not carry the table above forward as a fact. Recompute it against the live
Sources Log whenever a step is added, removed, or converted to a script — a skip
rate is a property of the current skill, not a constant.
