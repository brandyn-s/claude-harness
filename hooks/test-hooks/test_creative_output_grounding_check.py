#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for creative-output-grounding-check.py PostToolUse hook."""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "creative-output-grounding-check.py"


def run(payload: dict) -> tuple[int, str, str]:
    raw = json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode, proc.stdout, proc.stderr


def parse_systemmessage(stdout: str) -> str | None:
    if not stdout.strip():
        return None
    try:
        data = json.loads(stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, ValueError):
        return None
    return data.get("systemMessage")


def test_all_three_signals_present_silent():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "scout-frontier"},
        "tool_result": (
            "Finding 1: HIGH confidence approach. "
            "Source: https://arxiv.org/abs/2510.01171. "
            "Counterfactual: if width-scaling were not used, the analogy collapses "
            "(potential extrapolation, maintain confidence)."
        ),
    }
    code, out, _ = run(payload)
    assert code == 0
    assert parse_systemmessage(out) is None, "expected silent on all-three-present"


def _padded(text: str) -> str:
    """Pad text past the 500-char minimum content length so the hook scans it."""
    return text + " " + ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 12)


def test_missing_confidence_warns():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "brainstorm"},
        "tool_result": _padded(
            "Recommended approach. Source: https://example.com/paper. "
            "Counterfactual analysis: if the approach lacked property P, "
            "the claim would not hold."
        ),
    }
    code, out, _ = run(payload)
    assert code == 0
    msg = parse_systemmessage(out)
    assert msg is not None
    assert "confidence" in msg.lower()


def test_missing_provenance_warns():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "deep-dive"},
        "tool_result": _padded(
            "HIGH confidence finding. The approach is likely effective. "
            "Counterfactual: if the precondition were absent, recommendation collapses."
        ),
    }
    code, out, _ = run(payload)
    assert code == 0
    msg = parse_systemmessage(out)
    assert msg is not None
    assert "provenance" in msg.lower()


def test_missing_counterfactual_warns():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "refine"},
        "tool_result": _padded(
            "Finding labeled HIGH confidence. Cited source: https://arxiv.org/abs/1234.5678. "
            "Recommended action: adopt the approach."
        ),
    }
    code, out, _ = run(payload)
    assert code == 0
    msg = parse_systemmessage(out)
    assert msg is not None
    assert "counterfactual" in msg.lower()


def test_missing_two_signals_warns_with_aggregate_message():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "scout-frontier"},
        "tool_result": _padded("Adopt this paradigm; it is widely known and works."),
    }
    code, out, _ = run(payload)
    assert code == 0
    msg = parse_systemmessage(out)
    assert msg is not None
    assert "2+" in msg or "missing 2" in msg.lower()


def test_inferred_tag_satisfies_provenance():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "scout-frontier"},
        "tool_result": _padded(
            "MEDIUM confidence: structurally reasonable [INFERRED]. "
            "Counterfactual: would this still apply if domain X did not have property P?"
        ),
    }
    code, out, _ = run(payload)
    assert code == 0
    assert parse_systemmessage(out) is None


def test_meta_message_forked_execution_skipped():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "deep-dive"},
        "tool_result": (
            "Skill 'deep-dive' completed (forked execution). Result: Report saved successfully: 422 lines, ~43 KB."
        ),
    }
    code, out, _ = run(payload)
    assert code == 0
    assert parse_systemmessage(out) is None


def test_short_meta_message_skipped():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "brainstorm"},
        "tool_result": "Launching skill: brainstorm",
    }
    code, out, _ = run(payload)
    assert code == 0
    assert parse_systemmessage(out) is None


def test_non_skill_tool_silent():
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x.md"},
        "tool_result": "no labels at all here",
    }
    code, out, _ = run(payload)
    assert code == 0
    assert parse_systemmessage(out) is None


def test_skill_outside_target_set_silent():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "ship"},
        "tool_result": "no signals at all",
    }
    code, out, _ = run(payload)
    assert code == 0
    assert parse_systemmessage(out) is None


def test_malformed_json_input_silent_exit_0():
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="this-is-not-json-at-all",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_empty_tool_result_silent():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "scout-frontier"},
        "tool_result": "",
    }
    code, out, _ = run(payload)
    assert code == 0
    assert parse_systemmessage(out) is None


def test_skill_name_with_leading_slash_normalized():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "/scout-frontier"},
        "tool_result": _padded("Adopt this paradigm without justification."),
    }
    code, out, _ = run(payload)
    assert code == 0
    msg = parse_systemmessage(out)
    assert msg is not None  # warned because matched scout-frontier post-normalization


if __name__ == "__main__":
    failures = []
    tests = [
        test_all_three_signals_present_silent,
        test_missing_confidence_warns,
        test_missing_provenance_warns,
        test_missing_counterfactual_warns,
        test_missing_two_signals_warns_with_aggregate_message,
        test_inferred_tag_satisfies_provenance,
        test_meta_message_forked_execution_skipped,
        test_short_meta_message_skipped,
        test_non_skill_tool_silent,
        test_skill_outside_target_set_silent,
        test_malformed_json_input_silent_exit_0,
        test_empty_tool_result_silent,
        test_skill_name_with_leading_slash_normalized,
    ]
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures.append((t.__name__, str(e)))
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failures.append((t.__name__, repr(e)))
            print(f"ERROR {t.__name__}: {e!r}")

    if failures:
        print(f"\n{len(failures)} test(s) failed")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed")

# The warning text is USER-FACING and names the contract's location. When the
# contract moved out of rules/ (2026-08-26) the 17 tests here all still passed
# with three dead paths in that text, because none of them asserted on it -- the
# hook's exit code and firing behaviour are unchanged by a rotten citation.
# These tests close that gap: they pin the path a reader is sent to, and they
# assert the OLD ambient path is absent, so the next relocation cannot silently
# leave a stale pointer in a message shown to the user.
CONTRACT_PATH = "skills/_shared/output-grounding.md"
RETIRED_AMBIENT_PATH = "rules/output-grounding.md"


def test_single_missing_signal_warning_cites_the_live_contract_path():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "brainstorm"},
        "tool_result": _padded(
            "Recommended approach. Source: https://example.com/paper. "
            "Counterfactual analysis: if the approach lacked property P, "
            "the claim would not hold."
        ),
    }
    code, out, _ = run(payload)
    assert code == 0
    msg = parse_systemmessage(out)
    assert msg is not None, "expected a warning for a single missing signal"
    assert CONTRACT_PATH in msg, msg
    assert RETIRED_AMBIENT_PATH not in msg, (
        "warning still cites the retired ambient path; the file is gone, so the "
        f"user is sent nowhere: {msg}"
    )


def test_multi_missing_signal_warning_cites_the_live_contract_path():
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": "deep-dive"},
        "tool_result": _padded("Adopt approach X. It will improve throughput."),
    }
    code, out, _ = run(payload)
    assert code == 0
    msg = parse_systemmessage(out)
    assert msg is not None, "expected a warning for 2+ missing signals"
    assert "2+ signals" in msg, msg
    assert CONTRACT_PATH in msg, msg
    assert RETIRED_AMBIENT_PATH not in msg, msg


def test_the_relocated_contract_file_exists_and_still_binds():
    """A pointer to a missing file is the failure this relocation could cause."""
    contract = Path(__file__).resolve().parents[2] / CONTRACT_PATH
    assert contract.is_file(), f"warning points at a nonexistent file: {contract}"
    text = contract.read_text(encoding="utf-8")
    for needle in ("REQUIRED READ", "confidence", "provenance", "counterfactual"):
        assert needle.lower() in text.lower(), needle
    assert "advisory" in text.lower(), "must keep the hook-is-advisory caveat"
