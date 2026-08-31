---
name: run-status
description: Show the live state of long-running background work (oracle runs, terraform applies, measurement harnesses, deploy monitors) from their durable status files. Use when the user asks "what is the status?", "is X done?", "is the run still going?", or wants a snapshot of in-flight background jobs. Do NOT use for git/PR status (use gh) or CI-check status (use gh pr checks).
argument-hint: "[run-id, or blank for all active runs]"
effort: low
allowed-tools: [Bash, Read, Glob]
---

# run-status — durable background-run status surface

Answers "what is the status?" from durable per-run status files instead of
re-polling live services every time. Background runs write
`runs/<id>/status.json` + a `.done`/`.fail` marker on completion; this skill
reads them.

**Why this exists (2026-06-25 session self-audit):** a 3-day session logged ~30
"What is the status?" turns because long-running work had no queryable status —
every check was a fresh manual poll. A run that writes its status to a durable
file turns "status" into one file-read.

## Step 1 — Locate the runs directory

A run lives under `runs/<id>/` **repo-relative** by default (gitignored;
NOT `/tmp`, which the macOS date-rollover purges). If the user is in a repo,
`runs/` is there; otherwise check `$CLAUDE_RUNS_DIR`. The helper is at
`bin/run-status.py` in the claude-config checkout (`~/.claude/bin/run-status.py`).

```bash
# from the repo whose runs you want; or set CLAUDE_RUNS_DIR
python3 ~/.claude/bin/run-status.py list
```

## Step 2 — Report

- **No argument** → `list` every run, newest first, each labeled
  `DONE` / `FAILED` / `RUNNING` / `STALE` / `UNKNOWN`. STALE = status.json
  hasn't advanced past the stale window (default 15 min) and no marker —
  the run may be wedged; surface it as "possibly stalled, verify".
- **A run-id argument** → `show <id>` for that one run's phase / pct / detail /
  last-update time, plus its terminal marker body if `.done`/`.fail` exists.

State is read from **file state, never pid-liveness** — a hung run keeps its
pid; a finished run's pid is gone. The marker files are the source of truth.

## Step 3 — When a run is STALE or FAILED

- **FAILED** → read the `.fail` marker body (the failing reason) and the run's
  log if one exists; diagnose per `diagnose-before-fix` (read the actual error,
  don't guess).
- **STALE** → distinguish wedged-vs-slow on THREE signals, not one: liveness
  (`ps -p <pid>` if the run recorded a pid), output growth over ≥ one batch
  period, and whether the status detail advanced. A run between slow batches
  looks stale but is progressing.

## How a background run wires itself in (for run authors)

```bash
H=~/.claude/bin/run-status.py
python3 $H start my-run --phase init --detail "starting"
# ... work ...
python3 $H update my-run --phase judging --pct 47 --detail "S2 47%"
# on success:
python3 $H done my-run --summary "233 sessions judged"
# on failure:
python3 $H fail my-run --reason "SSO token expired mid-run"
```

A monitor script should `update` at each phase boundary and write the terminal
marker on exit, so this skill can report state without re-querying live services.

## Examples

**Example 1 — "what is the status?"**
Invoke with no argument → `run-status.py list` → report each run's state:
```
[RUNNING] oracle-day16  phase=judging 47%  upd=...  S2_content 47%
[DONE   ] render-deploy  phase=done  upd=...  render == :latest
[FAILED ] census-v3  phase=failed  upd=...  SSO token expired mid-run
```

**Example 2 — "is the render deploy done?"**
Invoke with `render-deploy` → `run-status.py show render-deploy` → report DONE +
the `.done` summary, or RUNNING + current phase/pct.

## Success Criteria

- Reports every background run's state from durable files in one invocation —
  no manual re-polling of live services.
- Correctly labels DONE/FAILED from marker files and RUNNING/STALE from
  status.json age; never infers "done" from pid-absence alone.
- For a FAILED/STALE run, points at the failing reason / the three wedged-vs-slow
  signals rather than guessing.
