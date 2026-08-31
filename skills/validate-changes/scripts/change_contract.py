#!/usr/bin/env python3
"""Deterministic change inventory and release verdict for /validate-changes."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Sequence


class ContractError(ValueError):
    """Raised for an invalid validation contract or inaccessible git state."""


def _git(repo: Path, args: Sequence[str], *, nul: bool = False):
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=False
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ContractError(message or f"git {' '.join(args)} failed")
    if nul:
        return [
            item.decode("utf-8", errors="surrogateescape")
            for item in result.stdout.split(b"\0")
            if item
        ]
    return result.stdout.decode("utf-8", errors="replace").strip()


def _paths(repo: Path, *args: str) -> list[str]:
    return sorted(set(_git(repo, (*args, "-z", "--"), nul=True)))


def build_change_inventory(
    repo: str | Path, base: str = "origin/main"
) -> dict[str, object]:
    """Return committed, staged, unstaged, and untracked change lanes."""

    repo_path = Path(repo).resolve()
    base_oid = _git(repo_path, ("rev-parse", base))
    head_oid = _git(repo_path, ("rev-parse", "HEAD"))
    commits_text = _git(repo_path, ("rev-list", "--reverse", f"{base}..HEAD"))
    commits = commits_text.splitlines() if commits_text else []
    committed_paths = _paths(repo_path, "diff", "--name-only", f"{base}...HEAD")
    staged_paths = _paths(repo_path, "diff", "--cached", "--name-only")
    unstaged_paths = _paths(repo_path, "diff", "--name-only")
    untracked_paths = sorted(
        set(
            _git(
                repo_path,
                ("ls-files", "--others", "--exclude-standard", "-z"),
                nul=True,
            )
        )
    )
    all_paths = sorted(
        set(committed_paths + staged_paths + unstaged_paths + untracked_paths)
    )
    return {
        "repo": str(repo_path),
        "base": base,
        "base_oid": base_oid,
        "head_oid": head_oid,
        "commits": commits,
        "commit_count": len(commits),
        "committed_paths": committed_paths,
        "staged_paths": staged_paths,
        "unstaged_paths": unstaged_paths,
        "untracked_paths": untracked_paths,
        "all_paths": all_paths,
    }


def release_verdict(
    *,
    regression: str,
    effectiveness: str,
    ab: str,
    vendor_dependent: bool = False,
    contract_status: str = "NOT_APPLICABLE",
) -> dict[str, str]:
    """Apply the vendor freshness gate before the existing phase gates."""

    regression_status = regression.upper()
    effectiveness_status = effectiveness.upper()
    ab_status = ab.upper()
    contract_input = contract_status.upper().replace(" ", "_")

    if vendor_dependent and contract_input != "VERIFIED":
        return {
            "contract": "CONTRACT UNVERIFIED",
            "verdict": "FIX FIRST",
            "reason": "current first-party runtime contract is not verified",
        }
    contract = "CONTRACT VERIFIED" if vendor_dependent else "NOT APPLICABLE"
    if regression_status != "PASS":
        return {
            "contract": contract,
            "verdict": "FIX FIRST",
            "reason": "regression failures must be resolved",
        }
    if effectiveness_status != "PASS":
        return {
            "contract": contract,
            "verdict": "FIX FIRST",
            "reason": "change does not produce intended behavior",
        }
    if ab_status == "FAIL":
        return {
            "contract": contract,
            "verdict": "REVERT",
            "reason": "change adds complexity without measurable benefit",
        }
    if ab_status not in {"PASS", "SKIPPED", "NOT_APPLICABLE"}:
        raise ContractError(f"unsupported A/B status: {ab}")
    return {
        "contract": contract,
        "verdict": "SHIP",
        "reason": "all applicable validation gates passed",
    }


def model_migration_contract(
    baseline_model: str,
    treatment_model: str,
    *,
    baseline_runtime: str | None = None,
    treatment_runtime: str | None = None,
) -> dict[str, str]:
    """Validate and preserve the exact identities used in a model A/B test."""

    baseline = baseline_model.strip()
    treatment = treatment_model.strip()
    if not baseline or not treatment:
        raise ContractError("baseline and treatment model IDs are required")
    if baseline == treatment:
        raise ContractError("baseline and treatment model IDs must differ")
    baseline_runtime_id = (baseline_runtime or "").strip()
    treatment_runtime_id = (treatment_runtime or "").strip()
    if not baseline_runtime_id or not treatment_runtime_id:
        raise ContractError("baseline and treatment runtime versions are required")
    return {
        "baseline_model": baseline,
        "treatment_model": treatment,
        "baseline_runtime": baseline_runtime_id,
        "treatment_runtime": treatment_runtime_id,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="inventory git changes")
    inventory.add_argument("--repo", default=".")
    inventory.add_argument("--base", default="origin/main")

    verdict = subparsers.add_parser("verdict", help="calculate release verdict")
    verdict.add_argument("--regression", required=True)
    verdict.add_argument("--effectiveness", required=True)
    verdict.add_argument("--ab", required=True)
    verdict.add_argument("--vendor-dependent", action="store_true")
    verdict.add_argument("--contract-status", default="NOT_APPLICABLE")

    migration = subparsers.add_parser(
        "migration", help="pin exact model and runtime identities for A/B testing"
    )
    migration.add_argument("--baseline-model", required=True)
    migration.add_argument("--treatment-model", required=True)
    migration.add_argument("--baseline-runtime", required=True)
    migration.add_argument("--treatment-runtime", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = build_change_inventory(args.repo, args.base)
        elif args.command == "verdict":
            result = release_verdict(
                regression=args.regression,
                effectiveness=args.effectiveness,
                ab=args.ab,
                vendor_dependent=args.vendor_dependent,
                contract_status=args.contract_status,
            )
        else:
            result = model_migration_contract(
                args.baseline_model,
                args.treatment_model,
                baseline_runtime=args.baseline_runtime,
                treatment_runtime=args.treatment_runtime,
            )
    except ContractError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
