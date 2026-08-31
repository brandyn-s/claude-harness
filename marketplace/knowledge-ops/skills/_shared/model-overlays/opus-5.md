# Opus 5 Runtime Overlay

- Use the exact effective model identifier in automated qualification.
- Prefer lean task contracts. Do not add blanket final-verification or
  verifier-subagent instructions; retain independent artifact/runtime oracles.
- Compare `high` and `xhigh` only on representative, scored task families.
- Record automatic switches and fallbacks so an Opus result is never attributed
  to another requested model, or vice versa.
- Keep delegation risk-tiered. Model capability does not expand authority or
  justify unnecessary fan-out.

Source snapshot: Anthropic [Opus 5 migration](https://platform.claude.com/docs/en/about-claude/models/migration-guide),
[effort](https://platform.claude.com/docs/en/build-with-claude/effort), and
[refusal/fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback)
guidance, verified 2026-08-08.
