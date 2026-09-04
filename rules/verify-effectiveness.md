@rule verify_effectiveness
@version 2026-08-06
@scope every behavior, configuration, infrastructure, rule, hook, skill, or measurement change

# Verify Effectiveness

Passing syntax or unit tests proves only the surface those checks exercised.
Completion requires evidence that the requested outcome works through the
real entry point without unacceptable regression.

## State and evidence contract

Keep these states distinct:

`source/configured/deployed/live/measured`

- Source: bytes exist in a working tree.
- Configured: the intended runtime references those bytes.
- Deployed: the bytes reached the target host/service.
- Live: the current process/session loaded them.
- Measured: a fresh observation exercised the requested outcome.

The ladder runs BOTH ways: `source -> live` is the familiar failure ("I merged
it, so it is deployed"); `live -> source` is its mirror — an out-of-band fix that
WORKS but was never committed, so the next apply reverts it.

REQUIRED after any change applied outside the normal commit path — a console
edit, a CLI mutation, a `terraform apply` from a local tree, a hand-run script:
confirm the change exists in source AND is committed before calling it done.
`git log`/`git grep` on the target file is the check. If it is not committed the
work is not finished; say so rather than reporting the measured outcome alone.

GUARD pattern="I verified it live, it works" or "the fix is deployed and
confirmed": state the SOURCE status in the same breath as the live status. Two
states, two sentences. NO EXCEPTIONS.

  # Full: incidents#2026-08-15-source-and-live-drift-in-both-directions

Never promote evidence from one state into another by inference. Every claim
names its state, mechanism, timestamp/freshness, target, and limitations.

## Required validation

For every behavior change perform both:

1. Plumbing verification — syntax, schema, wiring, imports, registration,
   unit tests, and expected files.
2. Outcome verification — exercise the public/runtime entry point with a
   known-positive and, where meaningful, known-negative oracle.

Use fresh verification from the current change. Historical green results,
generated documentation, and a child agent's completion message are leads,
not closure evidence.

## Rehearsals must not supply what the real invoke omits

A dry run that passes an argument the scheduled/production invoke does NOT pass
exercises a DIFFERENT code path, and the untested path is usually the defaulting
branch where the interesting bug lives. Before trusting a rehearsal, diff the
rehearsal's inputs against the real caller's and name every parameter the real
caller leaves unset.

Also enumerate the COLD states, plural. A guard on "state absent" does not cover
"state present but sentinel/zero", and infrastructure that SEEDS a placeholder
creates exactly that third case.

## A reporting lane's first real OUTPUT is a verification step

For anything whose product is a rendered artifact a human reads — a chat message, a
digest, an alert card, a report — read the FIRST real delivered output before calling it
verified; schema, plumbing, and unit tests assert the parts, and the defect is in the whole.

## Multi-seam changes

A multi-seam feature spans independently deployed or owned components: code
and IAM, producer and consumer, hook and settings, generator and artifact, or
source and a long-lived process. Test each component and the end-to-end seam.
Component-green is not system-green.

For runtime delivery, verify all applicable transitions:

`commit -> origin/default -> target bytes -> process/session reload -> behavior`

A probe must exercise the DEPLOYED CODE PATH, not a fresh equivalent of it. A
new client/connection/session constructed by the probe reports the LIBRARY DEFAULT
and says nothing about the configured runtime. Import the module and call its
accessor, or attach to the running process; never re-implement the setup you are
trying to verify.
Full: incidents#2026-08-16-probe-constructed-its-own-connection

An ABSENT check is not a passing check. A CI job that fails BEFORE creating any
job produces no logs and does not appear in the check list, which reads as "not
applicable to this repo" rather than broken. Before citing a named check as
passing, confirm that check appears by name; when a linter job fails, separate
ERROR from WARNING counts before concluding a fix did not work.
Full: incidents#2026-08-16-absent-check-read-as-passing

### 4th shape: a seam NO instrument you have can cross (n=4 for multi-seam)

The three recorded shapes -- seam-LOGIC, DEPLOY-BOUNDARY, STUBBED-SEAM -- assume you
COULD have tested the seam; the fourth is the one where you cannot, and every layer
you CAN test goes green. A probe that receives your output cannot validate a CONTRACT
that a different consumer enforces.
Full: incidents#2026-08-26-seam-no-instrument-can-cross

REQUIRED: when the last hop needs an instrument you do not have, say so as a BLOCKING
gap BEFORE claiming the feature works -- "this is unverified and needs you to click
it", above the summary, not as a footnote under a success report.

GUARD pattern="the direct-invoke E2E is green, so the feature works":
  Name every consumer that PARSES the output and ask which of them your probe was.
  If a consumer enforces a contract your probe does not check, the seam is UNTESTED.
  NO EXCEPTIONS.

## Instruments and measurements

When the triggering condition is TRANSIENT, capture the known-positive control
WHILE it still holds; once it clears you can construct synthetic controls but can
no longer confirm the detector fires on the genuine article. Grab the control
first, then build the fix.
Full: incidents#2026-08-17-transient-control-not-captured

Before relying on an instrument, prove it against a synthetic known-positive
whose expected value is known independently. Confirm pagination, caps,
filters, time windows, identity mapping, output stream, error rows, and the
final process exit status. Zero hits from an unqualified instrument mean
unknown, not absence.

A MULTI-GATE probe with a placeholder input tests only the FIRST gate: validation
SHORT-CIRCUITS, so a dummy value that fails gate 1 means gates 2..N were never
reached while the report shows N rows, N statuses, and N distinct-looking verdicts.
REQUIRED: order the gates, then satisfy every earlier one so the probe arrives at the
gate under test; if two rows produce the same error text, they are one gate.
The INVERSE also misleads: a projection that omits the discriminating field
manufactures a finding, and a checker whose INPUT was never produced reports a
confident zero. Print the field that would DISTINGUISH the rows, and assert the
input exists before believing a count of it.
Full: incidents#2026-08-26-placeholder-probe-tests-only-the-first-gate

Before publishing a benchmark or baseline:

- record the instrument and its qualification evidence;
- preserve failures/refusals/fallbacks rather than dropping rows;
- run enough repetitions to characterize variance;
- validate the comparator through the same surface;
- tag model/provider/effort/configuration when an LLM participates;
- separate observed counts from estimates and derived quantities.

Measure distributions before choosing thresholds. A round number or one
sample is not a calibrated boundary.

A REVOCATION rehearsal needs three observations, not one: (1) the SAME credential
accepted BEFORE the revocation, (2) that credential refused after, and (3) a
FRESHLY issued credential accepted after. Without (3) an outage reads as a
successful kill switch. Also test the INTERMEDIATE state; that is what falsifies a
one-step runbook.
Full: incidents#2026-08-25-secret-rotation-revoked-nothing

### Verify the instrument before fixing the subject

When one contingency-table cell holds 30% or more of the failure mass, sample 3-5 of
its edges, open the cited source for each, and classify REAL, INSTRUMENT, or UNCLEAR
before designing any fix: 3 of 5 INSTRUMENT means fix the harness and re-run; 3 of 5
REAL means fix the system; mixed means split the cell. Before claiming "+X pp", prove
baseline and treatment used the same instrument version, oracle rules, sampling
defaults, and index; re-baseline after any instrument change, and re-run a baseline
older than 24 hours. For an alarm whose metric a verifier you wrote produces, verify
the verifier first — its input artifact exists with the expected units, its logic
re-run by hand agrees, and the producer finished before it ran; while the producer is
unfinished emit INCONCLUSIVE and no metric. Code younger than the failure cannot be
its cause. If the authoritative instrument is unavailable the verdict is UNKNOWN; a
reachable proxy is context after that, never the headline. When a gate reports a
failure or an implausibly clean pass, check its own call plumbing first — argument
shape, `rc=$?` captured before any `$(...)` on the same line, and zsh's unsplit
variables — because a mis-called gate is an instrumentation error, not a finding.

## A clean source-vs-data diff is not exoneration — diff against the DEPLOYED code

REQUIRED: for a failing data-vs-code contract, download and read the DEPLOYED artifact
(`aws lambda get-function --query Code.Location`, the running image, the live task
definition), not the repository. A source-vs-data match narrows the fault TO the deployed
rung rather than clearing it.

## A test that RE-IMPLEMENTS the path it verifies is not testing that path

If a test rebuilds the sequence under test rather than invoking it, it verifies your MODEL
of the code, not the code. Stub the boundaries, not the logic — and prove the choice by
mutating the real path and requiring red.

## Artifacts and transformations

For a rewrite or format conversion, compare the field union, not a hand-picked
subset. Verify identifiers, values, counts, ordering requirements, binary or
track-change preservation, and any schema/runtime consumer. A self-authored
grep that mirrors the generator is not an independent oracle.

After batch edits, reopen representative and boundary targets, compare counts,
run the repository's validators, and inspect version-control state. A command
returning zero does not prove that every intended edit persisted.

An artifact that renders differently for different readers is not a shareable
artifact. PIN AND LABEL the timezone, locale, and any other host-derived
formatting an artifact resolves at view time; never leave a date to the viewer's
local zone. The check belongs in the artifact's own test: render under two or more
host zones and assert the displayed values are byte-identical. Anchor relative
windows ("last 6 months") to an explicit as-of date rather than to `max(data)`.
Full: incidents#2026-08-20-viewer-local-timezone-in-a-shared-report

## Regression and mutation checks

Choose regression tests proportional to blast radius. For a bug fix, prove the
test fails when the fix is removed or mutated and passes when restored. For a
control, test allow, deny, malformed, partial, and fallback states. Avoid
weakening assertions to make a changed behavior green.

## A degrade-then-restore repair must be per-target, never two batch loops

When the fix for N targets is degrade-then-restore — disarm/re-arm, disable/re-enable,
detach/reattach, revoke/re-grant — the targets are STRICTLY WORSE between the phases, and
two batch loops let one environmental phase-2 failure degrade EVERY target at once.

REQUIRED: iterate per target, completing degrade -> restore -> verify for one before
starting the next. A mid-sequence failure then leaves at most one target degraded.

REQUIRED: if the restore phase fails, the degraded state is the headline of the very
next thing you say, naming each affected target. Do not end a turn on a failed
restore — the transcript reads as "work in progress" while the durable state is
"protection removed."

REQUIRED on resume, re-read live state. The degrade may have landed, the restore may
have partially landed, and an exit code is not evidence of either.

## Irreversible actions

Do not take an irreversible or externally visible action on a partial review
journal or provisional result. First complete the required scope, reconcile
errors and missing subsets, and verify the final decision artifact.

## Reporting

Report the command/surface exercised, result counts, failures/skips, and
remaining uncertainty. If live access, authority, or an external dependency
is unavailable, mark that state unverified rather than claiming success.

## Re-measure BETWEEN the fix and the next task, not at the end of the arc

The outcome check belongs in the same turn-sequence as the fix that motivated it.
Deferring it to the end of a multi-part arc is the same failure as never running it,
because the intervening work is planned on the assumption that the fix worked.

REQUIRED after any change intended to move a measurable signal, read that signal before
starting unrelated work. State the value and its timestamp. A successful WRITE
(2xx, `success=true`, a green apply) is acceptance of the request, never movement of the
signal.

REQUIRED read the SLOPE, not just the level, when recovery is gradual. A flat series after
a fix means the fix did not reach the population; a rising series means it did and the rest
is propagation. Those demand opposite next actions — keep hunting versus wait — and the
level alone cannot distinguish them.

GUARD pattern="the push succeeded, moving on" or "I'll verify at the end":
  REFUSE. Read the outcome signal now and quote it with its timestamp. The cost of the
  deferred read is every hour of work planned on an unverified premise. NO EXCEPTIONS.

## Optional layers and cleanup end-states

A verification layer that is SKIPPED because its dependency is missing reports the
same exit code as one that ran. A missing dependency must FAIL and name the install
command, not degrade. Do NOT add a bypass flag: a flag set once in a shell profile
restores exactly the hole it was added to close. If a layer is genuinely optional,
its absence must change the reported COUNT and the exit status, never just a log line.
Full: incidents#2026-08-28-skipped-layer-reported-as-passing

An INDETERMINATE cell tallied beside definitive ones is the same hole one layer in.
Split outcomes into DEFINITIVE and INDETERMINATE classes, grade against the EXPECTED
target set rather than the attempted one, and make any errored, skipped, or
never-attempted cell a NON-ZERO exit. Report every zero WITH its bound ("0 against a
14-id set enumerated at 23:41Z") — a count with no denominator cannot distinguish
complete from partial. Measured 3x across domains; narrative in
`rules/incidents/verify-effectiveness.md`.

GUARD pattern="every mailbox/row/target it checked came back clean, so we are clean":
  REFUSE. Compare MEASURED against EXPECTED before reading a zero. An errored,
  skipped, or never-attempted cell makes the run INCOMPLETE, and an incomplete run
  has no all-clear to report. NO EXCEPTIONS.

Verify a CLEANUP or teardown path by its END STATE, not by each step succeeding. A
delete against an already-absent resource is the EXPECTED condition on a retry, so a
step-wise fail-fast turns a partially-completed teardown into a permanently
unresumable one. Make each delete tolerant, then read the world back and fail on
what SURVIVED. The verdict is the post-read, not the sequence of API acknowledgements.
Full: incidents#2026-08-28-teardown-verified-by-end-state

## When two artifacts must agree, assert the RELATIONSHIP, not two literals

A test asserting the same literal on both sides PASSES the lockstep edit that is the
normal way such a pair changes. Derive one side from the other, add a VACUITY FLOOR to
any per-item loop (an empty collection prints `0 mismatches of 0 checked`), and mark a
deliberately kept magnitude literal as a TRIPWIRE naming what to re-verify when it moves;
a comment claiming two files "cannot drift" is not a check.
Full: incidents#2026-08-29-pinned-pair-passes-lockstep

Detailed incident mechanisms, domain-specific measurement traps, and worked
examples live in `rules/incidents/verify-effectiveness.md` and are loaded on
demand for diagnosis.

## A read-back proves the TRANSPORT, not the freshness of your INPUT

Byte-identity after an upload compares the artifact to what you SENT, not to what
was current. Re-resolve the ref in the SAME sequence as the upload. A diverged
checkout is an invalid comparison BASELINE, not just an unsafe ship base.

GUARD pattern="read-back matched, the upload is verified":
  REFUSE. Name the resolved ref and re-fetch it in the same sequence. NO EXCEPTIONS.
GUARD pattern="I already fetched at the start of the session":
  REFUSE. Merges land between fetch and upload; re-resolve immediately before.

## Greening a red gate by narrowing its detector

When a check is red and the available fix NARROWS what the detector looks at,
enumerate the FULL population before adopting it. A narrower detector turns the
gate green by reducing coverage, which is worse than the gap it closed and
leaves no signal that coverage moved.

REQUIRED: build the truth table over every member of the population, not the
offending subset. Adopt the narrowing only if it reproduces the intended
membership EXACTLY; if any legitimate member falls outside it, the narrowing is
refuted regardless of how principled the discriminator looks.

Where the offending members cannot be resolved in the same change — because
resolving them needs an owner decision or data you would have to invent —
BASELINE them explicitly and gate the DELTA: record the known set in a named
constant, print it on every run, and add a test that fails when an entry goes
stale. A silently-subtracted baseline is a coverage lie; a printed one is a
backlog. Never raise a threshold or delete an assertion to accommodate a write.

  # Full: incidents#2026-08-29-greening-a-red-gate-by-narrowing-its-detector
