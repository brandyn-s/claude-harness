# Measurement harness — supergoal prior-arc guard delivery

A `build-measurement-harness` instance for the **superplan/supergoal** planning
skill: does supergoal actually deliver its headline value-prop — **"refuses
re-litigation of prior arcs"** — or does that guard silently no-op for ordinary
plans, so the ceremony is never enforced?

The prior-arc guard (`scripts/check_prior_arcs.py`) is supergoal's mechanism for
refusing to re-run a metric a previous terminal doc already retired (the
`HTTP_CALLS / IMPLEMENTS` "4 PRs, none moved it" failure mode, per
`references/prior-arc-check.md`). It keys **only** on `metric_names`, and on an
empty list it bails before doing anything:

```python
# check_prior_arcs.py
if not metric_names:
    print("PRIOR-ARC: skipped (no metric_names extracted)")
    return 0
```

`metric_names` is produced by `parse_plan.extract_metric_names(text)`. So the guard
is **only as good as that extractor's recall**: every metric name it misses is a
metric the prior-arc ledger can never match, and a plan whose metrics are *all*
missed gets the guard as a silent no-op — the value-prop is undelivered.

This measures the *mechanism's delivery of its value-prop*, deterministically and
offline. It does NOT measure "does prior-arc-checking actually reduce wasted
re-litigation in practice" — that needs a live corpus of related plans + terminal
docs over time (the **live arm**, sketched at the end).

## 1. Classify the measurement
- **Unit:** one plan-markdown snippet → its set of metric names.
- **Decision under test:** `scripts/parse_plan.extract_metric_names(text) -> list[str]`
  — the extractor whose output `check_prior_arcs.py` consumes verbatim. Empty output
  = guard no-op = value-prop not delivered for that plan.
- **Real signature exercised** (no wrapper): `extract_metric_names(text)`. The
  consuming guard's no-op branch is `if not metric_names:` in `check_prior_arcs.main`.

## 2. The oracle (INDEPENDENT hand-derived ground truth)
For each fixture snippet, `oracle_metric_names` is **what a careful human reads as
the plan's metrics** — the identifiers a prior-arc ledger would need to match
against a prior terminal doc. These labels were hand-written from the plan prose and
are **never** taken from `extract_metric_names`' own output (the cardinal rule). The
oracle deliberately **excludes** non-metric ALLCAPS noise (HTTP, JSON, CI, PR, env
vars) a human would not register as the plan's metric — so the metric cannot be gamed
by an extractor that simply returns every uppercase token.

**Metric = extraction recall**: fraction of hand-labeled metric names that
`extract_metric_names` actually returns, micro-averaged across all snippets
(each name weighted equally; macro/per-plan recall also reported for context).
Recall — not precision/F1 — is the value-prop-relevant axis: a *missed* name silently
disables protection, whereas a *spurious* extra name at worst causes an over-eager
ledger match (loud, not silent). Spurious names are still reported per-snippet for
visibility.

## 3. Fixture (`fixture.json`)
9 hand-labeled snippets spanning real metric-naming styles, with paired
works/silent-no-op cases:
- **ALLCAPS (works today):** `s1` (`RECALL`, `HTTP_CALLS`), `s2` (pure ALLCAPS
  control), `s3` (`METRIC <NAME>=` uppercase). Expected recall 100%.
- **All-non-ALLCAPS (silent no-op surface):** `s4` snake_case (`first_fix_rate`,
  `p95_latency_ms`), `s5` `METRIC <name>=` lowercase, `s6` camelCase
  (`firstFixRate`…), `s7` snake_case embedded in prose. Expected recall 0% →
  guard no-op.
- **Honest-keeper:** `s8` (`precision`/`recall`/`F1`) — lowercase metrics that
  happen to be the 5 literals `extract_metric_names` hardcodes via its second regex,
  so they ARE caught. Included so the metric does not over-credit the bug (not every
  non-ALLCAPS plan is a miss).
- **Mixed (partial recall):** `s9` (`FLAKE_RATE` caught + `review_turnaround_hours`
  missed) — the guard runs but checks only half the lineage surface.

`s4` is flagged `all_non_allcaps: true` and is the snippet the gate pins as
guard-active (the headline silent-no-op case that must flip GREEN once fixed).

## 4. Metric + gate
- **recall (micro)** — overall hand-labeled names found / total. TARGET is 0.90;
  `measure.py` reports against it (and exits 1 below it) so the residual gap stays
  visible.
- **The CI gate** (`tests/test_prior_arc_measurement.py`) enforces the chosen
  CONTRACT (§7), not the raw 0.90: (a) every structurally-declared plan
  (`METRIC=`/ALLCAPS/hardcoded: s1,s2,s3,s5,s8) extracts at recall 1.0 — the guard is
  fully delivered for conforming plans; (b) micro-recall stays >= the frozen 0.60
  floor (regression block); (c) the silent-no-op set is exactly the documented
  prose-only plans {s4,s6,s7}, which no-op WITH A WARNING by contract.

Run: `python3 skills/supergoal/harness/measure.py` (exits 1 vs the 0.90 target — the
gap is the 3 prose-only plans, by design under the chosen contract).

## 5. Frozen baseline (the measured answer — BEFORE)
Measured with the current `extract_metric_names` (regex `\b[A-Z][A-Z_0-9]{2,}\b`
plus 5 hardcoded literals `Acc@N|MRR|F1|precision|recall`):

| | recall (micro) | guard active | silent no-ops |
|---|---|---|---|
| **Before** (ALLCAPS + 5 literals) | **52.4%** (11/21) | 5/9 | s4, s5, s6, s7 |
| **After** (+ case-insensitive `METRIC <name>=`) | **61.9%** (13/21) | 6/9 | s4, s6, s7 |

The applied fix (§7) added ONLY the structured `METRIC <name>=` (any-case) pattern.
It caught `s5`'s lowercase declared metrics (first_fix_rate, dedupe_ratio) with
**zero spurious extractions**, and every structurally-declared plan (s1,s2,s3,s5,s8)
now extracts at 100%. The residual 38% gap is the 3 prose-only plans (s4,s6,s7) that
declare no `METRIC=` line — by the chosen contract they no-op with a visible warning
(`check_prior_arcs.py`) rather than risk the over-extraction global prose inference
would cause.

Per-snippet (BEFORE):

| snippet | style | recall | guard | missed |
|---|---|---|---|---|
| s1_allcaps_works | ALLCAPS | 100% | ACTIVE | – |
| s2_allcaps_only_works | ALLCAPS-only | 100% | ACTIVE | – |
| s3_metric_eq_upper_works | `METRIC NAME=` upper | 100% | ACTIVE | – |
| s4_snake_case_silent_noop | snake_case | **0%** | **NO-OP** | first_fix_rate, p95_latency_ms |
| s5_metric_eq_lower_silent_noop | `METRIC name=` lower | **0%** | **NO-OP** | dedupe_ratio, first_fix_rate |
| s6_mixed_case_metrics | camelCase | **0%** | **NO-OP** | buildTimeSeconds, cacheHitRatio, firstFixRate |
| s7_metrics_in_prose | snake_case prose | **0%** | **NO-OP** | auto_resolution_rate, mean_handle_time |
| s8_prose_hardcoded_literals | precision/recall/F1 | 100% | ACTIVE | – |
| s9_mixed_caught_and_missed | ALLCAPS + snake | 50% | ACTIVE | review_turnaround_hours |

**Finding:** for 4 of 9 realistic plans the prior-arc guard **silently no-ops** —
`check_prior_arcs.py` prints "skipped (no metric_names extracted)" and refuses
nothing — even though a human reads clear metrics in each. supergoal's "refuses
re-litigation of prior arcs" value-prop is **not delivered** for any plan whose
metrics are lowercase / snake_case / camelCase, which is most ordinary plans. The
gate is **RED** at 52.4% < 90%.

Baseline frozen here; the gate blocks regression once the proposed fix lifts recall.
(This harness does NOT modify `parse_plan.py` — see §7 for the proposed fix the
orchestrator can apply and re-measure.)

## 6. REAL vs INSTRUMENT (Phase-9 check)
The "before" misses are REAL, not instrument artifacts:
- `extract_metric_names` is a **pure function over text**; the fixture feeds it the
  literal plan-markdown a `superplan` author writes (same form `parse_plan.main`
  reads via `plan_path.read_text()`), with no wrapper or mock.
- Each `oracle_metric_names` is **hand-labeled from the prose, independent of the
  extractor's output** (cardinal rule), and was validated to introduce no stray
  ALLCAPS tokens — every snippet's oracle exactly partitions caught vs missed, with
  **zero spurious extractions**, so recall is not inflated or deflated by noise.
- The downstream no-op is REAL: `check_prior_arcs.py` line ~72 returns early on empty
  `metric_names`; the `metric_names` it reads is exactly `extract_metric_names`'
  output, stored verbatim in `state.json` by `parse_plan.main`.
- A regex that correctly extracts the missed names flips recall to 100% and turns the
  gate GREEN; nothing in the harness hard-codes the result.

## 7. Applied fix — structured `METRIC <name>=` declarations (chosen 2026-05-31)
The owner chose the **structured-declaration** contract (precise, zero
over-extraction) over global prose-inference. Applied to `extract_metric_names`
(`scripts/parse_plan.py`): a single case-insensitive pattern capturing the name from
`METRIC <name>=` lines — `re.findall(r"(?im)^\s*METRIC\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", text)`.
It matches only the explicit declaration form, so it never grabs prose / command-line
tokens. `check_prior_arcs.py`'s no-op branch now directs authors to declare metrics
this way.

**Rejected:** the broader snake_case/camelCase prose-inference regex below — the
harness's `spurious` column proved it over-extracts (it grabbed `ci_stats` from a
`python3 ci_stats.py` command line), which would pollute the prior-arc ledger and
risk false re-litigation refusals. Retained here only as the rejected alternative:

```python
def extract_metric_names(text):
    names = set(re.findall(r"\b[A-Z][A-Z_0-9]{2,}\b", text))          # existing ALLCAPS
    names.update(re.findall(r"\b(Acc@\d+|MRR|F1|precision|recall)\b", text))  # existing literals
    # NEW: explicit `METRIC <name>=...` declarations (any case) — the name is the
    # token after the METRIC keyword, regardless of casing.
    names.update(re.findall(r"(?im)^\s*METRIC\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", text))
    # NEW: snake_case / mixed-case identifiers that read as metric names — require an
    # underscore OR an interior capital (camelCase) and >= 6 chars to avoid matching
    # ordinary prose words.
    names.update(re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", text))    # snake_case
    names.update(re.findall(r"\b([a-z]+[A-Z][A-Za-z0-9]{2,})\b", text))      # camelCase
    blacklist = {"METRIC", "TODO", "FIXME", "XXX", "HACK", "NOTE", "WARN",
                 "ERROR", "DEBUG", "INFO"}
    return sorted(n for n in names if n not in blacklist)
```

Rationale / scope guard: the snake_case pattern requires at least one underscore
(so it won't fire on plain prose words); the camelCase pattern requires a lowercase
run, an interior capital, then 2+ chars (so `firstFixRate`/`cacheHitRatio` match while
ordinary words don't). The `METRIC name=` pattern anchors to the line keyword so it
captures the *declared* name in any case. After applying, re-run
`python3 skills/supergoal/harness/measure.py`; the over-extraction (`spurious`)
column per snippet is the regression signal to watch — broaden only until recall
hits target without spurious metric names appearing on the fixture. Tighten the
identifier heuristics if real plans show prose false-positives.

A complementary lighter-touch option (smaller blast radius, doc-only contract): keep
the regex but require `superplan` to emit metrics on explicit `METRIC <name>=` lines
and broaden ONLY the `METRIC name=` pattern above — then the snake_case/camelCase
heuristics aren't needed. The harness fixture covers both forms, so either fix is
measurable against it.

## 8. Live arm (not run here)
The downstream efficacy question — *does the prior-arc guard actually prevent wasted
re-litigation?* — needs a real `~/Documents/knowledge-base/plans/*-terminal.md`
corpus with related plans across sessions, and a measure of how often a fresh plan
targeting a retired metric is correctly refused vs. silently re-run. Protocol: seed N
terminal docs with known metrics, run `check_prior_arcs.py` on M fresh plans (some
re-litigating, some novel), measure refusal recall + false-refusal rate. This harness
is the upstream template (oracle + labeled fixture + recall metric + frozen baseline +
gate); the extractor recall it pins is a *necessary precondition* for the live arm to
mean anything (a guard that can't see the metric can't refuse on it).

## Adjacent robustness findings noted while reading (out of scope; for follow-on)
- `state_io.py --resume` (line ~184) does `state.get("plan_sha256")[:12]` in the
  SHA-mismatch refusal message. If `plan_sha256` is ever `None` (malformed/partial
  state), the `[:12]` slice raises `TypeError` and the refusal crashes instead of
  printing a clean "plan changed" message — the Wave-1 robustness finding. A guard
  (`(state.get("plan_sha256") or "?")[:12]`) would harden it. Not touched here.
