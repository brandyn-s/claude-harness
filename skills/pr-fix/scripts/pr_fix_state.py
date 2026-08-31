"""Deterministic state helpers for the pr-fix skill.

The skill still performs GitHub and git I/O. This module owns the small but
safety-sensitive decisions that should not depend on prose interpretation:
candidate identity, merge-queue-aware PR readiness, check completion, failure
fingerprints, and destructive cleanup preconditions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

JsonObject = Mapping[str, Any]


def dedupe_candidates(candidates: Iterable[JsonObject]) -> list[JsonObject]:
    """Return the first candidate for each owner-qualified repository and PR."""

    unique: dict[tuple[str, int], JsonObject] = {}
    for candidate in candidates:
        repository = candidate.get("repository")
        if not isinstance(repository, Mapping):
            raise TypeError("candidate.repository must be an object")
        name_with_owner = repository.get("nameWithOwner")
        if not isinstance(name_with_owner, str) or "/" not in name_with_owner:
            raise ValueError("candidate.repository.nameWithOwner is required")
        number = candidate.get("number")
        if not isinstance(number, int):
            raise TypeError("candidate.number must be an integer")
        unique.setdefault((name_with_owner.casefold(), number), candidate)
    return list(unique.values())


def _login(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("login")
    return value.casefold() if isinstance(value, str) else ""


#: Bot logins render differently per GitHub surface. ``gh search prs`` returns
#: ``dependabot[bot]`` while ``gh pr view`` returns ``app/dependabot`` for the
#: same actor, so a single spelling silently fails on hydrated input. Measured
#: 2026-08-08: a green unarmed Dependabot PR classified NO_ACTION instead of
#: PR-READY because only the search spelling was matched.
_DEPENDABOT_LOGINS = frozenset(
    {"dependabot", "dependabot[bot]", "app/dependabot"}
)


def _is_dependabot(login: str) -> bool:
    """Recognize Dependabot across every surface's login spelling."""

    return login in _DEPENDABOT_LOGINS


def classify_pr(pr: JsonObject, *, actor_login: str) -> str:
    """Classify a hydrated PR, including an explicit GraphQL queue observation.

    ``mergeQueueEntry`` must be present even when its value is ``null``. Omitting
    the field means queue state was not observed, so a CLEAN/unarmed PR is kept
    unknown rather than being reprocessed as ready.
    """

    if pr.get("state") != "OPEN":
        return "DROP"
    if bool(pr.get("isDraft")):
        return "NO_ACTION"

    queue_observed = "mergeQueueEntry" in pr
    if queue_observed and pr.get("mergeQueueEntry") is not None:
        return "PR-QUEUED"

    checks = pr.get("statusCheckRollup") or []
    conclusions = {
        item.get("conclusion")
        for item in checks
        if isinstance(item, Mapping)
    }
    # A still-running check reports its conclusion as EITHER JSON null OR an
    # EMPTY STRING — both shapes occur in one `statusCheckRollup` payload, so a
    # `None`-only test silently drops the empty-string ones. Measured 2026-08-12
    # on code-search#266: `unit-tests` and `StepSecurity Harden-Runner` both came
    # back `""` while in_progress. That is not merely a mislabel — an unnoticed
    # pending check falls through to the PR-READY branch below, and arming
    # auto-merge BEFORE mergeStateStatus is CLEAN is the documented trigger for
    # GitHub silently dropping the auto-merge request
    # (memory/mergequeue-json-cannot-see-queue-entry.md). So this check being
    # wrong can CAUSE the stuck-PR condition this skill exists to clear.
    if any(c is None or not str(c).strip() for c in conclusions):
        return "PR-PENDING"

    author = _login(pr.get("author"))
    actor = actor_login.casefold().lstrip("@")
    authored_by_actor = author == actor
    dependabot = _is_dependabot(author)
    merge_state = pr.get("mergeStateStatus")

    if (
        "FAILURE" in conclusions
        and authored_by_actor
        and merge_state != "UNSTABLE"
    ):
        return "PR-FAIL"
    if merge_state == "DIRTY" and authored_by_actor:
        return "PR-CONFLICT"
    if (
        pr.get("mergeable") == "MERGEABLE"
        and merge_state == "CLEAN"
        and pr.get("autoMergeRequest") is None
        and (authored_by_actor or dependabot)
    ):
        return "PR-READY" if queue_observed else "PR-UNKNOWN"
    review_requests = {
        _login(request)
        for request in (pr.get("reviewRequests") or [])
        if isinstance(request, Mapping)
    }
    if (
        not authored_by_actor
        and actor in review_requests
        and pr.get("reviewDecision") != "APPROVED"
    ):
        return "PR-REVIEW"
    if (
        authored_by_actor
        and (
            pr.get("reviewDecision") == "CHANGES_REQUESTED"
            or merge_state == "BLOCKED"
        )
    ):
        return "PR-BLOCKED"
    return "NO_ACTION"


def classify_prs(
    prs: Sequence[JsonObject], *, actor_login: str
) -> list[dict[str, Any]]:
    """Classify a batch of hydrated PRs, binding each bucket to its identity.

    One-process batch classification exists because per-PR invocation loses
    the (repo, number) binding: ``classify-pr`` prints a bare bucket, so a
    caller pairing 63 outputs with 63 inputs by loop position has no defense
    against a skipped or reordered element. Each element must carry an
    owner-qualified ``repo`` and an integer ``number`` so the output is
    self-identifying.
    """

    results: list[dict[str, Any]] = []
    for pr in prs:
        if not isinstance(pr, Mapping):
            raise TypeError("each batch element must be an object")
        repo = pr.get("repo")
        if not isinstance(repo, str) or "/" not in repo:
            raise ValueError("each batch element requires owner-qualified repo")
        number = pr.get("number")
        if not isinstance(number, int):
            raise TypeError("each batch element requires an integer number")
        results.append(
            {
                "bucket": classify_pr(pr, actor_login=actor_login),
                "repo": repo,
                "number": number,
            }
        )
    return results


def classify_checks(checks: Sequence[JsonObject]) -> str:
    """Classify a complete ``gh pr checks --json`` snapshot.

    Green requires affirmative pass evidence. Empty, cancelled, skipped-only,
    unknown, and still-running snapshots are never treated as success.
    """

    if not checks:
        return "NO_CHECKS"
    buckets = {
        str(check.get("bucket", "")).casefold()
        for check in checks
        if isinstance(check, Mapping)
    }
    if buckets & {"pending"}:
        return "PENDING"
    if buckets & {"fail", "failing"}:
        return "FAILED"
    if buckets & {"cancel", "cancelled", "canceled"}:
        return "CANCELLED"
    allowed = {"pass", "passing", "skipping", "skipped"}
    if not buckets <= allowed:
        return "INDETERMINATE"
    if buckets & {"pass", "passing"}:
        return "PASSED"
    return "NO_PASS_EVIDENCE"


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?\b", re.IGNORECASE
)
_RUN_ID_RE = re.compile(
    r"\b(?:run|job|build)\s*[#:=]?\s*\d+\b", re.IGNORECASE
)


def normalize_failure_detail(detail: str) -> str:
    """Remove common per-run noise while retaining the actual diagnostic."""

    detail = _ANSI_RE.sub("", detail)
    detail = _TIMESTAMP_RE.sub("<timestamp>", detail)
    detail = _RUN_ID_RE.sub("<run-id>", detail)
    return " ".join(detail.casefold().split())


def failure_signature(checks: Sequence[JsonObject]) -> str:
    """Fingerprint failing check identity plus normalized diagnostic content."""

    failures: list[tuple[str, str]] = []
    for check in checks:
        if str(check.get("bucket", "")).casefold() not in {"fail", "failing"}:
            continue
        name = str(check.get("name", "")).strip()
        detail = check.get("failureDetail")
        if not name or not isinstance(detail, str) or not detail.strip():
            raise ValueError(
                "each failing check requires name and failureDetail from its log"
            )
        failures.append((name.casefold(), normalize_failure_detail(detail)))
    if not failures:
        raise ValueError("at least one failing check is required")
    payload = json.dumps(sorted(failures), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def branch_is_deletable(
    *, expected_sha: str, current_sha: str, has_open_pr: bool
) -> bool:
    """Return whether destructive deletion still matches confirmed state."""

    return bool(expected_sha) and expected_sha == current_sha and not has_open_pr


_STANDING_BRANCHES = {
    "main",
    "master",
    "dev",
    "develop",
    "staging",
    "stage",
    "prod",
    "production",
    "release",
    "preview",
}


def vetted_branches(state: JsonObject) -> list[dict[str, str]]:
    """Join live branches to merged PR heads and exclude protected live work."""

    live = state.get("live")
    merged = state.get("merged")
    open_heads = state.get("open")
    default_branch = state.get("default_branch")
    if not isinstance(live, list) or not isinstance(merged, list):
        raise TypeError("live and merged must be arrays")
    if not isinstance(open_heads, list):
        raise TypeError("open must be an array")
    if not isinstance(default_branch, str) or not default_branch:
        raise ValueError("default_branch must be a non-empty string")

    open_names = {
        item if isinstance(item, str) else item.get("headRefName")
        for item in open_heads
        if isinstance(item, (str, Mapping))
    }
    merged_pairs = {
        (str(item.get("headRefName", "")), str(item.get("headRefOid", "")))
        for item in merged
        if isinstance(item, Mapping)
    }

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in live:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", ""))
        sha = str(item.get("sha", ""))
        protected = (
            name == default_branch
            or name.casefold() in _STANDING_BRANCHES
            or name.casefold().startswith("release/")
            or name.startswith("gh-readonly-queue")
        )
        if (
            not name
            or not sha
            or protected
            or name in open_names
            or name in seen
            or (name, sha) not in merged_pairs
        ):
            continue
        seen.add(name)
        result.append({"branch": name, "expected_sha": sha})
    return sorted(result, key=lambda item: item["branch"])


def _read_json(path: str | None) -> Any:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("dedupe", "checks", "failure-signature", "vetted-branches"):
        child = subparsers.add_parser(name)
        child.add_argument("--input", help="JSON file; defaults to stdin")

    classify = subparsers.add_parser("classify-pr")
    classify.add_argument("--input", help="JSON file; defaults to stdin")
    classify.add_argument("--actor", required=True, help="authenticated login")

    classify_batch = subparsers.add_parser("classify-prs")
    classify_batch.add_argument("--input", help="JSON file; defaults to stdin")
    classify_batch.add_argument(
        "--actor", required=True, help="authenticated login"
    )

    args = parser.parse_args(argv)
    data = _read_json(args.input)
    if args.command == "dedupe":
        print(json.dumps(dedupe_candidates(data), indent=2, sort_keys=True))
    elif args.command == "checks":
        print(classify_checks(data))
    elif args.command == "failure-signature":
        print(failure_signature(data))
    elif args.command == "vetted-branches":
        print(json.dumps(vetted_branches(data), indent=2, sort_keys=True))
    elif args.command == "classify-pr":
        print(classify_pr(data, actor_login=args.actor))
    elif args.command == "classify-prs":
        for row in classify_prs(data, actor_login=args.actor):
            print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
