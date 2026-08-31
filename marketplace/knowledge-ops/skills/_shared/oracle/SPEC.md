# audit-skill oracle — specification

This file is the oracle's specification. Every other file in
`oracle/` is implementation against this spec. If you change a
layer's verdict semantics, tier, or trace contract, update this
document in the same commit.

The structure of this spec follows the eight-principle construction
recipe (see `docs/oracle-construction.md` if it exists, otherwise the
canonical writeup the user supplied):

1. Define verdict semantics first (Principle 1).
2. Decorrelate failure modes from proposer (Principle 2).
3. Bound cost asymmetry (Principle 3).
4. Characterize failure distribution: TPR/TNR/refusal (Principle 4).
5. Build traces before verification logic (Principle 5).
6. Compose layers as a cascade with named tier transitions (Principle 6).
7. Schedule recalibration (Principle 7).
8. Pick the cheapest oracle that supports the actual decision (Principle 8).

The "decision" the oracle supports: **"is this finding from a Phase 2
agent audit real enough to act on?"** Acting on it means writing code
or docs to address the finding. The oracle's verdict gates that action.

---

## Layer A — `reverify`

**Mechanism.** A deterministic check (grep, bash, python, file-presence)
encoded as a `Reproducer` runs against the live working tree.

**Tier.** Tier 2 — instrumented executor. The check is mechanical, not
agent-judged.

**Positive verdict semantics.** A **STILL-FIRES** verdict means exactly
this: *the deterministic predicate encoded in the Reproducer evaluated
to True against the working tree at the timestamp recorded in the
trace.* It does NOT mean "the bug is real." It does NOT mean "the
finding's description is accurate." It does NOT mean "fixing this
will improve anything." It means only: the boolean specified by the
finding's author returned True today.

**Negative verdict semantics.** A **STALE** verdict means exactly
this: *the deterministic predicate evaluated to False against the
working tree at the trace timestamp.* It does NOT mean "the bug
never existed" or "the finding was wrong" — only that the predicate
the author chose does not currently return True. A predicate that's
too narrow (e.g., grep for a literal string that's been renamed) will
return False even if a real bug persists. STALE means "drop from this
worklist," not "verified absent."

**Other verdicts.**
- **MANUAL**: the reproducer is `type: manual` — there is no automated
  check. The harness has not made a verification claim; a human must.
- **ERROR**: the reproducer crashed (timeout, malformed command,
  unreachable file). The harness has not made a verification claim;
  the instrument is broken.

**Exit-code contract for grep / grep_absent.** The grep family of
reproducers has a tighter exit-code contract than `bash` because the
underlying tool's semantics are fixed:

| rc | grep | grep_absent |
|----|------|-------------|
| 0  | STILL-FIRES (match found = bug present) | STALE (match found = bug absent) |
| 1  | STALE (no match = bug absent)           | STILL-FIRES (no match = bug present) |
| ≥2 | **ERROR** (grep failure, not a verdict) | **ERROR** (grep failure, not a verdict) |

`rc ≥ 2` covers grep errors (bad regex, file not found, IO error) AND
shell errors (rc=127 command-not-found, rc=126 not-executable). All of
those mean the reproducer did not actually answer the question — the
harness raises and reverify routes the result to ERROR. The pre-2026-05-25
implementation collapsed `rc≥2` into the false branch, so a typo'd path
or a missing binary looked identical to "bug fixed." This contract gap
was the root failure under the WSL-bash bug (PR #977): WSL bash hung
or returned non-zero without the reproducer actually running, but the
oracle reported STALE instead of ERROR. The bash-binary fix removed
the trigger; the exit-code contract fix removes the conflation itself.

**Exit-code contract for python.** Same instrument-vs-predicate
separation as grep, expressed through stderr-pattern matching since
CPython collapses every exception path to rc=1:

| Condition | Verdict |
|-----------|---------|
| rc = 0 (snippet completed, no exception) | STALE (bug absent) |
| rc ≠ 0 AND stderr matches an instrument-failure pattern | **ERROR** |
| rc ≠ 0 otherwise (intentional `raise` / `sys.exit(1)`) | STILL-FIRES |

Instrument-failure patterns: `SyntaxError`, `IndentationError`,
`ModuleNotFoundError`, `ImportError`, `NameError`, `AttributeError`.
These are almost always reproducer bugs (typo, wrong API, missing
import), not predicate results. Without this separation, a typo
produces STILL-FIRES indistinguishable from a real bug, and Layer D
fix-loop reports "fix didn't work" because the typo persists across
the fix attempt — the same downstream failure mode as the original
grep `rc≥2` conflation. `RuntimeError`, `ValueError`, `AssertionError`,
etc. remain STILL-FIRES because reproducer authors commonly raise
those intentionally to encode a predicate.

**Exit-code contract for bash.** The third and last executable-
reproducer surface (closes the conflation class after grep and
python):

| Condition | Verdict |
|-----------|---------|
| `rc == expected_exit` | STILL-FIRES (predicate fires; author's bug-present rc was hit) |
| `rc != expected_exit` AND (`rc in {126, 127}` OR `rc >= 128` OR `rc < 0`) | **ERROR** (instrument failure) |
| `rc != expected_exit` otherwise | STALE (predicate doesn't fire) |

The instrument-failure rc set encodes documented shell exit semantics:

| rc | Meaning |
|----|---------|
| 126 | command found but not executable |
| 127 | command not found (typo or missing binary) |
| 128 + N | killed by signal N (Git Bash on Windows reports this form: 137 = SIGKILL, 139 = SIGSEGV, 143 = SIGTERM) |
| negative | signal kill in Python's subprocess convention on POSIX (Linux/macOS): `rc = -N` for signal N |

Both `rc < 0` and `rc >= 128` map to the same signal-kill semantic;
the difference is which interpreter is summarising it. POSIX
subprocess returns negative, Git Bash on Windows returns the shell
convention (128 + signal_no).

If the author explicitly sets `expected_exit` to one of these (e.g.
testing whether a command IS missing, `expected_exit=127`), the
equality branch wins first and STILL-FIRES is returned. Without
this routing, a typo'd command (`grpe -q ...`) returns rc=127, fails
the equality check against `expected_exit=0`, and the oracle reports
STALE — indistinguishable from "bug fixed." Same conflation class
the grep and python fixes closed; this is the last surface.

**Decorrelation analysis.** Reproducers are bash/grep/python — a
different mechanism from the LLM proposer that generated the Phase 2
finding. Mechanism diversity per Principle 2 holds: a finding that
overstates is caught when its own reproducer is too narrow to fire,
and a finding that's vacuous is caught when its reproducer fires on
input the proposer didn't consider. Three proposer failure modes Layer
A catches:

1. *Stale finding* (the proposer wrote the finding against yesterday's
   tree; the bug was fixed between then and now). Layer A re-runs the
   predicate and returns STALE.
2. *Hallucinated finding* (the proposer asserted a bug that was never
   present). Layer A returns STALE on the first run.
3. *Reproducer mismatch* (the proposer wrote a correct narrative but
   the reproducer doesn't actually test what the narrative claims).
   Layer A reveals this when a finding is STALE despite the bug
   being obvious to a reader — the reproducer needs revision.

**Cost asymmetry.** Per finding: reproducer wall-clock ~50ms-2s
(bash grep / pytest snippet / file stat). Agent generation of the
finding: ~10-60s. Ratio ~10:1 to 100:1. Cheaper than generation by
at least an order of magnitude on every input we've measured.

**Calibration.** TPR / TNR / refusal-rate measured against
`tests/golden-findings/calibration/findings.yaml` (≥30 labeled
findings, 50/50 true/false). Reported in the trace and in
`SPEC.md`'s "Last measured" table at the bottom of this document.

**Recalibration schedule.** Once per audit-skill release (i.e.,
when audit-skill SKILL.md or `bin/audit-skill.py` changes). The
release checklist runs `pytest -q -k calibration` and fails the
release if TNR drops below the recorded floor.

---

## Specificity guard

**Problem.** The oracle's decorrelation holds at *execution* (mechanical
bash/grep/python vs the LLM proposer) but NOT at *authorship*: the same
agent often writes both the finding and its reproducer. A vacuous
predicate (`grep -q .`, `grep -qE '.*'`, bash `true`) fires regardless of
repository content, so a STILL-FIRES verdict certifies nothing — the
proposer graded its own homework. This is the framework's #1
reward-hacking surface.

**Mechanism (deterministic, two layers).** `oracle/specificity.py`:
- **Static** (`finding.static_vacuity`): regex-match always-true
  predicates against the command. Zero I/O.
- **Control-run**: run the reproducer against a bug-absent control and
  reject if it still fires. Two controls, strongest first: (1) a
  `true_fixture`→`false_fixture` swap (content-aware — the false_fixture
  is "bug-shaped but correct") when the command targets a calibration
  fixture; (2) a synthetic benign control tree (benign placeholder files
  created at the command's path tokens) — a *specific* predicate won't
  match benign content, a vacuous one will.

**Verdict.** `SPECIFIC` | `NONSPECIFIC_STATIC` | `NONSPECIFIC_CONTROL`.
Non-specific reproducers are rejected at the dispatch boundary as
`REJECT_NONSPECIFIC_REPRODUCER` (`oracle/validate.py`,
`validate_for_dispatch`) and reported by the `specificity-check` CLI
subcommand.

**Fail-safe.** When the control is inconclusive (no parseable paths, the
reproducer errors on the control, an unsupported type) the verdict is
SPECIFIC — the guard never rejects a legitimate reproducer on ambiguity;
it rejects only on a positive vacuity signal. Scoped to grep/bash for the
control-run (grep_absent's inverse semantics need a bug-present control,
out of scope for v1; static still guards literal-vacuous grep_absent).

**Calibration.** The gamed stratum
(`tests/golden-findings/calibration/findings-gamed.yaml`, kept separate
from `findings.yaml`) pins detection: every gamed reproducer must be
classified non-specific (≥ 0.95) and no specific control may be flagged
(≤ 0.0). See
`test_oracle_calibration.py::test_gamed_stratum_classified_nonspecific`.

---

## Layer B — `ensemble` (formerly "consensus")

**Mechanism.** N independent LLM Phase 2 audits of the same skill;
findings clustered by Jaccard token overlap; the layer retains
findings reported by ≥M of N agents.

**Tier.** Tier 3 — soft evaluator. **NOT an oracle by Principle 2's
decorrelation criterion.** Same mechanism (LLM) as the proposer.

**Positive verdict semantics.** An **AGREED** verdict means exactly:
*≥M of N agents independently produced a finding whose
(skill, code, description-tokens) cluster matched.* It does NOT mean
"the bug is real" — N agents drawing from the same training data and
following the same SKILL.md prompt can co-error (Kim et al. ICML 2025:
cross-vendor LLM judges agree 60% of the time when both err). It
means: this finding is **less likely to be a single-agent
hallucination** than a 1-of-1 finding, by an amount the ensemble
calibration sample can quantify.

**Negative verdict semantics.** A finding outside the AGREED set is
demoted to `[unverified-low-consensus]`. This does NOT mean the
finding is wrong — only that fewer than M agents saw it. It may be
a real but subtle bug only one agent caught; the harness routes it
to human review rather than acting on it.

**Honest framing.** This layer was originally named "consensus." That
implied stronger guarantees than the mechanism provides. Renamed to
"ensemble" because that's what it is: an ensembling step over
LLM judges. The Kim et al. result is the bound: ensembling buys
modest decorrelation against single-agent hallucination, not
categorical decorrelation against systematic-misjudgment.

**Decorrelation analysis.** Cross-vendor diversity (Anthropic vs.
OpenAI vs. Google judges, if available) buys more than same-vendor
N-agent diversity. We default to same-vendor (Anthropic), which is
the weakest decorrelation. Mechanism diversity (LLM vs.
mechanical-reproducer) is the order-of-magnitude better path —
hence Layer A is the primary gate, B is supplementary.

**Cost asymmetry.** N×proposer-cost. For N=3 the ratio is 3:1
*against* the asymmetric ideal — verification costs more than
generation. Use only when (a) the finding survived Layer A and
(b) the act-on-it cost (e.g., a code change in a security-critical
skill) justifies the verification spend.

**Calibration.** Measured against the same calibration set as
Layer A, plus stratified samples by skill domain. Records TPR/TNR
in trace. NOT used as the sole verdict for any finding — always
composed with Layer A.

**Cross-vendor dispatch (opt-in).** `oracle/ensemble_dispatch.py`
upgrades Layer B from same-vendor to genuine cross-vendor: it calls the
anthropic/openai/xai adapters in-process (`audit-skill-oracle.py
ensemble-dispatch`), parses each vendor's findings, and feeds
`aggregate(vendor_by_agent=…)`. Each ConsensusFinding records the
distinct vendors that reported it (`distinct_vendor_count`); per-vendor
`layer:"B"` trace records carry `model_version`. Key-graceful — a missing
API key is recorded as `VENDOR_UNAVAILABLE`, never fatal — and never run
in CI. Cross-vendor buys MORE decorrelation than same-vendor N-of-1 but
is still NOT sound (cross-vendor judges co-err, Kim et al.); compose with
Layer A, never use as the sole verdict.

**Recalibration schedule.** Quarterly, or whenever a vendor releases
a major model version. Drift in agent judgment from training updates
is the main failure mode this layer must track.

---

## Layer C — `corpus` (golden-fixture regression)

**Mechanism.** Curated `expected-findings.yaml` per fixture skill,
specifying `required_codes` (Phase 2 MUST find these) and
`forbidden_codes` (Phase 2 must NOT find these). Compared against
live agent output on the fixtures.

**Tier.** Tier 4 — human-curated ground truth. The corpus IS the
oracle for the fixture skill; deviations from the corpus are
deviations from the curated specification, period.

**Positive verdict semantics.** A **PASS** verdict means: *for the
named fixture skill, every code in `required_codes` appeared in the
live audit and no code in `forbidden_codes` appeared.* It does NOT
mean "Phase 2 is correct in general" — only that on this fixture
the curated regression invariants held.

**Negative verdict semantics.** A **FAIL** verdict means at least
one required code was missing or at least one forbidden code was
present. The diagnosis tells you which one; the corrective action
is one of: (a) Phase 2 detection logic regressed (fix audit-skill);
(b) the fixture itself drifted (fix the fixture); (c) the corpus
entry is wrong (update the corpus). Layer C's verdict does not
distinguish among these three; that's the user's call.

**Decorrelation analysis.** Different mechanism (human curation),
different process (manual review at corpus-write time vs. agent
inference at audit time). Strong decorrelation, by design — the
corpus is precisely what an LLM cannot easily produce.

**Cost asymmetry.** Static check: ~ms per fixture. Live agent
audit cost: ~30s-2min per fixture. Asymmetric only when the
corpus is checked against pre-recorded findings; checking live
findings against the corpus inherits the agent cost.

**Calibration.** Layer C is itself the calibration mechanism for
Phase 2 audit-skill logic. Recalibration here means updating the
corpus when a new audit category lands (adding `required_codes`
for it) or when a fixture is refactored.

**Recalibration schedule.** On every audit-skill change that adds
or removes a finding code, before the change merges.

---

## Layer D — `fix_loop`

**Mechanism.** For a given finding + a fix candidate, run the
finding's Reproducer in two states: pre-fix (must fire = True) and
post-fix (must fire = False).

**Tier.** Tier 2 — instrumented executor. Same family as Layer A,
adding the temporal dimension (before vs after a fix).

**Positive verdict semantics.** A **VERIFIED** verdict means
exactly: *Reproducer.fires() returned True on the pre-fix state and
False on the post-fix state.* It does NOT mean "the fix is correct
in general" — only that the predicate the finding's author chose
flipped its truth value across the fix. A fix that satisfies the
reproducer's narrow predicate but introduces other bugs is not
detected by Layer D alone (compose with the regression test suite).

**Negative verdict semantics.**
- **STALE-PRE**: reproducer didn't fire pre-fix. The "fix" addresses
  a non-existent bug, or the bug was already fixed elsewhere. Don't
  apply the fix.
- **FIX-INEFFECTIVE**: reproducer still fires post-fix. The fix
  didn't resolve the predicate. Re-diagnose.

**Decorrelation analysis.** Reproducer is mechanical (decorrelated
from LLM); fix is LLM-produced. Layer D measures the gap between
what the LLM said it would do and what the deterministic
predicate observes. Three proposer failure modes Layer D catches:

1. *Vacuous fix* (the LLM edited the wrong file). Reproducer still
   fires post-fix → FIX-INEFFECTIVE.
2. *Already-fixed-by-someone-else* (the LLM is acting on a stale
   finding). Reproducer doesn't fire pre-fix → STALE-PRE.
3. *Reproducer too narrow* (the LLM-produced fix satisfies the
   reproducer's literal predicate but the real bug class still
   manifests). NOT caught by Layer D alone; needs Layer C or a
   richer reproducer.

**Cost asymmetry.** Two reproducer invocations + git worktree
operations: ~5-15s. Fix attempt by an agent: ~30s-3min. Ratio
~5:1 to 30:1. Asymmetric.

**Calibration.** Shares the calibration set with Layer A: same
reproducers, same labeled findings. Adds a stratified sample
where the "fix" is intentionally vacuous (e.g., touches the
wrong file) — Layer D should classify as FIX-INEFFECTIVE.

**Recalibration schedule.** Same cadence as Layer A.

**Trace + enforcement.** Layer D writes one trace record per fix verdict
(`layer:"D"`), stamped with `input.session_id` from
`AUDIT_SKILL_ORACLE_SESSION`. A regression side-check
(`verify_fix_with_regression_check`) additionally writes one `INTRODUCED`
record per sibling finding the fix broke. The `subagent-stop.py` hook
reads these records and BLOCKS the subagent (exit 2) when a fix
attributed to the current session is `FIX-INEFFECTIVE` or `INTRODUCED`
and not superseded by a later `VERIFIED` for the same finding — within a
recent window (`AUDIT_SKILL_ORACLE_GATE_WINDOW`, default 1800s).
Fail-safe: no session attribution (orchestrator didn't export
`AUDIT_SKILL_ORACLE_SESSION`) → no block.

---

## Layer profiles

The four layers are characterized by a **profile vector**, not the
monotonic Tier ladder. Profiles do not co-vary, and the ladder is
non-informative — Layers A and D are both "Tier 2" yet sit at opposite
ends of the cascade. The per-layer `**Tier.**` labels above are retained
only as a **derived, deprecated** alias (computed from `groundedness`);
`oracle/profile.py` is the machine-readable source of truth, exposed by
`audit-skill-oracle.py profile [--format json|markdown]`.

| Layer | Name | Soundness | FP rate | FN rate | Cost ratio | Automation | Groundedness | Derived tier |
|---|---|---|---|---|---|---|---|---|
| A | `reverify` | 0.95 | 0.20 | 0.05 | 10-100x cheaper than generation | automated | mechanical | Tier 2 |
| B | `ensemble` | — | — | — | ~3x MORE expensive than generation (N=3) | automated | soft | Tier 3 |
| C | `corpus` | 1.00 | 0.00 | 0.00 | ~free static check vs a live agent audit | human-curated | curated | Tier 4 |
| D | `fix_loop` | 0.95 | 0.20 | 0.05 | 5-30x cheaper than the fix attempt | automated | mechanical | Tier 2 |

Unmeasured cells are `—` (Layer B has no calibration); per Principle 4 an
oracle with an unmeasured failure distribution is not ready for
autonomous use, and the blank makes that visible rather than fabricating
a number. Keep this table in sync with `oracle.profile.PROFILES`
(`test_oracle_calibration.py::test_layer_profiles_consistent_with_spec`).

---

## Cascade composition

The four layers compose as a cascade, in invocation order:

```
                                     ┌─────────────────────┐
[Phase 2 agent finding] ─────────►  │ A: reverify        │ ─► STILL-FIRES ─►
                                     │ (Tier 2, mechanical)│    drop STALE
                                     └─────────────────────┘
                                              │
                                              ▼
                                     ┌─────────────────────┐
                                     │ B: ensemble        │ ─► AGREED ─►
                                     │ (Tier 3, soft)      │    demote others
                                     │ [SAME-MECHANISM]    │
                                     └─────────────────────┘
                                              │
                                              ▼
                                     ┌─────────────────────┐
                                     │ C: corpus regression│ ─► PASS/FAIL
                                     │ (Tier 4, curated)   │    (fixture only)
                                     └─────────────────────┘
                                              │
                                              ▼
                                     [propose a fix]
                                              │
                                              ▼
                                     ┌─────────────────────┐
                                     │ D: fix_loop         │ ─► VERIFIED ─►
                                     │ (Tier 2, mechanical)│    apply
                                     └─────────────────────┘
                                              │
                                              ▼
                                         [act on fix]
```

**Cascade composition rule** (Principle 6): the harness reports
findings at the strongest layer that **actually ran** for that
finding, never at the layer the marketing wants. A Phase 2 finding
that survived A but skipped B is reported as `A-VERIFIED`, not
`A+B-CONSENSUS-VERIFIED`. A finding that survived A and B but failed
C is reported as `C-FAIL` (the weakest tier that ran, which became
the bottleneck).

**The "decision" the cascade gates.** A finding is acted on iff:
- Layer A: STILL-FIRES, and
- For [behavior-fix] findings only: Layer D returns VERIFIED on a
  proposed fix BEFORE the fix lands.

Layer B is an optional pre-filter (recommended for high-stakes
skills). Layer C is a continuous regression gate (runs in CI; failure
blocks audit-skill changes).

---

## Trace contract (Principle 5)

Every invocation of every layer writes one JSONL record to
`~/.claude/oracle-trace.jsonl` with the following schema:

```json
{
  "ts": "2026-05-25T03:42:18+00:00",
  "layer": "A|B|C|D",
  "finding_id": "<sha256 of skill+code+description>",
  "skill": "<target skill name>",
  "verdict": "STILL-FIRES|STALE|MANUAL|ERROR|AGREED|PASS|FAIL|VERIFIED|STALE-PRE|FIX-INEFFECTIVE|INTRODUCED|DISPATCHED|VENDOR_UNAVAILABLE",
  "evidence": "<reproducer command + result, or agent agreement count>",
  "procedure_version": "<git sha of bin/audit-skill.py>",
  "model_version": "<for layer B: model id + sampling config>",
  "latency_ms": 0,
  "cost_usd": null,
  "input": {
    "reproducer_type": "...",
    "reproducer_command_sha": "...",
    "session_id": "<layer A/D: AUDIT_SKILL_ORACLE_SESSION, '' if unset>"
  },
  "breadth": {"specificity": "<NONSPECIFIC_* | null>", "rc": 0, "match_count": null}
}
```

`breadth` is the predicate-drift signal (Layer A/D; null for B/C): a
reproducer whose `specificity` trends non-specific over many runs is a
reward-hacking signal. `input.session_id` attributes a record to the
dispatching subagent for the enforced Layer-D gate.

The trace is the source-of-truth for drift detection,
audit-the-auditor, and quarterly recalibration. **Anything not in
the trace did not happen** for the purposes of the harness's
correctness story.

---

## Calibration results

Last measured against `tests/golden-findings/calibration/findings.yaml`
(N=38: 15 known-true, 15 known-false, 6 known-ERROR, 2 paired controls).

| Pathway | Floor | Last measurement | Last run |
|---|---|---|---|
| Predicate TPR (STILL-FIRES on expected_fires=true) | ≥ 0.95 | 1.000 | 2026-05-26 |
| Predicate TNR (STALE on expected_fires=false) | ≥ 0.80 | 1.000 | 2026-05-26 |
| ERROR TPR (ERROR on expected_status=ERROR) | ≥ 1.00 | 1.000 | 2026-05-26 |
| ERROR FPR (unexpected ERROR on predicate cases) | ≤ 0.05 | 0.000 | 2026-05-26 |

The ERROR pathway was added 2026-05-26 to pin the contracts established
in PR #979 (grep `rc≥2` → ERROR) and PR #981 (python instrument-failure
→ ERROR). Pre-addition, the calibration set could pass at TPR=TNR=1.0
while the conflation regressed silently — a known-bad reproducer would
be misclassified as STALE or STILL-FIRES and the test wouldn't notice.
The TPR floor is set to **1.0** for the ERROR pathway because the
entries are deterministic; any drop indicates the conflation has
returned. The FPR ceiling is 0.05 to allow the instrument-failure
pattern list to be slightly conservative without false-alarming every
well-formed predicate.

**ERROR-pathway entries**: 4 grep (file-not-found, malformed regex,
grep_absent file-not-found) + 3 python (SyntaxError, ImportError,
NameError) + 2 paired controls (intentional `raise RuntimeError` →
STILL-FIRES; grep no-match → STALE) that guard against over-correction.

**Layers**:
- A reverify: measured directly above
- B ensemble: not measured against this set — would need N agents per
  finding; tracked separately
- C corpus: deterministic; not measured against the same set — it IS
  ground truth
- D fix_loop: shares Reproducer.fires() with A; same calibration
  applies at fix-attempt time

**Re-run command**: `pytest skills/audit-skill/tests/test_oracle_calibration.py -q`

The test fails if ANY of the four metrics drops below floor / above
ceiling. The ERROR-pathway assertions are release-blocking — a
regression there means the rc≥2 / instrument-failure conflation is
back in the verdict pipeline.

---

## Cohen's kappa (chance-corrected agreement)

`oracle/kappa.py` adds a κ companion to the TPR/TNR floors. Raw accuracy
overstates agreement when one class dominates; κ corrects for chance.

- **Oracle-vs-truth (active gate).**
  `test_oracle_vs_truth_kappa_above_floor` computes κ between Layer A's
  verdict and the adjudicated ground-truth label over the predicate
  calibration entries and gates at **κ ≥ 0.7** (substantial; 0.5–0.7 is a
  soft warning per `harness/ORACLE-PLAN.md`). Runs on existing data — no
  second labeler required.
- **Inter-rater (human-populated).** The same helper computes κ between
  two independent labelers: `label_a` / `label_b` in `Finding.extra`, and
  a parallel `expected-findings-b.yaml` for Layer C. The machinery is
  ready; populating a genuine second-labeler column is a human task and is
  NOT auto-generated — fabricating it would defeat the purpose.

---

## Triage status (operator-set, gates dispatch)

Findings carry a `triage_status` field on the canonical Finding
schema (`oracle/finding.py:TRIAGE_STATUSES`). The valid values are:

| Status | Set by | Meaning | act_on behavior |
|---|---|---|---|
| `""` / `open` | default (untriaged) | actionable | included in worklist |
| `STALE` | operator OR `refresh-tracker` | re-audit confirmed no longer reproducible | DROPPED before reverify |
| `FIXED` | operator | resolved by a prior commit; tracker awaiting cleanup | DROPPED before reverify |
| `FALSE_POSITIVE` | operator | original finding was wrong (hallucination, mis-applied check) | DROPPED before reverify |
| `DEFER` | operator | real but out of scope for current wave | DROPPED before reverify |

**Why this is part of the oracle spec**: in the 2026-05-25 triage of
25 [unverified] Phase 2 findings, 21 were STALE (already addressed by
the campaign) and 4 were DEFER (real but not runtime-blocking). Manual
triage required reading each finding and its target code. The next
campaign would re-surface all 25 unless the YAML carried machine-
readable triage state.

**Operator workflow**:

- `audit-skill-oracle.py set-triage-status <findings> --status STALE
  --skill X --code Y --note "..."` — explicitly close a finding.
- `audit-skill-oracle.py refresh-tracker <findings>` — re-baseline
  against current tree; auto-stamp `STALE` on non-firing findings.

**act_on gate** (`oracle/act_on.py`):

```python
actionable = [f for f in findings if f.is_actionable()]
triage_filtered = [f for f in findings if not f.is_actionable()]
# Only actionable findings go through reverify; triage_filtered are
# carried in the report for summary but excluded from the worklist.
```

The triage_status field is preserved by the canonical YAML emitter
(`oracle/tracker.py:_to_yaml`) and round-tripped by `load_findings`.

---

## Out of scope (honest list of what this oracle does NOT do)

1. It does not verify the semantic accuracy of a finding's prose. If
   an agent writes "this skill leaks secrets" but the reproducer only
   greps for a `.env` mention, Layer A's STILL-FIRES verdict
   verifies only the grep, not the prose.
2. It does not assess findings whose reproducer is `manual`. Those
   pass through to human review unchanged.
3. It does not detect bugs the proposer never wrote a finding for.
   Phase 2's coverage is upstream of the oracle; Layer C catches some
   coverage regressions but only for fixture skills.
4. It does not run in production until the calibration table has real
   numbers, not TBDs. Per Principle 4, an oracle with unmeasured
   failure distribution is not yet ready for autonomous deployment.
5. It does not catch cross-skill systemic blind-spots that affect
   multiple fix-agents in parallel (e.g., all agents missing context
   about a sibling repo). The 2026-05-25 KB-citation incident was
   this class. The mitigation is structural —
   `AUDIT-TRACKERS/campaign-context.md` and
   `skills/audit-skill/known-external-paths.yaml` — loaded by the
   Phase 2 prompt template, not by the oracle itself. See
   `rules/incidents/check-before-change.md` for the parent failure
   mode.

---

## Verification battery

Beyond calibration, the exit-code contract and the Layer-D loop are pinned
by a dedicated battery (Phase 4):

- **Mutation** (`test_oracle_mutation.py`) — flips each exit-code branch
  (grep `rc>=2`, the bash `126/127/>=128` set, the python instrument
  patterns, grep fire-polarity) and asserts the verdict changes; a
  surviving mutant is a contract/corpus gap.
- **Property** (`test_oracle_properties.py`) — drives `rc ∈ {0,1,2,126,
  127,128,137,139,143}` and asserts the verdict matches the bash/python
  exit-code tables at every boundary.
- **Metamorphic** (`test_oracle_metamorphic.py`) — equivalent reproducer
  rewrites yield the same verdict; a broken reproducer yields ERROR, never
  STALE.
- **Layer-D on history** (`scripts/run_layer_d_history.py`) — runs Layer D
  over hand-seeded fix-PR cases (pre = parent, post = fix) to measure a
  real VERIFIED-rate. A script, not a CI gate; the logic is verified on a
  synthetic repo.
- **Audit-the-auditor** (`scripts/audit_the_auditor.py`) — samples trace
  records per layer for periodic human REAL/INSTRUMENT/UNCLEAR
  classification, applying the Phase-9 rule (>= 60% INSTRUMENT → fix the
  oracle, not the system).

---

## Versioning

This SPEC is at version 1.0. Changes to any tier classification,
verdict semantics, or trace schema increment the major version and
require a re-run of all calibration tests against the new spec.
