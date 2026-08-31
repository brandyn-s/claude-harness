# Phase 3b: Estimation and Ambiguity Resolution

Before constructing the plan, estimate effort and surface implementation
choices that affect the plan's shape.

## Question classification (before asking ANY question)

Before asking the user a question during planning, classify it:

| Type | Examples | Action |
|------|----------|--------|
| **Codebase Fact** | "What patterns exist?", "Where is X?", "What framework?" | **Explore first** — search/grep/read the codebase. NEVER ask the user. |
| **User Preference** | "Priority?", "Timeline?", "Which approach?" | Ask user via AskUserQuestion |
| **Scope Decision** | "Include feature Y?", "Cover repo Z?" | Ask user |
| **Requirement** | "Performance constraints?", "Compliance needs?" | Ask user |

**The anti-pattern**: Asking "Where is authentication implemented?" when
`grep -r "auth" src/` would answer in 2 seconds. Lazy questions waste user
time and produce vaguer answers than direct observation.
(Pattern source: yeachan-heo/oh-my-codex plan — Context7 registry 2026-04-08)

## Ambiguity scan

Analyze the task for decisions that must be made before planning:

1. **Technical approach** — Are there multiple valid strategies? (e.g.,
   MCP direct vs Python script, single agent vs parallel team)
2. **Scope boundaries** — Is the scope well-defined or open-ended?
   (e.g., "audit all repos" — which repos? how deep?)
3. **Integration points** — How does this connect to existing workflows?
   (e.g., does the output go to Linear, Slack, a file?)
4. **Verification** — How will we know it worked?
   (e.g., manual check, automated test, diff comparison)

For each significant ambiguity, present the choices with their
complexity/time impact:

```
AMBIGUITY: [description]
  Option A: [approach] — [impact on effort/complexity]
  Option B: [approach] — [impact on effort/complexity]
  Recommendation: [which and why]
```

**Ask the user** before proceeding if any ambiguity would change the plan
by more than 1 step or shift effort by more than 50%.

## Evidence-grounded option evaluation (for codebase-dependent choices)

When the right choice depends on codebase state — not just preference —
escalate from listing choices to researching them. This applies when:
- Options have different feasibility depending on what code exists
- One option requires a function/module that may or may not be present
- The complexity impact differs based on existing patterns in the codebase

**Trigger**: Any ambiguity where you'd say "it depends on what's already
there." Don't guess — investigate.

**Process**: Launch one Explore agent per option (max 3), in parallel,
each with a **5 tool-call budget**. Each agent investigates its option
against the actual codebase and answers:

1. What does this option require mechanically? (step by step)
2. What existing code supports it? (cite file:line)
3. What's missing that would need to be built?
4. What are the failure modes?
5. What evidence from the codebase argues for or against?

**Agent prompt template**:
```
You are researching ONE implementation option for a planning decision.

PROBLEM: {problem statement and constraints}
OPTION: {option name and description}
CODEBASE: {relevant directories or file patterns to search}

Investigate this option against the actual codebase. Budget: 5 tool calls.
Answer these 5 questions with cited evidence (file paths, line numbers):
1. What does this option require mechanically?
2. What existing code supports it?
3. What's missing that would need to be built?
4. What are the failure modes?
5. What codebase evidence argues for or against this option?

No option may be called "better" or "simpler" without citing evidence.
```

**Aggregation**: After agents complete, build a comparison table:

| Option | Supports (existing code) | Requires (new code) | Failure modes | Evidence |
|--------|-------------------------|--------------------|--------------:|----------|

State a recommendation with:
- Which option is recommended and the specific evidence
- What the recommended option does NOT solve (honest scope)
- What evidence would change the recommendation (falsifiable)

**Skip when**: The choice is purely preference-based (output format,
naming convention), or the user already stated their preference.
(Pattern source: bitflight-devops/hallucination-detector evaluate-options —
Context7 registry 2026-04-06)

## Effort estimation

After ambiguities are resolved, estimate using calibrated baselines:

| Size | Effort | Characteristics |
|------|--------|----------------|
| **XS** | ≤ 1 hour | Single file, obvious fix, one tool |
| **S** | ≤ 1 day | 1-3 files, known patterns, one domain |
| **M** | 2-3 days | Multiple files, some design decisions, cross-module |
| **L** | 3-5 days | Cross-domain, multiple repos, significant testing |
| **XL** | ≥ 6 days | Architectural change, break into sub-plans |

**Calibration baselines** (project-specific):

| Work type | Typical size | Notes |
|-----------|-------------|-------|
| New MCP server (Rust) | L-XL | API research + implementation + OPA + ECS deploy |
| New skill | S-M | SKILL.md + test + ship |
| New hook | XS-S | Script + settings.json + test |
| STIG assessment (per SRG) | M-L | Evidence gathering + cross-reference + report |
| Bulk API script | S | Python + boto3/httpx, known pattern |
| Rule file update | XS | Edit + verify no conflicts |
| Cross-tool investigation | M | Multi-MCP correlation + timeline + report |

**Assessment dimensions**: scope (files/repos touched), complexity
(CRUD vs architectural), testing needs, risk (reversible?), dependencies
(blocked by external?), documentation (docs/changelog needed?).

Include the size estimate and key assumptions in the plan header.
(Pattern source: ag-grid/ag-charts estimate-jira — Context7 registry 2026-04-06)
