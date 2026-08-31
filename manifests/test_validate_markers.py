"""Self-tests for manifests.validate_markers.

Designed to be runnable as a module from CI:
    python -m manifests.test_validate_markers

Asserts each schema accepts known-good payloads and rejects the specific drift
patterns we've seen. Adding a regression here is cheaper than asking for it
back in production after the next silent-zero bug.
"""
from __future__ import annotations

import sys

from manifests.validate_markers import validate, validate_consistency


def _expect_valid(marker_id: str, data) -> None:
    issues = validate(marker_id, data)
    assert not issues, f"expected {marker_id} valid, got: {issues}"


def _expect_invalid(marker_id: str, data, must_mention: str) -> None:
    issues = validate(marker_id, data)
    assert issues, f"expected {marker_id} invalid, got no issues"
    assert any(must_mention in i for i in issues), (
        f"expected issue mentioning {must_mention!r}; got: {issues}"
    )


def test_last_distill_well_formed() -> None:
    _expect_valid("last-distill", {
        "session_id": "sess-1",
        "timestamp": "2026-05-23T18:00:00+00:00",
        "lesson_count": 1,
        "lessons": [{"title": "x", "tier": "T3", "target": "y.md"}],
        "metrics": {"total_turns": 47, "wall_time": "~3h"},
    })


def test_last_distill_pr_958_bug() -> None:
    """The exact drift PR #958 fixed: writer emits `lessons[]` but no
    `lesson_count`, reader returns silent zero. Schema now catches it."""
    _expect_invalid("last-distill", {
        "session_id": "s",
        "timestamp": "2026-05-23T18:00:00+00:00",
        "lessons": [],
    }, must_mention="lesson_count")


def test_last_distill_placeholder_timestamp() -> None:
    """The exact drift PR #958 fixed: literal 'ISO 8601' in the docstring
    snippet, never replaced with a real timestamp."""
    _expect_invalid("last-distill", {
        "session_id": "s",
        "timestamp": "ISO 8601",
        "lesson_count": 0,
        "lessons": [],
    }, must_mention="ISO 8601")


def test_last_distill_tier_pattern() -> None:
    _expect_invalid("last-distill", {
        "session_id": "s",
        "timestamp": "2026-05-23T18:00:00+00:00",
        "lesson_count": 1,
        "lessons": [{"title": "x", "tier": "T99", "target": "y.md"}],
    }, must_mention="pattern")


def test_last_distill_lesson_count_drift() -> None:
    """Schema-orthogonal invariant: lesson_count must equal len(lessons)."""
    data = {
        "session_id": "s",
        "timestamp": "2026-05-23T18:00:00+00:00",
        "lesson_count": 5,
        "lessons": [{"title": "x", "tier": "T3", "target": "y.md"}],
    }
    assert validate("last-distill", data) == []
    cissues = validate_consistency("last-distill", data)
    assert cissues and "len(lessons)=1" in cissues[0]


def test_pending_config_well_formed() -> None:
    _expect_valid("pending-config", [
        {"action": "add_hook", "event": "PreToolUse", "matcher": "Write",
         "hook": {"type": "command", "command": "python x.py", "timeout": 5}},
        {"action": "remove_hook", "event": "PreToolUse", "script_name": "y.py"},
    ])


def test_pending_config_unknown_action() -> None:
    issues = validate("pending-config", [{"action": "reformat_disk"}])
    assert issues, "unknown action should fail"


def test_pending_config_add_hook_requires_hook() -> None:
    issues = validate("pending-config", [{"action": "add_hook", "event": "PreToolUse"}])
    assert issues, "add_hook without hook block should fail"


def test_topic_checksums_well_formed() -> None:
    _expect_valid("topic-checksums", {
        "topic-a": "a" * 64,
        "topic-b": "0123456789abcdef" * 4,
    })


def test_topic_checksums_bad_hash() -> None:
    _expect_invalid("topic-checksums", {"topic-a": "not-a-hash"}, must_mention="pattern")
    _expect_invalid("topic-checksums", {"topic-a": "A" * 64}, must_mention="pattern")  # uppercase


def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures.append((t.__name__, str(e)))
    if failures:
        for name, msg in failures:
            print(f"FAIL {name}: {msg}", file=sys.stderr)
        return 1
    print(f"validate_markers self-test: {len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
