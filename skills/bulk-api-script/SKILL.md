---

name: bulk-api-script
description: "Generate a Python script for bulk API operations (100+ results) instead of MCP pagination."
when_to_use: Use when performing bulk data operations (over 100 results) against any API - ensures Python script approach instead of MCP pagination. Do NOT use for small queries under 100 results that MCP tools handle natively, or for read-only lookups and triage (use /triage instead).
disable-model-invocation: false
argument-hint: "[API and operation, e.g. 'CrowdStrike export alerts', 'Tenable export vulns', 'Graph list all users', 'Ramp export spend']"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: AskUserQuestion Bash Write
---

## bulk-api-script

# Bulk API Script Pattern

AVOID paginating bulk data through MCP tools by default. Write a standalone Python script instead. Documented exceptions live in per-API notes below (e.g., Ramp uses MCP `load_*` + `execute_query` with SQL LIMIT/OFFSET — see the Ramp section).

## Steps
1. **Load the relevant topic file** from `~/.claude/agent-memory/topics/` for the API you're targeting (e.g., `crowdstrike.md`, `ramp.md`, `tenable.md`). The topic file has auth patterns, URL endpoints, and known gotchas.
2. Write script to a .py file using the Write tool (never inline via `python -c`)
3. Use `requests` (or pyTenable/falconpy for specific APIs - check topic file for recommended library)
4. Always specify `encoding='utf-8'` in open() calls
5. When using `str.replace()` / `bytes.replace()` on file content read in BINARY mode (`'rb'`) with `b'\n'`, the replacement matches only the `\n` byte and leaves any preceding `\r` orphaned -- producing partially-corrupted output (e.g., `b"line1\r\nline2\r\n"` → `b"line1\rline2\r"` when replacing `b'\n'` with `b''`). The bug is partial corruption, not a silent no-op. In Python 3 text mode (default), the open() call auto-converts `\r\n` → `\n` on read so `str.replace('\n', ...)` works as expected. Prefer `splitlines()` + `join()` or `re.sub(rb'\r?\n', ...)` if you need explicit line-ending-agnostic work on bytes.
6. Load credentials from environment variables - never hardcode (check topic file for env var names)
7. Include error handling: guard against None, check for error keys before iterating
8. Handle KeyboardInterrupt gracefully (flush partial output, print count so far)
9. On Windows/Git Bash, set `MSYS_NO_PATHCONV=1` before execution if script args contain URL paths
10. Execute with: `python3 script.py`

## API-Specific Rules

### Airlock Digital
- `type` field MUST be a list: `{'type': [2]}` not `{'type': 2}`
- `hashes` field MUST be a list: `{'hashes': ['abc...']}` not `{'hashes': 'abc...'}`
- Pagination breaks at 10K events -- use checkpoint-based retrieval
- Server: airlock.example.internal:3129, all operations are POST
- Auth: `headers = {'X-ApiKey': os.environ['AIRLOCK_API_KEY']}`
- API can return `None` instead of `[]` -- always guard with `events = resp.json()['response']['exechistories'] or []`
- SSL: add `--insecure` flag support and `urllib3.disable_warnings()` for self-signed certs
- Checkpoint calculation (MongoDB ObjectId, time-based):
  ```python
  from datetime import datetime, timedelta, timezone
  def objectid_n_hours_ago(n):
      dt = datetime.now(timezone.utc) - timedelta(hours=n)
      return hex(int(dt.timestamp()))[2:] + '0000000000000000'
  # Use '000000000000000000000000' (24 zeros) for ALL events from beginning of time
  ```
- Break condition: `if len(events) < 10000: break` (page is not full = last page)

### Tenable FedCloud
- URL: https://fedcloud.tenable.com (FedRAMP -- NOT commercial cloud.tenable.com)
- Export threshold: use exports for `num_assets >= 50`; for smaller result sets, use the interactive tools (`search_assets`, `search_vulnerabilities`, etc.) instead -- the export API path is optimized for bulk and not the right surface for small queries
- pyTenable severity filter uses **lowercase**: `severity=['critical', 'high']` (NOT `'Critical'`)
- Use export APIs (`tio.exports.vulns()`, `tio.exports.assets()`), not workbenches (deprecated)
- FedCloud returns **flat fields** -- `vuln['plugin_id']` NOT `vuln['plugin']['id']`. Never use nested access.
- Exports are async iterators -- chunks download in background, iterator blocks until ready
- Auth:
  ```python
  tio = TenableIO(
      access_key=os.environ['TENABLE_ACCESS_KEY'],
      secret_key=os.environ['TENABLE_SECRET_KEY'],
      url='https://fedcloud.tenable.com'
  )
  ```
- Pin `marshmallow<4` -- pytenable 1.9.0 breaks on marshmallow 4.x

### CrowdStrike GovCloud
- URL: api.laggar.gcw.crowdstrike.com (GovCloud -- NOT api.crowdstrike.com)
- **Use Alerts API v2/v3** -- `detects` API deprecated Sept 2025, `incidents` deprecated March 2026
  - Query: `GET /alerts/queries/alerts/v2?filter=<FQL>&limit=100&offset=0`
  - Details: `POST /alerts/entities/alerts/v2` body `{"composite_ids": [...]}`
  - Update: `PATCH /alerts/entities/alerts/v3` body `{"composite_ids": [...], "action_parameters": [...]}`
- Max 100 IDs per PATCH/POST detail request -- batch in loops
- FQL dates: ISO 8601 with quotes: `created_timestamp:>'2026-01-01T00:00:00Z'`
- CrowdScore: `modified_timestamp` is NOT a valid sort param on GovCloud -- omit sort or use default
- OAuth2 auth (tokens expire in 30 min, refresh 60s before expiry):
  ```python
  resp = requests.post(f'{BASE}/oauth2/token',
      data={'client_id': os.environ['CS_CLIENT_ID'],
            'client_secret': os.environ['CS_CLIENT_SECRET']})
  token = resp.json()['access_token']
  headers = {'Authorization': f'Bearer {token}'}
  ```
- Falconpy init (alternative to raw requests):
  ```python
  from falconpy import Alerts
  alerts = Alerts(client_id=os.environ['CS_CLIENT_ID'],
                  client_secret=os.environ['CS_CLIENT_SECRET'],
                  base_url='https://api.laggar.gcw.crowdstrike.com')
  ```
- MCP now supports writes (PR #242, 2026-03-24): `falcon_contain_host`, `falcon_update_alert`, `falcon_update_incident`, `falcon_add_host_to_group` (OPA-gated, require user confirmation). For bulk write operations not covered by MCP tools, or when scripting outside Claude, use `cs_hygiene.py` (documented location: `$HOME/Documents/CrowdStrike/cs_hygiene.py` — verify it exists on the current host before relying on it; some hosts have not had it migrated, in which case treat this as a gap and use the OPA-gated MCP write tools above or fall back to `/bulk-api-script`'s reviewed-script pattern instead of fabricating the file).

### MS Graph GCC High
- Endpoints: login.microsoftonline.us / graph.microsoft.us (NOT .com)
- Scope: https://graph.microsoft.us/.default
- Auth: OBO delegated only (via MCP Gateway app `00000000...`). No client credentials fallback.
  For standalone scripts, use MSAL client credentials:
  ```python
  from msal import ConfidentialClientApplication
  app = ConfidentialClientApplication(
      os.environ['GRAPH_CLIENT_ID'],
      authority='https://login.microsoftonline.us/' + os.environ['GRAPH_TENANT_ID'],
      client_credential=os.environ['GRAPH_CLIENT_SECRET'])
  token = app.acquire_token_for_client(scopes=['https://graph.microsoft.us/.default'])
  ```
- Pagination: Graph returns max 999 items per page. Follow `@odata.nextLink`:
  ```python
  url = 'https://graph.microsoft.us/v1.0/users?$top=999'
  while url:
      resp = requests.get(url, headers=headers).json()
      results.extend(resp.get('value', []))
      url = resp.get('@odata.nextLink')
  ```
- Add retry logic for 429/5xx (3 attempts, exponential backoff, respect Retry-After header) AND for raised connection exceptions — `requests.exceptions.ConnectionError` / `Timeout` / `ChunkedEncodingError` (e.g. a transient `WinError 10053`/`10054` abort mid-request). A retry loop that only branches on `response.status_code` silently propagates these *raised* exceptions and kills a long-running run; catch them and retry with the same backoff. Also pass `timeout=(connect, read)`. Applies to ANY long-running API loop — and to pre-authed raw `requests` calls (download URLs, upload-session chunks), not just Graph.
- Use `$select` to limit fields -- reduces payload size and speeds up large exports

### Ramp (SQL backend)
- Ramp MCP uses a SQLite backend with ~100-row result limit per query
- For bulk data: use `load_spend_export` (async, can take 2+ min for >1yr), then paginate with SQL `LIMIT`/`OFFSET`
- Always discover schema first: `PRAGMA table_info(spend_export)` before writing queries
- Use `GROUP BY` / `SUM()` aggregation to stay under the 100-row limit when possible
- Poll with `execute_query` every 15-20s after `load_spend_export` to check if table is populated
- Key columns: `payee_name` (clean merchant), `amount`, `user_transaction_time`, `user_first_name`
- Categories are unreliable (`sk_category_name`) -- cross-reference `payee_name` or `merchant_category_code`
- For Ramp, use MCP `load_*` + `execute_query` tools with LIMIT/OFFSET, NOT direct API scripts
- If MCP LIMIT/OFFSET is insufficient (need CSV export of all rows), write a Python script that calls `execute_query` in a loop with increasing OFFSET until 0 rows returned

## Success Criteria

- Script written to .py file before execution (never inline via `python -c`)
- All `open()` calls use `encoding='utf-8'`
- Script includes error handling for None responses and API errors
- KeyboardInterrupt handler flushes partial output and prints count so far
- Output includes record count, page count, error count, and duration
- Progress printed to stderr, data to stdout or file
- CSV for tabular data (use `csv.DictWriter`), JSON for nested/complex data (`json.dump` with indent=2)
- Credentials loaded from env vars, never hardcoded

## Examples

**Example 1: CrowdStrike alert export (Alerts v2/v3 -- NOT deprecated detects API)**
User says: "Export all critical alerts from the last 30 days"
Actions:
1. Write `cs_export_alerts.py` using falconpy `Alerts` class with GovCloud base URL
2. OAuth2 auth from `CS_CLIENT_ID`/`CS_CLIENT_SECRET` env vars
3. FQL filter: `severity_name:'Critical'+created_timestamp:>'2026-01-26T00:00:00Z'`
4. Query IDs via `/alerts/queries/alerts/v2`, then batch 100 IDs per detail request via `/alerts/entities/alerts/v2`
5. Write CSV output with `csv.DictWriter` and `encoding='utf-8'`, KeyboardInterrupt handler
6. Execute: `python3 cs_export_alerts.py`
Result: CSV file with alert composite_id, severity, hostname, timestamp, tactic, technique. Progress to stderr.

**Example 2: Tenable vulnerability export**
User says: "Get all critical vulns for our FedCloud assets"
Actions:
1. Write `tenable_vuln_export.py` using pyTenable with FedCloud URL
2. Auth from `TENABLE_ACCESS_KEY`/`TENABLE_SECRET_KEY` env vars
3. Use export API (not workbenches): `tio.exports.vulns(severity=['critical', 'high'], num_assets=50)`
4. Iterate async export chunks (flat field access: `vuln['plugin_id']` not nested)
5. Execute: `python3 tenable_vuln_export.py`
Result: JSON file with CVE, CVSS, asset hostname, first/last seen. Export metrics printed.

**Example 3: Ramp bulk spend export**
User says: "Export all spending data for the last 6 months"
Actions:
1. Use Ramp MCP `load_spend_export` with `from_date` and `to_date` params
2. Poll with `execute_query SELECT COUNT(*) FROM spend_export` every 15s until populated
3. Paginate with `SELECT * FROM spend_export LIMIT 100 OFFSET {n}` until 0 rows
4. If MCP pagination is too slow, write `ramp_export.py` that loops execute_query calls
Result: CSV file with payee_name, amount, user_transaction_time, user. Row count printed.

## Output Format

Two distinct outputs are produced:

1. **Data file** (the bulk export itself): CSV (`csv.DictWriter`) for tabular data, JSON (`json.dump` with indent=2) for nested/complex data. Written to a file or stdout.
2. **Summary report** (printed by the agent invoking the skill after the script completes): a markdown summary the user sees in chat.

The script itself MUST:
- Write data to the CSV/JSON file (or stdout if no `--output` arg).
- Print progress + final metrics to stderr (`print(..., file=sys.stderr)`).
- Exit non-zero on unrecoverable errors.

The agent's chat-facing summary uses this template:

```
### Bulk Export Results — {date}

**Script**: {filename.py}
**API**: {Airlock/Tenable/CrowdStrike/Graph/Ramp}
**Records exported**: {count}
**Output file**: {path to CSV/JSON}

| Metric | Value |
|--------|-------|
| Total records | {N} |
| Pages fetched | {N} |
| Errors/retries | {N} |
| Duration | {seconds}s |
```
