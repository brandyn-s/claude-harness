#!/usr/bin/env python3
"""Write the terminal-doc artifact when supergoal's /goal loop exits.
Reads state + event log; emits structured markdown + appends to the
cross-session bug ledger; commits via the same git+PR flow superplan
Step 5a uses.

Usage:
    write_terminal.py <state-dir-or-state-json> <exit-reason>

exit-reason values (rejected with exit 1 otherwise — see _is_valid_exit_reason):
    success | falsifier-<name>-triggered | budget-exhausted |
    plan-tampered | scorer-broken | stuck-no-progress

In headless mode (state["headless"] is true), the process exit code maps
the exit reason per references/headless.md:
    0=success, 10=falsifier-triggered, 11=budget-exhausted,
    12=plan-tampered, 13=scorer-broken, 14=stuck-no-progress, 1=other.
Setup-time exits (20=parse-failed, 21=prior-arcs-exist, 22=attestation-failed)
are emitted by parse_plan.py / check_prior_arcs.py respectively.

Sections produced:
    Header (date, plan, exit reason, turns, wallclock, advisory tokens)
    Per-phase freshness verdict
    Re-diagnosis (if exit != success)
    Retired hypothesis (grep-able, drives next-session prior-arc check)
    Named next-plan target
    Lineage (chain of prior arcs)
    Failure-mode audit (5 modes from evanflow: hallucinated, scope-creep,
        cascading, context-loss, tool-misuse) — agent self-reports
    Goodhart-probe verdict (if artifact_probe[] populated)

Also appends one row to ~/Documents/knowledge-base/plans/_bug_ledger.md
per cavekit's §B convention: Bn|date|root_cause|new_invariant.

Skips git+PR flow silently if KB has no .git or gh is unavailable; the
markdown is always written locally.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from state_io import locked_state, append_event, CorruptStateError


# Canonical exit_reason enum — kept in sync with references/terminal-doc.md
# §"When it fires" and references/headless.md §"Exit codes". `falsifier-*-triggered`
# is matched as a prefix (the falsifier's name varies).
VALID_EXIT_REASONS_LITERAL = frozenset({
    "success",
    "budget-exhausted",
    "plan-tampered",
    "scorer-broken",
    "stuck-no-progress",
})

# Runtime exit code map — references/headless.md "Exit codes" table.
# Setup-time codes (20/21/22) live in parse_plan.py / check_prior_arcs.py.
HEADLESS_EXIT_CODE = {
    "success": 0,
    "budget-exhausted": 11,
    "plan-tampered": 12,
    "scorer-broken": 13,
    "stuck-no-progress": 14,
    # falsifier-<name>-triggered handled separately (prefix match → 10)
}


def _is_valid_exit_reason(s):
    if s in VALID_EXIT_REASONS_LITERAL:
        return True
    # falsifier-<name>-triggered — name is plan-defined, but the suffix is fixed
    return bool(re.match(r"^falsifier-.+-triggered$", s))


def _exit_code_for(exit_reason):
    """Map exit_reason → process exit code per references/headless.md.
    Returns 1 for anything unmapped (defensive — validator runs first)."""
    if exit_reason in HEADLESS_EXIT_CODE:
        return HEADLESS_EXIT_CODE[exit_reason]
    if re.match(r"^falsifier-.+-triggered$", exit_reason):
        return 10
    return 1


def _is_test_plan(slug):
    """Test-fixture plans (minimal.plan and friends) exist to exercise the
    loop; their terminal docs are throwaway and must NOT be committed to the
    KB. RC4 (2026-05-29): a minimal.plan test loop committed 44 terminal docs
    as orphan-ancestor commits that the next session inherited as a 47-ahead
    parked branch."""
    return (slug.startswith("minimal.plan")
            or slug.startswith("test.")
            or "-test-fixture" in slug)


USAGE = (
    "usage: write_terminal.py <state-dir-or-state-json> <exit-reason>\n"
    "  Render the terminal-doc for a completed supergoal arc.\n"
    "  -h, --help  show this help message and exit"
)


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(USAGE)
        sys.exit(0)
    if len(sys.argv) != 3:
        sys.exit(USAGE)
    arg = Path(sys.argv[1]).expanduser()
    state_path = arg if arg.suffix == ".json" else arg / "state.json"
    exit_reason = sys.argv[2]

    if not _is_valid_exit_reason(exit_reason):
        sorted_known = sorted(VALID_EXIT_REASONS_LITERAL)
        sys.exit(
            f"ERROR: invalid exit_reason: {exit_reason!r}\n"
            f"  Allowed: {sorted_known} OR falsifier-<name>-triggered\n"
            f"  See references/terminal-doc.md for the canonical enum."
        )

    if not state_path.exists():
        sys.exit(f"state file not found: {state_path}\n  (run parse_plan.py first)")

    try:
        with locked_state(state_path) as state:
            missing_fields = [k for k in ("events_path", "plan_slug", "plan_path") if k not in state]
            if missing_fields:
                sys.exit(
                    f"state at {state_path} is missing required field(s): "
                    + ", ".join(repr(k) for k in missing_fields) + ".\n"
                    "  This usually means parse_plan.py never completed for this plan, "
                    "or the state file is a stale stub. Re-run parse_plan.py."
                )
            state["exit_reason"] = exit_reason
            state["exited_at"] = datetime.now(timezone.utc).isoformat()
            events_path = Path(state["events_path"])
            exit_turn = state.get("turn_budget_total", 0) - state.get("turn_budget_remaining", 0)
    except CorruptStateError as e:
        sys.exit(f"ERROR: {e}")

    # Release the active-arc pointer ATOMICALLY with the terminal exit. The
    # `type:agent` Stop hook keys off `~/.claude/supergoal/.active` (a single-line
    # path), NOT `exit_reason` — so stamping exit_reason without clearing .active
    # leaves a terminally-done arc's pointer dangling, and the hook then fires on
    # every UNRELATED later Stop ("plan never invoked / verification needed"),
    # because .active still points at a state file (per verification-hook.md:
    # "no .active OR points to a missing file → {ok:true, no-active-supergoal}").
    # Observed 2026-06-21: a mega-capture arc that exited success in-session left
    # .active set; the hook fired on a later /retro. Clear it here so terminal exit
    # and pointer-release can never diverge. Only clear if .active points at THIS
    # arc — never clobber a different live arc's pointer.
    # Resolve BOTH sides: parse_plan.py writes `.active` as str(state_path) (the
    # path AS PASSED, not canonicalized), while state_path here may differ in form
    # (~-expanded, symlinked, trailing slash). Comparing raw strings would silently
    # skip the clear on a form-mismatch — the same "clear didn't fire" class this
    # fix exists to kill. Resolve both so equality holds regardless of invocation form.
    active_ptr = state_path.parent.parent / ".active"
    try:
        if active_ptr.exists():
            pointed = Path(active_ptr.read_text(encoding="utf-8").strip()).expanduser().resolve()
            if pointed == state_path.expanduser().resolve():
                active_ptr.unlink()
    except OSError:
        pass  # best-effort release; a stale pointer is recoverable, a crash here is not

    append_event(events_path, {
        "turn": exit_turn,
        "event": "exited",
        "exit_reason": exit_reason,
    })

    with locked_state(state_path) as state:
        snapshot = dict(state)

    _print_summary(snapshot, exit_reason)

    # Headless invocation maps exit_reason → process exit code so the outer
    # /loop or cron scheduler can switch on it (per references/headless.md).
    # Interactive runs always exit 0 — the human reads the terminal doc.
    headless = bool(snapshot.get("headless"))
    final_code = _exit_code_for(exit_reason) if headless else 0

    # SUPERGOAL_PLANS_DIR redirects the terminal doc + bug ledger away from
    # the real KB. Tests MUST set it to a tmp dir: the RC4 fix (2026-05-29)
    # stopped test runs from committing, but their local writes still
    # polluted the production plans/ tree (B38-B52 ledger noise + terminal
    # doc rewrites, found by /pr-fix dirty-tree discovery 2026-06-12).
    override = os.environ.get("SUPERGOAL_PLANS_DIR")
    plans_dir = Path(override) if override else (
        Path.home() / "Documents" / "knowledge-base" / "plans")
    if not plans_dir.exists():
        print(f"TERMINAL-DOC: skipped (no {plans_dir})")
        return final_code

    slug = snapshot["plan_slug"]
    terminal_path = plans_dir / f"{slug}-terminal.md"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if terminal_path.exists():
        existing = terminal_path.read_text(encoding="utf-8")
        m = re.search(r"^\*\*Exit reason\*\*:\s*(.+)$", existing, re.MULTILINE)
        existing_reason = m.group(1).strip() if m else "?"
        if existing_reason == exit_reason:
            print(f"TERMINAL-DOC: {terminal_path} already exists with same exit_reason; idempotent (no rewrite)")
            return final_code
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_path = plans_dir / f"{slug}-terminal-{existing_reason}-{ts}.md"
        terminal_path.rename(archive_path)
        # ASCII '->' instead of '→' so this print survives subprocess
        # stdout decode on Windows (cp1252 default; can't encode U+2192).
        print(f"TERMINAL-DOC: archived prior exit ({existing_reason} -> {exit_reason}) to {archive_path.name}")

    body = _render(snapshot, exit_reason, today)
    terminal_path.write_text(body, encoding="utf-8")
    print(f"TERMINAL-DOC: wrote {terminal_path}")

    _append_bug_ledger(plans_dir, slug, today, exit_reason, snapshot)

    # Test-fixture plans write the terminal doc locally (above) but must NOT
    # commit/PR it — committing on every test iteration spammed the KB with
    # dozens of orphan-ancestor commits (RC4, 2026-05-29).
    if _is_test_plan(slug):
        print(f"TERMINAL-DOC: {slug} is a test-fixture plan; wrote locally, skipping commit+PR")
        return final_code

    _commit_and_pr(plans_dir.parent, terminal_path, slug, exit_reason)
    return final_code


def _print_summary(state, exit_reason):
    print(f"SUPERGOAL EXIT: {exit_reason}")
    print(f"  plan: {state.get('plan_path', '?')}")
    total = state.get('turn_budget_total', 0)
    remaining = state.get('turn_budget_remaining', 0)
    print(f"  turns: {total - remaining}/{total}")
    print(f"  wallclock: {state.get('wallclock_used_seconds', 0)}s/{state.get('time_budget_seconds', 0)}s")
    print(f"  tokens (advisory): {state.get('tokens_used_advisory', '?')}/{state.get('token_budget_advisory', '?')}")
    print(f"  last verified at: {state.get('last_verified_at')}")


def _render(state, exit_reason, today):
    falsifier_match = re.match(r"falsifier-(.+?)-triggered", exit_reason)
    triggered_falsifier = falsifier_match.group(1) if falsifier_match else None
    lineage = state.get("lineage", [])
    total = state.get('turn_budget_total', 0)
    remaining = state.get('turn_budget_remaining', 0)
    turns_used = total - remaining

    parts = [
        f"# Terminal doc: {state.get('plan_slug', '?')}\n",
        f"**Date**: {today}",
        f"**Plan**: `{state.get('plan_path', '?')}`",
        f"**Exit reason**: {exit_reason}",
        f"**Turns**: {turns_used}/{total}",
        f"**Wallclock**: {state.get('wallclock_used_seconds', 0)}s / {state.get('time_budget_seconds', 0)}s budget",
        f"**Tokens (advisory)**: {state.get('tokens_used_advisory', '?')}/{state.get('token_budget_advisory', '?')}",
        "",
        "## Per-phase freshness verdict",
        "",
    ]
    baseline = state.get("baseline")
    if baseline:
        parts.append(f"- Phase 3.5 baseline at start: currently={baseline['currently_N']}, expected={baseline['expected_M']}")
    parts.append(f"- Last verified at: {state.get('last_verified_at') or 'never'}")
    parts.extend(["", "## Re-diagnosis", ""])
    if triggered_falsifier:
        parts.append(f"Falsifier `{triggered_falsifier}` triggered. Re-diagnosis required.")
    elif exit_reason == "budget-exhausted":
        parts.append("Budget exhausted before demo achieved. Either predicted lift was too optimistic or mechanism is wrong.")
    elif exit_reason == "scorer-broken":
        parts.append("Verifier itself failed (scorer crashed mid-run). Human review of metric_command output required before re-attempting.")
    elif exit_reason == "stuck-no-progress":
        parts.append("3+ consecutive turns showed no metric improvement. Agent was looping without advancing.")
    elif exit_reason == "plan-tampered":
        parts.append("Plan SHA-256 changed mid-loop. Re-attest if change was intentional.")
    elif exit_reason == "success":
        parts.append("Demo achieved. No re-diagnosis required.")
    parts.extend(["", "## Retired hypothesis", ""])
    if exit_reason != "success":
        parts.append(f"Plan's proposed mechanism: (extract from {state['plan_path']})")
        parts.append(f"Did not move: {','.join(state.get('metric_names', []))}")
    else:
        parts.append("Hypothesis confirmed; not retired.")
    parts.extend(["", "## Named next-plan target", ""])
    if exit_reason != "success":
        parts.append("(Fill in: what should a successor plan investigate? Be specific — substrate, layer, mechanism. Avoid 'investigate further'.)")
    else:
        parts.append("N/A — demo achieved.")
    parts.extend(["", "## Lineage", ""])
    if lineage:
        parts.append(f"Arc {len(lineage) + 1} in a chain on these metrics:")
        for i, p in enumerate(lineage, 1):
            parts.append(f"  {i}. `{p}`")
        parts.append(f"  {len(lineage) + 1}. `{state['plan_path']}` (this attempt)")
    else:
        parts.append("First attempt on these metrics. No prior arcs.")
    parts.extend(["", "## Failure-mode audit (5 modes)", ""])
    parts.append("Self-report on which failure modes manifested during the loop (evanflow convention):")
    parts.append("")
    parts.append("- [ ] **Hallucinated actions**: agent invoked tools that didn't exist or with invalid args")
    parts.append("- [ ] **Scope creep**: agent changed files outside the plan's named slice")
    parts.append("- [ ] **Cascading errors**: a single failure produced repeated retries against the same broken state")
    parts.append("- [ ] **Context loss**: agent forgot prior turns' decisions; re-litigated settled choices")
    parts.append("- [ ] **Tool misuse**: agent called tools in wrong order or with wrong inputs (e.g., Edit before Read)")
    parts.append("")
    parts.append("For any checked mode, name the turn(s) in events.jsonl where it manifested.")

    if state.get("artifact_probe"):
        parts.extend(["", "## Goodhart-probe verdict", ""])
        parts.append("`artifact_probe[]` should be re-run before declaring success; the metric measures progress, the probe measures the artifact.")
        parts.append("Captured artifact_probe commands:")
        for cmd in state["artifact_probe"]:
            parts.append(f"  - `{cmd}`")

    return "\n".join(parts) + "\n"


def _append_bug_ledger(plans_dir, slug, today, exit_reason, state):
    if exit_reason == "success":
        return
    ledger = plans_dir / "_bug_ledger.md"
    next_n = 1
    if ledger.exists():
        existing = ledger.read_text(encoding="utf-8")
        ns = re.findall(r"^B(\d+)\|", existing, re.MULTILINE)
        if ns:
            next_n = max(int(n) for n in ns) + 1
    else:
        ledger.write_text("# Cross-session bug ledger (cavekit §B convention)\n\n", encoding="utf-8")
    metric_names = ",".join(state.get("metric_names", [])) or "?"
    root_cause = f"exit:{exit_reason}; mechanism in {slug} did not move {metric_names}"
    new_invariant = "(fill in once a successor plan retires the mechanism)"
    row = f"B{next_n}|{today}|{root_cause}|{new_invariant}\n"
    with ledger.open("a", encoding="utf-8") as f:
        f.write(row)
    print(f"BUG-LEDGER: appended B{next_n} to {ledger}")


def _commit_and_pr(kb_root, terminal_path, slug, exit_reason):
    if not (kb_root / ".git").exists():
        print("TERMINAL-DOC: KB has no .git; skipping commit + PR")
        return
    # Stage ONLY this plan's terminal artifacts + the bug ledger. NEVER
    # `git add -A` — it sweeps unrelated dirty files in the shared KB working
    # tree into the terminal commit (rules/git-hygiene.md: stage specific files
    # by name; RC4 2026-05-29 collateral-sweep + orphan-ancestor accumulation).
    plans_dir = kb_root / "plans"
    candidates = [terminal_path,
                  *sorted(plans_dir.glob(f"{slug}-terminal-*.md")),
                  plans_dir / "_bug_ledger.md"]
    rel = [str(p.relative_to(kb_root)) for p in candidates if p.exists()]
    if not rel:
        print("TERMINAL-DOC: nothing to stage; skipping commit + PR")
        return
    # Remember the KB checkout's branch so we can return to it after the
    # squash-merge. Leaving it parked on terminal/<slug> is what produced the
    # 47-ahead orphan-ancestor branch the next session inherited (RC4).
    rc, orig_branch = _run(["git", "branch", "--show-current"], cwd=kb_root)
    orig_branch = orig_branch.strip() if rc == 0 else ""
    branch = f"terminal/{slug}"
    # Branch from FRESH origin/main, not the parked local main. A contended KB
    # checkout (concurrent sessions) can be many commits behind origin/main, so a
    # branch cut from local main produces a PR whose diff-vs-origin sweeps up every
    # already-merged-elsewhere file as a phantom change (2026-06-25: a stale-base
    # terminal-doc branch produced a 37-file PR #990 of other sessions' merged work;
    # closed + rebuilt as the clean single-file #991). Fetch first; cut from
    # origin/main when the fetch succeeds, else fall back to local main with a warning.
    fetch_rc, _ = _run(["git", "fetch", "origin", "main"], cwd=kb_root)
    if fetch_rc == 0:
        rc, out = _run(["git", "checkout", "-b", branch, "origin/main"], cwd=kb_root)
    else:
        print("TERMINAL-DOC: git fetch origin main failed; branching from local main "
              "(PR base may be stale — verify the diff is single-file before merge)")
        rc, out = _run(["git", "checkout", "-b", branch], cwd=kb_root)
    if rc != 0:
        if "already exists" in out:
            rc2, out2 = _run(["git", "checkout", branch], cwd=kb_root)
            if rc2 != 0:
                print(f"TERMINAL-DOC: git checkout {branch} failed: {out2}")
                _restore_branch(kb_root, orig_branch)
                return
        else:
            print(f"TERMINAL-DOC: git checkout failed: {out}")
            _restore_branch(kb_root, orig_branch)
            return
    _run(["git", "add", "--", *rel], cwd=kb_root)
    rc, out = _run(["git", "commit", "-m", f"terminal({slug}): {exit_reason}"], cwd=kb_root)
    if rc != 0:
        print(f"TERMINAL-DOC: git commit failed: {out}")
        _restore_branch(kb_root, orig_branch)
        return
    rc, _ = _run(["git", "push", "-u", "origin", branch], cwd=kb_root)
    if rc != 0:
        print("TERMINAL-DOC: push failed — file written but not pushed")
        _restore_branch(kb_root, orig_branch)
        return
    _run(["gh", "pr", "create", "--title", f"terminal({slug}): {exit_reason}",
          "--body", f"Auto-generated terminal doc for {slug}.\nExit reason: {exit_reason}"], cwd=kb_root)
    _run(["gh", "pr", "merge", "--auto", "--squash", "--delete-branch"], cwd=kb_root)
    print(f"TERMINAL-DOC: PR opened + auto-merge enabled for {branch}")
    _restore_branch(kb_root, orig_branch)


def _restore_branch(kb_root, orig_branch):
    """Return the shared KB checkout to its pre-commit branch so the next
    caller never inherits a parked terminal/<slug> checkout (RC4 prevention)."""
    if not orig_branch:
        return
    rc, out = _run(["git", "checkout", orig_branch], cwd=kb_root)
    if rc != 0:
        print(f"TERMINAL-DOC: could not restore branch {orig_branch}: {out}")


def _run(cmd, cwd):
    # Capture bytes + explicit UTF-8 decode. `text=True` uses cp1252 on
    # Windows (rules/platform-constraints.md INVARIANT
    # subprocess_bytes_then_decode_utf8); `gh` and `git` output can
    # contain Unicode (PR titles, branch names with non-ASCII chars).
    p = subprocess.run(cmd, cwd=cwd, capture_output=True)
    stdout = p.stdout.decode("utf-8", errors="replace")
    stderr = p.stderr.decode("utf-8", errors="replace")
    return p.returncode, (stdout + stderr).strip()


if __name__ == "__main__":
    sys.exit(main())
