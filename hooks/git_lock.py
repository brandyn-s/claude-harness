"""File-based advisory lock for serializing concurrent hook writes.

Used by post-merge-sync.py to serialize read-modify-write
updates to shared state (recent-sessions.md episodic memory, auto-merge
markers) so two sessions ending near-simultaneously don't clobber each
other's entries (last-writer-wins).

Lives in hooks/ — which the installer deploys and which is already on both
consumers' import path. The previously-expected location
(~/.claude/scripts/git_lock.py) was never shipped by install.sh, so the
`except ImportError` no-op fallback was ALWAYS used and the "lock" did
nothing. Putting the module here makes the lock real.

Uses an O_EXCL lockfile (atomic create on POSIX and Windows) with a timeout
and stale-lock reclamation so a crashed holder can't deadlock future writers.
"""

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path

_LOCK_DIR = Path(os.path.expanduser("~")) / ".claude" / ".locks"


@contextmanager
def git_lock(repo_path, timeout=30, stale_after=120):
    """Acquire an exclusive advisory lock keyed on `repo_path`.

    Args:
        repo_path: Any string/Path identifying the resource to serialize on.
        timeout: Max seconds to wait for the lock before raising TimeoutError.
        stale_after: Seconds after which an unreleased lock is considered
            abandoned (holder crashed) and reclaimed.

    Raises:
        TimeoutError: lock not acquired within `timeout`.
    """
    try:
        _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Can't even create the lock dir — degrade to no-op rather than
        # blocking session end.
        yield
        return

    key = hashlib.sha1(str(repo_path).encode("utf-8")).hexdigest()[:16]
    lockfile = _LOCK_DIR / f"{key}.lock"
    deadline = time.monotonic() + timeout
    fd = None
    while True:
        try:
            fd = os.open(
                str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
            os.write(fd, f"{os.getpid()} {time.time()}\n".encode())
            break
        except FileExistsError:
            # Reclaim a stale lock left by a crashed holder.
            try:
                age = time.time() - lockfile.stat().st_mtime
                if age > stale_after:
                    lockfile.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"git_lock: timeout after {timeout}s waiting on {repo_path}"
                )
            time.sleep(0.1)
        except OSError:
            # Unexpected FS error — degrade to no-op so we never block.
            yield
            return

    try:
        yield
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lockfile.unlink()
        except OSError:
            pass
