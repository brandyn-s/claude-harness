"""Warn at SessionStart when ~/.claude is behind origin/main on ENFORCEMENT files.

Installed from hooks/staged/stale-claude-checkout-disables-hooks.spec.md
(staged 2026-07-29 by /distill) on 2026-08-01 via /ship-hook.

WHY THIS EXISTS
---------------
Hooks are code in the working tree. `settings.json` points at
`~/.claude/hooks/<name>.py`, so the guard that RUNS is whatever version is
checked out -- not whatever version was merged. A `~/.claude` that is N commits
behind `origin/main` is running N-commits-old enforcement, and nothing signals
it: no block, no warning, no change in fire counts. The guard simply is not
there.

Live instance 2026-07-29: local HEAD was 66 commits behind. `git-gating-pipe-guard`
had shipped the day before (PR #1765); the RUNNING
`bash-tail-buffering-guard.py` had 0 of its gating-pattern matches. In the same
session a `git checkout -q "$B" 2>&1 | tail -1` loop -- the exact shape that
guard was installed to block -- ran unimpeded, discarded checkout's exit status,
and two of three branches were silently created off the wrong base. The session
hit 8 OTHER guard blocks, which made enforcement FEEL present; the guards that
fired were the old ones. There is no way to notice from inside a session that a
NEWER guard is missing.

Second consequence, worse: staged-spec state is stale too. Installed specs are
REMOVED from `hooks/staged/` on install, so a stale tree still shows them --
and a /distill dedup pass reading that directory concludes "spec exists,
un-installed" and re-recommends installing an already-installed hook.
Confirmed again 2026-08-01: two specs already shipped on origin/main
(`WRAPPER_PREFIXES`, `check_trailing_status_swallow`) were invisible from a
23-behind local tree and read as pending work.

WHY A STARTUP CHECK AND NOT A PreToolUse HOOK
---------------------------------------------
A PreToolUse hook cannot detect its own staleness -- the stale version is the
one running, and it does not know a newer one exists. The check has to come
from a component whose job is environment validation, evaluated once, before
work starts.

RELATIONSHIP TO repo_sync
-------------------------
`repo_sync.py` DOES sync ~/.claude, but it returns early without fetching when
the tree is dirty AND another session is active:

    if is_dirty and has_concurrent_sessions(self_session_id):
        warnings.append("... Skipped auto-checkpoint+rebase ...")
        return warnings

That warning is about the DIRTY FILES. It says nothing about how far behind the
checkout has drifted or that enforcement is stale. On a contended host that
early return is the steady state, so the drift accumulates unreported. This
module is the missing DETECTION half; repo_sync remains the remediation half.

DESIGN NOTES
------------
* OFFLINE. Compares HEAD against the locally-cached `origin/main` ref -- no
  network call, so a session start can never hang or fail on connectivity.
  A stale cached ref under-reports (fails safe); it cannot over-report.
* NEVER BLOCKS. Session start must not fail closed. Every failure path returns
  an empty list.
* FIRES ON THE ENFORCEMENT DELTA, not merely on being behind. Being behind only
  MATTERS when the delta touches enforcement, so `hooks/` + `settings.json` is
  the precise signal and the differing files are named in the message.
* The spec's bare "1-9 behind" notice tier is deliberately NOT implemented.
  Per verify-effectiveness.md (measure distributions before setting thresholds)
  its fire rate is unmeasured, and the spec's own verification section says to
  drop that tier if sessions are routinely 1-9 behind. Shipping only the two
  tiers with a known-real signal keeps the channel credible; the notice tier
  can be added later against a measured rate.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

CONFIG_REPO = Path.home() / ".claude"

# Paths whose staleness silently disables enforcement.
ENFORCEMENT_PATHS = ("hooks/", "settings.json")

# At or above this many commits behind, warn even with no enforcement delta --
# a gap this wide means the whole config surface (rules, skills, agents) is old.
PROMINENT_BEHIND = 10

# Cap the named-file list so a very stale tree does not produce a wall of text.
MAX_NAMED_FILES = 6


def _git(args: list[str], repo: Path) -> subprocess.CompletedProcess | None:
    """Run a git command in `repo`. Returns None on any failure."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001 - session start must never fail closed
        return None


def check_stale_config_checkout() -> list[str]:
    """Return warnings when ~/.claude is behind origin/main on enforcement files.

    Offline, non-blocking, and silent on every error path.
    """
    try:
        if not (CONFIG_REPO / ".git").exists():
            return []

        # Offline: uses the locally-cached ref. Absent (fresh clone, never
        # fetched) -> non-zero rc -> silent, per the spec's test matrix.
        rev = _git(["rev-list", "--count", "HEAD..origin/main"], CONFIG_REPO)
        if rev is None or rev.returncode != 0:
            return []
        try:
            behind = int(rev.stdout.strip())
        except ValueError:
            return []
        if behind <= 0:
            return []

        # The load-bearing signal: does the delta touch enforcement?
        diff = _git(
            ["diff", "--name-only", "HEAD", "origin/main", "--", *ENFORCEMENT_PATHS],
            CONFIG_REPO,
        )
        changed: list[str] = []
        if diff is not None and diff.returncode == 0:
            changed = [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]

        if not changed and behind < PROMINENT_BEHIND:
            # Behind, but nothing enforcement-related changed and the gap is
            # small. Staying silent keeps this channel credible.
            return []

        lines = [
            (
                f"[claude-config] STALE CHECKOUT: ~/.claude is {behind} "
                f"commit(s) behind origin/main — the hooks that RUN are the "
                f"checked-out ones, not the merged ones."
            )
        ]

        if changed:
            shown = changed[:MAX_NAMED_FILES]
            more = len(changed) - len(shown)
            lines.append(
                ("  Enforcement files that differ from origin/main: ")
                + ", ".join(shown)
                + (f" (+{more} more)" if more > 0 else "")
            )
            lines.append(
                "  Enforcement you believe is active may be absent. Staged-spec "
                "state under hooks/staged/ is stale too — installed specs are "
                "removed on install, so this tree can show already-shipped specs "
                "as pending."
            )

        lines.append(
            "  Sync: `git -C ~/.claude status --short` first — a dirty tree with "
            "another session active makes repo_sync skip the rebase entirely "
            "(that early return is why this drift accumulates). Run /pr-fix to "
            "land or clear the dirty files, then fetch + fast-forward."
        )
        return ["\n".join(lines)]

    except Exception:  # noqa: BLE001 - session start must never fail closed
        return []
