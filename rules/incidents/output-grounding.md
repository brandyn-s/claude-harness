---
paths:
  - "**/skills/_shared/output-grounding.md"
  - "**/rules/incidents/output-grounding.md"
---

# output-grounding: Incident Narratives

Extracted from the output-grounding contract (now `skills/_shared/output-grounding.md`) to keep it small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## knowledge-asymmetric-outputs-require-trust-calibration-without

```
WHY: knowledge-asymmetric outputs require trust calibration. Without
     explicit HIGH/MEDIUM/LOW labels (or % values), users cannot
     tell which claims they should spot-check vs accept. Overconfident
     output is the most common failure mode in domain-naive review
     (AI Scientist v2 57% false-data rate on peer-reviewed papers,
     byteiota 2026).
```

## provenance-is-gameable-individually-but-auditable-collectively

```
WHY: provenance is gameable individually but auditable collectively.
     Without source URLs / DOIs / `[INFERRED]` tags, the user has
     no anchor to spot-check. The 57% false-data finding shows that
     plausible-sounding rationale text WITHOUT grounded source is
     worse than honest "I don't know" — it gives users false confidence.
```

## explanations-alone-do-not-reliably-improve-trust-calibration

```
WHY: explanations alone do NOT reliably improve trust calibration
     (well-replicated in HCI). The counterfactual-test forces a
     structural check on the recommendation: would this still hold
     if the relationship were inverted? If yes → recombination.
     If no → potential extrapolation. Without this, recombination
     passes as novelty.
```

## verify-later-is-the-failure-mode-the-rule-exists

```
WHY: "verify later" is the failure mode the rule exists to prevent.
     Users without domain expertise cannot retroactively distinguish
     well-grounded recommendations from confidently-stated wrong ones.
     AI Scientist v2 incident: 57% false data rate caught by
     independent re-review, NOT by "I'll verify later."
```

## class-ai-scientist-v2-byteiota-2026-57-false-data

```
INCIDENT class: AI Scientist v2 (byteiota 2026, 57% false-data
rate on peer-reviewed papers). Reviewer cannot catch fabrication
without domain expertise; LLM-generated text reads like research-
prose by construction.
```

## class-opus-4-7-kintal-t4-mode-collapse-5

```
INCIDENT class: Opus 4.7 KINTAL T4 mode-collapse. "5 different
approaches" returned as 5 paraphrases. Without counterfactual-test
and ordinary-persona checks, mode-collapse passes as variety.
```
