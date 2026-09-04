"""PreToolUse:Write|Edit — enforce worktree isolation for protected-repo writes.

TWO independent gates:

1. check_shared_checkout_branch_state() — blocks CONTENT edits (main session OR
   subagent) to the ~/.claude MAIN checkout when it is on a NON-MAIN branch. The
   shared-HEAD-race hazard: every concurrent session shares this one working tree
   + HEAD, so editing it on a feature branch invites dirty-accumulation +
   destructive reconcile (git-hygiene incidents 2026-05-04 / 2026-06-13 /
   2026-06-18 — the last reverted 3 sessions' in-flight work). Force /work first.
   Narrow scope (non-main branch only, worktrees + transients exempt) so it does
   NOT re-introduce the 2026-04-13 block-everything regression.

2. check() — blocks SUBAGENT writes to protected repo files unless in a worktree.
   Main session writes pass (the user's Write tool IS authorized). Subagent
   containment: bypassPermissions subagents have gone rogue (PR #130 — merged 7
   files, deleted 3 hooks). Changed 2026-04-13: was blocking ALL writes incl.
   main session, causing 15+ minute ship cycles; now subagent-only.

Both honor CLAUDE_SKIP_WORKTREE_CHECK=1 as a per-session override.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# The canonical protected-repository data file, shared with
# bash-security-guard.py (which reads its `repos` list from the same file
# beside itself). Its `local_paths` object is this guard's ONLY source.
PROTECTED_REPOS_FILE = Path(__file__).resolve().parent / "protected-repos.json"


def _inert_note(config: Path, reason: str) -> None:
    """One stderr line, then carry on with an empty map: this guard is "open"
    in write-edit-dispatcher.py (a load failure must not brick editing), so a
    missing or broken data file makes the subagent gate inert and says so."""
    sys.stderr.write(
        f"[worktree-guard] {config} {reason}; protected-repo gate for "
        "subagent writes is inert\n"
    )


def _load_protected_repos(config: Path = PROTECTED_REPOS_FILE) -> dict:
    """Load repo name -> lowercase forward-slash root from `local_paths` in
    hooks/protected-repos.json.

    Nothing else feeds this map. A hard-coded fallback used to sit here (the
    original author's Windows drive layout); on any other host it matched no
    path while looking configured, so a missing data file was
    indistinguishable from a working guard. Now a missing, unreadable or
    malformed file leaves the map empty with one stderr note (fail-open, the
    posture the dispatcher applies to this guard)."""
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _inert_note(config, f"missing or unreadable ({type(exc).__name__})")
        return {}
    local_paths = data.get("local_paths") if isinstance(data, dict) else None
    if not isinstance(local_paths, dict):
        _inert_note(config, "has no `local_paths` object")
        return {}
    out = {}
    for repo, path in local_paths.items():
        if not isinstance(path, str) or not path:
            continue
        # Resolve ~ and normalize to lowercase forward-slash form for the
        # downstream startswith() comparisons.
        resolved = os.path.expanduser(path).replace("\\", "/").lower()
        out[repo] = resolved
    return out


PROTECTED_REPOS = _load_protected_repos()

# Subagent-writable drop zones inside protected repos. Paths are repo-relative,
# matched against the file path after the protected-repo root. Curated content
# (topics/, reference/, templates/, README, etc.) stays protected; only these
# auto-generated artifact folders are open to forked subagents.
ALLOWED_SUBPATHS = {
    "knowledge-base": [
        "research/",  # /deep-dive, /gather-research outputs
        "plans/",     # /superplan saved plans
    ],
}


def _normalize(path):
    return path.replace("\\", "/").lower()


def _find_protected_repo(file_path_norm):
    for name, root in PROTECTED_REPOS.items():
        if file_path_norm.startswith(root):
            return name, root
    return None, None


def _is_allowed_subpath(repo_name, repo_root, file_path_norm):
    for subpath in ALLOWED_SUBPATHS.get(repo_name, ()):
        full = repo_root.rstrip("/") + "/" + subpath.lstrip("/")
        if file_path_norm.startswith(full.lower()):
            return True
    return False


def _is_in_worktree(cwd):
    cwd_norm = _normalize(cwd)
    if ".claude/worktrees/" in cwd_norm:
        return True
    try:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=cwd, timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
        git_common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, cwd=cwd, timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
        if git_dir.returncode == 0 and git_common.returncode == 0:
            gd = os.path.normpath(git_dir.stdout.strip())
            gc = os.path.normpath(git_common.stdout.strip())
            if gd != gc:
                return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def _git_branch(repo_dir):
    """Current branch of repo_dir's working tree, or None if undeterminable."""
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=str(repo_dir), timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


# Files inside ~/.claude that are session-state / hook-managed / per-machine —
# hooks and skills write these as a side effect, so they must NOT be gated.
_TRANSIENT_MARKERS = (
    "settings.json", "settings.local.json", "last-distill.json",
    "distill-history.jsonl", "mcp-needs-auth-cache.json",
    "session-friction-patterns.md", "gh-pr-status-cache.json",
    "daemon.log", "/.session-active/", "/projects/",
)


def check_shared_checkout_branch_state(data):
    """Block CONTENT edits to the ~/.claude MAIN checkout when it is on a
    non-main branch — the shared-HEAD-race hazard.

    ~/.claude is ONE working tree + HEAD that every concurrent session runs
    from. Editing it on a feature branch invites dirty-accumulation +
    destructive reconcile (git-hygiene incidents 2026-05-04 / 2026-06-13 /
    2026-06-18). The fix is per-session isolation (/work / EnterWorktree).

    This fires for the MAIN SESSION and subagents alike — a distinct axis
    from check() below, which the 2026-04-13 change scoped to subagents.
    Narrow by design so it does NOT re-introduce that block-everything
    regression: ONLY the ~/.claude main checkout (worktrees exempt), ONLY a
    non-main branch (on main → allowed, even dirty), ONLY content files
    (transients exempt). Override for one session: CLAUDE_SKIP_WORKTREE_CHECK=1.

    Returns (exit_code, stderr_payload, stdout_payload).
    """
    if data.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        return (0, None, None)
    if os.environ.get("CLAUDE_SKIP_WORKTREE_CHECK", "").strip() == "1":
        return (0, None, None)

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return (0, None, None)
    file_path_norm = _normalize(file_path)

    claude_root = _normalize(str(Path.home() / ".claude"))
    if not file_path_norm.startswith(claude_root + "/"):
        return (0, None, None)  # not a ~/.claude edit

    # Worktrees are the CORRECT isolated path — never gate them. Covers the
    # EnterWorktree default (~/.claude/worktrees/...) and ~/worktrees/...
    if "/worktrees/" in file_path_norm or _is_in_worktree(data.get("cwd", "")):
        return (0, None, None)

    # Session-state / hook-managed / per-machine files: writes are side effects.
    if any(m in file_path_norm for m in _TRANSIENT_MARKERS):
        return (0, None, None)

    branch = _git_branch(Path.home() / ".claude")
    if not branch or branch == "main":
        return (0, None, None)  # on main (normal) or undeterminable → fail open

    filename = os.path.basename(file_path)
    msg = (
        f"[shared-checkout-guard] BLOCKED: editing {filename} in the shared "
        f"~/.claude MAIN checkout while it is on branch '{branch}' (not main).\n"
        f"Concurrent sessions share this one working tree + HEAD — editing it on a "
        f"feature branch is the shared-HEAD-race hazard (git-hygiene incidents "
        f"2026-05-04 / 2026-06-13 / 2026-06-18; the last reverted 3 sessions' work).\n"
        f"FIX: run /work (EnterWorktree) to isolate this session, then edit there. "
        f"If this is the SOLE live session, `git -C ~/.claude checkout main` first.\n"
        f"Override for one session: CLAUDE_SKIP_WORKTREE_CHECK=1."
    )
    return (2, msg, None)


def check(data):
    """Returns (exit_code, stderr_payload, stdout_payload).

    THE dispatched entry point — write-edit-dispatcher.py calls check() (NOT
    main()), so BOTH gates must run here:
      Gate 1: shared-checkout branch-state (main session AND subagent).
      Gate 2: subagent worktree-containment (the original, subagent-only).
    """
    # Gate 1 runs first and applies to the MAIN SESSION too, so it must come
    # before the agent_type early-return below that exempts the main session.
    code, stderr_msg, stdout_msg = check_shared_checkout_branch_state(data)
    if code != 0:
        return (code, stderr_msg, stdout_msg)

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        return (0, None, None)

    agent_type = data.get("agent_type")
    if not agent_type:
        return (0, None, None)

    if os.environ.get("CLAUDE_SKIP_WORKTREE_CHECK", "").strip() == "1":
        return (0, None, None)

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return (0, None, None)

    file_path_norm = _normalize(file_path)
    cwd = data.get("cwd", "")

    repo_name, repo_root = _find_protected_repo(file_path_norm)
    if not repo_name:
        return (0, None, None)

    if _is_allowed_subpath(repo_name, repo_root, file_path_norm):
        return (0, None, None)

    if _is_in_worktree(cwd):
        return (0, None, None)

    filename = os.path.basename(file_path)
    agent_id = data.get("agent_id", "unknown")
    msg = (
        f"[worktree-guard] BLOCKED: Subagent {agent_id} writing to {filename} in "
        f"protected repo ({repo_name}) without worktree isolation.\n"
        f"Dispatch with isolation: 'worktree' to fix."
    )
    return (2, msg, None)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)
    # check() runs BOTH gates (branch-state + subagent). Standalone invocation
    # and the dispatcher (which calls check()) therefore behave identically.
    code, stderr_msg, stdout_msg = check(data)
    if stderr_msg:
        sys.stderr.write(stderr_msg + "\n")
    if stdout_msg:
        print(stdout_msg)
    sys.exit(code)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
