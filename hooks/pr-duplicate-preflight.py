"""PreToolUse:Bash — BLOCK `gh pr create` when one of YOUR open PRs already
touches the same files.

WHY THIS EXISTS
---------------
`rules/check-before-change.md` already requires it in prose: "check for a twin
before building and again before opening a PR." On 2026-08-27 I opened
example-labs-infra #345 to fix a red `ruff` S105 finding while MY OWN #343 — open
since 04:49 that morning, same single file, functionally identical diff — was
sitting there. #345 merged, #343 had to be closed as redundant, and applying it
afterwards would have conflicted.

The rule was loaded the whole time. Prose did not fire at the moment of action, so
this does.

WHAT IT CHECKS, AND WHY NOT SAME-BRANCH
---------------------------------------
The naive check — "is there already a PR from this branch" — would NOT have caught
the real incident: #343 was on a DIFFERENT branch touching the SAME file. `gh`
already errors on a same-branch duplicate, so that case needs no help. The signal
that matters is FILE OVERLAP with your own open PRs.

Only PRs authored by the same user are considered. Someone else's PR touching a
file you touch is normal collaboration, not your duplicate — blocking on that
would make the guard fire constantly and get bypassed reflexively.

FAIL-OPEN, BUT LOUDLY
---------------------
If `gh` is missing, unauthenticated, rate-limited, or the base ref is unfetched,
the check cannot run. It then ALLOWS and prints a note saying it did not run.
Blocking legitimate work because the guard's own tooling hiccuped is worse than
not having the guard; silently allowing while implying a check happened is worse
still. `security-review-before-pr.md` requires distinguishing "expected negative"
from "instrument failure" — the note is that distinction.

Exit codes:
  0 = allow (default, including every instrument-failure path)
  2 = BLOCK with stderr explanation (an open PR of yours overlaps these files)

Bypass: set CLAUDE_PR_ALLOW_DUPLICATE=1 for the intentional case (a deliberately
stacked PR, or a second independent change to a large shared file).
"""

import json
import os
import re
import subprocess
import sys

try:
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

PR_CREATE_RE = re.compile(r"\bgh\s+pr\s+create\b")
REPO_FLAG_RE = re.compile(r"--repo[=\s]+([\w.\-]+/[\w.\-]+)")
BASE_FLAG_RE = re.compile(r"--base[=\s]+([\w./\-]+)")
MAX_PRS = 20  # bounded: a hook must stay fast; 20 covers any realistic queue


def _run(args, cwd=None):
    """(stdout, ok). Never raises — every failure is an instrument failure."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=20, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return "", False
    if p.returncode != 0:
        return "", False
    return p.stdout, True


def changed_files(base):
    """Files this branch changes vs the base. ([], False) when undeterminable."""
    for ref in (f"origin/{base}", base):
        out, ok = _run(["git", "diff", "--name-only", f"{ref}...HEAD"])
        if ok:
            return [ln.strip() for ln in out.splitlines() if ln.strip()], True
    return [], False


def open_prs(repo):
    """Your open PRs with their changed files. (None) when undeterminable."""
    args = ["gh", "pr", "list", "--state", "open", "--author", "@me",
            "--limit", str(MAX_PRS), "--json", "number,title,headRefName,files"]
    if repo:
        args += ["--repo", repo]
    out, ok = _run(args)
    if not ok:
        return None
    try:
        return json.loads(out or "[]")
    except json.JSONDecodeError:
        return None


def overlapping(mine, prs, current_branch):
    """[(number, title, [shared paths])] for PRs that touch the same files.

    PURE — the whole decision lives here so it is testable without gh or network.
    A PR on the CURRENT branch is excluded: that is an update to the PR being
    created, not a duplicate of it, and gh reports that case itself.
    """
    # No `if not mine_set: return []` fast-path: mutation testing showed it is
    # INERT. With an empty set, `mine_set & theirs` is empty for every PR and the
    # function already returns [], so the branch changed no behaviour and could
    # not be tested. Dead code in a guard is worse than absent code — it reads as
    # a protection.
    mine_set = {p for p in mine if p}
    hits = []
    for pr in prs or []:
        if pr.get("headRefName") == current_branch:
            continue
        theirs = {f.get("path") for f in (pr.get("files") or []) if f.get("path")}
        shared = sorted(mine_set & theirs)
        if shared:
            hits.append((pr.get("number"), pr.get("title", ""), shared))
    return hits


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    command = (data.get("tool_input") or {}).get("command", "")
    if not PR_CREATE_RE.search(command):
        return 0
    if os.environ.get("CLAUDE_PR_ALLOW_DUPLICATE") == "1":
        return 0

    repo_m = REPO_FLAG_RE.search(command)
    base_m = BASE_FLAG_RE.search(command)
    repo = repo_m.group(1) if repo_m else None
    base = base_m.group(1) if base_m else "main"

    mine, ok = changed_files(base)
    if not ok:
        print(f"[pr-duplicate-preflight] NOT RUN: could not diff against "
              f"'{base}' — twin check skipped, verify by hand.", file=sys.stderr)
        return 0
    if not mine:
        return 0

    prs = open_prs(repo)
    if prs is None:
        print("[pr-duplicate-preflight] NOT RUN: could not list open PRs "
              "(gh missing/unauthenticated/rate-limited) — twin check skipped, "
              "verify by hand.", file=sys.stderr)
        return 0

    branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    hits = overlapping(mine, prs, branch.strip())
    if not hits:
        return 0

    lines = [
        "[pr-duplicate-preflight] BLOCKED: one of YOUR open PRs already touches "
        "these files.",
        "",
    ]
    for number, title, shared in hits:
        lines.append(f"  #{number} {title}")
        for path in shared[:5]:
            lines.append(f"      also changes {path}")
        if len(shared) > 5:
            lines.append(f"      … and {len(shared) - 5} more")
    lines += [
        "",
        "Measured 2026-08-27: example-labs-infra #345 was opened while #343 — same",
        "file, functionally identical diff, open since that morning — already",
        "existed. #345 merged and #343 had to be closed as redundant.",
        "",
        "Do one of these instead:",
        "  - add your commit to the existing PR's branch, or",
        "  - read that PR first and confirm yours is genuinely different, then set",
        "    CLAUDE_PR_ALLOW_DUPLICATE=1 for this call.",
    ]
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
