---

name: distill
description: "Extract a session's errors, failed approaches, and workarounds into governed persistence targets."
when_to_use: 'Use when a session had errors, failed approaches, debugging pain, discovered workarounds, wrong guidance given to user, or existing rules that failed to prevent mistakes. Trigger phrases: "distill", "hard lessons", "what went wrong", "capture errors", "lessons learned", "what broke", "why did you get it wrong". Do NOT use for strategic decisions or architectural insights (use /capture), task state resumption (skill not yet implemented), or routine successful work.'
argument-hint: "[omit for auto-distill from conversation context]"
effort: high
allowed-tools: Read Write Edit Bash Grep Glob mcp__memory-search__memory_search mcp__memory-search__memory_search_batch AskUserQuestion
metadata:
  author: example-security-engineering
  version: "1.3"
compatibility:
  # Requires memory-search MCP for pattern dedup against prior distilled lessons.
  requires:
    - mcp: memory-search

---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# Distill - Hard Lessons from Session Errors

Extract errors, fixes, and wasted-time patterns from the current session and
route them to the appropriate persistence tier so future sessions don't
repeat the same mistakes.

**How this differs from other learning systems:**
- **Auto-learn** (Stop hook): Post-session, background, writes to agent memory only (tier 4)
- **`/capture`**: Strategic decisions and insights to knowledge base wiki pages
- **`/distill`**: Errors, fixes, pain points, accuracy failures, and rule gaps routed to rules, runtime project memory, topic files, staged enforcement specs, or skill-local guidance

---

## Step 0: Resolution Gate Check

> Selectively cloned from aaddrick/claude-pipeline `/improvement-loop` gate.

**Before extracting any lessons, verify the work is done:**

1. Is the original task functionally complete?
2. Are tests passing (if applicable)?
3. Has the user confirmed resolution (or moved on to a new topic)?

If ANY check fails — the session is still mid-task — defer distill to
after the task completes. Say: "Task appears in-progress. Run /distill
after the current work is complete for better lesson extraction."

If all pass, or the user explicitly requested /distill, proceed.

**Resolve roots once before reading or writing persistence:**

- `STATE_ROOT` is `$HOME/.codex` when `$CODEX_THREAD_ID` is set, otherwise
  `$HOME/.claude`.
- `CONFIG_ROOT` is the claude-config Git worktree this session is editing, then
  `$CLAUDE_CONFIG_ROOT` when set, otherwise `$HOME/.claude`. Writes go to this
  canonical source repo, not to a generated marketplace or installed copy.
- `SKILLS_ROOT` is `$CONFIG_ROOT/skills` when present. For read-only discovery
  only, fall back to `$HOME/.agents/skills` in Codex or `$HOME/.claude/skills`
  in Claude Code.
- `PROJECT_MEMORY_SOURCE` and `PROJECT_MEMORY_WRITE_TARGET` are runtime-specific:
  - In Codex, the source is `$STATE_ROOT/memories/MEMORY.md`. Never edit that
    generated index directly. Each T2 write creates one governed extension note
    at `$STATE_ROOT/memories/extensions/ad_hoc/notes/<UTC-timestamp>-<short-slug>.md`.
  - In Claude Code, resolve
    `PROJECT_ID="${CLAUDE_PROJECT_ID:-$(pwd | tr '/:.' '---')}"` using the
    `skills/_shared/project-dir.md` convention. The source and write target are
    `$HOME/.claude/projects/$PROJECT_ID/memory/MEMORY.md`.

---

## Step 1: Extract Pain Points

Read the current conversation and identify pain points. Check
for prior distills in this session:

**Session-scoped dedup**: Before analyzing, check `$STATE_ROOT/last-distill.json`.
**Verify ownership first**:
compare its `session_id` to `$CODEX_THREAD_ID`, falling back to
`${CLAUDE_CODE_SESSION_ID:-$CLAUDE_SESSION_ID}`. The marker is shared mutable state that concurrent
sessions overwrite; if ids differ, IGNORE it and scan the full conversation. Live instance
2026-06-12: a parallel session's retro overwrote the marker 24 minutes before this session's
/retro. Only when the marker is THIS session's AND its `timestamp` is less than 2 hours old:
analyze only messages after that timestamp. If all pain points were already captured, report
"Nothing new since last distill at [time]" and stop.

For each pain point, assign BOTH a severity tier (Step 2) AND a friction
category from this taxonomy. The tier drives the fix; the category makes
the retro summary diagnostic ("3 rule-gaps, 1 skill-misfire" tells you
where to invest).
(ag-grid/ag-charts reflect friction-taxonomy — Context7 registry 2026-04-07)

| Friction category | What it means | Likely root cause |
|-------------------|--------------|-------------------|
| `tool-failure` | MCP call errored, timed out, or returned unexpected results | API change, auth issue, transport error |
| `skill-misfire` | Wrong skill triggered, or skill guidance was ignored/contradicted | Description too broad/narrow, missing trigger phrases |
| `rule-gap` | Agent lacked knowledge a rule should have provided, or rule didn't load | Missing rule, wrong glob, incomplete content |
| `rule-overload` | Large rules loaded but irrelevant to the task | Overly broad globs, missing `disable-model-invocation` |
| `context-waste` | Burned significant tokens on dead-end approach | Missing early-exit guidance, redundant info loaded |
| `permission-gap` | Tool calls denied that should have been allowed | Settings gaps, hook logic too strict |
| `missing-capability` | No skill/command covers a needed workflow | Missing skill — candidate for skill ideas backlog |

Look for:

- **Tool failures** (`tool-failure`): MCP calls that errored, timed out, or returned unexpected results
- **Abandoned approaches**: Methods tried then discarded for a different approach
- **Platform issues**: Encoding, path, shell, or OS-specific problems that caused errors
- **API surprises**: Response formats, required parameters, or behaviors that weren't obvious
- **Repeated mistakes**: Patterns that failed the same way as in previous sessions
- **Silent failures**: Things that appeared to succeed but produced wrong results
- **Information accuracy failures**: Cases where the user corrected guidance you presented. Look for phrases like "that's wrong", "we already know this", "why did you get it wrong", "we went through this before", "you got it wrong again". These indicate stale knowledge, missed local context, or reliance on unverified external sources. The fix is usually a rule/workflow update or a patterns file addition - not just noting the correct answer, but fixing WHY the wrong answer was given.
- **Rule effectiveness gaps**: Cases where an existing rule or workflow should have prevented a mistake but didn't. Grep `rules/*.md` and `agent-memory/topics/*.md` for rules that were relevant but insufficient. The fix is a rule UPDATE (strengthen the existing rule) not a new entry. Classify as T1 (rule update).
- **Plan gaps**: Cases where a preparation step, plan, or checklist missed something that caused rework. Extract the specific preventable gap and propose a concrete addition to the relevant checklist, plan template, or pre-deploy verification. Different from `/capture` which records the narrative - distill extracts the actionable fix.

### Root Cause vs Workaround - CRITICAL

For each pain point, ask: **"Was the root cause fixed in this session, or
was it only worked around?"**

- If the root cause was fixed: document the fix, not the workaround
- If a workaround was used but the root cause IS fixable: flag it as
  `[WORKAROUND - root cause unfixed]` and describe what the actual fix
  would be. Do NOT persist the workaround as the lesson - persist the
  root cause and the fix.
- If the root cause is genuinely unfixable (platform limitation, upstream
  bug, third-party constraint): only then document the workaround, and
  label it `[PLATFORM CONSTRAINT]` or `[UPSTREAM]` so it's clear why a
  workaround is necessary.

**Watch for fix-by-deletion** — the disguised workaround. If you resolved
something by *removing the trigger* (deleted debris, cleared a cache, killed a
process, force-pushed over a mess), the symptom is gone but the root cause may
be untouched — and the evidence went with it, so it's easy to misclassify as
T5/resolved. Ask: what *produced* the trigger, and is THAT fixed? Don't mark it
skip just because the symptom can no longer reproduce. (2026-06-13: a stray
`.pytest_cache` removed from `skills/` cleared a healthcheck Tier-A FAIL but
left the dir-filter bug that mis-flagged it — caught only a retro later.)

**Bad**: "Plugin hook blocks Write tool. Workaround: use Bash + Python."
**Good**: "Plugin hook blocks Write tool. Fix: remove the broken plugin
(4-step purge). Root cause: MSYS path corruption of CLAUDE_PLUGIN_ROOT."

The goal is to eliminate problems, not accumulate workarounds.

**Ignore**: Routine operations that succeeded on first try, strategic design
decisions (those belong in `/capture`), task-specific details with no
reuse value. Note: `/capture` records the NARRATIVE (what happened and why).
Distill records the PREVENTABLE GAP (what broke and how to stop it next time).
A single incident can be both captured and distilled - they serve different purposes.

**If the session had no meaningful errors or pain points, report "nothing to
distill", collect the Step 1b metrics, then go directly to Step 5 with
`lessons = []` before stopping.** Do not manufacture lessons from successful
work, run dedup, or write to a persistence tier. A clean session is a good
session; its zero-lesson coordination marker is still required.

---

## Step 1b: Collect Session Metrics

Scan the full conversation and count the following. These numbers go into the
retrospective header and make the severity of problems concrete.

**Measure, don't estimate — and use these definitions** (2026-08-22: a real
session had 6 user messages and 226 assistant messages; "total turns" mapped to
neither, and "tool calls failed" was ambiguous between 6 `is_error` tool
results and ~8 additional nonzero-exit incidents, so the run had to invent its
own definitions mid-flight):

| Metric | Definition (measurable) |
|--------|------------------------|
| **Total turns** | assistant messages in the transcript (count `type == "assistant"` records with text or tool_use content). Report user messages separately when they tell the story. |
| **Tool calls attempted** / **failed** | attempted = `tool_use` blocks; failed = `tool_result` blocks with `is_error: true`. Report guard blocks, push rejections, and other nonzero-exit evidence as a SEPARATE count — they are friction, not `is_error` results. |
| **Retries** | re-issues of a materially identical call after a failure |
| **Abandoned approaches** | approaches started then replaced by a different method |
| **Turns on dead ends** | assistant messages spent on work that was discarded |
| **Pivots** | direction changes on the main task |
| **Files touched** | distinct files written or edited |

**Counting a MARKER STRING over-reports, because the string is also in the
prose.** The guard-block count above is the trap: `BLOCKED` appears in every
guard's rejection text AND in every assistant message that quotes or explains
one, so substring-counting `tool_result` content inflates it by the number of
times the session TALKED about the blocks. Measured 2026-08-26: a metrics script
returned **35** guard blocks against a real **5** — a 7x over-report on the
exact metric this table asks for. The same class as `/retro` Step 0's
`grep -c isCompactSummary` warning; it reappears here because Step 1b asks you
to count from the transcript.

REQUIRED shape: attribute every block to a NAMED guard, report the per-guard
counts, and **verify the named counts SUM to the reported total**. An `unknown`
bucket that dominates the named ones means the pattern is matching your own
narration, not tool results — report the named sum, not the substring count.
The 35-vs-5 case was 30 `unknown` and 5 named (`bash-tail-buffering-guard=2`,
`commit-guard=2`, `inline-python-guard=1`), and the named breakdown is what made
the over-count obvious.

**Narration is not the only false source — a FILE YOU READ is one too.** Restricting
the scan to `tool_result` content (not assistant prose) is necessary but NOT
sufficient: a `Read` of a guard's own source or test file returns a `tool_result`
whose content legitimately contains the marker tokens. Measured 2026-08-30: reading
`hooks/test-hooks/test_rule_size_guard.py` — whose docstring states
`Contract: PreToolUse:Write|Edit` and `BLOCK 38,000` — put 2 phantom blocks into a
6-count whose real value was **4**. So require the result to **BE** a hook error,
not merely to contain the tokens: match the envelope at the START of the content
(`PreToolUse:<Tool> hook error:`), and treat a hit whose first line is anything else
as not-a-block. The named-sum control above is what surfaces it — here `unknown=2`
against `named=4` did not dominate, so only reading the two unknown entries' first
lines revealed they were file contents.

**Efficiency ratio**: `(total turns - turns on dead ends) / total turns` as a
percentage. Below 70% signals a rough session. Below 50% signals systemic issues.
On a long session the denominator swamps the numerator — 651 turns with ~20 dead-end
turns reads 97%, which says almost nothing. Report the dead-end turns and what they
were as an absolute count too; the ratio is only diagnostic when turns are few.

**Failure rate**: `tool calls failed / tool calls attempted` as a percentage.
Above 10% suggests tool or environment instability.

Not every metric will be meaningful for every session - report the ones that
tell the story. Zero-value metrics can be omitted.

---

## Step 1c: Skill-First Routing Check

> Selectively cloned from tobihagemann/turbo `/self-improve` routing logic.

**Before classifying by tier**, check whether each pain point corrects,
refines, or adds a guardrail to a specific skill's behavior. This includes:
lessons about skipping steps, wrong defaults, missing edge cases, or any
"don't do X when running /skill-name" correction.

For each pain point:

1. Scan `$SKILLS_ROOT/*/SKILL.md` filenames (already in context from
   step 1 extraction — skill invocations are visible in the conversation)
2. If the lesson clearly corrects a specific skill → route the fix to that
   skill's SKILL.md. Do NOT route to rules, memory, or topic files.
3. This is a **hard constraint** that takes precedence over the tier
   classification in Step 2.

**Interaction with Step 2 tier classification**: skill-routed lessons SKIP
Step 2 entirely. They are not assigned a tier (T0-T5) — the routing IS the
classification. The Step 2 invariant "every lesson classified to exactly one
tier" applies only to lessons that survive Step 1c without being skill-routed.
Skill-routed lessons appear in the final output table as `target: <skill-name>/SKILL.md`
with `tier: SKILL-ROUTED` (a sentinel value, not a real tier).

**Why**: Lessons routed to rules load ambient in ALL conversations, wasting
context budget. Lessons routed to the skill they correct load only when that
skill is invoked — better scoping, better signal-to-noise. The context:fork
incident and model:sonnet incident both resulted from corrections landing in
rules instead of the skills they corrected.

Pain points that pass this check (not skill-specific) proceed to Step 1d
(cross-cutting audit) before tier classification.

---

## Step 1d: Cross-cutting audit check

Before classifying a lesson as T1 (ambient rule, applies everywhere) or
recommending speculative cross-repo remediation: if the pattern has a
grep-friendly signature AND would route to T1 AND you haven't seen it
fail elsewhere, run a focused 5-minute grep across 2-3 sibling repos
BEFORE assigning the tier.

Decision rule:
- **≥2 repos with hits** → confirmed cross-cutting → T1 rule
- **0 hits across N≥3 sibling repos** → confirmed repo-local → T4
- **Did not audit** → flag as "T1 candidate, audit pending"

Full procedure and empirical example: `references/cross-cutting-audit.md`.

---

## Step 2: Classify by Persistence Tier

For each pain point, classify using this matrix:

| Tier | Name | Criteria | Target | Invocation action |
|------|------|----------|--------|----------|
| **T0** | Enforce | Pattern that MUST be enforced every time - Claude skipping it causes data loss, broken output, or security risk. Rules (T1) failed or would fail to prevent it. Sub-classify: **T0-hook** (PreToolUse/PostToolUse hook), **T0-startup** (SessionStart check, add to `session-start.py`), **T0-ci** (CI validation, add to `validate` workflow). | Varies by sub-type | **Auto-stage/report** |
| **T1** | Rule | Platform constraint, universal anti-pattern, or mistake repeated across 2+ sessions | `$CONFIG_ROOT/rules/*.md` | **Auto-write** |
| **T2** | System fact | Key behavior, path, or constant that affects all sessions | `$PROJECT_MEMORY_WRITE_TARGET` | **Auto-write** |
| **T3** | *(retired 2026-06-10)* | Folded into T4 — in ~10 weeks zero T3 entries ever landed (everything classified T4 in practice); the 6 `memory/*-patterns.md` stubs were deleted with the B7/F3 owner decision. API gotchas keep their dual-write to `~/Documents/api-docs/{api}/gotchas.md` under T4. | — | — |
| **T4** | Topic memory | Tool gotcha, API-specific behavior (response shape, parameter format, error codes), or operational pattern relevant to one domain | `$CONFIG_ROOT/agent-memory/topics/{domain}.md` | Auto-write |
| **T5** | Skip | Already exists at any tier, too session-specific, or not actionable | None | Report only |

Invoking `/distill` authorizes the in-scope, non-destructive local writes in
this matrix; do not add a second confirmation gate. It does not authorize live
hook installation, settings mutation, file deletion, or remote git/GitHub
writes. T0-startup and T0-ci remain concrete implementation instructions, not
inline mutations.

**Classification heuristics:**
- Must happen every time without exception, and a rule wouldn't reliably prevent it? -> **T0** (enforce)
- The key test: "If Claude forgets this instruction, does output break silently?" If yes, T0. If Claude forgetting means suboptimal but not broken output, T1.
- **T0 sub-classification:** Once classified as T0, determine the enforcement mechanism:
  - **T0-hook**: Fires on every tool call of a specific type. "Every .md write must have contiguous table rows." -> Build a hook.
  - **T0-startup**: Must be true at session start. "settings.json must have X field." -> Add check to `session-start.py`.
  - **T0-ci**: Must be true before merge. "Every skill dir must have a routing entry." -> Add to `validate` CI workflow.
- Applies regardless of domain or tool? -> **T1** (rule)
- A fact every session should have in context? -> **T2** (system fact)
- Specific to one API, tool, service, or domain? -> **T4** (topic file)
- Already captured somewhere? -> **T5** (skip)

---

## Step 3: Deduplicate Across All Tiers

For each lesson, check ALL existing persistence tiers before writing.

**Run this concurrently, not serially.** The independent local sources
(items 1-5) should be issued as **parallel tool calls in a single turn** rather
than one after another. The semantic source (item 6) is a network call; when
there are **multiple** lessons, collect one query per lesson and issue them in
a single `mcp__memory-search__memory_search_batch(queries=[...], limit=5)` call
instead of one `memory_search` per lesson. Same results, one round-trip.

1. **Rules**: Grep across `$CONFIG_ROOT/rules/*.md` for matching keywords
2. **Project memory**: Search `$PROJECT_MEMORY_SOURCE`; in Codex, also grep existing `$STATE_ROOT/memories/extensions/ad_hoc/notes/*.md` so a pending governed update does not duplicate another extension
3. **Agent memory (T4 topic files)**: Grep across `$CONFIG_ROOT/agent-memory/topics/*.md` for matching terms. (T4 writes to topic files, not to MEMORY.md — reading MEMORY.md here would miss the actual T4 write target. The former `memory/*-patterns.md` grep was retired with the T3 tier, 2026-06-10.)
4. **Skills** (Step 1c routing target): Grep across `$SKILLS_ROOT/*/SKILL.md` for matching keywords. The Skill-First Routing Check at Step 1c routes corrections to skill files; the dedup must scan them too or risk re-adding a lesson that already exists as a skill step. (Added 2026-05-03 after roundtable found this scope gap; all three agents converged on this fix.)
5. **Staged hooks**: Grep across `$CONFIG_ROOT/hooks/staged/*.spec.md` for matching keywords. T0-hook lessons may have already been staged in a prior session and not yet installed.
6. **Semantic**: Call `mcp__memory-search__memory_search(query=<lesson summary>, limit=5)` — or, for multiple lessons, one `mcp__memory-search__memory_search_batch(queries=[<each lesson summary>], limit=5)` call (see the concurrency note above).

**Missing-directory fallback (preconditions for items 1, 4, 5):** Some
deployments — worktrees, fresh headless sessions, partially provisioned
audit environments — may lack `$CONFIG_ROOT/rules/`, `$SKILLS_ROOT/`, or
`$CONFIG_ROOT/hooks/staged/`. Before each grep, check the parent dir exists.
If absent, skip that dedup source and
log "skipped: <path> not present in this deployment" to the lessons
table footer. Do NOT abort the skill — dedup is best-effort coverage,
and the remaining sources still provide signal. Items 2, 3, and 6
(project memory, agent-memory topic files, and semantic search) are also
optional and treated the same way: missing source = skip + log, never
abort.

**Dedup decisions:**
- Match at **same or higher tier** -> T5 (skip). Note "already in {file}".
- Match at **lower tier** -> propose **promotion** (move up). Show both old
  location and proposed new location.
- Match as `[observed]` in agent memory -> propose **confirmation** (edit
  in-place to `[confirmed]`, add confirmation date).
- No match anywhere -> proceed with classified tier.

**Semantic similarity threshold**: If memory_search returns a result with
cosine > 0.75 that covers the same concept, treat as a match.

**EXCLUDE `[auto-captured]` entries from dedup matches.** Topic files may
contain `### [auto-captured] Worker learning (YYYY-MM-DD)` entries appended
by `subagent-stop.py`. Those are auto-routed worker output, NOT the kind
of distilled lesson /distill produces. If the only match is an
auto-captured entry covering the same concept, treat it as NO MATCH and
proceed with the classified tier — the auto-capture is noise that should
not suppress a real distillation.

Skip pattern: when grep'ing topic files in step 3-4 above, filter out
sections starting with `### [auto-captured]` before applying the
semantic-similarity threshold. The 2026-05-28 retro caught this gap —
`subagent-stop.py` had polluted `agent-memory/topics/msgraph.md` with 9+
auto-captured entries, which caused /distill to mark legitimate session
lessons as "already persisted" when the matches were just hook noise.

---

## Step 4: Present and Write

Present the retrospective with a metrics header followed by the lessons table:

```
## Session Metrics

| Metric | Value |
|--------|-------|
| Total turns | 47 |
| Tool calls | 82 attempted, 11 failed (13%) |
| Retries | 6 |
| Abandoned approaches | 2 (pip install cascade, direct Edit on skill files) |
| Turns on dead ends | 14 |
| Efficiency | 70% (33 productive / 47 total) |
| Files touched | 8 |

## Distilled Lessons

| # | Lesson | Friction | Tier | Target | Action |
|---|--------|----------|------|--------|--------|
| 1 | Git Bash grep -E fails on complex patterns | tool-failure | T5: Skip | (in rules/platform-constraints.md) | SKIP |
| 2 | Tenable severity expects text not int | context-waste | T4: Topic | topics/tenable.md | NEW |
| 3 | CS FQL dates need quotes | rule-gap | T4: Topic | topics/crowdstrike.md | CONFIRM |
```

### Writing rules by tier

Full procedure for each tier (SKILL-ROUTED, T0-hook / T0-startup /
T0-ci, T1, T2, T4 with API dual-write, T5) plus the
post-writes summary format lives in
[`references/tier-writing-guide.md`](references/tier-writing-guide.md).

Quick map for the common case:
- **SKILL-ROUTED** — edit the target skill's `SKILL.md` directly; no
  rules/memory writes.
- **T0** — stage to `hooks/staged/{name}.spec.md` for `/ship-hook`;
  do NOT install inline.
- **T1** — append to the appropriate `rules/*.md`; check size budget,
  apply the T1 rule/incident split pattern if the rule exceeds 35K chars.
  **TEN rules have a 10,000-BYTE cap that the hook does NOT enforce — measure
  it before appending.** See the T1 size-budget note below.
- **T2** — write to `$PROJECT_MEMORY_WRITE_TARGET`; in Codex this means creating a governed extension note, never editing `memories/MEMORY.md` in place.
- **T4** — append to agent memory using the root-cause-required
  format; API gotchas dual-write to
  `~/Documents/api-docs/{api-name}/gotchas.md`.
- **T5** — skip with reason; no writes.

**Before any T1/T2/T4 write, check that `$CONFIG_ROOT` can actually SHIP the
target file — on a divergent checkout the write is invisible to every future
session.** `$CONFIG_ROOT` is usually `$HOME/.claude`, which on this host is
**278 commits ahead / 216 behind `origin/main`** with most of `agent-memory/topics/`
already dirty arc content. Appending there produces a file that can never be
merged (the arc's semantic conflicts), so the lesson lives only on one disk and
the next session reads `origin/main` without it.

For each resolved target, run `git -C "$CONFIG_ROOT" status --short -- <target>`:
- **clean** → append in place; `/retro` Step 5 ships it normally.
- **dirty (`M`/`MM`)** → do NOT append blind, and do NOT
  `git checkout origin/main -- <target>` (that destroys the local-only content,
  which is frequently a PRIOR session's unshipped lesson). Cut a worktree —
  `git -C "$CONFIG_ROOT" worktree add <path> -b distill/<slug> origin/main` —
  write there, and ship that branch. If the same lesson must also be visible in
  the live checkout, hand-merge it in and mark what it supersedes.
- Report which targets were shippable and which were worktree-routed. A write
  the skill cannot ship is not persistence, and reporting it as `NEW` is a false
  completion claim.

`/garden` already branches from `origin/main` for exactly this reason
(`skills/garden/references/checks-staging.md`, "Why Step 1 branches from
origin/main"); distill did not, and the cost is measurable. 2026-08-25: a
`topics/msgraph.md` bullet written 2026-08-24 recording that
`bin/msgraph_helper.py` was GET-only sat in a LOCAL-ONLY copy of that file. The
next day's session re-derived the whole app-only Graph write path from scratch —
the note existed, had the right content, and was structurally unreadable. Two
consecutive sessions paid for one unshippable write.

After all writes: report counts by tier and friction category, promotions,
and the worst offender (single pain point that consumed the most turns).

---

## Step 5: Write Distill Coordination Marker

After persistence writes—or directly from the clean-session path in Step 1—
create a marker so future /distill invocations can skip already-distilled
patterns.

Use the bundled atomic writer; do not copy or hand-edit marker-construction
code. It derives `session_id`, `timestamp`, and `lesson_count`, validates the
payload, and replaces the marker only after a complete write.

For a clean session:

```bash
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/distill/scripts/write_marker.py" --clean
else
  python3 "$CONFIG_ROOT/skills/distill/scripts/write_marker.py" --clean
fi
```

For a session with lessons, provide only measured metrics and structured
lessons. Omit any metric that cannot be measured; never substitute a guessed
zero. Include the friction category assigned in Step 1.

```bash
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  DISTILL_WRITER="${CLAUDE_PLUGIN_ROOT}/skills/distill/scripts/write_marker.py"
else
  DISTILL_WRITER="$CONFIG_ROOT/skills/distill/scripts/write_marker.py"
fi
python3 "$DISTILL_WRITER" --input - <<'JSON'
{
  "metrics": {"total_turns": 47, "tool_calls_attempted": 82, "tool_calls_failed": 11},
  "lessons": [
    {"title": "Tenable severity expects text", "tier": "T4", "target": "topics/tenable.md", "friction": "context-waste"}
  ]
}
JSON
```

The writer rejects caller-supplied derived fields and invalid tier or friction
values. `--input` also accepts a JSON file path when that is safer than stdin.

`lesson_count` and `lessons` are required together so the same-session dedup
gate and other explicit readers can verify the count against the structured
entries. Both keys MUST be emitted on every write; no lifecycle hook consumes
the marker implicitly.

The contract is captured by `manifests/schemas/last-distill.schema.json`
and enforced in CI (`tests.yml` → "Validate marker schemas"). If you
change the marker shape, update the schema in the same commit — the
validator runs every PR.

Future /distill invocations read this file's `timestamp` field (see Step 1
"Session-scoped dedup") and only scan conversation messages newer than that
timestamp. The `lessons` array is included so the same-session gate can also
report what was already distilled when it skips with "nothing new since last
distill"; it is NOT used for keyword-overlap filtering.


---

## Success Criteria

- Session metrics collected with concrete numbers, not vague impressions
- Pain points extracted focus on errors and wasted time, not successful work
- Every lesson assigned a single classification: either exactly one T0-T5 tier with clear rationale, OR routed to a specific skill per Step 1c (carries `tier: SKILL-ROUTED`, no T0-T5 tier)
- Dedup check runs against all 6 sources in Step 3 (Rules, project memory plus pending extensions, agent-memory topic files, Skills, staged hooks, semantic search) before any write
- Invocation authorizes all in-scope, non-destructive writes without a second approval prompt: skill-routed edits, T0-hook staged specs, and T1/T2/T4 writes. T0-startup and T0-ci remain implementation instructions; live hooks/settings, deletions, and remote git/GitHub mutations are out of scope
- T4 writes use the existing format of the target file
- Marker file written for distill coordination
- Every reported lesson retains its friction category in the result table and coordination marker
- If the session had no errors, the skill reports "nothing to distill", writes a zero-lesson coordination marker, and performs no persistence-tier writes
- T0-hook findings are designed and written as staged specifications to `hooks/staged/` (not installed inline)
- T0-startup and T0-ci findings are reported with specific instructions for manual implementation
- Zero duplicate entries created across any tier
- When deleting or moving files (pattern files, topic sections), grep topic files for `> Deep reference:` lines pointing to the deleted path and remove them
- T1 writes that would push a rule file >35K use the T1 rule/incident split pattern (strongwording in the rule, narrative in `rules/incidents/<name>.md`). The incident reference is not a T2 system-fact write. T1 writes that would push past 38K are blocked by `rule-size-guard.py` — extract older incidents first.
- **The ambient tier is NET-ZERO-GROWTH by default. Before any T1 append, plan the
  offset.** The two per-file caps this section used to describe (10,000 B on ten
  `formerly_dominant` rules, 5,000 B on ten `quality_rules`) are RETIRED. They were
  cliffs: repairs converged to just under them and the next append breached again --
  `git-hygiene.md` went breach -> repair FOUR times in 16 days at ~9,800 of 10,000,
  across 13 dedicated cap-repair PRs, and at retirement SIX rules across the two caps
  sat under 500 B of headroom while the corpus as a whole had room.

  What binds now:
  - `manifests/ambient-budget.json` sets a DERIVED ceiling on the whole unconditional
    corpus: `baseline + sum(justified ledger entries)`. There is no stored number to
    edit, so raising it requires appending an entry with a byte count and a reason.
  - `scripts/test_context_policy_contracts.py` enforces it (and RAISES on a missing or
    malformed ledger, so the gate cannot be deleted).
  - `rule-size-guard.py` still enforces WARN 35,000 / BLOCK 38,000 per file, and warns
    at authoring time when a write would breach the ledger ceiling. It is ADVISORY
    there and silent when the ledger is simply absent, because the deployed `~/.claude`
    can sit behind `origin/main`; CI is the enforcement.

  So a T1 append that grows the corpus needs one of these, cheapest first:
  1. relocate >= the added bytes out of ambient in the SAME change (to
     `rules/incidents/<name>.md` or `docs/rule-reference/<name>.md`, which cost nothing
     until read);
  2. route the lesson to `agent-memory/topics/` (T4) or a skill step instead;
  3. add `paths:` frontmatter if the rule is genuinely path-scoped -- it then leaves
     the unconditional corpus entirely;
  4. only if none fit, append a justified ledger entry.

  Measure against `origin/main`, not local HEAD: on a content-diverged checkout local
  HEAD understates the real figure (measured 2026-08-25: by 1,082 B, the whole margin).

  **So a T1 append to any of those ten passes the hook, passes this skill's
  stated gate, and reddens CI** — the guard has no per-file 10,000 rule, and the
  test runs in the "Run scripts/ tests" step that `validate` gates on, so every
  open PR in the repo then inherits a failure it did not cause.

  Measured, three times: #2013 and #2111 were both titled "bring git-hygiene.md
  back under the cap", and #2111 landed at **215 bytes** of headroom before the
  next distill broke it **one day later** (#2119 appended the
  hand-typed-object-ID FORBIDDEN → 10,345 B). #2127 was the third repair.
  Treat sub-500-byte headroom on these ten as "does not fit", and prefer routing
  the narrative to `rules/incidents/<name>.md` or
  `docs/rule-reference/<name>.md` over growing the ambient file.

  If an append genuinely will not fit, the honest outcomes are: relocate older
  detail out of the ambient rule in the SAME change, or record the lesson at T4
  and say the T1 slot is full. Do NOT raise the test's constant to accommodate a
  write.

- **The per-file byte caps this section describes were REPLACED upstream by a
  DELTA LEDGER. Read `manifests/ambient-budget.json` before any T1 append.** The
  operative ceiling is derived, not stored:
  `allowed = baseline_unconditional_bytes + sum(entry.bytes for entry in ledger)`,
  so there is no constant to edit — growth requires appending a ledger entry with
  a byte count and a reason. The old ten-rule 10,000-byte cap was retired for a
  measured reason: a cliff makes every repair converge just under it, which
  produced 13 cap-repair PRs between 2026-07-01 and 2026-08-26 and left 16,395
  bytes unused across seven files while three sat under 500 bytes of headroom.
  The `formerly_dominant` / `quality_rules` tuples still exist in
  `scripts/test_context_policy_contracts.py`, but they now gate only the
  `docs/rule-reference/<name>.md` existence-and-pointer assertions, NOT bytes.

  **The ladder, cheapest first, from the ledger's own comment:** (1) relocate
  equivalent bytes out of ambient in the SAME change — to `rules/incidents/<name>.md`
  or `docs/rule-reference/<name>.md`, which cost nothing until read; net zero, no
  ledger entry needed. (2) Route the lesson to a lazily-loaded tier instead
  (`agent-memory/topics/` for a domain gotcha, a skill step for an activity
  discipline). (3) Add `paths:` frontmatter if the rule is genuinely path-scoped.
  (4) Only if none fit, append a ledger entry and say why the bytes must be
  ambient. A NEGATIVE entry is how the ceiling ratchets DOWN.

  **Measure against `origin/main`, never the local checkout.** This host's
  `~/.claude` runs hundreds of commits behind, so its copy of both the test and
  `hooks/rule_context_budget.py` can describe a superseded mechanism. Measured
  2026-08-29: the local test still asserted the 10,000/5,000 per-file tuples and
  the local module reported `WARN_BYTES = 225_000`, while upstream had moved to
  the ledger and pristine `origin/main` was already **2,515 bytes over** its
  derived ceiling — so a T1 append sized against the local numbers reds CI on a
  gate the local tree cannot even see.

---


See `references/tier-decision-tree.md` for the full tier decision tree.

## Examples

**Example 1: Mixed tiers — new write, skip, and promotion**

| # | Lesson | Friction | Tier | Action |
|---|--------|----------|------|--------|
| 1 | FQL date values must be single-quoted ISO 8601 | rule-gap | T4: Topic | NEW in topics/crowdstrike.md |
| 2 | grep -E fails in Git Bash | tool-failure | T5: Skip | Already in rules/platform-constraints.md |
| 3 | Airlock MCP responses double-serialized | context-waste | T4: Agent | CONFIRM [observed] -> [confirmed] |

**Example 2: Novel rule + system fact**

| # | Lesson | Friction | Tier | Action |
|---|--------|----------|------|--------|
| 1 | Archestra requires Node <25 | rule-gap | T2: System fact | WRITE to resolved project-memory target |
| 2 | Edit tool on ~/.claude.json races with Claude process | tool-failure | T1: Rule | WRITE to rules/platform-constraints.md |

**Example 3: T0-hook enforcement**

| # | Lesson | Friction | Tier | Action |
|---|--------|----------|------|--------|
| 1 | Claude double-spaces markdown, breaking GFM tables | skill-misfire | T0-hook | STAGED spec at hooks/staged/md-table-spacing.spec.md |

Result: Hook spec designed and staged. Install via `/ship-hook` or manual review.
