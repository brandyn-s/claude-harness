"""Regression guard: shared-state hook files must be written atomically.

Two PostToolUse (or PreToolUse) hooks racing on the same JSON state file
will interleave writes and corrupt the JSON unless the writer uses
atomic_write (which writes to a tmp file then rename()s). This test
verifies the affected hooks import atomic_write and call it on their
state files.

Hooks under guard:
- auto-topic-loader.py  (marker file)
- pre-agent-dispatch.py  (active-agents file)
- post-merge-sync.py  (auto-merge markers)
- session-end.py  (bounded durable receipts)
- subagent-stop.py  (topic file updates)
"""
import re
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent

HOOKS_REQUIRING_ATOMIC = [
    "auto-topic-loader.py",
    "pre-agent-dispatch.py",
    "post-merge-sync.py",
    "session-end.py",
    "subagent-stop.py",
    # B3 review (2026-06-10): the two highest-frequency stateful hooks —
    # both fire on nearly every tool call, and parallel tool calls run
    # their PostToolUse hooks concurrently against the same state file.
    "loop-detector.py",
]


@pytest.mark.parametrize("hook_name", HOOKS_REQUIRING_ATOMIC)
def test_hook_imports_atomic_write(hook_name):
    src = (HOOKS_DIR / hook_name).read_text(encoding="utf-8")
    has_import = (
        "from atomic_write import atomic_write" in src
        or "from atomic_write import atomic_write as " in src
        or "import atomic_write" in src
    )
    assert has_import, (
        f"{hook_name} writes shared state but does not import atomic_write. "
        "Concurrent hooks racing on the same JSON file will corrupt it."
    )


@pytest.mark.parametrize("hook_name", HOOKS_REQUIRING_ATOMIC)
def test_hook_uses_atomic_write_call(hook_name):
    """Beyond importing atomic_write, the hook must actually CALL it
    (not just `from atomic_write import atomic_write` then never use)."""
    src = (HOOKS_DIR / hook_name).read_text(encoding="utf-8")
    # Look for atomic_write(...) call OR a local helper wrapping it
    # (_safe_write_baseline / _aw).
    call_pattern = re.compile(
        r"\b(atomic_write|_aw|_safe_write_baseline)\s*\("
    )
    assert call_pattern.search(src), (
        f"{hook_name} imports atomic_write but does not call it. The "
        "non-atomic write_text/json.dump path is still active."
    )


def test_auto_merge_marker_not_written_with_raw_handle():
    """The auto-merge marker (lost-commits push-guard) must be written via
    atomic_write, not raw open(...,'w')+json.dump. The generic
    test_hook_uses_atomic_write_call greps for atomic_write( anywhere and so
    passed even while the marker path used a raw handle (it matched an
    unrelated call). This pins the specific write path."""
    src = (HOOKS_DIR / "post-merge-sync.py").read_text(encoding="utf-8")
    assert 'open(_AUTO_MERGE_MARKER, "w"' not in src, (
        "auto-merge marker is written with a raw file handle; use atomic_write"
    )
    assert "atomic_write(_AUTO_MERGE_MARKER" in src, (
        "auto-merge marker should be persisted through atomic_write"
    )


# ── bounded_topic_append tests ──────────────────────────────────────────
# Backs the RC3 fix from the 2026-05-28 retro: subagent-stop.py wrote 26 KB
# JSON event payloads into msgraph.md because nothing bounded the per-entry
# size. memory-write-guard.py PreToolUse fires on Write/Edit tool calls but
# NOT on atomic_write() inside hooks. bounded_topic_append closes that gap
# with the same 2500-char ceiling.

import sys
sys.path.insert(0, str(HOOKS_DIR))
from atomic_write import (
    bounded_topic_append,
    TopicEntryTooLargeError,
    DEFAULT_MAX_TOPIC_ENTRY_CHARS,
)


def test_bounded_topic_append_writes_small_entry(tmp_path):
    """Entry under the budget appends cleanly."""
    topic = tmp_path / "fake.md"
    topic.write_text("# Existing\n", encoding="utf-8")
    bounded_topic_append(topic, "\n## New entry\n- a learning\n")
    body = topic.read_text(encoding="utf-8")
    assert body.startswith("# Existing\n")
    assert "## New entry" in body
    assert "- a learning" in body


def test_bounded_topic_append_refuses_oversized_entry(tmp_path):
    """Entry over the budget raises and the file is unmodified."""
    topic = tmp_path / "fake.md"
    original = "# Existing\n"
    topic.write_text(original, encoding="utf-8")
    huge_entry = "x" * (DEFAULT_MAX_TOPIC_ENTRY_CHARS + 1)
    with pytest.raises(TopicEntryTooLargeError) as exc_info:
        bounded_topic_append(topic, huge_entry)
    # File preserved
    assert topic.read_text(encoding="utf-8") == original
    # Error message names the path and the budget
    assert str(topic) in str(exc_info.value)
    assert str(DEFAULT_MAX_TOPIC_ENTRY_CHARS) in str(exc_info.value)


def test_bounded_topic_append_custom_budget(tmp_path):
    """Custom max_entry_chars overrides the default."""
    topic = tmp_path / "fake.md"
    topic.write_text("# X\n", encoding="utf-8")
    # 100-char entry rejected when budget is 50
    with pytest.raises(TopicEntryTooLargeError):
        bounded_topic_append(topic, "x" * 100, max_entry_chars=50)
    # Same entry accepted when budget is 200
    bounded_topic_append(topic, "x" * 100, max_entry_chars=200)
    assert topic.read_text(encoding="utf-8").endswith("x" * 100)


# ── atomic_write concurrency + durability ───────────────────────────────
# Regression for the fixed-temp-name race: the previous implementation used a
# single `<path>.tmp`, so N writers to the same target collided on one temp
# file and crashed with FileNotFoundError mid-rename. The helper must let
# concurrent writers to the SAME path all succeed.

import threading
from atomic_write import atomic_write


def test_atomic_write_concurrent_same_path_no_crash(tmp_path):
    """Many threads writing the same target must all succeed (no temp-file
    collision). With the old fixed `.tmp` name this raised FileNotFoundError
    in a large fraction of writers."""
    target = tmp_path / "shared-state.json"
    target.write_text("{}", encoding="utf-8")
    errors = []

    def writer(tag):
        for i in range(50):
            try:
                atomic_write(target, '{"writer": %d, "i": %d}' % (tag, i))
            except Exception as e:  # noqa: BLE001 - we want to record any failure
                errors.append(repr(e))

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent atomic_write raised {len(errors)} errors: {errors[:3]}"
    # The target is always one writer's complete, valid JSON — never torn.
    import json
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert "writer" in parsed and "i" in parsed


def test_atomic_write_leaves_no_temp_files(tmp_path):
    """After a successful write the unique temp file is renamed away — no
    stray `.<name>.<pid>.<uuid>.tmp` litter left in the directory."""
    target = tmp_path / "state.json"
    atomic_write(target, '{"ok": true}')
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == [], f"atomic_write left temp files behind: {leftovers}"


def test_atomic_write_overwrites_existing(tmp_path):
    """os.replace overwrites an existing target (Windows + Unix)."""
    target = tmp_path / "state.json"
    target.write_text("OLD", encoding="utf-8")
    atomic_write(target, "NEW")
    assert target.read_text(encoding="utf-8") == "NEW"


def test_bounded_topic_append_default_matches_memory_write_guard():
    """The bounded_topic_append default budget must match the PreToolUse
    memory-write-guard.py MAX_ENTRY_LENGTH so hook writes and user/agent
    Write/Edit calls share the same per-entry ceiling. Drifting these
    apart re-opens the asymmetry that caused the 2026-05-28 incident."""
    guard_src = (HOOKS_DIR / "memory-write-guard.py").read_text(encoding="utf-8")
    m = re.search(r"^MAX_ENTRY_LENGTH\s*=\s*(\d+)", guard_src, re.MULTILINE)
    assert m, "memory-write-guard.py must declare MAX_ENTRY_LENGTH at module scope"
    guard_limit = int(m.group(1))
    assert DEFAULT_MAX_TOPIC_ENTRY_CHARS == guard_limit, (
        f"bounded_topic_append default ({DEFAULT_MAX_TOPIC_ENTRY_CHARS}) "
        f"diverged from memory-write-guard.MAX_ENTRY_LENGTH ({guard_limit}). "
        "Keep these in lockstep to avoid the hook-write / Write-tool asymmetry."
    )
