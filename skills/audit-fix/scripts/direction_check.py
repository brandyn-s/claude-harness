#!/usr/bin/env python3
"""Mechanical fire-direction gate for /audit-fix Step 3 (pre-reverify).

For every finding the batch claims fixed (apply-state ``applied`` +
``skip_updated_reps`` + any ``--also-fixed`` indices), run its
reproducer — the PATCHED one, i.e. whatever reverify will actually
score — against BOTH trees and require:

    fires(pre-fix tree)  == True    (the bug was present before)
    fires(post-fix tree) == False   (the fix made it go quiet)

This is the check SKILL.md prose has demanded since 2026-06-16
("never trust the agent's reproducer type/exit; verify each one
resolves to fires == bug-present") — as a script instead of an
instruction, because the instruction kept being skipped: 2026-08-22,
the orchestrator ran reverify without it and 2 of 18 agent-supplied
``updated_reproducer``s were fire-direction INVERTED (grep_absent
firing on absence, i.e. only AFTER a correct fix), matching the 2-of-16
rate from 2026-06-16. A stable ~12% inversion rate is an authoring
property, not an anomaly; the gate has to be mechanical.

What each failure shape means:
  pre=False, post=False  → STALE-PRE: the predicate never saw the bug
                           (decoupled, or the fix pre-existed).
  pre=True,  post=True   → FIX-INEFFECTIVE or a decoupled/mention-grep
                           predicate the fix cannot flip (e.g. a fix
                           that QUOTES the retired string to deny it).
  pre=False, post=True   → INVERTED fire direction.
  ERROR (either tree)    → the instrument itself is broken.

Predicates run through the oracle's own ``Reproducer.fires()`` — never
a local reimplementation, so the verdict here is byte-identical to what
reverify computes (a private copy would drift; see
eval-shipping-discipline "commit the instrument").

Exit 0 — every checked finding is fire(pre) → quiet(post).
Exit 1 — one or more findings failed; one line each on stderr.
Exit 2 — operator error (missing file, unloadable worklist).

Usage:
  direction_check.py <patched-worklist.yaml> <apply-state.json>
      <pre-tree> <post-tree> [--also-fixed 0,9,13]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_oracle():
    """Import the shared oracle loader relative to this script
    (skills/audit-fix/scripts/ → skills/_shared/)."""
    shared = Path(__file__).resolve().parents[2] / "_shared"
    if not (shared / "oracle").is_dir():
        return None
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    from oracle.finding import load_findings  # noqa: E402
    return load_findings


def _indices(spec: str | None) -> set[int]:
    if not spec:
        return set()
    return {int(x) for x in spec.split(",") if x.strip()}


def check_direction(findings, expected_fixed, pre_tree: Path, post_tree: Path):
    """Return (ok_indices, failures). A failure is
    (idx, skill, code, shape, detail)."""
    ok, failures = [], []
    for i in sorted(expected_fixed):
        if i >= len(findings):
            failures.append((i, "?", "?", "OUT-OF-RANGE",
                             f"index {i} exceeds worklist size {len(findings)}"))
            continue
        f = findings[i]
        if f.reproducer.type == "manual":
            failures.append((i, f.skill, f.code, "MANUAL",
                             "manual reproducer cannot be direction-checked"))
            continue
        try:
            pre_fires, pre_ev = f.reproducer.fires(pre_tree)
        except Exception as e:  # timeout / instrument crash
            failures.append((i, f.skill, f.code, "ERROR",
                             f"pre-tree run failed: {e}"))
            continue
        try:
            post_fires, post_ev = f.reproducer.fires(post_tree)
        except Exception as e:
            failures.append((i, f.skill, f.code, "ERROR",
                             f"post-tree run failed: {e}"))
            continue
        if pre_fires and not post_fires:
            ok.append(i)
        elif not pre_fires and post_fires:
            failures.append((i, f.skill, f.code, "INVERTED",
                             f"fires only AFTER the fix — swap the fire "
                             f"direction (grep↔grep_absent / expected_exit); "
                             f"pre={pre_ev!r} post={post_ev!r}"))
        elif not pre_fires:
            failures.append((i, f.skill, f.code, "STALE-PRE",
                             f"never fired on the pre-fix tree — decoupled "
                             f"predicate or the fix pre-existed; pre={pre_ev!r}"))
        else:
            failures.append((i, f.skill, f.code, "STILL-FIRES-POST",
                             f"still fires on the fixed tree — fix "
                             f"ineffective, or the predicate matches the "
                             f"fix's own text (mention-grep on a denial); "
                             f"post={post_ev!r}"))
    return ok, failures


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worklist", type=Path,
                    help="the PATCHED worklist (post patch_worklist.py) — "
                         "its reproducers are what reverify will score")
    ap.add_argument("state", type=Path,
                    help="apply-state JSON from apply_fixes.py")
    ap.add_argument("pre_tree", type=Path,
                    help="checkout at the pre-fix base ref (e.g. a throwaway "
                         "`git worktree add <dir> <base-sha>`)")
    ap.add_argument("post_tree", type=Path,
                    help="the worktree the fixes were applied to")
    ap.add_argument("--also-fixed",
                    help="comma-separated extra indices fixed by the "
                         "orchestrator (same as batch_verdicts)")
    args = ap.parse_args(argv)

    for p in (args.worklist, args.state):
        if not p.is_file():
            print(f"error: not found: {p}", file=sys.stderr)
            return 2
    for p in (args.pre_tree, args.post_tree):
        if not p.is_dir():
            print(f"error: tree not found: {p}", file=sys.stderr)
            return 2

    load_findings = _load_oracle()
    if load_findings is None:
        print("error: skills/_shared/oracle not found relative to this "
              "script; run from a full claude-config checkout", file=sys.stderr)
        return 2

    findings = load_findings(args.worklist)
    state = json.loads(args.state.read_text(encoding="utf-8"))
    expected_fixed = {int(k) for k in (state.get("applied") or {})}
    expected_fixed |= {int(k) for k in (state.get("skip_updated_reps") or {})}
    expected_fixed |= _indices(args.also_fixed)

    if not expected_fixed:
        print("nothing to check: no applied/skip-updated/also-fixed indices")
        return 0

    ok, failures = check_direction(
        findings, expected_fixed, args.pre_tree, args.post_tree)

    print(f"direction check: {len(ok)} of {len(expected_fixed)} verified "
          f"fire(pre) → quiet(post)")
    for idx, skill, code, shape, detail in failures:
        print(f"  idx {idx} {skill}/{code} {shape}: {detail}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
