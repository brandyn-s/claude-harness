---
name: api-guardrails
description: "Production-readiness checklists for Claude API apps — fewer hallucinations, more consistent output."
when_to_use: "Use when building a Claude API application, writing system prompts, designing prompt pipelines, or reviewing Claude API code for production readiness. Provides checklists for reducing hallucinations and increasing output consistency. Do NOT use for Claude Code operational rules, non-Claude AI APIs, or general coding tasks."
effort: medium
argument-hint: "[system-prompt or code-file to review]"
allowed-tools: Read Grep Glob
verified_on: 2026-09-04
metadata:
  author: example-security-engineering
  version: "2.0"
---

# API Guardrails — Reduce Hallucinations and Increase Consistency

Companion to the `claude-api` skill. Apply these patterns to applications that
call the Claude API or Agent SDK. Resolve the effective runtime first; do not
assume that a model name, provider, feature, or retention contract is portable.

> **Runtime policy:** Follow `../_shared/model-runtime-policy.md`. Record the
> requested and effective model, provider, effort, context class, fallback or
> switch reason, and refusal outcome for each production request path.

Primary sources (verified 2026-09-04):

- [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) and its model pages
- [Choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
- [Migration guides](https://platform.claude.com/docs/en/about-claude/models/migration-guide)
- [Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking) and its [per-model table](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting)
- [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback)
- [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)
- [Reduce hallucinations](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)

## Step 1 — Resolve the Runtime Contract

Before reviewing prompts, identify:

1. Requested model and model ID actually returned by the provider.
2. Provider surface: Claude API, Claude Platform on AWS, Amazon Bedrock,
   Google Cloud, or Microsoft Foundry.
3. Effective effort and thinking mode.
4. Data-retention arrangement and whether the selected model is eligible.
5. Every terminal outcome: normal completion, truncation, refusal, fallback,
   tool use, pause, or API error.

Fail closed when a required capability or retention arrangement cannot be
confirmed. A provider redirect, fallback, or refusal is not an unqualified
success even when the HTTP status is 200.

### Current model capability matrix

<!-- model-capabilities:begin -->
<!-- Generated from contracts/model-capabilities.json by bin/render-model-capabilities.py; edit the contract, then run it with --write. -->
Rows verified 2026-09-04 against the primary sources above; `contracts/model-capabilities.json` is the source of record.

| Model | Thinking | Effort | Request restrictions | Retention and refusal notes |
|---|---|---|---|---|
| Claude Fable 5.1 (`claude-fable-5-1`) | Adaptive thinking is always on; `thinking: {"type": "disabled"}` returns 400. Manual `enabled`/`budget_tokens` returns 400. | `low`, `medium`, `high` (default), `xhigh`, `max` | Non-default `temperature`/`top_p`/`top_k` return 400. Assistant-message prefill returns 400. | Covered Model: requires 30-day data retention and is unavailable under ZDR. Handle classifier refusals and qualify fallback behavior. Web fetch is available. Priority Tier is unavailable. 1M context window; 128k max output. Forced `tool_choice` (`any`/`tool`) returns 400; keep `auto` and instruct. Thinking blocks are bound to the producing model and conversation; keep history append-only. |
| Claude Mythos 5.1 (`claude-mythos-5-1`) | Adaptive thinking is always on; `thinking: {"type": "disabled"}` returns 400. Manual `enabled`/`budget_tokens` returns 400. | `low`, `medium`, `high` (default), `xhigh`, `max` | Non-default `temperature`/`top_p`/`top_k` return 400. Assistant-message prefill returns 400. | Limited Project Glasswing availability. Covered Model: requires 30-day data retention and is unavailable under ZDR. Web fetch is available. Priority Tier is unavailable. 1M context window; 128k max output. Forced `tool_choice` (`any`/`tool`) returns 400; keep `auto` and instruct. Refusal behaviour is not stated by the vendor; handle `stop_reason: refusal`. |
| Claude Opus 5 (`claude-opus-5`) | Adaptive thinking is on by default. Thinking may be disabled at `low` through `high`; disabled + `xhigh`/`max` returns 400. Manual `enabled`/`budget_tokens` returns 400. | `low`, `medium`, `high` (default), `xhigh`, `max` | Non-default `temperature`/`top_p`/`top_k` return 400. Assistant-message prefill returns 400. | Handle classifier refusals and qualify fallback behavior. Web fetch is unavailable. Priority Tier is unavailable. 1M context window; 128k max output. Re-run effort sweeps rather than inheriting earlier-model settings. |
| Claude Sonnet 5 (`claude-sonnet-5`) | Adaptive thinking is on by default and may be disabled at any supported effort. Manual `enabled`/`budget_tokens` returns 400. | `low`, `medium`, `high` (default), `xhigh`, `max` | Non-default `temperature`/`top_p`/`top_k` return 400. Assistant-message prefill returns 400. | Handle cyber-safeguard refusals. Web fetch is available. Priority Tier is unavailable. 1M context window; 128k max output. Re-count tokens and re-test truncation because it uses a different tokenizer from Sonnet 4.6. |
| Claude Haiku 4.5 (`claude-haiku-4-5`) | Adaptive thinking is not supported. Manual extended thinking (`enabled` + `budget_tokens`) is supported. | Effort is unavailable. | `temperature` or `top_p` may be set, one at a time. Assistant-message prefill is accepted. | Priority Tier is supported. 200k context window; 64k max output. Current low-latency, high-volume, cost-sensitive option. Do not apply Claude 5 request restrictions to it. |
<!-- model-capabilities:end -->

For the Claude 5 rows above:

- Where an assistant-message prefill used to steer the output shape, use
  structured outputs (`output_config.format`) or system instructions instead.
- Use `output_config={"effort": "..."}` to tune total response work. Effort
  affects text, thinking, and tool use; it is a behavioral signal, not a token
  budget.
- Leave headroom in `max_tokens`: it limits thinking plus visible response.
- Do not ask the model to reveal private chain of thought. If readable reasoning
  is needed for an approved use case, request summarized thinking through the
  supported `thinking.display` contract and treat it as a summary, not an audit
  log of hidden reasoning.

Do not copy this matrix onto older or third-party models. Resolve the exact
model/provider feature table at runtime and keep compatibility branches scoped
to the model they serve.

## Step 2 — Reduce Hallucinations

### 1. Ground responses in supplied evidence

Tell Claude which sources are authoritative and what to do when they are
insufficient. Do not forbid all general knowledge unless the task truly requires
a closed evidence set.

```python
system = """Answer from the supplied documents only.
If the documents do not support an answer, return INSUFFICIENT_EVIDENCE and
name the missing evidence. Do not fill gaps from memory."""
```

### 2. Require evidence-addressable citations

Use the Citations API for supported document inputs or require stable source
locations. Verify that cited text actually entails the claim; citation presence
alone is not grounding.

### 3. Separate generation from an external oracle

For high-stakes claims, check the result against source documents, schemas,
calculators, tests, or a separately grounded verification call. Do not rely on a
blanket "double-check yourself" instruction: current models already self-verify
more often, and repeated reminders can add cost without independence.

```python
draft = client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    output_config={"effort": "high"},
    system="Draft a merger-report summary with source locations for every claim.",
    messages=[{"role": "user", "content": report}],
)

verified = client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    output_config={"effort": "medium"},
    system="Compare each draft claim with the original. Return only supported claims and an exception list.",
    messages=[{"role": "user", "content": f"ORIGINAL:\n{report}\n\nDRAFT:\n{draft_text}"}],
)
```

### 4. Use retrieval deliberately

Retrieve a bounded, versioned context set. Record document identifiers and
retrieval timestamps, and distinguish "not retrieved" from "not present in the
corpus."

### 5. Use disagreement as an evaluation signal

For the highest-stakes offline evaluations, compare independently sampled or
model-diverse outputs against a labeled oracle. Do not turn Best-of-N into a
default production ritual without measuring accuracy gain, latency, and cost.

## Step 3 — Increase Output Consistency

### 1. Prefer structured outputs for machine contracts

Use `output_config.format` or `client.messages.parse()` when downstream code
expects a schema.

```python
from pydantic import BaseModel
from typing import Literal

class FeedbackAnalysis(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"]
    urgency: Literal["low", "medium", "high"]
    summary: str

response = client.messages.parse(
    model="claude-sonnet-5",
    max_tokens=2048,
    output_config={"effort": "low"},
    messages=[{"role": "user", "content": f"Analyze: {feedback}"}],
    output_format=FeedbackAnalysis,
)
```

### 2. Specify semantics, not just syntax

Define field meanings, valid evidence, abstention behavior, and tie-breaking.
Schemas prevent malformed JSON; they do not make a wrong classification true.

### 3. Add representative few-shot examples

Use examples that cover boundary cases and abstention, not only happy paths.
Keep the examples consistent with the schema and current business rules.

### 4. Decompose only where the boundary is testable

Split extraction, verification, and synthesis when each stage has a clear
contract and failure state. Avoid chains whose intermediate prose merely gives
later calls more unverified material to trust.

### 5. Tune effort with task-family evaluations

Start at the model default (`high`) for a new workload, then sweep down or up.
Use `low`/`medium` for scoped work only when evals hold; use `xhigh`/`max` only
when measured gains justify latency and spend. Re-run the sweep after a model
change—an effort label is not a cross-model performance equivalence.

## Step 4 — Handle Refusal, Fallback, and Partial Results

Refusal-capable models (Fable 5.1, Opus 5) can return a classifier refusal as HTTP 200.
Treat it as a typed terminal outcome:

```python
response = client.messages.create(
    model="claude-opus-5",
    max_tokens=4096,
    output_config={"effort": "high"},
    messages=[{"role": "user", "content": user_request}],
)

if response.stop_reason == "refusal":
    details = response.stop_details
    record_refusal(
        category=getattr(details, "category", None),
        explanation=getattr(details, "explanation", None),
    )
    return refusal_response(details)
```

Required behavior:

1. Branch on `stop_reason == "refusal"` or `stop_details.type`, not response
   text. Category and explanation may be null.
2. Discard partial content from a refused response; it is incomplete.
3. Reset or reframe the triggering conversation state before continuing.
4. Retry on a separately qualified model when fallback is allowed; repeating
   the same request on the same model usually repeats the refusal.
5. Treat fallback as request configuration, not ambient global state. Give
   subagent calls their own fallback policy.
6. Record requested and effective model. For server-side fallback, inspect the
   top-level model, `fallback` content block, and `usage.iterations`.
7. Do not assume fallback handles capacity failures: the documented mechanism
   is for classifier refusals, not rate limits, overload, or server errors.
8. Message Batches do not support server-side fallback. Retry refused batch
   items explicitly and strip model-bound Fable thinking blocks from history.

Server-side fallback is a beta contract. Pin the required beta date, confirm
the Models API allows each target, and qualify every fallback model against the
same schema, tool, retention, latency, and quality requirements before enabling
it. A silent model change invalidates model-specific evaluation claims.

## Step 5 — Enforce Data Governance Before Model Selection

- Fable 5.1 and Mythos 5.1 (and their 5.0 predecessors) are Covered Models:
  30-day data retention, no ZDR unless Anthropic expressly authorizes it. Do
  not select either merely as a quality upgrade; Mythos 5.1 also requires
  Project Glasswing access.
- Retention responsibility differs by provider. On the Claude API and Claude
  Platform on AWS, Anthropic is the data processor; on Amazon Bedrock and
  Google Cloud, consult the provider's equivalent controls.
- Feature retention can differ from base Messages API retention. Re-check files,
  managed agents, code execution, MCP, skills, and other stateful features.
- Log the policy decision without logging prompts, responses, or secrets beyond
  the approved evidence boundary.

## Prompt Diagnostic Checklist

Load `references/prompt-diagnostic.md` for the full pattern checklist. Before
shipping, confirm:

- [ ] authoritative sources and insufficient-evidence behavior are explicit
- [ ] output schema includes semantic constraints and abstention states
- [ ] tool permissions and iteration/stop conditions are bounded
- [ ] every stop reason has a tested branch
- [ ] requested/effective model, effort, provider, refusal, and fallback are observable
- [ ] retention and model eligibility are approved for every request path
- [ ] evaluation fixtures cover normal, truncated, refused, fallback, and malformed outcomes

## Examples

### Example 1 — RAG pipeline review

Input: `/api-guardrails my-rag-app/prompts/synth.py`

Output: identifies missing source constraints and unsupported citations, then
recommends document IDs, an insufficient-evidence state, and entailment checks.

### Example 2 — Classifier migration

Input: `/api-guardrails classify-tickets.py`

Output: replaces sampling knobs with a structured-output schema, starts Sonnet 5
at `high`, and proposes a measured effort sweep before lowering production cost.

### Example 3 — Fable evaluation path

Input: `/api-guardrails high-stakes-review.py`

Output: blocks deployment until 30-day data retention is approved, adds typed
refusal handling, and validates any fallback model independently.

## Success Criteria

- User-facing claims are grounded, cited where applicable, and allowed to abstain.
- Machine-consumed output is schema-validated and semantically tested.
- Model-specific controls are gated by the effective model and provider.
- Refusal, truncation, fallback, and API errors cannot masquerade as success.
- Retention eligibility is confirmed before data reaches the selected model.
- Effort, latency, cost, and quality are requalified after model changes.

## Audit Coverage

This skill is documentation-only: it contains no scripts, state files, or
deployed executable. Script error paths, writer/reader formats, on-disk schemas,
and deployed entry-point tests are therefore not applicable. Revisit that
assessment if executable behavior is added.
