# STAGED SPEC — `iam-unsatisfiable-condition`

**Status:** STAGED, NOT INSTALLED. Requires the historical-replay fire-rate
measurement below before `/ship-hook`. Do not install on the strength of the
incident count alone.

**Tier:** T0-hook (PreToolUse on `Write`/`Edit`)
**Staged:** 2026-08-12
**Parent rule:** `rules/check-before-change.md` required check 8b
**Prior tier:** `agent-memory/topics/aws-infra-s3.md` — "An unsatisfiable CONDITION
is a DENY — and knowing the pattern is not checking against it (2026-08-02)"

---

## Why a hook rather than more rule text

This lesson has been documented since before 2026-08-02 and has now recurred
**three times**, with an escalating pattern that rules cannot fix:

1. Documented as a T4 topic entry (`s3:prefix` on `s3:GetBucketLocation`).
2. 2026-08-02: **I re-stated the mechanism in a Terraform comment**
   (`activity-signal-weekly.tf`) and then reproduced it *one statement over in the
   same file*. The topic entry's own title records this: "knowing the pattern is
   not checking against it."
3. 2026-08-12: reproduced again in `slack-audit-digest.tf` — `StringLike
   s3:prefix` on a statement granting `s3:GetBucketLocation`, which denied Athena's
   output-location preflight and killed the FIRST scheduled run of a new lane with
   `InvalidRequestException: Unable to verify/create output bucket`. The sibling
   alert lane had the same statement **unconditioned and working**; the defect came
   from re-deriving a "tighter" version of a proven statement.

Per `rules/incidents/verify-effectiveness.md` ("a rule violated under load with
correct wording is evidence for a MECHANICAL GATE, not for stronger prose"), the
correct response to a third recurrence of correctly-worded guidance is a gate.

The failure is also maximally quiet: `terraform validate`, `plan`, `apply`, and the
entire unit suite are green, because only a real runtime invoke exercises the
statement. There is no cheaper detection point than authoring time.

## Trigger

`PreToolUse` on `Write` and `Edit` where the target path matches `*.tf`,
`*.tf.json`, or a file whose content contains `"Version": "2012-10-17"`
(inline JSON policy documents in non-`.tf` files).

## Detection

Parse each policy statement in the written content (HCL `statement { }` blocks and
JSON `Statement` arrays). For each statement, intersect its `actions` against its
`condition` keys using a table of known action↔key incompatibilities. Emit a
finding when a statement contains an action that does not support a condition key
present on that same statement.

Seed table — every row is a measured incident, not a guess:

| condition key | supported only by | observed misuse |
|---|---|---|
| `s3:prefix` | `s3:ListBucket`, `s3:ListBucketVersions` | `s3:GetBucketLocation` (2026-08-02, 2026-08-12) |
| `s3:delimiter`, `s3:max-keys` | the same List actions | — |
| `cloudwatch:namespace` | `PutMetricData` and metric *writes* | `GetMetricStatistics` and other reads |
| `ecs:cluster` | cluster-scoped ECS actions | `ecs:DescribeTaskDefinition` (cluster-independent) |

The table is deliberately a curated allowlist of KNOWN pairs, not a general
derivation from AWS's service-authorization reference. A general check needs the
full condition-key matrix per action; that data is available
(`service-authorization/reference_policies_actions-resources-contextkeys.html`) but
ingesting and maintaining it is a separate deliverable. Start narrow.

## Output

Non-blocking `systemMessage` naming the statement, the action, the offending key,
and the remedy: *split the conditioned and unconditioned actions into separate
statements.* It must NOT block — see the fire-rate requirement.

## REQUIRED before install (fire-rate measurement)

`rules/verify-effectiveness.md` sets a >10% block-rate bar as a workflow DoS.
Before `/ship-hook`:

1. Run the detector over every `*.tf` file in `mcp-infra`, plus the other
   Terraform repos, as a historical replay.
2. Report: files scanned, statements parsed, findings, and a hand-classification
   of every finding as REAL or FALSE-POSITIVE.
3. A false positive here is expensive in a specific way — a legitimately
   conditioned statement that the parser mis-attributes would train me to dismiss
   the message, which is exactly how the 2026-08-02 recurrence happened past a
   comment I had written myself.
4. If the parser cannot reliably associate a `condition` block with its statement
   in HCL (dynamic blocks, `for_each`, merged locals, `aws_iam_policy_document`
   composition via `source_policy_documents`), report that as a coverage limit and
   scope the check to statically-analyzable statements rather than guessing.

Fire rate on the current corpus: **UNMEASURED.** Known real hits available as
positive controls: the 2026-08-12 `slack-audit-digest.tf` statement (now fixed —
recover it from git history) and the 2026-08-02 `activity-signal-weekly.tf` one.
Do not report a zero-finding replay as validation without running those two
through the detector first and confirming it flags them.
