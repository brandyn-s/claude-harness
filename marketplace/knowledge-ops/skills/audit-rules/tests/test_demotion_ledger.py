"""Tests for the demotion ledger + zero-emission + path-split changes
(2026-08-22 live-run improvements).

Three surfaces changed together:
  scan_violations.py: to_dict(include_all_rules=True) emits a zero-count
    entry per ALL_RULES detector; V1 buckets hits by open() path category.
  classify_rules.py: consults AUDIT-TRACKERS/demotions.yaml and reports a
    platform-effective demotion as hook-warned, not hook-enforced.
  detect_demotion_candidates.py: --scan-json reuses a prior scan; ledgered
    rules land in already_demoted, not demotion_candidates.

Platform note: the shipped ledger entry for encoding-missing-open has
scope non-win32, so assertions about its EFFECT are platform-conditional
(tdd-quality item 10 family — the Windows CI leg is a different world
here by design, not by accident).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parent.parent
DETECTOR = SKILL_DIR / "scripts" / "detect_demotion_candidates.py"


def _load_module(name, path, config_root=None):
    saved = os.environ.pop("AUDIT_RULES_CONFIG_ROOT", None)
    if config_root is not None:
        os.environ["AUDIT_RULES_CONFIG_ROOT"] = str(config_root)
    try:
        if name in sys.modules:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ.pop("AUDIT_RULES_CONFIG_ROOT", None)
        if saved is not None:
            os.environ["AUDIT_RULES_CONFIG_ROOT"] = saved
    return mod


def _load_scanner():
    return _load_module(
        "scan_violations", SKILL_DIR / "references" / "scan_violations.py")


def _load_classifier(config_root=None):
    return _load_module(
        "classify_rules", SKILL_DIR / "references" / "classify_rules.py",
        config_root=config_root)


# ── scanner: zero-emission ────────────────────────────────────────────────────

def test_to_dict_default_excludes_unrecorded_rules():
    """Tracker-level contract preserved: without include_all_rules, only
    recorded rules appear (a block signature alone must not fabricate)."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 3
    out = t.to_dict()
    assert out["violations"] == {}


def test_to_dict_include_all_rules_emits_zero_entries():
    """Every ALL_RULES detector appears, zero-hit ones with count 0 —
    'measured clean' is distinguishable from 'detector removed'."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 3
    t.record("inline-python-c", "s1", "python3 -c ...")
    out = t.to_dict(include_all_rules=True)
    assert set(sv.ALL_RULES) <= set(out["violations"])
    zero = out["violations"]["pip-install-upgrade-all"]
    assert zero["count"] == 0
    assert zero["unique_sessions"] == 0
    assert zero["session_rate_pct"] == 0
    assert zero["examples"] == []
    # Mapped zero rule still carries the breakdown shape, all zeros.
    enc = out["violations"]["encoding-missing-open"]
    assert enc["blocked_then_fixed_sessions"] == 0
    assert enc["net_silent_sessions"] == 0


def test_all_rules_registry_matches_detector_count():
    """ALL_RULES must list exactly the V1-V8 detectors (V9 disabled)."""
    sv = _load_scanner()
    assert len(sv.ALL_RULES) == 8
    assert "encoding-missing-open" in sv.ALL_RULES
    assert "pip-install-upgrade-all" in sv.ALL_RULES


# ── scanner: V1 path-split ────────────────────────────────────────────────────

def test_classify_open_path_buckets():
    sv = _load_scanner()
    assert sv._classify_open_path("open('/tmp/x.json')") == "scratch"
    assert sv._classify_open_path("open('/private/tmp/y')") == "scratch"
    assert sv._classify_open_path("open('/dev/stdin')") == "scratch"
    assert sv._classify_open_path("open('settings.json')") == "durable_or_unknown"
    assert sv._classify_open_path("open('/Users/me/report.md')") == "durable_or_unknown"
    assert sv._classify_open_path("open(f)") == "non_literal"
    assert sv._classify_open_path("open(sys.argv[1])") == "non_literal"


def test_path_split_reported_for_v1_categories():
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 2
    t.record("encoding-missing-open", "s1", "open('/tmp/a.json')",
             category=sv._classify_open_path("open('/tmp/a.json')"))
    t.record("encoding-missing-open", "s1", "open('cfg.json')",
             category=sv._classify_open_path("open('cfg.json')"))
    entry = t.to_dict()["violations"]["encoding-missing-open"]
    assert entry["path_split"] == {"scratch": 1, "durable_or_unknown": 1}


def test_path_split_absent_when_no_category_passed():
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 2
    t.record("git-commit-no-branch-check", "s1", "git commit")
    entry = t.to_dict()["violations"]["git-commit-no-branch-check"]
    assert "path_split" not in entry


def test_suppressed_hit_not_counted_in_path_split():
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[{
        "rule": "encoding-missing-open", "pattern": "open('/tmp/sup",
        "reason": "test",
    }])
    t.sessions_scanned = 1
    t.record("encoding-missing-open", "s1", "open('/tmp/sup.json')",
             category="scratch")
    assert t.path_categories["encoding-missing-open"] == {}


# ── classifier: ledger loading + platform scope ──────────────────────────────

def test_load_demotions_parses_repo_ledger():
    """The shipped ledger must parse and contain the encoding entry."""
    mod = _load_classifier()
    entries = mod._load_demotions()
    by_rule = {e["scanner_rule"]: e for e in entries}
    assert "encoding-missing-open" in by_rule
    e = by_rule["encoding-missing-open"]
    assert e["hook"] == "post-write-edit.py"
    assert e["scope"] == "non-win32"
    assert e["date"] == "2026-06-27"
    assert e["rationale"]


def test_load_demotions_missing_file_returns_empty(tmp_path):
    mod = _load_classifier(config_root=tmp_path)
    assert mod._load_demotions() == []


def test_load_demotions_drops_malformed_entries(tmp_path):
    trackers = tmp_path / "AUDIT-TRACKERS"
    trackers.mkdir()
    (trackers / "demotions.yaml").write_text(
        "demotions:\n"
        "  - scanner_rule: good-rule\n"
        "    hook: h.py\n"
        "    date: \"2026-01-01\"\n"
        "    rationale: \"evidence\"\n"
        "  - scanner_rule: no-rationale\n"
        "    hook: h.py\n"
        "    date: \"2026-01-01\"\n",
        encoding="utf-8",
    )
    mod = _load_classifier(config_root=tmp_path)
    entries = mod._load_demotions()
    assert [e["scanner_rule"] for e in entries] == ["good-rule"]


def test_demotion_effective_scopes():
    mod = _load_classifier()
    assert mod._demotion_effective({"scope": "all"}, platform="win32")
    assert mod._demotion_effective({"scope": "all"}, platform="darwin")
    assert not mod._demotion_effective({"scope": "non-win32"}, platform="win32")
    assert mod._demotion_effective({"scope": "non-win32"}, platform="darwin")
    assert mod._demotion_effective({"scope": "non-win32"}, platform="linux")
    # Unrecognized scope never silently reclassifies.
    assert not mod._demotion_effective({"scope": "weird"}, platform="darwin")
    # Missing scope defaults to "all".
    assert mod._demotion_effective({}, platform="darwin")


def test_classify_rules_annotates_demoted_rule():
    """Against the real repo: the encoding rule reports hook-warned
    (demoted) off-Windows, hook-enforced on Windows (block retained)."""
    mod = _load_classifier()
    rules, _ = mod.classify_rules()
    enc = [r for r in rules
           if r["rule"] == "Block Python scripts missing encoding='utf-8' in open()"]
    assert len(enc) == 1
    layer = enc[0]["layer"]
    if sys.platform == "win32":
        assert layer.startswith("hook-enforced"), layer
        assert "demotion" not in enc[0]
    else:
        assert layer.startswith("hook-warned (demoted 2026-06-27"), layer
        assert enc[0]["demotion"]["scanner_rule"] == "encoding-missing-open"


# ── detector: --scan-json + already_demoted ───────────────────────────────────

def _run_detector_with_scan(tmp_path, violations):
    scan = {
        "sessions_scanned": 10,
        "lines_scanned": 100,
        "scan_window": ["2026-08-08T00:00:00", "2026-08-22T00:00:00"],
        "suppressed": {},
        "violations": violations,
    }
    scan_path = tmp_path / "scan.json"
    scan_path.write_text(json.dumps(scan), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(DETECTOR), "--json", "--threshold", "10",
         "--scan-json", str(scan_path)],
        capture_output=True, text=True, timeout=120, cwd=str(REPO),
    )


def test_scan_json_reuse_skips_live_scan(tmp_path):
    """--scan-json needs NO transcript dirs (no HOME seeding here) — proof
    the scanner subprocess is not invoked."""
    r = _run_detector_with_scan(tmp_path, {
        "git-commit-no-branch-check": {
            "count": 9, "unique_sessions": 5, "session_rate_pct": 50.0,
        },
    })
    assert r.returncode == 0, r.stderr[:300]
    data = json.loads(r.stdout)
    assert data["scan_source"].endswith("scan.json")
    assert data["scan_window_days"] is None
    rules = [c["rule"] for c in data["demotion_candidates"]]
    assert "git-commit-no-branch-check" in rules


def test_ledgered_rule_lands_in_already_demoted(tmp_path):
    r = _run_detector_with_scan(tmp_path, {
        "encoding-missing-open": {
            "count": 100, "unique_sessions": 8, "session_rate_pct": 80.0,
        },
    })
    assert r.returncode == 0, r.stderr[:300]
    data = json.loads(r.stdout)
    cand_rules = [c["rule"] for c in data["demotion_candidates"]]
    demoted_rules = [d["rule"] for d in data["already_demoted"]]
    if sys.platform == "win32":
        # scope non-win32 → block retained on Windows → still a candidate
        assert "encoding-missing-open" in cand_rules
        assert demoted_rules == []
    else:
        assert "encoding-missing-open" in demoted_rules
        assert cand_rules == []
        d = data["already_demoted"][0]
        assert d["demoted_on"] == "2026-06-27"
        assert d["rationale"]
