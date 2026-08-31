# Athena lake contract — what the queries in this skill assume

The reconciliation and `--watch` legs query our own lake. Every convention
below was learned by a wasted round-trip; read this before hand-authoring any
query against these tables. (Run 6 burned three Athena round-trips on the
first two rows of this table alone.)

Execution context: database `mcp_compliance`, workgroup `mcp-compliance`,
region `us-east-2`, profile `dev-security` (constants in
`reconcile_observed.py`). Full-table DISTINCT scans are expensive — always
partition-scope with `(year*10000+month*100+day) >= <floor>`.

## `claude_code_events` (OTel events, flattened)

| Contract | Detail | How it bit |
|---|---|---|
| **Event names are stored BARE** | the flat view strips the vendor's `claude_code.` prefix: the lake holds `user_prompt`, `retention_sweep` — the DOCS write `claude_code.user_prompt` | run 6 queried the prefixed form and got 0 rows / a 32-row residue (a small emitter bypasses the strip), which briefly read as "the whole event lane broke". `NORMALIZERS` in `reconcile_observed.py` re-prefixes the OBSERVED side only for baseline comparison |
| **`retention_sweep` attributes are FLATTENED columns** | `sweep_skip_reason`, `sweep_period_days`, `sweep_used_default`, `sweep_transcripts_deleted`, `sweep_result` | run 6 guessed `json_extract_scalar(attributes, ...)` — there is no `attributes` column (COLUMN_NOT_FOUND) |
| **Identity column is `principal`** | COALESCE of best-available identity; `user_email` is 0% populated on Desktop (finding #18) | run 6 guessed `user_account_uuid` (COLUMN_NOT_FOUND); a per-user rollup joining on email silently drops the whole Desktop service |
| **`service_name` carries MANY products** | `claude-code`, `claude-desktop`, `claude-code-desktop`, `cowork`, `canary-recall-probe`, plus (since 2026-08-14) `codex-app-server`, `openai-monitor-ingest`, and other OpenAI-monitor services in the SAME table | an unscoped event census mixes vocabularies across products and two vendors; always filter `service_name` |
| **Old rows carry log content in `event_name`** | pre-floor records COALESCE down to `body.stringvalue` (12,431 phantom "events" measured 2026-08-02) | this is why `OBSERVED_FLOOR_YMD` exists; never lower it casually |
| **Partition columns** | integer `year`, `month`, `day` (+ `hour`) | string comparisons silently full-scan |

Healthy-volume reference (2026-08-22): `claude-code` ~300–460K rows/day;
`claude-desktop` ~20–30K/day. A canned check returning zero against those
norms is a query bug until a same-shape known-positive control also fails.

## `activities` (Compliance activity feed)

- `type` is the activity type, stored exactly as the vendor sends it (no
  prefix games). `actor` is a JSON string — read with
  `json_extract_scalar(actor, '$.type')` etc.; there is NO closed actor enum
  anywhere (finding #1).
- Same integer partition columns.

## `code_analytics` (CC Analytics daily report)

- Whole API records pass through to S3 (schema-on-read) — new vendor fields
  (e.g. `is_remote`, 2026-08-22) arrive with no ingest change.
- `core_metrics`, `tool_actions`, `model_breakdown` are JSON-STRING columns of
  three DIFFERENT shapes (object / object / array). Don't cast in SQL; return
  blobs and flatten in Python (`json_key_set`).

## `cowork_otel_traces` (spans, beta)

- Live since 2026-07-19 (1.44M+ spans); span names are the
  `otel-trace-spans` fact-set (`claude_code.tool.execution` etc.). Nothing
  consumes them yet.

## Query-shape gotchas (Athena/Trino)

- **Positional GROUP BY refers to the SELECT list** — `GROUP BY 1` against a
  concatenation containing `count(*)` fails EXPRESSION_NOT_SCALAR (run 6).
  Group by the raw columns in a subquery, concatenate outside.
- `athena_results()` returns the FIRST column only, and strips the header row
  by deriving the SELECTed column name — pack multi-column results into one
  `||`-joined column aliased `r` (see `watch_queries()` for the idiom).
- The CLI paginator needs `--max-items` + NextToken and is capped at 200
  pages here on purpose.
