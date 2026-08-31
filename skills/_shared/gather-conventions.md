# Gather-family shared conventions (canonical)

The execution-independent discipline shared by the upstream-sync skills
`gather-claude` (platform) and `gather-vendor` (openai|gemini|grok). This file
is the **canonical authority** for the items below — when a gather skill and
this file disagree on a field spelling, verdict name, or section schema, THIS
file wins, and the skill should be corrected. Extracted 2026-07-06 so the two
skills cannot drift on the shared surface (they were ~45% textually duplicated;
a red team flagged the drift risk + a live dead-drop between them).

Scope note: this covers only the SHARED, execution-independent discipline.
Each skill keeps its own Phase A/B mechanics (gather-claude's Watching-table /
CHANGELOG / installed-version machinery; gather-vendor's per-vendor probe +
references) — those are NOT shared and are not governed here.

## 1. Verdict set (MANDATORY — the parse surface)

Every finding gets **exactly one** verdict from this set, in the same run it
surfaces (no "decided later" — that produces the opportunity backlog these
skills exist to prevent). Subsequent runs PARSE the `Verdict:` field, so the
spellings are load-bearing:

| Verdict | Meaning |
|---------|---------|
| **ADOPT** | Directly apply only after deterministic qualification evidence was recorded in this same run (a pinned model id, an endpoint, a skill/hook/rule/config change). A doc note is a side effect, not the deliverable. |
| **QUALIFY** | Do not apply. Exercise the proposed edit in a disposable candidate with regression, mutation, replay, smoke, and relevant authenticated read-only probes in this same run; then replace this provisional verdict with ADOPT, DEFER, or REJECT before presentation. |
| **DEFER** | Reason + a **machine-checkable** re-eval trigger (e.g. "gpt-5.6* row appears in pricing.md"). Vague "maybe later" is REJECT. |
| **REJECT** | Reason logged; future runs surfacing a similar finding tag `[previously-rejected-similar]` and deprioritize. |

- **A category name is NEVER a verdict.** `DOCUMENT`, `NEW_FEATURE`,
  `KNOWN_BUG`, `NEW_FEATURE_AUTO` are *categories* (a separate axis). A
  document-only finding maps to REJECT-with-reason or DEFER-with-trigger — never
  a `Verdict: DOCUMENT`. (`NEW_FEATURE_AUTO` — platform applies it for free — is
  ADOPT-by-default; the doc note is the only deliverable.)
- **Can't decide at run time = REJECT** ("no use case identified at run-time").
- **QUALIFY is same-run and pre-application only.** It may exist while the
  current run executes deterministic evidence, but it may not be persisted,
  presented for approval, or used to justify a live edit. A failed or blocked
  qualification becomes DEFER (machine-checkable external trigger) or REJECT.
- **Evidence is terminal, not a placeholder.** `Verified: no`, `pending`,
  `unknown`, and an unqualified `yes` fail the release gate. `ADOPT` requires a
  `PASSED — <command and result>` statement whose overall command succeeded;
  expected non-zero negative controls must be labeled as expected. `DEFER` and
  `REJECT` use `not-applicable — <reason>` unless a real bounded qualification
  was completed.

## 2. Canonical finding format (exact field spellings)

```
### [#N] [HIGH|MEDIUM|LOW] Title
- **Category**: ...
- **Source**: [URL or issue/PR number]
- **Baseline ref**: [file + section]
- **What changed**: [1-2 sentences]
- **Recommended edit**: [specific file + change]
- **Verdict**: ADOPT | QUALIFY | DEFER | REJECT
- **Trigger**: [machine-checkable event; required for DEFER, omitted otherwise]
- **Qualification**: PASSED — <command and result> | not-applicable — <reason for DEFER/REJECT>
- **Verified**: [yes — read the cited file, confirmed the claim]
```

All fields shown above except `Trigger` are required and must use the exact
spelling shown — subsequent runs parse them. `Trigger` is additionally required
for DEFER and must name a machine-checkable event, not a placeholder such as
"maybe later". `Verified` must start with `yes —` and identify the evidence
that was re-read. Expected non-zero negative-control results in an ADOPT
qualification must be tied to their own clause and accompanied by a separate
successful overall/control result. A final report must contain no QUALIFY
verdict: resolve it in the same run before presentation.
The heading severity is mandatory and limited to `HIGH`, `MEDIUM`, or `LOW`;
malformed `### [` finding-like headings fail closed. `PASSED` must contain an
explicit result (for example, exit/rc 0 or a concrete passed-test count), and
`Verified: yes —` text that admits no evidence or pending verification is not
terminal evidence.

The lifecycle reader covers both dated (`### [YYYY-MM-DD]`) and legacy numbered
(`### [#…]`) active findings. Numbered findings do not become exempt from the
schema merely because they predate the dated format; preserve historical prose
under `## Archived` when it cannot be terminally reconciled from evidence.

## 3. Report section schema

```
## Metadata        (run date, window, sources; STALE-if-run-date>30d banner for out-of-skill consumers)
## Active Findings (grouped; each entry in the §2 finding format)
## Watching        (upstream items tracked across runs, with machine-checkable triggers)
## Channel Changes (optional; REQUIRED when a standing channel's format, location,
##                  or marker drifted this run — one line per channel: what drifted +
##                  where it was codified. Added 2026-08-22 after a run where 4 of 6
##                  findings were our-side channel drift with no diffable home.)
## Handoffs        (target-skill | finding | source — see §5)
## Archived        (acted-on findings)
## Sources Log     (per §4)
```

Snapshot the report before modifying on subsequent runs. Reject any legacy
calendar-observation state or unresolved QUALIFY verdict. Re-run direct
qualification without applying the edit, then record ADOPT, DEFER, or REJECT in
the same run; never deploy a change merely to observe it.

## 4. Sources Log — per-channel dates + marker asserts

Record the **last-SUCCESSFUL-fetch date PER CHANNEL** (not one global run date),
so a channel that failed this run re-scans its own gap next run instead of being
skipped past by a global window advance. Each standing fetch asserts a known
content marker; a fetch that returns but MISSES its marker is a dead/rewritten
channel (signal), NOT a quiet vendor — distinct from a transient failure. Log
skips as decisions ("skipped X: reason"), never silent omissions.

## 5. Handoffs — cross-skill finding routing (closes the dead-drop)

A finding relevant to ANOTHER skill goes in a `## Handoffs` table
(`target-skill | finding | source`) AND is acted on by the target skill's
Step-1 baseline read. Standard routes:

- `[cross-vendor]` — a vendor's dated model-EOL that cross-checks another
  vendor's retirement schedule (e.g. Vertex partner-model EOL → gather-claude;
  Bedrock model availability → gather-claude). **gather-claude's Step 1 reads
  the three vendor reports' `## Handoffs` sections** so this lands instead of
  evaporating.
- `[SECURITY-ADVISORY]` — a new nonzero GHSA on a vendor SDK/repo → route to the
  org's security-alert intake (`/security-alerts`), do not dead-end in the report.

## 6. Adversarial check (before recommending a removal)

For each REMOVE_WORKAROUND / UPDATE_PATTERN finding, search `"{keyword}
regression"` / `"{keyword} still broken"` (issue tracker + web) before
recommending removal. Counter-evidence downgrades the finding to KNOWN_BUG. This
prevents a CHANGELOG/docs keyword match from auto-removing a still-live workaround.

## 7. Currency calibration (verify before presenting)

Read the cited page/file; confirm the quote and the "what changed" claim.
Absence of a first-party hit in a *bounded* search is a property of the search,
not the world (`rules/uncharted-vs-refuted.md`): multiple independent credible
sources + no first-party contradiction → CURRENT at lower confidence; reserve
NONEXISTENT for claims with no credible attestation anywhere.

## 8. Codify run improvisations in the same run

If a run improvised a better query/tool/workaround than the documented
procedure, patch the skill's `references/` or `scripts/` in the SAME run — an
improvement that lives only in the Sources Log is re-derived from scratch next
run.

## 9. NEVER auto-write

Present findings with verdicts (AskUserQuestion). Apply only after explicit
approval: read the target, edit, re-read to confirm persistence, leave
uncommitted for user review. (Exception: content-free diff-baseline files — see
each skill's Step 10 — are committed with the report.)
