# Fable 5 Runtime Overlay

- Use the exact effective model identifier in automated qualification.
- Start routine qualification at `high`; reserve `xhigh` for task families
  whose measured quality benefit justifies its latency and cost.
- Do not add unconditional self-verification reminders. Keep deterministic
  external acceptance checks; for unusually long work, use bounded checkpoints
  only when the task contract needs them.
- Verify provider, context class, and data-retention eligibility before routing
  sensitive material. Fable 5 requires 30-day retention and is unavailable
  under ZDR. A model capability decision is not a data-governance decision.
- Record refusals and automatic fallbacks explicitly; do not score a fallback
  response as if Fable produced it.

Source snapshot: Anthropic [Fable 5](https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5),
[adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking),
[effort](https://platform.claude.com/docs/en/build-with-claude/effort), and
[retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)
guidance, verified 2026-08-08.
