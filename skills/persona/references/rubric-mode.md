# Rubric mode workflow

**Goal**: verify dispatch reproducibly finds known answers. Optimized
for verification, regression-testing, model comparison, methodology
validation.

**Aligns with**: F6's validated A2B2 protocol (structured problem +
pre-registered rubric + dual scoring with kappa report).

**F6 finding that shapes this mode**: structured problem statement
(A2) is necessary for rubric scoring to be interpretable. Loose
problem (A1) + rubric scoring returns 0% RC endorsement (uninterpretable).
Therefore rubric mode requires structured problems with explicit
symptoms.

## Pre-registration discipline

Rubric mode requires a pre-registered fixture file BEFORE first
dispatch. The fixture file specifies:
- Problem statement (structured: symptoms + constraints + question)
- Ground truth (RC1, RC2, ... with endorsement/rejection criteria)
- Known false leads (FL1, FL2, ...)
- Keyword sets per RC and FL
- LLM-judge prompt (template loads from rubric.yaml)
- **Provenance** (required) — see "Fixture provenance" below

Pre-registration is a **git-committed timestamp**: the fixture file's
git commit timestamp must predate the first dispatch's `STARTED.lock`
timestamp. The skill checks this automatically on completion. If the
fixture was edited after dispatches started, the analysis is flagged
as "post-hoc rubric edit, not pre-registered."

**Default behavior on post-hoc edit**: warn loudly. Skill prompts the
user to confirm proceeding (matches the user's preference for warn-not-
hard-fail).

## Fixture provenance — circular validation guard (Fix J, 2026-04-30)

Rubric mode validates that dispatch reproducibly endorses pre-specified
root causes. That validation is meaningful only when the fixture was
NOT authored against the same frame that produced the inventory and
prompt template. When fixture-author = inventory-author (or fixture
author consulted the inventory prose while writing keywords), the
rubric measures lexical matching between two artifacts written by the
same hand — not methodology generality.

Every fixture must declare `provenance:` with three fields:

```yaml
provenance:
  fixture_author: <name>
  inventory_authored_by: <name>
  independent: <true|false>
```

The harness behavior:
- **Missing `fixture_author`**: hard fail. Add the field, re-commit
  fixture, re-run.
- **`independent: false`**: continues but prints a NOTE that this run
  validates reproducibility within ONE frame and does not validate
  methodology generality.
- **`independent: true`**: silent — full validation discipline applies.

To get an `independent: true` fixture: have someone who hasn't read
the inventory write the RCs, FLs, and keywords from scratch based only
on the problem statement. Pull RC keywords from a corpus generated
independently of the inventory's prose (e.g., the engineering team's
post-incident docs, not the persona's framework essence).

## CLI override discipline (Fix K, 2026-04-30)

Pre-registration that CLI silently breaks isn't pre-registration. The
harness enforces fixture-wins-over-CLI:

- `--n`, `--sampling`, `--model`, `--effort`, `--judge-model`, and
  `--judge-effort` passed to dispatch
  that **conflict** with fixture values cause a hard fail.
- A `cli_override_attempt.json` file is written to the run dir
  recording the attempted override.
- `--override-fixture` is the explicit opt-out: CLI values are used,
  the run is flagged post-hoc, and the override is logged.

When fixture omits a field, CLI fills it in (or the harness default
applies). When fixture sets a field and CLI doesn't pass it, fixture
wins silently. The conflict path only fires when both are set and
they differ.

## Workflow

### 1. Pre-registration step

Skill checks if `pre-registration.md` and `fixture.yaml` exist in the
run dir. If not, generates from `templates/pre-registration.md` +
`templates/rubric.yaml` and prompts the user (via AskUserQuestion only
once at this step) to fill them in. After confirmation, the skill
git-commits these files with the slug as commit message and records
the commit hash.

### 2. Cohort selection

Same as discovery mode:
- Default N: 15
- Default sampling: bucket-coverage
- Default seed: deterministic
- Inventory: per `--inventory`

### 3. Structured problem dispatch

Each persona receives:
- Detailed framework prompt (≥800w from inventory)
- **Structured** problem statement (full symptoms + constraints +
  question — the A2 variant from F6)
- Standard recommendation request

The structured problem is what makes rubric scoring interpretable. F6
A1B2 returned 0% RC endorsement — without specific symptoms in the
problem, personas can't engage with the answer space.

### 4. Dual scoring (per F6 finding)

Every persona output gets scored TWICE:

**B2-keyword** (programmatic):
- Match recommendations against keyword sets in rubric.yaml
- Apply stance check: keywords preceded by "should not", "avoid",
  "not the issue", etc. → REJECT not ENDORSE
- Output: per-RC and per-FL endorsement / reject / absent

**B2-LLM-judge**. **Current operational default**: Opus 5 at `high`
effort, resolved at run start and recorded in each result's
`runtime_receipt`. The model and effort remain fixture/CLI/environment
configurable. Opus 4.7 and 4.8 kappa results are historical baselines only;
never compare them to Opus 5 without re-running the same pre-registered
fixture and reporting kappa again:
- Pass each output to a separate Anthropic SDK call with the rubric
- Different model than persona model (decouples judging from
  dispatching)
- Output: per-RC endorsement (endorse / reject / orthogonal / absent),
  per-FL stance, off-rubric actionable count, ambiguity notes

Qualification is all-or-nothing for the cohort. A refusal, truncation, invalid
JSON response, provider error, or requested/effective model mismatch in either
the producer or judge lane fails the command closed. Partial typed evidence is
preserved, but analysis/indexing is withheld and the command does not print
`Run complete`. Cached evidence is eligible only when response metadata proves
the effective model equals the requested model and `fallback` is false.

### 5. Inter-rater agreement (kappa)

Compute Cohen's kappa between keyword scoring and LLM-judge per RC.
Report kappa per RC in `analysis.md`. Per F6:

- Kappa < 0.6 on any RC: rubric is too ambiguous; flag and discuss
- Kappa = 0: scorers measure orthogonal constructs (F6 found this
  between B1 casual and B2 rubric — different from this mode's two
  B2 variants)
- Kappa ≥ 0.8: high agreement, scoring is reliable

### 6. Analysis output

`analysis.md` contains:
- **Per-RC endorsement rates**: table of keyword and LLM-judge
  endorsement counts per RC with Cohen's kappa
- **Inter-rater kappa per RC** — with notes on cells that fell below
  the kappa floor (default 0.6) and kappa-paradox guards for
  extreme base rates
- **Off-rubric actionable summary**: examples flagged by LLM-judge as
  novel-but-not-in-rubric (subset for manual review)
- **Methodology notes**: explanation of why keyword and LLM-judge are
  reported separately and never averaged

### 7. INDEX.md cross-link

Append entry to `~/Documents/knowledge-base/research/dispatch-runs/INDEX.md`:
date, slug, mode (rubric), problem (one-line), N, model, key metrics,
link to run dir.

## What rubric mode does NOT do

- Surface novel insights (use discovery mode for that)
- Generate the rubric (the user pre-registers it; skill validates the
  pre-reg)
- Average B1-style and B2-style scores (F6: they measure orthogonal
  constructs; never combine)

## When NOT to use rubric mode

- The team doesn't have known root causes for the problem yet — use
  discovery mode first to surface candidates, then write rubric, then
  rubric-mode for verification
- The goal is finding-novel-framings (rubric mode actively discards
  these as "off-rubric")
- The fixture would need to be invented to fit dispatch's outputs —
  that's p-hacking, run discovery instead

## Historical cost baseline (Haiku 4.5 personas, Opus 4.7 judge)

- 15 personas × ~$0.005 = ~$0.075
- 15 LLM-judge calls × ~$0.05 (Opus) = ~$0.75
- Total typical run: ~$0.85

Sonnet 4.6 judge: ~$0.20 total. Haiku 4.5 judge: ~$0.10 total
(but lower-quality judging — F6 used Opus 4.7 specifically because
the quality differential matters for rubric application).

These values document the dated F6 lane; they are not a current pricing
estimate. Before a new run, estimate cost from the requested current model and
effort and preserve actual token usage plus runtime receipts in the run output.

## Post-run checklist

After rubric-mode completes:
1. Read `analysis.md` for kappa values per RC. If any < 0.6, the
   rubric needs sharpening (consider re-running with revised rubric
   in a new run dir — never edit the original).
2. Review off-rubric actionable examples. Are any genuine novel
   insights? If yes, add as a candidate RC for the next iteration of
   the rubric.
3. If using rubric mode for cross-model comparison, repeat with
   different `--model` values, all using the same fixture and
   pre-registration.
