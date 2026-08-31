"""Behavior tests for git-destructive-checkout-guard.py.

Contract: PreToolUse:Bash. BLOCK (exit 2) a git command that would destroy work
existing in no git object — unstaged tracked edits, untracked files, or ignored
files — in the target repo. Allow (0) otherwise.

Upstream cause: anthropics/claude-code#89330 (open, data-loss, has repro,
platform:macos) — the built-in review skill ran `git checkout <ref> -- .` and
permanently destroyed an unstaged edit.

WHY THIS FILE IS EMPIRICAL (rewritten 2026-08-30). The first version of these
tests passed while the guard was wrong in BOTH directions: it allowed
`git clean -fd` with precious untracked files present, and blocked
`git restore --staged`, which touches only the index. The tests could not catch
either, because the fixtures encoded the SAME wrong model as the code
(`rules/tdd-mutation-testing.md` item 34 — an assumption-written test pins the
wrong boundary while passing, and mutation testing cannot see it because both
sides agree).

So the core test no longer asserts a hand-written expectation. It builds a repo
holding one unstaged tracked edit, one untracked file and one ignored file, RUNS
THE REAL COMMAND, observes which of the three actually disappeared, and asserts
the guard blocks if and only if something was destroyed. Git itself is the oracle.

Registered in conftest._NEEDS_GIT.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import HOOKS_DIR, make_bash_input, run_hook

HOOK = "git-destructive-checkout-guard.py"

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.com",
}

UNSTAGED = "tracked.txt"
UNTRACKED = "precious-untracked.txt"
IGNORED = "local.env"

# Command templates exercised against the real git binary. `{d}` is the repo.
# No expected verdict is written here on purpose — git decides.
COMMANDS = [
    "git -C {d} checkout main -- .",
    "git -C {d} checkout HEAD -- tracked.txt",
    "git -C {d} checkout -- .",
    "git -C {d} checkout -f main",
    "git -C {d} checkout main",
    "git -C {d} checkout -b feat/x",
    "git -C {d} switch -c feat/y",
    "git -C {d} switch --discard-changes main",
    "git -C {d} restore tracked.txt",
    "git -C {d} restore --worktree tracked.txt",
    "git -C {d} restore --staged tracked.txt",
    "git -C {d} reset --hard",
    "git -C {d} reset HEAD~0",
    "git -C {d} clean -fd",
    "git -C {d} clean -fdx",
    "git -C {d} clean -n",
    "git -C {d} stash push -- tracked.txt",
    "git -C {d} status --short",
    "git -C {d} diff",
]


def _git(args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=_ENV, check=check,
                          capture_output=True, text=True, timeout=20)


def _make_repo(root):
    d = root / "r"
    d.mkdir()
    _git(["init", "-q", "-b", "main"], d)
    (d / ".gitignore").write_text(f"{IGNORED}\n", encoding="utf-8")
    (d / UNSTAGED).write_text("committed\n", encoding="utf-8")
    _git(["add", ".gitignore", UNSTAGED], d)
    _git(["commit", "-qm", "init"], d)
    # the three unrecoverable artifacts
    (d / UNSTAGED).write_text("UNSTAGED EDIT\n", encoding="utf-8")
    (d / UNTRACKED).write_text("hours of work, in no git object\n", encoding="utf-8")
    (d / IGNORED).write_text("SECRET=local-only\n", encoding="utf-8")
    return d


def _snapshot(d):
    """Is each artifact still RETRIEVABLE?

    The guard's contract is "work recoverable from no git object", so the oracle
    must encode RECOVERABILITY, not mere file-content change. `git stash push`
    removes an edit from the working tree but stores it in a git object, so it is
    NOT destruction — checking file content alone wrongly counted it as such and
    made the first run of this test demand that `stash` be blocked.
    """
    stashed = bool(
        _git(["stash", "list"], d, check=False).stdout.strip()
    )
    return {
        "unstaged": (
            (d / UNSTAGED).read_text(encoding="utf-8") == "UNSTAGED EDIT\n"
            or stashed
        ),
        "untracked": (d / UNTRACKED).exists() or stashed,
        "ignored": (d / IGNORED).exists(),
    }


def _ask_guard(cmd):
    return run_hook(HOOK, make_bash_input(cmd))[0]


@pytest.mark.parametrize("template", COMMANDS)
def test_guard_verdict_matches_what_git_actually_destroys(tmp_path, template):
    """Git is the oracle: block iff running the command loses unrecoverable work."""
    # 1. verdict first, on a pristine repo (the guard reads live state)
    (tmp_path / "verdict").mkdir()
    d = _make_repo(tmp_path / "verdict")
    cmd = template.format(d=d)
    verdict = _ask_guard(cmd)

    # 2. now actually run it on an identical repo and see what survived
    (tmp_path / "run").mkdir()
    d2 = _make_repo(tmp_path / "run")
    before = _snapshot(d2)
    assert all(before.values()), "fixture must start with all three artifacts intact"
    subprocess.run(cmd.replace(str(d), str(d2)), shell=True, cwd=d2, env=_ENV,
                   capture_output=True, text=True, timeout=30)
    after = _snapshot(d2)

    destroyed = [k for k in before if before[k] and not after[k]]
    want = 2 if destroyed else 0
    assert verdict == want, (
        f"{cmd!r}\n  git destroyed: {destroyed or 'nothing'}\n"
        f"  guard said: {'BLOCK' if verdict == 2 else 'ALLOW'}\n"
        f"  expected:   {'BLOCK' if want == 2 else 'ALLOW'}"
    )


# --- the two regressions this rewrite exists for, pinned explicitly ---

def test_clean_is_gated_on_untracked_not_unstaged(tmp_path):
    """REGRESSION: v1 allowed `clean -fd` when only untracked work was at risk.

    The tracked tree is restored to HEAD so there is NO unstaged edit — v1's only
    signal — while the untracked file, which is what `clean` actually deletes,
    stays untracked. (A first draft of this test `git add -A`'d that file and
    committed it, which made it TRACKED and therefore not something `clean` would
    delete at all; the guard was right to allow it and the fixture was wrong.)
    """
    d = _make_repo(tmp_path)
    _git(["checkout", "--", UNSTAGED], d)  # clean tracked tree, no unstaged edit
    porcelain = _git(["status", "--porcelain"], d).stdout
    assert "??" in porcelain, "fixture must leave an UNTRACKED file for clean to eat"
    assert not any(l[1:2] in ("M", "D") for l in porcelain.splitlines() if len(l) > 1), \
        "fixture must have NO unstaged tracked edits, or it cannot pin the regression"
    assert _ask_guard(f"git -C {d} clean -fd") == 2, (
        "clean -fd must block on untracked files even with a clean tracked tree"
    )


def test_restore_staged_is_allowed_it_is_index_only(tmp_path):
    """REGRESSION: v1 blocked `restore --staged`, which never touches the tree."""
    d = _make_repo(tmp_path)
    assert _ask_guard(f"git -C {d} restore --staged {UNSTAGED}") == 0
    # but --staged --worktree DOES touch the tree
    assert _ask_guard(f"git -C {d} restore --staged --worktree {UNSTAGED}") == 2


def test_ignored_files_are_protected_from_clean_x(tmp_path):
    """`clean -fdx` deletes gitignored files, which is where local .env lives."""
    d = _make_repo(tmp_path)
    _git(["checkout", "--", UNSTAGED], d)
    (d / UNTRACKED).unlink()
    assert (d / IGNORED).exists()
    assert _ask_guard(f"git -C {d} clean -fdx") == 2, "must protect ignored files"
    assert _ask_guard(f"git -C {d} clean -fd") == 0, (
        "plain clean -fd does not touch ignored files, so nothing is at risk"
    )


def test_quoted_destructive_form_is_not_a_false_positive(tmp_path):
    """A destructive form QUOTED inside another command is not the real thing.

    v1 was a raw text matcher and blocked its own test payloads.
    """
    d = _make_repo(tmp_path)
    for cmd in (
        "echo 'git reset --hard'",
        f"grep -n 'reset --hard' {d}/tracked.txt",
        "printf '%s\\n' 'git clean -fdx'",
    ):
        assert _ask_guard(cmd) == 0, f"{cmd!r} mentions but does not run a destructive form"


def test_untokenizable_command_blocks_conservatively(tmp_path):
    """Unbalanced quotes must not silently disable the guard.

    This assertion used to pass by ACCIDENT: the fallback ignored `-C` and graded
    `os.getcwd()`, which happened to be a dirty repo. Staging that repo's edits
    flipped it to a failure (`tdd-mutation-testing` item 27 — an assertion reading
    live external state). The fallback now resolves `-C`, so the verdict depends on
    the TARGET repo only, which is what the pair below pins.
    """
    d = _make_repo(tmp_path)
    assert _ask_guard(f"git -C {d} reset --hard 'unbalanced") == 2


def test_untokenizable_verdict_follows_the_dash_C_target_not_the_cwd(tmp_path):
    """Same untokenizable command, two targets: dirty blocks, clean allows."""
    (tmp_path / "dirty").mkdir()
    (tmp_path / "clean").mkdir()
    dirty = _make_repo(tmp_path / "dirty")
    clean = _make_repo(tmp_path / "clean")
    # strip everything unrecoverable from `clean`
    _git(["checkout", "--", UNSTAGED], clean)
    (clean / UNTRACKED).unlink()
    (clean / IGNORED).unlink()

    assert _ask_guard(f"git -C {dirty} reset --hard 'unbalanced") == 2
    assert _ask_guard(f"git -C {clean} reset --hard 'unbalanced") == 0, (
        "a clean target must be allowed even when the shell's cwd is dirty — "
        "the fallback must read the -C repo, not os.getcwd()"
    )


# --- v2.1 regressions: the guard blocked its own repo's `git add` (2026-08-30) ---

def test_multiline_git_add_is_allowed(tmp_path):
    """REGRESSION: a backslash-continued `git add -- <files>` was BLOCKED.

    Mechanism: `_segments()` split on the newline, so shlex saw the fragment
    `git add -- \\` and raised; the command then fell to a conservative fallback
    that keyed on `git … -- <path>`, which `git add` matches. Found by this guard
    blocking the ship of the very commit that contains it.

    Mutation-verified as pinning the FALLBACK fix specifically: reverting the
    fallback to its subcommand-blind form fails this test. Removing the
    line-continuation join does NOT — with a verb-scoped fallback, `add` is not a
    destructive verb either way. See
    `test_multiline_safe_flags_on_a_destructive_VERB_still_tokenize` for the case
    that pins the join.
    """
    d = _make_repo(tmp_path)
    cmd = (f"git -C {d} add -- \\\n  {UNSTAGED} \\\n  .gitignore")
    assert _ask_guard(cmd) == 0, "multi-line `git add --` must be allowed"


@pytest.mark.parametrize("verb", ["add", "commit", "diff", "log", "status", "show HEAD"])
def test_safe_subcommands_never_block_even_with_pathspec(tmp_path, verb):
    """`git <safe-verb> -- <path>` is not destructive, tokenizable or not."""
    d = _make_repo(tmp_path)
    assert _ask_guard(f"git -C {d} {verb} -- {UNSTAGED}") == 0
    # and the same command made untokenizable must STILL be allowed, because the
    # conservative scan is now scoped to destructive verbs
    assert _ask_guard(f"git -C {d} {verb} -- {UNSTAGED} 'unbalanced") == 0


def test_line_continuation_does_not_hide_a_destructive_command(tmp_path):
    """The continuation join must not become a bypass."""
    d = _make_repo(tmp_path)
    assert _ask_guard(f"git -C {d} reset \\\n  --hard") == 2
    assert _ask_guard(f"git -C {d} clean \\\n  -fd") == 2


def test_multiline_safe_flags_on_a_destructive_VERB_still_tokenize(tmp_path):
    """This is the case the line-continuation join actually buys.

    `restore` IS a destructive verb, so the conservative fallback fires on the
    verb alone — but `--staged` makes this invocation index-only and safe. Only a
    command that TOKENIZES reaches the per-flag classification that knows that.
    Without the continuation join the multi-line form fragments, shlex raises, and
    the fallback blocks a safe command on the verb.

    Mutation-verified: removing the join flips this to BLOCK while every other test
    in this file still passes — which is why the `git add` test alone did not pin it.
    """
    d = _make_repo(tmp_path)
    assert _ask_guard(f"git -C {d} restore --staged {UNSTAGED}") == 0, "baseline"
    assert _ask_guard(f"git -C {d} restore \\\n  --staged {UNSTAGED}") == 0, (
        "multi-line index-only restore must be allowed; the continuation join is "
        "what lets it tokenize instead of falling to the verb-scoped fallback"
    )


# --- plumbing controls ---

def test_clean_tree_allows_everything(tmp_path):
    d = _make_repo(tmp_path)
    _git(["checkout", "--", UNSTAGED], d)
    (d / UNTRACKED).unlink()
    (d / IGNORED).unlink()
    for cmd in (f"git -C {d} reset --hard", f"git -C {d} clean -fdx",
                f"git -C {d} checkout main -- ."):
        assert _ask_guard(cmd) == 0, f"nothing at risk, {cmd!r} must be allowed"


def test_staged_only_is_allowed(tmp_path):
    """Staged work is recoverable via `git fsck --lost-found`; not our target."""
    d = _make_repo(tmp_path)
    (d / UNTRACKED).unlink()
    (d / IGNORED).unlink()
    _git(["add", UNSTAGED], d)
    assert _ask_guard(f"git -C {d} checkout main -- .") == 0


def test_bypass_env_allows(tmp_path):
    d = _make_repo(tmp_path)
    rc, _, _ = run_hook(HOOK, make_bash_input(f"git -C {d} reset --hard"),
                        env={"CLAUDE_ALLOW_DESTRUCTIVE_CHECKOUT": "1"})
    assert rc == 0


def test_non_bash_tool_allowed():
    rc, _, _ = run_hook(HOOK, {"tool_name": "Read",
                               "tool_input": {"file_path": "/tmp/x"}})
    assert rc == 0


def test_empty_command_allowed():
    assert run_hook(HOOK, make_bash_input(""))[0] == 0


def test_malformed_stdin_fails_open():
    p = subprocess.run([sys.executable, str(HOOKS_DIR / HOOK)],
                       input="not json at all", capture_output=True,
                       text=True, timeout=10)
    assert p.returncode == 0


def test_nonexistent_repo_dir_fails_open():
    assert _ask_guard("git -C /nonexistent/path/xyz reset --hard") == 0


def test_block_message_names_a_recoverable_alternative(tmp_path):
    d = _make_repo(tmp_path)
    rc, _, err = run_hook(HOOK, make_bash_input(f"git -C {d} reset --hard"))
    assert rc == 2
    assert "git stash push" in err
    assert "89330" in err


def test_message_reports_the_right_risk_class(tmp_path):
    """The explanation must name what is actually at risk, not a generic phrase."""
    d = _make_repo(tmp_path)
    _git(["checkout", "--", UNSTAGED], d)
    _, _, err = run_hook(HOOK, make_bash_input(f"git -C {d} clean -fd"))
    assert "untracked files" in err
    assert "unstaged tracked edits" not in err


def test_json_payload_quoting_matches_reality(tmp_path):
    """Sanity: the harness itself builds a payload the hook can parse."""
    d = _make_repo(tmp_path)
    payload = make_bash_input(f"git -C {d} reset --hard")
    assert json.loads(json.dumps(payload))["tool_input"]["command"].startswith("git ")
