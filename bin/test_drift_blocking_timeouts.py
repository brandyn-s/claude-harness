#!/usr/bin/env python3
"""Fixtures for H4: blocking-guard timeout drift between live and example settings.

THE DEFECT

`settings.example.json` -- the documented interface for adopters and the recovery
path -- carried 2-5 second timeouts where live settings use 15-30. Measured
2026-07-26: 44 of 57 shared hook registrations drifted, including EVERY blocking
security guard (bash-security-guard 30->3, destructive-ops-guard 30->3,
pre-agent-dispatch 30->3, security-write-confirm 30->3, write-edit-dispatcher 30->5,
staged-additions-guard 30->5, ...).

Why that is a security regression rather than cosmetic: `hooks/run-hook` documents
that a timed-out PreToolUse hook never returns its blocking decision, so the
operation proceeds UNGUARDED. Measured wrapper start-up on this host is 1.4-4.1s
(rules/incidents/verify-effectiveness.md), so a 3s budget can kill the guard before
its body runs -- a fresh install is materially weaker than the live host in exactly
the layer meant to be strongest.

`architecture-drift-check.py` reported OK throughout, because it compared event names
and script presence but never timeouts. This adds that comparison and tests it.

Run: pytest bin/test_drift_blocking_timeouts.py -q
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "adc", REPO / "bin" / "architecture-drift-check.py"
)
assert _SPEC and _SPEC.loader
adc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(adc)


def cfg(event, script, timeout):
    return {
        "hooks": {
            event: [
                {"hooks": [{"type": "command", "command": f'"$HOME/x" {script}',
                            "timeout": timeout}]}
            ]
        }
    }


def _script_name(hook):
    """Read a hook script from current exec form or legacy shell form."""
    args = hook.get("args", [])
    if isinstance(args, list):
        scripts = [arg for arg in args if isinstance(arg, str) and arg.endswith(".py")]
        if scripts:
            return Path(scripts[-1]).name
    command = str(hook.get("command", ""))
    return Path(command.split()[-1].strip('"')).name if command else None


def test_script_name_reads_exec_and_legacy_forms():
    assert _script_name({"command": "/x/run-hook", "args": ["guard.py"]}) == "guard.py"
    assert _script_name({"command": '"$HOME/x/run-hook" legacy.py'}) == "legacy.py"


# ---------------------------------------------------------------------------
# the check must FAIL on drift
# ---------------------------------------------------------------------------
def test_example_lower_than_live_is_flagged():
    """THE H4 FIX: a weaker example budget for a blocking guard is a hard failure."""
    issues = adc._check_blocking_timeouts(
        cfg("PreToolUse", "bash-security-guard.py", 30),
        cfg("PreToolUse", "bash-security-guard.py", 3),
    )
    assert len(issues) >= 1
    assert any("bash-security-guard.py" in i and "unguarded" in i for i in issues)


def test_equal_timeouts_are_clean():
    issues = adc._check_blocking_timeouts(
        cfg("PreToolUse", "guard.py", 30), cfg("PreToolUse", "guard.py", 30)
    )
    assert issues == []


def test_example_higher_than_live_is_allowed():
    """A MORE generous example budget is not a weakening."""
    issues = adc._check_blocking_timeouts(
        cfg("PreToolUse", "guard.py", 20), cfg("PreToolUse", "guard.py", 30)
    )
    assert issues == []


def test_below_floor_is_flagged_even_when_both_agree():
    """Agreement at 3s is not safety -- wrapper start-up alone is 1.4-4.1s."""
    issues = adc._check_blocking_timeouts(
        cfg("PreToolUse", "guard.py", 3), cfg("PreToolUse", "guard.py", 3)
    )
    assert issues, "a blocking guard at 3s in BOTH files must still be flagged"
    assert any("floor" in i for i in issues)


def test_non_blocking_events_are_ignored():
    """Loggers/fixers may legitimately differ; only blocking events are enforced."""
    issues = adc._check_blocking_timeouts(
        cfg("PostToolUse", "logger.py", 30), cfg("PostToolUse", "logger.py", 3)
    )
    assert issues == []


def test_precompact_is_treated_as_blocking():
    """PreCompact can block compaction (exit 2), so it is in scope."""
    issues = adc._check_blocking_timeouts(
        cfg("PreCompact", "precompact-ledger.py", 20),
        cfg("PreCompact", "precompact-ledger.py", 5),
    )
    assert issues


def test_missing_or_nonint_timeouts_do_not_crash():
    live = cfg("PreToolUse", "g.py", 30)
    ex = cfg("PreToolUse", "g.py", None)
    assert adc._check_blocking_timeouts(live, ex) == []
    assert adc._check_blocking_timeouts({}, {}) == []


def test_scripts_only_in_one_file_are_not_compared_here():
    """Presence drift is a DIFFERENT check; this one is about budgets."""
    issues = adc._check_blocking_timeouts(
        cfg("PreToolUse", "only-live.py", 30), cfg("PreToolUse", "only-example.py", 30)
    )
    assert issues == []


# ---------------------------------------------------------------------------
# the shipped tree must satisfy the gate it now enforces
# ---------------------------------------------------------------------------
def test_repo_has_no_blocking_timeout_drift():
    live = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    ex = json.loads((REPO / "settings.example.json").read_text(encoding="utf-8"))
    issues = adc._check_blocking_timeouts(live, ex)
    assert issues == [], "blocking-guard timeout drift:\n" + "\n".join(issues)


def test_no_shared_registration_drifts_at_all():
    """Stronger than the gate: the example should mirror live budgets exactly.

    The gate only fails on WEAKENING (example < live) plus a hard floor, so this
    documents the tighter property the tree currently satisfies.
    """
    live = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    ex = json.loads((REPO / "settings.example.json").read_text(encoding="utf-8"))

    def tmap(cfg_):
        out = {}
        for event, entries in (cfg_.get("hooks") or {}).items():
            for entry in entries or []:
                for h in entry.get("hooks", []) or []:
                    script = _script_name(h)
                    if script:
                        out[(event, script)] = h.get("timeout")
        return out

    a, b = tmap(live), tmap(ex)
    drift = {k: (a[k], b[k]) for k in set(a) & set(b) if a[k] != b[k]}
    assert drift == {}, f"{len(drift)} shared registrations drift: {drift}"


def test_drift_check_exits_zero_on_this_tree():
    p = subprocess.run(
        [sys.executable, str(REPO / "bin" / "architecture-drift-check.py")],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    assert p.returncode == 0, p.stdout[-1500:]


@pytest.mark.parametrize("script", [
    "bash-security-guard.py",
    "destructive-ops-guard.py",
    "pre-agent-dispatch.py",
    "security-write-confirm.py",
    "write-edit-dispatcher.py",
])
def test_named_security_guards_meet_the_floor_in_both_files(script):
    """Spot-check the guards whose failure is most consequential."""
    for fname in ("settings.json", "settings.example.json"):
        cfg_ = json.loads((REPO / fname).read_text(encoding="utf-8"))
        found = adc._hook_timeouts(cfg_, "PreToolUse").get(script)
        if found is None:
            continue  # not registered in that file; presence is another check
        assert found > adc.MIN_BLOCKING_TIMEOUT, f"{script} in {fname} is {found}s"

# ---------------------------------------------------------------------------
# install.sh is the THIRD source of hook timeouts and drifted independently
# ---------------------------------------------------------------------------
def test_installer_blocking_specs_meet_the_floor():
    """install.sh hardcodes its own hook specs and drifted separately from the example.

    Layout: 'EVENT|<matcher...>|script.py|TIMEOUT'. Before this fix the installer
    wired blocking guards at 3s (bash-security-guard, search-path-guard,
    block-partial-read, config-guard, memory-write-guard), so an installer-based
    deployment ran security guards on a budget below measured wrapper start-up.
    """
    import re
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    offenders = []
    for m in re.finditer(r"'(PreToolUse|PreCompact)\|(.*?)\|([A-Za-z0-9_.-]+\.py)\|(\d+)'", text):
        event, _matcher, script, timeout = m.groups()
        if int(timeout) <= adc.MIN_BLOCKING_TIMEOUT:
            offenders.append(f"{event}/{script}={timeout}s")
    assert offenders == [], f"installer blocking guards below floor: {offenders}"


def test_installer_timeouts_match_live_where_the_hook_is_registered():
    """Where a hook exists in BOTH install.sh and settings.json, budgets must agree."""
    import json as _json
    import re
    live = _json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    text = (REPO / "install.sh").read_text(encoding="utf-8")

    live_t = {}
    for event, entries in (live.get("hooks") or {}).items():
        for entry in entries or []:
            for h in entry.get("hooks", []) or []:
                script = _script_name(h)
                if script:
                    live_t[(event, script)] = h.get("timeout")

    mismatches = []
    for m in re.finditer(r"'([A-Za-z]+)\|(.*?)\|([A-Za-z0-9_.-]+\.py)\|(\d+)'", text):
        event, _matcher, script, timeout = m.groups()
        lv = live_t.get((event, script))
        if isinstance(lv, int) and lv != int(timeout):
            mismatches.append(f"{event}/{script}: install={timeout}s live={lv}s")
    assert mismatches == [], "installer/live timeout drift: " + "; ".join(sorted(set(mismatches)))
