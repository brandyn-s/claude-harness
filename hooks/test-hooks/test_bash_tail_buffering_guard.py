"""Behavior tests for bash-tail-buffering-guard.py.

Contract (v4, 2026-06-13): PreToolUse:Bash. Detection is unchanged from v3
(FIRST pipe segment's producer is long-running AND LAST segment is a buffering
filter). The ACTION changed:
  - tail/grep consumers  -> AUTO-REWRITE (exit 0 + hookSpecificOutput.updatedInput):
        `PRODUCER | filter` becomes `PRODUCER > FILE 2>&1\\ncat FILE | filter`.
  - head consumers       -> BLOCK (exit 2): head intends early termination
        (SIGPIPE); a run-to-completion redirect would regress it.
  - un-rewritable shapes (quoted pipe, producer-side redirect) -> BLOCK.
  - chained commands AFTER the filter (`| tail -5; echo done`) -> REWRITE
        (preserved byte-for-byte downstream of the producer).
Allow (exit 0, no output) when not a buffering pipe. Non-Bash passes through.
"""
import json
import os as _os
import shutil as _shutil

import pytest as _pytest

from conftest import make_bash_input, make_write_input, run_hook

HOOK = "bash-tail-buffering-guard.py"
# Route the producer's capture file to a scratch dir so tests don't makedirs
# in the shared /tmp/claude (the hook only mkdirs; the redirect writes at run).
ENV = {"CLAUDE_TAILBUF_DIR": "/tmp/claude/guardtest-tail"}


def _rewrite_cmd(out):
    """Extract hookSpecificOutput.updatedInput.command from a rewrite (exit-0 JSON) stdout."""
    return json.loads(out)["hookSpecificOutput"]["updatedInput"]["command"]


def _run(cmd):
    return run_hook(HOOK, make_bash_input(cmd), env=ENV)


# ── REWRITE cases: tail/grep consumer (producer runs to completion anyway) ──

def test_rewrites_python_pipe_tail_n():
    code, out, _err = _run("python run.py 2>&1 | tail -80")
    assert code == 0, f"expected REWRITE (exit 0), got {code}"
    new = _rewrite_cmd(out)
    assert "python run.py > " in new and "2>&1" in new
    assert "cat " in new and "| tail -80" in new
    # the producer's trailing 2>&1 is moved after the file redirect, not doubled
    assert new.count("2>&1") == 1


def test_rewrites_pytest_pipe_grep():
    code, out, _err = _run("pytest -q | grep FAIL")
    assert code == 0
    new = _rewrite_cmd(out)
    assert new.startswith("pytest -q > ")
    assert "cat " in new and "| grep FAIL" in new


def test_rewrites_bare_tail():
    code, out, _err = _run("go test ./... | tail")
    assert code == 0
    new = _rewrite_cmd(out)
    assert "go test ./... > " in new and "| tail" in new


def test_rewrites_env_prefixed_producer():
    code, out, _err = _run("PYTHONPATH=. python3 runner.py 2>&1 | grep ERROR")
    assert code == 0
    new = _rewrite_cmd(out)
    assert new.startswith("PYTHONPATH=. python3 runner.py > ")
    assert "| grep ERROR" in new


def test_rewrites_venv_python_pipe_tail():
    code, out, _err = _run(".venv/bin/python -m pytest tests/ 2>&1 | tail -25")
    assert code == 0
    assert "| tail -25" in _rewrite_cmd(out)


def test_rewrites_wrapper_binary_indexer():
    cmd = "~/.local/bin/codebase-memory-mcp cli index_repository '{\"repo_path\": \"~/x\"}' 2>&1 | tail -15"
    code, out, _err = _run(cmd)
    assert code == 0
    new = _rewrite_cmd(out)
    # single-quoted JSON arg has no top-level pipe → reconstruction is safe
    assert "index_repository" in new and "| tail -15" in new


def test_rewrites_multi_filter_chain():
    code, out, _err = _run("pytest | grep X | tail -5")
    assert code == 0
    new = _rewrite_cmd(out)
    assert "cat " in new and "| grep X | tail -5" in new


def test_rewrites_chained_command_after_filter():
    # The 2026-06-13 relaxation: `; echo done` sits downstream of the producer
    # and is preserved verbatim. (Was the single biggest block category.)
    code, out, _err = _run("python3 finalize.py 2>&1 | tail -5; echo done")
    assert code == 0
    new = _rewrite_cmd(out)
    assert "python3 finalize.py > " in new
    assert "| tail -5; echo done" in new


def test_rewritten_command_no_longer_blocks():
    # Idempotence: feeding the rewrite back in must NOT re-block (cat is not a
    # long-running producer).
    _code, out, _err = _run("pytest -q | grep FAIL")
    new = _rewrite_cmd(out)
    code2, _out2, _err2 = _run(new)
    assert code2 == 0


# ── head consumer: REWRITES as of v5 (2026-06-23) ──
# Rationale: this guard only fires when the producer is a BATCH command
# (_producer_is_long_running: pytest/cargo/go test/python*/...), all of which run
# to completion regardless — so head's SIGPIPE early-termination saves no producer
# work here (unlike `cat hugefile | head`, which never reaches this guard since cat
# isn't a long-running producer). So `batch-producer | head -N` is safely rewritten
# to `producer > FILE; cat FILE | head -N`. Measured: head was 142 of 412 fires.

def test_rewrites_python_pipe_head():
    # v5: head on a batch producer now REWRITES (was BLOCK pre-2026-06-23).
    code, out, _err = _run("python script.py | head -5")
    assert code == 0, f"expected REWRITE (exit 0), got {code}"
    new = _rewrite_cmd(out)
    assert "python script.py > " in new and "| head -5" in new


def test_rewrites_multi_filter_ending_head():
    code, out, _err = _run("pytest | grep X | head -5")
    assert code == 0
    new = _rewrite_cmd(out)
    # downstream filters preserved byte-for-byte after the producer's file redirect
    assert "pytest > " in new and "grep X | head -5" in new


def test_rewrites_newline_chained_producer_head():
    code, out, _err = _run("cd hooks/test-hooks\npytest -q | head -10")
    assert code == 0
    new = _rewrite_cmd(out)
    assert "head -10" in new


def test_blocks_unrewritable_producer_redirect():
    # A genuinely un-rewritable shape MUST still block — keeps the block path covered.
    # The producer already redirects stdout to a file → rewrite() bails (the `>` in
    # producer guard) → BLOCK. (Confirms head's promotion to rewrite did NOT remove
    # the block path for shapes that truly can't be rewritten.)
    code, _out, _err = _run("python script.py > out.txt | head -5")
    assert code == 2, f"expected BLOCK on un-rewritable producer-redirect, got {code}"


def test_rewrites_producer_stderr_suppressed():
    # `2>/dev/null` discards stderr; the rewrite preserves that disposition on
    # the producer's file redirect (stdout->FILE, stderr->/dev/null) rather than
    # capturing stderr via 2>&1. (2026-06-13 relaxation of the redirect bail.)
    code, out, _err = _run("python3 find.py 2>/dev/null | tail -20")
    assert code == 0
    new = _rewrite_cmd(out)
    assert "python3 find.py > " in new and "2>/dev/null" in new
    assert "2>&1" not in new  # stderr disposition preserved, not converted
    assert "| tail -20" in new


def test_blocks_producer_stdout_redirected_to_file():
    # stdout already redirected to a file makes the pipe pointless; the
    # producer-side `> file` is not safe to rewrite. Keep blocking.
    code, _out, _err = _run("python3 run.py > out.log 2>&1 | tail -5")
    assert code == 2


def test_blocks_quoted_pipe_mismatch():
    # A `|` inside a double-quoted arg makes positional reconstruction unsafe.
    code, _out, _err = _run('python3 -m pytest -k "a|b" 2>&1 | tail -5')
    assert code == 2


# ── ALLOW cases (unchanged from v3) ────────────────────────────────────────

def test_allows_grep_line_buffered():
    code, _out, _err = _run("python s.py | grep --line-buffered ERR")
    assert code == 0


def test_allows_tail_follow():
    code, out, _err = _run("python s.py 2>&1 | tail -f /tmp/x.log")
    assert code == 0
    assert out == ""  # allow = no rewrite JSON


def test_allows_short_running_producer():
    code, out, _err = _run("ls -la | head -5")
    assert code == 0 and out == ""


def test_allows_chained_producer_not_long_running():
    code, out, _err = _run("cd bench/ && gh pr view 285 | head -5")
    assert code == 0 and out == ""


def test_allows_no_pipe():
    code, out, _err = _run("python script.py > /tmp/out.log 2>&1")
    assert code == 0 and out == ""


def test_allows_grep_on_log_named_after_pytest():
    cmd = (
        "cd ~/Documents/GitHub/code-search && PYTHONFAULTHANDLER=1 "
        ".venv/bin/python -m pytest tests/integration/test_e2e.py -x -v "
        "> /tmp/claude/pytest-e2e-fh.log 2>&1; echo \"exit=$?\"; "
        "grep -n \"PASSED\" /tmp/claude/pytest-e2e-fh.log | head -30"
    )
    code, out, _err = _run(cmd)
    assert code == 0 and out == "", "instant grep on a static log must not block"


def test_allows_filter_on_python_named_artifact():
    code, out, _err = _run("grep ERR python3-build-output.log | tail -3")
    assert code == 0 and out == ""


def test_allows_newline_chained_short_producer():
    cmd = "python3 -m pytest -q > /tmp/hooktests.log 2>&1\ngrep -E 'passed|failed' /tmp/hooktests.log | tail -5"
    code, out, _err = _run(cmd)
    assert code == 0 and out == ""


# ── pass-through / crash-safety ────────────────────────────────────────────

def test_non_bash_tool_passes():
    code, _out, _err = run_hook(HOOK, make_write_input("/tmp/x.py", "print('hi') | head"))
    assert code == 0


def test_empty_stdin_does_not_crash():
    import subprocess

    from conftest import HOOKS_DIR, PYTHON
    r = subprocess.run([PYTHON, str(HOOKS_DIR / HOOK)], input="", capture_output=True,
                       text=True, encoding="utf-8", timeout=10)
    assert r.returncode == 0


# ── audit logging (feeds bin/hook-fire-report.py auto-fix metric) ───────────

def test_audit_log_skipped_under_test(tmp_path):
    # conftest sets CLAUDE_HOOK_TEST=1 for the whole suite → the guard must NOT
    # write an audit entry, else the test suite contaminates the friction metric.
    code, _out, _err = run_hook(HOOK, make_bash_input("pytest -q | tail -20"),
                                env={"CLAUDE_AUDIT_DIR": str(tmp_path)})
    assert code == 0  # rewrite path
    assert not list(tmp_path.glob("bash-tail-buffering-*.jsonl")), \
        "guard wrote an audit entry under CLAUDE_HOOK_TEST — would contaminate the metric"


def test_audit_log_records_autofix_and_block_in_production(tmp_path):
    # With CLAUDE_HOOK_TEST cleared, the guard logs auto-fixed (rewrite) and
    # blocked (an un-rewritable quoted pipe) so hook-fire-report can read the breakdown.
    import os
    import subprocess

    from conftest import HOOKS_DIR, PYTHON
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_HOOK_TEST"}
    env["CLAUDE_AUDIT_DIR"] = str(tmp_path)

    def fire(cmd):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(tmp_path)})
        subprocess.run([PYTHON, str(HOOKS_DIR / HOOK)], input=payload, capture_output=True,
                       text=True, encoding="utf-8", timeout=10, env=env)

    fire("pytest -q | tail -20")               # auto-fix (tail consumer)
    fire("pytest -q > out.txt | tail -5")      # block: producer already redirects stdout → rewrite() bails (None)
    logs = list(tmp_path.glob("bash-tail-buffering-*.jsonl"))
    assert logs, "no audit log written with CLAUDE_HOOK_TEST cleared"
    actions = [json.loads(l)["action"]
               for l in logs[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert "auto-fixed" in actions and "blocked" in actions, f"actions={actions}"


# --- v6 (2026-07-26): the rewrite must PRESERVE the producer's exit code ---
# Without this the rewrite ends on `cat FILE | filter`, so the command's status
# is the filter's (~always 0) and the producer's is discarded. INCIDENT: a
# `pr-merge-verified.py ... | tail -25` run reported "exit code 0" for a PR that
# had TIMED OUT in the merge queue (that script exits 2 on timeout, 0 only on
# MERGED). The guard rewrote and approved it as "buffering-safe" while the exit
# code still lied.

# The rewrite is a POSIX shell script ($? capture, /tmp paths). The two tests
# that EXECUTE it need a real POSIX shell; the string-assertion test below is
# platform-independent and must keep running everywhere, including the
# windows-2022 matrix leg.
_POSIX_SHELL = _shutil.which("zsh") or _shutil.which("bash")
_needs_posix_shell = _pytest.mark.skipif(
    _os.name == "nt" or _POSIX_SHELL is None,
    reason="rewrite executes a POSIX shell script; no zsh/bash on this platform",
)


def test_rewrite_captures_and_reexits_producer_status():
    _code, out, _err = _run("pytest -q | tail -20")
    cmd = _rewrite_cmd(out)
    assert "__tbg_rc=$?" in cmd, f"no rc capture in rewrite:\n{cmd}"
    assert cmd.rstrip().endswith("exit $__tbg_rc"), f"rewrite must end by re-exiting rc:\n{cmd}"
    # rc must be captured IMMEDIATELY after the producer, before the filter runs.
    lines = [l for l in cmd.splitlines() if l.strip()]
    assert lines[1].strip() == "__tbg_rc=$?", f"rc capture not adjacent to producer:\n{cmd}"


@_needs_posix_shell
def test_rewritten_command_actually_exits_nonzero_end_to_end(tmp_path):
    """Execute the rewrite for real -- a failing producer must fail the command.

    This is the seam the unit assertions above cannot cross: string-checking the
    rewrite proves the text, not the shell behavior.
    """
    import subprocess
    producer = tmp_path / "fails.py"
    producer.write_text("import sys\nprint('boom')\nsys.exit(2)\n", encoding="utf-8")
    _code, out, _err = _run(f"python3 {producer} 2>&1 | tail -5")
    cmd = _rewrite_cmd(out)
    p = subprocess.run([_POSIX_SHELL, "-c", cmd], capture_output=True, text=True, timeout=30)
    assert p.returncode == 2, f"exit code not preserved (got {p.returncode}):\n{cmd}"
    assert "boom" in p.stdout, "filtered output lost"


@_needs_posix_shell
def test_rewritten_command_still_exits_zero_on_success(tmp_path):
    import subprocess
    producer = tmp_path / "ok.py"
    producer.write_text("print('fine')\n", encoding="utf-8")
    _code, out, _err = _run(f"python3 {producer} 2>&1 | tail -5")
    cmd = _rewrite_cmd(out)
    p = subprocess.run([_POSIX_SHELL, "-c", cmd], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, f"success wrongly reported as failure ({p.returncode})"
    assert "fine" in p.stdout


# ── v7 (2026-07-28): the GIT-GATING pipe — BLOCK, never rewrite ──────────────
#
# A state-changing git verb piped to a filter whose status then gates an `&&`.
# Disjoint from the buffering checks above: those need a LONG-RUNNING producer,
# and gating git commands are instant (which is why they slipped through for 4
# documented recurrences). Detection was narrowed by a replay over 38,317 real
# historical Bash commands — see the v7 block in the hook for the four
# iterations and why the trailing `&&` is the discriminator.

def test_git_gating_blocks_the_verbatim_2026_07_22_incident():
    """The incident: merge REFUSED over another session's dirty files, tail
    exited 0, the `&&` proceeded, HEAD never moved. MUST block."""
    code, _out, err = _run(
        "git merge --ff-only origin/main 2>&1 | tail -1 && git rebase origin/main"
    )
    assert code == 2, f"expected BLOCK (exit 2), got {code}"
    assert "gates an `&&`" in err or "state-changing git" in err


def test_git_gating_blocks_across_stderr_redirect():
    """`2>&1` contains `&` — an earlier draft excluded `&` from the pre-pipe
    span and so MISSED every real incident. This pins that regression."""
    code, _out, _err = _run("git checkout main 2>&1 | tail -2 && git rebase origin/main")
    assert code == 2, f"expected BLOCK, got {code}"


def test_git_gating_blocks_stash_push_gate():
    code, _out, _err = _run("git stash push -m wip -- f.py | tail -1 && echo done")
    assert code == 2, f"expected BLOCK, got {code}"


def test_git_gating_blocks_pull_rebase_gate():
    code, _out, _err = _run(
        "git pull --rebase origin main 2>&1 | tail -10 && git log --oneline -1"
    )
    assert code == 2, f"expected BLOCK, got {code}"


def test_git_gating_allows_read_only_stash_list():
    """40% of the STAGED spec's historical matches were this class. Read-only:
    a masked status harms nothing, so blocking it is pure friction."""
    code, _out, _err = _run("git stash list | head -5 && echo next")
    assert code == 0, f"read-only inspection must PASS, got {code}"


def test_git_gating_allows_read_only_log_and_status():
    for cmd in (
        "git log --oneline main..origin/main | head -5 && echo next",
        "git status --short | head -3 && echo next",
        "git diff --stat | tail -3 && echo next",
        "git stash show -p stash@{0} | head -5 && echo next",
    ):
        code, _out, _err = _run(cmd)
        assert code == 0, f"read-only must PASS: {cmd!r} got {code}"


def test_git_gating_allows_terminal_push_pipe_no_gate():
    """`git push ... | tail -20` with nothing chained is idiomatic noise-trimming
    — nobody consumes the status. Blocking it took the replay rate to 5.05%."""
    code, _out, _err = _run("git push -u origin branch 2>&1 | tail -20")
    assert code == 0, f"terminal (non-gating) pipe must PASS, got {code}"


def test_git_gating_allows_separator_between_verb_and_pipe():
    """`git merge ... && git log | head` — the pipe belongs to the LOG command,
    so the merge's status is NOT what gets masked; the `&&` already gates it."""
    code, _out, _err = _run("git merge --ff-only origin/main && git log --oneline | head -3")
    assert code == 0, f"separator form must PASS, got {code}"


def test_git_gating_ignores_pattern_inside_a_quoted_string():
    """Runs on the SANITIZED command, so a pattern in a quoted arg or heredoc
    body cannot trigger it (the self-referential-probe class)."""
    code, _out, _err = _run(
        "echo 'git merge --ff-only origin/main | tail -1 && next' > /tmp/claude/note.txt"
    )
    assert code == 0, f"quoted-string mention must PASS, got {code}"


def test_git_gating_message_names_the_recurrence_and_the_fixes():
    _code, _out, err = _run("git merge --ff-only origin/main 2>&1 | tail -1 && echo x")
    assert "4th documented recurrence" in err
    assert "pipefail is unset" in err
    assert "SEPARATE Bash calls" in err or "rc=$?" in err


# ── v8: trailing `;`-chained command swallows a verdict command's exit status ──
# Installed 2026-07-31 from hooks/staged/trailing-command-swallows-verdict-exit.spec.md.
# Measured over 49,542 historical Bash commands: 607 would block (1.225%).

def test_trailing_status_swallow_blocks_the_known_positive():
    """THE 5x-recurring shape (#1788, #1785 x2, #1818, #1819).

    `verdict > log 2>&1; echo "EXIT=$?"; tail -8 log` — the echo writes the code
    to STDOUT while `tail` becomes `$?`, so under run_in_background the harness
    reports success for a failed verdict.
    """
    code, _out, err = _run(
        'python3 bin/pr-merge-verified.py 1788 --repo o/r > /tmp/m.txt 2>&1; '
        'echo "EXIT=$?"; tail -8 /tmp/m.txt'
    )
    assert code == 2, f"the known-positive must BLOCK, got {code}"
    # Must name the TRUE status-setter (the LAST command), not the mid-chain echo.
    assert "`tail`" in err
    assert "`echo`" not in err


def test_trailing_status_swallow_honours_explicit_propagation():
    """`exit $?` DOES preserve the code — must not block."""
    code, _out, _err = _run(
        "python3 bin/pr-merge-verified.py 42 --repo o/r > /tmp/m.txt 2>&1; exit $?"
    )
    assert code == 0, f"explicit propagation must PASS, got {code}"


def test_trailing_status_swallow_allows_verdict_command_last():
    """Verdict command LAST in the chain — its status is already intact."""
    code, _out, _err = _run("mkdir -p /tmp/x; python3 bin/pr-merge-verified.py 42")
    assert code == 0, f"verdict-last must PASS, got {code}"


def test_trailing_status_swallow_allows_redirect_only():
    code, _out, _err = _run(
        "python3 bin/pr-merge-verified.py 42 --repo o/r > /tmp/m.txt 2>&1"
    )
    assert code == 0, f"redirect-only must PASS, got {code}"


def test_trailing_status_swallow_ignores_pattern_in_heredoc():
    """Sanitized-command property: a verdict command inside a heredoc body is inert."""
    code, _out, _err = _run(
        "cat <<'EOF' > /tmp/claude/n.md\n"
        "python3 bin/pr-merge-verified.py 42; echo hi\n"
        "EOF"
    )
    assert code == 0, f"heredoc body must PASS, got {code}"


def test_trailing_status_swallow_does_not_cover_pytest():
    """DELIBERATE NARROWING at install — do not 'fix' this by re-adding pytest.

    The staged spec listed `pytest` and `python3 -m unittest` in VERDICT_COMMANDS.
    Both were dropped because they FAILED
    test_allows_grep_on_log_named_after_pytest, which pins the routine
    "pytest > log; echo exit=$?; grep the log" idiom as ALLOWED. Narrowing the
    tuple is the spec's own first lever under felt friction. Dropping them also
    took the measured fire rate from 3.547% to 1.225% while keeping every one of
    the 5 recorded incidents (all `pr-merge-verified.py`).
    """
    code, _out, _err = _run(
        '.venv/bin/python -m pytest tests/ -x > /tmp/p.log 2>&1; '
        'echo "exit=$?"; grep -n PASSED /tmp/p.log | head -30'
    )
    assert code == 0, f"pytest idiom must stay ALLOWED, got {code}"


# ── v8: wrapper-prefixed producers are long-running (spec: tail-guard-wrapper) ──
# True-delta replay: 324 of 49,542 newly fire (0.654%).

def _long_running(producer):
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "bash-tail-buffering-guard.py"
    s = importlib.util.spec_from_file_location("tbg_wrap", p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m._producer_is_long_running(producer)


def test_wrapper_prefixed_producers_are_detected():
    """The three gaps from the spec's Problem table must flip to True."""
    assert _long_running("timeout 280 python3 run.py")
    assert _long_running("nohup python3 run.py")
    assert _long_running("stdbuf -oL pytest -q")
    assert _long_running("timeout -k 10 5s pytest -q")
    assert _long_running("env FOO=1 timeout 30 python3 x.py")
    assert _long_running("nice -n 10 cargo test")


def test_wrapper_detection_controls_still_true():
    assert _long_running("pytest -q")
    assert _long_running("PYTHONPATH=. python3 x.py")


def test_wrapper_detection_does_not_over_reach():
    """Properties 2 and 3 from the spec's 'Guard against over-reach'.

    A wrapper at ARGUMENT position must not shift the index, a wrapper with no
    command must return False (not index past the end), and v3's
    pytest-in-a-FILENAME false-positive class must stay dead.
    """
    assert not _long_running("timeout 5"), "wrapper with no command"
    assert not _long_running("grep timeout app.log"), "wrapper as an argument"
    assert not _long_running("grep -n PAT /tmp/claude/pytest-e2e.log"), "v3 FP class"
    assert not _long_running("ls -la")


# ---------------------------------------------------------------------------
# v8 (2026-08-01): VERDICT command piped to a filter.
#
# Fourth disjoint shape. The pipeline exits with the FILTER's status and
# pipefail is unset, so the verdict is discarded AT THE PIPE — no `&&` and no
# `;` needed, which is why check_git_gating() and check_trailing_status_swallow()
# structurally cannot see it. Under run_in_background the CONSUMER is the
# harness: the task-completion notification reports the filter's 0 as the task's
# exit code.
# ---------------------------------------------------------------------------


def test_verdict_pipe_blocks_the_verbatim_2026_08_01_incident():
    """The incident: `pr-merge-verified.py 1840 | tail -6` under
    run_in_background. The script exits 0 ONLY on state==MERGED; the harness
    reported tail's 0 and the PR was still OPEN, so a merge was announced to the
    user as complete. This exact command was seen by this hook and classified
    `auto-fixed (buffering)` — the status loss went unchecked. MUST block."""
    code, _out, err = _run(
        "cd ~/.claude && timeout 850 python3 ~/.claude/bin/pr-merge-verified.py "
        "1840 --repo brandyn-s/claude-harness 2>&1 | tail -6"
    )
    assert code == 2, f"expected BLOCK (exit 2), got {code}"
    assert "discarded by the pipe" in err


def test_verdict_pipe_blocks_without_any_chain():
    """No `&&`, no `;` — the pipe alone discards the status. This is the whole
    point of the fourth check; the other two require a chain."""
    code, _out, _err = _run("python3 bin/pr-merge-verified.py 12 --repo x/y | tail -3")
    assert code == 2, f"expected BLOCK, got {code}"


def test_verdict_pipe_blocks_terraform_apply():
    code, _out, _err = _run("terraform apply -auto-approve | tail -20")
    assert code == 2, f"expected BLOCK, got {code}"


def test_verdict_pipe_blocks_gh_pr_merge():
    """2026-08-22 incident: `gh pr merge ... --auto | tail -1` masked a GraphQL
    enablePullRequestAutoMerge rejection as rc=0 (the filter's status), so the
    arm failure shipped as 'armed'. MUST block."""
    code, _out, _err = _run(
        "gh pr merge 1590 --repo o/kb --auto --squash 2>&1 | tail -2"
    )
    assert code == 2, f"expected BLOCK, got {code}"


def test_verdict_gh_pr_merge_bare_last_passes():
    """Unpiped, last in the chain — status intact, must NOT block."""
    code, _out, _err = _run("gh pr merge 2068 --repo o/r --squash --delete-branch")
    assert code == 0, f"bare gh pr merge must PASS, got {code}"


def test_verdict_pipe_allows_pipefail():
    """`set -o pipefail` makes the pipeline adopt the producer's status, so the
    verdict is NOT lost and the guard must stay out of the way."""
    code, _out, _err = _run(
        "set -o pipefail; python3 bin/pr-merge-verified.py 12 | tail -5"
    )
    assert code == 0, f"expected ALLOW, got {code}"


def test_verdict_pipe_allows_explicit_pipestatus():
    """`exit ${PIPESTATUS[0]}` propagates the piped verdict correctly. It was
    rejected by the trailing-swallow check's `$?`-only exemption — a false
    positive on the very idiom this guard's message recommends (found and fixed
    2026-08-01; pre-existing on origin/main)."""
    code, _out, _err = _run(
        "python3 bin/pr-merge-verified.py 12 | tail -5; exit ${PIPESTATUS[0]}"
    )
    assert code == 0, f"expected ALLOW, got {code}"


def test_verdict_pipe_allows_unpiped_verdict():
    code, _out, _err = _run("python3 bin/pr-merge-verified.py 12 --repo x/y")
    assert code == 0, f"expected ALLOW, got {code}"


def test_verdict_pipe_ignores_a_quoted_mention():
    """Runs on the SANITIZED command, so the pattern inside a string is inert."""
    code, _out, _err = _run('echo "pr-merge-verified.py | tail -5" > note.txt')
    assert code == 0, f"expected ALLOW, got {code}"


def test_verdict_pipe_does_not_fire_on_ordinary_pipes():
    """A non-verdict producer piped to tail is a buffering question at most,
    never a lost-verdict one. Guards the block-rate."""
    code, _out, _err = _run("ls -la | tail -5")
    assert code == 0, f"expected ALLOW, got {code}"


# ==========================================================================
# VERDICT MATCH POSITION + BACKGROUNDED VERDICT (2026-08-15)
# Origin: the staged spec `verdict-command-position-anchoring.spec.md`, which BOTH
# defects below closed. That spec existed ONLY in the ~/.claude local arc and never
# reached origin/main, so this pointer has always dangled here. Discovered and resolved
# 2026-08-27: the spec was verified fully obsolete (Defect A shipped as
# `_verdict_at_command_position`, Defect B as `_is_backgrounded`) and deleted rather
# than preserved; a tombstone entry in `bin/staged-spec-staleness.py` reports it STALE
# on the first run if it is ever re-staged from an old checkout.
#
# Defect A: both verdict checks used a bare `_VERDICT_RE.search()` over the whole
# segment, so `pr-merge-verified.py` matched anywhere -- including as a FILE BEING
# READ. Blocked live twice in one session while trying to read the script to check
# its own `--status-file` flag.
#
# This is a RECURRENCE. The guard's v3 changelog (2026-06-12) describes it
# exactly: `grep -n PAT /tmp/pytest-e2e.log | head` blocked because "pytest" was
# in the LOG FILENAME. v3 token-anchored the PRODUCER predicate; v8 added a second
# matcher and did not inherit it.
#
# Defect B: a `&`-backgrounded verdict has no status for a trailing segment to
# overwrite -- and the block hit the exact remedy the guard's own message
# recommends (`nohup ... --status-file ... &` + a readiness check).
# ==========================================================================

def test_verdict_pipe_ignores_the_script_as_a_file_argument():
    """Defect A: reading the verifier is not running it."""
    code, _out, _err = _run("grep -n armed bin/pr-merge-verified.py | head -20")
    assert code == 0, f"expected ALLOW (grep is the command, script is an arg), got {code}"


def test_trailing_swallow_ignores_the_script_as_a_file_argument():
    """Defect A, second call site: same shape through check_trailing_status_swallow."""
    code, _out, _err = _run(
        "grep -n armed bin/pr-merge-verified.py > /tmp/o.txt; wc -l < /tmp/o.txt"
    )
    assert code == 0, f"expected ALLOW, got {code}"


def test_verdict_pipe_still_blocks_via_interpreter():
    """Regression pin for the interpreter skip.

    Every recorded incident used `python3 <script>`, so if anchoring did not skip
    the interpreter the guard would stop firing on the shape it exists to catch.
    """
    code, _out, _err = _run("python3 bin/pr-merge-verified.py 12 | tail -3")
    assert code == 2, f"expected BLOCK (real piped invocation), got {code}"


def test_verdict_pipe_still_blocks_bare_invocation():
    """Anchoring must not require an interpreter to be present."""
    code, _out, _err = _run("./bin/pr-merge-verified.py 12 | tail")
    assert code == 2, f"expected BLOCK, got {code}"


def test_backgrounded_verdict_with_readiness_check_is_allowed():
    """Defect B: the guard's own recommended remedy must not be blocked."""
    code, _out, _err = _run(
        "nohup python3 ~/.claude/bin/pr-merge-verified.py 1898 --repo o/r "
        "--status-file /tmp/claude/m.json > /tmp/claude/m.log 2>&1 &\n"
        'sleep 2; pgrep -f "pr-merge-verified.py 1898"'
    )
    assert code == 0, f"expected ALLOW (backgrounded, no status to swallow), got {code}"


def test_foreground_verdict_then_trailing_command_still_blocks():
    """Defect B's known-negative: without the `&` the swallow is real.

    Without this, the backgrounding exemption could be satisfied by never firing
    on the `;`-trailing shape at all -- which is the coverage the guard exists for.
    """
    code, _out, _err = _run(
        "python3 ~/.claude/bin/pr-merge-verified.py 1898 --repo o/r; echo done"
    )
    assert code == 2, f"expected BLOCK (foreground verdict, status overwritten), got {code}"


def test_redirect_and_is_not_read_as_backgrounding():
    """`2>&1` contains `&` but is not trailing, so it must not exempt the segment."""
    code, _out, _err = _run(
        "python3 ~/.claude/bin/pr-merge-verified.py 1898 --repo o/r > /tmp/v.log 2>&1; echo done"
    )
    assert code == 2, f"expected BLOCK (2>&1 is not backgrounding), got {code}"
