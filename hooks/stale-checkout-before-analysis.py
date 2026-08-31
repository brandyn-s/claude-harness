"""PreToolUse:Read|Grep|Glob — advise when analysis reads a BEHIND checkout.

Generated from staged spec: hooks/staged/stale-checkout-before-analysis.spec.md
Installed by /ship-hook on 2026-08-27.

WHY THIS EXISTS. Every existing currency rule frames freshness around EDITING or
DEPLOYING: `worktree-by-default` says fetch and compare "before editing";
`check-before-change` says verify current state before a CHANGE. Reading a tracked
file for ANALYSIS is covered by neither, and that is where the damage starts — a
wrong analysis then drives the plan and the user-facing question, long before any
edit-time gate can fire.

Measured 2026-08-12: an analysis of `corpdev-dashboard` concluded the Pryzm adapters
were stubs that throw, the terraform variable did not exist, and the work was a
from-scratch build. A four-option scope question went to the user on that basis. All
of it was wrong — the checkout sat 24 commits behind `origin/main` and everything
had shipped in PR #81. The pre-edit fetch was performed correctly; it was simply too
late. The spec's parent plan records this as the #1 self-inflicted theme (~20x).

MEASURED BEFORE INSTALL, per the spec's own gate (442 sessions, 142 managed clones):
  distinct repos read per session   mean 1.15, median 1, max 6 (30.3% read none)
  clones behind their upstream      21 of 102 with an upstream = 20.6%
  estimated firings per session     1.15 x 20.6% = 0.24   (gate: "well under 1")
  sessions reading 3+ repos         10.2%  (falsifier needed "most" — not triggered)

DESIGN CONSTRAINTS, all three from the spec:
  * ADVISORY ONLY. exit 0 always. Analysis on a stale tree is sometimes correct and
    sometimes deliberate; the cost of being wrong is a wasted read, not damage.
  * NO NETWORK. Never fetch. A network call inside a Read hook is its own hazard, and
    a stale `@{upstream}` ref still catches the common case.
  * PER-REPO ONCE PER SESSION. Cached in a session-scoped marker, so a 200-file read
    sweep produces one line, not two hundred.

THE NO-UPSTREAM CASE IS THE ONE THAT MATTERS MOST. 40 of 142 clones (28%) have no
upstream — a fresh local branch, a detached worktree. `rev-list --count HEAD..@{upstream}`
exits NON-ZERO for those. That must be read as "unknown, stay silent", NEVER as
"0 behind" and never as a firing. Treating an error as 0 would be a silent
false-negative across a quarter of the fleet; treating it as a fire would be spam.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SESSION_ENV_DIR = Path.home() / ".claude" / "session-env"

# Bounded so a hook can never hang a Read behind a slow filesystem.
#
# THIS VALUE IS LOAD-BEARING FOR THE REGISTERED HOOK TIMEOUT, and the two are a
# relationship, not two independent numbers. `architecture-drift-check.py` enforces
# a 10s floor on any PreToolUse registration because the run-hook wrapper's start-up
# ALONE is a measured 1.4-4.1s. This hook then makes up to MAX_GIT_CALLS git calls,
# so the worst case is WRAPPER_STARTUP_CEILING_S + MAX_GIT_CALLS * GIT_TIMEOUT_S.
# At 4 calls that is 4.1 + 8 = 12.1s, which is why the registration is 15s and not
# the 5s it was first wired with. test_registered_timeout_covers_the_worst_case
# asserts the DERIVED bound, so raising GIT_TIMEOUT_S or adding a git call fails the
# suite instead of silently eating into the margin.
GIT_TIMEOUT_S = 2
MAX_GIT_CALLS = 4                  # toplevel, rev-list, abbrev-ref HEAD, abbrev-ref upstream
WRAPPER_STARTUP_CEILING_S = 4.1    # measured; see reference_hook-timeout-vs-runhook-overhead
REGISTERED_TIMEOUT_S = 15          # must be >= ceiling + MAX_GIT_CALLS * GIT_TIMEOUT_S


def _git(cwd: Path, *args):
    """(rc, stdout). Never raises; a failure is (nonzero, '')."""
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
        return r.returncode, r.stdout.strip()
    except Exception:
        return 1, ""


def _read_target(tool_input: dict) -> str | None:
    """The filesystem path this call will read, if it is absolute.

    Read uses file_path; Grep and Glob use path. Same extraction for all three.
    """
    for key in ("file_path", "path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v.startswith("/"):
            return v
    return None


def _session_id() -> str:
    sid = (os.environ.get("CLAUDE_SESSION_ID")
           or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default")
    return sid[:12]


def _already_warned(repo: Path) -> bool:
    """True when this session already advised about this repo.

    Marker is per (session, repo) so the advisory is once-per-repo, not
    once-per-session — a session touching two stale repos should hear about both.
    """
    key = str(repo).replace("/", "_").strip("_")[-80:]
    marker = SESSION_ENV_DIR / f"stalecheck-{_session_id()}-{key}"
    if marker.exists():
        return True
    try:
        SESSION_ENV_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except OSError:
        # Cannot cache -> better to advise once more than to go silent.
        pass
    return False


def behind_count(repo: Path):
    """Commits HEAD is behind its upstream, or None when that is UNKNOWABLE.

    None covers: no upstream configured, no upstream ref fetched yet, a git failure,
    a timeout. Every one of those means "unknown" — the caller must stay silent.
    """
    rc, out = _git(repo, "rev-list", "--count", "HEAD..@{upstream}")
    if rc != 0:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def advisory(repo: Path, branch: str, n: int, upstream: str) -> str:
    return (
        f"[stale-checkout-before-analysis] ADVISORY: reading {repo.name} on "
        f"{branch}, {n} commit(s) behind {upstream}.\n"
        "Analysis from this tree may describe code nobody runs — the pre-EDIT fetch "
        "is too late if the conclusion is already formed. Before concluding:\n\n"
        f"  git -C {repo} fetch && git -C {repo} log --oneline HEAD..{upstream}\n\n"
        "Measured 2026-08-12: a 24-behind checkout produced a confident analysis that "
        "was wrong in every particular, and it drove a user-facing scope question. "
        "This does not block; a deliberately old tree is a legitimate thing to read."
    )


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        tool_name = data.get("tool_name", "")
        if tool_name not in ("Read", "Grep", "Glob"):
            sys.exit(0)
        target = _read_target(data.get("tool_input") or {})
        if not target:
            sys.exit(0)

        start = Path(target)
        if not start.is_dir():
            start = start.parent
        if not start.is_dir():
            sys.exit(0)

        rc, top = _git(start, "rev-parse", "--show-toplevel")
        if rc != 0 or not top:
            sys.exit(0)                      # not a git repo — nothing to say
        repo = Path(top)

        n = behind_count(repo)
        if n is None or n <= 0:
            sys.exit(0)                      # unknown, or current — stay silent

        if _already_warned(repo):
            sys.exit(0)                      # once per repo per session

        _, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        _, upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
                           "@{upstream}")
        print(advisory(repo, branch or "?", n, upstream or "@{upstream}"),
              file=sys.stderr)
        sys.exit(0)

    except Exception:
        # Never let an advisory break a read.
        sys.exit(0)


if __name__ == "__main__":
    main()
