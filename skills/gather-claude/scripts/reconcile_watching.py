#!/usr/bin/env python3
"""Reconcile the gather-claude Watching set against upstream issue state.

WHY THIS EXISTS (retires the bulk `closed:>=DATE` intersection):
    Step 1b originally intersected the Watching numbers against a
    `gh issue list --search "closed:>=<last-run>"` list. That query's cost
    scales with the REPO's closure volume, not our Watching-set size — and
    anthropics/claude-code runs periodic stale-bot mass-triage waves that close
    hundreds of issues in a day. The list truncates before the relevant
    closures are even on the page: observed limit-capped at 100 (2026-06-11),
    at 400 (2026-07-23), and returning 0 at limit 500 (2026-07-18). A truncated
    closed-list SILENTLY under-reports closures -> a stale Watching row -> a
    compensating workaround kept for an already-fixed upstream bug. No
    `--limit` fixes a structurally-wrong query shape.

    The correct query is bounded by OUR set, not the repo's activity: ask
    "of these N specific numbers, what is each one's state?" via a GraphQL
    aliased batch (40 issues/query -> ~3-4 calls for ~128 numbers). Immune to
    the stale-bot wave, and fast. This was improvised as the fallback on the
    2026-07-20 and 2026-07-23 runs; this script makes it the primary path.

Usage:
    python3 reconcile_watching.py --since YYYY-MM-DD [REPORT_PATH]
    <watching-numbers> | python3 reconcile_watching.py --since YYYY-MM-DD -

    --since is the last run date. Closures on/after it are classified
    THIS-CYCLE; closures before it are STALE-MISSED (closed on a prior run but
    never pruned — the hygiene debt the bulk intersection kept accruing).

    REPORT_PATH default:
      ~/Documents/knowledge-base/research/claude-code-anthropic-intelligence.md
    Numbers are extracted with parse_watching.py's Item-column logic. Pipe a
    bare number set on stdin (`-`) if the report path is sandbox-blocked
    (macOS TCC ~/Documents) — same host caveat as parse_watching.py.

Requires: `gh` CLI (authenticated). One `gh api graphql` call per 40-number
chunk. Read-only.

Prints:
    - per-number state / stateReason / closedAt
    - three buckets: OPEN (keep), CLOSED THIS-CYCLE, CLOSED STALE-MISSED
    - a paste-ready list of numbers to PRUNE from Watching (all CLOSED),
      COMPLETED ones flagged separately (candidate REMOVE_WORKAROUND, not just
      a prune — a completed fix may retire one of our workarounds)
"""
import json
import os
import re
import subprocess
import sys

DEFAULT_REPORT = os.path.expanduser(
    "~/Documents/knowledge-base/research/claude-code-anthropic-intelligence.md"
)
OWNER, NAME = "anthropics", "claude-code"
CHUNK = 40  # GraphQL nodes per request — safe under the query node-limit
ISSUE_RE = re.compile(r"#(\d{4,6})\b")


def extract_numbers(text):
    """Item-column extraction, mirroring parse_watching.py (kept in sync)."""
    m = re.search(r"^##\s+Watching\b.*?(?=^##\s+\S)", text, re.MULTILINE | re.DOTALL)
    section = m.group(0) if m else text
    nums = set()
    for line in section.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = s.split("|")
        if len(cells) < 2:
            continue
        item = cells[1].strip()
        if set(item) <= {"-", " ", ":"}:
            continue
        nums.update(int(n) for n in ISSUE_RE.findall(item))
    if not nums:  # non-table input (bare list on stdin)
        nums = {int(n) for n in ISSUE_RE.findall(section)}
    return sorted(nums)


def watching_rows(text):
    """Return [(item_numbers, full_row_text)] for each ## Watching table row."""
    m = re.search(r"^##\s+Watching\b.*?(?=^##\s+\S)", text, re.MULTILINE | re.DOTALL)
    section = m.group(0) if m else text
    rows = []
    for line in section.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = s.split("|")
        if len(cells) < 2:
            continue
        item = cells[1].strip()
        if set(item) <= {"-", " ", ":"}:
            continue
        nums = [int(n) for n in ISSUE_RE.findall(item)]
        if nums:
            rows.append((nums, s))
    return rows


def classify_closed(text, closed):
    """Classify each closed NUMBER against its Watching ROW(s).

    The script reasons about NUMBERS; a row is prunable only when EVERY number
    in its Item cell is closed. Three consecutive runs (2026-07-24, 2026-08-06,
    2026-08-22) produced an all-noise stale-missed list whose members were
    already-annotated siblings of open canonicals — output that read as a
    paste-ready prune list and twice reached a user-facing plan with a wrong
    prune count. So the classification lives HERE now, not in an ad-hoc
    per-run snippet.

    Returns (prunable_rows, actionable_siblings, annotated_residue):
      prunable_rows       [(nums, row)] — every number in the row is closed
      actionable_siblings [n]           — closed sibling NOT yet annotated in
                                          its row's prose (annotate this run)
      annotated_residue   [n]           — closed sibling whose row already says
                                          "closed"; expected noise, no action

    Closed numbers not found in any table row (bare-number stdin input) are
    returned in actionable_siblings so they are never silently dropped.
    """
    closed_set = set(closed)
    prunable, actionable, residue = [], [], []
    seen = set()
    for nums, row in watching_rows(text):
        row_closed = [n for n in nums if n in closed_set]
        if not row_closed:
            continue
        if all(n in closed_set for n in nums):
            prunable.append((nums, row))
            seen.update(row_closed)
            continue
        annotated = "closed" in row.lower()
        for n in row_closed:
            if n in seen:
                continue
            (residue if annotated else actionable).append(n)
            seen.add(n)
    # Bare-number input has no table rows; never silently drop a closure.
    actionable.extend(n for n in closed if n not in seen)
    return prunable, actionable, residue


# A GraphQL aliased batch is ALL-OR-NOTHING at the `gh` exit-code level: one
# alias naming a number the repo cannot resolve (transferred/deleted issue) makes
# `gh api graphql` exit non-zero for the WHOLE chunk. The original code logged a
# warning and `continue`d, so every other number in that chunk vanished from the
# result and main() then reported all of them as "NOT FOUND (transferred/deleted)".
#
# MEASURED 2026-08-21: chunk 3 of a 142-number sweep failed on the single
# unresolvable #83731. The shipped code reported 22 numbers as transferred/deleted.
# Ground truth (recovered by bisecting the same chunk): 20 OPEN, 1 CLOSED
# COMPLETED (#85886, closed 2026-08-17), 1 genuinely unresolvable (#83731). So the
# bug BOTH fabricated 21 false closure-adjacent verdicts AND swallowed a real
# COMPLETED closure — precisely the "silently under-reports closures -> stale
# Watching row -> workaround kept for an already-fixed bug" failure this script
# exists to prevent.
#
# Two distinct non-zero causes must NOT be collapsed:
#   * a bad NUMBER  -> bisect to isolate it; siblings are recoverable
#   * a transport/auth/rate-limit error -> nothing is known about ANY number in
#     the chunk. Reporting those as "not found" would be the original bug wearing
#     a different hat, so they go to a loud UNVERIFIED bucket instead.
BAD_NUMBER_RE = re.compile(
    r"could not resolve to an? (issue|issue or pull request)", re.IGNORECASE
)


def _run_graphql(numbers):
    """One `gh api graphql` aliased-batch call. Seam for tests."""
    fields = "\n".join(
        f'  i{n}: issue(number: {n}) {{ number state stateReason closedAt }}'
        for n in numbers
    )
    query = (
        f'query {{\n repository(owner: "{OWNER}", name: "{NAME}") {{\n'
        f'{fields}\n }}\n}}'
    )
    return subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True,
    )


def _collect(res, out):
    """Merge a successful response's nodes into `out`. Null nodes are absent."""
    repo = (json.loads(res.stdout).get("data") or {}).get("repository") or {}
    for node in repo.values():
        if node is None:  # issue not found / transferred
            continue
        out[node["number"]] = {
            "state": node["state"],
            "stateReason": node.get("stateReason"),
            "closedAt": node.get("closedAt"),
        }


def _fetch(numbers, out, unverified, stats):
    """Resolve `numbers`, bisecting around any number the repo cannot resolve."""
    if not numbers:
        return
    res = _run_graphql(numbers)
    stats["calls"] += 1
    if res.returncode == 0:
        _collect(res, out)
        return
    err = (res.stderr or "").strip()
    if not BAD_NUMBER_RE.search(err):
        # Transport / auth / rate limit: state of these numbers is UNKNOWN.
        unverified.update(numbers)
        stats["errors"].append(f"{len(numbers)} number(s): {err[:160]}")
        return
    if len(numbers) == 1:
        return  # definitively unresolvable; falls out as NOT FOUND in main()
    mid = len(numbers) // 2
    _fetch(numbers[:mid], out, unverified, stats)
    _fetch(numbers[mid:], out, unverified, stats)


def graphql_batch(numbers):
    """Return ({number: {state, stateReason, closedAt}}, unverified, stats)."""
    out, unverified = {}, set()
    stats = {"calls": 0, "errors": []}
    for i in range(0, len(numbers), CHUNK):
        _fetch(numbers[i:i + CHUNK], out, unverified, stats)
    return out, unverified, stats


def main():
    args = sys.argv[1:]
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return
    since = None
    rest = []
    it = iter(args)
    for a in it:
        if a == "--since":
            since = next(it, None)
        else:
            rest.append(a)
    src = rest[0] if rest else DEFAULT_REPORT
    text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()

    numbers = extract_numbers(text)
    print(f"reconciling {len(numbers)} Watching numbers via GraphQL "
          f"({(len(numbers) + CHUNK - 1) // CHUNK} batch call(s))...", file=sys.stderr)
    state, unverified, stats = graphql_batch(numbers)
    print(f"...{stats['calls']} call(s) used "
          f"(bisecting retries included)", file=sys.stderr)

    # UNVERIFIED is not NOT-FOUND: a transport/auth failure tells us nothing about
    # these numbers, so they must not be pruned OR treated as still-open.
    missing = [n for n in numbers if n not in state and n not in unverified]
    open_, this_cycle, stale = [], [], []
    for n in numbers:
        s = state.get(n)
        if not s:
            continue
        if s["state"] == "OPEN":
            open_.append(n)
        else:
            closed_at = (s.get("closedAt") or "")[:10]
            bucket = this_cycle if (since and closed_at >= since) else stale
            bucket.append((n, s["stateReason"], closed_at))

    print(f"\nOPEN (keep): {len(open_)}")
    print(f"CLOSED this-cycle (since {since}): {len(this_cycle)}")
    for n, reason, at in sorted(this_cycle):
        print(f"  #{n} [{reason}] closed {at}")
    print(f"CLOSED stale-missed (before {since}, never pruned): {len(stale)}")
    for n, reason, at in sorted(stale):
        print(f"  #{n} [{reason}] closed {at}")
    if missing:
        print(f"NOT FOUND (transferred/deleted — investigate): "
              f"{' '.join('#'+str(n) for n in missing)}")
    if unverified:
        print(f"\n!! UNVERIFIED — {len(unverified)} number(s) whose state this run "
              f"could NOT determine (transport/auth/rate-limit, NOT absence). Do "
              f"NOT prune these and do NOT record them as open; re-run before "
              f"claiming a current-state sweep:")
        print(f"   {' '.join('#'+str(n) for n in sorted(unverified))}")
        for e in stats["errors"]:
            print(f"   cause: {e}")

    completed = [n for n, r, _ in this_cycle + stale if r == "COMPLETED"]
    closed_nums = sorted(n for n, _, _ in this_cycle + stale)
    # Per-ROW classification (a row is prunable only when EVERY number in its
    # Item cell is closed; a closed sibling of an open canonical is annotated,
    # not pruned — SKILL.md Step 1b). Before this lived in the script, the
    # candidates-only number list twice reached a user-facing plan as a wrong
    # prune count (2026-08-06: 10 reported / 0 prunable; 2026-08-22: 17 flagged,
    # all already-annotated residue).
    prunable, actionable, residue = classify_closed(text, closed_nums)
    print(f"\n# ROW CLASSIFICATION of {len(closed_nums)} closed number(s):")
    print(f"# PRUNABLE ROWS (every number closed): {len(prunable)}")
    for nums, _row in prunable:
        print(f"#   {' / '.join('#'+str(n) for n in nums)}  <- prune this row")
    print(f"# ANNOTATE (closed sibling, open canonical, NOT yet marked closed in "
          f"row prose): {len(actionable)}")
    for n in actionable:
        print(f"#   #{n}")
    print(f"# EXPECTED RESIDUE (already annotated in row prose — no action, will "
          f"re-flag every run by design): {len(residue)}")
    print(f"# COMPLETED (candidate REMOVE_WORKAROUND — verify the fix retires a "
          f"workaround, {len(completed)}): {' '.join('#'+str(n) for n in completed)}")


if __name__ == "__main__":
    main()
