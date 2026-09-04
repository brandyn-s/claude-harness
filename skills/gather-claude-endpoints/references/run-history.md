# gather-claude-endpoints — run history

Dated measurements and incidents behind the rules in SKILL.md. The rule lives in
SKILL.md; the evidence lives here. Runs are numbered from the establishing run
(run 1, 2026-07-27).

## Stale code and stale trees (Steps 0b, 1, 2)

- Run 5 diffed a KB tree **35 commits behind `origin/main`** — behind run 4's own
  output — and a `--update-baseline` commit from it would have reverted run 4
  (43 files, 824 deletions). The differ now refuses a stale tree.
- Run 6: the baseline-freshness gate (finding #27) checked the KB tree, but
  nothing checked the code being run. `~/.claude` was **143 commits behind**
  `origin/main`, so the run executed run-5-era scripts — the live reconcile leg
  died on a poll-budget bug finding #26 had already fixed upstream (PR #1960), and
  the differ ran without the freshness gate at all. Both scripts now run
  `code_freshness()` at startup (the offline `--observed` re-diff is exempt).
- 2026-08-24: a 208-commits-behind `~/.claude` reported phantom drift (+4 "otel
  events" that were exactly the four trace-span names run 6b had moved out) —
  finding #36, re-manufactured by a stale skill checkout.

## Phantom REMOVED rows on a reconciled baseline (run 3; fixed 2026-08-01)

Step 2c merges our telemetry into the same baseline files the docs differ reads,
so an observed-only value — which cannot appear in a docs extraction — reported
REMOVED forever: 25 phantom rows on run 3, the arithmetic exact (436 − 412 = the
24 merged activity types; 29 − 28 = `subagent_completed`). Fixed via per-value
`observed_values` + the `OBSERVED_ONLY` verdict.

## Extractor precision: declaration markers, not prose (2026-07-28)

A prose regex on the live compliance page yielded 33 "endpoints"; anchoring on the
vendor's `**verb** \`path\`` declaration markers gave 31 operations / 28 distinct
paths with **zero declared operations missed**. The old pattern never
under-captured; it OVER-captured by 5, all prefixes of real paths ("Download via
`GET .../apps/artifacts/{id}/content`" yielded a phantom `/apps/artifacts` fact).
Those 5 phantom rows cost a wrong "we don't call 11 of 33 endpoints" grading; four
were then probed as collection paths, 404'd, and reported as vendor phantoms when
the endpoints are real at their `{id}` form — a correction that had to be issued.

## Probe and observed legs (Step 2c)

- The first run of `reconcile_observed.py` reported *0/11 analytics endpoints
  unreachable* by reading a 400 "field required" as absence, when all 11 had been
  verified 200 the same day. `classify_probe()` now owns that mapping.
- Two guessed Keychain service names produced a false "no local key, BLOCKED"
  verdict (2026-07-28) while the key was present the whole time; the documented
  names are pinned by test.
- 2026-08-02, first real execution of the observed leg: an unbounded distinct
  event-name census of a flattened OTel export returned **12,431** values against a
  29-value baseline — log lines, not event names — where the same census bounded to
  15 days returned 198, none containing a space; `--update-baseline` would have
  written all 12,431 in. Unscoped to one product, the same export reported 169
  UNDOCUMENTED events, every one of them Claude Desktop's. Hence Step 2c's inventory
  rules: bound and scope the census at the producer, and drop-and-count anything
  that is not identifier-shaped.
- 2026-09-04: live-inventory collection moved out of the skill. Step 2c reads a
  `--observed` inventory file (the same contract as `gather-openai-endpoints`), so
  nothing in the skill queries a data store and the tests need no credentials.

## Why an observed inventory is the second authoritative source (measured 2026-07-28)

**24 activity types were live in our Compliance feed and absent from the 412-type
baseline** (incl. `claude_file_uploaded`, 46,860 events, a DLP signal), and
`claude_code.subagent_completed` was live in OTel (7,380 events) and absent from
the 28-event baseline **while already being consumed by a downstream usage report**
— a vendor rename would break a live consumer with no DRIFT ever firing. Neither
is findable by re-reading docs.

No machine-readable spec exists to fall back on: all four OpenAPI candidates 404
(`api.anthropic.com/v1/openapi.json`, `platform.claude.com/{,docs/,api/}openapi.json`),
and the official `anthropic-sdk-python` `api.md` declares 80 paths — **zero** of
them Admin, Analytics, or Compliance.

## Three false zeros (run 3) — each would have shipped a wrong HIGH finding

(a) A hand-rolled resolver reported 17 uncovered pages vs `enumerate_uncovered_pages()`'s
0 (`.md` keys vs bare names), and the guard is what found the real one-page delta.
(b) A Watching trigger names a SPECIFIC page: probing
`usage_report/retrieve_claude_code.md` instead of
`manage-claude/claude-code-analytics-api.md` returned 0 hits for an exclusion that
is intact verbatim. (c) `docs/llms.txt` returns **9 bytes** without redirects
(reads as "no such pages exist") and 56,941 with `curl -L`.

## Narrow greps manufacture false gaps (2026-07-28, four times in one session)

| What was grepped | Where it actually was |
|---|---|
| `compliance_poller.py` for `/settings` | `anthropic_audit_v2/compliance.py:248` |
| `lambda/*.py` for `organizations/analytics` | `anthropic_audit_v2/analytics.py:44` |

- Five Analytics endpoints called "never probed by us" were live at
  `anthropic_audit_v2/analytics.py:44`; a Compliance key inventory called
  "uncollected" was not only ingested but graded by an always-on credential guard
  emitting a CloudWatch alarm metric — stronger than the change proposed.
- A new actor type was graded HIGH for "breaking a SIEM rule keyed on 6 types".
  No closed actor enum existed anywhere — `actor` is a string column read with
  `json_extract_scalar`. Correct severity was LOW.
- The first run shipped two findings whose impact halves were inferred (one HIGH
  that should have been LOW, one that should have been REJECT); `API probe`,
  `Code probe`, and `Severity basis` became required fields.

## A DEFER trigger that watched the wrong system (2026-08-08)

Finding #4 asserted "OTel traces are a live signal we have **never enabled**" and
armed the trigger *"(beta) removed from the Traces heading"* — a vendor-doc watch.
Traces were in fact live the entire time, at **1,444,269 spans** with
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` deployed fleet-wide by MDM. The trigger was
well-formed, machine-checkable, and structurally incapable of firing on the half
that was false. It survived two further runs. Same session: DEFER #3 had already
been closed by another team, and its closure was already recorded in this KB's own
`channels/endpoint-registry.md` while `INTELLIGENCE.md` still said DEFER. 2 of 4
carried-forward DEFERs were stale on the run that first checked.
`service_account_actor`: 0 rows of 2,349,182 ⇒ `DOC_ONLY`, not a gap.

## Sources Log rows (run 5)

The differ's `--update-sources-log` found 8 registered channels with no Sources
Log row, silently missing.

## Extractor authoring (audited 2026-08-22)

The verb-suffix whitelist (80 phantoms + missed real types), the webhook prefix
family, the metric family list, the scope verbs (`org:admin` missed), and the
`1[mhd]` bucket literal were all the same defect: a closed alternation guarding an
open vocabulary. The engine moved to `skills/_shared/endpoint-drift/diff_engine.py`
the same day; `gather-openai-endpoints` is its second consumer.
