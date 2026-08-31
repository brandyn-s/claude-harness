# gather-claude — Examples, Evaluation Prompts, Measured Efficacy, and Rejection Log

## Measured Efficacy (live arm) — full record

**Verdict: `keep` — measured 2026-05-31, N=3, `claude-opus-4-8`, n=15 (vs fair baseline);
calibration FIX applied + re-measured in the same session.**
Pre-fix, the first-party framework caught more deprecations (refutation_recall 0.944 vs 0.833)
but its over-conservative "UNCHARTED unless first-party-confirmed" rule over-rejected genuine
current features (`effort:`/`/rewind`), regressing true_recall to 0.733 vs 0.933 (the `fix`
finding). The fix — a calibration floor per `uncharted-vs-refuted.md` (SKILL.md Step 13) — eliminated
the regression and flipped it to a lead: post-fix the framework is ≥ baseline on every axis
(true_recall 0.933 vs 0.800, refutation_recall 0.889 vs 0.778, fabrication_resistance 1.0 intact,
overall verdict_accuracy **0.933 vs 0.844, +0.089 primary**). Full before/after, the primary
re-designation (grounding_precision saturates → verdict_accuracy), and the REAL-vs-INSTRUMENT
check: `harness/PROBLEM.md §5–6`; CI gate: `tests/test_gather_claude_efficacy.py`.

## Examples

### Example 1: Routine monthly sync
**Command**: `/gather-claude`
Phase A: 8 workarounds scanned, 1 FIXED (stale rule to remove). Phase B: 3 targeted GitHub searches (40 issues), 6 doc pages extracted, 3 deep-fetched. 12 findings. User approves 4 edits.

### Example 2: Post-upgrade full sweep
**Command**: `/gather-claude full`
No time filter. CHANGELOG parsed for all versions. 4 targeted GitHub searches + broad scan. 20+ findings including 3 stale workarounds. High-value cleanup.

### Example 3: Focused hooks search
**Command**: `/gather-claude hooks`
All queries narrowed to hooks. GitHub: `"hooks" in searches`. Web: query includes "hooks". Tight report with 5-8 findings.

---

## Evaluation Prompts

Use these prompts to measure skill output quality before and after changes — run each prompt manually against the skill, then grade with the rubric below. (No automated skill-evaluation slash command exists in this architecture; manual scoring is the substitute.)

### Eval 1: Routine sync (no prior report)
**Prompt**: `/gather-claude since:2026-03-15`
**Grade on**:
1. Did Phase A scan workaround indicators in baseline files? (yes/no)
2. Did CHANGELOG get parsed version-by-version with compound keyword groups? (yes/no)
3. Were findings verified against actual file content before presenting? (yes/no)
4. Did adversarial search (Step 11b) fire for REMOVE_WORKAROUND findings? (yes/no)
5. Were findings categorized and prioritized per the table? (yes/no)

### Eval 2: Focused area search
**Prompt**: `/gather-claude hooks`
**Grade on**:
1. Were ALL queries narrowed to hooks? (yes/no)
2. Were non-hooks findings filtered out? (yes/no)
3. Did the report contain 3+ hooks-specific findings? (count)

### Eval 3: Post-upgrade full sweep
**Prompt**: `/gather-claude full`
**Grade on**:
1. Was the time filter removed for CHANGELOG parsing? (yes/no)
2. Were 15+ findings generated? (count)
3. Did the report include stale workarounds to remove? (count)

---

## Rejection Log

Track user rejections to avoid re-surfacing similar low-quality findings on future runs.

### How it works

When the user rejects a finding during the approval step, record it in the report:

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
