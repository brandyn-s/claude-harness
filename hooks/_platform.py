"""Shared OS detection for platform-conditional hooks + the platform-rules injector.

Claude Code has NO native OS-conditional loading (verified 2026-06-13 against
code.claude.com/docs: rules support only `paths:`; hooks/settings have no `os`
gate; no settings.<os>.json merge). So platform-specificity is implemented two
ways, both keyed off this single source of truth for the platform name:

  1. Rules: OS-specific rule files live in ~/.claude/platform-rules/<os>/ (NOT
     in the always-on ~/.claude/rules/ tree) and are injected at session start
     by session_start_modules/platform_rules.py for the active OS only.
  2. Hooks: a wholly platform-specific hook calls require_os(...) at the top to
     no-op on a non-matching platform.

Canonical platform names: macos | windows | linux | other.
"""
import platform
import sys

_SYSTEM_TO_NAME = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}


def current_os() -> str:
    """Return the canonical platform name for this host."""
    return _SYSTEM_TO_NAME.get(platform.system(), "other")


def require_os(*allowed: str) -> None:
    """Early-exit (exit 0, no-op) if the current OS is not in `allowed`.

    Call at the top of a wholly platform-specific hook so it fires ONLY on its
    target platform — e.g. `require_os("windows")` in a pwsh-only hook. exit 0
    means allow/pass-through, so a wrong-OS invocation leaves the tool call
    untouched. Do NOT use this for hooks that merely BRANCH per-OS (those run
    on every platform and choose a code path internally).
    """
    if current_os() not in allowed:
        sys.exit(0)
