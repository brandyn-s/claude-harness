#!/usr/bin/env python3
"""home-scratch-guard: warn on files written directly to the home root.

PreToolUse guard (Write|Edit), wired into write-edit-dispatcher.py. Fires
when a Write/Edit targets a NON-dotfile whose parent directory is exactly
$HOME — the pattern that accumulates scratch scripts, run logs, and report
.md files in the home directory instead of /tmp/claude (scratch) or a repo
(deliverables).

Warn-only (exit 0 + additionalContext). NOT a block: occasionally a file
genuinely belongs in the home root (e.g. a helper script the user must run
by hand), and a hard block would fight that. The warning nudges toward the
right location; the model proceeds if it has a reason. Posture in the
dispatcher GUARDS list is therefore "open".

Scope limit: catches files written DIRECTLY to $HOME. It does NOT catch a
file written into a freshly-created home-root SUBDIR (~/newdir/file) — the
parent there is the subdir, not $HOME — because distinguishing a stray
subdir from a legitimate clone/project (code/, go/, worktrees/, PSM/, ...)
would over-fire on the many valid home subdirs.

Origin: 2026-06-14 home-directory hygiene audit found a cluster of AWS
security reports, a paycom doc, sandbox helper scripts, and install logs
sitting in the home root across several prior sessions. The hook layer had
strong guards on the destructive path (deletion) and security, but nothing
enforced scratch/deliverable LOCATION; this guard fills that gap.

INTERRUPTION: safe — read-only classification of one path string; no file,
DB, git, or network state is touched.
"""

import json
import os
import sys
from pathlib import Path

# Extensions whose presence directly in $HOME almost always means a
# misplaced scratch artifact or deliverable. The explicit set means a rare
# legitimate home-root file without one of these suffixes (Brewfile,
# Makefile) does not nag.
SCRATCH_SUFFIXES = {
    ".py", ".log", ".md", ".json", ".yaml", ".yml",
    ".txt", ".sh", ".csv", ".tsv", ".ipynb", ".html", ".js",
}


def _target_path(tool_input):
    """Absolute Path of the write target, or None if not determinable.

    The Write/Edit tools require absolute paths, so a non-absolute value
    cannot be reliably resolved here (the hook's cwd need not match the
    session cwd) and is treated as "cannot classify" -> allow.
    """
    fp = tool_input.get("file_path", "")
    if not fp:
        return None
    p = Path(os.path.normpath(os.path.expanduser(fp)))
    return p if p.is_absolute() else None


def check(hook_input):
    """Returns (exit_code, stderr_payload, stdout_payload).

    Warn-only: always exit 0. Surfaces a nudge via additionalContext when a
    non-dotfile with a scratch-like suffix is written directly to $HOME.
    """
    tool_input = hook_input.get("tool_input", {})
    p = _target_path(tool_input)
    if p is None:
        return (0, None, None)

    # Only files DIRECTLY in $HOME, never dotfiles (.zshrc, .gitconfig, ...),
    # and only scratch-like suffixes.
    if p.parent != Path.home():
        return (0, None, None)
    if p.name.startswith("."):
        return (0, None, None)
    if p.suffix.lower() not in SCRATCH_SUFFIXES:
        return (0, None, None)

    warning = (
        f"'{p.name}' is being written to the home root (~/). That is where "
        f"scratch scripts, run logs, and report files accumulate as clutter. "
        f"Prefer: scratch / throwaway -> /tmp/claude/ (self-cleaning); "
        f"deliverables (reports, docs) -> a repo or ~/Documents/knowledge-base/; "
        f"project code -> the project's repo. Write to the home root only if "
        f"the file genuinely must live there (e.g. a helper the user runs by hand)."
    )
    return (0, None, json.dumps({"additionalContext": warning}))


def main():
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    code, stderr_msg, stdout_msg = check(hook_input)
    if stderr_msg:
        print(stderr_msg, file=sys.stderr)
    if stdout_msg:
        print(stdout_msg)
    sys.exit(code)


if __name__ == "__main__":
    main()
