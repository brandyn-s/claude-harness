---
description: Preserve the operator's earned diagnostic, change-history, and negative-finding discipline without loading the historical playbooks
---

# Operator discipline

For debugging, behavior changes, and exhaustive findings, preserve three
decision boundaries:

1. **Diagnose from evidence.** Read the actual error, failing output, current
   source, and—when available—a last-known-good comparison before proposing a
   fix. A status label or analogy is not a diagnosis.
2. **Check why before changing behavior.** Before removing a control or changing
   a default, inspect the relevant git history and available project memory for
   the reason it exists. Treat prior notes as hypotheses and verify them against
   current source or runtime state.
3. **Prove negative findings.** Before reporting “none,” “unused,” or “not
   supported,” confirm the command succeeded, the result was not truncated or
   capped, and one independent native query agrees. A zero from a failed,
   partial, or semantic-only search is unknown.

Use the shortest discriminator that can change the decision. Once direct
evidence proves the outcome, follow `outcome-over-verification.md` and stop.
