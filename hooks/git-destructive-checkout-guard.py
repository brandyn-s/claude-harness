#!/usr/bin/env python3
"""PreToolUse:Bash — BLOCK git commands that would destroy unrecoverable work.

WHY (upstream, 2026-08-24): anthropics/claude-code#89330 — `bug, has repro,
platform:macos, area:skills, data-loss`. The built-in `review` / `/code-review`
skill is documented to read a PR only through `gh`, but ran
`git checkout <remote-PR-branch> -- .` against the working tree. An unstaged edit
to a tracked file was PERMANENTLY destroyed: never staged, so git held no record
anywhere — no stash entry, no object in `.git`, no reflog path back.

REWRITTEN 2026-08-30 after a self-review probe found the first version wrong in
BOTH directions. The original gated every shape on "unstaged tracked
modifications", which is the wrong signal for half of them:

  * `git clean -fd` was ALLOWED on a tree with precious UNTRACKED files and no
    unstaged tracked edits — `clean` destroys UNTRACKED files, so the guard
    missed the exact case `clean` threatens.
  * `git restore --staged <path>` was BLOCKED even though it touches only the
    INDEX and leaves the working tree alone.

Both were confirmed by running the real commands, not by reading the code. The
first version's 27 tests passed anyway, because the fixtures were written to the
same wrong model as the code (`rules/tdd-mutation-testing.md` item 34 — an
assumption-written test pins the wrong boundary while passing). The test file is
now driven by an EMPIRICAL truth table: it runs each command for real and asserts
the guard's verdict matches what actually got destroyed.

RISK CLASSES, per command shape:
  unstaged  — destroys unstaged tracked modifications (exist in no git object)
  untracked — destroys untracked files (exist in no git object)
  ignored   — destroys ignored files (often `.env`, credentials, local config)

  git checkout <ref> -- <path>     unstaged     (the #89330 shape)
  git checkout -- <path>           unstaged
  git checkout -f|--force ...      unstaged     (force-switch discards local edits)
  git switch --discard-changes     unstaged
  git switch -f|--force ...        unstaged
  git restore <path>               unstaged     (default is --worktree)
  git restore -W|--worktree ...    unstaged
  git restore -S|--staged  ...     NOT BLOCKED  (index only)
  git reset --hard [<ref>]         unstaged
  git clean -f[d]                  untracked
  git clean -f[d]x                 untracked + ignored
  git clean -f[d]X                 ignored only

NOT BLOCKED: branch creation (`checkout -b/-B`, `switch -c/-C`) without a force
flag; `git reset` (soft/mixed — index only); `git stash` (recoverable by design);
`git clean -n` (dry run); any command on a repo with none of the relevant state.

PARSING: the command is tokenized with `shlex` per shell segment, so a destructive
form QUOTED inside another command (`echo 'git reset --hard'`, a grep pattern, a
JSON payload) is no longer mistaken for the real thing — that was a documented
false-positive surface of the first version. If tokenization fails (unbalanced
quotes), the guard falls back to a conservative regex scan and blocks, because
under-blocking costs unrecoverable work while over-blocking costs one retry.

Exit codes:
  0 = allow (default, and on ANY internal error — fail-open)
  2 = BLOCK with a stderr explanation naming the recoverable alternative

Bypass (deliberate, rare): CLAUDE_ALLOW_DESTRUCTIVE_CHECKOUT=1. Prefer
`git stash push -- <path>` or a `cp` snapshot; those keep the work.
"""
import json
import os
import re
import shlex
import subprocess
import sys

SEGMENT_RE = re.compile(r"\|\||&&|;|\||\n")

# A backslash-newline is a LINE CONTINUATION, not a segment boundary. Without this
# join a multi-line command fragments into pieces like `git add -- \`, which shlex
# rejects ("No escaped character"), so the command falls to the conservative scan.
# What the join buys, precisely (mutation-measured, not assumed): it lets a
# multi-line invocation TOKENIZE, so a destructive VERB carrying safe FLAGS reaches
# the per-flag classification that knows it is safe — `git restore --staged <path>`
# is index-only, but the verb-scoped fallback below cannot see the flag and would
# block it. It is NOT what fixes multi-line `git add`; the fallback scoping is.
LINE_CONTINUATION = re.compile(r"\\[ \t]*\n[ \t]*")

FORCE = {"-f", "--force"}

# The conservative scan runs ONLY when tokenization fails, and it must be scoped to
# verbs that can actually destroy work. An earlier version keyed on `git … -- <path>`
# and therefore fired on `git add -- a`, `git commit -- a`, `git diff -- a`,
# `git log -- a`, `git status -- a` and `git show HEAD -- a` — every one safe. Paired
# with the missing line-continuation join above, that made any multi-line
# `git add -- <files>` unrunnable: a worse false-positive class than the raw text
# matching it replaced. Measured 2026-08-30 by this guard blocking its own repo's ship.
DESTRUCTIVE_SUBCOMMANDS = ("checkout", "restore", "reset", "clean", "switch")
CONSERVATIVE_FALLBACK = re.compile(
    r"\bgit\b[^;|&\n]*?\b(?:" + "|".join(DESTRUCTIVE_SUBCOMMANDS) + r")\b",
)
# The fallback cannot tokenize, so it cannot use classify()'s `-C` handling — but it
# still must evaluate the TARGET repo's state. Without this the fallback silently
# checked os.getcwd() instead, so an untokenizable `git -C <other-repo> reset --hard`
# was graded against whatever repo the shell happened to sit in: it blocks or allows
# for the wrong reason, and a test asserting the block passes only while the ambient
# cwd happens to be dirty (`rules/tdd-mutation-testing.md` item 27). Measured
# 2026-08-30: staging this repo's own edits flipped that assertion from pass to fail.
DASH_C = re.compile(r"\bgit\s+(?:-\S+\s+)*?-C\s+(\S+)")


def _segments(command):
    command = LINE_CONTINUATION.sub(" ", command)
    for seg in SEGMENT_RE.split(command):
        seg = seg.strip()
        if seg:
            yield seg


def _git_tokens(segment):
    """Return the token list starting at `git`, or None if this segment isn't git.

    Raises ValueError when the segment cannot be tokenized.
    """
    toks = shlex.split(segment)
    i = 0
    # skip leading env assignments (FOO=bar git ...)
    while i < len(toks) and "=" in toks[i] and not toks[i].startswith("-"):
        i += 1
    if i < len(toks) and os.path.basename(toks[i]) == "git":
        return toks[i:]
    return None


def _split_flags(args):
    """Return (flag_set, positional_args, saw_double_dash)."""
    flags, positional, dd = set(), [], False
    for a in args:
        if a == "--":
            dd = True
        elif a.startswith("--"):
            flags.add(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1:
            for ch in a[1:]:
                flags.add("-" + ch)
        else:
            positional.append(a)
    return flags, positional, dd


def classify(tokens):
    """Return (label, risk_set, repo_dir_or_None) or None when harmless."""
    rest = tokens[1:]
    repo = None
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        if rest[i] == "-C" and i + 1 < len(rest):
            repo = rest[i + 1]
            i += 2
        elif rest[i] in ("-c", "--namespace") and i + 1 < len(rest):
            i += 2
        else:
            i += 1
    if i >= len(rest):
        return None
    sub = rest[i]
    flags, _positional, saw_dd = _split_flags(rest[i + 1:])
    forced = bool(flags & FORCE)

    if sub == "clean":
        if not forced:
            return None  # -n/dry-run or an incomplete invocation
        risks = set()
        if "-X" in flags and "-x" not in flags:
            risks.add("ignored")
        else:
            risks.add("untracked")
            if "-x" in flags:
                risks.add("ignored")
        return ("git clean -f", risks, repo)

    if sub == "checkout":
        if forced:
            return ("git checkout --force", {"unstaged"}, repo)
        if flags & {"-b", "-B"}:
            return None
        if saw_dd:
            return ("git checkout <ref> -- <path>", {"unstaged"}, repo)
        return None

    if sub == "switch":
        if forced or "--discard-changes" in flags:
            return ("git switch --discard-changes", {"unstaged"}, repo)
        return None

    if sub == "restore":
        staged = bool(flags & {"-S", "--staged"})
        worktree = bool(flags & {"-W", "--worktree"})
        if staged and not worktree:
            return None  # index only — leaves the working tree alone
        return ("git restore", {"unstaged"}, repo)

    if sub == "reset":
        if "--hard" in flags:
            return ("git reset --hard", {"unstaged"}, repo)
        return None

    return None


def _porcelain(cwd, ignored=False):
    argv = ["git", "status", "--porcelain"]
    if ignored:
        argv.append("--ignored")
    out = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=20)
    return out.stdout.splitlines() if out.returncode == 0 else []


def at_risk(cwd, risks):
    """Return {risk: [paths]} for every risk class with real exposure."""
    found = {}
    need_ignored = "ignored" in risks
    lines = _porcelain(cwd, ignored=need_ignored)
    if "unstaged" in risks:
        p = [l[3:].strip() for l in lines if len(l) > 3 and l[1] in ("M", "D")]
        if p:
            found["unstaged tracked edits"] = p
    if "untracked" in risks:
        p = [l[3:].strip() for l in lines if l.startswith("??")]
        if p:
            found["untracked files"] = p
    if need_ignored:
        p = [l[3:].strip() for l in lines if l.startswith("!!")]
        if p:
            found["ignored files"] = p
    return found


def main():
    if os.environ.get("CLAUDE_ALLOW_DESTRUCTIVE_CHECKOUT") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0

    hit = None
    for seg in _segments(command):
        try:
            toks = _git_tokens(seg)
        except ValueError:
            # Untokenizable: fall back to the conservative scan and block if it
            # looks destructive at all. Under-blocking is the costly direction.
            if CONSERVATIVE_FALLBACK.search(seg):
                m = DASH_C.search(seg)
                hit = ("an untokenizable git command",
                       {"unstaged", "untracked"},
                       m.group(1) if m else None)
                break
            continue
        if not toks:
            continue
        hit = classify(toks)
        if hit:
            break
    if not hit:
        return 0

    label, risks, repo = hit
    cwd = os.path.expanduser(repo) if repo else os.getcwd()
    try:
        exposure = at_risk(cwd, risks)
    except Exception:
        return 0
    if not exposure:
        return 0

    detail = []
    for kind, paths in exposure.items():
        shown = paths[:6]
        more = len(paths) - len(shown)
        listing = "\n".join(f"      {p}" for p in shown)
        if more > 0:
            listing += f"\n      ... and {more} more"
        detail.append(f"  {len(paths)} {kind}:\n{listing}")
    body = "\n".join(detail)

    print(
        f"[destructive-checkout-guard] BLOCKED: `{label}` in {cwd}\n"
        f"{body}\n\n"
        "These exist in NO git object — not the index, not a stash, not the "
        "reflog. This command overwrites or deletes them with no recovery path "
        "(anthropics/claude-code#89330, data-loss, still open).\n\n"
        "Recoverable alternatives:\n"
        "  git stash push -u -- <paths>     # -u also stashes untracked files\n"
        "  cp <path> /tmp/claude/<path>.bak # explicit snapshot first\n"
        "  git diff > /tmp/claude/wip.patch # keep a patch, then re-apply\n"
        "To read a PR without touching the working tree use `gh pr diff` / "
        "`gh pr view` (what the review skill is documented to do).\n"
        "Deliberate override: CLAUDE_ALLOW_DESTRUCTIVE_CHECKOUT=1",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # fail-open: a guard bug must never block legitimate work
        sys.exit(0)
