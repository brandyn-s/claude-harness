@rule check_before_change
@version 2026-06-14
@scope every modification to existing behavior, every file deletion, every cross-repo copy, every recommendation, every fix built from a shared work surface (session-start banner, consistency findings, CI digest) in a contended repo

# ─── INVARIANTS (always-true) ───

INVARIANT never_modify_existing_behavior_without_checking_why
  # WHY: features and defaults have history. Changing them without knowing
  #      why they are what they are re-introduces problems that were
  #      deliberately solved.

INVARIANT never_delete_files_without_grepping_for_references
  # WHY: CI workflows, hook configs, import statements, settings.json hook
  #   Full: incidents#ci-workflows-hook-configs-import-statements-settings-json-hook

INVARIANT never_bulk_copy_over_divergent_target
  # WHY: the target may have accumulated changes the source lacks.
  #      Bulk-copy destroys those additions.

INVARIANT verify_deployed_state_before_recommending
  # WHY: recommending work that's already done erodes trust and wastes
  #      cycles. Parallel sessions and teammates also ship changes.

# ─── WHAT COUNTS AS "CHANGING EXISTING BEHAVIOR" ───
SCOPE: removing code/features/config that currently exists
SCOPE: changing defaults (thresholds, flags, model overrides)
SCOPE: adding context:fork, model:, disable-model-invocation to skills
SCOPE: re-adding features that don't currently exist (may have been removed deliberately)

# ─── PROCEDURE: before changing existing behavior ───
STEP_1 memory_search(feature_name)  # check KB topics, pattern files, agent memory
STEP_2 git log --oneline --all -- <file>  # history of changes
STEP_3 IF rationale_found_that_contradicts_change:
         STOP. Present the conflict. "Was set to X because Y; change would Z. Proceed?"
STEP_4 IF no_rationale_found:
         Note "no prior decision found" and proceed, flagged as unverified.

# ─── PROCEDURE: before deleting a file ───
STEP_0 IF the file's existence is UNEXPLAINED (you didn't create it and no
        known process accounts for it): capture attribution evidence FIRST —
        `stat` it (mtime narrows WHICH caller/session wrote it) and copy it
        to $TMPDIR — before any deletion. The file IS the evidence; deletion
        destroys the only forensic record, and cleanup can wait ten seconds.
STEP_1 git grep <filename>  # catches CI workflows, imports, hook configs
STEP_2 check settings.json + settings.local.json for hook command refs
STEP_3 check .github/workflows/*.yml for `run:` commands invoking the file
STEP_3b GREP THE SIBLING REPOS. `git grep` stops at the repo boundary, so a
        same-repo-clean result is NOT evidence the file is unused — the caller
        may live in another checkout entirely. Scripts under `.github/scripts/`,
        `bin/`, `tools/`, and `scripts/` are the high-risk shapes, because other
        repos invoke them by ABSOLUTE path (`~/Documents/<repo>/tools/x.py`),
        which no in-repo grep can see. Sweep the checkouts that could call it:
          grep -rn "<filename>" ~/.claude/skills ~/.claude/bin ~/.claude/hooks \
            ~/Documents/GitHub/*/ 2>/dev/null | grep -v '/\.git/'
        Registry of legitimate cross-repo paths:
        `~/.claude/skills/audit-skill/known-external-paths.yaml`.
STEP_4 IF references_exist → update/remove them in the SAME commit; if the
        reference is in ANOTHER repo, that repo needs its own PR — say so
        explicitly rather than leaving the caller broken, and land both before
        calling the deletion done.
FORBIDDEN: reading a clean `git grep` as proof a script is unreferenced. The
           boundary the grep stops at is exactly where the caller lives.

# ─── PROCEDURE: before copying files between repos or forks ───
STEP_1 git diff <source>..<target>  # see divergent additions
STEP_2 FORBIDDEN: bulk-copy source files over target files
STEP_3 apply changes surgically — read both, identify delta, patch target
STEP_4 IF using python str.replace → read target first to confirm pattern exists

# ─── PROCEDURE: before scripted edits after a merge / rebase / stash-pop /
#     A POSTTOOLUSE FORMATTER ───
# A formatter counts: after Write/Edit, a PostToolUse hook may reorder imports,
# strip a trailing `# noqa`, or rewrap a line, so anchors copied from what YOU
# wrote no longer match what is ON DISK. The harness even says so
# ("PostToolUse hook modified <file> ... likely a formatter") — treat that
# notice as an anchor-invalidation event, not noise. (2026-08-04: a patch
# script asserted `from .index_staleness import heal_candidates, _short`;
# the formatter had alphabetised it to `_short, heal_candidates`.)
# Auto-merge may have already applied some of your planned hunks; anchors
# taken from the pre-merge file no longer match, and a failed assert
# mid-script aborts before any write — or after partial writes.
# (Incident: 2026-06-11 code-search #229 conflict resolution — heredoc edit
#  script asserted pre-merge anchors that git had already auto-merged.)
STEP_1 re-read the CURRENT file state, not the pre-merge copy you planned from
STEP_2 IF a planned hunk is already present → drop it from the edit script
STEP_3 prefer idempotent edit scripts: verify-then-write, never write-then-hope

# ─── PROCEDURE: before recommending a change ───
STEP_1 read_target_file  # if already in proposed state, recommendation is moot
STEP_2 git log --oneline -5 -- <file>  # parallel session may have landed change
STEP_3 grep for target pattern in the file
STEP_4 IF target_state_already_exists → say "already done in <commit/PR>" and skip

# ─── PROCEDURE: before building a fix sourced from a shared work surface ───
# Fires when the work item came from a surface EVERY session sees
# (SessionStart banner, consistency findings, index-staleness warnings,
# CI digest) AND the repo is contended (session start reports another
# active session / dirty files). Shared surfaces are an unclaimed work
# queue: concurrent sessions derive the SAME fix independently.
# (See incidents file: 2026-06-11 duplicate of open PR #1174.)
STEP_1 gh pr list --repo <org/repo> --state open  # scan titles vs the finding's keywords
        AND `gh pr list --state merged --search "<keyword>"` (last ~24h) AND
        `git log --all --grep="<keyword>"` — a parallel session may have MERGED a
        twin MINUTES ago, and a just-merged twin is invisible to `--state open`.
STEP_2 IF an open PR covers the finding → repair/queue THAT PR (diagnose its
        CI, fix forward); do NOT build a parallel version
STEP_2b IF a MERGED twin already shipped the finding → STOP; verify it, and if it
        has gaps THIS session's work would close, fix-FORWARD on top of it (a
        refinement PR) — do NOT re-implement.
STEP_3 IF no twin exists → build, and re-run the scan BEFORE opening your PR
        (build time is long enough for a twin to appear)
FORBIDDEN: treating "git log shows nothing merged" as proof the finding is
            unclaimed — open PRs are invisible to git log.
FORBIDDEN: scanning only `--state open` in a fast-moving contended repo — a twin
            can MERGE between your fetch and your build.
# WHY (recently-merged twin): 2026-06-14 — a second session began building the
#   Full: incidents#recently-merged-twin-2026-06-14-a-second-session
FORBIDDEN: probing "does branch/main already have this change?" by grepping
            for YOUR implementation's identifier names — grep for the
            modified SITE or behavior (the line being changed), not your
            variable names. (2026-06-11: PYTHON_BIN probe missed main's
            equivalent $PY fix; merge conflicted exactly there.)

# ─── PROCEDURE: before constructing instances of an unfamiliar type ───
# Fires when writing a test, integration harness, or any code that
# constructs a struct/enum/record from a crate/module you haven't recently
# read. Compile-time errors from field name/type mismatches eat 1-3
# turn-cycles per PR. (See incidents file: 2026-04-25 sbom-vex.)
STEP_1 read the type's definition in its crate (struct fields, enum variants)
STEP_2 note: optional vs required, type variances (Option<T> vs T),
              nested types (Vec<Affect> vs Vec<BomRef>)
STEP_3 IF the type is in the public API (pub struct), check if a constructor
        exists (`Type::new`, `Type::default`); prefer that over struct literal
STEP_4 IF struct literal is required, copy the field list verbatim from
        the definition into your code
FORBIDDEN: assuming field names from prior knowledge of similar types

# ─── PROCEDURE: before changing an API response shape ───
# Fires when modifying the JSON shape of an existing endpoint — adding,
# removing, renaming, or restructuring fields a deployed caller already
# reads. Failure mode is silent render breakage, not a loud crash.
# (See incidents file: 2026-05-18 ExampleApp admin agent-prompt.)
STEP_1 grep every consumer of the endpoint by path. Frontend + backend:
        Grep("/admin/agent-prompt", glob="prototype/**", path=".")
        Grep("/admin/agent-prompt", glob="**/*.py", path=".")
STEP_2 for every match, read the file and check what fields the caller
        consumes from the response. Old-shape readers silently break.
STEP_3 patch every affected caller IN THE SAME PR, OR keep both shapes
        on the server until consumers migrate.
FORBIDDEN: shipping the server shape change without verifying every
            consumer accepts the new shape.

# ─── PROCEDURE: before renaming/consolidating an MCP server's tools ───
# Fires when a server is renamed, merged (e.g. code-search + code-graph →
# codebase-memory-mcp), or re-registered under a new prefix. Tool names are
# an API surface whose consumers are wired by STRING MATCH — they fail
# SILENTLY: a hook matcher on an old name can never fire again (dead
# matcher), and routing tables keep asserting tools that don't exist.
STEP_1 grep settings.json + settings.example.json hook MATCHERS for the old prefix
STEP_2 grep hooks/*.py internals — tool_name checks and TOOL_HINTS-style maps
STEP_3 grep rules/ routing tables (mcp-tool-names.md, web-search-preference.md)
STEP_4 grep skills/*/SKILL.md + manifests (allowed-tools, requires_tools)
STEP_5 fix every consumer in the SAME PR, or enumerate the deferred set explicitly
FORBIDDEN: reading a zero-fire matcher as "just quiet traffic" — verify its
            tool still EXISTS before trusting silence; fire telemetry cannot
            distinguish a dead matcher from a quiet one.
STEP_6 for each dead matcher, ask WHAT IT WAS PREVENTING and whether that failure
        has been recurring — killing a preventive hook silently RE-ENABLES its
        failure, which then surfaces elsewhere as an unrelated-looking bug.
        INCIDENT 2026-07-30. Full: incidents#dead-matcher-re-enables-the-prevented-failure
# WHY: 2026-06-12 Fable 5 recompute — the codebase-memory-mcp consolidation
#   Full: incidents#2026-06-12-fable-5-recompute-the-codebase-memory

# ─── PROCEDURE: before relocating content between fields of a structured artifact ───
# Fires when MOVING content from one frontmatter/config/manifest key to another
# (e.g. trigger phrases + "Do NOT use" out of a skill's `description:` into
# `when_to_use:`) — NOT changing a value, but changing WHICH FIELD holds it.
# Every validator/hook/script that read the OLD field now sees less; the
# readers fail SILENTLY at lint/CI time, not at edit time.
STEP_1 grep EVERY reader of the old field across scripts/ bin/ hooks/
        .github/workflows/ AND tests/ — e.g. `grep -rn "description" bin/
        scripts/ tests/`. There is always more than one (a length gate here, a
        trigger-phrase scan there, an EVAL-FIXTURE in tests/<name>/*.yaml that
        pins the field's literal content).
STEP_2 for each reader: does it assume the relocated content still lives in the
        old field? Update it to read the NEW field, or the COMBINED old+new text.
STEP_3 fixing the ONE obvious validator is NOT enough — the miss is the SECOND
        reader, often with a fragile parser (a regex key-boundary that excludes
        `_` won't recognize `when_to_use:` as a field and bleeds the capture).
STEP_4 run the FULL lint/audit suite locally before pushing — CI runs more
        checks (audit-skill, validate-skills, eval harness) than you remember.
FORBIDDEN: fixing the first field-consumer you think of and pushing. The miss
            is always the consumer you didn't grep for.
# WHY: 2026-06-13 skill description→when_to_use split — fixed validate-skills.py
#   Full: incidents#2026-06-13-skill-description-when-use-split-fixed-validate-skil

# ─── PROCEDURE: before granting CI/deploy IAM for a multi-command step ───
# Fires when authoring (or extending) the IAM policy a CI/deploy job assumes —
# adding a permission so a workflow step can call a cloud API. The failure is a
# too-narrow grant: the step makes MORE API calls than the one verb its name
# implies, and the policy may be attached to a DIFFERENT role than the one the
# workflow actually assumes. Both fail only at deploy time — one
# missing-permission fix-forward round-trip each (~build+CI per miss).
STEP_1 enumerate the API calls of EVERY command in the step, not just the
        headline verb. One CLI command often makes several:
          aws lambda update-function-code   → lambda:UpdateFunctionCode
          aws lambda get-function           → lambda:GetFunction
          aws lambda wait function-updated  → lambda:GetFunctionConfiguration (polls)
          aws ecs update-service            → ecs:UpdateService + ecs:DescribeServices
        Waiters, `--query` post-reads, and digest-verify steps each add calls
        the action name never announces.
STEP_2 identify the role the workflow ACTUALLY assumes — read the job's
        `role-to-assume` (the `aws-actions/configure-aws-credentials` block /
        OIDC sub), not the generically-named role. Grant on THAT role.
STEP_3 verify against the LIVE attached policy, not the .tf source:
          aws iam get-role-policy --role-name <role> --policy-name <p>
        A permission present in ci.tf proves nothing until it is attached to
        the acting role AND applied. "It's in the .tf" is an authoring claim;
        the attached policy is the enforcement reality — scope-granted !=
        capability-exercisable.
STEP_4 scope Resource to the specific ARN pattern the step touches
        (`function:mcp-realtime-*`), not `*`.
FORBIDDEN: granting only the permission for the verb you ASSUMED the step
            used, without enumerating every command's full API-call set.
FORBIDDEN: treating "the permission exists in ci.tf" as proof the acting role
            has it — confirm with get-role-policy against the role the workflow
            assumes.
# WHY: 2026-06-25 build-detector Lambda-deploy step — IAM under-scope hit THREE
#   Full: incidents#2026-06-25-build-detector-lambda-deploy-step-iam

# ─── PROCEDURE: before pinning or locking a dependency to a specific version ───
# Fires when generating/refreshing a lock (`terraform providers lock`,
# pip-compile, package-lock), bumping a pinned SHA/tag, or choosing a base
# image. The resolver's default is "take the newest" — and the newest release
# is the one with the LEAST field exposure. A same-day release can already be
# known-broken upstream while the registry still serves it as latest.
STEP_1 read back the version the resolver ACTUALLY selected (from the lock or
        manifest). Do not assume it took the floor you wrote.
STEP_2 read that version's PUBLISH TIMESTAMP. Younger than ~48h = almost no
        field exposure; treat it as unproven, not as "current".
STEP_3 check the vendor's OWN issue tracker for that exact version BEFORE
        committing the pin. One call:
          gh search issues --repo <vendor/repo> --state open "<version>"
        A "serious bug / patch ASAP" issue is the signal. It will NOT be in the
        release notes, and the registry keeps serving the release regardless.
STEP_4 IF the selected version has an open critical issue → exclude that EXACT
        version (`!= 6.57.0`) rather than bumping the floor, relock, and record
        the upstream issue id inline at the constraint with the condition for
        removing the exclusion.
FORBIDDEN: committing a lock/pin at "latest" without STEP_2 + STEP_3 when that
            pin gates a deploy, an apply, or CI for everyone.
# WHY: 2026-07-29 mcp-infra — locked `aws v6.57.0` ~5h after publish; upstream
#   Full: incidents#2026-07-29-mcp-infra-locked-aws-v6-57

# ─── FIRST-APPLY PREFLIGHT (7 independent blocker classes, check ALL before run 1) ───
# On a gated cloud apply, each unchecked class surfaces ONE PER RUN, so N
# unchecked = N failed applies (each costing a plan + a human approval).
# RUN BEFORE REVIEWING a deploy-affecting change, not after shipping it: 5-7 are
# properties of the WORLD the change lands in, invisible to a diff review.
#   1 PERMISSIONS — the resource types the plan CREATES, full API-call set,
#     against the LIVE attached policy of the assumed role (IAM procedure above)
#   2 PLAN DURABILITY — plan and apply in separate jobs with a gate between?
#     then the lock must be COMMITTED and the constraint BOUNDED, or the saved
#     plan expires whenever a release lands during the approval wait
#   3 PROVIDER HEALTH — the dependency-pin preflight above, on the version this
#     plan will resolve
#   4 TRIGGER — will merging actually START the pipeline? Read the workflow's
#     `paths:` filter; a fix outside it merges and runs NOTHING
#   5 ARTIFACT EXISTS AND HONORS THE CHANGE — does the image/build the change
#     points at EXIST, and does THAT build read the contract being wired? List
#     the registry, read the deployed tag, grep the artifact's OWN commit for the
#     new env/flag/route. A git-SHA tag cannot be graded by a version regex, so
#     validating the tag STRING proves nothing about the build behind it. New env
#     on a build that never reads it is a SILENT no-op that looks deployed.
#   6 PLAN RUNS AT ALL — `plan` exits 0 on the CURRENT tree BEFORE reviewing a
#     change that must be applied. An erroring plan blocks EVERY change and is an
#     accidental interlock: drift accrues behind it, so the fix that unblocks the
#     plan also makes that drift APPLYABLE. Say so in the PR.
#   7 LIVE STATE FROM UNMERGED PRs — `gh pr list --state open` for PRs touching
#     the same resources, then diff live-vs-`main` there. An applied-but-unmerged
#     PR means apply-from-`main` REVERTS it, deleting live config nobody
#     declared. Merge that PR first; never re-implement its change in yours.
# FORBIDDEN: reading a failed apply as "the next permission surfaced" and
#   shipping one more grant without checking the other classes.
# FORBIDDEN: reviewing/approving a deploy-affecting change without 5-7. "The
#   Terraform is correct" and "this can be applied" are different claims.
# WHY: 2026-07-29 mcp-infra — main undeployed ~9h across FOUR runs, one per
# class, all four knowable before run 1. Full: incidents file, 2026-07-29.
# WHY (5-7): 2026-07-31 NavArch/Proteus #17 — reviewed, fixed and MERGED before
#   Full: incidents#5-7-2026-07-31-navarch-proteus-17-reviewed

# ─── USER OVERRIDE POLICY ───
# Check-before-change is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="the rule/config/policy says X, so the bug is Y" (concluded from a
  TRUNCATED value — a `[:200]` print, a table column, a grep line, a UI preview,
  a MEMORY.md index line, a doc's `description:`/frontmatter summary),
  or "my scan found N instances" (from a pattern matching ONE syntactic form):
  REFUSE the diagnosis until you read the value at FULL LENGTH and confirm the
  scan's pattern covers every form the construct can take. Both are the same
  error — reporting a SUBSET as the whole — and both fail silently, because a
  truncated value and a narrow pattern each return plausible, well-formed,
  wrong answers. For a value: print `len()` alongside it, and re-read untruncated
  before any causal claim. For a scan: state what forms the pattern does NOT
  match, and validate against a KNOWN-POSITIVE plus a KNOWN-NEGATIVE before
  trusting the count. NO EXCEPTIONS for a diagnosis or count you will report.
  # WHY: 2026-07-28 Entra dynamic-group audit, both halves in one session.
  #   Full: incidents#2026-07-28-entra-dynamic-group-audit-both-halves-session

GUARD pattern="edit the <named shared object> so <my thing> behaves differently"
  (a NAMED, REFERENCEABLE config object: a schedule, an IAM policy, a security
  group, a launch template, a shared runtime environment, a k8s ConfigMap):
  REFUSE the edit until you ENUMERATE ITS CONSUMERS. A named object is
  reference-by-name, so N things can point at it while its name suggests one
  owner — and editing it changes ALL of them silently, with no error and no diff
  on the consumers. The consumer list is one API call (`jobSchedules` grouped by
  schedule name, `list-entities-for-policy`, `describe-*` by group id). If the
  object has >1 consumer and you need per-consumer behaviour, CREATE a new object
  and RE-POINT only your consumer — never mutate the shared one. After
  re-pointing, assert exactly ONE binding per consumer: a re-point that adds the
  new link without deleting the old runs the consumer TWICE, and both runs
  succeed, so nothing surfaces it. NO EXCEPTIONS for a shared named object.
  # WHY: 2026-07-28 azure-automations — about to edit the `Daily` schedule's
  #   Full: incidents#2026-07-28-azure-automations-about-to-edit-the

GUARD pattern="the file's own docstring/comment describes this design, so I'll
  implement it" (adding a flag, field-consumer, or mode a doc block promises):
  GREP FOR THE FILE'S TESTS FIRST — an ENFORCED test outranks the file's own prose,
  and a docstring can describe a design that was ABANDONED. Tests do not always
  live in the obvious dir: `bin/preflight-skill.py`'s tests are
  `scripts/test_preflight_skill.py`, so globbing `bin/test_*` finds nothing and
  reads as "no tests exist". Search by MODULE NAME across the repo
  (`git grep -l "<module_stem>" -- '**/test_*.py'`), not by expected location.
  NO EXCEPTIONS when implementing a documented-but-absent capability.
  # WHY: 2026-07-29 — implemented preflight-skill.py's documented
  #   Full: incidents#2026-07-29-implemented-preflight-skill-py-s-documented

GUARD pattern="small change" or "one-liner" or "typo fix" or "trivial":
  REFUSE to skip the check. Size does NOT determine whether behavior has
  hidden rationale. RUN memory_search + git log anyway. NO EXCEPTIONS.

GUARD pattern="I'll add a <tag / helper / default / config key / policy / fix> for
  this" — about to INTRODUCE a mechanism, before having grepped for it:
  GREP FIRST, DESIGN SECOND. Two commands, both cheap:
    1. `grep -rn "<the thing>" --include="*.<ext>" .`   -> does a CONVENTION
       already exist? If the repo already solves this somewhere, MATCH that
       shape; do not invent a second one.
    2. `gh pr list --repo <org/repo> --state open`      -> is someone already
       fixing it? (the shared-work-surface GUARD below covers the contended-repo
       case; this is the same check applied to ANY new mechanism)
  A design proposed before the grep is a guess dressed as a recommendation, and
  it is wrong in the specific way that is hardest to see: plausibly, in a repo
  that already disagrees with it. NO EXCEPTIONS before introducing a mechanism.
  # WHY: 2026-07-26 mcp-infra, both halves failed in one session.
  #   Full: incidents#2026-07-26-mcp-infra-both-halves-failed-in

GUARD pattern="the old way was wrong anyway" or "current behavior is broken":
  VERIFY "broken": does git log show it was deliberately set? If yes,
  previous authors thought otherwise. Read their reason before changing.
  EXCEPTIONS: only when the current behavior crashes or produces wrong output.

GUARD pattern="bulk copy is simpler" or "just overwrite, files match":
  REFUSE. Read git diff source..target first. Bulk copy is only safe when
  target has zero divergent additions. NO EXCEPTIONS.

GUARD pattern="I'll verify the deployed state later" or "probably still not done":
  REFUSE deferred verification. Read the target file NOW before stating
  the recommendation. NO EXCEPTIONS.

GUARD pattern="I already checked, trust me" or "I know this area":
  VERIFY with actual grep/read before changing. Session memory is not
  machine-checkable. NO EXCEPTIONS when preparing to modify or delete.

GUARD pattern="the session-start banner flagged it, just build the fix" or "nothing merged covers it, so it's unclaimed":
  REFUSE building before `gh pr list --state open` when the repo is
  contended (another session active / dirty files at session start).
  Banners are a shared work queue with no claim mechanism; git log only
  proves nothing MERGED — an open twin PR is invisible to it. If a twin
  exists, repair it forward instead of duplicating. NO EXCEPTIONS in a
  contended repo.
  # WHY: 2026-06-11 — built+validated a complete duplicate of open PR
  #   Full: incidents#2026-06-11-built-validated-a-complete-duplicate-of

GUARD pattern="build the deliverable/artifact from the repo's main" (for a task an
  ACTIVE repo is working — recent pushes, concurrent sessions, or open PRs):
  REFUSE building from `main` before `gh pr list --state open` on that repo. An
  open PR may hold BOTH the authoritative artifact AND the solution to the exact
  problem you're about to re-derive from main's stale/inferior version. Prefer the
  open PR's artifact; if you must build, base it on that branch. Distinct trigger
  from the shared-banner GUARD above: building a DELIVERABLE from main, not a fix
  from a shared work surface. NO EXCEPTIONS when the task maps to a repo with open
  PRs on the same topic.
  # WHY: 2026-07-05 — built a Kaggle submission from the research repo's `main`
  #   Full: incidents#2026-07-05-built-a-kaggle-submission-from-the

GUARD pattern="git grep came back clean, nothing uses this script" or "I grepped
  the repo before deleting it" or "no consumers in this codebase":
  REFUSE the unreferenced conclusion for anything under `.github/scripts/`,
  `bin/`, `tools/`, or `scripts/`. `git grep` stops at the repo boundary and
  sibling repos invoke these by ABSOLUTE path, so a clean in-repo grep is
  evidence about the SEARCH, not the world (verify-before-assuming.md's
  `unavailable_claims_require_failed_check_not_assumption`). REQUIRED: sweep
  ~/.claude/{skills,bin,hooks} and the sibling checkouts (STEP_3b) before the
  delete, and land the consumer's PR in the same arc. NO EXCEPTIONS for a shared
  script directory.
  # WHY: 2026-07-26 — claude-knowledge-base #1239 deleted four
  #   Full: incidents#2026-07-26-claude-knowledge-base-1239-deleted-four

GUARD pattern="it's a new file, no check needed":
  EVALUATE: is it truly new, or replacing something that existed before?
  If replacing → treat as modification. If truly new → skip the memory_search.

GUARD pattern="I fixed the validator, the field move is safe" or "only one thing reads that field":
  REFUSE. When relocating content between fields (e.g. `description` → `when_to_use`),
  grep EVERY reader of the old field across scripts/ bin/ hooks/ .github/ AND tests/ — the miss
  is the second consumer, and field-readers fail at CI, not at edit time. Run the
  full audit suite locally before pushing. NO EXCEPTIONS.

GUARD pattern="add a NEW cloud-API call to a Lambda/service/task" (a `put_metric_data`,
  `put_object`, `publish`, `get_parameter` the code did not make before):
  GRANT IT ON THE RUNTIME ROLE IN THE SAME PR, and verify against the LIVE attached policy
  of that role — not the CI role, not a sibling role that already has it. The IAM guard
  below governs the CI/DEPLOY role; this is the RUNTIME variant and it fails differently:
  the deploy SUCCEEDS, so there is no failed apply to notice.
  WORSE, IT IS SILENT BY YOUR OWN DESIGN. Telemetry calls get wrapped in `try/except` so
  they cannot break the work — correct, and it means a missing grant produces a logged
  warning, a green deploy, and a metric that NEVER EXISTS. Any alarm on that metric then
  sits in INSUFFICIENT_DATA (or breaches on missing data) forever, indistinguishable from
  a quiet system. The defensive except and the silent failure are the SAME CODE; the only
  difference is whether anything counts the failures.
  REQUIRED: after the apply, confirm a real DATAPOINT exists (`get-metric-statistics`), not
  just that the policy statement is attached. A grant with no datapoint is unproven.
  NO EXCEPTIONS when the new call backs an alarm.
  # WHY: 2026-07-31 mcp-infra #762 → #763 — a metric emission shipped without its grant;
  #   Full: incidents#2026-07-31-mcp-infra-762-763-a-metric

GUARD pattern="the step calls update-function-code, so I'll grant UpdateFunctionCode" or "the permission is already in ci.tf":
  REFUSE the verb-scoped grant. Enumerate EVERY command's full API-call set
  (waiters + `--query` reads + verify steps each add calls the verb name hides),
  grant on the role the workflow ACTUALLY assumes (read `role-to-assume`), and
  confirm with `aws iam get-role-policy` against that role — not the .tf source.
  "In ci.tf" is an authoring claim; the attached-and-applied policy is the
  enforcement reality. NO EXCEPTIONS for CI/deploy IAM grants.
  # WHY: 2026-06-25 — under-scoped 3× in one deploy chain (wrong role, then two
  # missing waiter-polled permissions). Full: incidents file, 2026-06-25 entry.

GUARD pattern="lock it at the current version" or "pin to latest, that's the
  newest good one" or "the release notes look clean":
  REFUSE the pin until you read the selected version's PUBLISH TIMESTAMP and
  search the vendor's issue tracker for that exact version. Release notes are
  written at publish time and never amended when the release turns out broken;
  the registry keeps serving it as latest either way. A release younger than
  ~48h is UNPROVEN, not current. NO EXCEPTIONS when the pin gates a deploy, an
  apply, or CI for everyone.
  # WHY: 2026-07-29 — locked `aws v6.57.0` ~5h after publish; upstream #49181
  #   Full: incidents#2026-07-29-locked-aws-v6-57-0-5h

GUARD pattern="the apply failed on a missing permission, grant it and re-run" (on
  the 1st failed apply, before the whole preflight has been run):
  EVALUATE all four preflight items — permissions, plan durability, provider
  health, merge trigger — BEFORE shipping the grant. Fixing only the error in
  front of you converts one preflight into N sequential failed applies, each
  costing a plan + a human approval. This is NOT the same as scope-discipline's
  "STOP at the 2nd CI-apply failure": that one says stop grinding and search
  memory; this one says enumerate the other three classes on the FIRST failure,
  because they are independent and each hides behind the one before it.
  # WHY: 2026-07-29 — 4 runs, ~9h undeployed main, one blocker per run, all four
  # knowable up front. Full: the preflight procedure's WHY above.

# ─── FAILURE MODES (incidents → rules/incidents/check-before-change.md) ───

FAILURE re_added_deliberately_removed_feature:
  RECOVERY: revert, document the prior decision somewhere greppable.

FAILURE added_context_fork_to_agent_dispatching_skill:
  RECOVERY: remove context:fork. Verify skill body does not reference Agent.

FAILURE added_model_sonnet_to_complex_critical_path_skill:
  RECOVERY: remove model: override.

FAILURE deleted_shared_script_whose_consumer_lives_in_another_repo:
  SYMPTOM: a clean same-repo `git grep` licensed the deletion; the callers were
  in a sibling checkout, invoking by absolute path. The breakage surfaces only
  when someone runs the consumer, and looks like the CONSUMER is broken.
  # INCIDENT 2026-07-26 KB #1239 → config #1710: 4 scripts deleted, 5 skills broken.
  RECOVERY: restore or repoint every cross-repo caller in its own PR, and land
  both before calling the deletion done. Distinguish "citation is wrong" from
  "repo not cloned here" — the second is a provisioning gap, not a broken
  reference, and reporting it as the latter sends people chasing phantoms.

FAILURE deleted_file_without_grepping_refs:
  RECOVERY: restore via git revert OR remove the dangling references.

FAILURE deleted_unexplained_artifact_before_capturing_evidence:
  RECOVERY: reconstruct what you can (server logs, shell history, git
  reflog), add forward-looking attribution logging, then fix the CLASS
  of writer — the specific caller is unrecoverable.

FAILURE bulk_copied_over_divergent_fork:
  RECOVERY: git reset to pre-copy commit, redo surgically via str.replace.

FAILURE recommended_already_shipped_work:
  RECOVERY: acknowledge the existing work and move to next candidate.

FAILURE built_duplicate_of_open_pr_from_shared_banner:
  RECOVERY: snapshot the duplicate to /tmp, discard it, take over the open
  PR's branch (`git checkout -B <branch> origin/<branch>`), fix ITS
  blockers forward, re-arm auto-merge, verify state == MERGED.

FAILURE wrote_test_against_assumed_struct_shape:
  RECOVERY: read the type definition, copy field names into the literal, rebuild.

FAILURE cited_hook_behavior_in_skill_prose_without_checking_frontmatter:
  RECOVERY: read skill frontmatter + cited hook before stating the claim.

FAILURE shipped_api_shape_change_without_consumer_check:
  RECOVERY: grep all callers, patch them in the same PR.

FAILURE relocated_field_content_without_grepping_all_consumers:
  RECOVERY: grep every reader of the old field, fix each to read the new or
  combined field, run the full audit suite locally before re-pushing.

FAILURE granted_ci_iam_too_narrow_or_on_wrong_role:
  RECOVERY: enumerate every command's API calls (incl. waiters/post-reads),
  grant the missing permission(s) on the role the workflow assumes, verify with
  `aws iam get-role-policy`, re-apply, re-run the deploy. One fix-forward per
  missed permission — enumerate up front to collapse the chain to one PR.

# ─── WHAT DOES NOT REQUIRE THIS CHECK ───
- Adding new files, skills, or features that don't modify existing
- Bug fixes where current behavior is clearly broken (crashes, wrong output)
- Documentation updates that reflect current state

GUARD pattern="key a control/alarm/check on a data surface because it has the RIGHT
  PROPERTY" (ingest-time partitioned, monotonic, always-written, never-null):
  VERIFY THE SURFACE IS POPULATED IN THE HEALTHY STATE — not merely that it has the
  property. These are two different questions and only the second is interesting, which
  is exactly why the first goes unasked. A prefix/field can be perfectly
  ingest-time-partitioned AND written only by an ERROR path, so it is empty precisely
  when the system is healthy — the control then reports BROKEN forever, loudest when
  nothing is wrong.
  REQUIRED before shipping: grep every WRITE SITE of the surface and name what produces
  it. A surface whose only writers are tombstone/except/fallback paths is disqualified.
  Then COUNT it live over a healthy window — a zero IS the answer. Prefer a signal the
  PLATFORM emits (AWS/Lambda `Invocations`, queue depth) over one your own code writes:
  it cannot be empty-by-construction, needs no IAM, and a backfill cannot reorder it.
  NO EXCEPTIONS for a control that will page.
  # WHY: 2026-07-30 mcp-infra #756 -> #757 -> #758. A content-lane freshness control was
  #   Full: incidents#2026-07-30-mcp-infra-756-757-758-a

# Extend existing GUARD "I'll add a <helper/policy/fix> for this... GREP FIRST, DESIGN SECOND":
# WHY (additional instance): 2026-07-31 — wrote a regex assuming KB entries are dated
#   Full: incidents#additional-instance-2026-07-31-wrote-a-regex-assuming

# Extend the GUARD above ("add a NEW cloud-API call ... confirm a real DATAPOINT exists"):
# THE NETWORK VARIANT — and it defeats that guard's own remedy. That guard says to verify
# the IAM grant, so when IAM is CORRECT the check returns "all fine" and the alarm still
# breaches forever. An emitter also needs a ROUTE: from a private subnet, reaching
# CloudWatch requires an interface VPC endpoint AND an egress rule that reaches it.
# MEASURED 2026-08-03 (claude-gateway readyz probe): the Lambda HELD
# `cloudwatch:PutMetricData` and the `monitoring` endpoint existed, but its SG allowed 443
# only to the ALB's security group — so every invocation hung the full 15s to timeout with
# ZERO log output, and `readyz-failure` sat breaching on a HEALTHY system. One egress rule
# to the VPC CIDR took it to 256ms and datapoints appeared within a minute.
# REQUIRED when a datapoint is missing: check IAM *and* the route before touching the
# emitter. THE TELL IS A TIMEOUT WITH NO LOGS — an IAM denial logs an error, a blackholed
# route logs nothing, so "no output at all" points at the network, not the permission.

## Preserving a COMMENT is not preserving its INVARIANT (2026-08-26)

Recorded here rather than in the ambient rule: `rules/check-before-change.md` sits at 9,811
of the 10,000-byte cap `scripts/test_context_policy_contracts.py` asserts for the ten
`formerly_dominant` rules — 189 bytes of headroom. The ambient T1 slot is full.

When an existing comment states a PROPERTY of the value you are relocating — "on the same
filesystem", "same partition", "shared", "co-located", "byte-identical with X" — that
sentence is a CONSTRAINT SPEC, not prose. Copying it forward while moving the value carries
the words and drops the guarantee, and it reads as diligence in review.

Measured 2026-08-26. A release launcher's comment read: the JIT credential file "is a
sibling of the already validated, caller-owned credential so both stay on the same
**Docker-shared filesystem**". A config-only mode needed its own scratch directory (the
original template was relative to a credential path that mode does not have), so it was
moved to `${TMPDIR:-/tmp}` — and the replacement comment QUOTED that sentence verbatim. On
macOS `$TMPDIR` is `/var/folders/<...>/T/`, which Docker Desktop does not bind-share, so the
first live dispatch died at the pre-dispatch probe:

```
docker: Error response from daemon: invalid mount config for type "bind":
bind source path does not exist: /var/folders/sh/.../T//private-ai-runner.jBc5Qbo2/jit-config
```

The path DID exist on the host — the daemon reports a shared-filesystem miss as a MISSING
PATH, which sends you hunting a creation bug. Diagnosed with both controls against the exact
pinned runner image, same file created the same way: `$HOME` → mount rc=0; `$TMPDIR` → rc=125
reproducing the identical daemon error with the host confirming the file present first.

**Two required actions, not one.** Convert the sentence into an ASSERTION in the same change;
and mutate the VALUE the guard produces, not only the guard's control flow. A 17-mutation
battery shipped this defect because every launcher mutation targeted whether the guard
EXISTED, never which directory it named. Fix verified 4/4 by mutations that reintroduce the
TMPDIR path, use world-writable `/tmp`, make the template relative to cwd, and drop the
other mode's template.

## A pin advance is not an isolated change (2026-08-25)

Advancing a pinned sibling ref swaps the content of EVERY pinned file at once, so a verifier
that currently PASSES can start failing.

Measured: a 280-commit-stale pin was advanced to fix a red cross-repo contract gate. The
advance fixed that test and simultaneously broke a SECOND verifier which had been passing on
the stale pin — found only because both were run under the OLD and the NEW ref as a control
rather than assuming a pin bump was isolated. It was not an upstream regression: a commit in
the pinned repo had made `event.timestamp` authoritative because "timeUnixNano is not
retained by the CloudWatch Logs exporter", and the consuming verifier mutated
`timeUnixNano` — now a no-op, so that case had silently stopped exercising anything
(`tdd-mutation-testing` item 21: the knob the test set was no longer the knob the code
reads). REQUIRED: run every consumer of the pinned content under both refs before shipping.
