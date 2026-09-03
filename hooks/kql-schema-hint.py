"""KQL schema-hint hook for Defender Advanced Hunting queries (RC1).

Fires as PreToolUse on `mcp__remote-msgraph__call_tool` when the called
tool is `msgraph_run_hunting_query`. Detects queries that reference
specific columns via `| project col1, col2, ...` WITHOUT a corresponding
`| getschema` call earlier in the session for the same table.

Behavior: emits a soft `additionalContext` hint to the model (NOT a block). Does not prevent
the query — just nudges the model toward running `<Table> | getschema`
first when uncertain about column names.

Background (2026-05-28 retro RC1): a session burned 3 wrong-from-memory
KQL column names (`RiskScore`, `RiskLevel`, `CvssScore`) before running
`getschema`. The convention is documented in agent-memory/topics/msgraph.md
"Defender Advanced Hunting" subsection but ambient text under
conversational pressure isn't reliably applied. This hook is enforcement.

Design choices:
- Soft hint, not a block. Many legitimate queries reference well-known
  columns (Timestamp, DeviceName, DeviceId) without needing a getschema.
  Blocking would create more friction than it prevents.
- Session-scoped memory of which tables have been getschema'd. Reads the
  transcript JSONL to find prior `| getschema` invocations.
- Conservative regex match — only fires on explicit `| project` that
  references multiple comma-separated identifiers. Single-column
  `| project Foo` or `| where ...` queries are typically safe.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# Tables for which getschema-first is high-value. Defender hunting has
# schemas that change between tenants and over time; for these, a wrong
# column guess is the documented failure mode from 2026-05-28.
WATCHED_TABLES = (
    "DeviceInfo",
    "DeviceTvmSoftwareVulnerabilities",
    "DeviceTvmSecureConfigurationAssessment",
    "DeviceTvmSecureConfigurationAssessmentKB",
    "DeviceTvmInfoGathering",
    "AlertInfo",
    "AlertEvidence",
    "DeviceProcessEvents",
    "DeviceNetworkEvents",
    "DeviceFileEvents",
    "DeviceLogonEvents",
    "DeviceImageLoadEvents",
    "DeviceRegistryEvents",
    "EmailEvents",
    "EmailAttachmentInfo",
    "EmailUrlInfo",
    "IdentityLogonEvents",
    "IdentityDirectoryEvents",
    "IdentityQueryEvents",
    "CloudAppEvents",
)


def _extract_query(arguments):
    """Pull the KQL query string from the tool arguments dict."""
    if not isinstance(arguments, dict):
        return ""
    q = arguments.get("query")
    if isinstance(q, str):
        return q
    return ""


def _query_references_table(query, table):
    """True if the query references `table` as its source table."""
    # Match the table name at the start of the query or after a pipe
    pattern = re.compile(rf"(?:^|\|)\s*{re.escape(table)}\b", re.IGNORECASE)
    return bool(pattern.search(query))


def _query_has_explicit_project(query):
    """True if the query has `| project col1, col2, ...` with multiple columns.

    A single-column project (`| project DeviceName`) is typically a safe
    well-known reference; the high-risk pattern is multi-column projects
    where forgotten columns silently fail.
    """
    # Match: pipe, optional whitespace, "project", whitespace, one or more
    # identifiers separated by commas
    match = re.search(
        r"\|\s*project\s+([A-Za-z_][\w]*(?:\s*=\s*[^,|\r\n]+)?(?:\s*,\s*[A-Za-z_][\w]*(?:\s*=\s*[^,|\r\n]+)?)+)",
        query,
        re.IGNORECASE,
    )
    return bool(match)


def _scan_transcript_for_getschema(transcript_path, table):
    """Look in the session transcript JSONL for prior `<table> | getschema` calls."""
    if not transcript_path:
        return False
    try:
        text = Path(transcript_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    # Cheap substring scan — false positives here are fine (better to
    # under-warn than to spam). Look for "<Table>" near "getschema" within
    # the same line.
    needle = re.compile(
        rf"{re.escape(table)}[^\n]*?\|\s*getschema",
        re.IGNORECASE,
    )
    return bool(needle.search(text))


def main():
    try:
        if sys.stdin and not sys.stdin.closed:
            hook_input = json.load(sys.stdin)
        else:
            hook_input = {}
    except Exception:
        hook_input = {}

    tool_input = hook_input.get("tool_input") or {}
    tool_name = tool_input.get("name")
    # Only fire on the hunting-query tool
    if tool_name != "msgraph_run_hunting_query":
        return  # a pass emits nothing

    query = _extract_query(tool_input.get("arguments") or {})
    if not query or not _query_has_explicit_project(query):
        # Either no query, or no multi-column project — safe to pass through
        return  # a pass emits nothing

    transcript_path = hook_input.get("transcript_path")

    unverified_tables = []
    for table in WATCHED_TABLES:
        if not _query_references_table(query, table):
            continue
        if _scan_transcript_for_getschema(transcript_path, table):
            continue
        unverified_tables.append(table)

    if not unverified_tables:
        return  # a pass emits nothing

    table_list = ", ".join(unverified_tables[:3])
    hint = (
        f"[kql-schema-hint] Query projects columns from {table_list} "
        f"but no `{unverified_tables[0]} | getschema` call appears earlier in "
        f"this session. If column names aren't certain, prefer "
        f"`{unverified_tables[0]} | getschema | project ColumnName, ColumnType` "
        f"first — Defender hunting schemas drift between tenants and over time. "
        f"Background: rules/incidents/verify-effectiveness.md (2026-05-28 RC1)."
    )
    # additionalContext is the documented model-facing PreToolUse channel; the
    # former top-level systemMessage only reached the user (probed 2026-09-03).
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "additionalContext": hint}}))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Crash-safe: pass through silently on any internal error
        sys.exit(0)
