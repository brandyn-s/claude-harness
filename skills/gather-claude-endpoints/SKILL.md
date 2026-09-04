---
name: gather-claude-endpoints
description: "Detect drift in Anthropic's data-collection surface — OTel signals, Compliance API, Admin API, Analytics APIs, webhooks, rate limits, and documented exclusions — by diffing live docs against committed baselines, then PROBING each finding against the live API and our own code before grading it."
when_to_use: Use when checking whether Anthropic changed what telemetry, audit, usage, cost, or content data can be collected from claude.ai or platform.claude.com — new or removed endpoints, new OTel events or metrics, new Compliance activity types or actor types, changed rate limits, changed freshness or revision windows, or changed per-feed exclusions. Also use to probe, verify, or validate a claim about an Anthropic data endpoint (does it exist, what does it return, what does it clamp, do we already collect it), and to answer "what channels exist and what does each return" from the dedicated knowledge base. Trigger phrases - "gather-claude-endpoints", "did the Claude APIs change", "new Anthropic endpoints", "Compliance API changes", "OTel event changes", "Claude rate limit changes", "what can we collect from Claude", "Claude data channel drift", "Anthropic telemetry changes", "probe the Claude endpoints", "verify the Anthropic API findings", "validate what we collect". Do NOT use for Claude Code product features or CLI changes (use gather-claude), third-party LLM vendors (use gather-vendor), answering a spend or usage question from data we already hold (use cc-monitor), or community patterns (use gather-intel).
argument-hint: "[optional: 'full', a channel key, 'baseline' to refresh baselines, or 'probe' to re-validate existing findings]"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.1"
compatibility:
  requires:
    - cli: python3
allowed-tools: Bash Read Write Edit Glob Grep mcp__memory-search__memory_search AskUserQuestion
---

## gather-claude-endpoints

# Detect drift in Anthropic's data-collection surface

Narrow sibling of `/gather-claude`. That skill tracks the **Claude Code product**
(features, CLI, deprecations). This one tracks **only the data-collection
surface**: what telemetry, audit, usage, cost, and content data Anthropic exposes,
through which endpoint, under which key, with which limits and exclusions.

The dedicated knowledge base is
`~/Documents/knowledge-base/reference/claude-data-channels/`.

**Why a scripted differ rather than re-reading the docs each run:** additions are
salient in prose but **removals are invisible** — nothing in a new doc page
announces the event type that vanished. Only a set-difference against a committed
baseline catches both directions. And a raw-page diff drowns in prose rewording,
so the compared thing has to be a normalized fact-set.

Runs in the main thread. **Never auto-writes** anything except the baseline files
(see Step 6).

---

## Step 0: Scope guard + argument

Route away if the request is really about something else:

| Request is about | Use instead |
|---|---|
| Claude Code product features, CLI, model releases | `/gather-claude` |
| OpenAI / Gemini / Grok | `/gather-vendor` |
| Community patterns | `/gather-intel` |
| Academic research | `/gather-research` |

Argument: none = all channels · a channel key = just that one (`--list` to see
keys) · `baseline` = establish/refresh baselines after review.

---

## Step 0b: The scripts gate their OWN code freshness (enforced in code)

The baseline-freshness gate checks the **KB tree**; `code_freshness()` checks
the **code being run** — a stale checkout has executed old scripts against a
fixed-upstream problem before ([references/run-history.md](references/run-history.md)).

Both `diff_channels.py` and `reconcile_observed.py` run
`code_freshness()` at startup: **STALE refuses (exit 2)** and prints the fix;
UNKNOWN (non-git copy, failed fetch) warns and proceeds — unlike the baseline
gate, code legitimately runs from non-git copies, and the baseline gate is the
one protecting writes. When refused, run from a detached worktree of
`origin/main` (`git -C ~/.claude worktree add --detach /tmp/claude/ccwt
origin/main`) — never mutate the stale live checkout mid-run.
`--allow-stale-code` exists for deliberate archaeology only.

## Step 1: Load baseline (MANDATORY)

**Step 0.5 — run from a CURRENT checkout, never `~/Documents/knowledge-base`:**

```bash
git -C ~/Documents/GitHub/claude-knowledge-base worktree add \
  ~/worktrees/kb-gce-<date> -b docs/gather-claude-endpoints-<date> origin/main
```

The differ refuses a stale tree, but cannot fix your checkout — a stale tree has
produced a baseline commit that would have reverted the prior run's output
([references/run-history.md](references/run-history.md)).

Read in parallel; note any absent file in the Sources Log and continue:

1. `~/Documents/knowledge-base/reference/claude-data-channels/INTELLIGENCE.md` —
   its Metadata block sets the window; its **Watching** table sets this run's
   must-check triggers; any unresolved qualification state must be re-run and
   resolved in the same run without applying a live edit.
2. `CATALOG.md` + the `channels/*.md` pages relevant to the argument.
3. `memory_search` for our own probe results — the KB's `[OUR PROBE]` rows come
   from `topics/claude-telemetry-coverage.md`, `anthropic-platform-api.md`,
   `anthropic-billing-reconciliation.md`, `compliance-api-ingestion.md`. Vendor
   docs describe the surface; those topics describe **what we measured**, and the
   two disagree often enough to matter.

**Do not skip 3.** A vendor doc saying a feed returns per-user cost does not mean
it returns it *for us* — the documented exclusions decide that.

---

## Step 2: Run the differ (MANDATORY)

```bash
python3 ~/.claude/skills/gather-claude-endpoints/scripts/diff_channels.py \
  --kb ~/Documents/knowledge-base \
  --run-date <YYYY-MM-DD> \
  --json /tmp/claude/channel-drift-<date>.json
```

Add `--channel <key>` to scope, `--list` to enumerate channels and extractors.

When `--json` is given, every fetched page is also persisted to
`<json-path>-pages/<channel>.md` (override with `--pages-dir`, disable with
`--pages-dir ''`). **Step 4 verification reads THOSE files** instead of
re-downloading multi-MB pages the differ just fetched.

**Exit codes:** `0` no drift · `1` drift found OR a prose Watching trigger
fired · `2` instrument/channel problem.

**Self-vintage gate:** a stale skill checkout reports phantom drift
([references/run-history.md](references/run-history.md)). When `code_freshness()`
(Step 0b) refuses, run the differ from an origin/main worktree of claude-config
and pass an origin/main worktree of the KB via `--kb`.

**`[BASELINE_STALE]` / `[BASELINE_UNKNOWN]`** = the `--kb` tree is not proven current with
`origin/main`; the run stops (exit 2). Fix the checkout. `--allow-stale-baselines` is for
`--offline` fixture work and is **refused** alongside `--update-baseline`. `UNKNOWN` (no
git tree, failed fetch) is not fresh — a check whose instrument failed proves nothing.

### Read the verdicts correctly — they are not interchangeable

| Verdict | Meaning | Action |
|---|---|---|
| `CLEAN` | fact-set identical to baseline | nothing |
| `DRIFT` | real additions/removals | → Step 3, becomes a finding |
| `TRIGGER_FIRED` | a prose Watching trigger deviated (a load-bearing sentence vanished, or a forbidden token appeared — e.g. a `/v1/` path on an inference-hooks page) | → Step 3, a real vendor state change. The trigger's `note` says why it matters. These encode the Watching-table rows that used to be hand-checked each run (two hand-grep false zeros in run 6 alone). |
| `OBSERVED_ONLY` | the baseline holds values from OUR telemetry that the docs never listed; they are held out of the docs diff | **informational, not a problem.** Only `reconcile_observed.py`'s Athena leg can verify them |
| `NO_BASELINE` | first sight of this extractor | → Step 6, establish it **this run** |
| `INSTRUMENT_BLIND` | extraction fell below `min_expected` | **DETECTOR BUG** → Step 2b. Never report as "the vendor removed everything." |
| `CHANNEL_DEAD` | fetch returned but the liveness marker is absent | page moved/rewritten → re-derive the URL before trusting any diff |
| `FETCH_FAILED` | transient/network | retry; if it persists, log the gap per-channel |

`INSTRUMENT_BLIND` and `CHANNEL_DEAD` **invalidate that channel's diff for this
run**. Fix the instrument before grading anything from it. A 0-hit result on a
plausible phenomenon is a detection bug until proven otherwise.

### A `REMOVED` row on a RECONCILED baseline: check provenance before grading it

This tool reads ONE source (the docs). Step 2c merges a SECOND (our telemetry) into
the same baseline files; per-value `observed_values` and the `OBSERVED_ONLY` verdict
keep those values out of the docs diff (before that, every observed-only value
reported REMOVED forever — [references/run-history.md](references/run-history.md)).
A held-out value is **unchecked by this tool by design**, and both current ones back
*closed-set* detector predicates, so only the Athena leg can catch a rename of them.
Never "fix" a phantom removal by deleting the value — that re-opens the blindness
Step 2c exists to close. Mechanics, and what to do when a baseline has
`observed_source` but no `observed_values`: `references/adding-a-channel.md`.

### Step 2b: Fix a blind extractor in the same run

1. Fetch the page and confirm what the facts actually look like now — most often
   the tokens moved between backticked inline code and bare text, or moved to a
   **different page** entirely.
2. Patch `scripts/channel_specs.py`. If facts moved to another page, add a new
   `ChannelSpec` pointed at that page rather than stretching one spec across two
   (a spec spanning pages reports permanent `INSTRUMENT_BLIND` for the absent half).
3. Re-run `tests/test_diff_channels.py` — the fixture tests must still pass.
4. Record the fix in the Sources Log's *Instrument fixes* table (conventions §8:
   codify improvisations in the same run, or they are re-derived next run).

**Extract from the DECLARATION marker, never from surrounding prose.** A pattern
loose enough to match a path mentioned in a sentence captures path **PREFIXES** as
if they were endpoints. Anchor on the vendor's own declaration form —
`**<verb>** \`<path>\`` (measured precision:
[references/run-history.md](references/run-history.md)). Two follow-ons:

- **Capture the VERB with the path** (`kind="pair"`), because one path can carry
  both `GET` and `DELETE`. A `map`-shaped fact keyed on path alone silently
  dedupes them and undercounts the surface.
- **A prefix is NOT probeable as a collection.** A 404 on a path you synthesized
  is evidence about **your extractor**, not about the vendor. Before grading any
  path `404`/absent, confirm the path came from a declaration marker and not from
  your own regex's truncation of a longer one.

---

## Step 2c: Reconcile against LIVE data (MANDATORY when AWS is reachable)

Step 2 asks the vendor. This step asks **our own pipeline** — the only source that
can reveal a surface the docs omit (see *What "authoritative" means here*).

```bash
# Full: observed inventory + canned Watching checks + reachability probes.
# --watch is the standard form: it runs the Desktop-vocabulary, credential-pair,
# and retention-sweep lake checks that were hand-run (and hand-broken) before.
python3 scripts/reconcile_observed.py --kb <kb-dir> --probe --watch \
  --save-observed /tmp/claude/observed-<date>.json

# No AWS credentials? Probes only (Keychain keys, no Athena):
python3 scripts/reconcile_observed.py --kb <kb-dir> --probe-only

# Offline re-diff of a previously saved inventory. `--observed` READS the file
# `--save-observed` wrote (it is an INPUT — a nonexistent path is a clear
# error, not a crash, since 2026-08-22):
python3 scripts/reconcile_observed.py --kb <kb-dir> --observed observed.json

# The scan grew past the poll budget? Raise it -- do NOT read a timeout as "no data":
python3 scripts/reconcile_observed.py --kb <kb-dir> --probe --timeout 1800
```

All Athena queries in a run go as **one concurrent batch** (start all, poll
all): wall-clock is ~max of the scans, not their sum. The `--timeout` budget is
shared by the whole batch.

**`--watch` verdicts:** a MISSING baselined Desktop type (a rename — the only
detectable signature) alarms; a credential-pair threshold crossing
(≥100 events or ≥20 principals) alarms; an UNKNOWN retention-sweep
`skip_reason` (especially `settings_invalid_key_set`, the #41458 signature)
alarms. The fleet-norm `period_days=30/used_default=true` deliberately does
NOT (finding #23's correction). New unbaselined Desktop types are REPORTED
for reading, never auto-alarmed — check appearances by reading names
(finding #22). Lake naming/columns: `references/athena-lake-contract.md`.

**A timeout is not "no data" — recover it.** Budget is `DEFAULT_ATHENA_TIMEOUT_S`
(900 s; the largest scan runs ~460 s). On timeout the query is usually **still
RUNNING**: the error prints its id and poll command. Never let a timeout stand as a
live-leg result — it is the only leg that sees what the docs omit.

**Read these verdicts correctly — they are not symmetric:**

| Verdict | Meaning | Action |
|---|---|---|
| `UNDOCUMENTED` | live in our data, absent from the baseline | **the detector is blind to it.** Add to the baseline; consider whether it warrants a detector. |
| `DOC_ONLY` | documented, never observed in our org | **informational, NOT a gap.** A type the product supports but we never generate is not leverage left on the table — counting it as a gap inflates every coverage denominator. |
| `RECONCILED` | observed ⊆ baseline | nothing to do. |

Two hard rules on the probe leg:

1. **GET only — a DELETE is never probed.** The operations fact-set enumerates 5
   destructive compliance endpoints (DELETE on chats, projects, project documents,
   chat files, code artifacts). "Probe every endpoint to see if it's live" would
   issue those against production compliance data. A DELETE's existence is verified
   from the doc *declaration*; `probe_endpoint()` raises `UnsafeProbe` on any
   non-GET method, and no compliance channel is in the probe set at all.
2. **A 400 "field required" is REACHABLE, not a gap.** The request was incomplete,
   not the endpoint absent — an absent endpoint 404s, a wrong key class 401s, a
   missing scope 403s. `classify_probe()` owns that mapping; a missing Keychain key
   reports `SKIPPED_NO_KEY` (an instrument gap) and never as unreachable.

If `--update-baseline` is passed, `UNDOCUMENTED` values are merged into their
baselines and the file records `observed_source` — provenance matters, because a
value learned from our telemetry is not a vendor claim.

---

## Step 3: Grade each drift item

Severity by blast radius on **our** collection, not by the vendor's framing:

| Severity | Shape |
|---|---|
| **HIGH** | a **removal** that silently breaks something we run (event a detector keys on, endpoint our poller calls, scope our key holds); a rate-limit **reduction**; an exclusion **added** to a feed we publish from |
| **MEDIUM** | a new collectable surface we'd plausibly want; a freshness/revision-window change; a new actor/key/scope class |
| **LOW** | additions in a channel we don't consume; cosmetic/doc-only changes; known extractor noise |

**Removals outrank additions.** An addition is an opportunity; a removal is an
outage we haven't noticed yet.

Then check the **Watching** table from Step 1 explicitly — those triggers are
promises made by prior runs, and an unchecked one is a silent regression in the
skill itself.

---

## Step 4: Verify before presenting (MANDATORY)

For every finding:

1. **Read the cited page** and confirm the claim in the vendor's own words —
   from the differ's persisted copy (`<json-path>-pages/<channel>.md`), not a
   re-download: the bytes verified must be the bytes diffed. The diff proves a
   token set changed; it does not prove what that *means*.
2. **A count change is not a semantic change.** A doc reorganization can add a
   token with no new capability behind it. Confirm the capability, not the string.
3. **Prefer the API reference over the prose guide** where they disagree — finding
   #1 in this KB exists because the reference carried 3 actor types the guide
   omitted. When they differ, record both and say which you trust.
4. Currency calibration per `rules/symmetric-evidentiary-burden.md`: a bounded search
   finding nothing is a property of the search. `UNCHARTED` is a valid verdict;
   fabricated refutation is not.

**Adversarial check before recommending we *stop* collecting something** (the
removal case): search for the successor surface before concluding a capability is
gone. Vendors relocate more often than they delete.

Step 4 verifies the **vendor's** claim. It does NOT verify the **impact** claim —
that is Step 4b, and skipping it is how this skill shipped two wrong findings on
its first run.

---

## Step 4b: PROBE — validate the claim against the live API and our own code (MANDATORY)

Every finding has two halves. Step 4 checks the first; **this step checks the
second, and it is the one that fails.**

| Half of a finding | Verified by | Answers |
|---|---|---|
| "the vendor documents X" | Step 4 (read the page) | is the doc claim real? |
| **"which matters because it affects us"** | **Step 4b (probe)** | is the impact real? |

A finding whose "why it matters" is **inferred** rather than probed is a
HYPOTHESIS. Label it one, or probe it.

### 4b.1 — Probe the vendor's live API (behavioral truth)

Documented != actual. Probe the endpoint the finding is about, read-only, minimum
page size. Assert on **counts and shapes**, never on response byte size.

```bash
# shape probe: does it exist, what does it return, what does an error say?
curl -sS -w '\nHTTP %{http_code}\n' -H "x-api-key: $KEY" \
  "https://api.anthropic.com/v1/organizations/analytics/skills?limit=1"
```

What only a probe can tell you, all of which have bitten:
- **Silent clamps.** A `limit` the API accepts and quietly reduces turns a census
  into a sample with HTTP 200 and no warning. **Count returned records** — byte
  size is a proxy and lies (two responses of identical length can hold 100 vs
  1000 records).
- **Endpoints that disagree with each other.** The same parameter can 400 on one
  path and silently clamp on a sibling path in the same API.
- **Which error class you actually get.** A 403 can mean wrong key CLASS, wrong
  scope, or a malformed path — not necessarily "no access". Read the response
  **body**, not just the status code; it carries the actionable cause.
- **Absent rate-limit headers.** If the response carries no
  `X-RateLimit-*`/`Retry-After`, backoff must be blind and quota is unobservable
  from the response. That is a finding in itself.

**n=1 is not a contract.** A single 429 or a single anomaly is an observation.
Repeat it (paced and unpaced) before writing it down as behavior —
`verify-effectiveness.md`.

**If a probe is blocked** (no key of the right class, credential in a store you
must not read, quota risk): **STOP and surface the blocker to the user.** Do NOT
self-authorize a credential read, and do NOT silently downgrade to
doc-inference. State what you would probe and what you need. Tag the finding
`UNVERIFIED-BLOCKED` with the reason.

### 4b.2 — Probe OUR codebase before claiming a gap or an impact (MANDATORY)

**A claim about OUR system requires reading OUR system.** Every "we don't collect
this" / "this would break us" must cite a grep or a file:line — never vendor docs
alone.

#### The grep must be WIDE, or it manufactures false gaps

Every wrong "we don't collect X" claim on record came from a grep that was too
narrow, not from a missing grep — the implementation was in a module the searcher
didn't have in mind ([references/run-history.md](references/run-history.md)).

**Three rules:**

1. **Grep the FIELD NAME, not the endpoint path.** A path can be assembled
   (`f"{BASE}/organizations/{uuid}/settings"`) and never appear as a literal, while
   the response field you care about (`api_keys`) always does.
2. **Never scope to one module.** `~/Documents/GitHub` with `--include`, not the
   file you expect. Sibling bundles (`*_bundle/`) are the usual hiding place.
3. **Grep the CAPABILITY too, not just the data.** Before recommending "ingest and
   alert on X", search for the alerting verb (`_emit`, `put_metric_data`, `alarm`,
   `guard`). Twice the runtime was *stronger* than the change I was about to
   propose.

```bash
# 1. FIELD NAME across every repo -- the most reliable probe
grep -rn "api_keys" ~/Documents/GitHub --include="*.py" --include="*.tf"
# 2. endpoint path as a SECONDARY check (may be assembled, not literal)
grep -rn "organizations/analytics" ~/Documents/GitHub --include="*.py"
# 3. is there already a GUARD/alarm on it? (do not propose what exists)
grep -rn "put_metric_data\|_emit_\|guard_handler" ~/Documents/GitHub --include="*.py"
# 4. would a new enum value break anything? look for a CLOSED set
grep -rnE "\[[^]]*<known_value>[^]]*\]" ~/Documents/GitHub --include="*.py"
# 5. typed column (breaks) or schema-on-read (absorbs)?
grep -rn -A2 'name = "<field>"' ~/Documents/GitHub/mcp-infra
```

**A single-module grep returning nothing is NOT evidence of absence** — it is
evidence about the module you searched (`verify-before-assuming.md`: absence in a
bounded search is a property of the search).

Three questions, each with a recorded failure
([references/run-history.md](references/run-history.md)):

1. **"We never collect this" — do we already?** Per the three rules above: field
   name, every repo, and check for an existing guard.
2. **"This would break X" — would it?** Find the consumer and read it. A field
   stored as an untyped string and parsed schema-on-read **absorbs** new values;
   a typed column or a closed enum **breaks**.
3. **"This is a new capability" — is the surface reachable for us?** Capability
   != reachability (`verify-before-assuming.md`): a documented feature whose
   enable path is a console we don't govern is not available to us.

### 4b.3 — Downgrade the severity to what the probe supports

Re-grade AFTER probing, never before. The probe usually moves severity **down**,
because Step 3 grades on assumed blast radius:

| Probe result | Severity |
|---|---|
| impact reproduced (a consumer provably breaks / data provably absent) | keep Step 3's grade |
| our code absorbs it (schema-on-read, no closed enum, generic handler) | **downgrade** — cite the file:line that absorbs it |
| already covered in our code | **REJECT** the finding; it was never a gap |
| probe blocked | `UNVERIFIED-BLOCKED` + the blocker; do not assign a severity |

**A finding may not be presented with an unprobed impact claim.** Either the
probe backs it, or it is relabeled a hypothesis with the probe named as the next
step. This is `verify-before-assuming.md` applied to our own coverage.

---

## Step 5: Verdict per finding (MANDATORY)

One verdict per finding, from the shared set. Canonical authority —
`~/.claude/skills/_shared/gather-conventions.md` wins on any disagreement.

| Verdict | Meaning |
|---|---|
| **ADOPT** | directly apply only after deterministic qualification evidence was recorded in this same run (poller change, detector change, config change) |
| **QUALIFY** | do not apply; exercise a disposable candidate in this same run, then replace with ADOPT, DEFER, or REJECT before presentation |
| **DEFER** | reason + a **machine-checkable** trigger (e.g. "`analytics-endpoint-paths.json` count != 11") that **points at the system whose state the finding claims** — see below. Vague "maybe later" is REJECT. |
| **REJECT** | reason logged; similar future findings tagged `[previously-rejected-similar]` |

A category name (`NEW_DATA_SURFACE`, `UNTESTED_SURFACE`, `EXTRACTOR_NOISE`) is
**never** a verdict — category and verdict are separate axes, and future runs
parse the `Verdict:` field. Can't decide at run time = REJECT.

QUALIFY is a same-run, pre-application state. Run the API/code probes plus
regression, mutation, replay, and smoke checks against a disposable candidate;
record `PASSED — <command and result>` and resolve ADOPT, DEFER, or REJECT
before presentation. Never apply a collection change merely to observe it.

### A DEFER's trigger must watch the system whose state the finding claims

Every finding here has two halves (Step 4b): "the vendor documents X" and "which
matters because it affects us". **A trigger that watches the vendor cannot expire a
wrong claim about US.**

A well-formed vendor-doc trigger has survived two runs while the our-side half
of its finding was false the entire time
([references/run-history.md](references/run-history.md)). So, when writing a DEFER:

1. Identify which half the finding's action depends on. If the action is "we should
   start collecting X", the load-bearing half is **ours**, and the trigger must be a
   query against **our** telemetry/code/live state — not a doc marker.
2. **Re-measure every open DEFER's our-system half at the start of each run.** A DEFER
   is a claim about *current* state and nothing notifies this KB when it stops being
   true.
3. Reconcile Active Findings against their own `channels/*.md` pages, not just against
   the live system — two pages of one KB disagreeing is worse than uniform staleness,
   because either read alone looks authoritative.
4. For a documented-but-never-observed condition, get the **denominator** before
   proposing work: 0 rows of millions ⇒ `DOC_ONLY`, not a gap, and not grounds for
   editing a protected repo.

Finding format (exact field spellings — parsed by later runs):

```
### [#N] [HIGH|MEDIUM|LOW] Title
- **Category**: ...
- **Source**: [URL]
- **Baseline ref**: baselines/<extractor>.json
- **What changed**: [1-2 sentences]
- **Why it matters**: [effect on OUR collection]
- **Verified**: yes — [what you READ to confirm the vendor claim]
- **API probe**: [command + result] | N/A — [why no live probe applies]
                 | BLOCKED — [what is missing]
- **Code probe**: [grep/file:line proving the impact on OUR system]
                 | BLOCKED — [what is missing]
- **Severity basis**: probe-confirmed | downgraded-by-probe | UNVERIFIED-BLOCKED
- **Recommended edit**: [specific file + change]
- **Verdict**: ADOPT | QUALIFY | DEFER | REJECT
- **Trigger**: [machine-checkable event; required for DEFER, omitted otherwise]
- **Qualification**: PASSED — <command and result> | not-applicable — <reason for DEFER/REJECT>
```

`API probe`, `Code probe`, and `Severity basis` are **required fields**. A finding
missing them is incomplete, not merely under-documented — the allowed non-value is
an explicit `N/A —`/`BLOCKED —` **with a reason**, never a blank. The probe is what
separates a graded finding from a guess.

---

## Step 6: Present, then persist

Present only final findings via **AskUserQuestion**. **NEVER auto-write** a
channel page or a runtime edit. QUALIFY is not applied and must be resolved in
the same run. After approval of ADOPT: read the target, confirm the recorded
qualification evidence, edit, re-read to confirm persistence, and leave
uncommitted for review.

**Baseline carve-out.** Baseline files are content-free machine artifacts and ARE
committed with the report:

```bash
python3 ~/.claude/skills/gather-claude-endpoints/scripts/diff_channels.py \
  --kb ~/Documents/knowledge-base --run-date <date> --update-baseline
```

Rules:
- **Refresh baselines only after the drift has been graded** — updating first
  destroys the evidence for the finding you were about to write.
- **A first run ALWAYS establishes the baseline.** Fetching *is* establishing it;
  never defer a baseline to "next run" — that leaves run 2 with nothing to diff.
- **Never hand-edit a baseline.** A hand-edited baseline makes the next diff lie.
- **After refreshing a reconciled baseline, assert `observed_values` survived** (the
  pre-2026-08-01 writer erased it), then **re-run without `--update-baseline` and
  expect exit 0** — a non-idempotent refresh is a detector bug in a drift costume.

Then update `INTELLIGENCE.md`: rotate Metadata, move acted-on findings to
Archived, reject legacy calendar-observation state or unresolved QUALIFY, and
update the Watching table. The **per-channel Sources Log dates are bumped by
the differ itself** (`--update-baseline` implies it; `--update-sources-log`
does it standalone) — it bumps only fetched-OK channels and WARNS about any
registered channel with no row; add missing rows by hand with a real note.
Re-run deterministic qualification without applying the edit and resolve it in
the same run. Update any `channels/*.md` page whose facts changed, and bump the
`Verified` date in its header.

---

## Step 7: Handoffs

A finding relevant to another skill goes in the `## Handoffs` table
(`target-skill | finding | source`) so it does not dead-end here:

| Finding shape | Route to |
|---|---|
| a platform feature or env var that overlaps Claude Code product surface | `/gather-claude` |
| a new detection opportunity from a new OTel event or activity type | the detector work queue |

---

## What "authoritative" means here

Every fact in the KB traces to a vendor doc URL and carries a verification date.
Two rules keep it honest:

- **Vendor docs describe the surface; `[OUR PROBE]` rows describe what we
  measured.** Keep them labeled separately. They disagree often — a documented
  per-user cost feed that returns near-zero for us is *both* facts being true.
- **Untested is not the same as verified.** The 5 Analytics endpoints in finding
  #2 are documented but never probed; the KB says so explicitly. Do not let a
  documented endpoint graduate to "we can collect this" without a probe.
- **Vendor docs are a FILTER, not the surface — so they cannot be the only
  source.** `diff_channels.py` asks exactly one question: what do Anthropic's doc
  pages say? A filter returns a subset of what it was pointed at, so the differ is
  structurally incapable of finding anything the docs OMIT — live activity types
  and an already-consumed OTel event have sat outside the baselines that way
  ([references/run-history.md](references/run-history.md)). **Our own telemetry is
  the second authoritative source**, and for "what does this org actually emit" it
  is the better one: docs describe the product, telemetry describes us. Run
  `scripts/reconcile_observed.py` (Step 2c) so the diff is bidirectional.
- **There is no machine-readable spec to fall back on.** The OpenAPI candidates
  404 and the official SDK's `api.md` declares no Admin, Analytics, or Compliance
  paths, so doc prose genuinely is the only vendor source for our surfaces. That
  is exactly why the extraction must be STRUCTURED and the live reconciliation is
  not optional.
- **Three false zeros to avoid** (each shipped-a-wrong-HIGH near miss is in
  [references/run-history.md](references/run-history.md)): (a) call
  `enumerate_uncovered_pages()`, never a hand-rolled resolver; (b) a Watching
  trigger names a SPECIFIC page — probe that page, not a sibling; (c) `curl -L`
  the doc index and check `size_download` before believing any absence
  (`docs/llms.txt` returns 9 bytes without redirects).

---

## Worked examples

Two real runs — the establishing run that surfaced three detector bugs (not
vendor changes), and what a real drift run looks like — are in
[references/examples.md](references/examples.md).

## Reference

- `references/channel-map.md` — what each channel is, and the extractor rationale
- `references/adding-a-channel.md` — how to add a channel or extractor safely
- `references/athena-lake-contract.md` — lake naming/columns the queries assume
  (bare event names, `sweep_*` columns, `principal`; read BEFORE hand-authoring
  any Athena query)
- `references/run-history.md` — dated measurements behind the rules above
- `scripts/diff_channels.py` — compatibility shim; the ENGINE lives at
  `skills/_shared/endpoint-drift/diff_engine.py` and has a second consumer,
  `gather-openai-endpoints` — an engine change must keep both vendors' test
  suites green
- `scripts/channel_specs.py` — the channel + extractor + trigger registry
  (data, not logic; dataclasses import from `_shared/endpoint-drift/spec_types.py`)
- `tests/test_diff_channels.py` — fixture tests that prove the differ before use

**Extractor authoring rule:** never guard an open vocabulary with a closed
alternation (five extractors shared that one defect —
[references/run-history.md](references/run-history.md)). Anchor on the vendor's
DECLARATION FORM (table cell, enum bullet
+ description, `**Event Name**:` marker) and leave the value half open. Where
a closed set is genuinely unavoidable, mark it `ACCEPTED-CLOSED` with the
reason in the spec comment (see `hook-verdict-fields`, `otel-env-vars`).
