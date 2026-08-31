# Measurement harness — roundtable consensus integrity

> **Historical evidence plus a live regression oracle.** The frozen before/after
> measurements and dated model references are preserved. The deterministic
> quorum test remains active, but it does not qualify the current model slate.

A `build-measurement-harness` instance answering recommendation #1 ("measure the
heavy skills"): does `roundtable` actually deliver the **decorrelated
multi-vendor consensus** that is its entire reason to cost 3 vendors × up to 5
rounds — or does it declare consensus when it has collapsed to a sub-quorum of
surviving vendors?

This measures the *mechanism's delivery of its value-prop*, deterministically and
offline. It does NOT measure "does multi-vendor review find more real issues than
one model" — that needs live keys + a labeled-issue corpus (the **live arm**,
sketched at the end).

## 1. Classify the measurement
- **Unit:** one convergence/auto-stop decision = `(round_num, min_rounds, threshold, sims)`, where `sims = {vendor: self-similarity}` for the vendors that produced output this round.
- **Decision under test:** `scripts/embed.should_stop(...)` — the gate that decides "the roundtable has converged, stop spending." A `stop=True` is an implicit claim of consensus.

## 2. The oracle (deterministic ground truth)
A stop is a **valid consensus** iff a quorum of **≥ MIN_QUORUM = 2 distinct
vendors** is represented in `sims` AND all of them are ≥ threshold AND
`round_num ≥ min_rounds`. Rationale: "decorrelated" requires at least two
*different* vendors agreeing; one vendor agreeing with its own prior round is
self-similarity, not consensus. (Roundtable's own SKILL.md success criterion is
stronger still: "all 3 agents complete Round 1 + Round 2.")

A `stop=True` with `< 2` vendors in `sims` is a **FALSE CONSENSUS**: the
expensive ceremony collapsed to a single surviving vendor but still reports
agreement. This is the exact failure surfaced in the Wave 1 audit and reachable
in production — `harness.py:540` builds `sims` only from vendors whose round
files exist, so a vendor that errors/loses its key simply drops out.

## 3. Fixture (`fixture.json`)
9 hand-labeled scenarios, three classes (paired positives/negatives, the
FP=FN=0 fixture spirit):
- `true_consensus` (≥2 vendors, all ≥ threshold) → oracle stop = **true**.
- `collapse` (0 or 1 vendor, similarity would otherwise trigger) → oracle stop = **false** (the bug surface).
- `correctly_continues` (a vendor below threshold / below min_rounds / no embeddings) → oracle stop = **false**.

## 4. Metric + gate
- **false_consensus_count** — `collapse` scenarios where `should_stop` returns True. **Gate: must be 0** (`tests/test_consensus_integrity.py`).
- **false_consensus_rate** — over `collapse` scenarios (the decorrelation-failure rate under partial vendor failure).
- **consensus_recall** — `true_consensus` scenarios correctly stopped (guards against over-correction: the quorum fix must not suppress real consensus).
- **integrity** — overall `should_stop == oracle` agreement.

Run: `python3 skills/roundtable/harness/measure.py` (exit 1 if any false consensus).

## 5. Frozen baseline (the measured answer)
| | false_consensus_count | false_consensus_rate (collapse) | consensus_recall | integrity |
|---|---|---|---|---|
| **Before** (no quorum check) | 3 | **100%** | 100% | 67% |
| **After** (quorum guard, `min_agents=2`) | **0** | 0% | 100% | 100% |

The auto-stop mis-declared consensus on **100%** of partial-failure scenarios —
including the degenerate empty-`sims` case ("all agents converged (sims={})").
The quorum guard takes it to 0 without suppressing any true consensus
(recall stays 100%). Baseline frozen at 0; the gate now blocks regression.

## 6. REAL vs INSTRUMENT (Phase-9 check)
The "before" failures are REAL, not instrument artifacts: `should_stop` is a pure
function; the fixture feeds it `sims` of the exact shape `harness.py` constructs;
the oracle label is hand-set per scenario and independent of `should_stop`'s
output. A mutation that removed the new quorum check flips the gate red.

## 7. Live arm (requires keys — not run here)
The downstream efficacy question — *does a 3-vendor roundtable surface more real
issues than a single strong pass?* — needs `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/
`XAI_API_KEY` and a corpus of documents with **planted, labeled issues**. Protocol:
run roundtable vs. a single-vendor baseline over the corpus; measure planted-issue
recall and false-positive rate of each; the roundtable earns its 3–5× cost only if
its recall delta exceeds the cost ratio. Fixture + runner are future work; this
harness is the template (oracle + labeled fixture + metric + frozen baseline + gate).

## Not-yet-fixed deficiencies this harness documents (follow-on)
- `harness.py` has **no quorum abort**: a run with <2 surviving vendors proceeds to `max_rounds` (wasted spend) rather than aborting. The `should_stop` fix prevents the *false auto-stop*, not the wasted rounds.
- `synthesize.py` **hardcodes** "Three agents (Opus 4.7, Grok, GPT)" and "## Convergent findings (3-of-3 agreement)" (lines 18, 22) regardless of who ran, and `rounds_completed - 1` (line 119) underflows on early abort. The synthesis narrative therefore claims 3-of-3 even on a collapsed run. Measuring/fixing these is the next increment.

### Current-state addendum — 2026-08-08

The dated bullet above is preserved as audit evidence. Model-name hardcoding is
now resolved: synthesis reads the run receipt. The no-output path also exits
before calculating post-Round-1 count. The broader quorum claim is now
mechanically closed. The harness aborts with a typed `quorum_abort` receipt when
a main round has fewer than two distinct successful vendors. Synthesis reads
exact successful-arm coverage per main round, refuses a collapsed transcript,
and exposes 3-of-3 wording only when all three arms succeeded in every main
round. Finding-level support still must be verified from recorded outputs;
panel coverage is not itself agreement.
