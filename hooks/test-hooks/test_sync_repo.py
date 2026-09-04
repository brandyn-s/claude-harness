"""Unit tests for sync-repo.py pure helpers.

sync-repo.py is a standalone ops script (--git-status/--pull) whose main
paths do git network I/O. These tests cover the pure, deterministic
helpers that don't touch the network:
  - _parse_origin_org: GitHub remote URL -> org name (https + ssh forms)
  - _classify_dirty: `git status --porcelain` -> (modified, untracked) split
  - _label: friendly name + collision-disambiguating path tag
"""
import importlib.util
import os
import subprocess
from pathlib import Path

_HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "sync_repo", os.path.join(os.path.dirname(_HOOK_DIR), "bin", "sync-repo.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ── _parse_origin_org ──────────────────────────────────────────────────

def test_parse_org_https_with_git_suffix():
    assert _mod._parse_origin_org(
        "https://github.com/brandyn-s/claude-harness.git"
    ) == "brandyn-s"


def test_parse_org_ssh_form_preserves_case():
    assert _mod._parse_origin_org(
        "git@github.com:example-org/code-graph.git"
    ) == "example-org"


def test_parse_org_https_without_git_suffix():
    assert _mod._parse_origin_org("https://github.com/org-x/repo") == "org-x"


def test_parse_org_non_github_returns_none():
    assert _mod._parse_origin_org("https://gitlab.com/org/repo.git") is None


def test_parse_org_empty_returns_none():
    assert _mod._parse_origin_org("") is None


# ── _classify_dirty ────────────────────────────────────────────────────

def test_classify_untracked_only():
    # Two untracked entries, no tracked modifications.
    porcelain = "?? __pycache__/\n?? dev2.tfplan\n"
    modified, untracked = _mod._classify_dirty(porcelain)
    assert modified == []
    assert untracked == ["?? __pycache__/", "?? dev2.tfplan"]


def test_classify_modified_only():
    # A staged/unstaged tracked change is NOT untracked.
    porcelain = " M topics/session-friction-patterns.md\n"
    modified, untracked = _mod._classify_dirty(porcelain)
    assert modified == [" M topics/session-friction-patterns.md"]
    assert untracked == []


def test_classify_mixed_tracked_and_untracked():
    # The load-bearing distinction: ` M`/`A `/`MM` are tracked; only `??` untracked.
    porcelain = " M src/server.ts\nA  src/new.ts\nMM src/db.ts\n?? build/\n?? notes.log\n"
    modified, untracked = _mod._classify_dirty(porcelain)
    assert modified == [" M src/server.ts", "A  src/new.ts", "MM src/db.ts"]
    assert untracked == ["?? build/", "?? notes.log"]


def test_classify_empty_is_clean():
    assert _mod._classify_dirty("") == ([], [])
    assert _mod._classify_dirty("   \n  \n") == ([], [])


def test_classify_does_not_misread_filename_starting_with_question():
    # A tracked file whose NAME starts with '?' still leads with a status code,
    # never '??' — porcelain always prefixes the two-char XY status.
    porcelain = " M ??weird-name.txt\n"
    modified, untracked = _mod._classify_dirty(porcelain)
    assert modified == [" M ??weird-name.txt"]
    assert untracked == []


# ── _label ─────────────────────────────────────────────────────────────

def test_label_no_collision_is_bare_name():
    counts = {"code-graph": 1, "claude-config": 2}
    assert _mod._label("code-graph", Path("/anywhere/code-graph"), counts) == "code-graph"


def test_label_collision_appends_home_relative_path():
    counts = {"claude-config": 2}
    p = _mod.HOME / ".claude"
    assert _mod._label("claude-config", p, counts) == "claude-config @~/.claude"


def test_label_missing_from_counts_is_bare_name():
    # Defensive: a name absent from the counts dict is treated as non-colliding.
    assert _mod._label("solo", Path("/x/solo"), {}) == "solo"


# ── cmd_pull: merged-and-deleted upstream (2026-08-05) ─────────────────
#
# These DO touch git, but only against a local bare "remote" in tmp_path --
# no network. They cover the path that produced all nine 2026-08-05 failures,
# which the pure-helper tests above structurally cannot reach.


def _git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=check)


def _clone_on_merged_deleted_branch(tmp_path):
    """A clone parked on `feature`, whose remote branch was deleted elsewhere.

    The deletion is performed from a SECOND clone on purpose: `git push origin
    --delete` also drops the pushing clone's own remote-tracking ref, so
    deleting from `work` would leave nothing stale and the fixture would not
    reproduce the bug. In production GitHub's merge queue does the delete, so
    the local clone retains a tracking ref to a branch that no longer exists.
    """
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    # `-b main` is load-bearing: init.defaultBranch is unset on the CI runner, so
    # without it the bare HEAD dangles at refs/heads/master while main is the only
    # ref pushed, and later clones of this remote cannot check out or push main.
    # See the longer note in test_repo_sync.py's `repo` fixture.
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"),
                 ("commit.gpgsign", "false"), ("fetch.prune", "false")):
        _git(work, "config", k, v)

    (work / "f.txt").write_text("base\n", encoding="utf-8")
    _git(work, "add", "f.txt")
    _git(work, "commit", "-qm", "base")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-q", "-u", "origin", "main")

    _git(work, "checkout", "-qb", "feature")
    (work / "g.txt").write_text("work\n", encoding="utf-8")
    _git(work, "add", "g.txt")
    _git(work, "commit", "-qm", "feature work")
    _git(work, "push", "-q", "-u", "origin", "feature")

    # Squash-merge onto main under a NEW sha, then delete the remote branch.
    _git(work, "checkout", "-q", "main")
    _git(work, "merge", "--squash", "feature")
    _git(work, "commit", "-qm", "feature work (#1)")
    _git(work, "push", "-q", "origin", "main")

    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)],
                   check=True, capture_output=True)
    _git(other, "push", "-q", "origin", "--delete", "feature")

    _git(work, "checkout", "-q", "feature")
    return work


def test_bare_per_branch_fetch_fails_on_merged_deleted_branch(tmp_path):
    """Mechanism guard: the un-pruned fetch is what produced the hard ERR.

    If this ever stops failing, the regressions below pass for the wrong
    reason -- so assert the broken behaviour explicitly.
    """
    work = _clone_on_merged_deleted_branch(tmp_path)
    bare = _git(work, "fetch", "origin", "feature", check=False)
    assert bare.returncode != 0
    assert "couldn't find remote ref" in bare.stderr


def test_cmd_pull_reports_merged_and_gone_not_an_error(tmp_path, monkeypatch,
                                                      capsys):
    """A merged-and-deleted branch must SKIP with guidance, never count as ERR.

    Regression for 2026-08-05: nine clones each printed
    "ERR ...: fetch failed: couldn't find remote ref", which is
    indistinguishable from a network/auth fault and sends the reader hunting a
    problem that does not exist. The actionable fact is that the branch landed
    and the clone should move to main.
    """
    work = _clone_on_merged_deleted_branch(tmp_path)

    # cmd_pull discovers repos itself; pin discovery to just this clone.
    # raising=True is DELIBERATE: with raising=False a renamed target makes
    # the monkeypatch a SILENT no-op, so cmd_pull runs REAL discovery over
    # all 45 managed clones and does live network fetches (observed
    # 2026-08-05: the test ran past 120s and printed "Discovered 45 managed
    # repo(s)"). tdd-quality item 16: a mock bound to a dead name is a
    # no-op, not an error -- so bind to the REAL name and fail loudly.
    monkeypatch.setattr(_mod, "discover_managed_repos",
                        lambda: [("work", work)], raising=True)
    rc = _mod.cmd_pull()
    out = capsys.readouterr().out

    assert "ERR" not in out, f"merged-and-gone must not report ERR: {out}"
    assert "merged and deleted upstream" in out, (
        f"expected merged-and-gone guidance, got: {out}"
    )
    assert "switch to main" in out, "must tell the user what to do"
    assert rc == 0, f"a merged-and-gone branch is not a failure, rc={rc}"


def test_cmd_pull_prunes_the_stale_tracking_ref(tmp_path, monkeypatch, capsys):
    """--prune must actually run, so the stale ref is gone afterwards.

    This is the assertion that fails if someone removes `--prune`: without it
    the tracking ref survives and _prune_gone_branches stays inert.
    """
    work = _clone_on_merged_deleted_branch(tmp_path)
    before = _git(work, "rev-parse", "--verify", "--quiet", "origin/feature",
                  check=False)
    assert before.returncode == 0, "fixture must start with a STALE ref"

    monkeypatch.setattr(_mod, "discover_managed_repos",
                        lambda: [("work", work)], raising=True)
    _mod.cmd_pull()
    capsys.readouterr()

    after = _git(work, "rev-parse", "--verify", "--quiet", "origin/feature",
                 check=False)
    assert after.returncode != 0, (
        "cmd_pull must fetch --prune, clearing the stale tracking ref"
    )


def test_label_resolves_home_through_symlinks(tmp_path, monkeypatch):
    """Review 2026-09-03: macOS resolves /tmp -> /private/tmp, and Path.home()
    may be the unresolved spelling. relative_to() of a RESOLVED repo path
    against an UNRESOLVED HOME raises ValueError, so any user whose $HOME
    traverses a symlink lost the disambiguating label."""
    real_home = tmp_path / "real-home"
    (real_home / ".claude").mkdir(parents=True)
    link_home = tmp_path / "link-home"
    link_home.symlink_to(real_home, target_is_directory=True)
    monkeypatch.setattr(_mod, "HOME", link_home)
    assert _mod._label("claude-config", link_home / ".claude", {"claude-config": 2}) \
        == "claude-config @~/.claude"
