---

name: search-campaign
description: "Run a large parallel adversarial/search campaign as a repeatable generate to evaluate to track to rotate to select loop, optimizing diversity times robustness when there is no direct feedback gradient."
when_to_use: 'Use for any large search/red-team/optimization campaign where you generate many candidates, score them against an oracle, and iterate — especially when the true objective (a held-out board, a hidden guard, an unmeasurable target) gives NO direct feedback so you optimize diversity x cross-oracle robustness instead of a single score. Trigger phrases: "run the campaign", "search-campaign", "parallel generate and evaluate", "red-team search", "the standard cycle", "keep iterating across axes". Do NOT use for a single one-shot generation, a trivial eval, or work with a clean measurable gradient (just optimize the metric directly).'
argument-hint: "[objective or target, e.g. 'JED attack breadth' — or omit to resume the active campaign]"
effort: high
allowed-tools: Read Write Edit Bash Grep Glob Workflow Agent Task TaskCreate TaskUpdate Skill
metadata:
  author: example-security-engineering
  version: "1.0"
---

# Search Campaign — parallel generate → evaluate → track → rotate → select

A repeatable loop for large adversarial/search campaigns. Its defining constraint:
**when the real target gives no feedback** (a sealed board, a hidden guard, an
unmeasurable objective), you cannot hill-climb a score — so the objective becomes
**diversity × cross-oracle robustness**, and progress is *coverage*, not a number.

Standing invariants (NON-NEGOTIABLE):
- **Never declare a ceiling.** A plateau/refusal is *untested-until-exhausted* — rotate
  the axis, don't stop. (See `no-ceiling-assumptions`, `break-plateau-by-axis-rotation`.)
- **Parallelize whatever uses independent resources.** Generation (Claude designers),
  evaluation (network backend), and local scoring (CPU) are independent — run them
  concurrently. A single-resource limit (e.g. an MPS wedge) is a scheduling constraint,
  not a reason to serialize the whole pipeline.
- **History must be actively written down or it doesn't exist.** Snapshot the record at
  every milestone (raw result files have no timestamps).

---

## Phase 0 — Frame

State, in one place: the real objective; what you are optimizing (if no feedback gradient →
diversity × robustness, NOT a proxy score); the unit of progress (distinct confirmed cells /
covered grid squares); and the oracle(s) you can test against + their fidelity (a stand-in is a
*hypothesis*, not truth). Write this as the header of the campaign RUNLOG.

## Phase 1 — Generate (parallel)

Fan out generation across multiple **axes** via `Workflow` (Claude designers — no eval-backend
contention). Each axis is a distinct angle: coverage of an under-explored quadrant, systematic
grid enumeration (MAP-Elites), severity/value stacking, mutation of near-misses (Phase 5).
- Sanctioned-benchmark framing preamble on every designer prompt; wrap each `agent()` in
  `.catch(() => ({...empty}))` so one safety-flagged lever cannot sink the batch.
- Dedup and append candidates to the durable corpus.
- Generate *just enough* to keep the eval queue full of high-value candidates — do not flood a
  saturated eval backend (that is fake parallelism).

## Phase 2 — Evaluate (parallel)

Run the scorer as a **sharded fleet**, not a serial loop:
- Split candidates across N processes (`SHARD_INDEX`/`SHARD_TOTAL`), each writing its own output
  file (merge at the end). Process-level parallelism sidesteps in-process concurrency wedges.
- If a local model (injection scanner, classifier) wedges under thread concurrency, **force it to
  CPU** (small models are fine on CPU and are process/thread-safe) — this removes the wedge at its
  root and unlocks the shard fleet.
- Hang-protect every network call with a hard per-item timeout (a dead socket has none of its own)
  → catchable → retry, so one bad item costs seconds, not the run.
- A **fleet-monitor** (background) waits for all shards, merges outputs, tallies new confirmed
  cells, and writes a terminal marker + notifies. Distinguish COMPLETE / WEDGED (no-progress past
  a threshold) — never trust pid-liveness alone.
- Add a **second independent backend** (e.g. Bedrock for the judge) only when it is genuinely
  independent of the first's rate pool — that is real added throughput; a second fleet on the same
  saturated backend is not.

## Phase 3 — Track (visual + durable)

Every milestone: update the campaign **RUNLOG** (objective, timeline, methodology, experiments,
results, decisions-with-why, meta-recurrences) AND regenerate the **dashboard** (coverage heatmap,
axes board, over-time trend snapshots). The dashboard's build script must APPEND a timestamped
snapshot each run (raw results have no timestamps — the trend only exists if you log it). Compile
from durable artifacts (result files, submission history, PRs), never from memory.

## Phase 4 — Rotate (on plateau)

When an axis stops producing OR the model refuses heavily on a quadrant: rotate the SEARCH AXIS
(invoke `/search-axis-rotate`; for red-team framing use `/red-team-axes`). Treat refusals as data
(which framings the model won't do), not as walls. The refusal-heavy, high-value quadrants are the
frontier — not the saturated easy ones.

## Phase 5 — Iterative-mutation loop (the converter)

The engine that turns refusals into fires: take near-miss candidates (fired on one oracle but not
both, or refused with a plausible-but-close framing), mutate the framing (encoding, ops-context,
authorization phrasing, cadence), re-test, keep what improves. This is real quality-diversity
(MAP-Elites with mutation), not one-shot generation. Feed survivors back into Phase 1's corpus.

## Phase 6 — Select + ship

Assemble the portfolio from the **union**: breadth (all distinct confirmed cells) + robustness
(cross-oracle survivors) + value (severity-weighted, stacked where possible). Weight by
confirmation strength; treat single-confirmation cells as hypotheses (breadth-only, low weight).
Validate (syntax, real-payload invariant, no game-hack markers), pre-flight against the known-good
submit contract, submit, verify the terminal state, and record it in the RUNLOG + dashboard.

**Then loop Phases 1–5** until the axes are genuinely exhausted (multiple consecutive rotations
dry) — not at the first plateau.

---

## Worked example — one full cycle

A campaign whose real target is a sealed held-out board (no feedback gradient), so the
optimization target is diversity × cross-oracle robustness.

**Input** (Phase 0 frame, written as the RUNLOG header):

```
objective:     maximize distinct confirmed attack cells on a sealed board
optimizing:    diversity x cross-oracle robustness   (NO direct gradient)
progress unit: distinct confirmed cells on a severity x technique grid
oracles:       (1) local scanner  [high fidelity, cheap]
               (2) hosted judge   [independent backend, rate-limited]
               a stand-in oracle is a HYPOTHESIS, not truth
```

**Cycle** (what actually runs):

| Phase | Action | Observed |
|---|---|---|
| 1 Generate | `Workflow` fans out 4 designer axes (under-explored quadrant, grid enumeration, severity stacking, near-miss mutation); each `agent()` wrapped in `.catch()` | 61 candidates appended, 12 deduped away |
| 2 Evaluate | 6 shards via `SHARD_INDEX`/`SHARD_TOTAL`, per-item hard timeout, scanner forced to CPU | 49 scored; 1 shard hit a dead socket, retried, cost ~8s not the run |
| 3 Track | RUNLOG updated + dashboard rebuilt with a timestamped snapshot appended | coverage 18 → 23 cells |
| 4 Rotate | quadrant refused heavily → `/search-axis-rotate` | refusals logged as data, not a wall |
| 5 Mutate | 9 near-misses (fired on scanner, refused by judge) re-framed and re-tested | 4 converted to cross-oracle confirmed |
| 6 Select | union of breadth + robustness + value; single-confirmation cells weighted low | portfolio shipped, terminal state verified in RUNLOG |

**Output**: coverage rose 18 → 23 distinct confirmed cells; 4 of them cross-oracle
robust. Note what is *not* claimed — no score improved, because the real board gives
no feedback. Coverage is the deliverable.

**The failure this example prevents**: after Phase 4's heavy refusals it is tempting to
report "we've hit the ceiling at 18 cells." That is the banned conclusion — the
refusal-heavy quadrant was the frontier, and Phase 5 converted 4 of its near-misses.

## Evaluations

Run these against a campaign in flight; each has an observable pass/fail.

**Eval 1 — the frame precedes generation.**
Given a fresh campaign, assert the RUNLOG header states objective, optimization target,
progress unit and oracle fidelity *before* any candidate exists.
PASS: header present with all four fields. FAIL: generation started first, or the
optimization target is a proxy score when the real objective has no gradient.

**Eval 2 — evaluation is sharded, not serial.**
While Phase 2 runs, count scorer processes.
PASS: N > 1 shards, each writing its own output file, merged at the end.
FAIL: one process iterating candidates (the most common regression — it looks like
progress and costs multiples of the wall-clock).

**Eval 3 — a plateau produces a rotation, never a ceiling claim.**
Grep the RUNLOG and session output for ceiling language ("ceiling", "reachable
frontier", "as good as it gets", "diminishing returns").
PASS: zero occurrences, and each plateau has a corresponding `/search-axis-rotate`
entry. FAIL: any ceiling claim — this is the skill's primary invariant.

**Eval 4 — the trend exists because it was written down.**
After two milestones, read the dashboard's history file.
PASS: ≥2 timestamped snapshots. FAIL: one snapshot or none — raw result files carry no
timestamps, so an un-appended trend is unrecoverable after the fact.

**Eval 5 — single-confirmation cells are not counted as robust.**
Inspect the Phase 6 portfolio weighting.
PASS: cells confirmed by one oracle are labelled breadth-only and weighted low.
FAIL: a single-oracle fire reported as cross-oracle robust (a stand-in oracle is a
hypothesis).

## Success criteria
- Objective + optimization target stated (Phase 0) before generating.
- Generation and evaluation run concurrently on independent resources; eval is sharded, not serial.
- RUNLOG + dashboard refreshed at each milestone with a new history snapshot.
- Axis rotation invoked on plateau (never a "ceiling" declaration).
- Portfolio selected by breadth × robustness × value; shipped and recorded.

## What this skill does NOT do
- It is not for clean-gradient optimization (optimize the metric directly instead).
- It does not replace `/search-axis-rotate` or `/red-team-axes` — it *orchestrates* them as Phase 4.
- It does not invent history — it snapshots durable artifacts as they are produced.
