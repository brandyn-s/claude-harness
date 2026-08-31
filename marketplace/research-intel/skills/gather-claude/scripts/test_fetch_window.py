"""Tests for fetch_window.py's non-network logic.

Covers the 2026-08-22b run's three shipped behaviors:
  1. docs-baseline same-date no-clobber (a second same-day run must diff
     against the first run's file before overwriting it)
  2. docs-baseline origin/main fallback when the local checkout is behind
     (including the ls-tree cwd-relative-pathspec bug the fixture caught
     before ship: pathspecs must be resolved from the repo toplevel)
  3. report_issue_overlap: ALREADY-COVERED vs FRESH split + [cyber] bucketing

Network-dependent behavior (task fetching, escalation) is exercised by live
runs and stays out of unit scope.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "fetch_window.py"
spec = importlib.util.spec_from_file_location("fetch_window", SCRIPT)
assert spec is not None and spec.loader is not None
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)


def _git(cwd, *args, **kw):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          check=True, capture_output=True, text=True, **kw)


@pytest.fixture()
def kb_repo(tmp_path):
    """A clone with an origin/main holding one baseline file, and the local
    baselines dir empty (checkout-behind shape)."""
    bare = tmp_path / "origin.git"
    work = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(work)],
                   check=True, capture_output=True)
    bdir = work / "research" / "baselines"
    bdir.mkdir(parents=True)
    (bdir / "claude-docs-pages-2026-08-20.txt").write_text(
        "docs/en/a.md\ndocs/en/b.md\n")
    _git(work, "add", "-A")
    _git(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    _git(work, "push", "-q", "origin", "HEAD:main")
    _git(work, "fetch", "-q", "origin", "main")
    _git(work, "update-ref", "refs/remotes/origin/main", "FETCH_HEAD")
    return work, bdir


def _out_dir(tmp_path, pages):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "docs-llms.txt").write_text(
        "\n".join(f"docs/en/{p}.md" for p in pages) + "\n")
    return out


def test_origin_fallback_when_local_dir_empty(kb_repo, tmp_path, capsys):
    _, bdir = kb_repo
    (bdir / "claude-docs-pages-2026-08-20.txt").unlink()  # checkout behind
    out = _out_dir(tmp_path, ["a", "b", "c"])
    fw.persist_docs_baseline(out, str(bdir), "2026-08-22")
    got = capsys.readouterr().out
    assert "recovered from origin/main" in got
    assert "+1 / -0" in got
    assert "+ docs/en/c.md" in got
    # recovered temp copy is cleaned up, real baseline persisted
    assert not list(bdir.glob(".origin-*"))
    assert (bdir / "claude-docs-pages-2026-08-22.txt").exists()


def test_same_date_no_clobber_diffs_before_overwrite(kb_repo, tmp_path, capsys):
    _, bdir = kb_repo
    (bdir / "claude-docs-pages-2026-08-20.txt").unlink()
    out = _out_dir(tmp_path, ["a", "b", "c"])
    fw.persist_docs_baseline(out, str(bdir), "2026-08-22")
    capsys.readouterr()
    # second run same day, one page removed
    out = _out_dir(tmp_path, ["a", "c"])
    fw.persist_docs_baseline(out, str(bdir), "2026-08-22")
    got = capsys.readouterr().out
    assert "(same-date, earlier run)" in got
    assert "+0 / -1" in got
    assert "- docs/en/b.md" in got


def test_no_baseline_anywhere_is_reported(tmp_path, capsys):
    bdir = tmp_path / "baselines"  # not a git repo, nothing prior
    out = _out_dir(tmp_path, ["a"])
    fw.persist_docs_baseline(out, str(bdir), "2026-08-22")
    got = capsys.readouterr().out
    assert "no previous baseline anywhere" in got


def _manifest_with_issues(tmp_path, rows_by_task):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    manifest = {}
    for task, rows in rows_by_task.items():
        f = out / f"{task}.json"
        f.write_text(json.dumps(rows))
        manifest[task] = {"file": str(f), "rc": 0}
    return out, manifest


def test_overlap_split_and_cyber_bucket(tmp_path, capsys):
    out, manifest = _manifest_with_issues(tmp_path, {
        "census-unlabeled": [
            {"number": 101, "title": "plain bug"},
            {"number": 102, "title": "[Bug][cyber] classifier FP"},
            {"number": 103, "title": "already known bug"},
        ],
    })
    report = tmp_path / "report.md"
    report.write_text("prior report mentions #103 in a Watching row\n")
    fw.report_issue_overlap(out, manifest, str(report))
    got = capsys.readouterr().out
    assert "[cyber] classifier-FP bucket: 1 of 3" in got
    assert "#102" in got
    assert "1 already covered (#103)" in got
    # fresh excludes both the covered number and the cyber bucket
    assert "FRESH (triage these): 1 (#101)" in got


def test_overlap_without_report_only_buckets(tmp_path, capsys):
    out, manifest = _manifest_with_issues(tmp_path, {
        "kw-hook": [{"number": 7, "title": "[cyber] fp"}],
    })
    fw.report_issue_overlap(out, manifest, None)
    got = capsys.readouterr().out
    assert "classifier-FP bucket" in got
    assert "FRESH" not in got


def test_overlap_unreadable_report_degrades(tmp_path, capsys):
    out, manifest = _manifest_with_issues(tmp_path, {
        "kw-hook": [{"number": 7, "title": "x"}],
    })
    fw.report_issue_overlap(out, manifest, str(tmp_path / "missing.md"))
    got = capsys.readouterr().out
    assert "report unreadable" in got


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
