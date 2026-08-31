---

name: sca-review
description: "Simulate SCA reviewer feedback on CKLBs and ground finding claims against source code."
user-invocable: false
disable-model-invocation: true  # Intentionally inert: both user and model access stay off until the Phase 1 helpers are implemented and qualified.
when_to_use: |
  Use when preparing CKLBs for SCA submission. Trigger phrases: "SCA review",
  "simulate SCA feedback", "improve CKLB quality", "prepare CKLBs for submission".
  Do NOT use for initial STIG assessment or code scanning
  (use /semgrep). Multi-agent quality simulation: reviews findings against
  check_content and RAG conformance, dispatches evidence agents to ground claims
  against source code, produces diff of proposed improvements.
  STATUS: Phase 1 helpers (sca_extract_cluster.py, sca_apply_diff.py) are
  documented stubs — running them exits with a clear message. Skill is not
  yet end-to-end runnable until the helpers ship. This source is intentionally
  inert and excluded from marketplace packaging.
argument-hint: "[filename.cklb] [--target example-target|physical-mcs] [--repo source-path]"
effort: max
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Agent AskUserQuestion Bash Glob Grep Read mcp__codebase-memory-mcp__search_graph mcp__codebase-memory-mcp__index_status mcp__codebase-memory-mcp__index_repository mcp__codebase-memory-mcp__search_code
compatibility:
  # Requires the codebase-memory-mcp server for evidence-grounding against
  # PSM source code. CKLB files are read from local disk; no other external
  # service deps.
  requires:
    - mcp: codebase-memory-mcp
---


> **Runtime policy:** Resolve the effective model and preserve refusal/fallback provenance per `../_shared/model-runtime-policy.md`.

## sca-review

# SCA Review - Multi-Agent CKLB Quality Simulation

Simulates a Navy SCA reviewer examining each CKLB finding against its
check_content and RAG v2.2 requirements. An evidence agent searches the
codebase for truth. Output is a diff file of proposed changes.

## Pipeline Position

```
/stig-assess --> /stig-verify --> /sca-review --> submission
  (create)        (ground truth)    (SCA simulation)
```

Key distinction: `/stig-verify` asks "is this finding truthful?" (grounding).
`/sca-review` asks "would an SCA reviewer accept this finding?" (quality).

> **Required context:** Read `~/.claude/skills/_shared/stig-common.md` for target loading and CKLB handling rules.

## Phase 0: Setup

0. **Load target profile**: Parse `--target` argument (default: `example-target`). Read `~/.claude/skills/_shared/stig-targets/{target}.md`. All paths and device mappings come from the profile.

1. **Resolve CKLB path**: Parse argument. If bare filename, search the assessment repo's checklist directories from the profile, then the working directory.

2. **Detect assessment repo** from CKLB path or the profile. Set `ASSESSMENT_REPO`.

3. **Source repo**: `--repo` argument or the source repo from the loaded profile.

4. **Map device to ground truth files**: Match the CKLB filename against
   the profile's Device Config Map section (or `/stig-verify/references/device-config-map.md` for ExampleTarget legacy).
   This tells you:
   - Which config files to read upfront (ground truth)
   - Expected rule count for R11
   - Device keywords for context

5. **Read ground truth files upfront**: Before any cluster review, read ALL
   ground truth config files for this device into context. For vendor-radio: read
   `nix/packages/configd/vendor-radio.json` and `nix/modules/vendor-radio.nix`. For
   Mission Computer: read `stig-example-program.nix`, `configuration.nix`, `example.nix`.
   This avoids redundant queries per-rule - most findings can be verified
   directly against these files.

5b. **Read hardening guide** (if available): The device-config-map has a
   `Hardening guide` column. If a guide exists for this device, read it in
   Phase 0. For cloud_managed devices, the hardening guide IS the primary
   evidence source (vendor API capabilities, implementation status, known gaps).
   This was the Ball Camera lesson (2026-03-30): 13 rules were flagged for
   human review, then all 13 were resolved in minutes by reading the vendor-thermal-camera
   hardening guide.

6. **Prepare architecture brief**: Read the system overview from
   `<assessment-repo>/docs/architecture/example-target-systems-overview.md` (first 80 lines).
   For device-specific context, also read `<assessment-repo>/docs/<device>/`.
   Condense into a 10-15 line summary for evidence agent calls.

7. **Check indexing**: Run `mcp__codebase-memory-mcp__index_status`
   for PSM repo. If not indexed, run `mcp__codebase-memory-mcp__index_repository`.

8. **Load references**: Read `references/decision-matrix.md`,
   `references/srg-review-questions.md`, `references/reviewer-heuristics.md`.

9. **Find prior verify results**: Check these directories in order for
   `<stem>_grounding.json` or `<stem>_results.json`:
   - `<cklb_dir>/../scripts/verify_results/`
   - `<assessment-repo>/stig-assessment/scripts/verify_results/`
   If found, pass the directory to Phase 1.

9b. **Find prior SCA review diffs**: Check these directories for
   `<stem>_sca_diff.json`:
   - `<assessment-repo>/stig-assessment/sca_review_work/`
   - `~/sca_review_work/`
   If found, pass via `--prior-diff` to Phase 1. The extract script loads
   prior changes and reports them as a baseline. This prevents regressions
   (missing changes the prior session found) and surfaces the delta
   (what's new since the last review). The VendorRouter lesson (2026-03-30):
   running without prior-diff awareness missed 13 credential redactions
   that the prior session had already identified.

## Phase 1: Extract and Cluster (Python script)

> **Implementation status:** `sca_extract_cluster.py` and `sca_apply_diff.py`
> are documented-but-unimplemented stubs (exit 2 with a clear message).
> Phase 1 script implementation is in progress. Procedure prose below
> describes intended behavior; running the bash commands will fail until
> the scripts ship.

```bash
SCRIPTS="$HOME/.claude/skills/sca-review/scripts"
CKLB="{cklb_full_path}"
STEM="$(basename "$CKLB" .cklb)"

python3 "$SCRIPTS/sca_extract_cluster.py" \
  -f "$CKLB" \
  --verify-results "{verify_dir_if_found}" \
  --prior-diff "{prior_diff_if_found}" \
  --expected-rules {expected_count_from_device_config_map}
```

Output: `sca_review_work/<stem>_clusters.json`

The extract script produces clusters sorted by priority:
1. **Credential Exposures** (CRITICAL) — broadened patterns catch REDACTED-PASSWORD
   in any context, routerPassword=, glc_ tokens, RxAdmin/, API keys
2. **Host-vs-Device Confusion** (CRITICAL) — flags findings that cite
   NixOS host controls for switch/camera/radio SRG requirements
3. **CAT I Open** (CRITICAL)
4. **Copy-Paste NaF Divergent** (HIGH) — SCA rejection risk
5. **Prior SUSPICIOUS** (HIGH) — from /stig-verify
6. **Copy-Paste Open** (MEDIUM) — shared root cause, acceptable
7. **Remaining Open** (MEDIUM)
8. **NaF spot check** (LOW)

If `--prior-diff` was provided, the clusters JSON includes a `prior_delta`
section listing prior changes not yet reflected in the current CKLB.

For batch mode (all CKLBs in a directory):
```bash
python3 "$SCRIPTS/sca_extract_cluster.py" \
  --batch "{cklb_directory}" \
  --verify-results "{verify_dir}"
```
This produces a fleet triage ranking sorted by quality flags (worst first).

## Phase 2: Review Clusters (Core Loop)

Initialize:
- `decisions = []` (running list of all decisions)
- `discoveries = []` (facts learned from evidence, carried forward)
- `systemic_counts = {}` (root cause pattern tracking)

For each cluster in `clusters.json`:

### Step 1: Reviewer Pass (this session)

Write a Python script to read the cluster JSON and print rules for the
current cluster with their pre-computed flags (rag_violations, copy_paste,
cred_exposed, host_vs_device_mismatch, prior_verdict, prior_sca_action).
For each rule, print truncated check_content + finding_details.
Fill in Q1/Q2/Q3 for every rule — do not skip or batch-review.

For each rule, apply the review questions:

**STIG-mode rules** - three questions:
1. Does `finding_details` cite the specific file/setting/command that
   `check_content` asks about?
2. Does the cited value match what would support the status?
3. Is the cited path/setting plausible for this system?
   (see `references/reviewer-heuristics.md` NixOS path plausibility)

**SRG-mode rules** - three questions (from `references/srg-review-questions.md`):
1. Does the finding identify the SPECIFIC mechanism?
2. Does the finding explain HOW it was verified?
3. Does the finding address ALL aspects of check_content?

**All rules** - check flags from Phase 1:
- `rag_violations`: any structural RAG failures -> auto HIGH
- `copy_paste` + `cp_check_divergent`: sharing text with different check_content -> HIGH
- `cred_exposed`: credential in finding_details -> CRITICAL (redact immediately)
- `host_vs_device_mismatch`: wrong device evidence cited -> CRITICAL (see `references/reviewer-heuristics.md`)
- `prior_verdict`: SUSPICIOUS -> auto HIGH, UNCERTAIN -> at least MEDIUM
- `prior_sca_action`: if prior diff had a change for this rule, apply it unless contradicted

Assign each rule: priority (high/medium/low), critique text, which questions failed.

### Step 2: Evidence Investigation

**Choose investigation mode based on device complexity:**

**Cloud-managed devices** (device_class=cloud_managed: VendorRouter, vendor-satcom, cameras):
NO local config exists in the PSM repo. Do NOT dispatch an evidence agent.
Instead, evaluate findings using the **hardening guide** (loaded in Phase 0
Step 5b) and argument quality:
- Does the finding cite a specific vendor capability or management portal setting?
- Does it reference a vendor doc, NCM screenshot, or hardening guide?
- For NaF: is the claim plausible for this device class?
- For Open: is the deficiency clearly described?
- For NA: is the justification reasonable?

**IMPORTANT: Cloud-managed does NOT mean skip quality checks.** Even without
an evidence agent, the Phase 1 extract script still runs credential scanning,
host-vs-device confusion detection, RAG structural checks, and copy-paste
divergence analysis. Process CRITICAL and HIGH clusters from Phase 1 output
BEFORE accepting remaining rules. The VendorRouter lesson (2026-03-30):
accepting all 102 rules as-is missed 13 credential exposures that the
extract script's credential scan would have caught.

Do NOT flip to Open just because source code evidence doesn't exist -
the device has no source code to check.

**Small devices** (device_class=managed_device: vendor-radio, vendor-switch, vendor-switch-b, vendor-gnss):
Ground truth files are short (under 100 lines). Investigate in the main
session directly - read the ground truth files (already loaded in Phase 0
Step 5) and verify claims against them. Use code-search only for claims
that reference files outside the ground truth set.

**Large devices** (device_class=nixos_host: Mission Computer, Perception, Firewall, VPN, ASD):
Ground truth files are 500+ lines. Dispatch a worker evidence agent with:

```
cd {psm_repo} && claude --print ... (or use Agent tool from within PSM repo dir)
```

**IMPORTANT**: The Agent tool requires a git repo as CWD. Either:
(a) Use `Bash` to `cd` into the PSM repo before dispatching, or
(b) Investigate directly in main session if ground truth files are already loaded

Evidence agent prompt (for large devices only):

```
You are an evidence investigator for STIG/SRG assessment findings.
Your job is to find the truth - not to defend or attack findings.
This is READ-ONLY research - do NOT create or modify any files.

## System Context
{architecture_brief}

## Ground Truth Files Already Read
{list the files read in Phase 0 Step 5 and key contents}

## Relevant Discoveries from Prior Clusters
{filtered_discoveries}

## Instructions
For HIGH priority rules: query code-graph/code-search, read source files,
check architecture docs. Report file:line and exact content.
For LOW priority rules: confirm cited files exist.

## Response Format (per rule)
- group_id, evidence_found, evidence_contradicts_status, evidence_strength,
  proposed_finding_details, proposed_comments, discovery

Do NOT decide actions. Report evidence only.

## Rules to Investigate
{cluster rules with reviewer priorities and critiques}
```

### Step 3: Main Session Decides Disposition

For each rule, apply the decision matrix from `references/decision-matrix.md`.

| Reviewer Priority | Evidence Strength | Status Supported? | Action |
|---|---|---|---|
| any | strong | yes | `accept` - rewrite prose with real evidence |
| any | strong | no | `flip_open` - evidence disproves status |
| high | partial | plausible | `strengthen` prose + `flag_human` |
| high | none | - | `flip_open` (STIG) or `flag_human` (SRG) |
| medium | partial | plausible | `strengthen` with evidence found |
| medium | none | - | `flag_human` |
| low | file confirmed | yes | `accept` - no change needed |
| low | file missing/changed | - | escalate to high, rebut once |

Rebuttal: only when a LOW priority rule's cited file is missing/changed.
One rebuttal max per rule.

For `flag_human` actions: preserve the original finding_details (do NOT
blank them). Add the flag_reason explaining what the SCA reviewer would
question and what evidence is needed.

### Step 4: Record Results

Append each decision to the `decisions` list with fields:
- group_id, action, rule_mode, reviewer_priority, evidence_strength
- reviewer_critique, reviewer_questions_failed (list of Q1/Q2/Q3 that failed)
- evidence_found, old_status, new_status
- old_finding_details, new_finding_details (preserve original for flag_human)
- old_comments, new_comments, flag_reason, rag_violations_fixed

**Discoveries**: After each cluster, record key facts:
```
discovery: "vendor-radio.json has disable_concurrent_sessions=1 at id 34"
discovery: "No PKI/certificate settings exist on vendor-radio"
```
Filter discoveries for the next cluster using the relevance_index from Phase 1.

**Systemic tracking**: Count root cause patterns. If same pattern appears
3+ times, mark all instances with `systemic: true`.

**Batch strengthen for copy-paste groups**: When the Phase 1 clusters JSON
shows `check_content_divergent: true` for a copy-paste group (same finding
text but different check_content requirements), AND evidence exists for each
specific requirement, generate a batch of strengthen actions that replaces
the generic shared text with rule-specific evidence. Write a Python script
to iterate the group, map each rule's check_content keyword to the specific
evidence line, and produce per-rule proposed_finding_details. This is more
efficient than reviewing each rule individually.

Example: 10 audit rules share "stig-example-program.nix deploys comprehensive audit rules"
but each asks about a different syscall. stig-example-program.nix has the specific rules
at lines 67-100. The batch script maps: RULE-000000 (mount) -> line 84,
RULE-000000 (rename/unlink) -> line 81, RULE-000000 (init_module) -> line 87, etc.

## Phase 3: Diff, Report, Apply

### Generate Diff

Write a Python script to compile all decisions into
`sca_review_work/<stem>_sca_diff.json` with the schema:

```json
{
  "metadata": {
    "cklb": "filename.cklb",
    "date": "YYYY-MM-DD",
    "total_rules_reviewed": N,
    "clusters": M,
    "evidence_agent_calls": K,
    "rebuttals": R
  },
  "summary": {
    "accept_no_change": A,
    "accept_strengthened": B,
    "flip_open": C,
    "flag_human": D,
    "systemic_issues": E
  },
  "systemic_issues": [
    {"root_cause": "...", "affected_rules": [...], "recommendation": "..."}
  ],
  "changes": [
    {
      "group_id": "V-XXXXXX",
      "action": "accept | strengthen | flip_open | flag_human",
      "rule_mode": "stig | srg",
      "reviewer_priority": "high | medium | low",
      "reviewer_questions_failed": ["Q1", "Q3"],
      "evidence_strength": "strong | partial | none",
      "reviewer_critique": "...",
      "evidence_found": "...",
      "old_status": "not_a_finding",
      "new_status": "not_a_finding",
      "old_finding_details": "...",
      "new_finding_details": "...",
      "old_comments": "...",
      "new_comments": "[sca-review YYYY-MM-DD] ...",
      "flag_reason": "only for flag_human",
      "rag_violations_fixed": ["R3"]
    }
  ]
}
```

### Report

Print summary to user:
```
SCA Review Complete: {filename}
  {N} rules reviewed across {M} clusters
  {A} accepted (no change needed)
  {B} strengthened (better evidence prose)
  {C} flipped NaF -> Open (evidence not found)
  {D} flagged for human review
  {E} systemic issues detected

Systemic Issues:
  1. [{count} rules] {description}

Status Change Summary:
  Before: {NaF} NaF, {Open} Open, {NA} NA
  After:  {NaF'} NaF, {Open'} Open, {NA} NA
```

### Apply

Offer the user:
1. **Apply all**: `python3 "$SCRIPTS/sca_apply_diff.py" -f <cklb> --diff <diff>`
2. **Apply by type**: `--filter strengthen` or `--filter strengthen,flip_open`
3. **Apply individually**: walk through each change
4. **Skip**: keep diff as review artifact only
5. **Dry run**: `--dry-run` shows what would change without writing

## Examples

```
/sca-review STIG_Assessment_Mission_Computer.cklb
/sca-review SRG_Assessment_Silvus_Radio.cklb --repo ~/path/to/psm
/sca-review SRG_Assessment_Cradlepoint_R1900_NDM.cklb
```

## Success Criteria

- Every assessed rule receives a disposition (accept/strengthen/flip_open/flag_human)
- `flip_open` and `flag_human` cite specific evidence from the evidence agent
- `strengthen` actions produce prose that passes RAG R3/R8/R9
- Systemic issues grouped, not flagged individually
- Diff file provides full audit trail with reviewer_questions_failed
- SRG rules evaluated on argument quality, STIG rules on mechanical matching
- `flag_human` preserves original finding_details (doesn't blank them)
