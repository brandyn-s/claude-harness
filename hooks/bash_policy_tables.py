"""Directly sourced optional policy tables for ``bash-security-guard.py``.

The guard remains one hook process. These tables only select existing checks;
there is no generated runtime artifact and no second dispatcher.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

PACK_ORDER = ("delivery", "portability", "workflow")

POLICY_PACKS: dict[str, dict[str, tuple[str, ...]]] = {
    "delivery": {
        "block": (
            "check_forbidden_org",
            "check_commit_on_main",
            "check_admin_merge",
            "check_push_guard",
            "check_pr_before_push",
            "check_push_after_auto_merge",
        ),
        "autofix": (
            "_autofix_fork_pr_routing",
            "_autofix_pr_head_flag",
            "_autofix_rebase_dirty",
        ),
        "advisory": (
            "warn_forbidden_org_indirection",
            "warn_stale_branch_base",
        ),
        "observer": ("check_pr_security",),
    },
    "portability": {
        "block": (
            "check_heredoc_python_encoding",
            "check_inline_python_encoding",
        ),
        "autofix": (
            "_autofix_msys_python_path",
            "_autofix_double_prefix_general",
            "_autofix_msys_pathconv",
            "_autofix_python_interpreter",
        ),
    },
    "workflow": {
        "block": ("check_long_foreground_sleep",),
        "handler": ("handle_inline_python_oversize",),
        "autofix": ("_autofix_aws_profile",),
        "advisory": ("check_settings_json_staged",),
    },
}

# Preference-shaped command policies that formerly lived in the catastrophic
# pattern list. Each row is executable source with a stable ID and rationale.
PATTERN_BLOCKS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "workflow": (
        (
            "pre-release-package",
            r"pip\s+install\s+.*--pre\b",
            "pip install --pre installs pre-release packages. Ask the user for approval.",
        ),
        (
            "interactive-winget",
            r"winget\s+(install|upgrade|uninstall)",
            "winget waits for consent in non-interactive shells. Run it in a user terminal.",
        ),
    ),
}


def resolve_policy_packs(raw: str | None) -> tuple[str, ...]:
    """Resolve ``CLAUDE_BASH_POLICY_PACKS`` without implicit defaults."""
    value = (raw or "").strip()
    if not value:
        return ()
    requested = {item.strip() for item in value.split(",") if item.strip()}
    if requested == {"all"}:
        return PACK_ORDER
    unknown = requested.difference(PACK_ORDER)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown optional policy pack: {names}")
    return tuple(pack for pack in PACK_ORDER if pack in requested)


def entries(enabled: Iterable[str], stage: str) -> tuple[str, ...]:
    selected = set(enabled)
    return tuple(
        name
        for pack in PACK_ORDER
        if pack in selected
        for name in POLICY_PACKS[pack].get(stage, ())
    )


def pattern_block_reason(command: str, enabled: Iterable[str]) -> str | None:
    selected = set(enabled)
    for pack in PACK_ORDER:
        if pack not in selected:
            continue
        for policy_id, pattern, reason in PATTERN_BLOCKS.get(pack, ()):
            if re.search(pattern, command, re.IGNORECASE):
                return f"[{policy_id}] BLOCKED: {reason}"
    return None
