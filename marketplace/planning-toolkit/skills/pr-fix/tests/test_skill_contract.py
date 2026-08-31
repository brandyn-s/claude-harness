"""Text-level guardrails for the pr-fix operational contract."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SkillContractTest(unittest.TestCase):
    def test_skill_stays_below_mechanical_size_limit(self) -> None:
        words = (ROOT / "SKILL.md").read_text(encoding="utf-8").split()
        self.assertLessEqual(len(words), 5000)

    def test_pr_repair_uses_dedicated_worktree(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("dedicated worktree", text)
        self.assertNotIn('git stash --include-untracked -m "pr-fix-stash-<pr-number>"', text)
        self.assertNotIn("git checkout <headRefName>", text)

    def test_operational_docs_never_mutate_shared_checkout_in_place(self) -> None:
        documents = [ROOT / "SKILL.md", *(ROOT / "references").glob("*.md")]
        text = "\n".join(path.read_text(encoding="utf-8") for path in documents)
        self.assertNotIn("git stash", text)
        self.assertNotIn("git checkout", text)

    def test_branch_cleanup_carries_confirmed_sha_into_leased_delete(self) -> None:
        text = (ROOT / "references" / "branch-cleanup.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("git branch -r --merged", text)
        self.assertNotIn("gh api -X DELETE", text)
        self.assertIn("expected_sha", text)
        self.assertIn("--force-with-lease", text)

    def test_stale_filter_is_scoped_to_same_workflow(self) -> None:
        text = (ROOT / "references" / "stale-failure-filter.md").read_text(
            encoding="utf-8"
        )
        command = text[text.index("## Check 1"): text.index("## Stalled approval gates")]
        self.assertIn('--workflow "<workflow_name>"', command)

    def test_repo_policy_change_has_separate_confirmation(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = text[text.index("allow_auto_merge=false"): text.index("```", text.index("allow_auto_merge=false"))]
        self.assertIn("AskUserQuestion", policy)
        self.assertIn("one-off", policy)

    def test_iterate_contract_never_calls_absence_green(self) -> None:
        text = (ROOT / "references" / "iterate-mode.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("NO_CHECKS", text)
        self.assertIn("CANCELLED", text)
        self.assertIn("failureDetail", text)
        self.assertNotIn("If no failures: report success", text)
        self.assertNotIn("sorted list of failing check names", text)

    def test_worktree_fallback_never_builds_empty_negative_revision(self) -> None:
        text = (ROOT / "references" / "worktree-cleanup.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"$BRANCH" "^$UPSTREAM"', text)
        self.assertIn("DEFAULT_REF", text)
        self.assertIn('"$DEFAULT_REF..$BRANCH"', text)
        self.assertNotIn("worktree remove <exact-worktree-path> --force", text)

    def test_direct_mode_keeps_hydration_safety_gates(self) -> None:
        text = (ROOT / "references" / "direct-mode.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("headRefOid", text)
        self.assertIn("mergeQueueEntry", text)

    def test_manifest_declares_loaded_safety_rules_and_remote_effects(self) -> None:
        text = (ROOT / "manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("- worktree-by-default", text)
        self.assertIn("- security-confirmations", text)
        self.assertIn("pushes_to_remote", text)
        self.assertIn("deletes_branches", text)


if __name__ == "__main__":
    unittest.main()
