# Report Format and Lifecycle

## Report Location

`$HOME/Documents/knowledge-base/research/claude-code-anthropic-intelligence.md`

Living document. **Snapshot convention RETIRED 2026-08-22:** the report lives in a
git repository and every run ships as a PR, so each pre-run state is already
recoverable via `git log -- research/claude-code-anthropic-intelligence.md`. The
manual `YYYY-MM-DD-anthropic-intelligence-snapshot.md` copies duplicated that and
the convention was dead in practice — no run after 2026-08-12 saved one and
nothing was lost. Existing snapshot files stay as historical artifacts; do not
create new ones.

## Report Structure

```markdown
# Claude Code Anthropic Intelligence
## Metadata
## Active Findings (by section)
## Watching (open issues/PRs we track)
## Known Issues (open bugs + our workarounds)
## Learning Resources
## Archived (acted-on findings)
## Sources Log
```

The top-level `##` sections above are the file layout. Inside
`## Active Findings`, group entries under the five `###` subsections named
in Step 14 ("Architecture Debt", "Action Required", etc.) — those are
categories of findings, not top-level report sections.

## Metadata Header (Step 14)

```
Run date: YYYY-MM-DD | Claude Code version: vX.Y.Z
Time window: {since_date} to today
GitHub: N issues searched, N deep-fetched
Web: N pages extracted
Phase A: N workarounds audited (N FIXED, N CHANGED, N CURRENT)
Phase B: N findings after dedup
Cross-refs: N community-confirmed, N research-validated
```

## Active Findings Subsections (Step 14)

Use these as `###` headings inside the `## Active Findings` report section —
the top-level file layout is defined by "Report Structure" above:
1. Architecture Debt (REMOVE_WORKAROUND + Phase A stale items)
2. Action Required (UPDATE_PATTERN + DEPRECATION)
3. Opportunities (NEW_FEATURE + CONFIGURATION)
4. Known Issues & Incoming (KNOWN_BUG + INCOMING) — duplicate into
   `## Known Issues` for open bugs we still work around
5. Learning Resources (TRAINING) — also appears as `## Learning Resources`
   when entries warrant a standalone top-level section

## Canonical Finding Format (Step 14)

```
### [#N] [HIGH/MEDIUM/LOW] Title
- **Category**: ...
- **Source**: [URL or issue/PR number]
- **Baseline ref**: [file + section]
- **What changed**: [1-2 sentences]
- **Recommended edit**: [specific file + change]
- **Verdict**: ADOPT | QUALIFY | DEFER | REJECT (from Step 12b)
- **Trigger**: [machine-checkable event; required for DEFER, omitted otherwise]
- **Qualification**: PASSED — <command and result> | not-applicable — <reason for DEFER/REJECT>
- **Verified**: [yes - read target file, confirmed claim]
```

This finding format is the canonical schema for the `Active Findings` and
`Archived` sections of the report; subsequent runs (Step 5 in "Subsequent
Runs" below) parse the `Verdict`, `Trigger`, and `Qualification` fields. All
required fields must be present in the exact spelling shown. Do not apply
QUALIFY; resolve this provisional verdict to ADOPT, DEFER, or REJECT in the same
run before the report is presented.

### Field GRAMMAR that `report_lifecycle.py` enforces (measured 2026-08-30)

The spellings above are necessary but not sufficient — the gate parses these fields
and rejected **7 findings** on one run's first draft, then 1, then 1. Writing them
correctly the first time is cheaper than three reconcile passes:

- **`Verdict` must be the BARE token.** `DEFER — verdict corrected during application`
  fails. Put any explanation on its own following line, not after the token.
- **`Qualification: PASSED — …` must contain a SUCCESS_RESULT token**, and the
  recognised forms are narrow: `rc=0` / `exit 0`, `N tests passed` (digits, then
  optional `tests`, then the word **`passed`** — "1831 hook tests **pass**" does NOT
  match, nor does "1831 **hook** tests passed", because the words between the number
  and `passed` must be only `test`/`tests`), or `<overall|final|integration|suite|command|control> passed`.
- **A clause containing a failure word or a nonzero exit needs `expected` or
  `negative control` IN THAT CLAUSE.** Clauses split on `.` or `;` + space. So
  "a deliberately unclosed block fails, rc=1" is rejected unless the same clause says
  it is the expected negative control.
- **A risky clause also forces a SUCCESS token in a DIFFERENT, non-risky clause.**
  Having only `rc=0` inside the same clause as the `rc=1` control fails — add a
  separate sentence such as "the control passed."
- **These tokens are BANNED anywhere in `Qualification`**: `pending`, `not run`,
  `unverified`, `todo`, `tbd`, `unknown`. "DEFER pending authorization" fails; write
  "DEFER; this awaits an operator decision".
- **`Verified` must start `yes —`** (or `yes -`) and must not contain `no evidence`,
  `pending`, `unverified`, `not checked`, `unknown`, `could not read`, `failed to read`,
  `unable to read`. To state an honest limitation, describe it without those words:
  "the behavioural path was NOT exercised — macOS has no `HKLM:` provider" passes.
- `not-applicable — <reason>` is the only accepted non-PASSED form, and it must also
  avoid the banned tokens and failure words.

The gate parses both dated and legacy numbered active headings. Every canonical
field shown above except the conditional `Trigger` is required. `Verified`
must contain concrete evidence rather than `no`, `pending`, `unknown`, or a bare
`yes`. A `PASSED` qualification must name the successful command/result; label
an expected non-zero negative control explicitly so it is not mistaken for a
failed overall qualification. The heading must carry `HIGH`, `MEDIUM`, or
`LOW`; malformed finding-like headings fail closed. Move unreconcilable historical numbered findings
under `## Archived` without rewriting their evidence.

## Subsequent Runs

1. Confirm the pre-run report state is on origin (`git log -1 -- <report>`) —
   git history is the snapshot (manual snapshot files retired 2026-08-22)
2. Move acted-on findings to Archived
3. Check Watching items (closed/merged? promote to Active)
4. Check Known Issues (fixed? promote to REMOVE_WORKAROUND)
5. Run `report_lifecycle.py` and reject any legacy calendar-observation state,
   missing/invalid required field, or unresolved QUALIFY. Re-run deterministic
   qualification without applying the edit, then record ADOPT, DEFER, or REJECT
   in the same run. Never use a live edit as the qualification environment.
6. Add new findings, refresh Sources Log, update metadata

## Watching hygiene

The Watching table is the per-run working set: Step 1b re-checks every row
against issues closed since the last run. Left ungroomed it grows unbounded
(closures get archived, but open-and-not-affecting-us rows never age out), so
incremental runs end up re-checking dozens of rows that cannot change.

**Dormant Watching appendix.** Keep the live `## Watching` table to rows that
can still plausibly affect us, and move the rest to a `## Watching (Dormant)`
appendix that is **re-scanned only on `full` runs**, not on incrementals. This
keeps the incremental working set tight WITHOUT losing coverage — a dormant row
is still a tracked row, just not re-checked every short run.

Move a row to Dormant when ANY holds:
- It is tagged `[WIN-ONLY]` / locally-retired (host no longer matches the
  platform — upstream-open but it cannot affect this deployment).
- It has been OPEN and **untouched for >90 days** AND is not-currently-affecting
  us (no local repro, no mitigation we depend on).
- Its canonical issue migrated and the row is a pure pointer with no distinct
  signal of its own.

Do NOT move a row to Dormant if we maintain a live mitigation keyed to it, if
it is `[INSTALLED-VERSION-REGRESSION]` on the current version, or if it is in an
active cluster (fabrication, malformed-tool-call, transcript-loss). On a `full`
run, re-scan Dormant and either close (if the upstream issue closed) or restore
to live (if it became relevant again — e.g. a retired platform is back).
