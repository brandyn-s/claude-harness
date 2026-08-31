# Staged hook spec: git-statechange-pipe-guard

## Problem (measured 2026-08-24, twice in one session)
`git worktree add ... 2>&1 | grep -m1 <pat>` — grep exits at first match,
git receives SIGPIPE MID-CHECKOUT, and the result is a ghost worktree:
branch created, "Preparing worktree" printed, but the checkout unregistered
or incomplete. Bit twice in one session (claude-config-b3: directory vanished;
mcp-servers-edition: "fatal: not a git repository" with files present only
because a later script mkdir'd into it). `rules/platform-constraints.md`
already forbids important producers behind early-closing consumers, and
`bash-tail-buffering-guard` blocks the LONG-RUNNING shape — but a
STATE-CHANGING producer piped to `grep -m/-q` or `head -n` passes today.

## Enforcement
PreToolUse (Bash) check, either as an extension of bash-tail-buffering-guard
or standalone: BLOCK when a pipeline's producer segment matches
`\bgit\s+(worktree|clone|checkout|fetch|pull|merge|rebase|commit|push|am|apply)\b`
AND any downstream segment is `grep` with `-m` or `-q`, `head`, or `sed ...q`.
Message: "state-changing git must not feed an early-exiting filter — SIGPIPE
can kill it mid-operation; redirect to a file or let output print."

## Tests (hooks/test-hooks/)
- known-positive: `git worktree add /tmp/x -b b origin/main 2>&1 | grep -m1 branch` -> BLOCK
- known-positive: `git push origin b | head -2` -> BLOCK
- known-negative: `git log --oneline | head -5` -> ALLOW (read-only producer)
- known-negative: `git worktree add ... > /tmp/log 2>&1` -> ALLOW
