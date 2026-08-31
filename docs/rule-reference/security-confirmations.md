@rule security_confirmations
@version 2026-07-31
@scope every write/destructive operation against a security-sensitive tool (Airlock, CrowdStrike, Tenable, MS Graph, Slack, Linear, Tailscale, Confluence, Lever, NetCloud, Ramp)

# ─── POSTURE: ADVISORY (changed 2026-07-31 on operator instruction) ───
# This rule previously required an AskUserQuestion consent gate before every
# security-tool write, backed by a PreToolUse hook returning `ask`. BOTH halves
# were reverted to advisory on 2026-07-31 at the operator's explicit direction
# (prompt friction under the host's `auto` default permission mode).
#
# WHAT THIS MEANS, STATED PLAINLY: nothing now establishes human consent for a
# security-tool write. The hook warns; this rule says notify-and-proceed. OPA
# still gates AUTHORIZATION server-side, but authorization is not consent — OPA
# cannot establish that a human approved a specific target. The wrong-target
# class of error (right verb, wrong host/user/channel) is no longer caught
# before the write lands; it is caught after, or not at all.
#
# This is a deliberate, operator-owned risk acceptance, not an oversight. Do not
# silently re-tighten it. To restore the gate: revert this section and set the
# hook back to `permissionDecision: "ask"` (see hooks/security-write-confirm.py
# and PR #1727 for the implementation).

# ─── INVARIANTS (always-true) ───

INVARIANT the_advisory_is_notification_not_consent
  # WHY: an advisory records that a write was recognized and surfaced. It does
  #   Full: incidents#an-advisory-records-that-a-write-was-recognized-and

INVARIANT notification_includes_the_exact_target
  # WHY: "I'll contain the host" without the host id is theatre. The operator's
  #   Full: incidents#i-ll-contain-the-host-without-the-host-id

INVARIANT verbal_refusal_is_not_proof_of_no_action
  # WHY: a model under a safety classifier (or on the Opus-4.8 fallback)
  #   Full: incidents#a-model-under-a-safety-classifier-or-on-the

# ─── REQUIRED (must happen) ───

REQUIRED state_the_action_and_target_before_or_with_the_write
  # Notify in prose; do NOT call AskUserQuestion for routine security writes —
  # that is the gate that was removed. State the tool, the target identifier and
  # the action verb, then proceed without waiting.
  # When: any of these tool families is about to be called
  #   - mcp__remote-airlock__*  (block / approve / deny / modify)
  #   - mcp__remote-crowdstrike__*  (assign / close / contain / suppress)
  #   - mcp__remote-tenable__*  (launch_scan / modify_scan / schedule)
  #   - mcp__remote-msgraph__* / mcp__msgraph__*  (create_* / update_* / delete_* / patch_*)
  #   - Slack write ops on the current install — the Slack MCP is
  #     registered under GUID prefix
  #     `mcp__036e0c74-1e0e-4bce-ad71-2a678d79b204__*` (slack_send_message,
  #     slack_send_message_draft, slack_schedule_message, slack_update_canvas,
  #     etc.); legacy `mcp__slack-user__*` is also matched
  #   - Linear write ops — prefix depends on install: macOS/CLI registers
  #     the named prefix `mcp__linear-server__*` (current on this host);
  #     claude.ai-connector installs use the GUID prefix
  #     `mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__*`. The hook matches
  #     BOTH — named by prefix, GUID by operation-name (LINEAR_WRITE_TOOLS)
  #     — so save_*/create_*/delete_* stay gated under either id
  #   - mcp__compliance-access-framework__*  (provisioning writes:
  #     invite_to_workspace / create_* / link_* / sync_* — adds members to
  #     M365 groups, creates channels/spaces; matched as of 2026-06-15)
  #   - any other documented write op against a security tool
  # Then: say, at minimum:
  #   - the tool name being called
  #   - the target identifier (host/user/scan/channel/message)
  #   - the action verb (block, contain, send, …)

REQUIRED verify_post_state_after_a_destructive_write
  # WHY: this is the compensating control for the removed pre-gate. With no
  #   Full: incidents#this-is-the-compensating-control-for-the-removed-pre

REQUIRED bulk_writes_use_a_python_script_that_prints_its_target_list_first
  # WHY: the single-confirmation gate is gone, but the TARGET LIST is the part
  #   Full: incidents#the-single-confirmation-gate-is-gone-but-the-target

# ─── PROHIBITED (must not happen) ───

PROHIBITED claim_or_imply_that_a_write_was_human_approved
  # WHY: under this posture it was not. Writing "approved by operator" into a
  #   Full: incidents#under-this-posture-it-was-not-writing-approved-by
PROHIBITED silently_re_tightening_this_rule_back_to_a_gate
  # WHY: the operator chose this trade explicitly. Re-adding AskUserQuestion
  #   Full: incidents#the-operator-chose-this-trade-explicitly-re-adding-askuserquestion
PROHIBITED treating_this_relaxation_as_extending_to_the_deployment_gates_below
  # WHY: the DEPLOYMENT-APPROVAL GATES section is a SEPARATE control with a
  #      separate incident behind it. It is untouched by the 2026-07-31 revert.

# ─── EXCEPTIONS ───

EXCEPT read_operations_against_security_tools
  # Read-only queries (search_alerts, list_hosts, get_user, etc.) need
  # no notification at all. The rule is about state-changing writes.
  # NARROWED 2026-07-30 — this exception does NOT cover a read whose
  # RESPONSE carries a credential. Mutation is the wrong axis for a
  # read that EXFILTRATES: `airlock_get_agent_config` is tagged
  # `readOnlyHint: True` / `tags={"read"}` and returns the group's
  # agent SSL PRIVATE KEY in plaintext, so any OBO user holding only
  # airlock *read* access can extract an agent enrollment credential —
  # and because OPA's write-gating keys on mutation, nothing gates it.
  # The response also lands in the session transcript, which is
  # ingested, so a single call converts a stored secret into a
  # secret-at-rest in the log (this is what put C-8 rotation on the
  # table; rotation turned out to be console-only, no API).
  # THEREFORE when classifying ANY tool as read-safe, ask what the
  # response BODY contains, not just whether the call changes state.
  # Credential-bearing reads (agent/enrollment configs, connection
  # strings, `*_config` / `*_credentials` / `get_secret*` shapes) must
  # still be NOTIFIED like a write, and should redact the secret field
  # server-side. A tool that returns a key is a privilege-escalation
  # surface regardless of its verb.
  # NOTE (2026-07-31): this previously read "belong in the gated set".
  # There is no gated set any more — server-side redaction is now the
  # only real control on this class, which makes shipping it more
  # urgent, not less.

EXCEPT operations_already_authorized_by_a_skill_workflow
  # Skills that have their own confirmation step (e.g., /triage Phase
  # 5 actioning, /investigate IMMEDIATE actions) keep those steps —
  # they are skill-local and were NOT part of the 2026-07-31 revert.
  # Do not strip them to "match" this rule's new posture.

# ─── DETECTION (there is no enforcement) ───

Hook: `security-write-confirm` (PreToolUse) inspects tool name + params against
the write-op list above and emits an ADVISORY:

```json
{"systemMessage": "<exact action + target>"}
```

**REVERTED 2026-07-31 (operator instruction).** Between PR #1727 and this
revert the hook returned `permissionDecision: "ask"`, which per the
[hooks reference](https://code.claude.com/docs/en/hooks) prompts the user and —
critically on this `auto`-default host — *"forces a permission prompt in auto
mode: the classifier can still deny the tool call, but it can't approve the call
silently."* That gate was removed at the operator's request.

A top-level `systemMessage` is only a warning: it neither blocks nor prompts.
The measured consequence of this exact shape (audit finding H1, 14-day window):
**all 24** recognized Slack/Linear writes received the warning and **all 24
executed**; only 9/24 met the then-current confirmation contract. Expect the
same now. The hook's value is DETECTION and the audit log it writes via
`manifest_metrics`, not prevention.

**What each control does and does not do, under the current posture:**

| Control | Gates | Status |
|---|---|---|
| `security-write-confirm` hook | nothing — warns only | advisory (2026-07-31) |
| this rule's AskUserQuestion gate | nothing — removed | advisory (2026-07-31) |
| server-side OPA | authorization | **in force**, unchanged |
| the `auto`-mode safety classifier | its own judgement | in force, can still deny |
| post-write read-back | detection after the fact | required for destructive ops |

**OPA is not a substitute.** It gates *authorization* — whether the credential
may perform the operation. It cannot establish that a human approved a specific
target, so it does not close the wrong-target gap the removed gate covered. When
reasoning about coverage, do not count OPA as consent.

Fail-closed behavior (also 2026-07-26):
- **Generic wrapper envelopes** are normalized before classification. A tool like
  `mcp__msgraph__call_tool` carries the real operation in `tool_input["name"]`;
  classifying the outer name saw `call_tool`, matched neither a read nor a write
  verb, and silently allowed. All 12 MS Graph calls in the reviewed window used
  this shape (the observed inner operations were reads, so this was demonstrated
  reachability, not an observed unauthorized write).
- A wrapper whose **inner operation cannot be extracted** warns (it asked, until
  the 2026-07-31 revert — it no longer fails closed, because a warning stops
  nothing).
- An operation matching **neither a known read nor a known write verb** warns,
  with the same caveat.
- Read verbs are **token-anchored**. They were previously matched as raw
  substrings, so a read verb inside another word marked the operation read-only:
  `exfiltrate_widget` matched "get" inside "wid-get", and `budget_set` /
  `target_delete` / `widget_purge` would likewise have passed unreviewed.

Coverage: partial as detection, and zero as prevention — not every security write
is matched by the hook, and a same-user hook was never a hard boundary against
arbitrary same-user Bash execution even when it did gate. Under the current
posture "when in doubt" resolves to *name the target clearly and proceed*, not to
a manual AskUserQuestion — see PROHIBITED silently_re_tightening_this_rule_back_to_a_gate.

Referenced by:
- CLAUDE.md ("Write operations require confirmation")
- skills/investigate/manifest.yaml (requires_rules)
- skills/triage/manifest.yaml (requires_rules)
- skills/bulk-api-script/SKILL.md (bulk pattern)

# ─── DEPLOYMENT-APPROVAL GATES (GitHub environment protection) ───

INVARIANT never_clear_a_human_approval_gate_for_a_change_you_authored
  # WHY: a GitHub `environment` protection rule with a named required
  #   Full: incidents#a-github-environment-protection-rule-with-a-named-required

REQUIRED explicit_named_authorization_before_approving_a_deployment_gate
  # A generic "proceed", "continue", "go", or "ship it" is NOT authorization
  # to clear a deployment-approval gate, even when it directly follows the
  # agent saying it would not clear one. Those words authorize the WORK;
  # the gate is a separate, named decision. Required: the user names the
  # approval action or the specific run/environment.

FORBIDDEN approving_your_own_change_through_a_named_reviewer_gate
FORBIDDEN treating_can_approve_true_as_permission
  # `current_user_can_approve: true` is a capability statement, not consent.

# ─── FAILURE MODE ───

FAILURE self_approved_production_environment_gate_on_a_generic_proceed:
  # INCIDENT 2026-07-27 (mcp-infra): after stating "I'm deliberately not
  #   Full: incidents#2026-07-27-mcp-infra-after-stating-i-m
  RECOVERY: disclose the approval immediately and precisely (run id, what it
  deployed, that it was self-approved). Do not approve further gates. Ask
  once, with the action NAMED, and let the user decide.
  PREVENTION: when the answer to "did the user name THIS action?" is no,
  the answer to "may I approve it?" is no — regardless of how many times
  they have said to keep going. Surface the gate and hand over the exact
  command instead.
  NOTE: a later explicit direction ("I need you to deploy, ship, apply
  changes not gatekeep") IS sufficient for a NAMED apply, and clearing that
  gate then is correct. The failure is inferring it from a bare "proceed".

# ─── PR-REVIEW APPROVAL IS A NAMED REVIEWER GATE (scope clarification) ───
# The DEPLOYMENT-APPROVAL GATES heading above scopes to GitHub *environment*
# protection, and that heading is why the generically-worded
# `approving_your_own_change_through_a_named_reviewer_gate` FORBIDDEN read as
# not applying to an ordinary PR review. It does apply. A required-review gate
# IS a named reviewer gate; the separation it encodes is identical.

GUARD pattern="user said 'I approve' / 'approve it and merge' and I hold write
  access, so I'll submit `gh pr review --approve`" — on a PR containing ANY
  commit I authored or pushed:
  REFUSE to be the approver. The user's words authorize the DECISION; they do
  not make you a valid SECOND PARTY on code you wrote. Those are different
  things, and conflating them is the failure. Post the review only when you
  authored none of the diff.
  REQUIRED instead: state that you are disqualified, name who can approve
  (anyone who is neither you nor the PR author), and hand over the command.
  TELL THAT YOU GOT IT WRONG: the approval registers as a review object but
  `reviewDecision` stays `REVIEW_REQUIRED`. GitHub is refusing to COUNT it —
  under `require_last_push_approval: true` the approver may not be the last
  pusher, so an approval you submit after your own push is inert as well as
  improper. An approval that does not move `reviewDecision` is evidence you
  were not eligible, not evidence of a GitHub bug.
  NO EXCEPTIONS: authoring any part of the diff disqualifies you, regardless of
  how explicitly the user said "approve".
  # WHY: 2026-07-31 NavArch #17 — I pushed 3 review-fix commits, then read "I
  #   Full: incidents#2026-07-31-navarch-17-i-pushed-3-review

# ─── CHECK THE CONSTRAINT BEFORE THE WRITE, NOT AFTER THE BLOCK ───

GUARD pattern="this write is obviously benign / protective / helpful, so I'll
  just do it" — where the write is EITHER (a) a read/write the user has a
  `permissions.deny` rule for, reached via a DIFFERENT tool than the rule
  names, OR (b) an outbound write onto a THIRD PARTY's PR, issue, or channel:
  STOP and check the governing constraint FIRST. Both shapes share one
  mechanism: the action was judged on its INTENT and shipped without checking
  the boundary that governs it, and in both cases the boundary was knowable
  beforehand at zero cost.
  (a) A `Read(~/.aws/**)`-style deny is TOOL-LEVEL and subprocess-bypassable by
      construction (see KB `claude-code-managed-settings-deployment`), so the
      guard CANNOT stop you — which is exactly why the norm must be behavioral.
      Reaching the same content via `Bash`/`aws configure get`/`python3 open()`
      is routing around the rule, not satisfying it. Use the sanctioned path or
      ask; never treat "the deny didn't fire" as permission.
  (b) A comment that TAGS someone fires a notification immediately, and
      deleting it does NOT unsend that notification — so it is not reversible
      in the way a local edit is. Protective intent does not authorize it.
      Report the finding to YOUR user and let them decide who to tell.
  NO EXCEPTIONS for either shape: ask, or route it through the user.
  # WHY: 2026-07-31, twice in one session. (a) An `aws configure get` loop
  #   Full: incidents#2026-07-31-twice-in-one-session-a-an

GUARD pattern="the user replied with an ITEM NUMBER from a list you wrote ('do 2', 'fix 3',
  'the second one') and the referenced item is a SECURITY-CONTROL change" (disable a required
  review, widen a bypass, remove a check, loosen a policy):
  AN ITEM-NUMBER REFERENCE IS NOT A NAMED AUTHORIZATION. It is MORE deceptive than a bare
  "proceed" precisely because it feels specific — but the specificity lives in YOUR list, not
  in the user's words, so nothing in the transcript records that they authorized THIS
  control's removal, and a reader of the audit trail cannot reconstruct what was approved.
  REQUIRED: re-state the exact change as an AskUserQuestion option that NAMES the control, its
  scope, and what stops being enforced; act only on that selection. NO EXCEPTIONS for a
  STANDING control change — one that binds every future operation, not only the current one.
  # WHY: 2026-07-31 — "fix 3" referred to my own list item "azure-automations branch
  #   Full: incidents#2026-07-31-fix-3-referred-to-my-own


GUARD pattern="a permission/classifier denial cited a FLAGGED PATTERN (credential
  exploration, destructive scope, adversarial shape) and you are about to unblock it by
  ASKING the user for authorization":
  THE OPTION TEXT YOU WRITE IS THE CONSENT RECORD. A generic option ("authorize me for this
  session", "yes, proceed", "grant access") yields BLANKET consent, which does NOT clear a
  flagged pattern — the next attempt is denied again. This is the MIRROR of the item-number
  GUARD above: there the USER's reference was vague; here YOUR OWN option is, and it is
  easier to miss precisely because you wrote it and know what you meant.
  REQUIRED: the option must NAME the exact resource and the exact operation — the specific
  Keychain item / secret / ARN / role / path, and what will be read or written. Put it in the
  option label or description, NOT only in surrounding prose, which the consent record does
  not capture.
  ALSO REQUIRED: state the BRIDGING RATIONALE in the tool call's `description` whenever the
  resource's vendor differs from the task's stated subject. A probe that is unremarkable
  alone ("read Databricks credentials") scores as exploration when the stated task names a
  different system ("understand Claude configuration") and nothing connects the two.
  NO EXCEPTIONS after a denial that named a flagged pattern.
  # WHY: 2026-08-01 — a Databricks credential sweep was denied 3x. An AskUserQuestion option
  #   Full: incidents#2026-08-01-a-databricks-credential-sweep-was-denied

GUARD pattern="I need a credential for this task, let me find it" — about to ENUMERATE the
  credential store (`security dump-keychain`, `env | grep -i <vendor>`, a loop over guessed
  item names, profile-list fishing):
  LOOK UP THE ONE NAMED ITEM INSTEAD. Enumeration is the shape that scores as exploration,
  and it is almost never necessary: the item's exact name is usually already recorded in the
  KB topic for that system — and very often in a file you have ALREADY READ earlier in the
  same task. Grep the topic first (`grep -i keychain agent-memory/topics/<system>.md`), then
  read that ONE item by name.
  THE COST IS NOT ONE DENIAL. A sweep POISONS THE SESSION: denials are STICKY, so the narrow,
  correct follow-up you issue next is denied too on the accumulated pattern, and the only exit
  is the named-authorization round-trip in the GUARD above. Opening narrow costs one tool
  call; opening broad costs the sweep, every subsequent probe, and a user interruption.
  NO EXCEPTIONS: never enumerate a credential store to discover a name you could look up.
  # WHY: 2026-08-01 Atlassian token inventory — SECOND instance in ONE DAY (the Databricks
  # WHY above is the first). I opened with `security dump-keychain | grep -iE
  #   Full: incidents#above-is-the-first-i-opened-with-security-dump

GUARD pattern="launching an UNATTENDED loop (poller, striker, watcher, retry-until-success)
  that performs a REMOTE ACTION against a SINGLE host, device, or account":
  GIVE IT A FAILURE CEILING BEFORE YOU DETACH IT. A retry loop is correct for a
  TRANSIENT-UNREACHABLE target and catastrophic for a target the ACTION ITSELF is
  breaking — and those two look IDENTICAL from the caller's side, because both present
  as "connect, fail, host disappears." Retry-forever therefore converts an unknown
  failure mode into a sustained attack on one machine, and against a single evidence
  host each cycle also mutates the artifact you are preserving.
  REQUIRED: (a) a hard attempt cap and an abort-on-N-consecutive-failures; (b) an
  explicit cancel step in whatever plan supersedes it — pre-positioned automation does
  NOT re-evaluate itself when the situation changes; (c) the loop's OWN failures counted
  and surfaced, not just its successes.
  ALSO: the poll interval must be shorter than the target's OBSERVED WINDOW, not its
  interval — a 5-minute poll against a host appearing for <60s reads as permanently
  offline while it is reachable several times.
  NO EXCEPTIONS for a loop that writes, executes, or opens sessions on a single named host.
  # WHY: 2026-08-01 — a 15-second RTR striker was detached against one MacBook under
  #   Full: incidents#2026-08-01-a-15-second-rtr-striker-was
