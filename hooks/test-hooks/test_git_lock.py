"""Unit tests for hooks/git_lock.py — file-based advisory lock.

Covers acquire/release, mutual exclusion, timeout, and stale-lock
reclamation. The lock dir is redirected to a tmp path per test so the
suite never touches the real ~/.claude/.locks (tdd-quality item 12).
"""
import importlib.util
import os
import time

import pytest

_HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "git_lock", os.path.join(_HOOK_DIR, "git_lock.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.fixture(autouse=True)
def _isolated_lock_dir(tmp_path, monkeypatch):
    """Redirect the module's lock dir so tests never write real state."""
    monkeypatch.setattr(_mod, "_LOCK_DIR", tmp_path / "locks")
    yield tmp_path / "locks"


def _lockfile_for(repo_path):
    import hashlib
    key = hashlib.sha1(str(repo_path).encode("utf-8")).hexdigest()[:16]
    return _mod._LOCK_DIR / f"{key}.lock"


# ── acquire / release lifecycle ────────────────────────────────────────

def test_lock_creates_and_removes_lockfile():
    lf = _lockfile_for("/repo/a")
    with _mod.git_lock("/repo/a"):
        assert lf.exists(), "lockfile must exist while held"
        content = lf.read_text(encoding="utf-8")
        assert str(os.getpid()) in content, "lockfile records holder pid"
    assert not lf.exists(), "lockfile must be removed on release"


def test_release_happens_on_exception():
    lf = _lockfile_for("/repo/exc")
    with pytest.raises(RuntimeError), _mod.git_lock("/repo/exc"):
        assert lf.exists()
        raise RuntimeError("body failed")
    assert not lf.exists(), "lock must release even when the body raises"


def test_distinct_repos_do_not_contend():
    with _mod.git_lock("/repo/x"):
        # A different key must acquire instantly (distinct lockfile).
        with _mod.git_lock("/repo/y", timeout=1):
            assert _lockfile_for("/repo/x").exists()
            assert _lockfile_for("/repo/y").exists()


# ── contention ─────────────────────────────────────────────────────────

def test_second_holder_times_out():
    with _mod.git_lock("/repo/held", timeout=5):
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            with _mod.git_lock("/repo/held", timeout=0.5, stale_after=999):
                pass
        # Must have actually waited ~timeout, not raised instantly or hung.
        assert 0.4 <= time.monotonic() - t0 < 5


def test_stale_lock_is_reclaimed():
    lf = _lockfile_for("/repo/stale")
    _mod._LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lf.write_text("99999 0\n", encoding="utf-8")
    # Backdate mtime past stale_after so the reclaim path triggers.
    old = time.time() - 1000
    os.utime(lf, (old, old))
    with _mod.git_lock("/repo/stale", timeout=2, stale_after=120):
        assert lf.exists(), "reclaimed lock is re-created by the new holder"
    assert not lf.exists()


# ── degraded paths ─────────────────────────────────────────────────────

def test_unwritable_lock_dir_degrades_to_noop(monkeypatch, tmp_path):
    # Point the lock dir INSIDE a file so mkdir fails -> no-op yield.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(_mod, "_LOCK_DIR", blocker / "locks")
    ran = []
    with _mod.git_lock("/repo/degraded"):
        ran.append(True)
    assert ran == [True], "degraded mode must still run the body"
