#!/usr/bin/env python3
"""Queue a PR for auto-merge and drive it to a verified terminal state.

Encodes the merge-queue recovery discipline from rules/git-hygiene.md
(2026-05-31 bare --auto, 2026-06-07 silent drops, 2026-06-11 no-cascade
drops): on this repo's merge queue, `gh pr merge --auto` can return
silently having armed legacy auto-merge, and a queued PR can drop back
to CLEAN-but-OPEN with both autoMergeRequest and mergeQueueEntry null —
sitting un-merged forever unless re-armed. 2026-06-12 session: three
PRs (#1194/#1196/#1198) each needed a manual re-arm in one session,
which is what promoted this loop from inline poll snippets to a script.

Behavior:
  arm `--auto` (bare — merge queues dictate strategy; non-queue repos
  REJECT bare --auto, so arm() falls back to `--auto --squash`), then poll:
    MERGED                      -> exit 0 (the ONLY success signal)
    --queue-only + armed/queued -> exit 0 with QUEUED (caller owns terminal poll)
    --queue-only + repo cannot arm auto-merge at all -> exit 7 UNQUEUEABLE
                                   (no protected-branch rules: QUEUED is
                                   unreachable; merge directly when green, or
                                   re-run without --queue-only to poll to
                                   MERGED via the clean-status direct merge)
    CLEAN + not queued          -> silent drop: re-arm and keep polling
    DIRTY                       -> exit 3 (conflicts; caller resolves —
                                   for marketplace/*.json + .claude-plugin/*.json
                                   the canonical resolution is merge main,
                                   run scripts/build-marketplace.py, commit)
    CLOSED                      -> exit 4
    BEHIND + armed + not queued -> update-branch (server-side) + re-arm
    anything else (BLOCKED/UNKNOWN/UNSTABLE) -> keep waiting (CI)
    timeout                     -> exit 2

BEHIND IS NOT A WAIT STATE. Classic (legacy) auto-merge never updates a
branch, so a BEHIND + armed + unqueued PR sits forever and the poll burns
its whole timeout — the same shape as the DRAFT case below, and the same
one-command fix (`gh pr update-branch`). git-hygiene.md documents this as
the 2026-06-12 PR #1224 behind-race; 2026-07-28 KB #1273 reproduced it
exactly (20 min, exit 2, state BEHIND/armed/unqueued the entire time).
Only BEHIND holds this property: BLOCKED/UNSTABLE/UNKNOWN really are
transient CI states that clear on their own.

Usage:
  pr-merge-verified.py <pr-number> [--repo org/repo] [--timeout-mins N]
                       [--queue-only]

INTERRUPTION: safe — every action is an idempotent re-arm or a read;
re-running resumes from current PR state.

INVOCATION: run bare or redirect output to a file — do NOT pipe to
tail/grep. A pipeline's exit code is the filter's (0), which MASKS this
script's exit (2 on timeout, 0 on MERGED); a piped + backgrounded run can
look merged when it actually timed out. Read the final stdout line
("... MERGED" vs "... timeout after N min") and verify state regardless.

  RECURRED 2026-07-25 (mcp-infra #685): invoked as
  `pr-merge-verified.py 685 ... 2>&1 | tail -25` under run_in_background.
  The script correctly returned 2; `tail` returned 0; the harness reported
  "exit code 0" and the PR was briefly believed merged when it had timed
  out still sitting in the queue. The prose warning above already existed
  and did not prevent it — hence --status-file, which makes the terminal
  outcome a FILE the caller can read instead of an exit code a pipe can
  swallow:

    pr-merge-verified.py <N> --repo <r> --status-file /tmp/merge.json
    # then: jq -e '.terminal == "MERGED"' /tmp/merge.json

  Prefer --status-file for ANY backgrounded or redirected invocation.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def _gh_exe():
    """Resolve `gh` the way the PLATFORM resolves it, not the way a shell does.

    `subprocess.run(["gh", ...])` is shell=False, so it reaches Win32
    CreateProcess directly — and CreateProcess searches PATH appending only
    `.exe`. PATHEXT (which is what makes a bare `gh` find `gh.cmd`) is a
    cmd.exe feature, NOT a kernel one, so a `.cmd`/`.bat` on PATH is simply
    invisible to a bare-name subprocess call.

    That is a real portability bug in its own right, and it also silently
    removed test coverage: scripts/test_pr_merge_verified.py seams `gh` by
    putting a fake earlier on PATH. Its first version wrote a shebang script
    (Unix-only); the fix added a `gh.cmd` shim on the theory that PATHEXT
    would find it. It does not — nothing here ever consults PATHEXT — so
    windows-2022 still saw `gh calls were: []` and every assertion ran
    against an empty command log, timing out instead of failing loudly.

    `shutil.which` is the portable resolver: it iterates PATHEXT on Windows
    (`.CMD` is in the default list) and is a plain PATH lookup on POSIX.
    Resolved per-call, not cached at import, so a test that mutates PATH is
    honoured regardless of import order.
    """
    return shutil.which("gh") or "gh"


def gh(args, check=False):
    p = subprocess.run([_gh_exe()] + args, capture_output=True, timeout=60)
    out = p.stdout.decode("utf-8", errors="replace")
    err = p.stderr.decode("utf-8", errors="replace")
    if check and p.returncode != 0:
        print(f"gh {' '.join(args)} failed: {err.strip()}", file=sys.stderr)
    return p.returncode, out, err


def pr_state(num, repo):
    rc, out, _ = gh(["pr", "view", str(num), "--repo", repo,
                     "--json", "state,mergeStateStatus,autoMergeRequest,isDraft"])
    if rc != 0:
        return None
    d = json.loads(out)
    return {
        "state": d.get("state"),
        "mss": d.get("mergeStateStatus"),
        # A DRAFT can never arm auto-merge: every arm attempt returns
        # "Pull request is a draft (enablePullRequestAutoMerge)" and the poll
        # then burns its full timeout on a PR that was never going to merge.
        # 2026-07-27 mcp-servers #884: the script polled 20 minutes, exited 0,
        # and reported nothing wrong -- only a terminal-state check caught that
        # state was still OPEN. Surfaced here so the caller fails fast with the
        # actual reason instead of a generic timeout.
        "draft": bool(d.get("isDraft")),
        "armed": d.get("autoMergeRequest") is not None,
        "queued": _in_merge_queue(num, repo),
    }


def _in_merge_queue(num, repo):
    """True if the PR holds a mergeQueueEntry. A queued PR can show
    autoMergeRequest=null + CLEAN while its merge_group checks run
    (observed PR #1199, position 2, AWAITING_CHECKS) — NOT the drop
    signature. The true silent drop is CLEAN + BOTH fields null
    (git-hygiene 2026-06-11 addendum)."""
    owner, name = repo.split("/", 1)
    rc, out, _ = gh(["api", "graphql", "-f",
                     'query=query { repository(owner: "%s", name: "%s") '
                     '{ pullRequest(number: %d) { mergeQueueEntry { state } '
                     '} } }' % (owner, name, num)])
    if rc != 0:
        return False  # can't tell — let the CLEAN+unarmed re-arm proceed
    try:
        return (json.loads(out)["data"]["repository"]["pullRequest"]
                ["mergeQueueEntry"]) is not None
    except Exception:
        return False


def update_branch(num, repo):
    """Server-side merge of the base into the PR branch.

    The remedy for a BEHIND + armed + unqueued PR. Returns True on success.
    Note for the CALLER (not this script): afterwards the REMOTE branch
    carries a merge commit the local checkout lacks, so any further local
    commit needs `git pull --rebase origin <branch>` first or the push is
    rejected (git-hygiene 2026-06-12)."""
    rc, out, err = gh(["pr", "update-branch", str(num), "--repo", repo])
    msg = (out + err).strip()
    if rc == 0:
        return True
    # Already up to date is a benign race: another actor updated it first.
    if "up to date" in msg.lower() or "up-to-date" in msg.lower():
        return True
    print(f"PR #{num}: update-branch failed: {msg[:200] or '(silent)'}",
          file=sys.stderr)
    return False


# gh's rejection when the repo cannot HOLD an auto-merge request at all: the
# base branch has no protected-branch rules, so enablePullRequestAutoMerge is
# structurally unavailable (measured 2026-08-22 on claude-config: PRs #2051,
# #2062, and KB #1590 all failed both arm shapes with this text, while a plain
# `gh pr merge --squash` succeeded the moment checks were green).
_UNQUEUEABLE_MARKERS = (
    "does not have required protected branch rules",
    "protected branch rules not configured",
    "auto merge is not allowed for this repository",
)


def _is_unqueueable(msg):
    low = msg.lower()
    return any(m in low for m in _UNQUEUEABLE_MARKERS)


def arm(num, repo):
    """Try to arm auto-merge. Returns (ok, unqueueable):
    ok          — armed, queued, or merged directly on the clean-status path.
    unqueueable — BOTH arm shapes were rejected because the repo cannot hold
                  an auto-merge request (no protected-branch rules / repo
                  setting off). QUEUED is unreachable on such a repo; the only
                  paths to MERGED are the clean-status direct merge below or
                  the caller merging directly once checks are green."""
    rc, out, err = gh(["pr", "merge", str(num), "--repo", repo, "--auto"])
    msg = (out + err).strip()
    # "already queued" / silent exit 0 are both success per git-hygiene.
    # "clean status" means checks already passed pre-arm: merge directly
    # (bare for queue repos; --squash retry covers non-queue repos).
    if "clean status" in msg:
        rc2, _, _ = gh(["pr", "merge", str(num), "--repo", repo])
        if rc2 != 0:
            gh(["pr", "merge", str(num), "--repo", repo, "--squash"])
        return True, False
    if rc == 0 or "already queued" in msg:
        return True, False
    # NON-merge-queue repos reject bare --auto (gh demands an explicit
    # strategy; queues forbid one). Retry squash-armed. 2026-07-09:
    # KB #1118 sat CLEAN+unarmed to a blind 20-min timeout because this
    # path was silent — always log arm failures.
    rc3, out3, err3 = gh(["pr", "merge", str(num), "--repo", repo,
                          "--auto", "--squash"])
    msg3 = (out3 + err3).strip()
    if "clean status" in msg3:
        gh(["pr", "merge", str(num), "--repo", repo, "--squash"])
        return True, False
    if rc3 == 0 or "already queued" in msg3:
        return True, False
    print(f"PR #{num}: arm failed — bare --auto: {msg[:160] or '(silent)'} | "
          f"--auto --squash: {msg3[:160] or '(silent)'}", file=sys.stderr)
    return False, _is_unqueueable(msg) and _is_unqueueable(msg3)


def write_status(path, pr, repo, terminal, code):
    """Persist the TERMINAL outcome so a caller cannot mistake a masked exit
    code for success. Atomic (temp + os.replace) so a reader never sees a
    half-written file. Best-effort: a status-file failure must never change
    the merge outcome the caller is waiting on."""
    if not path:
        return
    try:
        payload = {"pr": pr, "repo": repo, "terminal": terminal, "exit": code}
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        print(f"warning: could not write status file {path}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pr", type=int)
    ap.add_argument("--repo", default="brandyn-s/claude-harness")
    ap.add_argument("--timeout-mins", type=float, default=20)
    ap.add_argument("--poll-secs", type=float, default=20)
    ap.add_argument("--status-file", default=None,
                    help="write terminal outcome as JSON here. Use this when "
                         "backgrounding or when stdout may be piped — the exit "
                         "code is then NOT trustworthy (see INVOCATION).")
    ap.add_argument(
        "--queue-only",
        action="store_true",
        help=(
            "return after auto-merge is durably armed or in the merge queue; "
            "the caller remains responsible for verifying terminal MERGED state"
        ),
    )
    args = ap.parse_args()

    def finish(terminal, code):
        write_status(args.status_file, args.pr, args.repo, terminal, code)
        return code

    # FAIL FAST ON A DRAFT. A draft cannot arm auto-merge, so without this the
    # loop polls to its full timeout and exits with a generic "timeout" that
    # hides the real, one-command-fixable reason. Checked BEFORE arm() so the
    # caller is told what to do rather than watching 20 minutes of no-ops.
    pre = pr_state(args.pr, args.repo)
    if pre and pre.get("draft") and pre.get("state") == "OPEN":
        print(f"PR #{args.pr}: DRAFT — auto-merge cannot arm on a draft. "
              f"Run `gh pr ready {args.pr} --repo {args.repo}` first "
              f"(a draft is often a deliberate hold; confirm before undrafting).",
              file=sys.stderr)
        return finish("DRAFT", 5)

    _, unqueueable = arm(args.pr, args.repo)
    if unqueueable and args.queue_only:
        # QUEUED is structurally unreachable here: the repo cannot hold an
        # auto-merge request, so a --queue-only caller would poll to timeout
        # (or exit on DIRTY) without ever getting its durable handoff. Fail
        # fast with the recipe instead (measured 2026-08-22, claude-config).
        print(f"PR #{args.pr}: UNQUEUEABLE — this repo cannot arm auto-merge "
              f"(no protected-branch rules / repo setting off). Merge directly "
              f"when checks are green: `gh pr merge {args.pr} --repo "
              f"{args.repo} --squash --delete-branch`, or re-run this helper "
              f"WITHOUT --queue-only to poll to terminal MERGED (it merges "
              f"directly on the clean-status path).", file=sys.stderr)
        return finish("UNQUEUEABLE", 7)
    deadline = time.monotonic() + args.timeout_mins * 60
    rearms = 0
    updates = 0
    s = None  # may stay None if the deadline has already passed

    while time.monotonic() < deadline:
        s = pr_state(args.pr, args.repo)
        if s is None:
            time.sleep(args.poll_secs)
            continue
        if s["state"] == "MERGED":
            print(f"PR #{args.pr}: MERGED (re-arms needed: {rearms}, "
                  f"branch updates: {updates})")
            return finish("MERGED", 0)
        if s["state"] == "CLOSED":
            print(f"PR #{args.pr}: CLOSED without merge", file=sys.stderr)
            return finish("CLOSED", 4)
        if s["mss"] == "DIRTY":
            print(f"PR #{args.pr}: DIRTY — conflicts with main; resolve "
                  f"(generated marketplace files: merge main + "
                  f"build-marketplace.py + commit), then re-run.",
                  file=sys.stderr)
            return finish("DIRTY", 3)
        if s["mss"] == "BEHIND" and not s["queued"]:
            # NOT a transient CI state. Legacy auto-merge never updates the
            # branch, so this configuration is stable-forever and polling it
            # only spends the timeout. Update server-side, then re-arm (the
            # update creates a new head, which can drop the arm).
            if update_branch(args.pr, args.repo):
                updates += 1
                print(f"PR #{args.pr}: behind base — updated branch "
                      f"(#{updates}) and re-arming")
                arm(args.pr, args.repo)
            else:
                # Can't self-heal (e.g. permissions, or a conflict the
                # update surfaces). Report it instead of polling to timeout.
                print(f"PR #{args.pr}: BEHIND and update-branch failed — "
                      f"resolve manually, then re-run.", file=sys.stderr)
                return finish("BEHIND_STUCK", 6)
            time.sleep(args.poll_secs)
            continue
        if args.queue_only and (s["armed"] or s["queued"]):
            print(
                f"PR #{args.pr}: QUEUED "
                f"(armed={s['armed']}, merge_queue={s['queued']})"
            )
            return finish("QUEUED", 0)
        if s["mss"] == "CLEAN" and not s["armed"] and not s["queued"]:
            # The documented silent-drop signature: green, idle, and
            # holding NEITHER an autoMergeRequest NOR a mergeQueueEntry.
            if arm(args.pr, args.repo)[0]:
                rearms += 1
                print(f"PR #{args.pr}: re-armed after silent drop "
                      f"(#{rearms})")
        time.sleep(args.poll_secs)

    print(f"PR #{args.pr}: timeout after {args.timeout_mins} min "
          f"(state poll shows {s})", file=sys.stderr)
    return finish("TIMEOUT", 2)


if __name__ == "__main__":
    sys.exit(main())
