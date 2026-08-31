---
paths:
  - "**/rules/validate-to-improve.md"
  - "**/rules/incidents/validate-to-improve.md"
---

# validate-to-improve: Incident Narratives

Extracted from `rules/validate-to-improve.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## all-tests-pass-with-6-unmentioned-issues-ships-the

```
WHY: "all tests pass" with 6 unmentioned issues ships the issues.
     User has to prompt twice to extract work that should be in the
     first response.
```

## memory-search-2026-03-20-8-tools-22-tests

```
INCIDENT memory-search (2026-03-20): 8 tools, 22 tests, 6 issues in
own output — corrupted DB from wrong journal mode, FTS orphans from
INSERT OR REPLACE, loose dedup threshold, integration tests hitting
live DB, zero checkpoint test coverage, docstring typo. Declared
"fully functional." User had to prompt twice.
```

## skills-polish-2026-03-20-9-changes-7-safe

```
INCIDENT skills-polish (2026-03-20): 9 changes, 7 safe metadata, 2
behavior (context:fork on Agent-using skill, model:sonnet on critical
path). Shipped, required corrective PR.
```

## 2026-08-01-gateway-report-a-span-class-bar-fill

```
WHY: 2026-08-01 gateway report — a `<span class="bar-fill">` inside a grid item stayed
`display: inline`, so `width`/`height` were silently ignored per the CSS box model and
ALL FOUR bars of the July-spend chart rendered at ZERO AREA. The chart was blank.

Every declarative check had passed: `validate_palette.js` returned ALL CHECKS PASS on
both light and dark palettes (six checks each — lightness band, chroma floor, CVD
separation, normal-vision floor, contrast), and a tag-balance scan found the markup
well-formed. The colours were correct and the chart was empty, which is exactly the
class of defect a colour validator cannot see.

The bug was invisible in the markup because THE PARENT WORKED. CSS blockifies a grid
container's DIRECT CHILDREN only, so `<span class="bar-track">` correctly honoured
`height: 1.1rem` while its descendant `.bar-fill` did not — the inheritance boundary is
the whole trap. And an inline element with no text content has zero area, so there is no
error, no console warning, and no layout shift: it fails to NOTHING.

Caught only by rendering headless in Chrome and reading the PNG. Fixed with explicit
`display: block` + `min-width: 2px` (so the $0.19 row is a visible hairline rather than
absent) and a CSS comment recording why.

Three related things the same render pass caught, all in the same family:
- **Clipping read as completeness.** A `--window-size=1100,3400` shot truncated at §4 of
  a ~11,360px document; the tail had never been inspected. Fixed by scanning up from the
  bottom row for the last non-uniform row and comparing to the window height.
- **Theme coverage.** The first render came out DARK, so the light-mode contrast WARN
  (green 2.74:1, amber 2.11:1) the validator had flagged was never visually checked.
  Forcing `data-theme="light"` confirmed the direct-value-label mitigation worked.
- **A lone wrapped KPI tile** (7th of 7 in an auto-fit grid) reads as breakage, not
  design — a layout judgment no linter makes.

RECURRED IN THE SAME SESSION on the v2 build: a probe scanning for the series-1 fill
colour returned ZERO matches and briefly read as "the bars are broken again." A colour
HISTOGRAM of the same PNG showed `#3987e5` present with 3,417 pixels — the probe was
wrong (it sampled x in steps of 10 from x=300, left of where the bar track starts). The
second-order lesson: when a verification probe reports absence, distinguish a broken
ARTIFACT from a broken PROBE before believing either.
```

## INCIDENT 2026-08-28 (capability shipped while the copy still denied it)

Measured 2026-08-28: a rename feature
shipped while the portal still told users the URL "cannot be changed after the
deploy"; the user found it in the UI within minutes of the deploy. A code comment
predicting the drift does NOT prevent it — the comment beside that string had named
this exact risk and no one read it.


## 2026-08-28 (session d42ae003) — relocated from the ambient rule

# Never promote a side effect of your own design into a benefit

When an implementation choice produces a consequence the user did not ask for,
report it as a consequence. Do NOT construct a rationale that reframes it as a
feature — that removes the user's ability to reject the tradeoff, because the
tradeoff is no longer visible as one.

Measured 2026-08-28: isolating a launcher's config directory had the side effect
of hiding the engineer's own skills, agents, and memory from that mode. It was
presented as "for regulated-data separation that is usually what you want." The user's
reply named the failure exactly: "Don't tell me about regulated-data separation, that has
nothing to do with skills. This is simply to use Bedrock in AWS GovCloud." The
justification was invented after the fact to fit a decision already made, and it
attached a compliance-sounding word to a change that had no compliance content.
The correct framing was available and one sentence long: the feature selects a
BACKEND, so nothing about the user's tooling should change.

Apply it this way:

- State the mechanism, then the consequence, then who it affects — before any
  argument about whether the consequence is acceptable.
- If a justification occurred to you only AFTER you chose the implementation,
  that is the signal to label it a tradeoff rather than a rationale.
- Name what the change is FOR in the narrowest true terms. A broad framing
  ("separation", "hardening", "compliance") is where invented benefits hide.

GUARD pattern="this side effect is actually desirable because <compliance word>":
  REFUSE. Report it as a consequence and let the user judge it. NO EXCEPTIONS.
GUARD pattern="the isolation is a feature, not a regression":
  Check whether the isolation was REQUIRED by the goal. If not, it is a cost.
