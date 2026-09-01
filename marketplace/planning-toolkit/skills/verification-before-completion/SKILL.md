---
name: verification-before-completion
description: "Prove the requested outcome with the smallest decisive evidence before claiming completion."
when_to_use: "Use immediately before a completion, fixed, passing, or ready-to-ship claim. Do not use as a substitute for implementation or as an excuse for repeated review."
effort: medium
metadata:
  author: example-security-engineering
  version: "2.0"
allowed-tools: Bash Read Grep AskUserQuestion
---

# Verification before completion

Verification is evidence for an outcome. It is not a separate deliverable.

## Declare the gate

Before running a verifier, name four things:

1. **Observable outcome** — what the user will be able to do or observe.
2. **Smallest decisive evidence** — the native command or runtime observation
   that answers whether the outcome exists.
3. **First material falsifier** — the first result that would make the
   completion claim false.
4. **Time budget** — how long this evidence path gets before it is simplified.

Prefer the product's native runtime, build, test, deployment, or readback. Add a
custom verifier only when native evidence cannot answer the material decision.

## Run and reconcile

Run the complete authoritative command fresh. Read its exit status and the
failure count; do not infer success from a partial command or an earlier run.

Then perform the **Outcome Reconciliation Gate**:

- Re-read the latest user outcome.
- List any unresolved acceptance blockers.
- Distinguish authored, tested, installed, deployed, and live-verified states.
- Settle actionable review findings once; do not repeat review to seek unanimity.
- If the decisive evidence passes, stop verification and report the outcome.

Repair a custom verifier at most once. If it is defective again, discard or
simplify it, narrow the claim, and use native evidence. Stop on the first
material falsifier.

## Reporting

Report the command, result, and remaining boundary in plain language. Never turn
skipped evidence into a pass. Never say "should pass" when a fresh command can
answer the question.

Example — code change:

> Outcome: malformed input no longer crashes the parser. Evidence: the focused
> regression test plus the repository's normal suite. Falsifier: either command
> reports a failure. Both ran clean; deployment was not requested.

Example — deployment:

> Outcome: the running service serves the new behavior. Evidence: exact deployed
> revision readback and one request through the real endpoint. Falsifier: a
> different revision or wrong response. Source and CI alone are insufficient.
