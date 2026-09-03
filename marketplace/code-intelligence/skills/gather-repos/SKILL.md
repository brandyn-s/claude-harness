---
name: gather-repos
description: "Discover community Claude Code repos and produce structured per-repo inventories."
when_to_use: 'Use when discovering community Claude Code repos. Trigger phrases: "gather repos", "find repos", "discover repos", "community repos". Do NOT use for community patterns/tips (use /gather-intel) or evaluation (use /evaluate-repos). Uses structural GitHub search, batch screening, and parallel subagent inventory. Produces structured inventories per repo — does NOT evaluate or implement.'
argument-hint: "[optional: specific repo URL for ad-hoc inventory]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires gh CLI for GitHub repo search and metadata retrieval. Tavily, Exa, and Firecrawl MCP servers for multi-source web augmentation (parallel discovery beyond GitHub keyword search).
  requires:
    - mcp: firecrawl
    - mcp: github
    - mcp: tavily
    - mcp: exa
    - cli: gh
allowed-tools: Bash Read Write Edit Glob Grep mcp__exa__get_code_context_exa mcp__exa__web_search_exa mcp__firecrawl__firecrawl_search mcp__tavily__tavily_search AskUserQuestion
---

# Gather Repos -- Community Config Discovery & Inventory

Discover, screen, and inventory Claude Code configuration repos from the
community. Produces structured per-bucket inventories that feed into
`/evaluate-repos` for debiased assessment via advocate/skeptic agents.

**This skill discovers and inventories. It does NOT evaluate, rate, or
implement.** Evaluation is `/evaluate-repos`. Implementation follows
user decisions from that evaluation.

Read `references/repo-assessment.md` for discovery methodology including
structural search queries and the repo type classifier.

---

## Scope guard

Before proceeding, verify the request is in-scope. If the user wants:
- **Community patterns/tips** (not repos) → redirect to `/gather-intel`
- **Evaluation** of discovered repos → redirect to `/evaluate-repos` (or use `/scout` for full pipeline)
- **Developer profiling** (a specific GitHub user's practices) → redirect to `/absorb`

Gather-repos inventories repos only — no quality verdicts, no adoption decisions. Those belong to /evaluate-repos.

---

## Ad-Hoc Mode (when argument is a URL)

If `$ARGUMENTS` contains a GitHub URL, skip discovery and triage:

1. Check for framework/product signals (package.json at root, npm
   package, own CLI tooling, README says "install")
2. If auto-SKIP type detected, warn: "This looks like a [type] (0%
   historical hit rate). Inventory anyway?" Proceed only if user confirms.
3. If not auto-SKIP, inventory across all 6 buckets (Step 3 below).

Update the ledger with inventory results.

---

## Step 1: Discover

### Read state

Read `~/.claude/assessed-repos.md` for:
- **Query cursors** -- which queries were used previously
- **Run Log** -- discovery strategies and results
- **Existing entries** -- for dedup
- **Assessment queue** -- score 4+ repos from prior runs not yet inventoried

**First-run bootstrap.** If `~/.claude/assessed-repos.md` does not exist,
create it with this template before proceeding:

```markdown
# Community Repo Assessments

Ledger for `/gather-repos`. Re-check entries >90 days old with new commits.

## Assessed

<!--
One heading entry per assessed repo, written by this skill:

### [inventoried|queued|auto-skip|dup|low-signal|canary] owner/repo (YYYY-MM-DD)
- N* | brief one-line content summary
- Found by: (query/source), score N/6
- Per-bucket: (optional structured bullets for inventoried entries)

`/evaluate-repos` may later add `### [adopted|upgraded|skip|bookmark|forked]`
entries on its own pass; this skill never writes those verdicts.
-->

## Assessment Queue
<!-- score-4+ repos from prior runs awaiting inventory -->

## Run Log
<!-- one entry per run: date, queries used, repos screened/inventoried -->

## Handoff to /evaluate-repos
<!-- last gather-repos run summary; consumed by /evaluate-repos -->
```

**Ledger verdict vocabulary** (this skill writes these — `/evaluate-repos`
later overwrites or annotates with its own vocabulary):

| Verdict | Meaning (set by this skill) |
|---|---|
| `inventoried` | Score 4+ repo passed triage and was inventoried this run |
| `queued` | Score 4+ repo deferred to a future run (in Assessment Queue) |
| `auto-skip` | Type classifier rejected (framework/aggregator/template) |
| `dup` | Already present in a prior row — no re-inventory |
| `low-signal` | Phase 1 score 1–3 and Phase 2 triage produced SKIP |
| `canary` | Inventoried + a pattern from it was canary-adopted (annotated later) |

`/evaluate-repos` may add `adopted`, `upgraded`, `skip`, `bookmark`, or
`forked` verdicts on its own pass; this skill never writes those.

Write each entry as a heading `### [verdict] owner/repo (YYYY-MM-DD)` so
the audit parser (`test-gather-repos.py --audit`) can extract it. Do NOT
use a markdown table; the audit regex anchors on the heading shape.

Then proceed with the rest of Step 1 against the freshly-created (empty) ledger.

### Canary check

Before discovering new repos, check `[canary]` entries from prior runs:
1. Search recent `/distill` and `/retro` entries for problems caused
   by canary implementations (hook latency, false positives, conflicts)
2. If problems found: flag for revert and warn the user
3. If 2+ sessions passed clean: promote from `[canary]` to `[adopted]`

### Discover, Classify, Screen

Run all 3 discovery strategies in parallel, then classify and screen.

1. **Dynamic query generation** + **random sampling** + **secondary source**
   Generate 2-3 new queries per run from structural marker combinations
   (see `references/repo-assessment.md`). Never repeat exact queries.

   **Multi-source web augmentation (Tavily + Exa + Firecrawl)**: GitHub structural search alone misses repos whose names don't contain "claude". Fire all three of these IN PARALLEL on each run — they have complementary strengths:

   - **Exa** (`mcp__exa__get_code_context_exa`, `mcp__exa__web_search_exa`): semantic content matching. Finds repos via content-of-files matching even when the repo name is unrelated. Use `get_code_context_exa(query="Claude Code CLAUDE.md hooks skills .claude configuration repo")` and `web_search_exa(query="Claude Code configuration setup repo", numResults=10)`.
   - **Tavily** (`mcp__tavily__tavily_search`): recent-content surfacing. Use `tavily_search(query="Claude Code skills hooks configuration GitHub", time_range="month")` to catch repos surfacing via blog posts, Reddit threads, X/Twitter announcements that don't yet have indexable code-content signals.
   - **Firecrawl** (`mcp__firecrawl__firecrawl_search`, `firecrawl_map`): once a high-signal config-aggregator site or community-curated list is found (e.g., a "best Claude Code repos" listicle, a community wiki page), use `firecrawl_map` to discover all linked repos and `firecrawl_search` to find more pages on that domain.

   Run Tavily and Exa as the primary parallel pair. Use Firecrawl as a follow-up only when one of the first two surfaces a curated list page worth deep-crawling — don't fire it on every run unsolicited (heavier per-call cost).

   **Dedup scope**: Web-discovered repos (from any of the three sources) go in the candidate list for
   Phase 1 screening, NOT in the dedup exclusion set. Only repos already
   in the assessed-repos.md ledger are excluded. Do not skip a repo just
   because it appeared in multiple discovery sources within the same run.
   (2026-04-05: Exa repos accidentally added to KNOWN set in screening
   script, excluding them from Phase 1.)

   **Paradigm-name queries**: when a discovery target has a known incumbent
   ("alternatives to our code-graph"), templates anchored on the incumbent's
   marketing keywords return same-paradigm peers. Surface paradigm-distinct
   candidates by also firing queries on **paradigm names**, not incumbent
   self-description:

   | Incumbent-keyword (anchors on peers) | Paradigm-name (anchors on novelty) |
   |---|---|
   | `"code knowledge graph"` | `"learned call resolution graph neural network"` |
   | `"tree-sitter mcp server"` | `"datalog code analysis incremental"` |
   | `"semantic code search"` | `"scope graph stitching name resolution"` |

   For each priority area, fire **both** an incumbent-keyword query and at
   least one paradigm-name query. If only same-paradigm peers come back,
   escalate to `/scout-frontier` (FP-tolerant, academic-frontier-first).
   Reference: `~/Documents/knowledge-base/topics/scouting-methodology.md`.
2. **Batch Phase 1 screening** -- use `${CLAUDE_PLUGIN_ROOT}/scripts/_gather_screen.py`
   to screen ALL discovered repos (not a hand-picked subset).

   **Script contract (stdout, one line per repo):**

   ```
     {repo}: {stars}* | {file_count}f | score {score}/6 [{BUCKETS}] | {desc} | pushed {pushed}
   ```

   - `{repo}` is the single combined `owner/repo` string (one
     interpolation, NOT two) — matches the entries in the script's REPOS
     list (e.g., `ya-luotao/claude-agent-sdk-ruby`).
   - `{score}` is integer 0–6, one point per bucket the repo populates
     (hooks, rules, skills, agents, memory, config).
   - `{BUCKETS}` is a space-separated, uppercased list of populated bucket
     names (e.g., `HOOKS RULES SKILLS`); empty `[]` when score is 0.
   - Unreachable repos print `  {repo}: UNREACHABLE` and produce no score.
   - Final line is the literal string `Done.`.

   Parse stdout line-by-line: split on ` | `, then extract the score from
   the `score N/6` token. Score 4+ goes to Track A (inventory); 1–3 to
   Track B (Phase 2 read); 0 or `UNREACHABLE` is dropped.
3. **Type classifier** -- auto-SKIP frameworks/aggregators/templates
   (exception: high hook-to-file density overrides file count)
4. **Two-track triage**:
   - Score 4+ repos -> DIRECT to inventory (skip Phase 2 triage)
   - Score 1-3 repos -> Phase 2 read from highest-scoring bucket

Dedup against the ledger. Log the run.

### Multi-signal supplementary ranking (2024+ research)

When the score-4+ list exceeds inventory budget (>10 repos), tier-break with these signals — **bucket-count remains the primary signal** because it measures Claude Code config substance, but these surface engagement and health that bucket-count misses:

| Signal | Source | What it catches |
|---|---|---|
| **HITS centrality** (He, Ye & Zhou, JSS 2024, arXiv:2405.07508) | GitHub bipartite user-repo graph (stargazers + forks edges) | Repos that are actively used/connected, not just starred. Drop in HITS = predicts deprecation. |
| **Composite Stability Index** (Adejumo & Johnson 2025, arXiv:2508.01358) | Weekly commit frequency + **median** issue resolution time + PR merge rate + community engagement | Repo health signal. Use **weekly** sampling (not daily) and **median** stat (not mean) — both empirically validated as more feasible. |
| **Recombination novelty** (Mészáros & Wachs 2024, arXiv:2411.14894) | Novel library-combination signature — does this repo combine libraries no peer combines? | Most empirically-supported innovation signal in OSS. Only meaningful when ≥3 repos in inventory candidate set. |
| **Stars** | GitHub | **Tie-breaker only.** Documented gameable (Borges & Valente JSS 2018; "Fault in Our Stars" NDSS 2024; StarScout 2024). |

**Honest computation status** (2026-04-27):

| Signal | Cheap to compute? | How |
|---|---|---|
| Bucket count (primary) | Yes — already done by `_gather_screen.py` | existing |
| Commit velocity (CSI component) | Yes | `gh api repos/{owner}/{repo}/commits?per_page=100&since=<8 weeks ago>` → count → /8 = weekly avg |
| Median issue resolution time (CSI component) | Yes (small repos) | `gh api repos/{owner}/{repo}/issues?state=closed&per_page=100` → median(closed_at - created_at) |
| PR merge rate (CSI component) | Yes | `gh api repos/{owner}/{repo}/pulls?state=closed&per_page=100` → merged/closed ratio |
| Stars (tie-break only) | Yes | `gh api repos/{owner}/{repo}` |
| **HITS centrality** | **No — requires bipartite stargazer/fork graph build** | Out of scope for this skill today; flag as "design intent" |
| **Recombination novelty** | **No — requires combination matrix across the candidate set + a scoring choice** | Out of scope today; flag as "design intent" |

**Qualitative tie-break checklist** (manual judgment when score-4+ list exceeds budget):

1. **Bucket count** is the only quantitative primary signal. Inventory by descending bucket count first.
2. **Among ties on bucket count**, prefer repos with higher commit velocity AND faster issue resolution AND higher PR merge rate (the three CSI components). Use `gh` queries above; eyeball the values rather than computing a normalized index.
3. **Among further ties**, prefer repos that combine library/skill ecosystems differently from peers in the candidate set (recombination — judged by reading manifests, not computed).
4. **Stars are the last tie-breaker only.** Never use as a primary or secondary signal.

If you find yourself wanting a numeric score: stop and ask whether the candidate set actually exceeds budget. With ≤10 score-4+ repos, just inventory all of them — no ranking needed.

Forbidden: filtering candidates by stars BEFORE this checklist. Star-popularity filtering changes correlation structure (Malviya-Thakur & Mockus 2024, arXiv:2401.10136 — commits-stars correlation flips sign in popularity-filtered samples).

Forbidden: treating "low-star = frontier" as a positive signal. Empirically not supported. Low-star correlates with utility libraries and recent-but-undeveloped repos, not paradigm novelty. Use `/scout-frontier` for paradigm-distance scouting; this skill is config-substance scouting.

Skip multi-signal ranking entirely when score-4+ candidates ≤ inventory budget (just inventory all of them).

## Step 2: Triage

**Track A (score 4+):** Apply type classifier only. If not auto-SKIP
type -> goes directly to inventory. No Phase 2 file reads needed.

**Track B (score 1-3):**
1. Read **1 file from highest-scoring bucket** (not always settings.json)
2. Skip README (it's marketing, not signal)
3. Classify: **INVENTORY** / **SKIP**

**Source-first for repos <5K LOC.** When inventorying small repos, read the
manifest (Cargo.toml/go.mod/package.json) + 1-2 key implementation files
before the README. README claims often contradict the code (the
`/scout-frontier` 2026-04-26 session caught a "no config required" claim
that was actually 5 hardcoded framework patterns once we read
`default_patterns.yaml` directly). Stars and recency are tiebreakers, not
gates — a dormant 2-year-old repo with substantive source beats a
freshly-spawned framework with marketing.

**No domain filtering.** Cross-domain transfer is the highest-value
pattern.

Update ledger entries.

## Step 3: Inventory

For repos that pass triage, produce a structured inventory across all
6 buckets. Use parallel Explore subagents (Sonnet) for throughput.

**Subagent scope (HARD CONSTRAINT).** Subagents inventory the external
repo ONLY. They must not perform gap analysis, quality ratings, or any
comparison against our local architecture — they cannot read our local
`~/.claude/` files and the resulting baseline drift produces false
"gap" claims (incident: 2026-03-22). Full subagent-scope rule, including
what the prompt must and must NOT request, lives in
`references/repo-assessment.md` § "Subagent scope rule (HARD CONSTRAINT)".

**Minimum 5 inventories per run.** If fewer than 5 candidates from
discovery, pull from the assessment queue. If the queue is also empty,
inventory all qualified candidates that remain and note the shortfall
("inventoried N — pool exhausted") in the run log; the "Minimum 5"
target is the discovery-pull rule, not a hard gate that blocks shipping
a smaller pool.

### Subagent inventory prompt

Dispatch Explore agents (2-3 repos per agent) with:

```
Read the Claude Code config at github.com/{owner}/{repo}. For each
bucket, read ALL files and report what each does (1-2 sentences):
- Hooks: read every .py/.sh/.ts/.js file in hooks/
- Rules: read every .md file in rules/
- Skills: read the 3 most distinctive SKILL.md files (skip "commit",
  "format"). Report methodology steps, gates, modes.
- Agents: read 2-3 agent .md files
- Config: read settings.json
- Memory: read memory/topic files if they exist
Report ONLY what each file does. Do NOT compare to any baseline.
```

### Per-bucket inventory checklist

For each inventoried repo, produce this table:

```
| Bucket  | Phase 1 | Files read              | Content summary |
|---------|---------|-------------------------|-----------------|
| Hooks   | (N)     | (list filenames read)   | (what they do)  |
| Rules   | (N)     | (list filenames read)   | (what they do)  |
| Skills  | (N)     | (list filenames read)   | (what they do)  |
| Agents  | (N)     | (list filenames read)   | (what they do)  |
| Memory  | (N)     | (list filenames read)   | (what they do)  |
| Config  | (N)     | (list filenames read)   | (what they do)  |
```

Rows with Phase 1 score > 0 and "Files read" empty = incomplete.

### Community insight routing

If community threads (Reddit, HN) produced architecture-relevant
insights, classify as Actionable (create Linear issue) or Informational
(log in run log).

## Step 4: Handoff to /evaluate-repos

After all inventories are complete, present a summary to the user AND write
a handoff section to `~/.claude/assessed-repos.md` that `/evaluate-repos`
will read.

### On-screen summary

```
DISCOVERY SUMMARY

Repos discovered: N
Phase 1 screened: N (of N)
Score 4+ candidates: N
Inventoried: N repos across M total bucket-files
Assessment queue: N repos deferred to next run

Inventoried repos:
  [repo] (N*, score N/6) -- [1-line summary of most distinctive content]
  ...

Run /evaluate-repos to evaluate these with advocate/skeptic pairs.
Or /evaluate-repos [repo-name] for a specific repo.
```

### Handoff file format (consumed by /evaluate-repos)

Create or overwrite the `## Handoff to /evaluate-repos` section in
`~/.claude/assessed-repos.md` with the most recent gather-repos run summary.
(Note: first-run bootstrap creates this section empty; subsequent runs overwrite it.)
`/evaluate-repos` reads exactly this section as its input contract.

```markdown
## Handoff to /evaluate-repos

Run date: YYYY-MM-DD
Run cursor: <query-cursor-token-or-N/A>

Inventoried this run:
- owner/repo (score N/6, buckets: hooks=N rules=N skills=N agents=N memory=N config=N)
  Distinctive: <1-line content summary>
  Files read: <comma-separated list of paths read during inventory>
- ...

Assessment queue (deferred):
- owner/repo (score N/6) -- <1-line why deferred>
- ...
```

Each `owner/repo` line under "Inventoried this run" is one candidate
`/evaluate-repos` will dispatch advocate/skeptic agents against. The
"Distinctive" line is the seed input to those agents. The
"Files read" list lets `/evaluate-repos` skip re-reading the same paths.

If no repos were inventoried this run, write `Inventoried this run: (none)`
so `/evaluate-repos` can detect an empty handoff and prompt for a repo
URL instead of failing.

## Step 5: Update Ledger

Update `~/.claude/assessed-repos.md` with:
- Inventory entries for each repo (Phase 1 scores, bucket counts)
- Assessment queue for score 4+ repos not inventoried this run
- Run log entry with queries used, type hit rates
- Canary promotions/flags from the canary check
- **Auto-archive**: run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/_gather_repos_archive.py`
  at the end of Step 5. It moves `## Run Log` entries older than 30 days
  from `~/.claude/assessed-repos.md` into `~/.claude/assessed-repos-archive.md`
  (append-only, preserves heading shape), keeping the most-recent run plus
  the last 30 days in the main ledger. `--dry-run` previews without writing.
  This prevents the ledger from growing past ~200 lines. (2026-04-05:
  ledger reached 774 lines, mostly archived run logs, forcing a manual
  reset; the script mechanizes the invariant so a missed agent-side archive
  no longer accumulates.)

---

## Rules

- **Always run when invoked.** Never refuse because "data is recent."
- Each run MUST use different queries than previous (cursor pagination)
- **No evaluation, quality ratings, or SKIP/UPGRADE verdicts.** That is
  /evaluate-repos. This skill inventories only.
- 0 new repos is a valid outcome (all duplicates or auto-SKIP types)
- The assessed-repos.md ledger is the single source of truth

## Success Criteria

- [ ] Discovery used random sampling + structural query + secondary source
- [ ] Batch screened ALL discovered repos (not hand-picked)
- [ ] Score 4+ repos went directly to inventory (no triage gate)
- [ ] Repo type classifier applied (auto-SKIP frameworks/products)
- [ ] Minimum 5 repos inventoried (or all qualified if fewer)
- [ ] Per-bucket inventory checklist complete for each repo
- [ ] Inventory subagents read from EVERY scored bucket
- [ ] No quality ratings, SKIP/UPGRADE verdicts, or approach comparisons
- [ ] Handoff to /evaluate-repos presented with summary
- [ ] Ledger updated with inventories, queue, and run log

## Examples

**Example 1: Regular discovery run**
```
/gather-repos
```
Generates 3 queries, batch screens 300+ repos, inventories 8 score-4+
repos via parallel agents, presents summary, suggests /evaluate-repos.

**Example 2: Ad-hoc repo inventory**
```
/gather-repos https://github.com/someone/interesting-config
```
Skips discovery, inventories the repo across all 6 buckets, adds to ledger.

**Example 3: Continue from prior run**
```
/gather-repos
```
Checks assessment queue first, inventories queued repos before discovering
new ones.

---

# Evaluation Prompts

Use these with `/skill-creator` to measure skill output quality before and after changes.

Two evals (regular discovery + ad-hoc inventory), the user-rejection log format,
and per-run signal-to-noise metrics live in
`references/evals-and-metrics.md`. Load that file when grading a run, when
appending to the rejection log, or when generating the Run Metrics block.
