---
name: sarif-parsing
description: "Parse, filter, and deduplicate SARIF results from CodeQL, Semgrep, or other scanners."
when_to_use: 'Parses and processes SARIF files from static analysis tools like CodeQL, Semgrep, or other scanners. Triggers on "parse sarif", "read scan results", "aggregate findings", "deduplicate alerts", or "process sarif output". Use after a scan completes, when SARIF results need filtering, deduplication, format conversion, or CI/CD integration. Does NOT run scans — use the Semgrep or CodeQL skills for that. Do NOT use for running security scans (use /semgrep or /codeql), reviewing PR diffs (use /differential-review), or triaging false positives (use /fp-check).'
allowed-tools: Bash Read Glob Grep AskUserQuestion
effort: medium
argument-hint: "[path-to-SARIF-file]  (e.g., ./results.sarif, ~/scans/repo.sarif)"
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires jq CLI for SARIF JSON processing.
  requires:
    - cli: jq

---

# SARIF Parsing Best Practices

You are a SARIF parsing expert. Your role is to help users effectively read, analyze, and process SARIF files from static analysis tools.

## When to Use

Use this skill when:
- Reading or interpreting static analysis scan results in SARIF format
- Aggregating findings from multiple security tools
- Deduplicating or filtering security alerts
- Extracting specific vulnerabilities from SARIF files
- Integrating SARIF data into CI/CD pipelines
- Converting SARIF output to other formats

## When NOT to Use

Do NOT use this skill for:
- Running static analysis scans (use CodeQL or Semgrep skills instead)
- Writing CodeQL or Semgrep rules (use their respective skills)
- Analyzing source code directly (SARIF is for processing existing scan results)
- Triaging findings without SARIF input (use variant-analysis or audit skills)

## PoC / staleness gate (semgrep, codeql, any SARIF tool)

Before triaging a SARIF batch, dedup it and **drop findings whose flagged
code is no longer present** — fixed, moved, or a wrong-location false
positive:

```bash
python3 resources/sarif_poc_gate.py results.sarif --root <scanned-tree> [--json]
```

It dedups (fingerprint), then routes each finding through the hardened
`_shared/oracle` grep reproducer and classifies it:

- **PRESENT** — flagged snippet still at the cited location. Kept. This is
  NOT an exploitability / true-positive verdict — that needs `/fp-check` and
  a human; PRESENT only means "not stale".
- **STALE** — the snippet (or the whole file) is gone. **Dropped.**
- **INCONCLUSIVE** — the tool emitted no snippet to check. Kept + flagged.
- **ERROR** — grep instrument failure. Kept + flagged.

Conservative by design: only STALE is dropped (positive staleness evidence);
nothing is dropped on uncertainty (FN cost > FP cost in security). Report at
the layer that fired — e.g. "40 raw → 31 deduped → 22 present, 7 stale, 2
inconclusive" — never collapse that to "22 vulnerabilities".

## SARIF Structure Overview

SARIF 2.1.0 is the current OASIS standard. Every SARIF file has this hierarchical structure:

```
sarifLog
├── version: "2.1.0"
├── $schema: (optional, enables IDE validation)
└── runs[] (array of analysis runs)
    ├── tool
    │   ├── driver
    │   │   ├── name (required)
    │   │   ├── version
    │   │   └── rules[] (rule definitions)
    │   └── extensions[] (plugins)
    ├── results[] (findings)
    │   ├── ruleId
    │   ├── level (error/warning/note)
    │   ├── message.text
    │   ├── locations[]
    │   │   └── physicalLocation
    │   │       ├── artifactLocation.uri
    │   │       └── region (startLine, startColumn, etc.)
    │   ├── fingerprints{}
    │   └── partialFingerprints{}
    └── artifacts[] (scanned files metadata)
```

### Why Fingerprinting Matters

Without stable fingerprints, you can't track findings across runs:

- **Baseline comparison**: "Is this a new finding or did we see it before?"
- **Regression detection**: "Did this PR introduce new vulnerabilities?"
- **Suppression**: "Ignore this known false positive in future runs"

Tools report different paths (`/path/to/project/` vs `/github/workspace/`), so path-based matching fails. Fingerprints hash the *content* (code snippet, rule ID, relative location) to create stable identifiers regardless of environment.

## Tool Selection Guide

| Use Case | Tool | Installation |
|----------|------|--------------|
| Quick CLI queries | jq | `brew install jq` / `apt install jq` |
| Python scripting (simple) | pysarif | `pip install pysarif` |
| Python scripting (advanced) | sarif-tools | `pip install sarif-tools` |
| .NET applications | SARIF SDK | NuGet package |
| JavaScript/Node.js | sarif-js | npm package |
| Go applications | garif | `go get github.com/chavacava/garif` |
| Validation | SARIF Validator | sarifweb.azurewebsites.net |

## Parsing Strategies

Five detailed strategies with worked code examples live in
[references/strategies.md](references/strategies.md):
Strategy 1 (jq CLI), Strategy 2 (pysarif), Strategy 3 (sarif-tools),
Strategy 4 (aggregating multiple files + deduplication), Strategy 5
(extracting structured findings). Pick the strategy matching your use
case and copy the template.

## Common Pitfalls and Solutions

### 1. Path Normalization Issues

Different tools report paths differently (absolute, relative, URI-encoded):

```python
from urllib.parse import unquote
from pathlib import Path

def normalize_path(uri: str, base_path: str = "") -> str:
    """Normalize SARIF artifact URI to consistent path."""
    # Remove file:// prefix if present
    if uri.startswith("file://"):
        uri = uri[7:]

    # URL decode
    uri = unquote(uri)

    # Handle relative paths
    if not Path(uri).is_absolute() and base_path:
        uri = str(Path(base_path) / uri)

    # Normalize separators
    return str(Path(uri))
```

### 2. Fingerprint Mismatch Across Runs

Fingerprints may not match if:
- File paths differ between environments
- Tool versions changed fingerprinting algorithm
- Code was reformatted (changing line numbers)

**Solution:** Drop environment-sensitive inputs (absolute paths, line numbers)
from the fingerprint and hash content-stable components. The snippet below
combines ruleId + first 100 chars of message, and optionally folds in the
trimmed source line when the file content is available — that fallback is
what makes the fingerprint robust to reformatting (the trimmed line content
is more stable than the line number). For a stronger approach with multiple
independent fingerprint strategies (e.g. fall back to ruleId+filename when
no source is available, then ruleId+message when even the file path is
unstable), chain the calls and union the resulting sets.

```python
def compute_stable_fingerprint(result: dict, file_content: str = None) -> str:
    """Compute environment-independent fingerprint."""
    import hashlib

    components = [
        result.get("ruleId", ""),
        result.get("message", {}).get("text", "")[:100],  # First 100 chars
    ]

    # Add code snippet if available
    if file_content and result.get("locations"):
        region = result["locations"][0].get("physicalLocation", {}).get("region", {})
        if region.get("startLine"):
            lines = file_content.split("\n")
            line_idx = region["startLine"] - 1
            if 0 <= line_idx < len(lines):
                # Normalize whitespace
                components.append(lines[line_idx].strip())

    return hashlib.sha256("".join(components).encode()).hexdigest()[:16]
```

### 3. Missing or Incomplete Data

SARIF allows many optional fields. Always use defensive access:

```python
def safe_get_location(result: dict) -> tuple[str, int]:
    """Safely extract file and line from result."""
    try:
        loc = result.get("locations", [{}])[0]
        phys = loc.get("physicalLocation", {})
        file_path = phys.get("artifactLocation", {}).get("uri", "unknown")
        line = phys.get("region", {}).get("startLine", 0)
        return file_path, line
    except (IndexError, KeyError, TypeError):
        return "unknown", 0
```

### 4. Large File Performance

For very large SARIF files (100MB+):

```python
import ijson  # pip install ijson

def stream_results(sarif_path: str):
    """Stream results without loading entire file."""
    with open(sarif_path, "rb") as f:
        # Stream through results arrays
        for result in ijson.items(f, "runs.item.results.item"):
            yield result
```

### 5. Schema Validation

Validate before processing to catch malformed files:

```bash
# Using ajv-cli
npm install -g ajv-cli
ajv validate -s sarif-schema-2.1.0.json -d results.sarif

# Using Python jsonschema
pip install jsonschema
```

```python
from jsonschema import validate, ValidationError
import json

def validate_sarif(sarif_path: str, schema_path: str) -> bool:
    """Validate SARIF file against schema."""
    with open(sarif_path) as f:
        sarif = json.load(f)
    with open(schema_path) as f:
        schema = json.load(f)

    try:
        validate(sarif, schema)
        return True
    except ValidationError as e:
        print(f"Validation error: {e.message}")
        return False
```

## CI/CD Integration Patterns

### GitHub Actions

```yaml
- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: results.sarif

- name: Check for high severity
  run: |
    HIGH_COUNT=$(jq '[.runs[].results[] | select(.level == "error")] | length' results.sarif)
    if [ "$HIGH_COUNT" -gt 0 ]; then
      echo "Found $HIGH_COUNT high severity issues"
      exit 1
    fi
```

### Fail on New Issues

```python
# Uses the shipped helper from resources/sarif_helpers.py. Add that file's
# directory to sys.path (or copy the helper into your repo) before importing.
from sarif import loader
from sarif_helpers import compute_fingerprint

def check_for_regressions(baseline: str, current: str) -> int:
    """Return count of new issues not in baseline."""
    baseline_data = loader.load_sarif_file(baseline)
    current_data = loader.load_sarif_file(current)

    baseline_fps = {compute_fingerprint(r) for r in baseline_data.get_results()}
    new_issues = [r for r in current_data.get_results()
                  if compute_fingerprint(r) not in baseline_fps]

    return len(new_issues)
```

## Key Principles

1. **Validate first**: Check SARIF structure before processing
2. **Handle optionals**: Many fields are optional; use defensive access
3. **Normalize paths**: Tools report paths differently; normalize early
4. **Fingerprint wisely**: Combine multiple strategies for stable deduplication
5. **Stream large files**: Use ijson or similar for 100MB+ files
6. **Aggregate thoughtfully**: Preserve tool metadata when combining files

## Skill Resources

For ready-to-use query templates, see [resources/jq-queries.md](resources/jq-queries.md):
- 40+ jq queries for common SARIF operations
- Severity filtering, rule extraction, aggregation patterns

For Python utilities, see [resources/sarif_helpers.py](resources/sarif_helpers.py):
- `normalize_path()` - Handle tool-specific path formats
- `compute_fingerprint()` - Stable fingerprinting ignoring paths
- `deduplicate()` - Remove duplicates from a list of `Finding` objects

## Reference Links

- [OASIS SARIF 2.1.0 Specification](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html)
- [Microsoft SARIF Tutorials](https://github.com/microsoft/sarif-tutorials)
- [SARIF SDK (.NET)](https://github.com/microsoft/sarif-sdk)
- [sarif-tools (Python)](https://github.com/microsoft/sarif-tools)
- [pysarif (Python)](https://github.com/Kjeld-P/pysarif)
- [GitHub SARIF Support](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning)
- [SARIF Validator](https://sarifweb.azurewebsites.net/)
## Examples

**Example 1: CodeQL results analysis**
User says: "parse the SARIF output from our CodeQL scan"
Actions: Read the SARIF 2.1.0 file, extract results with rule IDs and severity, deduplicate using fingerprints, present findings grouped by rule.
Result: Structured findings table with deduplication applied.

**Example 3: Aggregating multi-repo SARIF for fleet view**
> User: /sarif-parsing scans/2026-05-27-fleet/*.sarif
> Skill: Parses all SARIF files in the directory, groups findings by rule
> across repos, ranks by total count + max severity. Filters out warnings
> in test code via `--exclude tests/`. Produces fleet-wide top-20 finding
> table with per-repo breakdown.
> Result: 412 unique findings; top finding (CWE-79 in 11/14 repos) flagged
> for fleet remediation.

**Example 2: Cross-tool comparison**
User says: "compare SARIF outputs from Semgrep and CodeQL"
Actions: Parse both SARIF files, normalize finding formats, identify overlap using fingerprinting, present unique findings from each tool.
Result: Venn diagram summary showing shared and tool-unique findings.
## Success Criteria

- SARIF 2.1.0 schema correctly parsed including results, rules, and invocations
- Fingerprinting used for baseline comparison and deduplication across runs
- Tool-specific quirks handled (different severity scales, rule ID formats)
- Output format is actionable — findings can be triaged directly from the parsed output
