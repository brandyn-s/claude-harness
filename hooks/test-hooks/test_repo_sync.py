"""Tests for session_start_modules/repo_sync.py stranded-checkpoint recovery.

repo_sync's session-start auto-checkpoint can leave HEAD on checkpoint/<ts>
when its checkout-back fails (Windows file lock, concurrent .git access).
Before 2026-05-29 the branch check early-returned forever, so main never
rebased and real work piled up uncommitted on the checkpoint branch.

These tests cover the recovery behavior:
  - clean tree on checkpoint/* -> auto-return to main
  - dirty tree on checkpoint/* -> warn loudly, DO NOT move (preserve edits)
  - other non-main branch (feat/*) -> unchanged early-return

It also covers [gone]-branch pruning (audit finding H3, 2026-07-26):
  - [gone] + unpushed local commit -> PRESERVED (was force-deleted)
  - [gone] + tip already merged    -> pruned, with a recovery ref
  - no accepted base present       -> not deletable
"""
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

from session_start_modules.repo_sync import (  # noqa: E402 -- resolves via the sys.path insert above
    _TRANSIENT_DIRT,
    _branch_work_is_upstream,
    _content_dirty_paths,
    _gone_branch_is_recoverable,
    _porcelain_paths,
    _prune_gone_branches,
    _sync_one_repo,
)


@pytest.fixture(autouse=True)
def _sole_occupancy():
    """Pin the concurrent-session interlock OFF for every test in this file.

    `_sync_one_repo` skips checkpoint+rebase when the tree is content-dirty AND
    `has_concurrent_sessions()` is true. That predicate reads LIVE process and
    marker state, so on a host with any other Claude session running, the four
    dirty-tree tests below measured the environment instead of the code and
    failed with "another session is active" (measured 2026-08-30: 3 concurrent
    sessions; the failures read as a broken hook while the hook was correct).

    Same class as tdd-mutation-testing item 27 — pin the dependency at its seam
    and assert the logic on the pinned input. Its own MonkeyPatch context keeps
    it independent of a test's `monkeypatch.undo()`. The interlock itself is
    still covered, by test_concurrent_session_skips_checkpoint_of_dirty_tree.
    """
    import session_start_modules.repo_sync as R

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(R, "has_concurrent_sessions", lambda *_a, **_k: False)
        yield


def _git(repo, *args, check=True):
    # 30s, not 10s: git ops in AV-scanned temp dirs (Windows) routinely
    # exceed 10s on the first touch of a new repo.
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check, timeout=30,
    )


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _branch(repo):
    return _git(repo, "branch", "--show-current").stdout.strip()


def test_clean_strand_recovers_to_main(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "checkpoint/20260101000000")
    assert _branch(repo) == "checkpoint/20260101000000"

    warnings = _sync_one_repo(repo, self_session_id="test")

    assert _branch(repo) == "main", "clean strand should auto-return to main"
    assert any("Recovered from stranded" in w for w in warnings), warnings


def test_dirty_strand_warns_and_preserves_work(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "checkpoint/20260101000000")
    # Real uncommitted work the recovery must NOT clobber.
    (repo / "wip.txt").write_text("uncommitted work\n", encoding="utf-8")

    warnings = _sync_one_repo(repo, self_session_id="test")

    assert _branch(repo) == "checkpoint/20260101000000", "must NOT leave the branch"
    assert (repo / "wip.txt").read_text(encoding="utf-8") == "uncommitted work\n"
    assert any("STRANDED" in w for w in warnings), warnings


def test_feature_branch_left_untouched(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat/some-work")

    warnings = _sync_one_repo(repo, self_session_id="test")

    assert _branch(repo) == "feat/some-work", "intentional work branch untouched"
    assert not any(
        "Recovered" in w or "STRANDED" in w for w in warnings
    ), warnings


# ── _porcelain_paths ───────────────────────────────────────────────────
# Regression cover for 2026-07-24: the artifact writer parsed
# `stdout.strip().split("\n")`, so the FIRST line's leading space (the X
# slot of a worktree-only ` M `) was stripped and the fixed `[3:]` slice
# ate one character of the path. The recovery artifact + session-start
# banner then advertised `opics/session-friction-patterns.md` — a path
# `git checkout <branch> -- <path>` cannot match.


def test_porcelain_first_line_worktree_modification_keeps_full_path():
    # The verbatim shape that produced the truncated artifact.
    assert _porcelain_paths(" M topics/session-friction-patterns.md\n") == [
        "topics/session-friction-patterns.md"
    ]


def test_porcelain_leading_space_on_every_status_code_that_has_one():
    # ' M' is not the only leading-space code: ' D', ' T', ' A' all hit
    # the same first-line strip. Each must keep its first path char.
    porcelain = " D gone.md\n T typechange.md\n A added.md\n"
    assert _porcelain_paths(porcelain) == ["gone.md", "typechange.md", "added.md"]


def test_porcelain_mixed_statuses_all_paths_intact():
    porcelain = (
        " M topics/first.md\n"
        "M  staged.md\n"
        "MM both.md\n"
        "?? untracked.md\n"
    )
    assert _porcelain_paths(porcelain) == [
        "topics/first.md",
        "staged.md",
        "both.md",
        "untracked.md",
    ]


def test_porcelain_strips_exactly_three_chars_from_every_line():
    # Property: porcelain's prefix is a FIXED width, so the parse must be
    # a uniform 3-char strip — never dependent on line position.
    lines = [" M a/b.md", "?? c.md", "R  old.md -> new.md"]
    assert _porcelain_paths("\n".join(lines) + "\n") == [
        line[3:] for line in lines
    ]


def test_porcelain_trailing_newline_yields_no_empty_entries():
    assert _porcelain_paths(" M only.md\n\n") == ["only.md"]


def test_porcelain_empty_stdout_is_empty_list():
    assert _porcelain_paths("") == []
    assert _porcelain_paths("\n") == []

# ==========================================================================
# [gone]-branch pruning — audit finding H3 (2026-07-26)
#
# _prune_gone_branches used to run `git branch -D` on every [gone] branch,
# justified by "gone-upstream means GitHub already accepted and removed the
# remote -- local-only divergent history is not possible". That is FALSE:
# [gone] is a fact about the UPSTREAM REF, not local history, so any commit
# made after the last push is invisible to it. Reproduced on a disposable
# repo: a [gone] branch with one local-only commit was force-deleted, leaving
# reflog as the only path back.
# ==========================================================================

def git(cwd: Path, *args: str):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def make_git(cwd: Path):
    """Return a `_git(args)` callable shaped like repo_sync's."""
    def _git(args, _c=cwd):
        return git(_c, *args)

    return _git


@pytest.fixture()
def repo(tmp_path):
    """A clone with `main` pushed, plus a `feature` branch whose remote is deleted."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    # `-b main` is load-bearing, not cosmetic. Without it `git init --bare` takes
    # the branch name from init.defaultBranch, which is UNSET on the CI runner, so
    # the bare repo's HEAD points at refs/heads/master while the only ref that ever
    # gets pushed is main. A later `git clone` of that repo warns "remote HEAD
    # refers to nonexistent ref, unable to checkout", lands on master, and its
    # `git push origin main` dies with "src refspec main does not match any" --
    # silently, because git() below does not pass check=True. origin/main then
    # never advances, so a test that means "the work tree is BEHIND" actually sets
    # up "the work tree is level", and any assertion about catching up fails with
    # an empty warnings list. Measured 2026-08-15: passed on macOS
    # (init.defaultBranch=main) and failed on CI for exactly this reason.
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True,
                   capture_output=True)
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    git(work, "config", "commit.gpgsign", "false")

    (work / "f.txt").write_text("base\n", encoding="utf-8")
    git(work, "add", "f.txt")
    git(work, "commit", "-qm", "base")
    git(work, "branch", "-M", "main")
    git(work, "push", "-q", "-u", "origin", "main")
    return work


def make_gone_feature(work: Path, *, local_only: bool):
    """Create `feature`, push it, optionally add a LOCAL-ONLY commit, then delete remote."""
    git(work, "checkout", "-qb", "feature")
    (work / "g.txt").write_text("pushed\n", encoding="utf-8")
    git(work, "add", "g.txt")
    git(work, "commit", "-qm", "pushed commit")
    git(work, "push", "-q", "-u", "origin", "feature")

    local_sha = None
    if local_only:
        (work / "h.txt").write_text("local only\n", encoding="utf-8")
        git(work, "add", "h.txt")
        git(work, "commit", "-qm", "LOCAL ONLY never pushed")
        local_sha = git(work, "rev-parse", "HEAD").stdout.strip()

    # Simulate `gh pr merge --squash --delete-branch`: remote branch disappears.
    git(work, "push", "-q", "origin", "--delete", "feature")
    git(work, "checkout", "-q", "main")
    git(work, "fetch", "-q", "--prune")
    return local_sha


def track_state(work: Path, branch: str = "feature") -> str:
    return git(
        work, "for-each-ref", "--format=%(upstream:track)", f"refs/heads/{branch}"
    ).stdout.strip()


def branch_exists(work: Path, branch: str) -> bool:
    return git(work, "rev-parse", "--verify", "--quiet", branch).returncode == 0


# ---------------------------------------------------------------------------
# THE DATA-LOSS FIXTURE
# ---------------------------------------------------------------------------
def test_gone_branch_with_local_only_commit_is_preserved(repo):
    """THE H3 FIX. A [gone] branch carrying unpushed work must NOT be deleted."""
    local_sha = make_gone_feature(repo, local_only=True)
    assert local_sha, "fixture must produce a local-only commit"
    assert "[gone]" in track_state(repo), "fixture must actually produce [gone]"

    deleted = _prune_gone_branches(make_git(repo))

    assert deleted == 0, "a branch with unpushed commits must not be pruned"
    assert branch_exists(repo, "feature"), "the branch must survive"
    # The local-only commit must still be reachable by a NAME, not just reflog.
    containing = git(repo, "branch", "--contains", local_sha).stdout
    assert "feature" in containing


def test_gone_marker_alone_does_not_imply_merged(repo):
    """Pins the false premise: [gone] is true while the tip is NOT in main."""
    make_gone_feature(repo, local_only=True)
    assert "[gone]" in track_state(repo)
    merged = git(repo, "merge-base", "--is-ancestor", "feature", "main").returncode == 0
    assert merged is False, "[gone] must not be read as evidence of merge"
    assert _gone_branch_is_recoverable(make_git(repo), "feature") is False


# ---------------------------------------------------------------------------
# the legitimate cleanup path must still work
# ---------------------------------------------------------------------------
def test_gone_branch_fully_merged_is_pruned(repo):
    """A [gone] branch whose tip IS in main is safe to delete -- and still is."""
    make_gone_feature(repo, local_only=False)
    # Land the branch's commit on main so the tip becomes an ancestor.
    git(repo, "merge", "--no-edit", "-q", "feature")
    git(repo, "push", "-q", "origin", "main")
    assert _gone_branch_is_recoverable(make_git(repo), "feature") is True

    deleted = _prune_gone_branches(make_git(repo))
    assert deleted == 1
    assert not branch_exists(repo, "feature")


def test_pruned_branch_leaves_a_recovery_ref(repo):
    """Even a correct deletion must be undoable by name."""
    make_gone_feature(repo, local_only=False)
    tip = git(repo, "rev-parse", "feature").stdout.strip()
    git(repo, "merge", "--no-edit", "-q", "feature")
    git(repo, "push", "-q", "origin", "main")

    assert _prune_gone_branches(make_git(repo)) == 1
    rec = git(repo, "rev-parse", "--verify", "--quiet",
              "refs/gone-recovery/feature").stdout.strip()
    assert rec == tip, "recovery ref must point at the deleted tip"


def test_no_gone_branches_is_a_noop(repo):
    assert _prune_gone_branches(make_git(repo)) == 0


def test_main_and_master_are_never_pruned(repo):
    """A protected-name guard regression check."""
    make_gone_feature(repo, local_only=False)
    git(repo, "merge", "--no-edit", "-q", "feature")
    _prune_gone_branches(make_git(repo))
    assert branch_exists(repo, "main"), "main must never be pruned"


def test_recoverable_check_tolerates_a_missing_base(tmp_path):
    """With NO accepted base present, nothing can prove recoverability -> False.

    Built by renaming the initial branch away from main/master, so neither
    main, master, origin/main nor origin/master exists. The branch must NOT be
    considered deletable just because the check has nothing to compare against --
    absence of evidence is not evidence of merge.
    """
    work = tmp_path / "solo"
    work.mkdir()
    git(work, "init", "-q")
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("x\n", encoding="utf-8")
    git(work, "add", "a.txt")
    git(work, "commit", "-qm", "only")
    # Rename the default branch so no accepted base name resolves.
    git(work, "branch", "-M", "trunk")
    git(work, "checkout", "-qb", "odd")
    (work / "b.txt").write_text("diverged\n", encoding="utf-8")
    git(work, "add", "b.txt")
    git(work, "commit", "-qm", "diverged from trunk")

    for base in ("main", "master", "origin/main", "origin/master"):
        assert git(work, "rev-parse", "--verify", "--quiet", base).returncode != 0, base
    assert _gone_branch_is_recoverable(make_git(work), "odd") is False


def test_branch_at_the_same_commit_as_main_is_deletable(tmp_path):
    """A zero-divergence branch IS contained in main, so deleting it loses nothing.

    Documents the boundary: the guard asks "is this tip already reachable from an
    accepted base?", not "does this branch have a distinct name". A branch that
    never committed anything past main is correctly safe.
    """
    work = tmp_path / "same"
    work.mkdir()
    git(work, "init", "-q")
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("x\n", encoding="utf-8")
    git(work, "add", "a.txt")
    git(work, "commit", "-qm", "only")
    git(work, "branch", "-M", "main")
    git(work, "checkout", "-qb", "tip-equal")
    assert _gone_branch_is_recoverable(make_git(work), "tip-equal") is True


def test_mixed_repo_prunes_only_the_merged_branch(repo):
    """Two [gone] branches, one safe and one not: exactly one is deleted."""
    # safe branch
    make_gone_feature(repo, local_only=False)
    git(repo, "merge", "--no-edit", "-q", "feature")
    git(repo, "push", "-q", "origin", "main")

    # unsafe branch with unpushed work
    git(repo, "checkout", "-qb", "risky")
    (repo / "r.txt").write_text("pushed\n", encoding="utf-8")
    git(repo, "add", "r.txt")
    git(repo, "commit", "-qm", "pushed")
    git(repo, "push", "-q", "-u", "origin", "risky")
    (repo / "r2.txt").write_text("local only\n", encoding="utf-8")
    git(repo, "add", "r2.txt")
    git(repo, "commit", "-qm", "LOCAL ONLY")
    git(repo, "push", "-q", "origin", "--delete", "risky")
    git(repo, "checkout", "-q", "main")
    git(repo, "fetch", "-q", "--prune")

    deleted = _prune_gone_branches(make_git(repo))
    assert deleted == 1, "only the merged branch should go"
    assert not branch_exists(repo, "feature")
    assert branch_exists(repo, "risky"), "unmerged branch must survive"


# ---------------------------------------------------------------------------
# 2026-08-05: the fetch paths must PRUNE, and a merged-and-deleted branch must
# be reported as merged-and-gone, not as a hard fetch failure.
#
# These tests deliberately do NOT hand-run `git fetch --prune` in setup. Every
# pre-existing prune test above does (lines ~220, ~368), which is exactly why
# the production gap stayed invisible: the harness supplied the one step
# neither fetch path performed. A test that pre-prunes cannot detect a
# producer that never prunes.
# ---------------------------------------------------------------------------


def _stale_tracking_ref_repo(tmp_path):
    """Clone parked on a branch whose REMOTE was deleted, with NO prune run.

    Reproduces the 2026-08-05 state of nine clones: local `feature` still has
    a live-looking `origin/feature` tracking ref even though the remote branch
    is gone, so a bare `git fetch origin feature` hard-fails.
    """
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    # `-b main` is load-bearing, not cosmetic. Without it `git init --bare` takes
    # the branch name from init.defaultBranch, which is UNSET on the CI runner, so
    # the bare repo's HEAD points at refs/heads/master while the only ref that ever
    # gets pushed is main. A later `git clone` of that repo warns "remote HEAD
    # refers to nonexistent ref, unable to checkout", lands on master, and its
    # `git push origin main` dies with "src refspec main does not match any" --
    # silently, because git() below does not pass check=True. origin/main then
    # never advances, so a test that means "the work tree is BEHIND" actually sets
    # up "the work tree is level", and any assertion about catching up fails with
    # an empty warnings list. Measured 2026-08-15: passed on macOS
    # (init.defaultBranch=main) and failed on CI for exactly this reason.
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True,
                   capture_output=True)
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    git(work, "config", "commit.gpgsign", "false")
    # Ensure the local clone never prunes behind our back.
    git(work, "config", "fetch.prune", "false")

    (work / "f.txt").write_text("base\n", encoding="utf-8")
    git(work, "add", "f.txt")
    git(work, "commit", "-qm", "base")
    git(work, "branch", "-M", "main")
    git(work, "push", "-q", "-u", "origin", "main")

    git(work, "checkout", "-qb", "feature")
    (work / "g.txt").write_text("work\n", encoding="utf-8")
    git(work, "add", "g.txt")
    git(work, "commit", "-qm", "feature work")
    git(work, "push", "-q", "-u", "origin", "feature")

    # Squash-merge the content onto main under a NEW sha, then delete the
    # remote branch -- precisely `gh pr merge --squash --delete-branch`.
    git(work, "checkout", "-q", "main")
    git(work, "merge", "--squash", "feature")
    git(work, "commit", "-qm", "feature work (#1)")
    git(work, "push", "-q", "origin", "main")

    # CRITICAL: delete the remote branch from a DIFFERENT clone, never from
    # `work`. `git push origin --delete` also drops the PUSHING clone's own
    # remote-tracking ref, so deleting from `work` would leave no stale ref and
    # the fixture would silently not reproduce the bug (it would assert against
    # an already-clean state). In production the deletion happens on GitHub via
    # the merge queue, so the local clone keeps a tracking ref pointing at a
    # branch that no longer exists -- that divergence IS the defect.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(other), "push", "-q", "origin",
                    "--delete", "feature"], check=True, capture_output=True)

    git(work, "checkout", "-q", "feature")
    return work


def test_stale_tracking_ref_survives_until_something_prunes(tmp_path):
    """The precondition: without --prune the tracking ref lingers and fetch fails.

    This is the mechanism assertion. If it ever stops holding, the two tests
    below are passing for the wrong reason.
    """
    work = _stale_tracking_ref_repo(tmp_path)

    # The remote branch is gone...
    heads = git(work, "ls-remote", "--heads", "origin", "feature")
    assert heads.stdout.strip() == "", "remote branch should be deleted"

    # ...but the local tracking ref is still present, because nothing pruned.
    ref = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "--verify", "--quiet",
         "origin/feature"],
        capture_output=True, text=True,
    )
    assert ref.returncode == 0, "stale tracking ref must linger without --prune"

    # And a bare per-branch fetch hard-fails -- the observed 2026-08-05 error.
    bare = subprocess.run(
        ["git", "-C", str(work), "fetch", "origin", "feature"],
        capture_output=True, text=True,
    )
    assert bare.returncode != 0
    assert "couldn't find remote ref" in bare.stderr


def test_prune_clears_the_stale_ref_and_marks_branch_gone(tmp_path):
    """`fetch --prune` is what makes _prune_gone_branches reachable at all."""
    work = _stale_tracking_ref_repo(tmp_path)

    # Before pruning: no `[gone]` marker exists, so prune logic cannot fire.
    before = git(work, "for-each-ref",
                 "--format=%(refname:short) %(upstream:track)", "refs/heads/")
    assert "[gone]" not in before.stdout, (
        "without --prune there is no [gone] marker -- this is why "
        "_prune_gone_branches was inert in production"
    )

    subprocess.run(["git", "-C", str(work), "fetch", "origin", "--prune"],
                   capture_output=True, text=True, check=True)

    after = git(work, "for-each-ref",
                "--format=%(refname:short) %(upstream:track)", "refs/heads/")
    assert "[gone]" in after.stdout, "--prune must mark the branch [gone]"

    gone = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "--verify", "--quiet",
         "origin/feature"],
        capture_output=True, text=True,
    )
    assert gone.returncode != 0, "stale tracking ref must be pruned away"


def test_sync_one_repo_recovers_a_fully_merged_feature_branch(tmp_path):
    """A merged-and-deleted feature branch now auto-returns to main and syncs.

    SUPERSEDES `test_sync_one_repo_leaves_a_feature_branch_untouched`
    (2026-08-06). That test asserted the unconditional early-return and said, in
    its own docstring, "if someone later makes this path reachable on a feature
    branch, this test fails and points at the missing merged-and-gone handling."
    This is that change, so the tripwire is being answered rather than silenced
    -- the assertions get STRONGER (a completed recovery, not an absence).

    Why the behaviour changed: the silent early-return is how a checkout gets
    stranded indefinitely. Measured 2026-08-06, ~/.claude sat on a merged
    `docs/*` branch 14 commits behind origin/main, and those 14 included the PR
    whose purpose was fixing three SessionStart checker false positives -- so
    the banner was being emitted BY the stale checkers it had already fixed.

    This fixture IS the 2026-08-05 nine-clone state (squash-merged, remote
    branch deleted, stale tracking ref, `git fetch origin feature` hard-fails),
    so those clones now self-recover instead of reporting a hard fetch error.
    """
    work = _stale_tracking_ref_repo(tmp_path)
    assert _branch_name(work) == "feature"

    warnings = _sync_one_repo(work, "testrepo")

    assert _branch_name(work) == "main", (
        f"a fully-merged branch should return to main, got warnings: {warnings}"
    )
    assert any("fully-merged branch" in w for w in warnings), warnings
    # The branch itself must SURVIVE -- recovery moves HEAD, it does not delete
    # work. Ancestry says "unmerged" on a squash-merge repo, so the prune guard
    # correctly declines to remove it.
    assert branch_exists(work, "feature"), "recovery must not delete the branch"


def test_merged_branch_with_dirty_tree_warns_and_stays_put(tmp_path):
    """TODAY'S EXACT CASE (2026-08-06): merged branch + another session's edits.

    The branch is done, but the working tree is shared with live sessions, so a
    checkout would move it under them. Warn with the consequence named -- local
    main cannot advance, so the CHECKED-OUT hooks go stale -- and touch nothing.
    """
    work = _stale_tracking_ref_repo(tmp_path)
    (work / "someone_elses_wip.txt").write_text("in flight\n", encoding="utf-8")

    warnings = _sync_one_repo(work, "testrepo")

    assert _branch_name(work) == "feature", "must NOT move a shared dirty tree"
    assert (work / "someone_elses_wip.txt").read_text(encoding="utf-8") == "in flight\n"
    assert any("block the return to main" in w for w in warnings), warnings
    # The warning must name the CONSEQUENCE, not just the state -- a bare
    # "you are on a branch" line already exists elsewhere and was ignored.
    assert any("go stale" in w for w in warnings), warnings


def test_a_freshly_created_branch_is_not_treated_as_merged(tmp_path):
    """Zero unique commits != merged. Deliberate branching must be respected.

    `git cherry` reports nothing for BOTH a merged branch and a brand-new one,
    so the helper must distinguish them. If it did not, a user who just ran
    `git checkout -b feat/x` would be yanked back to main at the next session
    start -- destroying the intent they just expressed.
    """
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat/brand-new")

    assert _branch_work_is_upstream(make_git(repo), "feat/brand-new") is False

    warnings = _sync_one_repo(repo, self_session_id="test")
    assert _branch(repo) == "feat/brand-new", "must not switch off a new branch"
    assert not any("fully-merged" in w for w in warnings), warnings


def test_unmerged_commits_are_never_reported_upstream(tmp_path):
    """A branch with real unpushed work must read as NOT upstream, and stay silent."""
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat/real-work")
    (repo / "new.txt").write_text("unmerged\n", encoding="utf-8")
    _git(repo, "add", "new.txt")
    _git(repo, "commit", "-q", "-m", "genuinely unmerged")

    assert _branch_work_is_upstream(make_git(repo), "feat/real-work") is False

    warnings = _sync_one_repo(repo, self_session_id="test")
    assert _branch(repo) == "feat/real-work"
    # Silent, exactly as before -- an in-progress branch is normal, and warning
    # every session in every repo would be noise.
    assert not any("fully-merged" in w for w in warnings), warnings


def test_ancestry_says_unmerged_where_cherry_says_merged(tmp_path):
    """Pins WHY `git cherry` is used instead of `merge-base --is-ancestor`.

    Measured 2026-08-06 on the real branch docs/ssr-batch-diagnostics (merged as
    claude-config #1905): ancestry FALSE, cherry `-`. If this ever stops holding,
    the helper's whole justification is void and it should be revisited.
    """
    work = _stale_tracking_ref_repo(tmp_path)

    ancestor = git(work, "merge-base", "--is-ancestor", "feature", "origin/main")
    assert ancestor.returncode != 0, (
        "squash-merge should make ancestry FALSE -- if this passes, the repo is "
        "no longer squash-merging and the cherry-based helper can be simplified"
    )
    assert _branch_work_is_upstream(make_git(work), "feature") is True


# ── the concurrent-session gate must key on CONTENT dirt ────────────────
# A gate whose signal has a nonzero steady-state floor is permanently
# ENGAGED while its enabling flag still reads "on" -- it fails SILENT.
# Measured 2026-08-06: ~/Documents/knowledge-base was skipped at every
# session start on the strength of exactly one hook-rendered file.

def test_transient_only_dirt_does_not_engage_the_concurrent_gate():
    """A tree dirty ONLY with hook-rendered artifacts has no content dirt."""
    porcelain = (
        " M topics/session-friction-patterns.md\n"
        " M settings.json\n"
        "?? .session-active/abc.json\n"
    )
    assert _content_dirty_paths(porcelain) == []


def test_real_work_still_engages_the_concurrent_gate():
    """Negative control: without this, the fix above could pass vacuously."""
    porcelain = (
        " M topics/session-friction-patterns.md\n"
        " M skills/cc-monitor/SKILL.md\n"
    )
    assert _content_dirty_paths(porcelain) == ["skills/cc-monitor/SKILL.md"]


# The two above test the HELPER. These two test the GATE ITSELF -- a helper test
# validates composition logic while stubbing the seam the fix actually lives in,
# so without these the wiring could be reverted with the suite still green.

def test_gate_does_not_engage_when_only_transients_are_dirty(tmp_path, monkeypatch):
    """The KB case: a permanently-dirty rendered artifact must not hold the gate."""
    import session_start_modules.repo_sync as R

    repo = _init_repo(tmp_path)
    (repo / "settings.json").write_text('{"hook": "rendered"}\n', encoding="utf-8")
    # monkeypatch (not a bare setattr) so sibling test files cannot inherit this
    # stub via the shared sys.modules object -- tdd-quality.md item 15.
    monkeypatch.setattr(R, "has_concurrent_sessions", lambda _sid: True)

    warnings = _sync_one_repo(repo, self_session_id="test")

    assert not any("Skipped auto-checkpoint" in w for w in warnings), (
        f"transient-only dirt must not engage the interlock, got: {warnings}"
    )


def test_gate_still_engages_on_real_content_dirt(tmp_path, monkeypatch):
    """Negative control for the wiring: the interlock must still protect work."""
    import session_start_modules.repo_sync as R

    repo = _init_repo(tmp_path)
    (repo / "real_work.txt").write_text("another session's edits\n", encoding="utf-8")
    monkeypatch.setattr(R, "has_concurrent_sessions", lambda _sid: True)

    warnings = _sync_one_repo(repo, self_session_id="test")

    assert any("Skipped auto-checkpoint" in w for w in warnings), warnings
    assert (repo / "real_work.txt").read_text(encoding="utf-8") == (
        "another session's edits\n"
    ), "the gate exists to preserve this file"


def test_transient_dirt_covers_sibling_copies():
    """Pin the three copies of this classification against drift.

    The same "hook-managed / per-machine, so not real dirt" list exists in
    `hooks/worktree-enforcement.py` (_TRANSIENT_MARKERS) and
    `hooks/post-merge-sync.py` (_is_repo_dirty's `transients`). Two copies of a
    classification let its consumers diverge silently, so this asserts
    _TRANSIENT_DIRT is a SUPERSET of both -- a new transient added to either
    sibling fails here until it is added to the canonical tuple.
    """
    import importlib.util
    import re

    def _load(name, filename):
        spec = importlib.util.spec_from_file_location(name, HOOKS / filename)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    wt = _load("wt_enforcement_transients", "worktree-enforcement.py")
    for marker in wt._TRANSIENT_MARKERS:
        assert marker in _TRANSIENT_DIRT, (
            f"worktree-enforcement.py treats {marker!r} as transient but "
            f"repo_sync's _TRANSIENT_DIRT does not -- the gate will engage on it"
        )

    # post-merge-sync.py's list is a local inside _is_repo_dirty, so read it
    # from source rather than importing (importing runs its module body).
    pms = (HOOKS / "post-merge-sync.py").read_text(encoding="utf-8")
    block = re.search(r"transients = \[(.*?)\]", pms, re.DOTALL)
    assert block, "post-merge-sync.py's transients list moved; update this pin"
    for marker in re.findall(r'"([^"]+)"', block.group(1)):
        assert marker in _TRANSIENT_DIRT, (
            f"post-merge-sync.py treats {marker!r} as transient but "
            f"repo_sync's _TRANSIENT_DIRT does not"
        )


def _branch_name(work: Path) -> str:
    return git(work, "branch", "--show-current").stdout.strip()


# --- main is fast-forward-only (2026-08-15) -------------------------------
#
# The session-start sync used to run `git rebase origin/main` unconditionally.
# On a checkout whose local main is content-ahead of upstream that replays the
# whole divergent arc, conflicts, and aborts -- every boot. Measured on the
# live host: `git cherry origin/main HEAD` = +276/-0. The damaging part is the
# WINDOW: while the rebase runs, tracked files hold conflict markers, and
# session start is exactly when other sessions read ambient rules.


def _second_clone(remote: Path, dest: Path) -> Path:
    """A second clone, used to advance `origin/main` behind the work tree's back."""
    subprocess.run(["git", "clone", "-q", str(remote), str(dest)],
                   check=True, capture_output=True)
    # Fail LOUDLY if the clone did not land on main. `git clone` exits 0 even when
    # the remote HEAD dangles -- it only warns -- and every later step here is
    # unchecked, so without this assert a broken remote degrades into a test that
    # asserts against a work tree which was never actually made to fall behind.
    # That is the shape that made two tests pass on macOS and fail on CI.
    landed = git(dest, "branch", "--show-current").stdout.strip()
    assert landed == "main", (
        f"second clone landed on {landed!r}, not 'main' -- the bare remote's HEAD "
        f"is probably dangling (init.defaultBranch unset and no `-b main` on "
        f"`git init --bare`). Pushes to main from this clone would fail silently."
    )
    git(dest, "config", "user.email", "o@o")
    git(dest, "config", "user.name", "o")
    git(dest, "config", "commit.gpgsign", "false")
    return dest


def test_main_fast_forwards_when_local_has_no_unique_commits(tmp_path, repo):
    """The ordinary catch-up must still work: behind-only main fast-forwards."""
    other = _second_clone(tmp_path / "remote.git", tmp_path / "other")
    (other / "upstream.txt").write_text("from upstream\n", encoding="utf-8")
    git(other, "add", "upstream.txt")
    git(other, "commit", "-qm", "upstream commit")
    git(other, "push", "-q", "origin", "main")

    before = git(repo, "rev-parse", "HEAD").stdout.strip()
    _sync_one_repo(repo, self_session_id="test")
    after = git(repo, "rev-parse", "HEAD").stdout.strip()

    assert after != before, "a behind-only main should fast-forward"
    assert (repo / "upstream.txt").exists(), "upstream commit should be present"
    assert not (repo / ".git" / "rebase-merge").exists()


def test_divergent_main_is_skipped_and_never_leaves_conflict_markers(tmp_path, repo):
    """A divergent main must be SKIPPED, not replayed.

    Regression for the unconditional rebase. Both sides touch the same file, so
    the old code path conflicted; this asserts the tree is left pristine and no
    rebase state survives -- i.e. no window in which a tracked file holds
    `<<<<<<<` for another session to read.
    """
    other = _second_clone(tmp_path / "remote.git", tmp_path / "other")
    (other / "f.txt").write_text("upstream side\n", encoding="utf-8")
    git(other, "add", "f.txt")
    git(other, "commit", "-qm", "upstream edit")
    git(other, "push", "-q", "origin", "main")

    # A local-only commit on main touching the SAME file -> guaranteed conflict.
    (repo / "f.txt").write_text("local side\n", encoding="utf-8")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-qm", "local-only edit")
    local_head = git(repo, "rev-parse", "HEAD").stdout.strip()

    warnings = _sync_one_repo(repo, self_session_id="test")

    assert git(repo, "rev-parse", "HEAD").stdout.strip() == local_head, \
        "divergent main must not be moved"
    assert not (repo / ".git" / "rebase-merge").exists(), \
        "no rebase state may survive the sync"
    assert "<<<<<<<" not in (repo / "f.txt").read_text(encoding="utf-8"), \
        "no conflict markers may be left in a tracked file"
    assert any("cannot be fast-forwarded" in w for w in warnings), warnings
    assert any("git checkout origin/main --" in w for w in warnings), \
        "the warning must name the surgical-deploy alternative"


# ==========================================================================
# INTERRUPTED-REBASE RECOVERY (2026-08-15)
#
# ~/.claude sat wedged for ~20 minutes: .git/rebase-merge/ at msgnum=1 of
# end=276 and settings.json carrying 4 raw conflict blocks, so every new
# session read an UNPARSEABLE live config. Nothing reported it, and the
# existing recovery could not clear it: it keys on `--diff-filter=U`, and a
# KILLED git has written worktree conflict markers but NOT unmerged index
# entries. Measured 0 unmerged files while the rebase state dir existed.
#
# #1998 stopped this module from CREATING that state (the path fast-forwards
# and never rebases). This covers the other half — a wedge arriving from an
# external source, which after #1998 is the only way to reach it.
#
# The first assertion below pins the BLIND SPOT deliberately. Without it the
# test would exercise the pre-existing unmerged-files path and would pass with
# the new recovery reverted. Same lesson this module already learned with
# _prune_gone_branches (2026-08-05): a test must not pre-establish the very
# precondition whose absence was the defect.
# ==========================================================================

def _wedge_rebase_without_unmerged_index(work: Path) -> None:
    """Leave `work` mid-rebase with ZERO unmerged index entries.

    Reproduces the observed shape using nothing but git: start a conflicting
    rebase (which does create unmerged entries), then mark the conflict resolved
    in the INDEX while leaving the rebase itself in progress. Observable state
    then matches a killed git — rebase state dir present, `--diff-filter=U`
    empty.
    """
    git(work, "checkout", "-q", "-b", "diverge")
    (work / "f.txt").write_text("theirs\n", encoding="utf-8")
    git(work, "commit", "-qam", "diverge side")
    git(work, "checkout", "-q", "main")
    (work / "f.txt").write_text("ours\n", encoding="utf-8")
    git(work, "commit", "-qam", "main side")
    git(work, "rebase", "diverge")   # conflicts and stops
    git(work, "add", "f.txt")        # clears the unmerged INDEX entry


def _rebase_state_present(work: Path) -> bool:
    for state in ("rebase-merge", "rebase-apply"):
        probe = git(work, "rev-parse", "--git-path", state)
        if probe.returncode != 0:
            continue
        path = Path(probe.stdout.strip())
        if not path.is_absolute():
            path = work / path
        if path.exists():
            return True
    return False


def test_interrupted_rebase_is_detected_by_state_dir_not_unmerged_files(repo):
    _wedge_rebase_without_unmerged_index(repo)

    assert _rebase_state_present(repo), "fixture failed to leave a rebase in progress"
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()
    assert unmerged == "", (
        "fixture must reproduce the BLIND SPOT — a rebase in progress with ZERO "
        f"unmerged index entries. Got: {unmerged!r}"
    )

    warnings = _sync_one_repo(repo)

    assert not _rebase_state_present(repo), (
        "rebase state survived _sync_one_repo — the interrupted-rebase recovery "
        f"did not fire. warnings={warnings!r}"
    )
    assert any("interrupted rebase" in w.lower() for w in warnings), (
        f"the recovery must REPORT what it did, not clear silently. warnings={warnings!r}"
    )
    # And the tree is usable again: no conflict markers left in the tracked file.
    assert "<<<<<<<" not in (repo / "f.txt").read_text(encoding="utf-8")


# ==========================================================================
# CHECKPOINT ONLY WHEN A FAST-FORWARD IS ACTUALLY GOING TO HAPPEN (2026-08-15)
#
# The auto-checkpoint COMMITS the working tree onto checkpoint/<ts> and checks
# out back, which CLEARS the tree. It exists to protect that work across a
# branch-moving operation. After #1998 the only branch-moving operation is a
# fast-forward, and a divergent branch never gets one.
#
# The order used to be checkpoint -> fetch -> decide, so on a permanently
# divergent checkout every lone session start paid the full checkpoint cost to
# protect a fast-forward that was skipped 126 lines later. Measured: ~/.claude
# is 278 commits ahead, so that is its steady state. It also reverted a surgical
# per-path deploy of #1998/#1999 -- the deployed files read as dirt, were
# committed to a checkpoint branch, and the live hook silently returned to the
# pre-fix version.
# ==========================================================================

def _checkpoint_branches(work: Path) -> list[str]:
    out = git(work, "branch", "--list", "checkpoint/*").stdout
    return [ln.strip().lstrip("* ").strip() for ln in out.splitlines() if ln.strip()]


def test_divergent_repo_is_not_checkpointed(repo):
    """A divergent branch must not have its working tree committed away.

    Asserts the tree is PRESERVED and no checkpoint branch is created. Checking
    only for the warning would pass while the checkpoint still ran.
    """
    # Diverge: one local commit origin does not have.
    (repo / "local_only.txt").write_text("ahead\n", encoding="utf-8")
    git(repo, "add", "local_only.txt")
    git(repo, "commit", "-qm", "local only")
    # And leave real dirt in the tree, which is what the checkpoint would eat.
    (repo / "f.txt").write_text("uncommitted work\n", encoding="utf-8")

    assert _checkpoint_branches(repo) == []

    warnings = _sync_one_repo(repo)

    assert _checkpoint_branches(repo) == [], (
        "a divergent repo must NOT be checkpointed -- the checkpoint can only "
        f"protect a fast-forward, which will never happen here. warnings={warnings!r}"
    )
    assert (repo / "f.txt").read_text(encoding="utf-8") == "uncommitted work\n", (
        "the dirty working tree must be preserved, not committed away and cleared"
    )
    assert git(repo, "branch", "--show-current").stdout.strip() == "main", (
        "must still be on main, not stranded on a checkpoint branch"
    )
    assert any("cannot be fast-forwarded" in w for w in warnings), (
        f"the skip must still be reported. warnings={warnings!r}"
    )


def test_concurrent_session_skips_checkpoint_of_dirty_tree(repo, monkeypatch):
    """The interlock the autouse fixture pins OFF must still work when ON.

    Without this, pinning `has_concurrent_sessions` to False for the file would
    delete the coverage rather than isolate it — the 2026-04-26 incident this
    guard exists for is a parallel session checkpointing the active session's
    WIP onto a branch and leaving its tree at main HEAD.
    """
    import session_start_modules.repo_sync as R

    monkeypatch.setattr(R, "has_concurrent_sessions", lambda *_a, **_k: True)
    (repo / "f.txt").write_text("uncommitted work\n", encoding="utf-8")

    warnings = _sync_one_repo(repo)

    assert _checkpoint_branches(repo) == [], (
        f"a concurrent session must prevent checkpointing. warnings={warnings!r}"
    )
    assert (repo / "f.txt").read_text(encoding="utf-8") == "uncommitted work\n", (
        "the other session's working tree must be left alone"
    )
    assert any("another session" in w for w in warnings), (
        f"the skip must be reported. warnings={warnings!r}"
    )


def test_fast_forwardable_repo_still_checkpoints_and_syncs(repo, tmp_path):
    """The known-positive: a behind-only branch still checkpoints AND fast-forwards.

    Without this, the gate above could be satisfied by never checkpointing at
    all, which would silently drop the protection it exists to provide.
    """
    # Advance origin/main from a second clone so `repo` is strictly behind.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(repo / ".." / "remote.git"), str(other)],
                   check=True, capture_output=True)
    git(other, "config", "user.email", "t@t")
    git(other, "config", "user.name", "t")
    (other / "upstream.txt").write_text("from upstream\n", encoding="utf-8")
    git(other, "add", "upstream.txt")
    git(other, "commit", "-qm", "upstream commit")
    git(other, "push", "-q", "origin", "main")

    # Local dirt so the checkpoint path is exercised.
    (repo / "f.txt").write_text("local edit\n", encoding="utf-8")

    warnings = _sync_one_repo(repo)

    assert _checkpoint_branches(repo), (
        f"a fast-forwardable repo with dirt MUST still be checkpointed. warnings={warnings!r}"
    )
    assert (repo / "upstream.txt").exists(), (
        f"the fast-forward did not happen. warnings={warnings!r}"
    )


def test_failing_fetch_reports_and_leaves_the_tree_untouched(repo, monkeypatch):
    """A failing fetch must report and not touch the working tree.

    After the checkpoint/fetch reorder the fetch runs BEFORE anything stashes or
    checkpoints, so this path must be a pure early return.
    """
    import session_start_modules.repo_sync as R

    (repo / "f.txt").write_text("local edit\n", encoding="utf-8")
    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):
        if isinstance(cmd, list) and "fetch" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "fatal: unable to access")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    warnings = _sync_one_repo(repo)
    monkeypatch.undo()

    assert any("Fetch FAILED" in w for w in warnings), f"warnings={warnings!r}"
    assert (repo / "f.txt").read_text(encoding="utf-8") == "local edit\n", (
        "a failed fetch must not disturb the working tree"
    )
    assert git(repo, "stash", "list").stdout.strip() == "", (
        "nothing should have been stashed before the fetch"
    )
    assert _checkpoint_branches(repo) == [], (
        "nothing should have been checkpointed before the fetch"
    )


def test_stashed_is_not_referenced_before_it_is_assigned():
    """Static invariant: no `stashed` READ precedes its assignment in _sync_one_repo.

    The reorder moved the fetch above the checkpoint block that defines `stashed`,
    and the fetch-failure path used to read it -- an UnboundLocalError the
    function's `except Exception: pass` would hide. It did NOT lose the warning
    (the append precedes the read, and the handler falls through to
    `return warnings`), so NO behavioural assertion can catch it. Hence a source
    assertion.

    Uses `ast`, not a regex: a text scan matches the word inside comments and
    docstrings, which is exactly the false positive the first version of this
    test produced against the very comments explaining the fix.
    """
    import ast

    src = (HOOKS / "session_start_modules" / "repo_sync.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_sync_one_repo"
    )
    stores, loads = [], []
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == "stashed":
            (stores if isinstance(node.ctx, ast.Store) else loads).append(node.lineno)
    assert stores, "`stashed` is never assigned in _sync_one_repo"
    first_store = min(stores)
    early = sorted(lineno for lineno in loads if lineno < first_store)
    assert not early, (
        f"`stashed` is READ at line(s) {early} but first assigned at line "
        f"{first_store} -- UnboundLocalError, silently swallowed by the "
        "function's `except Exception: pass`."
    )


# ==========================================================================
# TEST ISOLATION FROM THE DEVELOPER'S REAL REPOS (2026-08-15)
#
# `sync_tracked_repos` is the ONLY place that chooses REAL Path.home() paths;
# `_sync_one_repo` takes an explicit repo argument, which is why every other
# test here can drive the sync logic safely. So the gate belongs at that one
# entry point -- it cannot be made safe by argument.
#
# Measured: `test_crash_safety[session-start.py]` spawns the real session-start
# hook, which submits this function, so the SUITE performed network fetches and
# git mutations against the live ~/.claude and ~/Documents/knowledge-base. It
# took ~25-29s against that test's own 30s timeout (flipping pass/fail under
# load on an unchanged commit) and it overwrote the live
# .last-auto-checkpoint.json recovery pointer while ~/.claude was wedged
# mid-rebase. The live hook alone costs 0.05s; all of that 25s was the unwanted
# real-repo sync. After the gate: 5.3s, 3/3 stable.
# ==========================================================================

def test_sync_tracked_repos_refuses_real_repos_under_hook_test(monkeypatch):
    """Under CLAUDE_HOOK_TEST, no git command may run against a real home path."""
    import session_start_modules.repo_sync as R

    monkeypatch.setenv("CLAUDE_HOOK_TEST", "1")
    seen_cwds = []
    real_run = subprocess.run

    def spy(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd and cmd[0] == "git":
            seen_cwds.append(str(kw.get("cwd", "")))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(R.subprocess, "run", spy)
    warnings = R.sync_tracked_repos()
    monkeypatch.undo()

    assert seen_cwds == [], (
        f"ran git against real paths under CLAUDE_HOOK_TEST: {seen_cwds!r}"
    )
    assert any("Skipped real-repo sync" in w for w in warnings), (
        f"the skip must be REPORTED, not silent. warnings={warnings!r}"
    )


def test_without_the_gate_it_would_have_chosen_the_real_repos(monkeypatch):
    """Known-positive for the gate, WITHOUT touching a real repo.

    Stubs `_sync_one_repo` so no git runs, then asserts the SELECTION includes
    the live ~/.claude. Without this, the gate above could be satisfied by a
    function that never selects anything, and the assertion would pass for the
    wrong reason.
    """
    import session_start_modules.repo_sync as R

    monkeypatch.delenv("CLAUDE_HOOK_TEST", raising=False)
    chosen: list[Path] = []
    monkeypatch.setattr(R, "_sync_one_repo", lambda repo, sid=None: chosen.append(repo) or [])
    R.sync_tracked_repos()
    monkeypatch.undo()

    assert Path.home() / ".claude" in chosen, (
        f"expected the real ~/.claude in the selection; got {chosen!r}"
    )


def test_checkpoint_artifact_honours_the_env_override(repo, tmp_path, monkeypatch):
    """The recovery artifact must land on the override path, not the live one.

    Asserts the override RECEIVED the artifact -- not merely that the default
    was spared. A test that only checked the live path stayed clean would pass
    if the write silently failed altogether.
    """
    import session_start_modules.repo_sync as R

    target = tmp_path / "artifact.json"
    monkeypatch.setenv("CLAUDE_LAST_CHECKPOINT_ARTIFACT", str(target))
    monkeypatch.delenv("CLAUDE_HOOK_TEST", raising=False)

    # Advance origin so `repo` is strictly behind -> fast-forwardable, which is
    # the only case that still checkpoints (see #2000).
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(repo / ".." / "remote.git"), str(other)],
                   check=True, capture_output=True)
    git(other, "config", "user.email", "t@t")
    git(other, "config", "user.name", "t")
    (other / "up.txt").write_text("up\n", encoding="utf-8")
    git(other, "add", "up.txt")
    git(other, "commit", "-qm", "upstream")
    git(other, "push", "-q", "origin", "main")

    (repo / "f.txt").write_text("dirty\n", encoding="utf-8")   # triggers the checkpoint
    R._sync_one_repo(repo)
    monkeypatch.undo()

    import json

    assert target.exists(), "the override path did not receive the artifact"
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body["repo"] == str(repo)
    assert body["branch"].startswith("checkpoint/")


def test_artifact_default_is_the_live_path_when_unset(monkeypatch):
    """Pin the default so the override cannot silently become the only path."""
    import session_start_modules.repo_sync as R

    monkeypatch.delenv("CLAUDE_LAST_CHECKPOINT_ARTIFACT", raising=False)
    assert R._last_checkpoint_artifact() == R.LAST_CHECKPOINT_ARTIFACT
    monkeypatch.setenv("CLAUDE_LAST_CHECKPOINT_ARTIFACT", "/tmp/x.json")
    assert R._last_checkpoint_artifact() == Path("/tmp/x.json")
