---
paths:
  - "**/skills/_shared/subagent-tool-discipline.md"
  - "**/rules/incidents/subagent-tool-discipline.md"
---

# subagent-tool-discipline: Incident Narratives

Extracted from the subagent contract (now
`skills/_shared/subagent-tool-discipline.md`) to keep it small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## the-read-tool-truncates-output-by-default-when-a

```
WHY: the Read tool truncates output by default. When a subagent
     cites a specific line number (e.g. `types.ts:262`) without
     having actually read that line, the citation is hallucinated.
     2026-04-29 Exp 6 (4 of 15 failing traces): direct quote —
     "Agent produced final markdown table with line numbers (e.g.
     types.ts:262) inferred from a partial Read of types.ts that
     only returned ~10 visible lines (255-264 truncated); never
     re-read the rest."
```

## when-prompt-is-too-long-or-equivalent-context-overflow

```
WHY: when "Prompt is too long" or equivalent context-overflow
     error returns, silent termination produces apparent success
     from the parent's view. The subagent must emit
     INSUFFICIENT_CONTEXT explicitly so the parent can re-dispatch
     with reduced scope. 2026-04-29 Exp 6 (6 of 15 failing traces):
     direct quote — "Agent terminated with 'Prompt is too long'
     after only one Glob and one failed Read on a directory,
     without exploring source files."
```

## from-the-parent-s-perspective-a-subagent-that-returns

```
WHY: from the parent's perspective, a subagent that returns
     partial work without flagging it is indistinguishable from
     one that completed correctly. The cost of explicit failure
     is one re-dispatch; the cost of silent partial is the parent
     acting on incorrect data.
```
