# Inventories

Each inventory file in `~/Documents/knowledge-base/research/` has a
metadata file here declaring its source, framework count, and bucket
structure. The skill resolves `--inventory <name>` by looking up the
matching `<name>.meta.yaml`.

## Current inventories

| Slot | Status | File |
|---|---|---|
| canonical-2026-04-29 | active (default) | `canonical-2026-04-29.meta.yaml` |
| source-B-llm-generated | placeholder | (not yet generated) |
| source-C-public-aggregation | placeholder | (not yet generated) |

## Adding a new inventory

1. Generate or curate the inventory file. Save in
   `~/Documents/knowledge-base/research/<date>-<slug>.md`.
2. Create `<name>.meta.yaml` here with:

```yaml
name: <name>
source: <how was this generated; who curated; which model if LLM-generated>
date: YYYY-MM-DD
file: ~/Documents/knowledge-base/research/<your-file>.md
framework_count: <int>
bucket_structure: |
  <list of buckets and counts>
confidence_distribution:
  HIGH: <int>
  MEDIUM: <int>
  INFERRED: <int>
notes: |
  <context, biases, what's distinctive about this inventory>
```

3. Use it: `python3 dispatch.py discovery '...' --slug ... --inventory <name>`

## Why support multiple inventories

Per F6 red-team residual #1: the canonical inventory is curator-biased.
Independent inventories (LLM-generated, public-aggregation) are the
mitigation. Run the same problem on each; compare results. Convergent
results increase confidence in methodology robustness; divergent
results identify which findings are inventory-dependent.

The prompt for generating an independent LLM inventory is at:
`~/Documents/knowledge-base/research/2026-04-30-framework-dispatch-template-v2.md`
(or wherever the user keeps it).
