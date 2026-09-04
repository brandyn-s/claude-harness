"""Contract tests for hooks/run-hook, the launcher every hook runs through.

run-hook is the single point of failure for the whole hook system: if it
mis-delivers stdin, swallows stdout/stderr, or rewrites an exit code, every
hook silently stops working while still reporting success. It runs the hook in
the BACKGROUND so its SIGTERM trap can fire promptly (bash defers a trap until
the current foreground child returns), and backgrounding is exactly what makes
stdin fragile — hence these tests.

CRITICAL — the stdin test must feed a PIPE, not a heredoc or a file. Bash
points a background job's stdin at /dev/null only when the parent's stdin is a
pipe; a heredoc is a seekable temp file and passes even in the broken shape.
Verified 2026-07-26: the `<&3` fix was written after a heredoc-based diagnostic
falsely cleared a shape that lost every hook payload. subprocess.run(input=...)
gives a pipe, which is also how Claude Code delivers the real payload.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
RUN_HOOK = HOOKS_DIR / "run-hook"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="run-hook is a bash launcher; the Windows branch needs Git Bash + pythonw",
)


@pytest.fixture()
def probe(request):
    """Write a throwaway hook script into hooks/ and remove it afterwards.

    run-hook resolves its target relative to its own directory, so the probe
    has to live in hooks/. The name is derived from the test to keep parallel
    runs from colliding, and prefixed `zz-` so it sorts clear of real hooks.
    """
    created: list[Path] = []

    def _write(source: str) -> str:
        name = f"zz-probe-{request.node.name}-{len(created)}.py"
        path = HOOKS_DIR / name
        path.write_text(source, encoding="utf-8")
        created.append(path)
        return name

    yield _write
    for path in created:
        path.unlink(missing_ok=True)


def invoke(hook_name: str, payload: dict, timeout: int = 60):
    """Run a hook through run-hook with the payload on a PIPE (see module docstring)."""
    return subprocess.run(
        [str(RUN_HOOK), hook_name],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def test_stdin_payload_reaches_the_hook(probe):
    """The JSON payload must arrive intact — the whole hook protocol depends on it."""
    name = probe(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "print('GOT:' + payload['prompt'])\n"
    )
    done = invoke(name, {"prompt": "payload-marker-42"})
    assert done.returncode == 0, f"stdout={done.stdout!r} stderr={done.stderr!r}"
    assert "GOT:payload-marker-42" in done.stdout


def test_blocking_exit_code_and_stderr_pass_through(probe):
    """exit 2 + stderr is how a hook blocks a tool call; both must survive."""
    name = probe(
        "import sys\n"
        "print('BLOCKED: not allowed', file=sys.stderr)\n"
        "sys.exit(2)\n"
    )
    done = invoke(name, {})
    assert done.returncode == 2
    assert "BLOCKED: not allowed" in done.stderr


def test_success_stdout_passes_through(probe):
    """exit 0 + stdout is how a hook emits a systemMessage warning."""
    name = probe("print('systemMessage payload')\n")
    done = invoke(name, {})
    assert done.returncode == 0
    assert "systemMessage payload" in done.stdout


def test_crash_forwards_nonzero_exit_and_traceback(probe):
    """A crashing hook must not be laundered into a success."""
    name = probe("raise RuntimeError('boom')\n")
    done = invoke(name, {})
    assert done.returncode == 1
    assert "RuntimeError" in done.stderr


def test_termination_is_prompt_and_logged(probe, tmp_path):
    """A timed-out hook must exit promptly, log exit=-1, and leave no orphan child.

    Claude Code enforces a hook's `timeout` by signalling this wrapper, so
    without the trap the fire is invisible to telemetry (verified 2026-07-26:
    zero entries for a killed hook). HOME is redirected so the assertion reads
    an isolated audit log instead of the developer's real one.

    Readiness is GATED on a marker the probe itself writes, never on a sleep.
    run-hook installs its trap before launching the hook, so "the hook started"
    is a genuine happens-before for "the trap is installed" — whereas signalling
    too early hits the default disposition (rc -15, nothing logged) and the test
    flakes. Measured 2026-07-26 on this host: wrapper start-up spanned 1.44s to
    6.63s under load, so any fixed sleep is a guess that fails under contention;
    the gated form was 6/6 deterministic.
    """
    marker = tmp_path / "hook-started"
    name = probe(
        "import pathlib, time\n"
        f"pathlib.Path({str(marker)!r}).write_text('up', encoding='utf-8')\n"
        "time.sleep(30)\n"
    )
    env = dict(os.environ, HOME=str(tmp_path))

    proc = subprocess.Popen(
        [str(RUN_HOOK), name],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdin is not None
    proc.stdin.write(b"{}")
    proc.stdin.close()

    deadline = time.monotonic() + 60
    while not marker.exists() and time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"run-hook exited early with rc={proc.returncode}")
        time.sleep(0.02)
    assert marker.exists(), "hook never started; run-hook did not launch it"

    start = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("run-hook did not exit on SIGTERM — the trap was deferred")
    elapsed = time.monotonic() - start
    assert elapsed < 10, f"exit took {elapsed:.2f}s; the trap should fire promptly"

    audit = tmp_path / ".claude" / "audit"
    entries = [
        json.loads(line)
        for path in sorted(audit.glob("hook-fires-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    killed = [e for e in entries if e.get("hook") == name and e.get("exit") == -1]
    assert killed, f"no exit=-1 telemetry for the killed fire; saw {entries}"

    # The hook process must be reaped, not left running past the wrapper.
    survivors = subprocess.run(
        ["pgrep", "-f", name], capture_output=True, text=True, check=False
    ).stdout.strip()
    assert not survivors, f"orphaned hook child still running: {survivors}"


def test_fire_row_records_elapsed_ms_even_without_epochrealtime(probe, tmp_path):
    """macOS ships bash 3.2, which has no EPOCHREALTIME, so every fire row the
    wrapper wrote there carried ms=null and hook-fire-report's latency view was
    blind on the owner's machine (2026-09-04). The wrapper must fall back to a
    sub-millisecond clock and record an integer."""
    name = probe("import sys, json\njson.load(sys.stdin)\nsys.exit(0)\n")
    env = {**os.environ, "HOME": str(tmp_path)}
    env.pop("CLAUDE_CONFIG_DIR", None)
    proc = subprocess.run([str(RUN_HOOK), name], input=json.dumps({"tool_name": "Bash"}),
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=False, env=env)
    assert proc.returncode == 0, proc.stderr
    audit = tmp_path / ".claude" / "audit"
    rows = [json.loads(line) for path in sorted(audit.glob("hook-fires-*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mine = [r for r in rows if r.get("hook") == name]
    assert mine, rows
    assert isinstance(mine[-1]["ms"], int) and 0 <= mine[-1]["ms"] < 60_000, mine[-1]
