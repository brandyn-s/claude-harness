"""PreToolUse:Bash|PowerShell destructive-ops guard.

Blocks the specific destructive patterns the assistant has historically
misfired on (per insights report 2026-04-29 → 2026-05-23):

  - `rm -rf` / `Remove-Item -Recurse -Force` of data/index/manifest paths
    (the freshly-rebuilt voyage-index deletion incident)
  - `kill` / `pkill` / `taskkill` / `Stop-Process` targeting MCP server
    processes (the fts5.db-lock session-break incident)
  - `reg delete` / `Remove-Item` on Windows registry hives (the wrong-hive
    HKCU/HKLM rename incidents)

Matches both the Bash and PowerShell tools. Most of these patterns are
valid in either shell, and the report's Windows-registry / MCP-kill work
gets routed through whichever shell tool is enabled, depending on the
state of CLAUDE_CODE_USE_POWERSHELL_TOOL and Git Bash presence.

Bypass paths (when the action is actually intended):
  - Include the literal token `# confirmed-destructive` in the command
  - Or set CLAUDE_DESTRUCTIVE_CONFIRM=1 in the session environment

Exit codes:
  2 = block with stderr reason
  0 = allow (passthrough)
"""

import json
import os
import re
import sys

try:
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

CONFIRM_ENV = "CLAUDE_DESTRUCTIVE_CONFIRM"
CONFIRM_TOKEN = "# confirmed-destructive"

# Strip quoted strings and heredoc bodies so commit messages or doc text
# mentioning these patterns don't false-positive.
_QUOTED_RE = re.compile(r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
_HEREDOC_RE = re.compile(r"<<\s*'?(\w+)'?.*?\n.*?\1", re.DOTALL)


def _strip_literals(s):
    s = _HEREDOC_RE.sub("", s)
    s = _QUOTED_RE.sub("", s)
    return s


# Data/index path tokens that past sessions treated as "stale/corrupt" and
# removed by mistake. Tuned to the actual incidents in the insights report:
#   - voyage indexes deleted as if they were corrupt manifest entries
#   - fts5.db lock that nearly got "resolved" by deleting the database
DATA_PATH_TOKENS = re.compile(
    r"voyage"
    r"|fts5"
    r"|\bindex(?:es|ing|ed)?\b"
    r"|\.db\b"
    r"|\bmanifest(?:s)?\b"
    r"|code[-_]graph[-_]data"
    r"|mcp[-_]data",
    re.IGNORECASE,
)

# `rm` with recursive+force in any flag arrangement.
RM_RF = re.compile(
    r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r"
    r"|--recursive\s+--force|--force\s+--recursive)\b",
    re.IGNORECASE,
)

# PowerShell `Remove-Item` flag detection (order-independent).
REMOVE_ITEM = re.compile(r"\bRemove-Item\b", re.IGNORECASE)
RECURSE_FLAG = re.compile(r"(?:-Recurse\b|\s-r\b)", re.IGNORECASE)
FORCE_FLAG = re.compile(r"(?:-Force\b|\s-f\b)", re.IGNORECASE)


def _has_destructive_remove_flags(cleaned):
    if RM_RF.search(cleaned):
        return True
    if (
        REMOVE_ITEM.search(cleaned)
        and RECURSE_FLAG.search(cleaned)
        and FORCE_FLAG.search(cleaned)
    ):
        return True
    return False


# MCP/server-process kill patterns.
MCP_PROCESS_TOKENS = r"mcp|fastmcp|code[-_]search|code[-_]graph|memory[-_]search|tavily"

KILL_BASH = re.compile(
    r"\b(?:kill|pkill|killall)\b[^|;&]*?\b(?:" + MCP_PROCESS_TOKENS + r")\b",
    re.IGNORECASE,
)
KILL_TASKKILL = re.compile(
    r"\btaskkill(?:\.exe)?\b[^|;&]*?\b(?:" + MCP_PROCESS_TOKENS + r"|node|python|pwsh|powershell)\b",
    re.IGNORECASE,
)
KILL_STOP_PROCESS = re.compile(
    r"\bStop-Process\b[^|;&]*?(?:-Name|-Id)[^|;&]*?\b(?:"
    + MCP_PROCESS_TOKENS
    + r"|node|python|pwsh|powershell)\b",
    re.IGNORECASE,
)

# Windows registry deletion.
REG_DELETE = re.compile(r"\breg(?:\.exe)?\s+delete\b", re.IGNORECASE)
REGISTRY_REMOVE_ITEM = re.compile(
    r"\bRemove-Item\b[^|;&]*?\bHK[CL][MU]:",
    re.IGNORECASE,
)
REGISTRY_REMOVE_PROPERTY = re.compile(
    r"\bRemove-ItemProperty\b[^|;&]*?\bHK[CL][MU]:",
    re.IGNORECASE,
)


def check(command):
    """Return a reason string if the command should be blocked, else None."""
    cleaned = _strip_literals(command)

    if _has_destructive_remove_flags(cleaned) and DATA_PATH_TOKENS.search(cleaned):
        return (
            "rm/Remove-Item recursively targets a data/index/database/manifest "
            "path. Past sessions deleted freshly-rebuilt voyage indexes thinking "
            "they were corrupt manifest entries. Run `ls -la` on the target and "
            "confirm with the user before deleting."
        )

    if KILL_BASH.search(cleaned):
        return (
            "kill/pkill targeting an MCP-related process. Past sessions broke "
            "retrieval mid-task by killing the wrong PID. Ask the user before "
            "stopping an MCP server."
        )
    if KILL_TASKKILL.search(cleaned):
        return (
            "taskkill targeting MCP/Node/Python/PowerShell — high risk of "
            "killing an active MCP server. Ask the user first."
        )
    if KILL_STOP_PROCESS.search(cleaned):
        return (
            "Stop-Process targeting MCP/Node/Python/PowerShell — high risk of "
            "killing an active MCP server. Ask the user first."
        )

    if REG_DELETE.search(cleaned):
        return (
            "`reg delete` modifies the Windows registry. Past sessions hit "
            "wrong-hive issues (HKCU vs HKLM). Confirm the hive and key with "
            "the user before running."
        )
    if REGISTRY_REMOVE_ITEM.search(cleaned):
        return (
            "Remove-Item on a registry hive (HKLM:/HKCU:). Confirm hive and "
            "policy key with the user before running."
        )
    if REGISTRY_REMOVE_PROPERTY.search(cleaned):
        return (
            "Remove-ItemProperty on a registry hive (HKLM:/HKCU:). Confirm hive "
            "and policy value with the user before running."
        )

    return None


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Bash", "PowerShell"):
        return 0

    command = (data.get("tool_input") or {}).get("command", "") or ""
    if not command:
        return 0

    if os.environ.get(CONFIRM_ENV) == "1":
        return 0
    if CONFIRM_TOKEN in command:
        return 0

    reason = check(command)
    if reason is None:
        return 0

    print(
        f"[destructive-ops-guard] BLOCKED ({tool_name}): {reason} "
        f"If this is genuinely intended, append the comment "
        f"`{CONFIRM_TOKEN}` to the command, or set {CONFIRM_ENV}=1 "
        f"for the session.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        # Deliberate, visible fail mode. Previously an unexpected exception
        # in check() propagated as a bare traceback + exit 1 — which lets the
        # command proceed anyway (only exit 2 blocks) but silently/ugly. Fail
        # OPEN but LOUD: surface the crash so it's noticed, don't block (a
        # guard bug shouldn't brick all Bash). Whether a data-loss gate should
        # instead fail CLOSED is the open posture question in the B2 report.
        print(
            f"[destructive-ops-guard] WARNING: guard crashed "
            f"({e.__class__.__name__}: {e}); command allowed unchecked.",
            file=sys.stderr,
        )
        sys.exit(0)
