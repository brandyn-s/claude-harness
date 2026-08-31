"""Unit tests for the code-search stale-project-guard module.

Verifies the path-classification logic and end-to-end cleanup against
a temp projects directory. Real-MCP integration is left to manual
verification (cd ~ → start Claude Code → look for the warning message
in the SessionStart summary).

The path classifier is safety-critical: getting it wrong deletes
legitimate project entries.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import code_search_stale_project_guard as mod  # noqa: E402


def _make_project(projects_dir: Path, name: str, project_path: str) -> Path:
    """Create a fake project entry with given path. Returns project dir."""
    proj_dir = projects_dir / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    info = {
        "project_name": name.split("_")[0],
        "project_path": project_path,
        "project_hash": name.split("_")[-1] if "_" in name else "deadbeef",
        "created_at": "2026-05-13T08:45:40.864524",
        "embedding_provider": "voyage",
        "embedding_model": "",
        "content_mode": "code",
    }
    (proj_dir / "project_info.json").write_text(json.dumps(info), encoding="utf-8")
    return proj_dir


def test_forbidden_exact_includes_home():
    """Home directory must be in the exact-match set."""
    exact, _scope = mod._forbidden_paths()
    assert Path.home().resolve() in exact


def test_forbidden_exact_includes_home_parent():
    """Parent of home (e.g., C:/Users) is also exact-match forbidden."""
    exact, _scope = mod._forbidden_paths()
    assert Path.home().parent.resolve() in exact


def test_is_forbidden_home_dir():
    """The exact home directory must classify as forbidden — this is
    the 2026-05-13 PSM incident shape."""
    exact, scope = mod._forbidden_paths()
    assert mod._is_forbidden(str(Path.home()), exact, scope) is True


def test_is_forbidden_real_repo_path():
    """A normal repo path under Documents/GitHub must NOT classify as
    forbidden. This is the test that caught my first-pass bug — children
    of home should be ALLOWED unless under a scope-set dir."""
    exact, scope = mod._forbidden_paths()
    assert mod._is_forbidden(
        str(Path.home() / "Documents" / "GitHub" / "real-repo"), exact, scope
    ) is False


def test_is_forbidden_documents_subdir():
    """Documents/anything is a valid project root."""
    exact, scope = mod._forbidden_paths()
    assert mod._is_forbidden(
        str(Path.home() / "Documents" / "knowledge-base"), exact, scope
    ) is False


def test_is_forbidden_appdata_subdir():
    """Subdirs of AppData must classify as forbidden (scope-set match)."""
    exact, scope = mod._forbidden_paths()
    if sys.platform == "win32":
        assert mod._is_forbidden(
            str(Path.home() / "AppData" / "Local" / "Temp"), exact, scope
        ) is True


def test_is_forbidden_cache_subdir():
    """Subdirs of ~/.cache must classify as forbidden."""
    exact, scope = mod._forbidden_paths()
    assert mod._is_forbidden(
        str(Path.home() / ".cache" / "some_project"), exact, scope
    ) is True


def test_is_forbidden_empty_path():
    """Empty / missing path is not forbidden (treat as 'unknown', skip)."""
    exact, scope = mod._forbidden_paths()
    assert mod._is_forbidden("", exact, scope) is False


def test_scan_finds_bogus_skips_legitimate():
    """End-to-end: scan should return the bogus entry, not the legit one."""
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        bogus = _make_project(
            projects_dir, "you_8bbeb258", str(Path.home())
        )
        legit = _make_project(
            projects_dir,
            "prototype-software-merry_780e511b",
            str(Path.home() / "Documents" / "GitHub" / "example-monorepo"),
        )

        exact, scope = mod._forbidden_paths()
        bogus_entries = mod._scan_projects(projects_dir, exact, scope)

        assert len(bogus_entries) == 1, (
            f"expected exactly 1 bogus, got {len(bogus_entries)}: "
            f"{[d.name for d, _ in bogus_entries]}"
        )
        assert bogus_entries[0][0] == bogus
        assert legit.exists(), "legit project must NOT be flagged for deletion"


def test_scan_handles_missing_projects_dir():
    """If the projects dir doesn't exist (fresh install), scan returns []."""
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "does-not-exist"
        exact, scope = mod._forbidden_paths()
        assert mod._scan_projects(projects_dir, exact, scope) == []


def test_scan_handles_malformed_json():
    """A project_info.json with bad JSON shouldn't crash the scan."""
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()
        bad = projects_dir / "broken_deadbeef"
        bad.mkdir()
        (bad / "project_info.json").write_text("{not valid json", encoding="utf-8")
        exact, scope = mod._forbidden_paths()
        assert mod._scan_projects(projects_dir, exact, scope) == []


def test_cleanup_returns_empty_when_nothing_to_clean(monkeypatch):
    """No bogus entries → empty message list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()
        _make_project(
            projects_dir,
            "legit_deadbeef",
            str(Path.home() / "Documents" / "real-repo"),
        )
        monkeypatch.setattr(mod, "PROJECTS_DIR", projects_dir)
        assert mod.cleanup_stale_projects() == []


def test_cleanup_deletes_and_returns_message(monkeypatch):
    """End-to-end: bogus entry exists → cleanup deletes it and returns a
    warning message naming the project and path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()
        bogus = _make_project(
            projects_dir, "you_8bbeb258", str(Path.home())
        )
        assert bogus.exists()
        monkeypatch.setattr(mod, "PROJECTS_DIR", projects_dir)
        messages = mod.cleanup_stale_projects()
        assert len(messages) == 1
        assert "you_8bbeb258" in messages[0]
        assert "deleted" in messages[0].lower()
        assert not bogus.exists(), "bogus project dir should be gone"


def test_cleanup_handles_locked_files_gracefully(monkeypatch, tmp_path):
    """If rmtree fails (running MCP holds lock), the message says so
    rather than crashing. Simulated by monkeypatching _delete_project."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    _make_project(projects_dir, "you_8bbeb258", str(Path.home()))
    monkeypatch.setattr(mod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(
        mod, "_delete_project", lambda _: (False, "Device or resource busy")
    )
    messages = mod.cleanup_stale_projects()
    assert len(messages) == 1
    assert "failed" in messages[0].lower()
    assert "Device or resource busy" in messages[0]
