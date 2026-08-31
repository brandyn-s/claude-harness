# Sonnet 5 Runtime Overlay

- Use the exact effective model identifier in automated qualification.
- Recount prompt and output headroom with the target model's token-counting
  endpoint; do not reuse Opus 4.x proxy multipliers.
- Keep progress-update instructions minimal unless the workflow has a specific
  receipt or checkpoint contract.
- Qualify effort per task family rather than inheriting a global `xhigh` choice.
- Record fallback, refusal, provider, and context class with the result.

Source snapshot: Anthropic [Sonnet 5 release guidance](https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5)
and [effort](https://platform.claude.com/docs/en/build-with-claude/effort),
verified 2026-08-08.
