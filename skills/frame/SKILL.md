---
name: frame
description: "Write the frame before the work: problem, checkable done-when, non-goals, riskiest assumption, what stays human — as INTENT.md in the repo."
when_to_use: 'Use before /superplan and at the start of any task with more than one slice, or when a prompt says "build / implement / migrate / refactor" without saying what done looks like. Trigger phrases: "frame this", "write the intent", "define done", "what does done look like", "scope this down". Produces INTENT.md in the working directory (created or updated, never silently overwritten) and feeds the session acceptance ledger through the proceed-gate hook. Do NOT use for a single small change, a question, or a pure research task (use brainstorm or deep-dive). Do NOT use to plan HOW -- that is /superplan; this skill fixes WHAT and WHAT NOT.'
argument-hint: "[one-line statement of the task, or nothing to be asked]"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: AskUserQuestion Read Write Edit Glob Grep Bash(git status*) Bash(git log*) Bash(ls*)
---
# frame

Generation is cheap; the frame is the bottleneck. Two minutes here give every
later `proceed` something to be checked against, and give `session-boundaries`
a completion point to stop at.

## Exit criteria (read first — this is the gate)

`INTENT.md` exists in the working directory with all five sections non-empty;
every *Done when* item is a command or an observation a stranger could re-run;
the riskiest assumption names its probe; *Stays human* lists at least one item.
Report in five lines or fewer and stop — do not start the work in this turn
unless the user's prompt already said to.

## Phase 0 — Should this be framed at all?

Skip (say so in one line) when the task is one slice under ~30 minutes, a
question, or research. Otherwise continue. If `INTENT.md` already exists, read
it: update the sections that changed, keep prior *Non-goals* and *Decisions*
unless the user retracts them explicitly, and append a dated *Revision* line.

## Phase 1 — Elicit only what the prompt does not answer

Take the answers from the prompt, the repo (`README`, `PLAN.md`, `git log`), and
the acceptance ledger if one was rehydrated. Ask **at most three** questions with
AskUserQuestion, in this priority: (1) what observable result completes the
task, (2) what is explicitly out of scope, (3) which assumption, if false, wastes
the most time. Never ask what the repo can tell you.

## Phase 2 — Write INTENT.md

Use `references/INTENT.template.md`. Rules for the content:

- **Problem** — one paragraph, the user's words where possible, no solution.
- **Done when** — checkboxes; each a command (`make check` passes) or an
  observation (`10k-row file imports in < 5 s on the sample`). No adjectives.
- **Non-goals** — what will not be built this time, including tempting nearby
  fixes. This is the section the ledger stores as REJECTED.
- **Riskiest assumption** — one sentence plus the cheapest probe that tests it,
  scheduled first in the plan.
- **Stays human** — decisions the model must bring back, not make: interfaces,
  data deletion, anything external-facing, anything the user named.
- **Model / effort** — which model the work runs on and why (see `model_notes`).

## Phase 3 — Route

- One slice → tell the user the frame is written and proceed on their word.
- Several slices, MCP or agent work, or an existing plan → invoke `/superplan`
  with `INTENT.md` as the task input; superplan plans HOW, this file fixes WHAT.
- High stakes or a plan that "looks right" → `/interview` against `INTENT.md`.

The `proceed-gate` hook ingests *Done when*, *Non-goals*, *Constraints* and the
riskiest assumption into the session acceptance ledger on the next prompt, and
session-start rehydrates that ledger after every compaction; nothing to do.

## Example

`/frame migrate the importer off the legacy CSV parser` in a repo with no
INTENT.md. Phase 1 finds the parser and its callers in the repo, asks one
question (what proves the migration: "the 10k-row fixture imports in under 5 s
with identical output"), and writes:

```
## Done when
- [ ] `make check` passes — parser unit and golden tests
- [ ] `time ./bin/import fixtures/10k.csv` < 5 s, output sha unchanged
## Non-goals
- No new file formats; no UI
## Riskiest assumption
Quoted commas are the only dialect difference — probe: `grep -c '"' fixtures/*.csv` first
## Stays human
- Deleting the legacy parser module (propose, do not do)
```

then routes to `/superplan` because three modules change.

## Anti-patterns this skill exists to stop

Done-criteria that emerge over hours; a third of prompts being `proceed`; a
rejected constraint re-entering after compaction because it was never written;
plans presented as deliverables. WHY: week of 2026-08-30 review and the 14-day
ledger review (35 of 58 corrective turns in six long sessions).
