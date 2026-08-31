---
paths:
  - "**/rules/api-doc-lookup.md"
  - "**/rules/incidents/api-doc-lookup.md"
---

# api-doc-lookup: Incident Narratives

Extracted from `rules/api-doc-lookup.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-07-26-shipped-an-analytics-poller-sending-limit

```
WHY: 2026-07-26 — shipped an Analytics poller sending `limit=250` to
cost/usage. Every reconciliation request 400'd (`limit must be at most 31
for bucket_width="1d"`), so all 4 cost/usage endpoints wrote ZERO
partitions on the first production run while the engagement lane looked
healthy. Both the cap AND the non-obvious "it caps TIME BUCKETS, not
rows" clarification were ALREADY documented 3 days earlier (2026-07-23)
in topics/anthropic-platform-api.md:293 AND a separate skill (not included in this export):229.
`ls ~/Documents/api-docs/` has no anthropic entry, so step 1 finds
nothing and step 3 says "ingest the vendor docs" — neither points at
where the answer actually lived. Cost: a failed prod run + a live API
probe to re-derive a fact we owned.
```

## 2026-07-30-airlock-logging-exechistories-was-declared-a

```
WHY: 2026-07-30 Airlock — `/logging/exechistories` was declared a server-side
regression and written into a vendor support case. It requires a 24-char hex
ObjectId in `checkpoint`; omitting it returns an EMPTY SET BY DESIGN and `"0"` is
rejected as malformed. The zero ObjectId `000000000000000000000000` returns records
immediately. FOUR false verdicts came from that one parameter error, including
"OTP execution types [3,14] are wrong" (they are correct — the query was unparameterised)
and "self-service OTP is aggregate-auditable only" (full per-OTP attribution works,
records carry `otpid`). The contract was in THREE places already: the ingested
Postman collection, a sibling tool's docstring measured the same day, and
`agent-memory/topics/airlock.md` written by an EARLIER RETRO IN THE SAME SESSION.
This is an ADHERENCE gap, not a knowledge gap — `diagnose-before-fix` already
mandates memory_search-before-debugging, but its trigger reads as
"cloud infrastructure" and an API 400 was not recognised as in scope.
```

## 2026-07-30-no-list-otps-endpoint-exists-was

```
WHY: 2026-07-30 — "no list-OTPs endpoint exists" was concluded from a wrapper
search; `POST /v1/otp/usage?clientid&status` is in the vendor collection. Separately
`airlock_get_server_activities` WAS wrapped and a first semantic query missed it —
its docstring held the checkpoint contract that resolved everything above.
"Documented but not served" (it 404s here) is a far narrower claim than "absent".
```

## 2026-08-01-atlassian-admin-api-access-v1-orgs

```
WHY: 2026-08-01 Atlassian `/admin/api-access/v1/orgs/{orgId}/api-tokens` —
probed 8 shapes (`limit`, `maxResults`, `status=ALLOWED`, `q=`, `cursor=`,
`sortBy/sortOrder`, `sort=CREATED_AT_DESC`), got a byte-identical 500 on every
one, and concluded "the parameter shape is not the variable, this is a server
fault" — applying the rule directly above. Every name was invented. The spec's
real page-size parameter is `pageSize`, and `?pageSize=10` returned HTTP 200
with data on the first try. The spec URL was printed on the doc page I had
already scraped; dereferencing its `$ref`s also produced the true `sort` enum
(`-lastActiveAt`, not `CREATED_AT_DESC`) and lowercase `status` / `gt|lt` /
`day` values that four more guesses had missed.
```

## 2026-07-30-airlock-otp-usage-i-had-it

```
WHY: 2026-07-30 Airlock `/otp/usage` — I had it right first ("documented in
the Postman collection but not served"), then talked myself OUT of it when
the query-string shape turned up in that same collection, and shipped #897
converting body→query params. Deployed it; measured 404 for a JSON body, for
no params, AND for a populated query string — three encodings, one result.
Retracted in #899. Cost: a PR, a deploy, and a docstring that asserted a
false fix (worse than no docstring — an LLM caller reads it as ground truth
and will not re-test it). The working path existed all along:
`/logging/svractivities` filtered for OTP task types.
```

## Recovered 2026-08-08: the local-corpus inventory command and the unmigrated library

The 2026-08-06 condensing of `rules/api-doc-lookup.md` (163 -> 24 lines) routed its
narrative here and its host detail to `agent-memory/topics/api-ingest.md`. An audit while
reconciling the rule found ~26 lines that landed in NEITHER — mostly superseded host-status
snapshots, but two items were substantive and are restored below. Recorded so the
extraction is honest about what it dropped rather than implying a clean split.

**The inventory command, and why absence-plus-convention is strong evidence.**

```bash
grep -rhoE '/v1/[A-Za-z0-9/_-]+' ~/Documents/api-docs/<vendor>/ | sort -u
```

That is the authority on endpoint existence in the local corpus — and it also reveals the
family's NAMING CONVENTION, which is itself evidence. Airlock's `exception` family has
`list`/`approve`/`deny` and **no `/new`**, while six sibling families all have an explicit
`/new`. Absence *plus* a convention the siblings follow is a much stronger negative than a
wrapper search, which only proves the MCP layer lacks it.

**The unmigrated Windows-era library.** 25+ doc sets predate this host and were never
migrated: `microsoft-graph`, `slack`, `azure-automation-rest`/`-python`/`-runtime-env`,
`ashby`, `cornerstone-csod`, `exa-websets`, `fastmcp`, `firecrawl`, `netcloud`, `openai`,
`prowler`, `scubagear`, `tailscale`, `wireguard`, and more. Those genuinely need
`/api-ingest` on first use — a corpus miss for one of them is expected, not evidence the
vendor lacks the endpoint.

The discipline (docs before guessing) is host-independent; only the library
location/state is host-specific.

## 2026-08-06 ExampleService/CAF — a complete read of the wrong contract

A reconciler refused 51 of 51 grant-eligible enrollments for roughly two days
while reporting healthy. The read looked complete: 140 enrollments, no
pagination cap or parse errors, and exact disposition arithmetic. That evidence
was used to call it a vendor-data problem.

The object schema showed the opposite. ExampleService had removed
`CafEnrollment.usperStatus`; the tolerant reader mapped the absent property to
an empty string, erasing the distinction between a missing field and an empty
value. The same schema read exposed five newly added fields, which supplied the
other half of the likely rename. The load-bearing lesson is to inspect current
schema plus raw key presence before blaming data when one field is uniformly
empty across every record.

## 2026-08-29-jamf-redeploy-on-update-a-clean-experiment-with-a-wrong-oracle

```
WHY: 2026-08-29 Jamf — declared "redeploy_on_update is Jamf-UI-only, no amount of
API work will do it" and told the user to click through three profiles in the
console. The claim rested on a GOOD experiment: PUT the field -> HTTP 201 but
readback unchanged; PUT a known-writable <description> with the IDENTICAL body
shape -> persisted (so the mechanism works); PUT invalid enum values -> 409 (so
the server parses and validates the field). That triple is a textbook
discriminator and it ruled out every cause except "read-only field". The
tenant's own live /api/schema also showed redeploy_on_update 0 times across 550
paths. Everything measured was TRUE.

The verdict was still wrong, because the ORACLE was wrong. ruby-jss
lib/jamf/api/classic/base_classes/configuration_profile.rb:148 shows
`def update(redeploy_to_all:)` set the field, PUT, then
`# always reset to newly assigned`; the attribute is documented readonly and
"always contains REDEPLOY_NEWLY_ASSIGNED when fetched". So
201-plus-unchanged-readback IS the success signature. One Exa search found it,
after the user had to say "review Jamf source documentation so you aren't making
stuff up."

Re-run with the correct (device-side) oracle: the PUT redistributed profile 182
and a managed Mac's bearer moved Feb -> AWSCURRENT in ~90 seconds, ending a
5-day 80%-401 telemetry outage that had otherwise required console access.

COST: one wrong recommendation shipped to the user, plus a near-miss — the same
arc recommended DELETING profile 189, which uniquely carried the M365
managedMcpServers key, on the strength of a second instrument bug.

GENERALISE: the failure is NOT "I skipped the docs". It is that a rigorous
experiment FEELS like sufficient evidence, so the docs-lookup step never fires.
A discriminator can correctly prove your request shape works and still yield a
confident wrong verdict when the field you read back is not where success shows
up. The tripwire is one question — "what told me what success looks like here?"
If the answer is your own readback assumption, the experiment is ungrounded no
matter how clean its controls are. This is what the ambient FORBIDDEN clause
"an experiment whose success oracle came from your own assumption rather than
the vendor contract" refers to.
```
