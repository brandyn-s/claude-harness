---
name: variant-analysis
description: "Hunt similar vulnerabilities and bug variants across codebases via pattern analysis."
when_to_use: "Find similar vulnerabilities and bugs across codebases using pattern-based analysis. Use when hunting bug variants, building CodeQL/Semgrep queries, analyzing security vulnerabilities, or performing systematic code audits after finding an initial issue. Do NOT use for initial vulnerability discovery (use /semgrep or /codeql), false positive triage (use /fp-check), or general code review (use /differential-review)."
effort: high
argument-hint: "[vulnerability-pattern or CVE to find variants of]"
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Bash Read Grep Glob AskUserQuestion
---

# Variant Analysis

You are a variant analysis expert. Your role is to help find similar vulnerabilities and bugs across a codebase after identifying an initial pattern.


> **Runtime policy:** Resolve the effective model and preserve refusal/fallback provenance per `../_shared/model-runtime-policy.md`.

## When to Use

Use this skill when:
- A vulnerability has been found and you need to search for similar instances
- Building or refining CodeQL/Semgrep queries for security patterns
- Performing systematic code audits after an initial issue discovery
- Hunting for bug variants across a codebase
- Analyzing how a single root cause manifests in different code paths

## When NOT to Use

Do NOT use this skill for:
- Initial vulnerability discovery (use /semgrep or /codeql — same guidance as the frontmatter)
- General code review without a known pattern to search for
- Writing fix recommendations (use /pr-fix instead)
- Understanding unfamiliar code (use /code-explore or /codebase-memory-exploring for deep comprehension first)

## The Five-Step Process

### Step 1: Understand the Original Issue

Before searching, deeply understand the known bug:
- **What is the root cause?** Not the symptom, but WHY it's vulnerable
- **What conditions are required?** Control flow, data flow, state
- **What makes it exploitable?** User control, missing validation, etc.

### Step 2: Create an Exact Match

Start with a pattern that matches ONLY the known instance:
```bash
rg -n "exact_vulnerable_code_here"
```
Verify: Does it match exactly ONE location (the original)?

### Step 3: Identify Abstraction Points

| Element | Keep Specific | Can Abstract |
|---------|---------------|--------------|
| Function name | If unique to bug | If pattern applies to family |
| Variable names | Never | Always use metavariables |
| Literal values | If value matters | If any value triggers bug |
| Arguments | If position matters | Use `...` wildcards |

### Step 4: Iteratively Generalize

**Change ONE element at a time:**
1. Run the pattern
2. Review ALL new matches
3. Classify: true positive or false positive?
4. If FP rate acceptable, generalize next element
5. If FP rate too high, revert and try different abstraction

**Stop when false positive rate exceeds ~50%**

### Step 5: Analyze and Triage Results

For each match, document:
- **Location**: File, line, function
- **Confidence**: High/Medium/Low
- **Exploitability**: Reachable? Controllable inputs?
- **Priority**: Based on impact and exploitability

For deeper strategic guidance, see [METHODOLOGY.md](METHODOLOGY.md).

## Deterministic verification (harness)

This skill ships an oracle. After Step 5 (Analyze and Triage), encode the
hunt as a `hunt-spec.json` (`hunt_id`, `root_cause`, `seed_file`,
`seed_line`, per-level `patterns[]` — each pattern carrying `sampled_fp`,
the count of false positives found when you triaged its matches in
Step 5 — and optional `fp_rate_cap`) and run:

```bash
python3 scripts/verify_variants.py hunt.json --target . --ndjson run.ndjson --strict
python3 scripts/hunt_history.py append run.ndjson --root-cause "<short label>"
```

The Tier-1 oracle (`exact_baseline`) gates that Level-0 still matches
the seed; the Tier-2 oracle (`variant_run` via `rg`, falling back to
`grep -rnE` when ripgrep is absent, or `semgrep`)
deterministically returns match counts; the FP gate enforces the 50%
cap from `METHODOLOGY.md` — under `--strict`, every pattern with one
or more matches must carry `sampled_fp`, else the gate reports
UNVERIFIED and the run exits 1. See
[references/harness-pattern.md](references/harness-pattern.md) for the
eight-component map; the script is the verifier of record, not the
prose Success Criteria.

## Tool Selection

| Scenario | Tool | Why |
|----------|------|-----|
| Quick surface search | ripgrep | Fast, zero setup |
| Simple pattern matching | Semgrep | Easy syntax, no build needed |
| Data flow tracking | Semgrep taint / CodeQL | Follows values across functions |
| Cross-function analysis | CodeQL | Best interprocedural analysis |
| Non-building code | Semgrep | Works on incomplete code |

## Key Principles

1. **Root cause first**: Understand WHY before searching for WHERE
2. **Start specific**: First pattern should match exactly the known bug
3. **One change at a time**: Generalize incrementally, verify after each change
4. **Know when to stop**: 50%+ FP rate means you've gone too generic
5. **Search everywhere**: Always search the ENTIRE codebase, not just the module where the bug was found
6. **Expand vulnerability classes**: One root cause often has multiple manifestations

## Critical Pitfalls to Avoid

These common mistakes cause analysts to miss real vulnerabilities:

### 1. Narrow Search Scope

Searching only the module where the original bug was found misses variants in other locations.

**Example:** Bug found in `api/handlers/` → only searching that directory → missing variant in `utils/auth.py`

**Mitigation:** Always run searches against the entire codebase root directory.

### 2. Pattern Too Specific

Using only the exact attribute/function from the original bug misses variants using related constructs.

**Example:** Bug uses `isAuthenticated` check → only searching for that exact term → missing bugs using related properties like `isActive`, `isAdmin`, `isVerified`

**Mitigation:** Enumerate ALL semantically related attributes/functions for the bug class.

### 3. Single Vulnerability Class

Focusing on only one manifestation of the root cause misses other ways the same logic error appears.

**Example:** Original bug is "return allow when condition is false" → only searching that pattern → missing:
- Null equality bypasses (`null == null` evaluates to true)
- Documentation/code mismatches (function does opposite of what docs claim)
- Inverted conditional logic (wrong branch taken)

**Mitigation:** List all possible manifestations of the root cause before searching.

### 4. Missing Edge Cases

Testing patterns only with "normal" scenarios misses vulnerabilities triggered by edge cases.

**Example:** Testing auth checks only with valid users → missing bypass when `userId = null` matches `resourceOwnerId = null`

**Mitigation:** Test with: unauthenticated users, null/undefined values, empty collections, and boundary conditions.

## Resources

Ready-to-use templates in `resources/`:

**CodeQL** (`resources/codeql/`):
- `python.ql`, `javascript.ql`, `java.ql`, `go.ql`, `cpp.ql`

**Semgrep** (`resources/semgrep/`):
- `python.yaml`, `javascript.yaml`, `java.yaml`, `go.yaml`, `cpp.yaml`

**Report**: `resources/variant-report-template.md`
## Examples

**Example 1: Post-detection variant hunt**
User says: "/variant-analysis" after finding a SQL injection in `api/users.py`
Actions: Understand the root cause pattern (unsanitized input reaching query builder), create exact-match query, identify abstraction points (other query builders, other input sources), generalize iteratively, analyze all matches.
Result: Variant report with N additional instances of the same root cause pattern.

**Example 2: CodeQL-based variant search**
User says: "find variants of this XSS pattern across the frontend"
Actions: Understand the vulnerable pattern, write a CodeQL query targeting the specific data flow, run against the codebase, rank results by confidence.
Result: Prioritized list of potential XSS variants with data flow evidence.
## Success Criteria

- Root cause understood before generalizing — not just the symptom pattern
- Abstraction points identified incrementally (don't over-generalize in one step)
- Each variant confirmed by reading the actual code, not just matching a pattern
- Report distinguishes confirmed variants from potential variants requiring manual review
