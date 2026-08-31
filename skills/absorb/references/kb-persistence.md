# KB Persistence — Frontmatter Template, Field Rules, Finalize Rationale

Consult when persisting the Phase 3 profile to
`~/Documents/knowledge-base/topics/absorb-<username>.md` and finalizing the KB artifact.

## Frontmatter template

```yaml
---
title: "absorb: <username>"
description: "<1-2 sentence retrieval synopsis: who they are + the 2-3 named systems/patterns someone would search for. REQUIRED — written for a search index, distinct from the title.>"
stage: seedling
created: <today>
updated: <today>
tags: [absorb, developer-profile, <username>]
---
```

## Why `description:` is mandatory

> **`description:` is MANDATORY**, not optional polish. The KB `Docs CI` structure gate
> hard-requires `title`/`description`/`stage`/`updated` in frontmatter; a topic missing
> `description:` fails CI. The 2026-06-07 absorb batch (16 profiles) shipped without it
> and turned `main` red. Write it as a retrieval synopsis (searchable terms: names, system
> names, techniques), not a restatement of the title.

## Why stage = seedling

> **Stage = `seedling`, not `evergreen`.** An absorb profile is a single dated capture
> event, and `/garden`'s stage model counts *dated entries* (not structural `##`
> sections). A one-entry file is a seedling by that model regardless of how much
> structural content it carries. Defaulting to `evergreen` here caused `/garden` to
> demote the file on its next run, producing seedling↔evergreen flip-flop churn
> (observed across PRs #247/#434/#658). If a profile later accrues 3+ dated entries,
> `/garden` promotes it automatically.

## Finalize rationale — why a bare .md is incomplete

A topic `.md` alone is **not** a complete KB artifact. The knowledge-base `Docs CI` lint
job runs over the **whole `topics/` tree**, so an unfinalized profile fails CI *and blocks
every other KB PR* until fixed. Before opening the PR, bring the topic to the state CI
enforces — run `/garden` (which performs all three) or run the scripts directly.

The knowledge-base ships **one finalize entrypoint** that creates the manifest, rebuilds
the backlink index, regenerates the README, and then validates — so you don't enumerate
the individual scripts. Run it after writing the profile (the KB's committed
`.githooks/pre-commit` runs it on every commit too, so a missed call is caught — but run
it yourself so the PR is born green).

**Born-compliant, not retro-fixed.** Skipping finalize is the documented root cause of the
2026-06-07 batch: 16 profiles merged without `description:` / manifests / index, `main`
went red, and a later 3-file PR inherited four staged lint failures (structure → garden →
backlinks → README) before any of it could merge.
