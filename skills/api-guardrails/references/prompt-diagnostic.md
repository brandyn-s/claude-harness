# Prompt Diagnostic Checklist

Adapted from [nidhinjs/prompt-master](https://github.com/nidhinjs/prompt-master) patterns.
Scoped to Claude API system prompts, MCP tool descriptions, and Agent SDK configurations.

Scan every system prompt, tool description, or agent config for these failures.
Fix silently when reviewing your own output. Flag to the user when reviewing theirs.

---

## Task Clarity

| # | Anti-pattern | Example | Fix |
|---|---|---|---|
| 1 | Vague role | "You are a helpful assistant" | "You are a compliance analyst. You review STIG findings against DoD SRG requirements and flag non-conformances." |
| 2 | Multiple responsibilities in one system prompt | "Classify the ticket, draft a response, and update the database" | Split into pipeline stages -- one prompt per task (see Consistency #4 in SKILL.md) |
| 3 | No success criteria | "Analyze this document" | "Done when every factual claim is tagged SUPPORTED or UNSUPPORTED with a source citation" |
| 4 | Over-permissive agent | Agent SDK with no tool restrictions | Explicit `allowed_tools` list + forbidden actions in system prompt |
| 5 | Emotional/subjective instructions | "Make it really good and thorough" | "Return exactly 3 findings per control, each with evidence quote and severity rating" |

## Context Grounding

| # | Anti-pattern | Example | Fix |
|---|---|---|---|
| 6 | No format specification | "Return the results" | Pydantic schema via `output_format=` or 2-3 few-shot examples of exact output shape |
| 7 | Missing negative constraints | Only says what to do | Add "Do NOT use training knowledge", "Do NOT infer missing fields", "Do NOT fabricate citations" |
| 8 | Assumed domain knowledge | "You know our compliance framework" | Provide the framework in context or retrieve via RAG. Claude has no memory of your org. |
| 9 | No knowledge boundary | "Answer questions about our product" | "Answer using ONLY the provided context. If not found, say 'Not in provided documents.'" |
| 10 | Hallucination invitation | "What do experts say about X?" | "Cite only sources present in the provided documents. If no relevant source exists, state that explicitly." |
| 11 | Undefined end user | "Write something for users" | "Audience: Navy SCA reviewers with DISA STIG experience. Use RMF terminology." |
| 12 | Contradicting prior context | New prompt ignores decisions from earlier pipeline stages | Pass forward a context block with all established facts and constraints from prior stages |

## Scope Control

| # | Anti-pattern | Example | Fix |
|---|---|---|---|
| 13 | Unbounded scope | "Review the codebase" | "Review only `src/auth/middleware.py` lines 40-120 for SQL injection vulnerabilities" |
| 14 | No stop condition (agents) | "Build the whole feature" | "Stop after creating the migration file. Do not run it. Output the file path and a summary of changes." |
| 15 | Full context dump | Entire repo or document in every call | Scope to the relevant section. Use RAG retrieval, not bulk paste. |
| 16 | Mixed concerns in one call | "Extract, analyze, and generate a report" | Chain: extract facts -> verify facts -> generate report from verified facts only |
| 17 | No tool boundaries | Agent can call any MCP tool | Restrict to `allowed_tools: ["read_file", "search"]` -- no write tools unless explicitly needed |

## Agent and Pipeline Specific

| # | Anti-pattern | Example | Fix |
|---|---|---|---|
| 18 | No error recovery | Agent encounters unexpected input and halts | "If the API returns an error, log the error and skip to the next item. Do not retry." |
| 19 | No iteration limit | Agent loops indefinitely on ambiguous input | "Maximum 3 attempts per item. After 3 failures, mark as UNRESOLVED and continue." |
| 20 | No state specification | Agent doesn't know what to persist | "Append each result to the `results` list. Do not modify previous entries." |
| 21 | Implicit handoff | Pipeline stage assumes the next stage knows context | Pass an explicit context object between stages with all decisions, not just the final output |
| 22 | No checkpoint output | Long agent run with no intermediate verification | "After every 10 items, output a progress summary: processed, succeeded, failed, skipped" |

## MCP Tool Descriptions

| # | Anti-pattern | Example | Fix |
|---|---|---|---|
| 23 | Vague description | "Gets information about a resource" | "Returns the resource's name, status, last-modified timestamp, and owner. Use to check resource state before updates." |
| 24 | Missing consequences | Write tool with no warning | "Permanently deletes the resource. Not reversible. Requires confirmation." |
| 25 | No return value context | "Returns the device" | "Returns JSON with fields: id, name, status, ip_address, last_seen. status is one of: online, offline, dormant." |
| 26 | Ambiguous tool selection | Two tools sound identical | Differentiate: "Use `get_device` for single device by ID. Use `search_devices` for filtered lists by name/status/tag." |
| 27 | Missing preconditions | Tool requires prior state | "Requires an active session from `connect()`. Fails with 401 if session expired." |
