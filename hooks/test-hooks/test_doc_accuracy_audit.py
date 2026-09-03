"""Tests for doc_accuracy_audit.py: project auto-discovery + orphan scan.

The 2026-05-23 fixes:
  1. CLAUDE_CONFIG_DIR fallback no longer leaks the literal string '$HOME/.claude'.
  2. Project subdirectory is auto-discovered (was hardcoded placeholder).
  3. Hook orphan scan uses an inverted index (was O(candidates * dirs * files)).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', '..', 'skills',
    'audit-architecture', 'references'
))
import doc_accuracy_audit as daa  # noqa: E402


def _make_fake_base(tmp_path):
    """Lay out a minimal ~/.claude tree under tmp_path."""
    base = tmp_path / 'claude'
    (base / 'skills' / 'demo').mkdir(parents=True)
    (base / 'skills' / 'demo' / 'SKILL.md').write_text(
        '---\nname: demo\ndescription: x\n---\nbody\n', encoding='utf-8'
    )
    (base / 'agents').mkdir()
    (base / 'agents' / 'sample.md').write_text('agent', encoding='utf-8')
    (base / 'agent-memory' / 'topics').mkdir(parents=True)
    (base / 'rules').mkdir()
    (base / 'rules' / 'demo.md').write_text('rule', encoding='utf-8')
    (base / 'hooks').mkdir()
    (base / 'hooks' / 'test-hooks').mkdir()
    (base / 'settings.json').write_text('{"hooks": {}}', encoding='utf-8')
    (base / 'ARCHITECTURE.md').write_text('# arch\n', encoding='utf-8')
    return base


def _set_home_claude_json(tmp_path, monkeypatch):
    """Point ~/.claude.json at a temp file under tmp_path."""
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.setattr(os.path, 'expanduser',
                        lambda p: p.replace('~', str(fake_home)))
    (fake_home / '.claude.json').write_text(
        '{"mcpServers": {}, "projects": {}}', encoding='utf-8'
    )


class TestBaseResolution:
    def test_base_is_not_literal_dollar_home(self):
        # Module-level constant must resolve to a real path on import.
        assert not daa.base.startswith('$'), (
            f"daa.base resolved to a literal shell variable: {daa.base!r}"
        )


class TestProjectDiscovery:
    def test_returns_none_when_projects_dir_missing(self, tmp_path, monkeypatch):
        # Pin BOTH roots: without pinning deployed_base, the #2054
        # deployed-tree fallback makes the result depend on whether THIS
        # HOST has a deployed ~/.claude/projects (failed locally / passed
        # on CI runners, 2026-08-22).
        monkeypatch.setattr(daa, 'base', str(tmp_path))
        monkeypatch.setattr(daa, 'deployed_base', str(tmp_path / 'no-deploy'))
        assert daa.discover_project_dir() is None

    def test_returns_none_when_no_project_has_claude_md(self, tmp_path, monkeypatch):
        (tmp_path / 'projects' / 'empty-proj').mkdir(parents=True)
        monkeypatch.setattr(daa, 'base', str(tmp_path))
        monkeypatch.setattr(daa, 'deployed_base', str(tmp_path / 'no-deploy'))
        assert daa.discover_project_dir() is None

    def test_falls_back_to_deployed_projects_root(self, tmp_path, monkeypatch):
        # Positive control for the #2054 fallback: base is a worktree with
        # no projects/, the deployed tree has one — discovery must return
        # the deployed project, not None.
        worktree = tmp_path / 'worktree'
        worktree.mkdir()
        deployed = tmp_path / 'deployed'
        proj = deployed / 'projects' / '-Users-someone'
        proj.mkdir(parents=True)
        (proj / 'CLAUDE.md').write_text('# project', encoding='utf-8')
        monkeypatch.setattr(daa, 'base', str(worktree))
        monkeypatch.setattr(daa, 'deployed_base', str(deployed))
        assert daa.discover_project_dir() == str(proj)

    def test_fallback_not_taken_when_base_projects_exists(self, tmp_path, monkeypatch):
        # base/projects wins even when a deployed root also exists.
        base_proj = tmp_path / 'base' / 'projects' / 'local-proj'
        base_proj.mkdir(parents=True)
        (base_proj / 'CLAUDE.md').write_text('# local', encoding='utf-8')
        deployed_proj = tmp_path / 'deployed' / 'projects' / 'deployed-proj'
        deployed_proj.mkdir(parents=True)
        (deployed_proj / 'CLAUDE.md').write_text('# deployed', encoding='utf-8')
        monkeypatch.setattr(daa, 'base', str(tmp_path / 'base'))
        monkeypatch.setattr(daa, 'deployed_base', str(tmp_path / 'deployed'))
        assert daa.discover_project_dir() == str(base_proj)

    def test_picks_project_with_claude_md(self, tmp_path, monkeypatch):
        proj = tmp_path / 'projects' / 'C--Users-someone'
        proj.mkdir(parents=True)
        (proj / 'CLAUDE.md').write_text('# project', encoding='utf-8')
        monkeypatch.setattr(daa, 'base', str(tmp_path))
        assert daa.discover_project_dir() == str(proj)

    def test_picks_most_recently_modified_when_multiple(self, tmp_path, monkeypatch):
        import time
        older = tmp_path / 'projects' / 'older'
        newer = tmp_path / 'projects' / 'newer'
        older.mkdir(parents=True)
        newer.mkdir(parents=True)
        (older / 'CLAUDE.md').write_text('old', encoding='utf-8')
        (newer / 'CLAUDE.md').write_text('new', encoding='utf-8')
        # Stamp older with an earlier mtime.
        old_time = time.time() - 3600
        os.utime(str(older), (old_time, old_time))
        monkeypatch.setattr(daa, 'base', str(tmp_path))
        assert daa.discover_project_dir() == str(newer)


class TestAuditClaudeMdGracefulMissing:
    def test_returns_empty_when_no_project_dir(self):
        # state['project_dir'] is None — function must return [] without error
        state = {'project_dir': None, 'skills': []}
        assert daa.audit_claude_md(state) == []

    def test_returns_empty_when_project_dir_has_no_claude_md(self, tmp_path):
        state = {'project_dir': str(tmp_path), 'skills': []}
        assert daa.audit_claude_md(state) == []


class TestAuditMemoryMdGracefulMissing:
    def test_returns_empty_when_no_project_dir(self):
        findings, lines, links = daa.audit_memory_md(None)
        assert findings == []
        assert lines == 0
        assert links == 0

    def test_returns_empty_when_memory_dir_missing(self, tmp_path):
        findings, lines, links = daa.audit_memory_md(str(tmp_path))
        assert findings == []
        assert lines == 0
        assert links == 0


class TestOrphanHookScan:
    """The inverted-index rewrite must produce the same results as before:
    a hook referenced anywhere (test, skill, manifest, other hook) is NOT
    orphaned; a hook referenced nowhere IS orphaned."""

    def _build_minimal_state_and_scan(self, tmp_path, monkeypatch):
        base = _make_fake_base(tmp_path)
        _set_home_claude_json(tmp_path, monkeypatch)
        monkeypatch.setattr(daa, 'base', str(base))
        return daa.load_actual_state()

    def test_hook_referenced_in_skill_is_not_orphan(self, tmp_path, monkeypatch):
        base = _make_fake_base(tmp_path)
        # Add a hook file
        (base / 'hooks' / 'my_hook.py').write_text('# hook', encoding='utf-8')
        # Reference it from a skill
        (base / 'skills' / 'demo' / 'SKILL.md').write_text(
            '---\nname: demo\ndescription: x\n---\nUses my_hook.py for X.\n',
            encoding='utf-8',
        )
        _set_home_claude_json(tmp_path, monkeypatch)
        monkeypatch.setattr(daa, 'base', str(base))
        state = daa.load_actual_state()
        assert 'my_hook.py' not in state['orphan_hooks']

    def test_hook_referenced_by_stem_only_is_not_orphan(self, tmp_path, monkeypatch):
        base = _make_fake_base(tmp_path)
        (base / 'hooks' / 'cool_check.py').write_text('# hook', encoding='utf-8')
        # Reference by stem only (no .py extension)
        (base / 'skills' / 'demo' / 'SKILL.md').write_text(
            '---\nname: demo\ndescription: x\n---\nThe cool_check module helps.\n',
            encoding='utf-8',
        )
        _set_home_claude_json(tmp_path, monkeypatch)
        monkeypatch.setattr(daa, 'base', str(base))
        state = daa.load_actual_state()
        assert 'cool_check.py' not in state['orphan_hooks']

    def test_truly_orphaned_hook_is_flagged(self, tmp_path, monkeypatch):
        base = _make_fake_base(tmp_path)
        (base / 'hooks' / 'truly_orphan.py').write_text('# unused', encoding='utf-8')
        _set_home_claude_json(tmp_path, monkeypatch)
        monkeypatch.setattr(daa, 'base', str(base))
        state = daa.load_actual_state()
        assert 'truly_orphan.py' in state['orphan_hooks']

    def test_hook_helpers_are_never_flagged(self, tmp_path, monkeypatch):
        base = _make_fake_base(tmp_path)
        (base / 'hooks' / 'atomic_write.py').write_text('# helper', encoding='utf-8')
        _set_home_claude_json(tmp_path, monkeypatch)
        monkeypatch.setattr(daa, 'base', str(base))
        state = daa.load_actual_state()
        assert 'atomic_write.py' not in state['orphan_hooks']

    def test_hook_self_reference_does_not_clear_orphan_flag(self, tmp_path, monkeypatch):
        """A hook whose only mention is its own filename inside its own file
        must still be flagged as orphan."""
        base = _make_fake_base(tmp_path)
        (base / 'hooks' / 'lonely.py').write_text(
            '# this is lonely.py and nobody else mentions it\n',
            encoding='utf-8',
        )
        _set_home_claude_json(tmp_path, monkeypatch)
        monkeypatch.setattr(daa, 'base', str(base))
        state = daa.load_actual_state()
        assert 'lonely.py' in state['orphan_hooks']


class TestMainSmoke:
    """A full main() run on a minimal fixture should exit cleanly with valid
    JSON on stdout — this catches the kind of bug B1/B2 introduced."""

    def test_main_runs_without_crashing_on_minimal_tree(self, tmp_path, monkeypatch, capsys):
        base = _make_fake_base(tmp_path)
        _set_home_claude_json(tmp_path, monkeypatch)
        monkeypatch.setattr(daa, 'base', str(base))
        # Should exit cleanly (return 0 or 1, never raise)
        exit_code = daa.main()
        assert exit_code in (0, 1)
        captured = capsys.readouterr()
        # stdout is JSON
        parsed = json.loads(captured.out)
        assert 'architecture_md' in parsed
        assert 'claude_md' in parsed
        assert 'memory_md' in parsed


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
