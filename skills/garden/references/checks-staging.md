# Garden check family: Staging

Operative rules live in SKILL.md "Stage Audit" (and Step 1); this file holds
the measured history and edge-case rationale behind them.

## Why Step 1 branches from origin/main

Garden always ships from a feature branch, so local `main` is never needed.
Two measured failures of the former stash/rebase-main sync:

- 2026-08-15: the staging path was a SYMLINK to a clone on a plan branch, 88
  behind and 9 AHEAD of origin/main, with 26 dirty files and 24 stashes —
  `git rebase` on a branch that is AHEAD rewrites its history, and
  `git stash pop` replays another session's work onto a moved base.
- 2026-08-22: local `main` was held by another worktree, so `git checkout
  main` failed outright (exit 128); `git checkout -B garden/<date>
  origin/main` delivered identical content without touching it. The same run
  found untracked `plans/`/`research/` files that a blanket `git stash -u`
  would have needlessly stashed — hence the dirty-check scoped to `topics/`
  and `generated/`.

## Why overstaged is report-only (incident history)

Reference-style topics, hub pages left behind by a mega-topic split, and
deliberate curator choices all look "overstaged" to a band recount, so
demotion from a recount was never safe. The analyzer exempts two
perpetual-noise shapes:

- **Hubs** (`## Sub-topics` index): structurally exempt per KB CLAUDE.md —
  their content lives in sub-topics, so a hub carries 0 dated entries and only
  1-2 `## ` sections. Before this exemption, 9 of 14 overstaged rows were
  permanent unresolvable noise every run (measured 2026-07-24; the exemption
  took the list 14 → 5).
- **Zero-dated reference topics with ≥3 `## ` sections** (absorb profiles,
  landscape reports): they carry a curated stage despite no dated entries —
  26 such rows recurred every run before the exemption (2026-06-16, dominated
  by `absorb-*`). A near-empty mis-staged placeholder (<3 sections, not a hub)
  still surfaces.

## Why named non-promotion stages are skipped

Promoting a `retired` topic back to evergreen because its entry count crossed
a threshold would silently un-retire it. Measured 2026-05-22: three retired
topics — bifrost-ai-gateway, litellm-llm-gateway,
litellm-llm-gateway-next-steps — would have been incorrectly promoted without
this guard. A `retired` topic with 18 H2 entries stays retired.

## Why the curator pin exists

`stage_pinned: true` was added 2026-08-22 after measuring that 5 of 7
overstaged rows were the same curator-chosen placeholders in every report —
report-only findings that garden cannot demote and no curator intended to
change. The pin is the human's "confirmed intentional" statement; it exempts
the topic from the whole audit (promotion, overstaged row, and demotion).
Parser note: the analyzer strips an inline YAML comment from the value
(`stage_pinned: true  # garden: ...` must still read as true — the naive
frontmatter parser keeps everything after the colon; measured failing
2026-08-22 on the live corpus before the strip landed).

## Demotion boundary

Demotion fires only after the Merge Candidates check (which can shrink the
smaller file's entry count to zero before deletion) or after a manual user
edit that removed entries. The Cross-File Fact Duplication check no longer
rewrites in-place, so it cannot cause demotion. This keeps stage truthful to
current entry count rather than peak historical state, without letting a
recount demote.
