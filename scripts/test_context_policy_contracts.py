"""Cross-corpus context and model-runtime policy contracts."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hooks"))

import rule_context_budget as rule_budget


def test_current_docs_record_context_reconciliation_and_merged_delivery():
    architecture = (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8")
    markdown = (
        REPO / "docs" / "CLAUDE_CODE_ARCHITECTURE_REVIEW_2026-08-05.md"
    ).read_text(encoding="utf-8")
    html = (
        REPO / "docs" / "claude-code-architecture-modernization-report.html"
    ).read_text(encoding="utf-8")

    for text in (architecture, markdown, html):
        assert "526,404" in text
        assert "152,949" in text
        assert "38,237" in text
        assert "33" in text

    for text in (markdown, html):
        current = text.split("Historical snapshot", 1)[0]
        assert "1e7a5cc7ee53c2c5f0429b2b500041a6b809a7de" in current
        assert "PR #1948" in current
        assert "merged" in current.lower()
        assert "draft PR #1948" not in current

    assert "current-state addendum dated 9 August 2026" in html
    assert "current-state addendum is dated 9 August 2026" in html


def test_ambient_rules_fit_measured_fixed_context_budget():
    assert rule_budget.WARN_BYTES == 225_000
    assert rule_budget.BLOCK_BYTES == 250_000
    assert rule_budget.WARN_BYTES < rule_budget.BLOCK_BYTES
    current = rule_budget.unconditional_rule_bytes(REPO / "rules")
    assert current <= rule_budget.WARN_BYTES, (rule_budget.WARN_BYTES, current)

    # THE DELTA GATE. The absolute ceilings above bound the corpus; this bounds its
    # GROWTH, which is the thing that actually generated the repair treadmill.
    #
    # The ceiling is DERIVED (baseline + sum of justified ledger entries), never
    # stored -- so it cannot be raised by editing a number. Raising it requires
    # appending an entry that names the bytes and the reason, which is a reviewable
    # line in a diff instead of a surprise when CI goes red. A NEGATIVE entry
    # ratchets the ceiling down so a relocation's savings become permanent.
    budget = rule_budget.load_ambient_budget(REPO / rule_budget.BUDGET_LEDGER_RELPATH)
    assert current <= budget.allowed_bytes, (
        "ambient rule corpus grew past the ledger ceiling",
        {"current": current, "allowed": budget.allowed_bytes,
         "over_by": current - budget.allowed_bytes,
         "resolve": "relocate equivalent bytes out of ambient in this change, route "
                    "the lesson to agent-memory/a skill step, add paths: frontmatter, "
                    f"or append a justified entry to {rule_budget.BUDGET_LEDGER_RELPATH}"},
    )
    # The ceiling must stay DERIVED. Asserting allowed == baseline + sum(entries)
    # would be worthless here -- load_ambient_budget computes allowed that way, so the
    # check would compare the loader's arithmetic to itself and pass no matter what
    # (the regenerate-and-compare trap in rules/incidents/verify-effectiveness.md).
    # The property that can actually fail is the absence of a STORED ceiling: if a
    # future change adds one to the JSON, a bare number becomes editable again and the
    # whole gate reverts to the cliff it replaced.
    ledger_raw = json.loads(
        (REPO / rule_budget.BUDGET_LEDGER_RELPATH).read_text(encoding="utf-8")
    )
    for forbidden in ("allowed_unconditional_bytes", "allowed_bytes", "ceiling"):
        assert forbidden not in ledger_raw, (
            f"{forbidden!r} must not be stored in the ledger -- the ceiling is derived "
            "from baseline + sum(ledger entries) so that raising it requires a "
            "justified entry rather than editing a number"
        )
    # Every entry must carry its justification, or the ledger becomes the same
    # unreviewable bump. load_ambient_budget enforces this; assert it is still wired.
    for entry in budget.entries:
        assert entry.get("reason", "").strip(), entry

    formerly_dominant = (
        "verify-before-assuming.md",
        "check-before-change.md",
        "diagnose-before-fix.md",
        "grading-discipline.md",
        "git-hygiene.md",
        "worktree-by-default.md",
        "security-confirmations.md",
        "scope-discipline.md",
        "transcript-over-summary.md",
        "subagent-verification.md",
    )
    # The per-file 10,000-byte cap that used to apply here is RETIRED. It was a
    # one-time descope mechanism (hence the tuple name) frozen into a permanent
    # constraint, and it failed measurably: a ceiling is a cliff, so repairs
    # converged to just under it and the next append breached it again --
    # git-hygiene.md went breach -> repair FOUR times in 16 days at ~9,800/10,000,
    # across 13 dedicated cap-repair PRs. It also MISALLOCATED: three files sat under
    # 500 bytes of headroom while 16,395 bytes went unused in the other seven.
    #
    # Growth is now bounded by the DERIVED ledger ceiling asserted below, and
    # per-file size is still bounded by rule-size-guard's WARN 35,000 / BLOCK 38,000
    # on every rules/*.md -- so no single file is left unbounded.
    #
    # The reference-pointer requirement is STRUCTURAL, not about size, so it stays:
    # it is what keeps the extraction target discoverable from the ambient rule.
    for name in formerly_dominant:
        path = REPO / "rules" / name
        reference = REPO / "docs" / "rule-reference" / name
        assert reference.is_file(), reference
        assert f"docs/rule-reference/{name}" in path.read_text(encoding="utf-8"), name

    quality_rules = (
        "validate-to-improve.md",
        "verify-instrument-before-fix.md",
        "security-critical-search-verification.md",
        "web-search-preference.md",
        "complete-the-whole-instruction.md",
        "symmetric-evidentiary-burden.md",
        "red-team-rubric-discipline.md",
        "reproduce-before-optimize.md",
        "compare-by-need.md",
        # output-grounding.md RELOCATED 2026-08-26 to skills/_shared/ after the
        # relocation pilot measured EXPOSED=0 over 438 transcripts (coverage 100%,
        # activity 19 == owner-skill invocation 19). Its four owner skills now carry
        # a REQUIRED-READ pointer; docs/rule-reference/ and rules/incidents/ are kept.
    )
    # The per-file 5,000-byte cap here is RETIRED for the same reason as the 10,000
    # one above, and it was in the same state: THREE of these ten sat under 500 bytes
    # of headroom (security-critical-search-verification 100 B, web-search-preference
    # 268 B, verify-instrument-before-fix 339 B), so six ambient rules across the two
    # caps were effectively unwritable while the corpus as a whole had room.
    #
    # Retiring both is deliberate: leaving one in place would keep the cliff, just on
    # a smaller set. Growth is bounded by the derived ledger ceiling above, and
    # per-file size by rule-size-guard's WARN 35,000 / BLOCK 38,000.
    #
    # The reference-pointer requirement is structural and stays.
    for name in quality_rules:
        path = REPO / "rules" / name
        reference = REPO / "docs" / "rule-reference" / name
        assert reference.is_file(), reference
        assert f"docs/rule-reference/{name}" in path.read_text(encoding="utf-8"), name

    # Path-scoped rules leave the unconditional corpus entirely. rule-authoring
    # joined them 2026-08-26 (-6,438 B); its trigger is a file path, so the
    # platform delivers it when a rule-like file is in play. The reference-doc
    # pointer is asserted too: the compaction moved measured evidence there, and
    # a pointer to a missing file is the failure this could cause.
    for name in ("tdd-mutation-testing.md", "rule-authoring.md"):
        text = (REPO / "rules" / name).read_text(encoding="utf-8")
        assert rule_budget.has_paths_frontmatter(text), name

    # subagent-tool-discipline moved to skills/_shared/ 2026-08-26 (-7,015 B) and is
    # injected by the SubagentStart hook. Three things must hold together or the
    # contract is delivered NOWHERE: the ambient copy is gone, the shared copy exists,
    # and the hook actually references it.
    assert not (REPO / "rules" / "subagent-tool-discipline.md").exists(), (
        "the ambient copy must be gone; two copies is the two-source drift class"
    )
    subagent_contract = REPO / "skills" / "_shared" / "subagent-tool-discipline.md"
    assert subagent_contract.is_file(), subagent_contract
    contract_text = subagent_contract.read_text(encoding="utf-8")
    for needle in ("INSUFFICIENT_CONTEXT", "GUARD pattern=", "partial read"):
        assert needle in contract_text, needle
    hook_src = (REPO / "hooks" / "subagent-start-context.py").read_text(encoding="utf-8")
    # Strip comments BEFORE asserting. The un-stripped check was satisfied by the
    # hook's own comment ("relocated from ambient rules/subagent-tool-discipline.md"),
    # so a mutation that pointed CONTRACT_PATH at a nonexistent file was MISSED --
    # rules/tdd-mutation-testing.md item 32, a check matching prose about the thing
    # instead of the thing.
    hook_code = "\n".join(
        line for line in hook_src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "subagent-tool-discipline.md" in hook_code, (
        "the hook must reference the contract IN CODE or nothing delivers it"
    )
    assert "INJECTION_BUDGET_CHARS" in hook_src, (
        "an unbudgeted injection is silently replaced by a ~2KB preview"
    )
    # It must fit the hook's budget with room for topic files, or the relocation
    # preserves the rule by degrading every dispatch. The bound is DERIVED from the
    # hook's own constant rather than a chosen number, so raising the budget relaxes
    # this automatically and lowering it tightens it.
    budget_match = re.search(r"INJECTION_BUDGET_CHARS\s*=\s*([\d_]+)", hook_src)
    assert budget_match, "could not read the hook's injection budget"
    injection_budget = int(budget_match.group(1).replace("_", ""))
    assert len(contract_text) <= injection_budget // 2, (
        "the contract must leave at least half the injection budget for topic files",
        {"contract": len(contract_text), "budget": injection_budget},
    )

    authoring = (REPO / "rules" / "rule-authoring.md").read_text(encoding="utf-8")
    assert (REPO / "docs" / "rule-reference" / "rule-authoring.md").is_file()
    assert "docs/rule-reference/rule-authoring.md" in authoring
    # It must now obey its OWN top-ranked lever, which the prose version did not.
    assert authoring.count("GUARD pattern=") >= 5, authoring.count("GUARD pattern=")


def test_mutation_verdict_rule_is_path_scoped_across_code_and_config_surfaces():
    mutation = (REPO / "rules" / "tdd-mutation-testing.md").read_text(
        encoding="utf-8"
    )
    quality = (REPO / "rules" / "tdd-quality.md").read_text(encoding="utf-8")

    assert rule_budget.has_paths_frontmatter(mutation)
    for pattern in (
        '"**/*.py"',
        '"**/*.ts"',
        '"**/*.sh"',
        '"**/*.ps1"',
        '"**/*.yaml"',
        '"**/*.json"',
        '"**/*.toml"',
        '"**/*.tf"',
    ):
        assert pattern in mutation, pattern
    assert "both ambient" not in mutation.lower()
    assert "ambient too" not in quality.lower()


def test_eval_shipping_decision_contract_is_global_compact_and_routes_detail():
    rule = REPO / "rules" / "eval-shipping-discipline.md"
    reference = REPO / "docs" / "rule-reference" / "eval-shipping-discipline.md"
    text = rule.read_text(encoding="utf-8")

    assert not rule_budget.has_paths_frontmatter(text)
    assert rule.stat().st_size <= 7_000
    assert reference.is_file()
    assert "docs/rule-reference/eval-shipping-discipline.md" in text

    for phrase in (
        "every metric-driven production default or PR ship decision",
        "per-query data",
        "paired bootstrap",
        "n_bootstraps >= 10000",
        "production-mode",
        "every affected fixture",
        "fail closed",
        "pre-implementation retirement",
        "axis audit",
        "independent candidate pool",
        "second rater",
        "ratio/set",
        "carried-forward artifact",
        "selection bias",
        "three consecutive regressions",
        "same depth",
        "same instance order",
        "commit the instrument",
    ):
        assert phrase in text, phrase


def test_compacted_global_rules_retain_load_bearing_invariants():
    verification = (REPO / "rules" / "verify-effectiveness.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "source/configured/deployed/live/measured",
        "multi-seam",
        "known-positive",
        "fresh verification",
        "field union",
        "instrument",
        "irreversible",
    ):
        assert phrase in verification, phrase

    platform = (REPO / "rules" / "platform-constraints.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "Never expose secrets",
        "settings.json is live runtime state",
        "foreground sleep",
        "pipeline",
        "AWS",
        "worktree",
        "destructive",
    ):
        assert phrase in platform, phrase


@pytest.mark.parametrize(
    ("relative_path", "phrases"),
    (
        ("rules/scope-discipline.md", (
            "45 minutes", "observable outcome", "stop and simplify",
            "proof machinery must stay smaller", "production change",
            "uncontrolled harness", "never self-authorize an admin/",
        )),
        ("rules/security-confirmations.md", (
            "authorization envelope", "read-only checks", "polling", "receipts",
            "live readback",
            "material source, plan, graph, account, authority, or safety drift",
            "residual plan after a partial apply",
        )),
        ("rules/manifests/scope-discipline.yaml", (
            "45 minutes", "proof machinery", "uncontrolled harness",
        )),
        ("rules/manifests/security-confirmations.yaml", (
            "authorization envelope", "read-only checks",
            "residual plan after a partial apply",
        )),
    ),
)
def test_simple_fast_correct_policy_contract(relative_path: str, phrases: tuple[str, ...]):
    text = (REPO / relative_path).read_text(encoding="utf-8").lower()
    assert not (missing := [phrase for phrase in phrases if phrase not in text]), missing


def test_active_skills_use_model_independent_contract_with_current_overlays():
    shared = REPO / "skills" / "_shared"
    contract = (shared / "model-runtime-policy.md").read_text(encoding="utf-8")
    assert "Model-independent runtime contract" in contract
    for overlay in ("fable-5.md", "mythos-5.md", "opus-5.md", "sonnet-5.md"):
        assert (shared / "model-overlays" / overlay).is_file()
        assert f"model-overlays/{overlay}" in contract

    historical = (shared / "opus-4-7-policy.md").read_text(encoding="utf-8")
    assert "HISTORICAL BASELINE" in historical
    assert "current default" not in historical
    assert "scripts/token-audit.py` for token-level audit (uses" not in historical

    skill_bodies = list((REPO / "skills").glob("*/SKILL.md"))
    old_refs = [
        path
        for path in skill_bodies
        if "opus-4-7-policy.md" in path.read_text(encoding="utf-8")
    ]
    assert old_refs == []
    assert sum(
        "model-runtime-policy.md" in path.read_text(encoding="utf-8")
        for path in skill_bodies
    ) >= 18


def test_subagent_policy_is_model_independent_without_losing_scope_barrier():
    skill = (
        REPO / "skills" / "subagent-driven-development" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "model-runtime-policy.md" in skill
    assert "Opus 4.7 default" not in skill
    assert "Scope-change barrier" in skill


def test_large_active_skills_have_early_compaction_recovery_contracts():
    missing = []
    marker = "**Compaction continuity:**"
    for path in sorted((REPO / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        proxy = (len(text) + 3) // 4
        intentionally_inert = (
            "disable-model-invocation: true" in text[:2000]
            and "user-invocable: false" in text[:2000]
        )
        if proxy > 4000 and not intentionally_inert:
            early = text[:20_000]
            marker_position = early.find(marker)
            recovery = (
                early[marker_position : marker_position + 1200]
                if marker_position >= 0
                else ""
            )
            if not (
                re.search(r"\bre-invoke\b", recovery, re.IGNORECASE)
                and re.search(r"\bstop and ask\b", recovery, re.IGNORECASE)
            ):
                missing.append((path.parent.name, proxy))

    assert missing == []


def test_compaction_validator_fails_without_recovery_and_kills_marker_mutation(
    tmp_path: Path,
):
    validator_path = REPO / "scripts" / "validate-skills.py"
    spec = importlib.util.spec_from_file_location("validate_skills_compaction", validator_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    def fixture(name: str, marker: str) -> Path:
        skill_dir = tmp_path / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            'description: "Use for a compaction fixture. Do NOT use elsewhere."\n'
            "---\n"
            f"{marker}\n"
            "# Fixture\n\n"
            + ("load-bearing tail instruction\n" * 700),
            encoding="utf-8",
        )
        return skill_dir

    absent, _ = module.score_skill(fixture("absent", ""))
    marker_only, _ = module.score_skill(
        fixture("marker-only", "**Compaction continuity:** arbitrary words")
    )
    present, _ = module.score_skill(
        fixture(
            "present",
            "**Compaction continuity:** re-invoke after compaction; if model "
            "invocation is unavailable, stop and ask the user to invoke it",
        )
    )

    assert absent["C1b_token_budget"] is False
    assert marker_only["C1b_token_budget"] is False
    assert present["C1b_token_budget"] is True


@pytest.mark.parametrize(
    "relative_path",
    [
        "skills/mcp-forge-build/scripts/build_history.py",
        "skills/threat-model/scripts/model_history.py",
        "skills/audit-skill/scripts/audit_history.py",
    ],
)
def test_history_emitters_never_invent_a_model(monkeypatch, relative_path: str):
    path = REPO / relative_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    provenance = module._model_provenance([])
    assert provenance == {
        "requested_model": "<unavailable>",
        "requested_model_source": "unavailable",
        "effective_model": "<unavailable>",
        "effective_model_source": "unavailable",
        "provider": "<unavailable>",
        "effort": "<unavailable>",
        "context_class": "<unavailable>",
        "claude_code_version": "<unavailable>",
        "fallback": "<unavailable>",
        "refusal": "<unavailable>",
    }

    monkeypatch.setenv("CLAUDE_MODEL", "claude-fable-5")
    provenance = module._model_provenance([])
    assert provenance["requested_model"] == "claude-fable-5"
    assert provenance["requested_model_source"] == "environment"
    assert provenance["effective_model"] == "<unavailable>"
    assert provenance["effective_model_source"] == "unavailable"


@pytest.mark.parametrize(
    "relative_path",
    [
        "skills/mcp-forge-build/scripts/build_history.py",
        "skills/threat-model/scripts/model_history.py",
        "skills/audit-skill/scripts/audit_history.py",
    ],
)
def test_history_emitters_preserve_switch_and_fallback_receipt(
    monkeypatch, relative_path: str
):
    path = REPO / relative_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    receipt = {
        "requested_model": "claude-opus-5",
        "effective_model": "claude-fable-5",
        "effective_model_source": "response_metadata",
        "provider": "anthropic",
        "effort": "high",
        "context_class": "1m",
        "claude_code_version": "2.1.226",
        "fallback": True,
        "refusal": False,
    }
    provenance = module._model_provenance([{"runtime_receipt": receipt}])

    assert provenance["requested_model"] == "claude-opus-5"
    assert provenance["requested_model_source"] == "runtime_receipt"
    assert provenance["effective_model"] == "claude-fable-5"
    assert provenance["effective_model_source"] == "response_metadata"
    assert provenance["fallback"] is True
    assert provenance["refusal"] is False
    assert provenance["claude_code_version"] == "2.1.226"

def test_utilization_path_scope_predicate_matches_the_authoritative_one():
    """bin/rule_utilization.py reimplements the paths: predicate so it can run
    standalone from any checkout without importing the hooks package. That is a
    deliberate duplication, which makes it a DRIFT RISK -- so assert the two agree
    on every real rule plus adversarial shapes, rather than trusting the comment
    that says they do.
    """
    spec = importlib.util.spec_from_file_location(
        "rule_utilization_probe", REPO / "bin" / "rule_utilization.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec: the module defines @dataclass classes, and dataclasses'
    # annotation resolution looks the module up in sys.modules. Without this the
    # import fails inside _process_class rather than anywhere informative.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    # every real rule
    checked = 0
    for path in sorted((REPO / "rules").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert module._is_path_scoped(text) == rule_budget.has_paths_frontmatter(text), (
            path.name
        )
        checked += 1
    assert checked >= 30, checked

    # adversarial shapes: the duplicate must not be laxer than the original
    for text, expected in (
        ("---\npaths:\n  - \"**/*.py\"\n---\nbody", True),
        ("no frontmatter at all", False),
        ("---\nname: x\n---\nbody", False),
        ("body\n---\npaths:\n  - x\n---\n", False),   # frontmatter must be FIRST
    ):
        assert module._is_path_scoped(text) is expected, (expected, text[:40])
        assert rule_budget.has_paths_frontmatter(text) is expected, (expected, text[:40])
