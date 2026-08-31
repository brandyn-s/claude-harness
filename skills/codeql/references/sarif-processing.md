# SARIF Processing

jq commands for processing CodeQL SARIF output. Used in the run-analysis workflow Step 5.

> **SARIF structure note:** `security-severity` and `level` are stored on rule definitions (`.runs[].tool.driver.rules[]`), NOT on individual result objects. Results reference rules by `ruleIndex`. The jq commands below join results with their rule metadata.
>
> **Portability note:** These jq patterns assume CodeQL SARIF output where `ruleIndex` is populated. CodeQL nominally always emits `ruleIndex`, but the SARIF spec allows results to omit it; if a result is missing `ruleIndex`, indexing with `null` crashes jq (`Cannot index array with null`). The patterns below use a defensive `ruleId`-based fallback (see **Portable rule lookup** at the bottom of this file) so a single result missing `ruleIndex` does not abort the whole summary.

> **Directory convention:** Unfiltered output lives in `$RAW_DIR` (`$OUTPUT_DIR/raw`). Final results live in `$RESULTS_DIR` (`$OUTPUT_DIR/results`). The summary commands below operate on `$RESULTS_DIR/results.sarif` (the final output).

## Count Findings

```bash
jq '.runs[].results | length' "$RESULTS_DIR/results.sarif"
```

## Summary by SARIF Level

The `lookup_rule` helper falls back from `ruleIndex` to `ruleId` so results lacking `ruleIndex` do not crash jq:

```bash
jq -r '
  def lookup_rule($run): . as $r |
    if ($r.ruleIndex // null) != null and ($r.ruleIndex >= 0)
    then $run.tool.driver.rules[$r.ruleIndex]
    else ($run.tool.driver.rules[] | select(.id == $r.ruleId) // null)
    end;
  .runs[] |
  . as $run |
  .results[] |
  ((. | lookup_rule($run)).defaultConfiguration.level // "unknown")
' "$RESULTS_DIR/results.sarif" \
  | sort | uniq -c | sort -rn
```

## Summary by Security Severity (most useful for triage)

```bash
jq -r '
  def lookup_rule($run): . as $r |
    if ($r.ruleIndex // null) != null and ($r.ruleIndex >= 0)
    then $run.tool.driver.rules[$r.ruleIndex]
    else ($run.tool.driver.rules[] | select(.id == $r.ruleId) // null)
    end;
  .runs[] |
  . as $run |
  .results[] |
  ((. | lookup_rule($run)).properties["security-severity"] // "none") + " | " +
  .ruleId + " | " +
  (.locations[0].physicalLocation.artifactLocation.uri // "?") + ":" +
  ((.locations[0].physicalLocation.region.startLine // 0) | tostring) + " | " +
  (.message.text // "no message" | .[0:80])
' "$RESULTS_DIR/results.sarif" | sort -rn | head -20
```

## Summary by Rule

```bash
jq -r '.runs[].results[] | .ruleId' "$RESULTS_DIR/results.sarif" \
  | sort | uniq -c | sort -rn
```

## Important-Only Post-Filter

If scan mode is "important only", filter out medium-precision results with `security-severity` < 6.0 from the report. The suite includes all medium-precision security queries to let CodeQL evaluate them, but low-severity medium-precision findings are noise.

The filter reads from `$RAW_DIR/results.sarif` (unfiltered) and writes to `$RESULTS_DIR/results.sarif` (final). The raw file is preserved unmodified.

```bash
# Filter important-only results: drop medium-precision findings with security-severity < 6.0
# Medium-precision queries without a security-severity score default to 0.0 (excluded).
# Non-medium queries are always kept regardless of security-severity.
# Reads from raw/, writes to results/ — preserving the unfiltered original.
RAW_DIR="$OUTPUT_DIR/raw"
RESULTS_DIR="$OUTPUT_DIR/results"
jq '
  def lookup_rule($run): . as $r |
    if ($r.ruleIndex // null) != null and ($r.ruleIndex >= 0)
    then $run.tool.driver.rules[$r.ruleIndex]
    else ($run.tool.driver.rules[] | select(.id == $r.ruleId) // null)
    end;
  .runs[] |= (
    . as $run |
    .results = [
      .results[] |
      . as $r |
      (($r | lookup_rule($run)).properties.precision // "unknown") as $prec |
      (($r | lookup_rule($run)).properties["security-severity"] // null) as $raw_sev |
      (if $prec == "medium" then ($raw_sev // "0" | tonumber) else 10 end) as $sev |
      select(
        ($prec == "high") or ($prec == "very-high") or ($prec == "unknown") or
        ($prec == "medium" and $sev >= 6.0)
      )
    ]
  )
' "$RAW_DIR/results.sarif" > "$RESULTS_DIR/results.sarif"
```

---

## Portable rule lookup

The `lookup_rule` helper above falls back from `ruleIndex` to `ruleId` so that:
- CodeQL SARIF (always emits `ruleIndex`) uses the fast O(1) array index path.
- A result missing `ruleIndex` falls back to scanning `tool.driver.rules[]` for the matching `ruleId` (O(N)) instead of crashing with `Cannot index array with null`.
- SARIF from other tools (Semgrep, Snyk) that emit `ruleId` without `ruleIndex` works too.

If both `ruleIndex` and `ruleId` are absent (extremely rare; would indicate a malformed SARIF), the helper returns `null` and downstream `// "unknown"` / `// "none"` defaults take over without aborting the pipeline.
