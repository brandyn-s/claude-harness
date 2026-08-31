"""Regression tests for parse_watching.py Item-column-only extraction.

The 2026-07-03 run's whole-section extraction captured inline issue/PR
references embedded in prose columns ("Subsumed by #40929", "PR #1489"),
inflating a 90-row Watching table to 120 numbers. These tests pin the fix:
only the table's first (Item) cell contributes numbers; whole-section scanning
survives solely as a labeled fallback for non-table input.
"""
import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "parse_watching",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "parse_watching.py",
)
assert _SPEC is not None and _SPEC.loader is not None
parse_watching = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(parse_watching)

REPORT = """\
# Claude Code Anthropic Intelligence

## Watching

| Item | Type | Status | Why we care | Updated |
|------|------|--------|-------------|---------|
| #36670 | Bug | Open | Agent Teams gap. Subsumed by #40929. | 2026-04-08 |
| #37793 | Bug | Open | Prompt too long; workaround shipped in PR #1489. | 2026-04-08 |
| #73508 | Bug | Open | AskUserQuestion auto-continue (see #73586 for the plugin variant). | 2026-07-03 |

## Archived

| #11111 | should never be extracted (different section) |
"""


def test_item_column_only():
    section = parse_watching.watching_section(REPORT)
    nums, used_fallback = parse_watching.item_column_numbers(section)
    assert nums == [36670, 37793, 73508], nums
    assert not used_fallback
    # the inline prose references must NOT leak into the set
    for inline_ref in (40929, 1489, 73586, 11111):
        assert inline_ref not in nums


def test_section_slicing_stops_at_next_header():
    section = parse_watching.watching_section(REPORT)
    assert "#11111" not in section


def test_fallback_for_non_table_stdin_input():
    bare = "## Watching\n\ntracking #12345 and #67890 informally\n"
    section = parse_watching.watching_section(bare)
    nums, used_fallback = parse_watching.item_column_numbers(section)
    assert nums == [12345, 67890]
    assert used_fallback


# --- Dormant-appendix exclusion (2026-08-30) ---------------------------------
#
# `## Watching` nests a `### Watching (Dormant)` appendix. The section slice
# terminates at the next TOP-LEVEL `## ` heading, and that lookahead requires
# whitespace after two hashes — so it can never match a `###` heading, and every
# incremental run swept the appendix too. Observable cost: #83731 (a Dormant row,
# deleted upstream) was re-extracted every run and re-reported by
# reconcile_watching as the "sole recurring NOT FOUND", which several runs then
# re-investigated. Dormant's own preamble says it is re-scanned on `full` runs only.
#
# These tests were originally added in a SECOND file at
# skills/gather-claude/scripts/test_parse_watching.py, which collided with this
# file's basename and broke `pytest skills/` collection with "import file
# mismatch" (pytest imports by module name, and neither dir is a package). Merged
# here — the canonical location, which also loads the module by explicit path
# instead of a sys.path insert.

REPORT_WITH_DORMANT = """\
# Report

## Watching

| Item | Type | Status | Why we care | Updated |
|------|------|--------|-------------|---------|
| #11111 | Bug | Open | active row; prose mentions PR #99999 | 2026-08-30 |
| #22222 / #33333 | Bug | Open | cluster row | 2026-08-30 |

### Watching (Dormant)

Rows parked out of the per-run working set. Re-scanned only on `full` runs.

| Item | Type | Status | Why we care | Updated |
|------|------|--------|-------------|---------|
| #44444 | Bug | DELETED upstream | dormant row | 2026-08-22 |
| #55555 | Bug | Open | [WIN-ONLY] | 2026-08-01 |

## Archived

| Item | Type | Status | Why we care | Updated |
|------|------|--------|-------------|---------|
| #66666 | Bug | Closed | archived, must never be extracted | 2026-07-01 |
"""

ACTIVE = {11111, 22222, 33333}
DORMANT = {44444, 55555}
ARCHIVED = {66666}
PROSE_ONLY = {99999}


def _numbers(text, include_dormant=False):
    section = parse_watching.watching_section(text, include_dormant=include_dormant)
    nums, fallback = parse_watching.item_column_numbers(section)
    return set(nums), fallback


def test_dormant_excluded_by_default():
    nums, fallback = _numbers(REPORT_WITH_DORMANT)
    assert not fallback, "should have parsed table rows, not fallen back"
    assert nums == ACTIVE
    for n in DORMANT:
        assert n not in nums, f"#{n} is a Dormant row"


def test_full_flag_includes_dormant():
    nums, _ = _numbers(REPORT_WITH_DORMANT, include_dormant=True)
    assert nums == ACTIVE | DORMANT


def test_archived_never_extracted_either_way():
    for flag in (False, True):
        nums, _ = _numbers(REPORT_WITH_DORMANT, include_dormant=flag)
        assert not nums & ARCHIVED, f"include_dormant={flag} leaked Archived"


def test_item_column_only_still_holds_with_dormant_present():
    """The 2026-07-05 Item-column-only fix must survive the new slicing."""
    for flag in (False, True):
        nums, _ = _numbers(REPORT_WITH_DORMANT, include_dormant=flag)
        assert not nums & PROSE_ONLY, "PR #99999 is prose, not a tracked row"


def test_strip_subsections_reports_dropped_line_count():
    section = parse_watching.watching_section(REPORT_WITH_DORMANT, include_dormant=True)
    active, dropped = parse_watching.strip_subsections(section)
    assert dropped > 0
    assert "Dormant" not in active


def test_strip_subsections_is_a_noop_without_a_subsection():
    plain = "## Watching\n\n| Item |\n|---|\n| #12345 |\n"
    active, dropped = parse_watching.strip_subsections(plain)
    assert dropped == 0
    assert active == plain


def test_top_level_terminator_cannot_match_a_triple_hash():
    """The root cause, asserted directly: this is WHY strip_subsections exists.

    If the top-level terminator ever starts matching `###`, the extra pass
    becomes redundant — but until then, removing it silently re-includes Dormant.
    """
    import re

    terminator = re.compile(r"^##\s+\S", re.MULTILINE)
    assert terminator.match("### Watching (Dormant)") is None
    assert terminator.match("## Archived") is not None
