# Model Runtime Policy

This is the active, model-independent runtime contract for skills. Model
names and behavior notes are overlays, not security or completion controls.

## Model-independent runtime contract

1. Resolve the effective model and provider at runtime. Do not infer them
   from a moving alias, a repository default, or an earlier session.
2. Record the requested and effective model, effort, provider, context class,
   Claude Code version, fallback/switch reason, and refusal outcome whenever a
   workflow produces qualification evidence. History-producing event logs use
   a `runtime_receipt` object for these fields. Mark every unobserved value
   `<unavailable>`; `CLAUDE_MODEL` is requested/default provenance and must not
   be relabelled as the effective model.
3. Treat refusals, fallbacks, partial results, and model switches as typed
   outcomes. None is an unqualified success.
4. Keep authorization, scope, evidence, artifact, and destructive-operation
   controls deterministic and model-independent.
5. Use external acceptance oracles for required artifacts and runtime
   behavior. Do not add blanket prompt reminders merely because an older
   model once needed them.
6. Never assume a fixed context window. Use the active lane's reported
   capacity and produce a durable checkpoint/handoff only at a real boundary.
7. For a cross-model validation, second-rater, or panel task, every arm is its
   vendor's flagship; a mid-tier arm confounds the comparison. Substitute another
   vendor's flagship or surface the block rather than downgrade silently, and
   record each arm's exact model id and tier (`rules/eval-shipping-discipline.md`).

## Current overlays

Load only the overlay matching the effective model family:

- `model-overlays/fable-5.md`
- `model-overlays/mythos-5.md`
- `model-overlays/opus-5.md`
- `model-overlays/sonnet-5.md`

Historical measurements remain valid evidence for the model and configuration
that produced them, but they are not current runtime policy. Exact model IDs
belong in frozen baselines and qualification receipts; moving aliases are for
interactive routing only.

## Defensive-security refusals

Legitimate defensive work may still produce a refusal. Preserve the refusal
and effective-model metadata, confirm that the request stays within authorized
defensive scope, and follow the organization's approved access/escalation path.
Do not weaken, disguise, or fragment the request to bypass safeguards.

Sources verified 2026-08-08: Anthropic [model configuration](https://code.claude.com/docs/en/model-config),
[effort](https://platform.claude.com/docs/en/build-with-claude/effort),
[migration](https://platform.claude.com/docs/en/about-claude/models/migration-guide),
and [Fable 5 / Mythos 5](https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5),
[refusal/fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback)
guidance.
