---

name: retrospective
description: "Review what went well, what went wrong, and what's missing across recent sessions."
when_to_use: 'Use when reviewing what happened across recent sessions - what went well, what went wrong, and what gaps exist in skills, hooks, rules, or memory. Trigger phrases: "retrospective", "what happened", "review sessions", "weekly review". Do NOT use for single-session error capture (use /distill), memory curation (use /review-learnings), or infrastructure audits (use /audit-architecture).'
argument-hint: "[48h] [focus-domain] - e.g. '7d security', '48h', '1w infrastructure'"
effort: max
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: AskUserQuestion Bash Glob Grep Read Skill Write mcp__memory-search__memory_search
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.




# Retrospective

Deep analysis of session transcripts, git history, PRs, and learning reports to produce a strategic retrospective. The extractor prepares structured data. YOUR JOB is to actually read and analyze that data - not just summarize the aggregates.

## Rationalizations to Reject

| Rationalization | Why it's wrong |
|-----------------|---------------|
| "Context is getting long, do a lite analysis" | The user asked for a retrospective. Do the retrospective. All 13 passes. You have 1M context — use it. A partial report with deferred passes is not a retrospective, it's a summary. (Violated 2026-03-29.) |
| "The aggregates tell the story" | Aggregates hide the sessions that matter most. The 191-bash gather-claude session, the 32:0 retro ratio, the 8 high-bash no-skill sessions — all invisible in aggregates. Read every session. |
| "No data for this pass, skip it" | Report "No data — first measurement, baseline established" and move on. A pass with no data still needs a section in the report so the next retro can trend against it. |
| "The extractor didn't provide this field" | Read raw transcripts. The extractor is a starting point, not the only data source. Passes 7-13 explicitly require Grep on .jsonl files. |

## Step 1: Parse Arguments

- Format: `{number}{h|d|w}` optionally followed by a domain keyword
- Convert: `h` = literal, `d` = multiply by 24, `w` = multiply by 168
- Default: `48h`, no focus filter

## Step 2: Run the Extractor

The extractor script lives in the claude-config repo at `scripts/retro-extract.py`. Whether it is already reachable at `${CLAUDE_PLUGIN_ROOT}/scripts/retro-extract.py` depends on the deployment model: when `~/.claude` itself IS the claude-config checkout (the common Mac install — see the `claude-config-mac-deploy` memory note), the script is already there; when claude-config is cloned separately (e.g. `~/claude-config`) and `~/.claude` is a distinct install target, the script lives only in that separate clone. The resolver below checks both locations at runtime, so either deployment model works. Always redirect output to `/tmp/retro-extract.json` — for 7d+ windows raw JSON exceeds stdout display limits and dumps to the console if not captured.

Note: The extractor also writes a dated copy of the full output to `~/.claude/retrospectives/extract-YYYY-MM-DD.json` in addition to stdout. This file accumulates on repeated runs and can be used for historical comparison, but is not required for the analysis steps below.

```bash
python3 "$EXTRACTOR" --window {HOURS} [--focus {DOMAIN}] > /tmp/retro-extract.json
# where $EXTRACTOR is resolved from the first existing path below:
#   $HOME/claude-config/scripts/retro-extract.py  (conventional clone)
#   ${CLAUDE_PLUGIN_ROOT}/scripts/retro-extract.py        (already present when ~/.claude IS the claude-config checkout)
#   $(git -C "$HOME/claude-config" rev-parse --show-toplevel)/scripts/retro-extract.py
# Full resolver:
EXTRACTOR=""
for candidate in \
  "$HOME/claude-config/scripts/retro-extract.py" \
  "${CLAUDE_PLUGIN_ROOT}/scripts/retro-extract.py" \
  "$(git -C "$HOME/claude-config" rev-parse --show-toplevel 2>/dev/null)/scripts/retro-extract.py"; do
  if [ -f "$candidate" ]; then EXTRACTOR="$candidate"; break; fi
done
[ -z "$EXTRACTOR" ] && { echo "retro-extract.py not found; clone claude-config first" >&2; exit 2; }
python3 "$EXTRACTOR" --window {HOURS} [--focus {DOMAIN}] > /tmp/retro-extract.json
```

The extractor outputs JSON with: per-session metrics, error classifications, friction scores, git commits, PR data, and learning report summaries.

If no transcripts found, inform user and stop.

## Step 3: Multi-Pass Deep Analysis

This is the core of the retrospective. You MUST read the data thoroughly - not skim aggregates. The extractor provides the data. You provide the judgment.

### Pass 1: Read the Metrics (5 min)

Read the `aggregates` section of the extractor output. Note:
- Session count, error rate, friction score, retry rate
- Error breakdown by category (bash_error, tool_error, api_error subcategories)
- Friction components: `empty_results_friction` (genuine search misses) vs `empty_results_validation` (intentional absence checks after Edit/Write). Only friction empties count toward the friction score.
- Strategic signals: `sessions_without_skills` now excludes trivial sessions (<10min or <20 tool calls). Check `complexity_tiers` for the tier breakdown. Only flag skill-less as a gap for standard+ sessions.
- Skill utilization: check `parent_skill_invocations` for orchestrator counts (/retro, /retrospective). Skills attributed as `retro>distill` are child invocations via /retro, NOT standalone. The `skill_utilization` field shows both `retro>distill` (attributed) and bare `distill` (standalone).
- Per-day rates in `per_day` field for cross-window comparison.

### Pass 2: Read Every Session (15 min)

Read the `sessions` array. For EACH session, understand:
- What did the user ask for? (user_request field - read the full text, not truncated)
- What was the outcome? (outcome.has_git_commit, has_file_write, ended_with_error)
- What skills were invoked? Were they the right ones?
- What domains were touched?
- What errors occurred? (errors.classified - read the subcategories and messages)
- What was the friction breakdown? (empty results, user corrections with full messages, approach changes)
- What task patterns were detected? (task_patterns_detected)

Group sessions into themes: Which sessions were part of the same multi-session project? Which were standalone tasks?

### Pass 3: Read the Git History and PRs (10 min)

Read `git_commits` and `pr_data`. For each repo:
- What were the major deliverables? (group PRs by theme, not just list them)
- What was the velocity? (PRs per day, lines per PR)
- Were there PRs that took multiple attempts? (look for "fix:" PRs that follow a feature PR)
- Correlate: which sessions produced which commits/PRs?

#### 3a: Commit Classification and Fix Ratio

Classify each commit by its conventional prefix (`fix:`, `feat:`, `chore:`, `docs:`, `refactor:`, `ci:`, `test:`). Report the distribution. A fix ratio >40% suggests more time chasing bugs than building features. Trend this against previous retros — is the ratio improving or worsening?

The retro spans every repo the user has worked on in the window — never run bare `git log` from the CWD. Use `git -C <repo>` and iterate over the repo list (extractor exposes them under `git_commits.<repo>` and `pr_data.<repo>`):

```bash
# REPOS is the list discovered by the extractor; iterate explicitly with `git -C`.
# Defaults if extractor data is unavailable: ~/.claude, ~/claude-config, ~/Documents/knowledge-base.
# [WINDOWS-ONLY] git -C rejects the MSYS $HOME form (/c/Users/...) under Git Bash
# ("fatal: cannot change to '/c/...'"); cygpath -m gives C:/Users/... . On macOS this is
# a no-op — cygpath is absent so the $HOME fallback is used, and git -C ~/... works.
HOME_WIN="$(cygpath -m "$HOME" 2>/dev/null || echo "$HOME")"
REPOS=("$HOME_WIN/.claude" "$HOME_WIN/claude-config" "$HOME_WIN/Documents/knowledge-base")  # replace with extractor's list
for repo in "${REPOS[@]}"; do
  [ -d "$repo/.git" ] || continue
  fix_count=$(git -C "$repo" log --oneline --since="{hours} hours ago" | grep -cE "^[a-f0-9]+ fix:")
  total_count=$(git -C "$repo" log --oneline --since="{hours} hours ago" | wc -l)
  echo "$repo: fix=$fix_count total=$total_count"
done
```

#### 3b: Hotspot Files and Rework Rate

From git log, count changes per file across all repos. Report top 10 hotspot files. For each hotspot, check if the file was changed again within 7 days of a prior change (rework). High-rework hotspots are architectural pain points or files doing too much.

```bash
# Top changed files across all repos — aggregate per repo, then merge:
for repo in "${REPOS[@]}"; do
  [ -d "$repo/.git" ] || continue
  git -C "$repo" log --name-only --pretty=format: --since="{hours} hours ago" \
    | sed "s|^|$(basename "$repo")/|"
done | sort | uniq -c | sort -rn | head -10
```

#### 3c: PR Failure Rate (Change Failure Rate)

Count PRs with follow-up `fix:` PRs within 48 hours (same repo, same file set), and explicit reverts. This is the DORA "change failure rate" adapted for our workflow.

```bash
revert_total=0
for repo in "${REPOS[@]}"; do
  [ -d "$repo/.git" ] || continue
  r=$(git -C "$repo" log --oneline --since="{hours} hours ago" --grep="revert" | wc -l)
  revert_total=$((revert_total + r))
done
echo "reverts across all repos: $revert_total"
```

Report: total PRs, fix-follows within 48h, reverts, failure rate percentage.

### Pass 4: Read Every Learning Report (10 min)

Read `learning_reports`. The extractor returns a dict with:
- `session_reports`: legacy `session-transcripts/*.md` reports (mostly empty since March 2026)
- `commits`: dict keyed by repo (`.claude`, `knowledge-base`) with `distill`/`retro`/`capture` commit entries in the window — this is the MAIN source

For each commit entry in `commits`:
- What pattern was captured? (read the `subject` — commit messages are concise)
- Which kind fired? (`distill` = operational lesson; `capture` = strategic insight; `retro` = orchestrator sync)
- Are any of these patterns STILL causing errors in the session data? (lesson captured but not applied)
- Are there error patterns in the sessions that should have been captured but weren't?
- Which repo is receiving the most entries? A rapid divergence (e.g., many captures, few distills, or vice versa) hints at missing flow.
- **Cross-reference with memory-search**: For each recurring error category, run `mcp__memory-search__memory_search(query="<error category description>", limit=5)` to find related prior learnings. If a lesson exists but errors recur, the lesson isn't being applied — flag as a gap in the skills/rules/hooks.

### Pass 5: Read the Previous Retrospective (5 min)

Check `~/.claude/retrospectives/` for the most recent `.md` file. If found:
- Which gaps from the previous retro were addressed?
- Which gaps are still open?
- Did the metrics improve or regress?
- Are there recurring themes across retros?

**Window normalization**: When comparing windows of different lengths (e.g., 10d current vs 7d previous), ALWAYS use `per_day` rates from the extractor for trend analysis. Report both the raw count and the per-day rate. Flag when windows differ: "Note: comparing {X}d to {Y}d window. Per-day rates used for fair comparison."

### Pass 6: Read Topic File Changes (5 min)

On this host, `~/.claude` is a git repository (the deployed install directory is a checkout of claude-config). Topic files under `~/.claude/agent-memory/topics/` are symlinks (or copies) of files in the claude-config repo. Resolve the repo root explicitly to ensure the git log runs in the correct directory:

```bash
# Resolve repo root. Prefer the conventional clone path; fall back to git toplevel of the symlink target.
REPO_ROOT="$HOME/claude-config"
[ -d "$REPO_ROOT/.git" ] || REPO_ROOT="$(git -C "$(readlink -f "$HOME/.claude/agent-memory/topics" 2>/dev/null || echo "$HOME/.claude")" rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT/.git" ] && { echo "claude-config repo root not resolvable; skip Pass 6" >&2; }
git -C "$REPO_ROOT" log --oneline --name-only --since="{hours} hours ago" -- agent-memory/topics/
```

- Which topic files were updated most?
- Is the knowledge base growing in the right areas relative to the work being done?
- Are there domains being worked on heavily that have no corresponding topic file updates?

### Passes 7-13: Raw Transcript Access

Passes 7-13 require data beyond what the extractor provides. Read raw `.jsonl` transcript files directly:

```bash
# List transcript files in the time window.
# Resolve project dir. Claude Code encodes the absolute CWD into the project
# directory name by replacing every non-alphanumeric character (`/`, `.`, `:`,
# ...) with `-` (dots too: /Users/jane.doe -> -Users-jane-doe). The leading dash
# MUST be preserved (e.g., /home/user/claude-config -> -home-user-claude-config).
# Do NOT strip the leading dash — the historical sed 's|^-*||' recipe in
# _shared/project-dir.md silently produces a path that never resolves.
PROJECT_ID="${CLAUDE_PROJECT_ID:-$(pwd | sed 's/[^a-zA-Z0-9]/-/g')}"
PROJECT_DIR="$HOME/.claude/projects/$PROJECT_ID"
if [ ! -d "$PROJECT_DIR" ]; then
  # Fallback: most-recently-modified projects/ subdir (handles headless/worktree
  # sessions where $CLAUDE_PROJECT_ID is unset and CWD encoding doesn't match).
  PROJECT_DIR=$(ls -dt "$HOME"/.claude/projects/*/ 2>/dev/null | head -1)
  [ -z "$PROJECT_DIR" ] || [ ! -d "$PROJECT_DIR" ] && { echo "no project dir resolvable; pass --project-dir manually" >&2; exit 2; }
fi
CUTOFF=$(python3 -c "import tempfile,os; print(os.path.join(tempfile.gettempdir(), 'retro-cutoff'))")
# BSD/macOS touch lacks GNU relative `-d`; derive the timestamp via a BSD||GNU date fallback.
touch -t "$(date -v-{hours}H +%Y%m%d%H%M 2>/dev/null || date -d "{hours} hours ago" +%Y%m%d%H%M)" "$CUTOFF"
find "$PROJECT_DIR" -name "*.jsonl" -newer "$CUTOFF" 2>/dev/null
```

For each transcript, search for specific patterns using Grep (not by loading full files into context). The transcripts encode every tool call as a `"type":"tool_use"` JSON block whose `"name"` field is the tool name — there is no top-level `"tool"` key. Use these patterns:
- Tool-use blocks (any tool call): `Grep pattern='"type":"tool_use"' path=<transcript>`
- Skill invocations: `Grep pattern='"type":"tool_use"[^}]*"name":"Skill"' path=<transcript>` (or grep for `"name":"Skill"` after first filtering for `tool_use`)
- Specific tool by name: `Grep pattern='"name":"<ToolName>"' path=<transcript>`
- User corrections: `Grep pattern="no,|that's wrong|try again" path=<transcript>`
- ToB skill names (search within Skill tool-use inputs): `Grep pattern='"skill":"(fp-check|insecure-defaults|differential-review|sharp-edges|variant-analysis|agentic-actions-auditor)"' path=<transcript>`

Work from Grep results, not full file reads. Transcripts can be 50K+ lines.

### Pass 7: Skill Usage Metrics (5 min)

Scan every session in the extract for Skill tool invocations. Build:

1. **Frequency table**: skill name -> session count, sorted descending
2. **Co-occurrence matrix**: which skills appear together in the same session (top 10 pairs)
3. **Trend delta**: Compare against previous retrospective's frequency table (if exists). Flag: skills with >50% usage increase or decrease, new skills appearing, skills dropping to zero.
4. **Parent-skill attribution**: Use `parent_skill_invocations` and `child_skill_attributions` from the extractor. Skills like `retro>distill` were invoked BY /retro, not standalone. Report: parent orchestrator counts (e.g., "/retro: 50 invocations") separately from standalone child skills. Do NOT compare retro vs manual capture+distill — /retro IS the workflow that chains them.
5. **Skill execution cost**: For each skill in the frequency table, estimate token cost by summing input+output tokens for tool calls within that skill's invocation window in the transcript. Report: top 5 most expensive skills by total tokens and by per-invocation average. This answers: "Is stig-assess worth 25 turns? Is differential-review adding significant cost to ship?"

### Pass 8: ToB Integration Trigger Rates (5 min)

Search transcripts for invocations of Trail of Bits plugin skills embedded in existing workflows.

**Methodology note (2026-07-26 correction, supersedes 2026-04-21):** a `git commit` does not imply `/ship` — but `/retro` **does** chain `/ship`. The authoritative orchestration edges are the `requires_skills` lists in each skill's `manifest.yaml`, not this prose; query them with `python3 manifests/query_engine.py depends-on retro` rather than assuming. As of this writing `retro/manifest.yaml` declares `[distill, capture, ship, mega-distill]`, and `/retro` Step 5 makes `/ship` **mandatory** for session-produced artifacts (Step 0 routes to `/mega-distill` on large/compacted sessions).

The previous version of this note asserted that `/ship` is "not auto-chained by `/retro`" and that "`retro>ship` does not exist in the current architecture." **Both were false** and they biased every ship-related count here. Measured over 602 local transcripts: `retro` → `ship` in the same session occurs in 2 sessions — rare, but non-zero. Treating a real edge as impossible mis-attributes exactly those sessions, and the same error hid `retro>mega-distill`.

- A "ship session" = a session where the `ship` Skill tool was invoked, **whether standalone or attributed as `retro>ship`**. Count actual Skill invocations. Do NOT infer `/ship` fired because a session committed code — 30+ sessions per window commit via direct git commands. (This half of the original note was correct: it prevents over-counting.)
- `retro>distill` and `retro>capture` are not `/ship` invocations, but `retro>ship` **is** — count it. Likewise `retro>mega-distill` is a real edge on large/compacted sessions.
- When a window has zero `/ship` invocations (standalone **and** retro-attributed), the security gate embedded in `/ship` cannot have fired. Report 0 fires against 0 `/ship` sessions — do NOT impute them to commit-eligible sessions.
- If you want to measure whether ToB coverage is adequate, compare **commit-eligible sessions** (has_git_commit) to **actual ToB skill invocations across all sessions**. Low coverage is a routing/workflow gap, not a ToB skill failure.

**Before reporting any ToB-in-`/ship` ratio, verify the gate is actually implemented in `/ship`.** Live `/ship` implements exactly **one** security gate: the conditional `differential-review` at its Step 4. A gate this table attributes to `/ship` that `/ship` does not implement yields a **false zero** — "0 fires" reads as a coverage failure when the truth is "not implemented". Report those as **NOT IMPLEMENTED**, never as 0/N.

| Integration | Search pattern | Eligible set | Host gate |
|---|---|---|---|
| `differential-review` | `/differential-review` invocation | `/ship` sessions with security-sensitive diffs OR explicit diff review | **In `/ship` Step 4** (conditional) |
| `insecure-defaults` | `/insecure-defaults` invocation (standalone only) | explicit security-review requests | **NOT in `/ship`** — standalone |
| `agentic-actions-auditor` | `/agentic-actions-auditor` invocation (standalone only) | sessions touching `.github/workflows/` | **NOT in `/ship`** — standalone |
| `semgrep` | `/security-scanner:semgrep` invocation (bare `/semgrep` also works) | `/security-alerts` sessions (optional) | **NOT in `/ship`** — standalone |
| `fp-check` | `/fp-check` invocation | triage sessions with CRITICAL/HIGH findings | standalone |
| `variant-analysis` | `/variant-analysis` invocation | triage sessions after fp-check TRUE POSITIVE | standalone |
| `sharp-edges` | `/sharp-edges` invocation | full/red-team `/stig-assess` sessions | standalone |

The **Host gate** column exists because the earlier version of this table listed
`insecure-defaults`, `agentic-actions-auditor` and `semgrep` with `/ship`-scoped
eligible sets, implying `/ship` runs them. It does not — only
`differential-review` is embedded there. Measuring the other three "inside
`/ship`" produced denominators that can never be non-zero.
`manifests/test_orchestration_prose_matches_manifest.py` now pins the real
inventory, so adding a gate to `/ship` fails that test until this table is
updated in the same change.

For each: report fires/eligible ratio. Eligible count is 0 when `/ship` (or the host skill) itself was not invoked — in that case report "N/A — host skill not invoked" instead of implying a broken integration. If the host skill fires but the embedded ToB step does not, that's a real integration gap. If the host skill is being bypassed entirely (zero `/ship` across a window where many commits happened), that's a **workflow routing gap**, not a ToB integration gap — record it under GAPS not under ToB health.

### Pass 9: Rationalization Calibration (10 min)

For sessions that invoked `triage`, `investigate`, or `stig-assess`, search for evidence of cognitive shortcuts matching the rationalizations-to-reject tables:

1. **Rationalizations that fired**: Transcript shows the AI considered and rejected a shortcut listed in the table. Record which entry matched.
2. **Rationalizations never relevant**: Entries that had zero matches across all sessions. Candidates for removal if still zero after 3 retros.
3. **Uncovered shortcuts**: Transcript shows a shortcut was taken (finding auto-closed, FP assumed without verification, severity accepted from tool without rescoring) that ISN'T in the rationalization table. These are candidates for new entries.
4. **Miscalibrated entries**: A rationalization blocked a CORRECT shortcut (e.g., auto-closing a genuinely recurring known FP that was re-verified). These need qualifiers added.

### Pass 10: Security Gate Skip Rate (5 min)

For sessions that invoked `ship` (actual Skill tool invocation — see Pass 8 methodology note), check:

1. **`/ship` Step 4 (differential-review)** — the ONLY security gate `/ship`
   implements. How many times did the conditional gate ask "Run
   /differential-review before push?" How many run vs skip responses? If the
   skip rate is >80%, the gate triggers too broadly.

Do **not** report `/ship`-scoped trigger rates for `insecure-defaults` or
`agentic-actions-auditor` — `/ship` does not invoke either, so such a ratio is a
false zero (see the Pass 8 gate table's Host gate column). If you want their
coverage, count **standalone** invocations across all sessions and say so
explicitly.

Report the implemented gate's trigger rate, finding rate, and skip/accept ratio.

**If /ship invocation count is 0** for the window: skip-rate questions are not meaningful at the gate level. Instead report:
- `/ship` invocations = 0 of N commit-eligible sessions
- ToB Step A/B/C gates could not fire because the host skill was not invoked
- File this under **GAPS > workflow routing** (e.g., "`/ship` bypassed on 31/31 commit sessions") — not under ToB integration health.

### Pass 11: Abandoned Skill Invocations (5 min)

For each skill invocation in the transcripts, check whether it reached its Success Criteria:

1. **Triage**: Did it produce a scored triage table? (Search for composite score output)
2. **Investigate**: Did it produce a timeline? (Search for chronological event listing)
3. **Stig-assess**: Did it produce findings or run verification scripts?
4. **Ship**: Did it create a PR or push? (Search for PR URL or push confirmation)
5. **Superplan**: Did it produce a plan? (Search for numbered task list)

For each skill, report: invocations vs completions. Abandonment rate >30% indicates friction in the skill workflow. Note the PHASE where abandonment happened (Phase 0 = context loading problem, Phase 2+ = mid-execution friction).

### Pass 12: Anti-Pattern Recurrence (10 min)

Cross-reference known constraints against session errors to find rules being violated:

1. **Load rule files**: Read all rule files in the rules directory. Resolve the rules dir at runtime — `~/.claude/rules/` is the canonical install path (a symlink or copy of the repo's `rules/` directory), but a partial install or fresh clone may not have it deployed yet. Pick the first existing path:
   ```bash
   for rules_dir in \
     "$HOME/.claude/rules" \
     "$HOME/claude-config/rules" \
     "$(git -C "$HOME/claude-config" rev-parse --show-toplevel 2>/dev/null)/rules"; do
     if [ -d "$rules_dir" ]; then RULES_DIR="$rules_dir"; break; fi
   done
   [ -z "$RULES_DIR" ] && { echo "rules dir not resolvable; skip Pass 12 anti-pattern recurrence" >&2; }
   # Then: read every $RULES_DIR/*.md
   ```
   Extract each constraint (the "never do X", "always do Y" patterns). Key files:
   - `platform-constraints.md` — encoding, shell, Git Bash, CRLF gotchas
   - `diagnose-before-fix.md` — "read the actual error before proposing a fix"
   - `check-before-change.md` — "search memory/git before modifying defaults"
   - `git-hygiene.md` — branch naming, stash before rebase, verify branch before commit
   - `security-review-before-pr.md` — pre-PR checklist items
2. **Load rationalizations**: Read the Rationalizations-to-Reject tables from `triage`, `investigate`, and `stig-assess` SKILL.md files.
3. **Scan sessions for violations**: Use the extractor's classified error subcategories (e.g., `encoding_error`, `dirty_working_tree`, `file_not_read`) to map violations to rules. Do NOT scan raw transcripts for bare keywords like `cp1252` or `dirty_working_tree` — these appear in rule file text loaded into every session's system prompt, producing false positives (the 2026-04-05 retro reported 39.3% encoding errors when the real rate was ~5%, because `cp1252` appeared in platform-constraints.md rule text in every transcript). Instead:
   - Use the extractor's `errors.classified` subcategories — these come from `is_error:true` tool results, not from rule text
   - Map subcategories to rules: `encoding_error` → platform-constraints, `dirty_working_tree` → git-hygiene, `file_not_read` → check-before-change
   - A user correction like "no, read the error first" maps to `diagnose-before-fix`
4. **Report**:
   - **Most violated rules** (top 5 by session count) — these need stronger enforcement (hooks, hard gates, or skill steps)
   - **Never-violated rules** — candidates for removal after 3 consecutive retros at zero. But verify they're not preventing errors silently (the absence of violations might mean the rule works)
   - **New anti-patterns** — repeated mistakes with no corresponding rule. These are candidates for new rules or rationalization entries.
   - **Decay tracking**: For each anti-pattern, note when the rule was created. If violations persist >30 days after rule creation, the rule isn't working — escalate from rule to hook or skill step.

### Pass 13: Pattern Emergence (10 min)

Detect effective approaches that repeat across sessions but aren't codified:

1. **Tool call sequences**: Extract the ordered sequence of tool calls per session. Find sequences of 3+ tools that appear in 3+ sessions. Examples: "Read → Grep → Edit" (understand-then-fix), "git stash → git rebase → git stash pop" (safe rebase). Filter out universal sequences (every session starts with Read).
2. **Skill chains**: From Pass 7's co-occurrence data, identify chains of 3+ skills that appear together in temporal order across 3+ sessions. Example: brainstorm → /superplan → superpowers:subagent-driven-development is a known chain. NEW chains (not in any skill's workflow) are discovery candidates.
3. **Recovery patterns**: When an error occurs, what does the NEXT successful action look like? Repeated error→recovery pairs are candidates for automated recovery (hook or skill step). Example: "CRLF mismatch error → re-read in binary mode" appears 5 times → candidate for a hook.
4. **Report**:
   - **Codified patterns** (already in a skill/rule) — confirm they're still effective, note frequency
   - **Emerging patterns** (3+ sessions, not codified) — recommend: new rule, new skill step, or new skill
   - **Recovery patterns** — recommend: hook (automatic), rationalization entry (awareness), or skill step (manual gate)

## Rules

> Anti-skip enforcement inspired by tobihagemann/turbo `/finalize` and
> `/polish-code` patterns.

- Each pass does distinct work that no other pass covers. Pass 7 (skill usage)
  does not substitute for Pass 12 (anti-pattern recurrence). Passing tests
  does not substitute for reading transcripts. No pass is skippable.
- Session length, context usage, perceived prior-pass thoroughness, and "the
  aggregates tell the story" are NEVER valid reasons to skip a pass or do a
  "lite analysis." You have 1M context — use it.
- All 13 passes must run. If a pass has no data, report "No data — first
  measurement, baseline established" and continue. A pass with no data still
  needs a section so the next retro can trend against it.
- Do not present aggregates and offer to "do detailed analysis in a follow-up."
  The detailed analysis IS the retrospective. Aggregates alone are a summary,
  not a retro.

## Step 4: Synthesize the Report

Now - and ONLY now, after reading all the data - write the report following `references/report-template.md`.

**Your analysis must demonstrate that you read the data:**
- Reference specific sessions by ID and quote their user requests
- Reference specific PRs by number and explain what they delivered
- Reference specific learning report entries and assess whether they're being applied
- Reference specific error messages, not just category counts
- Correlate: "Session X asked for Y, produced PRs #A and #B, encountered errors in Z, and /distill captured pattern W"

**Strategic analysis must go beyond error counting:**
- Which recurring tasks need a new skill? (cite the sessions)
- Which existing skills have routing problems? (cite the wrong-name invocations)
- Which hooks are effective vs noise? (cite the hook block counts vs what they prevented)
- What architecture changes would eliminate systemic error categories? (cite the category counts)
- What workflows are being done manually that should be automated? (cite the bash pattern data)
- Are past lessons being applied or re-discovered? (cross-reference learning reports with current errors)

## Step 5: Write the Report File

Write to: `~/.claude/retrospectives/YYYY-MM-DD-{window}.md`

## Step 6: Print Terminal Summary

```
RETROSPECTIVE: {date_range} ({window})

METRICS
  Sessions: {n} | Avg duration: {n} | Total tool calls: {n}
  Errors: {n} ({n}%) | Retries: {n} ({n}%) | Friction: {n} (avg {n}/session)
  Output: {commits} commits, {prs} PRs merged across {repos} repos
  Skills used: {n} unique | Auto-learn: {n}/{n} ({n}%)

WHAT WAS ACCOMPLISHED
  {2-3 line summary of major deliverables by theme}

WHAT WENT WELL ({count})
  - {one-line with specific metrics}

WHAT WENT WRONG ({count})
  - {one-line with specific metrics}

STRATEGIC OPPORTUNITIES ({count})
  - {skill/agent/architecture opportunity + which sessions showed the need}

TOB INTEGRATION HEALTH
  {n}/{n} integrations firing on eligible sessions
  {list any BROKEN or INVESTIGATE status integrations}

ANTI-PATTERNS
  Top violated: {rule name} ({n} sessions)
  New anti-patterns: {n} discovered | Emerging patterns: {n} candidates

GAPS ({count})
  P1: {gap + recommendation + effort}
  P2: {gap + recommendation + effort}
  ...

Full report: ~/.claude/retrospectives/{filename}
```

## Success Criteria

- You READ every session in the extract, not just the aggregates
- You READ every learning report with entries
- You READ the git commits and PR data per repo
- Every finding references specific sessions, PRs, or error messages
- Strategic analysis cites specific sessions that demonstrate the need
- Learning report entries are cross-referenced against current errors
- Gap recommendations are concrete ("create /mcp-diagnose skill") not vague ("improve debugging")
- When a previous retro exists, you show which gaps were resolved and which recur

## Examples

**Example 1: Default 48h retro**
```
/retrospective
```

**Example 2: Weekly security-focused**
```
/retrospective 7d security
```

**Example 3: Quick daily check**
```
/retrospective 24h
```
