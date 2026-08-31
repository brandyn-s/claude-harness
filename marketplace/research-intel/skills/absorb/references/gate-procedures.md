# Phase 4 Gate Procedures — Divergence Analysis, Latent Gap Lifecycle, Verdict Challenge

Consult when executing Phase 4 (gap analysis) for same-team targets, latent-gap
classification, and DEFER/REJECT verdict challenges.

## Same-team divergence analysis (full procedure)

> "Where does [target] diverge from your practice within the same environment?"
>
> Compare: PR size distribution, commit message style, review depth, merge speed,
> branch naming, CI configuration choices. Divergences in shared repos are higher-signal
> than divergences in separate repos — same tools, same constraints, different choices.

This turns "zero recommendations" into "zero gaps but here are the interesting
divergences worth discussing with your teammate."

## Latent gap lifecycle

The latent-gap classification prevents the false-negative problem where genuinely useful
patterns are rejected simply because the pain hasn't been formally documented yet.

- **Promote** when: an incident is documented in the gap's domain, OR the gap becomes
  `[cross-validated: 3+]` across independent developers
- **Prune** when: 6+ months old with no incident and no cross-validation. Change status
  to "pruned" (don't delete — leave the record for dedup)
- **Review** during `/garden` runs: scan `## Latent Gaps` sections across all profiles

## Verdict challenge questions (Step 4b)

| Challenge question | What it catches |
|-------------------|----------------|
| "Is the deferral reasoning a strawman?" | Rejecting a hook when a rule would work; rejecting enforcement when guidance already failed |
| "Are there incidents with different labels that share this root cause?" | Planning failures labeled as "evaluation failures"; verification failures labeled as "audit incidents" |
| "Is 'no documented incident' the same as 'no problem'?" | Diffuse friction not formally documented; problems caught by human oversight that should be caught earlier |
| "Is the implementation cost actually high, or am I inflating it?" | 4-line convention additions deferred as "low priority"; rule additions deferred because "existing rules cover this" when they don't |

### Why the challenge step exists

The 2026-04-05 absorb batch deferred 6 patterns. When 3 were challenged, all 3
flipped to IMPLEMENT — the deferral reasoning was wrong in each case. Root cause:
DEFER requires no evidence ("no incident documented"), while IMPLEMENT requires
positive evidence. This asymmetry biases toward inaction. The challenge step forces
the same evidentiary standard on both verdicts.
