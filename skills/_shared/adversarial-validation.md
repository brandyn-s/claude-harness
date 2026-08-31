# Adversarial Validation - Step Template

> Include this step after severity scoring and before final output in any skill
> that produces security findings. Read this file, then execute the validation
> process against the current findings set.
>
> **Research basis**: Huang et al. (2023) proved self-critique without external
> signals degrades accuracy. Snorkel AI (2025) showed self-critique turns 98%
> accuracy into 57% on high-performance tasks. This template provides external
> verification signals (rules, questions, databases) instead of self-critique.
> See knowledge-base/topics/adversarial-validation-research.md for full citations.

## 1. Load Suppression Database

Read `~/.claude/agent-memory/false-positives.json` and filter entries matching the
current domain (component_id, tool, stig_id, or finding_pattern).

Also check for domain-specific false positive files:
- Component hardening: `example-compliance-repo/docs/hardening/false-positives.json`
- STIG assessment: `example-compliance-repo/stig-assessment/false-positives.json` (if exists)

### Expiration check

After loading false-positive entries, check the `review_date` field on each:
- If `review_date` is **past today**: the entry is expired. Do NOT suppress. Report: "FP-xxx expired on [date], finding re-enabled for review."
- If `review_date` is **within 30 days**: suppress normally, but warn: "FP-xxx expires [date], schedule re-review."
- If `review_date` is **missing**: treat as non-expiring (legacy entry). Flag for backfill.

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

### Evidence tiers

When assigning confidence, use the source authority to determine the tier:

| Tier | Source | Example |
|------|--------|---------|
| **1** | Live system state (API query, SSH session, device output) | `show running-config`, API response, SNMP walk |
| **2** | Source-of-truth config files and deployment scripts | Nix configs, Terraform state, Ansible playbooks, CI/CD outputs |
| **3** | Documentation and vendor claims | Confluence pages, vendor PDFs, datasheets, README files |

If you did not query the live system, the highest confidence you can assign is **LIKELY** (Tier 2), not **CONFIRMED**. CONFIRMED requires Tier 1 evidence or Tier 2 evidence on an immutable system (e.g., NixOS where config IS state).

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
  "review_date": "YYYY-MM-DD (max 12 months from accepted_date, REQUIRED for new entries)",
  "component_id": "optional"
}
```

**`review_date` is required on all new entries.** Maximum period: 12 months. Expired entries stop suppressing findings automatically, forcing periodic re-review.
