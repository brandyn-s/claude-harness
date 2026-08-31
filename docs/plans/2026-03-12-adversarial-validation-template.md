# Adversarial Validation Step Template - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a reusable adversarial validation reference file that any security skill can include to challenge its own findings before presenting them as final. Then integrate it into the three consuming skills.

**Architecture:** A single `references/adversarial-validation.md` file lives in a shared location (`~/.claude/skills/_shared/`). Skills reference it by reading the file at runtime. A cross-domain `false-positives.json` in agent-memory persists suppression decisions across all skills. Each consuming skill adds a one-line include instruction pointing to the shared reference.

**Tech Stack:** Markdown reference files, JSON data file. No code dependencies.

---

### Task 1: Create shared references directory and validation template

**Files:**
- Create: `~/.claude/skills/_shared/adversarial-validation.md`

**Step 1: Create the shared directory**

```bash
mkdir -p $HOME/.claude/skills/_shared
```

**Step 2: Write the adversarial validation template**

The template must be domain-agnostic. It references a false-positives database, defines suppression rules as a table, lists challenge questions parameterized by domain, and specifies the 4-tier confidence scoring system.

```markdown
# Adversarial Validation - Step Template

> Include this step after severity scoring and before final output in any skill
> that produces security findings. Read this file, then execute the validation
> process against the current findings set.

## 1. Load Suppression Database

Read `~/.claude/agent-memory/false-positives.json` and filter entries matching the
current domain (component_id, tool, stig_id, or finding_pattern).

Also check for domain-specific false positive files:
- Component hardening: `example-compliance-repo/docs/hardening/false-positives.json`
- STIG assessment: `example-compliance-repo/stig-assessment/false-positives.json` (if exists)

## 2. Auto-Suppression Rules

Apply these rules to each finding. If a rule matches, suppress the finding
(remove from primary output, log to suppressed list with reason).

| Rule | Condition | Action |
|------|-----------|--------|
| **False positive match** | Finding title/pattern matches a `false-positives.json` entry | Suppress: "Previously accepted risk (FP-xxx)" |
| **Already remediated** | Config repo shows the fix is applied (git log, file content) | Remove: "Fixed in commit [sha]" |
| **Vendor limitation** | Vendor does not support the recommended control (documented) | Reclassify: "Accepted risk - vendor limitation" |
| **Duplicate finding** | Same root cause as another finding in this set | Merge: keep higher-severity instance, note duplicate |
| **Stale finding** | CVE/advisory older than 2 years with no known active exploitation | Deprioritize: reduce severity by 1 level |

## 3. Challenge Questions

For each remaining finding, evaluate these questions. Answer each YES/NO
with a one-line justification. If 3+ answers reduce the risk, lower the
adjusted severity by one level.

### Architecture context
1. **Is this exploitable given the network architecture?**
   Consider: network segmentation, VPN-only access, air-gapped networks,
   firewall rules. A CVE in a web UI reachable only via Tailscale VPN on
   an isolated VLAN is different from one on a public-facing server.

2. **Does the host OS mitigate this?**
   Consider: NixOS immutability (read-only filesystem), SELinux/AppArmor,
   containerization. If the attack requires persistent filesystem changes
   and the host is read-only, impact is reduced.

3. **Is this a machine-to-machine interface?**
   If there are no interactive user sessions (no keyboard, no browser),
   attacks requiring user interaction (phishing, social engineering,
   session hijacking) are not applicable.

### Evidence quality
4. **Is the evidence from a high-authority source?**
   Tier 1 (running device/API state) > Tier 2 (config files/source code) >
   Tier 3 (documentation/vendor claims). Findings based only on Tier 3
   evidence should be marked UNCERTAIN, not CONFIRMED.

5. **Has the default credential/config actually been deployed?**
   Check config repos and deployment scripts. "Default credentials" is
   only a finding if the defaults are actually in production. If custom
   credentials are deployed, the finding is invalid.

6. **Has the CVE been patched in the deployed version?**
   Cross-reference the deployed firmware/software version against the CVE's
   affected version range. If patched, the finding is invalid.

### Operational context
7. **Is this a known accepted risk?**
   Check topic memory files for `[confirmed]` entries about this exact
   pattern. If the org has previously accepted this risk with documented
   compensating controls, note it rather than re-flagging.

8. **Would remediation break functionality?**
   Some hardening actions disable features the system depends on (e.g.,
   disabling SSLv3 on a device that only speaks SSLv3). Flag as "Accepted
   risk - operational dependency" rather than recommending a breaking change.

## 4. Confidence Scoring

After applying suppression rules and challenge questions, assign confidence:

| Level | Score | Criteria | Action |
|-------|-------|----------|--------|
| **CONFIRMED** | 90-100% | Tier 1/2 evidence, exploitable in actual architecture, not suppressed | Include in primary findings |
| **LIKELY** | 70-89% | Tier 2/3 evidence, plausible but not device-verified | Include in primary findings |
| **UNCERTAIN** | 40-69% | Tier 3 only (docs/vendor claims), not verified against deployment | Include in appendix only |
| **SUPPRESSED** | 0% | Matched suppression rule or all challenge questions reduce risk | Log to suppressed list |

## 5. Output Structure

After validation, the findings set should have three sections:

### Primary findings (CONFIRMED + LIKELY)
These go in the main report/output. Each includes the confidence level
and a one-line validation note (e.g., "Confirmed: admin/admin in
vendor-switch-registry.nix, default deployed to all targets").

### Appendix (UNCERTAIN)
These are reported separately with a note that they need device-level
verification. Do not mix with primary findings.

### Suppression log
For audit trail. Each suppressed finding includes the rule that matched
and the justification. New suppressions that should persist across runs
are appended to `false-positives.json` with the user's approval.

## 6. Updating False Positives

If a finding was suppressed for a reason that should persist (accepted risk,
vendor limitation, operational dependency), ask the user:

> "Finding [title] was suppressed as [reason]. Should this be persisted to
> false-positives.json so it's automatically suppressed in future runs?"

If yes, append an entry:
```json
{
  "id": "fp-NNN",
  "domain": "component|stig|triage",
  "finding_pattern": "title or regex",
  "reason": "accepted risk - ...",
  "accepted_by": "user name",
  "accepted_date": "YYYY-MM-DD",
  "review_date": "YYYY-MM-DD (6 months out)",
  "component_id": "optional"
}
```
```

**Step 3: Verify the file is readable and under reasonable size**

Run: `python -c "content = open('$HOME/.claude/skills/_shared/adversarial-validation.md', encoding='utf-8').read(); print(f'{len(content.split())} words, {len(content)} chars')"`

Expected: ~800-1000 words

**Step 4: Commit**

```bash
cd $HOME/.claude
git add skills/_shared/adversarial-validation.md
git commit -m "feat: add shared adversarial validation step template"
```

---

### Task 2: Create cross-domain false positives database

**Files:**
- Create: `~/.claude/agent-memory/false-positives.json`

**Step 1: Write the initial empty structure**

```json
{
  "version": "1.0",
  "updated": "2026-03-12",
  "entries": []
}
```

This is the cross-domain database. The component-hardening specific one at
`example-compliance-repo/docs/hardening/false-positives.json` already exists and is
checked first for component-specific suppressions.

**Step 2: Verify**

Run: `python -c "import json; d=json.load(open('$HOME/.claude/agent-memory/false-positives.json', encoding='utf-8')); print(f'Valid, {len(d[\"entries\"])} entries')"`

Expected: `Valid, 0 entries`

**Step 3: Commit**

```bash
cd $HOME/.claude
git add agent-memory/false-positives.json
git commit -m "feat: add cross-domain false positives database"
```

---

### Task 3: Integrate into /component-hardening

**Files:**
- Modify: `~/.claude/skills/component-hardening/SKILL.md`

**Step 1: Replace the inline Step 5.5 with a reference to the shared template**

Find the current Step 5.5 section (adversarial validation with inline suppression rules,
challenge questions, and confidence scoring). Replace with:

```markdown
## Step 5.5: Adversarial Validation

Read and follow the shared validation template:
`~/.claude/skills/_shared/adversarial-validation.md`

**Domain-specific additions for component hardening:**
- Check `example-compliance-repo/docs/hardening/false-positives.json` first (component-specific)
- Then check `~/.claude/agent-memory/false-positives.json` (cross-domain)
- For challenge question #2 (host OS): NixOS immutability is always YES for ExampleTarget components
- For challenge question #3 (machine-to-machine): YES for all onboard components except management terminals
```

This keeps the component-specific context while delegating the generic framework to the shared template.

**Step 2: Verify SKILL.md structure and word count**

Run: `python -c "
content = open('$HOME/.claude/skills/component-hardening/SKILL.md', encoding='utf-8').read()
assert 'adversarial-validation.md' in content, 'Missing reference to shared template'
words = len(content.split())
print(f'{words} words (limit 5000)')
assert words < 5000
print('Structure OK')
"`

**Step 3: Commit**

```bash
cd $HOME/.claude
git add skills/component-hardening/SKILL.md
git commit -m "refactor(component-hardening): delegate validation to shared template"
```

---

### Task 4: Integrate into /triage

**Files:**
- Modify: `~/.claude/skills/triage/SKILL.md`

**Step 1: Read the current triage skill to find the right insertion point**

The validation step should go after Phase 2 (severity scoring) and before Phase 3
(output). Read the skill to find the exact location.

**Step 2: Add a validation phase**

Insert after the severity scoring phase:

```markdown
## Phase 2c: Adversarial Validation (optional)

When triage produces 5+ findings, run adversarial validation to reduce noise:

Read and follow: `~/.claude/skills/_shared/adversarial-validation.md`

**Domain-specific for triage:**
- Check `~/.claude/agent-memory/false-positives.json` for cross-domain suppressions
- For triage, challenge questions #1 (network architecture) and #7 (known accepted risk) are highest value
- Suppress findings tagged `[KNOWN]` in Phase 2 from the primary output (they're already deprioritized)
- Skip this phase for triage sets under 5 findings (overhead not worth it for small sets)
```

**Step 3: Verify**

Run: `python -c "
content = open('$HOME/.claude/skills/triage/SKILL.md', encoding='utf-8').read()
assert 'adversarial-validation.md' in content, 'Missing reference'
words = len(content.split())
print(f'{words} words (limit 5000)')
assert words < 5000
print('Triage integration OK')
"`

**Step 4: Commit**

```bash
cd $HOME/.claude
git add skills/triage/SKILL.md
git commit -m "feat(triage): add adversarial validation phase for large finding sets"
```

---

### Task 5: Integrate into a separate skill (not included in this export)

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export)

**Step 1: Read the current stig-assess skill to find the right insertion point**

The validation should apply during red-team mode or when reviewing OPEN findings.

**Step 2: Add validation reference**

Find the red-team or review section and add:

```markdown
### Adversarial Validation for OPEN Findings

When reviewing or red-teaming OPEN findings, run adversarial validation:

Read and follow: `~/.claude/skills/_shared/adversarial-validation.md`

**Domain-specific for STIG assessment:**
- Challenge question #2 (host OS): NixOS immutability applies to all ExampleTarget compute nodes
- Challenge question #3 (machine-to-machine): All onboard devices are M2M except management access via Tailscale
- Findings rated UNCERTAIN should be marked NOT_REVIEWED in the CKLB (not OPEN)
- Findings rated SUPPRESSED should be marked NOT_APPLICABLE with justification in the comments field
```

**Step 3: Verify**

Run: `python -c "
content = open('$HOME/.claude/a separate skill (not included in this export)', encoding='utf-8').read()
assert 'adversarial-validation.md' in content, 'Missing reference'
print('STIG integration OK')
"`

**Step 4: Commit**

```bash
cd $HOME/.claude
git add a separate skill (not included in this export)
git commit -m "feat(stig-assess): add adversarial validation for OPEN findings review"
```

---

### Task 6: Verification and validation

**Step 1: Verify all files exist and parse**

```bash
python -c "
import json

# Shared template exists and is readable
t = open('$HOME/.claude/skills/_shared/adversarial-validation.md', encoding='utf-8').read()
assert '## 1. Load Suppression Database' in t
assert '## 4. Confidence Scoring' in t
assert 'CONFIRMED' in t and 'SUPPRESSED' in t
print(f'Template: {len(t.split())} words, all sections present')

# Cross-domain false positives valid JSON
fp = json.load(open('$HOME/.claude/agent-memory/false-positives.json', encoding='utf-8'))
assert 'entries' in fp
print(f'False positives: valid, {len(fp[\"entries\"])} entries')

# All three skills reference the template
for skill in ['component-hardening', 'triage', 'stig-assess']:
    s = open(f'$HOME/.claude/skills/{skill}/SKILL.md', encoding='utf-8').read()
    assert 'adversarial-validation.md' in s, f'{skill} missing reference'
    words = len(s.split())
    assert words < 5000, f'{skill} over word limit: {words}'
    print(f'{skill}: references template, {words} words')

print('All checks passed')
"
```

**Step 2: Trace through a triage scenario**

Mental verification: `/triage CrowdStrike critical` with 8 findings:
1. Phase 0: Load CrowdStrike topic memory
2. Phase 1: Query alerts API, get 8 critical detections
3. Phase 2: Severity score all 8
4. **Phase 2c**: Read adversarial-validation.md -> load false-positives.json -> 0 suppressions -> challenge questions on each -> 2 findings downgraded (test hosts), 1 marked UNCERTAIN (Tier 3 only) -> 5 CONFIRMED, 2 LIKELY, 1 UNCERTAIN
5. Phase 3: Output 7 primary findings, 1 in appendix, 0 suppressed

This is correct - the validation reduces noise without blocking legitimate findings.

**Step 3: Ship all changes**

Batch all commits from Tasks 1-5 into a single PR for claude-config.

---

## Verification Summary

| Check | What it validates | Method |
|-------|-------------------|--------|
| Template sections | All 6 sections present (suppression, challenge, confidence, output, FP update) | String assertions |
| JSON validity | false-positives.json parses | json.load() |
| Skill references | All 3 consuming skills reference the template | String search |
| Word counts | No skill exceeds 5000 words after integration | len(split()) |
| Workflow trace | Triage scenario produces correct finding distribution | Manual trace |
| Non-interference | Template is read-only reference, doesn't modify skill execution order | Structural: skills add one phase, template is passive |
