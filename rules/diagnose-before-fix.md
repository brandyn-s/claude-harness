@rule diagnose_before_fix
@version 2026-08-06
@scope every failure, regression, slowness complaint, API/service/auth error, reported user problem, recommendation derived from prior observations, and bug fix
@reference docs/rule-reference/diagnose-before-fix.md

# DIAGNOSE BEFORE FIX — DECISION CONTRACT

Diagnose from the failing evidence and a discriminating comparison before changing
anything. Full domain playbooks and incident evidence remain available on demand at
`docs/rule-reference/diagnose-before-fix.md`.

## Triggers

- Any error, red CI/apply signal, regression, outage, access verdict, latency or
  "wedged" claim, unexpected result, or problem the user says persists.
- Any edit intended to fix a bug, mechanism claim in a shipped artifact, coverage
  claim, conflicting documentation, or reliance on a distilled observation.

## Core invariants

INVARIANT read_the_actual_error_first_never_guess
INVARIANT file_must_be_read_before_editing
INVARIANT distilled_rules_are_observations_not_facts
INVARIANT measured_impact_under_expected_has_second_bug
INVARIANT docs_consensus_is_not_evidence_source_code_is

## Required checks

1. **Read the real failure first.** Read the complete error body, logs, traceback,
   failed CI step, apply log, service events/task stop reason, and relevant source.
   A status code or step name is only a category. For HTTP errors, identify which
   gate fired (routing, schema, authn, authz, business logic); use a schema-valid
   probe before drawing a permission conclusion.
2. **Recall before rediscovery, and before ESCALATION.** For cloud infrastructure,
   auth/permission errors, and network posture/reachability, run
   `memory_search(component + symptom)` before deep debugging. Treat memory/distilled
   rules as hypotheses to verify against the current API, source, IaC, and live
   state—not as facts.
   Recall is also required before you declare a blocker, request elevated access or a
   new role, or hand the task back. Escalation FEELS like the end of debugging, so the
   recall step gets skipped exactly when it is most valuable: the prior art usually
   names the missing step, and asking the operator for privileges you do not need is
   the most expensive way to discover that. GUARD pattern="I've exhausted the levers,
   I need an admin role" or "this is blocked pending access": run
   `memory_search(component + symptom)` FIRST and say what it returned. NO EXCEPTIONS.
   INCIDENT 2026-08-14: escalated for an admin role in a GovCloud account to reach an
   untried Bedrock lever. The operator replied "we've done this before for other
   accounts"; the memory search that comment triggered returned a topic file naming the
   exact missing step (the entitlement does not auto-propagate cross-partition and must
   be created explicitly). The recall cost one tool call and would have avoided the
   escalation entirely.
3. **Compare with a working baseline.** Locate last-good logs/config/run/transcript.
   Test every suspected anomaly against it and diff event sequences; present in both
   means background, while the missing next event may be the signal. Before suggesting
   restart/retry, verify the record has not already shown it ineffective.
4. **Use the shortest discriminator.** Version regression: confirm good, then bisect.
   Slowness: time direct requests at real batch sizes and ramp them. Config-says-allow
   but traffic rejects: use the platform path analyzer. Same config/different instance:
   compare each instance's input telemetry. Threshold failure: read the last green
   metric and compare equivalent pipelines, not just verdicts. REFUTING one hypothesis
   does not IDENTIFY the cause: a control can block for INDEPENDENT reasons, and the
   first one you disprove hides the rest. Measured 2026-08-26 -- a WAF 403 on an upload:
   "too big" was refuted by a 141-byte probe, then "markup only" was refuted by a
   20,000-byte plain-text probe. BOTH rules were live (XSS-any-size AND an 8192-byte
   cap), so the obvious fix for the second, base64, would have shipped and still 403'd.
   Vary each axis independently to EXHAUSTION before designing the fix, and pin the
   threshold (8000 passed, 8192 blocked) rather than inferring it.
5. **Classify runtime state.** A long batch is not wedged until process liveness, CPU,
   write delta over at least one full batch period, and network I/O agree. A platform
   classifier/model outage is not a command bug: stop identical retries, try one
   genuinely different safe path, then report the service block.
6. **Read before edit and before build.** Read the current file, actual failing test,
   local type/contract, official platform data, and existing implementation. Inspect
   what the platform already provides before building custom computation. Avoid
   interactive/login probes that create user-visible side effects; use non-interactive
   status/help/artifact checks.
7. **Prove the mechanism.** A diagnostic-derived PR/report/issue must cite source
   file:line for the claimed mechanism and distinguish hypothesis from evidence.
   Compile/check the deployed artifact and inspect live runtime state; grep alone cannot
   prove correctness, deployment, or operation.
   For a value resolved through a FALLBACK CHAIN (`a ?? b ?? default`), fixing the
   producer of one source is not the mechanism proof: grep who SETS every
   earlier-precedence source in the failing path and confirm your fixed value is
   actually consumed there. Measured 2026-08-24: a gateway /v1/models fix shipped
   through a full protected release while LibreChat's hardcoded FetchTokenConfig
   enum gated the fetched value off for this endpoint — the 32K-default symptom
   reproduced unchanged and a second release (static config, the branch that
   bypasses the gate) was required.
8. **Measure expected versus observed.** Compute the expected improvement. If observed
   impact is below `0.3 × expected`, continue end-to-end profiling for a compounding
   bug; "better than before" is not the expected fix.
9. **Hunt variants.** After fixing an anti-pattern, grep the whole repo for textual
   instances and fix or justify each. For a semantic invariant, use an exhaustive/
   property test over the finite state space and mutation-verify it; grep is not a
   semantic variant hunt. Apply the same distinctive-token search to copied prose.
10. **Coverage and conflicting claims.** Every coverage cell needs a specific primary
    source or live test, including empirical checks of every claimed-absent data source.
    When docs disagree, trace the code/config that physically interacts with the entity.
    Existence alone is insufficient: verify the operation is applyable under real IAM,
    environment, and side-effect constraints.
11. **Respect reported reality and method.** If the user reports persistence, a failed
    fix, or two or more affected entities, collect the same diagnostics for each and
    reopen the root cause; do not dismiss the report from one entity's data. Follow
    explicitly requested individual/no-batch methodology and the topic actually asked.

## Forbidden shortcuts

- "Probably/must be X", analogy-first fixing, or any proposed fix before reading the
  actual error and current source.
- Calling a red signal transient/pre-existing/unrelated without reading its log now.
- Attributing a post-edit diagnostics/lint signal to your own change without opening the
  cited line — your insertions SHIFT line numbers, so untouched pre-existing findings
  re-report as "new". Inverse of the line above; both are fixed by reading the cited line.
  (`incidents#2026-08-18-new-diagnostics-line-shift`.)
- Diagnosing from a status code without its body and gate, from a plan instead of apply
  output, or from one failing state without a last-good comparison.
- Calling an ASYNCHRONOUS mechanism broken without measuring ITS OWN latency from its
  history and waiting past it — absence in your window is a property of the window, and
  the baseline is usually in the response you already fetched.
  (`incidents#2026-08-27-autosync-declared-dead-in-2-minutes`.)
- Recommending restart/redeploy/retry already shown ineffective; retrying an identical
  platform-outage call more than twice.
- Blaming rate limits, a hook, a missing component, or an instance before direct probes
  establish a plausible mechanism.
- Editing from memory; building a platform feature before inspecting supplied data;
  shipping a source-only or doc-consensus mechanism claim.
- Stopping at a partial performance gain far below expectation.
- Fixing one textual site while variants remain, or using grep as proof that a semantic
  invariant holds.
- Declaring a persistent/multi-user problem "fine", "working as intended", or a red
  herring without systemic evidence.
- Reporting a cloud permission/capability verdict without the recall and current-state
  checks merely because no fix was requested.

- Forming a third hypothesis about a collapsed error path instead of emitting the FIELD
  that splits it (`error_type`, the failing assertion, the resolved target). Measured
  2026-08-29: 4 hours and 3 wrong fixes on one flat string; one `error_type` field named
  the cause on the next run. Relatedly, a probe that passes while the real lane fails,
  unchanged by fixes, IS the finding — diff the two call paths for their first difference
  (origin, region, account, identity, base revision) before theorising further about the
  subject. (`incidents#2026-08-29-emit-the-discriminator`.)

Load the archived reference when a domain-specific playbook is needed; do not return its
incident narratives to the always-loaded contract.
