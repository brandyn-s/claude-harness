"""Unit tests for healthcheck/references/_check_targets.py (Check 8).

Pins the output-target verdict: all present → PASS(0); any missing → WARN(1),
each labelled expected (all 4 current targets are non-optional as of the
2026-07-03 /distill last-run-marker retarget — see git history for the retired
optional-labelling test). Honors CLAUDE_CONFIG_DIR (monkeypatched here).
"""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_targets",
    Path(__file__).resolve().parent.parent / "references" / "_check_targets.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def _wire(tmp_path, monkeypatch, staging=True, last_distill=True, kb=True, ledger=True):
    claude = tmp_path / ".claude"
    home = tmp_path / "home"
    (claude).mkdir(parents=True, exist_ok=True)
    if staging:
        (claude / "hooks" / "staged").mkdir(parents=True, exist_ok=True)
    if last_distill:
        (claude / "last-distill.json").write_text("{}", encoding="utf-8")
    if ledger:
        (claude / "assessed-repos.md").write_text("## Assessed", encoding="utf-8")
    topics = home / "Documents" / "knowledge-base" / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    if kb:
        (topics / "a-topic.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(hc, "CLAUDE_DIR", claude)
    monkeypatch.setattr(hc, "HOME", home)
    return claude


def test_all_targets_present_passes(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    status, msg = hc.check_targets()
    assert status == "PASS"
    assert "4 output targets verified" in msg


def test_missing_expected_target_warns(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, ledger=False)
    status, msg = hc.check_targets()
    assert status == "WARN"
    assert "gather-repos ledger (expected)" in msg


def test_empty_kb_topics_warns(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, kb=False)   # topics dir exists but holds no .md
    status, msg = hc.check_targets()
    assert status == "WARN"
    assert "KB topics (expected)" in msg


def test_missing_last_distill_marker_warns(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, last_distill=False)
    status, msg = hc.check_targets()
    assert status == "WARN"
    assert "last-run marker (expected)" in msg


def test_main_passes_when_all_present(tmp_path, monkeypatch, capsys):
    _wire(tmp_path, monkeypatch)
    assert hc.main() == 0
    assert "Targets: PASS" in capsys.readouterr().out


def test_main_warns_when_target_missing(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, ledger=False)
    assert hc.main() == 1
