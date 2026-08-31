@rule verify_before_assuming
@version 2026-08-06
@scope every capability, availability, absence, coverage, vendor-behavior, current/deployed-state, destructive-operation, recommendation-assumption, LLM-decision, and repo-target claim
@reference docs/rule-reference/verify-before-assuming.md

# VERIFY BEFORE ASSUMING — DECISION CONTRACT

Load this contract whenever a conclusion depends on what a tool, API, vendor,
configuration, repository, or deployed system can do. The full pre-compaction
procedures, examples, and incident evidence remain available on demand at
`docs/rule-reference/verify-before-assuming.md`.

## Triggers

- Claiming a tool, endpoint, feature, setting, policy, record, or capability is
  missing, unavailable, unsupported, removed, or safe to skip.
- Describing vendor behavior, vendor guidance, research findings, or what the
  current/deployed internal system does.
- Reporting a security audit, census, coverage sweep, zero result, or sampled set.
- Calling a destructive MCP operation; recommending work with hidden assumptions;
  framing an LLM as a decision-maker; pushing, opening, or merging in a repo.

## Core invariants

INVARIANT never_assume_MCP_capability_without_ToolSearch
INVARIANT unavailable_claims_require_failed_check_not_assumption
INVARIANT destructive_MCP_calls_require_pre_call_inspection
INVARIANT state_load_bearing_assumptions_alongside_recommendations
INVARIANT security_audit_scope_defaults_to_full_coverage
INVARIANT LLM_output_is_suggestion_not_decision
INVARIANT verify_repo_target_before_push_pr_merge

## Required checks

1. **Capability and absence.** Run exact discovery first: use ToolSearch with
   `select:<tool_name>` for present and old names; inspect app registrations,
   permissions, the settings schema, official docs/source, and reachable live
   surfaces as applicable. Distinguish capability, reachability, authentication,
   authorization, organization/account binding, configuration, and deployment.
   One failed endpoint or one 4xx does not decide the capability.
2. **Zero-result controls.** A plausible zero is a detector result, not proof of
   absence. Test known-positive and known-negative controls; derive search strings
   from the original source; enumerate actual status values before filtering and
   match failures positively. Remember that `grep -c` exits 1 on zero, and that
   `grep -c` over MULTIPLE files returns ONE count over concatenated input — a
   zero there is a property of the invocation, not of any file. One pattern, one
   file, per call when the answer is load-bearing.
2b. **Empty field vs absent field.** Query a field from the table that OWNS it.
   Selecting a child's field through a parent table can return an EMPTY VALUE
   rather than an error, so "no data" and "no such field" are indistinguishable
   and the failure is silent. Probe with a projection (a real field returns a KEY
   even when empty; a nonexistent one is absent from the response) before building
   any join or distribution on it. Never probe field existence with a filter — an
   unknown-field clause is often silently dropped and returns everything.
3. **Coverage.** Dynamically enumerate the live target population. Do not type a
   frozen repo/account/path list and call the output exhaustive. Default security
   audits to full coverage. Sampling requires the user's scope, documented
   first-pass design, or demonstrated rate-limit math; always label sample,
   denominator, cap, omissions, and termination condition.
3b. **Never select which subsets to inspect by NAME plausibility.** When a
   population is partitioned into named groups, categories, prefixes, or namespaces,
   enumerate the groups WITH THEIR SIZES and read the largest ones, whatever they are
   called. A group name is a label chosen by the vendor for a different purpose than
   your question, so "that one doesn't sound relevant" is not evidence about its
   contents. Report the fraction of the population actually inspected.

   INCIDENT 2026-08-12: assessing coverage of Slack's 726-entry audit-action catalog
   across 26 groups, I sampled the groups whose NAMES read as security-relevant and
   skipped `workspace_or_org`. That group holds 312 actions — 43% of the entire
   catalog — including 122 `pref.*` actions of which ZERO were covered. The
   coverage claim was reported before the largest group had been read at all.
4. **Primary evidence.** For vendor claims, use the vendor's current source or a
   direct live test; for explicit research, every dated/versioned/availability/
   pricing claim must trace to a source fetched this session. Read bodies, diffs,
   and artifacts—not titles, metadata, aggregates, summaries, or recollection.
   If unverifiable, label it unverified. Before advising on upgrade priority or
   risk, read EVERY section of the release notes, not the first one: `Added`
   describes features and reads as optional, while `Fixed`/`Security` carries the
   cross-tenant leaks, auth bypasses, and session-invalidation repairs that decide
   the recommendation. Version distance is not a proxy for diff size either —
   measure commits and changed files.
5. **Current and deployed state.** Fetch before inspecting source. Trace the actual
   entrypoint and call chain, including who consumes flags and config. Separate
   source/configured/deployed/live/measured state. For deployed claims, inspect the
   deployed artifact/runtime; a ledger, header comment, prior doc, or compaction
   summary is not current-state evidence. On resuming a multi-day task, re-read
   live state before listing remaining work: a state read from a prior day is a
   historical artifact, and ONE already-observed staleness signal — a create that
   returns "already exists", a resource whose id you did not author — invalidates
   the whole read, not just the item that produced it.
5b. **A finding is a claim about the REPO, not the copy you stand in.** Reading the
   real file proves only what your checkout holds. `git fetch` first, diagnose against
   `origin/<default>`, and say which you read. Hardest on a DEPLOYED path (`~/.claude`,
   installed package, running container): most likely to lag, least likely to look it.
   2026-08-15: 5 defects reported off a 70-commit-behind copy; 2 already fixed upstream.
6. **Configuration absence.** Search memory, then enumerate every relevant current
   and legacy file, registry hive/key family, environment scope, remote-managed
   surface, and product/app variant. When the user says it exists, treat a negative
   probe as incomplete until exhaustive evidence or a clarifying question resolves it.
7. **Destructive operations.** Read the tool implementation/docstring, resolve the
   exact target and disambiguator, and obtain confirmation when identity is name-only
   or ambiguous. Use a safe dummy only when it cannot affect real data. Afterward,
   verify the intended state directly; `success=true` is not target correctness.
7b. **A write that changes nothing proves nothing.** To establish WRITE capability
   the submitted value must DIFFER from the stored one: a same-value write can
   return success with no update stamp, no version increment, and no audit row,
   which is indistinguishable from a silently discarded write. Safety and
   discriminating power are in tension here — the inert probe is the uninformative
   one. Prefer the smallest REAL intended change on the lowest-blast-radius record,
   and get authorization for that specific write. An "inert probe" and "modify
   content then restore" are DIFFERENT acts; escalating from the first to the
   second is a new authorization, not a refinement of the old one.
8. **Recommendations and LLM outputs.** State load-bearing network, runtime, auth,
   scope, and environment assumptions beside the recommendation. Say an LLM
   "proposes", "suggests", or "drafts"; require structured evidence and a human or
   gated system to decide. Auto-apply needs measured accuracy proportionate to blast
   radius.
9. **Repo targeting.** Immediately before push/PR/merge, run `pwd` and inspect
   remotes; verify the intended org/repo and explicit repo list. Prior checks and
   session memory are not current evidence.
10. **Manual findings.** "No automated check" does not mean unverifiable. Read the
    cited source or run a safe read-only probe and classify CONFIRMED,
    FALSE-POSITIVE, or AMBIGUOUS; only ambiguity after inspection goes to a human.

## Forbidden shortcuts

- "0 hits means absent", "the obvious location was empty", or "the deferred-tools
  reminder is the complete surface".
- A title, `diff --stat`, author, filename, module header, memory entry, prior report,
  paraphrase, or self-authored transcription used as proof of underlying content.
- A fixed discovery list, prefix sample, capped response, or killed loop reported as
  a census/all-clear without completeness evidence.
- Vendor or research assertions from training knowledge when a current primary source
  is available; internal behavior claims from stale source or prose.
- Declaring a capability unavailable from one endpoint, status code, org-bound key,
  product mode, or untested skip condition.
- Trying a destructive call on the real target as a dry run, or resolving an ambiguous
  short instruction toward a destructive option without asking.
- "The LLM decides/verifies/ensures" without measured accuracy and an external gate.
- "Checked yesterday" or "I know the repo" before a repository write.
- Reporting a mechanism, verdict, or severity at the confidence of the FIRST read
  when a confirming probe costs one call.

GUARD pattern="the mechanism is obvious from what I just read" or "this is clearly
unresolvable / clearly abandoned / clearly a no-op":
  RUN THE ONE-CALL PROBE BEFORE THE CLAIM LEAVES. Name the cheapest observation
  that would REFUTE the reading, run it, then report. Fails in BOTH directions,
  which look nothing alike, so neither warns you about the other. NO EXCEPTIONS
  for a verdict that reaches the user. Both 2026-08-15 instances (an asserted
  unresolvable fixpoint that was an ordered computation; a dismissed vendor fork
  whose diff was also a major upgrade): docs/rule-reference/verify-before-assuming.md

When a specialized case is not resolved by this contract, load the archived reference;
do not recreate its incident narrative in the always-loaded rule.
