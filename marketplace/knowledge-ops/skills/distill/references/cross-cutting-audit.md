# Cross-cutting audit (Step 1d detail)

> Added 2026-05-06 from code-search session lesson "audit-then-find-zero is also a finding".

Before classifying a lesson as T1 (ambient rule, applies everywhere) or
recommending speculative cross-repo remediation, ask: **is this pattern
likely repo-local or cross-cutting?** If unsure, run a focused 5-minute
grep across 2-3 sibling repos BEFORE assigning the tier.

**Why**: lessons routed to T1 load ambient in every conversation. If the
pattern is actually repo-local, the rule wastes context and may produce
false guidance. The natural reflex on "this seems important" is to assume
it's everywhere — the audit converts unknown into one of two confirmed
states cheaply.

## Trigger conditions (only audit when at least one fires)

- Pattern has a grep-friendly signature (function name, env var name,
  hardcoded constant, specific anti-pattern shape)
- Lesson would route to T1 (universal rule) and you haven't seen the
  pattern fail in another repo
- Recommendation includes "this probably affects other repos too"
  language

## Audit procedure

1. Identify the grep signature (e.g. `asyncio\.run\(.*AsyncAnthropic`)
2. Run main-thread Grep on 2-3 candidate sibling repos. Skip Explore
   agent dispatch when parent context is large — the prompt-too-long
   recovery cost is documented in `rules/agent-delegation.md`.
3. Tabulate hits per repo

## Decision rule

- **≥2 repos with hits** → confirmed cross-cutting → T1 rule, fix-everywhere
- **0 hits across N≥3 sibling repos** → confirmed repo-local → T4
  in the originating-repo's topic file
- **Did not audit** → flag as "T1 candidate, audit pending" rather than
  promoting prematurely

## Empirical example

The 2026-05-06 code-search session: three patterns from PR #126 / #130 /
#131 were candidates for cross-cutting promotion. A 5-minute focused
grep across mcp-servers + mcp-infra + code-graph found 0 hits on all
three. They were repo-local; T4 entries in code-search-dev.md were the
right tier. The audit prevented speculative remediation work in three
sibling repos and false confidence about "fix everywhere coverage."

See: knowledge-base/topics/engineering-assessment-methodology.md
section "Audit-then-find-zero is also a finding (2026-05-06)".
