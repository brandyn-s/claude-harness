# Triage Output Format

## Summary Table

```
### Triage Summary - {date} ({scope})

**Tools queried**: {list tools checked and their status: online/offline}
**Findings**: {total} ({critical} Critical, {high} High, {medium} Medium, {low} Low)
**Known patterns filtered**: {count}

| # | Finding | Severity | Composite | Confidence | Tool | Status | Entity | Known? | Action |
|---|---------|----------|-----------|------------|------|--------|--------|--------|--------|
| 1 | (title/ID) | Critical | 9.2 | HIGH | CS | New | (hostname) | -- | Investigate |
```

Confidence levels:
- **HIGH**: Corroborated by 2+ independent tools
- **MEDIUM**: Single tool finding that matches known patterns
- **LOW**: Single tool finding that is ambiguous or lacks corroboration

## Detail Block (CRITICAL and HIGH only)

```
**[#] {title}**
- **Source**: {tool} - {detection ID, CVE, issue ID, or alert ID}
- **Severity**: {level} | **Composite score**: {score}/10 | **Confidence**: {HIGH/MEDIUM/LOW}
  - Severity: {x}/10 | Asset: {x}/10 | Exposure: {x}/10 | Context: {x}/10
- **Affected**: {entity} - {details}
- **Evidence**: {key indicators}
- **Correlation**:
  - {Tool}: {cross-tool finding or "no matches"}
- **Topic memory match**: {matching [confirmed]/[observed] entry, or "none"}
- **Recommended action**: {Investigate/Remediate/Escalate/Monitor/Close} - {1-sentence rationale}
```

## MEDIUM/LOW Summary

```
### MEDIUM/LOW Summary ({count} findings)

| Category | Count | Top finding |
|----------|-------|-------------|
```

## Footer

```
### Next Steps
- [ ] {Recommended action 1}
- [ ] {Recommended action 2}

### Tools Status
Every Phase 1 tool MUST appear with an explicit status label:
- `online` — reachable, findings or none-found inline
- `online (no findings)` — reachable, empty result set
- `offline` — unreachable
- `auth-expired` — credentials need refresh
- `error: <one-line cause>` — call failed for other reasons
- `topic-missing` — topic-memory file not loaded; tool query proceeded without it

| Tool | Status |
|------|--------|
| CrowdStrike | online |
| Tenable | auth-expired |
| ... | ... |

### Writes Executed
List each approved write operation verbatim, in execution order. Empty list means read-only.

| # | Tool | Operation | Approved by |
|---|------|-----------|-------------|
| 1 | Airlock | Add SHA-256 abc... to allowlist on policy Workstations | user (Phase 5) |
```
