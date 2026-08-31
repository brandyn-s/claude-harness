# Ubiquitous Language

> Canonical terms for the Example Claude Code architecture. When a skill, rule,
> hook, or doc uses these terms, they mean exactly this — nothing more, nothing less.
> Generated 2026-04-06 by /scout-skills (mattpocock/ubiquitous-language pattern).

---

## Architecture Layers

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **MCP server** | An integration that lets Claude call an external API via Model Context Protocol | Plugin, connector, integration (too vague) |
| **Skill** | A reusable multi-step workflow defined as a SKILL.md file in a kebab-case directory under `~/.claude/skills/` | Command (ambiguous — see below), playbook, recipe |
| **Slash command** | A `/name` invocation that triggers a skill or built-in CLI command | Skill (not all slash commands are skills — `/help`, `/clear` are built-ins) |
| **Rule** | A markdown file in `~/.claude/rules/` loaded into every conversation turn as ambient context | Constraint, guideline, policy (see Enforcement below) |
| **Hook** | A Python script that runs automatically before or after a tool call, session event, or agent lifecycle event | Guard, gate, validator (see Enforcement below) |
| **Agent** | A Claude subprocess spawned via the Agent tool with its own context window | Worker, subagent (see Agent Types below) |

## Agent Types

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Main thread** | The primary Claude session that the user interacts with directly | Parent, orchestrator (implies the main thread always delegates — it often doesn't) |
| **Worker** | A generic agent defined in `agents/worker.md` that loads topic files on demand | Subagent (too generic — there are 5 agent types), helper |
| **Subagent** | Any agent spawned by the main thread or another agent via the Agent tool | Worker (a worker is one type of subagent) |
| **Agent team** | Multiple agents sharing a task list, coordinated by a team lead | Multi-agent, swarm (overloaded industry terms) |
| **Explore agent** | A specialized subagent type for codebase search and exploration | Research agent (Explore has specific tool restrictions — no Edit, Write, Agent) |

## Memory and Persistence

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Topic file** | A 20-50 line file in `~/.claude/agent-memory/topics/` containing critical gotchas and key patterns for one tool or domain. Loaded by workers on demand. | Agent memory (ambiguous — topic files are one PART of agent memory), pattern file (different tier) |
| **Pattern file** | A deep-reference file in `projects/.../memory/` with full API documentation and response shapes. Mostly consolidated into knowledge base (2026-03-25). | Topic file (different tier — pattern files are deeper, topic files are summaries) |
| **Knowledge base** | A digital garden of dated wiki entries in `~/Documents/knowledge-base/topics/`. Managed by /capture, /recall, /garden. | KB, wiki, docs (ambiguous) |
| **MEMORY.md** | A concise index file always loaded into conversation context. Capped at 200 lines. Pointers to details, not details themselves. | Memory, config (MEMORY.md is an index, not a store) |
| **Auto-memory** | The built-in Claude Code memory system that writes to `~/.claude/projects/.../memory/` based on `memory:` frontmatter settings | Session memory (different thing — auto-memory persists, session context doesn't) |

## Enforcement Mechanisms

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Guard** | A PreToolUse hook that **blocks** a tool call by exiting with code 2 | Hook (too generic — not all hooks guard), validator |
| **Fixer** | A PostToolUse hook that **modifies** output after a tool call completes | Hook (too generic), transformer |
| **Gate** | A skill step that requires explicit user input via AskUserQuestion before proceeding. Binary — happened or didn't. | Guard (guards are hooks, gates are skill steps), checkpoint |
| **Rule** | Ambient context loaded every turn — followed by convention, not enforced by code | Constraint (implies enforcement — rules can be ignored under cognitive load) |
| **Enforcement** | A hook, CI check, or startup validation that fires automatically — cannot be skipped | Rule (rules are guidance; enforcement is mechanical) |
| **Drift gate** | An automated check (`bin/architecture-drift-check.py`, run by pre-push + CI) that fails when a documented claim — a count, a hook table, a pinned settings value — no longer matches the repo | Lint (style, not claim-vs-reality), validator (too generic) |

## Skill Lifecycle

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Invoke** | Trigger a skill via `/skill-name` or keyword match | Run, execute, call (invoke is the standard term in Claude Code docs) |
| **Ship** | The full PR lifecycle: branch, commit, push, PR, CI, merge, sync | Commit (just one step), push (just one step), deploy (we don't deploy from /ship) |
| **Distill** | Extract errors and operational fixes from a session into persistence tiers | Capture (different skill — distill is errors, capture is strategic insights) |
| **Capture** | Record strategic decisions, lessons, and patterns to the knowledge base | Distill (different skill — capture is strategic, distill is operational) |
| **Retro** | Run /distill then /capture in sequence with shared context | Postmortem (retro is lighter — no formal incident response) |

## Change Classification

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Additive** | A change that adds content alongside existing behavior without modifying it (new example, diagram, table, step) | Enhancement, improvement (too vague — additive means specifically "nothing existing changes") |
| **Structural** | A change to how a skill or rule is organized (new reference file, new frontmatter field, refactored sections) | Refactor (structural can add new files, refactor typically doesn't) |
| **Behavioral** | A change that alters execution: model routing, workflow order, output format, enforcement logic | Breaking change (behavioral changes may not break anything — they change how the system acts) |

## Relationships

- A **Skill** is invoked by a **Slash command**, but not all slash commands map to skills
- A **Worker** is a type of **Subagent** that loads **Topic files** for domain context
- A **Guard** is a type of **Hook** that blocks; a **Fixer** is a type of hook that modifies
- A **Gate** lives inside a **Skill**; a **Guard** lives in `hooks/` and `settings.json`
- **Distill** writes to **Rules**, **Topic files**, and **MEMORY.md** (operational)
- **Capture** writes to the **Knowledge base** (strategic)
- **Retro** chains Distill then Capture, deduplicating between them

## Search and Intelligence

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Semantic search** | Query-by-meaning search over code or documents using vector embeddings (FAISS + Voyage AI). Provided by the `code-search` MCP server. Returns ranked results by relevance, not string matching. | Full-text search (that's BM25, one component of hybrid search), grep (text pattern matching) |
| **Graph query** | Structural query over a code knowledge graph (SQLite + tree-sitter ASTs). Provided by the `code-graph` MCP server. Answers "what calls X?", "what breaks if I change Y?", "is this dead code?" | Code search (different tool -- graph is structure, search is meaning), grep (text matching) |
| **Hybrid search** | The combination of vector similarity (semantic) and BM25 keyword matching, fused via Reciprocal Rank Fusion. This is what `code-search` actually does -- neither pure semantic nor pure keyword. | Semantic search (technically hybrid is more accurate, but "semantic search" is acceptable shorthand) |
| **MRR** | Mean Reciprocal Rank -- the primary quality metric for code-search. How often the correct result is at position #1. MRR 0.828 means position #1 is correct 83% of the time. | Accuracy (too vague), precision (different metric) |
| **Golden test** | A hand-verified query-to-expected-file mapping used to evaluate search quality. 102 golden queries exist across 4 languages. | Unit test (golden tests measure quality, not correctness), benchmark (golden tests are the benchmark inputs) |
| **Indexing** | Converting source files into searchable representations -- either vector embeddings (code-search) or graph nodes/edges (code-graph). Both tools index independently. | Scanning (implies read-only), crawling (that's for web pages) |
| **API doc ingestion** | The pipeline of crawling API documentation (Firecrawl), converting to markdown, and indexing with code-search for semantic retrieval. Managed by the `/api-ingest` skill. | API integration (building against an API), API reference (the raw docs before ingestion) |

## Web Research Tools

| Term | Definition | Aliases to avoid |
|------|-----------|-----------------|
| **Exa** | Web search tool with dedicated indexes for GitHub, companies, people, research papers. Best for code search, category-filtered search, and semantic/neural matching. | Tavily (different strengths), web search (too generic) |
| **Tavily** | Web search tool with deep research, URL extraction, site crawling, and Reddit/HN thread coverage. Best for community discussions, URL content extraction, and multi-source research. | Exa (different strengths), web search (too generic) |
| **Firecrawl** | Web scraping tool for structured site crawling, page extraction, and browser automation. Best for the API doc ingestion pipeline -- converts doc sites to clean markdown. | Tavily (different -- Tavily searches, Firecrawl scrapes), web fetch (too simple) |
| **Context7** | Third-party library documentation lookup. Resolves library names to indexed doc sets and queries them. Used when writing code against library APIs. | Web search (Context7 searches curated doc indexes, not the open web) |

## Flagged Ambiguities

- **"memory"** is used to mean 4 different things: topic files (Tier 1), pattern files (Tier 2), knowledge base (Tier 3), and MEMORY.md (the index). Always qualify: "topic memory," "knowledge base entry," or "MEMORY.md pointer."
- **"hook"** is used for both blocking guards and modifying fixers. Specify "guard hook" or "fixer hook" when the distinction matters.
- **"agent"** means both the abstract concept (any spawned subprocess) and the specific `agents/worker.md` definition. Use "worker" for the generic task executor, "subagent" for the abstract concept, "Explore agent" or "Plan agent" for specialized types.
- **"rule"** is used for both `rules/*.md` files (ambient guidance) and enforcement hooks (mechanical constraints). Rules are guidance that can be forgotten; enforcement cannot. If something MUST happen every time, it's enforcement, not a rule.
- **"ship"** vs **"commit"** vs **"push"**: Users say "ship" to mean the full lifecycle. "commit" and "push" are individual git operations within the ship workflow. Never treat "commit" as a synonym for "ship."
- **"pattern"** appears in "pattern file" (Tier 2 persistence), "anti-pattern" (something to avoid), and "community pattern" (external practice to evaluate). Context usually disambiguates, but qualify when writing persistence documentation.

## Example Dialogue

> **Dev:** "I added a new guard that blocks `git push` to main."
> **Domain expert:** "Is it a PreToolUse hook or a skill step?"
> **Dev:** "PreToolUse — it fires on every Bash call matching `git push`."
> **Domain expert:** "Then it's a **guard hook**, not a **gate**. A gate would be an AskUserQuestion step inside the /ship skill. The guard fires mechanically; the gate requires the skill to be running."
> **Dev:** "Should I also add it as a rule?"
> **Domain expert:** "The guard IS the enforcement. A rule in `rules/git-hygiene.md` says 'don't push to main' — but that's guidance the model can forget. Your guard makes it impossible to forget. You have enforcement; you don't need a rule for the same thing unless you want to explain WHY the guard exists."
