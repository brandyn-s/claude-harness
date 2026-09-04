# Adding a channel or extractor

The registry lives in `scripts/channel_specs.py` and is **data, not logic** — you
should never need to touch `diff_channels.py` to add a channel.

## Add a channel

```python
NEW = ChannelSpec(
    key="short-stable-key",          # names nothing on disk; used for --channel
    title="Human title",
    url="https://.../page.md",       # ALWAYS the .md form -- see below
    marker="a string that must be present",
    surface="claude.ai|platform|both|self-hosted|local",
    extractors=(...),
    note="anything a reader needs that isn't an extractable fact",
)
```
Then append it to `ALL_CHANNELS`.

**Use the `.md` URL.** Every Anthropic doc page serves a clean markdown twin at
`<page>.md`. Fetching the HTML instead means extracting through nav chrome and
Mintlify wrappers, which is how extractors go brittle.

**Choose the marker carefully.** It must be a string that would only be present if
the page is still *the page you meant*. A word like `analytics` is too weak — a
soft-404 page in the same docs site might contain it. An endpoint path or an exact
env-var name is strong. Soft-404s return **HTTP 200** with a "Page not found" body,
so the status code proves nothing on its own.

## Add an extractor

```python
Extractor(
    key="unique-key",        # NAMES THE BASELINE FILE -- must be globally unique
    pattern=r"...(group)...",# exactly one capture group = the fact
    min_expected=N,          # floor; below it = INSTRUMENT_BLIND
    note="what a diff on this fact-set means operationally",
)
```

### Rules that keep the false-positive rate near zero

1. **Extract identifiers, never prose.** Names, paths, integers, enum values. If
   you find yourself matching a sentence, the fact isn't extractable — put it in
   the channel's `note` and the KB page instead.

2. **Do not anchor on backticks by default.** This has bitten four extractors:
   several facts appear only inside `export FOO=1` code blocks or as bare schema
   tokens in the API reference. Requiring backticks silently extracted **zero**
   for `activity-actor-types` and dropped `CLAUDE_CODE_ENABLE_TELEMETRY` from
   `otel-env-vars`. Use `\b...\b` unless you have a reason.

3. **Strip trailing punctuation on paths.** Reference pages render paths
   mid-sentence, so a naive character class captures `.../{id}` **and**
   `.../{id}.` as two distinct "endpoints" → permanent phantom drift. End the
   pattern on a definite character class:
   `(/v1/compliance/[A-Za-z0-9_/{}-]+[A-Za-z0-9_}])`.

4. **Keep fact-sets disjoint.** `otel-metrics` and `otel-events` deliberately do
   not overlap (a negative lookahead excludes dotted counters from the event set).
   If two extractors can capture the same token, one rename shows up as drift in
   both and gets double-counted.

5. **Set `min_expected` from the live count, minus headroom.** It is a
   *blindness* floor, not an assertion of the current value. Too high and normal
   removal reads as a detector bug; too low and a restructured page reads as mass
   removal. Roughly 60-80% of the live count is a reasonable starting point.

6. **One page per spec.** If half your facts live on another page, that's a second
   `ChannelSpec` — not a wider pattern. A spec spanning two pages reports permanent
   `INSTRUMENT_BLIND` for whichever half is absent. (`compliance-access` exists
   because scopes live on the access page while endpoints live on the reference.)

## Then, in the same change

1. **Add a fixture test.** `tests/test_diff_channels.py` builds a tiny corpus with
   hand-countable ground truth. Add your extractor's expected values and assert
   exact equality — not "non-empty". Non-empty is how a wrong regex ships.
2. **Run the tests.** `python3 -m pytest tests/ -q`
3. **Run live, scoped:** `--channel <key>` and read the count. If it comes back
   `INSTRUMENT_BLIND`, the pattern is wrong — not the vendor.
4. **Establish the baseline** in the same run (`--update-baseline`). Never defer.
5. **Write the KB page** (or extend one) and add a row to `CATALOG.md`.

## Verdict semantics you must not blur

The whole value of this tool is that these three are distinguishable:

| | Means | If you conflate it with the others |
|---|---|---|
| `DRIFT` | the vendor changed something | you chase a phantom or miss a real change |
| `INSTRUMENT_BLIND` | **our** extractor broke | you report "Anthropic deleted 400 activity types" |
| `CHANNEL_DEAD` | the page moved | you trust a diff computed against the wrong page |
| `OBSERVED_ONLY` | the baseline holds telemetry-learned values the docs never had | you read them as vendor REMOVALS, every run, forever |

A detector that cannot tell its own failure from the world's change is worse than
no detector, because it reports confidently either way.

## Baseline provenance — two sources, one file

`diff_channels.py` reads the **docs**. `reconcile_observed.py --observed` (Step 2c)
merges what an **observed inventory** of the deployment reports into the *same*
baseline files. Those two sources disagree by construction: a value only the
observed inventory sees can never appear in a docs extraction.

Baselines therefore carry per-value provenance:

```json
{
  "values": ["...", "claude_code.subagent_completed"],
  "observed_values": ["claude_code.subagent_completed"],
  "observed_source": "docs + observed-inventory reconciliation"
}
```

`load_baseline()` returns `(docs_sourced, observed_only)`; only the first half is
diffed. Rules that follow from that, each with a test in `test_diff_channels.py`:

- **The held-out set is the INTERSECTION of `observed_values` and `values`.** A
  stale `observed_values` entry no longer in `values` must not invent a phantom
  member or skew the docs count.
- **A held-out value the docs later carry is PROMOTED**, not "added" — and it must
  leave `observed_values`, or it would be excluded from every future diff and never
  checked again. The report prints it as `[NOW DOCUMENTED]`.
- **`--update-baseline` must preserve provenance.** The pre-2026-08-01 writer
  emitted a fixed 5-key dict and silently erased `observed_values`/`observed_source`
  — the docs-only differ destroying the reconciliation record it was supposed to
  respect. It now merges docs-live ∪ held-out and carries the keys forward.
- **`observed_source` with NO `observed_values` is treated as fully docs-sourced**,
  and will report phantom removals. Deliberate: a flat string says some values came
  from telemetry but not *which*, and a loud wrong answer beats a silent guess about
  what to stop checking. Fix it by adding the per-value list, not by deleting values.

**What a held-out value costs.** It is unchecked by this tool, permanently. Both
current ones (`claude_code.subagent_completed`, and 24 activity types incl.
`claude_file_uploaded`) feed **closed-set** predicates in live detectors downstream
— a vendor rename *breaks* those rather than being absorbed, and only the observed
leg (a fresh inventory diffed with `--observed`) can notice. That is why
"observed-only staleness" is a Watching trigger and not a diff.

## The baseline you diff must be the NEWEST one, not just a valid one

A baseline file can be perfectly well-formed and still be the wrong reference: an
older *version of itself*. `diff_channels.py` reads whatever `--kb` points at, and
until run 5 it never asked whether that tree was current.

Measured 2026-08-11: the run was launched against `~/Documents/knowledge-base` while
that checkout sat **35 commits behind `origin/main`** — behind the previous run's own
output. The channel directory differed by **43 files / 824 deletions**, including a
whole `channels/inference-hooks.md` that existed upstream and not locally. Two harms:

1. **False findings.** Three already-shipped changes were re-derived, graded, and
   drafted (`session.budget_reached`, `inference_hooks_request_denied`, an
   Inference-hooks/App-Attest coverage gap). The stale `webhook-event-types.json`
   said 37 where upstream said 38 — that one digit *is* the phantom finding.
2. **Silent revert.** `--update-baseline` writes docs-live ∪ held-out to the tree it
   was given. On a stale tree it writes **older** values back, and committing that
   reverts the previous run while the report says DRIFT.

`baseline_freshness()` now gates every non-`--offline` run. Three rules it encodes:

- **STALE names the missing commits.** "Behind" without *what* is behind is not
  actionable, and the commit subjects are what identify the shipped findings.
- **UNKNOWN is not FRESH.** No git tree, or a failed `git fetch`, returns UNKNOWN and
  refuses. A freshness check whose own instrument failed proves nothing — reporting
  FRESH there is exactly how a stale tree gets trusted.
- **`--allow-stale-baselines` is refused with `--update-baseline`.** The override
  exists for fixture/offline work; combining it with a write is the one
  irrecoverable case.

Always cut a worktree from `origin/main` before a run. The gate refuses a stale
tree; it cannot rebase one for you.

## The coverage guard's pattern must express every path SHAPE

`COVERED_NEIGHBOURHOODS` regexes decide what `enumerate_uncovered_pages()` can even
see. The original `manage-claude/[a-z0-9-]+\.md` had no `/`, so seven
`wif-providers/*.md` pages were invisible — and the guard reported "0 uncovered"
for a reason that had nothing to do with coverage. That is the guard's *own* founding
failure (filter-and-assume) recurring inside it.

When adding a neighbourhood: allow a subdirectory (`(?:[a-z0-9-]+/)?`), key rows on
the path *relative to the neighbourhood root* so a subdirectory page cannot collapse
onto a same-named top-level page, and add a fixture asserting an unrecorded page
still surfaces as `UNCOVERED` — without that negative control, a guard that returns
an empty list passes every other test.

## Add a prose trigger (a Watching row that runs in code)

For an expectation about PROSE rather than a fact-set — "this exclusion
sentence must stay" (`expect="present"`), "no `/v1/` path may appear here"
(`expect="absent"`) — add a `ProseTrigger` to the channel instead of an
extractor. No baseline file is involved; the expectation lives in the spec.

```python
prose_triggers=(
    ProseTrigger(
        key="ih-config-api",       # stable id, shows in the report
        pattern=r"/v1/",           # evaluated with re.MULTILINE on the page
        expect="absent",           # or "present"
        note="why firing matters — this renders under the fired trigger",
    ),
),
```

Rules learned building the first eight (2026-08-22):

- **A fired trigger is DRIFT-class** (exit 1), not an instrument problem. A
  BAD trigger regex FIRES rather than silently passing — a broken trigger
  reading as "all clear" is the hand-check failure this mechanism replaces.
- **Point the trigger at the page that carries the sentence.** Run 3
  false-zeroed the Bedrock-exclusion hand check by probing the wrong page; a
  trigger is attached to a ChannelSpec, so this class of miss is structural
  now — but only if you attach it to the right spec.
- **A channel may be trigger-only** (no extractors): `analytics-cc-guide` and
  `app-attest` exist purely to keep their pages fetched and their sentences
  watched. A trigger-only channel still needs a `marker` (liveness) and it
  clears the coverage guard like any channel.
- **Verbatim sentences are fine.** Firing on a reword is usually wanted — the
  wording IS the fact, and a fired trigger means "re-read this page", not
  "vendor removed the capability".
- If the fact is COUNTABLE (table rows, enum values), prefer a real extractor
  with a baseline: `zdr-table-rows` replaced a hand-counted "still 5 rows?"
  Watching row.
