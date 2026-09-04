# Rules ratchet plan

Written 2026-09-03 on `feat/rules-ratchet`. Objective: take the always-loaded rule
corpus from 198,971 B to the A/B-qualified 50,000-60,000 B band
(`hooks/rule_context_budget.py`), removing nothing the harness relies on. Every
number below was measured on this branch; the commands are in the appendix so the
table can be regenerated after each step.

## Where the corpus stands

| Measure | Value | Source |
|---|---|---|
| Rule files | 37, 287,551 B | `wc -c rules/*.md` |
| Ambient (no `paths:`; what the ledger counts) | 30 files, 198,971 B, ~72,700 tok | `bin/ambient-load-report.py` |
| Path-scoped | 7 files, 88,580 B | same |
| Path-scoped but effectively universal (`**/tests/**`) | `tdd-quality.md` + `tdd-mutation-testing.md`, 32,627 B | same; effective coding-session load is 231,598 B |
| Derived ceiling | 199,344 B (373 B headroom) | `manifests/ambient-budget.json`: 214,063 baseline − 14,719 ledger |
| Loaded by `profiles/fresh-laptop` | `outcome-over-verification.md`, `claude-md-quality.md` | `install.sh` `starter_rules` |
| Added by `profiles/brandyn-operator` | `operator-discipline.md` | same |
| Author-workstation only | the other 34 rules | |
| Rules with a derived enforcement edge | 9, all `partial` | `manifests/compile.py` `derive_enforced_by` over `settings.json` |
| Dated-narrative paragraphs in ambient rules | 77,903 B (39%) | appendix, detector N |
| GUARD blocks in ambient rules | 85 blocks, 17,602 B; 33 `NO EXCEPTIONS` | appendix, detector G |
| INVARIANT lines in ambient rules | 8,602 B | appendix, detector G |
| Verbatim-duplicate paragraphs (Jaccard > 0.8) | 0 of 452,676 pairs; closest 0.64 | `scripts/test_rule_paragraph_duplicates.py` |
| Load-bearing literals (oracle baseline) | 1,823 across 37 rules | `bin/rule-preservation-check.py extract` |

Two precedents fix the bar. `docs/fresh-laptop-control-audit.md` demoted
`never-stop-early` and `validate-to-improve` as older-model compensation, and both
were deleted today with negative ledger rows (−2,160, −5,034). And
`operator-discipline.md` (1,202 B) is the compact the operator profile already runs
on in place of `check-before-change` + `diagnose-before-fix` +
`verify-before-assuming` (29,910 B): a 25× compression of three "essential" rules
that has been the live operator contract since 2026-09-01.

## Classes

A rule's **primary class** is the reason most of its bytes can go; the action column
says what happens to the rest. Two measured columns cut across classes:

- **narr B** — bytes in paragraphs carrying a dated measurement (`Measured 2026-…`,
  `INCIDENT 2026-…`, a bare date). `AGENTS.md` §8 says the contract stays resident and
  the narrative goes to `rules/incidents/`; 26 of the 30 ambient rules already have an
  incidents file, so this is relocation, not deletion, and the oracle's `--also
  rules/incidents` mode verifies it.
- **hook** — the derived `enforced_by` edge. Coverage is `partial` on all nine, so
  class (i) applies to *sections*, never to a whole rule; the estimate is ~4,500 B.

Classes: (i) **HOOK** redundant with a wired hook; (ii) **DUP** restates another
rule; (iii) **SCAF** older-model scaffolding — step-by-step re-read/restate gates,
phrase-list GUARD blocks, `NO EXCEPTIONS` preambles, the DSL format program that
`rule-authoring.md` itself measured as "marginal on Opus, decisive on Haiku";
(iv) **ESS** essential: stays, shrunk to its kernel. **ESS→skill** is essential text
whose trigger is a skill activity, relocated to `skills/_shared/` as a REQUIRED READ
of its owner skills (the `output-grounding.md` precedent, ledger 2026-08-26).

Scope: A = ambient (counted), P = `paths:` (not counted). Profile: F = fresh-laptop,
O = operator, — = author only. Targets are post-ratchet estimates in bytes.

| Rule | B | Sc | Pr | Class | narr B | Evidence | Action | Target |
|---|---:|---|---|---|---:|---|---|---:|
| agent-delegation | 6,548 | A | — | ESS | 1,750 | hook: `pre-agent-dispatch` injects the same auth warning the "Authentication boundary" section states; `subagent-start-context` does the topic loading. Two dated narratives (2026-08-22 proposal agents wrote the worktree; 2026-08-29 under-delegation) already have incidents anchors. `scripts/test_rule_runtime_coherence.py` pins four auth phrases. Required by superplan. | narratives → incidents; auth section → one line + hook pointer (move the pinned phrases with it or update the test); keep tiers, tool-set-not-prompt, topic table, output contract | 3,000 |
| api-doc-lookup | 2,214 | A | — | ESS | 0 | Domain procedure (`~/Documents/api-docs/`, llms-full caveat, SCHEMA_VS_DATA); no narrative. All five requirers are skills (api-ingest, api-preflight, gather-*-endpoints, gather-vendor). | keep; last-mile candidate for the skill tier if `bin/rule_utilization.py` shows no main-session activity | 1,600 |
| best-in-class-for-cross-model | 6,838 | A | — | SCAF | 1,825 | One directive ("cross-model arms are each vendor's flagship; never silently downgrade") wrapped in a WHY block, 3 INVARIANT+WHY, 5 STEP, 4 GUARD (1,357 B, 4× NO EXCEPTIONS), FAILURE modes and a RELATION commentary. Single requirer: gather-vendor. Overlaps eval-shipping "LLM-rater count is provider-dependent". | delete; ~500 B kernel into `skills/_shared/model-runtime-policy.md` (already read by 18+ skills) | 0 |
| bulk-data | 1,122 | A | — | ESS | 0 | Org-specific (OPA, `falcon_*`, Graph `@odata.nextLink`); already compact. | keep | 1,100 |
| check-before-change | 9,811 | A | — | ESS | 7,922 | 80% narrative: #3b, the 1.5 KB IAM-condition bullet (#8b, already in `agent-memory/topics/aws-infra-s3.md`), the 2026-08-24 sweep. `operator-discipline` #2 is its 300 B compact. Required by 10 skills. | narrative → incidents (exists); 10 checks at one line each | 3,000 |
| claude-md-quality | 1,382 | P | F | ESS | 0 | Fresh core, `**/CLAUDE.md`. | keep | 1,382 |
| compare-by-need | 3,296 | A | — | ESS→skill | 175 | Fires only when assessing external work; requirers absorb, evaluate-repos, gather-intel, scout-skills, scout. Change-type review depth duplicates `UBIQUITOUS_LANGUAGE.md`. 5 GUARD (850 B). | relocate to `skills/_shared/` as REQUIRED READ for the five owners; drop GUARD restatements | 0 |
| complete-the-whole-instruction | 3,856 | A | — | DUP | 822 | Completion-discipline sibling of the two rules deleted today: "Re-read the STEP_1 enumeration", "restate the instruction as enumerated parts", 7 GUARD (972 B). What "done" means is owned by `outcome-over-verification` (fresh core); component-green ≠ done by `verify-effectiveness`; discovered-issue scope by `scope-discipline`. Unique content: the 2026-08-24 named-artifact format contract. No skill requires it. | delete; one ~300 B bullet ("update the original artifact on its own template") into scope-discipline #6 | 0 |
| data-pipeline-live-fire | 3,677 | P | — | ESS | 1,779 | Path-scoped (tf/sql/etl). "Why CI is blind" nine-defect paragraph is narrative already cited to mcp-infra LESSONS-LEARNED. 3 GUARD/NO EXCEPTIONS. | narrative → pointer; keep the four-step sequence | 1,800 |
| diagnose-before-fix | 9,686 | A | — | ESS | 8,631 | 89% narrative: every check carries a dated case (08-14 escalation, 08-26 WAF, 08-24 fallback chain, 08-29 discriminator). hook: `bash-error-classifier` + `post-failure-guide` deliver check #1 at the failure moment. `operator-discipline` #1 is its 250 B compact. Required by 5 skills. | cases → incidents (3 anchors exist); check #1 → hook pointer | 2,500 |
| eval-shipping-discipline | 4,943 | A | — | ESS | 248 | Author marked it "intentionally global"; low narrative. Oracle/rater and experiment-design gates are harness-specific (`skills/_shared/eval-harness-roadmap.md` exists). | keep ship gates; move oracle/rater/experiment gates to `_shared` for build-measurement-harness, search-campaign | 3,000 |
| git-hygiene | 9,823 | A | — | ESS | 4,889 | hook: force-push to main, direct push to main on protected repos (`PUSH_TO_MAIN_RE`), `gh pr merge --admin` (`GH_MERGE_ADMIN_RE`), staged-additions, empty push, post-merge sync (= STEP_8), destructive checkout/clean (`git-destructive-checkout-guard` in the Bash dispatcher) — ~1,500 B of INVARIANT/FORBIDDEN lines say what those hooks already refuse. FORBIDDEN section mirrors the STEP section. Required by absorb, audit-fix, pr-fix, ship, work. | hook-covered lines → one pointer; dated measurements → reference; keep org boundaries, branch prefixes, merge-queue forms, `git cherry`, reconciliation, generated conflicts | 4,000 |
| grading-discipline | 8,243 | A | — | ESS | 5,322 | Kernel = axis table before letter, currency stamps, count provenance. Heartbeat-alarm section (2026-08-25, ~1,700 B) and #5 blast-radius case are narrative. #6 controls duplicate verify-before-assuming #2 and search-efficiency COUNT_OVER_SILENCE. Required by 3 skills. | narrative → incidents; 12 checks at one line each | 2,800 |
| mcp-tool-names | 1,173 | A | — | ESS | 0 | Org MCP quirks (Tailscale DELETE 405, NetCloud 500 cap). | keep | 1,150 |
| operator-discipline | 1,202 | A | O | ESS | 0 | Operator core; the live compact of three 10 KB rules. | keep; it is the target shape for those three | 1,200 |
| outcome-over-verification | 3,986 | A | F | ESS | 143 | Fresh-core stop contract. 4 GUARD (983 B) restate the FORBIDDEN list. The 45-minute budget is repeated in scope-discipline #12/#13. | keep; sole owner of the 45-minute and proof-proportionality rules; GUARDs to one line each | 3,000 |
| platform-constraints | 16,526 | A | — | ESS | 12,934 | 78% narrative; 14 incidents anchors already exist. hook: `bash-tail-buffering-guard` (the 950 B "guard blocking the SAME shape twice" paragraph is about the guard), `zsh-dialect-guard`, `output-secret-redact`, `post-write-edit` (encoding), `bash-security-guard` (ps listing secrets). The BSD-dialect section (1,900 B) restates search-efficiency COUNT_OVER_SILENCE (sentence Jaccard 0.77); the branch-from-stale-`origin/main` and compound-command bullets restate git-hygiene STEP_4/STEP_5 and say so. Required by 8 skills. | dated paragraphs → incidents; hook-covered bullets → pointers; BSD section → pointer to search-efficiency | 3,500 |
| red-team-rubric-discipline | 4,099 | A | — | ESS→skill | 1,068 | Requirers persona, roundtable. "A PROPOSED REMEDIATION IS A DETERMINATION" (2026-08-20, ~900 B) duplicates `AGENTS.md` §9; STEP_1-2 duplicate grading-discipline #2. 7 GUARD (1,019 B). | kernel (mode decomposition, security severity) → `skills/_shared/` for persona, roundtable, red-team-axes; narrative → incidents | 0 |
| reproduce-before-optimize | 2,866 | A | — | SCAF | 461 | One idea (run the reference verbatim before building; spend scarce quota only on validated candidates) as 5 INVARIANT, 6 STEP including STEP_6 "restate the current diagnosis and verify that the action obeys it", 6 GUARD (876 B). Single requirer: search-axis-rotate. | delete; ~400 B kernel into search-axis-rotate's shared read | 0 |
| rule-authoring | 6,057 | P | — | SCAF | 967 | Its thesis is the format program — GUARD phrase lists, DSL, strongwording — that it measured "marginal on Opus, decisive on Haiku" and mandates "for mixed-model routes". The size/budget/delivery section (~1,200 B) is the live authoring contract. | cut to budget/size/delivery + "narrative goes to incidents"; drop the levers and override-pattern tables | 1,500 |
| scope-discipline | 9,614 | A | — | ESS | 2,230 | Kernel = deliverable first, smallest path, Critical/High/Nice/Skip, visible discovered issues, bounded write targets, viable unblock paths. #12/#13 duplicate outcome-over-verification. "Why is this taking so long" (~2,000 B) and the GA-grant comment are narrative with anchors. Required by readiness-review, service-review. | narrative → incidents; #12/#13 → pointer; absorb the named-artifact bullet | 3,500 |
| search-efficiency | 6,558 | A | — | ESS | 5,082 | 77% narrative — every block carries its 2026-08 measurement. hook: `search-path-guard` (BOUND), `zsh-dialect-guard` (ZSH_ZERO quoting, advisory). RECALL_NEVER_CAPPED, JSON_FIELD/JSON_ABSENCE, HANDOFF are essential mechanics. | measurements → incidents (exists); BOUND/ZSH_ZERO → pointers; predicates as one-liners | 2,500 |
| security-confirmations | 7,628 | A | — | ESS | 685 | Posture + named high-risk gates (org tool list). hook: `security-write-confirm` (advisory, which the rule explains), `prompt-secret-scan`, `bash-security-guard`. 10 INVARIANT + 11 REQUIRED + 14 FORBIDDEN, the FORBIDDEN section mirroring REQUIRED (~1,500 B). Required by pr-fix, triage. | collapse the mirror; keep posture, gates, envelope, third-party boundary | 3,500 |
| security-critical-search-verification | 4,911 | A | — | ESS→skill | 1,886 | Fires only on code-intel CALLS/semantic-search claims; requirer verify-search-result. 7 GUARD (1,473 B) including a 700 B 2026-08-18 log-line comment. | relocate to `skills/_shared/` for verify-search-result, code-explore, codebase-memory-*; comment → incidents | 0 |
| security-review-before-pr | 14,542 | P | — | ESS | 6,582 | Path-scoped narrow. Checklists are the contract; "Known Secrets" (one 2,700 B bullet), "tool that PROCESSES secrets" and "Redact by OUTPUT SHAPE" (~3,500 B) are incident write-ups; the untrusted-repo section pins Claude Code v2.1.169-177. | write-ups → new `rules/incidents/security-review-before-pr.md`; keep checklists | 6,000 |
| skill-standards | 30,295 | P | — | ESS | 14,868 | Path-scoped narrow (`**/SKILL.md`). "Pre-push validation" (~7 KB) duplicates `bin/preflight-skill.py --list` and `AGENTS.md` §5/§8; the frontmatter table duplicates the cited official doc. `scripts/test_model_capability_contracts.py` pins 11 literals here. The Step Format research table belongs in the knowledge base. Required by manifest-gen. | cut to authoring contract + pinned literals; procedure → `preflight-skill --list`; research → KB | 10,000 |
| subagent-verification | 6,580 | A | — | ESS | 172 | hook: `subagent-stop`, `task-completed` (completion-contract paths), `worktree-enforcement` (protected-repo writes outside a worktree). 8 INVARIANT + 10 REQUIRED + 11 FORBIDDEN, FORBIDDEN mirroring REQUIRED (~900 B). Dispatch contract duplicates agent-delegation "Required output contract". Required by 4 skills. | hook-covered REQUIRED lines → pointer; collapse mirror; dispatch contract → agent-delegation | 3,000 |
| symmetric-evidentiary-burden | 3,644 | A | — | ESS | 153 | Owns the SUPPORTED/REFUTED/CONTESTED/UNCHARTED verdict set, instrument provenance, READ-vs-GENERATED coverage. 6 GUARD (709 B). Requirer roundtable; merge target for uncharted-vs-refuted. | absorb uncharted's "an unqueried first-party surface is not UNCHARTED" corollary (~600 B); GUARDs to one line each | 3,000 |
| tdd-mutation-testing | 3,031 | P | — | ESS | 221 | `**/tests/**` makes it effectively universal. ~1,300 B is split bookkeeping ("item numbers PRESERVED", "9 references across 7 files") written for humans. | keep verdict table + pointer; drop the split history | 1,500 |
| tdd-quality | 29,596 | P | — | ESS | 15,018 | Second-largest effective load (universal `**/tests/**`). "The Problem / The Rules" (Reddit-sourced 2026-03, "AI agents take the simplest path to green") is older-model scaffolding; items 10-41 are platform gotchas with the full incident inline; two bookkeeping sections about the split. | each item → one-line rule + incidents anchor (file exists); drop the intro and bookkeeping | 8,000 |
| transcript-over-summary | 5,561 | A | — | ESS→skill | 141 | Fires on session-history claims (retro, distill, capture, mega-distill, self-audit); `precompact-priorities` now carries the compaction checklist. 7 INVARIANT + 8 FORBIDDEN mirror the STEPs. | relocate to `skills/_shared/` for mega-distill, distill, capture, retro, retrospective after `bin/rule_utilization.py` measures activity (as output-grounding was) | 0 |
| uncharted-vs-refuted | 8,255 | A | — | DUP | 2,938 | Restates symmetric's verdict set and absence ≠ refutation (its own INTEGRATION section says they pair). 6 GUARD = 2,485 B and 7× NO EXCEPTIONS, both the most in the corpus; three FAILURE narratives from one 2026-04-29 incident; WHY comment lines. Unique kernel: the 2026-08-15 "query the first-party surface first" corollary and "an absence claim needs every surface" (0/361 mutations). Required by 6 skills. | merge kernel into symmetric; delete; repoint `requires_rules` in gather-claude-endpoints, gather-openai-endpoints, gather-vendor, red-team-axes, scout-frontier, search-axis-rotate | 0 |
| verify-before-assuming | 10,413 | A | — | ESS | 5,383 | Kernel = ToolSearch before a capability claim, zero-result controls, dynamic coverage, primary evidence, deployed state, destructive ops, repo targeting. 5b duplicates check-before-change #2; #2 is repeated in search-efficiency, verify-effectiveness, grading; #9 duplicates git-hygiene STEP_2. 3b Slack incident (~900 B), 7b, release-notes bullet are narrative. `operator-discipline` #3 is its 300 B compact. Required by 4 skills. | narrative → incidents (exists); duplicates → pointers | 3,500 |
| verify-effectiveness | 21,773 | A | — | ESS | 8,856 | Largest ambient rule; required by 16 skills. Kernel = state ladder, plumbing + outcome, multi-seam, instrument qualification, regression/mutation, reporting. Twelve dated sections each restate one lesson beside a ~1 KB measurement (the detector counts 8,856 B; by reading ~14 KB is section-level narrative). Ladder repeated in verify-before-assuming #5 and git-hygiene; "Greening a red gate" repeats `AGENTS.md` invariant 3. 6 GUARD (1,156 B). | each section → its REQUIRED line + incidents anchor (3 exist); ladder owned here, pointers elsewhere | 5,000 |
| verify-instrument-before-fix | 4,661 | A | — | DUP | 1,178 | "Verify the instrument before fixing the subject" is verify-effectiveness "Instruments and measurements" + grading #6. The dominant-cell 3-5-sample gate is specific to its four requirers (build-measurement-harness, plateau-diagnose, red-team-axes, search-axis-rotate); the alarm gate duplicates grading's heartbeat section; Gate-plumbing-first appendix (~900 B) is narrative. 5 GUARD (709 B). | dominant-cell + comparable-measurement gates → `skills/_shared/` for the four owners; alarm gate merges with grading's; delete; update `requires_rules` ×4 | 0 |
| web-search-preference | 4,732 | A | — | ESS | 1,922 | Vendor routing and parameter contracts the model cannot know (MCP schema ⊂ REST, topic enum). hook: `tavily-search-cap` enforces the HARD_CAP `max_results <= 5` line; `tavily-research-poll`. 4 GUARD (474 B). Required by 8 gather/deep-dive skills. | HARD_CAP → hook pointer; MCP-vs-REST comment → reference (exists); GUARDs to one line | 3,200 |
| worktree-by-default | 8,409 | A | — | ESS | 1,087 | hook: derived edge is only `git-empty-push-guard`; `worktree-enforcement` blocks protected-repo writes outside a worktree but its manifest does not list this rule (manifest gap). 7 INVARIANT + 11 REQUIRED + 11 FORBIDDEN, FORBIDDEN mirroring REQUIRED (~700 B). MUTATION AND BASELINE SAFETY belongs to path-scoped tdd-mutation-testing. 2026-08-12 driver incident inline. Required by pr-fix, run-status, work. | collapse mirror; mutation section → tdd-mutation-testing; incident → incidents (exists); add the worktree-enforcement edge | 3,200 |

### Totals by primary class

| Class | Ambient rules | Ambient B | Path-scoped B | Notes |
|---|---:|---:|---:|---|
| (i) HOOK | 0 whole rules | ~4,500 (sections) | 0 | 9 rules carry a derived edge; all `partial`. Sections: agent-delegation auth (~600), diagnose #1 (~500), git-hygiene main/force/admin/destructive/STEP_8 (~1,500), platform-constraints guard paragraph + encoding/ps lines (~1,150), search-efficiency BOUND/ZSH_ZERO (~350), subagent-verification protected-repo lines (~300), web-search HARD_CAP (~60), worktree-by-default protected-repo lines (~100). |
| (ii) DUP | 3 | 16,772 | 0 | uncharted-vs-refuted 8,255; verify-instrument-before-fix 4,661; complete-the-whole-instruction 3,856 |
| (iii) SCAF | 2 | 9,704 | 6,057 | best-in-class-for-cross-model 6,838; reproduce-before-optimize 2,866; rule-authoring (P). Cross-cutting inside ESS rules: GUARD blocks 11,203 B, INVARIANT lists 6,317 B, 19 `NO EXCEPTIONS`. |
| (iv) ESS | 25 | 172,495 | 82,523 | of which dated narrative 70,679 B (relocatable) and four ESS→skill rules 17,867 B (transcript-over-summary, security-critical-search-verification, compare-by-need, red-team-rubric-discipline) |
| Total | 30 | 198,971 | 88,580 | |

Sum of the ambient target column: 60,250 B across 21 rules. Landing inside the band
needs the two last-mile tier moves named in step 8 (api-doc-lookup, the
eval-shipping oracle gates), which take it to ~55,600 B.

## Sequence

Each step is one branch, one ledger row per touched rule (negative, so the saving
cannot be re-spent), and one oracle pass: `extract` before, `verify` after with
`--also rules/incidents --also docs/rule-reference --also skills/_shared`, and an
`--allow-drop` file whose every entry names its reason. Deltas are estimates from the
table; the ledger row records the measured value.

| Step | What | Ledger delta | Corpus after | Preconditions and tests to touch |
|---|---|---:|---:|---|
| 1 (this branch) | Oracle, duplicate gate, this plan. The mechanical collapse of duplicate paragraphs over Jaccard 0.8 was run and found **no targets** (0 of 452,676 pairs; closest 0.64); no rule byte changed, so no ledger row. | 0 | 198,971 | — |
| 2 | Relocate dated-narrative paragraphs to the existing `rules/incidents/<rule>.md` behind `<a id>` anchors: platform-constraints −12,000, verify-effectiveness −12,000, diagnose-before-fix −6,500, check-before-change −6,000, verify-before-assuming −5,000, grading-discipline −4,500, search-efficiency −3,500, git-hygiene −3,000, scope-discipline −2,500, agent-delegation −1,700. Mechanical: a paragraph moves whole; the oracle with `--also rules/incidents` must report 0 lost. | ≈ −56,700 | ≈ 142,300 | `scripts/test_incident_anchors.py` (every `Full: incidents#` must resolve); `test_rule_runtime_coherence.py` agent-delegation phrases |
| 3 | Class (ii): merge uncharted-vs-refuted's corollary into symmetric-evidentiary-burden (+600), complete-the-whole-instruction's named-artifact bullet into scope-discipline (+300), verify-instrument-before-fix's instrument gates into verify-effectiveness (+300) and its dominant-cell gate into `skills/_shared/`; delete the three rules, their manifests, incidents and rule-reference files (the validate-to-improve pattern). | ≈ −15,600 | ≈ 126,700 | `requires_rules` in 10 skill manifests; `compile.py --check`; `skills/audit-rules/tests/test_forbidden_signatures.py` needs ≥10 FORBIDDEN ids corpus-wide |
| 4 | Class (iii): delete best-in-class-for-cross-model (kernel → `_shared/model-runtime-policy.md`) and reproduce-before-optimize (kernel → search-axis-rotate's shared read); across ESS rules reduce each GUARD block to its one distinct fact, drop the "not preference-based; NO EXCEPTIONS within scope" preambles and INVARIANT lines that only restate a REQUIRED line. | ≈ −19,900 | ≈ 106,800 | `requires_rules` in gather-vendor, search-axis-rotate; oracle allow-drop for each removed GUARD phrase, reason "phrase-list compensation" |
| 5 | Class (i): each hook-covered section becomes one line naming the hook (`enforced by hooks/<name>.py`); fix the `worktree-enforcement` manifest to list worktree-by-default so the edge derives. | ≈ −3,800 | ≈ 103,000 | `compile.py --check` (coverage labels vs derived edges) |
| 6 | ESS→skill: measure activity for transcript-over-summary, security-critical-search-verification, compare-by-need, red-team-rubric-discipline with `bin/rule_utilization.py`; for each rule whose scope is active only inside its owner skills, move it to `skills/_shared/<rule>.md`, add a REQUIRED READ line to each owner, keep the rule manifest pointing at the new home (as `output-grounding.yaml` does). A rule that is active in main sessions without its skill stays ambient — that is the falsifier. | ≈ −17,900 | ≈ 85,100 | `test_rule_runtime_coherence.py` shape (`not rules/<name>.md exists`, manifest `_source`); `requires_rules` closure |
| 7 | Collapse the REQUIRED/FORBIDDEN mirror sections in git-hygiene, security-confirmations, subagent-verification, worktree-by-default: keep whichever side carries the distinct fact. | ≈ −4,500 | ≈ 80,600 | oracle: banner/env literals must survive on one side |
| 8 | Kernel compaction of the remaining ESS rules to the target column, one file per branch, oracle per file. Then the last mile: api-doc-lookup to its five api/gather owners and the eval-shipping oracle/rater/experiment gates to `_shared/eval-harness-roadmap.md`. | ≈ −25,000 | ≈ 55,600 | `bin/ambient-load-report.py` for the effective load; re-run the fresh-laptop control audit's context report |
| P | Path-scoped, outside the ledger but inside the effective load: tdd-quality 29,596 → 8,000, skill-standards 30,295 → 10,000, security-review-before-pr 14,542 → 6,000, rule-authoring 6,057 → 1,500, tdd-mutation-testing 3,031 → 1,500, data-pipeline-live-fire 3,677 → 1,800. | — (P) | effective load ≈ −58,400 | `scripts/test_model_capability_contracts.py` (skill-standards literals); `test_rule_runtime_coherence.py` (tdd-mutation-testing `paths:`) |

The order matters. Step 2 is mechanical and large, and it is the step the oracle
was built for; steps 3-5 remove whole rules or sections and need the manifest and
skill-closure edits; step 6 needs a utilization measurement before each move;
steps 7-8 are judgment and go one file at a time so each ledger row is small enough
to review.

## Step 1 result

- `bin/rule-preservation-check.py extract --rules rules` recorded 1,823 literals
  (412 headings, 6 banners, 909 code spans/fences, 130 env names, 261 paths, 3 URLs,
  102 numbers with units); `verify` against the same tree: 1,823/1,823, exit 0.
- `scripts/test_rule_paragraph_duplicates.py`: 952 paragraphs of ≥8 content words,
  0 pairs over 0.8. The closest pairs are all DSL boilerplate — the
  `# Full rationale, examples, and incident history: docs/rule-reference/<name>.md`
  pointer (0.64) and the `# Hard guards / # <X> is not preference-based; NO EXCEPTIONS
  within scope.` preamble (0.60 ×3) — which is itself evidence for class (iii), not
  something to collapse behind a pointer.
- At sentence granularity the closest cross-rule pair is 0.77 (platform-constraints
  BSD section vs search-efficiency COUNT_OVER_SILENCE: "prefer a predicate that emits a
  NUMBER, and pair every zero with a known-positive control in the same command").
  Below the bar; handled in step 2/5 as a pointer, not here.
- No rule bytes changed; no ledger row. The ledger records byte changes, not measurements.

## Executed 2026-09-03 on `feat/rules-ratchet-step1`: the four whole-rule deletions

| Deleted | B | Sentences no surviving rule stated, and where they went | Net ledger row |
|---|---:|---|---:|
| uncharted-vs-refuted | 8,255 | unqueried first-party surface is not UNCHARTED; absence claim needs every surface; world-vs-literature claims; out-of-era sources → symmetric-evidentiary-burden (+1,192) | −7,063 |
| best-in-class-for-cross-model | 6,838 | every cross-model arm is its vendor's flagship; never downgrade silently; state model id and tier → eval-shipping-discipline rater gates (+739) and `_shared/model-runtime-policy.md` item 7 | −6,099 |
| verify-instrument-before-fix | 4,661 | dominant-cell gate; comparable measurement; verify the verifier; code younger than the failure; UNKNOWN over proxy; gate plumbing → verify-effectiveness "Instruments and measurements" (+1,312) | −3,349 |
| complete-the-whole-instruction | 3,856 | hardest part first, no silent "next", design docs before planning; named-artifact format contract → scope-discipline checks 1 and 6 (+743) | −3,113 |

Ambient 198,971 → 179,347 B (−19,624); 33 rule files, 267,927 B. Requirers repointed:
11 skill `requires_rules` entries and 2 skill `enforces` entries (uncharted → symmetric),
`bin/rule_relocation_pilot.py` and `bin/rule_utilization.py` owner sets,
`scripts/test_rule_relocation_pilot.py`, `hooks/judgment-rules.json`, and 39 prose
pointers across 31 skill and reference files. Dated incident narratives and the roundtable
gold fixture keep the old names as historical records. The manifest gap was closed:
`worktree-enforcement.yaml` now lists `worktree-by-default`, so its edge derives.
Oracle: 1,823 literals recorded before; after, every literal outside the four deleted
files is present, and the deleted files' remainder was dropped file-by-file with the
reasons above.

## Executed 2026-09-04 on `feat/rules-ratchet-step2`: the two largest narrative relocations

| Rule | Before | After | Moved to `rules/incidents/<rule>.md` |
|---|---:|---:|---|
| platform-constraints | 16,526 | 10,633 | 13 dated blocks behind new anchors (guard-blocked-six-times, ifs-tab-read, unquoted-heredoc, blocked-compound, background-notification, npm-pruned-jsdom, bsd-dialect-gaps, aws-region-leak, load-dump-round-trip, hash-pinned-lock, stale-origin-main, pre-commit-hidden-by-tail, empty-capture) plus the urllib mechanism under its existing 2026-07-05 anchor |
| verify-effectiveness | 23,085 | 17,990 | 9 dated blocks behind new anchors (probe-own-connection, absent-check, seam-no-instrument, transient-control, placeholder-probe, rotation-revoked-nothing, viewer-local-timezone, skipped-layer, teardown-end-state) plus the ladder mechanism (2026-08-15 anchor) and the pinned-pair example (2026-08-29 anchor) |

Ambient 179,347 → 168,359 B. Every block moved verbatim; each leaves its directive and a
`Full: incidents#<anchor>` pointer. Oracle: 1,699/1,699 literals present with
`--also rules/incidents`, 0 lost, no allow-drop needed. What remains in both files is
directive text (REQUIRED lines, GUARDs, imperatives); reaching the table's 3,500/5,000 B
targets needs step 8 (kernel compaction), which rewrites directives and is a judgment step.

## Executed 2026-09-04 on `feat/rules-ratchet-step2b`: the next four, dated narrative only

Base 05956d3 (PR #11). First, the gap that PR found: `scripts/test_incident_anchors.py`
resolved `Full: incidents#` pointers in `rules/*.md` only, while `docs/rule-reference/*.md`
carries 246 of the same pointers. One resolver (`_dangling`) now runs over both
directories (`POINTER_SOURCES`); a negative control appends a wrong anchor to a temp
copy of a reference doc and expects exactly that report. Measured: 246 reference
pointers, 0 dangling.

| Rule | Before | After | Blocks | Anchors in `rules/incidents/<rule>.md` |
|---|---:|---:|---:|---|
| verify-before-assuming | 10,413 | 9,912 | 3 | `2026-08-12-slack-audit-catalog-largest-group-unread` (check 3b INCIDENT), `2026-08-15-five-defects-off-a-70-commit-behind-copy` (check 5b), `2026-08-15-one-call-probe-both-directions` (closing GUARD citation) |
| git-hygiene | 9,823 | 9,823 | 0 | none. The only dated text is a provenance stamp (`Measured 2026-08-23.`, STEP_6) and a two-date citation (`2 occurrences (2026-08-14, 2026-08-24); both in the reference.`); each is shorter than the pointer that would replace it. The table's 4,889 narr B is detector N counting the whole STEP and FORBIDDEN paragraphs because each contains one date |
| check-before-change | 9,811 | 9,095 | 2 | `2026-08-12-unsatisfiable-iam-condition-third-occurrence` (check 8b narrative plus the closing sentence's dated clause), `2026-08-24-blanket-sweep-broke-data-dir-and-js-key` (Forbidden shortcuts) |
| diagnose-before-fix | 9,686 | 8,680 | 4 | `2026-08-14-escalated-for-admin-role-before-recall` (check 2), `2026-08-26-waf-403-two-independent-rules-live` (check 4), `2026-08-24-fallback-chain-fix-gated-off-by-enum` (check 7), existing `2026-08-29-emit-the-discriminator` (Forbidden shortcuts) |

Ambient 168,160 → 165,937 B (−2,223; PR #11 had taken it from 168,359 to 168,160 in
between). Every block moved verbatim. Where a directive and its dated clause shared one
sentence (check-before-change 8b's closing sentence and the blanket-sweep bullet), the
sentence went to incidents whole and the rule kept the directive half closed with a
period. Oracle per rule, `extract` before and `verify --also rules/incidents` after:
1,608/1,608, 1,605/1,605 and 1,599/1,599 literals present, 0 lost, no allow-drop (the
count falls as moved literals leave the rule tier). Three negative ledger rows: −501,
−716, −1,006.

The yield is 2,223 B against the sequence table's ≈20,500 for these four rules because
detector N counts a whole paragraph when it carries one date, and in these files the
dates sit inside numbered checks, STEP and FORBIDDEN blocks whose other sentences are
directives. What remains is directive text, which is step 8 (kernel compaction, a
judgment step), not relocation. Kept as undated directives: verify-before-assuming
check 4's release-notes paragraph and check 7b; check-before-change 3b; git-hygiene
STEP_4's wrong-base mechanism sentence (already a pointer to the reference).

## Next eight, by expected bytes freed per unit of judgment

1. **platform-constraints.md** 16,526 → ~3,500 — 78% dated narrative (12,934 B), 14 incidents anchors already exist, five hooks cover its guard, encoding and secret lines.
2. **verify-effectiveness.md** 21,773 → ~5,000 — twelve sections each restate one lesson beside a ~1 KB measurement; 3 anchors exist for the rest to join.
3. **uncharted-vs-refuted.md** 8,255 → 0 — restates symmetric-evidentiary-burden's verdict set (its own INTEGRATION section says so); 2,485 B of GUARDs and 7× NO EXCEPTIONS, the most in the corpus.
4. **diagnose-before-fix.md** 9,686 → ~2,500 — 89% dated narrative; two hooks deliver check #1 at failure time; the operator profile runs on its 250 B compact.
5. **check-before-change.md** 9,811 → ~3,000 — 80% narrative; the 1.5 KB IAM-condition bullet already lives in `agent-memory/topics/aws-infra-s3.md`.
6. **best-in-class-for-cross-model.md** 6,838 → 0 — one directive under 1,357 B of GUARDs, a WHY block and a RELATION commentary; its single requirer already reads `_shared/model-runtime-policy.md`.
7. **verify-instrument-before-fix.md** 4,661 → 0 — duplicates verify-effectiveness's instrument section; its dominant-cell gate is specific to its four owner skills.
8. **complete-the-whole-instruction.md** 3,856 → 0 — the completion-discipline sibling of the two rules deleted today; its "re-read the enumeration before saying done" gate is what outcome-over-verification already owns.

## What would change this plan

- `bin/rule_utilization.py` shows an ESS→skill rule active in main sessions without
  its owner skill: it stays ambient (step 6 is per rule, not a batch).
- The oracle lists a lost literal with no allow-drop reason after a "mechanical"
  step: the step was not mechanical; stop and read the diff.
- `scripts/test_rule_paragraph_duplicates.py` goes red during a consolidation: a copy
  was left behind.
- The effective load (`bin/ambient-load-report.py`) does not fall with the ledger:
  the bytes moved to a `paths:` rule that loads anyway (`**/tests/**`), which is the
  loophole `manifests/ambient-budget.json` warns about.

## Appendix: how the numbers were produced

```bash
PY=/tmp/claude-review/venv-claude-harness/bin/python      # any Python 3.11+ with PyYAML
$PY bin/ambient-load-report.py                              # corpus, effective load
$PY manifests/compile.py --root . --no-reindex && $PY manifests/query_engine.py --root . unenforced_rules
$PY -c 'import json;g=json.load(open("manifests/graph.json"));print({k:v["enforced_by"] for k,v in g.items() if isinstance(v,dict) and v.get("type")=="rule" and v.get("enforced_by")})'
$PY bin/rule-preservation-check.py extract --rules rules --out /tmp/rules-before.json
$PY -m pytest -s scripts/test_rule_paragraph_duplicates.py -q                 # Jaccard pairs
grep -c "NO EXCEPTIONS" rules/*.md
```

Detector N (dated narrative): a blank-line paragraph counts if it matches
`\b20\d\d-\d\d(-\d\d)?\b|\bINCIDENT\b|\bMeasured\b`; bytes are UTF-8 of the whole
paragraph. Detector G (scaffolding): a GUARD block is a `GUARD pattern=` line plus its
indented continuation and `#` comment lines; an INVARIANT line is one `^INVARIANT `
line. Both are byte counts, not judgments; the per-rule values are in the table's
`narr B` column and in the class (iii) row.
