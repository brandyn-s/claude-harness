"""Healthcheck Check 0: main checkout freshness.

The healthcheck helpers read from `CLAUDE_DIR` (default `~/.claude`).
When that checkout is stale — on a feature branch instead of `main`, OR
many commits behind `origin/main` — every downstream check reads stale
state. Previous skill content, deleted files, and outdated hooks all
surface as false findings.

INCIDENT 2026-05-29: a `checkpoint/20260527000921` auto-checkpoint left
the main checkout 27 commits behind origin/main. Subsequent healthcheck
runs reported 30 of 33 findings as "real" — 30 were stale-checkout
artifacts. Hours of investigation chasing phantoms.

INCIDENT 2026-08-30: staleness is not only a COMMIT-POSITION property.
This check measured branch and behind/ahead only, so a checkout on main,
0 behind, 0 ahead, carrying UNCOMMITTED tracked edits reported PASS — and
because the orchestrator keys its `[POSSIBLY STALE]` stamping and its
WIP-FAIL labelling on this check's exit status, nothing was stamped and
`Overall: UNHEALTHY` was printed. 19 findings were traced to working-tree
state rather than committed code: 11 drift findings from a locally
regressed ARCHITECTURE.md (HEAD held all 11 entries), 5 drift-gate
violations plus 2 hook-test failures from an uncommitted settings.json
rewrite, and 3 hook-test failures from untracked files absent on
origin/main. A clean worktree at origin/main reported 0 drift and passed
the gate. The near-miss is what makes this load-bearing: the reported fix
for the 11 drift items was to ADD them to ARCHITECTURE.md, which already
contained all 11 — the "fix" would have shipped 11 duplicates.

This check runs FIRST so all subsequent findings can be flagged
`[STALE]` when freshness fails, or trusted when freshness passes.

Read-only. Exit 0 = fresh. Exit 1 = stale. Exit 2 = couldn't determine
(e.g., CLAUDE_DIR isn't a git repo).

Usage:
  python _check_freshness.py [--max-behind N] [--no-fetch]
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))

# Threshold: how many commits behind origin/main is "too stale"? Five
# is a heuristic — captures "you missed a normal day's worth of work"
# while not flagging every brief lag. Tune via --max-behind.
DEFAULT_MAX_BEHIND = 5

# Suppress console window flash on Windows when subprocesses spawn.
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _git(args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run `git -C CLAUDE_DIR <args>`. Returns (rc, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(CLAUDE_DIR), *args],
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return -1, "", str(e)


def _dirty_tracked() -> list[str]:
    """Tracked files modified relative to HEAD.

    Only TRACKED modifications are measured. Untracked files have a large
    permanent floor in the deployed dir (measured 2026-08-30: 48 untracked —
    `.locks/`, `.memory-audit-archive/`, `run/`, `tmp/`, `projects/` — against
    exactly 1 tracked modification), so triggering on them would engage the
    stamp permanently. A permanently-engaged interlock is indistinguishable
    from a disabled one, which is the failure `grading-discipline` names for
    destructive gates: split the permanent population from the transient one.
    Untracked files are reported as CONTEXT and never set the exit status.
    """
    rc, out, _ = _git(["diff", "--name-only", "HEAD"])
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def _untracked_count() -> int:
    rc, out, _ = _git(["ls-files", "--others", "--exclude-standard"])
    if rc != 0:
        return 0
    return len([ln for ln in out.splitlines() if ln.strip()])


def check_freshness(max_behind: int = DEFAULT_MAX_BEHIND, do_fetch: bool = True) -> int:
    """Run the freshness check and emit a single-line report.

    Returns 0 = fresh, 1 = stale, 2 = couldn't determine.
    """
    if not (CLAUDE_DIR / ".git").exists():
        print(f"Freshness: SKIP — {CLAUDE_DIR} is not a git repo")
        return 2

    # Optional fetch — keeps the check honest. Skip with --no-fetch when
    # offline or when you already fetched within the last minute.
    if do_fetch:
        rc, _, err = _git(["fetch", "origin", "main"], timeout=15)
        if rc != 0:
            # Don't fail the check on fetch failure (offline, auth issues);
            # proceed with whatever origin/main ref we already have.
            print(f"Freshness: WARN — fetch failed ({err.splitlines()[0] if err else 'unknown'}); checking against cached origin/main")

    rc_branch, branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    rc_head, head_sha, _ = _git(["rev-parse", "--short", "HEAD"])
    rc_origin, origin_sha, _ = _git(["rev-parse", "--short", "origin/main"])

    if rc_branch != 0 or rc_head != 0 or rc_origin != 0:
        print("Freshness: SKIP — couldn't read git refs (rev-parse failed)")
        return 2

    rc_behind, behind_out, _ = _git(["rev-list", "--count", "HEAD..origin/main"])
    rc_ahead, ahead_out, _ = _git(["rev-list", "--count", "origin/main..HEAD"])
    behind = int(behind_out) if rc_behind == 0 and behind_out.isdigit() else -1
    ahead = int(ahead_out) if rc_ahead == 0 and ahead_out.isdigit() else -1

    is_main = branch == "main"
    is_behind = behind > max_behind
    dirty = _dirty_tracked()
    untracked = _untracked_count()

    if is_main and not is_behind and not dirty:
        print(f"Freshness: PASS — on main ({head_sha}, {behind} behind, "
              f"{ahead} ahead, clean; {untracked} untracked)")
        return 0

    # Stale — emit the diagnosis with recovery steps. A checkout that is BOTH
    # behind and ahead has DIVERGED: `git pull --ff-only` fails outright there,
    # so the advice must not suggest it (2026-08-22: reported "131 behind" while
    # 278 local commits existed — the printed recovery was impossible to run).
    diverged = is_behind and ahead > 0
    parts = ["Freshness: WARN —"]
    if not is_main:
        parts.append(f"on '{branch}' instead of main")
    if diverged:
        parts.append(f"diverged: {behind} commits behind / {ahead} ahead of origin/main")
    elif is_behind:
        parts.append(f"{behind} commits behind origin/main")
    if dirty:
        shown = ", ".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
        parts.append(f"{len(dirty)} tracked file(s) modified ({shown})")
    parts.append(f"(HEAD={head_sha}, origin/main={origin_sha})")
    print(" ".join(parts))
    print("  ↳ Findings in subsequent checks may reflect stale state.")
    if dirty:
        print("  ↳ Uncommitted TRACKED edits are read by the checks as if they were "
              "current state, so they can MANUFACTURE findings that do not exist in "
              "committed code.")
        print("  ↳ Confirm each finding against committed state before acting: "
              "git worktree add /tmp/hc-verify origin/main && "
              "CLAUDE_CONFIG_DIR=/tmp/hc-verify python3 <the check>")
    print("  ↳ Recover: cd ~/.claude && git status -s  # check for uncommitted work")
    if not is_main:
        print("  ↳         git checkout main  # (or rename current branch if main is taken by a worktree)")
    if diverged:
        print(f"  ↳         checkout holds {ahead} unpushed commit(s) — ff-only pull will fail;")
        print("  ↳         reconcile deliberately (rebase or merge) per git-hygiene, don't force")
    elif is_behind:
        print("  ↳         git pull --ff-only  # fast-forward to current origin/main")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-behind", type=int, default=DEFAULT_MAX_BEHIND,
                        help=f"max commits behind origin/main before WARN (default {DEFAULT_MAX_BEHIND})")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the `git fetch` step (use cached origin/main)")
    args = parser.parse_args()
    return check_freshness(max_behind=args.max_behind, do_fetch=not args.no_fetch)


if __name__ == "__main__":
    sys.exit(main())
