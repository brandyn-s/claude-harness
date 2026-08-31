#!/usr/bin/env python3
"""Apply fix-proposal agent output to a worktree (audit-fix Step 4).

Input: the proposal-workflow results — either the raw workflow output
JSON (the orchestrator return value) or an extracted results array.
Each result is {skill, fixes[], skipped[], notes} where a fix is
{idx, file, edits[{old_string,new_string}], note, updated_reproducer?}.

Contracts enforced:
  - edits apply only under skills/<proposing-skill>/ (scope guard);
    out-of-scope proposals are recorded as failures for orchestrator
    review, never applied
  - old_string must occur EXACTLY ONCE in the target file; zero or
    multiple occurrences fail that finding without writing
  - a single edit with old_string == "" CREATES the file (must not
    already exist); .py/.sh creations get the executable bit
  - DELETIONS are not expressible — agents must skip them; the
    orchestrator handles deletions manually after the full
    check-before-change reference grep (.github/workflows + settings
    included; a campaign-11 agent's deletion claim missed a .yml CI
    reference and would have broken validate.yml)
  - note/field-mismatch warning: when a fix's prose note mentions a
    replacement reproducer but the structured updated_reproducer field
    is absent, the finding is flagged (campaign 11: one agent described
    the predicate in prose only, costing a diagnose-and-patch cycle)

Output: a state JSON consumed by patch_worklist.py and batch_verdicts.py:
  {applied: {idx: [[file, n_edits|"created"]...]},
   failed: {idx: [[file, reason]...]},
   updated_reps: {idx: reproducer},
   skip_updated_reps: {idx: reproducer},   # corrected predicates on SKIPPED
                                           # findings (already-fixed-in-tree
                                           # with a decoupled tracker
                                           # reproducer); batch_verdicts
                                           # expects these to adjudicate STALE
   skipped: [[skill, idx, reason]...],
   warnings: [str...]}

A skipped entry may carry `updated_reproducer` (same nested object as a
fix's) — installed by patch_worklist so the tracker's predicate becomes
honest even though no edit was applied.

Usage:
  apply_fixes.py <results.json> <worktree-root> --state-out <state.json>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_NOTE_MENTIONS_REPRODUCER = re.compile(
    r"updated[ _-]reproducer|doc-state (?:predicate|reproducer)|"
    r"replacement (?:predicate|reproducer)", re.IGNORECASE)


def extract_results(doc):
    """Accept either the raw workflow output JSON or a bare results array."""
    if isinstance(doc, list):
        return doc
    for key in ("result", "returnValue", "value", "output"):
        inner = doc.get(key)
        if isinstance(inner, dict) and "results" in inner:
            return inner["results"]
    if "results" in doc:
        return doc["results"]
    return None


def apply_all(results, worktree: Path):
    applied, failed, updated_reps, skipped, warnings = {}, {}, {}, [], []
    # Corrected predicates supplied on SKIPPED findings (e.g. "already
    # fixed in-tree, but the tracker's reproducer is doc-decoupled and
    # fires forever — here is the honest one"). Kept separate from
    # `updated_reps` because these indices were NOT edited: batch_verdicts
    # must expect them to adjudicate STALE (the corrected predicate sees
    # the already-fixed tree) rather than STILL-FIRES. Before 2026-08-22
    # this channel didn't exist and agents put replacement predicates in
    # prose skip reasons, where nothing could install them.
    skip_updated_reps = {}

    for r in results:
        if not r:
            continue
        skill = r["skill"]
        for s in r.get("skipped") or []:
            skipped.append((skill, s["idx"], str(s.get("reason", ""))[:200]))
            if s.get("updated_reproducer"):
                skip_updated_reps[s["idx"]] = s["updated_reproducer"]
            elif _NOTE_MENTIONS_REPRODUCER.search(str(s.get("reason", ""))):
                warnings.append(
                    f"SKIP_NOTE_REPRODUCER {skill}/idx{s['idx']}: the skip "
                    f"reason describes a replacement reproducer but the "
                    f"structured updated_reproducer field is absent — the "
                    f"predicate exists only in prose and will not be "
                    f"installed in the tracker."
                )
        for fx in r.get("fixes") or []:
            idx = fx["idx"]
            rel = fx["file"]
            note = str(fx.get("note", ""))
            if fx.get("updated_reproducer") is None and _NOTE_MENTIONS_REPRODUCER.search(note):
                warnings.append(
                    f"NOTE_FIELD_MISMATCH {skill}/idx{idx}: the note describes a "
                    f"replacement reproducer but updated_reproducer is empty — "
                    f"the predicate likely exists only in prose; recover it "
                    f"before Layer A or the finding may not flip."
                )
            if not rel.startswith(f"skills/{skill}/"):
                failed.setdefault(idx, []).append((rel, "outside skill dir"))
                continue
            p = worktree / rel
            edits = fx["edits"]
            if len(edits) == 1 and edits[0]["old_string"] == "":
                if p.exists():
                    failed.setdefault(idx, []).append((rel, "create-file but exists"))
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(edits[0]["new_string"], encoding="utf-8")
                if rel.endswith((".py", ".sh")):
                    os.chmod(p, 0o755)
                applied.setdefault(idx, []).append((rel, "created"))
            else:
                if not p.exists():
                    failed.setdefault(idx, []).append((rel, "file missing"))
                    continue
                text = p.read_text(encoding="utf-8")
                ok = True
                for e in edits:
                    old, new = e["old_string"], e["new_string"]
                    n = text.count(old)
                    if n != 1:
                        failed.setdefault(idx, []).append(
                            (rel, f"old_string count={n}"))
                        ok = False
                        break
                    text = text.replace(old, new, 1)
                if ok:
                    p.write_text(text, encoding="utf-8")
                    applied.setdefault(idx, []).append((rel, len(edits)))
            if fx.get("updated_reproducer"):
                updated_reps[idx] = fx["updated_reproducer"]

    return applied, failed, updated_reps, skip_updated_reps, skipped, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", type=Path,
                    help="workflow output JSON (or extracted results array)")
    ap.add_argument("worktree", type=Path, help="worktree root to apply edits in")
    ap.add_argument("--state-out", type=Path, required=True,
                    help="where to write the apply-state JSON")
    args = ap.parse_args(argv)

    if not args.results.exists():
        print(f"error: results file not found: {args.results}", file=sys.stderr)
        return 2
    try:
        doc = json.loads(args.results.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: {args.results} is not valid JSON: {e}", file=sys.stderr)
        return 2
    results = extract_results(doc)
    if results is None:
        print(f"error: could not locate a results array in {args.results}",
              file=sys.stderr)
        return 2
    if not args.worktree.is_dir():
        print(f"error: worktree root not found: {args.worktree}", file=sys.stderr)
        return 2

    applied, failed, updated_reps, skip_updated_reps, skipped, warnings = apply_all(
        results, args.worktree)

    args.state_out.write_text(json.dumps({
        "applied": {str(k): v for k, v in applied.items()},
        "failed": {str(k): v for k, v in failed.items()},
        "updated_reps": {str(k): v for k, v in updated_reps.items()},
        "skip_updated_reps": {str(k): v for k, v in skip_updated_reps.items()},
        "skipped": skipped,
        "warnings": warnings,
    }, indent=1), encoding="utf-8")

    print(f"findings with edits applied: {len(applied)}")
    print(f"findings with failed edits:  {len(failed)}")
    for idx, fails in list(failed.items())[:10]:
        print(f"  idx {idx}: {fails}")
    print(f"updated reproducers: {len(updated_reps)}")
    print(f"skip-side updated reproducers: {len(skip_updated_reps)}")
    print(f"agent-skipped: {len(skipped)}")
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
