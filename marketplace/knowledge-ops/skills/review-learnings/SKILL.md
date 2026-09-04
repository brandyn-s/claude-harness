---

name: review-learnings
description: "Audit, prune, and correct agent persistent memory across topic files and pattern stores."
when_to_use: Use when auditing, pruning, or correcting agent persistent memory across all topic files and pattern stores. Shows what agents have learned, removes stale entries, fixes inaccuracies, and promotes patterns into system prompts. Trigger phrases - "review learnings", "audit memory", "prune topics", "what have agents learned". Do NOT use to capture new patterns from the current session (use /distill or /capture instead), or for external intelligence gathering.
# disable-model-invocation: this skill is user-invoked only (the model will not
# auto-route to it from chat). Once invoked, the procedure itself runs normally
# and the agent calls MCP tools, AskUserQuestion, etc. as documented.
disable-model-invocation: true
argument-hint: "[optional focus, e.g. 'security topics', 'stale entries', 'version cleanup', 'all topics']"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
  body-cap: exempt
  body-cap-reason: "PERIODIC: memory audit-and-prune sweep the session-start consistency module reminds about when overdue, disable-model-invocation, 15-40 turns; no requires_skills edge into it"
compatibility:
  # Requires memory-search MCP to audit agent memory files.
  requires:
    - mcp: memory-search
allowed-tools: Bash Read Glob Grep mcp__memory-search__memory_search mcp__memory-search__memory_stale mcp__memory-search__memory_stats AskUserQuestion
---

## review-learnings

# Review Agent Learnings

Read all topic-indexed memory files and present a structured audit.

## Steps

1. **Discover ALL memory locations**:
   - `~/.claude/agent-memory/topics/*.md` (canonical topic files — written by /distill, /capture, and workers; discover dynamically with Glob since the count grows over time)
   - `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/*-patterns.md` (if any exist — pattern files were consolidated 2026-03-25)
   - `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/MEMORY.md` (global auto-memory — concise index)
   - If `$CLAUDE_PROJECT_ID` is unset (headless / worktree sessions), derive it inline: the encoded ID is the absolute working-directory path with every `/`, `:`, and `.` replaced by `-` (the leading `/` becomes a KEPT leading `-`; e.g. `$HOME` → `-Users-you`). Full recipe: `_shared/project-dir.md`. If neither resolves, skip the project-scoped paths above rather than reading from an empty path.
   - Check for remnant directories: `~/.claude/agent-memory/security-ops/`, `sentinel/`, etc. Flag as legacy artifacts for cleanup.
1b. **Run the bundled analyzer first.** The mechanical analysis — per-file
   inventory, leading-tag counts, per-file format classification (`entry-format`
   / `reference-guide` / `mixed`), stale `[observed]` aging (dual-date
   "(opened, resolved by …)" entries age from the opened date), `[promoted]`
   tombstones and `[FIXED]` entries (each carrying a `keep_decision` flag when
   a prior audit's "Kept for historical record"-style note is present),
   `PROMOTE-CANDIDATE` / `[auto-captured]` inventories (auto-captured rows
   carry `junk_markers` when they contain transcript-prose fragments),
   duplicate titles, stale `> Deep reference:` paths, version-tag inventory,
   oversized entry-format files (cap-notice-aware; size-expected reference
   guides are listed separately under `large_reference_files`),
   `cap_notice_files` with hook/settings `producer_mentions` for the
   producer-liveness judgment, and mixed-format detection — is deterministic
   and is performed by `scripts/analyze_memory.py` (relative to this skill
   directory):

   ```bash
   python3 "<skill-dir>/scripts/analyze_memory.py" ~/.claude/agent-memory/topics --preflight
   ```

   `--preflight` also embeds the Step 15b contention classification (fetch,
   behind-count, per-file `SAFE` / `DEFER_DIRTY` / `DEFER_DIVERGED` /
   `DEFER_UNTRACKED` verdicts, live-session markers) under the `preflight`
   key — consume it in Step 15b instead of re-running the git commands by hand.

   It writes a JSON report to a temp path (printed on stdout). Consume that
   JSON for every count and candidate list in Steps 8-14; you (the LLM) apply
   the judgment parts — correctness review, promotion decisions, cross-topic
   merge choices, lossy-compression cost-benefit. Do not re-derive the
   mechanical counts by hand: /garden gained its analyzer for exactly this
   reason (prose-only checks get silently skipped or inconsistently applied —
   the 2026-06-08/06-10 detection-gap incident). If the script is unavailable,
   fall back to performing the inventory by hand per the steps below.
2. **Check current version**: Run `claude --version` to get the installed Claude Code version. This is needed for version staleness checks.
3. **Targeted reads only — do NOT read every topic file in full.** The corpus
   exceeds 1 MB and the analyzer already inventoried it; a full read costs
   ~350K tokens and adds nothing the JSON does not carry. Read: (a) every
   entry in an analyzer candidate list you must judge (at its cited file, via
   Grep for the entry title), (b) files whose analyzer row looks anomalous
   (contradictory counts, unexpected format), and (c) 2-3 spot-check files for
   the correctness review. Only if the analyzer is unavailable, fall back to
   reading each file in full.
4. **Read pattern files** (if any exist): Read any `*-patterns.md` files found in Step 1. If none exist (pattern files were consolidated into topic files), skip this step.
5. **Read global memory**: Read `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/MEMORY.md`. This contains entries that may overlap with topic files.
6. **Check knowledge capture health**:
   - Count transcript files in `~/.claude/projects/*/` (`*.jsonl` — the primary location) and the legacy `~/.claude/session-transcripts/` dir — if 0 transcripts exist in both, flag "no transcripts saved."
   - Check recent retrospectives for /distill and /capture usage rates.
7. **Legacy artifact check** (P0 — catches stale remnants):
   - If any directories exist under `~/.claude/agent-memory/` OTHER than `topics/`, flag as legacy artifacts from the old per-agent architecture.
   - Check if they contain unique content not already migrated to topic files. If unique, flag for migration. If duplicate, flag for deletion.
8. **Present a summary table** for each topic file:
   - Topic name
   - Number of entries (count distinct sections/bullets)
   - Topics covered (1-line summary per section)
   - Last modified date
   - Count of `[observed]`, `[confirmed]`, `[promoted]`, `PROMOTE-CANDIDATE` tags
   - Any format inconsistencies (mixed `###` headers vs `- bullet` styles within same file)
   - **Before flagging a file as "oversized" based on line count alone, read its header for an auto-management notice and verify that the named producer is still active.** A declared cap is evidence only when the producer remains wired and the actual entry count matches it. Historical files such as `recent-sessions.md` may retain old cap text after their lifecycle writer is retired; do not treat stale automation prose as a current exemption. The analyzer's `cap_notice_files[].producer_mentions` lists every hooks/ and settings.json line naming the file (with a `writer_hint`); YOU judge writer-vs-reader from those lines — zero mentions, or reader-only mentions, means the producer is retired and the cap notice is stale prose.
8b. **Decay Scoring** (if memory-search MCP available):
   - **FIRST, check reindex recency.** Call `mcp__memory-search__memory_stats()` and read `last_reindex`. A reindex resets every entry's last-access timestamp, so `memory_stale` and access-count data are meaningless until entries have been queried again. IF `last_reindex` is more recent than `days_threshold` (e.g. reindexed today but querying 14/30-day staleness), the decay data is UNRELIABLE this pass: note "decay scoring reset by reindex on {date} — access data not yet accumulated; falling back to authoring-date staleness (analyzer `stale_observed`)" and SKIP the access-based prune-candidate flags below. Corroborating signal: a `staleness_distribution` with `very_stale_30d_plus: 0` while most entries sit in one recent bucket is the reset fingerprint. (2026-07-24: `memory_stale(30)` returned 0 stale purely because the index was reindexed 5h earlier — every 86 authoring-old `[observed]` entry was still retrieval-live.)
   - Call `mcp__memory-search__memory_stale(days_threshold=14)` to get entries not accessed in 14+ days.
   - Include in the "Time staleness" section:
     - Show `decay_score` alongside each entry
     - Actionable thresholds: >=0.7 = healthy, 0.4-0.7 = aging (review), below 0.4 = stale (prune candidate)
     - Entries with `access_count=0` have never been retrieved by semantic search — flag as "never referenced — prune candidate"
   - **Fallback**: If memory-search MCP times out OR the reindex-recency check above fired, skip the access-based flags and note the reason. Fall back to date-based (authoring) staleness only.
8c. **Write-Only Memory Detection** (if decay scoring succeeded in 8b):
   - Filter entries from 8b where `access_count=0` AND entry age > 30 days.
   - These are "write-only" — they were written to memory but have NEVER been retrieved by any semantic search in 30+ days of existence. This is distinct from "stale" (accessed before but not recently) — write-only means "never useful since creation."
   - For each write-only entry, assess the likely cause:
     - **Poor discoverability**: the entry title uses vague or non-searchable terms (e.g., "API issue" instead of "Airlock POST /endpoints returns double-serialized JSON"). Recommend: reword title with specific tool names, error codes, and API endpoints.
     - **Low value**: the entry captures something too specific or session-bound to be useful again. Recommend: prune.
     - **Covered elsewhere**: the same knowledge exists in a topic file, rule, or MEMORY.md at a higher tier. Recommend: prune (already captured better).
   - Present in a dedicated "Write-Only Memory" section in the output (see Output Format below).
9. **Flag potential issues**:
   - Entries that contradict CLAUDE.md, agent system prompts, or other topic files
   - Entries that duplicate information already in the agent's `.md` system prompt file (candidates for deletion from memory)
   - `[observed]` entries older than 30 days — flag as "stale observed — confirm or prune"
   - Entries that appear 3+ times and should be promoted into the agent's system prompt
   - **`[promoted]` tombstones**: Entries tagged `[promoted]` are dead weight — flag ALL for removal (they're just bookmarks saying "moved elsewhere")
   - **`PROMOTE-CANDIDATE` entries**: Surface ALL entries with the `PROMOTE-CANDIDATE` tag — these have 3+ observations and are awaiting user action to promote into the agent's system prompt `.md` file
   - **Global memory overlap**: Entries in agent MEMORY.md that also appear in `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/MEMORY.md` — flag as "duplicated in global auto-memory"
   - **Format inconsistency**: If an agent uses mixed entry formats (some `### [tag]` headers, some `- [tag]` bullets, some `## Title [tag]`), flag for normalization. Mixed formats confuse `curate-memory.py` pruning logic.
10. **Version staleness check**:
   - Entries tagged `[workaround:vX.Y.Z]`: if current version >= the version where the fix landed, flag as "workaround likely obsolete — verify and remove"
   - Entries tagged `[until:vX.Y.Z]`: if current version >= vX.Y.Z, flag as "version constraint met — remove"
   - Entries tagged `[experimental:FLAG_NAME]`: check if the feature has graduated (no longer needs the flag) or been removed — flag for review
   - Entries that describe workarounds or version-specific behavior but lack version tags: flag as "consider adding a version tag for future pruning"
   - Also scan CLAUDE.md and ARCHITECTURE.md for version-specific workarounds that may be stale (e.g., references to bugs fixed in older versions)
11. **Cross-agent dedup check**:
   - **Primary method (fast, no MCP)**: For each entry title/topic across all agents, do a textual substring match against all other agents' entries. Flag entries where the same tool name, API endpoint, or error message appears in multiple agents' memory.
   - **Secondary method (if memory-search MCP available and responsive)**: Call `mcp__memory-search__memory_search(query=<entry title>, limit=3)` for the top 5 longest entries only (not every entry — avoids timeout). If a match in a DIFFERENT agent's memory has similarity > 0.7: flag as cross-agent duplicate.
   - **Fallback**: If memory-search times out on the first call, abandon MCP-based dedup entirely and rely on textual matching only.
   - Present duplicates with both agents and ask user which to keep (or merge into a shared topic file)
12. **Most-accessed analysis** (if memory-search MCP available):
   - Call `mcp__memory-search__memory_stats()` to get chunk-level access data
   - Identify the top 5 most-accessed entries across all agents (highest retrieval count from semantic search)
   - These are **validated high-value patterns** — candidates for promotion to agent .md files or CLAUDE.md
   - Present as: "Most referenced entries (highest operational value)"
   - **Fallback**: If MCP unavailable, skip and note "access frequency data unavailable."
13. **Archive health check** (skip if no archives exist):
   - For each agent with an `archive.md`, report line count and entry count.
   - If archive has >200 lines: flag "archive growing large — consider periodic purge of entries older than 90 days."
   - If archive has entries that were archived within the last 7 days but are `[confirmed]`: flag "confirmed entry was archived — possible incorrect pruning by enforce_bounds()."
   - Check: does archive contain any `PROMOTE-CANDIDATE` entries? If so, flag "high-value entry was archived instead of promoted — rescue it."
14. **Safe cleanup pass** (dead-weight removal — always recommend):
   - **HONOR prior-audit "kept" decisions first.** The analyzer pre-flags these: `fixed_entries[]` and `promoted_tombstones[]` rows carry `keep_decision: true` when the entry body contains an explicit keep-decision — "Kept for historical record", "no action needed", "[KEEP]", or a keep-decision note. Never propose removal of a `keep_decision: true` row. For candidate types the analyzer does not body-scan (duplicates, stale refs), still scan the entry's adjacent lines yourself before proposing removal. If a keep-decision is present, do NOT re-propose removal: a prior `/review-learnings` (or the entry's author) already decided this deliberately. Re-litigating it is a check-before-change violation and re-surfaces a finding the owner closed. Leave it and move on. (2026-07-24: the single `[FIXED]` entry in claude-code-config.md carried "Resolution verified by review-learnings audit (2026-07-03) … Kept for historical record; no action needed" — Step 14's blanket "Remove ALL [FIXED]" would have re-litigated a 3-week-old considered call.)
   - **Promoted tombstones**: Remove `[promoted]` entries — they're bookmarks to content that already lives elsewhere. (Skip any carrying a keep-decision per above.)
   - **[FIXED] entries**: Remove entries documenting resolved issues (the fix is in git history) — UNLESS the entry carries a keep-decision per above. A `[FIXED]` entry explicitly retained "for historical record" by a prior audit is NOT dead weight; it is a decision. Do not re-propose its removal.
   - **Exact duplicates**: Remove entries that appear twice in the same file (same content, different dates). Keep the more detailed version.
   - **Stale references**: Remove cross-references to deleted files, renamed directories, or deprecated systems.
   - **Stale observed**: If any `[observed]` entry is >60 days old, suggest pruning or confirming.
   - **Topic file overlap**: If pattern files exist and overlap with topic files, suggest deduplication.
   - **Stale deep references**: If topic files contain `> Deep reference:` lines pointing to deleted files, remove them.
   - **Cross-topic duplicates**: If the same pattern appears in 2+ topic files, keep in the canonical location and replace the other with a one-line cross-ref.
   > **Lossy compression guidance:** See references/output-format.md for the cost-benefit analysis framework.
15. **Present findings in two sections** (ALL findings from Steps 7-14):
   **Section A: Safe cleanup** (recommend "do all" — no information lost):
   - Prune promoted tombstones, [FIXED] entries, exact duplicates, stale references
   - Correct inaccurate entries
   - Promote PROMOTE-CANDIDATE entries into agent `.md` system prompt files
   - Add version tags to untagged workarounds
   - Delete stale project-scoped memory files / legacy artifacts
   - Rescue archived high-value entries
   - Cross-topic dedup (replace with cross-ref, not deletion)

   **Section B: Lossy compression** (do NOT recommend — mention only if asked):
   - Note: "{N} entries could theoretically be consolidated, but this removes exact error strings and root-cause narratives. Only consolidate if hitting context limits on a specific topic file."

15b. **Contention/divergence preflight — REQUIRED before editing ANY git-tracked file.**
   The `~/.claude` main checkout is frequently contended (concurrent sessions,
   dirty in-flight files, local `main` behind `origin/main`). Editing a tracked
   file in that checkout in place can revert a concurrent session's work or build
   on a stale base. Per `worktree-by-default.md` + `git-hygiene.md`, before any
   tracked edit consult the analyzer's `preflight` key (from the Step 1b
   `--preflight` run — re-run it if the Step 1b run predates your edit decision):
   - `preflight.files[<name>]` gives the verdict per tracked topic file:
     `DEFER_DIRTY` (concurrent work — editing collides/reverts),
     `DEFER_DIVERGED` (file differs between local HEAD and `origin/main` —
     stale base), `DEFER_UNTRACKED` (another session may be mid-creation —
     do not race it), or `SAFE` (clean vs HEAD AND vs `origin/main` —
     editable, in a worktree below).
   - `preflight.behind_origin_main` and `preflight.live_session_markers` set
     the overall contention picture; `preflight.fetched: false` means the
     behind-count is against a stale ref — re-run with network before trusting it.
   Manual fallback if the analyzer is unavailable:
   ```bash
   cd ~/.claude
   git fetch origin main --quiet
   git log --oneline HEAD..origin/main | head        # behind? (any output = stale)
   git status --short | head                          # concurrent dirty files?
   ls -la ~/.claude/.session-active/ 2>/dev/null      # other live sessions? (markers)
   git diff HEAD -- <file>                            # per-file: non-empty = DEFER
   ```
   Then CUT A WORKTREE from `origin/main` — never edit the contended main checkout in place:
   ```bash
   git -C ~/.claude worktree add ~/worktrees/claude-config-memory-audit -b chore/memory-audit-cleanup origin/main
   ```
   Apply all approved tracked edits IN THE WORKTREE. If, after classification, ZERO
   tracked edits remain safe (all deferred), there is nothing to ship — report the
   deferrals and skip Step 16 entirely. (2026-07-24: local main was 10 commits behind,
   `runbook.md` was dirty with a concurrent distill, an untracked stub was mid-creation
   by another session, and the one `[FIXED]` target carried a prior keep-decision — all
   four tracked edits correctly deferred, so no PR was cut. Untracked deletions, which
   carry no shared-HEAD risk, were done in the main checkout directly.)

16. **Persist changes via PR** (MANDATORY for git-tracked topic files):
   - Topic files in `~/.claude/agent-memory/topics/` are git-tracked in the claude-config repo.
   - **Untracked deletions** (empty legacy dirs, transient skill-scratch YAMLs, linter caches, gitignored files) carry no shared-HEAD risk — do them in the main checkout with plain `rm`, no worktree, no PR.
   - **IMPORTANT**: Use `git ls-files agent-memory/topics/` to determine which files are tracked. Gitignored files (e.g., `recent-sessions.md`) should NOT be staged.
   - This step runs FROM THE WORKTREE created in Step 15b (branch already cut off
     `origin/main`), where the approved tracked edits already live:
     ```bash
     WT=~/worktrees/claude-config-memory-audit
     cd "$WT"
     # Stage each edited file by explicit path; never `git add -A` here — that
     # would sweep in gitignored transients like recent-sessions.md.
     git add agent-memory/topics/<changed-file-1> agent-memory/topics/<changed-file-2>
     git commit -m "chore: memory audit — <summary of changes>"
     git push -u origin chore/memory-audit-cleanup
     gh pr create --title "chore: memory audit — <summary>" --body "<details>"
     # claude-config does NOT currently have a merge queue or auto-merge:
     # `gh pr merge --auto` fails to arm (main has no required checks;
     # enablePullRequestAutoMerge is absent — measured 2026-08-22, PR #2061).
     # Use the verifier helper, which arms/falls back and exits 0 only on
     # state==MERGED. On a DIRTY verdict it prints the generated-file
     # conflict recovery (merge main + build-marketplace.py + commit).
     python3 ${CLAUDE_PLUGIN_ROOT}/bin/pr-merge-verified.py <N> --repo brandyn-s/claude-harness --status-file /tmp/claude/pr<N>-status.json
     ```
   - After the PR reports `state == MERGED`, remove the worktree:
     `git -C ~/.claude worktree remove ~/worktrees/claude-config-memory-audit`.
   - **Important**: Run each git operation (`git add`, `git commit`, `git push -u`, `gh pr create`, `gh pr merge`) in separate Bash tool calls. Chaining them (add + commit + push + pr in one bash block) violates PreToolUse guards when evaluated against pre-command state — guards evaluate the ENTIRE string, so a chained block starting on a no-upstream branch will trip commit-guard and pr-guard. Separate calls let each guard check the fresh post-command state (rules/git-hygiene.md, 2026-05-29 incident).

> **Output format:** See references/output-format.md for the full report template.

Do NOT make changes without user confirmation. Present ALL findings first, then act on instructions.

## Success Criteria

- Both global (`~/.claude/agent-memory/`) AND project-scoped (`~/.claude/projects/$CLAUDE_PROJECT_ID/memory/`) directories discovered and read
- Project-scoped divergence flagged for every file present in both locations
- Knowledge capture health checked (transcript count, /distill and /capture usage)
- Version staleness checked against current `claude --version`
- ALL `[promoted]` tombstones flagged for removal
- ALL `PROMOTE-CANDIDATE` entries surfaced with explicit promotion recommendation
- Supplementary files (`*-patterns.md`) read if they exist (skip gracefully if consolidated)
- Archive health reported if archives exist (skip gracefully if none)
- Every flagged issue includes agent name, entry title, recommended action, and priority (P0/P1/P2)
- Cross-agent dedup uses textual matching first, MCP only as secondary (with timeout fallback)
- 0 changes made without user confirmation (the approval gate fires
  BEFORE any persistence step — confirmation is the precondition for
  the PR workflow below, never the other way around)
- Lossy compression NOT recommended by default — only mentioned if user asks, with cost-benefit gate
- Once user has explicitly approved the proposed changes, all changes
  are persisted via PR (not direct file writes) for git-tracked topic
  files. The git workflow runs only after approval.
- Before any git-tracked edit, the Step 15b contention/divergence preflight ran
  (fetch + behind-check + dirty-target classification + live-session check), and
  tracked edits were applied in a worktree cut from `origin/main` — never in the
  contended main checkout in place. Files dirty-with-concurrent-work, untracked/
  mid-creation, or carrying a prior keep-decision are DEFERRED, not edited.
- Decay/write-only flags (Steps 8b/8c) are suppressed when `last_reindex` is more
  recent than the staleness threshold (reindex resets access data); the audit
  falls back to authoring-date staleness and says so.
- Prior-audit "kept" decisions on `[FIXED]`/`[promoted]`/stale entries are honored,
  not re-litigated.
- If consolidation happens, `[consolidated]` tag used (never `[confirmed]` on merged blocks)
- Format inconsistencies flagged (mixed header/bullet styles that confuse curate-memory.py)

## Examples

**Example 1: Routine memory audit**
User says: "Review what agents have learned"
Actions:
1. Discover all topic files in `agent-memory/topics/` + global MEMORY.md. No pattern files (consolidated). No legacy dirs.
2. Check knowledge capture health: 12 transcripts saved, /distill used 3 times in last retro
3. Legacy check: security-ops/MEMORY.md has 3 entries not in any topic file. sentinel/baselines.md is audit-architecture state.
4. Find: security.md has 2 `PROMOTE-CANDIDATE` entries, infrastructure.md has 2 `[promoted]` tombstones
5. Read `ramp-patterns.md` - find 3 entries duplicated between topic file and pattern file
6. Cross-topic dedup: "Graph GCC High uses .us endpoints" appears in both msgraph.md and runbook.md
7. Present full audit table with prioritized recommended actions
Result: User approves: migrate legacy entries to topics, remove tombstones, promote 2 PROMOTE-CANDIDATEs, deduplicate cross-topic entries.

**Example 2: Post-upgrade cleanup**
User says: "We just upgraded Claude Code — check for stale workarounds"
Actions:
1. Read all agent memories (both locations) + CLAUDE.md + ARCHITECTURE.md
2. Compare version tags against current installed version
3. Find 3 entries referencing older versions where fixes landed
4. Check archives for any PROMOTE-CANDIDATE entries incorrectly pruned
5. Present version staleness table with REMOVE recommendations
Result: User approves removing 2 of 3, keeps 1 pending manual verification.

**Example 3: Focused agent audit**
User says: "/review-learnings security topics"
Actions:
1. Read security.md, crowdstrike.md, tenable.md, airlock.md topic files
2. Find: 1 `[promoted]` tombstone in security.md (Airlock rebuild), 1 `PROMOTE-CANDIDATE` in crowdstrike.md (FQL date quoting)
3. Cross-topic: "Airlock type must be list" in both security.md and airlock.md
4. Check for stale `> Deep reference:` lines pointing to deleted pattern files
Result: User approves tombstone removal, promotes PROMOTE-CANDIDATE, migrates legacy entry to topics/security.md, deduplicates cross-topic.
