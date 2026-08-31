"""Tests for skill_quality_audit.py reference-resolution logic.

Focus: validate_references() cross-skill path resolution. The 2026-04-20 bug
was that references pointing to a sibling skill's references/ dir (e.g.
~/.claude/skills/codebase-memory-exploring/references/code-graph-reference.md
cited from codebase-memory-quality/SKILL.md) were misattributed to the
referencing skill's own references/ dir, generating 8 false positives.
"""
import os
import sys
import pytest

# Import the module under test
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', '..', 'skills',
    'audit-architecture', 'references'
))
import skill_quality_audit as sqa  # noqa: E402


def _write_skill(skills_root, name, body='', refs=None):
    """Create a skill directory with SKILL.md and optional references/ files."""
    skill_dir = os.path.join(skills_root, name)
    refs_dir = os.path.join(skill_dir, 'references')
    os.makedirs(refs_dir, exist_ok=True)
    frontmatter = f'---\nname: {name}\ndescription: test\n---\n\n'
    with open(os.path.join(skill_dir, 'SKILL.md'), 'w', encoding='utf-8') as f:
        f.write(frontmatter + body)
    for ref_name, ref_body in (refs or {}).items():
        with open(os.path.join(refs_dir, ref_name), 'w', encoding='utf-8') as f:
            f.write(ref_body)


class TestResolveReferenceTarget:
    """_resolve_reference_target should route a cited path to the correct skill."""

    def test_same_skill_reference_resolves_to_source(self):
        result = sqa._resolve_reference_target(
            'references/foo.md', 'my-skill', {'my-skill', 'other-skill'})
        assert result == ('my-skill', 'foo.md')

    def test_cross_skill_relative_reference_resolves_to_target(self):
        result = sqa._resolve_reference_target(
            'other-skill/references/foo.md', 'my-skill',
            {'my-skill', 'other-skill'})
        assert result == ('other-skill', 'foo.md')

    def test_cross_skill_absolute_reference_resolves_to_target(self):
        result = sqa._resolve_reference_target(
            '~/.claude/skills/other-skill/references/foo.md', 'my-skill',
            {'my-skill', 'other-skill'})
        assert result == ('other-skill', 'foo.md')

    def test_cross_skill_semi_absolute_reference_resolves_to_target(self):
        result = sqa._resolve_reference_target(
            'skills/other-skill/references/foo.md', 'my-skill',
            {'my-skill', 'other-skill'})
        assert result == ('other-skill', 'foo.md')

    def test_unknown_prefix_falls_back_to_source(self):
        # Prefix doesn't match a known skill — treat as same-skill
        result = sqa._resolve_reference_target(
            'unknown-skill/references/foo.md', 'my-skill', {'my-skill'})
        assert result == ('my-skill', 'foo.md')

    def test_path_without_references_segment_returns_none(self):
        result = sqa._resolve_reference_target(
            'some/other/path.md', 'my-skill', {'my-skill'})
        assert result is None


class TestValidateReferences:
    """validate_references should correctly identify broken + orphaned refs."""

    def test_cross_skill_valid_reference_not_flagged_broken(self, tmp_path, monkeypatch):
        """Regression test for 2026-04-20 bug: cross-skill references were
        incorrectly flagged as broken because the scanner looked for the file
        under the referencing skill's own references/ dir."""
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        # skill-a has a real reference file
        _write_skill(skills_root, 'skill-a', refs={'shared.md': '# shared'})
        # skill-b references skill-a's reference using an absolute path
        _write_skill(
            skills_root, 'skill-b',
            body='See ~/.claude/skills/skill-a/references/shared.md for details.\n'
        )

        orphaned, broken = sqa.validate_references()
        # skill-b's reference to skill-a/references/shared.md resolves correctly
        assert broken == []
        # shared.md is mentioned in skill-b's SKILL.md → not orphaned
        assert orphaned == []

    def test_truly_broken_reference_still_flagged(self, tmp_path, monkeypatch):
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        _write_skill(
            skills_root, 'skill-c',
            body='See references/nonexistent.md for details.\n'
        )

        _, broken = sqa.validate_references()
        assert any('nonexistent.md' in b for b in broken)

    def test_broken_cross_skill_reference_attributed_to_target(self, tmp_path, monkeypatch):
        """A broken reference pointing at skill-x should be reported as
        skill-x/references/<file> (referenced by skill-y) — not as
        skill-y/references/<file>."""
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        _write_skill(skills_root, 'skill-x')  # has references/ but no files
        _write_skill(
            skills_root, 'skill-y',
            body='See skill-x/references/missing.md.\n'
        )

        _, broken = sqa.validate_references()
        # Should attribute to skill-x (the target), mention skill-y as referrer
        matches = [b for b in broken if 'missing.md' in b]
        assert len(matches) == 1
        assert matches[0].startswith('skill-x/references/missing.md')
        assert 'referenced by skill-y' in matches[0]

    def test_orphan_detected_when_no_skill_mentions_file(self, tmp_path, monkeypatch):
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        _write_skill(
            skills_root, 'skill-d',
            refs={'orphan.md': '# nobody mentions me'}
        )

        orphaned, _ = sqa.validate_references()
        assert any('orphan.md' in o for o in orphaned)

    def test_cross_skill_mention_clears_orphan_flag(self, tmp_path, monkeypatch):
        """A file in skill-e/references/ mentioned only from skill-f's SKILL.md
        should NOT be flagged as orphaned (the 2026-04-20 upgrade adds this
        cross-skill orphan check)."""
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        _write_skill(
            skills_root, 'skill-e',
            refs={'shared.md': '# referenced externally'}
        )
        _write_skill(
            skills_root, 'skill-f',
            body='See skill-e/references/shared.md.\n'
        )

        orphaned, _ = sqa.validate_references()
        assert not any('shared.md' in o for o in orphaned)

    def test_sibling_reference_file_mention_clears_orphan_flag(self, tmp_path, monkeypatch):
        """A file in skill-a/references/ mentioned only from another file
        IN THE SAME references/ directory (not from SKILL.md) should NOT
        be flagged as orphaned. (2026-05-23 widening — the 67% false-positive
        rate on real config came mostly from sibling-reference cases.)"""
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        _write_skill(
            skills_root, 'skill-a',
            refs={
                'data.md': '# the data file',
                'overview.md': 'For details see references/data.md.\n',
            },
        )

        orphaned, _ = sqa.validate_references()
        assert not any('data.md' in o for o in orphaned), \
            f"data.md flagged orphan despite sibling mention: {orphaned}"

    def test_external_script_mention_clears_orphan_flag(self, tmp_path, monkeypatch):
        """A reference file mentioned only from outside skills/ (scripts/,
        manifests/, rules/, agent-memory/) should NOT be flagged orphaned."""
        skills_root = str(tmp_path / 'skills')
        os.makedirs(skills_root)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        _write_skill(skills_root, 'probe-skill', refs={'probe.yaml': 'probe data'})
        # File outside skills/ that references probe.yaml
        scripts_dir = tmp_path / 'scripts'
        scripts_dir.mkdir()
        (scripts_dir / 'monitor.py').write_text(
            '# This consumes skills/probe-skill/references/probe.yaml\n',
            encoding='utf-8',
        )

        orphaned, _ = sqa.validate_references()
        assert not any('probe.yaml' in o for o in orphaned), \
            f"probe.yaml flagged orphan despite scripts/ mention: {orphaned}"

    def test_marketplace_mention_does_not_clear_orphan_flag(self, tmp_path, monkeypatch):
        """marketplace/ is a generated mirror — mentions there must NOT
        rescue a truly orphaned file from the orphan list."""
        skills_root = str(tmp_path / 'skills')
        os.makedirs(skills_root)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        _write_skill(skills_root, 'demo', refs={'lonely.md': 'only-in-marketplace'})
        # Pretend the marketplace mirror references the file. The walk
        # should skip marketplace/ entirely.
        mkt = tmp_path / 'marketplace' / 'skills' / 'demo'
        mkt.mkdir(parents=True)
        (mkt / 'SKILL.md').write_text(
            '---\nname: demo\n---\nReferences references/lonely.md.\n',
            encoding='utf-8',
        )

        orphaned, _ = sqa.validate_references()
        assert any('lonely.md' in o for o in orphaned), \
            "marketplace/ mention incorrectly rescued an orphan"


class TestMechanicalSkillsExemption:
    """Mechanical skills (ship, pr-fix, etc.) are exempt from C1/C2/X2 checks
    that assume verbose judgment-heavy descriptions."""

    def test_mechanical_skills_list_contents(self):
        # ship is in MECHANICAL_SKILLS
        assert 'ship' in sqa.MECHANICAL_SKILLS
        # manifest-gen is NOT — it's a judgment skill
        assert 'manifest-gen' not in sqa.MECHANICAL_SKILLS

    def test_mechanical_skills_set_is_nonempty(self):
        # Sanity — guard against accidental deletion of the exemption list
        assert len(sqa.MECHANICAL_SKILLS) >= 5

    def test_yaml_type_mechanical_classifies_as_mechanical(self):
        # New skill declaring `type: mechanical` is treated as mechanical
        # regardless of whether it's in the hardcoded fallback list.
        frontmatter = '\nname: brand-new\ntype: mechanical\ndescription: x\n'
        assert sqa._is_mechanical('brand-new', frontmatter) is True

    def test_yaml_type_judgment_does_not_classify_as_mechanical(self):
        frontmatter = '\nname: thoughtful\ntype: judgment\ndescription: x\n'
        assert sqa._is_mechanical('thoughtful', frontmatter) is False

    def test_yaml_type_absent_falls_back_to_hardcoded_set(self):
        frontmatter = '\nname: ship\ndescription: x\n'
        assert sqa._is_mechanical('ship', frontmatter) is True
        frontmatter2 = '\nname: manifest-gen\ndescription: x\n'
        assert sqa._is_mechanical('manifest-gen', frontmatter2) is False

    def test_yaml_type_quoted_value_is_recognized(self):
        frontmatter = '\nname: x\ntype: "mechanical"\ndescription: y\n'
        assert sqa._is_mechanical('x', frontmatter) is True


class TestDefaultBaseResolution:
    """When CLAUDE_CONFIG_DIR is unset the module must fall back to a real
    path (~/.claude expanded), not the literal string '$HOME/.claude'."""

    def test_base_is_not_a_literal_dollar_home(self):
        # The module-level constant must not start with a literal '$'.
        assert not sqa.base.startswith('$'), (
            f"sqa.base resolved to a literal shell variable: {sqa.base!r}"
        )


class TestC6SizeCheck:
    """C6 fails on the ~5000-word token-budget proxy, NOT on line count.
    The 500-line cap is advisory per Anthropic (rules/skill-standards.md):
    a long body ALONE no longer fails C6 — only an over-word body without
    a references/ rescue does."""

    def test_skill_over_500_lines_does_not_fail_c6(self, tmp_path, monkeypatch):
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        # 600 lines of short content — over the advisory line cap but well
        # under 5000 words. Lines are advisory now, so C6 must NOT fail on
        # line count alone. No references/ dir → proves it isn't a rescue.
        body = '\n'.join(f'line {i}' for i in range(600))
        _write_skill(skills_root, 'too-long', body=body)
        os.rmdir(os.path.join(skills_root, 'too-long', 'references'))
        # Need a skill-rules.json present for load_routing_rules.
        rules_dir = os.path.join(tmp_path, 'hooks')
        os.makedirs(rules_dir, exist_ok=True)
        with open(os.path.join(rules_dir, 'skill-rules.json'), 'w', encoding='utf-8') as f:
            f.write('{"rules": []}')
        monkeypatch.setattr(sqa, 'rules_path', os.path.join(rules_dir, 'skill-rules.json'))

        _, _, _, _, fails, meta = sqa.evaluate_skill('too-long', set())
        assert meta['lines'] > 500
        assert 'C6_size' not in fails

    def test_skill_over_word_cap_fails_c6_without_refs(self, tmp_path, monkeypatch):
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        # >5000 words with no references/ rescue → C6 must fail. Pins the
        # REAL cap (the token-budget proxy) so C6 is not left vacuous now
        # that the line cap is advisory.
        body = ' '.join(f'w{i}' for i in range(5001))
        _write_skill(skills_root, 'too-wordy', body=body)
        os.rmdir(os.path.join(skills_root, 'too-wordy', 'references'))
        rules_dir = os.path.join(tmp_path, 'hooks')
        os.makedirs(rules_dir, exist_ok=True)
        with open(os.path.join(rules_dir, 'skill-rules.json'), 'w', encoding='utf-8') as f:
            f.write('{"rules": []}')
        monkeypatch.setattr(sqa, 'rules_path', os.path.join(rules_dir, 'skill-rules.json'))

        _, _, _, _, fails, meta = sqa.evaluate_skill('too-wordy', set())
        assert meta['words'] > 5000
        assert 'C6_size' in fails

    def test_skill_under_500_lines_passes_c6(self, tmp_path, monkeypatch):
        skills_root = str(tmp_path)
        monkeypatch.setattr(sqa, 'skills_dir', skills_root)
        body = '\n'.join(f'line {i}' for i in range(50))
        _write_skill(skills_root, 'compact', body=body)
        rules_dir = os.path.join(tmp_path, 'hooks')
        os.makedirs(rules_dir, exist_ok=True)
        with open(os.path.join(rules_dir, 'skill-rules.json'), 'w', encoding='utf-8') as f:
            f.write('{"rules": []}')
        monkeypatch.setattr(sqa, 'rules_path', os.path.join(rules_dir, 'skill-rules.json'))

        _, _, _, _, fails, _ = sqa.evaluate_skill('compact', set())
        assert 'C6_size' not in fails


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
