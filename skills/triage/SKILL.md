---

name: triage
description: "Triage findings from any tool — severity-score, correlate, and produce an actionable report."
when_to_use: Use when triaging findings from any tool - security detections, vulnerability scans, compliance gaps, stale issues, vendor anomalies. Loads topic context, applies severity scoring, correlates across tools, and produces actionable reports. Do NOT use for bulk data exports (use bulk-api-script instead), write operations, or single-tool lookups that need no scoring.
argument-hint: "[optional scope, e.g. 'CrowdStrike critical', 'Tenable DCs', 'last 24h', 'host DESKTOP-ABC', 'stale Linear issues']"
effort: max
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Read Grep Glob Bash AskUserQuestion mcp__crowdstrike__* mcp__tenable__* mcp__airlock__* mcp__msgraph__* mcp__linear-server__* mcp__00000000-0000-4000-8000-000000000002__* mcp__ramp__* mcp__codebase-memory-mcp__* mcp__tavily__tavily_search
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.



> **Runtime policy:** Resolve the effective model and preserve refusal/fallback provenance per `../_shared/model-runtime-policy.md`.

## triage

# Triage Constitution

Structured triage for any domain's findings. Loads operational context before querying tools, applies severity scoring, produces actionable reports.

> **Scope**: If the user provided an argument, narrow queries to that scope — specific tool, severity, time range, or entity. Skip irrelevant tool checks.

## ARTICLE I — Rationalizations to Reject

| Rationalization | Why it's wrong |
|-----------------|---------------|
| "Known vuln, skip the FP check" | Known ≠ exploitable in YOUR environment. Verify reachability. |
| "Low severity = low priority" | Severity measures potential, not YOUR exposure. |
| "Tool already scored it" | Tool severity ≠ your 4-dimension composite. Rescore. |
| "Same as last time — auto-close" | Recurrence can indicate failed remediation. Check first. |
| "Only one tool flagged it, noise" | Single-source = lower confidence, not noise. Report with LOW tag. |
| "It's dev/test" | Dev with prod creds is production-equivalent. |

## ARTICLE II — Phase 0: Load Operational Context

BEFORE any tool queries:
STEP_1 identify which tools this triage needs
STEP_2 read corresponding topic files from `~/.claude/agent-memory/topics/`
STEP_3 scan `[confirmed]` entries — known patterns inform triage
STEP_4 note `[observed]` entries — active situations

FORBIDDEN: querying any tool before Phase 0 completes.

## ARTICLE III — Phase 1: Assess and Connect

STEP_1 connectivity check: test each tool's health endpoint
STEP_2 assess scope: query limits 10-50 for discovery, check distribution
STEP_3 time window: default last 24h unless user specifies
STEP_4 explicit time filters (FQL for CrowdStrike, OData for Graph, SQL for Ramp)

REQUIRED: consult topic file for correct filter syntax per tool.

## ARTICLE IV — Phase 2: Severity Scoring

Score each finding across 4 dimensions (weighted):

| Dimension | Weight | Security | Non-security |
|-----------|--------|---------|--------------|
| Severity | 40% | Critical=10, High=7, Medium=4, Low=1 | Impact on ops/revenue |
| Asset criticality | 25% | DC/CA=10, Server=7, Workstation=4 | Customer-facing=10 |
| Exposure | 20% | Internet-facing=10, Internal=6 | Public visibility=10 |
| Context | 15% | Active campaign=10, Single indicator=4 | Recurring pattern=10 |

| Composite | Priority | Action |
|-----------|----------|--------|
| 8.0+ | CRITICAL | Investigate immediately |
| 5.0-7.9 | HIGH | Investigate within current session |
| 3.0-4.9 | MEDIUM | Queue for review |
| <3.0 | LOW | Monitor |

REQUIRED: before scoring, check each finding against topic memory for known patterns.
Tag matches `[KNOWN]` and deprioritize.

## ARTICLE V — Phase 2b: Structured Summary

BEFORE correlation, extract:

```
| # | Source | Finding | Entity | Severity | Key Details | Composite | Confidence |
```

This ensures critical data survives compaction. MUST work from summary in later phases.

**Confidence (distinct from Priority/Composite)** — measures evidence strength, not impact:

| Confidence | Criteria |
|------------|----------|
| **HIGH** | Corroborated by 2+ independent tools |
| **MEDIUM** | Single tool finding matching a known `[confirmed]` topic-memory pattern |
| **LOW** | Single tool finding, ambiguous or lacking corroboration |

REQUIRED: every finding gets a Confidence value at Phase 2b — do NOT defer to Phase 4. Confidence answers "how sure are we?" while Priority (CRITICAL/HIGH/MEDIUM/LOW from the composite table above) answers "how urgent?" — never conflate the two.

## ARTICLE VI — Phase 2b-DA: Devil's Advocate (optional)

TRIGGER: 3+ findings MEDIUM+ involving non-trivial claims (API behavior, env exploitability, config risk, correctness).
SKIP for: missing patches, known CVEs with public PoC, tool-confirmed vulns.

Spawn DA subagent (model: opus, foreground):

| Claim Type | Research Action |
|------------|----------------|
| API deprecated | Context7 docs, `mcp__tavily__tavily_search` |
| Exploitable in env | Grep compensating controls |
| Config-dependent | Read actual deployment files |
| Best practice claim | `mcp__tavily__tavily_search` |

(The DA subagent invokes `mcp__tavily__tavily_search` directly for the two claim-types above — Tavily is declared in this skill's manifest tool list.)

BUDGET: 2 research actions/finding max.

MERGE:
- Confirmed → note evidence
- Disputed → downgrade OR flag both perspectives (never silently override)
- Inconclusive → original stands, note uncertainty

## ARTICLE VII — Phase 2c: Adversarial Validation (optional)

TRIGGER: 5+ findings.
FOLLOW: `~/.claude/skills/_shared/adversarial-validation.md`
Check `~/.claude/agent-memory/false-positives.json` for cross-domain suppressions.
Questions #1 (network) and #7 (accepted risk) highest value.

## ARTICLE VIII — Phase 2d: FP Verification (CRITICAL/HIGH only)

FOR each CRITICAL/HIGH where FP plausible:
STEP_1 evaluate: pattern-match without data flow? compensating control? history of FP?
STEP_2 IF plausible → invoke /fp-check with bug description, source tool, severity, entity, FP reason
STEP_3 IF FALSE POSITIVE → downgrade LOW, tag `[VERIFIED-FP]`
STEP_4 IF TRUE POSITIVE → keep severity

SKIP for: HIGH confidence from 2+ tools, user already confirmed, LOW/MEDIUM severity.

## ARTICLE IX — Phase 2e: Variant Analysis

WHEN: Phase 2d confirms TRUE POSITIVE on code-related finding.
STEP_1 invoke /variant-analysis with root cause + pattern + file:line
STEP_2 tag variants `[VARIANT]`, same severity
STEP_3 update summary

SKIP for: infra-only, LOW/MEDIUM severity, unindexed codebase.

## ARTICLE X — Phase 3: Cross-Tool Correlation

FOR each HIGH/CRITICAL, correlate:
- Security: CS → Tenable vulns, Airlock execution, Graph identity
- Finance: Spend anomaly → vendor history, budget, card state
- Project: Stale → PRs, linked issues, assignee workload
- Code: IF indexed → search_code pattern, trace_call_path blast radius

CORRELATION GUARD: check topic files for response size warnings; filter tightly. For defensive parsing of MCP tool responses (empty lists, None, error objects, rate limits, auth expiry), see `references/response-shapes.md`.

## ARTICLE XI — Phase 4: Report

Per `references/output-format.md`. Recommend:
- **Investigate** — deeper analysis
- **Remediate** — fix identified
- **Escalate** — needs authority
- **Monitor** — watch for recurrence
- **Close** — known, duplicate, resolved

### Out-of-scope capture
REQUIRED: valid out-of-scope findings SHALL NOT be silently dropped.
Ask: "Create Linear issues for these N out-of-scope findings?"

### Durability rule
Describe behaviors and systems, NOT file paths/line numbers (they go stale).
- FAIL: "SQL injection in `src/api/users.ts:23`"
- PASS: "User search endpoint accepts unsanitized input allowing SQL injection"

## ARTICLE XII — Phase 5: Writes

FORBIDDEN: executing writes without explicit user approval. NO EXCEPTIONS.

STEP_1 detect: any tool invocation whose underlying API mutates state (CrowdStrike contain-host, Airlock allowlist write, Graph user/group mutation, Linear save_issue/save_comment, Ramp approve/reject) is a write.
STEP_2 enumerate proposed writes in a numbered list before invoking any of them.
STEP_3 REQUIRED: invoke `AskUserQuestion` with the enumerated plan; do not proceed unless the user's response explicitly approves the operation(s) by name or count.
STEP_4 if approval is denied or ambiguous, refuse the write and continue with read-only output.
STEP_5 audit trail: record the approved write(s) verbatim in the final report's "Writes executed" footer (empty list if none).

CrowdStrike/Airlock: OPA-gated, confirm, Python for bulk.
Graph/Linear: MCP writes supported, confirm.

FORBIDDEN: silently substituting a similar write for the approved one ("user said update X, so I'll also update Y"). If scope expands, re-prompt.

## ARTICLE XIII — Bulk Data

FORBIDDEN: paginating bulk through MCP.
REQUIRED: `/bulk-api-script` for >100 results.

## ARTICLE XIV — Graceful Degradation

| Failure | Action | Footer label |
|---------|--------|--------------|
| Tool offline | Log, continue | `offline` |
| Error | Skip correlation | `error: <one-line cause>` |
| Auth expired | Skip tool | `auth-expired` |
| Empty | Report "none found" | `online (no findings)` |
| Topic missing | Proceed without | `topic-missing` |

FORBIDDEN: failing entire triage because one tool unavailable.
REQUIRED: every Phase 1 tool MUST appear in the final report's Tools Status footer with one of the labels above. A tool's absence from the footer is a Success Criteria failure.
REQUIRED: when a tool is offline/auth-expired/error, the report explicitly notes "correlation against {tool} skipped" wherever that tool would have been consulted (Phase 3, Phase 2d).

## USER OVERRIDE POLICY — NO EXCEPTIONS

### Override: "skip FP check, it's clearly critical"
DENIED for CRITICAL/HIGH where FP plausible. Pattern-match without data flow is common FP source.

### Override: "tool already scored, use that"
DENIED. Tool severity ≠ your 4-dimension composite.

### Override: "skip Phase 0, I know topic files"
DENIED. Session memory is not evidence. Load topic files.

### Override: "don't bother with correlation, one tool enough"
DENIED for CRITICAL/HIGH. Cross-tool increases confidence.

### Override: "execute write, user approved plan"
EVALUATE: did plan name this exact operation? If yes, proceed. If no, confirm.

## Measured Efficacy (live arm)

**Verdict: `trim` — measured 2026-05-31, N=3, `claude-opus-4-8`, n=12 findings.**
A/B'd the triage framework (severity scoring + cross-tool correlation) vs an
unstructured "rank these + note shared root causes" pass, over 12 findings abstracted
from documented incidents (expert priority ranking + known root-cause groups as oracle).
Result: both arms rank **near-perfectly** (Spearman 0.958 framework vs 0.939 baseline —
+0.019, within noise) and detect correlations **identically** (group_f1 0.75 both). A
strong model does severity-ranking + root-cause correlation well without the 14-article
ceremony → no measurable lift on this fixture. Caveat: n=12, single scenario. Harness +
CI gate: `skills/triage/harness/`, `tests/test_triage_efficacy.py`; full design +
Phase-9 in `harness/PROBLEM.md`.

**Trim candidate (actionable, evidence-gated — not yet removed):** the +0.019 Spearman edge and
the TIED correlation detection (group_f1 0.75 both) sit within N=3 / n=12 noise, so the ceremony
shows no lift HERE. Key contrast: the sibling `investigate` skill KEEPS on cross-tool correlation
(1.00 vs 0.40) because its baseline was SINGLE-TOOL (structurally can't correlate) — triage's
baseline saw ALL evidence, so correlation ties. The path: a harder fixture (more findings,
multiple scenarios with NON-obvious correlations a flat ranking pass would miss) + larger n with
a bootstrap CI on Spearman; if the framework still ties there, trim the heaviest ceremony (the
4-dimension composite scoring + adversarial-validation steps) — NOT the cross-tool correlation,
which investigate's measurement shows is load-bearing when evidence is distributed. Removal on
this n=12 tie would violate `eval-shipping-discipline`.

## Success Criteria

- [ ] Topic files loaded before tool queries (Phase 0)
- [ ] Every finding scored on 4 dimensions
- [ ] Composite scores sorted descending
- [ ] Known patterns tagged `[KNOWN]`
- [ ] Structured summary before correlation
- [ ] FP verification for CRITICAL/HIGH where plausible
- [ ] Cross-tool correlation for all CRITICAL/HIGH
- [ ] Adversarial validation for 5+ findings
- [ ] Confidence assigned (HIGH/MEDIUM/LOW)
- [ ] Output follows `references/output-format.md`
- [ ] Tools Status footer lists every Phase 1 tool with explicit status label
- [ ] Zero writes without explicit approval
- [ ] Writes executed footer lists each approved operation verbatim (empty if read-only)

## Examples

**Example 1: Security detection**
User: `/triage CrowdStrike critical`
Phase 0 loads crowdstrike.md + security.md → Phase 1 connect + query critical (24h, limit=10) → Phase 2 score + flag known FPs → Phase 3 correlate Tenable + Graph → Phase 4 table + actions.

**Example 2: Batch across tools**
User: "Triage last 24h"
Phase 0 loads all security topics → Phase 1 check all with time filter → Phase 2 score cross-tool → Phase 3 correlate CRITICAL/HIGH → Phase 4 full table + detail + summary.

**Example 3: Non-security**
User: `/triage stale Linear issues`
Phase 0 loads linear.md → Phase 1 query 14+ day stale → Phase 2 score by priority + workload + impact → Phase 4 sorted list with close/reassign/escalate.

**Example 4: Monitor-only outcome**
User: `/triage CrowdStrike low last 24h`
Phase 0 loads crowdstrike.md + security.md → Phase 1 connect + query LOW (24h, limit=50) → Phase 2 score; all findings composite <3.0 (Priority=LOW) → Phase 2b summary populated, Confidence=LOW (single-tool, no corroboration) → Phase 3 skipped (no HIGH/CRITICAL) → Phase 4 report recommends **Monitor** for the cluster: no individual finding warrants Investigate, but the volume merits watching for recurrence over the next window.

**Example 5: Close-only outcome**
User: `/triage Tenable critical host DC-01`
Phase 0 loads tenable.md → Phase 1 query CRITICAL on DC-01 → Phase 2 surfaces one CRITICAL → Phase 2b summary populated → Phase 2d FP verification: topic memory contains a `[confirmed]` entry "DC-01 KB5021233 false positive — Tenable plugin 156789, accepted risk 2026-04-12, review 2026-10-12" → tagged `[KNOWN]` and `[VERIFIED-FP]`, downgraded LOW → Phase 4 report recommends **Close** with rationale: "Matches accepted-risk entry; suppression still in effect, no new evidence."

**Example 6: Graceful degradation (Article XIV)**
User: `/triage last 24h` with CrowdStrike auth expired and Tenable reachable.
Phase 1 connectivity: CS returns 401 → labelled `auth-expired`, Tenable `online`, Graph `online`, Linear `online`, Airlock `online (no findings)`, Ramp `online (no findings)` → Phase 2 scores Tenable + Graph findings only → Phase 3 correlation for HIGH/CRITICAL notes "CS correlation skipped — auth-expired" inline against each finding that would have queried CS → Phase 4 report produced; Tools Status footer enumerates all six tools with explicit status labels; triage does NOT fail because CS is down.

**Example 7: Write requiring explicit approval (Article XII)**
User: `/triage CrowdStrike critical` surfaces one CRITICAL with proposed Airlock allowlist write.
Phase 4 produces report with Investigate + Remediate recommendation including a candidate write ("Add SHA-256 abc… to Airlock allowlist on policy Workstations") → Phase 5 enumerates the single proposed write as a numbered list → invokes `AskUserQuestion`: "Approve write 1 (Airlock allowlist add abc… on Workstations)? yes/no" → user replies "yes" → write executes → "Writes executed" footer lists the operation verbatim. If user replies "no", the report is delivered read-only and the "Writes executed" footer is empty.
