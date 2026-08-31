---
paths:
  - "**/rules/security-critical-search-verification.md"
  - "**/rules/incidents/security-critical-search-verification.md"
---

# security-critical-search-verification: Incident Narratives

Extracted from `rules/security-critical-search-verification.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## code-graph-calls-edges-resolve-via-heuristic-strategies-suffix

```
WHY: code-graph CALLS edges resolve via heuristic strategies (suffix_match,
     unique_name, type_dispatch, fuzzy). PSM measurement (2026-05-04 baseline,
     `bench/accuracy/baselines/2026-05-04-psm-rust.md`) reports per-strategy
     precision: type_static_dispatch ≥0.95, type_dispatch ~0.90, suffix_match
     0.55-0.95 (Python adversarial as low as 0.00-0.35), unique_name 0.88
     Go / 0.10-0.40 Python. A single CALLS edge is a HYPOTHESIS for any
     strategy below `type_static_dispatch`, not a fact.
```

## voyage-cosine-ranks-by-embedding-similarity-top-1-reflects

```
WHY: Voyage cosine ranks by embedding similarity. Top-1 reflects the model's
     best guess given the query phrasing. The 2026-05-04 PSM eval surfaced a
     median MRR of ~0.5, meaning ~50% of correct results are NOT at rank 1.
     For security-critical queries (where the cost of wrong is breach, not
     a few wasted seconds), top-1 alone is below the safe-action bar.
```

## verified-without-a-quoted-source-excerpt-file-line-citation

```
WHY: "verified" without a quoted source excerpt + file:line citation is
     indistinguishable from "I trust the result." Verification must produce
     a CONFIRMED / FALSE-POSITIVE / AMBIGUOUS verdict tied to a specific
     readable artifact.
```

## a-fail-open-fail-closed-default-allow-deny-or

```
WHY: a fail-open/fail-closed, default-allow/deny, or auth-bypass claim
     must be read from the runtime decision function's actual branches —
     NOT a docstring, code comment, CLAUDE.md/README, or any prose that
     asserts a posture. Prose drifts from code; the docstring is not the
     decision. INCIDENT 2026-06-09: the "OPA reads fail-open" claim came
     from a STALE docstring in `shared/opa_middleware.py`; the runtime
     `_evaluate` actually fails CLOSED for all tools (both exception
     branches `return (False, ...)`). The unverified prose was propagated
     across THREE repos (mcp-servers KB, mcp-infra rubric, claude-knowledge-base
     topic) before being read and corrected (PRs #496/#385/#728). The
     verification artifact is the decision function's branch lines, quoted.
```

## 2026-07-28-elb-17-asserted-false-positive-all

```
WHY: 2026-07-28 ELB.17 — asserted "false positive, all four listeners use
ELBSecurityPolicy-TLS13-1-2-2021-06, AWS's current recommended TLS 1.3 policy"
from confidence, and had already written a suppression task. The backing Config
rule `elbv2-predefined-security-policy-ssl-check` carries a NON-customizable
8-value `sslPolicies` allowlist; ours is absent from it. The discriminator is the
`-Res-` (restricted) token — every accepted TLS-1.2-capable policy is a `-Res-`
variant, ours is the non-restricted one that retains weaker ciphers. Had the
suppression shipped, 4 listeners (2 internet-facing) would have kept weaker
ciphers behind documentation saying they were fine — a control silenced by a
wrong verdict is worse than an unaddressed finding, because it stops being
re-examined. Sibling of the prose-vs-decision-function guard above: there the
wrong source was a docstring, here it was the vendor's compatibility table.
```

## 2026-06-22-f4-credential-census-a-candidate-routing

```
INCIDENT 2026-06-22 F4 credential census: a candidate-routing scheme classed
"HEX-only" candidates as a cheap-downgrade/skip target on the (correct) prior
that 15-char hex is ~99.98% non-secret noise (0.02% confirm-rate vs 13.87%
baseline — measured). But the FULL signal join showed 830 of the HEX-matching
candidates ALSO carried judge=is_credential=TRUE; the safe key was
"HEX-only AND judge-absent," not "HEX-only." A blind downgrade on the partial
key would have silently dropped 830 judge-CONFIRMED candidates = a recall
regression on a recall-primary system. Caught by counting confirmed-positives
under the proposed filter key BEFORE shipping it.
```

## the-trap-a-low-aggregate-confirm-rate-on-a

```
WHY (the trap): a low aggregate confirm-rate on a candidate class ("HEX is mostly
noise") tempts a skip filter, but the class is a UNION over signals — the noisy
bulk hides a confirmed-positive subset. "Mostly noise" ≠ "all noise."
```
