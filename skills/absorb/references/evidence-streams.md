# Evidence Streams — Phase 2 Detailed Instructions

Read these when executing Phase 2. The three tiers group the evidence streams; the sub-sections below are the actual collection steps.

---

## TIER 1: CODE (Primary Evidence)

### 2a. Source code and coding style (THE MOST IMPORTANT STREAM)

**Read actual source code, not just directory listings.** This is the centerpiece of the
skill. Use `gh api` contents endpoint to read files, or Exa crawling for public repos.

For top 1-2 repos, read **at least 4 source files**. Adapt file selection to the repo's
actual structure — not every repo has a dedicated error module or conventional entry point.

**Required reads (adapt to what exists):**

1. **Manifest** (`Cargo.toml`, `package.json`, `pyproject.toml`, `go.mod`, or equivalent)
   - Dependency count, pinning strategy, dev/prod separation, feature flags, workspace structure

2. **Entry point or orchestration file** — whatever bootstraps the application. May be
   `src/main.rs`, `src/index.ts`, `main.go`, `app.py`, or in monorepos/Terraform repos,
   the top-level module or root config. If unclear, check the manifest's `main`/`bin` field
   or the repo's README for how to run it.
   - Naming conventions, function size/decomposition, import organization, configuration
     approach, initialization patterns

3. **Error handling** — may be a dedicated module (`error.rs`, `errors.ts`, `exceptions.py`)
   or patterns visible in the entry point. If no dedicated error module exists, note that
   as a signal (errors handled inline, or not at all).
   - Error philosophy (typed vs string), granularity, HTTP mapping, unwrap/panic discipline

4. **One domain logic file** (not utils, not config — actual business logic)
   - Type usage, comment density/style, logging/observability, guard clauses vs nesting,
     magic numbers, data transformation patterns (imperative vs functional)

**Optional reads (if budget allows):**

5. **One test file** — testing style, assertion patterns, mock usage, naming conventions
6. **CI configuration** (`.github/workflows/*.yml`) — enforced checks, permissions, security

**For non-standard repo structures** (Terraform modules, monorepos, config-only repos,
hook collections): replace files 2-4 with the 3 highest-signal files for that repo type.
For Terraform: a root module, a variables file, and one resource module. For hook/config
repos: the most complex hook, the settings/config file, and one representative skill/rule.

**Language-specific style signals to look for:**

| Language | Key style signals |
|----------|------------------|
| Rust | `unwrap()` frequency, `?` vs `match`, trait bounds style, lifetime elision, `clippy` config |
| TypeScript | `any` usage, strict mode, branded types, discriminated unions, `as` casting frequency |
| Python | type hints coverage, f-strings vs format(), dataclasses vs dicts, context managers |
| Go | error wrapping style, interface size, package organization, goroutine patterns |
| HCL/Terraform | module composition, variable validation, output organization, state management |

### 2a-b. Architecture patterns (from code structure)
From the files read in 2a, also extract:
- **Module structure** — pipeline, layered, monolith, hexagonal, or flat?
- **Dependency philosophy** — minimal vs batteries-included
- **Performance instrumentation** — timing built in? Metrics collection? Profiling hooks?
- **Security posture** — `.env.example` patterns, secrets handling, CORS config,
  dependency lockfile presence and freshness

### 2a-c. Test behavior
Two sub-dimensions:

**Test-first vs fix-first (bug-fix PRs):** Within PRs that fix bugs, examine commit
ordering. Does a test commit appear before the fix commit? Check 3-5 bug-fix PRs.

**Test file presence ratio (ALL PRs):** Across PRs examined later in 2d, count how many
include changes to test files. Calculate `test_including_prs / total_prs`.

### 2a-d. Refactoring discipline
Search for PRs with "refactor" in the title:
```
gh search prs --author=<username> --owner=<org> "refactor" --limit=10
```
Are refactoring changes isolated PRs or mixed with features? Maps to Janke & Mäder's
"tangling" dimension.

### 2a-e. Module breadth and change spread
From commits and PRs, count unique directories touched. Specialists touch few dirs;
generalists touch many.

---

## TIER 2: AUTOMATION ARTIFACTS (Secondary Evidence)

**Goal:** Extract patterns from how the target structures their automation — skills, hooks,
agents, configuration, and CLAUDE.md. For Claude Code config authors, this tier is often
higher-signal than source code.

### 2i. Skill design patterns
If the target has a `.claude/skills/` directory or equivalent:
- Read 2-3 skill SKILL.md files. Extract: frontmatter usage, trigger design (when to fire
  vs when not to), how they scope `allowed-tools`, whether skills reference each other,
  how they structure multi-step workflows, whether they include examples and success criteria.
- Note skill count and coverage breadth — how many lifecycle events do they automate?
- **Do NOT compare against your skills yet** — that happens in Phase 4 when patterns are
  scoped to specific domains. Comparing here wastes budget reading your own files.

### 2j. Hook architecture
If the target has hooks (`.claude/settings.json`, `.githooks/`, or hook scripts):
- Read the hook implementations. Extract: which lifecycle events they cover (PreToolUse,
  PostToolUse, PostToolUseFailure, Stop, Start, etc.), error handling philosophy
  (fail-open vs fail-closed), whether hooks are blocking or informational, how they
  compose multiple hooks, whether they use `suppressOutput`.

### 2k. Agent/subagent configuration
If the target defines agents (agent markdown files, `AGENTS.md`, Paperclip configs):
- Read agent definitions. Extract: role separation, how they constrain agent scope,
  whether agents have explicit "do NOT" boundaries, reporting hierarchy, how they handle
  agent output verification.

### 2l. CLAUDE.md and settings philosophy
Read the target's `CLAUDE.md` (or equivalent project instructions file):
- How do they balance brevity vs comprehensiveness?
- Do they embed rules inline or route to external files?
- What do they prioritize in their instructions (code quality, speed, safety, style)?
- How do they handle tool permissions and model routing?

### 2m. Prompt engineering in automation
Within skills and agent definitions, examine the actual prompt text:
- How do they constrain output format?
- How do they handle ambiguity or missing information?
- Do they use examples, anti-examples, or decision trees?
- How do they structure multi-step instructions (numbered steps, phases, checklists)?
- **Cite the specific file and quote the specific text.** "Their /review skill uses
  a decision tree for severity classification (SKILL.md lines 45-60)" is a pattern.
  "They seem to write better prompts" is not.

---

## TIER 3: WORKFLOW (Tertiary Evidence)

### 2b. Commit message style
```
gh api 'repos/<owner>/<repo>/commits?per_page=15'
```
Run on the same repos used for Tier 1 code reading. Extract: message format, prefix
conventions, whether they include WHY, issue references, version bump style, cadence
and batching patterns.

### 2c. Code review voice (reviewing others)
Search for PRs the target reviewed:
```
gh search prs --reviewed-by=<username> --owner=<org> --limit=10
```
**Sample 3 PRs first.** For each sampled PR, check BOTH review actions AND inline comments:
```
gh api repos/<owner>/<repo>/pulls/<number>/reviews
gh api repos/<owner>/<repo>/pulls/<number>/comments
```
The reviews endpoint shows approve/reject; the comments endpoint shows line-level
discussion. **Both are required** — approve-only reviews with zero inline comments IS
a pattern worth capturing; but don't assume "no comments" without checking the right
endpoint.

**Expand to 5 PRs only if the initial 3 show interesting signal** (substantive inline
comments, mixed approve/reject, or notably fast/slow turnaround). If all 3 are bare
approvals with no comments, the pattern is established — don't spend 4 more API calls
confirming it.

**Review turnaround time:** For the sampled PRs, compare PR `created_at`
with the first review's `submitted_at`. Fast turnaround (hours) = responsive collaborator.
Multi-day gaps = potential bottleneck. (Haystack engineering metrics research; multiple
SE studies confirm turnaround correlates with team velocity.)

**Participation breadth:** From the `--reviewed-by` results, group by PR author. Does the
target review PRs from many different authors, or only from 1-2 people? Broad review
participation signals team-wide engagement; narrow participation signals siloed
collaboration. (Jo & Kwon, "Impact of Collaboration Patterns," Applied Sciences, 2025.)

**Review reciprocity:** Cross-reference: do the people whose PRs the target reviews
also review the target's PRs? Balanced reciprocity indicates healthy peer collaboration;
one-directional review flow may indicate a hierarchy or gatekeeping pattern.

### 2c-b. Review response behavior (receiving feedback)
The flip side of 2c — how does the target respond when THEIR PRs get reviewed?
Search for PRs by the target that have review comments from others:
```
gh api repos/<owner>/<repo>/pulls/<number>/comments
```
Look for: do they argue or accept? Do they reply "done" with no context, or write
explanatory follow-up commits? Do they force-push over review history, or add clean
fixup commits? Do they thank reviewers or ignore feedback?

This reveals collaboration maturity. Someone who writes "Added test for undefined
input and updated error message. Good catch." after a review comment shows different
engineering culture than someone who replies "fixed" and force-pushes.

### 2d. Issue triage behavior
```
gh api 'repos/<owner>/<repo>/issues/comments?per_page=100'
```
Filter for target's comments. Extract: response time, triage style (diagnostic-first
vs. prescriptive), how they close issues, how they redirect duplicates, comment length.

Also check issue authoring:
```
gh search issues --author=<username> --owner=<org> --limit=10
```
Do they file issues? Use labels? Reference tickets from external trackers? Write detailed
repro steps or terse titles?

### 2e. Deleted and abandoned work (optional — skip if budget tight)
Search for PRs the target opened that were closed WITHOUT merging:
```
gh search prs --author=<username> --owner=<org> --state=closed --limit=10
```
Filter to those where `merged_at` is null. These reveal: what the target tried and
abandoned, what got rejected by reviewers, what they learned from. Closed-without-merge
PRs are higher-signal than merged PRs — they show judgment about when to stop.

Also check for revert patterns: commits containing "revert" in the message, or PRs
where PR N+1 immediately fixes PR N. Clean reverts show engineering maturity; piled
fix-on-fix commits show haste.

### 2f. PR authoring patterns
```
gh search prs --author=<username> --repo=<org>/<repo> --limit=25
```
Search their PRs on **own repos AND org repos** discovered in Phase 1 step 3. For each
org, run `gh search prs --author=<username> --owner=<org> --limit=10`. Extract:
PR size (commits, files changed), iteration speed (created-to-merged time), self-merge
patterns, how many PRs per feature.

**PR description quality (distinct dimension):** Don't just note "has description" vs
"n/a". Evaluate: does the body explain WHAT changed, WHY it changed, and HOW TO TEST?
Does it link to issues? Does it include screenshots for UI changes? Structured sections
(`## What`, `## Why`, `## Testing`) vs free-form prose vs empty body are three different
signals about how the target thinks about communicating intent to reviewers.
(arXiv 2602.14611: "The Value of Effective Pull Request Description" — PR description
quality independently predicts review speed and merge outcomes.)

**Prior merge rate (context-dependent signal):** Calculate:
```
merged_prs / total_closed_prs
```
from `gh search prs --author=<username> --state=closed`. Per E-PRedictor (Science China,
2025), this correlates with contributor quality in multi-reviewer projects. **Caveats:**
This metric is meaningful only in repos with real review gates (required approvals, external
reviewers). In self-merge repos with 0 required approvals (like Example's setup), merge rate
is ~100% for everyone and carries no signal. Also, a developer who wisely closes 30% of their
own bad PRs has a *lower* merge rate than one who forces everything through. Interpret in
context, not as a standalone quality score.

**Test file presence ratio (across ALL PRs, not just bug-fix):** For each PR examined,
note whether test files were changed. Calculate the ratio of test-including PRs to total
PRs. Research shows test-file inclusion strongly predicts merge success (Borle et al.,
PeerJ, 2016; E-PRedictor). This extends the bug-fix test ordering check from 2a-c (which
covers bug-fix PRs only) to all PR types.

**Change spread:** For the PRs examined, note the average number of unique directories
touched per commit. Concentrated changes (1-2 dirs) signal surgical precision; scattered
changes (10+ dirs) signal either broad ownership or shotgun debugging. (Janke & Mäder,
"7 Dimensions of Software Change Patterns," Scientific Reports, 2024.)

**Branch naming:** Extract branch names from merge commit messages (`Merge pull request #N
from org/branch-name`). Note naming conventions — do they use prefixes (`feat/`, `fix/`),
ticket references (`SEC-1234`), or free-form names?

### 2f-b. Documentation contributions
Check whether the target's commits touch non-code files:
- `.md`, `.rst`, `.txt` files (docs)
- `CONTRIBUTING.md`, `README.md`, `CHANGELOG.md` (project documentation)
- Inline code comments added in PRs (visible in diff)

Pure-code contributors vs those who also maintain documentation show different
engineering philosophies. Documentation contributions signal that the target thinks
about future readers, not just current functionality.

### 2g. Cross-repo workflow (enterprise path only)
When the target works across multiple repos in the same org:
```
gh search prs --author=<username> --owner=<org> --sort=created --limit=25
```
Group PRs by date. Look for: same-day PRs across repos (coordinated changes), dependency
ordering (does repo A's PR reference repo B's?), whether cross-cutting changes are atomic
or staged.

### 2h. Supplementary context (ONLY if Phase 1 surfaced it)
If their GitHub profile links a blog, or a PR references a talk — crawl those specific
URLs for philosophy in their own words. Do NOT speculatively search for content that
may not exist. Max 3 Exa crawls.

---

## Evidence limitations (what the skill cannot see)

The skill can only see what's publicly visible (or org-visible for enterprise targets).
It cannot see private repos at prior employers, abandoned unpushed branches, pair
programming contributions, verbal design discussions, or production outcomes. The profile
is a sample of artifacts, not a complete picture. Additionally, AI-assisted code is
increasingly prevalent — patterns extracted from recent commits may reflect Copilot/Claude
output rather than the developer's natural style. Watch for: uniform formatting across all
files, suspiciously comprehensive doc comments, and style inconsistency between older and
newer commits.

## Temporal weighting (full guidance)

Prefer recent evidence. When reading source code, choose repos with pushes in the last
6 months over stale repos. When examining PRs and commits, weight the last 12 months more
heavily than older activity. A developer's style 3 years ago may be radically different
from today — note the date range of evidence in Phase 3 and flag patterns sourced
exclusively from old repos (>18 months since last push).

## Why the tier split exists (calibration history)

The Boris absorb session (2026-04-04) proved code-first ordering: source code reading
produced every recommendation that shipped. The 2026-04-05 batch run (9 developers)
revealed a blind spot: Tier 2 automation artifacts (skills, hooks, agents) were observed
but compared against rules instead of actual skill/hook implementations — producing zero
skill improvement recommendations across 113 patterns. Tier 2 was added to fix this, and
the Phase 2 budget was raised from 25 gh + 5 Exa to 30 gh + 7 Exa to accommodate the
Tier 2 automation artifact reads.
