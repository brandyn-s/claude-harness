# Eight-component harness map — variant-analysis

`variant-analysis` is the third reference implementation of the harness
pattern in this repo. The first is `audit-skill`; the second is
`mcp-forge-build`. All follow the same eight-component structure,
differing only in problem domain.

## Entry test

The harness framework requires **verification asymmetry**: checking a
candidate solution must be meaningfully cheaper than generating one.

For variant-analysis the asymmetry is structural:

- **Generation** = reasoning about a root-cause statement, climbing the
  abstraction ladder one variable at a time, balancing FP rate against
  recall. Hundreds to thousands of LLM tokens per generalization round.
- **Verification** = running `rg` or `semgrep` against the target tree
  and counting matches. Tens to hundreds of ms per pattern.

The Tier-1 oracle (baseline match against the seed bug) is mechanical:
either the Level-0 pattern matches `seed_file:seed_line` or it doesn't.
The Tier-2 oracle (sandbox executor that runs the pattern over the tree)
is also non-interpretive — the result is an integer match count plus a
list of file:line locations.

The harness pattern fits this domain in the Glasswing/narrow-parallel
sense: each "hunter" is one pattern at one abstraction level. Multiple
hunters run in parallel against the same root cause, and the oracle
gates which ones survive.

## Per-component map

### 1. Proposer

Claude reads the seed-bug context, formulates a **root cause statement**
("untrusted data reaches dangerous op without required protection"),
then emits per-level patterns climbing the abstraction ladder (Level 0
exact, Level 1 variable abstraction, Level 2 structural, Level 3
taint-mode). The five-step procedure in `SKILL.md` documents the loop.

The proposer can be the cheap model in this domain — verification is
doing the quality work. Sonnet generates pattern variations; Opus is
only needed for triage of borderline matches.

### 2. Oracle / verifier (stratified)

`scripts/verify_variants.py` runs the per-hunt verification suite
deterministically:

- **pattern_parse** (Tier 1, mechanical) — `re.compile` for ripgrep
  patterns; `semgrep --validate` for Semgrep rules. Catches malformed
  patterns before they touch the target tree.
- **exact_baseline** (Tier 1, kernel) — Level-0 pattern MUST match the
  declared `seed_file:seed_line`. If the baseline misses the seed bug,
  the entire hunt is invalid — no point climbing the ladder.
- **variant_run** (Tier 2, sandbox executor) — `rg` or `semgrep`
  subprocess against the target tree. Returns the structured match list
  (file, line, snippet) per pattern.
- **fp_rate_gate** (Tier 2, sampled) — if the caller provides a
  sampled FP count via `sampled_fp`, gates the FP rate against
  `fp_rate_cap` (default 0.5 per METHODOLOGY.md). Informational when no
  sample provided.
- **semgrep_validate** (Tier 2) — `semgrep --validate <rule>`
  subprocess; skipped if Semgrep absent.

The script never launders verdicts up the stack: skipped checks report
"skipped + reason" and don't masquerade as passes. Failures surface the
specific violation (e.g., `seed api/users.py:42 not in 0 match(es)`).

What's *not* in the oracle: exploitability triage and fix
recommendations both require human reasoning + reachability analysis
and remain orchestrator/skill-driven.

### 3. Context engineering

Three reference / resource files feed the proposer:

- `METHODOLOGY.md` — abstraction ladder (Levels 0-3), generalization
  rules, FP-rate caps per context, vulnerability-class expansion.
- `resources/codeql/<lang>.ql` and `resources/semgrep/<lang>.yaml` —
  ready-to-fork templates per language. The proposer adapts these
  rather than writing rules from scratch.
- `resources/variant-report-template.md` — the output shape (a
  tracking doc with pattern/level/FP-rate per row).

The hunt-spec.json shape (consumed by `verify_variants.py`) is the
proposer/oracle contract: root cause, seed file + line, per-level
patterns. The proposer emits one of these per hunt; the oracle gates.

### 4. Tool surface (minimal)

The skill declares: `Bash` (rg + semgrep + codeql subprocess), `Read`,
`Grep`, `Glob`, `AskUserQuestion`. No specialized linters — POSIX +
Semgrep + CodeQL carry the verification.

The Vercel d0 lesson applies: fewer tools mapping onto well-understood
primitives (rg, semgrep, codeql) outperform a bespoke variant-hunting
DSL.

### 5. Orchestration / parallelism

Patterns at different abstraction levels are independent: Level-0 and
Level-2 patterns against the same root cause produce disjoint result
sets and can run in parallel. The hunt-spec.json model is per-level;
the harness loops over `patterns[]` and emits per-pattern NDJSON.

When a single root cause spawns multiple **vulnerability-class
expansions** (METHODOLOGY.md §"Expanding Vulnerability Classes" —
e.g., `isAuthenticated` -> `isActive` / `isAdmin` / `isVerified`), each
expansion is a separate hunt-spec.json. Dispatch via the Agent tool
with `parallel=true`; each agent runs `verify_variants.py` on its own
spec; results merge via the hunt-history.jsonl on completion.

The "Glasswing pattern" — narrow-scope hunters that each look for ONE
specific shape, in parallel — is the natural decomposition. A hunter
that tries to be both Level-0 and Level-3 is doing two jobs poorly.

### 6. Memory / skill library

`hunt-history.jsonl` accumulates one row per hunt verification.
`scripts/hunt_history.py {append,diff,summary}` surfaces patterns:

- **`append`** — read NDJSON from `verify_variants.py --ndjson`, write
  one summary row (run_id, root_cause, n_matches_total, per-check
  pass/fail, git_sha).
- **`diff`** — compare last two hunts for trend signals: did pattern
  tightening reduce match count? Did FP-rate gates start passing?
- **`summary`** — repeat-offender checks across all hunts (e.g.,
  "Level-3 patterns trip the FP-rate gate 70% of the time on this
  codebase — start at Level 2 by default").

This is Voyager-style skill-library accumulation in a constrained
domain: per-codebase pattern effectiveness gets remembered between
hunts, informing which abstraction level to start at next time.

### 7. Failure-detection middleware

- **`exact_baseline` as kernel gate** — if Level-0 misses the seed, the
  generalization is built on sand. The check forces early failure
  before the proposer wastes tokens on higher abstraction levels.
- **`fp_rate_gate`** — the 50% FP cap from METHODOLOGY.md is now
  machine-enforced (when sampled FP is provided). Patterns that exceed
  the cap are flagged for revert rather than carried forward silently.
- **`hunt_history.py diff` as a CI gate** — when CI re-runs a hunt
  after a fix, a regression (fewer matches → more matches) flags an
  incomplete remediation. Wire into post-fix CI.

### 8. Observability / audit trail

`verify_variants.py --ndjson PATH` emits one record per check:

```json
{"run_id": "2026-05-30T...", "check": "pattern_parse", "kind": "rg", "pattern_id": 0, "passed": true}
{"run_id": "2026-05-30T...", "check": "variant_run", "kind": "rg", "pattern_id": 0, "passed": true, "n_matches": 1}
{"run_id": "2026-05-30T...", "check": "exact_baseline", "seed_file": "api/users.py", "seed_line": 42, "passed": true}
{"run_id": "2026-05-30T...", "check": "variant_run", "kind": "semgrep", "pattern_id": 2, "passed": true, "n_matches": 7}
{"run_id": "2026-05-30T...", "check": "fp_rate_gate", "n_matches": 7, "cap": 0.5, "passed": true, "reason": "no FP sample provided; gate informational only"}
```

Replayable. Grep-able. The `--json` output is the per-hunt summary; the
NDJSON is the per-check event log feeding `hunt_history.py`.

## Lifting the pattern further

The same eight components apply to other harness candidates in the
corpus. Already lifted: `audit-skill`, `mcp-forge-build`,
`variant-analysis`. Sibling lifts in flight:

- **`insecure-defaults`** — sandbox-executor oracle (Tier 2). Run the
  code without the env var; observe fail-open vs fail-secure startup.
- **`threat-model`** — code-graph CALLS/HTTP_CALLS/USAGE edges as
  Tier-2 oracle. Claim "X crosses Y trust boundary" → verify by
  querying code-graph.
