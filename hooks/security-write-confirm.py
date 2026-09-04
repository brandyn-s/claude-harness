"""PreToolUse hook: surface MCP write operations against security-sensitive servers.

Enforces the security-confirmations rule by detecting MCP write tool calls to
the servers the ENVIRONMENT CATALOG lists as security-sensitive (an EDR, a
vulnerability scanner, a directory service, chat, ticketing, network gear:
whatever the operator names in the `security_write_confirm` section of
contracts/environment-catalog.json / ~/.claude/environment-catalog.json, loaded
through hooks/_environment_catalog.py) and injecting an advisory. The hook
itself names no server: with an empty section every call passes through.

Detects writes by matching operation names against each server's write
indicators. Read-only tools (list, get, search, query, describe) pass through
without an advisory.

Server identification (all three shapes come from the catalog):
  - `servers`: stable-named servers match by the mcp__<server>__ prefix and
    carry a label plus a write-indicator list.
  - `operation_rules`: hosted connectors that connect under unstable,
    install-specific server ids (e.g. GUID prefixes). Hardcoding those ids
    silently stops matching when the server reconnects, so they are identified
    by OPERATION NAME (an `op_prefix` such as `chat_`, or explicit `op_names`)
    regardless of prefix. The settings.json matcher is therefore broad
    (mcp__.*) and this hook is the source of truth for which calls warrant an
    advisory.
  - `wrapper_tools`: generic envelopes (`mcp__<server>__call_tool`) whose real
    operation rides in tool_input["name"]; classified on the INNER operation.
  A rule may spell out `write_indicators` or borrow them from listed servers
  with `write_indicators_from`.

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
  chat/tracker writes received the warning and all 24 executed. The hook is a
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
  * Generic wrapper envelopes (e.g. `mcp__<server>__call_tool`, whose real
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
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _environment_catalog import load_section

# Where a wrapper envelope carries its inner operation name, unless the catalog
# entry says otherwise.
DEFAULT_INNER_OP_KEYS = ("name", "tool", "tool_name", "operation")


def _indicators(spec, servers):
    """A rule's write indicators: its own list plus those of any servers it
    borrows from (`write_indicators_from`), de-duplicated in order."""
    raw = list(spec.get("write_indicators") or [])
    for prefix in spec.get("write_indicators_from") or []:
        raw.extend((servers.get(prefix) or {}).get("write_indicators") or [])
    seen, out = set(), []
    for indicator in raw:
        if isinstance(indicator, str) and indicator and indicator not in seen:
            seen.add(indicator)
            out.append(indicator)
    return out


def load_rules(section=None):
    """Build the classification tables from the catalog's `security_write_confirm`.

    Returns (write_patterns, prefix_labels, operation_rules, wrapper_tools):
      write_patterns  {mcp__<server>__: [indicators]}   stable-named servers
      prefix_labels   {mcp__<server>__: label}
      operation_rules [{label, op_prefix, op_names, indicators}]  in catalog order
      wrapper_tools   {outer tool name: (label, [indicators], inner-op arg keys)}
    Malformed entries are skipped; an empty section yields empty tables.
    """
    if section is None:
        section = load_section("security_write_confirm")
    servers = {
        prefix: spec for prefix, spec in (section.get("servers") or {}).items()
        if isinstance(spec, dict)
    }
    write_patterns, labels = {}, {}
    for prefix, spec in servers.items():
        write_patterns[prefix] = _indicators(spec, servers)
        labels[prefix] = str(spec.get("label") or prefix)
    operation_rules = []
    for spec in section.get("operation_rules") or []:
        if not isinstance(spec, dict):
            continue
        operation_rules.append({
            "label": str(spec.get("label") or "MCP server"),
            "op_prefix": str(spec.get("op_prefix") or ""),
            "op_names": {n for n in (spec.get("op_names") or []) if isinstance(n, str)},
            "indicators": _indicators(spec, servers),
        })
    wrapper_tools = {}
    for tool, spec in (section.get("wrapper_tools") or {}).items():
        if not isinstance(spec, dict):
            continue
        keys = tuple(k for k in (spec.get("inner_op_keys") or []) if isinstance(k, str))
        wrapper_tools[tool] = (
            str(spec.get("label") or tool),
            _indicators(spec, servers),
            keys or DEFAULT_INNER_OP_KEYS,
        )
    return write_patterns, labels, operation_rules, wrapper_tools


# Stable-named security servers: matched by mcp__<server>__ prefix.
WRITE_PATTERNS, PREFIX_LABELS, OPERATION_RULES, WRAPPER_TOOLS = load_rules()

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
# operation in the arguments -- e.g. `mcp__<server>__call_tool` with the actual
# operation in tool_input["name"]. Classifying on the OUTER name alone sees
# "call_tool", finds neither a write verb nor a read verb, and silently allows.
# All 12 directory-server calls in the reviewed window used this shape; the
# observed inner operations were reads, so this is demonstrated REACHABILITY,
# not an observed unauthorized write.
#
# WRAPPER_TOOLS: outer tool name -> (server label, write indicators, inner-name arg keys).
# --------------------------------------------------------------------------


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

    Stable-named servers match by prefix. Operation rules match by operation
    name regardless of the (unstable) server id — split mcp__<server>__<operation>.
    """
    for prefix, indicators in WRITE_PATTERNS.items():
        if tool_name.startswith(prefix):
            return PREFIX_LABELS.get(prefix, prefix), indicators, tool_name[len(prefix):]
    parts = tool_name.split("__", 2)
    if len(parts) == 3 and parts[0] == "mcp":
        operation = parts[2]
        for rule in OPERATION_RULES:
            if (rule["op_prefix"] and operation.startswith(rule["op_prefix"])) \
                    or operation in rule["op_names"]:
                return rule["label"], rule["indicators"], operation
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
    except Exception:  # noqa: S110, BLE001 -- fail-open: telemetry must never break the advisory
        pass  # fail-open: telemetry only


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
    # Classifying the OUTER name of `mcp__<server>__call_tool` finds neither a
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
        _sid = data.get("session_id") or None
        log_advisory_warning("security-write-confirm", tool_name, operation or "", warned=True,
                             session_id=_sid)
        increment_warning("security-write-confirm", session_id=_sid)
    except Exception:  # noqa: S110, BLE001 -- fail-open: telemetry must never break the advisory
        pass  # fail-open: telemetry only

    # ADVISORY ONLY (reverted 2026-07-31 on operator instruction).
    #
    # This prints a warning and exits 0. It does NOT prompt and does NOT block, so
    # under this host's `auto` default the write proceeds on the classifier's own
    # judgement. Audit finding H1 measured this exact shape as unenforceable: all
    # 24 recognized chat/tracker writes in the reviewed window were warned and all
    # 24 executed.
    #
    # Treat the output of this hook as DETECTION + AUDIT LOG, never as proof of
    # human consent. The `ask` shape (PR #1727) is the only one that gates in auto
    # mode; restore it if a consent gate is wanted again.
    print(json.dumps(advisory_message(reason)))
    sys.exit(0)


if __name__ == "__main__":
    main()
