"""SessionStart module: inject the active platform's rules as additionalContext.

Claude Code has no native OS-conditional rule loading (verified 2026-06-13 vs
code.claude.com/docs/en/memory.md — rules support only `paths:`). So OS-specific
rule content lives OUTSIDE the always-on ~/.claude/rules/ tree, in
~/.claude/platform-rules/<os>/, and this module injects ONLY the active
platform's files at session start. Cross-platform (common) rules stay in
~/.claude/rules/ and load natively on every host.

Result: on macOS you get common + macos rules; the windows/ and linux/ trees
are never loaded into context. The SAME repo deploys the right set per host.

Returns (additional_context, summary). Best-effort: any error returns
("", "") so a problem here can never break session start.
"""
import glob
import os
from pathlib import Path

# Single source of truth for OS detection: hooks/_platform.py. session-start.py
# puts the hooks/ dir on sys.path before importing this module, so the bare
# `_platform` import resolves. Defensive fallback keeps this module fail-open
# if it is ever imported without that path set up.
try:
    from _platform import current_os
except Exception:  # pragma: no cover - fallback when _platform isn't on sys.path
    import platform as _platform_mod

    def current_os():
        return {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(
            _platform_mod.system(), "other")


def load_platform_rules():
    """Concatenate the active-OS platform-rules files for SessionStart injection.

    Returns (additional_context_str, summary_str):
      - additional_context: header + concatenated <os> rule files, or "" if none
      - summary: a one-line banner note for the session-start systemMessage, or ""
    The dir is CLAUDE_PLATFORM_RULES_DIR-overridable for tests.
    """
    try:
        osname = current_os()
        base = Path(os.environ.get("CLAUDE_PLATFORM_RULES_DIR")
                    or (Path.home() / ".claude" / "platform-rules"))
        d = base / osname
        if not d.is_dir():
            return "", ""
        files = sorted(glob.glob(str(d / "*.md")))
        parts = []
        for f in files:
            try:
                parts.append(Path(f).read_text(encoding="utf-8"))
            except OSError:
                continue
        if not parts:
            return "", ""
        header = (
            f"# Platform-specific rules for this host ({osname}) — injected "
            f"conditionally at session start.\n"
            f"# Cross-platform rules are in ~/.claude/rules/. Rules for OTHER "
            f"platforms are intentionally NOT loaded (see "
            f"~/.claude/platform-rules/).\n\n"
        )
        summary = f"Platform rules: injected {len(parts)} {osname} file(s)."
        return header + "\n\n".join(parts), summary
    except Exception:
        return "", ""
