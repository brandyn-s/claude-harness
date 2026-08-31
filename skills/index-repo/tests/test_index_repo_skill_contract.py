"""Executable workflow contract tests for the index-repo skill."""

from pathlib import Path
import unittest


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_PATH = SKILL_DIR / "SKILL.md"
MANIFEST_PATH = SKILL_DIR / "manifest.yaml"


def section(text: str, start: str, end: str) -> str:
    """Return a bounded Markdown section, failing clearly if anchors drift."""
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


class IndexRepoExecutionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = SKILL_PATH.read_text(encoding="utf-8")
        self.manifest = MANIFEST_PATH.read_text(encoding="utf-8")

    def test_indexing_workflow_waits_for_verified_completion(self) -> None:
        frontmatter = self.skill.split("---", 2)[1]
        split_workflow = section(
            self.skill,
            "## Split backend (code-search + code-graph)",
            "## Audit mode (split backend)",
        )
        normalized_split = " ".join(split_workflow.split())

        self.assertIn(
            'git -C "$repo_path" rev-parse --show-toplevel',
            self.skill,
        )
        self.assertNotIn("SKIP Steps 1-8", self.skill)
        self.assertIn("SKIP the split-backend section", self.skill)

        for contract_fragment in (
            "claude plugin list --json",
            "codebase-search@example-code-intelligence",
            "installPath",
            "skills/index-repo/SKILL.md",
            "read it completely",
            "single release-bound workflow",
            "Do not reproduce",
        ):
            self.assertIn(contract_fragment, normalized_split)
        self.assertIn("<resolved-root>", split_workflow)

        cli_fallback = section(
            self.skill,
            "**CLI fallback (MCP disconnected):**",
            "## Split backend (code-search + code-graph)",
        )
        self.assertIn(
            "'{\"repo_path\": \"<path>\", \"mode\": \"full\", \"skip_report\": true}'",
            cli_fallback,
        )

    def test_split_lane_matches_released_search_graph_and_delta_contracts(self) -> None:
        frontmatter = self.skill.split("---", 2)[1]
        split_workflow = section(
            self.skill,
            "## Split backend (code-search + code-graph)",
            "## Audit mode (split backend)",
        )

        for delegated_tool in (
            "mcp__code-search__get_index_status",
            "mcp__code-graph__index_status",
        ):
            self.assertNotIn(delegated_tool, frontmatter)
            self.assertNotIn(delegated_tool, self.manifest)

        self.assertIn("rev-parse --show-toplevel", self.skill)
        self.assertNotIn('provider="voyage"', split_workflow)
        self.assertNotIn('provider="voyage-context"', split_workflow)

        for delta_field in (
            "files_added",
            "files_modified",
            "files_removed",
            "chunks_added",
            "chunks_removed",
            "index_delta.mode",
            "files_discovered",
            "files_changed",
            "files_unchanged",
        ):
            self.assertIn(delta_field, split_workflow)
        self.assertIn("non-gating lifecycle telemetry", split_workflow)
        self.assertIn("do not infer semantic equivalence", split_workflow)
        self.assertNotIn("peak RSS", split_workflow)

        self.assertIn("--graph-precision heuristic|scip|auto", self.skill)
        self.assertIn("--scip-policy preferred|required", self.skill)
        self.assertIn("--scip-index", self.skill)

    def test_unified_audit_reconciles_integrity_and_identity_with_precedence(self) -> None:
        audit = section(
            self.skill,
            "**Audit (`--audit`):**",
            "**CLI fallback (MCP disconnected):**",
        )

        self.assertIn(
            'python3 "$HOME/.claude/scripts/verify-indexes.py" --json',
            audit,
        )
        for verifier_field in (
            "code_graph_corruption",
            "code_search_corruption",
            "transient_locks",
        ):
            self.assertIn(verifier_field, audit)
        self.assertIn('status == "skip"', audit)

        precedence = (
            "**CORRUPT**",
            "**STALE-PATH**",
            "**IDENTITY-ERROR**",
            "**IDENTITY-MISSING**",
            "**STALE-SOURCE**",
            "**HEALTHY**",
            "**UNKNOWN**",
        )
        positions = [audit.index(marker) for marker in precedence]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('identity_status == "missing"', audit)
        self.assertIn(
            "index_repository(repo_path=<root_path>, mode=\"full\", skip_report=true)",
            audit,
        )

    def test_split_audit_reference_is_audit_only(self) -> None:
        reference = (SKILL_DIR / "references" / "validation-checks.md").read_text(
            encoding="utf-8"
        )
        tier_a_disk = section(
            reference,
            "**On-disk signals**",
            "**code-graph signals**",
        )

        for artifact in (
            "project_info.json",
            "chunk_ids.pkl",
            "code.index",
            "metadata.db",
            "fts5.db",
            "stats.json",
        ):
            self.assertIn(artifact, reference)
        self.assertIn("audit-only", reference)
        self.assertNotIn("Used by `/index-repo` Step 8", reference)
        self.assertIn("release-bound plugin workflow", reference)
        self.assertIn("<= 10 bytes", tier_a_disk)
        self.assertNotIn("is exactly 5 bytes", tier_a_disk)

    def test_reindex_remediation_delegates_to_release_bound_workflow(self) -> None:
        reference = (SKILL_DIR / "references" / "validation-checks.md").read_text(
            encoding="utf-8"
        )
        post_cleanup = reference[reference.index("## Post-cleanup re-index") :]
        self.assertIn("release-bound", post_cleanup)
        self.assertIn("skills/index-repo/SKILL.md", post_cleanup)
        self.assertNotIn('provider="voyage"', post_cleanup)
        self.assertNotIn('provider="voyage-context"', post_cleanup)

    def test_manifest_exposes_modes_outputs_and_side_effects(self) -> None:
        frontmatter = self.skill.split("---", 2)[1]
        self.assertIn("--graph-precision heuristic|scip|auto", frontmatter)
        self.assertIn("--scip-policy preferred|required", frontmatter)
        self.assertIn("--scip-index path", frontmatter)
        self.assertIn("mcp__code-search__index_directory", frontmatter)
        self.assertIn("mcp__code-search__index_directory", self.manifest)

        for contract_fragment in (
            "mode:",
            "values: [index, audit]",
            "graph_precision:",
            "values: [heuristic, scip, auto]",
            "scip_policy:",
            "values: [preferred, required]",
            "scip_index:",
            "index_summary",
            "index_validation_report",
            "index_audit_report",
            "remediation_plan",
            "writes_index_cache",
            "changes_active_code_search_project",
            "writes_repository_report_only_with_explicit_user_request",
        ):
            self.assertIn(contract_fragment, self.manifest)


if __name__ == "__main__":
    unittest.main()
