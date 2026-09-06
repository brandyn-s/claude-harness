# Codex

This harness is Claude Code first, but the practice it encodes is tool-neutral,
and `bin/sync-codex-skills.py` already mirrors skills into Codex. This directory
carries the other half: the **posture** Codex should run under, and the
**instruction overlay** a Codex project reads.

| File | What it is | Where it goes |
|---|---|---|
| `config.toml.patch` | Two-line posture change plus one table: `workspace-write`, `on-request`, `approvals_reviewer = "auto_review"`, network off by default | `~/.codex/config.toml` (apply by hand; verify keys against your installed version) |
| `AGENTS.overlay.md` | ≤ 60 lines: frame first, evidence over assertion, scope, failure, session boundaries, sandbox expectations, per-model notes for GPT-5.6 / GPT-6 Astra, the journal ledger | append to each Codex project's `AGENTS.md`, or make it the whole file where none exists |

## Why both halves matter

A workstation that runs Claude Code inside the native sandbox with `acceptEdits`
and twenty deny rules, and Codex with `danger-full-access` and `approval_policy =
"never"`, has one posture per tool — and the weaker one is the effective one.
Codex reads `AGENTS.md` in full (32 KiB cap) and does not run this repository's
hooks, so for Codex the overlay is the whole advisory layer and the sandbox is the
whole enforcement layer. Keep the overlay short: it competes with the task for the
same context.

## Keeping it tool-neutral

Claude Code reads the same project file through `@AGENTS.md` in `CLAUDE.md` (this
repository's own `CLAUDE.md` is exactly that pointer), so the overlay is written
without tool names in its contracts. Only the "Model notes" section is per-model,
and each model applies only its own block — the same design as
`hooks/session_start_modules/model_notes.py` on the Claude side.

## What is deliberately not here

No Codex hooks (Codex has no hook surface comparable to Claude Code's), no
attempt to port `bash-security-guard.py` (the sandbox is the enforcement layer;
a guard the model can be argued out of is not one), and no Codex-side ledger
tooling beyond the `JOURNAL.md` convention in the overlay. The skills mirror is
`bin/sync-codex-skills.py`; see the README's "Advanced full-mirror
synchronization" section.
