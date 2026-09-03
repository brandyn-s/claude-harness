"""Focused contracts for rule prose, manifests, and live hook wiring."""

import importlib.util
import json
import re
import pytest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _hook_invocation(hook: dict) -> str:
    """Normalize both shell-string and structured command/args registrations."""

    return " ".join(
        [str(hook.get("command", "")), *(str(arg) for arg in hook.get("args", []))]
    )


def test_hook_invocation_accepts_structured_command_args_registration():
    invocation = _hook_invocation(
        {
            "command": "/Users/example/.claude/hooks/run-hook",
            "args": ["prompt-secret-scan.py"],
        }
    )
    assert "prompt-secret-scan.py" in invocation


def test_mutation_verdict_guidance_has_cross_language_delivery():
    rule_text = (REPO / "rules" / "tdd-mutation-testing.md").read_text(
        encoding="utf-8"
    )
    frontmatter = rule_text.split("---", 2)[1]
    paths = set(yaml.safe_load(frontmatter)["paths"])
    skill = (REPO / "skills" / "legacy-code-tdd" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    for pattern in (
        "**/*_test.go",
        "**/*Test.java",
        "**/*Tests.cs",
        "**/*_spec.rb",
        "**/*.tftest.hcl",
        "**/tests/**",
        "**/spec/**",
    ):
        assert pattern in paths
    assert "REQUIRED READ" in skill
    assert "docs/rule-reference/tdd-mutation-verdict-interpretation.md" in skill


def test_agent_delegation_retains_authenticated_remote_mcp_gate():
    rule = (REPO / "rules" / "agent-delegation.md").read_text(
        encoding="utf-8"
    ).lower()
    manifest = _yaml(REPO / "rules" / "manifests" / "agent-delegation.yaml")

    # The compact parent is the ambient contract. It must retain the auth
    # boundary advertised by its manifest, not leave it only in an incident.
    for phrase in (
        "authenticated remote mcp",
        "appear anonymous",
        "main thread",
        "do not dispatch",
    ):
        assert phrase in rule, phrase

    assert "check auth constraint before dispatching" in manifest["required_actions"]
    assert (
        "dispatch to remote MCP-dependent task via subagent"
        in manifest["prohibited_actions"]
    )


def test_output_grounding_is_a_prompt_and_evaluation_contract_without_a_hook():
    # RELOCATED 2026-08-26: the contract moved out of ambient rules/ to
    # skills/_shared/ (relocation pilot: EXPOSED=0 over 438 transcripts).
    # HOOK REMOVED 2026-09-03: the PostToolUse:Skill advisory diagnostic
    # (creative-output-grounding-check.py) was deleted. A 30-day replay found
    # zero substantive Skill payloads -- the tool response is launcher metadata,
    # never the final answer -- so it could not grade anything the runtime
    # supplied. Pin that no phantom enforcer creeps back in code or prose.
    rule = (REPO / "skills" / "_shared" / "output-grounding.md").read_text(
        encoding="utf-8"
    )
    reference = (REPO / "docs" / "rule-reference" / "output-grounding.md").read_text(
        encoding="utf-8"
    )
    rule_manifest = _yaml(
        REPO / "rules" / "manifests" / "output-grounding.yaml"
    )
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))

    skill_hooks = [
        _hook_invocation(hook)
        for entry in settings["hooks"].get("PostToolUse", [])
        if entry.get("matcher") == "Skill"
        for hook in entry.get("hooks", [])
    ]
    assert not any("grounding" in invocation for invocation in skill_hooks)
    assert not (REPO / "hooks" / "creative-output-grounding-check.py").exists()
    assert not (
        REPO / "hooks" / "manifests" / "creative-output-grounding-check.yaml"
    ).exists()

    # Both prose surfaces say what enforces the contract and why no hook can.
    for text in (rule.lower(), reference.lower()):
        assert "no hook" in text
        assert re.search(r"launcher\s+metadata", text)
        assert "final answer" in text
        assert "final-output evaluation" in text
    assert "enforced_by" not in rule_manifest
    assert rule_manifest["enforcement_coverage"] == "none"


def test_output_grounding_consumers_do_not_claim_final_answer_hook_coverage():
    paths = [
        REPO / "skills" / "_shared" / "output-grounding.md",
        REPO / "skills" / "scout-frontier" / "SKILL.md",
        REPO / "skills" / "design-evidence-first" / "SKILL.md",
        REPO / "skills" / "deep-dive" / "SKILL.md",
        REPO / "skills" / "refine" / "SKILL.md",
        REPO / "docs" / "DESIGN_RATIONALE.md",
    ]
    stale_claims = (
        "audits skill output",
        "audits output for",
        "audits the eventual output",
        "architectural-layer enforcement",
        "remains registered",
        "advisory payload diagnostic only",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        for claim in stale_claims:
            assert claim not in text, f"{path}: {claim}"

    rationale = paths[-1].read_text(encoding="utf-8").lower()
    assert "no hook enforces it" in rationale
    assert re.search(r"launcher\s+metadata", rationale)

# ---------------------------------------------------------------------------
# The manifest compiler's THIRD accepted source location for a type:rule
# manifest -- skills/_shared/<id>.md -- was added 2026-08-26 to give the
# reduction path a legal exit. Without it, relocating a rule out of ambient
# forces a choice between a MISSING_SOURCE error and deleting a REAL declared
# dependency from an owner skill's requires_rules.
#
# It needs a known-NEGATIVE or the acceptance is unfalsifiable: a validator that
# accepts every location would pass the positive case for the wrong reason.
# ---------------------------------------------------------------------------

def _rule_manifest_root(tmp_path, source_rel: str | None):
    """Build a minimal tree with one type:rule manifest, source at source_rel."""
    (tmp_path / "rules" / "manifests").mkdir(parents=True)
    (tmp_path / "rules" / "manifests" / "probe-rule.yaml").write_text(
        "id: probe-rule\ntype: rule\ndescription: probe\n", encoding="utf-8"
    )
    if source_rel is not None:
        target = tmp_path / source_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# probe\n", encoding="utf-8")
    return tmp_path


def _semantic_issues(root):
    spec = importlib.util.spec_from_file_location(
        "manifest_compile_probe", REPO / "manifests" / "compile.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    components = {"probe-rule": {"type": "rule", "_source": "rules/manifests/probe-rule.yaml"}}
    return module.validate_semantic(root, components)


@pytest.mark.parametrize(
    ("source_rel", "expect_ok"),
    [
        ("rules/probe-rule.md", True),                    # ambient
        ("skills/_shared/probe-rule.md", True),           # relocated (the new path)
        ("agent-memory/rules/probe-rule.md", True),       # historical, injector retired
        (None, False),                                    # KNOWN-NEGATIVE: nowhere
    ],
)
def test_rule_manifest_source_locations(tmp_path, source_rel, expect_ok):
    root = _rule_manifest_root(tmp_path, source_rel)
    issues = _semantic_issues(root)
    missing = [i for i in issues if "MISSING_SOURCE" in i and "probe-rule" in i]
    if expect_ok:
        assert not missing, (source_rel, issues)
    else:
        assert missing, "a manifest with NO source anywhere must report MISSING_SOURCE"


def test_relocated_output_grounding_manifest_resolves_and_is_marked_non_ambient():
    """The live instance of the above: its source is shared, not ambient."""
    manifest = _yaml(REPO / "rules" / "manifests" / "output-grounding.yaml")
    assert manifest["source"] == "skills/_shared/output-grounding.md"
    assert manifest["ambient"] is False
    assert (REPO / manifest["source"]).is_file()
    assert not (REPO / "rules" / "output-grounding.md").exists(), (
        "the ambient copy must be GONE -- two copies is the two-source drift class"
    )
