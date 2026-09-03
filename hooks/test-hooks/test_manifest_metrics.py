"""manifest_metrics must not write session state under the test suite.

Regression for a measured instrument corruption. pytest subprocesses inherit
CLAUDE_SESSION_ID from the parent session, and record_block wrote straight to
`~/.claude/session-env/advisory-<hook>-<sid>.json` with no test guard -- so
running the hook suite incremented the LIVE session's block counter.

Measured 2026-08-29: one run of test_bash_security_guard.py injected 97 phantom
blocks. A real session's escalation banner reported 2, then 201, then 396
blocks while its own transcript contained 4 real ones; the jumps were two test
runs. The counter's arithmetic was correct all along (+1 per block, +0 per
allowed command) -- the contamination was entirely fixture-driven.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
SID = "isolation-probe"


def _run(code: str, home: Path, hook_test: bool) -> subprocess.CompletedProcess:
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "CLAUDE_SESSION_ID": SID,
        "PYTHONPATH": str(HOOKS),
    }
    if hook_test:
        env["CLAUDE_HOOK_TEST"] = "1"
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=60, env=env, check=False)


BLOCK_TWICE = (
    "import manifest_metrics as m\n"
    "print(m.record_block('probe-guard'))\n"
    "print(m.record_block('probe-guard'))\n"
)


def _marker(home: Path) -> Path:
    return home / ".claude" / "session-env" / f"advisory-probe-guard-{SID[:12]}.json"


def test_record_block_writes_no_marker_under_hook_test(tmp_path):
    """The defect: fixtures must not touch the live session counter."""
    proc = _run(BLOCK_TWICE, tmp_path, hook_test=True)
    assert proc.returncode == 0, proc.stderr
    assert not _marker(tmp_path).exists(), \
        "CLAUDE_HOOK_TEST must suppress the on-disk block marker entirely"


def test_record_block_still_counts_in_process_under_hook_test(tmp_path):
    """Suppressing the write must not make the return value useless."""
    proc = _run(BLOCK_TWICE, tmp_path, hook_test=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["1", "2"], proc.stdout


def test_record_block_persists_when_not_under_hook_test(tmp_path):
    """Known-positive: without the test flag the counter still works.

    Without this the suppression could be total and both tests above would
    still pass, which would hide a broken escalation feature.
    """
    proc = _run(BLOCK_TWICE, tmp_path, hook_test=False)
    assert proc.returncode == 0, proc.stderr
    marker = _marker(tmp_path)
    assert marker.exists(), "a real block must still be recorded"
    assert json.loads(marker.read_text(encoding="utf-8"))["blocks"] == 2
    assert proc.stdout.split() == ["1", "2"], proc.stdout


def test_increment_warning_writes_no_marker_under_hook_test(tmp_path):
    proc = _run("import manifest_metrics as m; m.increment_warning('probe-guard')",
                tmp_path, hook_test=True)
    assert proc.returncode == 0, proc.stderr
    assert not _marker(tmp_path).exists()


def test_audit_writers_produce_no_files_under_hook_test(tmp_path):
    """log_manifest_query / log_advisory_warning also write session-scoped rows."""
    proc = _run(
        "import manifest_metrics as m\n"
        "m.log_manifest_query('probe-guard', 'q', 'r')\n"
        "m.log_advisory_warning('probe-guard', 'Tool', 'op')\n",
        tmp_path, hook_test=True)
    assert proc.returncode == 0, proc.stderr
    audit = tmp_path / ".claude" / "audit"
    written = sorted(p.name for p in audit.glob("*.jsonl")) if audit.is_dir() else []
    assert written == [], f"expected no audit rows under test mode, got {written}"


def test_guard_suite_leaves_block_counter_untouched(tmp_path):
    """End-to-end: the real suite, run the way CI runs it, writes no marker.

    This is the seam that actually failed. The unit tests above cover the
    function; only this one covers the pytest-inherits-CLAUDE_SESSION_ID path
    that produced the 97 phantom blocks.
    """
    env = dict(os.environ)
    env["CLAUDE_SESSION_ID"] = SID
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    live = Path.home() / ".claude" / "session-env" / f"advisory-bash-security-guard-{SID[:12]}.json"
    live.unlink(missing_ok=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "test_bash_security_guard.py", "-q",
             "-k", "block"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True, text=True, timeout=280, env=env, check=False)
        assert proc.returncode == 0, proc.stdout[-2000:]
        blocks = 0
        if live.exists():
            blocks = json.loads(live.read_text(encoding="utf-8")).get("blocks", 0)
        assert blocks == 0, (
            f"guard suite injected {blocks} phantom blocks into the session counter")
    finally:
        live.unlink(missing_ok=True)


# ── Review 2026-09-03: session id must come from the hook payload ─────────
#
# Claude Code delivers `session_id` in the stdin JSON; it does NOT export
# CLAUDE_SESSION_ID / CLAUDE_CODE_SESSION_ID to hook processes. Keying the
# marker on the env var therefore collapsed every real session into one
# `advisory-<hook>-default.json`, and the "blocked N TIMES THIS SESSION"
# banner became a lifetime counter (measured: three sessions, one marker, 3).

def _run_env(code: str, home: Path, extra_env: dict) -> subprocess.CompletedProcess:
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONPATH": str(HOOKS),
    }
    env.update(extra_env)
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=60, env=env, check=False)


def test_record_block_keys_marker_on_explicit_session_id(tmp_path):
    code = (
        "import manifest_metrics as m\n"
        "print(m.record_block('probe-guard', session_id='session-aaaa'))\n"
        "print(m.record_block('probe-guard', session_id='session-bbbb'))\n"
    )
    proc = _run_env(code, tmp_path, {})  # deliberately no CLAUDE_SESSION_ID
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["1", "1"], proc.stdout
    markers = sorted(
        p.name for p in (tmp_path / ".claude" / "session-env").glob("advisory-probe-guard-*.json")
    )
    assert markers == [
        "advisory-probe-guard-session-aaaa.json",
        "advisory-probe-guard-session-bbbb.json",
    ], markers


def test_repeat_escalation_is_silent_on_first_block_of_a_new_session(tmp_path):
    code = (
        "import manifest_metrics as m\n"
        "m.repeat_escalation('probe-guard', session_id='session-aaaa')\n"
        "print(repr(m.repeat_escalation('probe-guard', session_id='session-bbbb')))\n"
    )
    proc = _run_env(code, tmp_path, {})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "''", proc.stdout
