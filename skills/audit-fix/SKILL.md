---
name: audit-fix
description: "Dispatch one fix-agent per verified audit finding, with pre/post oracle verification; commit only verified fixes."
when_to_use: Take a verified worklist of STILL-FIRES audit findings and dispatch fix-agents, one per finding, with pre/post oracle verification (Layer D fix_loop). Each agent makes the minimal change to flip the reproducer from fires=True to fires=False. Only commits VERIFIED fixes. Use after /audit-skill produces a worklist (Phase 3) when the goal is to actually close the bugs instead of just surfacing them. Trigger phrases - "audit fix", "fix audit findings", "fix the audit worklist", "dispatch audit fixes". Do NOT use for unverified worklists (run /audit-skill Phase 3 act-on first), for STILL-FIRES with type=manual reproducers (those require human review, not automated fixes), or as a substitute for /pr-fix on CI failures.
argument-hint: "[worklist.yaml]  (path to a STILL-FIRES worklist produced by /audit-skill Phase 3, e.g., ~/.claude/audit-runs/2026-05-27-worklist.yaml)"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Bash Read Edit Write Grep Glob Agent AskUserQuestion
---

## audit-fix

Closes the discovery → fix loop for audit-skill. Each STILL-FIRES finding in
the input worklist gets a dedicated fix-agent that:

1. Reads the finding's reproducer and the cited skill source.
2. Makes the minimal change to flip the reproducer from fires=True to fires=False.
3. The orchestrator verifies via `oracle verify-fix` (Layer D) before committing.

Built on the oracle's Layer D fix_loop: a fix is only accepted if
the reproducer fired before AND no longer fires after. Anything else
(STALE-PRE / FIX-INEFFECTIVE) is rejected and surfaced for human review.

## When to use

- After `/audit-skill` Phase 3 produces a worklist with STILL-FIRES findings
- After PR merges that may have re-introduced bugs covered by the tracker
- When the MANUAL backlog has been re-classified down to the auto-checkable subset

## When NOT to use

- Worklist hasn't been through `act-on` (no trace records → validate_for_dispatch rejects)
- Findings still have `type: manual` reproducers (no automated verification possible)
- For CI failures or stuck PRs (use `/pr-fix`)
- For commit-and-ship (use `/ship` after this skill produces edits)

## Procedure

### Step -1: No worklist argument given

`/audit-fix` invoked bare has no worklist to validate — produce one
instead of improvising (2026-08-22: a bare invocation cost a tracker
hunt and two filter iterations):

1. Enumerate candidate trackers: `ls -t AUDIT-TRACKERS/*.findings.yaml`.
2. Run `act-on --auto-only` on the newest (or the one the user named)
   to measure the dispatchable count per tracker.
3. Present the counts in the Step-1 scope confirmation — the user picks
   the batch, not the orchestrator.

### Step 0: Validate the worklist

```bash
python3 ~/.claude/skills/audit-fix/scripts/validate_worklist.py <worklist.yaml>
```

The script applies the four validate gates and refuses worklists where:
- **Gate 1 (malformed)** — the worklist violates the act-on format
  (unparseable, missing required fields, or no findings at all), or a
  finding's reproducer is `type: manual` (no auto-check possible)
- **Gate 2 (stale)** — the trace record is older than 30 minutes (TTL
  expired; tune via `--max-age-seconds`)
- **Gate 3 (no-trace)** — no trace record exists (act-on wasn't run)
- **Gate 4 (error-verdict)** — the latest Layer-A verdict is ERROR (the
  reproducer itself is broken); repair the reproducer before dispatch

Exit 0 prints a JSON dispatch summary (per-finding trace age + verdict);
exit 2 names the tripped gate and reason. If validation fails, the
worklist isn't dispatchable. Run `act-on` again to refresh.

Produce worklists with `--auto-only` so they pass the gates as
written — a bare `act-on --out` includes MANUAL findings (Gate 1
rejects) and ERROR findings (Gate 4 rejects):

```bash
~/.claude/bin/audit-skill-oracle.py act-on <findings.yaml> \
    --auto-only --out /tmp/wl.yaml
```

For the oracle-side superset of these gates (adds the specificity
and verdict checks on top), run:

```bash
~/.claude/bin/audit-skill-oracle.py validate <worklist.yaml>
```

### Step 1: Confirm scope with the user

Before dispatching fix-agents, surface the dispatch plan via AskUserQuestion
(skip when the user already approved this exact batch in conversation):

- Count of findings to fix and the class/skill scope
- Rough cost (one proposal agent per skill, roughly 50 cents each —
  written out to avoid the harness's dollar-numeral argument substitution)
- Confirmation that the user wants automated edits to multiple skills

Reason: this skill modifies multiple files across the repo. The user
should explicitly authorize the scope.

Scope the worklist natively — `act-on` accepts repeatable filters:

```bash
~/.claude/bin/audit-skill-oracle.py act-on <findings.yaml> \
    --code A1 --code B --out /tmp/wl-batch.yaml
```

### Step 2: Dispatch PROPOSAL agents (read-only, one per skill)

> **Pattern change (2026-06-12, campaign 11 — 125 verified fixes, zero
> rogue writes).** Fix-agents do NOT edit the repo. They are read-only
> proposers; the orchestrator applies their edits centrally and the
> oracle verifies. This sidesteps the protected-repo hook blocks on
> subagent edits, the serialize-worktree constraint, and the silent-
> partial-apply class — and because agents don't write, they can run at
> engine-pool parallelism (one per skill) instead of waves of 2.

> **"Read-only" is NOT enforced by prose (2026-08-22 — 3 of 49 agents
> wrote the worktree directly despite an explicit prohibition, one
> before it even returned).** Two mitigations, both required:
> (a) dispatch with a read-only agent type when one is available (no
> Write/Edit in its tool set) rather than general-purpose + an
> instruction; (b) regardless of agent type, Step 3 snapshots and
> resets the worktree before central apply, so a rogue write can never
> merge unreviewed. The tell during collection: a returned `old_string`
> that counts **0** in the worktree usually means the agent already
> applied its own edit (the anchor is the pre-edit text and will match
> again after the reset).

**Concurrency**: the host caps concurrent subagents (8 on the current
host — the exact error is "Concurrent subagent limit reached"); excess
dispatches FAIL, they don't queue. Keep a dispatch ledger (packet name →
launched/returned/saved) and reconcile it against the packet count
before Step 3 — a bounced launch is silent finding loss.

Group findings by skill (one agent per skill, all of that skill's
findings in its packet). Each agent's prompt must include:

- **Read first**: `AUDIT-TRACKERS/campaign-context.md` — the campaign
  brief every fix-agent MUST load (external sibling-repo paths are NOT
  phantom; skipping it reproduces the May 2026 incident where 10
  parallel agents independently deleted citations to a sibling repo).
- The findings packet (description + location + reproducer each).
- The output contract: exact `{file, edits: [{old_string, new_string}]}`
  pairs — old_string verbatim-unique in the file; a single edit with
  `old_string: ""` means CREATE the file (full content in new_string);
  **deletions are not expressible** — skip them as cross-cutting (see
  Step 4).
- **Reproducer hygiene**: when the finding's reproducer probes host/
  shell state rather than the artifact (doc-decoupled), or references
  `~/.claude` (deployed-path), the agent must ALSO return
  `updated_reproducer` — a doc-state predicate that fires iff the bug
  is still present in the tree. Campaign 11 replaced 43 such predicates.
  This applies to SKIPPED findings too: a skip reason of "already fixed
  in-tree, but the tracker's reproducer fires forever" must carry the
  corrected predicate in the skipped entry's own `updated_reproducer`
  field (`skipped: [{idx, reason, updated_reproducer?}]`) — a predicate
  described only in prose cannot be installed (apply_fixes warns
  `SKIP_NOTE_REPRODUCER` when this happens).
- Constraints: edits only inside `skills/<skill>/`; verify on $TMPDIR
  copies, never in the worktree; no git/gh/MCP mutations; do NOT modify
  the audit-skill itself; cross-cutting fixes (shared repo-root
  scripts, other skills' files) are SKIPPED with the prescribed fix in
  the skip reason — the orchestrator applies those.
- **Three structured-output gotchas the orchestrator must defend against
  (gotchas 1-2 hit 2026-06-14, gotcha 3 hit 2026-06-16):**
  1. The proposing agent's returned `skill` field is UNRELIABLE — a
     fraction of agents echo the campaign/parent name (e.g. `audit-fix`)
     instead of their own. `apply_fixes.py`'s scope guard then rejects
     the (correctly-targeted) edit as "outside skill dir". Before
     applying, derive the true skill from each fix's `file` path
     (`skills/<skill>/…`), not from the agent's `skill` field.
  2. `updated_reproducer` must be the NESTED object
     `{type, command, expected_exit?}` that `apply_fixes.py` reads — flat
     sibling fields (`updated_reproducer_type`/`_command`) are silently
     ignored (apply reports "0 updated reproducers" and the doc-decoupled
     findings then false-fire at batch_verdicts).
  3. The `updated_reproducer`'s fire-DIRECTION is frequently inverted —
     a fraction of agents return `type: grep_absent` (fires on NO match)
     where they mean `grep` (fires on match), or set the wrong
     `expected_exit`, so the predicate FIRES after a correct fix instead
     of going STALE. Never trust the agent's reproducer type/exit; verify
     each one resolves to "fires == bug-present" against the post-fix tree
     before reverify (2026-06-16: 2 of 16 inverted — idx4 investigate,
     idx15 work). Fire-direction rules + the other reproducer couplings
     are in `skills/audit-skill/references/new-check-checklist.md` §10.

### Step 3: Apply centrally + verify via the oracle

Before collecting results into `results.json`, HTML-UNESCAPE any agent
output that arrived through a notification transport — `&gt;`/`&amp;`/
`&lt;` in an `old_string` will never match the file (2026-08-22: every
escaped result needed `html.unescape` before apply).

```bash
# 0. The worktree must be CLEAN before central apply — snapshot then
#    reset any rogue agent writes (see Step 2 note):
git -C <worktree> diff > /tmp/rogue-writes.diff
git -C <worktree> checkout -- . && git -C <worktree> status --short  # must be empty
# 1-3. apply → patch → mechanical fire-direction gate:
python3 ~/.claude/skills/audit-fix/scripts/apply_fixes.py \
    <results.json> <worktree> --state-out /tmp/apply-state.json
python3 ~/.claude/skills/audit-fix/scripts/patch_worklist.py \
    <worklist.yaml> /tmp/apply-state.json --out /tmp/wl-patched.yaml
git -C <worktree> worktree add /tmp/pre-tree <base-sha>   # pre-fix reference
python3 ~/.claude/skills/audit-fix/scripts/direction_check.py \
    /tmp/wl-patched.yaml /tmp/apply-state.json /tmp/pre-tree <worktree>
# 4-5. oracle reverify + batch gate:
WT/bin/audit-skill-oracle.py reverify /tmp/wl-patched.yaml --json \
    > /tmp/batch-reverify.json      # run the WORKTREE's oracle copy — see note
python3 ~/.claude/skills/audit-fix/scripts/batch_verdicts.py \
    /tmp/batch-reverify.json /tmp/wl-patched.yaml /tmp/apply-state.json
git -C <worktree> worktree remove /tmp/pre-tree
```

`direction_check.py` is the MECHANICAL form of gotcha 3 above — it runs
every expected-fixed finding's (patched) reproducer against both trees
and requires fire(pre) → quiet(post), classifying failures as INVERTED /
STALE-PRE / STILL-FIRES-POST / ERROR. Do not skip it and rely on the
prose instruction: the inversion rate is stable (~12% of agent-supplied
predicates in BOTH campaigns that measured it: 2/16 on 2026-06-16, 2/18
on 2026-08-22, the second time because the orchestrator skipped this
exact check).

> **Run the worktree's oracle copy for reverify, not `~/.claude/bin`'s.**
> `audit-skill-oracle.py` resolves reproducer paths against
> `REPO = Path(__file__).resolve().parent.parent` — its OWN checkout — and
> ignores `cwd`. Invoking `~/.claude/bin/audit-skill-oracle.py` scores the
> reproducers against the live `~/.claude` tree, so every fix you applied to
> the WORKTREE reads as STILL-FIRES (2026-06-14: 243 false still-fires this
> exact way). Run `<worktree>/bin/audit-skill-oracle.py reverify …` so `REPO`
> resolves to the worktree the edits live in.

`apply_fixes.py` enforces the exact+unique contract and the skill-dir
scope guard, and warns when an agent's NOTE describes a replacement
reproducer it didn't put in the structured field. `batch_verdicts.py`
is the gate: every applied finding must adjudicate STALE, every
unfixed finding must still fire — zero unexpected outcomes before
commit. For per-finding ref-based verification (e.g. orchestrator-
applied fixes), `verify-fix` still works:

```bash
~/.claude/bin/audit-skill-oracle.py verify-fix <worklist.yaml> \
    --finding-id <id> --pre-ref <pre-sha> --post-ref <post-sha>
```

It checks out both refs in throwaway worktrees: VERIFIED iff the
reproducer fired at pre-ref and no longer fires at post-ref. Reject
FIX-INEFFECTIVE / STALE-PRE findings — those need human review. An ERROR
outcome (pre/post run failure) surfaces in batch_verdicts output and requires
human investigation before commit.

**Cross-finding coupling** — batch_verdicts reporting "unfixed but
STALE" for a finding you didn't touch is not always an alarm: one fix
can legitimately flip ANOTHER finding whose predicate probes the same
artifact/condition (2026-08-22: adding a missing ledger section for one
finding made a sibling finding's grep go quiet). Verify the two share a
root cause, then pass BOTH via `--also-fixed` with the evidence in the
batch notes — do not "fix" the reproducer or re-dispatch.

### Step 4: Orchestrator-only actions

Some proposals are deliberately NOT agent-applied:

- **Cross-cutting skips** (shared repo-root scripts, another skill's
  files): apply the agent's prescribed fix yourself, after reading the
  target.
- **Deletions**: run the FULL check-before-change reference grep first —
  `git grep <filename>` PLUS `.github/workflows/*.yml` PLUS
  settings.json. Campaign 11: an agent's "referenced by nothing" claim
  grep'd only `*.md/*.yaml/*.py` and missed a `.yml` CI workflow that
  deliberately executes the file — deletion would have broken CI. If
  the reference grep refutes the finding, close it FALSE_POSITIVE with
  the evidence instead.

### Step 5: Commit + update the tracker

Stage explicitly, commit with the batch summary, ship via `/ship`
conventions (one PR per batch).

REQUIRED — the tracker update is part of the batch, not an optional
follow-up (2026-06-14's fix wave skipped it and 38 of this campaign's
81 "STILL-FIRES" findings were already-fixed ghosts). Close EVERY
dispatched finding, not just the fixed ones:

- fixed + oracle-verified → `FIXED` (batch note with the verification)
- verified already fixed in-tree → `STALE` (name the prior commit)
- premise refuted by source inspection → `FALSE_POSITIVE` (evidence)
- needs human/architect action or live spend → `DEFER` (what unblocks it)

`set-triage-status` applies surgically — only the matched blocks' triage
lines change:

```bash
~/.claude/bin/audit-skill-oracle.py set-triage-status <findings.yaml> \
    --skill <skill> --code <code> --status FIXED --note "<batch note>"
```

When skill+code over-matches (several findings share a code), script the
closure through `oracle.tracker.update_triage_surgical(path,
match_indices, status, note)` with indices matched on (skill, code,
description) — NEVER a full load→re-emit of the tracker (that path once
destroyed all 451 `location:` fields; the function's docstring records
the incident). Corrected reproducers from `updated_reps`/
`skip_updated_reps` are installed by patch_worklist into the WORKLIST;
for the TRACKER, record them in the triage note (a closed finding's
predicate is dormant — full re-emission risk outweighs durability).

Run `act-on` again as a HARD GATE, not a suggestion: the batch's
findings must appear under TRIAGE-CLOSED and the dispatchable count must
drop by the batch size. A count that didn't drop means closures missed.

### Step 6: Report

Print a summary table:

```
audit-fix summary (worklist=<path>)
  Dispatched:         N
  VERIFIED:           V (commits ready)
  FIX-INEFFECTIVE:    F (agent diff didn't flip reproducer; manual review)
  STALE-PRE:          S (reproducer didn't fire pre-edit; STALE)
  ERROR:              E (pre/post reproducer run failed; manual investigation)
  Cross-cutting:      X (agent reported multi-skill scope; needs replan)
```

## Examples

**Example 1: Fix one class from the current tracker**

```
~/.claude/bin/audit-skill-oracle.py act-on AUDIT-TRACKERS/<tracker>.findings.yaml \
    --code B --out /tmp/wl.yaml
/audit-fix /tmp/wl.yaml
```

Groups the class by skill, dispatches one read-only proposal agent per
skill at engine-pool parallelism, applies centrally, gates on
batch_verdicts (zero unexpected outcomes), ships one PR. Campaign-11
calibration: A1 batch 82 findings/48 agents → 81 verified + 1 cross-
cutting skip; B batch 45/28 → 44 verified + 1 FALSE_POSITIVE.

**Example 2: Fix a single skill's findings**

```
~/.claude/bin/audit-skill-oracle.py act-on AUDIT-TRACKERS/<tracker>.findings.yaml \
    --skill gather-repos --out /tmp/gr.yaml
/audit-fix /tmp/gr.yaml
```

## Success Criteria

- All worklist findings dispatched (no silent skips)
- Every VERIFIED fix has both pre and post reproducer evidence
- Tracker updated with triage_status=FIXED for each VERIFIED fix
- No commits for FIX-INEFFECTIVE / STALE-PRE findings
- Final summary table shows exact counts

## Failure modes

- **Agent went rogue**: per subagent-verification.md, verify diff before
  commit. If agent modified files outside the targeted skill, revert and
  re-dispatch with tighter prompt scope.

- **FIX-INEFFECTIVE on a "simple" finding**: the agent's understanding of
  the bug didn't match the reproducer's check. Likely the description
  was ambiguous; surface for human review.

- **Repository state changed mid-dispatch**: if PRs merge during the run,
  the post-fix verification may report STALE-PRE (the upstream fix
  beat us). Treat as a successful close and move on.
