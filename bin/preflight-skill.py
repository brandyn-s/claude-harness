#!/usr/bin/env python3
"""Run every CI gate that a skills/ change can break, locally, in one command.

WHY THIS EXISTS
---------------
The `validate` workflow has 30 steps. A skill author who runs "the usual few"
locally still discovers the rest one CI round-trip at a time -- and each
round-trip is ~4 minutes of waiting to learn something a local check answers in
under a second.

Measured on this repo 2026-07-28: every gate a skills/ change can break runs
locally in ~8.5s (fast tier) or ~40s (full tier, adding the two >10s outliers).
The two incidents this tool prevents cost 2 and 3 CI cycles respectively:

  2026-06-14  /lab-review #1276  -- 3 cycles. Only validate-skills + audit-skill
              were run locally; the architecture drift gate and the cross-chain
              validator are separate Matrix-validate steps.
  2026-07-28  /gather-claude-endpoints #1740 -- 2 cycles. (1) `guardrails:` in a
              manifest was filled with prose, but it is a REFERENCE field --
              manifests/compile.py --check reported 4 DANGLING refs. (2) Adding a
              skill moved the count 105 -> 106, which architecture-drift-check.py
              gates on in ARCHITECTURE.md AND README.md.

Both were catchable in <1s. Neither was caught, because the correct gate set had
to be REMEMBERED rather than EXECUTED. This file makes it executable.

DESIGN NOTES
------------
- Gate definitions mirror `.github/workflows/tests.yml (this export ships gitleaks.yml, plugins.yml, tests.yml; the upstream tests.yml is not part of it)` step-for-step, with
  the CI step name recorded on each gate so a drift between this file and the
  workflow is greppable. `--list` prints the mapping.
- Every gate is gated on its EXIT CODE, never on grepping stdout. CI itself was
  fixed away from output-prefix coupling on 2026-07-26 for exactly this reason
  (a changed prefix silently disables the gate).
- `--fast` (default for the pre-push hook) drops only the two gates measured
  over 10s. A pre-push gate that takes 40s gets bypassed with --no-verify; one
  that takes 8s does not. That is the whole reason for the split.
- Preflight is READ-ONLY, and that is ENFORCED rather than aspirational:
  `scripts/test_preflight_skill.py::test_no_gate_mutates_the_tree` asserts that no
  gate carries `mutates=True`, and that the audit-skill gate passes
  --no-marketplace-check (its freshness probe RUNS build-marketplace.py; a --fast
  run left 4 modified files behind on 2026-07-28). The `mutates` field exists so
  that test has something to assert on — it is deliberately always False.
  DO NOT add a mutating gate. An earlier revision of this docstring described a
  `--include-marketplace` opt-in for mutating gates; it was never implemented and
  is NOT the design — the read-only contract replaced it. Someone implemented that
  stale paragraph on 2026-07-29 and the test correctly rejected it.
  The marketplace-sync check belongs to `.githooks/pre-push`, which runs it AFTER
  this (read-only) tool and cleans up after itself.
- CAVEAT on that ownership: pre-push only runs where `core.hooksPath` is wired, and
  that wiring is ONE-TIME PER CLONE. repo_sync.py sets it for the repos it manages,
  which does not include a second clone of claude-config — so a worktree cut from
  an unwired clone pushes with NO pre-push gating at all, silently skipping both
  the marketplace check and this tool. Live instance 2026-07-29: PR #1780 passed
  all current gates locally, pushed from a worktree of an unwired
  ~/Documents/GitHub/claude-config, and failed CI on marketplace drift. Check
  `git config --get core.hooksPath` when a push reaches CI ungated; for a one-off
  manual check run `python3 scripts/check-marketplace-sync.py` directly (standalone
  by design — it is deliberately NOT wired as a gate).

Exit codes: 0 all passed - 1 one or more gates failed - 2 usage/setup error.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Resolve the interpreter the same way .githooks/pre-push does: macOS has no
# bare `python` (Homebrew ships python3 only); Windows Git Bash may have only
# `python`. Hardcoding either breaks one platform's CI parity.
PY = shutil.which("python3") or shutil.which("python") or sys.executable
# CI deliberately invokes the pytest console script for scripts/ tests. Use the
# same entrypoint locally: `python -m pytest` prepends the repository root to
# sys.path and can hide import failures that the CI command exposes.
PYTEST = shutil.which("pytest") or "pytest"


@dataclass(frozen=True)
class Gate:
    key: str
    ci_step: str  # the tests.yml step name this mirrors -- keeps drift greppable
    cmd: list[str]
    slow: bool = False  # measured >10s; excluded from --fast
    mutates: bool = False  # writes to the tree; needs explicit opt-in
    why: str = ""
    env: dict[str, str] = field(default_factory=dict)


# Ordered cheapest-first so a typo-level failure surfaces before the 3s gates.
GATES: tuple[Gate, ...] = (
    Gate(
        "settings-json",
        "Validate settings.json",
        [PY, "-c", "import json;json.load(open('settings.json',encoding='utf-8'))"],
        why="a malformed settings.json locks out every tool at session start",
    ),
    Gate(
        "version-floor",
        "Validate automatic-update policy and version floors",
        [PY, "scripts/validate-version-floor.py"],
        why="the update policy and user/managed version floors must remain coherent",
    ),
    Gate(
        "cross-session-settings",
        "Validate restrictive cross-session settings",
        [
            PY,
            "scripts/runtime-qualification/validate_cross_session_settings.py",
        ],
        why="cross-session messages must refuse inbound delivery and isolate peers",
    ),
    Gate(
        "hook-paths",
        "Verify every registered hook script exists + no orphan test files",
        [PY, "scripts/validate-hook-paths.py"],
        why="a registered hook pointing at a missing script fails open, logging nothing",
    ),
    Gate(
        "rule-context-budget",
        "Validate aggregate ambient-rule context budget",
        [PY, "scripts/check-rule-context-budget.py"],
        why="individually-small ambient rules can still exhaust every main and child context",
    ),
    Gate(
        "agent-frontmatter",
        "Validate agent frontmatter against the documented subagent fields",
        [PY, "scripts/validate-agent-frontmatter.py", "--warn-unbounded"],
        why="unsupported agent fields read like enforcement while doing nothing",
    ),
    Gate(
        "marker-schemas",
        "Validate marker schemas + example writers",
        [PY, "-m", "manifests.test_validate_markers"],
        why="marker writers and their schemas drift apart silently",
    ),
    Gate(
        "skill-chains",
        "Skill cross-chain validator",
        [PY, "scripts/validate-skill-chains.py", "--strict"],
        why="a SKILL.md citing /a-skill-that-does-not-exist is a dead route",
    ),
    Gate(
        "manifest-refs",
        "Validate manifests (dangling refs, missing sources)",
        [PY, "manifests/compile.py", "--root", ".", "--check", "--no-reindex"],
        why="reference fields (requires_rules, guardrails) must name IDs, not prose "
        "-- prose there is 4 DANGLING errors (#1740)",
    ),
    Gate(
        "audit-self-test",
        "audit-skill self-test",
        [PY, "bin/audit-skill.py", "audit-skill"],
        why="audit-skill must satisfy its own published contract",
    ),
    Gate(
        "eval-harness",
        "Skill deterministic eval harness",
        [PY, "scripts/run-skill-evals.py"],
        why="a skill's own deterministic assertions must hold",
    ),
    Gate(
        "scripts-test-collection",
        "Run scripts/ tests",
        [PYTEST, "scripts/", "-q", "--collect-only"],
        why=(
            "mirrors CI's pytest console-script import semantics without executing "
            "the scripts suite, whose marketplace tests mutate generated files; "
            "python -m pytest can add the repository root to sys.path and produce "
            "a false local green during collection"
        ),
    ),
    Gate(
        "rubric",
        "Skill rubric validator (Anthropic-aligned, 14 checks)",
        [PY, "scripts/validate-skills.py", "--gate", "13"],
        why="CI gates on a THRESHOLD (13/14); a bare run without --gate under-reports",
    ),
    Gate(
        "triggers",
        "Skill trigger-conflict scan (model-independent strict mode)",
        [PY, "scripts/validate-skills.py", "--triggers"],
        why="two skills claiming the same trigger phrase route unpredictably",
    ),
    Gate(
        "arch-drift",
        "Architecture drift gate",
        [PY, "bin/architecture-drift-check.py"],
        why="ADDING A SKILL moves the count in ARCHITECTURE.md AND README.md (#1740)",
    ),
    Gate(
        "tool-drift",
        "Skill tool-declaration drift gate",
        [PY, "bin/reconcile-skill-tools.py", "--all"],
        why="a SKILL.md using a tool its frontmatter/manifest omits fails CI",
    ),
    Gate(
        "audit-all-strict",
        "audit-skill self-test (--all --strict)",
        # --no-marketplace-check keeps this gate READ-ONLY. `--all` implies
        # --check-marketplace, whose freshness probe RUNS build-marketplace.py and
        # therefore writes marketplace/ + .claude-plugin/ -- which would leave the
        # tree dirty and falsify this tool's "read-only" contract (the pre-push
        # hook orders preflight first precisely because it does not mutate).
        # Marketplace sync is not lost: the hook's own CHECK 1 verifies it
        # immediately after, and CI verifies it in its own step.
        [PY, "bin/audit-skill.py", "--all", "--strict", "--no-marketplace-check"],
        why="repo-wide mechanical lint; --strict makes drift (not just errors) exit non-zero",
    ),
    # --- measured >10s: excluded from --fast ---
    Gate(
        "scaffold-extended",
        "Validate marker schemas + example writers",
        [PY, "-m", "manifests.test_scaffold_extended"],
        slow=True,
        why="scaffold generators vs their extended fixtures (~13.5s)",
    ),
    Gate(
        "eval-non-vacuity",
        "Skill eval non-vacuity gate",
        [PY, "scripts/mutation-check-evals.py", "--all"],
        slow=True,
        why="mutation-checks that each eval would actually FAIL if the skill broke "
        "-- an eval that passes on a mutated skill asserts nothing (~18s)",
    ),
)

BY_KEY = {g.key: g for g in GATES}


def repo_root() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def run_gate(g: Gate, root: Path, verbose: bool) -> tuple[bool, float, str]:
    env = {**os.environ, **g.env}
    t0 = time.time()
    try:
        p = subprocess.run(
            g.cmd, cwd=root, capture_output=True, text=True, env=env, timeout=900
        )
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, "TIMEOUT after 900s"
    except FileNotFoundError as exc:
        # A missing gate script is a SETUP problem, not a passing gate. Never
        # silently skip -- that is how a gate quietly stops gating.
        return False, time.time() - t0, f"gate script not found: {exc}"
    dt = time.time() - t0
    if p.returncode == 0:
        return True, dt, p.stdout if verbose else ""
    tail = (p.stdout or "") + (p.stderr or "")
    return False, dt, tail.strip()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--fast",
        action="store_true",
        help="skip gates measured >10s (pre-push default; ~8.5s vs ~40s)",
    )
    ap.add_argument("--only", action="append", help="run only these gate key(s)")
    ap.add_argument("--list", action="store_true", help="list gates + their CI step, then exit")
    ap.add_argument("--verbose", action="store_true", help="show stdout of passing gates too")
    ap.add_argument(
        "--quiet-on-pass", action="store_true", help="print nothing when everything passes"
    )
    args = ap.parse_args()

    if args.list:
        print(f"{'KEY':<20} {'TIER':<6} CI STEP")
        for g in GATES:
            print(f"{g.key:<20} {'full' if g.slow else 'fast':<6} {g.ci_step}")
            if g.why:
                print(f"{'':<27} why: {g.why}")
        return 0

    root = repo_root()
    if root is None:
        print("preflight-skill: not inside a git repository", file=sys.stderr)
        return 2
    if not (root / "manifests" / "compile.py").exists():
        print(
            f"preflight-skill: {root} does not look like claude-config "
            "(manifests/compile.py missing)",
            file=sys.stderr,
        )
        return 2

    selected = list(GATES)
    if args.only:
        unknown = [k for k in args.only if k not in BY_KEY]
        if unknown:
            print(f"preflight-skill: unknown gate key(s): {unknown}", file=sys.stderr)
            print(f"  known: {', '.join(BY_KEY)}", file=sys.stderr)
            return 2
        selected = [BY_KEY[k] for k in args.only]
    elif args.fast:
        selected = [g for g in GATES if not g.slow]

    tier = "fast" if args.fast else "full"
    header = f"preflight-skill: {len(selected)} gates ({tier} tier)"
    if not args.quiet_on_pass:
        print(header)

    failures: list[tuple[Gate, str]] = []
    total = 0.0
    lines: list[str] = []
    for g in selected:
        ok, dt, out = run_gate(g, root, args.verbose)
        total += dt
        lines.append(f"  {'PASS' if ok else 'FAIL'}  {dt:6.2f}s  {g.key}")
        if args.verbose and out:
            lines.append("        " + out.replace("\n", "\n        "))
        if not ok:
            failures.append((g, out))

    if failures or not args.quiet_on_pass:
        if args.quiet_on_pass:
            print(header)
        print("\n".join(lines))
        print(f"  {'-' * 34}\n  {total:6.2f}s total")

    if failures:
        print(f"\n{len(failures)} GATE(S) FAILED — fix here, not after CI:\n")
        for g, out in failures:
            print(f"=== {g.key}  (CI step: {g.ci_step}) ===")
            if g.why:
                print(f"    why it gates: {g.why}")
            print(f"    repro: {' '.join(g.cmd)}")
            if out:
                body = out.splitlines()
                shown = body[-25:]
                if len(body) > len(shown):
                    print(f"    ... ({len(body) - len(shown)} earlier lines omitted)")
                for ln in shown:
                    print(f"    {ln}")
            print()
        if args.fast:
            print(
                "NOTE: --fast skipped the >10s gates "
                "(scaffold-extended, eval-non-vacuity). Run without --fast before pushing."
            )
        return 1

    if not args.quiet_on_pass:
        print("\nAll gates passed.")
        if args.fast:
            print(
                "NOTE: --fast skipped scaffold-extended + eval-non-vacuity. "
                "Run the full tier before opening a PR."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
