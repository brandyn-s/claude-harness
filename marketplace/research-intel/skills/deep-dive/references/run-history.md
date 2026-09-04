# deep-dive — run history

Dated incidents behind the rules in SKILL.md. The rule lives in SKILL.md; the
evidence lives here.

## Fan-out width vs synthesis depth (2026-07-30)

A fork read "Cost and speed are not constraints" as licence for "a full
multi-wave campaign… all three providers in parallel", stalled with zero results,
and was killed by the 600 s watchdog. A bounded main-thread pass — 2 searches,
3 targeted fetches against `cyber.gov.au` and the vendor's own docs — then
produced better-sourced findings than the agent had, faster.

## Step 3b — why the freshness gate exists (2026-05-03 roundtable)

"No early exit" + "Cost and speed are not constraints" created sunk-cost friction
on narrow questions where the user already had fresh local knowledge. The same
roundtable identified per-finding counterfactuals as the structurally weakest
layer of the three-layer defense; the Step 12 PER-FINDING COUNTERFACTUAL check
closes that gap.

## Step 11b — jury skipped under a no-Agent directive (2026-08-17)

Step 11b was skipped citing a no-Agent directive and disclosed only in the report
header. When the user later asked for it, the jury changed two of three findings —
one downgraded to Low as ungroundable, one restated after a unanimous verdict that
its comparative claim was unsourced. The same-model N≥3 fallback was available the
whole time and went unused, and the report shipped an unadjudicated overclaim in
the interim.

## Step 12 — comparative claim invented in a finding title (2026-08-17)

A finding asserted "false-alarm rate — **not** detection range — is the limiting
factor"; three jurors independently returned INSUFFICIENT with the identical
objection that no supplied source compared the two. The qualitative half was
well-sourced across three non-vendor sources spanning 2019–2025; only the ranking
was invented, and it was in the finding's title.

## Graceful degradation — retry a hard error once (2026-08-17)

`web_search_exa error: fetch failed` was recorded as a permanent gap and
"recovered via Firecrawl"; the identical query retried later succeeded and
surfaced four facts Firecrawl had missed — a 41% vendor price contradiction, a
conflicting compliance claim, a government competition award, and an entire new
finding that changed a recommendation. The fallback provider is not equivalent
coverage.

## Graceful degradation — `memory_search` hang (2026-08-17)

`memory_search` hung 1800 s on a degraded VPN link; the row's former "skip and
note it" guidance turned a 5-second grep fallback into a published gap in the
report, which the user flagged. Grep found 0 hits across 179 memory files and
2 adjacent reports — a complete answer the semantic tool never delivered.

## Zero providers in a forked run (2026-08-26)

All three providers errored in a forked run. The fork continued anyway, produced
a 47 KB report whose only inputs were the invoking turn's own ground truth,
labelled it with an honest provider-status line — and introduced a fabricated
figure, "outlook … 99 tools", against a real filter list of 30. The main thread
then re-ran the identical wave successfully in 11 searches, because from the main
thread those same three providers work. Cost: one wasted fork run plus the full
re-run. The honest provider-status header is what made it survive review: it
looked like disclosed degradation rather than a null result.
