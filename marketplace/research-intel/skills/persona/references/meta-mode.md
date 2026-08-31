# Meta mode workflow

> **Implementation status (2026-05-02): MANUAL-ONLY.** `dispatch.py::run_meta()`
> is a stub that prints guidance. There is no automated multi-cell loop.
> Users invoke rubric mode N times with different `--slug` suffixes per cell
> and aggregate the run dirs via `scripts/analyze.py`. The workflow below
> describes the *target* design that meta mode would implement; for now,
> follow the manual pattern in the "Worked examples" section at the bottom.

**Goal**: test the methodology itself. Used for scaling experiments,
sampling-rule comparisons, model-effect studies, prompt-detail
ablations.

**Aligns with**: M4 (scaling), M5 (ablation), F6 (fixture validity).

**Critical distinction**: meta mode is research, not problem-solving.
The fixture is whatever's pre-registered for the experiment; the goal
is producing data about WHEN/HOW dispatch works, not solving the
fixture's problem.

## When to use

- Adding a new sampling rule and want to measure its effect
- New model release; replicating prior results to check generalization
- Testing a new framework taxonomy or inventory source
- Probing whether a methodology assumption holds (e.g., "does kappa>0.6
  generalize across fixtures")
- Pre-publication: replicating findings before promoting to a
  permanent methodology rule

## Workflow

### 1. Pre-registration (mandatory)

Same as rubric mode — git-committed pre-registration before first
dispatch. Includes:
- Hypothesis being tested
- Independent and dependent variables
- Predicted direction of effect
- Stopping rule (number of seeds, conditions)
- Multiple-comparison correction method (default: Bonferroni)

The pre-reg file lives in the run dir as `pre-registration.md` and
includes a section explicitly labeled "Methodology hypothesis."

### 2. Variable matrix specification

CLI args support multi-cell experiments:
- `--n 11,25,50,144` runs each N as a separate cell
- `--sampling random,bucket,curated` runs each rule as a separate cell
- `--model haiku,sonnet,opus` runs each model
- `--seeds 5` produces 5 random seeds per cell (variance estimation)

Total cells = product of all axes × seeds. Cost can balloon — skill
warns and confirms when projected cost exceeds $20.

### 3. Cohort sampling per cell

Each (cell, seed) pair gets its own RNG. The same cell with different
seeds produces different cohorts — the variance estimate.

### 4. Dispatches

Per-cell dispatch identical to rubric mode (structured problem +
dual scoring) or discovery mode (loose problem + manual review),
selected via `--inner-mode discovery|rubric`.

Most meta experiments use rubric inner-mode (need quantitative
metrics for cell comparison).

### 5. Statistical analysis

Per-cell metrics aggregated:
- Mean ± stdev across seeds
- ANOVA on cell effect (when ≥3 cells per axis)
- Bonferroni-corrected p-values per pre-registered hypothesis
- Effect size (Cohen's d or equivalent) per axis

### 6. Output structure

`analysis.md` for meta runs has these sections:
- Pre-registration recap
- Per-cell raw metrics
- Marginal effects per axis
- Statistical tests with corrections
- Effect-size estimates
- Confirmation/disconfirmation of pre-registered hypotheses
- Open questions surfaced (for future meta runs)

### 7. Methodology-evolution.md update

After meta-run completes, the user (manually) appends an entry to
`references/methodology-evolution.md` summarizing:
- Date, slug, hypothesis tested
- Result (confirmed / disconfirmed / inconclusive)
- Implication for skill defaults or behavior
- Link to run dir

Skill provides a template for this update; user reviews before
committing.

## Worked examples (from session history)

- **M4 scaling**: 4 cells (N=11/25/50/144) × 1 model × 1 seed.
  Result: saturation at N=11 on this fixture (caveat: F6 showed
  fixture telegraphed answers).
- **M5 ablation**: 2×2 (prompt-detail × code-context) × 1 model × 1
  seed. Result: detailed-prompt + lean-context = lowest FL rate
  (small effect).
- **M4 model replication**: 1 cell (N=11) × 3 models × 1 seed.
  Result: saturation generalizes across model class.
- **F6 fixture validity**: 2×2 (loose vs structured × casual vs rubric).
  Result: kappa=0 between B1 and B2; tradeoff between convergence
  and novelty.

## Cost guard

Meta runs warn-and-confirm when total dispatches exceed:
- 50 (~$2.50 at Haiku, ~$5 at Sonnet, ~$25 at Opus)
- 200 (~$10/$20/$100)

User can override with `--no-cost-warn`.

## Reproducibility

The pre-registration file + git-commit timestamps make meta runs
reproducible. Future researchers (including future-you) can:
- Check out the pre-reg commit
- Read variable matrix spec
- Re-run with the same seeds
- Compare new model results to old

## Caveats

Meta runs measure dispatch behavior on a specific fixture × inventory
× model × scoring combination. Generalization to other fixtures,
inventories, etc. is uncharted unless replicated. F6 documents this
extensively — the synthetic fixture telegraphs answers, which limits
external validity.

The methodology-evolution.md entry should explicitly note the scope
of any meta-run finding (fixture-specific vs across-fixtures, model-
specific vs across-models, etc.).
