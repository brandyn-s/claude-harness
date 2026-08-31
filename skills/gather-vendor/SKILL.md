---

name: gather-vendor
description: "Sync the architecture with what a third-party LLM vendor shipped — model releases, API changes, and deprecations affecting our eval/judge/monitor tooling. One skill, per-vendor argument (openai | gemini | grok)."
when_to_use: Use when syncing with what OpenAI, Google Gemini, or xAI/Grok has shipped, or when asked whether/what ChatGPT, Gemini, or Grok supports. Probes pinned-model liveness, sweeps the vendor's API changelog, deprecations page, SDK releases, and release notes, then audits existing vendor workarounds for staleness. Invoke as /gather-vendor (openai|gemini|grok) [full|since:YYYY-MM-DD|focus]. Trigger phrases - "gather-vendor", "gather-openai", "gather-gemini", "gather-grok", "what's new with OpenAI/ChatGPT/Gemini/Grok/xAI", "OpenAI/Gemini/Grok changelog", "did OpenAI/Google/xAI deprecate", "is the Gemini flagship current", "is x-monitor's API current". Do NOT use for Anthropic/Claude Code (use gather-claude), community patterns (use gather-intel), academic research (use gather-research), or running X searches (use bin/x-monitor.py).
argument-hint: "(openai|gemini|grok) [optional: 'full', 'since:YYYY-MM-DD', or focus area]"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  requires:
    - mcp: firecrawl
    - mcp: tavily
    - cli: gh
allowed-tools: Bash Read Write Edit Glob Grep mcp__exa__web_search_exa mcp__tavily__tavily_search mcp__firecrawl__firecrawl_scrape AskUserQuestion
---

## gather-vendor

# Gather Third-Party LLM Vendor Intelligence

One parameterized skill for the vendors we **consume** as eval/judge/monitor
dependencies (distinct from `/gather-claude`, which syncs the platform we run
on). Three phases: **Audit existing** -> **Gather new** -> **Verify and apply**.
Runs in the main thread; user approval before any file is written.

Collapsed 2026-07-05 from three per-vendor siblings (gather-openai/gemini/grok)
after a red team found the probe script and Phase C machinery triplicated with
no sync mechanism — a bugfix landing in one copy left the other two stale. The
shared logic lives here; per-vendor dependency maps + literal queries live in
`references/<vendor>.md`.

## Step 0: Resolve vendor + scope guard

Parse the vendor argument (`openai` | `gemini` | `grok`). If the request is
about **Anthropic/Claude Code** -> `/gather-claude`; **community patterns** ->
`/gather-intel`; **academic research** -> `/gather-research`. If the vendor
argument is **absent and context doesn't disambiguate**, ASK which vendor
(AskUserQuestion) — do NOT default to `/gather-claude` (a bare `/gather-vendor`
means the user wants one of the three and omitted the token). Then load the
vendor's profile: **read `references/<vendor>.md`** (dependency map + all
literal fetch commands for this run). Everything below is vendor-neutral
mechanics; the reference supplies the vendor-specific commands.

**Time window:** last run date from the vendor's report metadata; no prior run
= 30 days; `full` = no filter; `since:YYYY-MM-DD` = that date; focus area =
narrow all queries to it.

**Multi-vendor runs:** when the user selects two or more vendors, the Phase B
sweeps are independent and MAY be dispatched as parallel read-only Explore/worker
agents (one per vendor, each given only its `references/<vendor>.md` channels and
returning raw channel evidence). The probe (Step 2), all verdicts (Step 8), the
AskUserQuestion gate (Step 9), and every write (Step 10) stay in the main thread
— agents gather, the parent decides. Serial execution remains correct and is the
default for a single vendor.

---

# Phase A: Audit Existing

## Step 1: Load Baseline

Read in parallel (any absent file -> note in Sources Log, continue):
1. Prior report: `~/Documents/knowledge-base/research/<vendor>-intelligence.md`
   (openai / gemini / grok). Its metadata sets the time window.
2. Workaround indicators — grep pattern in `references/<vendor>.md`, then scan
   hits for "workaround", "deprecated", "retired", "until fixed", "410".
3. **Current pins** — the grep in `references/<vendor>.md` reads the LIVE model
   IDs from the runtime files (roundtable adapters, x-monitor). These pins feed
   Step 2 — do NOT let Step 2 fall back to the probe's baked-in DEFAULTS.
4. **Baseline-file precondition (fail loud HERE, not at Step 10):** for every
   baseline the vendor's reference names, `ls` the newest
   `research/baselines/<vendor>-<artifact>-*.txt`. A prior Sources Log that
   CLAIMS a baseline with no file on disk means the prior run logged a count
   instead of persisting the artifact — open a `[BASELINE-MISSING]` finding
   immediately and treat this run's fetch as establishing run 1 (measured
   2026-08-22: the 2026-07-05 run claimed all four baselines; zero files
   existed, silently disabling every run-over-run diff).

## Step 2: Pinned-Model Liveness Probe (MANDATORY)

```bash
python3 ~/.claude/skills/gather-vendor/scripts/probe_models.py <vendor> <pins-from-step-1>
```

Pass the Step-1 pins as arguments (the probe's DEFAULTS are a documented
fallback that drifts from the tooling). The probe detects: full retirement
(404/410), xAI silent slug-redirect (200 under a different canonical id), same-
slug weight swap (version/fingerprint change, printed for xAI), auth-vs-
retirement (401/403 branch), and Gemini catalog truncation (full pagination +
cap tripwire). Exit code 1 on any non-PRESENT pin.

**Findings by probe result:**
- non-200 retirement (404/410) or SILENT REDIRECT -> **HIGH `[PINNED-MODEL-RETIREMENT]`**;
  identify the successor on the deprecations page THIS run.
- 401/403 AUTH FAILURE -> NOT a retirement; key/rotation issue (do not open a
  retirement finding).
- version/fingerprint changed vs the report's last-run value -> **MEDIUM
  `[MODEL-CONTENT-CHANGE]`**; re-validate the rater/arm against golden tests.
- **Record the probe's identity evidence in the report EVERY run** — copy each
  pin's `version=`/`fingerprint=`/`created=` values into the Sources Log (and
  the Metadata block when they changed). This detector is comparison-based: a
  run that omits the values blinds the NEXT run (measured 2026-08-22 — the
  first run recorded none, so a whole window of weight-swaps was undetectable).
- **gemini only:** ALWAYS pass the recorded flagship id as the pin (a pin-less
  probe exits non-OK "NO flagship pin passed" — it verified nothing). Recorded
  flagship absent from the printed pro-tier -> **HIGH `[PINNED-MODEL-RETIREMENT]`**;
  a NEWER pro-generation above it in the printed set -> **NEW_FEATURE** (panel
  arms must be best-in-class per `rules/best-in-class-for-cross-model.md`).
- **Probe limits (do not over-credit it):** the metadata GET proves the id
  RESOLVES, NOT that the endpoint the tooling rides is INVOCABLE — the Live-
  Search-410 class is an endpoint retirement a model-id GET cannot see. For
  Gemini, listing != serving (a model can appear in ListModels past its
  shutdown date). Cross-check the deprecations table for the recorded flagship,
  and rely on probe-before-panel (wired into roundtable + x-monitor) for
  invocability.

---

# Phase B: Gather New

## Step 3: Standing Sources Sweep

Run the vendor's standing channels from `references/<vendor>.md`, filtered to
`{since_date}`. Prefer the fetch-and-assert helper for each curl-class channel —
it fetches, asserts the marker, writes the artifact, retries one 429, and fails
LOUD on a marker miss (collapsing the fetch/diagnose double-fetch loop measured
3x on 2026-08-22):

```bash
python3 ~/.claude/skills/gather-vendor/scripts/fetch_channel.py <url> '<marker>' <outpath>
```

Exit 0 = fetched + marker present; 2 = HTTP failure (transient class); 3 =
marker MISS on a 200 body (dead/rewritten channel — a finding, not a retry).

**Per-channel liveness assertion (MANDATORY):** each standing fetch asserts a
known content marker (the reference names it per channel). A fetch that returns
but MISSES its marker is a **dead/rewritten channel**, not a quiet vendor —
distinct from a transient failure. Vendor doc hosts churned repeatedly in 2026
(platform.openai.com->developers.openai.com; cloud.google.com->docs.cloud.google.com;
soft-404s return HTTP 200 with a "Page not found" body). Record the last-
SUCCESSFUL-fetch date PER CHANNEL in the Sources Log (not one global run date),
so a channel that failed this run re-scans its own gap next run instead of
being skipped past by a global window advance.

## Step 4: SDK / Release Lane

Run the vendor's `gh`-based release + security-advisory queries from the
reference. Deep-fetch bodies only for breaking-change / deprecation / removed-
endpoint entries. A NEW nonzero GHSA advisory -> tag `[SECURITY-ADVISORY]` AND
route it to the org's security-alert intake (do not let it dead-end in the report).

## Step 5: Gap Fill (only if needed)

Search fallbacks in the reference when a focus-area argument or an ambiguous
finding needs corroboration. No further waves.

---

# Phase C: Verify and Apply

## Step 6: Verify Claims (MANDATORY)

Read the cited page/file; confirm quotes + the "what changed" claim. Currency
calibration per `rules/uncharted-vs-refuted.md`: bounded-search absence !=
nonexistence; multiple independent credible sources + no first-party
contradiction -> CURRENT at lower confidence; reserve NONEXISTENT for claims
with no credible attestation anywhere.

## Step 7: Adversarial Check

For each REMOVE_WORKAROUND / UPDATE_PATTERN finding, search `"{keyword}
regression"` / `"{keyword} still broken"` before recommending removal; counter-
evidence downgrades to KNOWN_BUG.

## Step 8: Verdict per Finding (MANDATORY)

Every finding gets exactly ONE verdict from this set — **never a category name
(e.g. "DOCUMENT") in the Verdict field**; category and verdict are separate
axes, and future runs PARSE the Verdict field. This table, the no-category rule,
the finding format, adversarial check, Sources-Log dates, and Handoffs schema
are the gather-family shared discipline — canonical authority (wins on any
disagreement): `../_shared/gather-conventions.md`.

| Verdict | Meaning |
|---------|---------|
| **ADOPT** | Directly apply only after deterministic qualification evidence was recorded in this same run (a pinned model id, an endpoint, a skill/script change) |
| **QUALIFY** | Do not apply; test a disposable candidate in this same run, then replace with ADOPT, DEFER, or REJECT before presentation |
| **DEFER** | Reason + a **machine-checkable** re-eval trigger (e.g. "gpt-5.6* row appears in pricing.md") — vague "maybe later" is REJECT |
| **REJECT** | Reason logged; similar future findings tagged `[previously-rejected-similar]` |

A finding whose only action is a doc note maps to REJECT-with-reason or DEFER-
with-trigger, NOT a "DOCUMENT" verdict. Can't decide at run time = REJECT.
QUALIFY is provisional: run regression, mutation, replay, smoke, and relevant
authenticated read-only probes without changing live state. Record the evidence
as `PASSED — <command and result>` and resolve the verdict in the same run;
never deploy an edit merely to observe it.

Final finding fields use the canonical spellings:

```markdown
- **Verdict**: ADOPT | QUALIFY | DEFER | REJECT
- **Trigger**: [machine-checkable event; required for DEFER, omitted otherwise]
- **Qualification**: PASSED — <command and result> | not-applicable — <reason for DEFER/REJECT>
- **Verified**: [yes — source and target read]
```

## Step 9: Present and Apply

Present only final findings via AskUserQuestion. **NEVER auto-write.** QUALIFY is
not applied and must be resolved first. After approval of ADOPT findings: read
the target file, confirm its recorded qualification evidence, make the edit,
re-read to confirm persistence, and leave it uncommitted for user review.

## Step 10: Report Maintenance + Persist Baselines + Codify Improvisations

Update `~/Documents/knowledge-base/research/<vendor>-intelligence.md` (structure
below; snapshot before modifying): rotate the metadata block, move acted-on
findings to Archived, reject legacy calendar-observation state or unresolved
QUALIFY verdicts, and refresh the per-channel Sources Log. Re-run deterministic
qualification without applying the edit and resolve ADOPT, DEFER, or REJECT in
the same run. Then:
- **Persist diff baselines as FILES, not counts.** Any run-over-run diff channel
  (grok llms.txt section list, openai llms.txt link list, gemini pricing table)
  MUST write its full artifact to
  `~/Documents/knowledge-base/research/baselines/<vendor>-<artifact>-YYYY-MM-DD.txt`
  — a count in the Sources Log is NOT diffable on run 2. First run ALWAYS
  establishes the baseline (fetch + persist IS establishing it; never defer a
  baseline to "next run"). **Commit carve-out:** these baseline files are
  content-free machine artifacts and ARE committed with the report in the same
  PR — they are the ONE exception to Step 9's "leave uncommitted"; the report's
  findings still go up for user review before their edits land.
- **Codify run improvisations in the SAME run.** If this run improvised a better
  query/tool/workaround than the documented procedure, patch
  `references/<vendor>.md` or `scripts/` now — a Sources-Log-only improvement is
  re-derived from scratch next run.

## Report structure

```markdown
# <Vendor> Intelligence
## Metadata        (run date, window, probe result, sources, verdict counts;
##                  STALE-if-run-date>30d banner for out-of-skill consumers)
## Active Findings (canonical finding format: Category / Source / Baseline ref /
##                  What changed / Recommended edit / Verdict / Trigger /
##                  Qualification / Verified)
## Watching        (upstream items tracked across runs, with machine-checkable triggers)
## Channel Changes (optional; REQUIRED when a standing channel's format/location/
##                  marker drifted this run — one line each: channel, what drifted,
##                  where it was codified. Makes OUR-side drift diffable run-over-run
##                  instead of living only in git diffs of references/)
## Handoffs        (target-skill | finding | source — e.g. [cross-vendor] Vertex
##                  EOL dates -> gather-claude; [SECURITY-ADVISORY] -> /security-alerts)
## Archived        (acted-on findings)
## Sources Log     (per-channel last-successful-fetch date + marker check; skips logged;
##                  probe identity evidence — version/fingerprint/created per pin)
```

---

# Examples

### Example 1: Routine sync
`/gather-vendor openai` — probe confirms gpt-5.5-pro PRESENT (canonical);
changelog since last run has 2 API changes, 1 affects the rater; deprecations
page clean for our pin. 4 findings -> 1 ADOPT, 2 DEFER-with-trigger, 1 REJECT.

### Example 2: Retirement caught
`/gather-vendor grok models` — probe returns SILENT REDIRECT on a pinned arm
-> `[PINNED-MODEL-RETIREMENT]` HIGH; deprecations page names the successor;
ADOPT: update the roundtable adapter pin + re-run its golden test.

### Example 3: Flagship currency
`/gather-vendor gemini` — probe enumerates the full pro-tier; a newer pro
generation than the recorded flagship appears -> NEW_FEATURE (panel arms must
be best-in-class per `rules/best-in-class-for-cross-model.md`). ADOPT: update
the flagship record.

# Success Criteria

- Vendor resolved; `references/<vendor>.md` loaded before any fetch
- Probe ran with the Step-1 LIVE pins (not DEFAULTS); every pin PRESENT or a finding exists
- Standing channels swept with per-channel marker assertions + per-channel dates
- Diff baselines persisted as committed files (not counts)
- Every finding carries a final Verdict (never a category); QUALIFY was resolved
  in the same run and no change was applied merely for observation
- Report updated + snapshot saved; changes left uncommitted
- Run improvisations codified into references/<vendor>.md the same run
