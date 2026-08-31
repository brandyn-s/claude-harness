# CLAUDE.md — Session Instructions

> Copy this to `~/.claude/CLAUDE.md` and customize. Claude Code loads it every session.

## Who I Am

<!-- CUSTOMIZE: Replace with your role and context -->
I'm a software engineer working on [project/domain]. I prefer [concise/detailed] responses.

## How We Work Together

### Rules (loaded from `~/.claude/rules/`)

Rules are ambient guidance loaded every turn. The installed rules enforce:

- **check-before-change** — Verify WHY something exists before modifying it. Search git history and memory for prior decisions.
- **diagnose-before-fix** — Read actual errors before proposing fixes. No guessing.
- **never-stop-early** — Complete the task. Never suggest "let's continue in a new session."
- **validate-to-improve** — Every test pass produces a fix list, not just "PASS."
- **search-efficiency** — Read budgets prevent excessive file scanning.

### Skills (invoked with `/skill-name`)

Skills are multi-step workflows. Use them by typing the slash command:

- `/brainstorm` — Design exploration before creative work
- `/superplan` — Context-aware planning for non-trivial tasks
- `/interview` — Adversarial stress-test for plans
- `/semgrep` — Run static analysis scans
- `/handoff` — Write a session handoff document

### Hooks (fire automatically)

Hooks enforce rules mechanically — they fire every time regardless of context:

- **loop-detector** — Catches repeated failing actions (3+ identical calls)
- **bash-security-guard** — Blocks credential exposure and destructive shell commands
- **result-injection-guard** — Scans MCP results for prompt injection
- **promise-checker** — Blocks early session termination phrases

## Coding Standards

<!-- CUSTOMIZE: Add your language preferences, frameworks, conventions -->

- Write tests for new features
- No `console.log` in production code
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
- Don't suggest "continuing in a new session"
- Don't create documentation files unless explicitly asked
