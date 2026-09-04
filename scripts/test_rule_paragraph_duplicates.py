"""No two rule paragraphs may say the same thing.

docs/rules-ratchet-plan.md shrinks rules/ by consolidating text. A consolidation
that leaves a copy behind, or a blind append that duplicates a bullet (three were
removed on 2026-09-03 in f6f5a21), re-grows the corpus with no new content. This
gate measures paragraph overlap with the same content-word Jaccard as
scripts/test_skill_description_quality.py and fails on any pair over JACCARD_MAX.

Measured 2026-09-03, before the first ratchet step: 952 paragraphs of >= 8 content
words across 37 rules, 0 pairs over 0.8, closest pair 0.64 (two rules' "# Full
rationale, examples, and incident history: docs/rule-reference/<name>.md" pointer
lines, which differ only in the file they point at). The verbatim-duplicate lever
is therefore already spent; the remaining overlap is paraphrase, which the plan
handles rule by rule.

A "paragraph" is a blank-line-delimited block, split further at top-level list
items and the corpus's DSL keywords (STEP_n, GUARD, INVARIANT, FORBIDDEN,
REQUIRED), because most rules are lists and a duplicated bullet must not hide
inside a list that differs elsewhere.

Run `pytest -s scripts/test_rule_paragraph_duplicates.py` to print the closest pairs.
"""
from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

from test_skill_description_quality import content_tokens, jaccard

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = REPO_ROOT / "rules"
JACCARD_MAX = 0.8
MIN_TOKENS = 8
TOP_PAIRS = 10

ITEM_RX = re.compile(
    r"^(?:[-*]|\d+[a-z]?[.)]|STEP_\w+|GUARD\b|INVARIANT\b|FORBIDDEN\b|REQUIRED\b|ON\b|INCIDENT\b|FAILURE\b)\s"
)


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def paragraphs(text: str) -> list[tuple[int, str]]:
    """(first line number, text) per blank-line block, split at top-level items."""
    units: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0

    def flush() -> None:
        if current:
            units.append((start, "\n".join(current)))
            current.clear()

    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            flush()
            continue
        if not current or ITEM_RX.match(line):
            flush()
            start = lineno
        current.append(line)
    flush()
    return units


def rule_paragraphs(rules_dir: Path = RULES_DIR) -> list[tuple[str, int, str, frozenset[str]]]:
    units = []
    for md in sorted(rules_dir.glob("*.md")):
        for lineno, text in paragraphs(strip_frontmatter(md.read_text(encoding="utf-8"))):
            tokens = content_tokens(text)
            if len(tokens) >= MIN_TOKENS:
                units.append((md.name, lineno, text, tokens))
    return units


def ranked_pairs(units) -> list[tuple[float, str, int, str, int]]:
    pairs = [
        (jaccard(ta, tb), fa, la, fb, lb)
        for (fa, la, _, ta), (fb, lb, _, tb) in combinations(units, 2)
    ]
    pairs.sort(key=lambda row: (-row[0], row[1], row[3]))
    return pairs


def offenders(units, threshold: float = JACCARD_MAX) -> list[str]:
    return [
        f"{fa}:{la} <-> {fb}:{lb} jaccard={score:.3f}"
        for score, fa, la, fb, lb in ranked_pairs(units)
        if score > threshold
    ]


# --------------------------------------------------------------------------- tests

def test_top_level_list_items_are_separate_paragraphs():
    text = "- first bullet keeps going\n  onto a continuation line\n- second bullet\nplain\n\nnext block\n"
    assert [t for _, t in paragraphs(text)] == [
        "- first bullet keeps going\n  onto a continuation line",
        "- second bullet\nplain",
        "next block",
    ]


def test_gate_fires_on_a_duplicated_paragraph(tmp_path):
    """Known-positive control: the same paragraph in two files, one of them reflowed inside a list."""
    lesson = ("Pair every zero with a known-positive control in the same command, "
              "because a detector that finds nothing and a broken detector look identical.")
    (tmp_path / "a.md").write_text(f"# A\n\n{lesson}\n", encoding="utf-8")
    (tmp_path / "b.md").write_text(
        "# B\n\n- unrelated bullet about something else entirely here\n- " + lesson.replace(", ", ",\n  ") + "\n",
        encoding="utf-8",
    )
    found = offenders(rule_paragraphs(tmp_path))
    assert len(found) == 1 and found[0].startswith("a.md:3 <-> b.md:4"), found


def test_no_two_rule_paragraphs_exceed_jaccard_max():
    units = rule_paragraphs()
    assert len(units) >= 500, "rules/*.md corpus went missing or moved"
    found = offenders(units)
    assert not found, (
        f"{len(found)} rule paragraph pair(s) over {JACCARD_MAX} content-word overlap; "
        "keep one occurrence and point the other file at it:\n  " + "\n  ".join(found)
    )


def test_report_closest_pairs():
    """Always passes; prints the ranked table under `pytest -s`."""
    units = rule_paragraphs()
    pairs = ranked_pairs(units)
    print(f"\n{len(units)} rule paragraphs (>= {MIN_TOKENS} content words), {len(pairs)} pairs; "
          f"{TOP_PAIRS} closest (threshold {JACCARD_MAX}):")
    for score, fa, la, fb, lb in pairs[:TOP_PAIRS]:
        print(f"{score:7.3f}  {fa}:{la:<5} {fb}:{lb}")
