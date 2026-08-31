# Skill Design Audit — Wave 2 (Prompt-Only Skills)

**Date:** 2026-05-31
**Scope:** The 67 skills in `skills/` that ship **no executable Python/shell of
their own** — the SKILL.md (plus `references/`, templates, `.ql` text) *is* the
implementation. (The 24 coded skills are in the Wave 1 report.)
**Method:** Every file under each skill read; every description/SKILL.md claim
checked against the rest of the content and against on-disk referents (sibling
skills, scripts, rules). Judged on design quality, not code correctness.

## Claim-honesty rubric (H0–H3)

A prompt-only skill cannot run a deterministic check, so the key axis is whether
its language matches what a prompt can actually deliver:

| H | Meaning |
|---|---------|
| **H0** | Theater — claims deterministic verification/grounding it cannot perform |
| **H1** | Overstates rigor — "automated/enforced/measured" with no backing mechanism |
| **H2** | Mostly honest, minor overclaim |
| **H3** | Honest about being judgment/orchestration, OR backs "verify" with a real external tool/script it invokes |

**Headline:** the corpus skews strongly honest — **57 of 67 are H3**, 7 are H2,
3 are H1, and **none are H0**. Where skills say "verify/validate," it is almost
always delegated to a real external binary (`codeql`, `semgrep`, `gh`, `aws`, the
oracle's `verify_server.py` / `fix_loop.py`) rather than asserted in prose. Two
Wave-1 verification claims were re-confirmed against on-disk code here (see
"Cross-cutting"). The genuine defects are stale pointers, a few tool-surface
mismatches, and three "enforced/automated" mislabels.

---

## Scoreboard

### Security / audit
| Skill | H | Grade | One-liner |
|-------|---|-------|-----------|
| `differential-review` | H3 | A | Honest diff-review; best optional-`gh`-with-`git diff`-fallback handling in the corpus. |
| `agentic-actions-auditor` | H3 | A | Static GH-Actions AI-injection audit; references carry real detection logic + FP sections. |
| `codeql` | H3 | A | Honest CodeQL-CLI orchestration ("zero findings needs investigation"); ships no `.ql` by design. |
| `audit-fix` | H3 | A | **Real** oracle-backed fix loop (`verify_server`/`fix_loop` confirmed on disk); missing only a pre-VERIFIED specificity-check. |
| `stig-verify` | H3 | A− | The most claim-honest skill: cleanly separates the built manual path from unbuilt automation. `Write` missing from allowed-tools vs CKLB mutation. |
| `semgrep-rule-creator` | H3 | A− | Test-first rule authoring, all verification via the real `semgrep` binary; stale `static-analysis` skill name. |
| `fp-check` | H2 | B+ | Bias-aware FP triage; "algebraic proof" gate + prompt-based "enforcement" hook overstate; `Edit/Write` + `Agent/Task` over-broad for read-only. |
| `security-alerts` | H3 | B+ | Honest `gh`-driven Dependabot/CodeQL remediation; `allowed-tools` omits `Write/Edit` despite writing PRs. |
| `stig-assess` | H2 | B+ | Rigorous anti-rationalization content; guarantee-flavored success criteria on the script-less path; red-team mutates CKLB without a confirm gate. |
| `guardrail` | H2 | B | Honest S3 round-trip; but `test` mode *simulates* the proxy regex/PII engine while presenting MATCHED/MISSED as ground truth. |

### Knowledge / memory
| Skill | H | Grade | One-liner |
|-------|---|-------|-----------|
| `distill` | H3 | A | Tightest of the cluster; its one rigor claim (marker schema) is genuinely CI-enforced. |
| `index-repo` | H3 | A | Gold-standard honest "hard gate": every validation check is falsifiable + incident-grounded. |
| `codebase-memory-quality` | H3 | A− | Minimal correct tool surface; verifies dead-code candidates before recommending deletion. |
| `codebase-memory-tracing` | H3 | A− | Most epistemically careful: treats the graph as fallible, tells the agent how to catch gaps. |
| `obsidian` | H3 | A− | Security-aware ops runbook that fails loudly; de-dup the password boilerplate. |
| `absorb` | H3 | A− | Best-in-cluster claim honesty ("No vibes rule"); one stale `agent-memory/rules/` path. |
| `capture` | H3 | A− | Well-gated digital-garden capture; deliberate (documented) overlap with `distill`. |
| `review-learnings` | H3 | B+ | Conservative memory audit; `Write/Edit`-vs-allowed-tools ambiguity; step-count drifting toward bloat. |
| `codebase-memory-exploring` | H3 | B | Honest + well-scoped, but `query_graph` is missing from `allowed-tools` while its own Example 2 calls it. |

### Retro / gather / report
| Skill | H | Grade | One-liner |
|-------|---|-------|-----------|
| `gather-research` | H3 | A | The exemplar — its PRIMARY-source freshness framework turns "validated" into an enforced, failure-case-grounded procedure. |
| `deep-dive` | H3 | A | Mandatory non-boilerplate counterfactual + raw-error-diagnosis make its evidence grades trustworthy. |
| `evaluate-repos` | H3 | A | A de-biasing harness: deterministic forbidden-verdict re-dispatch makes "the user decides" real. |
| `retro` | H3 | A | Disciplined single-session orchestrator that brags about what it *stopped* doing (96%-fabrication step removed). |
| `retrospective` | H3 | A− | Heavyweight but self-correcting (documents prior measurement errors); length is the only risk. |
| `weekly-update` | H3 | A− | Hard coverage gates + a dated failure-mode log make its "record of truth" credible. |
| `gather-intel` | H3 | A− | Disciplined community-intel with genuine source-grounding; stale `/skill-creator` eval pointer. |
| `gather-internal-intel` | H3 | A− | Excludes unresolved discussion from memory; candid about missing Slack search scope. |
| `gather-claude` | H3 | B+ | Best-in-class upstream-sync honesty; **`allowed-tools` grants only Exa but the body calls Tavily** → Web Track may break. |

### Planning / goal
| Skill | H | Grade | One-liner |
|-------|---|-------|-----------|
| `plateau-diagnose` | H3 | A | Anti-theater by design — Step 6 "verify the failure cell is real before fixing." |
| `interview` | H3 | A | Model small skill: read-only, anti-softball question discipline, no bloat. |
| `superplan` | H3 | A− | Honest backbone — real `sha256` attestation + a real verification hook behind it; checklist/override triple-statement bloat; `side_effects:[none]` manifest is wrong (Step 5a writes). |
| `superplan-status` | H3 | A− | Exemplary tool-surface honesty ("fields NOT emitted by --show" list). |
| `supergoal-pause` | H3 | A− | Accurate state-machine semantics behind every claim. |
| `supergoal-resume` | H3 | A− | Real SHA-256 tamper-refusal closes superplan's attestation loop; pause/resume borderline fragmentation. |
| `refine` | H3 | A− | Sharp pre-execution enricher; airtight rule cross-referencing; 4 examples a touch long. |
| `brainstorm` | H3 | B+ | Disciplined design-gate; ~40 lines dead weight (redundant DOT graph + mis-numbered examples). |
| `superplan-loop` | H3 | B | Honest "compose `/loop`, don't reinvent a scheduler"; dup `Example`/`Examples`; `superplan-` vs `supergoal-` prefix confusion. |
| `context-budget` | H2 | B+ | Useful token-overhead auditor; stale `# words x 1.3` comment vs `chars/4` code; over-confident "48% reduction is typical." |

### Dev workflow
| Skill | H | Grade | One-liner |
|-------|---|-------|-----------|
| `sharp-edges` | H3 | A | Exemplary index-style design-review; immaculate chaining (every reference + deep anchor resolves). |
| `subagent-driven-development` | H3 | A | "Don't trust the subagent" enforced in the reviewer prompts + disk-verification, not just asserted. |
| `investigate` | H3 | A | Evidence-grounded cross-tool constitution (cited main-thread-auth invariant); "parallel" framing slightly oversells sequential reality. |
| `systematic-debugging` | H3 | A− | Best-in-set methodology; one war story told three times + motivational stats. |
| `work` | H3 | A− | Incident-driven worktree isolation, honest about its cwd limitation; one stale "Windows-path" comment contradicts its POSIX code. |
| `triage` | H3 | A− | Rigorous write-safe triage constitution; `tavily` frontmatter wildcard vs manifest-specific token mismatch. |
| `test-driven-development` | H2 | B+ | Real assertion-quality safeguard; "MANDATORY/HARD GATE" is self-policed prose (no hook); legacy-code section duplicated in body + reference. |
| `verification-before-completion` | H1 | B | The most useful "run the command before you claim" gate — but "**Automated** Verification Gates" is a misnomer; no Stop hook enforces it (the only adjacent hook is non-blocking + targets a different claim class). |
| `validate-changes` | H1 | C+ | Runnable for hooks/rules/MCP, but the skill/creative "PASS/SHIP" verdict is LLM self-scoring; stale "SKILL.md Step 6" pointer (logic is Step 3b). |

### API / MCP / infra
| Skill | H | Grade | One-liner |
|-------|---|-------|-----------|
| `mcp-create` | H3 | A | **Verification gate CONFIRMED real** — Phase 4 runs `verify_server.py` (on disk) whose load test blocks deploy exactly as described. |
| `provision` | H3 | A | Mature, idempotent-by-contract, loud-on-failure multi-system provisioning. |
| `cc-monitor` | H3 | A | Unusually candid about coverage blind spots (Code Desktop OTel = NO); accurate routing. |
| `manifest-gen` | H3 | A | Honestly self-correcting (retracted a bogus 12% stat); names its own footguns. |
| `build-measurement-harness` | H3 | A | Codifies instrument-skepticism as mandatory phases — the cleanest honest-measurement discipline in the corpus. |
| `api-guardrails` | H3 | A | Honest doc-only review checklist (declares its own N/A audit categories); repeated Opus-4.7 rule + an empty `---` section. |
| `bulk-api-script` | H3 | A− | Dense, honest bulk-export pattern; watch the perishable hardcoded API facts. |
| `api-preflight` | H3 | A− | Precise, gracefully-degrading constraint extraction; the constraint_graph.py ownership claim conflicts with api-ingest. |
| `api-ingest` | H2 | B+ | Thorough, honestly-verified ingestion; **contradicts api-preflight** on who owns `constraint_graph.py`; `context7` vs `context7-docs` naming drift. |

### PR / ship / repo
| Skill | H | Grade | One-liner |
|-------|---|-------|-----------|
| `verify-search-result` | H3 | A | A model of honest verification — "verify" means read-and-quote-the-source with hedged AMBIGUOUS handling, exactly as claimed. |
| `pull-repos` | H3 | A | Clean post-revision wrapper; safe default; honest provenance note on the removed mirror-sync. |
| `pr-fix` | H3 | A− | The strongest operational skill — comprehensive, safety-first guardrails, clean reference factoring. |
| `ship-hook` | H3 | A− | Disciplined atomic hook-installer that practices the safety it preaches (`os.replace`); ~production-ready. |
| `scout` | H3 | A− | Model orchestrator: thin where it should be, candidly labels its bias-guards "advisory, not propagated." |
| `linear-status` | H3 | A− | Incident-driven visibility safeguards; relocate the `/tmp` dry-run fixtures. |
| `invite-to-workspace` | H3 | A− | Honest about its blast radius; `AskUserQuestion` missing from `allowed-tools` though the skill mandates a confirm gate. |
| `code-explore` | H3 | B+ | Genuinely evidence-grounded router that over-explains itself (476 lines); `index_directory` is granted then forbidden in-body. |
| `docgen` | H2 | B | Cleanly-hedged front-end to an external doc pipeline; its "verification pass" is the pipeline's, not the skill's. |
| `ship` | H3 | B− | Well-structured shipper undermined by a **stale hardcoded org** `example-apps-org/code-search` (×3; correct = `example-org/code-search`); duplicates the repo map instead of reading `_shared/repo-map.md`. |
| `cross-repo` | H2 | C | Sound `git am` patch-transfer mechanics resting on a **GHES/GHEC dual-platform Repo Map that `_shared/repo-map.md` does not corroborate** — verify the premise (possibly obsolete). |

---

## Cross-cutting findings

### 1. Two Wave-1 verification claims re-confirmed at the source
- **`mcp-create`** Phase 4 calls `mcp-forge-build/scripts/verify_server.py --strict` (resolves on disk); its `check_8b_load` does the runtime import + `list_tools()` enumeration and **blocks deploy on non-zero** — exactly as the SKILL claims.
- **`audit-fix`** drives `bin/audit-skill-oracle.py verify-fix` → `fix_loop.verify_fix_against_refs`, which uses git worktrees and runs the reproducer pre/post (`VERIFIED iff pre_fires and not post_fires`). Real, not prose.

These are the model for the corpus: "verify" earns its keep when it shells out to a real checker.

### 2. The three H1/H2 "enforcement" mislabels (relabel, don't rebuild)
None of `verification-before-completion`, `validate-changes`, or `test-driven-development` is wired to an enforcing hook — the only adjacent hook (`verify-before-assuming.py`) is **non-blocking** and targets "unavailable"-capability claims, not completion gates. Their "Iron Law / HARD GATE / Automated Verification Gates / Verdict: SHIP" language is LLM self-policing. The fix is honest relabeling (e.g. "Self-Run Verification Gates (LLM-executed)") — or wiring a real Stop hook — not deleting the (genuinely useful) discipline.

### 3. Real bugs / staleness worth fixing
| Skill | Defect |
|-------|--------|
| `ship` | hardcodes the **defunct org** `example-apps-org/code-search` in 3 places; should be `example-org/code-search` (per `_shared/repo-map.md`, vacated 2026-04-26). `pr-fix` already uses the right org. |
| `cross-repo` | entire GHES/GHEC dual-platform model (`example.internal`, `~/Documents/GHES/…`) has **zero corroboration** in `_shared/repo-map.md` — confirm the skill isn't obsolete. |
| `api-ingest` ↔ `api-preflight` | **contradict** on whether `/api-ingest` generates `constraint_graph.py` (ingest: "bootstraps a stub"; preflight: "NOT generated by /api-ingest"). |
| `codebase-memory-exploring` | `query_graph` missing from `allowed-tools` but Example 2 + the reference call it. |
| `gather-claude` | body calls `mcp__tavily__*`; `allowed-tools` grants only `mcp__exa__*` → Web Track may be blocked. |
| `invite-to-workspace` | `AskUserQuestion` missing from `allowed-tools` though Step 2 mandates a confirm gate. |
| `gather-claude/intel/internal-intel/research` (×4) | eval sections point at `/skill-creator`, which does not exist. |
| `absorb` | `phase4-file-mapping.md` places `web-search-preference.md` under a nonexistent `agent-memory/rules/` dir. |
| `validate-changes` | stale "SKILL.md Step 6" pointer (actual logic is Step 3b). |
| `semgrep-rule-creator` | stale `static-analysis` skill name (should be `/semgrep`). |
| `work` | stale "Windows-style absolute paths" comment contradicts its POSIX (`$HOME`) code. |

### 4. Tool-surface mismatches (allowed-tools vs behavior)
- **Under-declared writes:** `security-alerts` and `stig-verify` mutate files/PRs but omit `Write`/`Edit` from `allowed-tools` (writes happen via Bash) — reconcile or document.
- **Over-broad:** `fp-check` grants `Edit`/`Write` (and both `Agent` and `Task`) on a `read_only`/`side_effects:[none]` skill; `triage` frontmatter `mcp__tavily__*` wildcard vs the manifest's specific token; `code-explore` grants `index_directory` then forbids it in-body; `superplan` manifest `side_effects:[none]` despite Step 5a writes.

### 5. Pervasive minor bloat (mechanical cleanup)
The tiny `superplan-*`/`supergoal-*` companions duplicate `## Example` and `## Examples` verbatim-ish; `code-explore` (476 lines) and `test-driven-development` duplicate content between SKILL.md and references that progressive disclosure should offload; `systematic-debugging` tells one war story three times. None affect correctness.

### 6. Family-split verdicts
- **`codebase-memory-{exploring,quality,tracing}`** — genuinely distinct (structure / quality / call-trace), non-colliding triggers, differentiated tool surfaces, mutually-consistent redirects. **Keep separate.**
- **`supergoal-pause` + `supergoal-resume`** — share a Bash-only surface, one state file, one lifecycle; the strongest candidate for consolidation into `/supergoal-control {pause|resume}`.
- **The four `gather-*` + `deep-dive`** — overlap is well-managed; every skill carries a reciprocal scope guard with concrete redirects.

---

## Recommended follow-ups (prioritized)

1. **`ship` stale org** — correctness bug; one find/replace (`example-apps-org` → `example-org`) or, better, source the fork facts from `_shared/repo-map.md` like `pr-fix` does.
2. **`gather-claude` Tavily grant** + **`invite-to-workspace` AskUserQuestion** + **`codebase-memory-exploring` query_graph** — three small `allowed-tools` fixes that unblock documented behavior.
3. **`api-ingest`/`api-preflight` constraint_graph contradiction** — pick one owner and state it identically in both.
4. **`cross-repo` premise check** — confirm GHES is still real; if the dual-platform model is dead, retire or rewrite against `_shared/repo-map.md`.
5. **Relabel the H1 trio** — rename "Automated Verification Gates" / "HARD GATE" to reflect LLM self-execution (or wire a real Stop hook).
6. **Sweep the stale pointers** — `/skill-creator` (×4), `absorb` rules path, `validate-changes` Step 6, `semgrep-rule-creator` `static-analysis`, `work` Windows comment.

No skill in this wave is dishonest theater (H0); the corpus is well-scoped and
honest. The work here is hygiene — stale pointers, tool-surface reconciliation,
and three "enforced" mislabels — not redesign.
