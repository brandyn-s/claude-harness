"""Unit tests for review-learnings/scripts/analyze_memory.py detections."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "analyze_memory",
    Path(__file__).resolve().parent.parent / "scripts" / "analyze_memory.py")
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


@pytest.fixture()
def mem(tmp_path):
    def run():
        return mod.analyze(str(tmp_path))
    run.dir = tmp_path
    return run


def _entry(tag, title, days_ago=None):
    d = f" ({(date.today() - timedelta(days=days_ago)).isoformat()})" if days_ago is not None else ""
    return f"### {tag} {title}{d}\n\nbody\n"


def test_stale_observed_over_60_days(mem):
    text = ("# T\n\n" + _entry("[observed]", "old gotcha", days_ago=90)
            + _entry("[observed]", "fresh gotcha", days_ago=10)
            + _entry("[confirmed]", "old but confirmed", days_ago=200))
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    assert len(r["stale_observed"]) == 1
    assert r["stale_observed"][0]["age_days"] == 90


def test_tombstones_fixed_and_promote_candidates_flagged(mem):
    text = ("# T\n\n" + _entry("[promoted]", "moved elsewhere")
            + _entry("[FIXED]", "resolved issue")
            + _entry("[observed] PROMOTE-CANDIDATE", "seen thrice"))
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    assert len(r["promoted_tombstones"]) == 1
    assert len(r["fixed_entries"]) == 1
    assert len(r["promote_candidates"]) == 1


def test_duplicate_titles_cross_file_normalized(mem):
    # same title, different tags/dates → still a duplicate
    (mem.dir / "a.md").write_text(
        "# A\n\n" + _entry("[observed]", "FQL dates need quotes", days_ago=5), encoding="utf-8")
    (mem.dir / "b.md").write_text(
        "# B\n\n" + _entry("[confirmed]", "FQL dates need quotes", days_ago=40), encoding="utf-8")
    r = mem()
    assert len(r["duplicate_titles"]) == 1
    assert {loc[0] for loc in r["duplicate_titles"][0]["locations"]} == {"a.md", "b.md"}


def test_stale_deep_reference_detected(mem):
    (mem.dir / "t.md").write_text(
        "# T\n\n> Deep reference: nonexistent/path/file.md\n", encoding="utf-8")
    r = mem()
    assert r["stale_deep_references"] == [
        {"file": "t.md", "ref": "nonexistent/path/file.md"}]


def test_oversized_flagged_unless_cap_notice(mem):
    big_body = "x" * 25_000
    (mem.dir / "big.md").write_text("# Big\n\n### [observed] e\n" + big_body, encoding="utf-8")
    (mem.dir / "capped.md").write_text(
        "# Capped\n\n> Max 20 entries, oldest pruned.\n\n### [observed] e\n" + big_body,
        encoding="utf-8")
    r = mem()
    assert [o["file"] for o in r["oversized_files"]] == ["big.md"]


def test_mixed_format_detected(mem):
    text = ("# T\n\n### [observed] header style entry (2026-01-01)\n\nbody\n\n"
            "- [confirmed] bullet style entry\n")
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    assert r["mixed_format"] == [{"file": "t.md", "headers": 1, "bullets": 1}]


def test_version_tags_inventoried(mem):
    text = "# T\n\n" + _entry("[observed] [workaround:v2.1.0]", "needs flag until fix")
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    assert r["version_tags"][0]["tag"] == "workaround:v2.1.0"


def test_tags_are_leading_brackets_only(mem):
    # Verbatim real titles that manufactured phantom tags "-failed" and "X"
    # when the whole title was scanned (2026-08-22 audit).
    text = ("# T\n\n"
            "### [observed] [tool-gotcha] StepSecurity output MASKS the failing "
            "step in `gh run view --log[-failed]` (2026-06-24)\n\nbody\n\n"
            '### [confirmed] `argument-hint: "[X]"` brackets vs manifest '
            "(2026-05-24)\n\nbody\n")
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    tags = r["inventory"]["t.md"]["tags"]
    assert tags == {"observed": 1, "tool-gotcha": 1, "confirmed": 1}
    assert "-failed" not in tags and "X" not in tags


def test_dual_date_entry_gets_age_from_opened_date(mem):
    # Verbatim shape of the claude-code-config [FIXED] entry whose dual-date
    # form parsed as age_days=null (2026-08-22 audit).
    days = 60
    opened = (date.today() - timedelta(days=days)).isoformat()
    text = (f"# T\n\n### [FIXED] [tool-gotcha] guard blocked writes "
            f"({opened}, resolved by 2026-07-03)\n\nbody\n")
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    assert r["fixed_entries"][0]["age_days"] == days


def test_keep_decision_detected_on_fixed_and_tombstones(mem):
    text = ("# T\n\n### [FIXED] resolved but retained (2026-04-01)\n"
            "- Kept for historical record; no action needed.\n\n"
            "### [FIXED] resolved and prunable (2026-04-01)\n\nbody\n\n"
            "### [promoted] moved elsewhere (2026-04-01)\n\nbody\n")
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    by_title = {e["entry"]: e["keep_decision"] for e in r["fixed_entries"]}
    assert any(v for v in by_title.values()) and not all(by_title.values())
    assert r["promoted_tombstones"][0]["keep_decision"] is False


def test_format_classification(mem):
    (mem.dir / "entries.md").write_text(
        "# E\n\n" + _entry("[observed]", "tagged entry", days_ago=5), encoding="utf-8")
    (mem.dir / "guide.md").write_text(
        "# G - Worker Topic Guide\n\n### CLI install\n\nprose section, no tags\n",
        encoding="utf-8")
    r = mem()
    assert r["inventory"]["entries.md"]["format"] == "entry-format"
    assert r["inventory"]["guide.md"]["format"] == "reference-guide"


def test_large_reference_guide_not_in_oversized(mem):
    big_body = "x" * 25_000
    (mem.dir / "guide.md").write_text(
        "# G\n\n### Section without tags\n" + big_body, encoding="utf-8")
    (mem.dir / "entries.md").write_text(
        "# E\n\n### [observed] e\n" + big_body, encoding="utf-8")
    r = mem()
    assert [o["file"] for o in r["oversized_files"]] == ["entries.md"]
    assert [o["file"] for o in r["large_reference_files"]] == ["guide.md"]


def test_auto_captured_junk_markers(mem):
    text = ("# T\n\n### [auto-captured] mid-transcript fragment (2026-07-29)\n"
            "Let me write the ECS.5 case-study entry.\n"
            "- Source:  agent (session 9510ff24)\n\n"
            "### [auto-captured] durable fact (2026-07-29)\n"
            "The API rejects batch sizes over 100.\n")
    (mem.dir / "t.md").write_text(text, encoding="utf-8")
    r = mem()
    junk = [e for e in r["auto_captured"] if e["junk_markers"]]
    clean = [e for e in r["auto_captured"] if not e["junk_markers"]]
    assert len(junk) == 1 and len(clean) == 1
    assert "let me " in junk[0]["junk_markers"]


def test_cap_notice_file_inventoried(mem):
    (mem.dir / "capped.md").write_text(
        "# C\n\n> Max 20 entries, oldest pruned.\n\n### [observed] e\n\nbody\n",
        encoding="utf-8")
    r = mem()
    assert r["cap_notice_files"][0]["file"] == "capped.md"
    # tmp_path has no hooks/ or settings.json → no producer mentions, no crash
    assert r["cap_notice_files"][0]["producer_mentions"] == []


def test_preflight_unavailable_outside_git_repo(tmp_path_factory):
    outside = tmp_path_factory.mktemp("no-repo")
    pf = mod.preflight(str(outside))
    assert pf["available"] is False and pf["error"]


def test_out_of_range_date_warns_and_continues(mem, capsys):
    # Regex-plausible but out-of-range date (was an unhandled ValueError
    # traceback aborting the whole audit): entry is treated as undated,
    # a warning lands on stderr, and analysis of other files continues.
    (mem.dir / "bad.md").write_text(
        "# T\n\n### [observed] bad date entry (2026-13-45)\n\nbody\n",
        encoding="utf-8")
    (mem.dir / "good.md").write_text(
        "# T\n\n" + _entry("[observed]", "valid entry", days_ago=90),
        encoding="utf-8")
    r = mem()
    assert r["totals"]["files"] == 2
    assert [s["file"] for s in r["stale_observed"]] == ["good.md"]
    assert "invalid date" in capsys.readouterr().err
