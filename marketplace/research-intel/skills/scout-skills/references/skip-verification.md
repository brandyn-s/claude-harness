# Multi-Model SKIP Verification (Step 3.5 detail)

Three documented failure modes converge here:

1. **Rejection bias** (2026-04-05): "our skill already covers this"
   without reading either skill.
2. **Asymmetric evidentiary burden** (2026-04-29, per
   `symmetric-evidentiary-burden.md`): SKIP verdicts trusted on a lower
   bar than ADOPT verdicts.
3. **Editorial-polish bias** (2026-05-17 roundtable, F-S1): a quorum
   that anchors on "OUR SKILL" only reproduces the same single-skill
   comparison frame across models and SKIP-confirms substantive
   techniques that would actually live in a rule or topic file.

v2 (2026-05-17): the quorum now compares the technique card from Step
2.7 against an **architecture-wide context set** — skill bodies AND
relevant rules / topics / memory snippets — not a single SKILL.md. If
any destination encodes the operationalizable atom, CONFIRMED-COVERED;
if no destination does, GAP-EXISTS even when adjacent topics are
discussed nearby.

## Trigger

Runs ONLY on SKIP-candidate verdicts (Step 3 routing returned "drop").
Adoption candidates (any routing destination) skip this step — they
proceed to Step 4 unchanged. This keeps total external-model calls
bounded at ~50-70% of the technique cards examined, not 100%.

## Skip the quorum entirely when

- The session has 0 SKIP-candidate verdicts (nothing to verify)
- The technique card is empty (Step 2.7 deemed the candidate purely
  editorial)
- Required env vars missing: `XAI_API_KEY`, `OPENAI_API_KEY` (degrade
  gracefully — note in report, proceed without quorum, downgrade
  confidence on remaining SKIPs)

## Workflow

For each SKIP-candidate, run with the technique card + ALL plausible
destination files (not just one):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/scout-skills/scripts/verify_skip.py \
  --technique-card /tmp/scout-skills/technique-cards/<id>.md \
  --community /tmp/scout-skills/scan-fetch-<repo>-<skill>.md \
  --ours ${CLAUDE_PLUGIN_ROOT}/skills/<our-skill>/SKILL.md \
  --ours $HOME/.claude/rules/<related-rule>.md \
  --ours $HOME/Documents/knowledge-base/topics/<related-topic>.md \
  --ours $HOME/.claude/agent-memory/topics/<related-memory>.md
```

`--ours` can be repeated for every plausible destination identified in
Step 3's routing table. The script reads all files, dispatches in
parallel to both adapters (reusing `skills/roundtable/scripts/adapters/`),
parses the verdicts, and returns a quorum decision:

| Exit code | Decision | Action |
|-----------|----------|--------|
| 0 | `SKIP-CONFIRMED` | At least one external model agrees with SKIP. Drop the pattern; record in report. |
| 10 | `REVIEW-NEEDED` | Both external models say GAP-EXISTS or AMBIGUOUS. Return to Step 3, re-read both skills, classify by Step 4 criteria. |
| 20 | `ABSTAIN` | No model confirmed coverage (both errored, or one/both errored with the other returning GAP/AMBIGUOUS). Note in report; treat as SKIP-CONFIRMED with lowered confidence ONLY if both models errored; otherwise proceed to Step 4 re-review. |
| 30 | Bad input | Fix path arguments and retry. |

The JSON output includes per-model verdict + one-line rationale, so a
flip from SKIP to REVIEW-NEEDED comes with a citation showing which
section of our skill the external model thought was inadequate.

## Cost envelope

- ~1 call to each external model per SKIP verdict (max_tokens=800 output — must match scripts/verify_skip.py; the budget gives the model room to emit the trailing VERDICT: line without truncation)
- Typical session: 8-12 patterns examined, ~5-8 SKIPs → 10-16 external calls
- Empirical cost (2026-05-17 scan run): would have been ~12 calls; at
  Grok+GPT pricing, well under $1 per scout-skills run

## When NOT to invoke

Skip Step 3.5 for these cases — the cost outweighs the benefit:

- **SKIP because the pattern is implementation, not adoptable structure**
  (e.g., wshobson Python class definitions that aren't patterns at all).
  These don't need quorum; the SKIP is mechanical, not judgmental.
- **SKIP because community skill is for a different stack** (e.g., .NET
  API design when we don't ship libraries). Domain mismatch, not coverage.
- **SKIP because the pattern is a generic OWASP rehash** with no new
  framing. The base material is well-known; quorum adds noise.

Save quorum verification for **judgmental SKIPs** where the question is
"did our skill already encode this insight?" — not "is this pattern even
applicable?"

## Report integration

The final scout-skills report (Step 5) should include a `Quorum:` line
per SKIP verdict:

```
Confirmed already-adopted (no action):
  - Pre-Conclusion Audit (getsentry/skills) → differential-review L145
    [Quorum: SKIP-CONFIRMED, grok=CONFIRMED-COVERED, gpt=CONFIRMED-COVERED]
  - Three-strike architecture gate (obra/superpowers-skills) → superpowers:systematic-debugging Phase 4.4
    [Quorum: SKIP-CONFIRMED, grok=AMBIGUOUS, gpt=CONFIRMED-COVERED]
```

Flips from SKIP → REVIEW-NEEDED get logged with the external rationale,
so the audit trail captures why the verdict changed.
