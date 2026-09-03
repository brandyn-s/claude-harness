---
name: design-evidence-first
description: "Companion to superpowers:brainstorming: before the first clarifying question, answer it from transcripts, memory, git history, and the existing code; validate one interpretation checkpoint; for significant designs dispatch competing-constraint agents; triage ideas Critical, High, Nice, Skip."
when_to_use: 'Use at the START of superpowers:brainstorming, before its first question, whenever the topic already has history in this repository or this user''s sessions, or when a design decision is significant enough (new skill, service, module split, API) that a single perspective would converge on the middle ground. Trigger phrases: "check what we already know", "evidence first", "competing designs", "before you ask me". Do NOT use for a fresh topic with no local history, and do NOT use as a replacement for brainstorming itself.'
allowed-tools: Read Grep Glob Bash Agent AskUserQuestion
---

# Design evidence first

Companion to `superpowers:brainstorming`, which owns the question-and-design
dialogue. This skill front-loads the evidence so that dialogue starts from
facts. Extracted on 2026-09-03 from this repository's fork of superpowers
v4.3.1.

> **Output grounding (REQUIRED READ)**: when the design will produce output for
> a non-expert user, read `skills/_shared/output-grounding.md` first and carry
> its three-layer contract into the design.

## 1. Answer the question from the data before asking it

Before asking the user any clarifying question, check whether the answer is
already in the material at hand:

- **Session transcripts**: `~/.claude/projects/<project-id>/*.jsonl` for prior
  discussion of this topic. If the project id is unknown, resolve it via
  `skills/_shared/project-dir.md` or skip this source rather than reading an
  empty path.
- **Persistent memory**: the auto-memory directory and, where installed, the
  knowledge base under `~/Documents/knowledge-base/topics/`.
- **Git history**: `git log --oneline --all --grep="<topic>"` for prior work.
- **Existing implementations**: read the actual code, skill, or hook the feature
  touches, not its description.
- **Tool usage**: if an MCP tool is involved, read how it is used today.

For each question you would ask, check in order: the codebase, git history,
memory, transcripts. If the data answers it, state the finding and your
interpretation instead of asking: "Based on [source], I see [finding]. I am
interpreting this as [conclusion]; correct?"

Ask the user only when the question is genuinely ambiguous, is about future
intent rather than current state, the sources disagree, or no data exists.

Measured 2026-03-28 across 14 days of transcripts: five of fifteen brainstorm
sessions had the user redirecting with "based on my usage, what do you think?"
The skill was asking questions the data could answer.

## 2. One interpretation checkpoint

After gathering evidence and before the first question, validate the
interpretation once:

"Based on [sources read], here is my understanding: [one or two sentences].
The key constraints appear to be [list]. Is this right, or am I misreading
something?"

A wrong inference from git history or existing code otherwise propagates
silently through every later question and into the design. Skip the
checkpoint when the evidence is unambiguous.

When the questions do begin, a bare "Proceed" accepts the stated defaults and
ends optional questioning; "start building" is an immediate fast-forward.
Record non-blocking unknowns as assumptions and continue. Never infer a data
classification from field names; use an authoritative source or the user's
explicit statement.

## 3. Competing-constraint agents for significant designs

For small decisions, propose two or three approaches conversationally with
trade-offs and a recommendation. For significant designs where the right
interface is not obvious, dispatch three agents with deliberately different
constraints:

```
Agent 1: minimize the interface — one to three entry points at most
Agent 2: maximize flexibility — support many use cases and extension
Agent 3: optimize for the most common caller — make the default case trivial
```

Each produces an interface sketch, a usage example, what it hides, and its
trade-offs. Present all three, compare in prose, then recommend one or a hybrid.
A single perspective proposing alternatives converges on the middle ground;
mandated biases cannot converge, so the disagreement is structural and exposes
trade-offs one voice misses. Skip this when the decision is small, the user
has a strong preference, or fewer than two plausible shapes exist. (Pattern
source: mattpocock/skills improve-codebase-architecture, Context7 registry
2026-04-06.)

## 4. Triage ideas before they become plan items

Tag each idea Critical, High, Nice, or Skip before it enters the design.
Skip-tagged ideas are dropped, not carried forward. Default to the smallest
correct change; this stops speculative build-everything ideas from surviving
into the plan.

Hand the evidence, the checkpoint result, and the triaged ideas to
`superpowers:brainstorming`, then to `superpowers:writing-plans`.
