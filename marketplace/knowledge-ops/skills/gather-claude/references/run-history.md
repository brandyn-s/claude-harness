# gather-claude — run history

Dated measurements and incidents that produced the rules in SKILL.md. Each
section is cited from the step it explains; the rule itself lives in SKILL.md,
the evidence lives here.

## Step 0b — worktree preflight

- 2026-08-08: edits applied in place were reverted by a concurrent session's
  whole-file re-serialization of `settings.json` — a file the other session was
  editing for unrelated reasons. "The tree is dirty but my edit is small /
  touches different files" is not a reason to skip the worktree.
- 2026-08-11, 08-12, 08-21: three consecutive runs found claude-config dirty AND
  diverged, and each one rediscovered it at Step 15 instead of Step 0. That late
  discovery is the main reason the adoption metric sits near half.
- 2026-08-22: `~/.claude` HEAD was behind `origin/main` and the working tree was
  diverged from both — a THIRD, stale intermediate. The run had to extract and
  execute origin/main script content from /tmp. Hence the deployed-skill
  freshness check.

## Step 1b — Watching-table reconciliation

**Row classification moved into `reconcile_watching.py` (2026-08-22)** after a
third consecutive run hand-derived the same PRUNABLE / ANNOTATE / EXPECTED
RESIDUE split. History of the failure it prevents: 2026-08-06 "prune 10" reached
a user-facing plan when 0 rows were prunable; 2026-07-24 same finding;
2026-08-22 17 flagged, all residue. Tests:
`test_reconcile_watching.py::ClassifyClosed`.

**Retired bulk `closed:>=DATE` intersection (Step 1b through 2026-07-20).**
Earlier runs intersected the Watching set against
`gh issue list --search "closed:>=<last-run>"`. That query's cost scales with the
REPO's closure volume, not our ~128-number Watching set, and
anthropics/claude-code runs stale-bot mass-triage waves that close hundreds of
issues per day — so the list truncates before the relevant closures are even on
the page. Observed: limit-capped at 100 (2026-06-11 — #58682 missed at item 100),
returning 0 at limit 500 (2026-07-18), capped at 400 (2026-07-23 — the GraphQL
batch found 12 closures the bulk cut surfaced only 2 of, including 3 standalone
rows the run had otherwise missed). No `--limit` fixes a query bounded by the
wrong thing.

**Watching-set extraction (2026-06-16).** Hand-typing ~85 issue numbers into the
script is the one place a typo silently drops a closure (→ stale Watching → a
workaround kept for an already-fixed bug). `parse_watching.py` extracts from the
table's Item column only (2026-07-05 fix — whole-section extraction
over-captured inline issue/PR references embedded in row prose, e.g. `PR #1489`,
inflating a 90-row set to 120; the 2026-07-03 run had to re-derive the
column-only set by hand with awk).

## Step 3 — CHANGELOG parse

The version-split regex was once hardcoded to `2\.1\.\d+` and silently left the
entire CHANGELOG as one unsplit blob when the version moved to 2.2.

## Step 4 — label queries

A Windows-era `platform:windows` query ran for weeks on a macOS host and missed
macOS-labeled regressions; the platform label must match the host. The
`regression`, `data-loss`, `api:bedrock`, and `area:security` labels were added
2026-07-05.

## Step 4b — security advisories (added 2026-07-05)

30 published GHSAs existed — including a HIGH sandbox escape via git-worktree
path confusion, the exact isolation mechanism this architecture depends on —
while the report contained zero advisory mentions. Cost: one `gh api` call per
run.

## Step 5 — retired 2026-08-02

Pain-Correlated Search was skipped or substituted in **6 of 15** recorded runs
(40%, the highest of any step), always with the same correct justification — the
area sweeps already covered it. The 2026-08-01 findings actually came from the
architecture-keyword sweeps that are now part of Step 4. Evidence and the general
rule: `run-metrics.md` "per-step SKIP RATE".

## Step 7b — release channels added 2026-07-05

- API SDK releases: the Sonnet 5 `temperature` removal 400'd our Bedrock
  detector before any covered source carried it.
- MCP spec releases: the 2026-07-28 protocol revision RC shipped 2026-05-29.
- npm dist-tags: `stable` 2.1.193 vs `latest` 2.1.201 observed 2026-07-05.

## Step 8 — docs inventory

- Firecrawl for Mintlify: `tavily_extract` returned nav-shell /
  `Content: undefined` on every extract until the 2026-07-05 routing fix.
- Page-list persistence was mandated 2026-07-05 and executed by ZERO runs, so the
  page-set diff had never once been derivable (measured 2026-08-22: no baseline
  file existed). `fetch_window.py` now writes the baseline itself.
- 2026-08-06: a keyword grep over the new inventory produced "+2 new pages"; the
  inventory had actually gone 180 → 176 — a NET LOSS of 4, including
  `ultraplan.md`, which the CHANGELOG independently confirmed as a removed
  feature. The removal was the real finding and the grep could not have found it.
- 2026-08-22: the hand-grep for already-covered issue numbers missed one that
  `--dedupe-against` catches.

## Step 8b — first-party release-notes sweep (added 2026-07-05)

The Fable 5 suspension/restoration, the Sonnet 5 parameter deprecations, and
every Admin-API endpoint migration were published ONLY in these channels. The
Desktop-3P surface (added 2026-07-16): M365 write tools (2026-07-07), the
websearch built-in (2026-06-25), and the `isDesktopExtensionEnabled` default flip
shipped ONLY in the Desktop-3P config changelog.

## Step 12a — report lifecycle

All four checks the script now performs failed on 2026-08-01 when they were
prose. Why that generalises: `run-metrics.md`.

## Step 12b — overlapping-setting DEFER rule (measured 2026-08-30)

`promptCacheTtl` / `subagentPromptCacheTtl` (v2.1.243) were graded ADOPT and
applied to the LIVE settings while `env.ENABLE_PROMPT_CACHING_1H` was already set
and `FORCE_PROMPT_CACHING_5M` also exists — with no source stating precedence. So
`subagentPromptCacheTtl: "5m"` may have SHORTENED subagent caching rather than
preserving it: an unmeasured cost/latency regression, shipped in the run whose
own headline finding was a cost control silently breaking. Both keys were
reverted the same day and re-graded DEFER. The tell to catch it earlier: the
finding's "What changed" called them "finer-grained successors" to the env var —
an inference stated as fact, with nothing read this run establishing that they
supersede rather than conflict.

## Step 15 — re-check upstream before applying (2026-08-08)

A `cc-monitor` eval repair was real against the local checkout AND
mutation-verified 8 BITES / 0 misses — yet was already obsolete on arrival:
#1930/#1922 had rewritten skill and eval together and the gate was 9/9 green
upstream. Applying it would have overwritten a CURRENT eval with one written
against older content. The mutation evidence was sound and measured the wrong
baseline, which is why "I verified it" does not cover this.

## Step 16 — codify improvisations; close the worktree loop

- 2026-07-05 audit: three run improvisations — `platform:macos` in the label
  sweep (2026-06-11), Item-column Watching extraction (2026-07-03),
  firecrawl-for-Mintlify (2026-07-03) — were each documented in Sources Logs but
  never codified; the spec kept the stale versions and later runs re-solved the
  same problems.
- 2026-08-22: FIVE gather-claude worktrees existed, at least one
  (`gc-skill-improvements`) matching an already-merged PR; each run that skips
  cleanup leaves the next run to re-classify the sprawl.
- Adoption metric: `≈6/≈17` rode forward unchanged across four runs, creating no
  pressure to re-evaluate the DEFER list.
