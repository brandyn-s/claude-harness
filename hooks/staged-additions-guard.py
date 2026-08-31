"""PreToolUse:Bash — BLOCK `git commit` when staged ADDITIONS coexist with
unstaged MODIFICATIONS (the PR #317 forgot-to-stage signature).

Generated from staged spec: hooks/staged/staged-additions-guard.spec.md
(Phase G of ~/Documents/knowledge-base/plans/2026-05-14-post-roadmap-consolidation.md).
Installed by /ship-hook on 2026-06-11.

Incident this prevents: rules/git-hygiene.md INCIDENT 2026-05-14
staged-only-additions-dropped-modifications — `git add <new files>` ran,
modifications to existing tracked files were left unstaged, and the commit
silently dropped them (PR #317 shipped without 4 M-files; the gate script
it added was dead code on main until follow-up PR #318).

Logic:
  1. Match `git commit` (skip --amend / --allow-empty / --allow-empty-message).
  2. Skip auto-staging shapes: `-a` / `-am` / `--all`, or an explicit
     `git add -A|--all|.` earlier in the same command line.
  3. Parse `git status --porcelain` in the resolved cwd.
  4. BLOCK (exit 2) iff staged addition (X=='A') AND unstaged modification
     (Y=='M') are both present — new files staged, edits forgotten.

Bypass for intentional partial commits: CLAUDE_GIT_COMMIT_ALLOW_PARTIAL=1.
Documented in rules/git-hygiene.md as discouraged but available for
split-commit workflows (separating fixtures from test code).
"""

import json
import os
import re
import subprocess
import sys

try:
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

COMMIT_RE = re.compile(r"\bgit\s+commit\b")
# Safe commit shapes: amend, allow-empty variants, -a / -am / --all auto-staging.
SAFE_FLAGS_RE = re.compile(
    r"--amend\b|--allow-empty(?:-message)?\b|--all\b|(?:^|\s)-a[a-z]*\b"
)
# Explicit stage-everything earlier in the same command line.
STAGE_ALL_RE = re.compile(r"\bgit\s+add\s+(?:-A\b|--all\b|\.(?:\s|$|;|&))")

_QUOTED_RE = re.compile(r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
_CD_RE = re.compile(r"\bcd\s+([^\s;&|]+)")


def _strip_quotes(s):
    return _QUOTED_RE.sub("", s)


def _resolve_cwd(command, cwd):
    matches = _CD_RE.findall(_strip_quotes(command))
    if not matches:
        return cwd
    target = matches[-1].strip("'\"")
    if target.startswith("~"):
        target = os.path.expanduser(target)
    if not os.path.isabs(target):
        target = os.path.abspath(os.path.join(cwd, target))
    return target


def _run_git(args, cwd, timeout=3):
    try:
        r = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def _format_block_message(unstaged_files, cwd):
    shown = unstaged_files[:10]
    listing = "\n".join(f"    M  {p}" for p in shown)
    more = (
        f"\n    ... and {len(unstaged_files) - len(shown)} more"
        if len(unstaged_files) > len(shown)
        else ""
    )
    return (
        f"\n[staged-additions-guard] BLOCKED: working tree at {cwd} has staged "
        f"ADDITIONS (new files)\n"
        f"  AND unstaged MODIFICATIONS to tracked files.\n"
        f"\n  This is the PR #317 (2026-05-14) signature: `git add <new-files>` was\n"
        f"  run, but modifications to existing files were left unstaged. Committing\n"
        f"  now would drop the unstaged modifications from the commit.\n"
        f"\n  Unstaged modifications ({len(unstaged_files)} file(s)):\n"
        f"{listing}{more}\n"
        f"\n  Recovery options:\n"
        f"    (a) Verify intent: `git diff --cached --stat` — if the staged set is\n"
        f"        complete and the M files belong to a separate commit, stash them\n"
        f"        or set CLAUDE_GIT_COMMIT_ALLOW_PARTIAL=1 to bypass.\n"
        f"    (b) Stage everything: `git add -A` then retry — captures BOTH the new\n"
        f"        files AND the modifications (the right path when M was forgotten).\n"
        f"    (c) Selectively stage: `git add <specific M files>` then retry.\n"
        f"\n  Bypass: CLAUDE_GIT_COMMIT_ALLOW_PARTIAL=1 — NOTE this must already be in\n"
        f"  the Claude Code process environment (settings.json `env`, or the shell that\n"
        f"  launched it). A command-line prefix (`VAR=1 git commit ...`) does NOT work:\n"
        f"  this hook runs OUTSIDE that command's process and never sees it. If you\n"
        f"  cannot set it, commit the tracked MODIFICATIONS alone (that path is not\n"
        f"  gated) and stage new files in a separate commit once the unrelated dirty\n"
        f"  files are resolved. (discouraged; documented in\n"
        f"  rules/git-hygiene.md).\n"
    )


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if os.environ.get("CLAUDE_GIT_COMMIT_ALLOW_PARTIAL") == "1":
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    command = tool_input.get("command", "") or ""
    cleaned = _strip_quotes(command)

    if not COMMIT_RE.search(cleaned):
        return 0
    if SAFE_FLAGS_RE.search(cleaned):
        return 0
    if STAGE_ALL_RE.search(cleaned):
        return 0

    cwd = _resolve_cwd(command, payload.get("cwd", os.getcwd()))
    if not os.path.isdir(cwd):
        return 0

    status = _run_git(["status", "--porcelain"], cwd)
    if status is None:
        return 0

    has_staged_addition = False
    unstaged_files = []
    for line in status.splitlines():
        if len(line) < 3:
            continue
        x, y = line[0], line[1]
        path = line[3:]
        if x == "A":
            has_staged_addition = True
        if y == "M":
            unstaged_files.append(path)

    if has_staged_addition and unstaged_files:
        print(_format_block_message(unstaged_files, cwd), file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
