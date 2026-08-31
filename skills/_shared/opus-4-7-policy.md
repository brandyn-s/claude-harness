# Opus 4.7 — HISTORICAL BASELINE (2026-04-16)

> Historical evidence only. This file preserves the assumptions used by Opus
> 4.7 measurements and migrations. It is not active runtime policy. Current
> skills use `model-runtime-policy.md` and a matching model overlay.

Shared advisory referenced by skills that touch security-context work or
agentic-loop control. Captures the Anthropic-published behavior changes that
affected how skills ran on Claude Opus 4.7 as of 2026-04-16.

## Cybersecurity safeguards (refusal risk)

> "Real-time cybersecurity safeguards: requests that involve prohibited or
> high-risk topics may lead to refusals. For legitimate security work,
> apply to the [Cyber Verification Program](https://claude.com/form/cyber-use-case)."
> — [What's new in Claude Opus 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)

Skills that may hit new refusals on 4.7 without Cyber Verification
enrollment:

- `vendor-breach` — vendor CVE / breach blast-radius
- `codeql`, `semgrep`, `semgrep-rule-creator` — security scanning + rule writing
- `fp-check` — verifying security bugs
- `triage` — security findings triage
- `variant-analysis` — vulnerability hunting
- `threat-model` — threat modeling
- `sca-review`, `stig-assess`, `stig-verify` — STIG/SCA
- `agentic-actions-auditor` — workflow security review
- `differential-review` — security-focused code review
- `insecure-defaults`, `sharp-edges` — defensive analysis
- `security-alerts` — Dependabot/CodeQL remediation

If a skill hits a refusal on 4.7 and the work is legitimate (auditing,
remediation, defensive analysis), the operator should be aware of the
Cyber Verification Program. None of our security skills are offensive
in nature, but the refusal signal may fire on the prose surface.

## Sampling parameters — REJECTED on 4.7

`temperature`, `top_p`, `top_k` set to any non-default value → 400 error.
Source: [Migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide).

Migration: omit these parameters entirely. Use `output_config.effort` and
prompting to guide determinism / variation. See `api-guardrails` skill
for the per-model matrix.

## Extended thinking — REMOVED on 4.7

`thinking: {type: "enabled", budget_tokens: N}` → 400 error.
Replace with `thinking: {type: "adaptive"}` + `output_config.effort`.
Adaptive thinking is **off by default** on 4.7; set the field explicitly
to enable.

## Task budgets (beta)

`task_budget` is the 4.7-recommended replacement for caller-side budget
tracking in agentic loops. Advisory (not enforced); model sees a running
countdown. Minimum 20k tokens. Beta header: `task-budgets-2026-03-13`.

Skills that currently implement their own budget tracking (`supergoal`,
`superplan`) can consider migrating to `task_budget` when the beta
graduates. Current implementations remain valid — `task_budget` is a
softer signal than the hard turn-cap supergoal enforces.

## Behavior changes that may affect existing skill prompts

The official 4.7 docs flag five behavior shifts. Each has a re-baseline
implication:

| Behavior change | Re-baseline action for skill authors |
|---|---|
| More literal instruction following (especially at lower effort) | "Do NOT use for X" clauses in skill descriptions are now weighted more heavily — keep them. |
| Response length calibrates to task complexity | Drop fixed-length scaffolding ("respond in exactly 5 paragraphs"). |
| Fewer tool calls by default; reasons more between calls | Drop scaffolding that forces tool use ("always call tool X first"). |
| More regular progress updates by default | Drop interim-status scaffolding ("after every 3 steps, print STATUS:"). |
| Fewer subagents spawned by default | Skills that need parallel agents (e.g., `subagent-driven-development`, `roundtable`) should explicitly prompt for it. |

## Tokenizer (1–1.35× expansion vs 4.6)

> "[The] new tokenizer may use roughly 1x to 1.35x as many tokens when
> processing text compared to previous models (up to ~35% more, varying
> by content)." — Migration guide.

Implications:
- `max_tokens` should be raised to give headroom
- SKILL.md body line counts undercounted actual context cost. The historical
  audit used a tiktoken proxy; current qualification uses a structural estimate
  plus the target model's token-counting endpoint.
- Per-skill metadata cost is ~100 tokens (per the
  [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview))

## Sources

- [What's new in Claude Opus 4.7](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7) (verified 2026-05-27)
- [Migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide)
- [Adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking)
- [Effort parameter](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Task budgets (beta)](https://platform.claude.com/docs/en/build-with-claude/task-budgets)
- [Cyber Verification Program](https://claude.com/form/cyber-use-case)
