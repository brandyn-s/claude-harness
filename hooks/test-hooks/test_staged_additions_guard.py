"""Tests for staged-additions-guard.py — PreToolUse:Bash guard that BLOCKs
`git commit` when staged ADDITIONS coexist with unstaged MODIFICATIONS
(the PR #317 / 2026-05-14 forgot-to-stage signature).

Two layers:
  - unit tests for the command-classification regexes and helpers
  - end-to-end main() exit-code tests via subprocess against real temp git
    repos (tests real behavior, not mock existence)
"""
import importlib.util
import json
import os
import subprocess
import sys

_HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOOK_PATH = os.path.join(_HOOK_DIR, "staged-additions-guard.py")

_spec = importlib.util.spec_from_file_location("staged_additions_guard", _HOOK_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ── unit: command classification ────────────────────────────────────────
def test_commit_re_matches_only_commit():
    assert _mod.COMMIT_RE.search("git commit -m x")
    assert not _mod.COMMIT_RE.search("git status")
    assert not _mod.COMMIT_RE.search("git add foo")


def test_safe_flags_skip_amend_and_autostage():
    for safe in ("git commit --amend", "git commit -a -m x", "git commit -am x",
                 "git commit --all", "git commit --allow-empty"):
        assert _mod.SAFE_FLAGS_RE.search(safe), safe


def test_safe_flags_do_not_match_plain_commit():
    assert not _mod.SAFE_FLAGS_RE.search("git commit -m 'message'")


def test_stage_all_re_matches_explicit_add_all():
    assert _mod.STAGE_ALL_RE.search("git add -A && git commit -m x")
    assert _mod.STAGE_ALL_RE.search("git add --all && git commit -m x")
    assert _mod.STAGE_ALL_RE.search("git add . && git commit -m x")
    assert not _mod.STAGE_ALL_RE.search("git add foo.py && git commit -m x")


def test_strip_quotes_prevents_false_stage_all_from_message():
    # a quoted commit message containing "git add -A" must NOT read as stage-all
    cleaned = _mod._strip_quotes("git commit -m 'remember to git add -A next time'")
    assert "git add" not in cleaned


# ── unit: cwd resolution ────────────────────────────────────────────────
def test_resolve_cwd_follows_last_cd(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    resolved = _mod._resolve_cwd(f"cd {sub} && git commit -m x", str(tmp_path))
    assert resolved == str(sub)


def test_resolve_cwd_defaults_to_payload_cwd():
    assert _mod._resolve_cwd("git commit -m x", "/some/dir") == "/some/dir"


# ── unit: block message ─────────────────────────────────────────────────
def test_block_message_lists_unstaged_files_and_bypass():
    msg = _mod._format_block_message(["a.py", "b.py"], "/repo")
    assert "BLOCKED" in msg
    assert "a.py" in msg and "b.py" in msg
    assert "CLAUDE_GIT_COMMIT_ALLOW_PARTIAL" in msg


# ── integration: real git repos via subprocess ──────────────────────────
def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _make_repo(tmp):
    _git(["init", "-q"], tmp)
    _git(["config", "user.email", "t@t"], tmp)
    _git(["config", "user.name", "t"], tmp)
    _git(["config", "commit.gpgsign", "false"], tmp)
    (tmp / "tracked.txt").write_text("orig\n")
    _git(["add", "tracked.txt"], tmp)
    _git(["commit", "-q", "-m", "init"], tmp)
    return tmp


def _run_hook(command, cwd, allow_partial=False):
    env = dict(os.environ)
    env.pop("CLAUDE_GIT_COMMIT_ALLOW_PARTIAL", None)
    if allow_partial:
        env["CLAUDE_GIT_COMMIT_ALLOW_PARTIAL"] = "1"
    payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
    proc = subprocess.run([sys.executable, _HOOK_PATH], input=payload,
                          capture_output=True, text=True, env=env)
    return proc.returncode


def test_blocks_staged_addition_with_unstaged_modification(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "new.txt").write_text("new\n")
    _git(["add", "new.txt"], repo)                  # staged addition (A)
    (repo / "tracked.txt").write_text("changed\n")  # unstaged modification (M)
    assert _run_hook("git commit -m x", repo) == 2


def test_allows_staged_addition_without_unstaged_modification(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "new.txt").write_text("new\n")
    _git(["add", "new.txt"], repo)                  # only A, no M
    assert _run_hook("git commit -m x", repo) == 0


def test_allows_commit_dash_a_autostage(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "new.txt").write_text("new\n")
    _git(["add", "new.txt"], repo)
    (repo / "tracked.txt").write_text("changed\n")
    assert _run_hook("git commit -am x", repo) == 0  # -a auto-stages M, safe


def test_allows_when_add_all_precedes_commit(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "new.txt").write_text("new\n")
    _git(["add", "new.txt"], repo)
    (repo / "tracked.txt").write_text("changed\n")
    assert _run_hook("git add -A && git commit -m x", repo) == 0


def test_ignores_non_commit_command(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "new.txt").write_text("new\n")
    _git(["add", "new.txt"], repo)
    (repo / "tracked.txt").write_text("changed\n")
    assert _run_hook("git status", repo) == 0


def test_bypass_env_allows_partial_commit(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "new.txt").write_text("new\n")
    _git(["add", "new.txt"], repo)
    (repo / "tracked.txt").write_text("changed\n")
    assert _run_hook("git commit -m x", repo, allow_partial=True) == 0


if __name__ == "__main__":
    test_commit_re_matches_only_commit()
    test_safe_flags_skip_amend_and_autostage()
    test_safe_flags_do_not_match_plain_commit()
    test_stage_all_re_matches_explicit_add_all()
    test_strip_quotes_prevents_false_stage_all_from_message()
    test_resolve_cwd_defaults_to_payload_cwd()
    test_block_message_lists_unstaged_files_and_bypass()
    print("unit tests passed; run via pytest for tmp_path integration tests")
