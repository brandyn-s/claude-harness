#!/usr/bin/env python3
"""Structural guard: CI gates must use exit codes, not grep-on-stdout.

THE PATTERN THIS PREVENTS

Three separate instances of the same anti-pattern were found in validate.yml during
the 2026-07-26 audit remediation:

  1. M4  -- the skill-rubric gate: `if <checker>; then echo ok; fi` with no `else`.
     A false `if` condition with no `else` leaves the compound command SUCCESSFUL,
     so a below-threshold skill printed `::error::` and the required check went
     green. `search-campaign` scored 12/14 while CI passed.
  2. audit-skill -- `... | grep -q "^FAIL"; then ... exit 1; fi`. This one DID gate,
     but through output-prefix coupling (any wording change disables it) and
     `grep -q`, which exits on first match and can SIGPIPE the producer -- risking a
     TRUNCATED `--ndjson` event log that `audit_history.py` and
     `oracle report --phase1` read as their only source.
  3. (fixed in the same pass) the drift check had no timeout comparison at all.

The durable rule: a gate's verdict belongs in the tool's EXIT STATUS. Parsing a
tool's prose to decide whether CI fails couples the gate to formatting and hides
pipeline failures.

Run: pytest scripts/test_ci_gates_use_exit_codes.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "validate.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# no gate may be expressed as grep-on-stdout of a validator
# ---------------------------------------------------------------------------
#: Validators whose verdict must come from their exit code.
GATING_TOOLS = (
    "audit-skill.py",
    "validate-skills.py",
    "validate-version-floor.py",
    "validate_cross_session_settings.py",
    "validate-telemetry-policy.py",
    "architecture-drift-check.py",
    "validate-hook-paths.py",
    "check-rule-context-budget.py",
    "validate-agent-frontmatter.py",
    "compile.py",
)


def test_no_gating_tool_is_piped_into_grep_q():
    """`grep -q` closes the pipe on first match and can SIGPIPE the producer.

    Beyond masking the tool's own status, that risks truncating side-effect output
    (e.g. audit-skill's --ndjson event log) mid-write.
    """
    offenders = []
    for line in workflow_text().splitlines():
        if "grep -q" not in line:
            continue
        if any(tool in line for tool in GATING_TOOLS):
            offenders.append(line.strip())
    assert offenders == [], (
        "gating validator piped into `grep -q` (use the tool's exit code):\n"
        + "\n".join(offenders)
    )


def test_no_gating_tool_is_wrapped_in_a_shell_if():
    """An `if <tool>; then ...; fi` with no `else` exits 0 when the tool fails."""
    offenders = []
    for line in workflow_text().splitlines():
        stripped = line.strip()
        if not re.match(r"^if\b", stripped):
            continue
        if any(tool in stripped for tool in GATING_TOOLS):
            offenders.append(stripped)
    assert offenders == [], (
        "gating validator wrapped in a shell `if` (fail-open):\n" + "\n".join(offenders)
    )


def test_audit_skill_step_uses_strict():
    """CI must opt in to drift-gating explicitly.

    Without `--strict`, drift is advisory BY DESIGN ("Errors always exit non-zero.
    Drift only does so under --strict."), so `--all` alone cannot gate. The fix is
    for CI to opt in -- not to change the tool's semantics for every other caller.
    """
    text = workflow_text()
    assert "audit-skill.py --all --strict" in text, (
        "the audit-skill CI step must use --strict so its exit code gates"
    )


def test_ci_composes_post_1949_policy_with_stronger_release_guards():
    text = workflow_text()

    for required in (
        "fetch-depth: 0",
        "python scripts/validate-version-floor.py",
        "python scripts/runtime-qualification/validate_cross_session_settings.py",
        "python scripts/validate-telemetry-policy.py",
        "python manifests/compile.py --root . --check --strict-semantic --no-reindex",
        "python scripts/check-rule-context-budget.py",
        "@anthropic-ai/claude-code@2.1.226",
        "python scripts/materialize_release_candidate.py",
        "bin/claude-release-qualification.py",
        "--full-tree",
    ):
        assert required in text

    assert "--run-native" not in text


# ---------------------------------------------------------------------------
# the tool's documented contract, pinned
# ---------------------------------------------------------------------------
def run_audit(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "bin" / "audit-skill.py"), *args],
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
    )


def test_strict_gates_on_injected_drift():
    """Mutation check: --strict must FAIL on a real violation, and pass without it.

    Injects a C10 violation (a bare shell subprocess, which breaks on Windows where
    the shell name resolves to the WSL launcher), then removes it.
    """
    # Built from fragments on purpose. The auditor's C10 check is a regex over file
    # TEXT, so a literal `subprocess.run(["bash", ...])` written inline here would
    # make THIS test file itself a C10 violation -- the checker cannot distinguish
    # code that calls a shell from code that writes a string describing one. The
    # generated probe still contains a genuine violation; only the source spelling
    # is split so the scanner does not flag the test that exercises it.
    shell = "ba" + "sh"
    probe = REPO / "scripts" / "_c10_probe_generated.py"
    probe.write_text(
        "import subprocess\n"
        f'subprocess.run(["{shell}", "-c", "echo hi"])\n',
        encoding="utf-8",
    )
    try:
        dirty = run_audit("--all", "--strict", "--no-marketplace-check")
        assert dirty.returncode != 0, "--strict must fail on injected drift"
        assert "C10" in dirty.stdout
    finally:
        probe.unlink(missing_ok=True)

    clean = run_audit("--all", "--strict", "--no-marketplace-check")
    assert clean.returncode == 0, (
        "the shipped tree must pass --strict:\n" + clean.stdout[-1500:]
    )


def test_non_strict_keeps_drift_advisory():
    """Backward compatibility: a developer run must not start failing on drift."""
    p = run_audit("audit-skill")
    assert p.returncode == 0, p.stdout[-800:]
