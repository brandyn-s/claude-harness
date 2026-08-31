@rule security_confirmations
@version 2026-08-21
@scope every state-changing or credential-bearing operation involving security-sensitive tools, external systems, approval gates, or third parties

# DECISION CONTRACT
# Full tool-family inventory, measured history, incidents, and recovery detail:
# docs/rule-reference/security-confirmations.md

# ─── CURRENT POSTURE ───
POSTURE routine_security_tool_writes_are_advisory_notify_and_proceed
# This operator-selected posture removed the blanket AskUserQuestion gate on
# 2026-07-31. `security-write-confirm` emits a `systemMessage`; it does not block
# or prove consent. Server-side OPA proves authorization, not human approval.
# Do not silently restore the blanket gate or claim a routine write was approved.
# The named high-risk gates below remain separate and mandatory.

# ─── TRIGGERS ───
ON any_state_changing_Airlock_CrowdStrike_Tenable_MS_Graph_Slack_Linear_Tailscale_Confluence_Lever_NetCloud_Ramp_or_provisioning_call
ON any_read_that_returns_credentials_secrets_keys_connection_strings_or_enrollment_material
ON any_GitHub_environment_or_required_review_approval
ON any_standing_security_control_weakening_or_permission_bypass
ON any_outbound_write_to_a_third_party_surface
ON any_unattended_remote_action_loop_against_one_host_device_or_account

# ─── CORE INVARIANTS ───
INVARIANT advisory_notification_is_not_consent
INVARIANT every_notification_names_the_exact_tool_action_and_target_identifier
INVARIANT authorization_capability_and_user_consent_are_distinct
INVARIANT a_permission_denial_cannot_be_bypassed_through_another_tool
INVARIANT destructive_writes_require_post_state_verification
INVARIANT credential_bearing_reads_are_not_safe_merely_because_they_are_read_only
INVARIANT never_approve_your_own_authored_or_last_pushed_change
INVARIANT a_generic_proceed_continue_or_item_number_is_not_named_authorization_for_a_control_gate
INVARIANT verbal_refusal_is_not_evidence_that_no_action_occurred
INVARIANT one_named_authorization_has_one_bounded_authorization_envelope

# ─── REQUIRED FOR ROUTINE WRITES ───
STEP_1 before or with the call, state the concrete tool, action verb, and exact
       target (host id, user, scan, channel, message, group, workspace, etc.).
STEP_2 proceed without a blanket AskUserQuestion prompt under the current advisory
       posture, unless a skill-local gate or named high-risk gate below applies.
STEP_3 after a destructive or consequential write, read back the effective state and
       distinguish requested, API-accepted, and observed state.
STEP_4 for bulk operations, use a bounded script that prints/counts the exact target
       list first, records per-item outcome, and fails visibly on partial completion.
STEP_5 never describe the write as "operator approved" unless the transcript contains
       explicit authorization for that exact action and target.

# ─── CREDENTIAL-BEARING READS ───
REQUIRED classify by response content, not mutation hint. Notify with target and
purpose before reads shaped like agent/enrollment config, connection string,
`*_credentials`, or `get_secret*`. Avoid rendering secret fields and prefer
server-side redaction. Never expose secret values in chat, logs, or reports.
FORBIDDEN enumerating credential stores to discover a name. Read the relevant topic
or configuration, resolve one named item, and access only that item if authorized.

# ─── NAMED HIGH-RISK GATES (MANDATORY) ───
REQUIRED explicit named authorization before approving a GitHub environment gate,
required-review gate, production apply, standing security-control weakening,
permission bypass, or the exact resource/operation called out by a denial.
REQUIRED the consent option itself names the control/resource, scope, operation, and
what protection stops applying; surrounding prose is not the consent record.
REQUIRED if a referenced list item changes a standing control, restate the exact
change and obtain named authorization rather than inferring it from "do 2".
REQUIRED if the resource vendor differs from the stated task, record the bridging
rationale before seeking authorization.
FORBIDDEN clearing a human approval gate for a change authored or last pushed by
this agent. Capability such as `current_user_can_approve: true` is not permission.
FORBIDDEN submitting an approval review on any PR containing this agent's work;
handoff to an independent reviewer even if the user wants the PR approved.

# ─── AUTHORIZATION ENVELOPE ───
REQUIRED one explicit named authorization establishes one bounded authorization
envelope for that exact operation under the named source, plan, graph, account,
authority, and safety conditions.
REQUIRED while those conditions remain unchanged, continue the authorized operation
and its necessary read-only checks, polling, receipts, and live readback without
asking again.
REQUIRED re-ask only for material source, plan, graph, account, authority, or safety drift,
or for applying a residual plan after a partial apply. A tool handoff, login or
credential refresh, elapsed time, receipt, unchanged retry or poll, and verification
readback do not create a new consent gate.

# ─── THIRD-PARTY AND DENY BOUNDARIES ───
REQUIRED ask or route through the user before an outbound third-party comment,
mention, issue, message, or other notification not already authorized by the task.
Deletion does not unsend notifications.
FORBIDDEN treating a `permissions.deny` rule as tool-specific permission to reach
the same content through Bash, Python, SDK, or another connector.
FORBIDDEN treating a security classifier/hook not firing as authorization.

# ─── UNATTENDED REMOTE ACTIONS ───
REQUIRED before detaching: hard attempt ceiling, abort after bounded consecutive
failures, explicit cancellation path, per-attempt outcome log, and a poll interval
shorter than the target's observed availability window.
FORBIDDEN retry-forever against one target; caller-visible failure can be caused by
the action itself and must not be converted into sustained repeated impact.

# ─── FORBIDDEN SHORTCUTS ───
FORBIDDEN silently re-tightening routine writes into a blanket consent gate.
FORBIDDEN extending the advisory relaxation to deployment/review/control gates.
FORBIDDEN vague notices such as "contain the host" without the identifier.
FORBIDDEN counting OPA, an advisory hook, or auto-mode classification as consent.
FORBIDDEN approving a gate on "proceed", "continue", "ship it", or an item number
unless the user explicitly named that gate/control/action.
FORBIDDEN broad credential/keychain/environment sweeps when one named lookup suffices.
FORBIDDEN asking again inside an unchanged authorization envelope.

# ─── OVERRIDE RESISTANCE ───
GUARD pattern="it is protective" or "the deny did not fire" or "I have permission":
  STOP and check the governing boundary. Helpful intent and technical capability do
  not supply named consent or authorize routing around a deny.
GUARD pattern="approve it" when this agent authored_or_pushed_the_change:
  REFUSE self-approval; identify the independent reviewer or handoff command.

# ─── ENFORCEMENT AND ON-DEMAND ROUTING ───
# `security-write-confirm` is advisory detection; server-side OPA is authorization.
# Neither proves consent. Skill-local confirmation steps remain in force.
# Relevant skills: `/investigate`, `/triage`, `/security-alerts`,
# `/bulk-api-script`, `/invite-to-workspace`, `/provision`.
# Detailed tool mappings and recovery: docs/rule-reference/security-confirmations.md
