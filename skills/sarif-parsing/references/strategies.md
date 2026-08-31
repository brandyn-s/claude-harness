# SARIF Parsing Strategies

Detailed strategies for parsing, aggregating, and extracting data from SARIF files.
Pick the approach that matches your use case — CLI exploration, programmatic access,
reporting, aggregation, or structured extraction.

## Strategy 1: Quick Analysis with jq

For rapid exploration and one-off queries:

```bash
# Pretty print the file
jq '.' results.sarif

# Count total findings
jq '[.runs[].results[]] | length' results.sarif

# List all rule IDs triggered
jq '[.runs[].results[].ruleId] | unique' results.sarif

# Extract errors only
jq '.runs[].results[] | select(.level == "error")' results.sarif

# Get findings with file locations
jq '.runs[].results[] | {
  rule: .ruleId,
  message: .message.text,
  file: .locations[0].physicalLocation.artifactLocation.uri,
  line: .locations[0].physicalLocation.region.startLine
}' results.sarif

# Filter by severity and get count per rule
jq '[.runs[].results[] | select(.level == "error")] | group_by(.ruleId) | map({rule: .[0].ruleId, count: length})' results.sarif

# Extract findings for a specific file ([]? skips results without locations)
jq --arg file "src/auth.py" '.runs[].results[] | select(.locations[]?.physicalLocation.artifactLocation.uri | contains($file))' results.sarif
```

## Strategy 2: Python with pysarif

For programmatic access with full object model:

```python
from pysarif import load_from_file, save_to_file

# Load SARIF file
sarif = load_from_file("results.sarif")

# Iterate through runs and results
for run in sarif.runs:
    tool_name = run.tool.driver.name
    print(f"Tool: {tool_name}")

    for result in run.results:
        print(f"  [{result.level}] {result.rule_id}: {result.message.text}")

        if result.locations:
            loc = result.locations[0].physical_location
            if loc and loc.artifact_location:
                print(f"    File: {loc.artifact_location.uri}")
                if loc.region:
                    print(f"    Line: {loc.region.start_line}")

# Save modified SARIF
save_to_file(sarif, "modified.sarif")
```

## Strategy 3: Python with sarif-tools

For aggregation, reporting, and CI/CD integration:

```python
from sarif import loader

# Load single file
sarif_data = loader.load_sarif_file("results.sarif")

# Or load multiple files
sarif_set = loader.load_sarif_files(["tool1.sarif", "tool2.sarif"])

# Get summary report
report = sarif_data.get_report()

# Get histogram by severity
errors = report.get_issue_type_histogram_for_severity("error")
warnings = report.get_issue_type_histogram_for_severity("warning")

# Filter results
high_severity = [r for r in sarif_data.get_results()
                 if r.get("level") == "error"]
```

**sarif-tools CLI commands:**

```bash
# Summary of findings (counts grouped by severity + rule)
sarif summary results.sarif

# List all SARIF files in a directory ('ls' lists files, not results)
sarif ls path/to/sarif-dir/

# Filter results by severity — sarif-tools has no per-result severity filter
# in the CLI; the global --check flag sets exit code, not output filtering.
# Use jq for output filtering by severity:
jq '.runs[].results[] | select(.level == "error")' results.sarif

# Or exit non-zero if any 'error' level findings are present (CI gate):
sarif --check error summary results.sarif

# Diff two SARIF files (find new/fixed issues)
sarif diff baseline.sarif current.sarif

# Convert to other formats — MUST use -o/--output; subcommand writes to
# <basename>.csv / <basename>.html in cwd by default, and only the
# status line reaches stdout (so shell '>' redirection captures the
# status string, NOT the report).
sarif csv -o results.csv results.sarif
sarif html -o report.html results.sarif
```

## Strategy 4: Aggregating Multiple SARIF Files

When combining results from multiple tools:

```python
import json
from pathlib import Path

def aggregate_sarif_files(sarif_paths: list[str]) -> dict:
    """Combine multiple SARIF files into one."""
    aggregated = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": []
    }

    for path in sarif_paths:
        with open(path) as f:
            sarif = json.load(f)
            aggregated["runs"].extend(sarif.get("runs", []))

    return aggregated

def deduplicate_sarif_results(sarif: dict) -> dict:
    """Remove duplicate findings based on fingerprints.

    Note: this is an inline reference implementation that operates on the
    raw SARIF dict. It is distinct from ``sarif_helpers.deduplicate()``
    in resources/sarif_helpers.py, which operates on a list of
    ``Finding`` dataclasses instead. Pick whichever matches your input.
    """
    seen_fingerprints = set()

    for run in sarif["runs"]:
        unique_results = []
        for result in run.get("results", []):
            # Use partialFingerprints or create key from location
            fp = None
            if result.get("partialFingerprints"):
                fp = tuple(sorted(result["partialFingerprints"].items()))
            elif result.get("fingerprints"):
                fp = tuple(sorted(result["fingerprints"].items()))
            else:
                # Fallback: create fingerprint from rule + location
                loc = result.get("locations", [{}])[0]
                phys = loc.get("physicalLocation", {})
                fp = (
                    result.get("ruleId"),
                    phys.get("artifactLocation", {}).get("uri"),
                    phys.get("region", {}).get("startLine")
                )

            if fp not in seen_fingerprints:
                seen_fingerprints.add(fp)
                unique_results.append(result)

        run["results"] = unique_results

    return sarif
```

## Strategy 5: Extracting Actionable Data

```python
import json
from dataclasses import dataclass
from typing import Optional

@dataclass
class Finding:
    rule_id: str
    level: str
    message: str
    file_path: Optional[str]
    start_line: Optional[int]
    end_line: Optional[int]
    fingerprint: Optional[str]

def extract_findings(sarif_path: str) -> list[Finding]:
    """Extract structured findings from SARIF file."""
    with open(sarif_path) as f:
        sarif = json.load(f)

    findings = []
    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            loc = result.get("locations", [{}])[0]
            phys = loc.get("physicalLocation", {})
            region = phys.get("region", {})

            findings.append(Finding(
                rule_id=result.get("ruleId", "unknown"),
                level=result.get("level", "warning"),
                message=result.get("message", {}).get("text", ""),
                file_path=phys.get("artifactLocation", {}).get("uri"),
                start_line=region.get("startLine"),
                end_line=region.get("endLine"),
                fingerprint=next(iter(result.get("partialFingerprints", {}).values()), None)
            ))

    return findings

# Filter and prioritize
def prioritize_findings(findings: list[Finding]) -> list[Finding]:
    """Sort findings by severity."""
    severity_order = {"error": 0, "warning": 1, "note": 2, "none": 3}
    return sorted(findings, key=lambda f: severity_order.get(f.level, 99))
```
