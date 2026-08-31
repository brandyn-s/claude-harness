@rule security_critical_search_verification
@version 2026-06-09
@scope every CALLS-edge claim, every semantic-search top-1 claim, every code-localize verdict, AND every security-posture claim (fail-open/fail-closed, default allow/deny, auth-bypass) that informs a security-critical decision (auth flow, crypto path, sanitization boundary, taint flow, privilege check, secret handling, access control)

# Full rationale and incidents: `docs/rule-reference/security-critical-search-verification.md`.

INVARIANT calls_edges_have_measured_false_positive_rates
INVARIANT semantic_search_top_1_is_a_hypothesis_not_a_decision
INVARIANT verification_artifact_is_file_line_with_source_excerpt
INVARIANT security_posture_claim_sourced_from_runtime_decision_function

Security-critical means a claim affecting authentication, authorization, crypto,
sanitization, taint-to-sink flow, privilege boundaries, secrets, or access control.
When uncertain, apply this rule.

# CALLS edges
STEP_1 inspect `r.resolution_strategy`.
- `type_static_dispatch`, `type_dispatch`, `import_map`, `same_module`, `lsp_*`:
  high precision; source inspection is a sanity check.
- `suffix_match`, `unique_name`, `fuzzy`, `self_method`, or null: hypothesis only;
  source verification is a gate.
STEP_2 read the caller at its cited file/line and resolve the actual target.
STEP_3 classify CONFIRMED, FALSE-POSITIVE, or AMBIGUOUS. Ambiguity becomes
"needs runtime confirmation," never an established finding.

# Semantic search and localization
- Semantic security search: read top-K with K>=3, verify each cited location, and
  decide from confirmed results—not top-1.
- `code_localize`/agent: read top-K with K>=5; candidates are not verdicts.
- If 0 of K confirms a plausible surface, re-query using framework-idiom and
  hypothetical-code phrasings before publishing "no exposure."
- A recall-primary downgrade/skip filter must count confirmed items it would drop.
  If any confirmed item is lost, add the missing qualifier; low prior changes order,
  never eliminates the verification pass.

# Security-posture and compliance claims
Read and quote the runtime decision branch, policy statements, exception return, or
machine-readable control definition. Docstrings, comments, resource descriptions,
vendor prose, and A PROGRAM'S OWN RUNTIME LOG OUTPUT cannot establish fail-open/closed,
allow/deny, exemptions, or control compliance. Log output is the most dangerous of
these because the program EMITS it, so it reads as authoritative while still being a
rendering written by someone who was summarising, not specifying — and a summary
compresses exactly the qualifiers a posture claim turns on. For a claimed false positive, quote accepted values/thresholds and name
the discriminator excluding the flagged value; check whether the control is tunable.
"Supported" is not "recommended." Untested exploitability remains AMBIGUOUS.

# Required artifact
```text
VERDICT: <CONFIRMED | FALSE-POSITIVE | AMBIGUOUS>
QUERY: <security-critical question>
TOOL: <CALLS | semantic search | code_localize | other>
RAW RESULT: <edge or candidate>
SOURCE: <file:line>
EXCERPT:
    <3-5 lines of source>
RATIONALE: <why the source supports the verdict>
```
Use `/verify-search-result` when available.

# Hard guards
GUARD pattern="the result looks right, ship the finding":
  REFUSE. Produce the source artifact. NO EXCEPTIONS.
GUARD pattern="top-1 is good enough" or "the rank is high":
  REFUSE. Read K>=3 search results or K>=5 localized files.
GUARD pattern="fuzzy/null edge is plausible":
  REFUSE plausibility as proof; verify the caller source.
GUARD pattern="quick audit, no time to verify":
  REFUSE for security-critical decisions.
GUARD pattern="docstring/description says fail open/closed":
  REFUSE prose; read the effective decision function or policy document.
GUARD pattern="the job log already says what this control does":
  REFUSE. A log line is a rendering, not the branch. Open the emitting source and
  read the condition that GATES the action before publishing a risk claim.
  # 2026-08-18: a regulated-data access gate logged `CUI_SWFDE: non_completers=2 (report-only,
  # grace N/A)`. I read "grace N/A" as "no grace protection -> removal is imminent"
  # and warned the operator that enabling a flag would strip 2 people's GHES +
  # GovCloud access. The source said the opposite: sub-group removals are hard-blocked
  # independent of that flag, and "grace N/A" meant the grace window is irrelevant
  # BECAUSE no removal happens. Same log line, inverted meaning. Reading the one
  # `elif remove_stale:` branch settled it in under a minute.
GUARD pattern="zero hits means no exposure":
  REFUSE until multi-phrasing and known-positive coverage checks complete.

# Exclusions
Candidate-only lists explicitly labeled unverified, non-security exploration, and
read-only history with no security decision may omit this artifact.
