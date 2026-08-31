---
name: red-team-axes
description: "Break a HARDENED target by rotating ATTACK axes, driven by the harness red-team platform (generator + oracle portfolios). Use when adversarial attempts refuse and a fresh attack angle is needed — trigger phrases: 'target refuses', 'attacks not landing', 'nothing cracks', 'red-team plateau', 'hardened target', 'new attack angle', 'find more attack surface'. Maps the six search axes onto the harness generators (bare-ctf / triage-rank / multi-agent / variant-seeded) and oracles (reproducer / fp-check / property / tiered), and enforces tested-refuted vs untested before calling a sink hardened. Do NOT use for non-adversarial search (use /search-axis-rotate), a single already-known vuln, or a target with no measurement/oracle available."
argument-hint: "<target> <sinks/predicates that refuse>"
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Read, Grep, Glob, Bash
compatibility:
  optional:
    - repo: harness
      path: ~/Documents/GitHub/harness
      fallback: "Run the axes manually; read harness/README.md + HANDOFF.md if the repo is present, else use the generator/oracle concepts directly."
effort: medium
---

# Red-Team-Axes

> The adversarial specialization of `/search-axis-rotate`. When a target refuses across attempts, rotate the ATTACK axis — and instantiate each axis with the harness platform, which already embodies this: its headline result was **recall 3→15-22 from a different GENERATOR, not a better model** ("methodology, not capability"). Do NOT rebuild the harness; drive it.

**Read first if present:** `~/Documents/GitHub/harness/HANDOFF.md` (live state + gotchas) and `README.md` (model + layout). The oracle/generator portfolios below are the harness's actual spine.

## Arguments
- `target` — the model/agent/system under test.
- `sinks/predicates that refuse` — what you have failed to make fire (the refusing surface).

## Step 1 — Map refusing vs cracked surface
Enumerate what already fires (cracked cells/vulns) and what refuses. The refusing surface is the search space; the cracked surface tells you which axes have already paid off.

## Step 2 — Rotate the attack axis via the harness

| Axis | Harness instantiation | How to drive it |
|------|----------------------|-----------------|
| **Representation** | generator prompt-shape | multi-turn / encoded / obfuscation-lubricant variants of a firing attack |
| **Diversity** | `generators/` portfolio | rotate bare-ctf → triage-rank → multi-agent → variant-seeded; **partition the space** so agents don't rediscover the same finding (decorrelate) |
| **Measurement** | `oracles/` portfolio + `substrate/scoring/` | **READ the oracle/scorer SOURCE first** (`oracles/route.py`, `score_tier_v2.py`) — the single highest-yield rotation; then route: crash→reproducer, invariant→property, sink→fp-check, composed→tiered_gate |
| **Orchestration** | `intake/run_intake.sh` | chains generator→gate→oracle read-only on a real target; parallelize generation, keep oracle eval serial if a shared resource bottlenecks |
| **Mechanism-class** | new generator / attack class | when one class refuses, switch KIND (injection→persona→indirection→fabricated-auth); one probe per class |
| **Method-blindspot** | the harness's own known gaps | crash-oracle has ZERO recall on logic/auth bugs; PARTIAL-mode sampling is prefix-biased — audit what your generator/oracle never evaluated |

**Default first rotation: MEASUREMENT — read the oracle/scorer source.** In real campaigns it repeatedly turned blind attack-spam into targeted search (per-lane scoring, hidden auth/scope dimensions, cell-collapse rules).

## Step 3 — Decorrelate the generators (diversity axis)
Partition the search space so parallel generators attack different surfaces (per `absorb-frontier-red-team` M5: "each agent focuses on a different file … reduces finding the same bug hundreds of times"). Triage-rank first, then sweep highest-risk.

## Step 4 — TESTED-refuted vs UNTESTED (the honesty gate)
A sink/predicate is **hardened (TESTED-REFUTED)** only when measured to refusal across a CLASS of mechanisms (+ ideally a direct probe of the exact scored condition) — not after one attempt. Otherwise it is **UNTESTED** — rotate to it. `reproduced@k=0` means "no crash-class result", NOT "no finding" (the crash oracle is blind to logic/auth/design bugs — the majority class on real code).

FORBIDDEN: calling a target/sink hardened from a single refusal or one mechanism class. FORBIDDEN: reading an oracle's silence as absence without checking that oracle covers the finding's class.

## Step 5 — Route real findings
Real findings are the operator's call to route (Linear / message) — the harness does NOT auto-route to the target repo. Persist per-finding verdicts incrementally (harness gates are crash-safe by policy).

## Output
- Refusing vs cracked surface map.
- Axes rotated + the harness generator/oracle used for each.
- What the oracle/scorer source read revealed (the measurement-axis payoff).
- Per refusing sink: TESTED-REFUTED (mechanism-class evidence) or UNTESTED (next rotation).

## Examples

**Example 1 — hardened sinks (JED, 2026-07).** shell.run + http.post-int refused. Rotated: representation (multi-turn), diversity (decorrelated swarm), **measurement (read scoring_v2.py → found per-lane scoring + auth dimension)**, orchestration (dynamic workflow), mechanism-class (8 injection classes via a workflow). Verdict: both sinks TESTED-REFUTED — 8 mechanisms + a direct private-IP probe all refused. Documented as a hardening finding, not an assumed wall. EXFIL, by contrast, cracked on the representation axis (obfuscation-lubricant multi-turn).

**Example 2 — real-target intake.** New crate to audit → drive the harness `intake/` real-target pipeline (read-only; it stages a scratch copy so the target tree is never written), which chains generator→gate→execution-oracle; CONFIRMED = observed crash. See the harness repo's README for the runbook. Rotate generators only once the thin loop is measured to fail (a reason to engineer, not before).

## Success Criteria
- Refusing surface mapped; ≥1 attack axis rotated via a named harness generator/oracle before any "hardened" claim.
- The oracle/scorer source was read (measurement axis exercised).
- Every "hardened" verdict is TESTED-REFUTED across a mechanism class, with evidence — never assumed from one refusal.

## When NOT to use
- Non-adversarial search/optimization → use `/search-axis-rotate`.
- A single already-characterized vuln (just fix/report it).
- No oracle/measurement available for the target (build one first — `/build-measurement-harness`).

## References
- `/search-axis-rotate` — the general parent; this is its adversarial specialization.
- `~/Documents/GitHub/harness` — `HANDOFF.md`, `README.md`, `generators/`, `oracles/`, `intake/`.
- `[[break-plateau-by-axis-rotation]]` (memory) + `absorb-frontier-red-team.md` (M5 decorrelation).
- Measurement rules: `verify-effectiveness.md`, `verify-instrument-before-fix.md`, `uncharted-vs-refuted.md`.
