# SCA Review Skill Design

**Date:** 2026-03-18
**Status:** Approved
**Approach:** Clustered Batch Dialogue (multi-agent adversarial review)

## Problem

The existing a separate skill (not included in this export) pipeline catches technical issues in CKLBs - fabricated evidence, wrong controls evaluated, grounding failures. But it doesn't evaluate whether findings would survive an actual Navy SCA review. The SCA reviewer asks different questions: does the finding answer what `check_content` asks? Is the argument convincing? Does it meet RAG v2.2 quality bars for mitigations and predisposing conditions?

The gap between "finding is technically grounded" and "finding would pass SCA review" is where assessment packages get sent back for rework.

## Solution

A new a separate skill (not included in this export) skill that simulates the SCA review process using two agents in an adversarial loop:

- **Reviewer (main session):** Reads each finding against its `check_content` and RAG v2.2 requirements. Identifies content quality issues.
- **Evidence agent (worker subagent):** Searches the codebase for evidence to substantiate or refute each finding. Reports what it found.
- **Main session decides disposition:** Using the reviewer's critique and the evidence agent's findings, determines whether to accept, strengthen, flip to Open, or flag for human review.

## Requirements

- One CKLB per invocation
- Confidence threshold model: evidence agent finds truth, main session decides action
- Reviewer criteria: RAG R1-R13 (structural via Python, content via LLM) + check_content matching
- Two review modes: STIG (mechanical - does finding cite the right setting?) and SRG (argumentative - does finding make a convincing case?)
- Evidence agent access: PSM repo (code-graph, code-search, file reads) + architecture docs (example-assessment-repo/docs/)
- Output: diff JSON file as primary artifact, optional user-controlled apply step
- Consumes prior a separate skill (not included in this export) results if available (grounding, verdicts, prose issues)

## Architecture

```
a separate skill (not included in this export) --> a separate skill (not included in this export) --> a separate skill (not included in this export) --> submission
  (create)        (ground truth)    (SCA simulation)
```

```
CKLB
  |
  v
Phase 0: Setup
  - Resolve paths, detect repos, load architecture docs
  - Prepare architecture brief (condensed system context for evidence agent)
  - Check code-search indexing
  |
  v
Phase 1: Extract & Cluster (Python: sca_extract_cluster.py)
  - Parse CKLB, classify STIG vs SRG mode per rule
  - RAG structural checks (R1-R6, R11-R13) - deterministic, no LLM
  - Cross-rule text similarity scan (Jaccard > 0.85 = copy-paste flag)
  - Contradiction pre-scan (same entity, opposing claims)
  - Cluster by topic (8-20 rules per cluster)
  - Attach prior a separate skill (not included in this export) results if available
  - Build relevance index for discovery routing
  - Output: <stem>_clusters.json
  |
  v
Phase 2: Review Clusters (main session loop, 15-25 iterations)
  For each cluster:
    Step 1 - Reviewer pass (main session):
      STIG mode: 3 questions (specific file/setting? correct value? plausible path?)
      SRG mode: 3 questions (specific mechanism? how verified? full requirement?)
      Cross-rule: review copy-paste and contradiction flags
      Output: priority (high/medium/low) + critique per rule

    Step 2 - Evidence agent (worker subagent):
      High priority: deep code-graph/code-search + file reads + arch docs
      Low priority: lightweight file existence check
      Reports: evidence found, strength, proposed prose, discoveries
      Does NOT decide status - reports evidence only

    Step 3 - Main session decides disposition:
      Uses decision matrix (priority x evidence strength x status supported)
      Actions: accept / strengthen / flip_open / flag_human
      Rebuttal trigger: only when low-priority rule's cited file is missing

    Step 4 - Record results:
      Append to <stem>_decisions.json
      Update discoveries list (filtered by relevance to future clusters)
      Log systemic patterns (same root cause 3+ times) - no halt
  |
  v
Phase 3: Diff, Report, Apply
  - Generate <stem>_sca_diff.json from decisions
  - Print summary report (counts, systemic issues, status changes, human queue)
  - User chooses: apply all / by type / individually / skip
  - Apply script modifies CKLB, preserves .bak.<timestamp>
  - Baseline comparison against prior SCA review run if exists
```

## Decision Matrix

The main session uses this matrix to determine the action for each rule after receiving the evidence agent's report:

| Reviewer priority | Evidence strength | Status supported? | Action |
|---|---|---|---|
| any | strong | yes | `accept` - rewrite prose with real evidence |
| any | strong | no | `flip_open` - evidence disproves status |
| high | partial | plausible | `strengthen` prose + `flag_human` |
| high | none | - | `flip_open` (STIG) or `flag_human` (SRG) |
| medium | partial | plausible | `strengthen` with evidence found |
| medium | none | - | `flag_human` |
| low | file confirmed | yes | `accept` - no change needed |
| low | file missing/changed | - | escalate to high, rebut once |

Key distinction for SRG mode: when evidence strength is `none`, SRG rules get `flag_human` instead of `flip_open` because the device may be configured through a management plane (e.g., NCM, vendor portal) that has no representation in the source repo.

## Review Modes

### STIG Mode (mechanical)

Applied to CKLBs matching `STIG_*` pattern or rules with specific file/command references in check_content.

Three reviewer questions:
1. Does `finding_details` cite the specific file/setting/command that `check_content` asks about?
2. Does the cited value match what would support the status?
3. Is the cited path/setting plausible for this system?

### SRG Mode (argumentative)

Applied to CKLBs matching `SRG_*` pattern or rules with capability language in check_content.

Three reviewer questions:
1. Does the finding identify the SPECIFIC mechanism the device uses to satisfy this requirement?
2. Does the finding explain HOW this mechanism was verified as active/configured?
3. Does the finding address ALL aspects of `check_content` or only part?

## Diff File Schema

```json
{
  "metadata": {
    "cklb": "filename.cklb",
    "date": "YYYY-MM-DD",
    "total_rules_reviewed": 247,
    "clusters": 18,
    "evidence_agent_calls": 18,
    "rebuttals": 3
  },
  "summary": {
    "accept_no_change": 142,
    "accept_strengthened": 58,
    "flip_open": 12,
    "flag_human": 31,
    "systemic_issues": 4
  },
  "systemic_issues": [
    {
      "root_cause": "description",
      "affected_rules": ["V-XXXXXX", ...],
      "recommendation": "how to fix globally"
    }
  ],
  "changes": [
    {
      "group_id": "V-XXXXXX",
      "action": "accept | strengthen | flip_open | flag_human",
      "rule_mode": "stig | srg",
      "reviewer_priority": "high | medium | low",
      "evidence_strength": "strong | partial | none",
      "reviewer_critique": "what the reviewer flagged",
      "evidence_found": "what the evidence agent found",
      "old_status": "not_a_finding | open | not_applicable",
      "new_status": "not_a_finding | open | not_applicable",
      "old_finding_details": "original text",
      "new_finding_details": "proposed replacement",
      "old_comments": "original comments",
      "new_comments": "proposed replacement with audit trail",
      "flag_reason": "only for flag_human actions",
      "rag_violations_fixed": ["R3", "R8"]
    }
  ]
}
```

## File Layout

### Skill files
```
~/.claude/a separate skill (not included in this export)
  SKILL.md                        # Skill definition + orchestration
  references/
    srg-review-questions.md       # 3 SRG review questions
    decision-matrix.md            # Priority x evidence -> action table
    reviewer-heuristics.md        # Cross-rule patterns, thresholds
```

### Scripts (shared repo)
```
claude-code-architecture/a separate skill (not included in this export)
  sca_extract_cluster.py          # NEW - extract, RAG checks, cluster, similarity
  sca_apply_diff.py               # NEW - apply diff JSON to CKLB
```

### Working artifacts (per assessment repo)
```
<assessment-repo>/stig-assessment/sca_review_work/
  <stem>_clusters.json            # Clustered rules with metadata
  <stem>_decisions.json           # Per-rule decisions from core loop
  <stem>_sca_diff.json            # Final diff (primary artifact)
```

## Evidence Agent Prompt

The evidence agent is a `worker` subagent. Key prompt elements:

- Role: "evidence investigator" - find truth, don't defend or attack
- Receives: architecture brief, cluster rules with reviewer critiques, filtered discoveries from prior clusters
- High priority rules: deep code-graph/code-search investigation, file reads, architecture doc review
- Low priority rules: confirm cited files exist, verify line numbers approximately correct
- Reports evidence only - does NOT decide actions
- Outputs: evidence_found, evidence_contradicts_status, evidence_strength, proposed prose, discoveries

## Red Team Mitigations (incorporated)

| Risk | Mitigation |
|---|---|
| No-challenge filter blinds defender | All rules sent to evidence agent; reviewer sets priority, not gate |
| "Defender" contradictory role | Renamed to "evidence agent" - finds truth, main session decides |
| Main session cognitive overload | RAG structural checks moved to Python script |
| Vague SRG review criteria | 3 concrete yes/no questions per SRG rule |
| Cross-cluster contradictions invisible | Pre-scan text similarity in Phase 1 Python |
| Discoveries list unbounded | Filtered by relevance (file path/key matching) per cluster |
| Systemic pattern halts automation | Logged with systemic flag, reported in Phase 3, no halt |
| Adversarial theatre (LLM self-play) | check_content IS the checklist - reviewer matches finding against it mechanically |

## What This Skill Does NOT Do

- Replace a separate skill (not included in this export) grounding - consumes grounding results, doesn't redo them
- Assess new rules - only reviews existing assessed findings
- Modify POA&M workbooks or XLSX - CKLB only (POA&M regenerated by existing scripts)
- Validate ACAS/Nessus scan artifacts - separate SCA requirement
- Run against all 18 CKLBs in one invocation - one CKLB per run

## Success Criteria

- Every assessed rule receives a disposition (accept/strengthen/flip_open/flag_human)
- `flip_open` and `flag_human` cite specific evidence (or lack thereof) from the evidence agent
- `strengthen` actions produce prose that passes RAG R3/R8/R9 (specific evidence, not generic)
- Systemic issues detected and grouped (not flagged 50x individually)
- Diff file provides full audit trail (old value, new value, reason, evidence)
- Baseline comparison detects regressions from prior SCA review run
- SRG rules evaluated on argument quality, not just field presence
- STIG rules evaluated on mechanical check_content matching

## Estimated Operational Characteristics

- 15-25 evidence agent calls per CKLB (one per cluster)
- 1 optional rebuttal call per escalated low-priority finding
- ~45-90 minutes per CKLB depending on rule count and evidence search depth
- Primary token cost is evidence agent calls (each gets architecture brief + cluster rules + codebase queries)
