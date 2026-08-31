# GitHub Track — Literal Queries (Steps 4, 4b, 5, 7, 7b)

Run these from the corresponding SKILL.md steps. Inject `{since_date}` into searches for
incremental runs; `full` runs drop the date filter where noted.

## Step 4: Targeted Issue Queries

Use `gh issue list --search` (NOT `gh search issues` which fails on label filters).

**Truncation note:** These queries use `--limit 50` and are subject to the same truncation risk as Step 1b (if result count EQUALS your limit, the list may be incomplete). For this discovery phase, the 50-result cap is an accepted bound — downstream triage surfaces the top findings — but be aware the full result set may be larger. Consider raising the limit or running full-history scans for production audit work.

**Platform label MUST match the host** (`uname` → `platform:macos` / `platform:windows`
/ `platform:linux`). A stale `platform:windows` query ran for weeks after the 2026-06
macOS migration and missed macOS-labeled regressions (e.g. #74314 transcript loss,
labeled `platform:macos`; caught 2026-07-05 only via the free-text Step 3b sweep).

**Labeling lag is ~A WEEK, not 1-2 days — the unlabeled sweep is mandatory on any
window up to ~10 days.** Maintainer labeling lags issue creation badly, so a
`created:>={since_date}` label filter matches little or nothing even when relevant
issues exist (2026-07-24, 1-day window: all 8 label queries empty; the unlabeled sweep
found 80 issues incl. 2 Watching-grade).

**Measured 2026-08-01 on an 8-DAY window: the 7 label queries topped out at issue
#79580 while the window's real issues ran to #83221 — the entire window was unlabeled,
and every finding that mattered came from the unlabeled sweep.** Note the trap: on a
multi-day window the label queries DO return rows (they use `updated:>=`, so they
surface OLDER issues that were re-touched), which makes the lane look healthy while it
covers none of the new window. **Treat a label sweep whose maximum issue number sits far
below the window's newest issue as EMPTY, regardless of row count** — check the max
number, not the row count.

**TWO health tests, not one — the max-number test alone gives a FALSE ALL-CLEAR
(measured 2026-08-21).** The max-number test detects labeling LAG. It does not detect
TRUNCATION, and the two failures look nothing alike:

| Test | Detects | Signal |
|---|---|---|
| max issue number vs window's newest | labeling lag | max far below window max → lane EMPTY |
| returned row count vs `--limit` | truncation | `rows == limit` → set INCOMPLETE |

On 2026-08-21 (9-day window) all 8 label sweeps PASSED the max-number test — topping
at #88480 against a window max of #88480, which reads as a fully healthy lane. But
**every one returned exactly `rows=50` against `--limit 50`**, i.e. all eight were
truncated and the row you needed could be the 51st. Run both tests and report both:

```bash
# Emit BOTH signals per sweep instead of eyeballing one of them
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title --search "$L updated:>={since_date}" \
  --jq 'if length==0 then "EMPTY" else "rows=\(length) max=#\([.[].number]|max)" end'
# rows == 50 -> TRUNCATED: re-run the sweep scoped to created:>= at --limit 100
```

**Prefer `created:>=` at `--limit 100` as the in-window census form.** `updated:>=`
mixes re-touched old issues into a 50-row budget, so the new-issue signal you want is
crowded out by rows you have already triaged in earlier runs. Scoping to `created:>=`
spends the whole budget on the window and made all 8 sweeps fit under the cap on the
same 2026-08-21 run that `updated:>=` truncated:

```bash
S={since_date}
for L in 'label:bug label:"platform:macos"' 'label:bug label:area:hooks' \
         'label:bug label:area:agents' 'label:bug label:area:mcp' \
         'label:regression' 'label:data-loss' 'label:api:bedrock' \
         'label:area:security'; do
  echo "=== $L ==="
  gh issue list --repo anthropics/claude-code --state open --limit 100 \
    --json number,title,createdAt --search "$L created:>=$S" \
    --jq '.[] | "\(.number)\t\(.createdAt[0:10])\t\(.title)"'
done
```

Keep the `updated:>=` form as a SECOND pass when you specifically want re-touched
older issues (a reopened bug, a maintainer re-triage) — just never read its
`rows == limit` output as coverage.

Fallback, not a skip: run one unlabeled title sweep and triage by relevance —
`gh issue list --repo anthropics/claude-code --state open --limit 80 --json
number,title,labels --search "created:>={since_date}"`. Volume is ~100 issues/day, so a
multi-day window will hit any `--limit` you set: pair the sweep with targeted
architecture-keyword queries (`hook`, `worktree`, `transcript`, `skill`,
`permission deny`, `sandbox bash`, `subagent`) scoped to `created:>={since_date}`, which
is what actually surfaced the 2026-08-01 findings. Zero label hits is lag, NOT absence
of signal.

```bash
# Platform bugs matching our host (macOS shown; swap the label per host)
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt \
  --search "label:bug label:\"platform:macos\" updated:>={since_date}"

# Hook behavior changes
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt \
  --search "label:bug label:area:hooks updated:>={since_date}"

# Agent behavior changes
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt \
  --search "label:bug label:area:agents updated:>={since_date}"

# MCP changes
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt \
  --search "label:bug label:area:mcp updated:>={since_date}"
```

## Step 4 (continued): High-Signal Labels (added 2026-07-05)

Maintainer-applied labels the 4-query set above cannot reach. Low-volume streams
(regression ~225/30d, data-loss ~65/30d, api:bedrock ~49/30d) — scan exhaustively;
high-volume (area:security ~500/30d) — triage by title.

```bash
# Maintainer-triaged regressions (higher precision than free-text keyword search)
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt --search "label:regression updated:>={since_date}"

# Data-loss reports (wiped transcripts/worktrees/files — our documented incident class)
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt --search "label:data-loss updated:>={since_date}"

# Bedrock lane (our GovCloud deployment path; platform:aws-bedrock is superseded, 0 open)
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt --search "label:api:bedrock updated:>={since_date}"

# Security-behavior issues below GHSA severity (permission bypasses, sandbox oddities)
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt --search "label:area:security updated:>={since_date}"
```

## Step 4b: Security Advisory Sweep

```bash
# First-party GHSAs on the CLI repo (severity, CVE, vulnerable + patched ranges)
gh api repos/anthropics/claude-code/security-advisories \
  --jq '[.[] | {cve: .cve_id, sev: .severity, published: .published_at, summary: .summary, ranges: [.vulnerabilities[] | {vulnerable: .vulnerable_version_range, patched: .patched_versions}]}]'

# SDK-side advisories invisible on the claude-code repo (e.g. Python SDK memory-tool)
gh api '/advisories?affects=anthropic' --jq '[.[] | {ghsa: .ghsa_id, sev: .severity, summary: .summary, published: .published_at}]'
```

Compare each `vulnerable` range against the installed version from Step 1. Inside the
range → HIGH `[SECURITY-ADVISORY]` finding, Act now. Outside → Known Issues note with
the patched version. On incremental runs, filter by `published_at >= {since_date}` but
ALWAYS run the installed-version range check (a version downgrade or an old pin can
re-enter a vulnerable range without any new advisory publishing).

For `full` runs, drop `updated:>=` filter and also query:
```bash
# Open feature requests sorted by most-reacted
gh issue list --repo anthropics/claude-code --state open --limit 50 \
  --json number,title,labels,updatedAt \
  --search "label:enhancement sort:reactions-+1-desc"
```

## Step 5: RETIRED 2026-08-02 (was Pain-Correlated Search)

Deleted from the skill: skipped or substituted in 6 of 15 recorded runs (40%), the
highest of any step, always with the same correct justification — the area sweeps
already covered it. See SKILL.md "Step 5: RETIRED" for the full rationale.

**Successor — architecture-keyword sweeps, run as part of Step 4.** These are what
actually surfaced the 2026-08-01 findings, and unlike the KB-derived keyword list
they need no external corpus, so they cannot be skipped for a missing precondition:

```bash
for k in hook "subagent nesting" worktree transcript skill "permission deny" "sandbox bash"; do
  gh issue list --repo anthropics/claude-code --state open --limit 14 \
    --json number,title,createdAt --search "$k created:>={since_date}"
done
```

**Truncation note:** if any single keyword returns exactly 14, that keyword's
results are INCOMPLETE — re-run it alone at a higher `--limit`.

Pair them with the unlabeled `created:>=` sweep — on a multi-day window the label
queries cover almost none of it (see the labeling-lag note at the top of this file).

## Step 7: Merged PRs (lightweight)

**Truncation note:** same truncation risk as Step 4 (`--limit 50`) — if the returned row count equals 50, treat the merged-PR list as INCOMPLETE and re-run with a narrower window or a higher `--limit`.

```bash
gh pr list --repo anthropics/claude-code --state merged --limit 50 \
  --json number,title,mergedAt --search "merged:>={since_date}"
```

## Step 7b: Release Notes (GitHub) + Version Channels

```bash
# Claude Code
gh release list --repo anthropics/claude-code --limit 20 \
  --json tagName,name,publishedAt,isLatest

# Agent SDKs (surface SDK-facing changes relevant to subagent/hook patterns)
gh release list --repo anthropics/claude-agent-sdk-python --limit 10 \
  --json tagName,name,publishedAt
gh release list --repo anthropics/claude-agent-sdk-typescript --limit 10 \
  --json tagName,name,publishedAt
```

Added 2026-07-05 — API SDKs, MCP spec, and Anthropic's stable-version pointer:

```bash
# API SDKs (~3 releases/week; param deprecations + new endpoints land here first)
gh release list --repo anthropics/anthropic-sdk-python --limit 10 \
  --json tagName,name,publishedAt
gh release list --repo anthropics/anthropic-sdk-typescript --limit 10 \
  --json tagName,name,publishedAt

# MCP spec revisions (protocol changes hit every MCP server/client we run)
gh release list --repo modelcontextprotocol/modelcontextprotocol --limit 5 \
  --json tagName,name,publishedAt,isPrerelease

# Anthropic's own stable-vs-latest channel designation (known-good version pointer)
curl -s https://registry.npmjs.org/-/package/@anthropic-ai/claude-code/dist-tags
```

A wide `stable`/`latest` gap is itself a finding: Anthropic is holding `stable` back
from recent releases (observed 2026-07-05: stable=2.1.193 vs latest=2.1.201) — weight
it when deciding whether an [INSTALLED-VERSION-REGRESSION] justifies a pin/downgrade.

Deep-fetch bodies only for versions not already covered by the CHANGELOG parse in Step 3:
```bash
gh release view {tag} --repo anthropics/claude-code --json body
```
