# Run-All Query Suite

In run-all mode, generate a custom `.qls` query suite file at runtime. This ensures all queries from all installed packs actually execute, avoiding the silent filtering caused by each pack's `defaultSuiteFile`.

## Why a Custom Suite

When you pass a pack name directly to `codeql database analyze` (e.g., `-- codeql/cpp-queries`), CodeQL uses the pack's `defaultSuiteFile` field from `qlpack.yml`. For official packs, this is typically `codeql-suites/<lang>-code-scanning.qls`, which applies strict precision and severity filters. This silently drops many queries and can produce zero results for small codebases.

The run-all suite explicitly references the broadest built-in suite (`security-and-quality`) for official packs and loads third-party packs with minimal filtering.

## Suite Template

Generate this file as `run-all.qls` in the raw directory (`$OUTPUT_DIR/raw/`) before running analysis. The unfiltered suite output lives in `raw/`; the final results in `results/` are a copy (run-all mode applies no post-analysis filter):

```yaml
- description: Run-all — all security and quality queries from all installed packs
# Official queries: use security-and-quality suite (broadest built-in suite)
- import: codeql-suites/<CODEQL_LANG>-security-and-quality.qls
  from: codeql/<CODEQL_LANG>-queries
# Third-party packs (include only if installed, one entry per pack)
# - queries: .
#   from: trailofbits/<CODEQL_LANG>-queries
# - queries: .
#   from: githubsecuritylab/codeql-<CODEQL_LANG>-queries  # <CODEQL_LANG> must be lowercase (python, javascript, cpp, ...)
# Minimal filtering — only select alert-type queries
- include:
    kind:
      - problem
      - path-problem
- exclude:
    deprecated: //
- exclude:
    tags contain:
      - modeleditor
      - modelgenerator
```

## Generation Script

```bash
RAW_DIR="$OUTPUT_DIR/raw"
SUITE_FILE="$RAW_DIR/run-all.qls"

# NOTE: CODEQL_LANG must be set before running this script (e.g., CODEQL_LANG=cpp)
# NOTE: INSTALLED_THIRD_PARTY_PACKS must be a space-separated list of pack names

# Pre-condition checks BEFORE writing the suite file. If CODEQL_LANG is unset
# we must abort before any `cat > "$SUITE_FILE"` would emit a broken
# `codeql/-queries` reference to disk.
: "${OUTPUT_DIR:?ERROR: OUTPUT_DIR must be set before generating suite}"
: "${CODEQL_LANG:?ERROR: CODEQL_LANG must be set before generating suite}"
: "${SUITE_FILE:?ERROR: SUITE_FILE must be set}"
mkdir -p "$RAW_DIR"

cat > "$SUITE_FILE" << HEADER
- description: Run-all — all security and quality queries from all installed packs
- import: codeql-suites/${CODEQL_LANG}-security-and-quality.qls
  from: codeql/${CODEQL_LANG}-queries
HEADER

# Add each installed third-party pack. tr+read splits the space-separated
# list portably (zsh does not word-split an unquoted $VAR in for-loops).
echo "$INSTALLED_THIRD_PARTY_PACKS" | tr ' ' '\n' | while IFS= read -r PACK; do
  [ -n "$PACK" ] || continue
  cat >> "$SUITE_FILE" << PACK_ENTRY
- queries: .
  from: ${PACK}
PACK_ENTRY
done

# Append minimal filtering rules (quoted heredoc — no expansion needed)
cat >> "$SUITE_FILE" << 'FILTERS'
- include:
    kind:
      - problem
      - path-problem
- exclude:
    deprecated: //
- exclude:
    tags contain:
      - modeleditor
      - modelgenerator
FILTERS

# Verify the suite resolves correctly
if ! codeql resolve queries "$SUITE_FILE" | wc -l; then
  echo "ERROR: Suite file failed to resolve. Check CODEQL_LANG=$CODEQL_LANG and installed packs."
fi
echo "Suite generated: $SUITE_FILE"
```

## How This Differs From Important-Only

| Aspect | Run all | Important only |
|--------|---------|----------------|
| Official pack suite | `security-and-quality` (all security + code quality) | All queries loaded, filtered by precision |
| Third-party packs | All `problem`/`path-problem` queries | Only `security`-tagged queries with precision metadata |
| Precision filter | None | high/very-high always; medium only if security-severity >= 6.0 |
| Post-analysis filter | None | Drops medium-precision results with security-severity < 6.0 |
