---
paths:
  - "**/rules/verify-before-assuming.md"
  - "**/rules/incidents/verify-before-assuming.md"
---

# Verify Before Assuming: Incident Narratives

Extracted from `rules/verify-before-assuming.md`. The parent rule
keeps invariants, procedures, guards, and one-line recovery hints;
full incident narratives live here.

---

## 2026-05-12 SKILL.md cap claim — propagated stale vendor recommendation
**Anchors:** procedure `before citing vendor authority`

Told the user "Anthropic actually recommends under 5,000 words" for
SKILL.md cap by quoting `rules/skill-standards.md`. User asked to
verify.

Context7 query to
`/websites/platform_claude_en_agents-and-tools_agent-skills` returned
the canonical text: **"keep the body of SKILL.md under 500 lines."**

The `skill-standards.md` claim was wrong (stale or fabricated). Was
~30 seconds away from reverting valid work based on a fictional
vendor recommendation.

**Cost.** One Context7 query (free). Cost of propagating the wrong
number: nearly an hour of unwarranted refactoring.

**Lesson encoded.** Local rules are derivative. Before stating
"Anthropic recommends X" / "vendor Y says Z", verify against the
vendor's source via Context7 or fetched docs — not against a local
rule that cites them. If the local rule disagrees with the vendor,
the vendor wins AND fix the local rule in the same session.

---

## 2026-05-02 PSM-full index custom-path detour
**Anchors:** procedure `before creating an index, build, or artifact`

Wrote `index_psm_full.py` pointed at
`benchmarks/eval_v4/psm-full/voyage_4_large/` (custom path, 1450s
indexing wall, ~$0.50 voyage cost). Claimed it was "semantically
equivalent to /index-repo".

User pushed back: it wasn't.
- No registry registration
- No dual-model index
- No code-graph
- No hard-gate validation

PSM had ALREADY been indexed at the canonical path
(`~/.claude_code_search/projects/`) on 2026-04-28. A `list_projects`
call would have surfaced this in 30 seconds and saved the entire
detour.

**Lesson encoded.** Before indexing/building/embedding, check the
registry/list for existing instances. Custom-path artifacts bypass
project registries (invisible to `switch_project`/`list_projects`)
AND bypass the documented validation gates of the production
workflow.

---

## 2026-05-17 CLAUDE_CODE_SUBPROCESS_ENV_SCRUB warning — false prompt-injection flag
**Anchors:** GUARD on system-styled warnings about `CLAUDE_CODE_*` env vars

User pasted a runtime warning:
> "⚠ Permission mode forced to default —
> `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` is set (allowed_non_write_users
> hardening)."

Flagged it as suspected prompt injection citing "unknown variable"
without searching memory first.

`memory_search` on the variable name returned:
- **ARCHITECTURE.md:762** — *"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB
  (v2.1.83): Set to 1 to strip Anthropic and cloud provider
  credentials from subprocess environments"*
- **2026-03-25 anthropic-intelligence-snapshot** — captured from
  CHANGELOG v2.1.83.

Variable was set to `"1"` in user's `settings.json:23`. The warning
was a NEW v2.1.14x hardening (downgrading permission mode when scrub
is on alongside `bypassPermissions`) — not yet in 2026-05-15
`gather-claude` snapshot but consistent with the documented feature
surface.

**Cost.** One explicit user correction ("review the release notes
and gather-claude work"), one retraction message, ~3 turns of
false-alarm framing.

**Lesson encoded.** Before responding to ANY system-styled warning
mentioning a `CLAUDE_CODE_*` variable or a `settings.json` field
name, run `memory_search` on the variable/field name + check
ARCHITECTURE.md env section. Treat prompt-injection framing as the
LAST hypothesis, not the first, when the warning's vocabulary
matches our documented architecture surface.

---

## 2026-04-30 "Try now" — destructive misinterpretation of brief reply
**Anchors:** GUARD on ambiguous brief instructions resolving to destructive operations

"Try now" interpreted as "execute the deletion batch I just offered"
when user meant "retest the consent verification endpoints from the
prior offer." **6 app registrations soft-deleted; user caught it;
restored.**

Repeated 1 turn later when "Wraithwatch (PoC)" was deleted as "dead"
but actively in use.

Both incidents avoidable by 1-line clarification.

**Lesson encoded.** When a brief instruction ("try now" / "do it" /
"yes" / "go") could resolve to multiple recent offers AND any
candidate is destructive: ASK explicitly which offer the brief reply
refers to before any DELETE/POST-mutation. A 1-line clarification
beats restoring 6 deleted apps.

---

## 2026-05-12 arxiv-mcp-server 0.3.2 → 0.4.12 — declared API rewrote from partial inventory
**Anchors:** `assumed_API_rewrote_from_partial_tool_inventory`

After Claude Code restart, the system reminder's deferred-tools list
showed 6 tools (`check_alerts`, `citation_graph`, `get_abstract`,
`reindex`, `semantic_search`, `watch_topic`).

Declared "the tool API rewrote completely" — claimed the 4 old tools
(`search_papers`, `download_paper`, `read_paper`, `list_papers`)
were "gone, replaced by new API." Flagged that "any skill or
workflow referencing the old arxiv tool names will silently break."

User asked me to verify. `ToolSearch` on
`select:mcp__arxiv-mcp-server__search_papers,...` returned all **4
old tools intact** (with enhanced parameters); 10 tools total. The
v0.3 → v0.4 bump was purely additive.

**Cost.** False-alarm message + correction message + new reference
doc + rule update.

**Lesson encoded.** The deferred-tools list in system reminders is a
**sampled inventory** shown to the model — not the authoritative
tool catalog. Major version bumps are additive far more often than
they are rewrites. `ToolSearch` each old tool name with `select:`
BEFORE declaring API changes; only an empty result is evidence of
removal.

---

## 2026-05-12 Loc-Bench — multi-hour retry plan without preflight
**Anchors:** procedure `before committing to a multi-hour retry/recovery plan`

Claimed "67 of 200 instances can be re-cloned" without running
`git ls-remote --exit-code` first.

A 30-second preflight (Fix B of code-graph PR #296) showed **ALL 67
were permanently unreachable**.

**~4 hours of failed retries preceded the preflight existing.**

**Lesson encoded.** Before estimating effort or proposing a >1-hour
retry plan, run the cheap preflight check:
- Reachability: `git ls-remote --exit-code <url> <sha>`
- Existence: HEAD request, `ls` of file, single API probe
- Smoke: `--n 1` run, single-instance dry-run, sample-of-1

If preflight fails → commit to NO recovery; document why and stop.
If preflight passes → propose the retry plan with the preflight
result as evidence.

---

## 2026-06-07 forceLoginOrgUUID — "not configured" from a partial probe, three times
<a id="2026-06-07-forceloginorguuid"></a>
**Anchors:** procedure `before concluding a setting/policy/config is NOT present`; GUARD "I checked the obvious location"

Concluded "no managed settings" (missed HKLM\Policies\Claude, the
Desktop policy a [confirmed] memory entry NAMED) then "CLI not on
Bedrock" (missed the shared registry policy / govcloud profile that
drives it). 3 wrong conclusions, 3 user corrections in one session.
memory_search + full enumeration = right on turn 1.

**Lesson encoded.** Absence in a partial probe is a property of the
probe, not the system. Before any "X is not configured / not set /
doesn't use Y" conclusion: memory_search the component + "managed
settings|policy|registry|config" FIRST (we often already document the
exact location — claude-desktop-policy.md NAMES HKLM\SOFTWARE\
Policies\Claude). Then enumerate ALL platform locations: per-OS file
paths (deprecated + current); registry HKLM AND HKCU, ALL
product-family key variants (`Policies\Claude` vs
`Policies\ClaudeCode`) + WOW6432Node; remote/server-managed (fetched
at runtime, NO local artifact); env vars Process AND User AND Machine
scope. Multi-app products (Claude Desktop + Claude Code): check BOTH
apps' config surfaces — one app's policy can drive behavior you're
attributing to the other (the CLI's Bedrock backend). When the USER
asserts a config exists your probe missed, the PROBE was incomplete —
believe them, locate it exhaustively or ASK.

---

## 2026-05-28 dynamic-workflows — capability presented as deployment-reachable
<a id="2026-05-28-dynamic-workflows"></a>
**Anchors:** procedure `before presenting a vendor feature as available/enable-able`

Told the user workflows were CLI-available + enable-able via /config
or claude.ai admin; the enable gate is the claude.ai org-admin page
(not reachable from our platform.claude.com / GovCloud deployment)
and /config showed no row. Corrected twice by the user. The doc was
accurate (CLI-capable); capability != deployment reachability.

**Lesson encoded.** Separate CAPABILITY (does the platform/CLI
support it — the vendor doc answers this) from REACHABILITY (is the
control plane that ENABLES it one OUR deployment has). Identify the
enable/disable surface from the doc (/config toggle, claude.ai
org-admin page, managed-settings, Bedrock/Vertex/Foundry console) and
verify that surface governs OUR deployment. Our Claude Code runs
against platform.claude.com / Bedrock GovCloud — claude.ai org-admin
toggles do NOT govern it; a feature gated solely behind claude.ai
admin is effectively UNAVAILABLE to us regardless of CLI capability.
Present it as "not enable-able in our deployment", NOT "available".

---

## 2026-06-02 CSOD transcript — one blocked endpoint generalized to "capability blocked"
<a id="2026-06-02-csod-transcript"></a>
**Anchors:** GUARD "this API/endpoint failed, so the capability is unavailable"

Exhaustively proved the legacy Foundational LOTranscript/
TranscriptSearch was disabled (400 "Rest Services not enabled"; two
backends, two OAuth apps, spec-canonical request) and concluded
"transcript API blocked → GCS case", even writing it into a report.
The MODERN /services/api/v1/transcripts/* product was ENABLED under
the same transcript:read scope and worked. ~15 turns + 3 user
pushbacks to correct; the OpenAPI full-path list surfaced the v1
surface that one more probe confirmed.

**Lesson encoded.** A failed probe proves only THAT endpoint/product
is blocked — not that the capability is unavailable. Before
concluding "blocked / requires vendor enablement", enumerate every
API surface that could provide the capability: read the OpenAPI
spec's FULL path list AND the scopes/permissions catalog, then test
the alternatives. Modern and legacy API products routinely coexist
under the SAME scope.

---

## 2026-06-16 GovCloud Route 53 public zones — asserted vendor behavior unverified while verifying the confirming half
**Anchors:** GUARD "this is just how AWS / <vendor> works"; procedure `before citing vendor authority OR asserting vendor-system behavior`

Advising on a "PROD public CNAME → Gov DLB" Route 53 request, asserted
"GovCloud Route 53 has no public hosted zones; GovCloud public DNS is
always served from commercial" as a load-bearing reason for "create it
in Commercial." User posted a GovCloud console screenshot showing
`example.internal`, Type: **Public**, in account `123456789012` — direct
refutation. Same shape as the 2026-06-11 `aws:PrincipalArn` incident:
AWS behavior asserted backwards from training knowledge.

The sharper miss: in the SAME response I ran a live `route53
list-hosted-zones` to verify the COMMERCIAL zone (the confirming half)
while asserting the GOVCLOUD capability (the load-bearing half) from
memory. Verification was applied asymmetrically — to the claim that
needed it least.

**Cost.** One confidently-wrong "definitively Commercial" answer; caught
only because the user happened to open the GovCloud console. Corrected
answer + topology persisted to memory (`example-dns-topology`).

**Lesson encoded.** When already running verification queries for a
recommendation, verify the LOAD-BEARING claim, not just the half that
confirms your prior. A vendor-capability negative ("X can't do Y") is
load-bearing and needs a 30-second probe (`list-hosted-zones`, a doc
check) before it ships — especially when the opposite is one console
glance away. GovCloud Route 53 DOES support public hosted zones; it
lacks domain registration, not public zones.

---

## failure-mode-incident-citations
**Extracted incident details for the parent rule's FAILURE keys (2026-06-10 descope).**

### claimed_MCP_unavailable_without_ToolSearch
INCIDENT 2026-04-12: Firecrawl claimed not installed; Linear MCP
claimed unavailable; harness pruning reported "none found" without
grep. All three wrong.

### destructive_delete_hit_wrong_target
INCIDENT 2026-04-17 code-search: delete_project iterated in
non-deterministic iterdir() order; killed populated 97.7MB entry
instead of empty skeleton. Re-indexing took ~30 min. Recovery:
restore from last index backup; re-run with project_hash.

### baked_in_unstated_assumption
INCIDENT 2026-04-19 sbom-rs airgap: assumed offline generation
required; reshaped 6 recommendations invisibly. User had to challenge
to surface.

### audit_scope_silently_sampled
INCIDENT 2026-04-19 example-technologies Vercel audit: scoped to "top
30 most-recently-updated" of 337 repos without approval. User had to
screenshot GitHub UI to flag the gap. Recovery: ran full sweep
(43 min, ~1000 of 5000 API calls — well under budget).

### LLM_overclaim_as_determines
INCIDENT 2026-04-19 sbom-rs VEX: wrote "LLM determines CVE
actionability." Reframe required for auditor-facing accuracy:
"proposes with rationale, gated by human/pipeline."

---

## paraphrased-probe-false-zero

### 2026-07-26 — three false zeros in one session, all on content that was present
**Anchors:** GUARD "I grepped for it and got 0 hits, so the content didn't land"

Three post-merge / post-deploy verifications reported content MISSING that was
in fact present, because the search string came from my own PR-body or summary
prose rather than the committed text:

| Probe used | Committed text | Artifact checked |
|---|---|---|
| `"UNKNOWN from ABSENT"` | `"UNKNOWN(could not read)"` | `origin/main` rules file |
| `"PENDING INVITATION"` | `"pending INVITATION"` | `origin/main` topic file |
| `"not the cause of the A0FJ"` | `"NOT the cause"` (case) | DEPLOYED Azure runbook |

In every case the ARTIFACT was correct — origin/main, the live deployed runbook.
Only the PROBE was invented. That is what distinguishes this from the
circular-verification guard: there the artifact is your paraphrase and the
failure is a false PASS; here the artifact is right and the failure is a false
ZERO. Verifying against the correct artifact does not protect you if the pattern
is fabricated.

Compounding it: the first probe used `grep -c ... && <next step>`, and `grep -c`
EXITS 1 when the count is zero — so the `&&` chain died and the follow-up checks
never ran, which read as a *second* independent failure rather than one masked
command.

**Cost.** Three needless re-investigations, and a moment of believing a merge had
not landed when it had.

**Lesson encoded.** Derive every probe string from the source you are checking
for (`git show <ref>:<f> | grep -F "<line copied from the diff>"`), or prefer a
check that needs no string at all — `git diff --numstat`, `cmp`, byte-length,
entry count. Guard `grep -c` with `|| true` so a zero count cannot silently kill
a chain.

---

## adhoc-resolver-phantom-refs

### 2026-07-24 — a hand-rolled reference resolver reported 12 phantom broken refs
**Anchors:** GUARD "my script/grep says this cited path doesn't exist, so the reference is broken"

A corpus review ("what skills need fixing?") used a hand-rolled resolver globbing
`scripts/([\w-]+\.py)` against `~/.claude` only. It reported **13 broken script
references; 12 were FALSE**:

- `finalize_topics.py` + `rebuild_backlinks.py` — live in `knowledge-base/.github/scripts/`
- `verify_server.py`, `state_io.py`, `parse_plan.py` — live in sibling skills
- `team-spawn.py` — an illustrative example inside sample output, never a real path

The 13th (a separate skill (not included in this export) → `obsidian-infra`) was real but **misdiagnosed** as "broken
skill, add a Step 0 gate" — the skill ALREADY had that gate at line 76 with the exact
clone command. The true fault was a **host provisioning gap**: the repo was never
cloned after the Windows→macOS migration.

The registry that would have prevented all of this already existed:
`skills/audit-skill/known-external-paths.yaml` listed `~/Documents/obsidian-infra/`
annotated *"Cited by a separate skill (not included in this export), a separate skill (not included in this export)"*. It had been created for the
2026-05-25 KB-citation incident — the SAME failure mode — but was reachable only from
inside `/audit-skill`, with no ambient rule pointing at it until the parent guard was
written.

**Cost.** Reporting the unverified list would have sent the user chasing 12 phantom
bugs to find one real provisioning task.

**Lesson encoded.** Skills legitimately cite sibling repos and user-data dirs, so a
resolver that searches only the current checkout reports every one as phantom. Match
cited paths against the known-external-paths registry first, `test -e` registry hits to
separate "not cloned on this host" (provisioning) from "genuinely missing", and read the
citing SKILL.md — it may already carry a prerequisite gate. Prefer `/audit-skill`, whose
D3a/D3b checks consult the registry by construction.
## 2026-07-24 hand-rolled-resolver false broken-reference sweep
<a id="2026-07-24-hand-rolled-resolver"></a>

 WHY: 2026-07-24 corpus review ("what skills need fixing?") — a hand-rolled
 resolver globbing `scripts/([\w-]+\.py)` against ~/.claude only reported 13
 broken script refs; 12 were FALSE (finalize_topics.py + rebuild_backlinks.py in
 knowledge-base/.github/scripts/, verify_server.py + state_io.py + parse_plan.py in
 sibling skills, team-spawn.py an illustrative example in sample output). The 13th
 (a separate skill (not included in this export) → obsidian-infra) was real but MISDIAGNOSED as "broken skill, add a
 Step 0 gate" — the skill ALREADY had that gate at line 76 with the exact clone
 command; the true fault was a host provisioning gap (repo never cloned after the
 Windows→macOS migration). `known-external-paths.yaml` ALREADY listed
 ~/Documents/obsidian-infra/ annotated "Cited by a separate skill (not included in this export), a separate skill (not included in this export)" — it
 was created for the 2026-05-25 KB-citation incident, the SAME failure mode, and
 is reachable ONLY from inside /audit-skill (no ambient rule pointed at it until
 this guard). Reporting the unverified list would have sent the user chasing 12
 phantom bugs to find one real provisioning task.

## 2026-07-19 research prior overrode fetched source

 WHY: 2026-07-19 hardware-research — user said "Do research"; searches RAN, but the
 synthesis reported the M5 Max MacBook Pro as new/upcoming from a stale prior while a
 fetched June-2026 roundup IN-CONTEXT listed it as shipping (March 2026 launch). Two user
 corrections: first the fact, then the diagnosis ("your error was that you didn't listen
 when I said research this" — not training-data recency). Same family as the 2026-07-07
 memory-search incident above: in-context evidence contradicting a claim went unreconciled.
 Feedback memory: projects/-Users-you/memory/feedback_measure-dont-infer.md.

## 2026-07-28 four-false-gap-claims
<a id="2026-07-28-four-false-gap-claims"></a>

FOUR false "we don't collect X" claims in ONE session, each formed by reading a VENDOR doc
and then running a grep scoped to the module I already had in mind. Two were graded HIGH and
came within a commit of shipping.

| # | Claim | Reality | Where it actually lived |
|---|---|---|---|
| 1 | "a SIEM rule keyed on 6 actor types drops three principal classes" (HIGH) | no closed actor enum exists anywhere; `actor` is an untyped string column read schema-on-read | `compliance.tf:1365/1466` |
| 2 | "5 Analytics endpoints documented but never probed by us" (MEDIUM) | all seven engagement endpoints already called by a deployed Lambda lane | `anthropic_audit_v2/analytics.py:44` |
| 3 | "rate-limit headers available but unused — recommend consuming them" | already consumed: proactive throttle below `RATELIMIT_MIN_REMAINING=30`, honors server `Retry-After` | `compliance_poller.py:207-219` |
| 4 | "uncollected Compliance key inventory — recommend ingesting + alerting" (HIGH) | ingested AND graded by an always-on credential guard emitting `UnexpectedDeleteCapableComplianceKeys` to CloudWatch | `anthropic_audit_v2/compliance.py:248,273` |

Root cause, identical all four times: **the grep was too narrow, not missing.** I searched
`compliance_poller.py` and `lambda/*.py` — the modules I had in mind — while both #2 and #4
lived in the sibling `anthropic_audit_v2/` bundle. #4 is the sharpest: I drafted a HIGH
finding recommending we build alerting that already existed and was *stronger* than my
proposal (allowlist grading + a CloudWatch alarm metric + a shared grader deliberately used
by two callers "so the gated evidence path and the always-on control path can never disagree
about what healthy means").

Three rules extracted, now in the rule's GUARD:
1. Grep the FIELD/RESPONSE NAME, not the endpoint path — paths get assembled by f-string and
   never appear as literals; the response field always does.
2. Never scope to one module — `~/Documents/GitHub` with `--include`; `*_bundle/` is the
   usual hiding place.
3. Grep the CAPABILITY verb before proposing to build it (`put_metric_data`, `_emit`,
   `alarm`, `guard`) — twice the runtime already exceeded the proposal.

A fifth instance the same session, one layer up: the `/gather-claude-endpoints` channel
registry watched 15 doc pages while `manage-claude/` alone has 28, because the registry was
seeded by KEYWORD-GREPPING the doc index and then treated as the surface. A page whose title
lacked a monitoring keyword (`access-transparency.md` — an entire data channel) was
structurally invisible, and the probe phase could not compensate because probing only visits
what the registry lists. Fixed by enumerate-and-subtract with an `UNCOVERED` report, plus 16
exclusions carrying written reasons (claude-config #1745/#1746, claude-knowledge-base
#1273/#1274).

A **sixth** instance, same session, one layer deeper than the fifth — and the one that
generalizes furthest. Having fixed the registry's *coverage* of the docs, the detector was
still **docs-only**: every fact it compared came from vendor prose. That is not a tuning gap,
it is a **structural ceiling** — a filter over documentation is incapable, at any coverage,
of finding what the documentation OMITS. The user named it directly: *"it seems like it keeps
missing things."* What it could not see, measured against our own live pipeline: **24
activity types present in production and absent from the docs**, plus a whole OTel event
(`subagent_completed`). No amount of better doc-scraping would surface any of them.

Two facts make this permanent rather than fixable-by-more-docs:
- **No machine-readable spec exists.** Four candidate OpenAPI URLs all 404, and the
  official SDK's `api.md` carries **zero** Admin/Analytics/Compliance paths. There is no
  authoritative schema to diff against; prose is the only vendor artifact.
- **Probing cannot compensate**, because a probe only visits what the registry already
  lists. Coverage of the docs bounds the probe, so both stages share one blind spot.

The fix is a second, INDEPENDENT source: reconcile the doc-derived baseline against
**observed production data** — `SELECT DISTINCT` over the lake for what actually arrives,
plus read-only reachability probes — and emit a verdict per fact that names the direction of
the gap: `UNDOCUMENTED` (live but absent from docs — the class that was previously
invisible), `DOC_ONLY` (documented, never observed), `RECONCILED`, `NO_BASELINE`. Shipped as
`scripts/reconcile_observed.py`, deliberately SEPARATE from `diff_channels.py` so the doc
check still runs without AWS (claude-config #1758).

The transferable rule: **when a detector's only input is one party's description of a system,
its recall is bounded by that description's completeness — so it cannot report its own
blind spot.** Ask what a second, structurally different source would be (production
telemetry, a live probe, an independent implementation), and if the answer is "there isn't
one", say so explicitly rather than presenting doc coverage as surface coverage.

## 2026-07-07 memory-search-assessment (extracted from the rule 2026-07-28)
<a id="2026-07-07-memory-search-assessment"></a>

Asserted "BM25 disabled, reranker off, HR@5≈0.85" from a MODULE HEADER DOCSTRING plus
rule-file history. All three stale: the header contradicted the PR #425 frozen-stack block
1000 lines below in the same file (hybrid default since 2026-05-17, Sonnet listwise reranker
default-ON, HR@5 0.914 per the corpus-stamped 2026-06-11 baseline). Sharpest miss: the LIVE
probe metadata in the SAME turn reported `search_mode:"hybrid"` — in-context empirical
evidence contradicting the claim, unreconciled.

Second facet: called sqlite-vec "the scale escape valve" from its LOAD code; a consumer grep
showed `_use_sqlite_vec` is consulted NOWHERE in any query path (and the package was not
installed) — nearly shipped a dependency serving a dead code path. That facet is the direct
ancestor of the 2026-07-28 rule (c): a flag that is only SET is not a capability.

User-prompted audit caught all of it; header fixed in mcp-servers #807.

## 2026-07-08 paraphrase-as-review-artifact (extracted from the rule 2026-07-28)
<a id="2026-07-08-paraphrase-as-review-artifact"></a>
**Anchors:** GUARD "I verified the finding against the artifact under review"

Security-brief assessment: transcribed the Slack brief into a review `.txt`, compressing a
20-item MEDIUM credential list to a "(sample) X; Y; Z" paraphrase to save space, then fanned
verify-agents that "confirmed" a "MEDIUM renders as a semicolon-wall (vs HIGH's bullets)"
finding against that paraphrase. The real poster renders crit/high/med IDENTICALLY; the
"wall" was an artifact of MY compression. Two findings shipped-then-retracted; caught only by
reading the actual poster source. The paraphrase, not the code, was the thing being reviewed —
and the subagent fan-out laundered the circularity at scale, since each agent inherited the
paraphrase as ground truth.

## 2026-07-26-expired-token-and-stale-read-false-negatives

Two false negatives from OUR OWN verification tooling in one session, opposite
directions, same root class: absence-of-evidence read as evidence-of-absence.

**(a) Expired credential turned every check into FAIL.** A deploy-readiness
checker reported the OIDC credential, the release container, and all 3 RBAC
assignments as FAIL / "no assignment" — purely because the local Graph token had
expired mid-session. Every one of those resources existed and had been verified
minutes earlier. A checker that cannot distinguish "I could not look" from "it is
not there" manufactures a blocking verdict out of its own broken auth.
FIX: an up-front reachability probe plus a three-valued exit code —
`0` = satisfied, `1` = genuinely missing, `2` = UNKNOWN / could not observe.

**(b) The mirror image — a stale read during propagation.** A post-change
verification read `role_name: none` for an active contributor on a repo they
push to. Seconds later the same read returned `admin`; the first was a stale read
during permission propagation. Acting on that false negative (a rollback) would
have undone a correct change.

The general form is `absence_of_evidence_in_a_search_is_a_property_of_the_search`
(uncharted-vs-refuted.md), applied not to the literature but to our own probes:
a verification tool's negative result is a claim about the tool's reach at that
instant, not about the world.

## 2026-06-11-awsprincipalarn

Asserted — in chat AND in a shipped KB entry — that an SCP's IAM-role-form
exemption "never matches an SSO admin session," on the reasoning that
`aws:PrincipalArn` resolves to the assumed-role STS form
(`arn:aws:sts::<acct>:assumed-role/<role>/<session>`).

BACKWARDS. AWS's own docs state `aws:PrincipalArn` is the **role ARN**
(`arn:aws:iam::<acct>:role/<role>`), which is exactly the form the exemption
matches. Worse, the SAME KB page already held a verified 2026-05-30
out-of-band success proving the exemption matched in practice — refuting
evidence sitting in the artifact being edited.

A 30-second vendor-doc check, run only later, flipped the claim. Cost: a wrong
claim delivered to the user plus a shipped KB entry needing a correction PR
(KB #763). The lesson is the source-check bar for vendor-behavior claims is the
same whether or not the sentence is phrased as a citation — "X behaves like Y"
about someone else's system is a vendor-authority claim.

## 2026-07-29 diagnosed a live defect from a checkout 3 commits behind origin/main

A three-step self-correction, all one root cause: **local source was treated as evidence
about deployed behaviour without a `git fetch` first.**

The claim: "the gold ETL maps `mcp_server_name` to a raw attribute key that does not
exist." Asserted, then revised, then revised again:

1. **Wrong mapping** — refuted by extracting the DEPLOYED view from Glue: it correctly
   maps `COALESCE('mcp_server.name','server_name')`, the exact keys present in raw.
2. **Wrong layer** — "then the bug is the CTAS materialization." Refuted: the view
   returns 5,780/5,780 populated; the ETL is a thin positional `INSERT ... SELECT` whose
   column order matches the DDL.
3. **Actual cause** — the view had been FIXED by PR #735, merged **2026-07-28 22:00**,
   roughly 30 minutes before I "discovered" the bug. `otel-flat-views.tf:151` looked
   unfixed because my checkout sat at #734/#736. `git fetch` + re-read resolved it.

Same session, same root cause from a different direction: the corrected "8.7% anonymous
identity" figure (itself a fix for a NULL-predicate bug) was ALSO stale — PR #732 had
already recovered `claude-desktop` identity at the resource level, taking it from 0 to
168 distinct principals across 139 sessions. Two shipped artifacts carried the stale
claim and had to be corrected.

**Why the existing rules did not fire.** `verify-before-assuming`'s
"before claiming what your OWN CURRENT/DEPLOYED system does" procedure says to grep the
live entrypoint's call chain — which I did. It assumes the local tree IS current, and
never says to fetch first. `worktree-by-default` has a fetch-before-edit procedure, but
it is scoped to EDITING a tracked file, not to DIAGNOSING from one. The gap is precise:
grep-the-entrypoint is necessary but insufficient when the checkout is behind.

**The durable fix is mechanical, not another correction note.** Prose-level "remember to
fetch" has now failed repeatedly (a KB plan already names stale-state as the #1
self-inflicted theme at ~20 instances). What actually closed this class here was a
committed drift guard that reads the DEPLOYED catalog and compares it to the artifact —
independent of any checkout's freshness. When a diagnosis depends on deployed state,
read the deployed state (`glue.get_table`, `ViewOriginalText`, the Lambda zip), not a
file on disk.

## 2026-06-22 credential-census v4 — current-method claim from a chronological ledger

(Extracted from the rule 2026-07-29 to reclaim ambient-load budget; the rule keeps a
one-line pointer.)

Claimed "the latest method uses a multi-model panel" and proposed "composing the panel
back in." Source showed single-Sonnet (`census_v3_harness.judge` n_passes=1;
`f4_adjudicate.adjudicate` single-model); `census_panel.py` was a REMOVED v2-era artifact
that a chronological doc-28 had listed as one of 6 co-equal methods. The error surfaced in
all 3 mega-distill slices and was user-caught ("our latest method didn't have a panel"),
forcing a full source-grounded rebuild.

Same family as symmetric-evidentiary-burden's single-instance-→-SYSTEM
over-generalization, applied across VERSIONS rather than instances.

## 2026-07-30 descoped from rules/verify-before-assuming.md — moved verbatim, not trimmed

Moved by the #1802 house pattern so the parent rule drops below the
rule-size-guard write-block. Content is unchanged; the parent carries a
pointer at each original location.

# ─── PROCEDURE: before presenting a vendor feature as available/enable-able ───
STEP_1 separate CAPABILITY (platform/CLI supports it) from REACHABILITY (the enable
       control plane exists in OUR deployment).
STEP_2 identify the enable surface from the doc (/config, claude.ai org-admin,
       managed-settings, Bedrock/Vertex/Foundry console).
STEP_3 verify that surface governs OUR deployment (platform.claude.com / Bedrock
       GovCloud — claude.ai org-admin toggles do NOT govern it).
STEP_4 IF the enable path is unreachable → present as "not enable-able in our
       deployment", NOT "available".
FORBIDDEN: presenting "supported in X / on all plans" as "available to you" without
           confirming the enable control plane is reachable.
# WHY: 2026-05-28 dynamic-workflows — corrected twice; capability != reachability.
#      Full: incidents#2026-05-28-dynamic-workflows

# ─── PROCEDURE: before committing to a multi-hour retry/recovery plan ───
STEP_1 identify the cheap preflight that proves recoverability:
       reachability `git ls-remote --exit-code <url> <sha>`; existence (HEAD request,
       ls, single API probe); smoke (--n 1, single-instance dry-run)
STEP_2 run the preflight FIRST, before estimating effort or proposing the plan
STEP_3 IF preflight fails → commit to NO recovery; document why and stop
STEP_4 IF preflight passes → propose the plan with the preflight result as evidence
FORBIDDEN: claiming "X of N are recoverable" without the preflight
FORBIDDEN: committing to a >1-hour retry plan when a <1-minute preflight exists
# WHY: 2026-05-12 Loc-Bench — "67 of 200 recoverable" without preflight; all 67
#      permanently unreachable; ~4 hrs of failed retries. Full: incidents (entry).

# ─── PROCEDURE: before distributing guidance / a runbook / a golden path to OTHER teams ───
# Fires when shipping instructions others will FOLLOW and TRUST — a golden path, runbook,
# remediation doc, "do it this way" guide. "Works for us" (our own tests pass) is NOT
# "ready for others" (the recommended fix actually resolves end-to-end in their hands).
STEP_1 separate what your tests actually verify from what the guidance PROMISES. Tests that
        check RULE LOGIC (does the check fire on a bad fixture?) do NOT verify that the
        recommended REMEDY works (does the fix the doc tells them to apply actually deploy?).
STEP_2 execute the recommended remedy end-to-end, or confirm every concrete resource it names
        EXISTS: the ARN/endpoint/role/bucket/layer the doc says to use. A doc that hands a
        reader a resource identifier must point at a real one, or be explicit it's illustrative.
STEP_3 re-run any validation AFTER changing the guidance — prior validation does not transfer
        to a modified artifact (a doc edit can introduce a dead reference the old test never saw).
FORBIDDEN: shipping a golden path / runbook whose load-bearing step references a resource that
            does not exist (the reader hits "not found" at exactly the step meant to help them).
FORBIDDEN: treating "our policy/lint/CI checks pass" as proof the guidance is followable — the
            checks grade the artifact, not the reader's journey through it.
## 2026-06-11-settings-configurability-row-fable-5-fallback-po
<a id="2026-06-11-settings-configurability-row-fable-5-fallback-po"></a>

# WHY (settings-configurability row): 2026-06-11 Fable 5 fallback posture —
# told the user the "Switch models when a message is flagged" toggle was
# claude.ai-web-only and "can't be set from here," based on the support
# article. The /update-config schema showed `switchModelsOnFlag` is a plain
# settings.json boolean. Cost: one wrong USER-ACTION item in a shipped
# report + a correction cycle. The schema check is one grep.

## 2026-06-22-credential-census-v4-plan-claimed-latest-method
<a id="2026-06-22"></a>
<a id="2026-06-22-credential-census-v4-plan-claimed-latest-method"></a>

# WHY: 2026-06-22 credential-census v4 plan — claimed "the latest method uses a multi-model
#      panel" from a chronological method-ledger; source showed single-Sonnet, and
#      `census_panel.py` was a REMOVED v2-era artifact the ledger listed co-equally.
#      User-caught; forced a source-grounded rebuild. Same family as
#      symmetric-evidentiary-burden's single-instance→SYSTEM over-generalization, across
#      VERSIONS not instances.

## 2026-05-02-psm-full-custom-path-index-1450s-0-50-wasted-alr
<a id="2026-05-02-psm-full-custom-path-index-1450s-0-50-wasted-alr"></a>

# WHY: 2026-05-02 PSM-full custom-path index — 1450s + ~$0.50 wasted; already indexed
#      at the canonical path. Full: incidents (2026-05-02 entry).
# WHY: 2026-06-11 tailscale — began scaffolding a local stdio MCP (venv probe,
#      launcher plan) for a server already deployed at service.mcp.example.internal
#      (85 tools, ECS); user caught it ("do we not already have a tailscale mcp
#      built?"). managed-mcp.json omitted tailscale, which masked the deployment.

## 2026-07-23-3p-web-search-5-retractions-session-no-custom-co
<a id="2026-07-23-3p-web-search-5-retractions-session-no-custom-co"></a>

  # WHY: 2026-07-23 3P web-search — 5 retractions in one session (no-custom-connector →
  # it's-Exa → it's-built-in → local-MCP-can't-reach-3P → AgentCore-can't-enter-3P), each
  # from a partial UI/profile fragment; the actual 3P admin UI (shown by the user) resolved
  # it in one look. The 2nd retraction should have triggered "show me the real surface,"
  # not the 5th. Pairs with the SUBJECT-not-format recall trigger in project CLAUDE.md.

## 2026-07-26-globalprotect-missing-macos-network-system-exten
<a id="2026-07-26-globalprotect-missing-macos-network-system-exten"></a>

  # WHY: 2026-07-26 GlobalProtect — a missing macOS Network System Extension was named as
  # the tunnel blocker across several turns, driving a reinstall recommendation. Its
  # entitlements were `app-proxy` / `dns-proxy` / `content-filter` with NO packet-tunnel
  # provider — it cannot build a tunnel, and the config had its enforcer features disabled
  # anyway. Confirmed conclusively when the VPN connected with the extension STILL absent.

## 2026-07-26-three-false-zeros-session-all-self-inflicted-all
<a id="2026-07-26-three-false-zeros-session-all-self-inflicted-all"></a>

  # WHY: 2026-07-26, THREE false zeros in one session, all self-inflicted and all reported-then-
  # corrected: searched origin/main for "UNKNOWN from ABSENT" (PR-body phrasing; committed text
  # said "UNKNOWN(could not read)"), for "PENDING INVITATION" (committed: "pending INVITATION"),
  # and the DEPLOYED runbook for "not the cause of the A0FJ" (committed: "NOT the cause" —
  # case). Every one was present. The first also killed its `&&` chain via grep -c's exit 1,
  # which read as a second failure. Cost: three needless re-investigations plus a moment of
  # believing a merge had not landed.

## 2026-06-14-audit-skill-all-parked-12-manual-reproducer-find
<a id="2026-06-14-audit-skill-all-parked-12-manual-reproducer-find"></a>

  # WHY: 2026-06-14 /audit-skill --all — parked 12 MANUAL-reproducer findings as
  #      "needs human review" claiming they couldn't be verified. User: "What do
  #      you mean you cannot verify these? You must do it." Source-read verified
  #      ALL 12 as real (zero false positives); 5 were behavior bugs the skill
  #      shipped — wrong AWS profile (proven by a live 403), semgrep --severity
  #      rejecting MEDIUM/HIGH/CRITICAL (semgrep's own click.Choice), codeql wrong
  #      pack names (vendor README), a security-guardrail gap. No-predicate was
  #      never no-verifiability.

## 2026-06-18-cloud-paved-roads-pre-distribution-review-golden
<a id="2026-06-18-cloud-paved-roads-pre-distribution-review-golden"></a>

# WHY: 2026-06-18 cloud-paved-roads pre-distribution review — the golden path told teams to use
# a layer-hub ARN (123456789012:layer:awscli:1) that was never published (the hub apply was
# gated/deferred). Every policy test passed (they check rule logic against synth fixtures), but a
# team copying the documented snippet would hit "layer not found" at the exact step meant to fix
# their problem. Caught by a checkable probe (aws lambda list-layer-versions → empty), not by any
# test in the suite. Fix: docs reframed to "no hub published yet; use no layer / AWS-published only."

GUARD pattern="my verifier / audit / readiness check reports a resource ABSENT, a
  permission MISSING, or a check FAILED — when the underlying credential expired,
  the service was unreachable, or the write only just landed":
  REFUSE emitting "absent / missing / not configured" for anything the check could
  not actually READ. A verifier MUST distinguish three states, not two:
  PASS / FAIL(genuinely wrong) / UNKNOWN(could not read) — and UNKNOWN must exit on
  its own code, never fold into FAIL. Probe reachability ONCE up front (a cheap
  read-only call) and label every dependent check UNKNOWN when it fails; a
  two-state verifier reports an unreadable resource identically to a nonexistent
  one, which invites someone to RE-CREATE an identity, container, or grant that
  already exists — or to conclude shipped work never landed. Symmetrically, for an
  eventually-consistent system (GitHub permissions, IAM, DNS), RE-READ a failing
  item before treating a post-change FAIL as a regression or starting a rollback.
  NO EXCEPTIONS for a verifier whose output gates a create/rollback decision.
  # WHY: 2026-07-26 — an expired Graph token made a deploy-readiness checker report
  # every existing resource as FAIL/"no assignment"; plus the mirror-image stale-read
  # false negative during permission propagation. This is
  # `absence_of_evidence_in_a_search_is_a_property_of_the_search`
  # (uncharted-vs-refuted.md) applied to OUR OWN verification tooling.
  # Full: incidents#2026-07-26-expired-token-and-stale-read-false-negatives
GUARD pattern="a REVERT's own commit message / a code comment / a prior session's note
  explains WHY something can't be done, and you repeat that reason as the current
  constraint":
  REFUSE to propagate the stated rationale without checking it against the RESOURCE
  CONTRACT (the provider schema, the API reference, the type definition). A revert
  message is the author's diagnosis under time pressure, not a verified fact — and it
  is the most-copied kind of derived claim, because it reads as settled history. Check
  whether the reason names the SAME entity your change touches: two resources with
  adjacent names can have opposite constraints, and "we tried that, it can't work"
  then blocks work that was always possible. NO EXCEPTIONS for a constraint you are
  about to repeat to the user as the reason NOT to do something.
## 2026-07-27-mcp-infra-called-codifying-evidence-lake-worm-re
<a id="2026-07-27-mcp-infra-called-codifying-evidence-lake-worm-re"></a>

  # WHY: 2026-07-27 mcp-infra — called codifying the evidence-lake WORM retention rule
  # BLOCKED, quoting PR #369's revert ("object_lock_enabled is creation-only, cannot be
  # set on an imported bucket"). True — of a DIFFERENT resource.
  # `aws_s3_bucket.object_lock_enabled` is creation-only;
  # `aws_s3_bucket_object_lock_configuration` takes a bucket NAME and is freely settable
  # on an existing bucket — and the same repo's detection.tf had used that pattern all
  # along. Codifiable the whole time; the retention gap persisted 5 months partly because
  # the revert's rationale went unchallenged. One provider-schema read refuted it.
  # Sibling of 2026-05-12 (local rule citing a vendor) — here the derivative source is
  # our OWN git history.

# ─── FAILURE MODES to recognise ───
# Per-failure incident citations: incidents#failure-mode-incident-citations

FAILURE claimed_MCP_unavailable_without_ToolSearch:
  RECOVERY: run ToolSearch, re-evaluate.  # 2026-04-12: Firecrawl/Linear/pruning — all wrong

FAILURE assumed_API_rewrote_from_partial_tool_inventory:
  RECOVERY: ToolSearch each old tool name with `select:` BEFORE declaring API changes;
  the deferred-tools list is a sampled inventory.  # 2026-05-12 arxiv 0.3→0.4 was additive

FAILURE deferred_verifiable_finding_to_human_review:
  RECOVERY: read the cited source / vendor doc / run a read-only probe; render
  CONFIRMED / FALSE-POSITIVE / AMBIGUOUS. Reserve "needs human review" for
  AMBIGUOUS-after-reading only.  # 2026-06-14 /audit-skill: 12/12 "manual" findings verified real on source-read

FAILURE destructive_delete_hit_wrong_target:
  RECOVERY: restore from last index backup; re-run with project_hash.  # 2026-04-17

FAILURE baked_in_unstated_assumption:
  RECOVERY: enumerate assumptions, re-evaluate with user.  # 2026-04-19 sbom-rs airgap

FAILURE audit_scope_silently_sampled:
  RECOVERY: run the full sweep (the math usually fits the budget).  # 2026-04-19 Vercel

FAILURE LLM_overclaim_as_determines:
  RECOVERY: reframe as "proposes with rationale, gated by human/pipeline".  # 2026-04-19 VEX

FAILURE pushed_to_wrong_remote:
  RECOVERY: add --repo <Org/Repo> and retry.  # fork repos default to upstream

# ─── COMMON REPO TARGETING MISTAKES ───
- Targeting `example-technologies` (blocked org) instead of example-org
- Pushing to upstream fork instead of example-apps-org/code-search
- Writing docs from memory/inference instead of reading actual source data
- Editing files in the main checkout when a worktree is active


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-06-11-aws-principalarn-asserted-an-scp-exemption

```
WHY: 2026-06-11 aws:PrincipalArn — asserted an SCP exemption semantic BACKWARDS in
     chat AND a shipped KB entry, while the SAME KB page held refuting verified
     evidence; a 30s doc check flipped it. Full: incidents#2026-06-11-awsprincipalarn
```

## 2026-07-28-mcp-infra-739-excluded-success-enumeration

```
WHY: 2026-07-28 mcp-infra #739 — excluded `"success"`; enumeration showed the only
values are connected/failed/disconnected (3,223/1,944/613), so all 3,223 HEALTHY
connections were reported as failures. Caught only by running against REAL data —
a stub returning canned rows accepts it. Sibling of the gap-claim GUARD below:
enumerate-and-subtract, never guess-and-exclude.
```

## 2026-06-11-aws-principalarn-asserted-a-vendor-iam

```
WHY: 2026-06-11 aws:PrincipalArn — asserted a vendor IAM semantic BACKWARDS in chat AND
     a shipped KB entry, while the SAME KB page held refuting verified evidence. A 30s
     doc check flipped it. Full: incidents#2026-06-11-awsprincipalarn (KB #763).
```

## 2026-07-28-four-false-we-don-t-collect

```
WHY: 2026-07-28 — FOUR false "we don't collect X" claims in ONE session, two graded
HIGH; +2 more instances (keyword-seeded registry; a docs-only detector blind to 24 live
activity types). Full: incidents#2026-07-28-four-false-gap-claims
```

## 2026-07-07-memory-search-assessment-asserted-stale-defaults

```
WHY: 2026-07-07 memory-search assessment — asserted stale defaults from a MODULE HEADER
     while the same file's config block AND the live probe metadata in the SAME turn said
     otherwise; also called a flag-that-is-only-SET an available fallback. Fixed in
     mcp-servers #807. Full: incidents#2026-07-07-memory-search-assessment
```

## 2026-07-07-memory-search-assessment-asserted-a-stack

```
WHY: 2026-07-07 memory-search assessment — asserted a stack's defaults from a MODULE
     HEADER while the same file's config block 1000 lines below said otherwise, AND the
     LIVE probe metadata in the SAME turn contradicted the claim, unreconciled. Second
     facet: a flag that was only SET (never consumed) called an available fallback.
     Full: incidents#2026-07-07-memory-search-assessment (mcp-servers #807).
```

## 2026-07-19-hardware-research-user-said-do-research

```
WHY: 2026-07-19 hardware-research — user said "Do research"; searches RAN but a
stale training prior overrode a fetched in-context source. Two corrections.
Full: incidents#2026-07-19-research-prior-overrode-fetched-source
```

## 2026-07-24-corpus-review-a-hand-rolled-resolver

```
WHY: 2026-07-24 corpus review — a hand-rolled resolver reported 13 broken script
refs; 12 were FALSE (sibling repos / user-data dirs), the 13th was a host
provisioning gap misdiagnosed as a skill bug. Full: incidents#adhoc-resolver-phantom-refs
```

## 2026-08-07 — empty-vs-absent field, and a write that proved nothing

Two instances in one ServiceNow session, both producing well-formed wrong answers.

**Empty is not absent.** Querying the PARENT `task` table with
`sysparm_fields=...,request_item` returned `request_item=''` for **all 130** active
`sc_task` rows, so every join produced `parent=-` and read as "these tasks have no
parent." The same rows via `/api/now/table/sc_task` returned it populated on **130
of 130**. `request_item` is a field on `sc_task`, not on `task`; selecting it
through the parent yields an EMPTY STRING rather than an error. The mirror case
appeared in the same session: `stage` exists on `sc_req_item` but NOT on `sc_task`,
so a stage axis built over a `task`-table query collapsed to `-` for every row and
read as "unset" instead of "no such field." Fix: a `sysparm_fields` PROJECTION
probe per class — a real field returns a KEY even when empty, a nonexistent one is
absent from the response — then query each class from its own table. Never probe
field existence with `sysparm_query`; an unknown-field clause is silently dropped
and returns the whole table.

**A third variant hit my own diagnostic.** `grep -c` over MULTIPLE files returns
ONE count over concatenated input, so a verification pass reported "0 hits" for
content that was present on `origin/main`. Compounded by `--delete-branch` having
moved the checkout to a stale `main` after auto-merge fired. One pattern, one file,
per call when the answer is load-bearing; the PR's own `state == MERGED` was the
authoritative answer all along.

**A same-value write cannot establish write capability.** Probing PATCH on
`sc_cat_item` with `{"active": "true"}` where `active` was already `true` returned
**HTTP 200** with `sys_updated_on` unmoved, `sys_mod_count` static at 56, and a
`sys_audit` delta of 0. Two explanations produce that identical observation —
accepted-and-no-opped, or silently discarded — and the probe cannot separate them.
Safety and discriminating power were in direct tension and the safe design was the
uninformative one. To establish capability the submitted value must DIFFER; prefer
the smallest REAL intended change on the lowest-blast-radius record. Escalating
from the authorized inert probe to modify-content-then-restore was blocked by the
permission classifier, correctly: "inert probe" and "modify then revert" are
DIFFERENT acts, and restore-immediately does not convert one into the other.
`sc_cat_item` also carries **0 `sys_audit` rows** despite `sys_mod_count = 56`, so
the audit cross-check available on task tables does not exist there.
