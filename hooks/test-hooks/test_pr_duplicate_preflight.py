"""Behavior tests for pr-duplicate-preflight.py.

Contract: PreToolUse:Bash. BLOCK (exit 2) on `gh pr create` when one of YOUR
open PRs already changes a file this branch changes. Allow (0) for: non-matching
commands, no overlap, a PR on the CURRENT branch (an update, not a twin), no
changed files, the CLAUDE_PR_ALLOW_DUPLICATE=1 bypass, and EVERY instrument
failure — with a NOT RUN note so a skipped check is never mistaken for a passed
one.

The decision lives in a pure function (`overlapping`), so the interesting cases
need no gh, no network, and no repo.
"""
import importlib.util
import json
import os
from pathlib import Path

from conftest import make_bash_input, run_hook

HOOK = "pr-duplicate-preflight.py"


def _mod():
    """Import the hook as a module to exercise its pure core directly."""
    path = Path(__file__).resolve().parents[1] / HOOK
    spec = importlib.util.spec_from_file_location("pr_dup_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pr(number, branch, *paths, title="t"):
    return {"number": number, "title": title, "headRefName": branch,
            "files": [{"path": p} for p in paths]}


def _shim_env(tmp_path, overlap=True):
    """PATH pointing at fake `git` and `gh` so the hook's DOWNSTREAM logic runs.

    Without this, every boundary test exits through the empty-diff short-circuit:
    a branch with no commits yields no changed files, the hook returns 0, and the
    test passes for a reason unrelated to what it claims. Mutation testing proved
    that — the bypass test and the command-matching test both stayed green with
    the bypass and the command regex broken. A fixture that cannot reach the code
    tests nothing.
    """
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    shared = "hooks/pr-duplicate-preflight.py" if overlap else "some/other/file.py"
    payload = json.dumps([{
        "number": 999, "title": "duplicate work",
        "headRefName": "some-other-branch",
        "files": [{"path": shared}],
    }])
    (shim / "gh").write_text(
        f"#!/bin/sh\ncat <<'JSON'\n{payload}\nJSON\n", encoding="utf-8")
    (shim / "gh").chmod(0o755)
    (shim / "git").write_text(
        "#!/bin/sh\n"
        "case \"$1 $2\" in\n"
        "  'diff --name-only') echo hooks/pr-duplicate-preflight.py ;;\n"
        "  'rev-parse --abbrev-ref') echo my-branch ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n", encoding="utf-8")
    (shim / "git").chmod(0o755)
    return {"PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}"}


# ── the pure decision ────────────────────────────────────────────────────────

def test_the_real_incident_shape_is_caught():
    """#343 vs #345: DIFFERENT branch, SAME single file.

    A same-branch check would have missed this entirely, which is why the guard
    keys on file overlap. gh already errors on a same-branch duplicate.
    """
    m = _mod()
    hits = m.overlapping(
        ["scripts/paved_road.py"],
        [_pr(343, "fix/ruff-s105-false-positive", "scripts/paved_road.py",
             title="fix(ci): S105 on GRAPH_SECRET_ID is a false positive")],
        "fix/ruff-s105-secret-id",
    )
    assert len(hits) == 1
    assert hits[0][0] == 343
    assert hits[0][2] == ["scripts/paved_road.py"]


def test_no_overlap_allows():
    m = _mod()
    assert m.overlapping(["a.py"], [_pr(1, "other", "b.py", "c.py")], "mine") == []


def test_a_pr_on_the_current_branch_is_not_a_twin():
    """That is an update to the PR being created, not a duplicate of it."""
    m = _mod()
    assert m.overlapping(["a.py"], [_pr(1, "mine", "a.py")], "mine") == []


def test_partial_overlap_still_counts_and_names_only_shared_paths():
    m = _mod()
    hits = m.overlapping(["a.py", "b.py"], [_pr(7, "other", "b.py", "z.py")], "mine")
    assert hits[0][2] == ["b.py"], "must report the shared path, not the union"


def test_no_changed_files_allows():
    m = _mod()
    assert m.overlapping([], [_pr(1, "other", "a.py")], "mine") == []
    assert m.overlapping(["", None], [_pr(1, "other", "a.py")], "mine") == []


def test_multiple_overlapping_prs_are_all_reported():
    m = _mod()
    hits = m.overlapping(["a.py"], [_pr(1, "x", "a.py"), _pr(2, "y", "a.py")], "mine")
    assert sorted(h[0] for h in hits) == [1, 2]


def test_a_pr_with_no_file_data_is_skipped_not_crashed():
    """gh can return a PR whose files list is absent; that must not raise."""
    m = _mod()
    assert m.overlapping(["a.py"], [{"number": 1, "headRefName": "x"}], "mine") == []


# ── the hook boundary ────────────────────────────────────────────────────────

def test_non_matching_command_is_allowed():
    code, _out, _err = run_hook(HOOK, make_bash_input("gh pr list --state open"))
    assert code == 0


def test_gh_pr_view_is_not_mistaken_for_create(tmp_path):
    """Shimmed so the command match is the ONLY thing keeping this at exit 0.

    Under these shims `gh pr create` blocks. If the regex widened to `gh pr`,
    `gh pr view` would block too — which is what this asserts against.
    """
    code, _out, _err = run_hook(HOOK, make_bash_input("gh pr view 12 --json files"),
                                env=_shim_env(tmp_path))
    assert code == 0


def test_bypass_env_allows_without_running_the_check(tmp_path):
    """Shimmed so that WITHOUT the bypass this exact input blocks (see the
    block-path test). The bypass is therefore the only thing under test."""
    env = _shim_env(tmp_path)
    env["CLAUDE_PR_ALLOW_DUPLICATE"] = "1"
    code, _out, err = run_hook(
        HOOK, make_bash_input("gh pr create --base main --title t --body b"), env=env)
    assert code == 0
    assert "NOT RUN" not in err, "the bypass should be silent, not a NOT RUN note"


def test_no_overlap_reaches_the_end_and_allows(tmp_path):
    """Known-negative through the full boundary: shims present, PR does NOT overlap."""
    code, _out, err = run_hook(
        HOOK, make_bash_input("gh pr create --base main --title t --body b"),
        env=_shim_env(tmp_path, overlap=False))
    assert code == 0
    assert "BLOCKED" not in err
    assert "NOT RUN" not in err, "the check RAN and found nothing; that is not a skip"


def test_instrument_failure_allows_but_says_so():
    """An unresolvable base ref: the diff cannot run, so the check cannot either.

    This is the load-bearing behaviour. Blocking real work because the guard's own
    tooling could not run would be worse than having no guard; allowing SILENTLY
    would let a skipped check read as a passed one. So: exit 0 AND a NOT RUN note.
    """
    code, _out, err = run_hook(HOOK, make_bash_input(
        "gh pr create --base no-such-ref-abc123 --title t --body b"))
    assert code == 0
    assert "NOT RUN" in err
    assert "verify by hand" in err


def test_the_BLOCK_path_actually_executes(tmp_path):
    """KNOWN-POSITIVE for exit 2. A gate never seen blocking is not a gate.

    Stubs `gh` on PATH so `gh pr list` returns a PR that overlaps a file this
    branch really changes (the hook itself). `git diff` is real, so this exercises
    the whole boundary: stdin parse -> diff -> pr list -> overlap -> exit 2.
    """
    code, _out, err = run_hook(
        HOOK,
        make_bash_input("gh pr create --base main --title t --body b"),
        env=_shim_env(tmp_path),
    )
    assert code == 2, f"expected BLOCK, got {code}; stderr={err[:300]}"
    assert "#999" in err
    assert "hooks/pr-duplicate-preflight.py" in err
    assert "NOT RUN" not in err, "a real block must not also claim it did not run"


def test_the_block_message_names_the_pr_and_the_remedy():
    """A block a reader cannot act on gets bypassed reflexively."""
    m = _mod()
    hits = m.overlapping(["scripts/paved_road.py"],
                         [_pr(343, "other", "scripts/paved_road.py")], "mine")
    assert hits, "fixture must overlap or the assertions below prove nothing"
    src = (Path(__file__).resolve().parents[1] / HOOK).read_text(encoding="utf-8")
    assert "CLAUDE_PR_ALLOW_DUPLICATE=1" in src, "must state its own bypass"
    assert "add your commit to the existing PR" in src, "must state the remedy"
