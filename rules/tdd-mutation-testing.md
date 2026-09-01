---
paths:
  - "**/test_*.py"
  - "**/*_test.py"
  - "**/tests/**/*.py"
  - "**/conftest.py"
  - "**/*.spec.ts"
  - "**/*.test.ts"
  - "**/*.spec.js"
  - "**/*.test.js"
---

# Mutation-Testing Verdict Interpretation

Mutation testing is the only way to prove a test actually exercises the branch it
claims to. It is also the only check whose OWN OUTPUT is routinely misread — a
mutation's verdict has FIVE distinct causes, and four of them indict something
other than what they appear to.

**Split from `rules/tdd-quality.md` (2026-07-31), which reached 37,872 of its
38,000-char block.** The two files are path-scoped siblings that load on the
test, code, or configuration surfaces where their decisions apply:

| file | family |
|---|---|
| `tdd-quality.md` | AI test-shortcutting, platform/keyless-CI test env, cross-file pollution |
| this file | interpreting a mutation's verdict, and the harness that produces it |

The item numbers are PRESERVED from the original file, so a cross-reference written
as "item 20 §4" or "item 26" still resolves — it just resolves here now. Every
in-repo reference naming a moved item was repointed to this filename in the same PR
(9 references across 7 files); references that cite only the item NUMBER need no
change. New items here continue the shared sequence rather than restarting at 1.

Incident narratives for both files remain in `rules/incidents/tdd-quality.md`.

## Reading a verdict

| verdict | naive reading | the other causes |
|---|---|---|
| **PASSES** | the test is weak | the FIXTURE never reaches the line (18); the MUTATION is inert (25); the KNOB you set was overwritten (21); the LIVE STATE moved between runs (27) |
| **FAILS** | the test bites | it bit for an unrelated reason — malformed assertion, or a stub modelling the wrong contract (20) |
| **either** | — | the HARNESS manufactured the verdict: unapplied mutation, hang, stale `.pyc`, un-restored tree (24) |
| **unstable** | flaky test, re-run it | the assertion reads unpinnable state, so the two runs never compared the same thing (27) |

A verdict you have not attributed to a cause is not a result. **A verdict you have
not reproduced is not a verdict** — re-run any mutation on a test that reads live
state before believing either outcome (27).

## The numbered case corpus

The individual mutation cases (items 18-41: unreachable fixtures, inert
mutations, overwritten knobs, harness defects, tautological fixtures,
false CAUGHT verdicts) live in
`skills/test-driven-development/references/mutation-verdict-interpretation.md`.
They are read while interpreting a specific verdict, so they load on
demand rather than on every edit. Item numbers are unchanged.
