# gather-claude-endpoints — worked examples

Real output from the establishing run, 2026-07-27.

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
