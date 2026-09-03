---

name: gather-claude
description: "Sync the architecture with what Anthropic shipped — new Claude Code features, fixes, and deprecations."
when_to_use: Use when wanting to sync the architecture with what Anthropic has shipped, or when asked a question about whether/what Claude Code or gather-claude supports, covers, or pulls from. Searches official sources (GitHub issues/PRs, CHANGELOG, docs, blog) for new features, fixed bugs, and deprecations, then audits existing workarounds for staleness. Trigger phrases - "gather-claude", "what's new in Claude Code", "sync with upstream", "check for updates", "does gather-claude", "does claude code", "does anthropic", "what does gather-claude cover", "what sources does", "is X in the gather sources". Do NOT use for community patterns (use gather-intel), academic research (use gather-research), or general topics (use deep-dive).
argument-hint: "[optional: 'full', 'since:YYYY-MM-DD', or focus area like 'hooks', 'MCP', 'agents']"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires gh CLI and web-search MCP (Tavily or Firecrawl) for upstream Claude Code monitoring.
  requires:
    - mcp: firecrawl
    - mcp: tavily
    - cli: gh
allowed-tools: Bash Read Write Edit Glob Grep mcp__exa__web_search_exa mcp__tavily__tavily_map mcp__tavily__tavily_extract mcp__tavily__tavily_search mcp__firecrawl__firecrawl_scrape AskUserQuestion
---

## gather-claude

# Gather Anthropic Intelligence

Three phases: **Audit existing** (backward-looking) -> **Gather new** (forward-looking) -> **Verify and apply**. This skill runs in the main thread with user approval before writing findings.

> **Dual-skill coordination**: If `gather-intel` or `gather-research` ran earlier in this session, consume their reports for cross-reference. Never modify their reports. See `skills/gather-intel/references/gather-coordination.md` for full coordination protocol.

> **Focus area**: If the user provided an argument (e.g., `/gather-claude hooks`), narrow ALL queries to that focus area.

---

## Scope guard

Before proceeding, verify the request is in-scope. If the user is asking about:
- **Community patterns** from Reddit, HN, GitHub config repos → redirect to `/gather-intel`
- **Research frontier** (arXiv papers, NeurIPS proceedings, lab blogs) → redirect to `/gather-research`
- **General topic research** unrelated to Claude Code → redirect to `/deep-dive`

If out-of-scope, tell the user which skill to use instead, then stop.

---

# Phase A: Audit Existing Architecture

## Step 0: Preconditions and Time Window

**gh CLI presence check (mandatory):** every GitHub track step (1b, 3, 3b,
4, 4b, 6, 7, 7b) shells out to `gh`. Verify the binary is installed before doing
anything else:

```bash
command -v gh >/dev/null 2>&1 || { echo "gh CLI required; install via brew install gh (macOS), apt install gh (Debian/Ubuntu), or winget install GitHub.cli (Windows)"; exit 2; }
```

If `gh` is missing, abort the skill with the exit-2 message — do NOT fall back to
"Web Track only" (the architecture audit and CHANGELOG parse both require `gh api`
calls). Rationale + the auditing note for verification environments:
[references/preconditions-and-degradation.md](references/preconditions-and-degradation.md).

## Step 0b: Write-Target Preflight (MANDATORY — run BEFORE gathering)

This skill's deliverable is an APPLIED edit (Step 12b/15), and its write targets
are `~/.claude` (claude-config) and the knowledge-base repo. Both are live git
checkouts that concurrent sessions also write. Measure their state FIRST, because
it determines which verdicts are even reachable this run:

```bash
for repo in "$HOME/.claude" "$HOME/Documents/knowledge-base"; do
  echo "=== $repo ==="
  git -C "$repo" status --short | head -30
  git -C "$repo" rev-parse --abbrev-ref HEAD
  git -C "$repo" fetch -q origin
  echo "behind:"; git -C "$repo" log --oneline HEAD..origin/main | head -5
  echo "unpushed (git cherry, + = NOT upstream):"
  git -C "$repo" cherry origin/main HEAD | head -10
done
```

**Record the result in the metadata header** and let it gate Step 12b:

| Observed state | Consequence for this run's verdicts |
|---|---|
| Clean, in sync | ADOPT may edit in place; Step 15 persistence check still required |
| Dirty (unrelated files modified) | Do NOT edit in place — a concurrent session's whole-file re-serialization drops keys it does not model. Apply in a **worktree** and leave uncommitted, or DEFER with trigger `git status --short` empty |
| Unpushed commits (`git cherry` shows `+`) | **`origin/main` is NOT the right worktree base.** Diff the files you intend to edit between `HEAD` and `origin/main` first; a base chosen by habit silently reverts unmerged work |

```bash
# Before cutting a worktree, prove which side holds the newer content:
git -C "$HOME/.claude" diff --stat origin/main HEAD -- skills/<target>/
```

GUARD pattern="the tree is dirty but my edit is small / touches different files":
  Still use a worktree. The 2026-08-08 edits were reverted by a concurrent
  session's re-serialization of `settings.json` — a file the other session was
  editing for unrelated reasons. Measured again 2026-08-11, 08-12 and 08-21:
  three consecutive runs found claude-config dirty AND diverged, and each one
  rediscovered it at Step 15 instead of Step 0. That late discovery is the main
  reason the adoption metric sits near half.

**Deployed-skill freshness (run in the same preflight):** the scripts this skill
executes live in the checkout you just measured. If `~/.claude` is behind
`origin/main`, the DEPLOYED skill may be older than the skill's own upstream —
and the working tree can hold a THIRD, stale intermediate (measured 2026-08-22:
HEAD behind, working tree diverged from both; the run had to extract and execute
origin/main script content from /tmp). Check and prefer origin content when behind:

```bash
git -C ~/.claude diff --stat origin/main HEAD -- skills/gather-claude/ | tail -3
# any output -> extract before running:
mkdir -p /tmp/claude/gc-skill/scripts && for f in fetch_window.py reconcile_watching.py report_lifecycle.py parse_watching.py; do
  git -C ~/.claude show "origin/main:skills/gather-claude/scripts/$f" > "/tmp/claude/gc-skill/scripts/$f"
done
```

**Time window:**

1. **No argument**: Last run date from report metadata. No prior run = 30 days.
2. **`full`**: No time filter.
3. **`since:YYYY-MM-DD`**: That date.
4. **Focus area** (e.g., `hooks`): Since-last-run, narrowed to topic.

## Step 1: Load Baseline

Run `claude --version` via Bash. Read in parallel:
1. `~/.claude/ARCHITECTURE.md` (current config) + `~/.claude/docs/PLATFORM_NOTES.md` (version changelog — platform findings APPEND here per the 2026-06-11 B11/F5 split)
2. `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/MEMORY.md`
3. `~/.claude/projects/$CLAUDE_PROJECT_ID/CLAUDE.md`
4. Key rules: `platform-constraints.md`, `subagent-verification.md`
5. Existing report: `knowledge-base/research/claude-code-anthropic-intelligence.md`
6. Community/research reports (for cross-reference only)
7. **Vendor-report Handoffs (closes the dead-drop):** the `## Handoffs` section
   of each vendor report — `knowledge-base/research/{openai,gemini,grok}-intelligence.md`
   (absent until `/gather-vendor` has run for that vendor — skip silently if so).
   Act on rows targeting gather-claude: a `[cross-vendor]` model-EOL (e.g. a
   Vertex partner-model or Bedrock availability date that cross-checks an
   Anthropic retirement) becomes a Watching row or a finding here. Schema +
   routing: `../_shared/gather-conventions.md` §5.

**Missing baseline files:** items 1, 2, 3, or 5 may be absent on fresh deployments —
log the missing path in the Sources Log (`baseline: <path> absent`) and continue with
the remaining reads; do NOT abort. Only item 4 (rules) is required. Full handling:
[references/preconditions-and-degradation.md](references/preconditions-and-degradation.md).

If `$CLAUDE_PROJECT_ID` isn't set (headless / worktree sessions), resolve
it via the recipe in `../_shared/project-dir.md` (relative to this
skill's directory; the file lives at `<claude-config-repo>/skills/_shared/project-dir.md`
in the source tree and at `~/.agents/skills/_shared/project-dir.md` when deployed
to Codex) before the reads in items 2–3.

## Step 1b: Check Watching Table (incremental runs only)

If an existing report has a Watching table, check each tracked issue:

```bash
python3 scripts/reconcile_watching.py --since <last-run-date> <report-path>
```

Reconciles the ENTIRE Watching set in one pass via a **GraphQL aliased batch**
(40 issues/query → ~3–4 `gh api graphql` calls for ~128 numbers). It prints each
number's `state` / `stateReason` / `closedAt`, bucketed into OPEN (keep),
CLOSED-this-cycle, and CLOSED-stale-missed (closed on a prior run but never
pruned), plus a paste-ready PRUNE list and a COMPLETED list. Numbers come from
`parse_watching.py`'s Item-column logic (same host caveat — pipe the Read-tool
`## Watching` section on stdin `-` if `~/Documents` is TCC-blocked).

**THE SCRIPT NOW CLASSIFIES ROWS ITSELF** (added 2026-08-22 after a THIRD
consecutive run hand-derived the same split): its output ends with a
`# ROW CLASSIFICATION` block bucketing every closed number into
**PRUNABLE ROWS** (every number in the Item cell closed), **ANNOTATE**
(closed sibling of an open canonical, not yet marked closed in row prose),
and **EXPECTED RESIDUE** (already-annotated siblings — no action, and they
re-flag every run by design). Quote prune counts ONLY from the PRUNABLE ROWS
bucket; never from the closed-numbers total.

Expect the stale-missed bucket and the EXPECTED RESIDUE count to stay
non-empty run over run — that is NOT evidence of missed work. (History:
2026-08-06 "prune 10" reached a user-facing plan when 0 rows were prunable;
2026-07-24 same finding; 2026-08-22 17 flagged, all residue. The
classification moved into `reconcile_watching.py` — tests in
`test_reconcile_watching.py::ClassifyClosed` — precisely because three runs
re-derived it by hand.)

Act on each closed number by reason:
- `completed` → promote to Active findings as REMOVE_WORKAROUND or UPDATE_PATTERN. Verify the fix actually retires one of OUR workarounds before retiring it — do not auto-retire on `completed` alone.
- `not_planned` → prune the row from Watching, note in Archived
- `duplicate` → find the canonical (close event / comments); canonical already in Watching → archive the duplicate row as corroboration; otherwise repoint the row to the canonical number (re-checked next run)
- still `open` → keep in Watching, refresh the Updated date
- **multi-number cluster rows**: if a CLOSED number is a NON-canonical sibling in a `#A / #B / #C` row whose canonical is still OPEN, ANNOTATE the sibling as closed in the row prose — do NOT prune the row. (The parser extracts every Item-column number, so the reconcile flags siblings too; only prune a row when ALL its numbers are closed.)

**RETIRED — the bulk `closed:>=DATE` intersection (do NOT use; kept as rationale).**
Earlier runs (Step 1b through 2026-07-20) intersected the Watching set against
`gh issue list --search "closed:>=<last-run>"`. That query's cost scales with the
REPO's closure volume, not our ~128-number Watching set, and anthropics/claude-code
runs stale-bot mass-triage waves that close hundreds of issues per day — so the list
truncates before the relevant closures are even on the page. Observed limit-capped at
100 (2026-06-11 — #58682 missed at item 100), returning 0 at limit 500 (2026-07-18),
and capped at 400 (2026-07-23 — the GraphQL batch found 12 closures the bulk cut
surfaced only 2 of, including 3 standalone rows the run had otherwise missed). No
`--limit` fixes a query bounded by the wrong thing; the GraphQL batch above is bounded
by OUR set and is immune to the wave. Per-item `gh issue view {number} --json
state,stateReason` remains valid for spot-checking a single number, but is not the
set-reconciliation path.

**Watching-set extraction — generate, don't transcribe (2026-06-16):** the
intersection input is the Watching issue numbers. Hand-typing ~85 of them into
the script is the one place a typo silently drops a closure (→ stale Watching →
a workaround kept for an already-fixed bug). Generate the set:
`python3 scripts/parse_watching.py <report-path>` prints the tracked issue
numbers from the report's `## Watching` section as a paste-ready Python set.
The script extracts from the table's **Item column only** (2026-07-05 fix —
whole-section extraction over-captured inline issue/PR references embedded in
row prose, e.g. `PR #1489`, inflating a 90-row set to 120; the 2026-07-03 run
had to re-derive the column-only set by hand with awk). HOST CAVEAT: where
the report lives under a Bash-sandbox-blocked path (e.g. `~/Documents` under
macOS TCC — `cp`/`ls`/`git` there return "Operation not permitted" even with the
sandbox disabled), pipe the Read-tool's `## Watching` section to the script on
stdin (`-`); never eyeball-transcribe.

**Closure-boundary overlap:** `reconcile_watching.py --since` classifies a
closure as this-cycle when `closedAt >= since` (INCLUSIVE), so it re-surfaces
issues that closed ON the last run's date (already processed). Dedupe this-cycle
hits against the previous run's Archived — same-day overlap is expected, not a
new closure. (Inclusive is deliberate: it also catches issues that closed late on
the last-run day, after the prior sweep ran.) The stale-missed bucket is the
safety net for closures earlier runs' truncated intersections dropped — expect it
to be non-empty for several runs while the historical backlog drains.

**Watching aging (see `references/report-format.md` "Watching hygiene"):** move
`[WIN-ONLY]`/locally-retired and >90-day-untouched-not-affecting-us rows to a
`## Watching (Dormant)` appendix re-scanned only on `full` runs — keeps the
incremental working set tight without losing coverage.

## Step 2: Prioritized Workaround Scan

Grep baseline files for workaround indicators: "workaround", "upstream bug", "known bug", "compensate", "GitHub #", "until fixed". These are the items most likely to be obsoleted by new releases.

Build a short list (expect 5-15 items). Skip pure constraints and patterns - they rarely change.

## Step 3: Structured CHANGELOG Diff

Fetch the raw CHANGELOG.md from GitHub (Tavily truncates the page - it's too long):

```bash
gh api repos/anthropics/claude-code/contents/CHANGELOG.md --jq '.content'
```

Decode from base64 in a Python script. Parse into per-version sections using a generic semver regex `re.split(r'^## (\d+\.\d+\.\d+)', text, flags=re.MULTILINE)` — the prior pattern was hardcoded to `2\.1\.\d+` and silently left the entire CHANGELOG as one unsplit blob whenever the version moved to 2.2, 3.0, etc.

For each workaround from Step 2, build **compound keyword groups** (2+ keywords that must ALL appear in the same changelog line). Single keywords produce ~80% false positives. Example:
- "autocompact fires at 76K" -> `[["autocompact", "threshold"], ["compact", "premature"], ["compact", "token"]]`
- "background task output fails" -> `[["background", "task", "output"], ["background", "path"]]`

Cross-reference each changelog line (lines starting with `-`) against these compound groups. Report matches with version numbers.

Also scan for:
- Any line containing "breaking change" or "deprecated"
- Any line mentioning hooks, skills, agents, MCP, or settings (these are architecture-relevant even if they don't match a workaround)

**Retain the FULL per-version bullet list — Step 14b needs it.** The compound-keyword
match above is tuned for workaround staleness: high precision, deliberately low recall,
and it can only fire on wording that resembles a defect we already track. It is
structurally incapable of surfacing a capability that is new to us, because we have no
workaround keyword for a feature we never had. Write every version's
`Added`/`Changed`/`Improved`/`Removed`/`Reverted` bullets to a file in the same parse and
narrate from that file in Step 14b:

```python
newer = [(v, body) for v, body in versions if key(v) > key(installed)]
for v, body in newer:                      # newest-first
    bullets = [ln.strip() for ln in body.splitlines() if ln.strip().startswith('-')]
    # -> write to changelog-window.txt; Step 14b reads THIS, not the keyword matches
```

Classify each matched workaround:

| Status | Meaning | Action |
|--------|---------|--------|
| **FIXED** | Bug was fixed | Recommend removing workaround |
| **CHANGED** | Behavior modified | Recommend updating pattern |
| **DEPRECATED** | Feature removed | Recommend removing usage |
| **SUPERSEDED** | New feature replaces old pattern | Evaluate replacement |

## Step 3b: Installed-Version Regression Sweep (MANDATORY)

After CHANGELOG parse, immediately check open issues for regressions tagged
against the **currently installed version** (captured in Step 1) — bugs
that affect us right now, not future ones. Full `gh issue list` queries,
rationale from the 2026-04-17 #50252 incident, and tagging convention live
in `references/installed-version-sweep.md`. Any match is a HIGH-priority
finding tagged `[INSTALLED-VERSION-REGRESSION]`.

---

# Phase B: Gather New

Two parallel tracks. Fire GitHub Track and Web Track simultaneously.

**Prefer `scripts/fetch_window.py` over running Steps 4-8b's ~30 `gh`/`curl` calls
conversationally.** Run one at a time, they dominate wall-clock, and a hand-run
sweep keeps reintroducing three hazards the script closes structurally: a
truncated set (`rows == limit`) auto-escalates instead of silently passing the
max-number health check; every fetch lands in a file so neither
`bash-security-guard` nor `bash-tail-buffering-guard` can fire; and every task
gets its own manifest entry, so a failed channel is visibly failed rather than
indistinguishable from one nobody fetched.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/gather-claude/scripts/fetch_window.py --since {since_date} --out /tmp/claude/gc-run \
  --dedupe-against ~/Documents/knowledge-base/research/claude-code-anthropic-intelligence.md
```

Pass `--dedupe-against <prior report>` on every incremental run: it splits the
window's issue numbers into ALREADY-COVERED vs FRESH (and buckets the `[cyber]`
classifier-FP wave into one counted line), so overlapping or same-day windows
need no hand-grep (2026-08-22: the hand-grep missed a covered number the flag
catches). Use `--get <task>` to print a task's output file path instead of
guessing extensions (`npm-dist-tags` is `.json`; `changelog-b64` is RAW BASE64
`.txt` — decode it directly, it is not the `gh api` JSON envelope; `status` is
`.json`). The docs baseline persists and diffs automatically, recovers the
previous baseline from `origin/main` when the local checkout is behind, and
diffs against a same-date earlier run's file instead of clobbering it.

Read `manifest.json` for per-task `rc`/`rows`/`truncated`/`escalations` before
treating any source as covered; a nonzero `rc` means UNKNOWN, not empty — record
it in the Sources Log rather than silently omitting that channel from the report.
The reference files below still document the literal query shapes (and remain
the fallback if the script itself needs debugging or a channel needs a one-off
re-run at a wider window).

## GitHub Track

### Step 4: Targeted Issue Queries

Use `gh issue list --search` (NOT `gh search issues` which fails on label filters).
Inject `{since_date}` into searches for incremental runs. Run the label-filtered
bug queries from [references/github-track-queries.md](references/github-track-queries.md):
the **host-matching platform label** (`platform:macos` on macOS, `platform:windows`
on Windows — the label MUST match the host this deployment runs on; a
Windows-era `platform:windows` query ran for weeks on a macOS host and missed
macOS-labeled regressions), the three area labels (area:hooks, area:agents,
area:mcp), and the four high-signal labels added 2026-07-05: `regression`
(maintainer-triaged, higher precision than keyword search), `data-loss`,
`api:bedrock` (our GovCloud lane), and `area:security`. Low-volume labels
(regression, data-loss, api:bedrock) are scanned exhaustively; high-volume ones
(platform, area:security) are triaged by title. For `full` runs, omit the date
filter and add the most-reacted enhancement query (same reference).

### Step 4b: Security Advisory Sweep (MANDATORY)

Fetch first-party security advisories and cross-check the installed version
(from Step 1) against each advisory's vulnerable range — literal queries in
[references/github-track-queries.md](references/github-track-queries.md):
`gh api repos/anthropics/claude-code/security-advisories` plus the advisory-DB
`affects=anthropic` query (catches SDK-side advisories the repo feed misses).

- Installed version inside a vulnerable range → **HIGH finding tagged
  `[SECURITY-ADVISORY]`**, Act-now priority (upgrade or mitigate).
- Otherwise → Document in Known Issues with the patched version noted.

Rationale (2026-07-05): 30 published GHSAs existed — including a HIGH sandbox
escape via git-worktree path confusion, the exact isolation mechanism this
architecture depends on — while the report contained zero advisory mentions.
Advisories never appear in the CHANGELOG; this sweep is the only lane that
carries them. Cost: one `gh api` call per run.

### Step 5: RETIRED 2026-08-02 — Pain-Correlated Search (do NOT reinstate)

Deleted because it did not run: skipped or substituted in **6 of 15** recorded runs
(40%, the highest of any step), always with the same correct justification — the
area sweeps already covered it. Evidence + the general rule:
[references/run-metrics.md](references/run-metrics.md) "per-step SKIP RATE".

**Successor, already folded into Step 4**: architecture-keyword sweeps (`hook`,
`worktree`, `transcript`, `skill`, `permission deny`, `sandbox bash`, `subagent`)
scoped to `created:>={since_date}` — where the 2026-08-01 findings actually came from.

The NUMBER is retired, not renumbered, so `Step 6`..`Step 16` and every historical
citation still resolve. Same convention as the RETIRED bulk `closed:>=` intersection
in Step 1b.

### Step 6: Deep-Fetch High-Signal Items

From Steps 4-5, triage to the top 10 most relevant (prioritize: platform-specific > behavior changes > new features). Deep-fetch:

```bash
gh issue view {number} --repo anthropics/claude-code --json body,comments
```

### Step 7: Merged PRs (lightweight)

Only check for behavior-changing PRs, not all merges — `gh pr list` query in
[references/github-track-queries.md](references/github-track-queries.md). Scan titles
only. Deep-fetch only PRs whose titles mention hooks, skills, agents, MCP, settings,
or Windows.

### Step 7b: Release Notes (GitHub) + Version Channels

Release notes often have more narrative than CHANGELOG.md. Fetch in parallel with PRs:
`gh release list` for `anthropics/claude-code` plus the Python and TypeScript Agent SDKs
(SDK-facing changes relevant to subagent/hook patterns) — literal queries in
[references/github-track-queries.md](references/github-track-queries.md). Filter to
releases after `{since_date}`; deep-fetch bodies only for versions not already covered
by the Step 3 CHANGELOG parse.

Also fetch (added 2026-07-05, same reference for literal commands):
- **API SDK releases** (`anthropics/anthropic-sdk-python` / `-typescript`, ~3/week) —
  API-surface changes (new endpoints, beta headers, param deprecations) land here first
  in machine-readable form; the Sonnet 5 `temperature` removal 400'd our Bedrock
  detector before any covered source carried it.
- **MCP spec releases** (`modelcontextprotocol/modelcontextprotocol`) — protocol
  revisions hit our MCP gateway fleet; the 2026-07-28 revision RC shipped 2026-05-29.
- **npm dist-tags** for `@anthropic-ai/claude-code` — Anthropic's own `stable` vs
  `latest` designation (one curl). A wide stable/latest gap (e.g. 2.1.193 vs 2.1.201
  observed 2026-07-05) is a first-party known-good-version signal for pinning decisions.

## Web Track

### Step 8: Docs Inventory (llms.txt) + Extract Key Pages

**Tool routing**: Follow `rules/web-search-preference.md` (source: `<claude-config-repo>/rules/web-search-preference.md`; deployed at `~/.claude/rules/web-search-preference.md`). The Claude Code docs are Mintlify-hosted — that rule routes Mintlify extraction to `mcp__firecrawl__firecrawl_scrape` (tavily_extract returns nav-shell/`Content: undefined` on these pages; observed degraded on every extract until the 2026-07-05 fix). Exa stays for date-filtered discovery; Tavily for non-Mintlify extraction and search.

Fetch the docs inventory from `https://code.claude.com/docs/llms.txt` (one GET, ~169
lines, every page WITH a one-line description) and diff it against the previous run's
Sources Log page list. This replaces the old `tavily_map` crawl (kept as fallback if
llms.txt 404s — literal calls in
[references/web-track-queries.md](references/web-track-queries.md)). Then
`firecrawl_scrape` the six high-value pages (changelog, hooks, skills, settings,
sub-agents, mcp).

**New pages in the inventory are high-signal** — extract them immediately.

**PERSIST THE PAGE LIST, NOT JUST ITS COUNT.** `fetch_window.py` now does this
automatically (added 2026-08-22): it extracts the page set from the fetched
`docs-llms.txt`, writes `research/baselines/claude-docs-pages-<date>.txt`
(override with `--baseline-dir`), and prints the +added/-removed diff against
the newest previous baseline. The automation exists because the manual step
was a dead letter — mandated since 2026-07-05, executed by ZERO runs, so the
page-set diff had never once been derivable (measured 2026-08-22: no baseline
file existed). Verify the `docs baseline:` line appears in the fetch output;
its absence or a "NOT persisted" message goes in the Sources Log.

(`gather-vendor` follows the same convention — `research/baselines/openai-llms-links-YYYY-MM-DD.txt`.)

**A COUNT DELTA IS NOT A PAGE DIFF, AND A KEYWORD GREP IS NOT EITHER.** With only
the prior count, the temptation is to grep the new inventory for interesting-looking
topics and call the hits "new" — but a keyword grep returns pages that have been
catalogued for months, so it over-reports additions AND is structurally blind to
REMOVALS (a page that disappeared cannot match a grep). Report a page-set change
ONLY from a real set-diff; if the prior list is unavailable, say the diff was not
derivable rather than substituting a grep. (2026-08-06: a keyword grep produced
"+2 new pages"; the inventory had actually gone 180 → 176 — a NET LOSS of 4,
including `ultraplan.md`, which the CHANGELOG independently confirmed as a removed
feature. The removal was the real finding and the grep could not have found it.)

### Step 8b: First-Party Release-Notes Sweep (added 2026-07-05)

Five cheap fetch groups per run — literal commands in
[references/web-track-queries.md](references/web-track-queries.md); filter each to
entries after `{since_date}`:

1. **Claude Platform (API) release notes** — Admin/Usage/Analytics API changes, model
   access events, param deprecations (curls clean as `.md`).
2. **Claude apps / Enterprise release notes** (support.claude.com) — admin console,
   model entitlements, Compliance API, desktop/web ships our claude.ai monitoring rides on.
3. **Model deprecations page** — lifecycle states + retirement dates for every model we pin.
4. **AWS Bedrock What's New RSS** (grep Anthropic/Claude) — GovCloud model availability
   never appears in any Anthropic-hosted channel.
5. **Claude Desktop 3P configuration changelog + M365 connector page** (added
   2026-07-16) — we run this surface in production (Jamf "Claude 3P" profiles,
   Bedrock GovCloud, built-in M365 local connector against the GCC High tenant).
   Watch for: new `managedMcpServers` subfields / built-in `server:` values, M365
   tool-catalog changes (Outlook mail-folder tools, Teams posting), GCC High/DoD
   notes, and **silent default flips** on new config keys — deployed profiles
   inherit vendor defaults for keys they don't set; diff new keys against the
   deployed plists.

Findings flow into the normal categories (NEW_FEATURE, DEPRECATION, UPDATE_PATTERN).
Rationale: the Fable 5 suspension/restoration, the Sonnet 5 parameter deprecations, and
every Admin-API endpoint migration were published ONLY in these channels — none reach
the CHANGELOG or the claude-code issue tracker. Likewise the Desktop-3P surface: M365
write tools (2026-07-07), the websearch built-in (2026-06-25), and the
`isDesktopExtensionEnabled` default flip shipped ONLY in the Desktop-3P config
changelog — invisible to every other track.

### Step 9: Gap Fill (only if needed)

If Step 8 left gaps for specific architecture components, fire in parallel: the
`tavily_search` component query, the seven first-party extraction URLs (anthropic.com
news / research / engineering, claude.com blog, docs overview, support, status), and the
Exa `web_search_exa` gap fill — literal calls in
[references/web-track-queries.md](references/web-track-queries.md).

**No further waves.** First-party sources are finite.

### Graceful Degradation

Never fail the entire skill because one source is unavailable. The only full abort is a
missing `gh` at Step 0 (exit 2); every other failure — a single `gh` command erroring
mid-run, a missing Step 1 baseline file, empty Tavily
results, a URL 404 — is noted in the Sources Log, skipped, and the run continues.
Per-failure action table:
[references/preconditions-and-degradation.md](references/preconditions-and-degradation.md).

---

# Phase C: Verify, Present, and Apply

## Step 10: Merge and Deduplicate

Same finding from multiple sources = one finding citing all sources. Prefer: issue/PR > CHANGELOG > docs.

## Step 11: Cross-Reference

Check each finding against:
1. Phase A workaround matches
2. Community report (tag `[community-confirmed]`)
3. Research report (tag `[research-validated]`)

## Step 11b: Adversarial Verification

For each REMOVE_WORKAROUND or UPDATE_PATTERN finding, run a lightweight
adversarial check (gh issue search for "regression"/"still broken" + Exa
community-reports query) before auto-writing. Counter-evidence downgrades
the finding from REMOVE_WORKAROUND to KNOWN_BUG. Full queries and the
downgrade rule live in `references/adversarial-verification.md`.

## Step 12: Categorize and Prioritize

| Category | Priority | When to act |
|----------|----------|-------------|
| **REMOVE_WORKAROUND** | Act now | Bug we worked around is fixed |
| **DEPRECATION** | Act now | Something we use is deprecated |
| **UPDATE_PATTERN** | Act soon | Behavior we depend on changed |
| **KNOWN_BUG** | Document | Open issue explains our pain |
| **NEW_FEATURE** | Evaluate | Capability we're not using |
| **NEW_FEATURE_AUTO** | Document only | Platform applies it for free (memory leak fixes, FD limits, retry behavior). ADOPT-by-default per Step 12b. |
| **INCOMING** | Watch | Open PR signals upcoming change |
| **CONFIGURATION** | Low | Better config option exists |
| **TRAINING** | Low | New learning resources |

Sort by category (table order = priority order). Within a category, sort by number of architecture files touched.

**When a finding recommends a numeric threshold, limit, or cap**: collect the actual distribution from session/log data before proposing a value. Report percentiles (P50, P75, P90, P95, P99). State what percentage of real operations would be affected. Never propose a threshold based on assumption alone.

## Step 12a: Report-lifecycle walk (MANDATORY)

```bash
python3 scripts/report_lifecycle.py <report-path>   # exit 1 = report is not presentation-ready
```

One pass over active report prose and dated or legacy-numbered findings: legacy
calendar-observation state, unresolved QUALIFY verdicts, DEFERs missing a
trigger, the machine-countable adoption metric, invalid/missing Verdict,
missing or unresolved Qualification/Verified evidence, and Watching counts. Act on it BEFORE Step
12b. Re-run deterministic qualification without applying the edit; resolve the
finding to ADOPT, DEFER, or REJECT in the same run. Archived historical records
remain historical and do not block.

It is a script because all four of these failed on 2026-08-01 as prose. Why that
generalises: [references/run-metrics.md](references/run-metrics.md).

## Step 12b: Assign verdict per finding (MANDATORY)

Every finding gets one of four verdicts in the same run it surfaces. No "decided later" — that produces the multi-month opportunity backlog this skill exists to prevent. The verdict set, the "a category is never a verdict" rule, and the canonical finding-format field spellings are the gather-family shared discipline — `../_shared/gather-conventions.md` §1–2 is the canonical authority (it wins on any disagreement).

| Verdict | Meaning | What this run does |
|---------|---------|--------------------|
| **ADOPT** | Apply after qualification | Concrete edit to `settings.json`, `~/.claude.json`, a skill, hook, or rule only after deterministic qualification evidence is recorded in this same run. Doc update is a side-effect, not the deliverable. |
| **QUALIFY** | Do not apply | Exercise the proposed edit in a disposable candidate in this same run, then replace this provisional verdict with ADOPT, DEFER, or REJECT before presentation. |
| **DEFER** | Don't apply yet | Reason + concrete re-eval trigger (e.g., "until Bedrock eval is active", "if PR-CI integration added"). Vague "maybe later" is REJECT, not DEFER. |
| **REJECT** | Don't apply | Reason logged. Future runs surfacing the same finding tag `[previously-rejected-similar]` and deprioritize per Rejection Log. |

Findings tagged NEW_FEATURE_AUTO (platform applies it for free — memory leak fixes, FD limits, retry behavior) are ADOPT-by-default; the only deliverable is the doc note.

If you can't pick a verdict at run-time, the verdict is REJECT — surface as "no use case identified at run-time." This prevents the holding-pen failure mode.

**A new setting that OVERLAPS a mechanism we already run is DEFER, not ADOPT, until the
precedence is measured.** ADOPT requires deterministic qualification, and for a setting
that duplicates existing coverage, "the key name is real and the file parses" is not
qualification — it says nothing about which mechanism wins or what the current behaviour
already is. Before grading such a finding ADOPT, establish: (a) does any first-party
source state the precedence, and (b) what does the existing mechanism deliver TODAY.
If (a) is silent, the verdict is DEFER with the measuring instrument named as the trigger.
Measured 2026-08-30: `promptCacheTtl` / `subagentPromptCacheTtl` (v2.1.243) were graded
ADOPT and applied to the LIVE settings while `env.ENABLE_PROMPT_CACHING_1H` was already
set and `FORCE_PROMPT_CACHING_5M` also exists — with no source stating precedence. So
`subagentPromptCacheTtl: "5m"` may have SHORTENED subagent caching rather than preserving
it: an unmeasured cost/latency regression, shipped in the run whose own headline finding
was a cost control silently breaking. Both keys were reverted the same day and re-graded
DEFER. The tell to catch it earlier: the finding's "What changed" called them
"finer-grained successors" to the env var — an inference stated as fact, with nothing read
this run establishing that they supersede rather than conflict.

QUALIFY is a same-run, pre-application state only. Run the applicable regression,
mutation, transcript replay, smoke, and authenticated read-only probes against a
disposable candidate. Record the command and result in `Qualification`, then
replace QUALIFY with ADOPT only on success. A blocked qualification becomes
DEFER only when it has a machine-checkable external trigger; otherwise REJECT.
Do not apply a live edit merely to observe it. The exact success form is
`PASSED — <command and result>`; the lifecycle gate rejects a bare `PASSED`.
It also rejects pending/unknown verification and an unlabeled non-zero overall
result. Identify expected non-zero negative controls as expected evidence.

In addition to the required identity/evidence fields in the canonical format,
the lifecycle fields use these exact spellings:

```markdown
- **Verdict**: ADOPT | QUALIFY | DEFER | REJECT
- **Trigger**: [machine-checkable event; required for DEFER, omitted otherwise]
- **Qualification**: PASSED — <command and result> | not-applicable — <reason for DEFER/REJECT>
- **Verified**: [yes — source and target read]
```

## Step 13: Verify Claims (MANDATORY)

Before presenting any finding, verify it: read the cited file, confirm
the quoted text exists, confirm the "what changed" claim is accurate,
and de-conflate findings that reference the same setting. Correct or
downgrade — never present unverified findings. Full 4-step procedure
and the originating near-miss (Finding #2 conflating `settings.json` vs
`~/.claude.json`) live in `references/verify-claims.md`.

**Currency calibration — do not over-reject current features (measured fix):**
when judging a feature/flag/command NONEXISTENT or stale, apply
`uncharted-vs-refuted.md` — absence of a first-party hit in a *bounded* search
is a property of the search, not evidence of absence. If multiple independent
credible sources describe the SPECIFIC feature and no first-party source
contradicts it, classify it CURRENT at lower confidence; reserve NONEXISTENT for
features with no credible attestation anywhere. (Live arm measured the
pre-calibration framework over-rejecting real `effort:`/`/rewind` — see
`harness/PROBLEM.md`.)

## Step 14: Present Report

Emit the **metadata header**, then `## Active Findings` grouped into its five `###`
subsections (Architecture Debt; Action Required; Opportunities; Known Issues & Incoming;
Learning Resources), with each entry in the **canonical finding format** — all three
templates live in [references/report-format.md](references/report-format.md). The
finding format is the canonical schema for the `Active Findings` and `Archived`
sections; subsequent runs parse `Verdict`, `Trigger`, and `Qualification`, so
all required fields must be present in the exact spelling shown there. Re-run
`report_lifecycle.py` after composing the report; unresolved QUALIFY, legacy
staged state, or an invalid/missing field blocks presentation.

## Step 14b: What Changed Upstream — narrative (MANDATORY)

Emit a `## What Changed Upstream` section BEFORE `## Active Findings`, narrating each
update in the window **as a change or a new capability, not as a defect**. Every other
part of this report is defect-shaped: the categories are REMOVE_WORKAROUND / KNOWN_BUG /
UPDATE_PATTERN / DEPRECATION, Phase A audits workarounds, and Step 3's compound-keyword
match only fires on lines resembling a bug we already track. That structure answers "what
of ours broke or got fixed" and **silently drops "what can we now do that we could not
before"** — a run can pass every gate while never telling the reader what Anthropic
actually shipped.

Write prose, one short paragraph per update, grouped by channel. Say what changed, what
it now enables, and whether it touches anything we run. Name versions and dates.

**In scope (narrate these):** new settings keys, env vars, hook events, tools, tool
parameters, CLI flags, slash commands; new API endpoints, toolsets, or beta→GA
promotions; model availability and lifecycle changes (including partner platforms);
protocol revisions; new managed/MDM configuration keys; default flips; renames and
aliases; docs-inventory additions and removals; capability limits raised or lowered.

**Out of scope (do NOT narrate; they belong in findings):** pure bug fixes with no
behavioral surface we rely on, cosmetic/TUI polish, and anything platform-specific to a
host we do not run. A fix DOES belong here when it changes a behaviour our architecture
depends on — say so explicitly and cross-reference the finding.

Cover every channel every run, in the order given by the per-channel checklist and
template in [references/report-format.md](references/report-format.md) ("What Changed
Upstream template").

**A channel with nothing to narrate must say so with its evidence** (item count, newest
entry date). An omitted channel is indistinguishable from a channel that was never
fetched — that ambiguity is the thing this section exists to remove.

Derive the CLI paragraph from ALL `Added`/`Changed`/`Improved`/`Removed`/`Reverted`
bullets in the window's versions, not from the Step 3 compound-keyword matches. Step 3's
keyword groups are tuned for workaround staleness (high precision, deliberately low
recall); reusing them here inherits their blind spot.

## Step 15: User Approval and Apply

Present the categorized findings to the user **with final verdicts attached**
(Step 12b). Ask: "Approve all ADOPT findings? Override any verdicts? Skip any?"

**NEVER auto-write.** Wait for explicit user approval before modifying any files.

After user approval, for each ADOPT finding:
0. **`git fetch` the target repo, then re-check the finding still exists UPSTREAM.**
   Reading the target file proves what your CHECKOUT holds, not what the repo holds —
   step 1 below is necessary but not sufficient. This checkout routinely sits tens of
   commits behind (recurring P1 across retros), so a finding derived from it can be a
   problem someone already fixed. Verify with `git show origin/<default>:<path>`, not
   the working copy, and drop the finding if upstream is already correct.
   (2026-08-08: a `cc-monitor` eval repair was real against the local checkout AND
   mutation-verified 8 BITES / 0 misses — yet was **already obsolete on arrival**:
   #1930/#1922 had rewritten skill and eval together and the gate was 9/9 green
   upstream. Applying it would have overwritten a CURRENT eval with one written
   against older content. The mutation evidence was sound and measured the wrong
   baseline, which is why "I verified it" does not cover this.)
   Also check each target with `git cat-file -e origin/<default>:<path>` — a file that
   exists only locally cannot ship independently; drop that part of the finding and say
   so rather than dragging its parent commits along.
1. Read the target file (even if read during verification — file may have changed)
2. **ADOPT means concrete runtime edit**, not just an `ARCHITECTURE.md` prose bullet. Targets are `settings.json`, `~/.claude.json`, a skill body, a hook script, a rule file. If the only edit you can produce is a doc bullet, the verdict was wrong — reclassify as DEFER with an explicit reason.
3. Make the specific edit
4. **Verify the edit persisted**: re-Read the target file and confirm the intended change is present at the intended location. Concurrent sessions and post-write-edit hooks can silently revert edits between Edit and the next command. If the change is not present, report as `Attempted — reverted externally` rather than `Applied`.
5. Confirm the report records the same-run deterministic qualification evidence
   that justified ADOPT. A missing or stale result sends the finding back to
   QUALIFY; do not apply it.
6. Log the change in the report — use `Applied` (ADOPT, persisted) or
   `Attempted (reverted)` per persistence check.
7. Leave changes **uncommitted** for user review before committing.

## Step 16: Codify Run Improvisations (MANDATORY)

If this run improvised anything better than the documented procedure — a different
label set, a better extraction tool, a workaround for a broken query or parser — patch
the skill in the SAME run: edit the relevant `references/*.md` or `scripts/*` alongside
the report edits (same worktree/PR), or record the exact intended diff in the report as
a `SKILL-DEBT` finding so the next run ships it. An improvisation that lives only in
the Sources Log is re-derived from scratch every subsequent run.

Rationale (2026-07-05 audit): three run improvisations — `platform:macos` in the label
sweep (2026-06-11), Item-column Watching extraction (2026-07-03), firecrawl-for-Mintlify
(2026-07-03) — were each documented in Sources Logs but never codified; the spec kept
the stale versions and later runs re-solved the same problems.

**Close the worktree loop:** a skill-improvement worktree whose PR has MERGED is
debris — verify containment (`git cherry origin/main <branch>` all `-`, clean
tree, no unique stash), then remove it. Measured 2026-08-22: FIVE gather-claude
worktrees existed, at least one (`gc-skill-improvements`) matching an
already-merged PR; each run that skips this step leaves the next run to
re-classify the sprawl.

**Adoption metric**: in the metadata header, record `Adopted last 90d: X / Y opportunities`. The number on the right counts every NEW_FEATURE finding surfaced in runs from the last 90 days; the left counts only findings that reached `Applied` after direct qualification. QUALIFY is not adoption. Visible drift = pressure to re-evaluate the DEFER list at the next run. **Re-derive both counts each run** by tallying `Verdict:` lines across the last-90-days run-metadata/Archived blocks — do NOT hand-carry the prior run's figure. A number that rides forward unchanged with a `≈` (as `≈6/≈17` did across four runs) creates no pressure: either recompute it from the report, or write `(not recomputed this run)` so the staleness is explicit rather than disguised as a measurement.

---

# Output File Management

## Report Format and Lifecycle

The report file location, top-level Markdown structure (Metadata / Active
Findings / Watching / Known Issues / Learning Resources / Archived /
Sources Log), the Step 14 templates (metadata header, subsections, finding format),
and the subsequent-run procedure (snapshot, promote Watching, reject unresolved
qualification state, etc.) live in
[references/report-format.md](references/report-format.md).

---

# Success Criteria

## Measured Efficacy (live arm)

**Verdict: `keep` — measured 2026-05-31, N=3, `claude-opus-4-8`, n=15 (vs fair baseline);
calibration FIX applied + re-measured in the same session.** Post-fix the framework is
≥ baseline on every axis (overall verdict_accuracy **0.933 vs 0.844, +0.089 primary**),
after the Step 13 calibration floor eliminated the pre-fix over-rejection regression.
Full before/after record:
[references/examples-and-evals.md](references/examples-and-evals.md) ("Measured
Efficacy"); REAL-vs-INSTRUMENT check: `harness/PROBLEM.md §5–6`; CI gate:
`tests/test_gather_claude_efficacy.py`.

## Process criteria

- Phase A scans workaround items (not all baseline items) against CHANGELOG
- CHANGELOG parsed version-by-version (new features, fixes, breaking changes)
- GitHub Track uses targeted searches, not bulk scanning
- Platform label matches the CURRENT host; regression/data-loss/api:bedrock/area:security labels swept
- Security advisories (GHSA) swept every run and cross-checked against the installed version
- First-party release-notes channels (platform API, apps/Enterprise, model deprecations, Bedrock RSS) checked every run
- Docs inventory via llms.txt diff (tavily_map only as fallback); Mintlify pages extracted with firecrawl_scrape
- Run improvisations codified into the skill in the same run (Step 16), not stranded in the Sources Log
- Architecture-keyword sweeps run alongside the Step 4 label queries (the retired Step 5's successor); a label sweep whose max issue number trails the window counts as EMPTY
- Web Track maps docs site + extracts key pages in parallel
- Every finding verified against actual file content before presenting
- Findings with threshold recommendations include empirical distribution data
- Category-based priority (no composite scoring unless >20 findings)
- Findings presented to user for approval before writing
- Changes left uncommitted
- Individual source failures don't kill the skill

---

# Examples, Evaluation Prompts, Rejection Log

See `references/examples-and-evals.md` for three worked examples (routine sync, post-upgrade full sweep, focused area search), three eval prompts with grading rubrics, and the rejection-log discipline used to deprioritize previously-rejected findings on subsequent runs.

---

# Run Metrics

Track efficiency metrics per run to identify which search strategies have the best signal-to-noise ratio. See `references/run-metrics.md` for the metrics schema (queries, findings counts, signal-to-noise ratio) and the per-run procedure for recording and comparing them.
