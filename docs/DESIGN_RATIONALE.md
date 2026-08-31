# Design Rationale

> Split from ARCHITECTURE.md 2026-06-11 (B11/F5, DECIDE #9). ARCHITECTURE.md
> is the drift-gated reference — what the system IS. This file is the WHY:
> the principles and the evidence behind them. Content moved verbatim.

## Philosophy

Three principles drive every design decision:

**1. Work is task-based, not domain-siloed.** An earlier version of this system had five specialized agents (security-ops, finance-ops, recruiting-ops, project-ops, runbook-dev) with rigid routing rules. Analysis of 150+ sessions showed that 52% of dispatches used a generic agent anyway, 43% of sessions used no agents at all, and cross-domain tasks required awkward multi-agent handoffs. The domain boundaries were artificial friction. The current design uses a single generic worker that loads whatever domain context it needs from topic files. A worker handling a CrowdStrike triage loads `security.md` and `crowdstrike.md`. The same worker type handling a Ramp spend analysis loads `ramp.md`. No routing ambiguity, no idle specialized agents.

**2. Memory should be indexed by topic, not by agent.** When domain agents were retired, their accumulated knowledge (API quirks, gotchas, workflow patterns) needed to survive. Rather than dumping everything into one file, the system splits knowledge into topic files - one per tool or cross-cutting concern. A CrowdStrike gotcha goes in `crowdstrike.md`, a Terraform pattern goes in `infrastructure.md`. Workers load only the topics relevant to their task, keeping context focused. Deep reference material lives in separate pattern files, loaded only when the topic file's summary isn't enough.

**3. Safety through automation, not discipline.** Humans forget rules. So do AI agents. Rather than relying on instructions like "never push to main" or "always check encoding," the system enforces these through hooks - Python scripts that run automatically before or after every tool call. A hook blocks direct pushes to protected branches. Another warns when dispatching a sub-agent that needs authenticated API access it won't have. Another checks every new Python file for missing `encoding='utf-8'`. The hooks don't require the agent to remember - they just fire.

---

---

## Self-Improvement Loop

The system learns from its own sessions through an automated feedback loop:

### During a session

1. Workers follow the **transparency protocol** (`transparency.md`): announce learnings inline, classify as `[observed]` (first occurrence) or `[confirmed]` (seen 2+ times)
2. The **SubagentStop hook** scans worker output for learning markers and routes them to the appropriate topic file based on keyword detection (CrowdStrike gotcha goes to `crowdstrike.md`, Terraform pattern goes to `infrastructure.md`)
3. The **PostToolUseFailure hook** triggers reflection on every failure: diagnose root cause, suggest fix, check if the pattern file already covers this error, persist the lesson

### After a session

1. The **Stop hook** (`session-stop.py`) saves the session transcript and checks if it exceeds 1MB
2. For large sessions (>1MB), it launches a separate Opus analysis that reads the full transcript, compares against existing memory, and writes up to 5 classified entries
3. Entries are deduplicated against existing topic files - if the same pattern is already documented, it gets promoted from `[observed]` to `[confirmed]` instead of being duplicated
4. Transcripts are retained for 7 days, then auto-pruned

### At session start

1. The **SessionStart hook** runs consistency checks to validate the system's integrity
2. It alerts on stale topic files (>14 days since last update)
3. It checks reference repo freshness (claude-code, opa, fastmcp sources) and warns if >7 days stale

This creates a virtuous cycle: sessions generate knowledge, knowledge improves future sessions, and consistency checks prevent drift.

---

---

## Creative Discovery and Knowledge-Asymmetric Collaboration

For tasks where the user is no longer the domain expert and cannot validate AI output by reading it (canonical example: research-frontier discovery in an unfamiliar field), this architecture applies a coherent set of patterns synthesized from 2024-2026 research (van der Stappen et al. 2026 Hybrid Intelligence Quality Model, Padmakumar et al. 2025 originality-quality tradeoff curve, Salvi et al. 2026 transformational-creativity ceiling, with counter-evidence from Chan et al. arXiv:2511.07448 on structured creativity prompting and Yang et al. ICML 2025 on emergent symbolic abstract reasoning, Lewis-Mitchell et al. 2026 counterfactual analogy, Zhang et al. 2026 Verbalized Sampling, byteiota 2026 AI Scientist v2 57% false-data finding).

**Three-layer defense (`skills/_shared/output-grounding.md`)**: every load-bearing claim from the four creative-discovery skills (`/scout-frontier`, `/brainstorm`, `/deep-dive`, `/refine`) carries (1) a confidence label (HIGH/MEDIUM/LOW or hedging), (2) provenance (source URL, DOI, or `[INFERRED]` tag), and (3) at least one counterfactual-test result per recommendation. Each layer alone is gameable; together they form a usable verification surface for non-expert users.

**Prompt/evaluation enforcement with an advisory payload diagnostic**: skill instructions, deterministic fixtures, transcript replay, and final-output evaluation enforce the three-layer contract. `hooks/creative-output-grounding-check.py` remains registered as a non-blocking PostToolUse diagnostic for the rare case where Claude Code supplies a substantive Skill response. A 30-day replay found 11 target-skill invocations: nine metadata payloads, two short payloads, and zero substantive responses. The hook therefore cannot grade the later user-facing answer, and silence is not evidence of compliance.

**Creativity tradeoff curve (not hard ceiling)**: LLM creativity sits on an originality-quality tradeoff (Padmakumar 2025) with constrained transformational creativity (Salvi 2026) — but Chan et al. arXiv:2511.07448 and the HuggingFace community show creative-prompting techniques (oblique strategies, structured ideation) shift the curve, and Yang et al. ICML 2025 documents emergent symbolic abstract-reasoning mechanisms in transformer models. `/scout-frontier`, `/brainstorm`, `/deep-dive`, and `/refine` are combinational-variation-at-scale-with-verification tools, NOT sole-source frontier-discovery oracles. Outputs are drafts subject to user verification. The tradeoff is documented in `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md` (multi-source 2024+ rewrite per PR #337) and operationally enforced by the output-grounding rule's FAILURE MODES section.

**Diversity primitives (mode-collapse mitigation)**: `/scout-frontier` uses five primitives from `references/verbalized-sampling-template.md` to mitigate Opus 4.7 mode-collapse on variation generation (KINTAL T4 finding): (1) Verbalized Sampling with assigned probabilities, (2) ordinary personas (no creative-celebrity personas — they collapse to stereotype), (3) factuality filter post-VS for tail samples, (4) abstraction-then-mapping (YARN) for cross-domain analogies, (5) counterfactual-test extending Step 6 Check 5.

**Validation infrastructure**: `/validate-changes` Step 3b "Creative-Regression Mode" fires when a change affects the four target skills OR when a model migration is being evaluated. It runs the canonical fixture in `skills/validate-changes/references/creative-test-prompts.md` (7 KINTAL-style prompts) and applies a mechanical 2-dimension rubric (distinctness + grounding, each 1-5). Pass criterion: ≥80% of prompts within 1 rubric-point of baseline. Will be used by Experiment 11 (Opus 4.7 vs 4.6 A/B test) per the research backlog.

**Model migration policy**: As of **2026-05-28 the system runs on Opus 4.8** and the creative-discovery hold on 4.6 was **lifted to 4.8 by user decision — untested**. Experiment 11 (the 4.7-vs-4.6 A/B that gated the hold) was never run and 4.7 is now superseded, so the original gate is moot. Rationale for the lift: 4.8 is honesty/coding-focused and supersedes the 4.7 regression evidence; 4.8 creative-divergence is **UNCHARTED** (no public eval, and 4.8's anti-overconfidence training could plausibly help *or* worsen mode-collapse). Risk accepted; the canonical 7-prompt creative-regression fixture (`validate-changes` Step 3b) remains the one-command check if creative-quality drift is observed. Engineering-heavy skills (`/ship`, `/superplan`) migrate freely. See `~/Documents/knowledge-base/topics/opus-4-7-creative-tradeoffs.md` for the (now-historical) KINTAL/AIWorkflows/GitHub #51440/Calloway/Claude Directory regression evidence and the 2026-05-28 lift record.

**KB topics**: `llm-creativity-ceiling.md`, `knowledge-asymmetric-collaboration.md`, `opus-4-7-creative-tradeoffs.md` (claude-knowledge-base PR #329).

**Research source**: `~/Documents/knowledge-base/research/claude-code-research-intelligence.md` Section "New Findings (2026-04-28 — Creative Discovery & Knowledge-Asymmetric Collaboration Focus)" — 10 findings, 3 threads, 3 experiment backlog entries (9, 10, 11).

---
