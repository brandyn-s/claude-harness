# gather-claude-endpoints — worked examples

Real output: Examples 1 and 2 from the establishing run (2026-07-27); Example 3
from the observed leg run against a fixture knowledge base.

### Example 1 — a run that surfaced three detector bugs, not vendor changes

```
$ python3 scripts/diff_channels.py --kb ~/Documents/knowledge-base --run-date 2026-07-27
========================================================================
CLAUDE DATA-CHANNEL DRIFT REPORT
========================================================================
channels: 15  drift: 0  new-baseline: 10  problems: 3

-- INSTRUMENT / CHANNEL PROBLEMS (fix before trusting any diff) --
  [INSTRUMENT_BLIND] compliance-activities:
      extractor activity-actor-types: extracted 0 < min_expected 6
      -- treat as extractor blindness (page restructured?), NOT as removal
  [INSTRUMENT_BLIND] compliance-endpoints:
      extractor compliance-scopes: extracted 0 < min_expected 3
  [INSTRUMENT_BLIND] gateway:
      extractor gateway-telemetry-keys: extracted 1 < min_expected 4
```

Correct reading: **zero of these is a vendor change.** Without the
`min_expected` floor, the first would have been reported as "Anthropic removed
all actor types." Diagnosis and fixes, all applied in the same run (Step 2b):

| Extractor | Root cause | Fix |
|---|---|---|
| `activity-actor-types` | required backticks; the API **reference** lists actor types as bare schema tokens | dropped the backtick anchor |
| `compliance-scopes` | pointed at the endpoint reference, which never names scopes | split out a new `compliance-access` channel |
| `gateway-telemetry-keys` | required backticks; pushed-var list is a plain bullet list | dropped the backtick anchor |

Fixing #1 produced a genuine **HIGH** finding: the reference carries **9** actor
types (`federated_identity_actor`, `service_account_actor`, `system_actor` beyond
the prose guide's 6). A SIEM rule keyed on a 6-member union silently drops three
principal classes.

Post-fix, clean:

```
channels: 15  drift: 0  new-baseline: 14  problems: 0
  activity-types: 412 values captured
  activity-actor-types: 9 values captured
  analytics-endpoint-paths: 11 values captured
```

### Example 2 — what a real drift run looks like

```
-- DRIFT --
  otel  (https://code.claude.com/docs/en/monitoring-usage.md)
    otel-events: 28 baseline -> 29 live
      + claude_code.sandbox_denied   [NEW]
      why it matters: Event types are the audit-grade surface.
                      New event = new detection opportunity.

  analytics-enterprise  (https://platform.claude.com/docs/en/api/admin/analytics.md)
    analytics-endpoint-paths: 11 baseline -> 10 live
      - /v1/organizations/analytics/plugins   [REMOVED]
```

Grade these differently (Step 3): the **addition** is MEDIUM — an opportunity.
The **removal** is HIGH — if anything we run calls that endpoint, it is already
broken and we hadn't noticed. Removals outrank additions.

### Example 3 — the observed leg (Step 2c): an inventory diffed against the baselines

```
$ python3 scripts/reconcile_observed.py --kb <kb-dir> --observed observed.json
========================================================================
OBSERVED-vs-DOCUMENTED RECONCILIATION
========================================================================
fact-sets: 3   detector-blind: 1

[DOC_ONLY] activity-types
    baseline 3  observed 2  documented-but-unobserved 1
[UNDOCUMENTED] otel-events
    baseline 5  observed 5  documented-but-unobserved 1
    UNDOCUMENTED  claude_code.subagent_completed
[NO_BASELINE] webhook-event-types
    observed 1, no baseline to compare

ACTION: add the UNDOCUMENTED values to their baselines (--update-baseline), and consider whether each warrants a detector.
These are LIVE in the observed data and the docs-only differ can never see them.
```

Exit 1. `observed.json` was `{"otel-events": ["api_error", ..., "subagent_completed"],
"activity-types": [...], "webhook-event-types": [...]}` — bare OTel event names,
normalised to the documented `claude_code.` form before comparison.

Reading it: `DOC_ONLY` is informational (one documented activity type this org never
generated — not a gap). `UNDOCUMENTED` is the finding: a live event the docs never
listed, so the docs differ is blind to it until `--update-baseline` merges it with
`observed_values` provenance (after which the differ reports it `OBSERVED_ONLY`,
held out of the docs diff). `NO_BASELINE` means the differ has not established that
fact-set yet (Step 6) — nothing drifted.
