#!/usr/bin/env python3
"""VERSION, CHANGELOG.md, the release tag and the UPSTREAM example agree.

The consuming contract (docs/consuming-from-a-private-overlay.md) lets a private
overlay pin this repository by version. That only means something if the version
in the tree, the changelog entry for it, the tag that names it and the example pin
never disagree. Offline: the tag check is skipped when no `v<VERSION>` tag exists
in this clone.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


def _version() -> str:
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


def test_version_is_one_semver_line():
    raw = (REPO / "VERSION").read_text(encoding="utf-8")
    assert raw.endswith("\n") and raw.count("\n") == 1, "VERSION is exactly one line"
    assert SEMVER.match(raw.strip()), raw


def test_changelog_has_an_entry_for_the_version_and_an_unreleased_section():
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text
    assert re.search(rf"^## \[{re.escape(_version())}\] — \d{{4}}-\d{{2}}-\d{{2}}$", text, re.M), \
        f"CHANGELOG.md has no dated entry for {_version()}"
    headings = re.findall(r"^## \[([^\]]+)\]", text, re.M)
    assert headings[0] == "Unreleased" and headings[1] == _version(), headings[:2]


def test_release_tag_if_present_points_at_a_commit_with_that_changelog_entry():
    tag = f"v{_version()}"
    exists = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
                            cwd=REPO, capture_output=True, text=True).returncode == 0
    if not exists:
        pytest.skip(f"{tag} is unreleased in this clone; nothing to check")
    # A PRESENT REF DOES NOT PROVE A READABLE OBJECT. A shallow or partial
    # clone, or a fetch that raced the tag push, leaves refs/tags/<tag>
    # resolvable while the tagged tree is absent — so `git show` exits 128 and
    # check=True turned a clone limitation into a red main (measured
    # 2026-09-07: this test failed on the 1.0.0 push and passed on re-run,
    # unchanged). Read without check= and branch on the outcome, so a clone
    # that cannot answer SKIPS visibly and only a readable tag can assert.
    shown = subprocess.run(["git", "show", f"{tag}:CHANGELOG.md"], cwd=REPO,
                           capture_output=True, text=True)
    if shown.returncode != 0:
        pytest.skip(
            f"{tag} resolves but its CHANGELOG.md is not present in this clone "
            f"(git show exit {shown.returncode}); run in a full clone to check"
        )
    assert f"## [{_version()}]" in shown.stdout, \
        f"tag {tag} does not carry its own changelog entry"


def test_upstream_example_names_this_version_and_the_core_paths():
    pin = json.loads((REPO / "contracts" / "UPSTREAM.example.json").read_text(encoding="utf-8"))
    assert pin["version"] == _version()
    assert re.fullmatch(r"[0-9a-f]{40}", pin["commit"])
    for path in pin["paths"]:
        assert (REPO / path.rstrip("/")).exists(), f"core path {path} is not in the tree"
    for path in pin["overrides"]:
        assert (REPO / path).is_file(), f"override {path} is not a shipped file"
    assert "hooks/" in pin["paths"] and "rules/" in pin["paths"]
    assert "skills/" not in pin["paths"], "skills are vendored selectively; the example must not claim them whole"


def test_consuming_doc_and_readme_point_at_each_other():
    doc = (REPO / "docs" / "consuming-from-a-private-overlay.md").read_text(encoding="utf-8")
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "bin/upstream-check.py" in doc and "UPSTREAM.json" in doc
    assert "consuming-from-a-private-overlay.md" in readme
    assert "CHANGELOG.md" in readme
