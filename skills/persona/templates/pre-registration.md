# Pre-registration template (rubric mode)

Copy this file to `pre-registration.md` in the run dir. Fill in BEFORE
first dispatch. Git-commit it. The harness checks the commit
timestamp predates the first dispatch's `STARTED.lock`.

If you edit this file after `STARTED.lock` exists, the harness flags
the run as "post-hoc rubric edit" with a loud warning.

---

```markdown
# Pre-registration — <run slug>

**Date authored**: YYYY-MM-DD
**Author**: <name>
**Git commit hash (filled by harness)**: <auto>

## Hypothesis

<What is being tested? E.g., "Does dispatch reproducibly identify all
3 known root causes of code-graph's Go precision plateau?">

## Problem statement

<Full structured problem statement. Symptoms + constraints + question.
This is what every persona will see. Per F6: structured statements
with explicit symptoms make rubric scoring interpretable.>

## Ground truth

### Known root causes

**RC1 — <short name>**

Endorsed iff persona proposes:
- (a) <criterion 1>, AND
- (b) <criterion 2>

Rejected iff persona explicitly argues against <RC1's intervention>.

NOT endorsed if persona just says "<generic phrase>" without the
specific articulation in (a) or (b).

**RC2 — <short name>**

[Same structure as RC1]

**RC3 — <short name>**

[Same structure as RC1]

### Known false leads

**FL1**: <short>. Persona output mentioning this counts as FL endorsement
unless the stance check shows rejection ("not the issue", "rule out").

**FL2** through **FL5**: same.

## Keyword sets

**RC1 keywords** (case-insensitive):
- "phrase 1", "phrase 2", "phrase 3"

**RC2 keywords**:
- ...

**RC3 keywords**:
- ...

**FL keyword sets**:
- FL1: ...
- FL2: ...

## Stance check (negation-context detection)

Within 30 chars before each matched keyword, look for:
- "should not", "avoid", "not the issue", "ignore", "rule out",
  "is not the cause", "isn't the cause", "don't bother"

If matched, classify the keyword hit as REJECT not ENDORSE.

## LLM-judge instructions

The LLM-judge (Opus 5 at high effort by default) receives this rubric verbatim plus
the persona output. It outputs a JSON object:

```
{
  "rc1": "endorse | reject | orthogonal | absent",
  "rc2": "endorse | reject | orthogonal | absent",
  "rc3": "endorse | reject | orthogonal | absent",
  "fl_endorsed": [list of FL ids endorsed-as-fix],
  "off_rubric_actionable_count": <int>,
  "off_rubric_examples": [up to 3 short quotes],
  "kappa_check_notes": "<one sentence on rubric ambiguity>"
}
```

The judge is instructed to be strict — endorsement requires both
criteria (a) AND (b) per the rubric. "Orthogonal" means the persona
didn't engage with that root cause.

## Cohort selection

- N: <e.g., 15>
- Sampling rule: <bucket-coverage | random | curated>
- If curated, framework IDs: <list>
- Inventory: <path or "canonical-2026-04-29">
- Seed: <e.g., 42 or "auto" for deterministic-from-slug>
- Persona requested model / effort: <model> / <effort or unset>
- Judge requested model / effort: <model> / <effort>
- Covered-model retention approval: <not applicable | approved lane>

## Stopping rule

Run all <N> personas. No early stopping based on intermediate results.

If a persona dispatch returns an API error, retry once. If the retry
fails, exclude that persona and report n_excluded in analysis.

## Pre-dispatch sanity check

[Optional] One-paragraph note: "I expect <pattern> based on <reason>."
Lock prediction here so post-hoc rationalization is detectable.

## Stopping conditions for the run

This run is complete when:
- All N personas dispatched
- B2-keyword and B2-LLM-judge scores recorded for each
- Inter-rater kappa computed per RC
- Off-rubric actionable count tallied
- analysis.md written
- INDEX.md cross-link appended

## Notes / caveats

[Any context not captured above. Anything that, if missing,
post-hoc analysis might fill in incorrectly.]
```

---

## After committing

Once you've filled in this template, run:

```
git add pre-registration.md
git commit -m "Pre-registration: <slug>"
```

The harness reads the commit timestamp via `git log -1 --format=%ct
pre-registration.md`. First dispatch's `STARTED.lock` must postdate
this timestamp.

## Post-hoc edits

If you genuinely need to fix a pre-reg issue (typo, ambiguous
criterion):
1. Document the edit in the commit message ("fix: clarify RC2
   criterion (b) wording, no semantic change")
2. The harness will warn but proceed
3. analysis.md will note: "post-hoc edit at <timestamp>; reviewer
   should evaluate whether semantics changed"

If the edit changes semantics (e.g., adds a new RC or moves a keyword
from RC1 to RC3), abandon this run and start fresh in a new dated
run dir. **Don't try to salvage a contaminated pre-registration.**
