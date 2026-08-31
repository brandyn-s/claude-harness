# Skill Sense & Effectiveness Critique — Wave 3 (all skills)

**Date:** 2026-05-31
**Question:** not "is it well-built / honest?" (Waves 1–2) but **"does it make
sense and is it effective?"** — three sub-questions per skill:
1. **Problem-validity** — is the problem real, and worth a dedicated skill (vs. baseline Claude, a rule, or another skill)?
2. **Approach-soundness** — is the prescribed method *causally* connected to the goal, or is it ceremony that *feels* rigorous?
3. **Cost/benefit** — does the overhead (tokens, turns, agent fan-outs, user interrupts, maintenance) justify the benefit?

**Scope honesty:** this is a *reasoned* critique, grounded in each skill's actual
mechanism, **not** a measured-outcome evaluation. A "❓ unproven-ceremony"
verdict means *the approach is plausible but its marginal benefit is unmeasured
and often gated on the model complying with long prose* — not that it fails.
Measuring those would need the empirical/A-B work (the other options).

## Verdict scale
- ✅ **Sound** — real problem, causal method, proportionate cost. Keep as-is.
- ⚖️ **Overbuilt** — sound approach, heavier than the benefit warrants (length / fragmentation / agent cost). Trim or merge.
- ❓ **Unproven-ceremony** — plausible, but benefit hinges on structure/compliance and is unmeasured. Prime candidate for a real efficacy harness.
- 🔁 **Redundant** — substantially overlaps a sibling; consolidation candidate.
- ⚠️ **Questionable** — problem-validity/approach doubt, or not-yet-functional.

---

## The five cross-cutting "sense" findings (the real signal)

### 1. Process-theater is the dominant open question, and it's systemic
A large share of the corpus is **multi-step process scaffolding** — "constitutions"
(triage 14 articles, investigate, superplan 492 lines), N-pass analyses
(retrospective 13 passes), and disciplines (TDD, systematic-debugging,
verification-before-completion). The *methods are almost all causally plausible*
and the problems are real. But **none has measured that its heavy structure beats
a lean version**, and most have effectiveness **gated entirely on the model
actually following the prose under load**. Opus 4.x's literal-instruction-following
makes this more likely to help than it would have on older models — but "more
likely to help" is still unmeasured. This is the single biggest "does it make
sense" caveat and it is concentrated, not random.

### 2. The corpus is self-aware about this — and barely acts on it
It *ships* the cure: `build-measurement-harness` (stand up real efficacy evals),
`plateau-diagnose` (verify the instrument before trusting the metric), and the
oracle calibration discipline. Yet measurement is applied to a **tiny** fraction —
the audit/oracle family and the code-search/code-graph harness. The
process-skill majority asserts its benefit. **The highest-leverage move is to
point `build-measurement-harness` at the heaviest unproven skills** (superplan,
roundtable, the gather family, the constitutions).

### 3. Fragmentation inflates surface area without obvious benefit
- **superplan / supergoal family = 6 skills** (`superplan`, `-loop`, `-status`, `supergoal-pause`, `-resume`, + the `supergoal` engine). The lifecycle is real, but `supergoal-pause`+`-resume` share one tool surface / state file / lifecycle and should be one `/supergoal-control`; the `superplan-` vs `supergoal-` prefix split is itself confusing.
- **gather family = 4 + deep-dive** (`gather-claude/intel/internal-intel/research` + `deep-dive`): ~2,200 lines of near-parallel research machinery. Scope guards keep triggers from colliding, but it's a lot of duplicated structure for "research, scoped by source-type." Candidate to parameterize.
- **retro vs retrospective**, **scout vs scout-frontier vs scout-skills**, **capture vs distill** — each pair/triple has a real boundary, but the boundaries are fine enough that the split costs more in trigger-ambiguity and maintenance than it saves.
- **Counter-example (good split):** `codebase-memory-{exploring,quality,tracing}` are genuinely distinct intents with differentiated tool surfaces — keep separate.

### 4. A few skills are cost-disproportionate
- `roundtable` — 3 vendors × up to 5 rounds of LLM calls to produce a "consensus" that (per Wave 1) collapses to a single Opus narration. High token/latency cost, dubious marginal benefit over one strong critique pass.
- `evaluate-repos` (≤6 foreground agents) and `persona` (N persona API calls) — the *de-biasing* and *diverse-framing* ideas are sound, but the cost is high and the outcome benefit is unmeasured.
- `absorb` (506 lines, N=1 by construction) — niche problem, heavy apparatus.

### 5. The sound, proportionate spine
The skills that unambiguously make sense share a profile: **a real, recurring
chore + a deterministic or causally-direct method + low cost.** The deterministic
utilities (`pull-repos`, `garden`, `mcp-diagnose`, `sarif-parsing`, `index-repo`,
`healthcheck` helpers, the `_shared/oracle`/audit family), the small
design-dialogue skills (`interview`, `brainstorm`, `plateau-diagnose`,
`sharp-edges`, `refine`), and the strong ops skills (`pr-fix`, `ship-hook`,
`provision`, `verify-search-result`) are the corpus's backbone. These are where
"makes sense" is clearly yes.

**Verdict distribution (~90 skills):** ✅ Sound ~50 · ⚖️ Overbuilt ~17 ·
❓ Unproven-ceremony ~13 (overlaps ⚖️) · 🔁 Redundant ~7 · ⚠️ Questionable ~4.
*Most skills make sense at the approach level; the open question for the heavy
minority is whether the ceremony earns its cost — which is unmeasured.*

---

## Per-skill verdicts

### Deterministic utilities & the audit/oracle core — the spine
| Skill | Verdict | Why |
|---|---|---|
| `_shared/oracle` + `audit-skill` | ✅ | The measured-efficacy island; calibration proves detection works. The model for the rest. |
| `audit-rules` / `audit-architecture` / `mcp-forge-audit` / `audit-fix` | ✅ | Real deterministic detection grounded in the oracle; audit-fix's pre/post loop is causal. |
| `sarif-parsing` | ✅ | Conservative PoC/staleness gate; directly cuts SARIF noise. |
| `garden` | ✅ | Deterministic KB hygiene; every flag computed from file contents. |
| `index-repo` | ✅ | Real corruption problem + falsifiable validation gate. |
| `healthcheck` | ✅ | FS/AST/git drift checks; causal. (Orphaned recall-probe is dead weight — wire or delete.) |
| `mcp-diagnose` | ✅ | Log-cascade parser solves a real, fiddly diagnosis; the live-probe half is prose. |
| `pull-repos` | ✅ | Multi-repo status/pull in one command; deterministic, cheap. |
| `semgrep` | ✅ | Small SARIF-merge utility; sound for its scope. |
| `threat-model` | ✅ | Deterministic claim-grounding; shallow but causal. |
| `insecure-defaults` | ✅ | (post-fix) locate+classify+probe; causal. |
| `vendor-breach` | ✅ | Live GitHub exposure scan; exit-code-checked. |
| `recall` | ⚖️ | Retrieval itself is prose; the shipped telemetry measures *usage*, not retrieval quality. Useful but limited. |
| `variant-analysis` | ⚖️ | Runs real tools, but its only quality bound (FP cap) is inert by default. |
| `lab-deploy` | ⚖️ | `verify_waf` is sound fail-closed; the deploy step reports "started" without confirming. |
| `sca-review` | ⚠️ | Valid problem, but the helpers are NOT-IMPLEMENTED stubs — aspirational until built. |

### Security / static-analysis
| Skill | Verdict | Why |
|---|---|---|
| `differential-review` | ✅ | Diff security review with determination gates; well-scoped, causal. |
| `fp-check` | ✅ | Adversarial FP triage; bias-awareness is causally sound; subagent cost justified for security. |
| `agentic-actions-auditor` | ✅ | Static GH-Actions AI-injection audit; references carry real detection logic. |
| `codeql` | ✅ | Honest CLI orchestration; the engine does the work. |
| `semgrep-rule-creator` | ✅ | Test-first authoring backed by the real `semgrep` binary. |
| `security-alerts` | ✅ | Dependabot/CodeQL remediation; sound, well-scoped org sweep. |
| `stig-assess` / `stig-verify` | ✅ | Domain compliance; heavy, but the domain genuinely demands it. |
| `guardrail` | ⚖️ | S3 guardrail mgmt sound; `test` mode is a simulation (now labeled). |
| `scout-frontier` | ❓ | Real goal (spot paradigm shifts), but the "score" is a fixture self-consistency lint, not a measurement. Honestly disclaimed. |

### Research / gather / evaluate
| Skill | Verdict | Why |
|---|---|---|
| `deep-dive` | ✅ | General research with causal grounding rules (mandatory counterfactual, raw-error diagnosis). |
| `gather-research` | ✅ | The PRIMARY-source freshness framework is the soundest of the family. |
| `gather-intel` | ⚖️🔁 | Sound, but part of a 4-way near-parallel research split. |
| `gather-claude` | ⚖️🔁 | Sound upstream-sync; same family-overhead question. |
| `gather-internal-intel` | ⚖️🔁 | Sound internal sweep; same. |
| `gather-repos` | ✅ | Screen scoring (post-fix) is causal. |
| `scout` | ✅ | Thin, honest chainer (gather-repos→evaluate-repos). |
| `scout-skills` | ✅ | Real decorrelated 2-model SKIP quorum with defensive abstention. |
| `evaluate-repos` | ⚖️ | De-biasing advocate/skeptic is a sound answer to a real bias; ≤6 agents is costly. |
| `absorb` | ⚖️ | Niche (study one dev), heavy (506 lines, N=1). Method sound; cost/benefit thin. |

### Planning / goal / long-horizon
| Skill | Verdict | Why |
|---|---|---|
| `interview` | ✅ | Adversarial plan stress-test; tight, read-only, causally direct. |
| `brainstorm` | ✅ | Design-gate dialogue with an evidence-gather step; sound (trim the DOT graph). |
| `plateau-diagnose` | ✅ | "Verify the failure cell is real before fixing" — anti-ceremony by design. |
| `refine` | ✅ | Lightweight pre-execution enrichment; cheap, sound. |
| `superplan` | ❓⚖️ | Thoughtful (substrate detection, falsifiers, sha256 attestation) but a 492-line constitution whose benefit over `/goal`+judgment is unmeasured. |
| `supergoal` | ❓ | Per-turn "deterministic evidence" loop is actually prose; effectiveness gated on a Stop-hook agent complying. |
| `supergoal-pause` / `supergoal-resume` | 🔁 | Share tool surface + state file + lifecycle → merge into one `/supergoal-control {pause\|resume}`. |
| `superplan-loop` / `superplan-status` | ⚖️ | Honest thin wrappers; the `superplan-`/`supergoal-` prefix split confuses ownership. |
| `context-budget` | ⚖️ | Real token-bloat problem; value is one-time-ish and was overclaimed ("48% typical"). |

### Dev workflow / disciplines (compliance-gated)
| Skill | Verdict | Why |
|---|---|---|
| `systematic-debugging` | ✅ | Root-cause-first is a sound, well-evidenced discipline. (Trim the thrice-told war story.) |
| `subagent-driven-development` | ✅ | "Don't trust the subagent; verify on disk" is causally right. |
| `test-driven-development` | ✅ | Sound discipline; benefit gated on adherence (now honestly labeled "self-enforced"). |
| `verification-before-completion` | ✅❓ | Approach is exactly right ("run the command before you claim"); effectiveness *entirely* compliance-gated and unenforced — high value IF followed. |
| `sharp-edges` | ✅ | Misuse-resistance review; well-scoped index. |
| `work` | ✅ | Worktree isolation for a real shared-HEAD race; deterministic. |
| `validate-changes` | ⚖️ | Runnable for hooks/rules/MCP; the skill/creative verdict is LLM self-scored. |
| `triage` | ⚖️❓ | Write-safety gates are genuinely valuable; the 14-article constitution format is unproven vs. a lean version. |
| `investigate` | ⚖️❓ | Cross-tool correlation + cited main-thread-auth invariant are sound; heavy constitution, unproven ceremony. |

### MCP / API / infra
| Skill | Verdict | Why |
|---|---|---|
| `mcp-create` / `mcp-forge-build` | ✅ | The `verify_server` runtime load-gate is a real causal check before deploy. |
| `provision` / `invite-to-workspace` | ✅ | Idempotent, write-safe multi-system provisioning. |
| `bulk-api-script` | ✅ | "Write a script, don't paginate MCP" is causally right for bulk; per-API rules perishable. |
| `manifest-gen` | ✅ | Scaffold + judgment-fill; sound. |
| `cc-monitor` | ✅ | Data-source router, honest about blind spots. |
| `api-guardrails` | ✅ | Cheap doc-only Claude-API review checklist. |
| `build-measurement-harness` | ✅ | The meta-skill — and the *answer* to this whole critique's open question. Under-applied. |
| `api-preflight` | ⚖️ | Sound constraint extraction; part of the moderately-heavy api-* trio + constraint_graph machinery. |
| `api-ingest` | ⚖️ | Sound ingestion; same trio overhead. |
| `docgen` | ⚖️ | Evidence-cited docs are sound, but the substance + its verification live in an off-tree pipeline. |
| `cross-repo` | ⚠️ | GHES/GHEC premise uncorroborated by `_shared/repo-map.md` — possibly obsolete (now flagged in-skill). |

### Knowledge / memory / reporting
| Skill | Verdict | Why |
|---|---|---|
| `distill` | ✅ | Error/gap extraction with a CI-backed marker schema; coherent. |
| `capture` | ✅⚖️ | Decision capture; sound, with a deliberate (managed) overlap with distill. |
| `review-learnings` | ✅ | Conservative memory audit; sound. |
| `codebase-memory-exploring` / `-quality` / `-tracing` | ✅ | Genuinely distinct intents; graph-vs-grep token argument is causal. Keep separate. |
| `code-explore` | ✅ | Evidence-grounded search router; sound but over-explains (476 lines). |
| `obsidian` | ✅ | Security-aware ops runbook. |
| `weekly-update` | ✅⚖️ | Anti-invisibility coverage gates justify the weight; heavy. |
| `linear-status` | ✅ | Session-status posting with a real anti-silent-drop gate. |
| `retro` | ✅ | Single-session orchestrator that pruned its own fabrication-prone step. |
| `retrospective` | ⚖️🔁 | 13-pass multi-session analysis; sound passes, ceremony-heavy, boundary with `retro` is fine-grained. |
| `persona` | ❓ | Diverse-framing stress-test is plausible; "kappa" is method-agreement not inter-rater; N API calls, benefit unmeasured. |
| `ship` | ✅ | Full commit→PR→merge lifecycle; sound (post org-fix). |
| `pr-fix` | ✅ | The strongest operational skill — comprehensive, safety-first PR triage. |
| `ship-hook` | ✅ | Atomic hook installer that practices its own safety. |
| `verify-search-result` | ✅ | Read-and-quote-the-source verification; causally honest. |

---

## Recommended actions (from the "sense" lens)

1. **Consolidate the clear fragmentation** — merge `supergoal-pause`+`-resume` → `/supergoal-control`; resolve the `superplan-`/`supergoal-` prefix; evaluate collapsing the 4 `gather-*` into one source-parameterized skill.
2. **Point `build-measurement-harness` at the heavy unproven skills** — `superplan`/`supergoal`, `roundtable`, the gather family, `triage`/`investigate`. This converts "❓ unproven-ceremony" into measured ✅ or a decision to trim. It's the corpus's own prescribed cure.
3. **Right-size the cost-disproportionate ones** — measure whether `roundtable`'s 3×5 LLM spend and `evaluate-repos`'s 6 agents beat a single strong pass; if not, cut rounds/agents.
4. **Decide `cross-repo` and `sca-review`** — confirm GHES is live or retire `cross-repo`; implement `sca-review`'s stubs or fold its prose into `differential-review`.
5. **Trim the over-explainers** (no behavior change) — `code-explore` (476 lines), `systematic-debugging` (triplicated anecdote), the constitution checklists — shorter prose is *more* likely to be followed, which is the actual efficacy lever for compliance-gated skills.

**Bottom line:** the corpus *makes sense* — the problems are real and the methods
are, with few exceptions, causally connected to their goals. What it lacks is
*proof of proportion*: for the heavy process/planning minority, no one has shown
the ceremony out-performs a lean version. That's not a structural flaw; it's the
next measurement frontier, and the repo already owns the tool to close it.
