"""Tests for aggregate always-loaded rule context accounting."""

import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

import rule_context_budget as budget  # noqa: E402 -- resolves via the sys.path insert above


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_counts_only_top_level_rules_without_paths_frontmatter(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    _write(rules / "ambient.md", "a" * 100)
    _write(
        rules / "scoped.md",
        "---\npaths:\n  - '**/*.py'\n---\n" + "b" * 200,
    )
    (rules / "incidents").mkdir()
    _write(rules / "incidents" / "old.md", "c" * 300)

    assert budget.unconditional_rule_bytes(rules) == 100
    assert [p.name for p in budget.unconditional_rule_files(rules)] == ["ambient.md"]


def test_projected_override_can_scope_or_grow_a_rule(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    target = _write(rules / "ambient.md", "a" * 100)

    assert budget.unconditional_rule_bytes(rules, {target: "a" * 150}) == 150
    scoped = "---\npaths:\n  - '**/*.md'\n---\n" + "a" * 150
    assert budget.unconditional_rule_bytes(rules, {target: scoped}) == 0


def test_frontmatter_parser_does_not_treat_body_word_as_scope():
    assert not budget.has_paths_frontmatter("# Rule\nMention paths: later\n")
    assert not budget.has_paths_frontmatter("---\ntitle: x\n---\npaths: body\n")
    assert budget.has_paths_frontmatter("---\npaths:\n  - '**'\n---\n# Rule\n")


def test_counts_utf8_bytes_not_characters(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    _write(rules / "ambient.md", "é" * 10)
    assert budget.unconditional_rule_bytes(rules) == 20


def test_projected_override_counts_utf8_bytes_not_characters(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    target = _write(rules / "ambient.md", "a")

    assert budget.unconditional_rule_bytes(rules, {target: "é" * 10}) == 20


def test_malformed_frontmatter_fails_closed(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    _write(rules / "ambient.md", "---\ntitle: broken\npaths:\n  - '**'\n")
    with pytest.raises(budget.RuleContextBudgetError, match="unterminated"):
        budget.unconditional_rule_bytes(rules)


def test_delimited_but_invalid_yaml_frontmatter_fails_closed(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    _write(rules / "ambient.md", "---\npaths: [\n---\n" + ("x" * 300_000))
    with pytest.raises(budget.RuleContextBudgetError, match="invalid YAML"):
        budget.unconditional_rule_bytes(rules)


def test_invalid_utf8_fails_closed(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "ambient.md").write_bytes(b"\xff")
    with pytest.raises(budget.RuleContextBudgetError, match="UTF-8"):
        budget.unconditional_rule_bytes(rules)


def test_top_level_symlink_escape_fails_closed(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    outside = _write(tmp_path / "outside.md", "secret")
    (rules / "ambient.md").symlink_to(outside)
    with pytest.raises(budget.RuleContextBudgetError, match="symlink"):
        budget.unconditional_rule_bytes(rules)
