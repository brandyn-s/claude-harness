---
paths:
  - "**/rules/agent-delegation.md"
  - "**/rules/incidents/agent-delegation.md"
---

# agent-delegation: Incident Narratives

Extracted from `rules/agent-delegation.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## inline-on-multi-step-cross-tool-work-breaks-context

```
WHY: "inline" on multi-step cross-tool work breaks context budget, loses
     topic-file guidance, and makes errors harder to isolate.
Example: User says "deploy terraform + verify IAM + check CI all inline."
         You MUST use dispatch_worker(topics=["infrastructure.md"]) — it's
         multi-step cross-tool work that needs the infrastructure playbook.
```

## without-topic-files-the-worker-operates-on-defaults-that

```
WHY: without topic files, the worker operates on defaults that have missed
     critical patterns (e.g. CrowdStrike MCP capabilities recurrence, Entra
     pagination, Ramp SQL 100-row limit).
```

## windows-incident-each-subagent-spawns-all-configured-mcp-servers

```
WHY (Windows incident): each subagent spawns ALL configured MCP servers
     (17+ at the time); 3 parallel agents = 51+ MCP child processes
     observed crashing Windows (35 GB Non-Paged Pool). Worktree-isolated
     parallel cleanup can destroy the entire .git directory (#48927).
```

## 2026-06-16-audit-skill-all-phase-2-11

```
WHY: 2026-06-16 /audit-skill --all Phase 2 — 11 general-purpose dispatches
     AND 1 Explore dispatch all blocked ("Subagent targets protected repo
     '.claude' with write operations"); pivoted to main-session execution.
     This is the DISPATCH-time gate, distinct from worktree-enforcement.py's
     Write|Edit-time block (subagent-verification.md). A capability-based
     gate cannot see read-only INTENT — Bash alone trips it.
```

## without-a-contract-workers-return-summaries-instead-of-structured

```
WHY: without a contract, workers return summaries instead of structured
     findings; claude-hud audit incident (2026-03-22) was 6/10 wrong claims
     from an Explore agent without a contract.
```

## 2026-04-24-two-parallel-explore-agents-dispatched-to

```
INCIDENT 2026-04-24: Two parallel Explore agents dispatched to review 41 PowerShell
runbooks (~1MB total source). Both returned "Prompt is too long" — failed before
touching any file. Cause: parent session had ~250K+ tokens loaded (system reminders,
rules, claudeMd, prior tool outputs); the dispatch prompt + inherited context
exceeded the spawn limit. Recovery: fell back to main-thread direct file reads with
targeted Grep + Read offset/limit. Cost ~10K tokens but worked.
```

## 2026-04-30-dispatched-agent-to-verify-94-sp

```
INCIDENT 2026-04-30: dispatched agent to verify 94 SP candidates with per-SP sign-in
checks. Agent invented its own approach: bulk dump all `auditLogs/signIns` in time
slices and group by appId. Stalled at 600s no-progress on the dumps; watchdog killed
it. Per-SP queries (`appId eq '<id>'`, $top=1, parallel batch of 10-15) would have
finished in ~90 seconds.
```

## 2026-08-29 — the measured failure is UNDER-delegation on multi-hypothesis investigation
<a id="2026-08-29-under-delegation"></a>

Every incident above is an OVER-delegation failure: too many agents, wrong context,
unsafe parallelism. The rule is written accordingly and it works. This is the first
recorded instance of the opposite, and it is the expensive one.

Measured on a 4,578-turn session: **12 of 2,045 tool calls (0.6%)** were
`Agent`/`Workflow`. Effort distribution — git/PR/CI 611 (29%), read/search 453 (22%),
authoring 371 (18%), delegate 12 (0.6%). The single most expensive phase, an
identity/consent investigation, spent **1,130 turns and 35% of all session errors**
working three competing hypotheses (wrong identity vs wrong scope vs wrong tenant)
strictly serially. Each was answerable by a bounded READ against a different
surface, so none of them contended for a writer — the exact RISK MEDIUM shape the
rule already permits.

**Why the rule did not fire.** Nothing in it is wrong; the shape was simply not
recognised as delegable, because the work FELT sequential — each hypothesis was
formed after the previous one was refuted. But they were independent from the start;
only my discovery of them was serial. That is the tell worth naming: if you can
enumerate the competing explanations, the enumeration is the fan-out, regardless of
the order they occurred to you.

**Adversarial pairing, measured the same session.** A read-only fan-out over 11
candidates returned one verdict that a refutation agent then OVERTURNED — the
evidence described a live resource owned by a DIFFERENT root, and that root had been
deprecated. A serial pass would have shipped it. The asymmetry worth copying: verify
only findings whose being-wrong costs something. A wrong "not live" verdict leaves
the status quo; a wrong "live" verdict gets acted on. Spend the refutation budget on
the second kind — the same logic as `symmetric-evidentiary-burden.md`'s stakes-follow
-the-bar rule, applied to which findings get a second reader rather than to how many
sources each needs.

## 2026-05-30-64080-observed-on-claude-code-v2

```
INCIDENT 2026-05-30 (#64080, observed on Claude Code v2.1.158 + Opus 4.8, plain
Task/Agent fan-out — NOT Agent Teams): a single assistant turn that fanned out a
FIXED set of parallel subagents degenerated into re-emitting the same batch ~4×
before yielding the turn. Intended fan-out of 6 ran as 24, each a full subagent at
70k-220k tokens. The harness does NOT dedup identical parallel tool_use blocks and
has NO concurrent-fan-out cap, so the ~4× token blowup is SILENT until the
running-agent count is noticed. Companions in the same Opus-4.8/1M/parallel-batch
instability class: #64774 (QUANTIFIED /gather-claude 2026-06-05 — opus-4-8 emits
malformed/unparseable tool-call markup at ~1.5% [148/9805 turns], 0% on
4.7/sonnet-4.6/haiku; antml: prefix dropped → harness silently drops the call →
turn STALLS ["agent silently stopped"]; correlates with 1M context + long sessions
+ reasoning blocks + long/CJK args + AskUserQuestion long descriptions; persists
v2.1.156/160/161; #63998 closed DUPLICATE into this), #65423 (/gather-claude
2026-06-05 — ≥3 parallel subagents permanently WEDGE on Windows + Opus-4.8-1M:
finish work, return "Tool result missing due to internal error", then go unkillable
8h+, ignore queued input, hold agent slots; only a full session restart clears
them; v2.1.162), #63884 (model hallucinates results before parallel tasks finish),
#64095 (tool-result envelope injected into the tool-call input channel during
parallel batches). Root: near-identical short parallel prompts on Opus 4.8 + long
1M sessions maximally seed an autoregressive re-emission loop.
```
