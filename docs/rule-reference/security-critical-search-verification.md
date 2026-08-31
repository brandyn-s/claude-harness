@rule security_critical_search_verification
@version 2026-06-09
@scope every CALLS-edge claim, every semantic-search top-1 claim, every code-localize verdict, AND every security-posture claim (fail-open/fail-closed, default allow/deny, auth-bypass) that informs a security-critical decision (auth flow, crypto path, sanitization boundary, taint flow, privilege check, secret handling, access control)

# ─── INVARIANTS (always-true) ───

INVARIANT calls_edges_have_measured_false_positive_rates
  # WHY: code-graph CALLS edges resolve via heuristic strategies (suffix_match,
  #   Full: incidents#code-graph-calls-edges-resolve-via-heuristic-strategies-suffix

INVARIANT semantic_search_top_1_is_a_hypothesis_not_a_decision
  # WHY: Voyage cosine ranks by embedding similarity. Top-1 reflects the model's
  #   Full: incidents#voyage-cosine-ranks-by-embedding-similarity-top-1-reflects

INVARIANT verification_artifact_is_file_line_with_source_excerpt
  # WHY: "verified" without a quoted source excerpt + file:line citation is
  #   Full: incidents#verified-without-a-quoted-source-excerpt-file-line-citation

INVARIANT security_posture_claim_sourced_from_runtime_decision_function
  # WHY: a fail-open/fail-closed, default-allow/deny, or auth-bypass claim
  #   Full: incidents#a-fail-open-fail-closed-default-allow-deny-or

# ─── WHAT COUNTS AS "SECURITY-CRITICAL" ───

A query / claim is security-critical when its truth value affects:
- **Authentication** — who can call this, how identity is established
- **Authorization** — what operations are permitted given an identity
- **Cryptography** — encrypt / decrypt / sign / verify / KDF / RNG paths
- **Sanitization** — input validation, output encoding, path normalization
- **Taint flow** — does untrusted input reach a sink (SQL, shell, eval, deserialize)
- **Privilege boundary** — admin vs user, root vs non-root, kernel vs userspace
- **Secret handling** — keys, tokens, passwords, certificates
- **Access control** — file ACLs, network policy, RBAC, ABAC

When uncertain, treat as security-critical. The cost of unnecessary verification
is one extra Read tool call; the cost of skipped verification is shipping a
false-positive-driven security claim.

# ─── PROCEDURE: when reading a CALLS-edge claim ───

STEP_1 inspect the edge's `r.resolution_strategy` property
  - `type_static_dispatch`, `type_dispatch`, `import_map`, `same_module`,
    `lsp_*` → high-precision strategies. Edge is reliable; verification is
    a sanity check rather than a gate.
  - `suffix_match`, `unique_name`, `fuzzy`, `self_method` → heuristic
    strategies. Edge is a HYPOTHESIS. Verification REQUIRED before action.
  - `null` → instrumentation gap. Treat as heuristic until A1's full
    propagation lands (Phase A 2026-05-10).

STEP_2 read the caller's source at the edge's caller `file_path`. Confirm
       the call site exists and resolves to the claimed target by direct
       inspection.

STEP_3 produce a verification artifact:
  - **CONFIRMED**: source explicitly calls the target (e.g.
    `validate_token(req)` matches edge `validate_request → validate_token`).
    Cite file:line + 3-5 surrounding source lines.
  - **FALSE-POSITIVE**: target name appears nowhere in the caller's source,
    or the call is to a same-named function on a different type.
  - **AMBIGUOUS**: call site exists but cannot be verified to match the
    claimed target without running the code. Common with trait dispatch,
    interface satisfaction, dynamic dispatch.

STEP_4 base the security decision on the verification artifact, NOT the
       edge alone. AMBIGUOUS edges propagate to "needs runtime confirmation"
       in the security finding.

# ─── PROCEDURE: when reading semantic-search top-K results ───

STEP_1 read top-K (K ≥ 3) — never top-1 alone for security-critical queries.

STEP_2 for each result, read the cited file at the cited line. Verify the
       result actually relates to the security concept the query targets.

STEP_3 produce verification artifacts per result (CONFIRMED / FALSE-POSITIVE
       / AMBIGUOUS). Multiple CONFIRMED hits at different sites indicate
       a real surface; one CONFIRMED amid two FALSE-POSITIVES indicates
       the model returned tangentially-related results.

STEP_4 if 0 of K results are CONFIRMED, the query phrasing missed the
       surface — re-query with framework-idiom or hypothetical-code phrasing
       (per `code-explore/SKILL.md` Step 1.5 multi-phrasing) before
       declaring "no exposure."

# ─── PROCEDURE: when reading code-localize / code_localize_agent verdicts ───

The localizer's job is to surface candidate files; the security audit's
job is to verify them. A "candidate" rank is not a verdict.

STEP_1 read the top-K (K ≥ 5) localized files at the cited lines.
STEP_2 for each, verify the security concept exists in source as claimed.
STEP_3 produce CONFIRMED / FALSE-POSITIVE / AMBIGUOUS per file.
STEP_4 act on the union of CONFIRMED files, never the localizer's top-1.

# ─── USER OVERRIDE POLICY ───
# Security-critical search verification is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="the result looks right, ship the finding":
  REFUSE. "Looks right" is not a verification artifact. Read the cited
  file at the cited line. Produce CONFIRMED / FALSE-POSITIVE / AMBIGUOUS.
  NO EXCEPTIONS for security-critical claims.

GUARD pattern="top-1 is good enough" or "the rank is high":
  REFUSE for security-critical queries. Read top-K (K ≥ 3 for search,
  K ≥ 5 for code-localize). Top-1 is a hypothesis; multiple confirmed
  hits are evidence. NO EXCEPTIONS.

GUARD pattern="this is a quick audit, no time for verification":
  REFUSE. The cost of verification is one Read tool call per cited result.
  The cost of a wrong finding is the security incident the audit was
  supposed to prevent. NO EXCEPTIONS.

GUARD pattern="the resolver_rule is fuzzy but the candidate looks plausible":
  REFUSE acting on plausibility. Fuzzy / suffix_match / unique_name edges
  have measured false-positive rates ≥40% on adversarial fixtures.
  Verify in source. NO EXCEPTIONS.

GUARD pattern="strategy is null because instrumentation gap":
  REFUSE acting on null-strategy edges as if reliable. Treat as heuristic
  until the strategy property is reliably populated (Phase A complete +
  remaining 276 minor-source nulls investigated). NO EXCEPTIONS.

GUARD pattern="the user trusts code-graph / code-search":
  EVALUATE: trust is calibrated to the precision tier. type_static_dispatch
  (0.95+ precision) earns more trust than suffix_match (0.55-0.95). For
  security decisions, the verification artifact closes the precision gap.
  NO EXCEPTIONS for sub-95% precision strategies.

GUARD pattern="this is internal code, low blast radius":
  EVALUATE: does the code touch auth / crypto / sanitization / taint /
  privilege / secrets / access control? If yes → security-critical
  regardless of "internal." If no → this rule doesn't fire.

GUARD pattern="the docstring/CLAUDE.md/comment/resource-Description says it fails open/closed" (AWS policy/SCP Description fields are prose too):
  REFUSE to assert a security posture from prose. Read the runtime decision
  function (the allow/deny branches, the except-handler return values) — or
  for cloud policies, the policy DOCUMENT's statements via describe-policy —
  and quote the branch/statement lines as the verification artifact. Prose
  drifts; the 2026-06-09 OPA "fail-open" error was a stale docstring
  contradicted by the code, and on 2026-06-12 a commercial SCP Description
  claimed "Terraform/CI-CD/Lambda" exemptions while the actual Conditions
  exempted a different role set entirely (RequireMFAForDestructive
  p-mwpdh7ph — caught only at statement level; the wrong list was briefly
  persisted to memory). NO EXCEPTIONS for fail-open/closed, default
  allow/deny, auth-bypass, or exemption-list claims.

GUARD pattern="re-query phrasing is overhead":
  REFUSE for negative findings ("no exposure") on security-critical queries.
  Multi-phrasing (per code-explore Step 1.5) catches results single-phrase
  search misses. Negative findings without multi-phrasing are 0-hit-on-
  plausible-phenomenon, which `verify-before-assuming.md` calls a detection
  bug. NO EXCEPTIONS for negative security findings.

GUARD pattern="this control is a FALSE POSITIVE — the flagged value is the current
  recommended/best-practice one" (a compliance control: Security Hub, Config, CIS,
  STIG, a linter's rule):
  REFUSE the false-positive verdict until you read the control's OWN MACHINE-READABLE
  CRITERION — `securityhub:GetSecurityControlDefinition`, the backing Config rule's
  `InputParameters`, the STIG's check-content, the lint rule's config. A compliance
  control does not grade against the vendor's PROSE; it grades against a specific
  allowlist/threshold, and those two disagree routinely.
  **"Supported" and "recommended" are different claims.** A value can appear dozens of
  times in the vendor's docs — in protocol/cipher/compatibility tables — without ONE of
  those mentions being a recommendation. Pattern-matching a modern-looking name plus a
  recent date to "current best practice" is not a source.
  REQUIRED: quote the criterion's actual accepted values, and name the DISCRIMINATOR
  that excludes yours (a token, a bound, a flag). If you cannot state the discriminator,
  you have not read the criterion. Also check the parameter is CUSTOMIZABLE before
  proposing a tune-instead-of-fix — a 0-parameter control has exactly one passing
  configuration, so "suppress with a rationale" is the only alternative to fixing it.
  NO EXCEPTIONS for a false-positive verdict that will be shipped, suppressed, or
  documented as accepted risk.
  # WHY: 2026-07-28 ELB.17 — asserted "false positive, all four listeners use
  #   Full: incidents#2026-07-28-elb-17-asserted-false-positive-all

# ─── PROCEDURE: produce a verification artifact ───

REQUIRED format (cite as a code block in the response or skill output):

```
VERDICT: <CONFIRMED | FALSE-POSITIVE | AMBIGUOUS>
QUERY: <the security-critical question>
TOOL: <code-graph CALLS / code-search semantic / code_localize / etc.>
RAW RESULT: <the edge / top-K result / localized file the tool returned>
SOURCE: <file:line>
EXCERPT:
    <3-5 lines of cited source>
RATIONALE: <why this verdict given the source>
```

The skill `/verify-search-result` (Phase D2) is the operational
implementation — when the rule says "verify," the skill produces this
artifact.

# ─── FAILURE MODES to recognise ───

FAILURE acted_on_calls_edge_without_source_verification:
  RECOVERY: open the caller's source at the cited file:line, confirm the
  call exists, produce a CONFIRMED / FALSE-POSITIVE artifact retroactively.
  If FALSE-POSITIVE, retract the security finding and document the false
  edge for the next code-graph precision-tier audit.

FAILURE acted_on_top_1_semantic_search_for_security_query:
  RECOVERY: read top-3 results, run multi-phrasing if 0 of 3 confirm,
  rebase the security finding on the CONFIRMED set.

FAILURE declared_no_exposure_from_single_phrasing_negative:
  # 0 hits on a plausible security pattern is usually a detection bug
  # per `verify-before-assuming.md`. Multi-phrasing surfaces results that
  # single-phrase search misses.
  RECOVERY: re-query with framework-idiom + hypothetical-code phrasings
  (per code-explore Step 1.5). If still 0, sample 3-5 known-positive
  candidates manually before publishing the negative finding.

FAILURE used_localize_top_1_as_authoritative:
  # The localizer surfaces candidates. Verification turns candidates into
  # verdicts. Loc-Bench Acc@1 is below Acc@10; top-1 alone misses real
  # surfaces.
  RECOVERY: read top-5, verify in source, base finding on CONFIRMED union.

FAILURE downgrade_filter_keyed_on_partial_signal_dropped_confirmed_positives:
  # INCIDENT 2026-06-22 F4 credential census: a candidate-routing scheme classed
  #   Full: incidents#2026-06-22-f4-credential-census-a-candidate-routing
  # WHY (the trap): a low aggregate confirm-rate on a candidate class ("HEX is mostly
  #   Full: incidents#the-trap-a-low-aggregate-confirm-rate-on-a
  RECOVERY: before shipping ANY downgrade/skip/low-prior filter on a recall-primary
  system, count how many CONFIRMED / true-positive items the filter key would drop.
  If >0, the key is under-specified — add the qualifier (judge-absent, no-corroborating-arm)
  that excludes the confirmed subset. A "mostly noise" class still gets the full
  precision pass on its confirmed members; downgrade means low-prior ordering, NEVER skip.

# ─── INTEGRATION WITH OTHER RULES ───

- `verify-before-assuming.md` — the general anti-pattern is "act on
  unverified tool output." This rule is the security-specific
  specialization. When a query is security-critical AND involves
  semantic search / CALLS edges, BOTH rules fire.
- `red-team-rubric-discipline.md` — when a security audit produces
  findings, the severity rubric must be explicit. CONFIRMED-with-source
  is a different severity from AMBIGUOUS-needs-runtime-confirmation.
- `subagent-tool-discipline.md` — subagent verifications must include
  the source excerpt; subagent self-reports without excerpt fail this
  rule's REQUIRED format.
- `compare-by-need.md` — recommendations from search need evidence;
  verification is the form that evidence takes for security-critical
  recommendations.

# ─── WHAT DOES NOT REQUIRE THIS RULE ───

- Non-security queries (architecture exploration, refactor planning,
  documentation lookup, performance investigation)
- Internal-team-only repo browsing where there's no decision riding
  on the result
- Read-only history queries ("what did this function look like 6 months
  ago") that don't inform a security decision
- Localizer / search results that the user explicitly asks to surface
  candidates only (no decision)

## A CI check's conclusion is not its verdict when the verdict is a job output

### 2026-08-25 — `verify-attestation / verify` published as a masking gate, then retracted

A example-labs-org PR audit reported `verify-attestation / verify` as a "masking security
gate" because it reported SUCCESS while annotating `No security attestation found.`
on all five PRs examined. That finding was wrong and had to be retracted.

Reading the source (`example-org/.github/.github/workflows/verify-attestation.yml`
@82275864) settles it:

```yaml
echo "valid=false" >> "$GITHUB_OUTPUT"
echo "::warning::No security attestation found. Developer must run ..."
exit 0
```

The job's contract is to DETERMINE attestation state and report it as an output. A
missing attestation is a valid determination, so exiting 0 is correct. The gate lives
in the consumer:

```yaml
attestation-valid: ${{ needs.verify-attestation.result == 'success'
                       && needs.verify-attestation.outputs.valid == 'true' }}
```

`auto-merge` therefore takes its documented standard path (all CI checks must pass)
instead of the attestation fast path. Nothing is masked.

**Why the wrong reading was tempting.** The same audit had just found a REAL masking
check in the same org — `baseline / Python Test` captures pytest's exit code, emits
`::warning::Tests failed`, and exits 0 unless a caller passes
`fail-on-test-failure: true` (0 of 31 repos did; 6 were masking real failures). Having
confirmed one green-with-warning check was masking, the second was pattern-matched
rather than sourced. One was a masking default; the other a two-value reporter. They
are indistinguishable from conclusion + annotation alone.

**The check.** For any CI-derived security-posture claim the decision function is the
workflow source PLUS the expression consuming its outputs. A job that emits
`outputs.*` has deliberately separated "did I run" from "what did I find"; its
conclusion answers only the first.

NOTE: this narrative lives here rather than in the ambient rule because
`rules/security-critical-search-verification.md` is one of the ten `quality_rules`
capped at 5,000 bytes by
`scripts/test_context_policy_contracts.py::test_ambient_rules_fit_measured_fixed_context_budget`,
and it sits at 4,900 B — 100 bytes of headroom. The T1 slot is full.
