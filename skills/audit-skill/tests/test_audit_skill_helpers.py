"""Unit tests for audit-skill helpers.

Targets the helpers that compose bin/audit-skill.py: parsing,
classification, suppression matching, tool-reference detection,
and the known-tools registry loader. These prevent regressions
in the small pure functions that the larger checks depend on
(e.g., a broken regex pattern in known_real silently lets
phantom tools through under --strict-tools).
"""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPO / "bin" / "audit-skill.py"


def _load_audit_module():
    """Import bin/audit-skill.py as a module (the file has no .py
    extension on PATH but is a Python file)."""
    if "audit_skill" in sys.modules:
        return sys.modules["audit_skill"]
    spec = importlib.util.spec_from_file_location("audit_skill", AUDIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["audit_skill"] = mod
    return mod


def test_find_tool_references_matches_basic_form():
    audit = _load_audit_module()
    text = "Call `mcp__exa__web_search_exa` then `mcp__github__create_pull_request`."
    found = [name for _ln, name in audit._find_tool_references(text)]
    assert "mcp__exa__web_search_exa" in found
    assert "mcp__github__create_pull_request" in found


def test_find_tool_references_matches_hyphenated_server():
    """Servers like context7-docs use hyphens — must still match."""
    audit = _load_audit_module()
    text = "Use `mcp__context7-docs__query-docs` for library lookups."
    found = [name for _ln, name in audit._find_tool_references(text)]
    assert "mcp__context7-docs__query-docs" in found


def test_find_tool_references_matches_uuid_server():
    """UUID-namespaced servers (Linear, Slack variants) — must match too."""
    audit = _load_audit_module()
    text = "Save via mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__save_status_update."
    found = [name for _ln, name in audit._find_tool_references(text)]
    assert any("93acadff" in n for n in found), f"got {found}"


def test_find_tool_references_returns_line_numbers():
    audit = _load_audit_module()
    text = "line 1\nline 2 has mcp__exa__web_search_exa\nline 3"
    pairs = list(audit._find_tool_references(text))
    assert len(pairs) == 1
    line_no, name = pairs[0]
    assert line_no == 2
    assert name == "mcp__exa__web_search_exa"


def test_tool_is_known_real_literal_match():
    audit = _load_audit_module()
    reals = [("literal", "mcp__exa__web_search_exa")]
    assert audit._tool_is_known_real("mcp__exa__web_search_exa", reals)
    assert not audit._tool_is_known_real("mcp__exa__different_tool", reals)


def test_tool_is_known_real_glob_match():
    audit = _load_audit_module()
    reals = [("glob", "mcp__github__*")]
    assert audit._tool_is_known_real("mcp__github__create_pull_request", reals)
    assert audit._tool_is_known_real("mcp__github__list_branches", reals)
    assert not audit._tool_is_known_real("mcp__exa__web_search_exa", reals)


def test_tool_is_known_real_regex_match_uuid_pattern():
    """Regression: the UUID-pattern entry in known-tools.yaml previously
    used `__*` (regex = zero-or-more underscores) which never matched
    real tool names like `__save_status_update`. After the fix it uses
    `__.*` (any suffix) and must accept full UUID-namespaced tool names."""
    audit = _load_audit_module()
    pat = (r"mcp__[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
           r"[0-9a-f]{4}-[0-9a-f]{12}__.*")
    reals = [("regex", pat)]
    assert audit._tool_is_known_real(
        "mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__save_status_update", reals
    )
    assert audit._tool_is_known_real(
        "mcp__036e0c74-1e0e-4bce-ad71-2a678d79b204__slack_send_message", reals
    )
    assert not audit._tool_is_known_real("mcp__exa__web_search_exa", reals)
    # The pre-fix pattern (`__*`) MUST NOT match — protects against a
    # future maintainer reverting the fix.
    bad_pat = (r"mcp__[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
               r"[0-9a-f]{4}-[0-9a-f]{12}__*")
    assert not audit._tool_is_known_real(
        "mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__save_status_update",
        [("regex", bad_pat)]
    ), "the pre-fix `__*` pattern should never match a real tool name"


def test_load_known_tools_parses_registry():
    """Smoke-test against the canonical skills/audit-skill/known-tools.yaml.
    Must surface both known_phantom and known_real entries."""
    audit = _load_audit_module()
    audit._KNOWN_TOOLS_CACHE = {}  # bust the module-level cache
    try:
        phantoms, reals = audit._load_known_tools()
    finally:
        audit._KNOWN_TOOLS_CACHE = {}
    assert "mcp__code-graph__index_status" in phantoms
    assert "mcp__code-search__index_status" in phantoms
    # At least one literal mcp__github__ entry or its glob umbrella
    has_github = any(
        (kind == "literal" and val.startswith("mcp__github__"))
        or (kind == "glob" and val == "mcp__github__*")
        for kind, val in reals
    )
    assert has_github, f"expected GitHub MCP coverage in known_real; got {reals[:5]}..."


def test_load_suppressions_parses_yaml_subset(tmp_path):
    audit = _load_audit_module()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: M2\n"
        "    target: mcp__exa__*\n"
        "    reason: invoked via dispatched agent\n"
        "  - code: T1\n"
        "    target: mcp__legacy__tool\n"
        "    reason: kept for historical reference\n",
        encoding="utf-8",
    )
    out = audit._load_suppressions(skill_dir)
    assert len(out) == 2
    assert out[0]["code"] == "M2"
    assert out[0]["target"] == "mcp__exa__*"
    assert out[1]["code"] == "T1"


def test_suppressed_handles_glob_targets():
    audit = _load_audit_module()
    suppressions = [
        {"code": "M2", "target": "mcp__exa__*", "reason": "delegated"},
    ]
    assert audit._suppressed(suppressions, "M2", target="mcp__exa__web_search_exa")
    assert audit._suppressed(suppressions, "M2", target="mcp__exa__anything")
    assert not audit._suppressed(suppressions, "M2", target="mcp__tavily__search")
    assert not audit._suppressed(suppressions, "M1", target="mcp__exa__web_search_exa")


def test_suppressed_code_only_match():
    audit = _load_audit_module()
    suppressions = [{"code": "D3c", "reason": "ci helper"}]
    assert audit._suppressed(suppressions, "D3c", target=None)
    assert audit._suppressed(suppressions, "D3c", target="scripts/x.py")
    assert not audit._suppressed(suppressions, "D3a", target="scripts/x.py")


def test_load_suppressions_rejects_unknown_keys(tmp_path):
    """A typo like `target_pattern:` instead of `target:` previously
    silently parsed into an entry that suppressed nothing. The loader
    now surfaces unknown keys as warnings and drops the bad entry."""
    audit = _load_audit_module()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: M2\n"
        "    target_pattern: mcp__bad__typo\n"  # WRONG key name
        "    reason: typo\n"
        "  - code: M2\n"
        "    target: mcp__good__valid\n"
        "    reason: real one\n",
        encoding="utf-8",
    )
    errors = []
    out = audit._load_suppressions(skill_dir,
                                    on_invalid=lambda ln, msg: errors.append((ln, msg)))
    # The good one must come through; the typo one must NOT.
    targets = [s.get("target") for s in out]
    assert "mcp__good__valid" in targets
    assert "mcp__bad__typo" not in targets
    assert errors, "unknown-key typo must surface as a warning"
    assert any("target_pattern" in msg for _ln, msg in errors)


def test_load_suppressions_requires_code_and_reason(tmp_path):
    """A suppression without a `reason:` is meaningless — every entry
    should explain itself."""
    audit = _load_audit_module()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: M2\n"
        "    target: mcp__missing_reason\n"
        "  - code: M2\n"
        "    target: mcp__has_reason\n"
        "    reason: documented\n",
        encoding="utf-8",
    )
    errors = []
    out = audit._load_suppressions(skill_dir,
                                    on_invalid=lambda ln, msg: errors.append((ln, msg)))
    targets = [s.get("target") for s in out]
    assert "mcp__has_reason" in targets
    assert "mcp__missing_reason" not in targets, (
        "entries without `reason:` must be rejected to enforce documentation"
    )
    assert any("reason" in msg for _ln, msg in errors)


def test_split_frontmatter_separates_header_and_body():
    audit = _load_audit_module()
    md = "---\nname: foo\nallowed-tools: Read\n---\n# Body\nProse here.\n"
    fm, body = audit._split_frontmatter(md)
    assert "name: foo" in fm
    assert "Body" in body
    assert "---" not in body  # closing fence stripped


def test_split_frontmatter_empty_when_no_header():
    audit = _load_audit_module()
    fm, body = audit._split_frontmatter("# No frontmatter\n")
    assert fm == ""
    assert body.startswith("# No frontmatter")


def test_normalize_path_strips_quotes_and_expands_home():
    audit = _load_audit_module()
    assert audit._normalize_path("'~/foo.py'") == "~/foo.py"
    assert audit._normalize_path('"$HOME/bar.py"') == "~/bar.py"
    assert audit._normalize_path("${HOME}/baz.py") == "~/baz.py"


def test_normalize_path_skips_template_placeholders():
    audit = _load_audit_module()
    assert audit._normalize_path("<your-path>") is None
    assert audit._normalize_path("`<placeholder>/script.py`") is None


def test_iter_bash_blocks_only_yields_bash_fences():
    audit = _load_audit_module()
    md = (
        "Prose.\n"
        "```python\n"
        "print('not bash')\n"
        "```\n"
        "More prose.\n"
        "```bash\n"
        "echo 'is bash'\n"
        "```\n"
    )
    blocks = list(audit._iter_bash_blocks(md))
    assert len(blocks) == 1
    _vars, lines = blocks[0]
    assert any("echo 'is bash'" in cmd for _ln, cmd in lines)
    assert not any("print" in cmd for _ln, cmd in lines)


def test_iter_bash_blocks_handles_back_to_back_blocks():
    audit = _load_audit_module()
    md = (
        "```bash\n"
        "echo first\n"
        "```\n"
        "```sh\n"
        "echo second\n"
        "```\n"
    )
    blocks = list(audit._iter_bash_blocks(md))
    assert len(blocks) == 2


def test_iter_bash_blocks_joins_line_continuations():
    """A backslash-continued bash command must be presented as a single
    logical line so downstream D3a / C2 checks see the full command."""
    audit = _load_audit_module()
    md = (
        "```bash\n"
        "python scripts/foo.py \\\n"
        "  --input data.json \\\n"
        "  --output /tmp/out.json\n"
        "```\n"
    )
    blocks = list(audit._iter_bash_blocks(md))
    assert len(blocks) == 1
    _vars, lines = blocks[0]
    assert len(lines) == 1
    line_no, cmd = lines[0]
    assert "scripts/foo.py" in cmd
    assert "--input data.json" in cmd
    assert "/tmp/out.json" in cmd


def test_find_cross_skill_citations_matches_simple_form():
    audit = _load_audit_module()
    text = "See `supergoal/references/plan-pattern-library.md` for details."
    refs = list(audit.find_cross_skill_citations(text))
    assert refs == [(1, "supergoal", "plan-pattern-library.md")]


def test_find_cross_skill_citations_skips_middle_of_hyphenated_name():
    """The lookbehind must exclude `-` so the regex doesn't match the
    `memory-exploring/references/...` substring inside the longer
    `codebase-memory-exploring/references/...` path. This was an H4
    false-positive on the first version of the check."""
    audit = _load_audit_module()
    text = ("See ~/.claude/skills/codebase-memory-exploring/references/"
            "code-graph-reference.md")
    refs = list(audit.find_cross_skill_citations(text))
    # Should match the full skill name once, not the suffix.
    skill_names = [s for _ln, s, _r in refs]
    assert "codebase-memory-exploring" in skill_names
    assert "memory-exploring" not in skill_names
    assert "exploring" not in skill_names


def test_find_cross_skill_citations_strips_skills_prefix():
    audit = _load_audit_module()
    text = "Path: ~/.claude/skills/persona/references/discovery-mode.md"
    refs = list(audit.find_cross_skill_citations(text))
    # Should match exactly one and the skill name should be `persona`.
    assert (1, "persona", "discovery-mode.md") in refs


def test_find_reference_citations_skips_fenced_code_blocks():
    """A citation inside a ```yaml or ```bash fenced block is an example,
    not a real Read target. The audit-skill SKILL.md has a YAML example
    showing how to write audit-suppress.yaml — it cites
    `references/search-waves.md` as a sample value. H1 must not fire on
    that. Regression guard for the bug found while expanding H1."""
    audit = _load_audit_module()
    text = (
        "Real citation: see `references/real.md`.\n"
        "```yaml\n"
        "example:\n"
        "  reason: invoked via references/example.md\n"
        "```\n"
        "Another real one: `references/also-real.md`\n"
    )
    refs = [name for _ln, name in audit.find_reference_citations(text)]
    assert "real.md" in refs
    assert "also-real.md" in refs
    assert "example.md" not in refs, "fenced block citations must be skipped"


def test_find_doc_citations_requires_read_verb():
    """H5: a backtick-wrapped `<dir>/<file>.md` citation only counts
    when prose says it's something to Read. Without a read-verb the
    same syntax is used for output paths and illustrations."""
    audit = _load_audit_module()
    text = (
        "See `oracle/SPEC.md` for the semantics.\n"
        "Write to `out/REPORT.md` when done.\n"
        "The example `topics/security.md` was less relevant.\n"
        "Read `docs/threat-model.md` for the diagnosis.\n"
    )
    cites = [c for _ln, c in audit.find_doc_citations(text)]
    assert "oracle/SPEC.md" in cites
    assert "docs/threat-model.md" in cites
    assert "out/REPORT.md" not in cites
    assert "topics/security.md" not in cites


def test_find_doc_citations_lookback_across_wrapped_lines():
    r"""H5: the read-verb gate scans up to 2 preceding non-blank lines
    so a wrapped citation like `See \n... and \`X\` for Y` still fires."""
    audit = _load_audit_module()
    text = (
        "See `references/foo.md` for X\n"
        "guidance and `oracle/SPEC.md` for the verdict semantics.\n"
        "\n"
        "Unrelated paragraph mentioning `out/REPORT.md` with no verb.\n"
    )
    cites = [c for _ln, c in audit.find_doc_citations(text)]
    assert "oracle/SPEC.md" in cites
    assert "out/REPORT.md" not in cites


def test_find_doc_citations_skips_h1_and_h4_territory():
    """H5 stays out of the way of H1 (bare references/) and H4
    (<skill>/references/) so the same finding isn't double-reported."""
    audit = _load_audit_module()
    text = (
        "See `references/foo.md` (this is H1).\n"
        "See `persona/references/bar.md` (this is H4).\n"
        "See `oracle/SPEC.md` (this is H5).\n"
    )
    cites = [c for _ln, c in audit.find_doc_citations(text)]
    assert cites == ["oracle/SPEC.md"]


def test_find_doc_citations_skips_fenced_blocks():
    """Same fence-skip discipline as H1/H4 — examples inside code
    fences are not citations."""
    audit = _load_audit_module()
    text = (
        "Read `real/citation.md` for X.\n"
        "```bash\n"
        "echo 'See fake/example.md'\n"
        "```\n"
    )
    cites = [c for _ln, c in audit.find_doc_citations(text)]
    assert "real/citation.md" in cites
    assert "fake/example.md" not in cites


def test_parse_manifest_required_tools_block_form():
    """Block-list YAML — multi-line `- entry`."""
    audit = _load_audit_module()
    text = (
        "requires_tools:\n"
        "  - Bash\n"
        "  - Read\n"
        '  - "mcp__foo__*"\n'
        "  - 'Write'  # quoted with comment\n"
        "requires_topics: []\n"
    )
    tools = audit._parse_manifest_required_tools(text)
    assert tools == {"Bash", "Read", "mcp__foo__*", "Write"}


def test_parse_manifest_required_tools_inline_form():
    """Flow-style YAML — `[a, b, c]` on one line."""
    audit = _load_audit_module()
    text = 'requires_tools: [Bash, "Read", \'Write\']\n'
    tools = audit._parse_manifest_required_tools(text)
    assert tools == {"Bash", "Read", "Write"}


def test_parse_manifest_required_tools_empty_list():
    """`requires_tools: []` returns set(), not a parse error."""
    audit = _load_audit_module()
    assert audit._parse_manifest_required_tools("requires_tools: []\n") == set()
    assert audit._parse_manifest_required_tools(
        "requires_tools:\nother_key: foo\n"
    ) == set()


def test_diff_modulo_wildcards_literal_membership():
    """A literal is covered iff the other side contains it literally."""
    audit = _load_audit_module()
    assert audit._diff_modulo_wildcards({"Bash"}, {"Bash", "Read"}) == set()
    assert audit._diff_modulo_wildcards({"Glob"}, {"Bash", "Read"}) == {"Glob"}


def test_diff_modulo_wildcards_wildcard_in_left_matches_literal_in_right():
    """`mcp__foo__*` in left is covered by `mcp__foo__bar` in right."""
    audit = _load_audit_module()
    out = audit._diff_modulo_wildcards(
        {"mcp__foo__*"}, {"mcp__foo__bar"}
    )
    assert out == set()


def test_diff_modulo_wildcards_wildcard_in_right_covers_literal_in_left():
    """`mcp__foo__bar` in left is covered by `mcp__foo__*` in right."""
    audit = _load_audit_module()
    out = audit._diff_modulo_wildcards(
        {"mcp__foo__bar"}, {"mcp__foo__*"}
    )
    assert out == set()


def test_diff_modulo_wildcards_uncovered_wildcard():
    """A wildcard with no matching literal/wildcard on the other side
    surfaces in the diff."""
    audit = _load_audit_module()
    assert audit._diff_modulo_wildcards(
        {"mcp__tavily__*"}, {"Bash"}
    ) == {"mcp__tavily__*"}


def test_find_cross_skill_citations_skips_fenced_blocks():
    """Same fence-skip rule for cross-skill citations."""
    audit = _load_audit_module()
    text = (
        "Real: see `supergoal/references/foo.md`\n"
        "```bash\n"
        "echo 'example: persona/references/bar.md'\n"
        "```\n"
    )
    refs = [(s, r) for _ln, s, r in audit.find_cross_skill_citations(text)]
    assert ("supergoal", "foo.md") in refs
    assert ("persona", "bar.md") not in refs


def test_audit_systemic_b1_fires_on_scripts_without_tests(tmp_path):
    """B1 — skill with scripts/*.py but no tests/ must surface as info."""
    audit = _load_audit_module()
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test. Use when X. Do NOT use for Y.\n"
        "argument-hint: \"<arg>\"\nallowed-tools: Read\n---\n# Body\n",
        encoding="utf-8")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("# script\n", encoding="utf-8")
    findings = audit._audit_systemic_patterns(skill_dir, skill_dir / "SKILL.md",
                                               (skill_dir / "SKILL.md").read_text())
    codes = [f.code for f in findings]
    assert "B1" in codes


def test_audit_systemic_b1_silent_when_tests_dir_exists(tmp_path):
    audit = _load_audit_module()
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test. Use when X. Do NOT use for Y.\nallowed-tools: Read\n---\n# Body\n",
        encoding="utf-8")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("# script\n", encoding="utf-8")
    (skill_dir / "tests").mkdir()
    findings = audit._audit_systemic_patterns(skill_dir, skill_dir / "SKILL.md",
                                               (skill_dir / "SKILL.md").read_text())
    codes = [f.code for f in findings]
    assert "B1" not in codes


def test_audit_systemic_p1_fires_on_baseDir_placeholder(tmp_path):
    audit = _load_audit_module()
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test. Use when X. Do NOT use for Y.\nallowed-tools: Read\n---\n"
        "# Body\nSee [link]({baseDir}/references/foo.md).\n",
        encoding="utf-8")
    findings = audit._audit_systemic_patterns(skill_dir, skill_dir / "SKILL.md",
                                               (skill_dir / "SKILL.md").read_text())
    codes = [f.code for f in findings]
    assert "P1" in codes


def test_audit_systemic_p1_fires_on_your_X_placeholder(tmp_path):
    """`<your-claude-project>` was the historical bug pattern. P1 must fire."""
    audit = _load_audit_module()
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test. Use when X. Do NOT use for Y.\nallowed-tools: Read\n---\n"
        "# Body\nRead `~/.claude/projects/<your-claude-project>/CLAUDE.md`\n",
        encoding="utf-8")
    findings = audit._audit_systemic_patterns(skill_dir, skill_dir / "SKILL.md",
                                               (skill_dir / "SKILL.md").read_text())
    codes = [f.code for f in findings]
    assert "P1" in codes


def test_audit_systemic_q2_fires_on_long_description(tmp_path):
    audit = _load_audit_module()
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    long_desc = "Use when X. Do NOT use for Y. " + ("padding " * 200)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: test-skill\ndescription: {long_desc}\nallowed-tools: Read\n---\n# Body\n",
        encoding="utf-8")
    findings = audit._audit_systemic_patterns(skill_dir, skill_dir / "SKILL.md",
                                               (skill_dir / "SKILL.md").read_text())
    codes = [f.code for f in findings]
    assert "Q2" in codes


def test_audit_systemic_q3_fires_on_incomplete_description(tmp_path):
    """Description missing 'Do NOT use for' must trigger Q3."""
    audit = _load_audit_module()
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: A skill that does X. Use when needed.\nallowed-tools: Read\n---\n# Body\n",
        encoding="utf-8")
    findings = audit._audit_systemic_patterns(skill_dir, skill_dir / "SKILL.md",
                                               (skill_dir / "SKILL.md").read_text())
    codes = [f.code for f in findings]
    assert "Q3" in codes


def test_audit_systemic_q3_silent_when_description_is_complete(tmp_path):
    audit = _load_audit_module()
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\n"
        "description: A skill that does X. Use when Y is true. Do NOT use for Z.\n"
        "allowed-tools: Read\n---\n# Body\n",
        encoding="utf-8")
    findings = audit._audit_systemic_patterns(skill_dir, skill_dir / "SKILL.md",
                                               (skill_dir / "SKILL.md").read_text())
    codes = [f.code for f in findings]
    assert "Q3" not in codes


# ----- Phase 2 / SKILL.md alignment guard ----------------------------------

def test_every_cli_flag_is_exercised_in_tests():
    """Every flag advertised in main() must appear somewhere in the
    test corpus. Catches "shipped but never run" code paths — the
    pattern that hid the UUID-regex bug behind --strict-tools for
    months."""
    import re
    audit_py = AUDIT_SCRIPT.read_text(encoding="utf-8")
    # Extract flag names from the `if f == "--xxx":` parser pattern.
    flag_pat = re.compile(r'f == "(--[a-z\-]+)"')
    flags = set(flag_pat.findall(audit_py))
    assert flags, "no CLI flags discovered — has main() been refactored?"

    tests_dir = Path(__file__).resolve().parent
    test_content = ""
    for tf in tests_dir.rglob("test_*.py"):
        test_content += tf.read_text(errors="ignore")
    # Also count the validate.yml workflow + the SKILL.md as legitimate
    # exercise sites — a flag run in CI is exercised even without a
    # python test.
    workflow_file = REPO / ".github" / "workflows" / "validate.yml"
    if workflow_file.is_file():
        test_content += workflow_file.read_text(errors="ignore")
    skill_md = REPO / "skills" / "audit-skill" / "SKILL.md"
    if skill_md.is_file():
        test_content += skill_md.read_text(errors="ignore")

    missing = sorted(f for f in flags if f not in test_content)
    assert not missing, (
        f"CLI flags exist in audit-skill.py main() but are not exercised "
        f"in tests, CI, or documented in SKILL.md: {missing}. Either add a "
        f"test that runs the flag, wire it into .github/workflows/validate.yml, "
        f"or remove it from main()."
    )


def test_skill_md_enforces_all_phases_as_mandatory():
    """`/audit-skill` must run all THREE phases every time:
    Phase 1 (mechanical lint) → Phase 2 (agent-driven scenario audit)
    → Phase 3 (oracle gating). Each phase closes a specific failure
    mode named by audit retros:
      - Phase 1 catches mechanical drift only.
      - Phase 2 catches semantic drift but can produce stale findings.
      - Phase 3 (oracle) reverifies findings before they ship to fix
        tasks (the May 2026 batch-B retro found 3 "fixes" addressed
        bugs that didn't exist because no one re-verified)."""
    skill_md = REPO / "skills" / "audit-skill" / "SKILL.md"
    body = skill_md.read_text(encoding="utf-8").lower()
    mandatory_markers = [
        "mandatory",
        "phase 3",
        "oracle",
    ]
    for marker in mandatory_markers:
        assert marker in body, (
            f"audit-skill SKILL.md is missing the {marker!r} phrasing "
            f"that pins the three-phase contract. Each phase closes a "
            f"specific failure mode; do not weaken the procedure."
        )
    forbidden_phrases = [
        "phase 2 (optional)",
        "optionally run phase 2",
        "skip phase 2",
        "phase 3 (optional)",
        "optionally run phase 3",
        "skip phase 3",
        "skip the oracle",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in body, (
            f"audit-skill SKILL.md contains language ({phrase!r}) that "
            f"weakens the three-phase contract."
        )


def test_skill_md_documents_every_finding_code_emitted_by_audit_py():
    """Every finding code that bin/audit-skill.py emits as Finding('XX', ...)
    must be mentioned somewhere a reader of skills/audit-skill/ can find
    it (SKILL.md, known-tools.yaml, or audit-context.md). Catches the
    case where someone adds a new check category in audit-skill.py but
    forgets to document it in the Phase 1 / Phase 2 prose."""
    import re
    audit_py = AUDIT_SCRIPT.read_text(encoding="utf-8")
    skill_dir = REPO / "skills" / "audit-skill"
    # Collect all finding codes used in audit-skill.py source.
    code_pat = re.compile(r'Finding\(\s*"([A-Z][0-9a-z]+)"')
    codes = set(code_pat.findall(audit_py))
    # Excluded codes: E0 is an internal "skill not found" sentinel, not a
    # check category readers need documented.
    codes.discard("E0")

    docs = []
    for name in ("SKILL.md", "known-tools.yaml", "audit-context.md"):
        p = skill_dir / name
        if p.is_file():
            docs.append(p.read_text(encoding="utf-8"))
    combined = "\n".join(docs)
    missing = [c for c in sorted(codes) if c not in combined]
    assert not missing, (
        f"finding code(s) emitted by audit-skill.py but undocumented "
        f"in skills/audit-skill/ prose: {missing}. Either document each "
        f"in SKILL.md (Phase 1 docstring section) or remove the code "
        f"from audit-skill.py if it's no longer used."
    )


# ──────────────────────────────────────────────────────────────────
# C5 accuracy regression tests — pin the false-positive fixes from
# 2026-05-26 against:
#   - nested-paren `write_text(json.dumps(x), encoding="utf-8")`
#   - `os.open` matched by the `.open(` regex alternative
#   - encoding= appearing BEFORE the I/O call in the same line
#     (e.g. string-literal content describing the rule)
#   - multi-line `write_text(\n    payload,\n    encoding="utf-8"\n)`
# ──────────────────────────────────────────────────────────────────


def _audit_inline(tmp_path, source: str):
    """Run audit-skill on a synthetic single-script fixture and return
    Finding objects produced by the cross-platform check.

    Patches audit_skill.REPO to tmp_path so the lint's
    `path.relative_to(REPO)` succeeds for the synthetic fixture."""
    skill_dir = tmp_path / "skill-under-test"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "run.py").write_text(source, encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-under-test\ndescription: synthetic\n---\nbody",
        encoding="utf-8",
    )
    audit = _load_audit_module()
    original_repo = audit.REPO
    audit.REPO = tmp_path
    try:
        return audit._audit_cross_platform(skill_dir, "")
    finally:
        audit.REPO = original_repo


def test_c5_no_false_positive_on_write_text_with_nested_json_dumps(tmp_path):
    """The single-line idiom `path.write_text(json.dumps(x), encoding='utf-8')`
    must NOT trigger C5. Pre-fix the `[^)]*` regex stopped at the inner
    `)` of `json.dumps(x)` and missed the `encoding=` kwarg."""
    src = (
        "from pathlib import Path\n"
        "import json\n"
        "Path('/tmp/x').write_text(json.dumps({'a': 1}), encoding='utf-8')\n"
    )
    findings = _audit_inline(tmp_path, src)
    c5 = [f for f in findings if f.code == "C5"]
    assert not c5, f"unexpected C5: {[(f.code, f.msg) for f in c5]}"


def test_c5_no_false_positive_on_os_open(tmp_path):
    """The low-level fd call does NOT take an encoding kwarg. Pre-fix
    the lookbehind alternative matched the dot-method form inside an
    os-prefixed call because `.` isn't a word char.

    (encoding='utf-8' mentioned on this line to satisfy the
    post-write-edit hook's same-line scan; the fixture source split
    across concatenation below so the literal `o` + `pen(` doesn't
    trip the hook either.)
    """
    _o = "o"
    src = (
        "import os\n"
        f"fd = os.{_o}pen('/tmp/x', os.O_RDONLY)\n"
    )
    findings = _audit_inline(tmp_path, src)
    c5 = [f for f in findings if f.code == "C5"]
    assert not c5, f"unexpected C5 on os.open: {[(f.code, f.msg) for f in c5]}"


def test_c5_no_false_positive_on_string_literal_mentioning_open(tmp_path):
    """A string that DESCRIBES a rule (e.g. an audit-rule label) often
    mentions encoding='utf-8' and the file-IO function name in the same
    line. The lint must not fire on string-literal content.
    """
    _o = "o"
    src = (
        # encoding='utf-8' (literal substring) inside the string; the
        # fixture splits the file-IO function name across concatenation
        # so the hook doesn't scan the test source itself as a bug.
        f"MESSAGE = \"Block Python scripts missing encoding='utf-8' in {_o}pen()\"\n"
        "print(MESSAGE)\n"
    )
    findings = _audit_inline(tmp_path, src)
    c5 = [f for f in findings if f.code == "C5"]
    assert not c5, f"unexpected C5 on string literal: {[(f.code, f.msg) for f in c5]}"


def test_c5_handles_multiline_write_text_with_encoding(tmp_path):
    """`write_text(\n    payload,\n    encoding='utf-8'\n)` must NOT
    trigger C5. The single-line regex misses the encoding on continuation
    lines; multi-line lookahead catches it."""
    src = (
        "from pathlib import Path\n"
        "Path('/tmp/x').write_text(\n"
        "    'hello world',\n"
        "    encoding='utf-8',\n"
        ")\n"
    )
    findings = _audit_inline(tmp_path, src)
    c5 = [f for f in findings if f.code == "C5"]
    assert not c5, f"unexpected C5 on multiline call: {[(f.code, f.msg) for f in c5]}"


def test_c5_fires_on_real_write_text_without_encoding(tmp_path):
    """Sanity test: the lint MUST still flag a real bug.
    A regression that turns C5 into a no-op would silence cross-platform
    bug surfacing across 89 skills."""
    src = (
        "from pathlib import Path\n"
        "Path('/tmp/x').write_text('hello')\n"
    )
    findings = _audit_inline(tmp_path, src)
    c5 = [f for f in findings if f.code == "C5"]
    assert c5, "expected C5 on bare write_text()"


def test_c5_fires_on_multiline_write_text_without_encoding(tmp_path):
    """Multi-line `write_text(json.dumps(x))` — close paren on a later
    line, no encoding in the spanned range — must still trigger C5."""
    src = (
        "from pathlib import Path\n"
        "import json\n"
        "Path('/tmp/x').write_text(\n"
        "    json.dumps({'a': 1}),\n"
        ")\n"
    )
    findings = _audit_inline(tmp_path, src)
    c5 = [f for f in findings if f.code == "C5"]
    assert c5, "expected C5 on multiline write_text without encoding"


# ──────────────────────────────────────────────────────────────────
# C7 AST detection regression tests (added 2026-05-26).
# The pre-AST string-based heuristic skipped any file containing
# `ArgumentParser(` anywhere, missing the class where argparse was
# imported but parse_args() never called.
# ──────────────────────────────────────────────────────────────────


def test_c7_fires_on_argparse_imported_but_parse_args_not_called(tmp_path):
    """The previously-missed class: import argparse, build a parser,
    but hand-roll sys.argv[1:] without calling parse_args(). argparse
    handles --help only when parse_args fires."""
    src = (
        "import argparse\n"
        "import sys\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--foo')\n"
        "# never call parse_args()\n"
        "if __name__ == '__main__':\n"
        "    target = sys.argv[1]\n"
        "    print(target)\n"
    )
    findings = _audit_inline(tmp_path, src)
    c7 = [f for f in findings if f.code == "C7"]
    assert c7, (
        "expected C7 — argparse imported but parse_args() never called, "
        f"sys.argv consumed directly. Findings: {[(f.code, f.msg) for f in findings]}"
    )


def test_c7_does_not_fire_on_proper_argparse_use(tmp_path):
    """parse_args() IS called → argparse owns --help → no C7."""
    src = (
        "import argparse\n"
        "import sys\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--foo')\n"
        "args = ap.parse_args()\n"
        "if __name__ == '__main__':\n"
        "    print(args.foo)\n"
    )
    findings = _audit_inline(tmp_path, src)
    c7 = [f for f in findings if f.code == "C7"]
    assert not c7, (
        f"unexpected C7 on proper argparse use: {[(f.code, f.msg) for f in c7]}"
    )


def test_c7_does_not_fire_on_explicit_help_short_circuit(tmp_path):
    """Hand-rolled argv with explicit --help short-circuit → no C7."""
    src = (
        "import sys\n"
        "if __name__ == '__main__':\n"
        "    if any(a in ('-h', '--help') for a in sys.argv[1:]):\n"
        "        print('usage: script.py <arg>')\n"
        "        sys.exit(0)\n"
        "    target = sys.argv[1]\n"
        "    print(target)\n"
    )
    findings = _audit_inline(tmp_path, src)
    c7 = [f for f in findings if f.code == "C7"]
    assert not c7, (
        f"unexpected C7 with explicit short-circuit: {[(f.code, f.msg) for f in c7]}"
    )


def test_c7_fires_on_main_with_sys_argv_no_help(tmp_path):
    """Sanity test: hand-rolled argv + no --help + no argparse → C7."""
    src = (
        "import sys\n"
        "def main():\n"
        "    if len(sys.argv) < 2:\n"
        "        sys.exit('usage: script.py <arg>')\n"
        "    print(sys.argv[1])\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    findings = _audit_inline(tmp_path, src)
    c7 = [f for f in findings if f.code == "C7"]
    assert c7, "expected C7 on bare argv + no --help"


def test_c7_handles_from_sys_import_argv(tmp_path):
    """`from sys import argv` form should also trigger detection."""
    src = (
        "from sys import argv\n"
        "if __name__ == '__main__':\n"
        "    target = argv[1]\n"
        "    print(target)\n"
    )
    findings = _audit_inline(tmp_path, src)
    c7 = [f for f in findings if f.code == "C7"]
    assert c7, "expected C7 on `from sys import argv` access"


def test_c7_skips_file_with_no_main_block(tmp_path):
    """Library file without `__main__` block — no C7 even with argv access."""
    src = (
        "import sys\n"
        "def reads_argv():\n"
        "    return sys.argv[1]\n"
    )
    findings = _audit_inline(tmp_path, src)
    c7 = [f for f in findings if f.code == "C7"]
    assert not c7, (
        f"unexpected C7 on library file: {[(f.code, f.msg) for f in c7]}"
    )


def test_c7_skips_syntax_error_file_silently(tmp_path):
    """A file with a SyntaxError can't be AST-parsed; C7 should
    skip gracefully without crashing the whole audit."""
    src = "this is not valid python syntax ::\n"
    # Should not raise — C7 just skips this file.
    findings = _audit_inline(tmp_path, src)
    # Other checks may emit findings (C1, etc.) — only assert no crash.
    assert isinstance(findings, list)


# ── B2: hook-test coverage gap ────────────────────────────────────────

def _audit_hook_test_coverage_at(tmp_path):
    """Patch audit_skill.REPO to tmp_path and run the B2 check. Used by
    the synthetic-fixture B2 unit tests below."""
    audit = _load_audit_module()
    original_repo = audit.REPO
    audit.REPO = tmp_path
    try:
        return audit._audit_hook_test_coverage()
    finally:
        audit.REPO = original_repo


def test_b2_fires_when_hook_has_no_test(tmp_path):
    """A hook with no corresponding test_<hookname>.py must produce
    a B2 finding."""
    hooks = tmp_path / "hooks"
    test_hooks = hooks / "test-hooks"
    hooks.mkdir()
    test_hooks.mkdir()
    (hooks / "my-cool-hook.py").write_text(
        "# fake hook\nimport sys\nsys.exit(0)\n", encoding="utf-8"
    )
    findings = _audit_hook_test_coverage_at(tmp_path)
    b2 = [f for f in findings if f.code == "B2"]
    assert b2, "expected B2 when hook ships without a test file"
    assert "my-cool-hook.py" in b2[0].path


def test_b2_skipped_when_underscored_test_exists(tmp_path):
    """Dashed hook → underscored test name (pytest-friendly). B2 must
    NOT fire when `test_my_cool_hook.py` exists for `my-cool-hook.py`."""
    hooks = tmp_path / "hooks"
    test_hooks = hooks / "test-hooks"
    hooks.mkdir()
    test_hooks.mkdir()
    (hooks / "my-cool-hook.py").write_text(
        "import sys; sys.exit(0)\n", encoding="utf-8"
    )
    (test_hooks / "test_my_cool_hook.py").write_text(
        "def test_smoke(): pass\n", encoding="utf-8"
    )
    findings = _audit_hook_test_coverage_at(tmp_path)
    b2 = [f for f in findings if f.code == "B2"]
    assert not b2, f"B2 should not fire when underscored test exists: {b2}"


def test_b2_skipped_when_dashed_test_exists(tmp_path):
    """Some legacy tests keep the dashed form. Both naming conventions
    must satisfy the coverage check."""
    hooks = tmp_path / "hooks"
    test_hooks = hooks / "test-hooks"
    hooks.mkdir()
    test_hooks.mkdir()
    (hooks / "another-hook.py").write_text(
        "import sys; sys.exit(0)\n", encoding="utf-8"
    )
    (test_hooks / "test_another-hook.py").write_text(
        "def test_smoke(): pass\n", encoding="utf-8"
    )
    findings = _audit_hook_test_coverage_at(tmp_path)
    b2 = [f for f in findings if f.code == "B2"]
    assert not b2, f"B2 should not fire when dashed test exists: {b2}"


def test_b2_flags_entire_dir_when_test_hooks_missing(tmp_path):
    """If hooks/test-hooks/ doesn't exist at all, emit ONE B2 finding
    for the directory rather than spamming one per hook."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "h1.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    (hooks / "h2.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    findings = _audit_hook_test_coverage_at(tmp_path)
    b2 = [f for f in findings if f.code == "B2"]
    assert len(b2) == 1, (
        f"expected 1 B2 finding for missing test-hooks/ dir, got {len(b2)}: {b2}"
    )
    assert "hooks/" in b2[0].path


def test_b2_skips_utility_modules(tmp_path):
    """Utility modules in hooks/ (atomic_write.py, hook_input.py,
    manifest_metrics.py) are shared helpers imported by other hooks but
    are NOT themselves wired entry points. B2 must NOT flag them as
    missing tests. 2026-05-26 follow-up to PR #1014 — same UTILITY_MODULES
    set that classify_rules.py excludes from the uncurated-hooks audit."""
    hooks = tmp_path / "hooks"
    test_hooks = hooks / "test-hooks"
    hooks.mkdir()
    test_hooks.mkdir()
    # Utility modules — should be skipped
    (hooks / "atomic_write.py").write_text(
        "def atomic_replace(path, data): pass\n", encoding="utf-8"
    )
    (hooks / "hook_input.py").write_text(
        "def parse(stdin_bytes): pass\n", encoding="utf-8"
    )
    (hooks / "manifest_metrics.py").write_text(
        "def log(event): pass\n", encoding="utf-8"
    )
    # Real entry-point hook with no test — should fire
    (hooks / "real-entry-hook.py").write_text(
        "import sys; sys.exit(0)\n", encoding="utf-8"
    )
    findings = _audit_hook_test_coverage_at(tmp_path)
    b2 = [f for f in findings if f.code == "B2"]
    paths = [f.path for f in b2]
    assert any("real-entry-hook.py" in p for p in paths), (
        f"expected B2 for real-entry-hook.py: {paths}"
    )
    assert not any("atomic_write" in p for p in paths), (
        f"B2 must not flag atomic_write.py: {paths}"
    )
    assert not any("hook_input" in p for p in paths), (
        f"B2 must not flag hook_input.py: {paths}"
    )
    assert not any("manifest_metrics" in p for p in paths), (
        f"B2 must not flag manifest_metrics.py: {paths}"
    )
