# Topic Format Reference

Complete format specification for digital garden topic pages. Referenced by
the capture skill's Step 4.

## New Topic Page Template

```markdown
---
title: Topic Title
stage: seedling
tags: [relevant, tags]
aliases: [Short Name, Abbreviation]
cssclasses: [topic]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
# Topic Title

> One-line description of what this topic covers.

---

## Entry title (YYYY-MM-DD) [verified]

Content of the entry.

<!-- captured: YYYY-MM-DD session:XXXXXXXX -->
```

## Confidence Tags

Optionally tag entry titles with confidence:

| Tag | When to use |
|-----|-------------|
| `[verified]` | Production-validated changes, confirmed behavior |
| `[exploratory]` | Speculative insights, single data point, untested theory |
| (omit) | Confidence is neutral or obvious from context |

## Alias Generation

When creating a new topic page, add 1-3 aliases to the frontmatter.
Aliases are alternate names Obsidian users might search for:

- **Abbreviations**: "OBO Authentication" → `["OBO", "OBO Auth"]`
- **Short forms**: "API Gateway Architecture" → `["API Gateway", "APIGW"]`
- **Synonyms**: "Supply Chain Security" → `["SCA", "Supply Chain"]`

Do not duplicate the title as an alias — Obsidian indexes titles automatically.

## Wiki-Linking Rules

When drafting entry content, check every concept, technology, or system name
against the link index built in Step 2.

**If a match exists**, insert a display-text wiki-link:
`[[topic-slug|Display Title]]`

Examples:
- "...the MCP gateway uses..." → `...the [[mcp-gateway-architecture|MCP Gateway Architecture]] uses...`
- "...similar to the hook patterns..." → `...similar to the [[hook-design-patterns|Hook Design Patterns]]...`

**Constraints:**
- Link on **first mention** only within an H2 entry — no repeat-linking
- Link naturally within prose, not as a list of see-alsos
- If no existing topic matches a concept, don't force a link

## Session Comment

At the end of each entry, add an HTML comment with session context:

```
<!-- captured: YYYY-MM-DD session:XXXXXXXX -->
```

Where `XXXXXXXX` is the first 8 characters of the active session id. Resolve
it as `${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID}}` — main-session surfaces
populate `CLAUDE_SESSION_ID`, while forked/subagent surfaces populate
`CLAUDE_CODE_SESSION_ID`. If both are empty, omit the `session:XXXXXXXX`
fragment rather than emit `session:` with a blank value. This is invisible in
Obsidian but enables tracing entries back to source sessions and prevents
ambiguous Edit matches when multiple entries share the same date.

## Maturity Stages

| Stage | Entry Count | Threshold |
|-------|-------------|-----------|
| seedling | 1-2 | Default for new pages |
| budding | 3-7 | Cross on 3rd dated H2 entry |
| evergreen | 8+ | Cross on 8th dated H2 entry |

Count only dated H2 entries matching `^## .* (YYYY-MM-DD)` — exclude
structural headings that don't represent dated knowledge entries.

## Oversized Entry — Prefer Splitting over Trimming

When an entry exceeds the ~2,500-char chunk budget (the memory-search chunker
splits on `##`; an over-long `##` becomes one oversized parent chunk that
buries concepts), **prefer SPLITTING over TRIMMING** — splitting preserves
detail that trimming destroys. Per the KB CLAUDE.md "Section size limit"
preference order:

1. **Promote to a new topic article** (preferred when the content is a
   distinct, self-contained concept or case study). An entry that has grown
   its own narrative arc — a deployment saga, a multi-gate investigation, a
   subsystem's design — belongs in its own `topic.md`, with the parent topic
   keeping a one-paragraph pointer (`see [[new-slug|Title]]`). This keeps a
   generic/mechanics topic generic and gives the new concept room to grow.
   (2026-06-19: the Proteus GovCloud saga split out of the generic ECS-Fargate
   topic into `proteus-govcloud-deployment.md` rather than being compressed.)
2. **Split into concept-named `###` sub-sections** (one concept too dense for
   a single chunk, not separable into its own article).
3. **Create a follow-up dated `##` entry** (genuine second capture event).
4. **Trim** ONLY content genuinely redundant with what's written elsewhere
   (e.g. mechanics already distilled to a rule/agent-memory) — trim to a
   pointer, never delete load-bearing detail to hit a character count.
