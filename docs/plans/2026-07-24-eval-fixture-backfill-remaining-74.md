# Eval-fixture backfill — plan for the remaining 74 skills

**Status:** wave 0 shipped (PR #1701). Waves 1-3 planned, not started.
**Measured:** 2026-07-24 against `origin/main` @ e5a29cd8.
**Re-derive any number here with** `python3 scripts/measure-eval-coverage.py`.

---

## 1. Where things stand

| | before #1701 | after #1701 | target |
|---|---|---|---|
| skills with a CI-gating `deterministic:` fixture | 27 / 105 (26%) | **31 / 105 (30%)** | see §6 |
| enforced assertions | 121 | 157 | — |
| uncovered | 78 | **74** | — |

Wave 0 shipped `mega-distill`, `retro`, `supergoal`, `cc-monitor` — the four
uncovered skills with the most accrued friction across 79 sessions in the 14-day
transcript extract.

**"Has a YAML" is not "has a CI gate."** `run-skill-evals.py` returns `[]` and skips
silently when a fixture has no `deterministic:` block. Coverage must always be measured
on the deterministic count, never on file existence. (Currently 0 qualitative-only
stragglers — keep it that way.)

---

## 2. Wave structure

Batched by **whether a regression would cost anything** (invocation count) and **whether
a defensible non-tautological assertion is even available** (audit findings / scripts /
references as anchors).

### Wave 1 — 16 skills, invoked at least once

A regression here has already-demonstrated blast radius.

| skill | invocations | findings | scripts | refs |
|---|---|---|---|---|
| `garden` | 40 | ✓ | 2 | 2 |
| `gather-claude` | 18 | ✓ | 4 | 9 |
| `pull-repos` | 13 | — | 0 | 0 |
| `deep-dive` | 11 | ✓ | 2 | 6 |
| `roundtable` | 6 | ✓ | 14 | 5 |
| `mcp-diagnose` | 5 | ✓ | 1 | 0 |
| `gather-intel` | 4 | ✓ | 2 | 9 |
| `retrospective` | 4 | ✓ | 0 | 1 |
| `monitor` | 4 | — | 0 | 0 |
| `audit-rules` | 2 | ✓ | 7 | 0 |
| `review-learnings` | 2 | ✓ | 1 | 1 |
| `brainstorm` | 2 | ✓ | 0 | 0 |
| `api-ingest` | 1 | ✓ | 0 | 9 |
| `provision` | 1 | ✓ | 0 | 3 |
| `mega-capture` | 1 | — | 0 | 0 |
| `run-status` | 1 | — | 0 | 0 |

Start with `garden` and `roundtable`: `garden` is the most-invoked uncovered skill and
already has pytest coverage of its analyzer (so the eval layer complements rather than
duplicates); `roundtable` has 14 scripts, the richest `script_exists` / `script_runs`
surface in the corpus.

### Wave 2 — 44 skills, zero invocations but anchorable

Zero recorded invocations, but each has audit findings and/or scripts — so a
behavior-pinning assertion is genuinely available. Highest-anchor first: `persona`
(8 scripts, 9 refs), `sharp-edges` (16 refs), `agentic-actions-auditor` (12 refs),
`codeql` (12 refs), `scout-skills`, `absorb`, `scout-frontier`, `vendor-breach`.

### Wave 3 — 14 skills, thin anchor surface

Zero invocations, no audit findings, no scripts. 13 of the 74 have **no anchor at all**
(no scripts, no refs, no findings). See §6 — this wave is where coverage risks becoming
theater, and my recommendation is *not* to fixture most of it.

---

## 3. Per-shape assertion strategy

### (a) Audit findings + scripts — the strong case

1. **Pin fixed bugs, not historical ones.** Check current state first (§5 risk A).
2. `script_exists` on every load-bearing script; `script_runs "<script> --help"` on the
   entrypoint (catches import-time breakage — a silent whole-skill outage).
3. `body_contains` on named invariants and hard-won measured numbers.

### (b) Audit findings only

Pin the corrected state of each finding plus documented routing/guard rules:
thresholds, "do NOT use for X" boundaries, named gates, ordering constraints
("checked FIRST"). Prefer strings a *deliberate* edit would change and an accidental
one wouldn't.

### (c) Neither — be honest

For a zero-invocation, script-less, finding-less skill there is often **no defensible
behavior-pinning assertion available**, only structural boilerplate. The minimum honest
set is:

```yaml
deterministic:
  - frontmatter_equals: {name: <skill>}   # pins the invocation contract
  - references_resolve: true              # only if it HAS references
  - body_contains: "<the skill's single load-bearing routing rule>"
```

If the third line cannot be filled with something a regression would actually break,
**write no fixture** and record the skill as deliberately uncovered. Do not pad to make
a coverage number move.

---

## 4. Mechanical non-vacuity verification — keep the gate, drop the agents

Wave 0 used one authoring agent + one adversarial LLM mutation agent per skill. At
2 agents × 74 skills that is ~148 high-effort agents. **Don't.**

`scripts/mutation-check-evals.py` (shipped in #1701) already does the mutation pass
mechanically: it snapshots, breaks each pinned contract, re-runs the harness to confirm
the assertion fails, restores via `try/finally`, and re-verifies green.

**Measured: the entire 31-fixture corpus in 13 seconds.** It found 0 tautological and 0
malformed assertions across all 157 assertions, and independently reproduced the LLM
agent's `retro` verdict (10/10 bite) — two methods agreeing where they are genuinely
independent.

### CORRECTION (2026-07-25): scope of what the gate proves

An earlier revision of this plan called it an "anti-tautology gate." **That overstates
it.** Measured: `body_contains: "## Examples"` — the canonical weak assertion this plan
itself cites — is reported **BITES**, because deleting `## Examples` genuinely does fail
the assertion. Ditto `body_contains: "e"` (BITES after removing all 2,847 occurrences).

The gate proves **coupling**, not **meaningfulness**:

| | |
|---|---|
| **UNIQUELY CATCHES** | **vacuously-passing assertions** the harness cannot see. Proven on `gather-vendor` (3 files in `references/`, 0 cited in the body): `references_resolve: true` → harness **exit 0, "1 passing"**; gate → **exit 1, TAUTOLOGICAL**. Cite nothing and the assertion passes trivially, forever, on any skill. |
| **ALSO CATCHES** | `TAUTOLOGICAL` generally (decoupled / shadowed), `UNMUTATABLE`, `BASELINE_NOT_GREEN`, `RESTORE_FAILED` |
| **NOT UNIQUE** | `MALFORMED` — the harness already hard-fails on it (verified: exit 1). Wave 0's 21-assertion case was caught by the harness, not by this gate. |
| **MISSES** | coupled-but-meaningless assertions — no mechanical check can judge these |

So "is this assertion worth having?" stays **authoring-time human judgment**, per the
two questions in `tests/README.md`. The gate is a floor (nothing *inert* ships), not a
quality bar.

**Why gate anyway, given the corpus currently has 0 instances?** Because the vacuity
class scales with fixtures-written-in-bulk, which is precisely what waves 1-3 are. At 31
hand-checked fixtures the risk is theoretical; at ~92 written across waves it is the
most likely way fake coverage enters. Gating now costs 13s/PR and makes the floor
structural instead of dependent on whoever reviews the wave.

Revised cost: **~1 authoring agent per skill + one 13s mechanical gate per wave**, i.e.
roughly *half* the projected agent count. Reserve LLM mutation agents for the handful of
skills where the mechanical mutator reports `UNMUTATABLE`.

### Wired into CI (2026-07-25)

At 13s it is cheap enough to gate, and it is now a merge requirement — step
"Skill eval non-vacuity gate" in `.github/workflows/validate.yml`, immediately after
"Skill deterministic eval harness":

```yaml
- name: Skill eval non-vacuity gate
  run: python3 scripts/mutation-check-evals.py --all
```

---

## 5. Risks

**A. Asserting bugs that are already fixed — the big one.**
3 of wave 0's 4 skills had AUDIT-FINDINGS entries already fixed (`cc-monitor` ×2 A1
HIGH, `retro` D2). A fixture asserting the *bug* fails immediately, and the tempting
"fix" is to weaken it into a tautology. **Mitigation:** grep the current file for every
candidate string before asserting; pin the corrected state. Treat AUDIT-FINDINGS as
*historical*, never as current state.

**B. Assertions that gate nothing. NOT mechanically mitigated — this is the residual
risk of the whole campaign.** §4's gate catches only assertions that never run or are
decoupled. A *coupled-but-meaningless* assertion (`body_contains: "## Examples"`) is
reported BITES and sails through. The skill-rubric validator already covers structure,
so a fixture that re-asserts it adds a green check and zero enforcement. **Mitigation is
review, not tooling:** for each assertion ask "would a plausible regression remove this
string?" — and treat a wave whose fixtures are mostly structural as a failed wave even
when the gate is green. This is the one place where scaling the backfill can quietly
manufacture fake coverage.

**C. CI runtime.** `script_runs` shells out per assertion with `cwd = skill dir`. Full
harness is currently <1s; the mutation gate is 13s and grows roughly linearly with
assertion count. At 105 skills × ~6 assertions expect ~45-60s for the mutation gate —
still acceptable, but re-measure at wave 2 and cap `script_runs` to entrypoints only.

**D. Over-pinning prose that is expected to change.** A fixture that breaks on every
legitimate SKILL.md edit trains people to weaken fixtures. Pin *contracts* (thresholds,
routing rules, guard names, script paths, corrected-bug strings) — not narrative wording.
Rule of thumb: if a copy-edit would break it, it's over-pinned.

**E. Two harness sharp edges** (both hit live in wave 0, both documented inline in the
shipped fixtures):
- Each `deterministic:` item needs **exactly one key**. A sibling `pins_what:` makes the
  assertion `malformed` and it never runs — an initial `mega-distill` draft had 21
  assertions, all silently dead. Rationale goes in comments.
- `body_contains` does **not** see frontmatter. `supergoal` declares its whole
  `type:agent` Stop-hook prompt in frontmatter; those contracts need
  `frontmatter_contains`.
- A `contains` assertion is satisfied by **any** occurrence, so a mutator replacing only
  the first occurrence false-positives "tautological" (`retro` pins `"10+ turns"` ×2 and
  `"/distill"` ×9). Already fixed in the shipped mutator; relevant if anyone writes
  another one.

**F. `script_runs` cross-platform.** Wave 0's `supergoal` fixture is the corpus's first
`script_runs`. It passes on windows-2022 / macos-14 / ubuntu — `python3` resolves on all
three, and `state_io.py` guards `fcntl` behind `sys.platform == "win32"`. Any new
`script_runs` must be checked on the Windows leg, which is its only oracle.

---

## 6. Recommendation on the 58 zero-invocation skills

**Position: fixture wave 2 (44, anchorable). Do not fixture most of wave 3 (14).**

For wave 2 the anchors are real — audit findings are already-diagnosed bugs, and
`script_exists` / `script_runs` catch deploy-shaped breakage regardless of invocation
count. A skill nobody has invoked yet is exactly the one whose rot goes unnoticed, and
the marginal cost is one agent plus 13s of gate.

For wave 3 — and specifically the 13 skills with **no scripts, no references, and no
findings** — a fixture could only assert `frontmatter_equals: {name: X}` plus boilerplate.
That moves coverage from 30% toward 100% while gating nothing, which is worse than an
honest gap: it converts a visible "78 skills untested" into an invisible "105/105
covered" that no longer prompts anyone to look.

Concretely: several of wave 3 are thin satellites of already-covered skills
(`supergoal-pause`, `supergoal-resume`, `superplan-loop`, `superplan-status` orbit
`supergoal`, which now has a fixture). Their real contract is *shared state-file
behavior*, already tested by `skills/supergoal/tests/` pytest. Duplicating it as prose
assertions adds maintenance, not signal.

**Proposed end state: ~92 of 105 skills fixtured (88%), with the remaining ~13 recorded
as deliberately uncovered** in `scripts/measure-eval-coverage.py` output — an explicit,
reviewable list rather than an implied 100%.

---

## 7. Sequencing

1. **Approve or reject the CI gate** (§4). Cheap, and it makes every later wave
   self-policing.
2. **Wave 1** (16 skills) — start `garden`, `roundtable`, `gather-claude`, `deep-dive`.
   Per skill: read SKILL.md + manifest + its AUDIT-FINDINGS section, verify each
   candidate string against the *current* file, author, run the harness, run
   `mutation-check-evals.py --skill <name>`.
3. **Wave 2** (44 skills) in batches of ~8, mechanical gate per batch.
4. **Wave 3 triage** — decide per skill whether an honest anchor exists; record the
   deliberate-uncovered list.
