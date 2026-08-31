"""PreToolUse hook: require user confirmation before security write operations.

Enforces the security-confirmations rule by detecting MCP write tool calls
to security-sensitive servers (CrowdStrike, Tenable, Airlock, MS Graph, Slack,
Linear, Tailscale, Confluence, Lever, NetCloud, Ramp) and injecting a
confirmation prompt.

Detects writes by matching tool names against known write patterns. Read-only
tools (list, get, search, query, describe) pass through without confirmation.

Server identification:
  - Stable-named servers (remote-*, msgraph, slack-user, linear-server) match
    by the mcp__<server>__ prefix.
  - Slack and Linear also connect under unstable, install-specific server ids
    (e.g. GUID prefixes). Hardcoding those ids silently stops matching when the
    server reconnects, so they are ALSO identified by operation name
    (slack_* for Slack; specific tool names for Linear) regardless of prefix.
    The settings.json matcher is therefore broad (mcp__.*) and this hook is the
    source of truth for which calls warrant confirmation.

DECISION CONTRACT (ADVISORY ONLY — reverted 2026-07-31 at operator request)
  This hook prints a top-level advisory and exits 0:
      {"systemMessage": "<exact action + target>"}

  It does NOT return a permissionDecision. Per
  https://code.claude.com/docs/en/hooks a top-level systemMessage is only a
  WARNING shown to the user: it neither blocks the call nor prompts for
  confirmation. Under this host's `auto` default permission mode the call
  therefore proceeds on the classifier's own judgement.

  KNOWN CONSEQUENCE — this is the pre-2026-07-26 behaviour that audit finding H1
  measured as unenforceable: in the reviewed 14-day window all 24 recognized
  Slack/Linear writes received the warning and all 24 executed. The hook is a
  DETECTION and LOGGING surface, not a consent gate. Do not cite it as evidence
  that a human approved a specific write.

  History: PR #1727 changed this hook to `permissionDecision: "ask"` to make the
  security-confirmations rule enforceable. That was reverted on operator
  instruction (prompt friction in auto mode). If the consent gate is wanted
  again, restore `ask` — it is the only output shape that survives auto mode:
  "A hook's `ask` also forces a permission prompt in auto mode: the classifier
  can still deny the tool call, but it can't approve the call silently."

  Server-side OPA is unaffected and remains in force, but it is a DIFFERENT
  control — it gates AUTHORIZATION, not human CONSENT, and cannot establish that
  a human approved this specific target. With this revert, nothing does.

CLASSIFICATION (H6 + unclassifiable operations) — detection retained, gate removed
  * Generic wrapper envelopes (e.g. `mcp__msgraph__call_tool`, whose real
    operation rides in tool_input["name"]) are normalized to the INNER operation
    before classification. Classifying the outer name saw "call_tool", matched
    neither a read nor a write verb, and silently allowed.
  * A wrapper whose inner operation cannot be extracted WARNS (it previously
    asked; it no longer fails closed, because an advisory stops nothing).
  * An operation matching neither a known read verb nor a known write verb
    WARNS, with the same caveat.

Exit codes:
  0 = always (the decision, if any, is carried in stdout JSON, not the exit code)
"""

import json
import re
import sys

SLACK_WRITE_INDICATORS = [
    "send_message", "send", "add_message", "post",
    "update_message", "delete_message",
    "set_channel_topic", "set_channel_purpose",
    "add_reaction", "schedule_message", "create_canvas", "update_canvas",
]
# Tailscale: DNS/ACL/key/invite mutations affect the whole mesh VPN.
TAILSCALE_WRITE_INDICATORS = [
    "set_", "update_", "create_", "delete_", "accept_", "resend_",
    "revoke", "rotate", "authorize", "expire",
]
# Confluence (FedRAMP): page mutations.
CONFLUENCE_WRITE_INDICATORS = ["create", "update", "delete"]
# Lever sunset 2026-07-24 — LEVER_WRITE_INDICATORS + prefix entries removed org-wide.
# NetCloud (VendorRouter): account/router/group/config/alert-rule CRUD.
NETCLOUD_WRITE_INDICATORS = ["create_", "update_", "delete_", "reboot"]
# Ramp (hosted connector, unstable server id — matched by operation name,
# same pattern as Slack). Ramp-side financial mutations only; the local
# SQL-cache tools (load_*, clear_table, execute_query) are not Ramp writes.
RAMP_OP_PREFIX = "ramp_"
RAMP_WRITE_INDICATORS = [
    "edit_", "approve", "lock_or_unlock", "activate", "repayment",
    "match_user",
]
LINEAR_WRITE_INDICATORS = [
    "save_issue", "save_status_update", "save_comment", "save_project",
    "save_milestone", "save_customer", "save_customer_need", "save_initiative",
    "save_document",
    "create_issue_label", "create_attachment", "create_record_comment",
    "delete_attachment", "delete_comment", "delete_customer",
    "delete_customer_need", "delete_status_update",
    # legacy aliases:
    "create_issue", "update_issue",
]

# Stable-named security servers: matched by mcp__<server>__ prefix.
WRITE_PATTERNS = {
    "mcp__remote-crowdstrike__": [
        "assign", "close", "update", "create", "delete", "contain",
        "uncontain", "hide", "suppress", "add", "remove", "set",
        "block", "approve", "deny", "modify", "edit", "patch",
    ],
    "mcp__remote-airlock__": [
        "block", "approve", "deny", "add", "remove", "update",
        "create", "delete", "modify", "set",
    ],
    "mcp__remote-tenable__": [
        "launch", "create", "update", "delete", "modify",
        "scan", "schedule", "pause", "resume", "stop",
    ],
    "mcp__remote-msgraph__": [
        "mutate", "create", "update", "delete", "patch",
        "add", "remove", "set", "assign", "revoke",
    ],
    "mcp__msgraph__": [
        "mutate", "create", "update", "delete", "patch",
        "add", "remove", "set", "assign", "revoke",
    ],
    "mcp__slack-user__": SLACK_WRITE_INDICATORS,
    "mcp__linear-server__": LINEAR_WRITE_INDICATORS,
    # B12/F2 tier completion (2026-06-10): mutation surfaces verified from
    # mcp-servers source before adding (prowler was verified scan/read-only
    # and is deliberately absent). Indicators use underscore forms where a
    # bare verb could substring-match a read tool (lever's
    # get_archive_reasons vs archive_candidate).
    "mcp__remote-tailscale__": TAILSCALE_WRITE_INDICATORS,
    "mcp__tailscale__": TAILSCALE_WRITE_INDICATORS,
    "mcp__remote-confluence__": CONFLUENCE_WRITE_INDICATORS,
    "mcp__confluence__": CONFLUENCE_WRITE_INDICATORS,
    "mcp__netcloud__": NETCLOUD_WRITE_INDICATORS,
    # Provisioning writes (invite-to-workspace / provision skills): adding a
    # member to an M365 group, creating channels/spaces, linking IdP groups.
    "mcp__compliance-access-framework__": [
        "create", "invite", "link", "sync", "assign", "add",
        "register", "provision", "remove", "update",
    ],
}

PREFIX_LABELS = {
    "mcp__remote-crowdstrike__": "CrowdStrike",
    "mcp__remote-airlock__": "Airlock",
    "mcp__remote-tenable__": "Tenable",
    "mcp__remote-msgraph__": "MS Graph",
    "mcp__msgraph__": "MS Graph",
    "mcp__slack-user__": "Slack",
    "mcp__linear-server__": "Linear",
    "mcp__remote-tailscale__": "Tailscale",
    "mcp__tailscale__": "Tailscale",
    "mcp__remote-confluence__": "Confluence",
    "mcp__confluence__": "Confluence",
    "mcp__netcloud__": "NetCloud",
    "mcp__compliance-access-framework__": "Access Framework",
}

# Server-id-agnostic identification for Slack/Linear (which connect under
# install-specific ids). Slack tools are `slack_*`; Linear write tools have
# these specific names. Matched regardless of the mcp__<server>__ prefix so a
# reconnect under a new id can't silently bypass the confirmation gate.
SLACK_OP_PREFIX = "slack_"
LINEAR_WRITE_TOOLS = {
    "save_issue", "save_status_update", "save_comment", "save_project",
    "save_milestone", "save_customer", "save_customer_need", "save_initiative",
    "save_document", "create_issue_label", "create_attachment",
    "create_record_comment", "delete_attachment", "delete_comment",
    "delete_customer", "delete_customer_need", "delete_status_update",
}

# Read-only patterns — these always pass through even if they match a write prefix.
#
# TOKEN-ANCHORED, not raw substring (fixed 2026-07-26). The previous pattern was an
# unanchored substring match, so a read verb appearing INSIDE another word marked the
# whole operation read-only and allowed it silently. Concretely,
# `exfiltrate_widget` matched "get" inside "wid-get"; by the same mechanism
# `budget_set`, `target_delete` or `widget_purge` on a security server would have
# passed through unreviewed. Found while writing the unclassifiable-operation
# negative fixture for this remediation.
#
# Operation names are snake_case, so the verb is its own `_`-delimited token. `\b`
# alone is insufficient: `_` is a word character, so r"\bget\b" does NOT match
# "get_user" but DOES fail to exclude "widget". Anchor on start/end or an underscore.
_READ_VERBS = (
    "list", "get", "search", "query", "describe", "fetch", "read",
    "find", "count", "check", "status", "health", "ping",
)
READ_ONLY_PATTERNS = re.compile(
    r"(?:^|_)(" + "|".join(_READ_VERBS) + r")(?:_|$)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Generic wrapper envelopes (H6).
#
# Some security-sensitive servers expose a GENERIC outer tool and carry the real
# operation in the arguments -- e.g. `mcp__msgraph__call_tool` with the actual
# operation in tool_input["name"]. Classifying on the OUTER name alone sees
# "call_tool", finds neither a write verb nor a read verb, and silently allows.
# All 12 MS Graph calls in the reviewed window used this shape; the observed inner
# operations were reads, so this is demonstrated REACHABILITY, not an observed
# unauthorized write.
#
# Map: outer tool name -> (server label, write indicators, inner-name arg keys).
# --------------------------------------------------------------------------
WRAPPER_TOOLS = {
    "mcp__msgraph__call_tool": (
        "MS Graph",
        WRITE_PATTERNS["mcp__msgraph__"],
        ("name", "tool", "tool_name", "operation"),
    ),
    "mcp__remote-msgraph__call_tool": (
        "MS Graph",
        WRITE_PATTERNS["mcp__remote-msgraph__"],
        ("name", "tool", "tool_name", "operation"),
    ),
    "mcp__tenable__call_tool": (
        "Tenable",
        WRITE_PATTERNS["mcp__remote-tenable__"],
        ("name", "tool", "tool_name", "operation"),
    ),
    "mcp__airlock__call_tool": (
        "Airlock",
        WRITE_PATTERNS["mcp__remote-airlock__"],
        ("name", "tool", "tool_name", "operation"),
    ),
    "mcp__security-remix__execute_tool": (
        "Security Remix",
        sorted(
            set(WRITE_PATTERNS["mcp__remote-crowdstrike__"])
            | set(WRITE_PATTERNS["mcp__remote-airlock__"])
            | set(WRITE_PATTERNS["mcp__remote-tenable__"])
            | set(WRITE_PATTERNS["mcp__msgraph__"])
        ),
        ("name", "tool", "tool_name", "operation"),
    ),
}


def resolve_wrapper(tool_name, tool_input):
    """Normalize a generic wrapper envelope to its INNER operation.

    Returns (server_label, write_indicators, inner_operation, unresolved_flag).

    `unresolved_flag` is True when the outer tool is a known wrapper but the inner
    operation could not be extracted. For a security-sensitive server that must
    FAIL CLOSED (ask), not fall through to a silent allow: an unreadable envelope
    on a mutation-capable server is exactly the case we cannot reason about.
    """
    entry = WRAPPER_TOOLS.get(tool_name)
    if not entry:
        return None, None, None, False
    label, indicators, arg_keys = entry
    if not isinstance(tool_input, dict):
        return label, indicators, None, True
    for key in arg_keys:
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return label, indicators, val.strip(), False
    return label, indicators, None, True


def resolve_security_tool(tool_name):
    """Return (server_label, write_indicators, operation) for a security-
    sensitive MCP tool, else (None, None, None).

    Stable-named servers match by prefix. Slack/Linear match by operation name
    regardless of the (unstable) server id — split mcp__<server>__<operation>.
    """
    for prefix, indicators in WRITE_PATTERNS.items():
        if tool_name.startswith(prefix):
            return PREFIX_LABELS.get(prefix, prefix), indicators, tool_name[len(prefix):]
    parts = tool_name.split("__", 2)
    if len(parts) == 3 and parts[0] == "mcp":
        operation = parts[2]
        if operation.startswith(SLACK_OP_PREFIX):
            return "Slack", SLACK_WRITE_INDICATORS, operation
        if operation.startswith(RAMP_OP_PREFIX):
            return "Ramp", RAMP_WRITE_INDICATORS, operation
        if operation in LINEAR_WRITE_TOOLS:
            return "Linear", LINEAR_WRITE_INDICATORS, operation
    return None, None, None


def advisory_message(reason):
    """Build a top-level ADVISORY. Warns; does not gate.

    Per https://code.claude.com/docs/en/hooks a top-level `systemMessage` is a
    warning shown to the user. It does NOT block the call and does NOT prompt for
    confirmation, so under this host's `auto` default the tool call proceeds
    regardless of what this returns.

    This is deliberate as of 2026-07-31 (operator request). It is NOT the shape to
    use if a consent gate is wanted -- see the DECISION CONTRACT note at the top of
    this file and PR #1727 for the `ask` implementation this replaced.
    """
    return {"systemMessage": reason}


def _log(tool_name, operation, warned):
    try:
        from manifest_metrics import log_advisory_warning
        log_advisory_warning("security-write-confirm", tool_name, operation or "", warned=warned)
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if not tool_name:
        sys.exit(0)

    # Claude Code's PreToolUse hook input uses `tool_input` (the older `input`
    # key was used by some legacy hooks; that misnamed key caused this hook
    # to always render `Parameters: none` and silently no-op the rule's
    # "include the exact target" requirement). Fall back to `input` for any
    # caller still using the old name.
    tool_input = data.get("tool_input") or data.get("input") or {}

    # --- H6: normalize a generic wrapper envelope BEFORE classifying. -------
    # Classifying the OUTER name of `mcp__msgraph__call_tool` finds neither a
    # write nor a read verb and silently allows, while the real mutation rides in
    # tool_input["name"].
    wrap_label, wrap_indicators, inner_op, unresolved = resolve_wrapper(tool_name, tool_input)
    if wrap_label:
        if unresolved:
            # FAIL CLOSED. A mutation-capable security server with an envelope we
            # cannot read is precisely the case we cannot reason about, so it must
            # reach the user rather than default to allow.
            _log(tool_name, "<unresolved-inner-operation>", True)
            print(json.dumps(advisory_message(
                f"{wrap_label}: wrapper tool '{tool_name}' carries an inner operation "
                f"that could not be identified from its arguments. Confirm the exact "
                f"operation and target before it runs (failing closed on an "
                f"unreadable envelope for a security-sensitive server)."
            )))
            sys.exit(0)
        server_label, write_indicators, operation = wrap_label, wrap_indicators, inner_op
        rendered_tool = f"{tool_name} -> {inner_op}"
    else:
        server_label, write_indicators, operation = resolve_security_tool(tool_name)
        rendered_tool = tool_name

    if not server_label:
        sys.exit(0)  # Not a security server tool

    op_lower = (operation or "").lower()

    # Check write indicators FIRST. A tool whose name embeds a write verb
    # (save_status_update, delete_message, create_issue) is a write even if
    # its name also contains a substring that looks like a read verb
    # ("status" inside save_status_update would otherwise match the
    # READ_ONLY_PATTERNS "status" indicator and silently pass).
    is_write = any(indicator in op_lower for indicator in (write_indicators or ()))

    if is_write:
        # Fall through to the confirmation flow.
        pass
    elif READ_ONLY_PATTERNS.search(operation or ""):
        # Pure read with no write indicator — pass through silently.
        _log(tool_name, operation, False)
        sys.exit(0)
    else:
        # Neither a known write indicator nor a known read verb.
        # Historically this defaulted to a SILENT ALLOW, which meant any operation
        # the indicator lists did not anticipate executed unreviewed on a
        # security-sensitive server. An unclassifiable operation is now surfaced to
        # the user (ask) rather than allowed: on these servers the cost of an
        # unnecessary prompt is far below the cost of an unreviewed mutation.
        _log(tool_name, operation, True)
        print(json.dumps(advisory_message(
            f"{server_label}: operation '{operation}' on '{rendered_tool}' matches "
            f"neither a known read verb nor a known write verb, so its effect cannot "
            f"be classified. Confirm the exact action and target before it runs."
        )))
        sys.exit(0)

    # Render the exact target. Naming what will be written (not merely that a write
    # is about to happen) is the whole value of the advisory: with the consent gate
    # removed, the operator READING this line is the only wrong-target defense left.
    param_preview = ", ".join(
        f"{k}={json.dumps(v)[:60]}"
        for k, v in list(tool_input.items())[:3]
    ) if isinstance(tool_input, dict) else ""

    # The text must NOT claim approval is required. It is not: this hook is advisory
    # (2026-07-31) and the write proceeds regardless of what this says. An advisory
    # asserting a gate that does not exist is worse than silence — the operator reads
    # "requires explicit approval" and infers something is holding the call.
    reason = (
        f"SECURITY WRITE (advisory — NOT a gate): {server_label} write operation "
        f"'{operation}' via {rendered_tool}. Parameters: {param_preview or 'none'}. "
        f"This warning does not block or prompt; the write proceeds. Verify the "
        f"target above, and read the post-state back afterwards if it is destructive."
    )

    try:
        from manifest_metrics import increment_warning, log_advisory_warning
        log_advisory_warning("security-write-confirm", tool_name, operation or "", warned=True)
        increment_warning("security-write-confirm")
    except Exception:
        pass

    # ADVISORY ONLY (reverted 2026-07-31 on operator instruction).
    #
    # This prints a warning and exits 0. It does NOT prompt and does NOT block, so
    # under this host's `auto` default the write proceeds on the classifier's own
    # judgement. Audit finding H1 measured this exact shape as unenforceable: all
    # 24 recognized Slack/Linear writes in the reviewed window were warned and all
    # 24 executed.
    #
    # Treat the output of this hook as DETECTION + AUDIT LOG, never as proof of
    # human consent. The `ask` shape (PR #1727) is the only one that gates in auto
    # mode; restore it if a consent gate is wanted again.
    print(json.dumps(advisory_message(reason)))
    sys.exit(0)


if __name__ == "__main__":
    main()
