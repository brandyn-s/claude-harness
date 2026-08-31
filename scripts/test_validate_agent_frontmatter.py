#!/usr/bin/env python3
"""Tests for the agent-frontmatter validator.

Mutation-verified: each test corresponds to a way the validator could silently
pass. A lint that cannot fail is worse than no lint, because it launders the
absence of checking into an appearance of coverage.

Run: pytest scripts/test_validate_agent_frontmatter.py -q
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "vaf", pathlib.Path(__file__).with_name("validate-agent-frontmatter.py")
)
assert _SPEC and _SPEC.loader
vaf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vaf)

REPO = pathlib.Path(__file__).resolve().parent.parent


def write(d: pathlib.Path, name: str, body: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


@pytest.fixture()
def agents(tmp_path):
    return tmp_path / "agents"


# ---------------------------------------------------------------------------
# the real repository must pass
# ---------------------------------------------------------------------------
def test_repo_agents_are_all_valid():
    assert vaf.main(["--dir", str(REPO / "agents")]) == 0


def test_repo_agent_corpus_matches_documented_inventory_and_tool_policy():
    """The README and real frontmatter must describe the same six agents."""
    expected_tools = {
        "api-ingest-worker.md": [
            "Read",
            "Write",
            "Glob",
            "Bash",
            "mcp__firecrawl__firecrawl_map",
            "mcp__firecrawl__firecrawl_scrape",
            "mcp__firecrawl__firecrawl_extract",
            "mcp__firecrawl__firecrawl_crawl",
            "mcp__firecrawl__firecrawl_check_crawl_status",
        ],
        "data-flow-analyzer.md": ["Read", "Grep", "Glob"],
        "exploitability-verifier.md": ["Read", "Grep", "Glob"],
        "poc-builder.md": ["Read", "Write", "Edit", "Grep", "Glob", "Bash"],
        "semgrep-scanner.md": ["Bash(semgrep scan:*)", "Bash"],
    }
    definitions = {
        path.name: path
        for path in sorted((REPO / "agents").glob("*.md"))
        if path.name not in {"README.md", "TEMPLATE.md"}
    }

    assert set(definitions) == {*expected_tools, "worker.md"}
    for name, tools in expected_tools.items():
        text = definitions[name].read_text(encoding="utf-8")
        assert vaf.parse_frontmatter_values(text, "tools") == tools
        assert "Agent" not in tools

    worker = definitions["worker.md"].read_text(encoding="utf-8")
    assert vaf.parse_frontmatter_values(worker, "tools") == []
    assert vaf.parse_frontmatter_values(worker, "disallowedTools") == ["Agent"]
    assert vaf.parse_frontmatter_values(worker, "skills") == [
        "systematic-debugging",
        "verification-before-completion",
    ]

    readme = (REPO / "agents" / "README.md").read_text(encoding="utf-8")
    for name in definitions:
        assert f"`{name.removesuffix('.md')}`" in readme
    assert "MCP server patterns" in readme
    assert "#84974" in readme
    assert "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1" in readme
    assert "tool fence is the primary" in readme

    template = (REPO / "agents" / "TEMPLATE.md").read_text(encoding="utf-8")
    assert "non-empty positive tools allowlist" in template
    assert "do not treat a denylist as a positive bound" in template


def test_worker_denies_the_agent_tool():
    """worker must not be able to dispatch subagents.

    No worker route needs delegation (all 20 skill-rules routes are domain-tool
    operations; the PARENT fans out per agent-delegation.md). Denying `Agent` also
    covers the documented fork exception, which otherwise inherits the parent's
    full tool list.
    """
    text = (REPO / "agents" / "worker.md").read_text(encoding="utf-8")
    keys = vaf.parse_top_level_keys(text)
    assert "disallowedTools" in keys
    # The deny list must actually name Agent.
    head = text.split("---")[1]
    body_lines = [ln.strip() for ln in head.splitlines()]
    assert "- Agent" in body_lines, "disallowedTools must include Agent"


def test_allowedAgentTypes_is_gone_from_live_agents():
    """Regression: the unsupported field must not come back."""
    for p in sorted((REPO / "agents").glob("*.md")):
        if p.name in {"README.md", "TEMPLATE.md"}:
            continue
        keys = vaf.parse_top_level_keys(p.read_text(encoding="utf-8"))
        assert "allowedAgentTypes" not in keys, p.name


# ---------------------------------------------------------------------------
# mutations: the validator must FAIL when it should
# ---------------------------------------------------------------------------
def test_unsupported_field_fails(agents):
    write(agents, "bad.md", "---\nname: bad\ndescription: x\nallowedAgentTypes: bad\n---\nbody\n")
    assert vaf.main(["--dir", str(agents)]) == 1


def test_arbitrary_unknown_field_fails(agents):
    write(agents, "bad.md", "---\nname: b\ndescription: x\nnotAField: 1\n---\nbody\n")
    assert vaf.main(["--dir", str(agents)]) == 1


def test_every_documented_field_is_accepted(agents):
    body = "---\n" + "\n".join(
        f"{k}: v" for k in sorted(vaf.SUPPORTED)
    ) + "\n---\nbody\n"
    write(agents, "ok.md", body)
    assert vaf.main(["--dir", str(agents)]) == 0


def test_commented_field_is_not_flagged(agents):
    """A '# allowedAgentTypes is NOT supported' doc note must not read as a declaration."""
    write(
        agents,
        "ok.md",
        "---\nname: ok\ndescription: x\n# allowedAgentTypes is NOT supported\n"
        "disallowedTools:\n  - Agent\n---\nbody\n",
    )
    assert vaf.main(["--dir", str(agents)]) == 0


def test_nested_list_items_are_not_treated_as_top_level_keys(agents):
    """Indented YAML must not be parsed as fields (would false-fail every agent)."""
    write(
        agents,
        "ok.md",
        "---\nname: ok\ndescription: x\ntools:\n  - Read\n  - Bash\nhooks:\n"
        "  PreToolUse:\n    - x\n---\nbody\n",
    )
    assert vaf.main(["--dir", str(agents)]) == 0


def test_unbounded_agent_warns_when_requested(agents, capsys):
    write(agents, "u.md", "---\nname: u\ndescription: x\n---\nbody\n")
    rc = vaf.main(["--dir", str(agents), "--warn-unbounded"])
    assert rc == 0  # a warning, not a failure
    assert "INHERITS every tool" in capsys.readouterr().out


def test_missing_directory_is_unknown_not_pass(tmp_path):
    """UNKNOWN must have its own exit code; folding it into 0 would hide a broken run."""
    assert vaf.main(["--dir", str(tmp_path / "does-not-exist")]) == 2


def test_readme_and_template_are_skipped(agents):
    """Docs carry illustrative frontmatter and must not fail the gate."""
    write(agents, "README.md", "---\nname: x\nallowedAgentTypes: y\n---\n")
    write(agents, "TEMPLATE.md", "---\nname: x\nallowedAgentTypes: y\n---\n")
    write(agents, "real.md", "---\nname: r\ndescription: x\ntools:\n  - Read\n---\n")
    assert vaf.main(["--dir", str(agents)]) == 0
