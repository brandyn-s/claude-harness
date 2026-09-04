# capture — run history

Dated incidents behind the rules in SKILL.md. The rule lives in SKILL.md; the
evidence lives here.

## Step 0 — in-flight prior-session work

- 2026-05-28: the /retro session found the KB repo on
  `capture/bedrock-bearer-token-jamf-ongoing` with uncommitted work alongside the
  current session's intune-mde topic. Without the preflight, /capture either
  hijacks the prior branch (bad) or silently dances around it (what happened —
  worked but wasted turns).
- 2026-07-28: `kb-capture-20260728` was already taken by a parallel session, on a
  different branch; `worktree add` failed on a path another live session owned,
  costing two retries. The date alone is not unique; sessions are.

## Step 1 — transcript selection (2026-06-25)

`ls -t` grabbed a parallel session's 88MB/11-compaction transcript; the real one
was 760KB. Select by this session's id, not by mtime.

## Step 4 — pre-write budget (2026-07-28)

Three entries were written, then rejected by `kb.py check` at 3,525c / 3,601c /
3,115c, then re-split — and the same run also had to retro-fit a
`## Current understanding` because the append silently crossed 8 entries. All
four facts were knowable before the first Write.

## Step 4 — a new page's initial stage (2026-08-15)

A new page shipped with 5 entries and `stage: seedling`; /garden promoted it 20
minutes later. The bands read as append-only, so nothing was violated — that WAS
the gap. The same run also caught a skipped Step 4b MoC placement and two
un-bumped `updated:` fields (execution misses of steps already documented).

## Step 4a — contradiction check

- INCIDENT 2026-05-10 (D1 surprise positive vs A4 prior diagnosis): D1's measured
  +0.036 golden MRR contradicted A4's earlier "Voyage doesn't weight identifier
  tokens enough to move retrieval" diagnosis. /capture wrote the new D1 entry but
  did NOT back-annotate A4's findings doc with `[Superseded]`, so future readers
  of A4 see the falsified diagnosis as still-current. The Corrections prose was
  not a structural gate; Step 4a made it one.
- 2026-06-11: a 2-claim SCP entry's *second* claim was backwards and the refuting
  same-page evidence sat at 0.52 cosine, below the gate, because only the
  headline claim was queried. Hence one opposite-query per distinct factual claim.
- INCIDENT 2026-06-11: a shipped SCP entry asserted `aws:PrincipalArn` is the
  assumed-role STS form — backwards (it is the role ARN); the cosine gate didn't
  catch it and it needed a correction PR (#763). Hence the vendor-behavior source
  check.

## Step 4a.1 — resolution sweep (INCIDENT 2026-06-07)

The messages-empty gap stayed documented as open in two topics until Step 4a
happened to fire on a same-page write. The corpus's many reactive
`[Superseded]`/`[RESOLVED]` annotations are the rot this sweep prevents.

## Step 4a.2 — re-budget after regenerating Current understanding (2026-08-30)

The entry itself budgeted clean (largest chunk 1,082c), then a 6-line CU
paragraph took the `Is this the system, or the instrument?` sub-section from
2,189c to **3,245c** — past the 3,000c hard limit. The fix was the same `###`
split the checker recommends, cheap only while the text was still in hand.

## Step 4c — Keychain identifiers (2026-06-15)

A backfill caught 2 error-message IDs (AADSTS700016 "client ID … not found" /
"tenant not registered") that would have been stored as working credentials.

## Step 5 — push flow

- 2026-08-17, both fast-forward shapes observed: the first ff had incoming edits to
  all three compiled files (`generated/`, README.md, Home.md) and needed the
  discard; the second was `plans/`-only and fast-forwarded straight through.
  Doing the check proactively costs 3 read-only commands; reactively it costs a
  worktree, a `--theirs` checkout, a rebuild, a merge commit, and a re-armed PR.
- 2026-08-22: an append-vs-append conflict on `verification-instrument-discipline.md`
  — a parallel session captured to the same topic the same day.
- 2026-07-22: resolving a DIRTY PR in the shared checkout was blocked by other
  sessions' dirty topic files; resolve in a worktree off the capture branch.
