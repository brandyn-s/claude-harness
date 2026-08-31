#!/usr/bin/env python3
"""Layer D on real git history — measure the true VERIFIED-rate.

For each case ``{id, pre_ref, post_ref, finding}`` run
``fix_loop.verify_fix_against_refs`` (pre = parent, post = fix) and tally
the verdict. The cases file is hand-seeded from known fix-PRs — each PR's
bug encoded as a deterministic reproducer that fired pre-fix and should
not fire post-fix. This is a SCRIPT, not a CI gate: git-history dependent
and slow; the unit test exercises the logic on a synthetic repo.

Usage:
  python3 run_layer_d_history.py --repo /path/to/repo --cases cases.json [--out results.json]

cases.json schema:
  {"cases": [
     {"id": "PR979", "pre_ref": "<sha>^", "post_ref": "<sha>",
      "finding": {"skill": "...", "code": "...", "severity": "drift",
                  "label": "behavior-fix", "description": "...",
                  "reproducer": {"type": "grep", "command": "grep -q ... path"}}}
  ]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _oracle():
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "skills" / "_shared"))
    from oracle.finding import Finding  # noqa: E402
    from oracle.fix_loop import verify_fix_against_refs  # noqa: E402
    return Finding, verify_fix_against_refs


def verify_cases(repo_root, cases: list[dict]) -> list[dict]:
    """Run Layer D over each case; return one result row per case. A case
    whose reproducer errors is recorded as status ERROR, not dropped."""
    Finding, verify = _oracle()
    results: list[dict] = []
    for c in cases:
        row = {"id": c.get("id", ""), "status": "ERROR",
               "pre_fires": None, "post_fires": None, "error": ""}
        try:
            f = Finding.from_dict(dict(c["finding"]))
            r = verify(f, Path(repo_root), c["pre_ref"], c["post_ref"])
            row.update(status=r.status, pre_fires=r.pre_fires, post_fires=r.post_fires)
        except Exception as e:  # noqa: BLE001 — a broken case shouldn't abort the batch
            row["error"] = f"{type(e).__name__}: {e}"
        results.append(row)
    return results


def summarize(results: list[dict]) -> dict:
    n = len(results)
    verified = sum(1 for r in results if r["status"] == "VERIFIED")
    statuses = {r["status"] for r in results}
    return {
        "n": n,
        "verified": verified,
        "verified_rate": round(verified / n, 3) if n else 0.0,
        "by_status": {s: sum(1 for r in results if r["status"] == s) for s in statuses},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Layer D VERIFIED-rate over git history")
    ap.add_argument("--repo", required=True, help="repo to checkout refs from")
    ap.add_argument("--cases", required=True, help="cases JSON (see module docstring)")
    ap.add_argument("--out", help="write full results JSON here")
    args = ap.parse_args(argv)
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    results = verify_cases(args.repo, cases)
    summary = summarize(results)
    if args.out:
        Path(args.out).write_text(
            json.dumps({"summary": summary, "results": results}, indent=2),
            encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
