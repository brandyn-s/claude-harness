# Garden check family: Chunks and content shape

Operative rules live in SKILL.md (Soft-Chunk Sections, Non-Canonical Dated
Headers, Stale `updated:`, Current-Understanding Coverage, Step 3b Size
Sweep); this file holds the measured history and rationale behind them.

## Soft-chunk disposition accounting (why it is mandatory)

The 2026-06-08 run split 5 of ~25 analyzer-reported soft chunks and silently
dropped the rest — no disposition, no report trace — which is how 24 soft
violations survived to the 2026-06-10 audit. Split + left-indivisible must
equal the analyzer count, or the run is not done.

Always use the leaf-chunk counts from `analyze.py`: it shares the CI gate's
exact algorithm (including the +3/+4 header-marker chars and the whole-content
split), so computing chunk size any other way produces phantom violations —
the disagreement class that also produced the absorb stage flip-flop.

## Non-canonical dated headers (history)

Date-FIRST entry headers (`## 2026-06-07: Title`) are invisible to the shared
dated-entry regex, corrupting both the stage count and the suspect-MoC
classification. 67 were normalized corpus-wide on 2026-06-10. The former
lifecycle producer emits canonical headers now, so a non-zero count means an
authored or generated content source regressed — note the producing file
pattern in the report.

## Size sweep rationale (Step 3b)

**SPLIT, NEVER TRIM** — verified against each cap's own source 2026-07-29;
two say it outright (`topic-authoring.md:36` "do not trim load-bearing
evidence"; Anthropic "no context penalty until accessed"). Content behind a
pointer costs zero until read, so splitting preserves evidence AND removes
cost.

`agent-memory` was auto-split on paper until the first live run refuted it —
a one-level split of a 119 KB / 56-section topic left 5 of 6 siblings still
over cap, and two files have a single `##` section already over 8 KB
(measured bound: 8-15 siblings needed). Multi-way splits are a dedicated
session, like a KB hub-split. `split_plan.py` packs whole `##` units into as
many bins as required — descending to `###` for any section over cap on its
own — and names what a human must decide: the subdomain taxonomy (a sibling's
name must predict its contents, which a size-packer cannot do).

Delivery-path triage, measured 2026-07-29: reading the loader's route map and
stamping each row `INJECTED` / `read-only` / `DELIVERY UNKNOWN` narrowed 21
over-cap agent-memory topics to 4 real defects — and the corpus's largest
file (119 KB, 1248% of cap) was not one of them. A hook-injected topic is
capped at 10,000 chars (85-98% goes missing); one reached by `Read` is merely
a token cost.
