---
paths:
  - "**/rules/diagnose-before-fix.md"
  - "**/rules/incidents/diagnose-before-fix.md"
---

# Diagnose-Before-Fix: Incident Narratives

Extracted from `rules/diagnose-before-fix.md` to keep the ambient body
small while preserving the failure-mode history that calibrates the
rule. The parent rule keeps the keys (invariants, procedures, guards,
failure modes) with one-line recovery hints; full narratives live here.

---

## 2026-08-18 new-diagnostics-line-shift — adopted someone else's finding as my own
<a id="2026-08-18-new-diagnostics-line-shift"></a>
**Anchors:** Forbidden shortcut "Attributing a post-edit diagnostics/lint signal to
your own change without opening the cited line"

Relocated verbatim from the parent rule on 2026-08-27 to fund an append under the
ambient delta gate (`manifests/ambient-budget.json` option 1, net-zero relocation).

A `<new-diagnostics>` block reports what is flagged NOW, not what your edit
introduced. Insertions SHIFT line numbers, so untouched pre-existing findings
re-report as "new". This is the exact inverse of the neighbouring shortcut: there
the reflex is to DISMISS a real signal as pre-existing, here it is to ADOPT
someone else's as yours. Both are fixed by the same action — open the cited line
before acting on it.

INCIDENT 2026-08-18: renamed a local variable to silence a "ModuleType is not
callable" report that turned out to sit in test code I never touched. It surfaced
only because my additions moved it down the file.

---

## 2026-08-27 autosync-declared-dead-in-2-minutes — published a negative claim into two merged docs
<a id="2026-08-27-autosync-declared-dead-in-2-minutes"></a>
**Anchors:** Forbidden shortcut "Calling an ASYNCHRONOUS mechanism broken without
measuring ITS OWN latency"; procedure `cloud_infrastructure_debug` STEP recall

Shipping a NetSuite-sync fix through `azure-automations`. After the PR merged I
polled `sourceControlSyncJobs` twice over roughly two minutes, saw no new job,
and concluded `autoSync` was broken — naming an expired GitHub PAT or deleted
webhook as the likely cause. That claim went into a report AND into two KB PRs
that both MERGED before it was refuted. A third PR had to retract it.

**Every refuting datum was already in hand or one cheap call away:**
- The webhook was healthy: `active: true`, `last_response: 202 OK`, with a
  delivery logged for the merge push itself (`gh api repos/<r>/hooks/<id>/deliveries`).
- The "nine-day gap since the last sync" was not evidence at all — the only
  intervening merge touched ZERO files under `runbooks/`, so no sync was due.
- A webhook-triggered sync job DID arrive, 4 seconds after the manual one I
  triggered out of impatience.
- **The latency baseline was in the same API response I had already fetched to
  check for new jobs.** Two prior commits sat there with their sync timestamps:
  1m47s and 1m47s. I waited ~2 minutes against a 1m47s mechanism.

**Why the existing rule did not stop it: it was ADHERENCE, and the miss was total.**
`agent-memory/topics/azure-automation.md`'s **most recent entry, dated 2026-08-18 —
nine days earlier** — already contained every instrument this episode needed:
- `folderPath` scopes the sync, so a merge touching no file under `/runbooks`
  produces no sync job and **"an empty recent-sync list is therefore not evidence
  the webhook is dead."** That is verbatim the inference I got wrong.
- the job LIST lags job creation (~75 s observed), with the literal prescription
  **"re-poll once before diagnosing."** Following that one line would have
  prevented the entire retraction.
- the deployed-content byte-compare **"needs to tolerate"** the single trailing
  newline the ARM endpoint appends — which I also re-derived.

Four rediscoveries from ONE unread file in ONE session: this, plus
`start_time == end_time` as a metadata quirk (THIRD recurrence — see the
2026-07-28 entry below, which records the identical wrong first hypothesis), plus
the 512-char variable description cap (second, already carrying "assert
client-side BEFORE the PUT"). One `memory_search` on the component returned the
autoSync material at cosine 0.53-0.62 when finally run — after the claim shipped.

The rule's trigger already covers this surface (2026-07-28 broadened it to Azure
Automation; 2026-07-26 added POSTURE questions for exactly the "nothing errored"
framing). Restating the recall mandate a fourth time is not the fix; the additive
instrument is the LATENCY BASELINE in the Forbidden-shortcuts line above, because
none of the prior entries name "measure the mechanism's own normal duration."

**lesson:** an async mechanism has a measurable normal latency, and "I looked and
it wasn't there" is a statement about the looking. Measure the baseline from the
mechanism's own history BEFORE the claim — and treat publishing a negative claim
about infrastructure as the same commitment as publishing a fix, because a merged
wrong claim costs a retraction in every place it landed.

---

## 2026-07-28 azure-automation-rediscovery — the recall gap was scoped to AWS, so it never fired
**Anchors:** procedure `cloud_infrastructure_debug` (renamed from
`cloud_infrastructure_debug` by this incident)
`aws_infrastructure_debug` by this incident)

An 8-hour Azure Automation run-status review across 48 runbooks / 4,500 jobs
re-derived at least three facts the KB already held, because the
memory_search-first mandate was scoped to **AWS components only** and this was
an Azure/Entra investigation. Unlike the 2026-07-24 Bedrock recurrence below
(logged as a rule-ADHERENCE failure — I held the rule and didn't run it), this
was a genuine **rule GAP**: the trigger list did not cover the cloud in play.

Re-derived from scratch, each already documented:
1. `start_time == end_time` on a failed Azure Automation job is a **metadata
   quirk, not a startup crash** — `azure-automation-runtime-modernization.md`
   carries an entry titled almost exactly that. I made the identical wrong first
   hypothesis ("the job died instantly / never ran"), and it was only corrected
   by reading the job OUTPUT stream. The temptation recurred twice more.
2. jobSchedule links are **silently deletable state; verify by GET after PUT** —
   same KB file. I rediscovered the adjacent fact that `jobSchedules` returns
   `name: null` and the usable id is `properties.jobScheduleId` (without it the
   old links can't be deleted and each runbook runs TWICE).
3. A fixed-UTC-vs-local **DST trap** — `netsuite-employee-sync.md` documents the
   same shape. The shared `Daily` schedule is `America/Chicago` (23:59 local =
   04:59 UTC) and shifts an hour at DST; new `Etc/UTC` schedules authored on a
   UTC assumption would have collided in November.

fix: broadened the procedure's scope line from `cloud_infrastructure_debug` to
fix: broadened the procedure's scope line from `aws_infrastructure_debug` to
`cloud_infrastructure_debug`, explicitly naming Azure Automation / Entra /
Graph / SCIM alongside the AWS components. The procedure's STEPS were already
cloud-agnostic — only the trigger was AWS-shaped, so this cost ~270 bytes rather
than duplicating 15 lines for a second cloud. All 5 references to the old
procedure name were updated in the same pass (`rules/scope-discipline.md` ×3,
this file, `agent-memory/topics/aws-infra-misc.md`) per check-before-change's
renamed-contract rule.

lesson: when a recall-discipline procedure keeps recurring, check whether the
TRIGGER covers the surface you are on before concluding it is an adherence
problem. A mandate scoped to one cloud silently exempts every other one, and the
exemption is invisible — nothing errors, you simply never search.

---

## 2026-05-15 cloudfront-oac-rediscovery — skipped memory_search on AWS debug
<a id="2026-05-15-cloudfront-oac-rediscovery"></a>
**Anchors:** procedure `cloud_infrastructure_debug`

The session burned 3+ hours rediscovering the
CloudFront-OAC-for-Lambda-Function-URL incompatibility that was already
in aws-deployment-patterns.md from three days earlier (2026-05-12 →
2026-05-15 recurrence).

AWS has many cross-component incompatibilities (OAC types, L@E + origin
signing, IAM principal liveness in KMS policies, etc.) that are not
well-documented in AWS's own docs but ARE well-documented in our topic
files after we've hit them. The knowledge IS captured; the failure mode
is FAILING TO RECALL. The cost of the memory_search is 30 seconds; the
cost of skipping it is hours of rediscovery.

---

## 2026-05-01 openai-gpt55-pro-404 — diagnosed from training data, not response body
<a id="2026-05-01-openai-gpt55-pro-404"></a>
**Anchors:** procedure `http_api_client_error`

OpenAI gpt-5.5-pro returned 404. Wrapper showed "404 model not found".
WebSearch said "Pro tier rolled out to Pro/Business/Enterprise". I
diagnosed "tier-gated" and shipped PR #804 dropping the default. Real
cause (per response body, accessible via direct curl): "This is not a
chat model... did you mean v1/completions?" — wrong endpoint, not tier.
The training-data heuristic was about the consumer ChatGPT product
launch tier, not API access. Reading the response body would have
caught it in one turn instead of two PRs.

---

## 2026-05-02 sqlite-wal-lock-false-trail — killed wrong process class
<a id="2026-05-02-sqlite-wal-lock-false-trail"></a>
**Anchors:** procedure `process state before testing fixes`

Trying to delete an eval index dir, hit Device-or-resource-busy on .db
files. Scanned tasklist for `pythonw.exe`, found 6 code-search MCP
server processes (3 active pairs from prior sessions), killed all of
them. Did NOT release the locks. Real lock-holder was PID 37572 — a
`python.exe` (NOT pythonw) running my background `index_psm_full.py`
script that had hung. Killing the active MCP pair also broke the Claude
Code session's MCP connection (per Anthropic claude-code#43177 stdio
reconnect gap), forcing a full restart. The correct first move was
`Get-CimInstance ... Where CommandLine -like '*psm-full*'` which would
have surfaced PID 37572 directly without touching MCP servers.

---

## 2026-04-26 code-graph-mcp-spawn-context — 15 turns of program hypotheses
<a id="2026-04-26-code-graph-mcp-spawn-context"></a>
**Anchors:** procedure `process works in shell but fails when spawned by parent X`

code-graph MCP debugging. Spent ~15 turns rotating through hypotheses
(CC stdio EOF bug #43177, Node 24 .cmd handling, pythonw vs python.exe
console state, MCP protocol version 2025-11-25, Python daemon thread
shutdown crash) — each disproven. User had to stop me: "take a step
back from making assumptions and investigate the actual root cause".
Once I dumped env from both contexts, diff showed CC's PATH lacked
C:\Program Files\Git\mingw64\bin and the binary had a 3-second Popen
delay. `objdump -p` showed libwinpthread-1.dll import — MinGW DLL, not
system. Three-step diagnostic (env diff + objdump) would have found
this in 5 minutes.

---

## 2026-05-13 code-search-upstream-pr-515-516 — shipped wrong-mechanism diagnosis
<a id="2026-05-13-code-search-upstream-pr-515-516"></a>
**Anchors:** procedure `before shipping a diagnostic-derived artifact`

context: 2026-05-13 test battery surfaced a code-search MCP hang. From
log signature `auto_reindex_if_needed: project=None ...
project=you force_full=False`, I generated the plausible
mechanism "server auto-registers its CWD as a project on startup with
no validation" and shipped that as PR #515's main TL;DR +
suggested-fix sections.

problem: Reading `mcp_server/code_search_server.py:259-413` would have
shown the refuse-check ALREADY exists (added Phase A 2026-05-07 at line
408). The actual bug is finer-grained: `get_project_storage_dir` writes
`project_info.json` at line 383 BEFORE `ensure_project_indexed`'s
refuse-check fires at line 408, leaving an orphan project dir on disk
that `auto_reindex_if_needed` (separate code path with no refuse-check)
then hits on every 5-min cron tick. PR #516 shipped the corrected
diagnosis with line citations.

cost: low because the revision happened in the same session before
anyone acted on PR #515. Would have been high if the artifact had been
filed externally first — anyone reading #515's "the fix is to add a
refuse-check at registration" would have wasted time trying to find the
registration point and adding a check that already exists.

recovery: ship a revision PR with source-cited diagnosis + Changelog
section explicitly documenting what the prior draft got wrong. Don't
silently overwrite a wrong artifact — the audit trail of "what we
learned" is itself valuable.

---

## 2026-05-13 code-graph-edit-before-read — analogy-driven edit left file broken
<a id="2026-05-13-code-graph-edit-before-read"></a>
**Anchors:** procedure `before editing a file`

context: After the source-cited revision, started editing
`internal/tools/tools.go` to add an `isForbiddenSessionRoot` helper
based on the same mechanism I'd just (correctly) diagnosed for
code-search.

problem: User interrupted with "what were the results of the test
battery per the original intent of this session?" before I finished.
The edit I'd made (`!isForbiddenSessionRoot(cwd)`) was correct logic
but called an undefined helper — leaving the file in a broken state.
Worse, I hadn't yet read the existing refuse-check pattern in
code-graph to see if a similar guard already existed. (It did — the
`cwd != os.Getenv("HOME")` check at line 187 was the broken
Windows-only version of what I was about to add.)

fix: reverted the partial edit, returned to main, addressed the user's
question first. Resumed the fix later WITH the source already read —
replacing the broken check rather than adding redundant code.

lesson: when an edit is informed by analogy to ANOTHER incident, the
analogy is itself a diagnosis — verify by reading the local source
before editing.

---

## 2026-06-06 compliance-chat-worker-grep-said-correct — grep cannot see SyntaxError
<a id="2026-06-06-compliance-chat-worker-grep-said-correct"></a>
**Anchors:** GUARD "grep shows the code is correct"

context: Audit pipeline's `messages` table empty for June. Diagnosed
across two sessions via grep + Athena: first "the worker code is
correct" (grep of compliance_chat_worker.py showed the chat_messages
fix present), then a KB artifact (#687) hypothesizing "worker stopped
consuming SQS."

problem: BOTH wrong. grep CANNOT see a module-level SyntaxError. The
deployed Lambda had an unclosed `{` at line 389 (a dead half-deleted
block from a prior edit) → it failed at IMPORT on every invocation.
Live introspection found the truth in minutes: `py_compile` the file
(SyntaxError), CloudWatch (Runtime.UserCodeSyntaxError every
invocation), SQS (2.04M-msg DLQ), Lambda metrics (300k invocations/day,
all failing), SSM (watermark frozen). Mechanism: import-crash → every
msg DLQs → frozen two-phase watermark → poller re-enqueues all chats
each cycle → exponential amplification.

lesson: for "is this code correct?" and "why did this DEPLOYED pipeline
stop / go silent?", grep-of-source is necessary but NOT sufficient — it
cannot catch syntax/import errors, stale deploys, or runtime state.
REQUIRED before concluding: (1) compile the ACTUAL deployed file
(`python -m py_compile <file>` / the language's parse/build) — a green
grep over broken source is a false "correct"; (2) read LIVE runtime
state — queue + DLQ depth, Lambda invocations/errors, CloudWatch logs,
watermark/cursor SSM — not just the repo source. The deployed artifact
is what runs.

recovery: PR #380 (fix) + #688 (corrected KB diagnosis documenting the
wrong mechanism) + a `py_compile lambda/*.py` CI gate (#381) so a
SyntaxError can never deploy via terraform-only CI again.

---

## 2026-07-26 mcp-infra-reachability-posture — 3 wrong architecture claims from partial observed surfaces
<a id="2026-07-26-mcp-infra-reachability-posture"></a>
**Anchors:** procedure `cloud_infrastructure_debug` (POSTURE scope + STEP_5)

context: the question was "is slack-connect reachable without Tailscale?" — a
POSTURE question, not a failure. NOTHING had errored, so the
`cloud_infrastructure_debug` procedure felt inapplicable and STEP_1's
memory_search was never run.

problem: THREE successive wrong architecture claims in ~10 minutes, each derived
from a different partial OBSERVED surface:
1. **DNS** → "slack-connect is public, the others are internal." Wrong: there is
   one shared edge; every service resolves to the same 4 IPs.
2. **curl status codes** → "crowdstrike + security-remix are filtered." Wrong: a
   POST-vs-GET artifact with no control in the measurement — a GET control
   returned 200 for all four.
3. **response headers** → "the ALB is internet-facing, the doc is wrong." Wrong:
   `alb.tf:5` is `internal = true`; CloudFront → API Gateway → VPC Link
   deliberately front it, and `cloudfront.tf`'s priority-0 WAF rule blocks
   `/internal/*` at the edge (verified 403 live).

what would have settled it: ONE `grep "internal =" mcp-infra/*.tf` plus
mcp-infra/CLAUDE.md's "Network: Tailscale VPN mesh + API Gateway public path for
all services."

worst part: agent-memory ALREADY had it — `aws-infra-misc.md:291` ("Route53
wildcard → CloudFront publicly; Tailscale DNS rewrites the same hostname to the
internal ALB") and `memory/macos-mcp-gaps.md`'s literal "Reachability matrix."
~8 probes to rediscover a documented fact.

lesson: the procedure's memory_search step applies to POSTURE/reachability
questions too, not just to errors — "nothing has errored" is exactly the framing
that skips it. A claim built from one observed surface (DNS, a status code, a
header) needs a control before it ships.

---

## 2026-07-26 globalprotect-working-baseline — 4 refuted theories, 3 killed by one grep
<a id="2026-07-26-globalprotect-working-baseline"></a>
**Anchors:** procedure `diff the failing state against the WORKING baseline`; GUARDs "this anomaly is the root cause" / "try restarting"

context: GlobalProtect stopped connecting on macOS 26.3.2 after an in-place
upgrade to 6.2.8-948. UI showed "Invalid portal". Two real faults existed: the
`PanGPS` service was dead (upgrade stopped it cleanly; `KeepAlive
{SuccessfulExit: false}` means launchd only restarts on NON-zero exit, so it
stayed down ~4.5 days), and — after that was fixed — the client authenticated
fully via SAML/Entra + Azure MFA but never loaded its portal config
(`Error(1746): m_portalCfg is NULL`).

problem: FOUR causal hypotheses were stated with confidence and then refuted:
1. **Missing macOS Network System Extension.** Drove a reinstall recommendation
   across several turns. Its entitlements are `app-proxy` / `dns-proxy` /
   `content-filter` — NO packet-tunnel provider — so it cannot build a tunnel;
   GlobalProtect tunnels in userspace via `utun`. Definitively exonerated when
   the VPN later connected with the extension STILL unregistered.
2. **Cache-filename hash mismatch** (`PanPUAC_a8575bede…` vs on-disk
   `PanPUAC_655de051…`). The Jul-22 WORKING log showed the identical
   `a8575bede…` miss — it is simply the first key always probed.
3. **`CheckServerCert return 0x2000`** read as a cert failure. It appears on
   **17/17** attempts across both logs, including every working one.
4. **Stale portal cache.** Cleared it (backed up first); failure reproduced
   byte-identically. Cache state was provably irrelevant.

Additionally, a **reboot** was recommended while `pan_gp_event.log` already
showed `GlobalProtect service started` twice that same hour, each followed by
the same failure — a known-ineffective action presented as the next step.

the one command that mattered: `PanGPS.1.log` (the Jul-22 working generation)
sat in the same directory the entire session. Grepping it invalidated theories
2 and 3 immediately and reframed 1. The REAL signal was an ABSENCE: the working
run probed a SECOND cache key after the first miss; the failing run never did.
No error-grep can find that, because a missing line emits no error text — only
a sequence diff against the baseline surfaces it.

resolution: reinstall of the SAME version (6.2.8) via Jamf Self Service. Post-
reinstall the two-key fall-through returned and the tunnel established
(`tunnel-status = connected`, `utun4`, 172.16.13.24). Root cause was a
client-side state defect, not configuration — every config variable had been
eliminated. An IT-facing incident report was delivered
(`~/Documents/reports/it/2026-07-26-globalprotect-outage-report.md`).

cost: ~38 of 122 turns on dead ends; 4 retractions; 3 wrong commands handed to
the user (`system/…pangps` and `system/…pangpsd` — neither label is in the
system domain; `bootstrap` where `kickstart` was needed); one `bootout` that
removed the WORKING Aqua-agent registration and briefly left PanGPS at zero
processes; and a user "Explain to me what is going on".

lesson: on any "it used to work" regression, the failing state is full of
conspicuous anomalies and MOST OF THEM ARE BACKGROUND. The working baseline is
the only instrument that separates background from signal, and it is usually
already on disk as a rotated log. Establish it BEFORE generating hypotheses,
not after four of them have been published. Corollary: verify a proposed remedy
has not already been tried, from the record, before recommending it.

---

## failure-mode-incident-citations
**Extracted incident details for the parent rule's FAILURE keys (2026-06-10 descope).**

### hypothesis_debugging_20_turns_when_bisect_was_5min
INCIDENT code-graph v0.5.0 (2026-03-16): 20+ turns of hypothesis
debugging; bisect found the answer in 5 minutes.

### inferred_coverage_table_from_training_data
INCIDENT OTel (2026-03-13): 5 turns wasted on incorrect coverage
tables. INCIDENT Cowork (2026-03-14): claimed "no visibility" without
querying Athena (table literally named cowork_otel).

### doc_consensus_overrode_source_truth
INCIDENT PSM switch IPs (2026-03-17): 5 docs agreed on IPs, all wrong;
configd source had the truth. 3 turns wasted.

### reframed_user_question_through_compliance_lens
INCIDENT gather-intel (2026-03-13): user asked about Paved Road; AI
reframed every finding through NIST/CMMC/FedRAMP. 3 correction turns.

### ignored_no_batches_methodology
INCIDENT STIG POA&M (2026-03-17): user said "no batches" 3 times; AI
kept reverting to batch generators. 3 corrections.

### built_feature_platform_already_provides
INCIDENT claude-hud (2026-03-23): built 96-line pricing module;
platform already sent cost.total_cost_usd. 30 min wasted.

### shipped_PR_on_wrong_distilled_rule
INCIDENT Internal-Apps auto-merge (2026-03-24): shipped PR based on
wrong distilled rule; one gh api call would have caught it.

### blamed_rate_limits_without_probe
INCIDENT code-search voyage-context (2026-04-17): 2 hours of "wait for
rate limits" before API probe showed Voyage returning 200 in <100ms.
Actual cause: two compounding client-side batch caps.

### accepted_2x_instead_of_expected_100x
INCIDENT code-search voyage-context (2026-04-17): PR #62 raised inner
batch cap 4→500 (125× theoretical). Observed: 2×. Second bottleneck
(incremental_indexer.py outer cap=64) shipped as PR #63.

### prototyped_broken_undocumented_feature
INCIDENT Context7 allowed-tools (2026-04-05): 3 turns on prototype;
GitHub #37683 confirmed feature unenforced. One gh search issues call
would have caught it.

### blamed_hook_for_mystery_revert
INCIDENT bulk-api-script CRLF (2026-04-17): saw system reminder,
assumed hook reverted. No hook writes SKILL.md. Root cause was NOT the
hook.

### pattern_fix_missed_variants_cost_20min_later
INCIDENT code-graph tx-deadlock (2026-04-22): PR #50 fixed two sites
that used `s.db` instead of `s.q` inside WithTransaction. Shipped. PR
#7 (semantic similarity edges) ran 20+ minutes into a new index hang
before realizing 3 MORE unfixed sites existed — UpsertEmbedding,
EmbeddingCount, loadEmbeddingCache, all bypassing the tx. A single
`grep -rn 's\.db\.' internal/store/` in PR #50 would have surfaced
every site in one shot.

INCIDENT azure-automations entra_account_state (2026-07-23): PR #31
fixed the hits[0] duplicate-mail hazard in packages/govslack_deprov/
graph.py + the Function's vendored copy — the two KNOWN copies — but
never grepped the repo for the idiom. `github-member-deprovision.py`
carried a third, COPY-PASTED entra_account_state with the identical
`hits[0]` bug (same docstring, same shape), so a re-joiner with a
lingering disabled duplicate object could still be kicked from the
GitHub org. Found same-session only because /distill's cross-cutting
audit step greps sibling repos; a `grep -rn "mail eq" .` at PR #31
time would have caught it in the same PR. The new facet vs the
2026-04-22 incident: the missed variant was a whole vendored FUNCTION
in a sibling runbook, not additional call sites of the fixed module.

## 2026-07-30 descoped from rules/diagnose-before-fix.md — moved verbatim, not trimmed

Moved by the #1802 house pattern so the parent rule drops below the
rule-size-guard write-block. Content is unchanged; the parent carries a
pointer at each original location.

# ─── PROCEDURE: a defect that only appears in an environment you do not have ───
# Fires when a failure is reported by CI / another OS / a remote runner and does
# NOT reproduce on this host (a platform-only test failure, a cross-platform hash
# mismatch, a locale/encoding difference). The expensive path is hypothesise →
# push → wait for the round trip; each cycle tests ONE guess and tells you only
# pass/fail. The cheap path is to emulate the MECHANISM locally.
STEP_1 name the mechanism that differs, not the platform. "Windows" is not a
        cause; "text=True decodes with the locale's preferred encoding, which is
        cp1252 there" is. The mechanism is what you can emulate.
STEP_2 emulate it locally by patching the seam — monkeypatch the call to force
        the other behaviour, set the env var, sweep the constant. Then RUN A
        NEGATIVE CONTROL: confirm the emulation reproduces the failure with the
        fix REMOVED. Without the control, a passing emulation proves nothing.
STEP_3 make the remote report LOCALIZING before spending another cycle on it. A
        check that says only "the two differ" cannot be acted on from a host
        that cannot reproduce either side — add per-region hashes, upload the
        actual artifact from each leg, print the differing values.
STEP_4 ONLY when the mechanism genuinely cannot be emulated (real GPU, real
        vendor endpoint) is the round trip the cheapest instrument. Say so.
FORBIDDEN: a 3rd remote/CI cycle on a 3rd hypothesis for the same defect while
            the seam is monkeypatchable locally.
## 2026-06-21-corpus-mode-found-across-3-sessions-retried-call
<a id="2026-06-21-corpus-mode-found-across-3-sessions-retried-call"></a>

  # WHY: corpus-mode 2026-06-21 found this across 3 sessions — one retried the SAME call ~13× on a
  #      "classifier temporarily unavailable" error (the opus-4-8 fallback outage). The retry is
  #      pure cost: the outage is server-side. Also: the auto-mode classifier ANCHORS on the prior
  #      turn's context — a brand-new user message that fully specifies a prod-cred/external task can
  #      be denied for "scope escalation" carried from earlier; re-state the task standalone or
  #      surface the false denial rather than retrying.
  #      ANCHOR-ON-BLOCKED-COMMAND VARIANT (2026-07-05): the classifier can assert a BLOCKED
  #      command's intended effects as executed fact — it denied a schedule-link twice claiming
  #      "DRY_RUN was set to false and never reverted" when the set-command had itself been DENIED
  #      (a blocked call runs nothing), and a fresh read-verification in the transcript (variable
  #      == "true") did NOT clear the anchor. After 2 denials on factually-wrong grounds: STOP,
  #      state the verified truth, and hand the user the EXACT command to run via `!` bash-input —
  #      it executes outside the classifier and its output lands in-session.
  #      CAVEAT (2026-07-08, installed v2.1.204): #75397 (OPEN, has-repro, macOS) — a `!`-prefix
  #      terminal command now INCORRECTLY triggers Claude analysis instead of executing directly.
  #      On 2.1.204 the `!` bash-input escape hatch above may itself be intercepted by the
  #      classifier — VERIFY it still executes (output lands in-session) before relying on it as
  #      the bypass; if intercepted, surface the exact command for the user to run in a RAW
  #      terminal (outside Claude Code) instead.

## 2026-07-26-report-builder-windows-only-12-byte-render-misma
<a id="2026-07-26-report-builder-windows-only-12-byte-render-misma"></a>

# WHY: 2026-07-26 report-builder — a Windows-only 12-byte render mismatch cost
# 2 CI cycles on wrong hypotheses (footer width driving layout; Vega
# canvas-vs-estimation text metrics). Emulating a cp1252 locale at the
# subprocess seam then reproduced it EXACTLY (6,620 bytes with mojibake vs
# 6,608 fixed — the same 12 bytes), with a negative control proving the
# emulation valid. A per-region fingerprint + uploading each platform's HTML
# turned "the documents differ" into a one-diff answer. Both cheap instruments
# worked on first use; both were reached for only after the guessing.

# ─── PROCEDURE: process state before testing fixes ───
STEP_1 identify processes holding exclusive resources (SQLite locks, file locks, ports)
       REQUIRED: query by what actually references the resource, not just
       process name. macOS:
         - file/db lock holder: `lsof <locked-path>` (or `lsof <db>-wal`)
         - port holder: `lsof -nP -iTCP:<port> -sTCP:LISTEN`
         - by command-line pattern: `pgrep -f '<pattern>'` (PIDs ONLY),
           then confirm each PID with `ps -p <pid> -o comm=`. NEVER add
           `-l` to `-f` on macOS — BSD pgrep's `-l -f` prints the FULL
           argv (same secret leak as `pgrep -af`; see
           platform-constraints.md macOS CORRECTION 2026-06-11, which
           this line previously contradicted). `-f` matches full argv,
           so generic substrings false-positive on /opt/homebrew paths —
           the per-PID `comm=` check is mandatory before concluding.
       All Python here is `python3` — there is no python/pythonw split.
       # [WINDOWS-ONLY — inactive on macOS]: prior host used pwsh
       #   `Get-CimInstance Win32_Process | Where {$_.CommandLine -like
       #   '*<locked-path>*'}` and had to filter BOTH python.exe AND
       #   pythonw.exe (MCP servers ran pythonw); tasklist-by-name missed
       #   ad-hoc python.exe subprocesses holding the same locks.
STEP_2 kill the SPECIFIC PID that references the locked path (`kill <pid>`,
       `kill -9 <pid>` if it ignores SIGTERM) — never mass-kill a class.
       BEWARE `pgrep -f <script> | head -1`: a backgrounded run has BOTH a
       launcher/wrapper process AND the actual worker matching the same
       pattern; `head -1` may grab the WRAPPER. Killing it leaves the worker
       running (and vice-versa). After a kill, CONFIRM the intended target is
       gone (re-`pgrep`; for a writer, confirm its output STOPPED advancing) —
       don't trust the kill's exit code. (2026-06-22: killed PID 28923, the
       recall_recovery launcher wrapper; the worker 28929 kept running +
       writing — only a row-count recheck revealed the run never stopped.)
STEP_3 THEN test the fix

# ─── PROCEDURE: process works in shell but fails when spawned by parent X ───
# (MCP spawn, systemd, Docker exec, CI runner, scheduled task — the failure is in the
# SPAWN CONTEXT, not the program; speculating about the program burns hours.)
STEP_1 capture full spawn context from the failing parent — env, cwd, sys.argv,
        console handles (Windows: GetConsoleWindow, GetStdHandle). Dump to a log.
STEP_2 capture the same context from a known-working parent (your shell).
STEP_3 diff the two. First signals: PATH (missing toolchain dirs), env-count delta,
        cwd, spawn duration (multi-second Popen = loader hunting for DLLs).
STEP_4 inspect the binary's dependencies BEFORE guessing about behavior:
        Windows `objdump -p exe | grep "DLL Name"` / `dumpbin /dependents`;
        Linux `ldd`; macOS `otool -L`. A dep missing from the failing parent's
        PATH/load-path IS the root cause (0xC0000139 / "library not loaded" /
        "cannot open shared object" = loader failure; no program code ran).
FORBIDDEN: changing wrapper code, build flags, or program logic before the env diff.
FORBIDDEN: hypothesizing about the program (protocol version, stdio EOF, shutdown
           handling) without first reading the exit code and dependency list.
# WHY: 2026-04-26 code-graph MCP — ~15 turns of disproven hypotheses; env diff +
#      objdump would have found libwinpthread-1.dll in 5 minutes.
# Full: incidents#2026-04-26-code-graph-mcp-spawn-context

# ─── PROCEDURE: config-identical instances behaving differently ───
# Fires when two+ instances that are byte-identical in config (replicas,
# multi-AZ, sibling CloudFront distributions, load-balanced servers, A/B arms)
# produce DIFFERENT behavior. The variable is almost never the instance — it is
# the INPUT each instance received (client routing, source IP, headers, which
# edge/PoP, which shard, IP protocol).
STEP_1 do NOT modify the instance (no redeploy, toggle, re-associate, recreate)
        yet — that's a fix attempt before diagnosis, and on a config-identical
        instance it is almost always a no-op.
STEP_2 read each instance's OWN telemetry of the input it judged — WAF
        get_sampled_requests ClientIP, ALB/access logs, the request + headers the
        instance actually saw — NOT your client's HTTP response code.
STEP_3 compare the inputs across instances. The behavioral difference tracks an
        input difference (different source IP, route, protocol), not the instance.
FORBIDDEN: inferring "instance X is broken" from your client's response codes
            when instances are config-identical. A response code reflects the
            whole client→instance path (DNS, routing, VPN split-tunnel, IPv4/IPv6),
            not the instance's correctness.
## 2026-07-26-prose-variants-example-labs-handbook-claim-desir
<a id="2026-07-26-prose-variants-example-labs-handbook-claim-desir"></a>

# WHY (prose variants): 2026-07-26 Example Labs handbook — the claim "`desired_count = 1`
# is what makes SQLite-on-EFS safe" was refuted by our own BiFrost incident (corruption on
# EVERY restart, i.e. even single-writer). It sat in THREE files: HANDBOOK.md §7,
# constraints.md, and roads.md's R2 app contract. Fixing only the one I noticed would have
# left two docs asserting the refuted version — and a reader hitting roads.md (the one an
# implementer actually follows) would have gotten the wrong answer. Grepping the token
# `desired_count` found all three in one pass.

## 2026-07-05-caf-reconciler-revocation-suppression-class-revo
<a id="2026-07-05-caf-reconciler-revocation-suppression-class-revo"></a>

# WHY: 2026-07-05 CAF reconciler revocation-suppression class — a REVOKED enrollment was
#      silently dropped at 5 differ prechecks (conflicting-duplicate, cross-program
#      collision, invalid-codename, unknown-gate + one more); Phase A fixed 1 site by
#      example, a 26-agent red-team found the other 4 one at a time. The fix that ended the
#      recurrence was NOT more grepping — it was an exhaustive `test_INV1` (192-combo
#      cross-product) that fails on any suppression path, plus an INVARIANTS.md stating the
#      property forward. Mutation-verified: reverting any one exemption re-fails the test.
#      Pairs with verify-effectiveness (property/exhaustive testing) — that rule covers HOW
#      to test a class; this STEP is the "hunt the class, don't fix the instance" trigger.

## 2026-06-12-qm-dev-waf-enforcing-config-byte-identical-enfor
<a id="2026-06-12-qm-dev-waf-enforcing-config-byte-identical-enfor"></a>

# WHY: 2026-06-12 qm-dev "WAF not enforcing" — config byte-identical to enforcing
# siblings; TWO fix attempts (redeploy + disassociate/reassociate toggle, both
# no-ops) + a drafted AWS support case before reading get_sampled_requests
# ClientIP showed the WAF correctly ALLOWED an allowlisted split-tunnel VPN egress
# IP — no bug. Full: memory waf-cloudfront-testing-gotcha.md.

# ─── PROCEDURE: before deriving a submission/format/protocol CONTRACT from source ───
# Fires when the question is "how does X's SUBMISSION / OUTPUT-FORMAT / WIRE-PROTOCOL
# work" (a CONTRACT) — distinct from "what does this code DO" (behavior, where source
# IS truth, above). For a CONTRACT the authoritative sources are (a) the PROVIDED
# validator/linter/dry-run and (b) a KNOWN-GOOD WORKING EXAMPLE — NOT reading the
# framework's own source and inferring.
STEP_1 does the system ship a validator/checker/conformance tool (a `validate`
        subcommand, a schema linter, `--dry-run`, a sample test)? RUN IT FIRST —
        it names contract violations in one call.
STEP_2 find a KNOWN-GOOD working example (a passing submission, a scoring notebook,
        a reference request/response) and replicate its EXACT shape.
STEP_3 ONLY THEN read framework source, and only to explain a discrepancy the
        validator/example surfaced.
FORBIDDEN: burning real attempts (submissions, deploys, paid API calls) on a
            contract derived from framework-source inference when a validator OR a
            known-good example was available.
## 2026-07-05-kaggle-jed-2-burned-submissions-2-sessions-infer
<a id="2026-07-05-kaggle-jed-2-burned-submissions-2-sessions-infer"></a>

# WHY: 2026-07-05 Kaggle JED — 2 burned submissions + ~2 sessions inferring the
# gateway submission contract from templates.py / *_gateway.py; the SDK's own
# `aicomp validate redteam` named the bug (a phantom fallback import) in ONE call,
# and one pull of a scoring notebook settled the shape. Source is truth for
# BEHAVIOR; the validator + a working example are truth for a CONTRACT.


## 2026-07-26-mcp-infra-saw-failed-main-terraform-apply-02-54
<a id="2026-07-26-mcp-infra-saw-failed-main-terraform-apply-02-54"></a>

  # WHY: 2026-07-26 mcp-infra — saw a failed `main` Terraform apply at 02:54,
  # labelled it "pre-existing, worth watching", and proceeded to grade the
  # session's work (scoring deploy-completeness a B). The real cause (an org SCP
  # denying an untagged lambda create) surfaced only ~40 min later when a SECOND
  # apply — my own PR's — failed the same way. In between, four PRs merged green
  # onto a pipeline that could not deploy anything. The first failure's log said
  # exactly what was wrong the whole time.
  # COROLLARY: the first red signal is also the CHEAPEST to attribute — one
  # failure has one plausible cause; by the third they interleave (a state-lock
  # error masked the SCP denial for 40 minutes).

---

## 2026-07-31-emitted-string-drift
<a id="2026-07-31-emitted-string-drift"></a>

Reverting a security-write consent gate to advisory (claude-config #1818). The
mechanism change was correct and the doc-variant hunt was actually RUN — four `.md`
sites asserting the removed gate were found and fixed in the same PR (`SECURITY.md`,
`ARCHITECTURE.md`, `README.md`, `projects/*/CLAUDE.md`).

**What the hunt missed.** The hook's OWN EMITTED STRING. `security-write-confirm.py`
kept printing, at every security write:

    Per the security-confirmations rule this requires explicit approval of the
    exact action and target before execution.

False the moment #1818 merged, and in the single most-read place — the one line a
human sees at the moment of the write. Worse than a stale doc: an advisory that
claims something is holding the call makes the operator infer a gate exists and stop
reading the target, and reading the target was the ONLY wrong-target defense left
after the gate was removed. Cost a second PR (#1819).

**Why the hunt missed it.** I grepped `--include='*.md'`. The claim's last copy lived
in a Python f-string, so the doc-set sweep could not see it by construction. STEP_6's
"every doc in the set" reads as documentation; a control's runtime message is
documentation with a much shorter path to a human than any README.

**The check.** After changing what a control DOES, grep the control's own source for
strings asserting what it does — `grep -n 'requires\|must\|will block\|approval'
<the changed file>` — not just the `.md` set. Then pin it: #1819 added
`test_advisory_text_does_not_claim_approval_is_required`, asserting on the RENDERED
output (so the test can safely hold the forbidden phrases as literals without
self-matching, per tdd-mutation-testing item 19). Mutation-verified: restoring the old wording
fails exactly that one test.

**Generalises to:** any artifact that emits prose about its own behaviour — a hook's
systemMessage, a CLI's `--help`, an error message naming a policy, a banner. Changing
the behaviour without changing the string ships a confident lie at the point of use.


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-08-29 — emit the discriminating FIELD instead of forming a third hypothesis
<a id="2026-08-29-emit-the-discriminator"></a>

Two mechanisms from one session, both cheap, both reached only after the guessing.

**1. A collapsed error path costs more than the field that would split it.** An
importer lane reported one flat string for several distinct causes — a multi-exception
`except` tuple whose handler formatted a generic "failed" message. Four hours and
three wrong fixes went into reasoning about which cause it was. Adding
`safe_details={"error_type": type(exc).__name__}` named `ValueError` on the very next
run and ended it.

The generalisation: when an error path collapses several causes into one string, STOP
hypothesising and emit the discriminator — `error_type`, the failing assertion's name,
the resolved target, the gate that rejected. A structured field on the error path beats
another round of reasoning about it, and it is usually a one-line edit to code you are
already looking at. Same family as the parent rule's "read the complete error body,"
extended to the case where the body is complete and *deliberately* uninformative.

**2. Two instruments that never move together are not measuring the same thing.** A
release-check probe kept passing while the real lane kept failing, unchanged across
fixes. I treated the divergence as noise around whichever hypothesis I held. It WAS
the finding: the probe and the lane differed in their origin pin, so they were
exercising different code paths — the same class as
`incidents/verify-effectiveness.md#wrong-artifact-verification` (verifying against the
wrong artifact), but with the tell available much earlier, because a probe that cannot
reproduce a live failure has already told you it is not the same measurement.

Check, before forming another theory about the subject: diff the two call paths for
their FIRST difference — origin, region, account, identity, base revision, installed
set. One of those is why they disagree.

## aws-cross-component-incompatibilities-are-documented-in-our-topic

```
WHY: AWS cross-component incompatibilities are documented in OUR topic files, not
     AWS docs; the failure mode is FAILING TO RECALL. 3+ hours burned re-finding
     CloudFront-OAC 2026-05-15. Full: incidents#2026-05-15-cloudfront-oac-rediscovery
```

## bedrock-added-2026-07-20-govcloud-bedrock-accessdenied-re

```
WHY (Bedrock added 2026-07-20): GovCloud Bedrock AccessDenied → re-derived the entire
     two-partition enablement procedure (~10 turns + a wrong retired-console pointer
     given to the user) that topics/aws-govcloud-bedrock.md had documented 2 days
     earlier. An access-denial "looks like IAM, not infra" — that framing is why the
     search was skipped; hence the scope line now names access/permission errors.
```

## step-4-2026-06-19-proteus-read-5-enforcement

```
WHY (STEP_4): 2026-06-19 Proteus — read 5 enforcement layers (SG/NACL/route/EIP/prefix-list),
     ALL said allow, circled for many turns on a config-vs-dataplane paradox; Reachability
     Analyzer named `VPC_BLOCK_PUBLIC_ACCESS_ENABLED` in ONE call. BPA (block-bidirectional)
     sits above SG/NACL/route and is invisible to per-resource reads. See aws-infra.md BPA gotcha.
```

## posture-scope-step-5-added-2026-07-26-a

```
WHY (POSTURE scope + STEP_5 added 2026-07-26): a "is X reachable?" question where
     NOTHING had errored — so the procedure felt inapplicable and STEP_1's
     memory_search was skipped. THREE successive wrong architecture claims in ~10 min,
     each from a partial OBSERVED surface (DNS, then uncontrolled curl status codes,
     then response headers); one grep + the repo's CLAUDE.md settled all three, and
     agent-memory ALREADY documented it.
     Full: incidents#2026-07-26-mcp-infra-reachability-posture
```

## 2026-07-26-globalprotect-4-hypotheses-refuted-in-one

```
WHY: 2026-07-26 GlobalProtect — 4 hypotheses refuted in one session; 3 died to ONE grep
of the Jul-22 working log sitting in the same directory. Full: incidents#2026-07-26-globalprotect-working-baseline
─── PROCEDURE: a defect that only appears in an environment you do not have → moved to rules/incidents/diagnose-before-fix.md (2026-07-30 descope) ───
```

## 2026-05-02-sqlite-wal-lock-false-trail-killed

```
INCIDENT 2026-05-02 SQLite-WAL-lock false-trail: killed 6 MCP `pythonw.exe`
processes; real holder was a hung `python.exe` background script (wrong class,
broke the session's MCP). Query by what REFERENCES the path, not by name.
Full: incidents#2026-05-02-sqlite-wal-lock-false-trail
```

## 2026-05-13-full-incidents-2026-05-13-code

```
INCIDENT 2026-05-13. Full: incidents#2026-05-13-code-graph-edit-before-read
"READ" means the Read TOOL on the EXACT absolute path being edited:
  - Reading the SAME file content at a DIFFERENT path does NOT count —
    main-checkout Read does not license a worktree-path Edit (same
    commit, same bytes, still refused).
  - Bash views (sed -n / cat / grep) did NOT satisfy it as of v2.1.174
    (2026-06-11, two refusals in one session). NOTE: CHANGELOG v2.1.89
    claimed Bash-viewed files became editable without Read — treat that
    claim as stale/not-applicable; Read-tool the exact path before Edit.
  - WRITE to an EXISTING file (incl. a reused /tmp/claude scratch name) needs
    a prior Read too — same gate as Edit. For throwaway scripts use a FRESH
    unique name so the gate never fires (2026-06-13 48h transcript review:
    80 of 107 read-before-edit failures were Write-overwrites of existing
    files, many reused temp-script names; CORROBORATED 2026-06-14 — a 14-day
    transcript mine measured read-before-edit as the #1 self-inflicted friction
    class: 144 blocks [126 "not been read" + 11 "modified since read"] vs only
    2 user-corrections across 25,368 turns, i.e. nearly all avoidable by a fresh
    unique scratch name). Auto-read via a hook is NOT
    possible — the gate is enforced in the harness BEFORE any PreToolUse hook.
```

## reading-source-costs-30-90s-a-shipped-wrong-diagnosis

```
WHY: reading source costs 30-90s; a shipped wrong diagnosis is high-cost and
     asymmetric. INCIDENT 2026-05-13 PR #515/#516 (wrong mechanism shipped, then
     source-cited revision). Full: incidents#2026-05-13-code-search-upstream-pr-515-516
```

## 2026-07-31-superplan-run-4-recurrences-in-one

```
WHY: 2026-07-31 /superplan run, 4 recurrences in ONE plan: a Terraform edit written for a
CI role that is SCP-denied (applied out-of-band via SSO admin instead); a "Generate"
phase with no invocable path free of production side effects; tests green locally but
failing under the CI job's actual keyless environment; a passing test whose own stated
mechanism was factually wrong. All four checked EXISTENCE, none checked APPLYABILITY.
```
