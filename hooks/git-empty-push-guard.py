"""PreToolUse:Bash — BLOCK `git push` of a branch with 0 commits ahead.

Phase A of the post-measurement-discipline plan (PR #416,
~/Documents/knowledge-base/plans/2026-05-04-post-measurement-discipline-followups.md).

Cross-session-git-index-race symptoms recurred FOUR times in one session
on 2026-05-04 (see ~/.claude/rules/git-hygiene.md INCIDENT 2026-04-17
+ INCIDENT 2026-05-04). Each recurrence cost ~5-10 min of cherry-pick
recovery. This hook upgrades the prior advisory-only behavior to a hard
BLOCK — the roundtable synthesis (N3) flagged that warn-with-confirm
degrades under load, and four documented recurrences in one session is
the empirical confirmation.

The actual root cause is shared-HEAD confusion in concurrent worktrees;
this hook does NOT fix that. It blocks the visible symptom (`gh pr
create` rejection on empty branch, push that uploads no commits) at
push-time, before the broken push lands and the user has to recover
via reflog cherry-pick.

Logic:
  1. Match `git push` (excluding force-with-lease cases that intentionally
     rewrite or push tags).
  2. Resolve the LOCAL ref being pushed:
     - `git push origin branch` → refs/heads/branch
     - `git push -u origin branch` → refs/heads/branch
     - `git push` (bare) → currently checked out branch
     - `git push origin sha:refs/heads/branch` → bypassed (advanced refspec)
  3. Resolve the upstream tracking ref for that local ref. If none, skip
     (first push of a new branch is the legitimate empty-equivalent case).
  4. Compute `git rev-list --count <upstream>..<local>`. If 0, BLOCK.

False-positive guards (skip the check):
  - --force or --force-with-lease (rewrites are valid)
  - --tags or --delete or --mirror
  - non-branch refspec (sha:ref form)
  - upstream ref doesn't exist locally (first push of a branch — typical
    when -u is being set; the ref will be created on origin)
  - pushing tags only or running gh pr create (matched separately)

Exit codes:
  0 = allow (default)
  2 = BLOCK with stderr explanation (the cross-session-race signature)

Bypass for legitimate cases (rare): set CLAUDE_GIT_PUSH_ALLOW_EMPTY=1 in
the env. Documented in git-hygiene.md as discouraged but available for
edge cases where the user has reflog-confirmed that the empty-equivalent
push is intentional (e.g., re-running a script after upstream sync).
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

PUSH_RE = re.compile(r"\bgit\s+push\b")
SKIP_FLAGS_RE = re.compile(
    r"--(force|force-with-lease|tags|delete|mirror|prune)\b|^\s*-f\b|\s+-f\s|\s+-f$"
)
DEL_REFSPEC_RE = re.compile(r"\s:[\w/.\-]+")  # `:branchname` deletes
SHA_REFSPEC_RE = re.compile(r"\b[0-9a-f]{7,40}:[\w/.\-]+")

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
        return r.stdout.strip()
    except Exception:
        return None


def _parse_push_target(command):
    """Return the local branch ref the push targets, or None to skip checking.

    Returns None for: deletes, sha:branch refspecs, --tags-only, ambiguous cases.
    """
    cleaned = _strip_quotes(command)
    if SKIP_FLAGS_RE.search(cleaned):
        return None
    if SHA_REFSPEC_RE.search(cleaned):
        return None  # explicit sha refspec is not the bare-branch case
    if DEL_REFSPEC_RE.search(cleaned):
        return None  # delete operation

    # tokenize, drop quoted strings, drop redirects
    tokens = re.findall(r"\S+", cleaned)
    try:
        i = tokens.index("git")
    except ValueError:
        return None
    if i + 1 >= len(tokens) or tokens[i + 1] != "push":
        return None

    args = []
    j = i + 2
    while j < len(tokens):
        t = tokens[j]
        if t in ("&&", "||", ";", "|"):
            break
        # strip option-style flags but keep their values together
        if t.startswith("-"):
            j += 1
            # `-u origin branch` - skip the flag, the next two tokens are positional
            continue
        args.append(t)
        j += 1

    # args is now [<remote>?, <refspec>?]
    if not args:
        return "__bare__"  # `git push` - check current branch
    if len(args) == 1:
        # `git push origin` — pushes current branch's upstream
        return "__bare__"
    if len(args) >= 2:
        spec = args[1]
        # refspec like `local:remote` or `+local:remote`
        if ":" in spec:
            local = spec.split(":", 1)[0].lstrip("+")
            return local if local else None
        return spec
    return None


def _warn_unwired_githooks(cwd):
    """WARN (never block) when a repo ships .githooks/ but this clone isn't wired.

    `core.hooksPath` is ONE-TIME PER CLONE and a worktree INHERITS its parent
    clone's config, so a second clone of a repo that ships `.githooks` pushes
    with ZERO pre-push gating — silently: no error, no skipped-hook notice, just
    an ordinary-looking push. `repo_sync.py` wires it opportunistically but only
    for the repos it manages, so claude-config and claude-knowledge-base (both
    of which ship `.githooks`) are wired only incidentally.

    WARNS rather than blocks, deliberately. The sibling status-loss checks in
    bash-tail-buffering-guard block because a false verdict is silent and
    unrecoverable; an unwired clone is neither — the push succeeds, the gates
    simply did not run, and CI still catches what they would have. Measured
    across 30d, this hook family's value is overwhelmingly non-blocking
    (611,993 fires / 1,299 blocks = 0.2%), and `bash-security-guard` auto-fixes
    2.6x more often than it blocks. A block here would be the wrong severity for
    a recoverable, informational condition.

    Not auto-fixed either: `git config core.hooksPath` mutates the user's repo
    config, which a PreToolUse hook should not do unasked. The message carries
    the exact one-line command instead.

    WHY: 2026-07-29 — ~/Documents/GitHub/claude-config had hooksPath UNSET, so a
    push from it ran no pre-push gate at all and the omission was invisible.
    """
    try:
        if not os.path.isdir(os.path.join(cwd, ".githooks")):
            return  # repo ships no hooks — the concept does not apply
        configured = _run_git(["config", "--get", "core.hooksPath"], cwd)
        if configured:
            return
        print(json.dumps({"systemMessage": (
            "[git-empty-push-guard] This clone ships `.githooks/` but "
            "`core.hooksPath` is UNSET, so pre-push gates did NOT run for this "
            "push — silently (no error, no skipped-hook notice). Wire it once "
            "per clone:  git config core.hooksPath .githooks"
        )}))
    except Exception:
        return  # advisory only — never let this path affect the push


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if os.environ.get("CLAUDE_GIT_PUSH_ALLOW_EMPTY") == "1":
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    command = tool_input.get("command", "") or ""
    if not PUSH_RE.search(_strip_quotes(command)):
        return 0

    target = _parse_push_target(command)
    if target is None:
        return 0  # skip case (force/tags/delete/sha-refspec/etc.)

    cwd = _resolve_cwd(command, payload.get("cwd", os.getcwd()))
    if not os.path.isdir(cwd):
        return 0

    _warn_unwired_githooks(cwd)

    if target == "__bare__":
        local_branch = _run_git(["branch", "--show-current"], cwd)
        if not local_branch:
            return 0
    else:
        local_branch = target

    # Resolve upstream tracking ref
    upstream = _run_git(
        ["rev-parse", "--symbolic-full-name", f"{local_branch}@{{upstream}}"],
        cwd,
    )
    if not upstream:
        # No upstream set — first push of a new branch. Not the failure shape.
        return 0

    ahead = _run_git(["rev-list", "--count", f"{upstream}..{local_branch}"], cwd)
    if ahead is None:
        return 0
    try:
        n_ahead = int(ahead)
    except ValueError:
        return 0

    if n_ahead == 0:
        local_sha = _run_git(["rev-parse", "--short=12", local_branch], cwd) or "?"
        upstream_sha = _run_git(["rev-parse", "--short=12", upstream], cwd) or "?"
        msg = (
            f"\n[git-empty-push-guard] BLOCKED: branch '{local_branch}' has 0 commits "
            f"ahead of upstream {upstream} ({upstream_sha} == local {local_sha}).\n"
            f"  This is the typical signature of cross-session-git-index-race "
            f"(see ~/.claude/rules/git-hygiene.md INCIDENT 2026-04-17 +\n"
            f"  INCIDENT 2026-05-04). Pushing this would land an empty-equivalent\n"
            f"  branch on origin and `gh pr create` would reject with 'No commits\n"
            f"  between main and ...'.\n"
            f"\n  Likely your commit landed on a different branch (HEAD-confusion in\n"
            f"  a shared worktree). Recovery:\n"
            f"    git reflog -n 20  # find the orphaned commit SHA\n"
            f"    git checkout -b feat/<name>-clean origin/main\n"
            f"    git cherry-pick <sha>\n"
            f"    git push -u origin feat/<name>-clean\n"
            f"\n  To bypass this block (rare; e.g. you've reflog-confirmed the empty\n"
            f"  push is intentional): set CLAUDE_GIT_PUSH_ALLOW_EMPTY=1 in env.\n"
        )
        print(msg, file=sys.stderr)
        # Exit 2 = BLOCK with stderr explanation (PreToolUse hook protocol)
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