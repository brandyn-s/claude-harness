"""Smoke tests for security-write-confirm.py.

PreToolUse hook: emits a top-level {"systemMessage": ...} ADVISORY on MCP write
ops against security servers. Exit 0 always. Read-only tools pass through
silently (no output at all).

CONTRACT CHANGE 2026-07-31 (reverted on operator instruction): the hook returned
`permissionDecision: "ask"` between PR #1727 and this revert. It no longer emits
any permissionDecision, so it neither prompts nor blocks -- under this host's
`auto` default the write proceeds regardless.

WHAT THESE TESTS DO AND DO NOT COVER. They assert DETECTION: that a write against
a security server is correctly classified and surfaced with its server, operation
and target named. They deliberately do NOT assert consent, because the hook no
longer establishes it. Audit finding H1 measured this shape as unenforceable (all
24 recognized writes in the reviewed window warned and then executed), so a green
run here is evidence the hook SEES the write -- never evidence a human approved it.

`test_advisory_contract_emits_no_permission_decision` pins the revert so that
re-introducing `ask` is a deliberate act with a failing test, not a silent drift.
"""
import json

from conftest import run_hook

HOOK = "security-write-confirm.py"


def _payload(stdout):
    """Return the parsed hook payload, or None if the hook stayed silent."""
    if not stdout.strip():
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def _decision_reason(stdout):
    """The user-facing advisory text, or None when the call passed through.

    The assertions below check the same property they always have (the write was
    surfaced, with server + operation named); only the carrier field changed.
    """
    out = _payload(stdout)
    if not out:
        return None
    return out.get("systemMessage")


#: Back-compat alias so the body of every pre-existing test keeps working.
_systemmessage = _decision_reason


def _warns(stdout) -> bool:
    """True when the hook surfaced an advisory. NOT a consent gate -- see module docstring."""
    out = _payload(stdout)
    return bool(out) and bool(out.get("systemMessage"))


def test_non_security_tool_passes_through():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "Bash",
        "input": {"command": "ls"},
    })
    assert rc == 0
    assert not stdout.strip()


def test_crowdstrike_write_triggers_warning():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__contain_host",
        "input": {"host_id": "abc123"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg is not None
    assert "CrowdStrike" in msg
    assert "contain_host" in msg


def test_crowdstrike_list_is_read_only_no_warning():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__list_detections",
        "input": {},
    })
    assert rc == 0
    assert not stdout.strip()


def test_tenable_scan_write_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-tenable__launch_scan",
        "input": {"scan_id": 5},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Tenable" in msg


def test_airlock_block_write_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-airlock__block_application",
        "input": {"hash": "deadbeef"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Airlock" in msg


def test_msgraph_create_user_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-msgraph__create_user",
        "input": {"userPrincipalName": "u@x"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "MS Graph" in msg


def test_slack_send_message_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__slack-user__send_message",
        "input": {"channel": "C1", "text": "hi"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Slack" in msg


def test_graph_search_passes_through():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-msgraph__search_users",
        "input": {"query": "alice"},
    })
    assert rc == 0
    assert not stdout.strip()


def test_malformed_input_exits_cleanly():
    rc, _, _ = run_hook(HOOK, {})
    assert rc == 0


def test_missing_tool_name_exits_cleanly():
    rc, stdout, _ = run_hook(HOOK, {"tool_name": ""})
    assert rc == 0
    assert not stdout.strip()


def test_slack_guid_send_message_warns():
    """Current install registers Slack under a GUID prefix; hook must
    match it the same as the legacy mcp__slack-user__ prefix."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__036e0c74-1e0e-4bce-ad71-2a678d79b204__slack_send_message",
        "tool_input": {"channel_id": "C1", "text": "hi"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Slack" in msg
    assert "slack_send_message" in msg


def test_slack_guid_schedule_message_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__036e0c74-1e0e-4bce-ad71-2a678d79b204__slack_schedule_message",
        "tool_input": {"channel_id": "C1", "text": "later", "post_at": 1234},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Slack" in msg


def test_slack_guid_read_passes_through():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__036e0c74-1e0e-4bce-ad71-2a678d79b204__slack_read_channel",
        "tool_input": {"channel_id": "C1"},
    })
    assert rc == 0
    assert not stdout.strip()


def test_linear_guid_save_issue_warns():
    """Linear is now registered under a GUID prefix. save_issue creates
    or updates an issue — a write op that needs confirmation."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__save_issue",
        "tool_input": {"title": "incident X"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Linear" in msg


def test_linear_guid_save_status_update_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__save_status_update",
        "tool_input": {"projectId": "p1", "body": "shipped"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Linear" in msg


def test_linear_guid_read_passes_through():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__list_issues",
        "tool_input": {},
    })
    assert rc == 0
    assert not stdout.strip()


def test_linear_legacy_create_issue_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__linear-server__create_issue",
        "tool_input": {"title": "incident X"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Linear" in msg


def test_tool_input_key_renders_parameters():
    """Regression test: the hook reads `tool_input`, not the legacy `input`.
    With `tool_input` present, the systemMessage must show the params, not
    'Parameters: none'."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__contain_host",
        "tool_input": {"host_id": "abc123"},
    })
    msg = _systemmessage(stdout)
    assert msg
    assert "host_id" in msg
    assert "Parameters: none" not in msg


def test_legacy_input_key_still_renders():
    """Backwards-compat: callers using the old `input` key still work."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__contain_host",
        "input": {"host_id": "abc123"},
    })
    msg = _systemmessage(stdout)
    assert msg
    assert "host_id" in msg


def test_slack_write_under_NEW_guid_still_warns():
    """Server-id-agnostic: Slack reconnecting under a DIFFERENT id (not the
    previously-hardcoded one) must still be confirmed. This is the regression
    guard for the UUID-rot bug — detection keys on the slack_* operation."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__ffffffff-0000-1111-2222-333344445555__slack_send_message",
        "tool_input": {"channel_id": "C1", "text": "hi"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Slack" in msg


def test_linear_write_under_NEW_guid_still_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__ffffffff-0000-1111-2222-333344445555__save_status_update",
        "tool_input": {"projectId": "p1", "body": "shipped"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg and "Linear" in msg


def test_unknown_server_generic_create_passes_through():
    """A generic create_* on an unrelated server is NOT a Linear write — the
    agnostic Linear match keys on specific tool names, not bare verbs."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__ffffffff-0000-1111-2222-333344445555__create_widget",
        "tool_input": {"name": "w"},
    })
    assert rc == 0
    assert not stdout.strip()


# ── B12/F2 tier completion (2026-06-10): tailscale / confluence /
#    netcloud (stable prefixes) + ramp (hosted connector, op-name fallback).
#    Lever sunset 2026-07-24 — its two tests removed with the server.


def test_tailscale_set_dns_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-tailscale__set_dns_configuration",
        "input": {"nameservers": ["1.1.1.1"]},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg is not None and "Tailscale" in msg


def test_tailscale_list_devices_read_passes():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-tailscale__list_device_invites",
        "input": {},
    })
    assert rc == 0
    assert not stdout.strip()


def test_confluence_create_page_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-confluence__confluence_create_page",
        "input": {"space": "SEC"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg is not None and "Confluence" in msg




def test_netcloud_update_configuration_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__netcloud__update_configuration",
        "input": {"router_id": 42},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg is not None and "NetCloud" in msg


def test_ramp_guid_edit_transaction_warns():
    # Hosted connector under an install-specific server id — matched by the
    # ramp_ operation prefix, like the Slack/Linear GUID pattern.
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__a1b2c3d4__ramp_edit_transaction",
        "input": {"transaction_id": "t1"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg is not None and "Ramp" in msg


def test_ramp_guid_get_reimbursements_for_approval_read_passes():
    # "for_approval" must not substring-hit the "approve" indicator.
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__a1b2c3d4__ramp_get_reimbursements_for_approval",
        "input": {},
    })
    assert rc == 0
    assert not stdout.strip()


def test_ramp_local_cache_tools_pass():
    # load_*/clear_table/execute_query are local-SQL-cache ops, not Ramp
    # writes — they don't carry the ramp_ prefix and must pass through.
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__a1b2c3d4__clear_table",
        "input": {},
    })
    assert rc == 0
    assert not stdout.strip()


def test_compliance_access_framework_invite_warns():
    # invite-to-workspace adds a member to an M365 group via this server; the
    # skill manifest declares the security-write-confirm guardrail, so the hook
    # must actually fire for it (was a coverage gap before this case).
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__compliance-access-framework__invite_to_workspace",
        "input": {"workspace": "team-x", "upn": "security@example.com"},
    })
    assert rc == 0
    msg = _systemmessage(stdout)
    assert msg is not None
    assert "Access Framework" in msg
    assert "invite_to_workspace" in msg


def test_compliance_access_framework_read_no_warning():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__compliance-access-framework__get_workspace_status",
        "input": {"workspace": "team-x"},
    })
    assert rc == 0
    assert not stdout.strip()


# ══════════════════════════════════════════════════════════════════════════
# 2026-07-26 audit remediation. Negative fixtures for findings H1 and H6.
# ══════════════════════════════════════════════════════════════════════════


# ── ADVISORY CONTRACT (2026-07-31 revert of the H1 `ask` decision) ───────

def test_advisory_contract_emits_no_permission_decision():
    """PINS THE REVERT. The hook warns; it must not gate.

    This is the inverse of the former `test_write_returns_ask_decision_not_
    systemmessage`. It is retained (rather than deleted) so that restoring
    `permissionDecision` is a deliberate act that fails a named test, instead of
    drifting back in unnoticed.

    Read this test as documenting a KNOWN GAP, not a desired property: per audit
    finding H1 a top-level systemMessage neither blocks nor prompts, so every
    write asserted here proceeds unreviewed under the host's `auto` default.
    """
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__contain_host",
        "tool_input": {"host_id": "abc123"},
    })
    assert rc == 0
    payload = json.loads(stdout)
    assert "hookSpecificOutput" not in payload, (
        "the hook must not emit a permissionDecision while it is advisory-only"
    )
    assert payload["systemMessage"]
    assert "contain_host" in payload["systemMessage"]


def test_advisory_text_does_not_claim_approval_is_required():
    """The message must not assert a gate the hook does not implement.

    The 2026-07-31 revert changed the DECISION but initially left the message
    saying "this requires explicit approval of the exact action and target before
    execution" -- false, and in the single most-read place. An advisory that
    claims something is holding the call is worse than silence: the operator
    infers a gate exists and stops reading the target.

    Asserting on the hook's rendered OUTPUT (not a whole-file scan) is why this
    test can safely contain the forbidden phrases as literals.
    """
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__contain_host",
        "tool_input": {"host_id": "abc123"},
    })
    msg = json.loads(stdout)["systemMessage"]
    for forbidden in ("requires explicit approval",
                      "requires approval",
                      "before execution",
                      "awaiting confirmation"):
        assert forbidden not in msg, (
            f"advisory text claims a gate that does not exist: {forbidden!r}"
        )
    # And it must positively disclose that it does not gate.
    assert "does not block or prompt" in msg
    assert "advisory" in msg.lower()


def test_advisory_names_the_exact_target():
    """The rule requires naming WHAT will be written, not just that a write occurs."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__linear-server__save_status_update",
        "tool_input": {"projectId": "proj-42", "body": "shipped"},
    })
    reason = _decision_reason(stdout)
    assert reason
    assert "save_status_update" in reason
    assert "proj-42" in reason, "the exact target must be rendered for the user"


def test_read_only_still_returns_no_decision():
    """Reads must not acquire a prompt -- that would DoS ordinary work."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__list_detections",
        "tool_input": {},
    })
    assert rc == 0
    assert not stdout.strip()


# ── H6: generic wrapper envelopes hide the real operation ────────────────

def test_msgraph_wrapper_inner_write_is_caught():
    """THE H6 FIX. `call_tool` outer name + inner mutation must ASK.

    Previously the outer name matched neither a read nor a write verb, so the
    call was silently allowed while the mutation rode in tool_input["name"].
    """
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__msgraph__call_tool",
        "tool_input": {"name": "add_group_member",
                       "arguments": {"groupId": "g-1", "userId": "u-9"}},
    })
    assert rc == 0
    assert _warns(stdout), "inner write via wrapper must require confirmation"
    reason = _decision_reason(stdout)
    assert "add_group_member" in reason
    assert "MS Graph" in reason


def test_msgraph_wrapper_inner_read_passes_through():
    """A wrapper carrying a READ must not acquire a prompt."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__msgraph__call_tool",
        "tool_input": {"name": "list_users", "arguments": {}},
    })
    assert rc == 0
    assert not stdout.strip()


def test_msgraph_wrapper_unresolvable_inner_warns():
    """An envelope we cannot read must at least be SURFACED.

    Formerly `..._fails_closed`: it returned `ask`, so an unreadable envelope on a
    mutation-capable server could not proceed unreviewed. Post-revert it only
    warns, so it DOES proceed. Renamed rather than left asserting a closure
    property the hook no longer has.
    """
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__msgraph__call_tool",
        "tool_input": {"arguments": {"groupId": "g-1"}},  # no inner name
    })
    assert rc == 0
    assert _warns(stdout), "unresolved inner operation must still be surfaced"


def test_wrapper_with_non_dict_input_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__msgraph__call_tool",
        "tool_input": "not-a-dict",
    })
    assert rc == 0
    assert _warns(stdout)


def test_tenable_wrapper_inner_launch_scan_is_caught():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__tenable__call_tool",
        "tool_input": {"name": "launch_scan", "arguments": {"scan_id": 7}},
    })
    assert _warns(stdout)
    assert "launch_scan" in _decision_reason(stdout)


def test_security_remix_execute_tool_inner_write_is_caught():
    """security-remix proxies writes across CrowdStrike/Airlock/Tenable/Graph."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__security-remix__execute_tool",
        "tool_input": {"name": "contain_host", "arguments": {"host_id": "h-1"}},
    })
    assert _warns(stdout)


# ── unclassifiable operations must no longer default to silent allow ─────

def test_unclassifiable_operation_on_security_server_warns():
    """An op matching no known read OR write verb is surfaced, not silently dropped.

    It formerly ASKED (unreviewed mutation >> unnecessary prompt). Post-revert it
    warns only, so the unclassifiable op executes; the classification still fires
    and still reaches the audit log.
    """
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__remote-crowdstrike__exfiltrate_widget",
        "tool_input": {"target": "x"},
    })
    assert rc == 0
    assert _warns(stdout), "unclassifiable op on a security server must ask"


def test_read_verb_inside_another_word_is_not_treated_as_a_read():
    """PRE-EXISTING DEFECT found by this remediation, now fixed.

    READ_ONLY_PATTERNS was an unanchored substring regex, so a read verb appearing
    INSIDE another word marked the whole operation read-only and allowed it
    silently: `exfiltrate_widget` matched "get" inside "wid-get". By the same
    mechanism `budget_set`, `target_delete` and `widget_purge` on a security server
    would have passed through unreviewed. The verbs are now token-anchored.
    """
    for op in ("exfiltrate_widget", "budget_set", "target_delete", "widget_purge"):
        rc, stdout, _ = run_hook(HOOK, {
            "tool_name": f"mcp__remote-crowdstrike__{op}",
            "tool_input": {"target": "x"},
        })
        assert rc == 0
        assert stdout.strip(), f"{op} must not be silently allowed as a 'read'"


def test_genuine_read_verbs_still_pass_through():
    """The anchoring fix must not turn real reads into prompts."""
    for op in ("list_detections", "get_host_details", "search_hosts",
               "query_graph", "describe_scan", "count_org_devices"):
        rc, stdout, _ = run_hook(HOOK, {
            "tool_name": f"mcp__remote-crowdstrike__{op}",
            "tool_input": {},
        })
        assert rc == 0
        assert not stdout.strip(), f"{op} is a read and must stay silent"


def test_write_indicator_still_beats_a_read_token():
    """`save_status_update` contains the read token 'status' but is a WRITE.

    Write indicators are evaluated before read verbs; this pins that ordering.
    """
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__linear-server__save_status_update",
        "tool_input": {"projectId": "p-1"},
    })
    assert _warns(stdout), "a write whose name contains a read token must still ask"


def test_unclassifiable_op_on_NON_security_server_still_passes():
    """Fail-closed must NOT leak onto unrelated servers."""
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__ffffffff-0000-1111-2222-333344445555__frobnicate",
        "tool_input": {},
    })
    assert rc == 0
    assert not stdout.strip()


def test_malformed_json_still_exits_zero():
    """A broken payload must never wedge the tool call."""
    rc, stdout, _ = run_hook(HOOK, {})
    assert rc == 0
