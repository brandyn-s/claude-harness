# Methodology evolution — dated lessons

A living history of every experiment that taught the skill something.
Each entry: date, source experiment, finding, implication for skill.

When a new experiment teaches something, append an entry. Don't edit
prior entries (history is informative even when superseded).

---

## 2026-04-29 — Original dispatch on Go precision = 0.515

**Source**: voice-mode chat session + 11-framework dispatch in Claude
Code session.

**Finding**: dispatching 11 of 144 frameworks at the Go-precision
plateau surfaced edge-type partitioning (Bisociation), top-of-funnel
constraint analysis (Cynefin, ToC), and stub-target separation as a
convergent fix theme across multiple buckets. Engineering shipped
~17pp precision lift in PR #121. The dispatch produced framings the
team hadn't previously considered.

**Implication for skill**:
- Concrete problem statements matter; abstract framing produced no
  useful output.
- Cross-bucket convergence is the positive signal (≥3 buckets agreeing).
- Synthesis layer that groups personas by theme helps the human reviewer.

**Captured in**: `references/discovery-mode.md` workflow.

---

## 2026-04-30 — M1 measurement-design inversion

**Source**: M1 task in superplan execution.

**Finding**: when conventional metrics plateau and the engineer can't
articulate what to measure next, dispatch can be inverted: ask
personas "what would your framework MEASURE that current metrics
don't capture?" instead of "what would your framework FIX?"

**Implication for skill**:
- Discovery mode supports `--inversion` flag.
- Persona prompt in inversion mode swaps to measurement-design framing.

**Captured in**: `references/discovery-mode.md` Step 1; future
`references/inversion-flag.md` if inversion grows complex enough to
warrant its own page.

---

## 2026-04-30 — M2 triage gate (Article VI)

**Source**: M2 task in superplan execution; refined Article VI of
the dispatch template.

**Finding**: dispatch costs (latency, API budget) make cargo-cult
application wasteful. A 5-trigger AND-gate prevents speculative
dispatch on fresh problems where conventional engineering hasn't been
tried.

**Implication for skill**:
- Step 0 of every mode is the triage gate.
- ≥2 of 5 triggers must hold.
- Skill exits with redirect when gate fails.

**Captured in**: `references/triage-protocol.md`.

---

## 2026-04-30 — M3 inventory audit

**Source**: M3 audit of the 144-framework master inventory.

**Finding**: 165/170 entries score 3-4 of 4 quality criteria. 5
flagged entries are intentional cross-reference pointers, not
deficiencies. Mean word count 135 (well above the 80-word threshold).

**Implication for skill**:
- Pointer-stub filter (`len(body) > 200`) excludes the 5 stubs
  automatically.
- No further inventory rewrite work needed.
- Quality threshold of 80+ words and structured-format compliance is
  validated.

**Captured in**: `scripts/parse_inventory.py` filter logic.

---

## 2026-04-30 — M4 scaling experiment

**Source**: M4 task in superplan; 4 cohort sizes × Haiku 4.5,
replicated with Sonnet 4.6 + Opus 4.7 at N=11.

**Finding**: on the synthetic fixture, all-3-RC saturates at N=11
(100%) and stays at 98-100% through N=144. False-lead rate increases
slightly with N (0.64 → 0.99 from N=11 to N=144). Saturation
generalizes across all three model classes (Haiku/Sonnet/Opus all hit
100% all-3-RC at N=11). Higher-capability models reduce noise
(~30% fewer false leads) but not signal.

**Caveat (F6 finding)**: the synthetic fixture telegraphs answers
in its symptoms. Saturation may be fixture-specific, not general.

**Implication for skill**:
- Default N=15 (saturation point + safety margin).
- Cost-warn at N>50 (no measured benefit on rubric scoring).
- Higher N is acceptable for discovery mode where divergent ideas
  matter; rubric mode capped at 50 by default.
- Cross-model replication built into meta-mode workflow.

**Captured in**: `references/discovery-mode.md` Step 2,
`references/rubric-mode.md` Step 2.

---

## 2026-04-30 — M5 prompt-detail × code-context ablation

**Source**: M5 task; 2×2 × N=15 per cell × Haiku 4.5.

**Finding**: detailed framework prompt (≥800w) + lean code context
produces the lowest false-lead rate (0.73 vs 1.60 worst). All cells
saturated on root-cause coverage. Effect size small (~0.74 FL/persona
gap), n=15 per cell underpowered for strong claims.

**Implication for skill**:
- Default persona prompt template uses detailed framework body
  (≥800w from inventory).
- Default problem statement is structured-but-lean (symptoms +
  constraints + question; not appendix-heavy).

**Captured in**: `templates/dispatch-prompt.md`,
`templates/pre-registration.md`.

---

## 2026-04-30 — F6 fixture-validity test

**Source**: F6 task; 2×2 (loose vs structured problem × casual vs
rubric scoring) on real code-graph problem with known root causes.

**Finding**: B1 (casual scoring) and B2 (rubric scoring) measure
**orthogonal constructs**. Cohen's kappa = 0.0 on the same persona
outputs. B1 measures plausibility; B2 measures pre-specified
correctness. Loose problem + rubric scoring returns 0% RC endorsement
(uninterpretable). Structured problem + LLM-judge produces meaningful
rubric scoring. Off-rubric "novelty" in loose-problem mode is mostly
generic diligence advice, not insight.

**Implication for skill — load-bearing**:
- Two distinct modes (discovery vs rubric) — never average their
  outputs.
- Discovery uses loose problem + non-automated synthesis.
- Rubric uses structured problem + dual scoring (keyword + LLM-judge)
  with kappa report per RC.
- B1-style scoring (Haiku as casual rater) is rejected as a
  standalone measurement — only used in discovery for surface-clustering.

**Captured in**: SKILL.md mode separation, `references/scoring-disciplines.md`.

---

## 2026-04-30 — Red-team self-critique of M4/M5/F6 methodology

**Source**: red-team exercise after publishing M4/M5/F6 conclusions.

**Findings**:
- Synthetic fixture telegraphed answers (RC1 cue in symptoms text)
- Keyword scoring designed after seeing samples (p-hacking)
- Bucket-coverage sampling tautologically saturates at N=11
- No null-framework or no-framework controls
- Single seed across all M4 cells

**Implication for skill**:
- Pre-registration discipline mandatory in rubric mode (file timestamp
  vs first dispatch lock).
- Default sampling = bucket-coverage but `--sampling random` available
  for tests of whether coverage emerges naturally.
- Meta-mode supports null-framework and no-framework controls (via
  manual fixture configuration).
- Meta-mode encourages multi-seed (`--seeds 5+`).

**Captured in**: `references/rubric-mode.md` pre-registration step,
`references/meta-mode.md` controls section.

---

## 2026-04-30 — Multi-inventory bias check (proposed, not yet run)

**Source**: red-team residual concern that the 144-framework
inventory is curator-biased.

**Mitigation designed**:
- Skill supports `--inventory PATH` for multiple inventories.
- Three slots: canonical (current), source-B (LLM-generated alt),
  source-C (public-aggregation). Each with metadata file declaring
  source, date, count, bucket structure.
- Meta-mode workflow can run same problem on multiple inventories
  for cross-comparison.

**Status**: design complete, source-B and source-C inventories not
yet generated.

**Captured in**: `references/inventory-management.md`.

---

## 2026-04-30 — Re-framing M4/M5 claims as preliminary signal

**Source**: red-team of /persona skill itself (severity-rubric review).

**Finding**: the M4 saturation claim ("N=11 saturates rubric coverage")
and the M5 prompt-detail claim ("detailed framework prompt + lean code
context = lowest false-lead rate") rest on a single synthetic fixture
that F6 then identified as telegraphing answers in its symptoms text.
Both findings should be read as **preliminary signal from n=1 fixture,
pending cross-fixture replication** — not as validated methodology.

This is not a contradiction of M4/M5 — it's a downgrade of the
generality claim. Within the one fixture, both findings are real. The
question of whether they generalize to other problems, fixtures, or
inventories is open and requires replication.

**Implication for skill**:
- Skill descriptions and reference docs that cite M4 saturation or
  M5 prompt-detail must qualify as "preliminary, n=1 fixture."
- Default `--n 15` remains (it's a reasonable working default), but
  the skill should not present N=11 as an empirically-validated floor.
- Replication across at least one independent fixture (J finding's
  resolution path) is required before promoting either claim from
  preliminary to validated.

**Captured in**: this entry (no edits to M4/M5 originals per the
"never edit prior entries" policy).

---

## 2026-04-30 — Four rubric-mode validity fixes (G, K, J, H)

**Source**: severity-recalibrated red-team review of /persona skill.
The original red-team conflated rubric-mode validity criteria with
discovery-mode goals; recalibration produced a surgical four-fix
list that strengthens rubric mode without damping discovery's wild
swings.

**Findings**:
- **G** — Cohen's kappa is base-rate-sensitive (Feinstein & Cicchetti
  1990 "kappa paradox"). Flagging `kappa < 0.6` as rubric ambiguity at
  extreme base rates produces false ambiguity flags.
- **K** — `run_rubric` previously let CLI flags silently override
  pre-registered fixture values. Pre-registration that CLI breaks
  silently isn't pre-registration.
- **J** — When fixture-author = inventory-author (or fixture author
  consulted inventory prose), the rubric measures lexical matching
  between two same-frame artifacts, not methodology generality. Self-
  validation risk was not surfaced anywhere.
- **H** — M4 and M5 claims read as validated, but rest on n=1 fixture
  with documented telegraphing.

**Implication for skill** — implemented changes:
- `analyze.py`: kappa table reports both base rates per RC, and the
  `kappa < 0.6` flag fires only when both base rates ∈ [0.2, 0.8].
  Outside that band the table prints "low kappa, extreme base rate —
  kappa unreliable" rather than "rubric ambiguity."
- `dispatch.py` `run_rubric`: argparse defaults for `--n`, `--sampling`,
  `--model`, `--judge-model` changed to `None` sentinel. CLI values
  conflicting with fixture cause hard fail with `cli_override_attempt.json`
  written to run dir. New `--override-fixture` flag opts out
  explicitly; the override is logged and the run is flagged post-hoc.
- `templates/rubric.yaml`: required `provenance:` block with
  `fixture_author`, `inventory_authored_by`, `independent` flag.
  `run_rubric` hard-fails on missing `fixture_author`; prints a NOTE
  about within-frame-only validation when `independent: false`.
- This entry plus the M4/M5 re-framing entry above downgrade
  saturation and prompt-detail claims to preliminary.

**Implication for skill** — explicitly NOT changed (preserves discovery
mode wildness):
- Personas still receive the same dispatch prompt template (no
  three-layer-defense labels added — would damp framework swings).
- Discovery mode still calls its synthesis "manual review" (user-as-
  scorer when user IS the domain expert is not B1 casual scoring).
- 1500-char framework body truncation, bucket-coverage default, and
  no diversity verification all stay — these support discovery's
  novelty-fishing goal.

**Captured in**: `scripts/analyze.py` (G), `scripts/dispatch.py` (K, J),
`templates/rubric.yaml` (J), `references/rubric-mode.md` (J, K), this
entry.

---

## 2026-05-02 — Multi-agent roundtable review (P0/P1/P2/P3 ship)

**Source**: 5-round adversarial roundtable v1 + v2 against /persona +
/plateau-diagnose, three independent reviewers (Opus 4.7, Grok
4.20-reasoning, GPT-5.5-pro), null-control injection (Agent D),
pre-registration substeps. See `~/tmp/PERSONA_RECOMMENDATIONS.md` for
the full P0-P3 list and the v1+v2 META_SYNTHESIS docs.

**Findings (convergent, all 3 reviewers, both rounds)**:
- **DISPATCH_PROMPT_TEMPLATE doc-vs-code drift**: inlined runtime
  template lacked the `[novel]/[default]` calibration tags + "Measurable
  axis" requirement that `templates/dispatch-prompt.md` and
  `discovery-mode.md` claim are required.
- **Inversion mode dual output spec**: `str.replace` left two
  conflicting output requirements blocks in the prompt. Personas
  received contradictory format instructions.
- **Validate mode advertised in CLI / SKILL.md but absent from
  argparser** — 211-line `validate-mode.md` reference described a
  workflow that did not exist in code.
- **Methodology defaults overfit to one telegraphing fixture** (M4/M5/F6
  on the same source). The skill ships those defaults as if validated.
  Already documented in 2026-04-30 re-framing entry; the surface area
  in user-facing description hadn't been narrowed.
- **`run_meta()` is a print stub, not a tested workflow** — public
  description should not list it as operational without caveat.
- **Triage gate has no enforcement** — "Tier 3: Embedded step" in
  prose only; SKILL.md text but no Python check. (Documented; not yet
  fixed in this pass.)
- **Three sessions in a row, the contingency-table failure cell turned
  out to be an instrument bug** — promoted to a Tier-1 ambient rule
  `~/.claude/rules/verify-instrument-before-fix.md`, distinct from
  /plateau-diagnose's Step 6 so the discipline fires regardless of
  skill invocation.

**Implication for skill — implemented changes (2026-05-02)**:

| Recommendation | File(s) touched | Behavior change |
|---|---|---|
| P0 #1 sync template | `scripts/dispatch.py` | `DISPATCH_PROMPT_TEMPLATE` now requires `[novel]/[default]` tag + Measurable axis; output format updated to match |
| P0 #2 remove validate | `SKILL.md`, `references/validate-mode.md` (deleted), `templates/validate-fixture.yaml` (deleted) | Three-mode skill (was four). Examples + reference table updated |
| P0 #3 inversion separate template | `scripts/dispatch.py` | New `INVERSION_PROMPT_TEMPLATE` constant; `build_persona_prompt` selects by mode instead of `str.replace` |
| P0 #4 meta manual-only header | `references/meta-mode.md`, `SKILL.md` | Status banner at top of meta-mode.md; SKILL.md description + mode table reflect manual-only |
| P1 #7 curator-bias warning | `scripts/dispatch.py` (`_warn_curator_bias`) | Stderr warning at dispatch start when inventory metadata flags curator-biased |
| P2 #9 configurable paths | `scripts/dispatch.py` | `PERSONA_DISPATCH_RUNS`, `PERSONA_INVENTORY`, `PERSONA_COHORT_YAML` env vars override hardcoded paths |
| P3 #12 inventory parser logging | `scripts/parse_inventory.py` | Replaced silent body-length filter with explicit-marker + length-fallback; logs every drop to stderr |
| P3 #13 _parse_error skip | `scripts/dispatch.py` (rubric loop) | LLM-judge cache only skipped when judgment has rc1+ keys AND no `_parse_error` |
| P3 #14 INDEX.md locking | `scripts/dispatch.py` (`update_index`) | Sidecar `O_CREAT\|O_EXCL` lock with 10s wait + 100ms backoff |
| /plateau-diagnose Step 1 optional | `skills/plateau-diagnose/SKILL.md` | Step 1 marked OPTIONAL; recipe stands on Steps 2-6 alone |
| Tier-1 verify-instrument rule | `~/.claude/rules/verify-instrument-before-fix.md` (new) | Fires regardless of /plateau-diagnose invocation |

**Implication for skill — DEFERRED with documented runbooks**:

- **P1 #5 Run external-fixture rubric dispatch** — requires an external
  fixture authored by someone who hasn't read the canonical inventory.
  Single test that converts "documented overfitting" into "validated
  within scope." Runbook: see `references/_runbook-deferred.md`.
- **P1 #6 Replace bucket-coverage with axis-independence metric** —
  requires recommendation embedding pipeline (Voyage), 200+ lines new
  code. The bucket-coverage tautology is independent of the fixture-
  leakage critique; cross-fixture replication does NOT fix it.
- **P2 #8 Stop auto-promoting Tier-1 rules from single-session
  recurrence** — architectural change to the rule-promotion mechanism,
  which lives outside /persona. Out of scope for this pass.
- **P2 #10 Honesty surface (full code-enforce Step 0 + content-hash
  pre-reg)** — partially shipped (P1 #7 + P2 #9). Remaining: structured
  AskUserQuestion triage form + content-hash check on pre-reg.
- **P3 #11 Context-bundle hybrid for closed-context dispatch** — new
  feature, ~300 lines. Spec in `references/_runbook-deferred.md`.

**Captured in**: `scripts/dispatch.py`, `scripts/parse_inventory.py`,
`SKILL.md`, `references/meta-mode.md`,
`~/.claude/skills/plateau-diagnose/SKILL.md`,
`~/.claude/rules/verify-instrument-before-fix.md`, this entry,
`references/_runbook-deferred.md` (new).

---

## Template for future entries

```
## YYYY-MM-DD — <experiment name>

**Source**: <task / context>

**Finding**: <one paragraph>

**Implication for skill**: <bulleted list of changes to defaults,
workflows, references>

**Captured in**: <files updated>
```

Append to bottom of this file. Never edit prior entries (history is
informative). When a finding supersedes an earlier one, write a new
entry that explicitly references and supersedes the old one.
