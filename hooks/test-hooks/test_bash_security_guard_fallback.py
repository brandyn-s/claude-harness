"""protected-repos.json is the only source of the guard's protected set.

The push/commit/pr guards used to fall back to a hard-coded list of the author's
repositories when protected-repos.json could not be read. A stale built-in list
is worse than an inert guard: it silently protects the wrong repos on another
machine and re-introduces the author's environment into a public file. The guard
now mirrors worktree-enforcement.py: empty set plus one visible stderr note.
"""
# validate-hook-paths-target: hooks/bash-security-guard.py
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[1]
GUARD = HOOKS_DIR / "bash-security-guard.py"

FORMER_FALLBACK_NAMES = (
    "example-compliance-repo",
    "example-sbom-tool",
    "mcp-servers",
    "mcp-infra",
)


def _load_guard_from(directory: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, directory / "bash-security-guard.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guard_source_carries_no_hard_coded_protected_repo_list():
    source = GUARD.read_text(encoding="utf-8")
    fallback_region = source[source.index("_config_path = os.path.join"):]
    fallback_region = fallback_region[: fallback_region.index("def _forbidden_github_orgs")]
    for name in FORMER_FALLBACK_NAMES:
        assert f'"{name}"' not in fallback_region, f"hard-coded protected repo {name!r} is back"


def test_missing_protected_repos_file_leaves_the_guard_inert_with_one_note(tmp_path, capsys):
    """A copy of the guard with no protected-repos.json beside it: empty set, one stderr line."""
    shutil.copy(GUARD, tmp_path / "bash-security-guard.py")
    sys.path.insert(0, str(HOOKS_DIR))  # the guard imports sibling helpers
    try:
        module = _load_guard_from(tmp_path, "bash_security_guard_without_config")
    finally:
        sys.path.remove(str(HOOKS_DIR))

    assert module.PROTECTED_REPOS == set()
    assert module.FORK_REPOS == {}
    err = capsys.readouterr().err
    assert err.count("protected-repos.json unreadable") == 1, err


def test_present_protected_repos_file_is_read_verbatim(tmp_path, capsys):
    shutil.copy(GUARD, tmp_path / "bash-security-guard.py")
    (tmp_path / "protected-repos.json").write_text(
        json.dumps({"repos": ["alpha-repo", "beta-repo"], "fork_repos": {"beta-repo": "up/beta"}}),
        encoding="utf-8",
    )
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        module = _load_guard_from(tmp_path, "bash_security_guard_with_config")
    finally:
        sys.path.remove(str(HOOKS_DIR))

    assert module.PROTECTED_REPOS == {"alpha-repo", "beta-repo"}
    assert module.FORK_REPOS == {"beta-repo": "up/beta"}
    assert "protected-repos.json unreadable" not in capsys.readouterr().err
