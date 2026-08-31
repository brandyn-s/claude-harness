# API Ingest — Output Templates (Phase 3b)

After `reference.md` and `constraints.md` exist, emit two AI-native formats alongside them for external / cross-tool consumption.

## llms-full.txt

Concatenation of the two files with a header. Single-file consumption format (agentskills.io / llmstxt.org convention) so the API can be fed to any LLM system without parsing a directory.

```
# {API Name} — Full Documentation

Source: {source URL or spec path}
Generated: {YYYY-MM-DD}

## API Reference

{contents of reference.md}

## Constraints, Auth, Rate Limits

{contents of constraints.md}
```

Write to `~/Documents/api-docs/{api-name}/llms-full.txt`. **Skip** if the combined size would exceed 10 MB (single-file consumption stops being useful above that).

## skill.md

Condensed action-oriented summary for agent frameworks. **Emit only when operation count ≤ 50** — larger APIs belong in semantic search, not a single digest file.

```
---
name: {api-name}
description: {API Name} API — {one-line purpose from info.description or info.title}
---

# {API Name}

## Authentication
{method: bearer | api-key | oauth2 | mTLS}. Env var: `{SERVICE}_API_TOKEN` (or equivalent).

## Base URL
{base_url}

## Operations

### {Resource Area}
- `{METHOD} {path}` — {one-line summary}

## Common Gotchas
- {gotcha 1}
- {gotcha 2}

## See also
- Full reference: `~/Documents/api-docs/{api-name}/reference.md`
- Constraints: `~/Documents/api-docs/{api-name}/constraints.md`
```

Write to `~/Documents/api-docs/{api-name}/skill.md`. Skip (with note) when operation count > 50.
