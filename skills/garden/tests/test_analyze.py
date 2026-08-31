"""Unit tests for garden/scripts/analyze.py detection logic.

Pins the 2026-06-10 detection-gap fixes:
- zero-dated PROSE reference topics (absorb profiles) classify as "topic",
  not "suspect_moc" — the misclassification that silently dropped 22 absorbs
  from the orphan/MoC-gap checks and let 27 MoC gaps accumulate
- non-canonical date-first headers are detected with a deterministic rewrite
- stale `updated:` and undated OPEN markers are detected
- stage audit splits auto-fixable under-promotion from report-only over-staging
- `maintenance`-tagged trackers are exempt from stage/orphan/gap checks
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "garden_analyze", Path(__file__).resolve().parent.parent / "scripts" / "analyze.py")
analyze_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analyze_mod)


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


FM = """---
title: {title}
description: A test topic.
stage: {stage}
tags: [{tags}]
cssclasses: [topic]
created: 2026-01-01
updated: {updated}
---
"""


def make_topic(title="T", stage="seedling", tags="testing", updated="2026-01-01", body=""):
    return FM.format(title=title, stage=stage, tags=tags, updated=updated) + body


# ── classify ─────────────────────────────────────────────────────────────────

def test_zero_dated_prose_reference_topic_is_topic():
    # Regression: absorb-style profile — many ## sections, zero dated entries,
    # mostly prose. Must be "topic" so orphan/MoC-gap checks see it.
    body = "# T\n\n" + "\n\n".join(
        f"## Section {i}\n\nProse paragraph about patterns observed in the wild, "
        "with detail sentences and no list links." for i in range(5))
    content = make_topic(body=body)
    assert analyze_mod.classify("absorb-example.md", 0, 5, "topic", content) == "topic"


def test_link_list_file_is_suspect_moc():
    body = "# T\n\n## Links\n\n" + "\n".join(
        f"- [[topic-{i}|Topic {i}]] -- descriptor" for i in range(10))
    content = make_topic(body=body)
    assert analyze_mod.classify("misc-links.md", 0, 3, "topic", content) == "suspect_moc"


def test_moc_prefix_and_cssclasses_still_win():
    assert analyze_mod.classify("_moc-x.md", 9, 9, "topic", "prose") == "moc"
    assert analyze_mod.classify("anything.md", 0, 9, "moc", "prose") == "moc"
    assert analyze_mod.classify("dashboard-x.md", 0, 9, "topic", "") == "dashboard"


# ── full-pass detections ─────────────────────────────────────────────────────

@pytest.fixture()
def garden(tmp_path):
    def run():
        return analyze_mod.analyze(str(tmp_path))
    run.dir = tmp_path
    return run


def test_noncanonical_dated_header_detected_with_rewrite(garden):
    body = ("# T\n\n## 2026-05-08: Phase A1 results [verified]\n\nx\n\n"
            "## Canonical entry (2026-05-09)\n\ny\n")
    _write(garden.dir, "t.md", make_topic(body=body))
    r = garden()
    assert len(r["noncanonical_dated_headers"]) == 1
    row = r["noncanonical_dated_headers"][0]
    assert row["suggested"] == "## Phase A1 results (2026-05-08) [verified]"


def test_date_first_header_with_existing_trailing_date_drops_prefix(garden):
    body = "# T\n\n## 2026-05-17 grading session: B to A (2026-05-17)\n\nx\n"
    _write(garden.dir, "t.md", make_topic(body=body))
    row = garden()["noncanonical_dated_headers"][0]
    assert row["suggested"] == "## grading session: B to A (2026-05-17)"


def test_stale_updated_detected(garden):
    body = "# T\n\n## New entry (2026-06-01)\n\nx\n"
    _write(garden.dir, "t.md", make_topic(updated="2026-05-01", body=body))
    r = garden()
    assert r["stale_updated"] == [
        {"file": "t.md", "updated": "2026-05-01", "newest_entry": "2026-06-01"}]


def test_undated_open_marker_suggests_enclosing_entry_date(garden):
    body = ("# T\n\n## Gap found (2026-04-02)\n\n"
            "> **STATUS:** OPEN (since ?) — thing is broken\n\nx\n")
    _write(garden.dir, "t.md", make_topic(body=body))
    r = garden()
    assert len(r["undated_open_markers"]) == 1
    assert r["undated_open_markers"][0]["suggested_since"] == "2026-04-02"
    assert r["open_markers"] == []


def test_annotated_since_date_is_not_flagged_undated(garden):
    body = ("# T\n\n## Gap (2026-06-09)\n\n"
            "> **STATUS:** OPEN (since 2026-06-09; narrowed 2026-06-09) — partial\n")
    _write(garden.dir, "t.md", make_topic(body=body))
    r = garden()
    assert r["undated_open_markers"] == []
    assert [m["since"] for m in r["open_markers"]] == ["2026-06-09"]


def test_stage_under_promotion_vs_overstaged_split(garden):
    dated = "\n\n".join(f"## Entry {i} (2026-03-0{i})\n\nx" for i in range(1, 5))
    _write(garden.dir, "under.md", make_topic(stage="seedling", body="# T\n\n" + dated))
    _write(garden.dir, "over.md",
           make_topic(stage="evergreen", body="# T\n\n## Prose section\n\nProse only.\n"))
    r = garden()
    assert [m["file"] for m in r["stage_mismatches"]] == ["under.md"]
    assert r["stage_mismatches"][0]["should_be"] == "budding"
    assert [m["file"] for m in r["stage_overstaged"]] == ["over.md"]


def test_maintenance_tagged_tracker_exempt(garden):
    dated = "\n\n".join(f"## Item {i} (2026-03-0{i})\n\nx" for i in range(1, 7))
    _write(garden.dir, "tracker.md",
           make_topic(stage="seedling", tags="garden, maintenance", body="# T\n\n" + dated))
    r = garden()
    assert r["stage_mismatches"] == []
    assert "tracker.md" not in r["orphan_topics"]
    assert "tracker.md" not in r["moc_gap_topics"]


def test_hub_split_candidate_by_section_count(garden):
    body = "# T\n\n" + "\n\n".join(
        f"## Entry {i} (2026-03-01)\n\nshort" for i in range(35))
    _write(garden.dir, "big.md", make_topic(stage="evergreen", body=body))
    r = garden()
    assert [c["file"] for c in r["hub_split_candidates"]] == ["big.md"]


def test_unmanaged_rolling_log_is_hub_split_candidate(garden):
    body = "# T\n\n" + "\n\n".join(
        f"## Session {i:08x} (3 friction events) (2026-06-01)\n\nshort" for i in range(35))
    _write(garden.dir, "session-friction-patterns.md",
           make_topic(stage="evergreen", body=body))
    r = garden()
    assert [candidate["file"] for candidate in r["hub_split_candidates"]] == [
        "session-friction-patterns.md"
    ]


def test_current_understanding_missing_and_stale(garden):
    dated8 = "\n\n".join(f"## Entry {i} (2026-05-0{i})\n\nx" for i in range(1, 9))
    # 8+ dated entries, no CU section → cu_missing
    _write(garden.dir, "missing.md", make_topic(stage="evergreen", body="# T\n\n" + dated8))
    # CU present but regenerated before the newest entry → cu_stale
    cu = ("## Current understanding\n\nstate.\n\n"
          "<!-- current-understanding regenerated: 2026-05-01 -->\n\n")
    _write(garden.dir, "stale.md", make_topic(stage="evergreen", body="# T\n\n" + cu + dated8))
    # CU fresh → clean
    fresh = cu.replace("2026-05-01", "2026-05-08")
    _write(garden.dir, "fresh.md", make_topic(stage="evergreen", body="# T\n\n" + fresh + dated8))
    # under threshold → exempt
    _write(garden.dir, "small.md", make_topic(body="# T\n\n## Entry (2026-05-01)\n\nx"))
    r = garden()
    assert [m["file"] for m in r["cu_missing"]] == ["missing.md"]
    assert [m["file"] for m in r["cu_stale"]] == ["stale.md"]
    assert r["cu_stale"][0]["newest_entry"] == "2026-05-08"


def test_retired_topic_exempt_from_current_understanding(garden):
    dated9 = "\n\n".join(f"## Entry {i} (2026-05-0{i})\n\nx" for i in range(1, 10))
    _write(garden.dir, "retired.md", make_topic(stage="retired", body="# T\n\n" + dated9))
    r = garden()
    assert r["cu_missing"] == []


# ── merge-pair tag gate ──────────────────────────────────────────────────────

def test_merge_pair_below_two_shared_tags_is_dropped(garden):
    # The SKILL's confirmation rule requires >=2 shared tags for ANY merge
    # (including slug-prefix pairs), so a pair below that bar is dead on
    # arrival — emitting it only wastes memory_search calls (2026-08-22:
    # 9 of 15 emitted pairs were unmergeable by construction).
    body = "# T\n\n## A (2026-01-02)\n\nx\n"
    _write(garden.dir, "alpha.md", make_topic(
        title="Falcon Sensor Deployment Runbook", tags="crowdstrike", body=body))
    _write(garden.dir, "beta.md", make_topic(
        title="Falcon Sensor Deployment History", tags="edr", body=body))
    r = garden()
    assert r["merge_candidate_pairs"] == []


def test_merge_pair_with_two_shared_tags_survives(garden):
    # Positive control for the gate above: same >=3 shared title words,
    # but 2 shared tags → the pair must still be emitted.
    body = "# T\n\n## A (2026-01-02)\n\nx\n"
    _write(garden.dir, "alpha.md", make_topic(
        title="Falcon Sensor Deployment Runbook", tags="crowdstrike, edr", body=body))
    _write(garden.dir, "beta.md", make_topic(
        title="Falcon Sensor Deployment History", tags="crowdstrike, edr", body=body))
    r = garden()
    assert [(p["a"], p["b"]) for p in r["merge_candidate_pairs"]] == [
        ("alpha.md", "beta.md")]
    assert r["merge_candidate_pairs"][0]["shared_tags"] == 2


def test_slug_prefix_pair_below_tag_bar_is_also_dropped(garden):
    # The tag gate applies to slug-prefix pairs too — the confirmation rule
    # has no prefix exception.
    body = "# T\n\n## A (2026-01-02)\n\nx\n"
    _write(garden.dir, "gateway.md", make_topic(title="Gateway", tags="infra", body=body))
    _write(garden.dir, "gateway-next-steps.md", make_topic(
        title="Followups", tags="planning", body=body))
    r = garden()
    assert r["merge_candidate_pairs"] == []


# ── over-90d markers as rows ─────────────────────────────────────────────────

def test_open_markers_over_90d_is_the_filtered_row_list(garden):
    # Regression 2026-08-22: the field was an int count while every sibling
    # field is a row list, which crashed the first consumer that iterated it.
    import datetime
    recent = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    body = (f"# T\n\n## Old gap (2020-01-01)\n\n"
            f"> **STATUS:** OPEN (since 2020-01-01) — ancient\n\n"
            f"## New gap ({recent})\n\n"
            f"> **STATUS:** OPEN (since {recent}) — fresh\n")
    _write(garden.dir, "t.md", make_topic(body=body))
    r = garden()
    assert [m["since"] for m in r["open_markers_over_90d"]] == ["2020-01-01"]
    assert r["open_markers_over_90d"][0]["age_band"] == "over-90d"
    assert len(r["open_markers"]) == 2


# ── curator stage pin ────────────────────────────────────────────────────────

def test_stage_pinned_exempts_from_promotion_and_overstaged(garden):
    dated4 = "\n\n".join(f"## Entry {i} (2026-03-0{i})\n\nx" for i in range(1, 5))
    # Under-promoted but pinned → no auto-promotion row. Uses the INLINE
    # attribution-comment form deliberately: the naive frontmatter parser
    # keeps everything after the colon, so the pin must survive a trailing
    # YAML comment (measured failing 2026-08-22 on the live corpus).
    _write(garden.dir, "pinned-under.md",
           make_topic(stage="seedling", body="# T\n\n" + dated4).replace(
               "stage: seedling",
               "stage: seedling\nstage_pinned: true  # garden: 2026-08-22 action:stage-pin"))
    # Overstaged placeholder but pinned → no report-only row.
    _write(garden.dir, "pinned-over.md",
           make_topic(stage="evergreen", body="# T\n\n## Prose section\n\nProse only.\n"
                      ).replace("stage: evergreen", "stage: evergreen\nstage_pinned: true"))
    # Unpinned control: same shapes must still be flagged.
    _write(garden.dir, "under.md", make_topic(stage="seedling", body="# T\n\n" + dated4))
    _write(garden.dir, "over.md",
           make_topic(stage="evergreen", body="# T\n\n## Prose section\n\nProse only.\n"))
    r = garden()
    assert [m["file"] for m in r["stage_mismatches"]] == ["under.md"]
    assert [m["file"] for m in r["stage_overstaged"]] == ["over.md"]


# ── wiki-links ───────────────────────────────────────────────────────────────

def test_table_escaped_pipe_yields_bare_slug():
    # Regression: inside a markdown TABLE the wiki-link separator must be
    # written `\|`. Splitting on a raw `|` left the backslash on the slug, so a
    # valid link read as broken -- and garden's auto-resolution for a broken
    # link is to strip the [[]] wrapping, i.e. destroy it.
    links = analyze_mod.extract_wiki_links(
        "| col | see [[msgraph-api-patterns\\|Graph GCC High API Patterns]] |")
    assert [ln["slug"] for ln in links] == ["msgraph-api-patterns"]
    assert links[0]["display"] == "Graph GCC High API Patterns"


def test_unescaped_pipe_still_splits_slug_and_display():
    # Negative control for the unescape above: ordinary prose links must be
    # unaffected, so the test cannot pass by the unescape swallowing everything.
    links = analyze_mod.extract_wiki_links("see [[msgraph-api-patterns|Graph Patterns]].")
    assert links[0]["slug"] == "msgraph-api-patterns"
    assert links[0]["display"] == "Graph Patterns"


def test_table_escaped_link_to_existing_topic_is_not_broken(garden):
    _write(garden.dir, "target.md", make_topic(title="Target"))
    _write(garden.dir, "src.md", make_topic(
        body="# T\n\n| c | [[target\\|Target Topic]] |\n"))
    r = garden()
    assert r["broken_links"] == []


def test_genuinely_missing_table_escaped_target_is_still_broken(garden):
    # Negative control: the unescape must not suppress a REAL broken link.
    _write(garden.dir, "src.md", make_topic(
        body="# T\n\n| c | [[no-such-topic\\|Missing]] |\n"))
    r = garden()
    assert [b["slug"] for b in r["broken_links"]] == ["no-such-topic"]
