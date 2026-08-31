"""Behavioral contract tests for pr-fix discovery and iteration state."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_fix_state.py"
SPEC = importlib.util.spec_from_file_location("pr_fix_state", SCRIPT)
assert SPEC and SPEC.loader
STATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATE)


class DiscoveryStateTest(unittest.TestCase):
    def test_dedupe_preserves_same_repo_name_and_pr_number_across_orgs(self) -> None:
        candidates = [
            {
                "number": 7,
                "repository": {
                    "name": "shared-name",
                    "nameWithOwner": "first-org/shared-name",
                },
            },
            {
                "number": 7,
                "repository": {
                    "name": "shared-name",
                    "nameWithOwner": "second-org/shared-name",
                },
            },
        ]

        self.assertEqual(len(STATE.dedupe_candidates(candidates)), 2)

    def test_dedupe_rejects_candidates_without_owner_qualified_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "nameWithOwner"):
            STATE.dedupe_candidates(
                [{"number": 7, "repository": {"name": "shared-name"}}]
            )

    def test_queued_clean_pr_is_not_ready(self) -> None:
        pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "mergeQueueEntry": {"state": "AWAITING_CHECKS"},
            "author": {"login": "me"},
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

        self.assertEqual(STATE.classify_pr(pr, actor_login="me"), "PR-QUEUED")

    def test_clean_unarmed_unqueued_pr_is_ready(self) -> None:
        pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "mergeQueueEntry": None,
            "author": {"login": "me"},
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

        self.assertEqual(STATE.classify_pr(pr, actor_login="me"), "PR-READY")

    def test_empty_string_conclusion_is_pending_not_ready(self) -> None:
        """A still-running check can report conclusion "" instead of null.

        Measured 2026-08-12 on code-search#266: `unit-tests` and
        `StepSecurity Harden-Runner` both returned "" while in_progress, in the
        same payload as null-conclusion siblings. A `None`-only pending test
        lets this PR reach PR-READY, and arming auto-merge before the status is
        genuinely CLEAN is the documented trigger for GitHub silently dropping
        the request. Everything else here is deliberately READY-shaped so the
        pending check is the ONLY thing this asserts on.
        """
        pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "mergeQueueEntry": None,
            "author": {"login": "me"},
            "statusCheckRollup": [
                {"conclusion": "SUCCESS"},
                {"conclusion": ""},
            ],
        }

        self.assertEqual(STATE.classify_pr(pr, actor_login="me"), "PR-PENDING")

    def test_whitespace_only_conclusion_is_also_pending(self) -> None:
        pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "mergeQueueEntry": None,
            "author": {"login": "me"},
            "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"conclusion": "  "}],
        }

        self.assertEqual(STATE.classify_pr(pr, actor_login="me"), "PR-PENDING")

    def test_missing_queue_observation_is_not_assumed_unqueued(self) -> None:
        pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "author": {"login": "me"},
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

        self.assertEqual(STATE.classify_pr(pr, actor_login="me"), "PR-UNKNOWN")

    def test_dependabot_is_recognized_under_every_login_spelling(self) -> None:
        """``gh search prs`` says ``dependabot[bot]``; ``gh pr view`` says
        ``app/dependabot``. A green unarmed Dependabot PR is PR-READY on either
        surface, so hydrated input must not fall through to No action."""

        for login in ("dependabot", "dependabot[bot]", "app/dependabot"):
            with self.subTest(login=login):
                pr = {
                    "state": "OPEN",
                    "isDraft": False,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                    "autoMergeRequest": None,
                    "mergeQueueEntry": None,
                    "author": {"login": login},
                    "statusCheckRollup": [{"conclusion": "SUCCESS"}],
                }

                self.assertEqual(
                    STATE.classify_pr(pr, actor_login="me"), "PR-READY"
                )

    def test_a_non_dependabot_bot_is_not_promoted_to_ready(self) -> None:
        """Negative control: the spelling set must not match any bot. Without
        this, broadening the match could auto-queue a third party's PR."""

        pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "mergeQueueEntry": None,
            "author": {"login": "app/stepsecurity-app"},
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

        self.assertNotEqual(STATE.classify_pr(pr, actor_login="me"), "PR-READY")

    def test_review_request_classification_is_preserved(self) -> None:
        pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeQueueEntry": None,
            "author": {"login": "review-author"},
            "reviewRequests": [{"login": "me"}],
            "reviewDecision": "REVIEW_REQUIRED",
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

        self.assertEqual(STATE.classify_pr(pr, actor_login="me"), "PR-REVIEW")


class BatchClassifyTest(unittest.TestCase):
    @staticmethod
    def _ready_pr(repo: str, number: int) -> dict:
        return {
            "repo": repo,
            "number": number,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "mergeQueueEntry": None,
            "author": {"login": "me"},
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        }

    def test_batch_output_binds_bucket_to_repo_and_number(self) -> None:
        """Per-PR invocation prints a bare bucket, so callers pair outputs to
        inputs by loop position — a skipped element silently shifts every
        later pairing. The batch output must carry its own identity."""

        conflicted = self._ready_pr("org/beta", 2)
        conflicted["mergeStateStatus"] = "DIRTY"
        conflicted["mergeable"] = "CONFLICTING"
        rows = STATE.classify_prs(
            [self._ready_pr("org/alpha", 1), conflicted],
            actor_login="me",
        )

        self.assertEqual(
            rows,
            [
                {"bucket": "PR-READY", "repo": "org/alpha", "number": 1},
                {"bucket": "PR-CONFLICT", "repo": "org/beta", "number": 2},
            ],
        )

    def test_batch_element_without_owner_qualified_repo_is_rejected(self) -> None:
        pr = self._ready_pr("alpha", 1)
        with self.assertRaisesRegex(ValueError, "owner-qualified"):
            STATE.classify_prs([pr], actor_login="me")

    def test_batch_element_without_number_is_rejected(self) -> None:
        pr = self._ready_pr("org/alpha", 1)
        del pr["number"]
        with self.assertRaisesRegex(TypeError, "number"):
            STATE.classify_prs([pr], actor_login="me")


class CheckStateTest(unittest.TestCase):
    def test_empty_check_list_is_not_green(self) -> None:
        self.assertEqual(STATE.classify_checks([]), "NO_CHECKS")

    def test_cancelled_only_check_list_is_not_green(self) -> None:
        checks = [{"name": "test", "bucket": "cancel"}]
        self.assertEqual(STATE.classify_checks(checks), "CANCELLED")

    def test_skipped_only_check_list_has_no_pass_evidence(self) -> None:
        checks = [{"name": "optional", "bucket": "skipping"}]
        self.assertEqual(STATE.classify_checks(checks), "NO_PASS_EVIDENCE")

    def test_at_least_one_pass_and_no_adverse_state_is_green(self) -> None:
        checks = [
            {"name": "test", "bucket": "pass"},
            {"name": "optional", "bucket": "skipping"},
        ]
        self.assertEqual(STATE.classify_checks(checks), "PASSED")

    def test_pending_and_failure_take_precedence_over_pass(self) -> None:
        self.assertEqual(
            STATE.classify_checks(
                [
                    {"name": "test", "bucket": "pass"},
                    {"name": "lint", "bucket": "pending"},
                ]
            ),
            "PENDING",
        )
        self.assertEqual(
            STATE.classify_checks(
                [
                    {"name": "test", "bucket": "pass"},
                    {"name": "lint", "bucket": "fail"},
                ]
            ),
            "FAILED",
        )

    def test_signature_changes_when_error_changes_under_same_check_name(self) -> None:
        first = [
            {"name": "test", "bucket": "fail", "failureDetail": "AssertionError: alpha"}
        ]
        second = [
            {"name": "test", "bucket": "fail", "failureDetail": "TypeError: beta"}
        ]

        self.assertNotEqual(
            STATE.failure_signature(first), STATE.failure_signature(second)
        )

    def test_signature_ignores_run_ids_and_timestamps(self) -> None:
        first = [
            {
                "name": "test",
                "bucket": "fail",
                "failureDetail": "2026-08-05T01:02:03Z run 123456 AssertionError: alpha",
            }
        ]
        second = [
            {
                "name": "test",
                "bucket": "fail",
                "failureDetail": "2026-08-05T02:03:04Z run 987654 AssertionError: alpha",
            }
        ]

        self.assertEqual(STATE.failure_signature(first), STATE.failure_signature(second))


class DestructiveStateTest(unittest.TestCase):
    def test_vetted_branches_require_same_sha_and_no_open_pr(self) -> None:
        state = {
            "live": [
                {"name": "fix/squash-merged", "sha": "a" * 40},
                {"name": "fix/moved", "sha": "b" * 40},
                {"name": "fix/open", "sha": "c" * 40},
                {"name": "main", "sha": "d" * 40},
                {"name": "trunk", "sha": "e" * 40},
            ],
            "merged": [
                {"headRefName": "fix/squash-merged", "headRefOid": "a" * 40},
                {"headRefName": "fix/moved", "headRefOid": "x" * 40},
                {"headRefName": "fix/open", "headRefOid": "c" * 40},
                {"headRefName": "main", "headRefOid": "d" * 40},
                {"headRefName": "trunk", "headRefOid": "e" * 40},
            ],
            "open": ["fix/open"],
            "default_branch": "trunk",
        }

        self.assertEqual(
            STATE.vetted_branches(state),
            [{"branch": "fix/squash-merged", "expected_sha": "a" * 40}],
        )

    def test_branch_must_still_match_confirmed_sha_and_have_no_open_pr(self) -> None:
        self.assertTrue(
            STATE.branch_is_deletable(
                expected_sha="a" * 40,
                current_sha="a" * 40,
                has_open_pr=False,
            )
        )
        self.assertFalse(
            STATE.branch_is_deletable(
                expected_sha="a" * 40,
                current_sha="b" * 40,
                has_open_pr=False,
            )
        )
        self.assertFalse(
            STATE.branch_is_deletable(
                expected_sha="a" * 40,
                current_sha="a" * 40,
                has_open_pr=True,
            )
        )

if __name__ == "__main__":
    unittest.main()
