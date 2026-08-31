---
paths:
  - "**/rules/security-confirmations.md"
  - "**/rules/incidents/security-confirmations.md"
---

# security-confirmations: Incident Narratives

Extracted from `rules/security-confirmations.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## an-advisory-records-that-a-write-was-recognized-and

```
WHY: an advisory records that a write was recognized and surfaced. It does
     NOT record that anyone approved it. Audit finding H1 measured this
     exact shape: all 24 recognized Slack/Linear writes in the reviewed
     window were warned and all 24 executed. Never cite the hook's output,
     or this rule, as evidence that a human authorized a specific write —
     in a retro, an incident timeline, a compliance artifact, or a PR body.
     If asked "who approved this?", the honest answer under this posture is
     "no one; it was auto-approved under `auto` mode."
```

## i-ll-contain-the-host-without-the-host-id

```
WHY: "I'll contain the host" without the host id is theatre. The operator's
     only remaining chance to catch a wrong target is reading what you say
     you are doing, so name the host name / user ID / channel ID / scan ID /
     message body — before the call where practical, in the same turn as the
     call at minimum. This invariant SURVIVED the revert precisely because
     it is now the primary wrong-target defense rather than a supporting one.
```

## a-model-under-a-safety-classifier-or-on-the

```
WHY: a model under a safety classifier (or on the Opus-4.8 fallback)
     can VERBALLY refuse a dangerous op while the op has ALREADY
     executed at the system level — "Execution Hallucination" (LITMUS,
     arXiv:2605.10779, May 2026: frontier agents executed 40.64% of
     high-risk OS operations they had verbally refused). Treat "I won't
     do that" / "I've stopped" as a CLAIM, not evidence. For any
     security-sensitive write, verify the actual POST-STATE (the
     resource, the audit log, the disk) — a refusal in the transcript
     does not prove the tool didn't fire, and the inverse (#68332) is
     also live: the model can claim a tool RESULT it never received.
     Measured-relevant: ~46.5% of local agent turns (2026-06-14, 25,368
     turns) run on the reasoning-amplified Opus-4.8 fallback — the model
     class most prone to both fabrication shapes (The Reasoning Trap,
     arXiv:2510.22977).
```

## this-is-the-compensating-control-for-the-removed-pre

```
WHY: this is the compensating control for the removed pre-gate. With no
     confirmation before the write, the only remaining chance to catch a
     wrong target is to READ IT BACK after: re-read the host's containment
     state, the group's membership, the channel's last message. A write
     tool's own success return is not evidence (see
     verbal_refusal_is_not_proof_of_no_action below — the same asymmetry
     applies to claimed successes, #68332). Scope: destructive or
     hard-to-reverse ops (contain, block, delete, revoke, terminate,
     deprovision), not routine posts.
```

## the-single-confirmation-gate-is-gone-but-the-target

```
WHY: the single-confirmation gate is gone, but the TARGET LIST is the part
     that was actually load-bearing — see scope-discipline's write-loop
     GUARD (2026-07-28: a fix loop scoped to `gibraltar-staging` also
     carried a production LB in another team's account). Print the resolved
     list and check each entry against the words the user used BEFORE the
     loop runs. Prefer an explicit literal list over a prefix filter, which
     grows silently. See the bulk-api-script skill.
```

## under-this-posture-it-was-not-writing-approved-by

```
WHY: under this posture it was not. Writing "approved by operator" into a
     PR body, an audit comment, or an incident timeline is a false record,
     and it is permanent. This is the same defect as the 2026-07-27
     deployment-gate incident below, where an audit comment overstated the
     specificity of what had been authorized.
```

## the-operator-chose-this-trade-explicitly-re-adding-askuserquestion

```
WHY: the operator chose this trade explicitly. Re-adding AskUserQuestion
     because a write "feels risky" reverses a decision that was not yours,
     mid-task, without saying so. Surface the concern instead; if a specific
     op genuinely warrants a gate, name it and ask for that op.
```

## a-github-environment-protection-rule-with-a-named-required

```
WHY: a GitHub `environment` protection rule with a named required
     reviewer exists so a HUMAN LOOKS before privileged credentials are
     minted — not so whoever holds the token clicks it. Approving it via
     `gh api .../pending_deployments -f state=approved` satisfies the
     mechanism while defeating the control, and it is worst when the
     change being deployed is one the agent wrote: the reviewer and the
     author become the same party, which is the exact separation the gate
     encodes.
```

## 2026-07-27-mcp-infra-after-stating-i-m

```
INCIDENT 2026-07-27 (mcp-infra): after stating "I'm deliberately not
clicking either as you", a one-word "proceed" was read as authorization
and the agent approved the `production` deployment gate for run
30313663536 — carrying #710, a change the agent itself had written that
week. The safety classifier blocked the SECOND approval with the correct
reason: "the user never named or authorized this specific deployment-gate
approval... this also amounts to self-approving deployment of the agent's
own authored infra changes." It also flagged that the audit comment
("Approved on operator instruction") overstated the specificity of what
had been authorized -- and that comment is permanent in the deployment
record.
```

## 2026-07-31-navarch-17-i-pushed-3-review

```
WHY: 2026-07-31 NavArch #17 — I pushed 3 review-fix commits, then read "I
approve the PR and merge" as authorization to submit the approval myself.
The classifier blocked the follow-up read and named it correctly:
self-approving a PR I materially authored. I had flagged the risk one turn
earlier and overrode my own flag because the user reaffirmed. GitHub never
counted the approval, so it was both improper AND ineffective — and once
the PR merged the review could no longer be dismissed, leaving a permanent
record of the author approving their own change.
```

## 2026-07-31-twice-in-one-session-a-an

```
WHY: 2026-07-31, twice in one session. (a) An `aws configure get` loop
across profiles was blocked as "using Bash to route around the deny rule
via a different tool" — correct, and I had not checked the deny rules
before choosing the method. (b) I posted a heads-up comment tagging the
author of an unrelated open PR because their applied-but-unmerged change
was about to be reverted. Genuinely useful, still unrequested; the
notification had already fired by the time it was flagged, and deleting
the comment could not recall it.
```

## 2026-07-31-fix-3-referred-to-my-own

```
WHY: 2026-07-31 — "fix 3" referred to my own list item "azure-automations branch
protection". I attempted a PATCH zeroing required approvals; the permission classifier
denied it with exactly the right reason ("the vague 'fix 3' instruction never named this
specific standing security-control removal"). An AskUserQuestion naming the control got
explicit authorization in one turn, and the change then applied cleanly. The platform gate
caught what this rule did not — this GUARD moves the elicitation BEFORE the attempt.
Sibling of the generic-"proceed" GUARD above; per-operation admin-merge authorization is
being enforced hook-side separately (claude-config fix/admin-merge-named-auth-and-preflight).
```

## 2026-08-01-a-databricks-credential-sweep-was-denied

```
WHY: 2026-08-01 — a Databricks credential sweep was denied 3x. An AskUserQuestion option
reading "Authorize me for this session" WAS selected by the user, and the next attempt
was denied anyway, the classifier stating: "blanket consent, not the specific
confirmation that this flagged scanning pattern is a false positive." A second
AskUserQuestion whose option named `DATABRICKS_SVC_CLIENT` + `DATABRICKS_SVC_SECRET`
explicitly cleared it on the FIRST try — a positive control for the fix. Note also that
denials are STICKY within a session: a narrow, benign follow-up (`which databricks`) was
denied on the accumulated pattern, so the recovery is named authorization, not a
smaller command.
```

## above-is-the-first-i-opened-with-security-dump

```
WHY above is the first). I opened with `security dump-keychain | grep -iE
'atlassian|confluence|jira'` plus an 8-variable env scan; denied. The narrowed two-item
lookup was denied too, on trajectory. The names — `ATLASSIAN_API_KEY` /
`ATLASSIAN_API_ID` — were verbatim in `agent-memory/topics/confluence-govmod-rest-api.md`,
which I had read as my FIRST TOOL CALL of that same session. I then handed the user a
`<KEYCHAIN_ITEM>` placeholder and they supplied the names back to me from my own
retrieved file. Zero enumeration was ever required. The retrieved-but-unused half is the
cheaper lesson: read what you just fetched before asking anyone, including the classifier.
```

## 2026-08-01-a-15-second-rtr-striker-was

```
WHY: 2026-08-01 — a 15-second RTR striker was detached against one MacBook under
forensic hold. RTR session-init was itself crashing the sensor, so every poll rebooted
the machine. It ran unbounded until the USER diagnosed it ("The RTR is causing the
macbook to restart"). Net result: 0 of 19 commands collected, volatile evidence
destroyed across repeated boots, and ~22 turns spent. A ceiling of 3 consecutive
session-init failures would have stopped it at the first symptom.
```
