---
name: verify-search-result
description: "Verify a CALLS-edge or search result before a security-critical decision (CONFIRMED/FP/AMBIGUOUS)."
when_to_use: "Use when a CALLS-edge claim, semantic-search top-K result, or code-localize verdict needs verification before informing a security-critical decision (auth / crypto / sanitization / taint flow / privilege boundary / secrets / access control). Reads the cited source, produces a CONFIRMED / FALSE-POSITIVE / AMBIGUOUS verdict artifact with file:line + source excerpt + rationale. Trigger phrases: \"verify this CALLS edge\", \"verify search result\", \"is this match real\", \"confirm this match\", \"audit this finding\". Do NOT use for non-security queries (architecture exploration, refactor planning) — the verification overhead isn't justified outside the security bar."
argument-hint: "[query] [claim from search]"
effort: low
allowed-tools: Read Grep Glob Bash AskUserQuestion mcp__codebase-memory-mcp__get_code_snippet
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires the codebase-memory-mcp server for the result being verified. The Read tool alone suffices if the user pasted the file:line directly.
  requires:
    - mcp: codebase-memory-mcp

---

## verify-search-result

# Verify Search Result — Source-Grounded Verdict for Security-Critical Claims

A CALLS edge or semantic-search hit is a **hypothesis**. This skill turns
hypotheses into **verdicts** by reading the cited source and producing a
structured artifact the security finding can rest on.

Companion to `rules/security-critical-search-verification.md` — when the
rule says "verify," this skill produces the artifact.

---

## When to invoke

Invoke when:
- A CALLS edge claim informs a security decision (e.g.
  "`validate_request → check_csrf` is the only CSRF entrypoint")
- A semantic-search top-K result is about to be cited as evidence in a
  security audit
- A `code_localize` / `code_localize_agent` verdict will drive a finding
- ANY tool result is being read as authoritative for an auth / crypto /
  sanitization / taint / privilege / secrets / access-control claim

Do NOT invoke for:
- Architecture exploration (`/code-explore` is the right tool)
- Refactor planning (different precision bar)
- Localization with no security stakes
- Read-only history queries

---

## Inputs

The skill expects the caller to provide:
1. The **query** that produced the result — what security question is
   being asked
2. The **raw result** — the CALLS edge, semantic hit, or localize verdict
3. Optionally the **tool name** that produced it (defaults to whatever
   the result format implies)

If the caller is the main session, these come from prior tool calls in
the same conversation. If the caller is a subagent, they MUST be
passed explicitly via the dispatch prompt.

---

## Workflow

### Step 1: Parse the result into (file_path, line, claim)

For CALLS edges: extract the caller's `file_path` + line range from
`a.file_path` + `a.start_line` / `a.end_line` properties (or the
get_code_snippet metadata).

For semantic-search hits: the result already carries `file_path`,
`start_line`, `end_line`, and the matched chunk text.

For code-localize: each ranked file carries the path; the line of
relevance is in the rationale or must be derived from the security
concept (grep within the file).

### Step 2: Read the source

Use Read with offset / limit targeting the cited line range +5 lines of
surrounding context. NEVER cite a line you did not read. Per
`subagent-tool-discipline.md` invariant
`subagent_must_complete_reads_before_citing_specific_lines`: if Read
returns truncated or partial output for the cited range, re-Read with
larger offset/limit until the cited region is in the read window.

### Step 3: Verify the claim against the source

For CALLS edges (`caller -> target`):
- Does the source at the caller's lines contain a call to the target?
- Is the call shape consistent with the resolution_strategy on the edge?
  - `import_map` / `same_module` / `type_static_dispatch` → expect
    explicit named call
  - `suffix_match` / `unique_name` / `fuzzy` → may be on a different
    type with the same method name; check the receiver type at the
    call site

For semantic-search hits:
- Does the chunk text actually relate to the security concept the query
  asked about, or did the model match on tangential vocabulary?
- Are the surrounding lines consistent with the chunk's framing (e.g.
  "JWT validation" chunk inside a comment vs. inside an actual
  implementation)?

For code-localize verdicts:
- Does the file contain the security concept the query targets?
  Grep the file for the core terms; confirm hits are functional code,
  not comments / strings / dead code.

### Step 4: Produce the verdict artifact

Print the verdict in the exact format the rule requires:

```
VERDICT: <CONFIRMED | FALSE-POSITIVE | AMBIGUOUS>
QUERY: <the security-critical question>
TOOL: <code-graph CALLS / code-search semantic / code_localize / etc.>
RAW RESULT: <the edge / top-K result / localized file the tool returned>
SOURCE: <file:line>
EXCERPT:
    <3-5 lines of cited source — quoted verbatim>
RATIONALE: <why this verdict given the source>
```

### Verdict definitions

- **CONFIRMED**: source explicitly contains the claim. The call exists,
  the security concept is implemented in the cited lines, the match is
  functional code (not a comment / docstring / unreachable branch).
- **FALSE-POSITIVE**: the claimed concept is not in the source. The
  call doesn't exist at the cited line, the concept is only in a
  comment, the result is on a different file with a coincidentally
  similar name.
- **AMBIGUOUS**: the cited source has the claim's vocabulary but the
  truth requires runtime confirmation. Common with trait dispatch,
  interface satisfaction, dynamic dispatch, conditional code paths.
  AMBIGUOUS verdicts MUST surface "needs runtime confirmation" in the
  downstream finding — they are NOT a soft CONFIRMED.

### Step 5: When to multi-verify

If verifying a single result is not sufficient (e.g. a security audit
needs to enumerate all CSRF entrypoints), the caller should invoke
this skill once per result. Each invocation produces one artifact;
the audit aggregates artifacts.

If verifying top-K semantic-search results, the skill expects the
caller to either:
- pass each result individually, OR
- pass them as a batch (the skill produces K verdicts, one per result)

The rule's NO EXCEPTIONS policy on K ≥ 3 (search) / K ≥ 5 (localize)
is the caller's responsibility to satisfy — this skill verifies what
it's given.

---

## Examples

### Example 1: CALLS-edge claim

User pastes: "code-graph CALLS edge: `auth.middleware.authorize_request`
calls `auth.middleware.validate_token` (resolution_strategy: suffix_match,
confidence: 0.55)."

Actions:
1. Read `auth/middleware.rs` at the caller's lines (e.g. 42-58)
2. Grep for `validate_token` in the function body
3. Inspect the call shape — is the receiver `self`? a different module?
4. Produce verdict

```
VERDICT: AMBIGUOUS
QUERY: Does authorize_request validate the request's token?
TOOL: code-graph CALLS edge
RAW RESULT: auth.middleware.authorize_request -> auth.middleware.validate_token
            (suffix_match, 0.55)
SOURCE: src/auth/middleware.rs:48
EXCERPT:
    pub fn authorize_request(req: &Request) -> Result<Identity> {
        let token = extract_bearer(req)?;
        let claims = self.validator.validate_token(&token)?;
        Ok(Identity::from_claims(claims))
    }
RATIONALE: The call exists but resolves through `self.validator`, not the
    free function `validate_token`. The CALLS edge's suffix_match strategy
    matched on the bare name and may have linked to the wrong target.
    Needs confirmation that `self.validator: TokenValidator::validate_token`
    is the true callee. Recommend re-running with type_dispatch strategy
    or reading the validator's class.
```

### Example 2: semantic-search result

User pastes top-1 result of "input sanitization in user-facing endpoints":
`src/web/handlers.rs:120-145` chunk about `parse_query_params`.

Actions:
1. Read `src/web/handlers.rs:115-150`
2. Verify the function actually sanitizes input (not just parses)
3. Produce verdict

```
VERDICT: FALSE-POSITIVE
QUERY: What input sanitization runs on user-facing endpoints?
TOOL: code-search semantic top-1
RAW RESULT: src/web/handlers.rs:120-145 (parse_query_params chunk)
SOURCE: src/web/handlers.rs:120-145
EXCERPT:
    fn parse_query_params(uri: &Uri) -> Result<QueryParams> {
        let raw = uri.query().unwrap_or("");
        let pairs = url::form_urlencoded::parse(raw.as_bytes());
        Ok(QueryParams { pairs: pairs.collect() })
    }
RATIONALE: The chunk parses query strings but performs no input
    sanitization (no length limits, no character filtering, no
    canonicalization). The semantic search matched on the vocabulary
    "parse" + "user-facing endpoint" but the function's actual behavior
    is parsing-only. Re-query needed with terms like "validate", "sanitize",
    "encode" to surface the real sanitization layer (which may not exist).
```

### Example 3: localize verdict

User pastes: "code_localize_agent ranked these top 5 for query 'where is
admin role checked': handlers/admin.rs (0.92), services/auth.rs (0.78),
db/users.rs (0.61), middleware/rbac.rs (0.55), config/policies.toml (0.42)."

Actions per file (or batched):
1. Read each file, grep for "admin" / "role" / "rbac"
2. Confirm functional admin-check vs. ambient mention
3. Produce 5 verdicts

(Output: 5 verdict blocks, one per file.)

---

## Success Criteria

- Every verdict cites file:line WITH source excerpt (3-5 verbatim lines)
- AMBIGUOUS verdicts are not silently upgraded to CONFIRMED
- FALSE-POSITIVE verdicts include the reason (vocabulary match vs.
  functional match, wrong receiver type, etc.)
- The skill never produces a verdict without reading the cited source
  in this invocation (no "remembered from prior session" verdicts)
- Multi-result audits produce one verdict per result; aggregation is
  the caller's job

## What this skill does NOT do

- Does NOT decide the security finding's severity (that's the caller's
  judgment given the artifact)
- Does NOT run the code (verification is static; AMBIGUOUS verdicts
  surface when runtime confirmation is required)
- Does NOT re-query the search tool (it operates on what the caller
  provides; multi-phrasing is the caller's responsibility per
  `code-explore/SKILL.md` Step 1.5)
- Does NOT validate the broader audit's coverage (per
  `verify-before-assuming.md` `INVARIANT security_audit_scope_defaults_to_full_coverage`,
  scope discipline is the audit's responsibility)

## References

- `rules/security-critical-search-verification.md` — the discipline this
  skill operationalizes
- `rules/verify-before-assuming.md` — the general "tool output is not
  evidence" rule this specializes
- `skills/_shared/subagent-tool-discipline.md` — subagent reads must complete
  before citing specific lines
- `skills/code-explore/SKILL.md` Step 1.5 — multi-phrasing for negative
  findings
