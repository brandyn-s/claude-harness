# Garden check family: Wiki-links

Operative rules live in SKILL.md (Broken Wiki-Links, Orphan Topics, MoC
Coverage Gaps, Bare Wiki-Links, Generated Link Graph); this file holds the
measured history and rationale behind them.

## Anchor-stripping (why it is load-bearing)

`[[slug#section]]` points to a section within `{slug}.md`; the link is broken
ONLY if `{slug}.md` doesn't exist. Measured 2026-05-22: 6 of 10 initial
"broken" hits were anchor links to valid files or same-page sections; only 4
were actually broken. The same rule protects the orphan check — a topic
referenced ONLY via anchor links would otherwise read as orphaned — and MoC
coverage (`[[foo#section]]` in a MoC counts as coverage for `foo`).

## Why the no-fit floor exists

The 2026-05-12 user feedback established that "human review" buckets
accumulate noise. `_moc-uncategorized.md` makes the holding pen explicit and
bounded rather than hidden under `## Recently Added` sections that pollute
curated MoCs. The ladder never forces a placement into an unrelated topical
MoC: no topical MoC receives an entry with zero tag overlap and <2 shared
title words.

## Generated link graph (drift history)

`tools/kb.py` recomputes the graph from the markdown source of truth on every
build (wiki-links + `(topics/<slug>.md)` links, with inline code and fenced
blocks excluded). Before the 2026-06-06 fix, a stale reverse index produced
~27 false orphans; the rebuild made that class structurally impossible —
edges are forward-only (`links_to`) and reverse links are derived at query
time. `check` is the CI gate and compares every artifact byte for byte.

Ordering is load-bearing: run the rebuild AFTER the orphan-adoption check —
orphan adoption adds the inbound MoC links that the rebuild then records.
