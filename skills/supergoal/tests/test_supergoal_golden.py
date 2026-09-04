"""End-to-end golden tests for supergoal scripts.

Pattern that other skills can copy:
    tests/golden/<scenario>.input         Input fixture
    tests/test_<skill>_golden.py          Pytest module that:
        - invokes the skill's scripts against the fixture
        - asserts exit code + output schema
        - uses a tempdir for state to avoid polluting ~/.claude/supergoal/

These run as part of the hook test suite (validate CI workflow:
`pytest hooks/test-hooks/ -q`). Per-skill golden tests run when
discovered by pytest collection from the skills/ tree.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"
GOLDEN = Path(__file__).resolve().parent / "golden"


def _run(*args, env=None, cwd=None):
    """Run a Python script; return (rc, stdout, stderr)."""
    e = os.environ.copy()
    if env:
        e.update(env)
    r = subprocess.run(
        [sys.executable, *args],
        capture_output=True, text=True, env=e, cwd=cwd,
    )
    return r.returncode, r.stdout, r.stderr


def test_parse_plan_minimal_round_trip(tmp_path):
    """parse_plan.py on a minimal valid plan: exits 0, writes state.json
    with all required schema fields, .active pointer present."""
    state_root = tmp_path / "supergoal"
    state_root.mkdir()

    # Copy fixture so the plan-path resolves uniquely
    plan = tmp_path / "minimal.plan.md"
    shutil.copy(GOLDEN / "minimal.plan.md", plan)

    rc, out, err = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan),
        "--reset",
        "--state-dir", str(state_root),
    )
    assert rc == 0, f"parse_plan.py failed: rc={rc}\nstdout={out}\nstderr={err}"

    # State file
    slug = plan.stem
    state_path = state_root / slug / "state.json"
    assert state_path.exists(), f"state.json not created at {state_path}"
    state = json.loads(state_path.read_text())

    # Schema completeness — every field the hook prompt reads must exist.
    required = [
        "plan_path", "plan_slug", "plan_sha256", "plan_mtime",
        "demo", "falsifiers", "metric_commands",
        "consecutive_blocks", "consecutive_no_progress",
        "turn_budget_remaining", "wallclock_used_seconds",
        "started_at", "paused_at", "lineage",
        "prior_arc_ledger", "prior_arc_count",  # the bug that bit us earlier
    ]
    missing = [k for k in required if k not in state]
    assert not missing, f"state.json missing fields: {missing}"

    # .active pointer
    active = state_root / ".active"
    assert active.exists(), ".active pointer not written"
    assert active.read_text().strip() == str(state_path), \
        ".active does not point at our state.json"


def test_write_terminal_records_int_turn(tmp_path):
    """write_terminal.py exit event must use int turn (not the string
    'exit' — that was the audit-found bug fixed earlier this branch).

    Tests both modes per references/headless.md:
    - Interactive (state.headless=false): exit code is always 0
    - Headless (state.headless=true): exit code maps the exit_reason
      (budget-exhausted → 11 per the table)

    Under pytest the subprocess has no TTY, so we explicitly skip
    --headless to force interactive mode for the rc==0 contract path.
    """
    state_root = tmp_path / "supergoal"
    state_root.mkdir()
    plan = tmp_path / "minimal.plan.md"
    shutil.copy(GOLDEN / "minimal.plan.md", plan)

    rc, _, err = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan), "--reset", "--state-dir", str(state_root),
    )
    assert rc == 0, err

    slug = plan.stem
    state_dir = state_root / slug

    # Force interactive mode by patching state.headless before write_terminal
    # runs — pytest subprocesses don't have a TTY so _auto_headless() returns
    # True, which would map budget-exhausted to exit code 11 per headless.md.
    state_path = state_dir / "state.json"
    state = json.loads(state_path.read_text())
    state["headless"] = False
    state_path.write_text(json.dumps(state, indent=2))

    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    rc, _, err = _run(
        str(SCRIPTS / "write_terminal.py"),
        str(state_dir),
        "budget-exhausted",
        env={"SUPERGOAL_PLANS_DIR": str(plans_dir)},
    )
    assert rc == 0, f"write_terminal.py failed: rc={rc}, err={err}"

    events = (state_dir / "events.jsonl").read_text().splitlines()
    exited = [json.loads(l) for l in events if json.loads(l).get("event") == "exited"]
    assert len(exited) == 1, "expected exactly one exited event"
    turn = exited[0]["turn"]
    assert isinstance(turn, int), f"exit event turn must be int, got {type(turn).__name__}: {turn!r}"


def test_write_terminal_headless_maps_exit_code(tmp_path):
    """Headless mode (state.headless=true) maps exit_reason → process exit
    code per references/headless.md. The audit caught that scripts didn't
    actually implement the documented mapping; this guards the seam."""
    state_root = tmp_path / "supergoal"
    state_root.mkdir()
    plan = tmp_path / "minimal.plan.md"
    shutil.copy(GOLDEN / "minimal.plan.md", plan)

    rc, _, err = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan), "--reset", "--headless",
        "--state-dir", str(state_root),
    )
    assert rc == 0, err

    slug = plan.stem
    state_dir = state_root / slug

    # Verify state.headless is recorded
    state = json.loads((state_dir / "state.json").read_text())
    assert state.get("headless") is True, "state.headless should be True after --headless"

    # Map exit_reason → expected code per references/headless.md
    cases = [
        ("budget-exhausted", 11),
        ("plan-tampered", 12),
        ("scorer-broken", 13),
        ("stuck-no-progress", 14),
        ("falsifier-noop-triggered", 10),
        ("success", 0),
    ]
    # Redirect the terminal doc + bug ledger into tmp — without this, every
    # test run rewrote the REAL ~/Documents/knowledge-base/plans/ terminal
    # doc and appended 5 placeholder ledger rows (B38-B52 pollution,
    # 2026-06-12 /pr-fix finding).
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()

    for exit_reason, expected_code in cases:
        # Fresh state per case — write_terminal is idempotent on same exit_reason
        # but archives the old one, which would obscure exit-code mapping for
        # subsequent cases.
        sub_state = state_root / f"case-{exit_reason}"
        sub_state.mkdir()
        shutil.copy(state_dir / "state.json", sub_state / "state.json")
        # patch state.json's events_path to point into sub_state
        s = json.loads((sub_state / "state.json").read_text())
        s["events_path"] = str(sub_state / "events.jsonl")
        (sub_state / "state.json").write_text(json.dumps(s, indent=2))

        rc, _, err = _run(
            str(SCRIPTS / "write_terminal.py"),
            str(sub_state),
            exit_reason,
            env={"SUPERGOAL_PLANS_DIR": str(plans_dir)},
        )
        assert rc == expected_code, (
            f"write_terminal.py {exit_reason!r}: rc={rc}, expected={expected_code}\n"
            f"  stderr: {err}"
        )

    # The override must actually receive the artifacts — proves the redirect
    # worked end-to-end (terminal doc written, ledger appended) rather than
    # silently falling through to the real KB.
    assert (plans_dir / "minimal.plan-terminal.md").exists(), \
        "terminal doc not written into SUPERGOAL_PLANS_DIR"
    ledger = plans_dir / "_bug_ledger.md"
    assert ledger.exists() and "budget-exhausted" in ledger.read_text(), \
        "bug ledger not appended in SUPERGOAL_PLANS_DIR"


def test_write_terminal_rejects_unknown_exit_reason(tmp_path):
    """write_terminal.py must reject unknown exit_reason strings — silent
    success on bad input was Finding B in the audit (skill-rerun supergoal)."""
    state_root = tmp_path / "supergoal"
    state_root.mkdir()
    plan = tmp_path / "minimal.plan.md"
    shutil.copy(GOLDEN / "minimal.plan.md", plan)

    rc, _, err = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan), "--reset", "--state-dir", str(state_root),
    )
    assert rc == 0, err

    slug = plan.stem
    state_dir = state_root / slug

    rc, _, err = _run(
        str(SCRIPTS / "write_terminal.py"),
        str(state_dir),
        "completely-unknown",
        env={"SUPERGOAL_PLANS_DIR": str(tmp_path / "plans")},
    )
    assert rc != 0, "write_terminal.py must reject unknown exit_reason"
    assert "invalid exit_reason" in err.lower(), f"expected enum-rejection error, got: {err}"


def test_write_terminal_stub_state_clean_error(tmp_path):
    """A stub state file (events_path present but no plan_slug/plan_path)
    must produce the clean missing-required-field error — not a KeyError
    traceback — and must NOT be mutated (no exit_reason marked, no exited
    event appended) by the failed run."""
    state_dir = tmp_path / "stub"
    state_dir.mkdir()
    stub = {"events_path": str(state_dir / "events.jsonl")}
    (state_dir / "state.json").write_text(json.dumps(stub))

    rc, _, err = _run(
        str(SCRIPTS / "write_terminal.py"),
        str(state_dir),
        "budget-exhausted",
    )
    assert rc != 0, "stub state must not exit 0"
    assert "Traceback" not in err and "KeyError" not in err, \
        f"expected clean error, got:\n{err}"
    assert "missing required field" in err, f"expected missing-field message, got:\n{err}"
    after = json.loads((state_dir / "state.json").read_text())
    assert "exit_reason" not in after, "stub state must not be marked exited by a failed run"
    assert not (state_dir / "events.jsonl").exists(), \
        "no exited event may be appended for a rejected stub state"


def test_parse_plan_exit_codes(tmp_path):
    """parse_plan.py setup-time exit codes must match references/headless.md."""
    state_root = tmp_path / "supergoal"
    state_root.mkdir()

    # Exit 20: plan file not found
    rc, _, _ = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(tmp_path / "nonexistent.md"),
        "--state-dir", str(state_root),
    )
    assert rc == 20, f"missing plan file should exit 20 (parse-failed), got {rc}"

    # Exit 20: plan missing required fields
    bad_plan = tmp_path / "bad.plan.md"
    bad_plan.write_text("Just some text. No demo line, no falsifiers.")
    rc, _, _ = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(bad_plan), "--reset",
        "--state-dir", str(state_root),
    )
    assert rc == 20, f"plan missing required fields should exit 20 (parse-failed), got {rc}"

    # Exit 20: unknown flag
    plan = tmp_path / "minimal.plan.md"
    shutil.copy(GOLDEN / "minimal.plan.md", plan)
    rc, _, _ = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan), "--unknown-flag",
    )
    assert rc == 20, f"unknown arg should exit 20 (parse-failed), got {rc}"


def test_state_io_locked_state_round_trip(tmp_path):
    """state_io.locked_state should read+write atomically. Verifies the
    cross-platform fcntl/msvcrt fallback works (this is what would
    crash on Windows if the refactor regressed)."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        from state_io import locked_state
    finally:
        sys.path.pop(0)

    state_path = tmp_path / "state.json"
    state_path.write_text('{"counter": 0}')

    with locked_state(state_path) as s:
        s["counter"] += 1

    assert json.loads(state_path.read_text())["counter"] == 1


def test_parse_plan_space_form_budget_flags(tmp_path):
    """Space-separated budget flags must parse identically to the `=` forms
    (--help documents 'seconds or 1h/30m'; budget.md promises '2M'), and bad
    or missing values must exit 20 cleanly — no ValueError/IndexError
    traceback (references/headless.md: 20 = parse-failed / bad args)."""
    state_root = tmp_path / "supergoal"
    state_root.mkdir()
    plan = tmp_path / "minimal.plan.md"
    shutil.copy(GOLDEN / "minimal.plan.md", plan)

    # Happy path: suffixed values accepted space-separated, same as `=` forms
    rc, _, err = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan), "--reset", "--state-dir", str(state_root),
        "--budget-wallclock", "30m", "--budget-tokens", "2M",
    )
    assert rc == 0, f"suffixed space-form budgets should parse: rc={rc}\n{err}"
    state = json.loads((state_root / plan.stem / "state.json").read_text())
    assert state["time_budget_seconds"] == 1800
    assert state["token_budget_advisory"] == 2_000_000

    # Bad value (both forms) and missing value: clean exit 20, no traceback
    for extra in (["--budget-turns", "abc"],
                  ["--budget-turns=abc"],
                  ["--budget-wallclock"]):
        rc, _, err = _run(
            str(SCRIPTS / "parse_plan.py"),
            str(plan), "--reset", "--state-dir", str(state_root), *extra,
        )
        assert rc == 20, f"bad budget args {extra} should exit 20, got {rc}\n{err}"
        assert "Traceback" not in err, f"bad budget args {extra} must not traceback:\n{err}"


def test_default_budgets_are_bounded_and_xl_requires_opt_in(tmp_path):
    sys.path.insert(0, str(SCRIPTS))
    try:
        from parse_plan import BUDGET_DEFAULTS
    finally:
        sys.path.pop(0)

    assert BUDGET_DEFAULTS["M"]["turns"] == 20
    assert BUDGET_DEFAULTS["M"]["wallclock_seconds"] == 3600
    assert BUDGET_DEFAULTS["L"]["turns"] == 40
    assert BUDGET_DEFAULTS["L"]["wallclock_seconds"] == 7200
    assert BUDGET_DEFAULTS["XL"]["turns"] == 80
    assert BUDGET_DEFAULTS["XL"]["wallclock_seconds"] == 14400

    state_root = tmp_path / "supergoal"
    state_root.mkdir()
    plan = tmp_path / "xl.plan.md"
    source = (GOLDEN / "minimal.plan.md").read_text()
    plan.write_text("Effort: XL\n" + source)

    rc, _, err = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan), "--reset", "--state-dir", str(state_root),
    )
    assert rc == 20
    assert "XL requires explicit user opt-in" in err

    rc, _, err = _run(
        str(SCRIPTS / "parse_plan.py"),
        str(plan), "--reset", "--state-dir", str(state_root),
        "--budget-turns", "80", "--budget-wallclock", "4h",
    )
    assert rc == 0, err
