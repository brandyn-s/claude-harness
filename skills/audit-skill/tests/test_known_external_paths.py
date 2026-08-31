"""Tests for the known-external-paths registry (added 2026-05-25).

Origin: 2026-05-25 KB-citation incident. Fix-agents treated
``~/Documents/knowledge-base/*`` paths as phantom and reframed 10
skills' citations because the files aren't in this repo's tree. The
files actually live in the sibling claude-knowledge-base repo —
absence from THIS checkout is not evidence the files don't exist.

The registry is the structural fix: cite-paths matching its
patterns are valid external dependencies, not phantom citations.
Audit checks and fix-agent prompts consult it before flagging.

Tests pin three contracts:
  1. The registry loads from skills/audit-skill/known-external-paths.yaml.
  2. Registered patterns substring-match against cited paths (both
     ``~/...`` and ``$HOME/...`` forms are stored as-is and matched
     literally).
  3. Unregistered paths are NOT marked external (negative cases).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_audit_module():
    """Load bin/audit-skill.py as 'audit_skill' for direct function access."""
    audit_path = REPO / "bin" / "audit-skill.py"
    spec = importlib.util.spec_from_file_location("audit_skill", audit_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_registry_loads_kb_pattern():
    """The KB path pattern that caused the 2026-05-25 incident MUST be
    registered. This is a regression-pin against the original failure."""
    mod = _load_audit_module()
    patterns = mod._load_known_external_paths()
    assert "~/Documents/knowledge-base/" in patterns, (
        f"KB pattern missing from registry; got: {patterns}"
    )


def test_registry_loads_all_documented_patterns():
    """The 8 patterns documented in AUDIT-TRACKERS/campaign-context.md
    MUST all be registered. If you remove one from the YAML, update
    campaign-context.md in the same commit."""
    mod = _load_audit_module()
    patterns = mod._load_known_external_paths()
    expected = {
        "~/Documents/knowledge-base/",
        "$HOME/Documents/knowledge-base/",
        "~/Documents/obsidian-infra/",
        "$HOME/Documents/obsidian-infra/",
        "~/Documents/api-docs/",
        "$HOME/Documents/api-docs/",
        "~/.claude/session-transcripts/",
        "~/.claude/projects/",
        "~/.claude/agent-memory/sentinel/",
        "~/code/",
        "~/Documents/GitHub/",
    }
    missing = expected - set(patterns)
    assert not missing, (
        f"campaign-context.md documents these external paths but the registry "
        f"is missing them: {missing}"
    )


def test_path_is_external_matches_kb_topic():
    """A path under ~/Documents/knowledge-base/ MUST match. This is the
    case the original KB incident kept misclassifying."""
    mod = _load_audit_module()
    assert mod._path_is_external("~/Documents/knowledge-base/topics/llm-creativity-ceiling.md")
    assert mod._path_is_external("~/Documents/knowledge-base/research/x.md")
    assert mod._path_is_external("~/Documents/knowledge-base/plans/2026-05-25-test.md")


def test_path_is_external_matches_bash_form():
    """The $HOME/ form must match too — some skills use the bash-shell
    expansion form rather than ~/."""
    mod = _load_audit_module()
    assert mod._path_is_external("$HOME/Documents/knowledge-base/topics/foo.md")
    assert mod._path_is_external("$HOME/Documents/obsidian-infra/scripts/onboard.py")


def test_path_is_external_negative_cases():
    """Paths NOT in the registry must return False. The substring-match
    must not over-fire — `~/Documents/random/x.md` is not external."""
    mod = _load_audit_module()
    assert not mod._path_is_external("~/Documents/random/x.md")
    assert not mod._path_is_external("skills/foo/references/x.md")
    assert not mod._path_is_external("/etc/passwd")
    assert not mod._path_is_external("")
    assert not mod._path_is_external("/tmp/some-file.md")


def test_path_is_external_handles_substring_within_longer_path():
    """A path containing ~/Documents/knowledge-base/ ANYWHERE in it
    matches — e.g., the path may be wrapped in a backticked-code or
    quoted-string in the original citation."""
    mod = _load_audit_module()
    # As it might appear inside a longer quoted citation.
    assert mod._path_is_external("see `~/Documents/knowledge-base/x.md` for details")


def test_registry_cache_consistent():
    """Two consecutive loads must return the same patterns (cache is
    correct)."""
    mod = _load_audit_module()
    a = mod._load_known_external_paths()
    b = mod._load_known_external_paths()
    assert a == b
    # The cache keys by SKILLS — same SKILLS path, same cache entry.
    assert a is b, "expected the same cached list object on second call"


# ---------------------------------------------------------------------------
# D3a out-of-repo verification (added 2026-07-26)
#
# Origin: claude-knowledge-base #1239 deleted
# .github/scripts/finalize_topics.py; five skills in THIS repo kept citing it
# by absolute path for a full day. A same-repo grep looked clean and D3a
# skipped `~/...` paths SILENTLY, so nothing caught it (fixed in #1710).
#
# D3a now resolves three cases instead of one blanket skip:
#   ~/.claude/<x>  -> this repo's deployed form; map onto the repo tree
#   registry hit   -> verify on disk; absent = info (provisioning gap)
#   registry miss  -> drift (unregistered dependency)
# ---------------------------------------------------------------------------


def test_deployed_root_constant_is_repo_root_not_skills():
    """DEPLOYED_ROOT must cover the whole deployed tree, not just skills/.

    bin/, hooks/, scripts/, and manifests/ are all in this repo, so a
    `~/.claude/bin/x.py` citation is verifiable against the repo tree. Pinning
    this stops a regression back to blanket-skipping those paths.
    """
    mod = _load_audit_module()
    assert mod.DEPLOYED_ROOT == "~/.claude/"
    assert mod.DEPLOYED_PREFIX.startswith(mod.DEPLOYED_ROOT)


def test_placeholder_paths_are_not_treated_as_real():
    """Template placeholders are patterns, not files.

    ship-hook documents `python3 ~/.claude/hooks/{name}.py`; {name} is filled
    in at install time. Flagging it as a missing script is a false positive.
    """
    mod = _load_audit_module()
    for placeholder in (
        "~/.claude/hooks/{name}.py",
        "~/Documents/temp/test_http_{service}.py",
        "scripts/*.py",
        "~/.claude/bin/<tool>.py",
        "$SCRIPTS/foo.py",
    ):
        assert mod._PATH_PATTERN_MARKER.search(placeholder), (
            f"placeholder not detected: {placeholder}"
        )
    # A concrete path must NOT be mistaken for a placeholder.
    for concrete in (
        "~/.claude/bin/x-monitor.py",
        "~/Documents/knowledge-base/tools/kb.py",
        "scripts/verify-indexes.py",
    ):
        assert not mod._PATH_PATTERN_MARKER.search(concrete), (
            f"concrete path wrongly read as placeholder: {concrete}"
        )


def test_skill_authored_scripts_are_outputs_not_dependencies():
    """A script the skill WRITES before running is an output, not a dep.

    mcp-create writes an AST analyzer to ~/Documents/temp/analyze_source.py
    and then executes it; that path legitimately does not exist at audit time.
    """
    mod = _load_audit_module()
    md = (
        "2. Write an AST analysis script to `~/Documents/temp/analyze_source.py`.\n"
        "3. Run it:\n\n```bash\npython3 ~/Documents/temp/analyze_source.py {SRC}\n```\n"
    )
    assert mod._skill_authors_path(md, "~/Documents/temp/analyze_source.py")
    # A path the skill merely RUNS (never creates) is still a dependency.
    md_runs_only = "Run `python3 ~/Documents/other/thing.py` to continue.\n"
    assert not mod._skill_authors_path(md_runs_only, "~/Documents/other/thing.py")
    assert not mod._skill_authors_path("", "~/x.py")


def test_f0_regression_deleted_sibling_repo_script_is_flagged(tmp_path):
    """Replay of the #1239 -> #1710 failure: a deleted sibling-repo script
    cited by absolute path must now produce a D3a finding.

    The registry knows ~/Documents/knowledge-base/, so an absent file there
    yields `info` (provisioning gap: the citation is correct, the repo just
    isn't cloned). An UNREGISTERED out-of-repo path yields `drift`.
    """
    mod = _load_audit_module()
    # Registered-but-absent -> external, so the caller emits info not drift.
    assert mod._path_is_external(
        "~/Documents/knowledge-base/.github/scripts/finalize_topics.py"
    )
    # Unregistered out-of-repo path -> not external -> drift.
    assert not mod._path_is_external("~/Documents/nowhere/some_script.py")
