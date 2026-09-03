"""Unit tests for healthcheck/references/_check_all.py pure helpers.

Covers parse_pytest (the pytest-summary parser behind the Hooks row — a
mis-parse here is what let a no-output run read as "0 tests passed PASS"
during development) and strip_prefix / first_line (the row-formatting that
removes a helper's own "Label: PASS —" prefix so the matrix isn't doubled).
The orchestration verdict + config/targets checks are covered separately.
"""
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_all",
    Path(__file__).resolve().parent.parent / "references" / "_check_all.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def test_parse_pytest_mixed():
    out = ("FAILED test-hooks/test_x.py::test_a - AssertionError\n"
           "FAILED test-hooks/test_y.py::test_b - AssertionError\n"
           "2 failed, 1046 passed, 52 skipped in 65.0s\n")
    passed, failed, fails = hc.parse_pytest(out)
    assert passed == 1046
    assert failed == 2
    assert fails == ["test-hooks/test_x.py::test_a", "test-hooks/test_y.py::test_b"]


def test_parse_pytest_all_pass():
    passed, failed, fails = hc.parse_pytest("1050 passed, 52 skipped in 60.0s\n")
    assert (passed, failed, fails) == (1050, 0, [])


def test_parse_pytest_empty_output_is_zero_zero():
    # Empty / no-summary output must NOT look like a pass; main() guards 0/0.
    assert hc.parse_pytest("") == (0, 0, [])


def test_strip_prefix_removes_label_and_status():
    assert hc.strip_prefix("Skills: PASS — 92/92 validated") == "92/92 validated"
    assert hc.strip_prefix("Paths: PASS - 50 paths verified") == "50 paths verified"
    assert hc.strip_prefix("Orphans: WARN — 2 orphan hooks") == "2 orphan hooks"


def test_strip_prefix_label_without_status():
    # Manifest's line has no PASS/WARN/FAIL token — only the label is dropped.
    assert hc.strip_prefix("Manifest: 92 on disk, 88 registered") == "92 on disk, 88 registered"


def test_first_line_skips_blanks_and_defaults():
    assert hc.first_line("\n  \nfirst real line\nsecond") == "first real line"
    assert hc.first_line("", "fallback") == "fallback"


def test_is_wip_failure_matches_all_drift_gate_shapes():
    """2026-08-22: on a diverged WIP tree, ALL 4 real hook-test failures were
    repo-consistency gates, but the old pattern matched only 2 — so a pure-WIP
    tree read as hard UNHEALTHY. Pin every observed drift-gate id shape."""
    real_wip_ids = [
        "test-hooks/test_architecture_drift_check.py::test_model_runtime_contract_matches_settings_and_covers_runtime_dimensions",
        "test-hooks/test_architecture_drift_check.py::test_repo_currently_passes_the_gate",
        "test-hooks/test_claude_release_qualification.py::test_branch_local_materialized_candidate_passes_complete_qualification",
        "test-hooks/test_settings_permissions.py::test_architecture_does_not_claim_dormant_or_lossy_controls_are_effective",
    ]
    for tid in real_wip_ids:
        assert hc.is_wip_failure(tid), f"drift-gate id not recognized as WIP: {tid}"
    # A behavior test must NOT be WIP-labeled — that would soften real breakage.
    assert not hc.is_wip_failure(
        "test-hooks/test_bash_security_guard.py::test_blocks_wide_process_listing")


def test_local_only_hooks_reads_exec_form_args(tmp_path, monkeypatch):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{
            "type": "command", "command": "/x/run-hook", "args": ["main.py"]
        }]}]}}), encoding="utf-8",
    )
    (claude / "settings.local.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{
            "type": "command", "command": "/x/run-hook", "args": ["local.py"]
        }]}]}}), encoding="utf-8",
    )
    monkeypatch.setattr(hc, "H", str(claude))

    assert hc.check_local_only_hooks() == ["local.py"]
