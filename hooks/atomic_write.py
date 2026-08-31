"""Atomic write helper for hooks.

Prevents partial writes and file corruption by writing to a temp file
and atomically replacing the target.
"""

import os
import time
import uuid
from pathlib import Path


def _replace_with_retry(src, dst, attempts=20, base_delay=0.001):
    """os.replace, retrying transient Windows contention failures.

    POSIX rename never fails under concurrent same-target renames (the first
    attempt wins). Windows MoveFileEx transiently raises PermissionError
    (ERROR_ACCESS_DENIED=5) or OSError winerror 32 (ERROR_SHARING_VIOLATION)
    when the target is briefly locked by another writer's replace or a
    reader. Retry with a short linear backoff; re-raise after the last try.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(base_delay * (attempt + 1))
        except OSError as e:
            # ERROR_SHARING_VIOLATION (winerror 32) is the same Windows
            # contention class; anything else is a real error -> re-raise.
            if getattr(e, "winerror", None) == 32 and attempt + 1 < attempts:
                time.sleep(base_delay * (attempt + 1))
            else:
                raise


def atomic_write(path, content, encoding='utf-8'):
    """Write content atomically and durably to path.

    Args:
        path: Target file path (str or Path)
        content: Content to write (str)
        encoding: Text encoding (default utf-8)

    Process:
        1. Write to a per-writer-unique temp file in the same directory
           (same filesystem -> rename is atomic; unique name -> concurrent
           writers to the same target never collide on one temp file).
        2. flush + fsync the temp file so the bytes are on disk BEFORE the
           rename (otherwise a crash after rename can leave a 0-length /
           truncated target despite the "atomic" rename).
        3. Atomic rename via os.replace() (overwrites on Windows too).
        4. Best-effort fsync of the directory so the rename itself is durable.
        5. Clean up the temp file on error.

    The unique temp name is critical: the previous implementation used a
    fixed `<path>.tmp`, so two processes/threads writing the same target
    raced on one temp file and crashed with FileNotFoundError mid-rename.
    """
    path = Path(path)
    # Unique per-writer temp name in the same directory (same filesystem so
    # the rename stays atomic). pid + uuid avoids cross-process collisions.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        # Open with a real fd so we can fsync the data before the rename.
        with open(tmp, 'w', encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        # os.replace is atomic on both Unix and Windows (overwrites target).
        # On Windows it transiently fails under concurrent same-target writes
        # (PermissionError / ERROR_SHARING_VIOLATION); the retry helper clears
        # that contention. POSIX succeeds on the first attempt.
        _replace_with_retry(tmp, path)
        # Best-effort: fsync the containing directory so the rename survives
        # a crash. Not supported on Windows / some filesystems -> ignore.
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            pass
    except Exception:
        # Clean up our own temp file if something went wrong. missing_ok
        # avoids a TOCTOU race with a concurrent writer's cleanup.
        try:
            tmp.unlink(missing_ok=True)
        except TypeError:  # Python < 3.8 has no missing_ok
            if tmp.exists():
                tmp.unlink()
        raise


class TopicEntryTooLargeError(ValueError):
    """Raised when a topic-file append would exceed the per-entry size budget."""


# Matches the PreToolUse memory-write-guard.py MAX_ENTRY_LENGTH threshold.
# Calibrated 2026-03-28: P50=1513, P75=2064, P90=2756 across 580 KB of
# legitimate topic entries. Bounds individual append size to prevent
# hook-driven pollution like the 2026-05-28 msgraph.md incident where
# subagent-stop.py appended 26 KB JSON event payloads as "Worker learning"
# entries while the memory-write-guard hook (PreToolUse on Write/Edit) was
# completely bypassed — atomic_write isn't a Write/Edit tool call.
DEFAULT_MAX_TOPIC_ENTRY_CHARS = 2500


def bounded_topic_append(topic_path, entry, max_entry_chars=DEFAULT_MAX_TOPIC_ENTRY_CHARS,
                         encoding='utf-8'):
    """Append an entry to a topic file with a per-entry size budget.

    Reads the existing file, appends `entry`, writes atomically. Refuses if
    `entry` itself exceeds `max_entry_chars` — bounds the worst case where a
    hook's learning extractor accidentally captures a multi-KB block (raw
    JSON event payload, tool result, error message).

    Args:
        topic_path: Path to the topic file (str or Path). Must exist.
        entry: String to append. Must be <= max_entry_chars or raises.
        max_entry_chars: Per-entry size budget. Default matches the PreToolUse
            memory-write-guard threshold so hook writes and user/agent
            Write/Edit calls share the same limit.
        encoding: Text encoding.

    Raises:
        TopicEntryTooLargeError: entry exceeds max_entry_chars. Caller
            should drop or truncate the entry.
        FileNotFoundError: topic_path does not exist.

    Defense-in-depth: callers should ALSO truncate at the source (e.g.,
    subagent-stop.py caps the snippet at LEARNING_SNIPPET_MAX_CHARS=800
    BEFORE calling this helper). This helper is the backstop for cases
    where the source-side cap was forgotten or set wrong.
    """
    topic_path = Path(topic_path)
    if len(entry) > max_entry_chars:
        raise TopicEntryTooLargeError(
            f"Topic entry exceeds budget: {len(entry)} > {max_entry_chars} chars "
            f"(path={topic_path}). Truncate at the source or split into multiple entries."
        )
    existing = topic_path.read_text(encoding=encoding)
    atomic_write(topic_path, existing + entry, encoding=encoding)
