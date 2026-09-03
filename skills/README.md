# Skills index

81 skills. **Generated from each `SKILL.md` frontmatter -- do not
hand-edit; regenerate instead.**

A skill is a procedure Claude invokes by matching your request against the
`description` in its frontmatter, so that description *is* the routing logic.
Bigger skills push detail into `references/` and deterministic helpers into
`scripts/`, so `SKILL.md` stays scannable.

| Skill | What it does | Has |
|---|---|---|
| [`absorb`](./absorb/SKILL.md) | Study how a builder works — repos, commits, PRs, reviews — to extract practices worth adopting into the architecture. | references |
| [`agentic-actions-auditor`](./agentic-actions-auditor/SKILL.md) | Audit GitHub Actions workflows for AI-agent security holes (attacker input reaching Claude Code Action or Codex). | references |
| [`api-guardrails`](./api-guardrails/SKILL.md) | Production-readiness checklists for Claude API apps — fewer hallucinations, more consistent output. | references |
| [`api-ingest`](./api-ingest/SKILL.md) | Ingest API documentation into the searchable doc library (probes OpenAPI/llms.txt, falls back to Firecrawl scraping). | references |
| [`api-preflight`](./api-preflight/SKILL.md) | Map an API's auth, scopes, token types, and prerequisite chain before writing code against it. | - |
| [`audit-architecture`](./audit-architecture/SKILL.md) | Audit the Claude Code architecture for drift and coverage gaps across MCP servers, agents, hooks, skills, and rules. | references, tests |
| [`audit-fix`](./audit-fix/SKILL.md) | Dispatch one fix-agent per verified audit finding, with pre/post oracle verification; commit only verified fixes. | scripts, tests |
| [`audit-rules`](./audit-rules/SKILL.md) | Measure rule compliance from transcripts and recommend promotions for the most-violated rules. | references, scripts, tests |
| [`audit-skill`](./audit-skill/SKILL.md) | Audit a skill (or all skills) for external-contract drift, content hygiene, and behavior gaps. | references, scripts, tests |
| [`build-measurement-harness`](./build-measurement-harness/SKILL.md) | Build an instrumented measurement harness with two-source ground truth and freshness gates from day one. | references |
| [`bulk-api-script`](./bulk-api-script/SKILL.md) | Generate a Python script for bulk API operations (100+ results) instead of MCP pagination. | - |
| [`capture`](./capture/SKILL.md) | Record session decisions, lessons, and breakthroughs as dated entries in the digital garden. | references |
| [`code-explore`](./code-explore/SKILL.md) | Find and understand code by meaning, combining semantic search with structural graph context. | references |
| [`codebase-memory-exploring`](./codebase-memory-exploring/SKILL.md) | Explore codebase structure — modules, functions, classes, routes — via the code graph. | references |
| [`codebase-memory-quality`](./codebase-memory-quality/SKILL.md) | Find dead code, unused functions, and high-fan-out refactor candidates via the code graph. | references |
| [`codebase-memory-tracing`](./codebase-memory-tracing/SKILL.md) | Trace call chains, callers/callees, and change impact via the code graph. | - |
| [`codeql`](./codeql/SKILL.md) | Deep dataflow and taint-tracking security analysis with CodeQL. | references |
| [`context-budget`](./context-budget/SKILL.md) | Audit token overhead from loaded skills, rules, MCP tools, hooks, and CLAUDE.md. | - |
| [`debugging-hypotheses`](./debugging-hypotheses/SKILL.md) | Companion to superpowers:systematic-debugging for bugs whose cause is not obvious after the first evidence pass: enumerate the code's unusual mechanisms, form two... | - |
| [`deep-dive`](./deep-dive/SKILL.md) | Thorough multi-source research (Tavily + Exa + Firecrawl) synthesized into an evidence-graded report. | references, tests |
| [`design-evidence-first`](./design-evidence-first/SKILL.md) | Companion to superpowers:brainstorming: before the first clarifying question, answer it from transcripts, memory, git history, and the existing code; validate one... | - |
| [`differential-review`](./differential-review/SKILL.md) | Security-focused review of PRs, commits, or diffs, with blast-radius and test-coverage checks. | - |
| [`distill`](./distill/SKILL.md) | Extract a session's errors, failed approaches, and workarounds into governed persistence targets. | references, scripts |
| [`evaluate-repos`](./evaluate-repos/SKILL.md) | Evaluate external patterns against our architecture with advocate/skeptic agent pairs. | references, tests |
| [`fp-check`](./fp-check/SKILL.md) | Verify a suspected security bug as TRUE or FALSE positive, with documented evidence. | references |
| [`garden`](./garden/SKILL.md) | Curate the knowledge base — run a health check and auto-resolve every curation issue. | references, scripts, tests |
| [`gather-claude`](./gather-claude/SKILL.md) | Sync the architecture with what Anthropic shipped — new Claude Code features, fixes, and deprecations. | references, scripts, tests |
| [`gather-claude-endpoints`](./gather-claude-endpoints/SKILL.md) | Detect drift in Anthropic's data-collection surface — OTel signals, Compliance API, Admin API, Analytics APIs, webhooks, rate limits, and documented exclusions —... | references, scripts, tests |
| [`gather-intel`](./gather-intel/SKILL.md) | Discover new Claude Code community patterns from Reddit, HN, GitHub, X, and blogs. | references, tests |
| [`gather-openai-endpoints`](./gather-openai-endpoints/SKILL.md) | Detect drift in OpenAI's data-collection surface — ChatGPT Compliance Logs Platform, Platform Admin/Audit-Log APIs, Codex Analytics, and enterprise doc surfaces —... | references, scripts, tests |
| [`gather-repos`](./gather-repos/SKILL.md) | Discover community Claude Code repos and produce structured per-repo inventories. | references |
| [`gather-research`](./gather-research/SKILL.md) | Track the AI-agent research frontier (papers, talks, frameworks) and map it to our architecture. | references, tests |
| [`gather-vendor`](./gather-vendor/SKILL.md) | Sync the architecture with what a third-party LLM vendor shipped — model releases, API changes, and deprecations affecting our eval/judge/monitor tooling. | references, scripts, tests |
| [`harness-prune`](./harness-prune/SKILL.md) | Audit the harness for stale workarounds — model-version compensations and shipped library fixes. | scripts, tests |
| [`healthcheck`](./healthcheck/SKILL.md) | Quick architecture health check — hooks, config syntax, skill frontmatter, memory, and indexes. | references, tests |
| [`index-repo`](./index-repo/SKILL.md) | Index a repository for code search, or audit existing indexes for corruption. | references, tests |
| [`insecure-defaults`](./insecure-defaults/SKILL.md) | Detect fail-open insecure defaults — hardcoded secrets, weak auth, permissive security. | references, scripts, tests |
| [`interview`](./interview/SKILL.md) | Adversarially stress-test a plan, design, or proposal to expose hidden assumptions. | - |
| [`legacy-code-tdd`](./legacy-code-tdd/SKILL.md) | Companion to superpowers:test-driven-development for untested code and multi-layer features: characterization tests that pin current behavior before a change, a w... | - |
| [`manifest-gen`](./manifest-gen/SKILL.md) | Generate or refresh manifest.yaml files for skills, hooks, rules, KB topics, and more. | - |
| [`mega-capture`](./mega-capture/SKILL.md) | Recover the COMPLETE record of a large auto-compacted session and feed /capture's whole-session judgment, so strategic knowledge from the compacted-away head reac... | - |
| [`mega-distill`](./mega-distill/SKILL.md) | Recover the COMPLETE record of a large auto-compacted session into a condensed signal slice, so /distill judges the whole session instead of only the post-compact... | references, scripts, tests |
| [`modal`](./modal/SKILL.md) | Offload compute-heavy, egress-safe work to Modal serverless GPUs/containers from Claude Code: parallel batch fan-out, Sandboxes for untrusted/LLM-generated code,... | - |
| [`monitor`](./monitor/SKILL.md) | Start a real-time flaw AND observation tracker for the current session — log two event types THE MOMENT they surface: FLAWs (mistakes, refuted assumptions, bad in... | - |
| [`persona`](./persona/SKILL.md) | Dispatch framework personas at a plateaued metric to break diminishing returns. | references, scripts, tests |
| [`plateau-diagnose`](./plateau-diagnose/SKILL.md) | Find the contingency-table cell holding a stuck metric's failure mass before fixing. | - |
| [`pr-fix`](./pr-fix/SKILL.md) | Clear the PR queue — failing CI, stuck auto-merge, conflicts, stale branches, dirty trees, orphaned worktrees. | references, scripts, tests |
| [`readiness-review`](./readiness-review/SKILL.md) | Assess whether a vibe-coded internal tool is ready to put in a technical SME's hands — orchestrates a shape-adapted, capability-first readiness review and emits O... | references |
| [`recall`](./recall/SKILL.md) | Search the knowledge base (digital garden) for prior decisions, lessons, and patterns. | scripts, tests |
| [`red-team-axes`](./red-team-axes/SKILL.md) | Break a HARDENED target by rotating ATTACK axes, driven by the harness red-team platform (generator + oracle portfolios). | - |
| [`refine`](./refine/SKILL.md) | Enrich a complex prompt with missing constraints, success criteria, and decomposition. | - |
| [`retro`](./retro/SKILL.md) | Session wrap-up — runs /distill and /capture (using /mega-distill and /mega-capture for compacted sessions), then lands session artifacts through /ship. | references, tests |
| [`retrospective`](./retrospective/SKILL.md) | Review what went well, what went wrong, and what's missing across recent sessions. | references |
| [`review-depth-by-risk`](./review-depth-by-risk/SKILL.md) | Companion to superpowers:subagent-driven-development: size each task's review to its risk tier, allow one repair batch and one re-review then stop, keep concurren... | - |
| [`review-learnings`](./review-learnings/SKILL.md) | Audit, prune, and correct agent persistent memory across topic files and pattern stores. | references, scripts, tests |
| [`roundtable`](./roundtable/SKILL.md) | Run a multi-agent adversarial roundtable (Claude, Grok, GPT) for independent critique. | references, scripts, tests |
| [`run-status`](./run-status/SKILL.md) | Show the live state of long-running background work (oracle runs, terraform applies, measurement harnesses, deploy monitors) from their durable status files. | - |
| [`sarif-parsing`](./sarif-parsing/SKILL.md) | Parse, filter, and deduplicate SARIF results from CodeQL, Semgrep, or other scanners. | references, tests |
| [`scout`](./scout/SKILL.md) | Discover and evaluate community Claude Code config repos end-to-end in one pass. | - |
| [`scout-frontier`](./scout-frontier/SKILL.md) | Scout paradigm-distinct approaches and cross-domain analogies with mode-collapse mitigation. | references, scripts, tests |
| [`scout-skills`](./scout-skills/SKILL.md) | Mine the Context7 skills registry for techniques and route adoptions across the architecture. | references, scripts, tests |
| [`search-axis-rotate`](./search-axis-rotate/SKILL.md) | Rotate the SEARCH AXIS to break a stuck search / red-team / optimization. | - |
| [`search-campaign`](./search-campaign/SKILL.md) | Run a large parallel adversarial/search campaign as a repeatable generate to evaluate to track to rotate to select loop, optimizing diversity times robustness whe... | - |
| [`semgrep`](./semgrep/SKILL.md) | Scan code with Semgrep (SAST) using parallel subagents; auto-detects Pro for taint analysis. | references, scripts, tests |
| [`semgrep-rule-creator`](./semgrep-rule-creator/SKILL.md) | Write custom Semgrep rules for security vulnerabilities and bug patterns. | references |
| [`service-review`](./service-review/SKILL.md) | Review a backend service / API / CLI tool for production readiness — boots and drives the running tool live, adversarial-hammers every input path for fail-closed... | - |
| [`sharp-edges`](./sharp-edges/SKILL.md) | Identify error-prone APIs, footgun configs, and insecure-by-default designs. | references |
| [`ship`](./ship/SKILL.md) | Take pending changes through the full PR lifecycle — commit, push, branch, PR, auto-merge. | references, scripts, tests |
| [`ship-hook`](./ship-hook/SKILL.md) | Install a staged hook spec from hooks/staged/ — write, register, and test it. | - |
| [`supergoal`](./supergoal/SKILL.md) | Drive a superplan plan-file to completion autonomously with tool-backed verification. | references, scripts, tests |
| [`supergoal-pause`](./supergoal-pause/SKILL.md) | Pause an active supergoal loop without losing prior-arc lineage. | - |
| [`supergoal-resume`](./supergoal-resume/SKILL.md) | Resume a paused supergoal loop after verifying the plan is untampered. | - |
| [`superplan`](./superplan/SKILL.md) | Plan any non-trivial task — load operational knowledge and tools, produce a context-aware plan. | references, tests |
| [`superplan-loop`](./superplan-loop/SKILL.md) | Re-check supergoal progress on a cadence and surface concerning signals (read-only). | - |
| [`superplan-status`](./superplan-status/SKILL.md) | Report the current state of an active supergoal loop in-conversation (read-only). | - |
| [`threat-model`](./threat-model/SKILL.md) | Build a structured threat model — assets, trust boundaries, attacker stories, severity. | references, scripts, tests |
| [`triage`](./triage/SKILL.md) | Triage findings from any tool — severity-score, correlate, and produce an actionable report. | references, tests |
| [`validate-changes`](./validate-changes/SKILL.md) | Validate architecture changes (skills, hooks, rules, MCP) with regression and A/B testing. | references, scripts, tests |
| [`variant-analysis`](./variant-analysis/SKILL.md) | Hunt similar vulnerabilities and bug variants across codebases via pattern analysis. | references, scripts, tests |
| [`verify-search-result`](./verify-search-result/SKILL.md) | Verify a CALLS-edge or search result before a security-critical decision (CONFIRMED/FP/AMBIGUOUS). | - |
| [`work`](./work/SKILL.md) | Create a per-session git worktree with auto-prefixed branch to isolate concurrent sessions. | - |

## Note on cross-references

This is a curated subset of a larger private configuration. Some skills and
incident write-ups reference a skill that is not included here (it operated a
specific internal system). The lesson in those write-ups stands on its own;
the `/name` cross-reference will not resolve.
