# Relocated from hooks/ to bin/ on 2026-08-31. It has zero
# settings.json references: it is an operator CLI (--git-status /
# --pull), not a hook. Living in hooks/ made every hook census
# overcount, and an audit's own probe tripped on it by invoking it
# with a hook payload, where argparse correctly exits 2.
"""Refresh and report status of local clones of managed Example repos.

Usage:
    python sync-repo.py --git-status   # Git status of all managed repos
    python sync-repo.py --pull         # Fetch + rebase all managed repos to latest

History: this script previously also pushed the live ~/.claude tree to the
example-org/claude-code-architecture backup repo (--enumerate / --diff /
--push / --prune). That repo was retired on 2026-05-30 as a redundant content
mirror of claude-config, so the mirror-sync half was removed. Only the
multi-repo local-clone utilities below remain.
"""

import argparse
import re
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"

# Discovery configuration shared by BOTH --git-status and --pull: scan
# DISCOVERY_ROOTS for git repos whose `origin` remote points at one of
# MANAGED_ORGS (case-insensitive). New clones get picked up automatically —
# no static list to maintain. The two modes use the same discover_managed_repos()
# so they never disagree about which clones count as managed.
MANAGED_ORGS = [
    "example-org",
    "example-org",
    "example-apps-org",
    "example-labs-org",
    "example-labs-org",  # prototype-maturation org (ExampleService, etc.)
]

DISCOVERY_ROOTS = [
    HOME / "Documents" / "GitHub",          # primary clone dir
    CLAUDE_DIR,                             # ~/.claude is itself a clone (claude-config)
    HOME / "Documents" / "knowledge-base",  # standalone clone (claude-knowledge-base)
    HOME / "Documents" / "obsidian-infra",  # standalone clone
]

# Friendly-name overrides where the directory name differs from how we
# refer to the repo internally. Optional — only add when the directory
# name is misleading.
DISCOVERY_ALIASES = {
    "example-monorepo": "ExampleTarget",
    ".claude": "claude-config",
}


def _classify_dirty(porcelain: str) -> tuple[list[str], list[str]]:
    """Split `git status --porcelain` output into (modified, untracked) file lists.

    Pure string parser — no git I/O, so it's unit-testable. In porcelain v1,
    an untracked entry starts with '??'; everything else (' M', 'A ', 'MM',
    'R ', 'D ', etc.) is a tracked change ("modified"). The distinction is the
    whole point of this helper: untracked files (build junk, runtime state,
    logs) are cosmetically DIRTY but never block a rebase, whereas a tracked
    modification is real local work. Reporting them separately lets --git-status
    show a true triage signal and lets --pull safely advance untracked-only repos.
    """
    modified: list[str] = []
    untracked: list[str] = []
    # Split on newlines WITHOUT stripping the blob first — a leading ` M`/` D`
    # status code on the first entry would lose its significant leading space
    # to a blob-level .strip(). Trim only trailing newline noise per line.
    for line in porcelain.split("\n"):
        line = line.rstrip("\n\r")
        if not line.strip():
            continue
        if line.startswith("??"):
            untracked.append(line)
        else:
            modified.append(line)
    return modified, untracked


def _label(name: str, repo_dir: Path, name_counts: dict[str, int]) -> str:
    """Build a display label, disambiguating collisions with a ` @~/<path>` tag.

    When one friendly name maps to more than one clone (e.g. two checkouts of
    claude-config), a bare name is ambiguous — append the home-relative path so
    a PULL/SKIP pair for the same name stays readable. Shared by both modes so
    they label identically.
    """
    if name_counts.get(name, 0) <= 1:
        return name
    try:
        # Both sides resolved: macOS spells /tmp as /private/tmp after resolve(),
        # and a $HOME that traverses a symlink otherwise raises ValueError here.
        rel = str(repo_dir.resolve().relative_to(HOME.resolve())).replace("\\", "/")
        return f"{name} @~/{rel}"
    except ValueError:
        return f"{name} @{repo_dir}"


def cmd_git_status() -> list[str]:
    """Report git status of all managed repos discovered under DISCOVERY_ROOTS.

    Uses the SAME discovery as --pull (discover_managed_repos) so the two
    modes never disagree about which clones count as managed — there is no
    static list to drift out of sync. Reports branch, uncommitted-file
    count, unpushed (ahead) and stale (behind) commit counts. When the same
    friendly name maps to more than one clone (e.g. two checkouts of
    claude-config), a ` @~/<path>` tag is appended so duplicate clones are
    distinguishable.
    """
    repos = discover_managed_repos()
    if not repos:
        return ["  (no managed repos found — check DISCOVERY_ROOTS and MANAGED_ORGS)"]

    # Detect friendly-name collisions so duplicate clones are distinguishable.
    name_counts: dict[str, int] = {}
    for name, _ in repos:
        name_counts[name] = name_counts.get(name, 0) + 1

    lines = []
    for name, repo_dir in repos:
        label = _label(name, repo_dir, name_counts)

        try:
            # Current branch
            branch_result = _run_git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
            branch = (
                branch_result.stdout.strip()
                if branch_result.returncode == 0
                else "unknown"
            )

            # Uncommitted changes, split into tracked-modified vs untracked so
            # the report distinguishes real local work from cosmetic junk
            # (build output, runtime state) that never blocks a rebase.
            dirty_result = _run_git(repo_dir, "status", "--porcelain")
            modified, untracked = _classify_dirty(dirty_result.stdout)
            mod_n, unt_n = len(modified), len(untracked)

            # Ahead / behind upstream. `--left-right @{upstream}...HEAD` emits
            # "<behind>\t<ahead>"; skips cleanly when no upstream tracking ref.
            ahead = behind = 0
            counts = _run_git(
                repo_dir, "rev-list", "--count", "--left-right", "@{upstream}...HEAD"
            )
            if counts.returncode == 0 and counts.stdout.strip():
                parts = counts.stdout.split()
                if len(parts) == 2:
                    behind, ahead = int(parts[0]), int(parts[1])

            # Build status line — modified and untracked reported separately.
            issues = []
            if ahead > 0:
                issues.append(f"{ahead} unpushed commit{'s' if ahead > 1 else ''}")
            if behind > 0:
                issues.append(f"{behind} behind upstream")
            if mod_n > 0:
                issues.append(f"{mod_n} modified file{'s' if mod_n > 1 else ''}")
            if unt_n > 0:
                issues.append(f"{unt_n} untracked file{'s' if unt_n > 1 else ''}")

            if issues:
                lines.append(f"  DIRTY {label} ({branch}): {', '.join(issues)}")
                # Show modified first (real work), then untracked, capped at 5 total.
                shown = (modified + untracked)[:5]
                total = mod_n + unt_n
                for df in shown:
                    lines.append(f"        {df}")
                if total > 5:
                    lines.append(f"        ... and {total - 5} more")
                # Hygiene hint: dirty ONLY from untracked files means a rebase
                # is safe (--pull will advance it) and the noise is likely a
                # gitignore gap worth closing.
                if mod_n == 0 and unt_n > 0:
                    lines.append(
                        "        (untracked-only — safe to pull; consider a .gitignore rule)"
                    )
            else:
                lines.append(f"  OK    {label} ({branch}): clean, up to date")

        except Exception as e:
            lines.append(f"  ERROR {label}: {e}")

    return lines


_GITHUB_ORG_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)([^/]+)/", re.IGNORECASE
)


def _parse_origin_org(remote_url: str) -> str | None:
    """Extract the GitHub org name from a remote URL.

    Returns None for non-GitHub URLs. Handles both https:// and git@ forms,
    case-insensitively. The returned org name preserves the case from the
    URL — callers should case-fold for allowlist comparisons.
    """
    m = _GITHUB_ORG_RE.match(remote_url.strip())
    return m.group(1) if m else None


def discover_managed_repos() -> list[tuple[str, Path]]:
    """Walk DISCOVERY_ROOTS; return repos whose `origin` is in MANAGED_ORGS.

    Each entry is (friendly_name, path). friendly_name comes from
    DISCOVERY_ALIASES when set, otherwise the directory's basename.
    Sorted by friendly_name (case-insensitive) for stable output.
    Worktrees are included (`.git` may be a file pointing at the parent's
    worktrees/ dir); the existing pull logic skips them at the
    feature-branch / upstream-missing checks.
    """
    allowed = {org.lower() for org in MANAGED_ORGS}
    found: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    for root in DISCOVERY_ROOTS:
        if not root.exists():
            continue

        # CLAUDE_DIR is itself a git repo (claude-config); other roots are
        # parent directories whose immediate children are clones.
        if (root / ".git").exists():
            candidates = [root]
        else:
            candidates = [p for p in root.iterdir() if p.is_dir()]

        for repo_dir in candidates:
            if not (repo_dir / ".git").exists():
                continue
            try:
                resolved = repo_dir.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)

            # Read origin remote
            try:
                result = subprocess.run(
                    ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=CREATE_NO_WINDOW,
                )
            except (subprocess.SubprocessError, OSError):
                continue
            if result.returncode != 0:
                continue
            origin = result.stdout.strip()
            if not origin:
                continue

            org = _parse_origin_org(origin)
            if org is None or org.lower() not in allowed:
                continue

            dir_name = repo_dir.name if repo_dir.name else repo_dir.parent.name
            friendly = DISCOVERY_ALIASES.get(dir_name, dir_name)
            found.append((friendly, repo_dir))

    found.sort(key=lambda x: x[0].lower())
    return found


def _run_git(repo_dir: Path, *args, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command with Windows window suppression."""
    kwargs = dict(capture_output=True, text=True, timeout=timeout)
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return subprocess.run(["git", "-C", str(repo_dir)] + list(args), **kwargs)


def cmd_pull() -> int:
    """Fetch + rebase all managed repos to match GitHub. Skips dirty repos and feature branches.

    Returns the number of repos that FAILED, so callers can gate on it.

    Audit finding M8 (fixed 2026-07-26): this counted `errors` and printed them, then
    returned None, and `main()` ignored the result and always exited 0. A scheduled
    job or agent therefore could not distinguish a clean sync from a total failure --
    every outcome looked identical from the exit code.

    Repos are discovered by scanning DISCOVERY_ROOTS and filtering by
    MANAGED_ORGS — new clones are picked up automatically. No static list
    to maintain.
    """
    repos = discover_managed_repos()
    if not repos:
        print(
            "No managed repos found. Check DISCOVERY_ROOTS and MANAGED_ORGS in sync-repo.py."
        )
        # Not an error: an empty discovery set is a valid (if surprising) state.
        return 0

    print(f"Discovered {len(repos)} managed repo(s) in {len(DISCOVERY_ROOTS)} root(s).")
    updated = current = skipped = errors = 0

    # Detect friendly-name collisions so duplicate clones are distinguishable
    # (same pattern as cmd_git_status — without it, two claude-config clones
    # both print as bare "claude-config" and a PULL/SKIP pair is unreadable).
    name_counts: dict[str, int] = {}
    for name, _ in repos:
        name_counts[name] = name_counts.get(name, 0) + 1

    for name, repo_dir in repos:
        label = _label(name, repo_dir, name_counts)
        try:
            # Current branch
            cur_branch = _run_git(repo_dir, "branch", "--show-current")
            branch = (
                cur_branch.stdout.strip() if cur_branch.returncode == 0 else "unknown"
            )

            # Check for uncommitted changes FIRST — before any state-mutating
            # step (the --set-upstream-to below writes .git/config), so a dirty
            # repo is genuinely "left untouched" per the documented invariant.
            #
            # SKIP only on TRACKED modifications — those are real local work a
            # rebase could conflict with. Untracked-only dirtiness (build junk,
            # runtime state, logs) never blocks a clean rebase and survives it
            # untouched, so an untracked-only repo that is behind should still
            # advance. If a rare incoming commit WOULD collide with an untracked
            # path, git refuses and the existing `rebase --abort` path (below)
            # restores the exact prior state — so proceeding is safe by
            # construction, never a data-loss risk.
            dirty = _run_git(repo_dir, "status", "--porcelain")
            modified, untracked = _classify_dirty(dirty.stdout)
            if modified:
                dirty_count = len(modified)
                extra = f" (+{len(untracked)} untracked)" if untracked else ""
                print(
                    f"  SKIP  {label}: {dirty_count} modified file{'s' if dirty_count > 1 else ''}{extra}"
                )
                skipped += 1
                continue

            # Check if current branch has an upstream tracking ref
            upstream = _run_git(
                repo_dir, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"
            )
            if upstream.returncode != 0:
                # Try to auto-set upstream if origin/<branch> exists
                verify = _run_git(repo_dir, "rev-parse", "--verify", f"origin/{branch}")
                if verify.returncode == 0:
                    _run_git(
                        repo_dir, "branch", f"--set-upstream-to=origin/{branch}", branch
                    )
                    upstream_ref = f"origin/{branch}"
                else:
                    print(
                        f"  SKIP  {label}: branch '{branch}' has no upstream and origin/{branch} not found"
                    )
                    skipped += 1
                    continue
            else:
                upstream_ref = (
                    upstream.stdout.strip()
                )  # e.g. "origin/main" or "origin/master"

            # Get current HEAD before fetch
            before = _run_git(repo_dir, "rev-parse", "HEAD")
            before_sha = before.stdout.strip() if before.returncode == 0 else ""

            # Fetch + rebase using upstream ref.
            #
            # `--prune` is REQUIRED, not cosmetic (2026-08-05). A squash-merge
            # via `gh pr merge --delete-branch` removes the REMOTE branch while
            # the local clone keeps tracking it, so a clone parked on that
            # branch fails `git fetch origin <branch>` with "couldn't find
            # remote ref" -- a hard ERR that no amount of retrying clears. Nine
            # clones hit this at once on 2026-08-05 (all parked on a merged
            # chore/github-rename-you-s), and the failure is indistinguishable
            # from a real fetch problem in the output.
            #
            # Pruning FIRST makes the stale ref's absence explicit, so the
            # gone-upstream branch is reported as MERGED-AND-GONE (actionable:
            # switch to main) instead of ERR (looks broken). It also feeds
            # _prune_gone_branches() in session_start_modules/repo_sync.py,
            # whose docstring assumes "`git fetch --prune` (already run via the
            # rebase below)" -- that assumption was false on BOTH fetch paths.
            remote_name = upstream_ref.split("/")[0]  # "origin"
            remote_branch = "/".join(upstream_ref.split("/")[1:])  # "main" or "master"
            _run_git(repo_dir, "fetch", remote_name, "--prune")
            fetch = _run_git(repo_dir, "fetch", remote_name, remote_branch)
            if fetch.returncode != 0:
                # Distinguish "this branch was merged and deleted upstream"
                # from a genuine fetch failure. The first is expected hygiene
                # and tells the user exactly what to do; the second is an error.
                gone = _run_git(
                    repo_dir, "rev-parse", "--verify", "--quiet", upstream_ref
                )
                if gone.returncode != 0:
                    print(
                        f"  SKIP  {label}: branch '{branch}' was merged and deleted "
                        f"upstream ({upstream_ref} no longer exists) — "
                        f"switch to main to resume syncing"
                    )
                    skipped += 1
                    continue
                print(f"  ERR   {label}: fetch failed: {fetch.stderr.strip()}")
                errors += 1
                continue

            rebase = _run_git(repo_dir, "rebase", upstream_ref)
            if rebase.returncode != 0:
                # Abort failed rebase to leave repo clean
                _run_git(repo_dir, "rebase", "--abort")
                print(
                    f"  ERR   {label}: rebase failed (aborted): {rebase.stderr.strip()}"
                )
                errors += 1
                continue

            # Count commits pulled
            after = _run_git(repo_dir, "rev-parse", "HEAD")
            after_sha = after.stdout.strip() if after.returncode == 0 else ""

            if before_sha == after_sha:
                print(f"  OK    {label}: already up to date")
                current += 1
            else:
                count_result = _run_git(
                    repo_dir, "rev-list", "--count", f"{before_sha}..{after_sha}"
                )
                count = (
                    count_result.stdout.strip() if count_result.returncode == 0 else "?"
                )
                # Note when we advanced a repo that carried untracked files —
                # makes the "untracked doesn't block a pull" behavior visible.
                unt_note = (
                    f" ({len(untracked)} untracked file{'s' if len(untracked) > 1 else ''} preserved)"
                    if untracked
                    else ""
                )
                print(
                    f"  PULL  {label}: {count} new commit{'s' if count != '1' else ''}{unt_note}"
                )
                updated += 1

        except Exception as e:
            print(f"  ERR   {label}: {e}")
            errors += 1

    print(
        f"\nDone: {updated} updated, {current} current, {skipped} skipped, {errors} errors"
    )
    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Refresh / report status of local clones of managed Example repos"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--git-status", action="store_true", help="Git status of all managed repos"
    )
    group.add_argument(
        "--pull", action="store_true", help="Fetch + rebase all managed repos to latest"
    )

    args = parser.parse_args()

    if args.git_status:
        print("Git repos:")
        for line in cmd_git_status():
            print(line)
        return 0
    elif args.pull:
        failed = cmd_pull()
        if failed:
            print(
                f"\nFAILED: {failed} repo(s) did not sync. "
                "Exit code reflects the failure (M8, 2026-07-26).",
                file=sys.stderr,
            )
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
