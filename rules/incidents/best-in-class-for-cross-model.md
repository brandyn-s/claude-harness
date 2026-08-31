---
paths:
  - "**/rules/best-in-class-for-cross-model.md"
  - "**/rules/incidents/best-in-class-for-cross-model.md"
---

# best-in-class-for-cross-model: Incident Narratives

Extracted from `rules/best-in-class-for-cross-model.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## the-entire-value-of-a-cross-provider-second-rater

```
WHY: the entire value of a cross-provider / second-rater / panel task is
     INDEPENDENT corroboration. If one arm is mid-tier, a disagreement is
     ambiguous (real signal vs the weak model erring) and an agreement is
     weak (the strong model may be carrying it). Either way the conclusion
     is confounded. Best-in-class on EVERY arm is what makes the comparison
     interpretable.
```

## cross-provider-is-satisfied-by-vendor-diversity-but-validity

```
WHY: "cross-provider" is satisfied by vendor diversity, but VALIDITY needs
     each vendor's strongest generally-available reasoning model — OpenAI
     GPT-flagship, Google Gemini-flagship, Anthropic Opus-flagship, a vendor
     flagship on Bedrock — NOT the cheap/fast/mid SKU (Nova Pro, a -mini /
     -lite / -haiku tier) that happened to be reachable. Reachable != best.
```

## when-the-best-in-class-model-is-blocked-no

```
WHY: when the best-in-class model is blocked (no key, Legacy/30-day lock,
     provisioned-only, rate-limited), the correct move is to SURFACE the
     block and ask how to proceed — NOT to quietly substitute a mid-tier
     model and present the result as if the bar were met. Silent downgrade
     is exactly how the 2026-06-29 confounded finding shipped.
```
