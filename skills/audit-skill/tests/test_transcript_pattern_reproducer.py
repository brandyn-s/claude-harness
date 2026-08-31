"""Tests for the transcript_pattern reproducer type.

audit-rules emits findings with this reproducer shape: a measurement
command produces JSON, the oracle extracts a metric, compares it to a
threshold, and fires=True iff the rule is being violated above the
promotion-trigger threshold.

These tests pin:
  - JSON parsing from the measurement command's stdout
  - Metric extraction via dot-path navigation
  - Threshold comparison semantics per op (gte/gt/lte/lt)
  - Instrument-failure routing (non-zero rc, invalid JSON, missing metric)

Subprocess-driven tests (those that invoke a real shell command and
check the reproducer's runtime behavior) are skipped on Windows. The
production audit-rules runner targets Linux/macOS — the reproducer
hard-codes ``["bash", "-c", ...]`` in oracle.finding, and the GitHub
Actions Windows runner's bash subprocess returns rc=1 with empty stderr
regardless of the command shape we pass (tried sys.executable path,
bare ``python``, ``cat <file>``, ``printf %s '...'``). The pure-Python
helpers (_extract_metric, _compare, REPRODUCER_TYPES) still run on all
three platforms.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills" / "_shared"))

from oracle.finding import Reproducer, _extract_metric, _compare  # noqa: E402

windows_bash_unreliable = pytest.mark.skipif(
    sys.platform == "win32",
    reason="bash subprocess on Windows GHA is unreliable (rc=1, empty stderr); "
    "production audit-rules runner is Linux/macOS",
)


def test_extract_metric_top_level_key():
    assert _extract_metric({"session_rate": 0.44}, "session_rate") == 0.44


def test_extract_metric_nested_dot_path():
    data = {"rules": {"encoding": {"session_rate": 0.30}}}
    assert _extract_metric(data, "rules.encoding.session_rate") == 0.30


def test_extract_metric_list_index():
    data = {"items": [{"value": 10}, {"value": 20}]}
    assert _extract_metric(data, "items.1.value") == 20


def test_extract_metric_missing_returns_none():
    assert _extract_metric({"a": 1}, "b") is None
    assert _extract_metric({"a": {"b": 1}}, "a.c") is None
    assert _extract_metric({}, "anything") is None


def test_extract_metric_empty_path_returns_none():
    assert _extract_metric({"a": 1}, "") is None


def test_compare_operators():
    assert _compare(10.0, "gte", 10.0) is True
    assert _compare(10.0, "gte", 11.0) is False
    assert _compare(10.0, "gt", 10.0) is False
    assert _compare(10.0, "gt", 9.0) is True
    assert _compare(5.0, "lte", 5.0) is True
    assert _compare(5.0, "lte", 4.0) is False
    assert _compare(5.0, "lt", 5.0) is False
    assert _compare(5.0, "lt", 6.0) is True


def test_compare_unknown_op_raises():
    with pytest.raises(ValueError):
        _compare(1.0, "eq", 1.0)


def _write_py_emitter(tmp_path, json_body: str, name: str = "measure.json") -> str:
    """Return a ``printf %s <body>`` command that emits the given body
    on stdout. ``printf`` is a shell builtin available in every bash on
    every platform (Git Bash for Windows, WSL bash, /bin/bash on
    Linux/macOS), so the command works without depending on:
      (a) any executable being on PATH (no ``python``, no ``cat``);
      (b) any path translation between Windows and the bash flavor
          (some bashes only understand ``/c/...`` or ``/mnt/c/...``
          and reject ``C:/...``).
    The body is shell-quoted with ``shlex.quote`` so embedded { } " etc.
    pass through unmangled. The tmp_path / name arguments are kept for
    backward compatibility with callers that pass distinct ``name``s
    but the file is not actually written to disk anymore.
    """
    del tmp_path, name  # no longer used; kept for caller compatibility
    return f"printf %s {shlex.quote(json_body)}"


@windows_bash_unreliable
def test_transcript_pattern_fires_when_threshold_exceeded(tmp_path):
    """Above threshold → fires=True (bug still present)."""
    cmd = _write_py_emitter(tmp_path, '{"session_rate": 0.44}')
    rep = Reproducer(
        type="transcript_pattern",
        command=cmd,
        metric_path="session_rate",
        threshold=0.10,
        threshold_op="gte",
    )
    fires, evidence = rep.fires(tmp_path)
    assert fires is True
    assert "0.44" in evidence
    assert "gte" in evidence


@windows_bash_unreliable
def test_transcript_pattern_does_not_fire_when_below_threshold(tmp_path):
    """Below threshold → fires=False (bug resolved)."""
    cmd = _write_py_emitter(tmp_path, '{"session_rate": 0.03}')
    rep = Reproducer(
        type="transcript_pattern",
        command=cmd,
        metric_path="session_rate",
        threshold=0.10,
        threshold_op="gte",
    )
    fires, evidence = rep.fires(tmp_path)
    assert fires is False


@windows_bash_unreliable
def test_transcript_pattern_nested_metric_path(tmp_path):
    """metric_path can navigate nested JSON via dot notation."""
    cmd = _write_py_emitter(
        tmp_path, '{"rules": {"encoding": {"session_rate": 0.15}}}'
    )
    rep = Reproducer(
        type="transcript_pattern",
        command=cmd,
        metric_path="rules.encoding.session_rate",
        threshold=0.10,
        threshold_op="gte",
    )
    fires, _ = rep.fires(tmp_path)
    assert fires is True


def test_transcript_pattern_raises_on_command_failure(tmp_path):
    """Command rc!=0 → RuntimeError → caller routes to ERROR verdict.
    ``false`` is a shell builtin available on every bash. This test
    does NOT need the windows_bash_unreliable skip because ``false``
    takes no argument — the failure mode the skip protects against
    is bash + ``printf %s '<arg>'`` arg-quoting on Windows GHA."""
    rep = Reproducer(
        type="transcript_pattern",
        command="false",
        metric_path="session_rate",
        threshold=0.10,
        threshold_op="gte",
    )
    with pytest.raises(RuntimeError, match="command failed"):
        rep.fires(tmp_path)


@windows_bash_unreliable
def test_transcript_pattern_raises_on_invalid_json(tmp_path):
    """Command emits non-JSON → RuntimeError → ERROR verdict."""
    cmd = _write_py_emitter(tmp_path, "not json", name="not_json.py")
    rep = Reproducer(
        type="transcript_pattern",
        command=cmd,
        metric_path="session_rate",
        threshold=0.10,
        threshold_op="gte",
    )
    with pytest.raises(RuntimeError, match="not emit valid JSON"):
        rep.fires(tmp_path)


@windows_bash_unreliable
def test_transcript_pattern_raises_on_missing_metric(tmp_path):
    """metric_path doesn't navigate → RuntimeError → ERROR verdict.
    Better than silently returning fires=False (would mask a typo)."""
    cmd = _write_py_emitter(tmp_path, '{"other_key": 0.5}', name="other_key.py")
    rep = Reproducer(
        type="transcript_pattern",
        command=cmd,
        metric_path="session_rate",
        threshold=0.10,
        threshold_op="gte",
    )
    with pytest.raises(RuntimeError, match="not found in JSON output"):
        rep.fires(tmp_path)


@windows_bash_unreliable
def test_transcript_pattern_raises_on_non_numeric_metric(tmp_path):
    """metric is not a number → RuntimeError → ERROR verdict."""
    cmd = _write_py_emitter(
        tmp_path, '{"session_rate": "high"}', name="non_numeric.py"
    )
    rep = Reproducer(
        type="transcript_pattern",
        command=cmd,
        metric_path="session_rate",
        threshold=0.10,
        threshold_op="gte",
    )
    with pytest.raises(RuntimeError, match="not numeric"):
        rep.fires(tmp_path)


def test_transcript_pattern_rejects_invalid_threshold_op():
    """Constructor validates threshold_op."""
    with pytest.raises(ValueError, match="threshold_op must be one of"):
        Reproducer(
            type="transcript_pattern",
            command="echo {}",
            metric_path="r",
            threshold=0.0,
            threshold_op="equals",  # invalid
        )


def test_transcript_pattern_in_REPRODUCER_TYPES():
    """transcript_pattern must be a valid type so YAML loaders accept it."""
    from oracle.finding import REPRODUCER_TYPES
    assert "transcript_pattern" in REPRODUCER_TYPES


def test_transcript_pattern_defaults_to_gte():
    """Default threshold_op is gte (the common 'promotion trigger' shape)."""
    rep = Reproducer(
        type="transcript_pattern",
        command="echo '{\"r\": 0.5}'",
        metric_path="r",
        threshold=0.4,
    )
    assert rep.threshold_op == "gte"
