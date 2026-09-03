@rule diagnose_before_fix
@version 2026-06-10
@scope every failure, every "slow" complaint, every API/service error reported by user, every recommendation based on distilled rule, every edit

# Pointer shorthand: "Full: incidents#anchor" = rules/incidents/diagnose-before-fix.md
# (full incident narratives + per-FAILURE citations live there).

# ─── INVARIANTS (always-true) ───

INVARIANT read_the_actual_error_first_never_guess
  # WHY: a 503 or failure is ambiguous. Guessing costs 20+ min per wrong
  #      guess (write PR, wait CI, wait apply). Logs have the answer.

INVARIANT file_must_be_read_before_editing
  # WHY: editing from memory causes "string not found" errors. Reading
  #      is cheap; re-edits cost turns.

INVARIANT distilled_rules_are_observations_not_facts
  # WHY: distill captures what was OBSERVED. External API behavior may have
  #      changed. Verify with gh api / aws / relevant CLI before acting.

INVARIANT measured_impact_under_expected_has_second_bug
  # WHY: if fix expected 100× and observed 3×, there's a compounding bug
  #      upstream or downstream. Don't accept "better than before" and stop.

INVARIANT docs_consensus_is_not_evidence_source_code_is
  # WHY: multiple docs may share the same original error. Source code
  #      physically interacts with the entity in question.

# ─── PROCEDURE: failure diagnosis by type ───

ON ecs_failure:
  STEP_1 aws ecs describe-services (read events)
  STEP_2 aws ecs describe-tasks (read stopReason)
  FORBIDDEN: propose fix before reading both.

ON terraform_failure:
  STEP_1 read apply log error lines (not plan)
  FORBIDDEN: infer from plan output.

ON cloud_infrastructure_debug (AWS: CloudFront, ALB, ECS, Lambda, KMS, S3, OAC,
   Bedrock model-access/AccessDenied, SCP denials. AZURE/M365: Automation runbooks
   + schedules + variables, Entra dynamic-group rules, Graph, SCIM/GovSlack — ANY
   cloud access/permission/behaviour error counts as a "failure mode", not just
   broken infra. NOT AWS-only: a runbook-status or Entra investigation is the same
   recall problem, and scoping this to AWS is why it did not fire on 2026-07-28;
   AND any claim about OUR OWN network POSTURE/REACHABILITY — "is X public?",
   "is that behind the VPN?", "which path serves this hostname?" — even when
   NOTHING has errored):
  STEP_1 memory_search the failure mode (component + symptom) BEFORE deep debugging:
         mcp__memory-search__memory_search(query="<component> <error/symptom>", limit=5)
  STEP_2 IF a topic file documents this exact failure mode → use the documented fix.
         30 seconds of search vs hours of rediscovery.
  STEP_3 IF no memory hit → normal debug, then /distill the finding to a topic file.
  STEP_4 IF the symptom is "config says ALLOW but traffic is DROPPED" (reachable-on-paper
         but client times out; SG/NACL/route/EIP all read allow; flow log shows the SYN
         reaching the ENI then REJECT) → run VPC Reachability Analyzer FIRST, before
         reading individual layers again. It models the WHOLE configured path (incl.
         layers `describe-security-groups` etc. do NOT expose, like VPC Block Public
         Access) and names the blocking component + ExplanationCode in one call.
         `create-network-insights-path --source <igw> --destination <eni> --protocol tcp
         --filter-at-source` (GovCloud: dest type `loadbalancer` is unsupported — use the
         ALB's `network-interface`; `instance`/`internet-gateway`/`vpc-endpoint` also valid).
  STEP_5 IF the question is POSTURE/REACHABILITY rather than a failure, the PRIMARY
         surface is the IaC + the infra repo's own CLAUDE.md — grep `*.tf` for
         `internal =`, read apigateway.tf / cloudfront.tf / waf.tf, and read the repo
         doc's "Network:" line BEFORE probing. dig/curl/response-headers are the
         OBSERVED surface: they show the ONE path your host happens to take and cannot
         show intent, the WAF, or the alternate path. Probe only to CONFIRM the IaC.
  FORBIDDEN: skipping the memory_search because "I know this stack."
  FORBIDDEN: emitting a SECOND posture claim of the same class after the first is
             corrected — STOP and read the .tf (see verify-before-assuming's
             two-same-class-retractions GUARD). Three in a row is the documented cost.
  FORBIDDEN: re-reading SG/NACL/route a 3rd time on a config-says-allow/data-plane-rejects
             paradox instead of running Reachability Analyzer — it adjudicates deterministically.
  # WHY: AWS cross-component incompatibilities are documented in OUR topic files, not
  #   Full: incidents#aws-cross-component-incompatibilities-are-documented-in-our-topic
  # WHY (Bedrock added 2026-07-20): GovCloud Bedrock AccessDenied → re-derived the entire
  #   Full: incidents#bedrock-added-2026-07-20-govcloud-bedrock-accessdenied-re
  # WHY (STEP_4): 2026-06-19 Proteus — read 5 enforcement layers (SG/NACL/route/EIP/prefix-list),
  #   Full: incidents#step-4-2026-06-19-proteus-read-5-enforcement
  # WHY (POSTURE scope + STEP_5 added 2026-07-26): a "is X reachable?" question where
  #   Full: incidents#posture-scope-step-5-added-2026-07-26-a

ON ci_failure:
  STEP_1 read the failed step's job log
  FORBIDDEN: guess from step name.

ON api_or_service_error_from_user:
  STEP_1 pull CloudWatch logs IMMEDIATELY
  STEP_2 filter_log_events with error code or keyword
  STEP_3 read actual log lines (file, line, stack)
  FORBIDDEN: "it might be X" hypothesis before reading logs.

ON http_api_client_error (4xx/5xx from a direct API call we made):
  STEP_1 read the response BODY, not just the status code — the body has the
         actionable cause; the status code is only a category.
  STEP_2 IF the error came through a wrapper (CLI/SDK/library) → inspect the wrapper's
         error path first. Many wrappers strip the body on status-specific branches;
         a 404 with no body proves the wrapper hid the cause, not that the resource
         doesn't exist.
  STEP_3 IF the wrapper is yours, fix it: include response.text in EVERY error branch.
  FORBIDDEN: diagnosing a 4xx from training data ("docs say tier X required") without
             reading the response body — the heuristic may be stale or about a
             different product.
  # WHY: 2026-05-01 gpt-5.5-pro 404 — "tier-gated" diagnosis, real cause was wrong
  #      endpoint; cost two PRs. Full: incidents#2026-05-01-openai-gpt55-pro-404

ON version_x_works_y_doesnt:
  STEP_1 build known-good version, confirm it works
  STEP_2 bisect forward through commits between good and bad
  FORBIDDEN: hypothesis-driven debugging before bisect.

ON slow_client_to_api_pipeline:
  STEP_1 dump API key env var (masked)
  STEP_2 send one request at the batch size the client sends
  STEP_3 time.time() before/after
  STEP_4 ramp batch size: if per-call latency flat → client-side batching bug
  FORBIDDEN: blame "rate limits" without direct probe.

ON fix_shipped_impact_under_expected:
  STEP_1 compute expected improvement ratio
  STEP_2 measure observed ratio
  STEP_3 IF observed < 0.3 × expected → hunt compounding bug
  STEP_4 profile end-to-end, not just the code you fixed

ON platform_availability_error (safety-classifier / model "temporarily unavailable" / "auto mode
   cannot determine safety" / rate-limit-class errors from the HARNESS, not from your code):
  STEP_1 classify the error: is it a SERVICE OUTAGE (classifier/model unavailable, 503-class) or a
         genuine transient (network blip)? "temporarily unavailable, auto mode cannot determine
         safety of Bash" is an OUTAGE — the vetting service is down, not your command.
  STEP_2 on the FIRST outage error → STOP retrying the same call. An outage does not clear on
         immediate retry; re-issuing the identical call N times just re-hits the down service.
  STEP_3 surface it to the user (the classifier is down; the work is blocked on a service, not a
         fixable command) OR switch approach — do NOT loop.
  STEP_3b SWITCH-PATH TACTIC (the concrete "switch approach"): the classifier vets each tool-call
         independently and an outage often FLAPS rather than hard-downs, so the SAME read-only op can
         be denied via one path yet vetted via another in the same minute. If an op is reachable via
         BOTH an MCP tool and Bash, try the OTHER path ONCE before surfacing — distinct from re-issuing
         the SAME blocked call (still forbidden). 2026-06-26: `list_jobs` was denied as a Bash `az rest`
         call but went through immediately as the equivalent azure-automation MCP tool call.
  FORBIDDEN: retrying the same blocked call >2× on an identical platform-availability error.
  # WHY: corpus-mode 2026-06-21 found this across 3 sessions — one retried the SAME call ~13× on a
  #   Full: incidents#2026-06-21-corpus-mode-found-across-3-sessions-retried-call

# ─── PROCEDURE: diff the failing state against the WORKING baseline before hypothesizing ───
# Fires on any "it used to work and now doesn't" failure where a prior WORKING run left
# evidence behind (rotated logs, a last-good config, a prior successful CI run, an earlier
# transcript). The trap: the failing state is full of conspicuous anomalies, and the most
# salient one gets promoted to root cause. Most of them were ALSO present when the system
# was healthy — they are BACKGROUND, not signal. The working baseline is the only thing
# that separates the two, and it is usually already on disk.
STEP_1 locate the last-working evidence FIRST — rotated logs (`X.1.log`, `X.2.log`), the
        prior green CI run, a pre-change config snapshot, the earlier session transcript.
        `ls -lt <logdir>/` is usually the whole search.
STEP_2 for EVERY anomaly you are about to call the cause, grep the WORKING baseline for it.
        Present in both → BACKGROUND, discard it as an explanation (it may still be a
        separate finding). Present ONLY in the failing state → candidate.
STEP_3 diff the SEQUENCES, not just the presence of lines. The signal is often "the working
        run does step N+1 and the failing run stops at N" — a MISSING line, which no
        grep-for-errors will ever surface because absence has no error text.
STEP_4 verify a proposed remedy has not ALREADY been tried, from the record, before
        recommending it. A restart/reboot/retry that the log shows already happened (and
        did not help) is a known-ineffective recommendation, not a next step.
FORBIDDEN: promoting the most conspicuous anomaly in a failing state to root cause without
            checking whether it also appears in the working baseline.
FORBIDDEN: recommending a restart/reboot/re-run without first grepping the record for
            whether that exact action already occurred since the failure began.
# WHY: 2026-07-26 GlobalProtect — 4 hypotheses refuted in one session; 3 died to ONE grep
#   Full: incidents#2026-07-26-globalprotect-4-hypotheses-refuted-in-one

# ─── PROCEDURE: process state before testing fixes → moved to rules/incidents/diagnose-before-fix.md (2026-07-30 descope) ───

# ─── before concluding a long background run is WEDGED ───
# A batch run that writes per-N-item-batch only advances its output file once
# per batch PERIOD. Sampling its progress over a window SHORTER than one batch
# period (e.g. 30-60s when a batch takes ~90s) shows delta=0 and aliases a
# HEALTHY run as a wedge. Distinguish on THREE signals, not one:
#   liveness (`ps -p <pid>`)  — necessary, never sufficient (a wedge is alive)
#   %CPU + write-delta over ≥ ONE FULL batch period (≥90s for a slow batch)
#   network I/O (`lsof -p <pid> | grep ESTABLISHED`) — open conns to the
#     API/DB = I/O-blocked-on-a-call (will resume), ZERO conns + 0% CPU +
#     0 writes = genuinely wedged.
# (2026-06-22: a recall_recovery run with 0% CPU + 0 writes in a 30s window was
#  mis-diagnosed "wedged"; a 90s window + lsof showed it was mid-batch between
#  Athena pulls — alive and progressing. The real fault was an SSO-token expiry,
#  not a wedge — see verify-effectiveness auth-expiry GUARD.)
       # [WINDOWS-ONLY]: prior host used `MSYS_NO_PATHCONV=1 taskkill /F /PID <pid>`
# INCIDENT 2026-05-02 SQLite-WAL-lock false-trail: killed 6 MCP `pythonw.exe`
#   Full: incidents#2026-05-02-sqlite-wal-lock-false-trail-killed

# ─── PROCEDURE: before editing a file ───
STEP_1 Have you READ the file in this session? If not → Read first
STEP_2 IF fixing a bug → read the ACTUAL ERROR (logs, tracebacks, test output)
FORBIDDEN: edit from memory or from session context that may be stale
# Analogy-driven edits are diagnoses too — read the local source first.
# INCIDENT 2026-05-13. Full: incidents#2026-05-13-code-graph-edit-before-read
#   Full: incidents#2026-05-13-full-incidents-2026-05-13-code

# ─── PROCEDURE: before building a feature ───
STEP_1 read official platform docs for what's already sent (e.g., statusline stdin JSON)
STEP_2 dump and inspect actual data platform provides
STEP_3 only build custom computation if platform genuinely doesn't provide it

# ─── PROCEDURE: before prototyping undocumented feature ───
STEP_1 gh search issues --repo <repo> "<feature name>" --state open
STEP_2 IF open issues confirm feature broken/unimplemented → stop, note issue
STEP_3 IF no issues → proceed with prototype

# ─── PROCEDURE: before blaming a hook for reverted edit ───
STEP_1 grep -nE "atomic_write|write_text|f\.write|open\(.*'w'" ~/.claude/hooks/<name>.py
STEP_2 confirm the hook actually writes (our Edit PostToolUse hooks are read-only)
STEP_3 reproduce: edit + cat in a fresh test file; see if change persists
STEP_4 IF persists in reproducer → likely concurrent-session race, NOT hook bug

# ─── PROCEDURE: after fixing an anti-pattern, hunt variants ───
WHEN: you just fixed a bug caused by an anti-pattern at one call site
  (e.g., `s.db` vs `s.q` in WithTransaction; open() without encoding; missing newline='')
REQUIRED:
  STEP_1 identify the exact wrong idiom as a grep-able string/regex
  STEP_2 grep the whole codebase for every occurrence (variants live elsewhere)
  STEP_3 fix every instance in the same PR, or justify each remaining one
  STEP_4 IF grep is impractical (language-level pattern) → /variant-analysis (AST-aware)
  STEP_5 IF the bug violated a SEMANTIC INVARIANT (not a textual idiom) → grep CANNOT
         find the other sites, because they aren't textually identical. Enumerate the
         invariant as an EXHAUSTIVE / property test over the finite input space, then
         mutation-verify it. "A REVOKED enrollment always yields a REMOVE" is not a
         grep-able string — the 5 differ prechecks that suppressed it (`continue` before
         the dispatch) had NOTHING lexically in common. A cross-product test
         (itertools.product over the enum dimensions) fails on ANY suppression path,
         found or not; grep found only the one site whose text you already knew.
  STEP_6 IF the thing you corrected was a CLAIM IN PROSE (a doc, rule, runbook, README,
         or handbook assertion) rather than code → hunt its variants THE SAME WAY. A claim
         propagates by copy-paste across a doc set exactly like an idiom propagates across
         call sites, and the copies have no sync. Grep the CLAIM'S DISTINCTIVE TOKEN (the
         identifier or number, not your paraphrase of the sentence) across every doc in the
         set, and fix every hit IN THE SAME PR. Then re-read each fixed site in context:
         prose corrections can leave a now-contradictory neighboring sentence that a
         code fix never would.
FORBIDDEN: "this one call site is fixed, ship it" while the idiom exists elsewhere.
FORBIDDEN: correcting a wrong claim in the doc where you noticed it and shipping — a
           doc set is a set of call sites for that claim. The copy you didn't grep is
           the one the next reader will find, and it now CONTRADICTS the one you fixed,
           which is worse than uniformly wrong.
# WHY (prose variants): 2026-07-26 Example Labs handbook — the claim "`desired_count = 1`
#   Full: incidents#2026-07-26-prose-variants-example-labs-handbook-claim-desir
FORBIDDEN: treating grep as sufficient variant-hunting for a SEMANTIC invariant — grep
           finds textual twins, not behavioral ones. For a security/correctness invariant
           spanning a finite input space, the exhaustive test IS the variant hunt.
# WHY: 2026-07-05 CAF reconciler revocation-suppression class — a REVOKED enrollment was
#   Full: incidents#2026-07-05-caf-reconciler-revocation-suppression-class-revo

# ─── PROCEDURE: process works in shell but fails when spawned by parent X → moved to rules/incidents/diagnose-before-fix.md (2026-07-30 descope) ───

# ─── PROCEDURE: config-identical instances behaving differently → moved to rules/incidents/diagnose-before-fix.md (2026-07-30 descope) ───

# ─── PROCEDURE: capability/coverage claims ───
FORBIDDEN: construct coverage tables from training data or inference
REQUIRED: every cell cites specific doc page, API response, or live test result
REQUIRED: when claiming "product X has no coverage in monitoring system Y," run an
          empirical test against EACH data source.
  # A 30-second query is cheaper than propagating a wrong claim.

# ─── PROCEDURE: docs conflict ───
WHEN: multiple docs disagree (e.g., device X at IP A vs IP B)
FORBIDDEN: resolve by majority vote or cross-referencing other docs
REQUIRED: find the source code that physically interacts with the entity
  Hardware: configd device handlers, driver source, NixOS module defaults
  Services: Rust defvar!, NixOS mkOption defaults
  Protocols: actual network calls in source

# ─── PROCEDURE: before deriving a submission/format/protocol CONTRACT from source → moved to rules/incidents/diagnose-before-fix.md (2026-07-30 descope) ───

# ─── PROCEDURE: before shipping a diagnostic-derived artifact ───
# Fires when shipping a PR, issue draft, or edit whose load-bearing claim is
# "mechanism X causes problem Y" — a wrong-mechanism diagnosis puts everyone
# downstream on false ground.
STEP_1 identify the load-bearing mechanism ("X causes Y" / "the bug is at <fn>" /
        "the fix is to <modify X>")
STEP_2 read the source where X is implemented; cite file:line of the code that
        supports the claim. No supporting source → it's a hypothesis; say so.
STEP_3 for a code edit: also read the EXISTING code near X — the fix may already
        exist or collide with adjacent logic
STEP_4 ONLY THEN ship, with file:line citations in the artifact body.
FORBIDDEN: shipping a mechanism claim sourced only from log signatures, error
           messages, or pattern-matching to similar incidents.
# WHY: reading source costs 30-90s; a shipped wrong diagnosis is high-cost and
#   Full: incidents#reading-source-costs-30-90s-a-shipped-wrong-diagnosis

# ─── PROCEDURE: respect user intent and methodology ───
REQUIRED: respond to the topic the user asked about. Don't reframe through a
          different lens (compliance, security posture) unless user connects them.
REQUIRED: if user specifies "each one individually" / "no batches" → follow exactly
FORBIDDEN: optimize with range() / dict comprehensions when user said individual analysis

# ─── USER OVERRIDE POLICY ───
# Diagnose-before-fix is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="this anomaly in the failing logs is the root cause" (on an "it used to work"
  regression where last-working evidence exists — rotated logs, a prior green run):
  REFUSE the causal claim until you grep the WORKING baseline for that same anomaly. Present
  in both → BACKGROUND, cannot explain a regression. Rotated logs (`X.1.log`) are usually
  already on disk — `ls -lt <logdir>/`. Also diff SEQUENCES: the signal is often a line the
  working run emits and the failing run does NOT, which no error-grep surfaces. NO EXCEPTIONS.

GUARD pattern="a THRESHOLD-gated check just failed, so the thing it measures REGRESSED"
  (a perf/latency/size budget, a coverage floor, an alarm on a fixed bound):
  READ THE LAST GREEN RUN'S VALUE, NOT ITS VERDICT. A pass/fail history cannot distinguish
  "the measured thing got worse" from "the threshold was always inside the noise band" — and
  the second is far more common on a shared runner. The margin is the diagnosis: a check that
  passed by <1% was never passing, it was a PENDING FAILURE, and it says nothing about the
  code that finally tripped it. This is the working-baseline GUARD above applied to a NUMBER
  rather than to an anomaly: there you grep the baseline for the same line, here you read the
  baseline's own metric.
  ALSO CHECK WHETHER TWO PIPELINES RUN THE SAME CHECK DIFFERENTLY. Same commit, two workflows,
  different commands is a natural experiment already in hand — if one is green and one is red,
  the variable is the COMMAND (instrumentation, flags, env), not your change, and you get that
  for free without reproducing anything.
  FORBIDDEN: raising the threshold to clear the red without measuring, and equally forbidden
  is suppressing the check under the condition that exposed it — a fix that removes the RED
  while leaving the margin thin just relocates the flake to the other pipeline.
  NO EXCEPTIONS for a threshold you are about to change.
  # WHY: 2026-08-03 claude-hud — `CI` failed "took 212ms, expected <200ms", which reads as a
  #   perf regression. The last GREEN run of the same test was 199.97ms: a 0.03ms margin.
  #   Measured on ONE commit: 181.3ms uninstrumented (build-dist.yml, green) vs 212.0ms
  #   c8-instrumented (ci.yml, red) — so ~17% was instrumentation and the rest was a budget
  #   hugging its own runtime. My first fix hypothesis ("skip the assertion under coverage")
  #   was WRONG for exactly the reason this GUARD names: 181 vs 200 is a coin flip on its own,
  #   so gating on coverage would have moved the flake to build-dist.yml instead of killing it.

GUARD pattern="try restarting / rebooting / re-running it" (as a recommendation):
  REFUSE until you grep the record for whether that action ALREADY occurred since the failure
  began. A service that restarted twice in the last hour with no change makes "restart it"
  known-ineffective, not a next step. NO EXCEPTIONS.

GUARD pattern="it's probably X, I've seen this before" or "must be Y":
  REFUSE to propose a fix. Read logs/events FIRST. NO EXCEPTIONS.

GUARD pattern="I know what this is, saves time":
  REFUSE. 20+ minutes per wrong guess. 30-sec log read is cheaper. NO EXCEPTIONS.

GUARD pattern="pre-existing, worth watching" / "probably transient" / "unrelated to
  my change" / "I'll keep an eye on it" — said about a RED SIGNAL you just observed
  (a failed CI run, a failed apply, a non-zero exit, an alarm) while continuing
  other work:
  REFUSE the defer. "Worth watching" is a decision to be surprised later. READ THE
  LOG NOW — one `gh run view --log-failed` / one CloudWatch read. Only AFTER
  reading may you classify it as pre-existing/transient/unrelated, and then say
  WHICH, with the error text. A signal you have already SEEN costs 60 seconds to
  diagnose and hours to rediscover. NO EXCEPTIONS for a failure you observed in
  the current session.
  # WHY: 2026-07-26 mcp-infra — saw a failed `main` Terraform apply at 02:54,
  #   Full: incidents#2026-07-26-mcp-infra-saw-failed-main-terraform-apply-02-54

GUARD pattern="docs say X, so X" (without source verification):
  CHECK source code if docs disagree OR if cost of being wrong > cost of verifying.
  Docs consensus is not evidence. NO EXCEPTIONS for load-bearing claims.

GUARD pattern="I'll figure out the submission/output format by reading the framework source":
  REFUSE for a CONTRACT/format/protocol question when a provided validator OR a
  known-good working example exists. Run the validator + copy the example FIRST;
  read source only to explain a discrepancy it surfaces. Framework-source inference
  for a contract is the documented 2-burned-submission failure. NO EXCEPTIONS when
  an attempt has real cost (submission quota, deploy, paid API call).

GUARD pattern="I've read this file before, just edit":
  REFUSE edit-from-memory. READ the current file first. Concurrent sessions may have
  changed it. NO EXCEPTIONS.

GUARD pattern="the rate limit must be it" (without probing API directly):
  REFUSE blame. Probe the API with requests.post + time.time(). 30 seconds. NO EXCEPTIONS.

GUARD pattern="3× is better than 1×, ship it":
  REFUSE stopping at partial gains when theoretical was 100×. Compounding bug is
  present. NO EXCEPTIONS.

GUARD pattern="hook reverted my edit":
  REFUSE that claim until you grep the hook for write calls. Our Edit PostToolUse
  hooks are read-only by design. NO EXCEPTIONS.

GUARD pattern="distilled rule says X, so X":
  VERIFY with actual API call before acting on external-system behavior. Distill
  captures OBSERVED, not VERIFIED. NO EXCEPTIONS.

GUARD pattern="config is identical but instance X behaves differently, let me redeploy/toggle/recreate it":
  REFUSE the instance-modification before reading the instance's OWN input
  telemetry. Config-identical instances differ because of INPUT (source IP,
  route, protocol), not the instance. Read what each instance actually received
  (WAF get_sampled_requests ClientIP, access logs) and compare FIRST. A fix on a
  config-identical instance is almost always a no-op. NO EXCEPTIONS.

GUARD pattern="grep shows the code is correct" or "the source looks fine" or "the fix is present in the source":
  REFUSE that conclusion for "is it correct?" / "why did this DEPLOYED thing stop?"
  questions. grep cannot see a module-level SyntaxError, a stale deploy, or runtime
  state. REQUIRED: compile the actual deployed file (`python -m py_compile <file>`)
  AND read live runtime state (queue/DLQ depth, Lambda invocations/errors, CloudWatch,
  watermark/cursor). The deployed artifact is what runs. NO EXCEPTIONS.
  # INCIDENT 2026-06-06 compliance chat worker (green grep over a SyntaxError'd
  # Lambda; 2.04M-msg DLQ). Full: incidents#2026-06-06-compliance-chat-worker-grep-said-correct

GUARD pattern="it's actually fine / working as intended / that's a red herring" (for a problem a USER REPORTED, concluded from ONE user's data):
  REFUSE the not-a-problem conclusion when the user reports it PERSISTS, pushes back, or names MULTIPLE affected people. A reported problem recurring after your "fix" is EVIDENCE the diagnosis/fix was wrong — NOT that the user is mistaken. REQUIRED: pull the SAME diagnostic evidence for the OTHER affected entities (users/hosts/tenants) and compare — a second identical failure turns "user-specific" into "systemic" and changes the fix. Do NOT re-assert the prior fix or dismiss the lived report. NO EXCEPTIONS when a problem is reported by 2+ users or re-reported after a fix.
  # WHY: 2026-07-07 example.au MFA — concluded "contributor-a is fine, the passkey error is a red herring" from their logs alone; user pushed back ("you are being dismissive… both contributor-a and contributor-b"). Pulling contributor-b's audit logs showed BOTH failed identically (contributor-b fully locked out) — a tenant-wide `Enforce attestation=Yes` misconfig breaking desktop passkey registration, not a one-user quirk. The earlier "push-first" fix had even disabled the WRONG setting (self-service, never the blocker).

# ─── FAILURE MODES to recognise ───
# Per-failure incident citations: incidents#failure-mode-incident-citations

FAILURE guessed_at_ECS_failure_burned_20min:
  RECOVERY: always describe-services + describe-tasks first.

FAILURE hypothesis_debugging_20_turns_when_bisect_was_5min:
  RECOVERY: bisect when version-regressions reported.  # code-graph v0.5.0, 2026-03-16

FAILURE inferred_coverage_table_from_training_data:
  RECOVERY: cite each cell, query actual data sources.  # OTel 2026-03-13; Cowork 2026-03-14

FAILURE doc_consensus_overrode_source_truth:
  RECOVERY: trace to source code when docs conflict.  # PSM switch IPs, 2026-03-17

FAILURE reframed_user_question_through_compliance_lens:
  RECOVERY: respond to the topic asked.  # gather-intel, 2026-03-13

FAILURE declared_reported_issue_user_specific_without_systemic_check:
  RECOVERY: pull the same diagnostic for every other affected entity and compare; 2+ identical
  failures = systemic → re-open root-cause, don't re-assert the fix.  # 2026-07-07 example.au MFA (contributor-a+contributor-b: tenant-wide attestation block)

FAILURE ignored_no_batches_methodology:
  RECOVERY: follow user's methodology exactly, even if "same pattern".  # STIG POA&M, 2026-03-17

FAILURE built_feature_platform_already_provides:
  RECOVERY: inspect platform stdin JSON before building custom compute.  # claude-hud, 2026-03-23

FAILURE shipped_PR_on_wrong_distilled_rule:
  RECOVERY: verify distilled API-behavior rules with actual API first.  # 2026-03-24

FAILURE blamed_rate_limits_without_probe:
  RECOVERY: probe API directly before attributing slowness to throttling.  # voyage, 2026-04-17

FAILURE accepted_2x_instead_of_expected_100x:
  RECOVERY: profile end-to-end when observed < 0.3× expected.  # voyage PR #62/#63

FAILURE prototyped_broken_undocumented_feature:
  RECOVERY: search GitHub issues before building test fixture.  # Context7, 2026-04-05

FAILURE blamed_hook_for_mystery_revert:
  RECOVERY: grep hook for write calls before blaming it.  # CRLF, 2026-04-17

FAILURE pattern_fix_missed_variants_cost_20min_later:
  RECOVERY: after fixing a pattern-type bug, grep every occurrence of the wrong idiom
  before shipping; fix in the same PR. The variant may live in a COPY-PASTED SIBLING
  FILE (another runbook/script that vendored the same function), not just other call
  sites of the module you fixed — grep the REPO, not the module.
  # code-graph tx-deadlock 2026-04-22; azure-automations entra_account_state 2026-07-23

# PROCEDURE: existence != applyability (extends verify-before-assuming.md's
# capability-vs-reachability guard beyond vendor features)
STEP_1 for any plan step that trusts "the file/function/table/path exists" as sufficient,
        also ask: is the OPERATION this step depends on actually EXECUTABLE here — the
        right IAM/SCP permission, free of unintended production side effects, under the
        REAL runtime environment (not a more permissive local one)?
FORBIDDEN: Phase 0 preflight checks that verify entities EXIST without verifying they
  are APPLYABLE in the actual permission/environment/side-effect context.
# WHY: 2026-07-31 /superplan run, 4 recurrences in ONE plan: a Terraform edit written for a
#   Full: incidents#2026-07-31-superplan-run-4-recurrences-in-one

ON http_4xx_used_to_infer_a_PERMISSION_or_CAPABILITY_answer:
  # Extends ON http_api_client_error above. That procedure says READ THE BODY; this one says
  # know WHICH GATE the body came from. A request traverses gates IN ORDER —
  # routing -> body/schema validation -> authentication -> authorization -> business logic —
  # and it reports the FIRST one it fails. So a 4xx answers the question of the gate that
  # fired, which is frequently NOT the question you asked.
  STEP_1 identify which gate produced the status. In FastAPI/Pydantic/DRF/Rails-strong-params,
         **422 (and often 400) is SCHEMA validation, which runs BEFORE the permission check** —
         so a 422 proves the body was malformed and proves NOTHING about authorization.
  STEP_2 to ask a PERMISSION question, send a SCHEMA-VALID body. Only then does the response
         reach the authz gate and 401/403 become meaningful.
  STEP_3 the inverse also holds: a 200 on a request the server ignored fields from answers
         nothing about those fields.
  FORBIDDEN: concluding "X is permitted for this role" from a 422, or "the endpoint is
             broken" from a status whose gate you have not identified.
  # WHY: 2026-08-02 Open WebUI — `POST /prompts/create` returned 422 "Field required: name",
  #   read as "Prompts are seedable WITHOUT admin, unlike the model row". Re-probed with a
  #   valid body: **401**. The schema wanted `name`, not `title`; body validation had short-
  #   circuited before authz. The wrong reading briefly split one decision into two and
  #   would have shipped "non-admins can seed Prompts" into an as-built document.

GUARD pattern="an in-container errno on a path the IMAGE itself creates — `Permission
  denied` / EACCES / EPERM writing a MOUNTED directory — read as 'my Dockerfile is wrong'":
  THIS IS A PLATFORM QUESTION, so `cloud_infrastructure_debug` STEP_1 APPLIES: memory_search
  the MOUNT behaviour before reading your own image. The recall step does not fire by itself
  here because the error names a path YOU control, so it reads as your bug — that framing is
  the failure, not the errno. An errno is about the KERNEL's view of a mount, and on a
  managed runtime the mount is the platform's to create.
  MEASURED: Fargate renders a task-level name-only `volume` as `host:{}` and creates it
  **root:root 0755, REPLACING the image's `mkdir`+`chown`**, so a non-root container cannot
  write it and `MountPoint` has no uid/mode field. That is `[confirmed]` in
  `knowledge-base/topics/aws-deployment-ecs-fargate.md` since 2026-07-28 — WITH a one-line
  escape (declare `VOLUME <dir>` in the IMAGE so the mount inherits image permissions).
  Skipping the search cost a deploy cycle AND shipped a heavier fix (a root init container)
  than the documented one.
  ALSO: the first write to fail is not the only one blocked. If that mount is also the app's
  STATE dir, fixing only the file you noticed leaves a second failure queued behind it.
  NO EXCEPTIONS for an errno on a mounted/volume path under a managed container runtime.
  # WHY: 2026-08-03 claude-gateway — `cannot create /var/lib/claude-gateway/gateway.yaml:
  # Permission denied`; the Dockerfile DID chown 10001 (lines 195-197). The module's own
  # comment asserted the opposite ("Docker copies whatever the image already has at
  # config_dir into this volume") — true for Docker named volumes, false for Fargate.

GUARD pattern="run a diagnostic probe that can OPEN AN INTERACTIVE FLOW on the user's own
  machine" (`<vendor> auth login`, a browser OAuth, anything that launches a UI or listens
  on a callback port):
  CHOOSE A NON-INTERACTIVE PROBE, or do not run it. A probe you kill mid-flight leaves the
  user looking at a REAL error you manufactured — and they will reasonably attribute it to
  the thing under investigation, which corrupts the very diagnosis the probe was meant to
  inform. Prefer `--help`, a `status` subcommand, or reading the artifact on disk.
  IF one fires anyway: say plainly and UNPROMPTED that the symptom is YOURS, before
  answering anything else — an unattributed side effect becomes the user's next bug report.
  # WHY: 2026-08-03 — `claude auth login` opened a Safari OAuth tab; killing the process 12s
  # later dropped its localhost callback listener, so the user saw "Safari Can't Connect to
  # the Server" in the middle of debugging a login problem. It also proved a real fact (the
  # CLI subcommand ignores `forceLoginMethod` entirely) — the finding was worth having, the
  # collateral was avoidable with a flag that opens no browser.

GUARD pattern="a cloud AUTH/PERMISSION error you intend to REPORT rather than fix ('you may
  lack RBAC on X', 'the token is expired', 'this capability is blocked')":
  RUN cloud_infrastructure_debug STEP_1 ANYWAY. The memory_search trigger reads as "a failure
  to DIAGNOSE", so an error you have already decided to hand back as a FINDING slips past it —
  you are not debugging, you are reporting, and the step never fires. That framing is the bug:
  a permission verdict IS a diagnosis, and it ships to the user as fact.
  REQUIRED: memory_search(component + symptom) before the verdict leaves the turn. Auth errors
  are the highest-recurrence class in the KB precisely because each one feels like a one-off.
  NO EXCEPTIONS for an access verdict that reaches the user.
  # WHY: 2026-08-04 — three Azure `AuthorizationFailed`/AADSTS70043 errors reported as a
  #   possible RBAC gap without one memory_search. `agent-memory/topics/azure-automation.md`
  #   held the answer THREE TIMES over (wrong-principal 2026-06-15 + its own 2026-06-16
  #   recurrence on this same runbook; the 2026-07-31 "probe the CLI before declaring blocked"
  #   entry; the 2026-07-29 queued-job entry). All three were re-derived from scratch.
