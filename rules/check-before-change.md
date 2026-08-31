@rule check_before_change
@version 2026-08-06
@scope every modification to existing behavior or defaults, deletion, cross-repo copy, structured-contract change, recommendation, shared-work-surface fix, dependency pin, and deploy-affecting change
@reference docs/rule-reference/check-before-change.md

# CHECK BEFORE CHANGE — DECISION CONTRACT

Use this contract before editing behavior, removing or relocating anything, or
recommending a change. Full specialized procedures and incident evidence remain
available on demand at `docs/rule-reference/check-before-change.md`.

## Triggers

- Removing/re-adding code, features, files, hooks, config, or policy; changing a
  default, threshold, model, permission, schema, API response, field location, or
  tool/server name.
- Copying between repos/forks; editing a shared named object; introducing a new
  mechanism, cloud call, dependency pin, alarm, or deploy path.
- Acting on a shared banner/CI digest in a contended repo, or recommending work
  that a parallel session/PR/deployment may already have completed.

## Core invariants

INVARIANT never_modify_existing_behavior_without_checking_why
INVARIANT never_delete_files_without_grepping_for_references
INVARIANT never_bulk_copy_over_divergent_target
INVARIANT verify_deployed_state_before_recommending

## Required checks

1. **Read and recover rationale.** Read the current target and its tests. Run
   `memory_search(feature_name)` and `git log --oneline --all -- <file>` for any
   behavioral/default/removal change, even a one-liner. If prior rationale
   contradicts the change, stop and present the conflict. If none is found, say
   "no prior decision found" rather than inventing one.
2. **Verify current state.** Inspect the target pattern, recent history, source,
   configured/deployed/live state, and relevant open plus recently merged PRs.
   A shared banner is an unclaimed queue: check for a twin before building and
   again before opening a PR; repair or refine the existing work instead of
   duplicating it. Before reporting a repository-content finding, fetch the
   default branch and compare the checkout to its remote; reading a file proves
   only what the local checkout holds, not current repository state.
3. **Delete safely.** If an artifact is unexplained, capture `stat` and a recoverable
   copy before deletion. Search the filename/symbol in repo code, settings files,
   workflows, imports, manifests, docs, tests, and plausible sibling repos/user
   config. A clean `git grep` ends at the repo boundary and is not proof that a
   shared script is unused. Update every caller in the same change/arc and name any
   cross-repo delivery still required.
3b. **Never infer "stale/unused" from a status field, a name, or a volume number —
   identify the live PRODUCER and CONSUMER first.** A resource's own metadata is
   not a statement about whether anything depends on it. Before deleting, ask two
   questions and answer both with a measurement: *what writes to this* (query the
   data for its producer/source field, or the emitting identity's last-used
   timestamp) and *what reads from it* (enumerate linked objects via the platform's
   own relationship query, not by name pattern). A `state: disabled`/`inactive`
   field, an auto-generated `managed-*`/`Default*` name, and a zero or small
   volume figure are each individually consistent with a fully live dependency.
   Platforms routinely auto-create backing resources by design, and per-datatype
   status metadata frequently disagrees with actual flow.
4. **Patch divergent targets surgically.** Read both sides and inspect their diff.
   Preserve target-only additions; never bulk overwrite a fork or deployed copy.
   After merge/rebase/stash-pop or formatter activity, re-read on-disk content and
   use idempotent verify-then-write edits.
5. **Map every consumer of a contract.** Before changing an API shape, config/front-
   matter field, tool prefix, server name, or shared module, grep all readers across
   scripts, bin, hooks, settings/examples, workflows, rules, skills, manifests, tests,
   frontends, and sibling repos. Patch all affected consumers together or retain a
   compatible transition. For every retired matcher, identify the failure it used to
   prevent.
6. **Enumerate shared-object blast radius.** List every consumer of a referenced
   schedule, role/policy, security group, launch template, ConfigMap, or equivalent.
   If consumers need different behavior, create a separate object and repoint only the
   intended one; assert exactly one binding afterward.
7. **Cloud and deploy preflight.** Enumerate every API call made by commands, waiters,
   post-reads, and verification. Verify the actual runtime/CI role and live attached
   policy, resource scope, route/endpoint/egress, and a real resulting datapoint. Before
   first apply, check all seven independent classes: permissions, plan durability,
   provider health, merge trigger, artifact existence/contract consumption, a clean
   current plan, and applied-but-unmerged live state.
8. **Pins and releases.** Read the version actually selected, its publication time,
   and vendor issues for that exact version. Treat a release younger than about 48
   hours as unproven; exclude a known-bad exact version with the issue and removal
   condition recorded.
8b. **An IAM/policy CONDITION whose key the ACTION does not support is a DENY, not a
   narrower ALLOW.** Before adding any `Condition` to a statement, confirm every action
   in that statement supports every condition key used. A key the action does not
   publish never matches, so the statement can never authorize anything — and `plan`,
   `apply`, and the whole unit suite stay green because only a real invoke fails.
   PROMOTED to ambient on the THIRD occurrence. `agent-memory/topics/aws-infra-s3.md`
   already carries this as "An unsatisfiable CONDITION is a DENY — and knowing the
   pattern is not checking against it (2026-08-02)", which itself records re-stating
   the mechanism in a comment and then reproducing it one statement over. On
   2026-08-12 it recurred again: `StringLike s3:prefix` on a statement granting
   `s3:GetBucketLocation` (an action with no `s3:prefix` key) denied Athena's
   output-location preflight, so the FIRST scheduled run of a new lane died with
   `Unable to verify/create output bucket`. Known offenders seen here: `s3:prefix` on
   anything but `s3:ListBucket`; `cloudwatch:namespace` on a metric READ
   (`GetMetricStatistics`); `ArnEquals ecs:cluster` on cluster-independent
   `ecs:DescribeTaskDefinition`. Split the conditioned and unconditioned actions into
   separate statements, and prefer copying a sibling statement PROVEN in production over
   deriving a "tighter" one — the 2026-08-12 instance was a re-derivation of a working
   sibling that had no condition.

9. **Controls and signals.** Before keying a control/alarm on a surface, grep every
   writer, prove it is populated in healthy operation, measure it live, and prefer a
   platform signal. Missing telemetry requires both IAM and network-route checks.
10. **New mechanisms.** Grep for the repo's existing convention and open work before
    designing. For unfamiliar types, read the definition/constructor and copy the
    actual field contract. New files that replace old behavior are modifications, not
    exemptions.

## Forbidden shortcuts

- "Small/trivial/typo" as a reason to skip memory, history, tests, or current-state
  checks.
- Concluding an object is stale/unused/orphaned from its own status field, its
  auto-generated name, or a low volume number. GUARD pattern="it reports disabled"
  or "it's an auto-created/Default* resource" or "it has almost no data" or
  "it's obviously leftover": REFUSE the deletion. Query the producer (source
  field, last-used timestamp) AND enumerate consumers via the platform's
  relationship API. Status metadata is per-datatype config, not a flow
  measurement; auto-created backing resources are usually by design. NO
  EXCEPTIONS for a delete whose only evidence is a field value or a name.
- Deleting after only a same-repo grep, or destroying an unexplained artifact before
  preserving attribution evidence.
- Bulk copying over a divergent target, or scripted edits against pre-merge/
  pre-formatter anchors.
- Running a blanket text substitution (date/window/name sweeps) without excluding
  IDENTIFIER AND PATH contexts. A swept literal inside `os.path.join`, a dir name,
  or a JS data key is a consumer, not prose: one sweep pair broke a builder's
  DATA_DIR into a nonexistent dir and another blanked whole report sections via a
  renamed JS key (2026-08-24 ×2). Anchor sweeps per-site or filter path-bearing
  lines, then re-run the render/consumer gate.
- Recommending already-shipped work, duplicating an open/recently merged change, or
  probing for twins using only identifiers from your proposed implementation.
- Changing a server/API/field contract after finding only the first consumer.
- Mutating a shared object without enumerating consumers; adding a cloud call without
  runtime permission, network reachability, and observed output.
- Treating source/IaC as proof of deployed enforcement, or fixing one failed-apply
  symptom without running the whole preflight.
- Locking to "latest" without selected-version health evidence.
- Trusting truncated values, narrow-pattern counts, or a control surface whose healthy
  producer was never identified.

Exceptions are narrow: a truly new, non-replacement file; a fix for demonstrated crash
or wrong output; or documentation that only reflects verified current state. Read the
target first even then. Load the archived reference for specialized procedures rather
than restoring incident detail to the ambient rule.
