#!/usr/bin/env python3
"""Deploy-trigger probe. Classifies each push-triggered workflow that matches a
PR's diff as DEPLOY (declares a GitHub environment) or ci-only.

Errors are NOT suppressed: a probe whose failure looks like "no findings" is the
failure mode this is meant to avoid.
"""
import argparse
import base64
import fnmatch
import json
import subprocess
import sys

import yaml


def gh(args):
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} -> rc={p.returncode}: {p.stderr.strip()[:200]}")
    return p.stdout


def main(repo, pr):
    files = [line.strip() for line in gh(["pr", "diff", str(pr), "--repo", repo, "--name-only"]).splitlines() if line.strip()]
    print(f"  diff files ({len(files)}): {' '.join(files)}")

    names = json.loads(gh(["api", f"repos/{repo}/contents/.github/workflows?ref=main", "--jq", "[.[].name]"]))
    rows, errors = [], []
    for wf in names:
        try:
            content = gh(["api", f"repos/{repo}/contents/.github/workflows/{wf}?ref=main", "--jq", ".content"])
            body = base64.b64decode(content).decode("utf-8", "replace")
            d = yaml.safe_load(body)
        except Exception as e:                      # noqa: BLE001 - report, never swallow
            errors.append(f"{wf}: {type(e).__name__}: {e}")
            continue
        if not isinstance(d, dict):
            continue
        on = d.get(True) or d.get("on") or {}
        if not isinstance(on, dict):
            continue
        push = on.get("push") or {}
        if not isinstance(push, dict) or not push:
            continue
        pats = push.get("paths") or []
        if pats:
            matched = [f for f in files for g in pats
                       if fnmatch.fnmatch(f, g) or f.startswith(g.rstrip("*"))]
        else:
            matched = files if push.get("branches") else []
        if not matched:
            continue
        envs = [j.get("environment") for j in (d.get("jobs") or {}).values()
                if isinstance(j, dict) and j.get("environment")]
        rows.append((("DEPLOY" if envs else "ci-only"), d.get("name") or wf,
                     "yes" if pats else "NONE", envs))

    for kind, name, paths, envs in sorted(rows, key=lambda r: r[0] != "DEPLOY"):
        print(f"    {kind:8s} {str(name)[:46]:46s} paths={paths:4s} env={envs or '-'}")
    deploys = [r for r in rows if r[0] == "DEPLOY"]
    print(f"  matched={len(rows)}  DEPLOY={len(deploys)}  ci-only={len(rows) - len(deploys)}")
    if errors:
        print(f"  PARSE ERRORS ({len(errors)}) — probe coverage is incomplete:")
        for e in errors:
            print(f"    {e}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Classify push-triggered workflows matching a PR's diff as "
                    "DEPLOY (declares a GitHub environment) or ci-only.",
        epilog="Exit 0 always; read the DEPLOY count. A nonzero DEPLOY count means "
               "merging this PR deploys, and needs named authorization.",
    )
    ap.add_argument("repo", help="owner/name, e.g. example-org/mcp-infra")
    ap.add_argument("pr", help="pull request number")
    args = ap.parse_args()
    sys.exit(main(args.repo, args.pr))
