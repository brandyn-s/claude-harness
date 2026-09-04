# CLAUDE.md — Session Instructions

> Copy this to `~/.claude/CLAUDE.md` and customize. Claude Code loads it every
> session, so keep it short and operational (see `rules/claude-md-quality.md`).

## Who I Am

<!-- CUSTOMIZE: Replace with your role and context -->
I'm a software engineer working on [project/domain]. I prefer [concise/detailed] responses.

## How This Harness Is Wired

The fresh-laptop core installs one ambient rule, one path-scoped rule, and three
hooks. Hooks are mechanical; do not restate them here.

- `rules/outcome-over-verification.md` — verification is bounded evidence for the
  requested outcome; stop when decisive evidence answers the decision.
- `rules/claude-md-quality.md` — loads only when a `CLAUDE.md` is edited.
- `hooks/bash-security-guard.py` — blocks credential exposure, exfiltration, and
  destructive shell commands.
- `hooks/config-guard.py` — blocks settings edits that disable hooks.
- `hooks/result-injection-guard.py` — flags instruction-shaped text in MCP results.

The operator layer adds `rules/operator-discipline.md`, the loop detector, and
the prompt/output secret hooks. Optional skills are invoked with `/skill-name`;
`skills/README.md` is the index.

## Coding Standards

<!-- CUSTOMIZE: Add your language preferences, frameworks, conventions -->

- Write tests for new features
- Prefer composition over inheritance
- Error messages should be actionable

## Project Context

<!-- CUSTOMIZE: Describe your current project, tech stack, key repos -->

- **Language**: [TypeScript/Python/Rust/etc.]
- **Framework**: [Next.js/Django/Axum/etc.]
- **Key repos**: [list your repos]

## What NOT to Do

- Don't add features beyond what was asked
- Don't add comments to code you didn't change
- Don't create documentation files unless explicitly asked

## Invoke skills explicitly

Description routing is unreliable in practice (measured 2026-09-04: 8 of 30 real
sessions reached the expected skill on their own). Name the skill you want:
`/superplan` before non-trivial changes, `/validate-changes` before claiming
tests pass, `/ship` to deliver, `/capture` and `/distill` for knowledge work,
`/semgrep` and `/threat-model` for security review, `/interview` to pin
requirements. Keep this list short and specific to the project.
