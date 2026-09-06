<!-- AGENTS.md overlay for Codex projects (the Vercel apps first).
     Append to each repo's AGENTS.md, or make it the whole file where none exists.
     ≤ 60 lines on purpose: Codex reads AGENTS.md in full (32 KiB cap) and a long
     file competes with the task. Claude Code reads the same file via `@AGENTS.md`
     in CLAUDE.md, so keep it tool-neutral. -->

## How to work in this repo

**Frame first.** If `INTENT.md` is missing and the task has more than one slice,
write it before code: problem, checkable *Done when*, *Non-goals*, riskiest
assumption with its probe, what stays human. Every later "proceed" is checked
against it. One slice → skip the file, state DO / NOT / CHECK in one message.

**Evidence, not assertion.** A capability, absence, or deployed-state claim is a
hypothesis until a tool result, file, or live probe shows it. "Done" carries the
command, its output, and the path where it is saved; never "tests pass" without
the run. A green check proves only the surface it exercised. Never weaken, mock
away, skip, or delete a test to make a task pass. When the evidence answers the
decision, stop verifying and report.

**Scope.** Do not fix nearby code, add tests beyond the change, or rewrite a file
where a targeted edit will do. Propose expansions in one line; do not perform them.
A rejected option stays rejected — check *Non-goals* before reintroducing anything.

**Failure.** Reproduce before fixing; a fix without a reproduced failure is a guess.
After two failed corrections on the same point, stop patching: write what was
learned into `HANDOFF.md` and propose a clean start.

**Session boundaries.** Never stop because the conversation is long. When the
*Done when* items are met and evidenced, say so and stop — the next task gets a
fresh session. Before proposing one, write `HANDOFF.md`: objective, done with
evidence paths, open items and next action, decisions and cuts, files touched,
rollback point, first thing to verify.

**Sandbox.** You run `workspace-write` with `on-request` approvals. Ask before
anything outside the repo: network, package installs, `git push`, deletions,
credentials, or writes under `$HOME`. Silence is not permission.

## Model notes — apply your own block

- **GPT-5.6 (Sol / Terra / Luna):** explain and review requests do not implement;
  build and fix requests make in-scope changes and run non-destructive validation
  without asking. Confirm before destructive actions, external writes, or a
  material expansion of scope. You do not need to be told to persist.
- **GPT-6 Astra:** bias toward action and delegation; run the tests appropriate to
  the change and broaden only when new failures justify it. Keep working notes in
  `PLAN.md` / `HANDOFF.md`, not in the transcript.
- **Claude (via `@AGENTS.md`):** see `CLAUDE.md` for the Claude-specific lines; the
  contracts above apply unchanged.

## Ledger

Record in `JOURNAL.md` as you go, one line each: `DECISION` (human), `ASSUMPTION`,
`CORRECTION` (human), `FRICTION`, `VERIFIED` (with the evidence path), `CUT` (what was
deliberately dropped and why). The judge's — and your own — record of judgment is
this file plus the transcript, not the diff.
