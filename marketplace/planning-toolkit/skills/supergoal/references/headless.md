# Headless mode — `claude -p` invocation

## Why headless is the production path

Anthropic's `/goal` docs document `claude -p` non-interactive mode explicitly: "Setting a goal with `-p` runs the loop to completion in a single invocation." This is the autonomy use case — a long-running loop that doesn't need a terminal attached.

For supergoal, headless mode is where the design pays off: a plan + Demo + falsifiers + budget hands off to a process that runs to completion without supervision, then exits with a structured outcome.

## Invocation pattern

```bash
claude -p "/supergoal ~/Documents/knowledge-base/plans/2026-05-24-fix-extractor.md --budget-turns=100 --budget-tokens=2M"
```

Or, with explicit headless flag:

```bash
claude -p "/supergoal ~/Documents/knowledge-base/plans/2026-05-24-fix-extractor.md --headless --budget-turns=100"
```

The `--headless` flag is also implicitly set when supergoal detects it's running under `claude -p` (no TTY).

## Behavioral differences in headless mode

| Step | Interactive | Headless |
|------|-------------|----------|
| Step 2 prior-arc check | Refuses; user can re-invoke with `--force-rerun` | Exits 1 if prior arcs exist and `--force-rerun` not set; ledger to stdout |
| Step 5 user confirmation | `AskUserQuestion` go/no-go | Skipped — invocation implies consent |
| Hook timeouts | Surface to user | Logged; loop continues if /goal can recover |
| Step 7 terminal doc | Written + committed; user sees in transcript | Written + committed; exit code maps to exit reason |
| stdout shape | Conversational | Structured (last line is the exit reason) |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | `success` — demo achieved |
| 10 | `falsifier-triggered` — falsifier halted the loop |
| 11 | `budget-exhausted` — turn or token cap reached |
| 12 | `plan-tampered` — plan SHA-256 changed mid-loop |
| 13 | `scorer-broken` — verifier itself crashed; human review required |
| 14 | `stuck-no-progress` — `consecutive_no_progress` hit `max_stuck` (default 3) |
| 20 | `parse-failed` — plan missing required fields / bad args / plan-not-found |
| 21 | `prior-arcs-exist` — prior arcs found, `--force-rerun` not set |
| 22 | `attestation-failed` — couldn't write or verify SHA-256 |
| 1  | other / unexpected error |

The non-zero exit codes are deliberately spaced (10+ for runtime exits, 20+ for setup exits, 1 for unknown) so CI can switch on ranges.

Implementation: `write_terminal.py` maps the runtime exit reasons (10/11/12/13/14) when `state.headless` is true; `parse_plan.py` and `check_prior_arcs.py` map the setup-time codes (20/21/22). `parse_plan.py` auto-sets `--headless` when stdin is not a TTY (per `_auto_headless`); the flag then flows through `state.json` to other scripts.

## Per-turn history

Headless mode records per-turn history in the append-only event log at `~/.claude/supergoal/<slug>/events.jsonl` (written by the Stop hook). Each event is a JSON line with turn, timestamp, decision (block/allow), reason, metric values, and exit codes.

This is the post-mortem signal when something went wrong: replay the log against the plan to see where the loop stalled.

## Composing with CI / cron / `/loop`

Headless mode makes supergoal cron-friendly:

```bash
# Nightly: if the extractor regresses, automatically attempt a fix
0 2 * * * cd ~/repo && claude -p "/supergoal plans/auto-fix-extractor.md --budget-turns=50" >> ~/.cache/supergoal-nightly.log 2>&1
```

Or via `/loop` (Claude Code's scheduled-task primitive):

```
/loop 6h /supergoal plans/auto-fix-extractor.md --headless
```

Either pattern depends on the exit code semantics above so the outer scheduler can decide retry / alert / proceed.

## What headless does NOT do

- Does **not** re-attest the plan automatically if the SHA changes. The intentional update path is: stop, re-run `superplan` to update the plan, re-invoke supergoal.
- Does **not** push past `--force-rerun` defaults. Prior-arc check refuses headless runs unless the flag is set, by design — autonomous re-litigation is the failure mode this protects against.
- Does **not** elevate budgets. Override via `--budget-turns=`/`--budget-tokens=`; defaults are the same as interactive.
