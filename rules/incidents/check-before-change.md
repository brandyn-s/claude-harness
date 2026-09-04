---
paths:
  - "**/rules/check-before-change.md"
  - "**/rules/incidents/check-before-change.md"
---

# Check-Before-Change: Incident Narratives

Extracted from `rules/check-before-change.md` to keep the ambient body
small while preserving the failure-mode history that calibrates the
rule. The parent rule keeps the FAILURE keys and RECOVERY one-liners;
each entry below carries the full narrative.

---

## 2026-03-20 auto-learn — re-added deliberately removed feature
**Failure key:** `re_added_deliberately_removed_feature`

Re-added an auto-learn feature that had been removed after a
quantitative evaluation showed a 40% productive rate. 3 turns wasted
before the prior decision was rediscovered. The removal had been
deliberate; the proposed re-add silently regressed it.

**Lesson:** when a feature looks "missing," check `git log --all` for
its prior life before re-creating it.

---

## 2026-03-20 context:fork — added to agent-dispatching skill
**Failure key:** `added_context_fork_to_agent_dispatching_skill`

Added `context: fork` to `gather-intel`, which dispatches Agent tool
workers. Forked contexts cannot use the Agent tool. Resulted in PR
#274 → #275 (immediate revert).

**Lesson:** before adding `context: fork`, check that the skill body
does not dispatch Agent workers.

---

## 2026-03-20 model:sonnet — added to complex critical-path skill
**Failure key:** `added_model_sonnet_to_complex_critical_path_skill`

Added `model: sonnet` to `/ship`, which has complex conditional logic
(protected repos, fork handling, stash recovery) that needs Opus's
reasoning depth.

**Lesson:** model overrides require evidence that the simpler model
handles the skill's conditional surface.

---

## 2026-03-22 claude-hud fork — bulk-copied over divergent target
**Failure key:** `bulk_copied_over_divergent_fork`

Copied 11 TypeScript files from upstream `claude-hud` over a local
fork that had accumulated 7 additional commits. 12 compilation errors
followed; 6 turns to diagnose and restore.

**Recovery:** `git reset` to pre-copy commit, redo surgically via
`str.replace`.

**Lesson:** before any bulk-copy across a fork boundary, run
`git diff <source>..<target>` and apply the delta surgically.

---

## 2026-03-23 consistency cleanup — deleted file without grep
**Failure key:** `deleted_file_without_grepping_refs`

Deleted `validate-skill-frontmatter.py` and `task-completion-gate.py`
without grepping for references first. CI failed; the Stop hook
errored on the missing file.

**Lesson:** always run `git grep <filename>` and check `settings.json`
+ `.github/workflows/*.yml` before deleting any tracked file.

---

## 2026-04-19 already-shipped strongwording — recommended completed work
**Failure key:** `recommended_already_shipped_work`

Recommended converting `web-search-preference.md` to a stronger
wording. The conversion had already shipped earlier the same day in a
parallel PR (#662). Made the recommendation look uninformed.

**Lesson:** read the target file and check recent commits/PRs before
recommending a change to it.

---

## 2026-04-25 sbom-vex apply_to_sbom test — assumed struct shape
**Failure key:** `wrote_test_against_assumed_struct_shape`

PR #91 first attempt: wrote an integration test using `Affect` struct
with `composite_score` and `properties` fields on `Vulnerability`.
None of those fields existed. `Vulnerability` uses `Vec<BomRef>` for
affects and has `published` / `updated` / `cwes` instead. 5 compile
errors → 2 rounds of edits before passing.

**Recovery:** read the type definition, copy field names verbatim
into the struct literal, rebuild.

**Lesson:** before constructing an instance of a type from an
unfamiliar crate, open its definition. The two reads cost less than
two failed compiles.

---

## 2026-05-03 superplan disk save — cited hook without checking frontmatter
**Failure key:** `cited_hook_behavior_in_skill_prose_without_checking_frontmatter`

Added Step 5a prose in `/superplan` claiming "the
`worktree-enforcement.py` hook allows `knowledge-base/plans/` writes
from forked subagents, so this step works regardless of execution
context." But `/superplan` runs main-thread (no `context: fork` in its
frontmatter); the hook's `main()` returns `sys.exit(0)` immediately
when `agent_type` is missing, so it never enforces on `/superplan`.
The claim was imported from `/deep-dive` (which IS forked) without
re-reading `/superplan`'s frontmatter.

Caught by 5-agent roundtable as one of the HIGH-confidence convergent
findings; same-session edit-fix-resave cycle.

**Recovery:** when about to cite a hook or rule mechanism in skill
prose:
1. Read the skill's frontmatter — check the `context:` field.
2. Read the cited hook/rule — check what conditions it actually
   enforces under.
3. Verify the skill's execution context engages the cited mechanism.

If the mechanism doesn't fire for that skill's execution mode, drop
the claim or rewrite to describe realistic failure modes for that
context (path translation, permissions, disk full, readback mismatch).

**Prevention:** cargo-culting hook claims between similar skills is
the recurring shape. When copy-pasting prose from one skill to
another, frontmatter-check both before shipping.

---

## 2026-05-18 ExampleApp admin agent-prompt — silent API shape break
**Failure key:** `shipped_api_shape_change_without_consumer_check`

PR #58 changed `GET /admin/agent-prompt` from
`{name, version, model, system_prompt, ...}` to
`{variants: [...], synced, canonical_prompt, canonical_variant, note}`
to support multi-model routing. The SPA's `renderAgentPrompt(r)` was
not updated and continued reading flat-object fields, producing
`"(agent) · version ? · model ? · 0 chars · (empty)"` in the admin
pane. Caught only by user screenshot. PR #63 shipped the SPA-side
`_viewFromPromptResponse()` normalizer.

**Lesson:** the API-response-shape procedure (lines 73-99 of the
parent rule) was promoted to T1 ambient after this incident. The
existing `/superplan` cross-component coordination check covers
ADDING new signals; this rule extends it to MODIFYING existing
response shapes. Both classes cause silent-render failures (not loud
crashes), so they slip past smoke tests.

Had the parent rule fired on PR #58, the SPA edit would have been in
the same PR.

---

## 2026-06-11 consistency-banner fix — built a complete duplicate of open PR #1174
**Failure key:** `built_duplicate_of_open_pr_from_shared_banner`

The SessionStart consistency banner showed 6 orphan-hook false positives
plus a manifest-coverage gap. This session diagnosed the root cause
(3-tuple GUARDS regression breaking `_dispatcher_referenced_scripts`),
built the complete fix — regex, skip_files, 4 manifests, regression
tests — and validated it (old-vs-new checker A/B against the live tree:
6 findings → 0). Only when writing the PR body did the Write tool refuse
to overwrite `/tmp/claude/pr-body.md` — which turned out to contain
ANOTHER session's PR body for open PR #1174: the same fix, opened five
hours earlier, sitting red on a drift-gate failure (ARCHITECTURE.md
hook-manifest count claim 54 vs actual 58).

**Mechanism.** Session-start banners are a shared work queue with no
claim mechanism — every concurrent session sees the same findings and
derives the same fix. The existing before-recommending procedure checks
`git log` for already-landed work, which only proves nothing MERGED; an
open twin PR is invisible to it. The catch here was pure luck (temp-file
name collision), not process. Cost: ~8 turns of duplicate build work,
about half salvaged — the A/B validation harness transferred directly to
validating and repairing the canonical PR.

**Secondary lesson — probe for semantics, not your identifiers.** Before
taking over #1174, conflict risk vs main was probed by grepping main's
`.githooks/pre-push` for `PYTHON_BIN` — the BRANCH's variable name.
"Not present" was read as "no conflict risk". Main had an equivalent fix
under a different name (`$PY`, merged in PR #1172), and the merge later
conflicted exactly there. When probing whether another branch already
contains an equivalent change, grep for the modified SITE or behavior
(`command -v python`, the invocation line being changed) — never your
own implementation's identifier names.

**Recovery (worked, in order).** Snapshot the duplicate to /tmp;
discard; `git checkout -B <branch> origin/<branch>` to take over the
open PR; read the failing CI log (the drift gate was the only red); fix
the count claim 54 → 58; merge origin/main into the branch (resolving
pre-push in main's favor); push; re-arm the silently-dropped auto-merge
(bare `gh pr merge --auto`; "already queued" is success); verify
state == MERGED.

**Cross-refs.** The KB narrative tier already carried this discipline:
`knowledge-base/topics/git-workflow-guardrails.md` ("racing the
investigation", same day) and
`engineering-assessment-plan-falsifier-discipline.md` (plan-time
`gh pr list` check, 2026-05-04). Neither was ambient at fix-building
time; this incident promotes the discipline to a T1 procedure + guard in
the parent rule.

---

## 2026-06-11 code-graph stray ARCHITECTURE_REPORT.md — evidence deleted before capture
**Failure key:** `deleted_unexplained_artifact_before_capturing_evidence`

A repo indexed with `skip_report=true` on every known call grew an
`ARCHITECTURE_REPORT.md` anyway. I deleted the file as cleanup BEFORE
checking its mtime — the only evidence narrowing WHICH caller/session
wrote it. The writer remained formally unattributable: the mtime would
have instantly filtered hypotheses (the first one, "the auto-sync
watcher wrote it," cost investigation turns before reading
`syncProject` proved it writes no reports).

The fix had to close the whole CLASS of writers instead of the one
caller: sticky per-project skip_report preference (code-graph PRs
#382 handler persistence, #383 CLI key class, #384 CLI config-store
wiring), plus `index.report.skipped/ok` reason logging so the next
occurrence is attributable from server.log.

**Lesson:** ten seconds of `stat` + copy-to-$TMPDIR before deleting an
unexplained artifact preserves the forensic record. STEP_0 added to the
parent rule's deletion procedure.

---

## 2026-06-13 skill description→when_to_use split — fixed one validator, missed the second
**Failure key:** `relocated_field_content_without_grepping_all_consumers`

Simplifying ~91 skill `/`-menu descriptions meant relocating the trigger
phrases + "Do NOT use" disambiguation OUT of the `description:` field and
INTO a new `when_to_use:` field (the display menu shows only `description`;
the model still reads both for routing). I anticipated that
`scripts/validate-skills.py` graded the moved content — its A4 (trigger
phrases) and A5 (Do-NOT clause) checks read `description` — and fixed those
proactively to read the combined `description` + `when_to_use`. Shipped the
188-file PR believing the consumer surface was covered.

CI then failed on a SECOND consumer I never grepped for: `bin/audit-skill.py`.
Its Q2 length gate (`description` ≤ 1024) used the regex
`^description:\s*(.+?)(?=\n[a-z-]+:|\Z)` to find the next frontmatter key —
and `[a-z-]+:` excludes underscores, so `when_to_use:` was not recognized as
a field boundary. The capture bled straight through `when_to_use` into the
next hyphenated key, measuring `description`+`when_to_use` as one 1103-char
field and false-failing the 1024 gate on `mcp-diagnose` and `vendor-breach`
(real `description` ~95 chars). Q3 (when/trigger signal) shared the same
`desc` variable and was accidentally PASSING only because the buggy regex was
feeding it the bled-through `when_to_use` content.

**Mechanism.** A field-content relocation has TWO consumer sets — readers of
the old field (now see less) and readers of the new field (now see more) —
and they fail SILENTLY at lint/CI, not at edit time. I fixed the obvious
reader (validate-skills.py) and stopped; the miss was the second reader, made
worse by a fragile regex whose key-boundary char class predated the existence
of any underscore-containing frontmatter key.

**Recovery.** Fixed audit-skill.py the same way as validate-skills.py: parse
`description` and `when_to_use` separately (boundary `[\w-]+:`), Q2 measures
`description` alone, Q3 checks the combined text. `audit-skill --all` → 0 FAIL.
Pushed as a fix-forward commit onto the same PR. Cost: one CI round-trip +
diagnosis (read the failed job log → reproduce locally → find the regex).

**Prevention.** Added a "before relocating content between fields of a
structured artifact" procedure + GUARD to the parent rule: grep EVERY reader
of the old field across `scripts/`, `bin/`, `hooks/`, `.github/`, and run the
FULL audit suite locally before pushing — not just the one validator you
remember. The recurring shape: fixing the first field-consumer you think of
and pushing; the miss is always the consumer you didn't grep for.

**A 4th consumer surfaced 2026-07-03, three weeks later, in a live
`/audit-architecture` run.** `skills/audit-architecture/references/skill_quality_audit.py`
does its own independent regex-based frontmatter parsing (not
`validate-skills.py`'s YAML parser, not `bin/audit-skill.py`'s regex) — a
THIRD parser this rule's grep sweep never reached, because at write time
`skill_quality_audit.py` wasn't recognized as a description-field consumer at
all. Its `desc_text` (lines 149-155) captured only the `description:` YAML
value and stopped at the next top-level key, structurally blind to
`when_to_use:`. Since most skills' trigger phrases and "Do NOT use" content
now live in `when_to_use`, this made C1_triggers, C2_negative, and
X2_crossref false-fail on the overwhelming majority of the corpus — a live
run scored 9/90 "Excellent" before the fix, 98/99 after. The bug had been
silently depressing every `/audit-architecture` corpus score for three weeks
without anyone noticing, because a uniformly-low score across almost the
whole corpus reads as "the corpus needs work," not "the instrument is
broken" — the same shape `verify-effectiveness.md` warns about for
detection heuristics returning implausible near-zero or near-total results.
Fixed the same way as the first two: added a `routing_text` combining both
fields, routed C1/C2/X2 through it, left the field-specific S7 check (a real
1024-char limit on `description` alone) untouched. **Lesson for STEP_1:**
"grep every reader of the old field" must include every independent
scoring/audit/quality script in the repo, not just the ones a prior incident
already named — a NEW parser written after the rule shipped is invisible to
a grep for the OLD parsers' code, and only surfaces when someone runs it
against real corpus state and the result looks implausibly bad.

---

## 2026-06-25 build-detector Lambda deploy — CI IAM under-scoped 3× in one chain
**Failure key:** `granted_ci_iam_too_narrow_or_on_wrong_role`

While wiring `build-detector.yml` to auto-deploy the real-time secret-detector
Lambda (the stale-Lambda fix — the build pushed a new image to ECR but nothing
repointed the digest-pinned Lambda, so it ran a pre-Tier-0 image for a full
day), the new "Deploy image to real-time Lambdas" step needed an IAM grant on
the role GitHub Actions assumes. The grant was under-scoped THREE times in one
deploy chain, each surfacing as a separate failed `workflow_dispatch` →
fix-forward PR round-trip:

1. **Wrong role.** `lambda:UpdateFunctionCode` was granted on `github_actions`,
   but `build-detector.yml` assumes `github_actions_mcp_servers`
   (`mcp-mcp-servers-deploy` policy). The permission was present in `ci.tf` —
   just attached to a role the workflow never assumes. Fixed by mcp-infra #509
   (moved the `LambdaRealtimeDeploy` Sid to the correct role).
2. **Missing `GetFunction`.** The deploy step's digest-verify read
   (`aws lambda get-function --query Code.ResolvedImageUri`) needs
   `lambda:GetFunction` — not implied by the "update-function-code" verb.
3. **Missing `GetFunctionConfiguration`.** `aws lambda wait function-updated`
   (the waiter that blocks until the code update settles) polls
   `lambda:GetFunctionConfiguration`. Also never announced by the headline
   verb. Both (2) and (3) fixed by mcp-infra #510.

**Mechanism.** Two compounding errors. First, the grant was scoped to the API
call the step's *headline verb* implies (`update-function-code` →
`UpdateFunctionCode`) rather than to the full API-call set of EVERY command in
the step — waiters, `--query` post-reads, and digest-verify reads each make
calls the action name never announces. Second, the permission was verified to
EXIST in the `ci.tf` source, but not that the role the workflow ACTUALLY
assumes had it (an enforcement-model gap — scope-granted in source !=
capability-exercisable by the acting role). The same shape as
`red-team-rubric-discipline.md`'s CSOD entry (granted scope != exercisable
capability) and `security-critical-search-verification.md`'s "read the runtime
enforcement model, not the surface."

**Recovery (worked).** For each missed permission: read the failed CI step log
(`AccessDenied` names the exact `iam:*` action + the assumed-role ARN), add the
permission to the `LambdaRealtimeDeploy` Sid on `github_actions_mcp_servers`,
`terraform apply`, re-run the deploy. Each miss cost one round-trip; enumerating
all three up front would have collapsed the chain to one PR.

**Prevention.** Added a "before granting CI/deploy IAM for a multi-command
step" procedure + GUARD + this failure key to the parent rule: enumerate every
command's full API-call set (incl. waiters and post-reads), grant on the role
the workflow actually assumes (read `role-to-assume`), and verify against the
LIVE attached policy (`aws iam get-role-policy`), not the `.tf` source. Paired
in the same /retro with the DEPLOY-ARTIFACT-seam GUARD in
`verify-effectiveness.md` — both are the same session's lesson that "merged +
CI green" is not "deployed and running."

---

## 2026-07-26 KB migration — deleted 4 shared scripts; the consumers were in another repo
**Failure key:** `deleted_shared_script_whose_consumer_lives_in_another_repo`

`claude-knowledge-base` #1239 replaced 310 per-topic YAML sidecars and four
generator scripts with a single compiler (`tools/kb.py`). It deleted
`.github/scripts/{finalize_topics,rebuild_backlinks,garden_checks,gen_readme}.py`
and all of `topics/manifests/`. A same-repo `git grep` was clean, so the deletion
looked safe and shipped.

**The consumers were in `claude-config`.** Five skills invoked those scripts by
ABSOLUTE path — the one shape no in-repo grep can see:

```
skills/capture/SKILL.md:400        python3 ~/Documents/knowledge-base/.github/scripts/finalize_topics.py
skills/mega-capture/SKILL.md:149   finalize_topics.py
skills/garden/SKILL.md:236         rebuild_backlinks.py
skills/absorb/SKILL.md:219,220     finalize_topics.py (+ --check)
skills/absorb/SKILL.md:388,389     garden_checks.py / rebuild_backlinks.py / gen_readme.py
```

**Worse than a missing file.** `/capture` and `/mega-capture` also instructed
staging `topics/manifests/` — a directory the new `check` explicitly REJECTS. So
following the skill did not merely fail at one command; it produced an
unmergeable KB PR. `/capture`, `/mega-capture`, `/garden`, and `/absorb` — the
primary authoring paths into the KB — were broken for a full day until #1710.

**A sixth instance the first sweep missed.** `manifests/scaffold_extended.py --kb`
was a LIVE WRITER to `~/Documents/knowledge-base/topics/manifests/`; running it
would have recreated the retired sidecars and broken the KB again. Found only by
auditing the five known-broken skills and noticing a shared dependency. Retired
in #1712 (flag + dispatch removed, dead code deleted, 5 tests pinning the
retirement — verified to fail against the pre-fix scaffold).

**Why the existing rule did not fire.** `check-before-change.md` ALREADY said
"grep every consumer" (twice). The procedure implicitly assumed consumers are in
the same repo, and `git grep` silently honors that assumption. This is the same
category error as `verify-before-assuming.md`'s
`unavailable_claims_require_failed_check_not_assumption`: absence from THIS
checkout is a property of the search, not of the world.

**The auditor already had the check — pointed the wrong way.** `bin/audit-skill.py`
D3a verifies script paths cited by skills, but treated `~/...` and `/...` as
"deployed-but-out-of-repo; skip silently." The deleted `finalize_topics.py` lines
passed D3a *because* they were absolute. The tell: my own first draft of the
#1710 fix used RELATIVE paths and D3a flagged it instantly — the asymmetry was
visible only by accident. #1712 made D3a resolve them: `~/.claude/<x>` maps onto
the repo tree, registry-matched paths verify on disk (absent → `info`, a
provisioning gap, not a broken citation), unregistered → `drift`.

**Calibration note.** The first D3a implementation produced 17 findings, ALL
false — it classified `~/.claude/` as external when it is this repo's own
deployed path. Two further passes (template placeholders like
`~/.claude/hooks/{name}.py`; scripts a skill AUTHORS before running, e.g.
mcp-create writing an AST analyzer to `~/Documents/temp/`) took it to 0 findings
across 99 skills. A check calibrated only by inspection would have shipped a
false-positive flood.

**Prevention.** STEP_3b + a GUARD in the parent rule: sweep
`~/.claude/{skills,bin,hooks}` and the sibling checkouts before deleting anything
under a shared script directory, and land the consumer's PR in the same arc. The
registry of legitimate cross-repo paths is
`skills/audit-skill/known-external-paths.yaml`.

---

## 2026-07-29 mcp-infra WAF logging — four sequential failed applies, one blocker each
**Failure keys:** `pinned_a_dependency_to_a_known_broken_release`,
`shipped_one_grant_per_failed_apply_instead_of_a_preflight`

`main` sat undeployed for roughly nine hours across four Terraform runs. Each
run surfaced exactly one blocker, each blocker was independent, and all four
were knowable before the first run.

**Run 1 — `44f65d7`, missing IAM.** `aws_wafv2_web_acl_logging_configuration`
needs `wafv2:PutLoggingConfiguration`; the CI role lacked it. This is the
2026-06-25 pattern repeating (see that entry): the grant was scoped to the
resource's headline purpose, not its full API-call set. Fixed by #744 — whose
apply created the policy version at 07:42:09Z and then tried to *use* the
permission at 07:42:15Z, six seconds later. IAM had not propagated. That is the
two-cycle rule this repo's own `CLAUDE.md` already documents ("IAM policy
changes need 2 Terraform apply cycles").

**Run 2 — `bba38d2`, the saved plan expired.** The workflow plans in
`protected-plan` and applies in a separate `apply` job behind a `production`
approval gate; each job runs its own `terraform init`. `.terraform.lock.hcl` was
gitignored from the initial commit (stock-template boilerplate — `git log -S`
confirms it was never a reasoned decision) and `main.tf` constrained only a
floor, `aws >= 5.70`. So each job independently resolved the newest provider.
The run sat 6h31m in the gate; the AWS provider published v6.57.0 at 09:22:45Z,
*inside that window*:

```
protected-plan  07:42:47Z  ->  hashicorp/aws v6.56.0
apply           14:13:50Z  ->  hashicorp/aws v6.57.0
```

Terraform correctly refused: *"Inconsistent dependency lock file … A saved plan
can be applied only to the same configuration it was created from."* This is a
property of how long the gate is held, not of the change being applied — any
approval slower than the provider's release cadence (weekly: 07-08, 07-15,
07-22, 07-29) reproduces it. Fixed by #747, committing the lock.

**Run 3 — `907d4d8`, the pinned provider was upstream-broken.** #747 was the
right fix but generated the lock at *newest*, and newest was v6.57.0 — published
~5 hours earlier, with upstream issue #49181 ("Terraform AWS Provider v6.57.0
serious bug; v6.57.1 to be released ASAP", 8 linked reports) already open for
~4 hours. The plan failed with 189 errors: 81 `InvalidSignatureException`, 49
`SerializationException`, plus `InvalidAction` / `InvalidHttpRequest` /
`SignatureDoesNotMatch`, spanning ACM, CloudWatch, EventBridge, SSM and IAM.
Not a credential fault — the OIDC step authenticated cleanly and 383 resource
refreshes succeeded before the errors began. v6.57.1 was not published yet (404
on the tag), so waiting was open-ended. Fixed by #748: `!= 6.57.0` excluding
that exact release (not a floor bump) plus a relock onto v6.56.0.

**Run 3.5 — the fix merged and triggered nothing.** #747 touched only
`.gitignore` and `.terraform.lock.hcl`, which match *none* of the workflow's
push-to-main `paths:` filter (`*.tf`, `conftest/**`, `lambda/**`, three
`scripts/check_*.py`, two workflow files). Merging it started no run at all; a
`workflow_dispatch` was required. #748 touched `main.tf`, matched `*.tf`, and
auto-triggered — the difference was predicted and confirmed.

**Run 4 — success.** Plan clean on the locked v6.56.0, `3 to add, 1 to change,
1 to destroy`, both logging configurations present in the plan. Verified at the
far end rather than by exit code: `aws wafv2 get-logging-configuration` returned
a config for both `mcp-claude-proxy-public` and `mcp-gateway` (each with
`authorization` redacted), where both had returned `WAFNonexistentItemException`
an hour earlier.

**Mechanism.** Two distinct errors compounded. (1) Each failed apply was read as
"the next permission surfaced," so the response was one more grant rather than
enumerating the other blocker classes — which are independent and each hidden
behind the one before it. (2) A dependency lock was committed at "latest"
without checking the vendor's issue tracker, on the reasonable-sounding basis
that newest = current. Newest is the release with the *least* field exposure,
and the registry keeps serving a known-broken one as latest.

**Prevention.** Two procedures + two GUARDs added to the parent rule: a
dependency-pin preflight (read back the selected version, check its publish
timestamp, `gh search issues` the vendor repo for that exact version, exclude
the exact version rather than bumping the floor) and a first-apply preflight
(permissions, plan durability, provider health, merge trigger — all four before
run 1, not one per run). The second GUARD is deliberately distinguished from
`scope-discipline`'s "STOP at the 2nd CI-apply failure": that rule says stop
grinding and search memory; this one says enumerate the other three classes on
the *first* failure.

---

## 2026-07-29 stale-docstring-vs-enforced-test
**Key:** GUARD "the file's own docstring describes this design, so I'll implement it"

`bin/preflight-skill.py`'s module docstring stated, and had stated since it was
written, that tree-mutating gates "are marked `mutates=True` and are excluded
unless `--include-marketplace` is passed." Acting on a genuine gap (a marketplace
drift failure had just reached CI), I implemented exactly that: a `marketplace-sync`
gate with `mutates=True`, the `--include-marketplace` flag, and the selection
filter. All 16 local gates passed.

CI failed on **all three platforms**:

```
scripts/test_preflight_skill.py::test_no_gate_mutates_the_tree
AssertionError: gate marketplace-sync is marked mutates=True; a mutating gate
breaks the read-only contract the pre-push ordering relies on
```

**Root cause — two compounding misreads.**

1. **The docstring described an ABANDONED design.** The project converged on
   "preflight is read-only, full stop"; the read-only contract *replaced* the
   opt-in idea. `mutates` survives on the dataclass for one reason: so the test
   has a field to assert is always `False`. That is also why `main()` never
   filtered on it — I read the missing filter as an unfinished feature rather
   than as evidence the feature was never wanted.
2. **My test search looked in the wrong places.** I globbed
   `bin/test_*preflight*`, `tests/*preflight*`, and `hooks/test-hooks/*preflight*`,
   concluded "no dedicated preflight test file", and treated the docstring as the
   only specification. The tests are `scripts/test_preflight_skill.py` — a test for
   a `bin/` tool living under `scripts/`. Searching by expected LOCATION missed it;
   searching by MODULE NAME would have found it immediately.

**The test's rationale is sound and specific**, which is what makes implementing
past it costly: `.githooks/pre-push` runs preflight FIRST and the marketplace
rebuild SECOND, and refuses to run at all with uncommitted changes in
`skills/hooks/rules/marketplace`. A preflight that writes the tree falsifies the
hook's own "read-only, so a failure needs no cleanup" claim — observed live
2026-07-28, when a `--fast` run left 4 modified files behind. `--no-marketplace-check`
on the `audit-skill` gate exists for exactly this reason.

**Fix shipped.** Reverted the gate, flag, filter, and `--list` change (back to 16
read-only gates, unchanged for existing users). Kept
`scripts/check-marketplace-sync.py` as a STANDALONE script — the manual-check
value survives without violating the contract. Rewrote the stale docstring
paragraph to state the read-only contract, NAME the test that enforces it, and
record that implementing the old wording was rejected, so the next reader does not
repeat it.

**Cost.** One 3-platform CI cycle plus a fix-forward commit. Both avoidable by one
`git grep` for the module's name.

**Generalization.** When a file's prose and a test disagree about that file's
design, the test is the contract and the prose is a claim. This is the
`verify-before-assuming` module-header rule (headers are the least-maintained doc
surface) applied to IMPLEMENTATION rather than to characterization: there the risk
is describing a capability that isn't real; here it is BUILDING one that was
deliberately removed.

---

## dead-matcher-re-enables-the-prevented-failure

### 2026-07-30 claude-config #1785 — the dead matcher and the truncation bug were ONE root cause

The macOS migration renamed the gateway MCP servers (`mcp__remote-airlock__*` →
`mcp__airlock__*`, etc.). Six prefixes went dead. The consumer sweep found them in
10 source files, and — the highest-value find — in `settings.json` hook matchers:
`auto-topic-loader.py`, `mcp-output-trimmer.py`, and `kql-schema-hint.py` were all
keyed on `mcp__remote-.*`.

**The finding that changed the analysis.** `mcp-output-trimmer` exists to shrink
large gateway responses *before* they hit the 100K `MCP_MAX_RESPONSE_CHARS` cap.
Its matcher had matched no gateway server since the migration. Earlier the same
session, an unfiltered `airlock_search_endpoints` call had truncated mid-JSON-token
and cost a real debugging arc (invalid JSON, no structured cap field — which became
PR #894). Those two findings were logged as independent. They are not: the mechanism
designed to prevent the truncation had been pointed at a tool namespace that no
longer existed, so the trimmer's death is plausibly *why* the response truncated at
all.

**Why this generalizes.** A dead matcher's obvious cost is "the hook stopped
firing," which reads as a telemetry gap. But if the hook was PREVENTIVE, its death
silently re-enables the failure it existed to stop — and that failure surfaces
somewhere else entirely, where you debug it on its own terms without connecting it
back. The rename audit correctly enumerated the dead matchers; what it did not do
was ask, for each one, *what was this stopping, and has that thing started
happening?*

**Calibration — I over-claimed, then corrected.** My first report said "three hooks
silently inert." Reading the matchers showed: `kql-schema-hint` FULLY inert;
`mcp-output-trimmer` PARTIALLY inert (still fires for hologram/netcloud, never for
a gateway server); and the `graph_request` gate FINE — it already dual-listed the
live name. Dual-listing for cross-install compatibility is a legitimate pattern
(the Linear GUID prefix is intentionally dual-listed), so "prefix is stale" does
not imply "matcher is dead" — read each one.

## 2026-06-13-skill-description-when-use-split-fixed-validate-skil

# WHY: 2026-06-13 skill description→when_to_use split — fixed validate-skills.py
# A4/A5 proactively but missed bin/audit-skill.py Q2/Q3, whose `[a-z-]+:` key-
# boundary regex excluded underscores so `when_to_use:` wasn't a field boundary;
# the description capture bled through it and false-failed the 1024 length gate
# on 2 skills. Caught only by CI; cost a fix-forward round-trip. A THIRD
# consumer surfaced AFTER the rule shipped (2026-06-14): skill eval fixtures
# tests/<skill>/*.yaml assert the description's literal content (recall must
# contain 'knowledge', ship must match /commit/) — words that had moved to
# when_to_use, breaking the eval harness on the same PR. tests/ added to STEP_1.
# A FOURTH consumer surfaced 2026-07-03, ~3 weeks later, in a completely
# different tool: skill_quality_audit.py's own `desc_text` (an independent
# regex-based frontmatter parser, not validate-skills.py's YAML parser) never
# followed the split either, so X2_crossref/C1_triggers/C2_negative false-
# failed ~89 skills for months (9/90 "Excellent" corrected to 98/99 after the
# fix). Same STEP_1 grep would have caught it on day one — it just wasn't run
# against every scripts/bin/ scorer, only the ones already known to read the
# field. Full: incidents file, 2026-06-13 entry (updated with the 4th instance).
# VARIANT — ADDING a sibling, not relocating (5th instance, 2026-07-05): fires
# equally when a NEW module-level state constant/path is added BESIDE an
# existing one. The consumer you'll miss is the TEST HARNESS that MONKEYPATCHES
# the SIBLING: grep the sibling CONSTANT's name (not just module imports/function
# names) — every _setup/fixture patching MCP_BASELINE_PATH-style siblings must
# patch the new constant too, or the suite silently writes REAL user state and
# its assertions go order-dependent on that state. claude-config #1555:
# test_consistency._setup patched MCP_BASELINE_PATH but not the new
# NEVER_CONFIGURED_STATE; the full suite wrote real ~/.claude report-state, one
# test became order-dependent, and the live "first run" verification of the new
# gate was silently pre-consumed by the test run minutes earlier.
# VARIANT — changing a GATE's MODE semantics (6th instance, 2026-07-15): fires
# when a decision function grows a new MODE (allowlist → optional blocklist in
# CAF differ._blocked_status, PR #79). The consumer you'll miss is the one that
# HAND-ROLLED the old semantics instead of calling the gate: poll.py's pre-submit
# backstop kept `not in allowlist["programs"]`, so in blocklist mode every NEW
# program's ops would FATAL "gate leaked" — silently defeating default-allow.
# Live verification passed ONLY because the fallback list happened to contain the
# two active programs (the tested seam couldn't exercise a new program). Grep
# every reader of the gate's CONFIG DICT (`allowlist.get(`/`allowlist[`) — found
# 3: backstop (bug), new-program alerting, report falsifier — and fix the class
# by making re-implementations DELEGATE to the gate function (PR #81), not by
# patching their copies.

## 2026-07-28-entra-dynamic-group-audit-both-halves-session

  # WHY: 2026-07-28 Entra dynamic-group audit, both halves in one session.
  # (a) TRUNCATED VALUE: read a membershipRule at 200 chars and concluded
  # "missing accountEnabled clause". The guard WAS present at char ~430; the real
  # bug was operator precedence (`and` binds tighter than `or`, so or-chained UPN
  # overrides bypass it). The full read gave a completely different diagnosis and
  # a completely different fix. (b) NARROW SCAN: the first detector grepped for
  # `or (user.userPrincipalName` and reported 14 affected groups; a paren-depth-
  # aware scan found 27, because department/jobTitle alternatives bypass the guard
  # identically. The same narrow scan also produced a FALSE POSITIVE (an override
  # nested INSIDE a parenthesised alternation the guard already spanned), so it
  # was wrong in both directions at once.
  # (c) 2026-07-29 INDEX-LINE-AS-CONTENT: told the user a memory was STALE because
  # the `MEMORY.md` index line named only ONE over-budget rule file. The memory
  # itself was CURRENT — its own `description:` named two files and its 78-line body
  # documented three. MEMORY.md index lines are one-line HOOKS by construction
  # ("never put memory content there"), so they are ALWAYS a subset; assessing a
  # memory's currency or completeness from its index line is structurally guaranteed
  # to under-read it. Same for any doc's `description:`/frontmatter summary. Read the
  # FILE before claiming anything about what a memory does or does not contain.

---

## 2026-07-31 NavArch/Proteus #17 — reviewed and merged a deploy change before asking if it could be applied
**Failure key:** `reviewed_a_deploy_change_without_the_apply_preflight`

A Proteus ECS task-definition change (SPP v2.1 env contract, circuit breaker,
health-check path) was reviewed in depth, improved with three follow-up fixes,
and MERGED — all before anyone checked whether the resulting config could
actually be applied. It could not. Three independent blockers, every one findable
in a single preflight pass, instead surfaced serially across four rounds.

**Blocker 1 — the artifact did not exist (new class 5).** ECR held exactly two
images, both pushed 2026-06-19. The deployed one (`af5caee`) predated the v2.1
work: `grep` of its own `run.py` showed zero hits for `SPP_DRAIN_TIMEOUT_S` and
`SPP_FORWARDED_ALLOW_IPS`. No workflow builds images (0 docker/ECR references
across all four), so the June images were hand-pushed and the v2.1 code — on
`main` since 2026-07-28 — had never been built. Applying would have set four
`SPP_*` env vars on a build that reads none of them, including the FINDING HIGH
client-IP fix, which would have looked deployed and done nothing.

The `validation` block added during review could NOT catch this, and claiming it
"enforces v2.1+" was an over-claim: this repo tags images with git SHAs, so
`^v?1\.` never matches. **A tag is not a version.** Validating the tag STRING
says nothing about the build behind it; only reading the artifact's commit does.

**Blocker 2 — `plan` had been failing outright (new class 6).**
`data.aws_ec2_managed_prefix_list.globalprotect` filtered by name, and THREE
prefix lists in the account share the name `globalprotect-allowlist` (a systemic
pattern — `ghes-prime-access`, `example-ips-allowlist`, `SoftwareBKRunners` and
`unblock-allowlist` are triplicated too, so something upstream recreates rather
than updates them). Every change to the repo was blocked, not just this one.

The partial output was itself a trap: `plan` printed
`Plan: 1 to add, 1 to change, 1 to destroy` **and then** errored, silently
omitting the ECS service and a security group. Reading the count without the exit
code would have "confirmed" a shape that was never computed.

**Blocker 3 — live state from an unmerged PR (new class 7).** Fixing blocker 2
revealed what the erroring plan had been hiding: `aws_security_group.simetrics_ec2`
showed THREE ingress rules being REMOVED — direct RDP from GlobalProtect and two
trusted-CIDR prefix lists. Those rules are live in AWS but absent from `main`;
they come from open PR #6, applied 2026-05-18 and never merged. So the next apply
from `main` would delete them and cut direct RDP to the **Simetrics** server — a
second workload the PR body explicitly described as "untouched."

**Mechanism.** Two compounding errors, one of them new. (a) Ordering: the review
graded the DIFF ("is this Terraform correct?") and never asked the orthogonal
question ("can this be applied?"). Classes 5-7 are properties of the world the
change lands in, so no amount of diff-reading surfaces them. (b) An erroring plan
is an ACCIDENTAL INTERLOCK — while it failed, nobody could apply, so drift
accumulated harmlessly and invisibly. The fix that unblocks the plan therefore
also makes that drift applyable. That consequence must be stated in the PR that
does the unblocking; shipping it silently converts a latent problem into a live
one at the next apply.

**Prevention.** Classes 5-7 added to the FIRST-APPLY PREFLIGHT, plus a second
FORBIDDEN: reviewing or approving a deploy-affecting change without them. "The
Terraform is correct" and "this can be applied" are different claims and need
different evidence.

**Cost.** ~4 discovery rounds that one preflight pass would have collapsed into
one. Net positive only because the blockers were caught before an apply — a
broken deploy plus a second-workload RDP outage were both averted.

---

## 2026-07-31 runtime-role IAM: a new API call shipped without its grant
<a id="2026-07-31-runtime-role-putmetricdata"></a>

mcp-infra #762 -> #763. #762 added a `ContentMd5Mismatch` emission to the
`mcp-anthropic-audit-v2-content` worker without granting `cloudwatch:PutMetricData`
on that Lambda's role. Production logged, on every emission:

    AccessDenied ... assumed-role/mcp-anthropic-audit-v2-content is not
    authorized to perform: cloudwatch:PutMetricData

**Why it was invisible.** The call was wrapped in `try/except` so telemetry could not
break ingestion -- correct design. The consequence is that the fix itself worked
perfectly, the mismatches were captured and logged correctly, and the metric backing
the alarm simply never existed. The defensive except and the silent failure are the
SAME CODE; the only difference is whether anything counts the failures.

**Why the asymmetry hid it.** The sibling compliance role already carried an identical
namespace-scoped `ControlMetrics` statement, so `ChatCursorPendingAgeHours` (emitted by
the compliance Lambda) published fine while `ContentMd5Mismatch` (content Lambda) could
not. One lane working masked the other.

**How it surfaced.** Not by any alarm -- by grepping the content worker's logs for an
unrelated reason. An alarm on a never-emitted metric sits in INSUFFICIENT_DATA (or
breaches on missing data) indefinitely, indistinguishable from a quiet system.

Distinct from the CI/deploy IAM under-scope (2026-06-25, same rule): that one produces a
FAILED APPLY you cannot miss. This one deploys green.


<!-- extracted 2026-08-01: ambient-context reduction -->

## ci-workflows-hook-configs-import-statements-settings-json-hook

```
WHY: CI workflows, hook configs, import statements, settings.json hook
     commands may reference the file. Deletion without a grep breaks
     CI silently.
```

## recently-merged-twin-2026-06-14-a-second-session

```
WHY (recently-merged twin): 2026-06-14 — a second session began building the
/lab-review skill ~14 min after another session MERGED it (#1276). Invisible to
`--state open`; caught only because a just-updated sibling doc (skill-standards.md)
cited "#1276". Pivoted to a fix-forward refinement (#1278) instead of a duplicate.
```

## 2026-06-12-fable-5-recompute-the-codebase-memory

```
WHY: 2026-06-12 Fable 5 recompute — the codebase-memory-mcp consolidation
left 2 dead hook matchers (vocab-divert, chunk-drop), a stale TOOL_HINTS
map, 2 ambient routing rules asserting dead tools, and 15 skills citing
them. Wiring decay outpaced model decay. Fixed in PRs #1203/#1205/#1208;
the skills-layer pass is the enumerated remainder.
```

## 2026-06-25-build-detector-lambda-deploy-step-iam

```
WHY: 2026-06-25 build-detector Lambda-deploy step — IAM under-scope hit THREE
times in ONE chain: (1) UpdateFunctionCode granted on `github_actions` but
the workflow assumes `github_actions_mcp_servers` (#509 moved it); (2)
GetFunction then (3) GetFunctionConfiguration missing — the `aws lambda wait
function-updated` waiter polls GetFunctionConfiguration, which the verb
"update-function-code" never announces (#510). Each miss = one failed deploy +
fix-forward round-trip. Same enforcement-model gap as
red-team-rubric-discipline.md's CSOD entry (granted-scope != exercisable).
```

## 2026-07-29-mcp-infra-locked-aws-v6-57

```
WHY: 2026-07-29 mcp-infra — locked `aws v6.57.0` ~5h after publish; upstream
#49181 ("serious bug; v6.57.1 ASAP") had been open ~4h. Next apply: 81
InvalidSignatureException + 49 SerializationException. Full: incidents file,
2026-07-29 entry.
```

## 5-7-2026-07-31-navarch-proteus-17-reviewed

```
WHY (5-7): 2026-07-31 NavArch/Proteus #17 — reviewed, fixed and MERGED before
anyone asked whether it could be applied; 3 blockers, one pass apart, surfaced
over four rounds. Full: incidents file, 2026-07-31.
```

## 2026-07-28-azure-automations-about-to-edit-the

```
WHY: 2026-07-28 azure-automations — about to edit the `Daily` schedule's
startTime to stagger 4 backup runbooks off a git-ref race. `Daily` is ONE
SHARED object bound to 27 runbooks (the 4 + ExchangeAudit, DisabledUserGroups,
CrowdStrikeTags and 20 more); the edit would have rescheduled the entire
nightly fleet. Caught by a blast-radius check BEFORE the write. Fix was 3 new
per-runbook schedules + re-link + delete the old links (the delete needs
`properties.jobScheduleId`, since the list returns `name: null`).
```

## 2026-07-29-implemented-preflight-skill-py-s-documented

```
WHY: 2026-07-29 — implemented preflight-skill.py's documented
`--include-marketplace` + `mutates=True` design; `test_no_gate_mutates_the_tree`
forbids ANY mutating gate (preflight must be read-only for the pre-push
ordering). Failed on all 3 platforms; the field existed only so the test could
assert it is always False. Full: incidents#2026-07-29-stale-docstring-vs-enforced-test
```

## 2026-07-26-mcp-infra-both-halves-failed-in

```
WHY: 2026-07-26 mcp-infra, both halves failed in one session.
(1) CONVENTION: recommended adding `Owner` to the provider `default_tags` to
    satisfy an org SCP. One grep showed the repo already handled that SCP at
    FIVE sites, per-resource, with citation comments (ecs.tf:373,
    otel-realtime-detection.tf:225, ...). The proposal would have diverged
    from an established pattern AND churned tags on every existing resource.
(2) DUPLICATE: was one command from building the fix when `git worktree add`
    failed on an existing branch name — PR #687 had already been opened by a
    parallel session doing exactly that work, with a better test than planned.
    The save was an incidental error message, not process.
```

## 2026-06-11-built-validated-a-complete-duplicate-of

```
WHY: 2026-06-11 — built+validated a complete duplicate of open PR
#1174 (same root cause, same 4 manifests); caught only by a temp-file
name collision, not by process. Full: incidents file, 2026-06-11 entry.
```

## 2026-07-05-built-a-kaggle-submission-from-the

```
WHY: 2026-07-05 — built a Kaggle submission from the research repo's `main`
(v1 attack, ~0-firing) and pushed 2 rejected notebook versions while
re-deriving the submit-gate fix, when open PR #11 already held the verified v2
submission notebook AND a README documenting the exact fix. User had to
redirect ("check the latest PR"): ~2 wasted versions + a wrong "CLI can't
submit this competition" conclusion that the PR's README already refuted.
```

## 2026-07-26-claude-knowledge-base-1239-deleted-four

```
WHY: 2026-07-26 — claude-knowledge-base #1239 deleted four
.github/scripts/*.py; a same-repo grep was clean, so it shipped. FIVE skills
in claude-config still invoked them by absolute path (and staged a directory
`check` now rejects), breaking /capture, /mega-capture, /garden, /absorb for
a full day until #1710. Full: incidents/check-before-change.md.
```

## 2026-07-31-mcp-infra-762-763-a-metric

```
WHY: 2026-07-31 mcp-infra #762 → #763 — a metric emission shipped without its grant;
the try/except made it invisible and the sibling role's identical statement masked the
asymmetry. Full: incidents#2026-07-31-runtime-role-putmetricdata
```

## 2026-07-29-locked-aws-v6-57-0-5h

```
WHY: 2026-07-29 — locked `aws v6.57.0` ~5h after publish; upstream #49181
("serious bug; v6.57.1 ASAP") had been open ~4h. One `gh search issues`
call would have caught it; instead it cost a 4th failed apply.
```

## 2026-07-30-mcp-infra-756-757-758-a

```
WHY: 2026-07-30 mcp-infra #756 -> #757 -> #758. A content-lane freshness control was
keyed on `content-metadata-v2` kind=chat/kind=project because those are the lane's
only `_now()`-written (ingest-time) artifact. That property was real and verified.
Both write sites are `_store_chat_tombstone` / `_store_project_tombstone` — hydration
FAILURE paths — so ZERO such objects exist when the lane works. Measured post-apply:
ContentKindsStale = 2 hourly on a healthy lane until reverted. Replacement is
`AWS/Lambda Invocations`, AWS-emitted and not empty-by-construction.
INVERSE of the "control reports SUCCESS while doing nothing" family (five instances,
the monitoring topic notes, 2026-07-26/27): this reports FAILURE while
doing everything right. Same root — the control's signal was never checked against
the healthy state.
```

## additional-instance-2026-07-31-wrote-a-regex-assuming

```
WHY (additional instance): 2026-07-31 — wrote a regex assuming KB entries are dated
`(YYYY-MM-DD)` headings; two target pages actually use `[LIVE date]`/`[SRC]` markers.
Miscounted 1 vs the real 4, downgraded a topic page's stage incorrectly. kb.py (the
repo's own compiler) already implemented the correct rule — reading it first, instead of
re-deriving the convention from a couple of example files, would have caught it.
```


## 2026-08-01 audit-v2 compliance lane — an agreement-phrased diligence search missed a refutation

Before shipping PR #764 (removing a DLQ-empty gate from a chat-cursor drain check to end a
livelock), the diligence query was phrased IN AGREEMENT with the intended change. It surfaced the
exact KB entry documenting why the gate exists — added after a prior bug lost 825 chats — at cosine
0.51, below the visible dedup threshold, and it read as SUPPORTING CONTEXT rather than as a
refutation. #764 merged and applied to production. About two hours later /capture's Step 4a
contradiction gate, which runs an OPPOSITE-phrased query, surfaced the same entry and correctly
flagged a live data-durability regression on a 14-day SQS-retention fuse.

FIX: when a change REMOVES, LOOSENS, or DISABLES an existing check/gate/guard — not only when
adding something new — the STEP_1 diligence search MUST include at least one query phrased as the
OPPOSITE of the intended change ("<X> must always stay enabled" / "<X> exists because <the bug it
prevented>"), not only a query phrased in agreement with it. Treat any hit from a fail-safe or
durability design note as stop-and-present-conflict REGARDLESS of its cosine relative to the
agreement-phrased query — the agreement framing systematically depresses the score of the very
document that would refute you.

EVIDENCE (verbatim): "The gate works because it queries the opposite of your claim. My
agreement-phrased dedup query surfaced the very same KB entry at cosine 0.51 and I'd have read it
as supporting context. The opposite-phrased query — 'auto-redrive should always stay enabled' —
surfaced it as a refutation."

---

## 2026-08-08 confluence-gov review — reported a fixed finding because the checkout was stale
**Failure key:** `reviewed_a_stale_working_copy_and_reported_it_as_current`

Asked to review a newly-built MCP server, I read `govcloud/mcp-confluence/README.md` on
disk and reported that its network model was wrong: it described an internal/Tailscale ALB
while `network.tf` sets `internal = false` and admits `0.0.0.0/0` on 443. The finding was
real in the bytes I read, graded HIGH, and presented as open.

**It had been fixed roughly two hours earlier.** PR #889 — my own, same day — had already
reconciled that prose to the internet-facing SSO-only model. My local checkout was one
commit behind, so I reviewed content that no longer existed upstream and told the user a
solved problem was outstanding.

**What made it slip past the existing rule.** `check-before-change.md` already required
verifying current state and already forbade recommending already-shipped work — and I had
*read the actual file*, which felt like satisfying it. That is the category error: reading
proves what YOUR CHECKOUT holds, and a review is a claim about what the REPO holds. Same
shape as `verify-before-assuming.md`'s "absence from this checkout is a property of the
search, not of the world," applied to presence rather than absence.

The host makes this likely rather than exotic: `~/.claude` local main measured 22 commits
behind during this same session, and "local checkout N commits behind" has been a P1 in
multiple consecutive retros (37, then 38). Any review that does not fetch first is sampling
a random point in the past.

**One line of the finding was genuinely open** — the "Also required before the service is
usable" list still told operators to "replace `tailscale_cidrs` with the real ranges", a
variable with zero hits in `variables.tf`, so the instruction was unfollowable and
contradicted the corrected model 80 lines above it. Fixed in #890 with a positive "there is
no network-CIDR step" correction rather than a deletion, because the Tailscale framing is in
enough heads that silence invites re-adding it.

**Cost.** One wrong HIGH finding presented to the user, plus the correction. Prevented by
one `git fetch` before the first Read — which is now a GUARD in the parent rule rather than
an implication of "verify current state."
## 2026-08-09 Azure Sentinel cleanup — two proposed deletions would have severed live feeds
**Failure key:** `inferred_stale_from_metadata_field_instead_of_measuring_producer_and_consumer`

An Azure cost/coverage review produced a 26-item action register. Two of its
"cleanup" items were wrong in the same way, and both were caught only because the
execution step measured before deleting.

**(a) Four "stale" data connectors were the LIVE producers.** `M6` read: *4 data
connectors report their data types `disabled` while data flows — clean up the
stale objects.* The evidence was the connector object's
`properties.dataTypes[].state == "Disabled"`. Before deleting, a producer query:

```
248,631  OfficeActivity          SourceSystem=OfficeActivityManager
310,573  ThreatIntelIndicators   SourceSystem=Microsoft Defender Threat Intelligence
```

`OfficeActivity` had taken **17,906 rows in the preceding 3 hours**, newest 22:56.
The Office365 connector was not stale — it was the thing delivering M365 audit
data. `MicrosoftThreatIntelligence` likewise fed the 3.57M-row
`ThreatIntelIndicators` table that the SAME session's rule rewrite had just been
made to depend on, so the deletion would have broken the fix in the same breath.
`dataTypes[].state` is per-datatype configuration metadata; it does not track flow.

**(b) Three "empty" workspaces all backed live App Insights components.** `N2`
read: *3 empty workspaces — delete for hygiene.* Two were named `managed-*` and
one was a `DefaultWorkspace-*`, which read as auto-generated leftovers. A
relationship query (`microsoft.insights/components` → `WorkspaceResourceId`)
returned a consumer for every one:

| Workspace | Consumer |
|---|---|
| `managed-func-rr-entra-example-ws` | App Insights `func-rr-entra-example` (the RunReveal function) |
| `managed-ai-govslack-deprov-ws` | App Insights `ai-govslack-deprov` |
| `DefaultWorkspace-…-USBN1` | `Cornerstone` + `Paycom` — **receiving telemetry that same day at 19:00** |
| `DefaultWorkspace-…-SN` | `Trigger-TravelExemption-Runbook` |

The `managed-*` pattern is Azure auto-creating one workspace per
workspace-based App Insights component **by design**. Even the genuinely 0-GB
`-SN` workspace has a consumer; it is empty only because that Logic App is
Stopped — a separate, unrelated decision. Zero of the four were safe to delete.

**Mechanism.** Both findings were generated by reading a cheap surface — a status
field, a name, a volume number — and none by asking what writes to the object or
what reads from it. The parent rule already said "grep every consumer," but that
procedure was scoped to *changing a contract or a shared object*; neither of
these was a contract change, so the procedure did not fire on a plain "this looks
like leftover cruft, delete it." That scoping gap is what STEP_3b closes.

**What worked.** The three checks that refuted the findings each cost one query:
`summarize by SourceSystem` (who writes), a Resource Graph join on the consumer
type (who reads), and a `max(TimeGenerated)` (is it live right now). Run before
the delete, they cost seconds; run after, they would have been an incident review.

**Contrast with a real one.** In the same register, `M9` (a dangling Sentinel AWS
role + 2 queues) was ALSO proposed for deletion — and there the measurement
CONFIRMED it: `RoleLastUsed` was that same day and the queue was draining ~3.5K
msg/day, yet `AWSCloudTrail` held 0 rows for 3 days. That is genuinely a live-but-
useless path. The same two questions separated the two cases; the difference was
asking them, not guessing better.

**Related.** `knowledge-base/topics/engineering-assessment-measurement-validity.md`
("Never infer CONFIGURATION state from a telemetry counter", 2026-07-30) is the
inverse direction — a zero counter misread as "not configured". Here a
configuration field was misread as "not flowing". Both are the same error class:
substituting the cheap adjacent read for the expensive direct one.

## An extension-filtered grep is not a consumer census (3 instances in 2 days, 2026-08-27/28)

Check #5 commands mapping every consumer of a contract before changing it. All
three misses below had the RIGHT intent and the WRONG instrument — a grep whose
`--include='*.py' --include='*.tf' ...` list silently excluded the file that
carried the consumer:

1. Alarm re-key (mcp-infra #1556): the sweep for `SessionContentFailed` missed
   `tests/anthropic_session_capture_contract.tftest.hcl` (`.tftest.hcl` was in
   no include list). Cost: one fix-forward CI cycle — Terraform-native tests
   pin alarm attributes and only CI runs them.
2. Same PR, earlier: `lambda/test_anthropic_session_terraform.py` literal pin
   was found only by the full unittest discover, not the sweep.
3. Quarantine contract evolution (mcp-infra #1551/#1344, previous day): the
   consumer census missed `lambda/sec_automations_query_runner.py` — a RUNTIME
   reader of the manifest completeness status. The analyst "Pull session"
   button dead-ended on every quarantine-certified day until a pipeline-map
   subagent found it a day later (#1566 fixed it).

RULE OF INSTRUMENT: when changing a contract token (metric name, schema status,
field, threshold), the census sweep is `grep -rn "TOKEN" .` with NO extension
filters (exclude only `.git`/`.terraform`), plus the sibling repos that mirror
the contract. Extension filters may be used to ORGANIZE results, never to bound
the census. Sibling KB entry: sealed-artifact-contract-evolution.md ("the
consumer census includes payload constructors") — that instance missed
build-time consumers; these missed test-pin and runtime consumers the same way.
