"""PreToolUse:Write|Edit hook: hook self-protection.

Detects and blocks attempts to disable or remove hooks from settings.json.
Prevents rogue subagents or prompt injection from disabling security hooks
mid-session.

Selectively cloned from paceaitian/paceflow (2026-03-30).
Adapted from JavaScript to Python for Windows compatibility.

DEFENSE-IN-DEPTH: catches common cases (rm hooks/X, disableAllHooks=true),
not crafted bypasses (empty hooks {}, mv, cat /dev/null). Pair with
worktree isolation for adversary-grade protection.

Checks:
1. disableAllHooks=true → BLOCK (exit 2)
2. Removing hook entries from settings.json → WARN (stderr)
3. Removing hook .py files from hooks/ → WARN (stderr)
4. Empty hooks object {} → BLOCK (exit 2)
"""

import json
import os
import re
import sys

# The KEY/VALUE pair, not two independent substrings. The previous test was
# `"disableAllHooks" in content and "true" in content.lower()`, which fired on
# `"disableAllHooks": false` whenever any other key in the write was true --
# and `"enabled": true` is in nearly every settings.json (review 2026-09-03).
_DISABLE_ALL_HOOKS_RE = re.compile(r'"disableAllHooks"\s*:\s*true\b')

# Our registered hook filenames — protect these from deletion
PROTECTED_HOOKS = [
    "bash-security-guard.py",
    "post-write-edit.py",
    "session-start.py",
    "session-end.py",
    "config-guard.py",  # Self-protection
]

SETTINGS_FILENAMES = {"settings.json", "settings.local.json"}

# Empty-hooks object in any edit fragment (Edit/MultiEdit new_string), not just
# a full Write document: `"hooks": {}` would remove every registration.
_EMPTY_HOOKS_RE = re.compile(r'"hooks"\s*:\s*\{\s*\}')


def _extract_content(tool_name, tool_input):
    """All written/edited text for Write/Edit/MultiEdit, concatenated.

    MultiEdit nests its text under edits[].new_string, so a MultiEdit that
    disabled hooks (disableAllHooks=true) previously slipped the str-only
    Write/Edit reads and bypassed self-protection entirely.
    """
    if tool_name == "Write":
        return tool_input.get("content", "") or ""
    if tool_name == "Edit":
        return tool_input.get("new_string", "") or ""
    if tool_name == "MultiEdit":
        return "\n".join(
            e.get("new_string", "")
            for e in tool_input.get("edits", [])
            if isinstance(e, dict)
        )
    return ""


def check(hook_input):
    """Returns (exit_code, stderr_payload, stdout_payload)."""
    # Documented escape hatch: the disableAllHooks block message tells the
    # user to set SKIP_CONFIG_GUARD=1, so honor it here (it was advertised
    # but never read before the 2026-06-10 B2 review). An env var can't be
    # set by a prompt-injected Write/Edit, so this doesn't weaken the guard's
    # threat model (rogue subagent / injection editing settings.json).
    if os.environ.get("SKIP_CONFIG_GUARD") == "1":
        return (0, None, None)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    if tool_name not in ("Write", "Edit", "MultiEdit", "Bash"):
        return (0, None, None)

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for hook_name in PROTECTED_HOOKS:
            if hook_name in command and ("rm " in command or "del " in command):
                msg = (
                    f"[config-guard] BLOCKED: Attempt to delete protected hook {hook_name}. "
                    f"Hook deletion requires explicit user approval."
                )
                return (2, msg, None)
        return (0, None, None)

    file_path = tool_input.get("file_path", "")
    filename = os.path.basename(file_path)
    if filename not in SETTINGS_FILENAMES:
        return (0, None, None)

    content = _extract_content(tool_name, tool_input)
    if not content:
        return (0, None, None)

    if _DISABLE_ALL_HOOKS_RE.search(content):
        msg = (
            "[config-guard] BLOCKED: Detected disableAllHooks=true in settings edit. "
            "This would disable ALL security hooks including bash-security-guard, "
            "post-write-edit, and config-guard itself. If intentional, set "
            "SKIP_CONFIG_GUARD=1 in environment."
        )
        return (2, msg, None)

    # Empty hooks object — checked for any tool. For a full Write document we
    # can parse it; for Edit/MultiEdit fragments a regex catches `"hooks": {}`.
    empty_hooks = bool(_EMPTY_HOOKS_RE.search(content))
    if not empty_hooks and tool_name == "Write" and '"hooks"' in content:
        try:
            parsed = json.loads(content)
            hooks_val = parsed.get("hooks", None)
            empty_hooks = isinstance(hooks_val, dict) and len(hooks_val) == 0
        except (json.JSONDecodeError, Exception):
            pass
    if empty_hooks:
        msg = (
            "[config-guard] BLOCKED: Detected empty hooks object in settings edit. "
            "This would remove ALL hook registrations."
        )
        return (2, msg, None)

    for hook_name in PROTECTED_HOOKS:
        hook_stem = hook_name.replace(".py", "")
        if hook_stem in content and any(kw in content.lower() for kw in ["remove", "delete", "null"]):
            msg = (
                f"[config-guard] WARNING: Edit to {filename} may remove "
                f"protected hook {hook_name}. Verify this is intentional."
            )
            return (0, msg, None)

    return (0, None, None)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)
    try:
        code, stderr_msg, stdout_msg = check(hook_input)
    except Exception as exc:  # noqa: BLE001
        # FAIL-CLOSED. Wired directly (the fresh-laptop profile) there is no
        # write-edit-dispatcher wrapper to enforce the "closed" posture, and an
        # uncaught exception exits 1 -- a NON-blocking error in Claude Code -- so
        # a crashed self-protection guard silently permitted the settings edit.
        sys.stderr.write(
            f"[config-guard] BLOCKED: hook crashed ({exc.__class__.__name__}: {exc}). "
            "A self-protection guard that cannot run must not approve the edit; "
            "set SKIP_CONFIG_GUARD=1 to bypass deliberately.\n"
        )
        sys.exit(2)
    if stderr_msg:
        sys.stderr.write(stderr_msg + "\n")
    if stdout_msg:
        print(stdout_msg)
    sys.exit(code)


if __name__ == "__main__":
    main()
