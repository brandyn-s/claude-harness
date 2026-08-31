# Repo Assessment Methodology

Reference for `/gather-repos` discovery mode. Two-phase funnel: discover → triage. Deep assessment is out of scope (see `/evaluate-repos`).

## Discovery: Structural Search

The primary discovery source is **GitHub code search for structural markers**
that prove a repo is a Claude Code configuration — not topic enumeration.
Topic pages have 30K+ repos but <5% signal. Structural search narrows to
repos that actually contain skill/hook/rule files.

### GitHub Search Pagination Reality

GitHub code search returns `total_count` values (e.g., 1,508) but caps
actual results at ~200-300 regardless of pagination. Requesting page 3+
returns empty arrays. **Do not treat total_count as pageable.** Each
query yields ~200 usable results. Invest in MORE diverse queries instead
of paginating deeper into the same ones.

### Primary: Dynamic Query Generation (v6)

Static queries exhaust at ~200 results each. With 13K+ CC repos,
pre-defined queries address <10% of the population. **Generate queries
dynamically** from structural marker combinations.

#### Query generation protocol

Each run, generate 2-3 NEW queries by combining structural markers
from different categories. Never re-use an exact query from a
previous run.

**Bucket 1 — Hooks**: `SessionStart`, `PreToolUse`, `PostToolUse`,
`Stop`, `PreCompact`, `SubagentStart`, `WorktreeCreate`,
`TaskCompleted`, `PermissionRequest`, `exit 2`, `permissionDecision`,
`hookSpecificOutput`, `updatedInput`

**Bucket 2 — Rules**: `"incident"`, `"decision"`, `"anti-pattern"`,
`"constraint"`, `"never"`, `"always"`, `"platform"`, `path:rules`

**Bucket 3 — Skills**: `"verification"`, `"gate"`, `"success criteria"`,
`"step 1"`, `"workflow"`, `filename:SKILL.md`, `"user-invocable"`

**Bucket 4 — Agents**: `"allowed-tools"`, `"output-contract"`,
`"subagent"`, `"dispatch"`, `"team"`, `path:agents`

**Bucket 5 — Memory**: `"checkpoint"`, `"resume"`, `"knowledge"`,
`"topic"`, `"pattern"`, `path:memory`, `path:topics`

**Bucket 6 — Config**: `"permissions"`, `"deny"`, `"allow"`,
`filename:settings.json`, `"mcpServers"`, `"env"`

**File anchors**: `path:.claude`, `filename:settings.json`,
`filename:SKILL.md`, `filename:.md+path:rules`, `path:agents`

**Query formula**: Each run, generate 3-4 queries covering AT LEAST
2 different buckets. Rotate which buckets get queried — never run
3 consecutive hook-only queries. Anchor with `path:.claude` to
reduce false positives from non-CC repos.

Examples (each unique, never repeat):
```
"SessionStart" "Stop" filename:settings.json          # full lifecycle
"exit 2" "PreToolUse" path:hooks                      # enforcement hooks
"PreCompact" "SubagentStart" filename:settings.json   # advanced events
"deny" "allow" filename:settings.json path:.claude    # permission models
"incident" "verified" path:rules                      # evidence-based rules
"hookSpecificOutput" filename:.py path:hooks          # structured hook output
```

**Why this works**: Each combination surfaces a different ~200-repo
slice. With 12 events x 6 locations x 6 signals = 432 possible
combinations, the addressable population is effectively unlimited.

#### Supplementary: Exa neural search

GitHub code search finds exact string matches. Exa finds CONCEPTS.
Run one Exa query per run alongside GitHub:
```
exa get_code_context_exa "claude code enforcement hooks security"
exa web_search_exa "claude code personal config hooks governance"
```

#### How each run works

1. **Generate 2-3 new queries** from the category combinations above.
   Never repeat an exact query from any previous run.
2. **Fetch page 1** from each generated query (Python script).
3. **Dedup** against the ledger.
4. **Classify repo type** (see Repo Type Classifier below). Auto-SKIP
   frameworks, aggregators, templates, and tutorials.
5. **Content signal screen** the remaining candidates (see below).
6. **Log the queries used** in the Run Log (for non-repetition).

### Session circuit breaker

After 2 consecutive null-result runs **using the same discovery method**,
signal: "Discovery method X saturated this session. Remaining leads: [list]."

**Resets on**: methodology version change (new query categories),
new discovery method (dynamic queries after static exhaustion), or
new secondary source (author graph, fork graph). A null from static
queries does not count against dynamic queries.

Do NOT refuse to run — the skill always executes when invoked. But
proactively signal diminishing returns. The user decides whether to
continue.
### Repo Type Classifier (auto-SKIP at triage)

Classify each repo BEFORE depth screening. The following types have
**0% hit rate across 15+ deep assessments** and should be auto-SKIPped:

| Type | Signals | Historical hit rate | Action |
|------|---------|-------------------|--------|
| **Personal config** | Low stars, `.claude/` at root, settings.json with hooks, no npm/build | **High** (Turbo 37★, night-market 234★) | **Prioritize for ASSESS** |
| **Governance-focused** | rules/, quality gates, enforcement hooks, incident citations | **High** | **Prioritize for ASSESS** |
| **Framework/product** | npm package.json at root, own CLI tooling, README says "install", replaces CC workflows, has build system | **0%** (5/5 SKIP: babysitter, oh-my-claudecode, oh-my-openagent, gstack, pilot-shell) | **Auto-SKIP** |
| **Aggregator/listing** | "awesome-*", "curated list", 100+ skills with no hooks, skill collection | **0%** (4/4 SKIP: alirezarezvani, daymade, sickn33, VoltAgent) | **Auto-SKIP** |
| **Template/starter** | "template", "starter-kit", "boilerplate", generic project scaffold | **0%** (3/3 SKIP: stableversionapps, ecodelearn, FirasLatrech) | **Auto-SKIP** |
| **Tutorial/guide** | "mastery", "patterns", "guide", docs-heavy, README is the content | **0%** (3/3 SKIP: TheDecipherist, jawhnycooke, disler) | **Auto-SKIP** |
| **Platform wrapper** | "Don't learn X, use Y instead", replaces CC interface, npm global install | **0%** (2/2 SKIP: oh-my-claudecode, oh-my-openagent) | **Auto-SKIP** |

**Ambiguous cases**: If a repo has signals of BOTH personal config AND
framework (e.g., has npm but also has battle-tested hooks), triage
normally — don't auto-SKIP.

Update this table in the Run Log when a new type is identified or a
0% type produces a finding.

### Random sampling from topic populations

Structural queries are biased — GitHub ranks results by an opaque
relevance score and caps at ~200. Random sampling from the full topic
population finds repos that queries never surface.

**Method**: GitHub search API returns max 1000 results (10 pages of
100) regardless of `total_count`. To sample different slices of the
13K+ population, vary the query parameters:

```bash
# 6 different orderings give 6 × 10 = 60 distinct views
# Pick one ordering per run, then a random page 1-10
SORT=("stars" "updated" "created" "" "stars" "updated" "created" "")
ORDER=("desc" "desc" "desc" "desc" "asc" "asc" "asc" "asc")
idx=$((RANDOM % 8))
page=$((RANDOM % 10 + 1))
gh api "/search/repositories?q=topic:claude-code&sort=${SORT[$idx]}&order=${ORDER[$idx]}&per_page=100&page=$page"
```

**Prefer `sort=created`** — gives chronological slices less correlated
with marketing effort than star-sorting. Star-sorted samples (runs 7-8)
hit predictable bands: high=marketing, mid=products, low=noise.

**Vary the topic per run**: Rotate across `topic:claude-code`,
`topic:claude-skills`, `topic:claude-code-skills`, `topic:claude-hooks`,
`topic:claude-code-plugin` to cover different self-categorization choices.

**Why both random + structural**: Structural queries find 0-star
governance repos (BrianMills, robdtaylor) that random sampling would
take ~140 runs to hit. Random sampling covers repos without standard
structural markers. Neither alone is sufficient.

### Secondary: Supplementary sources

Run ONE of these per run alongside random sampling + structural queries:

| Source | When | Queries |
|--------|------|---------|
| **GitHub recently updated** | Every run | `gh api /search/repositories?q=claude+code+pushed:>{7-days-ago}&sort=updated&per_page=50` |
| **GitHub topics browse** | Every run | Tavily extract on `github.com/topics/claude-code` (GitHub's own curated/ranked view) |
| **Community threads** | **MANDATORY every 3rd run** (never defer) | `tavily_search` for `reddit ClaudeCode "my config" OR "my setup" OR "my hooks" 2026` — extract all GitHub URLs. Highest-signal source for personal configs. Runs 1-8 all deferred it. |
| **Author graph** | When ledger has 3+ ADOPTED | For each ADOPTED repo author: `gh api users/{author}/repos` |
| **Fork graph** | When ledger has 3+ ADOPTED | For each ADOPTED repo: `gh api repos/{owner}/{repo}/forks` |

Secondary queries use `sort=updated` (not `sort=stars`). High stars
inversely correlate with transfer value — the only 2 repos that produced
findings had 37★ and 234★, while 5 repos with 15K-117K★ were all SKIP.
No star filtering — repos of any star count are candidates.

### Query Lifecycle

Queries are GENERATED per run, not static. There is no "exhaustion"
in the traditional sense — the combinatorial space of Category A×B×C×D
provides thousands of unique queries.

**Temporal refresh**: GitHub indexes new repos daily. A query that
returned 50 results today may return 60 in two weeks. Queries are
not "exhausted" — they're "sampled." Re-running the same category
combination after 30 days is valid.

**Cross-platform** (every 5th run): `tavily_search` for
`"claude code" config site:gitlab.com`. Low volume but different
population (privacy-conscious devs).

**Retirement signal**: When 5 consecutive runs across 2+ sessions
produce 0 findings AND the SKIP regression test passes, the discovery
phase is mature. Shift to deterministic regression and regret checks only.

### Content Signal Screen (two-phase)

The old screen checked quantity (3+ skills OR 2+ hooks). This produced
a 6% hit rate — repos with hundreds of template files passed but had
no transferable value. The new screen checks operational quality in
two phases to balance thoroughness with API budget.

#### Phase 1: Fast tree check (1 API call per repo)

Run `gh api repos/{owner}/{repo}/git/trees/HEAD?recursive=1` and check
for the PRESENCE of these paths across ALL buckets:

| Bucket | What to check | Score |
|--------|--------------|-------|
| Hooks | `hooks/` with `.py`, `.sh`, or `.ts` files | +1 |
| Rules | `rules/` directory with `.md` files | +1 |
| Config | `settings.json` in `.claude/` or root | +1 |
| Skills | 5+ `SKILL.md` files with distinctive names (not just "commit", "format") | +1 |
| Agents | `agents/` directory with `.md` files | +1 |
| Memory | `memory/`, `topics/`, or knowledge-base structure | +1 |

**Depth flag**: After checking for file presence, verify scored files
contain actual logic, not stubs. For each bucket that scored 1+, check
if at least one file in that bucket is >10 lines AND contains logic
beyond echo/placeholder/TODO/stub content. If ALL files in a bucket
are stubs (echo-only commands, placeholder text, TODO markers, or <10
lines with no operational logic), reset that bucket's score to 0. This
prevents repos like hatch3r (echo placeholders in all hooks) from
inflating Phase 1 scores. (2026-04-05, scout session observation.)

**Score**: 1+ across ANY bucket → advance to Phase 2. Score 0 → SKIP.

**Why 1+, not 2+**: Runs 7-8 showed score-2+ filtered specialized repos
(Turbo: skills-only, instar: hooks+skills, robdtaylor: hooks-only).
Phase 2 reads are cheap — Phase 1 should be permissive.

**Screen ALL repos from the page**, not a hand-picked subset. Phase 1
is one API call per repo (~300ms). Do NOT pre-filter by name — that
reintroduces the bias the methodology eliminates. (Runs 7-8 screened
only 8/200 repos, missing 96% of the population.)

#### Phase 2: Bucket-routed content reads (2-3 API calls per candidate)

For repos that passed Phase 1, read 1-2 files from the **highest-scoring
bucket** — not always settings.json + hooks. Route by what scored highest
in Phase 1:

| Highest bucket | What to read | Strong signal |
|---------------|-------------|---------------|
| **Hooks** | settings.json + 1 hook file | Hook has exit codes, JSON stdin handling, error handling |
| **Rules** | 1 rule file | Incident citations, specific constraints, anti-patterns |
| **Skills** | 1 distinctive SKILL.md (not "commit" or "format") | Methodology with verification gates, structured steps, success criteria |
| **Agents** | 1 agent .md | Tool restrictions, output contracts, scope enforcement |
| **Config** | settings.json | Env vars, permissions model, hook registrations |
| **Memory** | 1 memory/topic file | Knowledge organization, retrieval patterns |

If multiple buckets tie, read from the LEAST hook-like bucket first.
The hook bias (runs 1-17) caused systematic under-evaluation of skills,
rules, and memory patterns. Turbo (skills-only), vibeeval (skills with
0 hooks), and night-market (rules + quality gates) all produced findings
from non-hook buckets.

**Phase 2 scoring**: If the read file shows operational depth (not stubs,
templates, or generic content) → full triage candidate.

**Anti-triage-as-assessment bias** (run 20 lesson): Phase 2 reads 1 file.
If that file is generic (role template, project-specific rule, framework
docs), DO NOT SKIP the entire repo based on one file. Read a second file
from a DIFFERENT bucket before deciding ASSESS vs SKIP. Three UPGRADE
findings (IDS Protocol, Batch Safety, meta-claudemd) were hidden behind
triage-level reads that happened to hit generic files first. The per-bucket
checklist (Step 3.5) catches this for ASSESS repos — this rule catches it
at triage, before the ASSESS/SKIP decision. (2026-03-31, runs 19-21.)

No star count filter. No recency filter. No domain filter.

### Operational Validation

Synthetic tests (unit tests, pattern matching) are necessary but NOT
sufficient for hook implementations. Before marking a hook as complete:

1. **Stop hooks**: Feed a real session transcript (or recent `.jsonl`
   segment) through the hook: `cat <transcript> | python hook.py`
2. **PreToolUse hooks**: Construct a real `tool_input` JSON from a
   recent session and pipe it to the hook
3. **PostToolUse hooks**: Same — real tool output JSON, not fabricated

If no real artifact is available, document: "Operational validation
blocked — no real artifact." Do not deploy the hook until replay, regression,
mutation, and smoke qualification completes against a representative artifact.

Dedup against `~/.claude/assessed-repos.md`. Skip already-assessed repos
unless entry is >90 days old AND repo has new commits since assessment.

### Architecture-triggered re-scan (every 5th run)

Cross-reference `[skip]` entries against recent architecture changes.
Check recent `/distill` entries, new rules, new skills, and new hooks.
If a SKIP was rejected because "no friction exists" but friction has
since been documented, upgrade to triage candidate. Example: if Agent
Teams are adopted, CAS and oh-my-claudecode team-orchestration patterns
become relevant.

**No BOOKMARK verdict.** If it's good enough to bookmark, assess it now.
Deferred decisions accumulate without a mechanism to revisit. (2026-03-30)

### Qualification regression check (every run)

Before discovering new repos, also check `[qualified]` entries from the
previous run's implementations:

1. Search recent `/distill` and `/retro` entries for problems caused
   by the qualified implementation (hook latency, false positives, conflicts)
2. If problems found: flag for revert and warn the user
3. Do not promote based on elapsed sessions. Record direct qualification
   evidence; `/evaluate-repos` owns any later `[adopted]` verdict.

### Log the run

Append to the `## Run Log` section of the ledger:

```markdown
### Run YYYY-MM-DD
- Pages: claude-code=3, claude-skills=2, agent-skills=2, claude=3
- Supplementary: GitHub trending
- Raw results: 312 (after cross-topic dedup: 198)
- After content screen: 14 with skill/hook content
- After ledger dedup: 8 new
- Triage: 3 INVENTORY, 5 SKIP
```

The page numbers are the KEY state — they tell the next run where to start.
The next run reads this log and fetches page 4 of claude-code, page 3 of
claude-skills, etc.

## Triage (sequential, 2-3 min per repo)

For each candidate that passed Phase 1, read ONE file from the
highest-scoring bucket to confirm quality:

| Highest-scoring bucket | What to read |
|----------------------|--------------|
| Hooks | settings.json (hook registrations) + 1 hook file |
| Rules | 1 rule file — look for incident citations, specific constraints |
| Skills | 1 distinctive SKILL.md — look for methodology, verification gates |
| Agents | 1 agent .md — look for tool restrictions, output contracts |
| Config | settings.json — look for env vars, permissions model |

Skip the README (marketing, not signal). Read 1-2 files max — triage
is fast, not thorough. Save thorough reading for deep assessment.

5. Classify:

| Verdict | Criteria |
|---------|----------|
| **INVENTORY** | Operational depth in ANY bucket: hooks with enforcement logic, rules citing incidents, skills with structured methodology/verification gates, agents with tool restrictions, or memory/knowledge patterns not obviously covered by existing architecture |
| **SKIP** | Template/stub config, auto-SKIP repo type (see classifier), or no operational depth signals |

**No BOOKMARK verdict.** If it's good enough to bookmark, it's good enough
to inventory now. Deferred decisions accumulate without a mechanism to revisit.
(Policy change 2026-03-30.)

**No domain filtering.** Cross-domain transfer is the highest-value
pattern. A solo-dev QA pipeline (Turbo) produced 8 improvements to a
security architecture.

6. Update ledger using this skill's actual verdict vocabulary (see
   SKILL.md's "Ledger verdict vocabulary" table and the `Ledger Schema`
   section below): `inventoried` for repos inventoried this run, `queued`
   for score 4+ repos deferred to a future run, or `low-signal` for SKIP.
   Do not write ad-hoc bracket tags like `[assess]` or `[discovered]` —
   they are not in the audit regex (`test-gather-repos.py --audit`) and
   will not be parsed.

## Deep Assessment (OUT OF SCOPE — see `/evaluate-repos`)

**This section documents `/evaluate-repos` workflow, not `/gather-repos`.** Gather-repos discovers and inventories repos. Evaluation, quality ratings, and SKIP/UPGRADE verdicts are `/evaluate-repos` responsibilities.

For reference: `/evaluate-repos` runs deep assessment on inventoried repos
and writes its own verdicts (`adopted`/`upgraded`/`skip`/`bookmark`/`forked`
— see "Ledger Schema" below), never `[assess]` — that tag is not in the
audit regex and gather-repos never writes it either. Apply **diminishing returns check**:
after each deep assessment, check if the last 3 consecutive assessments
were all SKIP. If yes, stop — the remaining candidates are likely the
same type. Resume in the next run. This is adaptive: a run with
high-quality candidates may assess 5+, while a run hitting template
repos stops at 3.

### Subagent scope rule (HARD CONSTRAINT)

**Subagents inventory the external repo only. The main session does all
gap analysis and quality comparison against our architecture.**

Root cause: subagents can read external repos via GitHub API but cannot
read our local files (`~/.claude/hooks/`, `~/.claude/rules/`). When given
a text baseline ("we have 38 hooks including X, Y, Z"), the subagent
compares against the incomplete list and presents false claims about gaps.
This happened in run 16 — subagent claimed 3 gaps that were all false
(teammate-idle.py, skill-routing-hint.py, bash-error-classifier.py existed
but weren't in the baseline text). Same class as the claude-hud audit
incident (2026-03-22).

**Subagent prompt should request** (ALL scored buckets, not just hooks):
- Read all hook files, report what each does (1-2 sentences per hook)
- Read all rule files, report key constraints
- Read settings.json, report hook registrations and permissions
- Read 2-3 most distinctive skills (pick by name — skip "commit", "format", "review"), report methodology steps, verification gates, success criteria
- Read 1-2 agent definitions, report tool restrictions and output contracts
- Read memory/knowledge structure, report organization pattern

**Equal depth per bucket.** The prompt must request the same level of
detail for skills as it does for hooks. "Read 2-3 distinctive skills,
report methodology" is the minimum — not an optional bullet that gets
dropped when the hook inventory is long.

**Subagent prompt should NOT request**:
- Gap analysis ("what do they have that we don't")
- Quality ratings (1-5 scale requires reading our files)
- Verdicts (UPGRADE/SKIP/etc)
- Any claim about "our architecture lacks X"

The main session receives the inventory, reads our actual hook/rule files,
and makes the comparison. (Policy: 2026-03-30, user directive.)

### Step 1: Clone and inventory

```bash
cd /tmp && git clone --depth 1 <repo-url> assessment-target
find /tmp/assessment-target -name "SKILL.md" -o -name "*.py" -path "*/hooks/*" | sort
```

### Step 2: Assess by bucket (MANDATORY per-bucket reads)

Assess the repo against ALL 6 architectural buckets. **Each bucket
that scored 1+ in Phase 1 MUST have at least 1 file read.** Do not
skip buckets — the hook-focused bias across 17 runs caused systematic
under-evaluation of skills, rules, and memory patterns.

**Before presenting findings, verify this checklist:**

| Bucket | Phase 1 score | Files read | Findings |
|--------|--------------|------------|----------|
| Hooks | (fill) | (list files read) | (fill) |
| Rules | (fill) | (list files read) | (fill) |
| Skills | (fill) | (list files read) | (fill) |
| Agents | (fill) | (list files read) | (fill) |
| Memory | (fill) | (list files read) | (fill) |
| Config | (fill) | (list files read) | (fill) |

Any row with Phase 1 score > 0 and "Files read" = 0 means the
assessment is incomplete. Go back and read a file from that bucket.

**Historical examples of findings from non-hook buckets:**
- Turbo (2026-03-29): skills-only repo → 8 adoptions (threat-model,
  Devil's Advocate, skill-first routing, etc.)
- vibeeval (2026-03-30): 1 hook, 234 skills → factcheck-guard adopted
  from the SKILLS bucket, not the hooks bucket
- night-market (2026-03-29): rules + quality gates → read budgets and
  output contracts adopted from the RULES bucket

#### Bucket 1: Skills (workflow methodology)

Read the most distinctive SKILL.md files (not generic "commit" or
"format" — pick the most original names). **Read the METHODOLOGY
(phases, steps, gates), not just the description preamble.** A skill's
value is in HOW it does the work, not WHAT it does.

For each skill, extract:
1. **What problem it solves** (1 sentence)
2. **How it solves it** (list the methodology steps, gates, modes)
3. **What structural features it has** that our equivalent may lack
   (intermediate outputs, fallback modes, error escalation, composition
   interfaces, interactive vs autonomous modes)

Do NOT label-match and SKIP. "Chronicle = session journaling, we have
distill + capture → SKIP" is existence checking. Instead: "Chronicle
has a `pending` mode tracking open threads across sessions — does our
/resume track MULTIPLE open threads? Chronicle has `curate` for
interactive memory organization — does our /garden do this for session
memory (not just knowledge base)?" Evaluate the APPROACH delta.

**The anti-pattern this prevents** (runs 19-22): reading 40 lines of
a 300-line skill, matching the description to an existing skill name,
and calling it "quality 4 → SKIP" without reading the methodology.
4 UPGRADE findings were initially SKIPped this way. The user had to
intervene twice ("You didn't like any of these?", "Are you evaluating
skills for adoption?") to force proper evaluation.

**Our baseline**: 89 skills across security, planning, code quality,
intel gathering, session lifecycle, shipping, debugging, domain ops.
(Refresh this count when the audit reproducer fires —
`ls /home/user/claude-config/skills/*/SKILL.md | wc -l`.)

#### Bucket 2: Hooks (enforcement and automation)

Read settings.json hook registrations + the most distinctive hook
files. Look for:
- **Enforcement patterns**: PreToolUse hooks that block dangerous
  operations (our bash-security-guard, mcp-operation-gate)
- **Quality automation**: PostToolUse hooks that validate or fix
  output (our post-write-edit encoding/compile/secrets check)
- **Lifecycle hooks**: bounded SessionStart/SessionEnd/Stop hooks that
  preserve only the state required at that event (our minimal session-start,
  session-end receipt, and promise-checker); compare richer maintenance
  workflows separately rather than assuming lifecycle automation is desirable
- **Novel gating**: hooks on AskUserQuestion, MCP tools, or
  tool combinations we don't gate

**Our baseline**: 135 hook files including bash-security-guard (13 checks),
mcp-operation-gate, file-scope-guard, auto-checkpoint. (Counts every
`.py`/`.sh` under `hooks/`, including test harnesses; refresh when the
audit reproducer fires —
`find /home/user/claude-config/hooks -type f \( -name '*.py' -o -name '*.sh' \) | wc -l`.)

#### Bucket 3: Rules (governance and constraints)

Read rule `.md` files. Look for:
- **Incident-cited rules**: rules that reference specific failures
  (our strongest pattern — every rule cites its origin incident)
- **Methodology rules**: decision frameworks, anti-patterns, workflow
  constraints (our compare-by-need, diagnose-before-fix, etc.)
- **Platform constraints**: environment-specific gotchas, tool quirks
- **Novel constraints**: rules addressing problems we haven't
  codified (e.g., read budgets before we added them)

**Our baseline**: 31 rules. Strongest: platform-constraints (150+
lines), methodology rules, git-hygiene. (Refresh when the audit
reproducer fires — `ls /home/user/claude-config/rules/*.md | wc -l`.)

#### Bucket 4: Agents (dispatch and specialization)

Read agent `.md` definitions. Look for:
- **Tool restrictions**: agents with explicit allowed/disallowed
  tools (our exploitability-verifier is read-only, poc-builder
  gets Bash)
- **Output contracts**: agents with structured output requirements
- **Dispatch patterns**: team compositions, model routing, scope
  enforcement
- **Novel agent designs**: agents for tasks we don't delegate

**Our baseline**: 8 agent files (1 generic worker, security and
data-flow specialists, 1 semgrep scanner, 1 api-ingest worker, plus
README and TEMPLATE scaffolding). (Refresh when the audit reproducer
fires — `ls /home/user/claude-config/agents/*.md | wc -l`.)

#### Bucket 5: Memory and knowledge

Look for:
- **Knowledge organization**: how the repo structures persistent
  knowledge (topic files, pattern files, knowledge bases)
- **Session continuity**: checkpoints, handoff files, continuity
  ledgers, memory compaction strategies
- **Retrieval patterns**: how knowledge is loaded into context
  (topic loading, semantic search, embedding-based recall)

**Our baseline**: 3-tier memory (project memory always loaded →
23 agent topic files on demand → knowledge base via memory-search
MCP with semantic embeddings).

#### Bucket 6: Configuration and integration

Look for:
- **Settings patterns**: env vars, permissions, hook registration
  patterns, MCP server config
- **CI/CD integration**: GitHub Actions, validation workflows,
  consistency checks
- **Cross-tool coordination**: how different components (hooks,
  skills, agents) reference and invoke each other

**Our baseline**: git-tracked settings.json, validate-consistency.py
CI check, pending-config.json for deferred hook registration.

### Step 3: Map findings against architecture (approach-level, not label-level)

For each pattern found in ANY bucket, compare at the APPROACH level:

| Bucket | Their approach | Our approach | Approach delta |
|--------|---------------|-------------|----------------|
| (fill) | (HOW they solve it — methodology, steps, modes) | (HOW we solve it — read our actual file) | (what their approach does that ours doesn't) |

**The "Approach delta" column is the key output.** If it's empty
("same approach"), that's a genuine SKIP. If it contains specific
capabilities ("tracks multiple open threads", "interactive curation
mode", "staged review pipeline"), those are evaluation candidates
for Step 4.

**Read the actual implementation files** — not just ARCHITECTURE.md
summaries. Apply the claim verification protocol: claims about "what
we have" must be [VERIFIED] by reading the file.

**Label matching is NOT approach comparison.** These are different:
- Label: "They have session journaling. We have /distill + /capture." → SKIP
- Approach: "Their chronicle has 8 modes (capture, curate, insights,
  pending, search, consolidate, publish, summarize). Our /distill
  captures errors, /capture writes strategic insights, /recall searches,
  /resume loads checkpoints. Approach delta: pending thread tracking
  across sessions, interactive curation, usage analytics." → Evaluate

(Added 2026-03-31 after runs 19-22: 4 findings initially SKIPped via
label matching, recovered only after user intervention.)

### Step 4: Evaluate each pattern (quality comparison, not existence check)

For each capability found in the external repo:

**4.1: Identify our equivalent.** What addresses the same concern, even
if differently? Read the SPECIFIC SECTION of our implementation, not
just ARCHITECTURE.md summaries.

**4.2: Rate coverage quality (1-5 scale).**

| Rating | Meaning | Example |
|--------|---------|---------|
| **1 — No coverage** | Nothing addresses this problem space | Threat modeling before /threat-model existed |
| **2 — Minimal** | Something exists but it's vague or generic | "Run verification commands" vs 10 explicit automated gates |
| **3 — Adequate** | Functional but less thorough/structured than theirs | Ad-hoc checkpoint JSON vs defined YAML handoff schema |
| **4 — Strong** | Comparable quality, different mechanism | /fp-check multi-phase verification vs tournament adversary |
| **5 — Superior** | Our approach is more thorough than theirs | /semgrep + /codeql + /fp-check vs grep-based security audit |

**4.3: Dynamic calibration check.** "Would this methodology have caught
the MOST RECENT adoption?" After each run, the calibration target updates
to the last repo that produced findings. Currently: athola/claude-night-market
(read budgets + output contracts, adopted 2026-03-29). If the current
finding would have been adopted under the same reasoning as the calibration
target, it should not be rejected by a stricter standard. Update the
calibration target in the Run Log whenever a new adoption occurs.

**4.4: Forward-looking value check.** Don't just ask "has our approach
failed?" Ask "would this improve future outcomes?" A reasonable engineer
adopting this pattern to improve their workflow is valid evidence. The
user's professional judgment about what benefits their work is higher
authority than the absence of a cited incident.

**4.5: Self-adversarial (quality comparison, not existence check).**
Compare HOW WELL our approach covers this, not WHETHER something exists.
If our approach rates 3 (adequate) and theirs rates 5, that's an
UPGRADE candidate even if ours "works."

### Assessment biases (both directions)

| Bias | Direction | Prevention |
|------|-----------|-----------|
| **Feature-absence = gap** | False positive | Check what solves the same PROBLEM, not pattern |
| **Sunk cost of assessment** | False positive | 0 findings is valid |
| **Hypothetical friction** | False positive | "Could help if X" needs at least a forward-looking value argument |
| **SKIP inflation after SKIPs** | False negative | If 100% SKIP across 3+ repos, run the SKIP rate check (Step 4.6) |
| **Existence = equivalence** | False negative | Rate quality 1-5, don't just check if something exists |
| **Incident-only evidence** | False negative | Forward-looking value and professional judgment are valid signals |
| **Cognitive momentum** | False negative | Each repo assessed independently; prior verdicts are not priors |
| **Repo type bias** | Both | Small/unknown repos produce findings; large/popular repos don't. Don't prioritize by stars. |

**4.6: SKIP rate check.** If the current run has produced 100% SKIP
across 3+ repos, pause and ask: "Is the architecture genuinely complete
for these patterns, OR is the methodology suppressing legitimate
findings?" Review all SKIP verdicts from this run. For any finding
rated 3 (adequate) on quality, reconsider as UPGRADE.

### Step 5: Classify findings

| Verdict | Quality rating | Definition | Evidence required |
|---------|---------------|-----------|-------------------|
| **SELECTIVE CLONE** | 1 (no coverage) | Build a native skill — nothing covers this problem space | No equivalent exists after checking all skills, rules, hooks |
| **IMPROVE** | 2 (minimal) | Enhance an existing skill — current approach is demonstrably insufficient | Quality rating 2 + forward-looking value argument |
| **UPGRADE** | 3 (adequate) | Current approach works but theirs is measurably more thorough, structured, or portable | Quality rating 3 + specific quality delta described |
| **SKIP** | 4-5 (strong/superior) | Comparable or better coverage | Quality comparison shows parity or advantage |
| **SKIP** | Any | Wrong domain, adoption cost exceeds value, or architecturally incompatible | Mismatch identified |

**How to present UPGRADE findings**: Describe the specific quality delta.
"Our /verification-before-completion says 'run verification commands.'
Their DoD has 10 explicit automated gates (lint, unit, integration, e2e,
security, performance, docs, pipeline, review, agent). Same concept,
higher specificity." Let the user decide if the quality delta justifies
the adoption cost.

**User override**: The user can override any SKIP with "I want this."
Professional judgment about what benefits their workflow is higher
authority than the methodology's evidence gates. When the user overrides,
log it as `[adopted: user override]` in the ledger.

### Calibration: the two assessment failures

**Failure 1 — false positives (2026-03-29 runs 1-2)**: Four findings
classified IMPROVE collapsed under scrutiny. Root cause: feature-absence
treated as gap, existence check without quality comparison.

**Failure 2 — false negatives (2026-03-29 runs 3-4)**: 10 repos produced
100% SKIP. When the user challenged this, analysis showed the methodology
would have rejected every Turbo adoption that produced the session's
only value. Root cause: incident-only evidence requirement, existence
check instead of quality comparison, SKIP momentum.

Both failures are instructive. The methodology must avoid BOTH inflating
findings (recommending things we don't need) AND suppressing findings
(missing things that would genuinely help). The quality rating scale
and UPGRADE category balance these tensions.

### Step 6: `/evaluate-repos` presents findings and updates the ledger

`/evaluate-repos` produces a summary table:

```
| Finding | Type | Quality | Target | Effort | Delta |
|---------|------|---------|--------|--------|-------|
| [pattern] | SELECTIVE CLONE | 1 | /new-skill | medium | New capability |
| [pattern] | IMPROVE | 2 | /existing-skill | low | Insufficient → functional |
| [pattern] | UPGRADE | 3 | /existing-skill | low | Adequate → thorough |
| [pattern] | SKIP | 4-5 | — | — | Already strong/superior |
```

For UPGRADE findings, `/evaluate-repos` describes the specific quality delta
so the user can judge whether the improvement justifies the cost, presenting
UPGRADE findings separately from IMPROVE — they're "nice to have" not "need
to fix."

If any SELECTIVE CLONE, IMPROVE, or UPGRADE findings exist, `/evaluate-repos`
asks the user whether to act on each one — UPGRADEs are optional quality
improvements the user may approve, defer, or skip individually. This is
`/evaluate-repos`'s decision gate, not gather-repos's; gather-repos never
asks the user to approve implementation.

`/evaluate-repos` updates `~/.claude/assessed-repos.md` with verdict, what
was taken, and PR number.

### Step 7: Clean up

```bash
rm -rf /tmp/assessment-target
```

## Cross-Run Learning

The Run Log should capture patterns about which repo types produce
findings, not just which repos were assessed. After each run, update
the Repo Type Classifier hit rates in the methodology reference AND
in the Run Log.

### What to track per run

- Repos assessed by type (personal config, governance, framework, etc.)
- Hit rate per type (findings / assessments)
- Any new type identified (add to classifier table)
- Calibration target update (if a new adoption occurred)

### Calibration target

The dynamic calibration check (Step 4.3) uses the most recent adoption
as the reference. Update this after each adoption:

**Current calibration target**: athola/claude-night-market (2026-03-29)
- Patterns adopted: read budgets, output contracts
- What made it findable: governance-focused (rules/, quality_gates.json)
- What made it valuable: operational specificity (incident-driven rules,
  config-driven quality gates with per-dimension thresholds)

**Previous calibration target**: tobihagemann/turbo (2026-03-29)
- Patterns adopted: Devil's Advocate, skill-first routing, /threat-model, etc.
- What made it findable: small personal config (37★), deep skills
- What made it valuable: methodology innovations, not feature additions

## Ledger Schema

File: `~/.claude/assessed-repos.md`

All entries use heading style — never a markdown table. The audit regex
in `test-gather-repos.py --audit` anchors on the heading shape.

Two vocabularies write into this ledger:

**Written by `/gather-repos`** (this skill, discovery+inventory only):
```markdown
### [inventoried|queued|auto-skip|dup|low-signal|qualified] owner/repo (YYYY-MM-DD)
- N* | brief one-line content summary
- Found by: (query/source), score N/6
- Per-bucket: (optional structured bullets for inventoried entries)
```

**Written by `/evaluate-repos`** (later pass, advocate/skeptic assessment):
```markdown
### [adopted|upgraded|skip|bookmark|forked] owner/repo (YYYY-MM-DD)
- Stars: N | Skills: N | Type: brief description
- Verdict/Reason: what happened
- Taken: what was selectively cloned, improved, or upgraded (if adopted/upgraded)
- Quality ratings: [pattern: N/5, pattern: N/5] (for non-skip verdicts)
```

`qualified` is written only after direct deterministic qualification.
`/evaluate-repos` may later replace it with an explicit adoption decision.

The audit regex in `test-gather-repos.py --audit` matches BOTH vocabularies.
Keep `SKILL.md` "Ledger verdict vocabulary" table, this section, and the
test's verdict regex in sync.

Re-assessment trigger: >90 days AND new commits since assessment date.
