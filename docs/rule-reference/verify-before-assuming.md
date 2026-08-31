@rule verify_before_assuming
@version 2026-06-10
@scope every MCP capability claim, every "unavailable" claim, every destructive MCP call, every recommendation with assumptions, every security audit dispatch, every LLM-decision framing, every repo target

# Pointer shorthand: "Full: incidents#anchor" = rules/incidents/verify-before-assuming.md
# (full incident narratives + per-FAILURE citations live there).

# ─── INVARIANTS (always-true) ───

INVARIANT never_assume_MCP_capability_without_ToolSearch
  # WHY: our MCP servers are custom implementations with write tools off-the-shelf
  #      versions lack. 34 friction events in 30 days.

INVARIANT unavailable_claims_require_failed_check_not_assumption
  # WHY: 0 hits without a real check is usually a detection bug. Skip path is always
  #      cheaper than verify path; that's why verify must be mandatory.

INVARIANT destructive_MCP_calls_require_pre_call_inspection
  # WHY: tools without disambiguators (name-only params) can match arbitrary records.
  #      code-search delete_project (2026-04-17) nuked 97.7MB instead of empty skeleton.

INVARIANT state_load_bearing_assumptions_alongside_recommendations
  # WHY: prior-session context leaks silently; sbom-rs airgap assumption (2026-04-19)
  #      reshaped 6 recommendations invisibly.

INVARIANT security_audit_scope_defaults_to_full_coverage
  # WHY: negative findings ("no exposure") are only as strong as coverage. Sampled
  #      scope masquerades as exhaustive in the user's reading.

INVARIANT LLM_output_is_suggestion_not_decision
  # WHY: without measured accuracy on labeled data, "determines" overstates capability.

INVARIANT verify_repo_target_before_push_pr_merge
  # WHY: 18 friction events in 30 days. Fork repos + gh CLI default to upstream
  #      without --repo flag.

# ─── PROCEDURE: MCP tool discovery ───
STEP_1 ToolSearch for the MCP server's tools BEFORE claiming a capability doesn't exist
STEP_2 If tool not found → ask user. NEVER declare "out of scope" or "not possible"
STEP_3 Check existing app registrations + permissions before claiming API can't do X
STEP_4 Example CrowdStrike MCP supports read AND write (60+ tools) — NOT default falcon-mcp

# ─── PROCEDURE: unavailable claims ───
| Claim | Required evidence |
|---|---|
| "MCP server X is unavailable" | ToolSearch returned empty AND not in `<available-deferred-tools>` |
| "This API doesn't support X" | Checked code-search indexed docs OR Firecrawl live docs |
| "No tool exists for this" | ToolSearch with `select:` query returned empty |
| "This step can be skipped" | Skip condition defined in skill is actually met (verified) |
| "MCP server's API was rewritten / old tools replaced" | ToolSearch with `select:<old_tool_name>` returned empty for each old tool. The deferred-tools list in system reminders is a SAMPLE, not the complete API surface — never used as evidence of removal. |
| "This Claude Code behavior can't be configured locally / is web-UI-only" | Checked the settings.json schema (json.schemastore.org/claude-code-settings, or the /update-config skill's embedded schema) for a matching key. A support article describing a web toggle is NOT evidence the setting lacks a local key. |
# WHY (settings-configurability row): 2026-06-11 Fable 5 fallback posture —
#   Full: incidents#2026-06-11-settings-configurability-row-fable-5-fallback-po

# ─── PROCEDURE: destructive MCP operations (delete/drop/remove/archive/revoke/deprovision) ───
STEP_1 Read the tool's implementation or docstring BEFORE first call
STEP_2 Identify disambiguator. IF name-only (no hash/id): confirm with user
STEP_3 Probe on a safe dummy target first. Verify which match was killed.
STEP_4 FORBIDDEN: "just try it on the real target" as a dry-run
STEP_5 After call: verify on-disk state with ls/equivalent. success=true ≠ right thing happened.

# ─── PROCEDURE: recommendations with assumptions ───
STEP_1 Identify constraints the recommendation depends on (network, runtime, offline, scope, auth)
STEP_2 State each constraint explicitly in the same breath as the recommendation
STEP_3 Ask user to confirm if any non-obvious assumption is load-bearing
STEP_4 FORBIDDEN: carrying prior-session context silently into current recommendations

# ─── PROCEDURE: security audit scope ───
DEFAULT: full coverage of target set
EXCEPTIONS (require explicit justification): (a) user requested sampled scope;
  (b) rate limits block completion (show the math); (c) sampled scope is a
  documented first-pass gate
FORBIDDEN: preemptively scoping to "top N" or "representative sample" without approval

# ─── PROCEDURE: LLM-backed feature framing ───
Describe as: "proposes" / "suggests" / "drafts" / "outputs evidence"
FORBIDDEN: "determines" / "decides" / "ensures" / "verifies" without measured accuracy
REQUIRED: human or gated system is the decision-maker
REQUIRED: structured output with citations, not prose claims
REQUIRED: auto-apply only after shadow-mode accuracy measurement ≥ target
ASYMMETRIC BAR: higher blast radius (claiming not_affected on real CVE) → higher confidence
ASYMMETRIC BAR: default toward "we don't know" over "it's fine"

# ─── PROCEDURE: repo target verification ───
STEP_1 git remote -v + pwd  # verify current directory matches intended repo
STEP_2 verify target remote correct (not upstream fork, not wrong org)
STEP_3 for multi-repo ops: confirm repo list with user before starting

# ─── PROCEDURE: before citing vendor authority OR asserting vendor-system behavior ───
# Fires on "Anthropic recommends X", "AWS docs say Y", "per their best practices" —
# AND on any CONFIDENT ASSERTION of how a third-party system behaves as fact, even when
# NOT phrased as a citation: IAM / policy-evaluation semantics ("aws:PrincipalArn is the
# session ARN"), deploy-pipeline mechanics, API response shapes, condition-key
# resolution, default behaviors. A bare "X behaves like Y" about a vendor system IS a
# vendor-authority claim; the "the docs say" framing is NOT required to trigger.
STEP_1 verify against the VENDOR'S source — not a local rule/topic/memory that cites
       them. Libraries: Context7 official ID. APIs: indexed api-docs or live fetch.
       Vendor-behavior facts: the vendor's reference docs OR a 30s live test — AND
       cross-check any same-corpus KB / empirical entry already in front of you that
       would confirm or refute it (a verified prior result outranks your recollection).
STEP_2 quote the vendor's actual phrasing. If the local rule disagrees, the vendor
       wins AND fix the local rule in the same session.
STEP_3 IF un-verifiable against the vendor source → flag unverified, investigate first.
FORBIDDEN: stating "Anthropic recommends X" / "vendor Y says Z" by reading ONLY a
           local rule that cites them. Local rules are derivative; propagating
           without source-check propagates their bugs.
FORBIDDEN: asserting a vendor system's behavior as fact — in chat OR a shipped artifact
           — from training knowledge / first-principles reasoning without a 30s source
           check, ESPECIALLY when same-corpus evidence is already in front of you.
FORBIDDEN: citing a doc/KB/issue/article by its TITLE as evidence of a capability or
           procedure without reading the BODY. Titles state the question, not the
           answer — "Delete Expired PGP Encryption Keys in Edge Import" is a
           you-can't-delete-them article (CSOD KB 000016428).
FORBIDDEN: characterizing an artifact from an AGGREGATE or its METADATA when the
           content is one command away — a `diff --stat` line count read as "the work",
           a PR judged by its AUTHOR + TITLE, a file by its size, a run by its name.
           An aggregate is a SUMMARY OVER something, and it silently encodes whatever
           the baseline is: `git diff --stat origin/main..<branch>` on a branch cut
           from an OLD main reports everything main has GAINED since as the branch's
           deletions. Read the content (`git show <sha> --stat` per commit; `gh pr
           diff`) before any claim about what it contains.
# WHY (aggregate): 2026-08-01 /pr-fix — reported a worktree as holding "158 files /
#      12,219 deletions" of at-risk work; per-commit diffs showed 2 commits and the
#      rest was stale-base artifact. Same turn, called a bot PR a workflow rewrite
#      from author+title; `gh pr diff` showed one 10-line .pre-commit-config.yaml.
#      Both were single commands away. This is git-hygiene's inflated-diff guard
#      (orphan-ancestor tips, PR #972: 11,298 lines vs 76 real) hit on a REPORTING
#      surface rather than a shipping one.
# WHY (title-citation): 2026-06-12 — shipped that deletion step into a rotation runbook off
#      the title alone; body said unsupported. Cost a wrong user-action + PR #34.
# WHY: 2026-05-12 SKILL.md cap — local rule said "5,000 words"; canonical is "under
#      500 LINES"; almost reverted valid work. Full: incidents (2026-05-12 entry).
# WHY: 2026-06-11 aws:PrincipalArn — asserted an SCP exemption semantic BACKWARDS in
#   Full: incidents#2026-06-11-aws-principalarn-asserted-an-scp-exemption

GUARD pattern="filter out the successes / exclude the OK rows" using a status value you
  never ENUMERATED (`!= "success"`, `not in ("ok",)`, `WHERE status <> 'passed'`):
  REFUSE. An exclusion against a GUESSED value is a silent NO-OP when the data never
  emits it — the filter inverts and every row you meant to DROP is reported as a hit.
  It cannot fail loudly: the query succeeds and the output looks plausible. REQUIRED:
  `GROUP BY <the status column>` once to enumerate the ACTUAL domain, then match the
  FAILURE values POSITIVELY (`in ("failed","disconnected")`) so a NEW value is
  invisible rather than silently reported as a failure. NO EXCEPTIONS for a filter
  whose output you will report or alarm on.
  # WHY: 2026-07-28 mcp-infra #739 — excluded `"success"`; enumeration showed the only
  #   Full: incidents#2026-07-28-mcp-infra-739-excluded-success-enumeration
# WHY: 2026-06-11 aws:PrincipalArn — asserted a vendor IAM semantic BACKWARDS in chat AND
#   Full: incidents#2026-06-11-aws-principalarn-asserted-a-vendor-iam

GUARD pattern="we don't collect / don't have / aren't measuring X" (a GAP claim about OUR
  system, formed while reading a VENDOR doc or any external surface):
  REFUSE until you grep OUR repos, and grep WIDE. The failure is never a MISSING grep; it
  is one scoped to the module you already had in mind. REQUIRED: (a) grep the FIELD/RESPONSE
  NAME, not the endpoint path — paths get assembled by f-string and never appear as
  literals; the field (`api_keys`) always does; (b) search EVERY repo with `--include`,
  never one expected file — sibling `*_bundle/` dirs hide it; (c) before proposing "ingest
  and alert on X", grep the CAPABILITY verb (`put_metric_data`, `_emit`, `alarm`, `guard`)
  — twice the runtime already EXCEEDED the proposal. Same shape one layer up: a registry
  seeded by KEYWORD-GREPPING an index is a filter mistaken for a surface —
  enumerate-and-subtract, never filter-and-assume. And a detector whose ONLY input is one
  party's DESCRIPTION of a system (vendor docs) has recall bounded by that description and
  CANNOT report its own blind spot — reconcile against a structurally independent source
  (production telemetry / a live probe) or say plainly that none exists. NO EXCEPTIONS when
  the claim reaches the user or ships to a KB.
  # WHY: 2026-07-28 — FOUR false "we don't collect X" claims in ONE session, two graded
  #   Full: incidents#2026-07-28-four-false-we-don-t-collect

GUARD pattern="a DISCOVERY step whose target set is a LITERAL LIST you typed" — any
  `for r in repo-a repo-b repo-c`, hardcoded path array, or fixed account/region set,
  in ANY sweep that will be reported as coverage ("N stale branches", "all clear",
  "no dirty repos"):
  ENUMERATE FROM THE LIVE SOURCE INSTEAD (`gh repo list <org>`, the API's own listing,
  a glob of the real directory). A frozen list does not fail — it returns a clean,
  confident, WRONG answer, and it under-reports in exactly the direction that reads as
  good news. The literal list is also self-justifying: it contains everything you
  thought of, so reviewing it finds nothing missing.
  THE TELL IS OBEYING IT SOMEWHERE ELSE IN THE SAME TASK. Dynamic discovery is usually
  documented for ONE axis of a multi-axis skill; you follow it there and hardcode every
  other axis, because the rule named that instance and not the mechanism. When a task
  has several sweeps, apply it to ALL of them.
  CROSS-CHECK before reporting: does the dynamic count exceed the literal one? If yes,
  the literal list was the bug — say what it missed.
  NO EXCEPTIONS for a sweep whose output is a coverage or all-clear claim.
  # WHY: 2026-08-01 /pr-fix — a hardcoded 8-repo branch sweep returned "0 deletable";
  # live enumeration over the org's 30 repos returned 41 (24 in `azure-automations`, a
  # repo absent from the list). Same run, a repo-map-driven worktree scan found 15 of
  # 41 real directories. The skill states "never hardcode discovery lists" for PR
  # discovery ONLY — which is precisely why PR discovery was correct and the other two
  # axes were not. Prior precedents, same mechanism: /pull-repos #1082, /pr-fix #1085
  # (a 15-repo loop missed 31 of 43 authored PRs), /weekly-update Stream 1 — all
  # recorded in `skills/_shared/repo-map.md` and the KB, NEITHER of which loads
  # ambiently. That non-delivery is why this GUARD is here and not only there.

# ─── PROCEDURE: before claiming what your OWN CURRENT/DEPLOYED system does ───
# Fires on any characterization of "the latest method" / "our current pipeline" / "the
# deployed detector uses X" / "we compose A+B+C" — architecture, model choices, which
# arms/passes/stages run. This is the INTERNAL twin of the vendor-behavior procedure
# above: the same source-check discipline, applied to your own system instead of a vendor's.
STEP_1 grep the CURRENT entrypoint's ACTUAL call chain — the function the deployed path
       invokes, end-to-end (e.g. `judge()` → `BRT.invoke_model`, `adjudicate()` → which
       model, n_passes). The evidence is the code that runs, not a doc/ledger/summary that
       describes it.
STEP_2 distinguish "tried this session/historically" from "in the CURRENT method." A
       chronological method-ledger lists everything ATTEMPTED; the current method is the
       subset the live entrypoint still calls. An artifact removed in a prior version
       (`census_panel.py`, a deleted arm) is NOT a current component just because a ledger
       lists it co-equally.
STEP_3 a claim that survives a compaction boundary is a RECOLLECTION, not the record —
       re-grep before restating it. Cross-version conflation (treating a removed v2 arm as
       a v3 component) is the specific trap.
FORBIDDEN: characterizing the current/deployed method from a method-ledger, a prior doc's
           framing, or a compaction-summary recollection — without grepping the live
           entrypoint's call chain. Building a plan on the wrong method-characterization is
           a "shaky foundation" the user will (rightly) reject.
# WHY: 2026-06-22 credential-census v4 plan — claimed "the latest method uses a multi-model
#   Full: incidents#2026-06-22-credential-census-v4-plan-claimed-latest-method
FORBIDDEN: grepping the entrypoint in a checkout you have not FETCHED. Grep-the-source is
           necessary, not SUFFICIENT: a diagnosis from a tree 3 commits behind blamed a bug
           a PR had fixed 30 min earlier (2026-07-29, asserted 3x before refuting itself).
           `git fetch` first; for DEPLOYED state read the deployed artifact (Glue
           `ViewOriginalText`, the Lambda zip), never a file on disk.
# WHY: 2026-06-22 credential-census v4 (ledger-as-current-method) + 2026-07-29 stale-checkout
#      misdiagnosis. Full: incidents#2026-06-22, incidents#2026-07-29.
FORBIDDEN: characterizing current defaults/capabilities from a MODULE HEADER DOCSTRING or
           file-top comment — headers are the least-maintained doc surface (read first,
           updated last); the truth lives in the config block / the code that runs. And a
           flag that is only SET is not a capability: grep who CONSUMES it before calling
           the path an available fallback (loading ≠ usage).
# WHY: 2026-07-07 memory-search assessment — asserted stale defaults from a MODULE HEADER
#   Full: incidents#2026-07-07-memory-search-assessment-asserted-stale-defaults
# WHY: 2026-07-07 memory-search assessment — asserted a stack's defaults from a MODULE
#   Full: incidents#2026-07-07-memory-search-assessment-asserted-a-stack

# ─── GUARD: user-instructed research — priors are DISTRUSTED, claims trace to fetched sources ───
GUARD pattern="user said 'research this' / 'do research' / 'look it up' — and a training-data
  prior conflicts with, or fills a gap in, the fetched results":
  REFUSE to ship any dated / versioned / availability / pricing claim that does not trace to
  a source FETCHED THIS SESSION. A research instruction is an instruction to DISTRUST priors:
  running searches is not research — source-grounding every load-bearing claim is. A conflict
  between prior knowledge and a fetched result resolves TO THE FETCHED RESULT, or ships
  flagged as unverified — never silently resolved toward the prior. Prefer routing explicit
  research asks to /deep-dive (its evidence-grading enforces exactly this). NO EXCEPTIONS.
  # WHY: 2026-07-19 hardware-research — user said "Do research"; searches RAN but a
  #   Full: incidents#2026-07-19-hardware-research-user-said-do-research

# ─── PROCEDURE: before creating an index, build, or artifact ───
STEP_1 check the registry/list for existing instances FIRST:
       code-search list_projects (~/.claude_code_search/projects/); code-graph
       list_projects; cargo target/; existing index dirs for stored vectors;
       MCP servers: mcp-catalog.json + managed-mcp.json + the DEPLOYED ECS
       services (`aws ecs list-services`) — an MCP may already be built AND
       deployed.
STEP_2 IF existing artifact at the canonical location → use it. Custom paths bypass
       project registries AND the production workflow's validation gates.
       For an already-DEPLOYED MCP: register the REMOTE client
       (`claude mcp add --transport http <name> https://<svc>.mcp.example.internal/mcp`),
       do NOT build/scaffold a local stdio copy (venv, launcher, key).
STEP_3 IF genuinely missing/stale → use the documented skill (/index-repo), not a
       hand-rolled script that bypasses its hard-gate validation.
FORBIDDEN: writing a hand-rolled `index_*.py` or `build_*.py` script that targets a
           custom-storage path without first checking whether the canonical
           version exists.
FORBIDDEN: scaffolding a LOCAL stdio MCP (venv/launcher/Keychain key) for a server
           that is already deployed — register the remote client instead.
# WHY: 2026-05-02 PSM-full custom-path index — 1450s + ~$0.50 wasted; already indexed
#   Full: incidents#2026-05-02-psm-full-custom-path-index-1450s-0-50-wasted-alr

# ─── PROCEDURE: before concluding a setting/policy/config is NOT present ───
STEP_1 memory_search the component + "managed settings|policy|registry|config" FIRST —
       we often already document the exact location.
STEP_2 enumerate ALL platform locations before concluding absence: per-OS file paths
       (deprecated + current); registry HKLM AND HKCU + ALL product-family key
       variants + WOW6432Node; remote/server-managed (no local artifact); env vars
       Process AND User AND Machine scope.
STEP_3 MULTI-APP products: check BOTH apps' config surfaces — one app's policy can
       drive behavior attributed to the other.
STEP_4 ONLY after STEP_1-3 are empty → "not configured", citing the locations checked.
FORBIDDEN: concluding "not configured / doesn't use X" from a SUBSET of locations.
# WHY: 2026-06-07 forceLoginOrgUUID — 3 wrong conclusions, 3 user corrections.
#      Full: incidents#2026-06-07-forceloginorguuid

# ─── PROCEDURE: before presenting a vendor feature as available/enable-able → moved to rules/incidents/verify-before-assuming.md (2026-07-30 descope) ───

# ─── PROCEDURE: before committing to a multi-hour retry/recovery plan → moved to rules/incidents/verify-before-assuming.md (2026-07-30 descope) ───

# ─── USER OVERRIDE POLICY ───
# Assumption-verification is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="this MCP obviously can't do X" or "it's clearly read-only":
  REFUSE to skip ToolSearch. Our MCPs are custom. Run ToolSearch anyway. NO EXCEPTIONS.

GUARD pattern="the API was rewritten" or "old tools are gone" or "version bump replaced X with Y":
  REFUSE without ToolSearch on the OLD tool names (`select:<old_tool_name>` each).
  Major-version bumps are typically ADDITIVE; the deferred-tools list is a sample.
  Only an empty ToolSearch result is evidence of removal. NO EXCEPTIONS.

GUARD pattern="0 hits means it's not there" or "no results, confirmed absent":
  REFUSE. 0 hits on a plausible phenomenon = detection bug. Sample 3-5 known-positive
  candidates. NO EXCEPTIONS.

GUARD pattern="my script/grep says this cited path doesn't exist, so the reference is broken"
  (an AD-HOC audit of skills/docs, run WITHOUT invoking /audit-skill):
  REFUSE the broken-reference verdict until the path is resolved against the
  KNOWN-EXTERNAL-PATHS REGISTRY: `skills/audit-skill/known-external-paths.yaml`.
  Skills legitimately cite SIBLING repos and user-data dirs
  (`~/Documents/knowledge-base/`, `~/Documents/obsidian-infra/`, `~/Documents/api-docs/`,
  `~/Documents/GitHub/<repo>/`). A resolver that searches only THIS checkout reports
  every one of them as phantom. Absence from this repo is not evidence of nonexistence
  (see the `unavailable_claims_require_failed_check_not_assumption` invariant).
  REQUIRED, in order: (1) match the cited path against the registry — a hit means
  NOT-a-finding; (2) for a registry hit, `test -e` the real path to distinguish
  "reference is fine, repo not cloned on this host" (a PROVISIONING gap — clone it)
  from "genuinely missing"; (3) for anything still unresolved, read the citing
  SKILL.md — the skill may already carry a prerequisite gate that fails loudly with
  clone instructions, in which case the skill is CORRECT and needs no change.
  PREFER `/audit-skill` over a hand-rolled resolver: its D3a/D3b checks consult the
  registry by construction, so this class cannot fire. NO EXCEPTIONS for a
  broken-reference finding that will be reported to the user.
  # WHY: 2026-07-24 corpus review — a hand-rolled resolver reported 13 broken script
  #   Full: incidents#2026-07-24-corpus-review-a-hand-rolled-resolver
  # WHY: 2026-07-24 — a hand-rolled resolver reported 13 broken refs; 12 FALSE, the
  # 13th a provisioning gap. Full: incidents#2026-07-24-hand-rolled-resolver

GUARD pattern="this API/endpoint failed, so the capability is unavailable / blocked / needs vendor (GCS/support) enablement":
  REFUSE to generalize from ONE endpoint. ENUMERATE every API surface that could
  provide the capability (OpenAPI FULL path list + scopes catalog), test the
  alternatives. Modern and legacy products coexist under the SAME scope. NO EXCEPTIONS
  for "capability unavailable / file a vendor ticket" conclusions.
  # WHY: 2026-06-02 CSOD transcript — ~15 turns + 3 pushbacks; the v1 surface worked.
  #      Full: incidents#2026-06-02-csod-transcript

GUARD pattern="just try the destructive call, let's see what happens":
  REFUSE. Destructive tools without disambiguators match arbitrarily. Probe a safe
  target first. NO EXCEPTIONS.

GUARD pattern="the user already knows the context" or "I don't need to state the assumption":
  REFUSE. State it anyway. Prior-session context leaks silently. NO EXCEPTIONS for
  load-bearing constraints.

GUARD pattern="top 30 is representative" or "sampled scope is good enough":
  REFUSE unless user approved, OR rate math shows impossibility, OR documented
  first-pass gate. Default full coverage. NO EXCEPTIONS.

GUARD pattern="the LLM will determine X" or "LLM decides":
  REFUSE. Reframe as "LLM proposes X; caller validates." Structured output with
  citations; decision goes to human or gated system. NO EXCEPTIONS.

GUARD pattern="I know this is the right repo" or "checked yesterday":
  VERIFY with git remote -v + pwd NOW. Session memory is not machine-checkable.
  NO EXCEPTIONS for push/PR/merge operations.

GUARD pattern="our rules say Anthropic recommends X" / "skill-standards.md cites the vendor as saying Y":
  REFUSE propagating without source-check (Context7 / indexed docs). If the local rule
  cites the vendor incorrectly, FIX it in the same session. The vendor's source wins.
  NO EXCEPTIONS for claims attributed to any queryable vendor.

GUARD pattern="this is just how AWS / <vendor> works" or asserting IAM/policy/API/deploy
  behavior as fact with no citation (a confident "X behaves like Y", not "the docs say"):
  REFUSE to ship the claim — chat OR artifact — on training-knowledge confidence. A
  vendor-behavior assertion needs the SAME source check as an explicit citation: verify
  against the vendor doc or a 30s live test, and reconcile against any same-corpus
  empirical evidence already retrieved. NO EXCEPTIONS for load-bearing vendor-behavior
  claims. # WHY: 2026-06-11 aws:PrincipalArn shipped backwards (see PROCEDURE above).

GUARD pattern="the doc says it's supported in the CLI / available on all plans":
  EVALUATE reachability, not just capability. The doc describes the platform SUPERSET;
  our deployment is a SUBSET. Verify the enable surface is reachable before calling a
  feature "available". NO EXCEPTIONS for admin-gated or research-preview features.

GUARD pattern="the API says this org/tenant/account can't do X" — concluding a CAPABILITY
  is absent from an error that is really about WHICH org the credential binds to
  ("not supported for this organization type", "not enabled for this tenant", wrong-account):
  NAME THE ORG THE KEY BINDS TO BEFORE GRADING THE CAPABILITY. When a vendor has TWO admin
  surfaces (Anthropic platform.claude.com `sk-ant-admin01-` vs claude.ai `sk-ant-api01-`;
  AWS commercial vs GovCloud; M365 tenants), a key CANNOT cross between them — so a
  cross-org probe returns a well-formed error that reads as a product verdict. The trap is
  NAME COLLISION: two orgs can share a DISPLAY NAME and differ only by UUID, so nothing in
  the response says "wrong org."
  REQUIRED before any "unavailable / unsupported / non-closeable" claim: resolve the key's
  org id (`get_organization` / `sts get-caller-identity`), confirm that org OWNS the endpoint
  family, then re-probe with the OTHER surface's key. Status codes are NOT interchangeable:
  `400 "not supported for this organization type"` = WRONG ORG; `403` = right org, missing
  SCOPE; `401` = wrong key CLASS; `404` = absent or wrong auth. NO EXCEPTIONS for a
  capability verdict that ships to the user or a KB entry.
  # WHY: 2026-08-01 — probed the Enterprise-only Spend Limits API with the CONSOLE key, got
  # 400, published "not available to us / NON-closeable" into TWO KB topics. Re-probe with
  # the claude.ai key: 403 (missing `read:spend_limits`) — live all along. Our own
  # `reconcile_observed.py::classify_probe()` already mapped that 400 to
  # ORG_TYPE_UNSUPPORTED "Console-vs-Enterprise, not a gap" — an ADHERENCE gap, not a
  # knowledge gap.

GUARD pattern="I've now retracted the same CLASS of capability claim twice this session (e.g. 'X can't reach Y' → corrected → 'X can't do Z' → corrected)":
  STOP inferring from partial surfaces. The SECOND retraction of a capability/config
  verdict is the signal that you are reasoning from fragments (screenshots, one profile,
  docs for a DIFFERENT product mode) instead of the authoritative surface. Do NOT emit a
  third verdict — instead, either (a) read the primary surface directly (the actual admin
  UI, the live config, the source), or (b) ASK the user to show/point at it. NO EXCEPTIONS
  after two same-class retractions.
  # WHY: 2026-07-23 3P web-search — 5 retractions in one session (no-custom-connector →
  #   Full: incidents#2026-07-23-3p-web-search-5-retractions-session-no-custom-co

GUARD pattern="I checked the obvious location, X isn't configured" OR "the user says X is configured but my probe found nothing":
  REFUSE the absence conclusion. memory_search FIRST, then enumerate ALL locations
  (files per-OS + HKLM/HKCU + key variants + WOW6432Node + remote-managed + env all
  scopes + BOTH apps). When the USER asserts a config exists, the PROBE was
  incomplete — locate exhaustively or ASK; do NOT imply they're wrong. NO EXCEPTIONS.

GUARD pattern="skip claim in step N of skill, I know it doesn't apply":
  REFUSE. A skip claim in step N requires the same evidentiary standard as step 1.
  Context fatigue is not evidence. NO EXCEPTIONS.

GUARD pattern="I verified the finding against the artifact under review" WHEN that artifact is
  your OWN transcription / paraphrase / summary of the original (a review .txt you wrote, a fixture
  you authored, a condensed copy):
  REFUSE — verifying a finding against your own paraphrase is CIRCULAR (you check the copy against
  itself, and a copy that dropped the detail the finding is about will "confirm" it). Verify against
  the ORIGINAL — the actual file, the live system, the source code, the real rendered output — not
  the copy you made of it. This holds double when the verification is fanned out to subagents: they
  inherit your artifact as ground truth and launder the circularity at scale. NO EXCEPTIONS for a
  load-bearing finding that will ship.
  # WHY: 2026-07-08 security-brief assessment — 2 findings shipped-then-retracted off my own
  # compressed transcription. Full: incidents#2026-07-08-paraphrase-as-review-artifact

GUARD pattern="I grepped for it and got 0 hits, so the content didn't land" — OR the
  UNIQUENESS direction, "I grepped the OTHER side for my lines and got 0 hits, so this
  content is unique to me / is unshipped work" — WHEN the SEARCH
  STRING came from your own summary/PR-body/commit prose rather than the committed text:
  REFUSE the absence conclusion. MIRROR IMAGE of the circular-verification guard above: there
  the ARTIFACT is your paraphrase (false PASS); here the artifact is CORRECT (origin/main, the
  deployed file) but the PROBE is your paraphrase (false ZERO on present content). The right
  artifact does not save you from an invented pattern.
  REQUIRED: derive every probe string from the SOURCE — `git show <ref>:<f> | grep -F "<line
  copied from the diff>"` — or prefer a string-free check (`--numstat`, `cmp`, byte-length,
  entry count). ALSO: `grep -c` exits 1 on zero, so `&&` silently skips the rest — use
  `|| true`; never read a chain that died early as "content missing."
  ON PROSE, PREFER A SEMANTIC MARKER OVER `grep -F` ENTIRELY. Two sides of a doc can carry
  the SAME lesson in REWORDED form, so a literal match on one side's phrasing returns 0 for
  content that is fully present — and the more the other side EDITED (tightened, extended),
  the more certain the false zero. Probe an identifier the rewording cannot touch (an issue
  number, a PR ref, a symbol, a dated marker) and compare LINE COUNTS; a side with strictly
  more content is not the side missing work.
  NO EXCEPTIONS for a post-merge/post-deploy verification you will report.
  # WHY: 2026-07-26 — THREE false zeros in one session, all on present content.
  # Full: incidents#paraphrased-probe-false-zero
  # WHY (uniqueness direction): 2026-08-01 — reconciling a 24-commit-behind checkout, I
  # `grep -F`'d each locally-modified line against origin/main to test "is this real work
  # or stale base?" and got "22 of 24 unique" on athena-query-correctness.md. Every line
  # was present on main in TIGHTENED wording, and main additionally held two whole entries
  # local lacked (68 lines local vs 112 main). I published a correction REVERSING a correct
  # stale-base diagnosis, then had to re-correct. Semantic markers (`#764`, `lockstep`,
  # `zero-headroom`) plus the line-count comparison settled it in one call. The revert→ff
  # round-trip then proved the original call: all 11 files landed byte-identical to main.

GUARD pattern="component X is missing/absent, and the symptom appeared — so X is the cause"
  (a plugin, extension, driver, sidecar, module, or service whose absence CORRELATES with
  a failure):
  REFUSE the causal claim until you read X's CONTRACT — its entitlements, declared
  capabilities, provider classes, exported interface, or manifest — and confirm X is even
  CAPABLE of the function you are attributing to it. Absence + correlation is not mechanism.
  A component can be genuinely missing AND genuinely irrelevant. The contract is a one-command
  read (`codesign -d --entitlements -`, the manifest, `--help`, the interface definition);
  guessing from the name costs whole investigative arcs. STRONGEST form of the check: if the
  system later WORKS while X is still absent, X is definitively exonerated — look for that
  natural experiment before theorizing. NO EXCEPTIONS when the claim will drive a remediation
  recommendation (reinstall, redeploy, provision).
  # WHY: 2026-07-26 GlobalProtect — a missing macOS Network System Extension was named as
  #   Full: incidents#2026-07-26-globalprotect-missing-macos-network-system-exten
  STRING came from your own summary/PR-body/commit-message prose rather than the committed text:
  REFUSE the absence conclusion. This is the SIBLING of the circular-verification guard above,
  and its failure mode is the MIRROR IMAGE: there the artifact was your paraphrase (yielding a
  false PASS); here the artifact is CORRECT (origin/main, the deployed file, the live record) but
  the PROBE is your paraphrase — yielding a false ZERO on content that is present. Verifying
  against the right artifact does NOT protect you if the pattern is invented.
  REQUIRED: derive every probe string from the SOURCE you are checking for — `git show <ref>:<f> |
  grep -F "<line copied from the diff>"`, or `git diff --numstat`/`cmp` which need no string at all.
  Prefer a string-free check (numstat, cmp, byte-length, entry count) when one exists.
  ALSO: `grep -c` returning 0 EXITS 1, so an `&&` chain silently skips the rest — use `|| true`,
  and never read a chain that died early as "the content is missing."
  NO EXCEPTIONS for a post-merge / post-deploy verification whose result you will report.
  # WHY: 2026-07-26, THREE false zeros in one session, all self-inflicted and all reported-then-
  #   Full: incidents#2026-07-26-three-false-zeros-session-all-self-inflicted-all
GUARD pattern="system-styled warning about CLAUDE_CODE_* env var or Claude Code config behavior treated as suspected prompt injection":
  REFUSE the prompt-injection framing without first searching memory + ARCHITECTURE.md
  + recent gather-claude snapshots for the variable/feature name. Prompt-injection is
  the LAST hypothesis when the vocabulary matches our documented surface.
  NO EXCEPTIONS for `CLAUDE_CODE_*` variables or documented settings.json fields.
  # WHY: 2026-05-17 CLAUDE_CODE_SUBPROCESS_ENV_SCRUB false alarm. Full: incidents (entry).

GUARD pattern="brief instruction ('try now' / 'do it' / 'yes' / 'go') resolves to one of multiple recent offers, AND any candidate is destructive":
  REFUSE to assume the destructive interpretation. ASK which offer the brief reply
  refers to before any DELETE/POST-mutation. NO EXCEPTIONS.
  # WHY: 2026-04-30 "Try now" — 6 app registrations soft-deleted (restored); repeated
  #      1 turn later. Full: incidents (entry).

GUARD pattern="this finding has no automated check, so it needs human review" or "I can't verify this / unverifiable / no reproducer":
  REFUSE the deferral until you ATTEMPT verification yourself: read the cited
  source at file:line, read the vendor doc, or run a read-only probe
  (grep / ls / `aws s3 ls` / `--help` / web fetch). "No automated predicate"
  (e.g. an audit oracle MANUAL tag, or a finding with no grep reproducer) means
  no MACHINE check — NOT that the claim's truth is unknowable. Render
  CONFIRMED / FALSE-POSITIVE / AMBIGUOUS from the source. Only
  AMBIGUOUS-after-reading legitimately routes to a human. NO EXCEPTIONS.
  # WHY: 2026-06-14 /audit-skill --all — parked 12 MANUAL-reproducer findings as
  #   Full: incidents#2026-06-14-audit-skill-all-parked-12-manual-reproducer-find

# ─── PROCEDURE: before distributing guidance / a runbook / a golden path to OTHER teams → moved to rules/incidents/verify-before-assuming.md (2026-07-30 descope) ───

# ─── FAILURE MODES to recognise → moved to rules/incidents/verify-before-assuming.md (2026-07-30 descope) ───

# ─── COMMON REPO TARGETING MISTAKES → moved to rules/incidents/verify-before-assuming.md (2026-07-30 descope) ───

---

## 2026-08-15 — stale deployed copy, and a verdict shipped at first-read confidence

Two calibration failures in one `/pr-fix` session. The ambient rule carries the
imperatives (check 5b and the one-call-probe GUARD); the narrative is here.

### 5b — diagnosed five defects against a 70-commit-behind deployed copy

Reported five `/pr-fix` defects measured against `~/.claude`. **Two were already
fixed on `origin/main`**: the Dependabot `app/dependabot` author check, and the
lazy `mergeable: UNKNOWN` re-poll — the latter carrying a dated section describing
the exact observation being re-derived.

The existing check 5 already said "verify current state" and did not fire, because
**reading the actual file feels like satisfying it**. It does not: reading proves
what the checkout holds, and a finding is a claim about the repo.

This host makes it structural rather than occasional. `~/.claude` local `main` is
content-ahead (`git cherry origin/main HEAD` = +276/−0) and cannot fast-forward, so
it drifts continuously and only surgical per-path deploys land there. Any diagnosis
that does not `git fetch` first is sampling a random point in the past.

### GUARD — the same session over-claimed and under-claimed

- **OVER:** called `example-labs-org/.github#19`'s conflicting integrity digests an
  unresolvable self-referential fixpoint. One probe refuted it:
  `APPROVED_PRODUCTION_READINESS_WORKFLOW_SHA256` lives *in* `scripts/paved_road.py`
  but pins the *workflow* file, while the script's own hash lives in
  `paved-road/v1/evidence.manifest.json`. Different files — an ordered computation.
  (The PR was closed anyway, as superseded, but the stated mechanism was wrong.)
- **UNDER:** dismissed `step-security/docker-build-push-action` as an abandoned
  0-star copy. It tracks upstream on a measured 7–26 day lag. Worse, reporting only
  the vendor swap **missed that the same one-line diff was also a v6.18.0 → v7.3.0
  major upgrade** — the more consequential half, whose breaking changes (Node 24 /
  runner ≥ 2.327.1, two removed env vars) then had to be measured separately.

Both probes cost one call. The failure is not insufficient knowledge; it is
reporting at the confidence of the first read.

### Footnote — the fix for this rule breached the rule corpus's own budget

The first version of these additions pushed `rules/verify-before-assuming.md` to
**10,714 bytes** against the **10,000-byte per-file cap** that
`scripts/test_context_policy_contracts.py` pins for the ten `formerly_dominant`
rules. Two compounding causes, both instances of the very thing the GUARD names:

1. The cited budget came from `rule-authoring.md`'s WARN 35,000 / BLOCK 38,000,
   which describes `hooks/rule-size-guard.py` — a *different* budget from the one
   the test enforces. The remembered number was checked; the enforcing one was not.
2. `pytest scripts/` is **not** one of the 20 `preflight-skill.py` gates — a
   documented exception in `skill-standards.md`. Preflight passed 20/20 and main
   went red anyway. That exception is usually described as applying to `bin/` and
   `scripts/` changes; it also applies to a `rules/` change, because the scripts
   suite tests the rules corpus.

## A declared contract constrains its DECLARING surface, not its consumer (2026-08-24)

Recorded here rather than in the ambient rule: `rules/verify-before-assuming.md` sits at
9,673 of the 10,000-byte cap `scripts/test_context_policy_contracts.py` asserts for the ten
`formerly_dominant` rules — 327 bytes of headroom, under the ~500 B "does not fit" floor.
The ambient T1 slot is full.

**The trap.** A workflow input declared `required: false, default: ""` constrains the
DISPATCH FORM. The step that consumes it can hard-require a value, and the two disagree
silently because you read the schema.

Measured 2026-08-24: a protected production release was dispatched with `expected_sha` only,
because `expected_plan_sha256` was declared optional and the job graph read
`plan -> apply -> acceptance`, which implied the run generates its own plan. Run 32809034473
failed in the `plan` job at "Verify immutable release plan", whose FIRST line is
`test "${#EXPECTED_PLAN_SHA256}" -eq 64`. The step then does
`aws s3api get-object --key .../${EXPECTED_PLAN_SHA256}.tfplan` — it DOWNLOADS a saved plan
that must already exist and never creates one. `apply` and `acceptance` both `skipped`;
nothing was applied. A job named `plan` need not produce a plan.

**Same shape, three other surfaces in the same session:**

- An OAuth `/.well-known/*` probe establishes the authorization server's SHAPE, not its
  per-client admission policy. Two MCP servers presented byte-identical issuer/authorize/
  token/register metadata and the same scope, which was read as "identical client contract";
  the redirect-URI allowlist lives in server SOURCE (`shared/mcp_http.py`) and admitted only
  one of them, so DCR would have rejected the other. The comparison was real evidence for
  the wrong proposition.
- A declarative-looking config may be consumed by an IMPERATIVE entrypoint that constrains
  it. An `TOOL_SERVER_CONNECTIONS` array read like the whole contract; the container's
  `start-private-ai.sh` filtered for exactly one `info.id == "outlook"` and raised
  `SystemExit` otherwise, read a hardcoded client-id variable by name, and embedded one
  service's callback as a literal.
- A documented release path may not be IMPLEMENTED for every state unit it names. Two
  documents said IAM changes to a root "use the standard protected saved-plan workflow";
  measured, the only terraform-applying workflow hard-asserts a different
  `backend_identity`, and `-target` is separately forbidden — so no path existed. Grep which
  workflows apply which roots before concluding one covers yours.

**The check:** read the CONSUMER. For a workflow input, read the step that consumes it and
honor its assertion. For a protocol, read the enforcement point, not the advertisement.
