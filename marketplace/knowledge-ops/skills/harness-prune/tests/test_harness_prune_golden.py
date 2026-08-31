"""Golden tests for harness-prune's scan_workarounds.py (created with the
skill per the 02-golden-tests.md creation-time convention).

Pins: a versioned model ref near workaround language is a candidate; the
same ref without a signal (or out of window) is not; bare workaround
language without a model ref is not; scan surface is skills/hooks/rules.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent
          / "scripts" / "scan_workarounds.py")


def _make_harness(tmp_path, skill_body):
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill_body, encoding="utf-8")
    (tmp_path / "hooks").mkdir()
    (tmp_path / "rules").mkdir()
    return tmp_path


def _run(root, *extra):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *extra],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_model_ref_near_signal_is_candidate(tmp_path):
    root = _make_harness(tmp_path, (
        "# Demo\n"
        "This step exists to work around Sonnet 3.5 truncating long "
        "tool results.\n"))
    out = _run(root)
    assert len(out["candidates"]) == 1
    c = out["candidates"][0]
    assert c["model_ref"].lower().startswith("sonnet")
    assert "work around" in c["signal"].lower()
    assert c["line"] == 2


def test_model_ref_without_signal_not_candidate(tmp_path):
    root = _make_harness(tmp_path, (
        "# Demo\nDefault model is claude-haiku-4-5 for cost reasons.\n"))
    out = _run(root)
    assert out["candidates"] == []


def test_signal_without_model_ref_not_candidate(tmp_path):
    root = _make_harness(tmp_path, (
        "# Demo\nWe work around the API rate limit by batching.\n"))
    out = _run(root)
    assert out["candidates"] == []


def test_signal_outside_window_not_candidate(tmp_path):
    filler = "filler line\n" * 5
    root = _make_harness(tmp_path, (
        "Opus 4.1 is referenced here.\n" + filler +
        "We compensate for slowness elsewhere.\n"))
    out = _run(root)
    assert out["candidates"] == []


def test_hooks_and_rules_scanned(tmp_path):
    root = _make_harness(tmp_path, "# clean\n")
    (root / "hooks" / "demo.py").write_text(
        "# compensate for opus-4-0 context anxiety\n", encoding="utf-8")
    (root / "rules" / "demo.md").write_text(
        "Context reset behavior on Haiku 3.5 requires this rule.\n",
        encoding="utf-8")
    out = _run(root)
    files = {Path(c["file"]).name for c in out["candidates"]}
    assert files == {"demo.py", "demo.md"}


def test_current_model_families_and_shared_policy_files_are_scanned(tmp_path):
    root = _make_harness(tmp_path, "# clean\n")
    shared = root / "skills" / "_shared"
    shared.mkdir()
    (shared / "model-policy.md").write_text(
        "Work around Fable 5 context anxiety here.\n"
        "Mythos 5 needs a context reset workaround.\n",
        encoding="utf-8",
    )
    out = _run(root)
    refs = {c["model_ref"].lower() for c in out["candidates"]}
    assert "fable 5" in refs
    assert "mythos 5" in refs
    assert out["scanned_files"] >= 2


def test_missing_root_exits_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path / "nope")],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 2


def test_negative_window_exits_2(tmp_path):
    root = _make_harness(tmp_path, "# clean\n")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root),
         "--window", "-1"],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert "error:" in r.stderr


def test_help_short_circuits():
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=30)
    assert r.returncode == 0
    assert "workaround" in r.stdout.lower()
