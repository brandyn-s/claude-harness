---
paths:
  - "**/rules/verify-effectiveness.md"
  - "**/rules/incidents/verify-effectiveness.md"
---

# Verify Effectiveness: Incident Narratives

Extracted from `rules/verify-effectiveness.md`. The parent rule keeps
invariants, procedures, guards, and one-line recovery hints; full
incident narratives live here.

---

## 2026-04-23 code-graph accuracy harness — instrument silent cap produced wrong baseline
<a id="2026-04-23-code-graph-accuracy-harness"></a>
**Anchors:** `instrument_silent_cap_produced_wrong_baseline`,
`prove_the_instrument_before_publishing_the_measurement`

`query_graph` had an undocumented `defaultMaxRows=200`. `compare.py`
retrieved 400 of ~2000 CALLS edges and reported **recall=0.20**. Two
PRs (harness scaffolding, oracle scope refinement) shipped before
sharded queries surfaced the cap. Real recall after bypassing the
cap: **0.98**. 80pp error was 100% instrument.

**Recurring pattern.** Ramp 100-row SQL cap, Voyage batch caps,
CrowdStrike FQL pagination, Graph API server-side filter limits —
tools silently cap, paginate, sample, or filter, turning a "census"
into a "sample" without the caller noticing.

**Recovery.**
1. Add truncation signaling to the tool (PR #65 pattern: `Truncated`
   bool + `EffectiveCap` int in Result, SQL fetches limit+1).
2. Before the next baseline, run on a ≤20-unit fixture with
   hand-verified ground truth and probe every tool for hidden caps.

---

## 2026-05-02 code-graph PR #165 — normalization fall-through to suffix match
<a id="2026-05-02-code-graph-pr-165"></a>
**Anchors:** `normalization_fall_through_to_suffix_match`

PR #165 introduced extractor-side `::` → `.` normalization for Rust
`scoped_identifier` nodes. Intent was to make `Foo::new` resolvable
via existing strategies.

**Effect.** EXTERNAL paths (`Vec::new`, `tracing::info`,
`anyhow::Context::context`) also normalized, then fell through to
project-wide suffix-match which bound them to internal `.new` /
`.info` / `.Context` defs. 155+ phantoms surfaced; aggregate F1
**0.927 → 0.801 (-12.6pp)**.

Reverted in PR #166. Replacement (PR #167) used a dedicated
type-static dispatch strategy with internal-class-membership gate
and DROP-ON-NO-MATCH (no fall-through).

**Lesson.** When adding a normalization that broadens the input
shape reaching downstream filters, gate the new shape on
internal-membership (importBindings, byName-class-label,
registered-module) and drop on no-match. Never let normalized
identifiers fall through to bare-name suffix-match — external paths
phantom-amplify.

---

## 2026-05-17 fastmcp 3.3.1 rollout — compat test used fresh install, not upgrade path
<a id="2026-05-17-fastmcp"></a>
**Anchors:** `compat_test_used_fresh_install_not_upgrade_path`

Ran a compat check in a freshly-built isolated venv (`python -m
venv` + `pip install fastmcp==3.3.1`) — all 8 distinct fastmcp
imports across 13 user MCP scripts resolved cleanly. Confidence:
high.

Then upgraded the 3 PRODUCTION venvs via `pip install --upgrade
fastmcp==3.3.1`. Within minutes, **7 stdio MCP servers disconnected**
with `ImportError: cannot import name 'FastMCP' from 'fastmcp'
(unknown location)`.

**Root cause.** fastmcp 3.3.1 is a namespace package with a sibling
dist (`fastmcp-slim`); `--upgrade` left the package directory in a
partial state that `--no-cache-dir` fresh installs avoid. The
fresh-venv compat test could not have caught this — the install
paths are different.

**Recovery.** When validating a package upgrade, the compat test
MUST replicate the production install procedure end-to-end:
1. Build a throwaway venv that MIRRORS production's prior state
   (install the OLD version first).
2. Run the SAME upgrade command production will run (`pip install
   --upgrade ...`).
3. Verify imports + run a minimal script that uses the package the
   way production code does.

"It imports in a fresh venv" is necessary but not sufficient.

**Prevention.** This rule's "prove the instrument" invariant
generalizes: prove the INSTALL PROCEDURE on a throwaway-but-realistic
fixture before running it on production. See
`rules/platform-constraints.md` GUARD `just pip install --upgrade
<pkg> to the new major version` and FAILURE
`pip_install_upgrade_left_partial_namespace_package`.

---

## 2026-05-03 code-graph PR #172 — re-introduced reverted fix with new infrastructure
<a id="2026-05-03-code-graph-pr-172"></a>
**Anchors:** `re_introduced_reverted_fix_with_new_infrastructure`

Tried re-adding the multi-line whitespace-trim (originally reverted
in PR #166) paired with new Trait/Impl Tier 2 modeling, hypothesizing
the trim's -11pp cost would be eliminated by accepting Trait-method
candidates.

**Result.** Trim still cost **-5.6pp (44 TPs lost)**. The
"Trait/Impl interaction" hypothesis was incomplete — the trim's cost
has more sources.

**Recovery.** When re-introducing a previously-reverted fix paired
with new infrastructure that "should make it safe," measure the fix
ALONE first (with the new infrastructure landed but the revert
un-reverted) to confirm it's actually safer. Don't ship the
combined change without a clean A/B between {old infra + revert} and
{new infra + revert}.

---

## 2026-05-08 code-graph A1 — slog output routing unverified before long measurement
<a id="2026-05-08-code-graph-a1"></a>
**Anchors:** `slog_output_routing_unverified_before_long_measurement`

Plan #459. Added `slog.Info` at resolve-empty exit in
`resolveAsClassWithReason`, built instrumented binary, ran 23-min
CLI-invocation index of PSM.

**Problem.** Slog records went to a stream the Bash tool didn't
capture (only 20 post-index summary lines kept). Could not extract
per-trait-name distribution. **~40 min of session time consumed for
zero captured data.** Pivoted to PR #265's pre-existing 20-trait
sample inference.

A 30-second pre-flight on a tiny synthetic fixture would have
surfaced the routing failure before the 23-min run.

**Recovery.** Emit one expected event on a short fixture, verify it
lands in the capture stream, THEN run the production measurement. If
the pre-flight fails, fix the routing (add `CODE_GRAPH_LOG_FILE`-style
explicit redirect, or capture stderr explicitly) before the long
run.

---

## 2026-04-24 code-graph accuracy session — bucket-count errors before prescribing fixes
**Anchors:** procedure `bucket-count errors before prescribing fixes`

First recommendation round claimed **+5pp** and **+8pp** gains from
hand-picked 10-sample inspection.

**Actual bucket-counted impacts:** ~1pp and ~12.6pp. Off by **5x in
one direction and 1.6x in the other**. The biggest actual gap
(non-callable target FPs, 55.8% of all FPs) wasn't in the original
recommendation list at all.

**Lesson.** Enumerate full FP/FN sets (not a 10-sample slice). Bucket
each into categories by pattern. Report counts and percentages per
bucket. Only then propose fixes — each fix targets a bucket with a
counted size. "This fix will gain ~Xpp" must be derivable from the
bucket size, not asserted.

---

## 2026-04-24 code-graph Rust fixture — aggregate F1 hides per-subset variance
**Anchors:** procedure `per-subset F1 for multi-project fixtures`

Aggregate scope-aligned F1 was **0.825**.

**Per-project breakdown.** 4/5 crates scored 0.984-1.000; 1 crate
(assetman) scored 0.742. The aggregate was essentially "assetman's
F1 weighted by its 76% edge share". "Rust F1 = 0.825" was
misleading — code-graph was perfect on 4 of 5 crates.

Go had **0.54pp spread** (store 0.445, cbm 0.986) hidden by aggregate
0.679.

**Lesson.** Compute F1 per subset (not just aggregate). Report the
spread (min, max, range). If range > 0.15, investigate outliers
individually. If one subset dominates the edge count (e.g., 76% of
total), flag the aggregate as "effectively the F1 of <dominant
subset>".

---

## 2026-06-30 example-requirements — serialization-format churn buried a 13-record edit
**Anchors:** `serialization-format-churn`, GUARD "my script rewrote a
version-controlled JSON/YAML/config file and the diff shows the WHOLE file changed"

Applying the 14 CUT-DUPLICATE refinement verdicts to `requirements/corpus.json`
was a small metadata change: flip `st` to Deprecated + set `cdup` on ~12 records.
The apply script wrote the file back with `json.dump(corpus, f, indent=2)`.

**Effect.** `git diff --stat` showed **42,810 lines changed (21,405 +/21,405 −)**
— the ENTIRE 21,408-line file. Every field of every one of the 285 records
appeared changed, including `stmt`/`title`/`rat` content fields the edit never
touched. On a certification artifact under review, a whole-file churn is
unreviewable and could hide silent content drops.

**Root cause.** The corpus was authored with **`indent=1`** (`{\n "schema_version"`),
but `json.dump(..., indent=2)` re-serialized every line at 2-space indent. The
content of 272 records was identical in meaning but every line's bytes differed.

**The tell + fix.** `git diff -w` (ignore whitespace) collapsed the diff to **98
lines / 49 records** — proving the rest was pure formatting. Byte-diffing an
unchanged record against HEAD showed the first difference at offset 3:
`{\n "k"` (HEAD) vs `{\n  "k"` (mine). The repo's own `export_requirements.py`
used `json.dumps(..., ensure_ascii=False, indent=1)` — the canonical format.
Reset corpus.json to HEAD, re-ran the apply with `indent=1`, and the diff became
the true 13-record change (st/cdup/inc/chg/qrev fields only, no content, no churn).

**Lesson.** Before writing back a tracked JSON/YAML/config file with a script,
match its EXISTING serialization (indent width, `ensure_ascii`, key order,
trailing newline) — ideally by reusing the repo's own writer. Verify with
`git diff -w`: if it collapses to a fraction of the raw diff, the rest is
formatting churn and must be eliminated before commit.

---

## multi-seam-feature judgment reminder (extracted from the parent rule 2026-06-30)
<a id="multi-seam-feature"></a>
**Anchors:** invariant `a_multi_seam_feature_is_not_done_until_one_real_run_crosses_every_seam_to_the_real_sink`

The `multi_seam` invariant now has n=2 across DIFFERENT shapes: 2026-06-22
real-time-credential-render (seam-LOGIC bugs across ~9 fix cycles) and 2026-06-26
detector-expansion (DEPLOY-BOUNDARY omission — `judge_hardening.py` shipped to
`detector/`, wired into the daily entrypoint, but the Lambda Dockerfile COPYs only
`scripts/`, so the fail-loud import crash-looped the deployed judge; `phases_complete=7`
was GREEN because the supergoal metric checked file-existence + repo-tests, and CI
was green because tests run where `detector/` exists; invisible until the Lambda ran).

The pattern RECURRED — exactly the promotion trigger the prior candidate-note named.
Common root: "declared a multi-seam feature DONE on component-green inference (tests
pass + file exists), without ONE real run crossing every seam to the real sink." A
future `mega-distill --corpus` run should confirm breadth before a
`judgment-rules.json` entry, but the recurrence is documented here. Reminder phrasing:
"did one real run cross every seam to the real sink (deployed + wired + invoked), or
just the component you touched?"

---

## 2026-07-26 claude-knowledge-base — a self-consistent check certified a frozen value
**Anchors:** `regenerate_and_compare_proves_reproducibility_not_correctness`,
`self_consistent_check_certified_a_deterministic_bug`,
GUARD "the drift check passes, so the generated output is correct"

The KB integrity migration (#1239) made `tools/kb.py` the sole compiler and gave
`check` a strong-sounding contract: compare all six generated artifacts —
`catalog.json`, `graph.json`, `evidence.json`, `health.json`, `README.md`,
`Home.md` — **byte for byte** against a fresh build, and reject any difference.
It ran in the pre-commit hook and in CI, and it passed.

**The bug it could not see.** `_readme()` re-stamps the index date with:

```python
re.sub(r"(?m)^\*Auto-generated:.*\*$",
       f"*Auto-generated from topic metadata through {source_date}*", current)
```

The pattern requires a colon after `Auto-generated`. The replacement it writes
says `Auto-generated from`. **The regex cannot match its own output**, so the
substitution was a no-op from the very first build. README's date froze at
`2026-07-24` while `catalog.json`'s `source_date` and `Home.md`'s `updated:`
advanced normally.

**Why byte-comparison was blind to it.** `check` compares the committed README
against a *freshly generated* README. Both contain the same frozen date, because
the no-op is deterministic. The comparison is exact, and the check reports
`"schemas and generated artifacts are exact"` — while shipping a wrong value
indefinitely. The check did not merely miss the bug; it **certified** it.

**How an independent review found it in one step.** Set any topic's `updated:` to
a future date and rebuild:

```
catalog.json source_date -> 2026-09-30   (advanced)
Home.md      updated:    -> 2026-09-30   (advanced)
README.md                -> 2026-07-24   (FROZEN)
tools/kb.py check        -> exit 0       (passes)
```

The tell is the divergence between artifacts, which no self-referential check can
surface. Fixed in #1240 by widening the pattern to `^\*Auto-generated[^\n]*\*$`
plus a test asserting README contains `_source_date(topics)` — an assertion that
does **not** come from the generator.

**Scope check, same session.** The sibling `_home()` substitution
(`^updated: \d{4}-\d{2}-\d{2}$`) WAS verified to round-trip against its own
output, so this was a genuine one-off rather than a systemic pattern. The audit
is per-emitter; do not assume every `re.sub` in a generator is broken, and do not
assume the one you found is the only one — round-trip each.

**Generalization.** Any check of the form "regenerate and diff" answers *is the
generator reproducible?* and never *is the generator correct?* Every generated
invariant needs at least one assertion sourced outside the generator:
cross-artifact equality, a count tied to the corpus, or a pinned value. The same
shape appears in `_evidence_references` (an extractor whose output feeds the
metric that grades it) and in any emitter+validator pair maintained together.


## transient-vs-auth-expiry-error-classes

Extracted from rules/verify-effectiveness.md 2026-07-26 (size guard). The
GUARD's imperative body stays in the rule; this is the narrative.

WHY (auth-expiry, 2026-06-22 recall_recovery): the dev-security SSO token
expired mid-run; the funnel's `except Exception: return None` (correct for a
transient blip) turned every oracle call into flag:False. Caught only because
the Llama-flag count was STILL CLIMBING at kill time (proving the worker hadn't
yet hit the dead token) — had it expired earlier, ~thousands of rows would have
been silently mis-recorded as non-credentials. An auth-expiry guard (probe
caller-identity; on failure write an AUTH_EXPIRED marker + halt) makes it
fail-loud instead of false-negative-flooding. Same shape as the 2026-04-29
azure-automation "token expires mid-investigation, calls fail silently" note,
now generalized to measurement harnesses.
WHY: 2026-06-20 accuracy run — a ~10-min bedrock-runtime network blip produced 139
EndpointConnectionError drops (34% of a day) because the retry matched only throttle
strings; EndpointConnectionError fell through to the G4 hard-drop. The endpoint was
fine 2 min later — all recoverable. The run-monitor said "progressing" the whole time;
it must ALARM when the live drop-rate crosses the pre-registered checkpoint, not just
report row counts. Fix: transient-vs-deterministic retry + circuit-breaker + auto-retry
pass (mcp-servers #600). Companion to "prove the instrument": prove it STAYS sound
under transient infrastructure failure across a long run, not just at t=0.

## deploy-artifact-seam

Extracted from rules/verify-effectiveness.md 2026-07-26 (size guard). The
GUARD's imperative body stays in the rule; this is the narrative.

WHY: 2026-06-25, TWICE in one session. (a) the real-time secret Lambda ran a pre-Tier-0 image for a
full day — build-detector.yml pushed to ECR but had no update-function-code step, TF's mutable
:latest never repointed; symptom = stale detections, no error. (b) PR #661 added
`import otel_tier2_conformal` to otel_session_daily.py but never added the module to
detector/Dockerfile's COPY list → the daily + 4h detector crash-looped ~2 days (ModuleNotFoundError),
gold-sessions + tracker ingest both stopped, caught only by the freshness alarm. Both are the
multi-seam invariant applied to the DEPLOY seam. Fixes: mcp-servers #663/#665, mcp-infra #509/#510.
AUTHORING-TIME PREVENTION: when you ADD an import to a module shipped in a name-list-COPY Dockerfile,
add the module to the COPY in the SAME commit (the Dockerfile-COPY analogue of check-before-change's
"grep every consumer").

## stubbed-seam-is-an-untested-seam

Extracted from rules/verify-effectiveness.md 2026-07-26 (size guard). The
GUARD's imperative body stays in the rule; this is the narrative.

WHY: 2026-06-26 Investigate-runner — `test_investigate_judge.py` stubbed `boto3.client("athena")`
to return canned rows; all 11 passed. But the real attribute-access SQL was a map subscript
`lr.attributes['session.id']` on a struct-ARRAY column → TYPE_MISMATCH on every click, and an
`except: return []` reported it identically to "no data" → "transcript not retrievable" for EVERY
session. The test validated rendering/masking/degrade-clean (the composition) but never ran the
SQL (the seam that broke). Fix: hardened the stub to assert the SQL uses element_at(transform(
filter(...))) NOT a map subscript + a live known-positive probe (mcp-infra #529). Third distinct
shape of the multi-seam invariant above (deploy-boundary + seam-logic + STUBBED-seam); the common
root is component-green inference. Pairs with diagnose-before-fix "read the source, don't
approximate the column shape from recollection."

## agreement-is-not-validation-when-a-gate-is-shared

Extracted from rules/verify-effectiveness.md 2026-07-26 (size guard). The
GUARD's imperative body stays in the rule; this is the narrative.

WHY: two methods agreeing validates a number ONLY to the degree they are
     INDEPENDENT. If both sit downstream of the SAME candidate-generation
     gate (regex allowlist, detector set, parser, retrieval prefilter),
     they agree BY CONSTRUCTION on whatever passes the gate and are blind
     to the same things the gate drops — so their agreement says NOTHING
     about recall. 2x-confirmed cross-cutting: (1) code-tool-comparison
     runner+oracle both parsed with Python `re` → agreed by construction,
     not by independent verification; (2) two credential detectors sharing
     one keyword/prefix prefilter converged at ~140 distinct, while a
     gateless LLM census of the prefilter-REJECTED content showed the gate
     missed ~35-40% (the convergence had validated nothing about recall).

## health-field-counting-one-error-class

Extracted from rules/verify-effectiveness.md 2026-07-26 (size guard). The
GUARD's imperative body stays in the rule; this is the narrative.

WHY: 2026-06-20 — a detector's brief counted only PARSE_ERROR in `parse_errors`;
JUDGE_ERROR (a total 403 Bedrock outage) was uncounted AND its findings carried
severity=med, so 179 judge failures rendered as "151 medium findings, parse_errors=0"
— an obviously-broken outage disguised as a normal-looking brief that hid for a full
day. Both the detector and the poster exited 0; nothing could alarm. Fix: count
JUDGE_ERROR distinctly + emit a JUDGE_HEALTH-degraded log line a metric filter alarms on
(mcp-servers #590 / mcp-infra #477). The corrected brief shows 0/0/0/179-judge_errors —
screams "investigate me." Sibling of the transient-error + alarm-on-drop-rate guards above.


## flaky-readiness-guess-vs-gated-readiness

### 2026-07-26 fixed-sleep readiness in a hook-wrapper test (claude-config #1714)

A test that signals a subprocess after `time.sleep(2.0)` to verify its SIGTERM trap
passed in isolation and failed under concurrent load. The instinct is to raise the
sleep; the correct move is to delete it.

Measured on this host: wrapper start-up (bash + interpreter spawn) spanned **1.44s to
6.63s** under load, so a 2.0s sleep was under the real wait in 3 of 6 trials.
Signalling before the trap is installed hits the DEFAULT signal disposition —
`rc -15`, nothing logged — which is indistinguishable from "the trap is broken." So
the flake corrupts the DIAGNOSIS, not just the run. **Any** fixed sleep is a guess
against an unbounded distribution.

Fix: gate on a marker the probe itself writes. `run-hook` installs its trap BEFORE
launching the hook, so "the hook started" is a genuine happens-before edge for "the
trap is installed" — a real synchronization point rather than a timing assumption.
6/6 deterministic in the diagnostic, then 3/3 clean full-suite runs under load.

The same measurement independently corroborated the PR's headline finding (fixed
wrapper overhead of 1.4-4.1s against hooks budgeted at 3s and 5s) — two instruments,
one conclusion.

**Generalization:** a flaky test is a diagnosis request, not a retry request. If the
flake is a timing guess, find the happens-before edge the system already provides and
gate on it. If none exists, make one observable — do not tune the sleep.

## wrong-artifact-verification

### 2026-07-26 verifying a finding against the WRONG artifact (report-builder PR #2)

A vision critic (claude-opus-5) reported "all 14 figures lack axis titles, tick
labels, and value labels." I "disproved" it by grepping the rendered **HTML** — 164
`<text>` elements, axis titles and category names all present — and wrote that the
finding was a false positive.

Then I opened the **PNG**. Zero rendered text. The critic was right and I was wrong:
the critic judges the PNG previews, the reader gets the HTML, and the two had silently
DIVERGED. `render_png.mjs` gave resvg a font NAME (`defaultFontFamily: "Arial"`) with
`loadSystemFonts: false` and no font file — so resvg had no font data at all and
dropped every glyph, exiting 0 with a structurally valid, textless PNG. Proven with a
probe: black `LABEL-PROBE` text on white rasterized to **0 dark pixels**.

Two compounding lessons:

1. **Verify a finding against the artifact the finding is ABOUT.** Same spec, two
   renders, different content — checking the wrong one produced a confidently wrong
   retraction. This is the artifact-mismatch sibling of verify-before-assuming's
   circular-verification guard (which covers verifying against your own paraphrase);
   here the artifact was real, just not the one under review.
2. **Divergence between a review artifact and a delivery artifact is worse than a
   defect in either.** It yields wrong findings in BOTH directions: a false positive
   (flagging labels the HTML has) and, symmetrically, a false NEGATIVE where the
   critic approves a PNG whose HTML differs. Every vision finding was untrustworthy
   until the two agreed.

Fix: pin the font as a version-pinned npm dependency (DejaVu Sans, Bitstream Vera
license — Arial is Monotype-proprietary and not redistributable), keeping
`loadSystemFonts: false` so output does not vary by host. Assert on rendered PIXELS,
not markup — every markup-level assertion passed throughout the bug. Later verified
across CI runners: macOS arm64, Linux x86_64, and Windows AMD64 all produce
byte-identical HTML and PNG hashes.

## self-checking-corpus-linter

### 2026-07-26 API-fact checker: 29% precision, then it flagged its own corrections

Built `skills/cc-monitor/scripts/check_api_facts.py` to stop a real drift class: the
same API parameter contract was asserted in ~15 files across 4 surfaces in 2 repos,
nothing compared them, and two surfaces ended up asserting OPPOSITE things about the
`usage_report/claude_code` date format. Two design failures, both found only by
measuring against the live corpus.

**Failure 1 — lexical matching is unusable on a documented corpus (29% precision).**
The obvious design regexes the WRONG value (`group_by "workspace"`). Measured on the
real corpus: **4 real defects / 14 flagged**. The 10 false positives were all CORRECT
prose that names the wrong value in order to warn about it —
`` `group_by[]=workspace_id` (NOT "workspace") ``, `service_tier is batch not fast`,
`account_id == org user_id`. A well-documented corpus discusses wrong values *more*
than a sloppy one, so precision gets worse the better the docs are. Suppressing by
keyword then hid a REAL defect: `group_by valid: workspace_id, user_id, ... NOT
api_key/workspace` has a live bug (`user_id` is rejected) on a line whose trailing
clause corrects a *different* term, so a line-wide `\bnot\b` suppressor swallowed it.

The fix was to change the signal from lexical to **structural**: find a line that
DECLARES an enumeration (`group_by valid: [a, b, c]` / `group_by ["a","b"]`), extract
the members, and diff that SET against the probe's ground truth. Prose that merely
mentions a value contributes no members and cannot false-positive. Result: 1 real /
1 flagged, 0 known misses. Two supporting gates were needed — a value-list gate
(every comma element must be a bare identifier, so a `[[wiki-link]]` isn't read as a
value array) and an array branch with no anchor word (requiring `valid|accepts` had
MISSED a real bare-array defect).

**Failure 2 — the checker flagged its own corrections, so it could never be satisfied.**
The KB mandates correcting visibly: the wrong claim STAYS on the page, struck through,
with the truth beside it. After using the checker to correct 3 real defects, it
reported **5** — the corrections themselves. A checker that gets LOUDER as the corpus
gets MORE correct is unsatisfiable, and an unsatisfiable alarm trains people to ignore
it. Three suppressions were required, each found by re-running after a fix:

1. `~~struck~~` spans overlapping a match.
2. **Markdown-WRAPPED unclosed strikes** — the closing `~~` is on the next line, so
   the overlap check can't see it. Count tildes to `match.END()`, not `match.start()`:
   the pattern begins on LIVE text (`bucket_width=1d`) while the offending token
   (`1w`) sits inside the strike, so counting to `start()` sees zero tildes.
3. **Quoted vendor errors and warning lists** — `400 ending_before: Extra inputs are
   not permitted` and `values the API rejects (user_id, workspace, ...)` are evidence
   OF the defect class, not instances of it. The last one was caught only AFTER the
   PR merged, by running the INSTALLED checker over the INSTALLED corpus (#1728).

**Generalization.** Before shipping any corpus checker: measure precision on the live
corpus and hand-classify every hit; then run it again after applying its own fixes and
confirm the count goes DOWN. Exempt the corpus's correction idioms explicitly. The
verify-effectiveness <10% block-rate bar for hooks applies here too — a doc checker
that false-blocks is the same DoS on the workflow, just slower.

## regenerate-and-compare-certifies-deterministic-bugs

### 2026-07-26 claude-knowledge-base (shipped in #1239, fixed in #1240)

`tools/kb.py check` compares all six generated artifacts byte for byte against a
fresh build. README's date-stamp substitution used the pattern
`^\*Auto-generated:.*\*$` but WROTE `*Auto-generated from topic metadata through
<date>*` — no colon, so the regex could never match its own output. The
substitution was a no-op from the first build; the date froze while catalog.json
and Home.md advanced. `check` said "schemas and generated artifacts are exact"
the entire time, because the fresh build contained the identical frozen date.

An independent-review probe (set a topic's `updated` to a future date, rebuild)
exposed it in one step: two artifacts moved, README did not, exit code 0.

Verified same session that the sibling Home.md substitution DOES round-trip
(`^updated: \d{4}-\d{2}-\d{2}$` matches what it writes) — so the round-trip smell
is a per-site check, not a blanket condemnation of the pattern.

(Narrative extracted from rules/verify-effectiveness.md 2026-07-26 under the
T1/T2 size-budget split; the REQUIRED/SMELL imperatives stay in the rule.)

## union-field-diff-campaign-11

### 2026-06-12 campaign-11 tracker — a hand-picked content-diff certified silent data loss

A set-triage-status rewrite re-emitted 453 findings through an emitter that wrote
only its own known field set. The approving content-diff compared SIX hand-picked
fields and PASSED, while all 451 `location:` fields vanished into a merged commit.

Restored positionally from the pre-rewrite ref; the emitter now round-trips
`Finding.extra`, and the oracle test suite pins the union round-trip property.

The fields you don't list are exactly where silent drops live — which is why the
rule requires the comparison key set be the UNION of both sides, with key-set
equality asserted BEFORE per-key value equality.

(Narrative extracted from rules/verify-effectiveness.md 2026-07-26 under the
T1/T2 size-budget split; the STEP/FORBIDDEN imperatives stay in the rule.)

## gate-mounted-in-the-generator-not-the-checker

### 2026-07-29 warchest #39 — a requirement CI never enforced

Auditing the War Chest `/api/v1` surface surfaced an asymmetry: every operation in
`docs/openapi.json` specified its FAILURES precisely and its success as the bare word
`"Success"`. That is a real trap for a token client, because the envelope keys are not
uniform — `GET /sub-catalog-items` returns `items` (not `subCatalogItems`) and
`GET /admin-log` returns `entries` (not `logs`), and a wrong guess reads as `undefined`
rather than raising. Two of my own audit probes bound to the wrong key and reported an
empty collection that actually held 5 items.

The fix added a `SUCCESS` table to `scripts/gen_openapi.js` and made the generator
**refuse to emit** a spec if any route lacked a success schema. I was one sentence away
from writing "the gate prevents recurrence."

**What the mutation test showed.** Deleting one entry from the `SUCCESS` table:

```
node scripts/gen_openapi.js   -> exit 1  "ROUTES MISSING A SUCCESS SCHEMA"
node scripts/check_openapi.js -> exit 0  "openapi check OK"
```

`check_openapi.js` is the script **CI actually runs on a PR**. It validated the
committed spec's *route set* and its *capability names*, but nothing about the content
the generator had just become responsible for. So a future route could have shipped with
a bare `"Success"` and CI would have been green — the guard existed, mounted where the
pipeline never looks.

This is the inverse of the born-broken-guard failures (2026-06-12, both never passed
once): here the guard works correctly and is simply in the wrong place. The generator
runs when a human regenerates; the checker runs on every PR.

**Fix.** Mirror the generator-side requirement as an assertion in the checker over the
committed artifact — `check_openapi.js` now walks `spec.paths` and fails when any
operation's 200/201 lacks `content['application/json'].schema`, naming where to add it.
Re-mutated after the fix: both scripts exit 1. Also validated the spec's claims against
LIVE production responses (11/11 envelope assertions), because a regenerate-and-diff
check proves reproducibility, not correctness — see
[regenerate-and-compare](#regenerate-and-compare-certifies-deterministic-bugs).

**Second-order lesson (cost one wrong conclusion).** The mutation run's own
`node ... | tail -5` reported `exit=0` for a command that really exited 1 — the pipe's
exit status is the FILTER's. I briefly recorded the guard as not firing. Re-checked
unpiped (`cmd >/tmp/out 2>&1; echo $?`) to get the truth. Already ruled in
`platform-constraints.md` FORBIDDEN `chaining_&&_after_a_piped_gating_command`; this is
its 4th observed instance, in the specific shape of *verifying whether a guard fired*.

## fp-rate-demoted-a-check-to-decorative

### 2026-07-30 claude-config — a working check that had been reporting the finding all along

Six `mcp__*` tool-name prefixes in `~/.claude` pointed at servers that no longer
exist (`mcp__remote-airlock__*`, `mcp__remote-crowdstrike__*`,
`mcp__remote-msgraph__*`, `mcp__remote-tenable__*`, `mcp__slack__*`,
`mcp__confluence-fedramp__*`). Confirmed dead by empty `ToolSearch` on each. The
blast radius was real: `/triage` and `/investigate` — the two primary
security-ops skills — declared `allowed-tools` against a dead namespace, and
three `settings.json` hook matchers keyed on `mcp__remote-.*` had been inert
since the macOS migration.

**My first hypothesis was that no check covered this.** The `known-tools.yaml`
header said `--strict-tools` "isn't run in CI." That comment was **stale** — CI
runs `python bin/audit-skill.py --all --strict-tools`. So I revised to "the audit
doesn't scan frontmatter." Tested it: **it does** (the finding text literally says
"in frontmatter").

**The actual reason was worse than a missing check.** The audit had been finding
these prefixes the entire time — at severity `T1 [info]`, which exits 0. It was
pinned non-blocking because `known_real` is incomplete enough to flag tools that
genuinely EXIST: it reported `mcp__linear-server__list_issues` as unknown. So the
check could not be made blocking without failing CI on false positives, and the
true signal sat in that noise for months. Nobody was ignoring a warning; the
warning was structurally incapable of escalating.

**The tell.** Two successive hypotheses about the check ("not run in CI", "doesn't
scan frontmatter") were BOTH wrong, and both would have led me to build a second
check beside a working one. The third question — *at what severity does it report,
and why that severity?* — was the one that mattered, and it is the question a
"do we have a check for this?" audit never asks.

**Fix (#1785).** Added the dead prefixes to `known_phantom`, which reports at
`drift` (blocking) and is checked by DEFAULT rather than behind `--strict-tools`.
Two follow-on defects surfaced in my own fix, both caught only by running it:

1. **The guard shipped inert.** `known_phantom` matching was
   `if tool_name in phantoms` — exact set membership — so a PREFIX entry could
   never match. Two call sites (lines 1499, 1528) needed a shared prefix-aware
   helper. See the sibling lesson on data-file entry SHAPE in
   `agent-memory/topics/architecture.md`.
2. **A guard entry for a violation you are NOT fixing reds CI on main.** Once
   matching worked, it flagged 12 pre-existing violations across 10 other skills.
   Correct resolution was to keep only the entries whose consumers this PR
   repairs and record the rest as a commented TODO block with their consumers
   named — the guard entry and its fix ship TOGETHER.

**Generalization.** "We have a check for that" is a claim about coverage that a
non-blocking check does not support. Before citing one, ask what SEVERITY it
reports at and WHY — a check demoted to `info` by its own false-positive rate is
decorative, and its FP source is the actual bug to fix.

## 2026-04-23-tools-silently-cap-paginate-sample-or-filter-turn

  # WHY: tools that silently cap, paginate, sample, or filter turn a
  #      "census" into a "sample" without the caller noticing. The
  #      baseline becomes an artifact of the instrument, not the
  #      system. INCIDENT 2026-04-23 code-graph accuracy harness
  #      (recall 0.20 published, real 0.98 — 80pp instrument error).
  #      Full narrative: rules/incidents/verify-effectiveness.md.

## 2026-07-26-check-validates-artifact-regenerating-comparing

  # WHY: a check that validates an artifact by REGENERATING it and comparing to
  #      the committed copy is blind to any bug that is DETERMINISTIC — because
  #      the bug is present on BOTH sides of the comparison. Byte-equality of
  #      "committed output" vs "fresh output" answers "is the generator
  #      reproducible?", NEVER "is the generator correct?". The check reports
  #      exact/clean with total confidence while shipping the wrong value
  #      forever, which is worse than no check: it actively certifies the bug.
  # REQUIRED: for every generated artifact, assert at least one property NOT
  #      derived from the generator — a CROSS-ARTIFACT equality, a count that must
  #      match the source, or a value pinned in a test. A rebuild-diff is not a
  #      substitute. SMELL: if a substitution's own output would not re-match its
  #      own pattern, it is a no-op no rebuild-diff can see (per-site check).
  # INCIDENT 2026-07-26 KB #1239→#1240: a README date-stamp regex could never
  #      match its own output; `check` certified "artifacts are exact" for the
  #      whole time because the frozen date was on BOTH sides.
  #      Full: incidents#regenerate-and-compare-certifies-deterministic-bugs

## 2026-06-12-campaign-11-6-field-hand-picked-content-diff-passed

# WHY: 2026-06-12 campaign-11 — a 6-field hand-picked content-diff passed while
#      451 `location:` fields vanished into a merged commit.
#      Full: incidents#union-field-diff-campaign-11

## 2026-07-26-kb-check-reported-generated-artifacts-are-exact-whil

  # WHY: 2026-07-26 KB — `check` reported "generated artifacts are exact" while
  # README's date had been frozen since the first build by a regex that could
  # not match its own replacement. Full: incidents/verify-effectiveness.md.

## 2026-06-26-investigate-runner-11-tests-green-stubbed-athena-cli

  # WHY: 2026-06-26 Investigate-runner — 11 tests green on a stubbed Athena client
  # while the real SQL TYPE_MISMATCH'd on every click, masked by `except: return []`.
  # Full: incidents#stubbed-seam-is-an-untested-seam.

## 2026-06-20-only-parse-error-counted-so-179-judge-error-bedrock

  # WHY: 2026-06-20 — only PARSE_ERROR was counted, so a 179-JUDGE_ERROR Bedrock
  # outage rendered as a busy day and hid for a full day, both processes exit 0.
  # Full: incidents#health-field-counting-one-error-class

## 2026-07-29-warchest-39-gen-openapi-js-exited-1-missing-success

  # WHY: 2026-07-29 warchest #39 — gen_openapi.js exited 1 on a missing success schema
  # while check_openapi.js (what CI runs) exited 0; a route could have shipped bare with
  # CI green. Full: incidents#gate-mounted-in-the-generator-not-the-checker

## 2026-07-26-value-regex-scored-4-real-14-flagged-29-structural-h

  # WHY: 2026-07-26 — value-regex scored 4 real/14 flagged (29%); structural hit 1/1.
  # Then after fixing 3 defects it reported FIVE — its own corrections.
  # Full: incidents#self-checking-corpus-linter

## 2026-04-24-incident-code-graph-accuracy-session-hand-picked

# WHY: INCIDENT 2026-04-24 code-graph accuracy session — hand-picked
#      10-sample claims off by 5x and 1.6x; biggest gap not in the
#      original list at all. Full: rules/incidents/verify-effectiveness.md.

## 2026-04-24-incident-code-graph-rust-fixture-agg-f1-0-825

# WHY: INCIDENT 2026-04-24 code-graph Rust fixture — agg F1 0.825 was
#      essentially one crate's weighted score; 4 of 5 crates were
#      perfect. Full: rules/incidents/verify-effectiveness.md.

## 2026-06-25-twice-session-stale-digest-missing-dockerfile-copy

  # WHY: 2026-06-25, twice in one session (stale digest; missing Dockerfile COPY).
  # Full: incidents#deploy-artifact-seam.
  # AUTHORING-TIME PREVENTION: when you ADD an import to a module shipped in a
  # name-list-COPY Dockerfile, add the module to the COPY in the SAME commit.

## 2026-07-10-caf-shadow-enforce-flip-declared-0-blockers-across-5

  # WHY: 2026-07-10 CAF shadow→enforce flip — declared "0 blockers across 5 lenses" from
  # only the 3 that had reported; both unreported lenses returned blocks_go_live=true (one
  # DO_NOT_FLIP). The outcome held by luck, not process — phantom_verification applied to
  # a fan-out gate on the session's most irreversible action.

## n-branch-control-untested-branch

### 2026-07-31 example-technologies/docs — a 3-state guard whose middle branch was unreachable

On 2026-07-28 an Amplify `buildSpec` gained a guard so a corrupt `package-lock.json`
would not break the docs deploy. It sorts the lockfile into three states and picks an
install strategy per state: conflict markers present → `npm install`; valid JSON →
`npm ci`; neither → `npm install`. It shipped having been exercised on exactly one
state, and it was **written by me**.

The validity probe was:

```sh
elif node -e "JSON.parse(require('"'"'fs'"'"').readFileSync('"'"'package-lock.json'"'"','"'"'utf8'"'"'))" 2>/dev/null; then
```

The `'"'"'` idiom escapes a single quote inside a **single**-quoted string. This sat
inside a **double**-quoted `node -e "..."`, so the outer quote closed early and node
received a mangled argument, dying with `Error: Cannot find module '"fs"'` — exit 1 on
**every possible input**. `2>/dev/null` swallowed the syntax error, so the `elif` was
always false and control always reached the `else`.

**Measured consequences over three days.** `npm ci` never ran on any of the six guarded
branches, so lockfile pinning was off repo-wide while every build stayed green. Worse,
the guard actively **misreported healthy branches**: a census reading each branch's own
build log returned `LOCKFILE UNPARSEABLE` for all six and `HEALTHY = 0` — including
`develop`, whose lockfile was independently proven clean (no markers, parses, in sync
with `package.json`, confirmed later by the PR gate in docs PR #950).

**What caught it.** A positive control: run the deployed probe verbatim against a
*known-valid* lockfile. It exited 1; the corrected single-quoted form exited 0. Without
that control the uniform census reads as a genuine six-branch outage. `HEALTHY = 0`
across a whole cohort is the same instrument-artifact signature as the 2026-06-12
partial-index `EXACT-0.000` cohort — real effects move values, they do not zero a
population.

**A second instrument was dead in the opposite direction.** `npm install`'s
`up to date in 11s` looked like proof the lockfile parsed. Negative control: `npm
install` exits 0 on valid, truncated-invalid, and marker-corrupted lockfiles alike,
silently regenerating the file. So one instrument manufactured corruption while the
other concealed it, and averaging them would have produced a confident wrong answer in
either direction. Neither could answer the actual question.

**Why nothing detected it for three days.** The guard's contract was checked against its
*wording* — "only alarms on real corruption" — never against its *behaviour*. This is
the same defect as the 2026-07-28 remediation in the same arc, which was verified as a
valid **command** rather than as correct **content**. It is also a masking control: it
converted a loud failure (red build) into a silent degradation (green build, unpinned
deps), which removed the pressure to fix while creating a new failure mode nobody
watched. A fallback must be observable and time-boxed or it becomes the steady state.

**Fix (docs PR #950).** Requote the probe; drop `2>/dev/null` so a real parse error
prints its position. The durable parts are structural, not the requote: the build spec
moved out of console-only config — no history, no review, no diff, which is exactly why
the bug survived — into the repo as `amplify.yml`; a committed self-test extracts the
guard from that file and asserts routing across five lockfile shapes plus four
regression assertions pinning this bug shut; it runs on change **and weekly**, because a
control nobody edits is where this rots. `npm ci` also gained an `|| npm install`
fallback: branches that ran on `npm install` for three days may hold lockfiles that are
valid JSON yet out of sync, so restoring `npm ci` without it could turn green branches
red — the `valid_out_of_sync` fixture covers precisely that.

**Sequencing constraint that falls out.** Do not alarm on fallback usage until the
fallback rate has been measured at zero. Shipped while the lockfiles are still unknown
it fires on every branch on every build, and an always-firing alarm mutes every other
finding on its metric (see grading-discipline's firing-rate GUARD).

Distinct from [gate-mounted-in-the-generator-not-the-checker](#gate-mounted-in-the-generator-not-the-checker):
there the guard worked and sat where CI never looked. Here the guard was mounted
correctly and one of its branches had never once executed.


<!-- extracted 2026-08-01: ambient-context reduction -->

## plumbing-syntax-tests-pass-proves-code-does-what-code

```
WHY: plumbing (syntax/tests pass) proves code does what code says.
     Outcome (realistic scenario improves) proves the change is a net
     positive. Shipping plumbing-only ships without evidence of lift.
```

## verifying-components-in-isolation-and-inferring-the-whole-works

```
WHY: verifying COMPONENTS in isolation and inferring the whole works is the
     single most expensive pattern there is. A feature spanning seams
     (code↔IAM, code↔schema, dispatch↔execution, render↔sink) has its bugs IN
     THE SEAMS — exactly what component tests skip, so each isolated green
     feels like progress and the NEXT seam's bug waits for production.
RECURRENCE n=3, all different shapes: seam-LOGIC, DEPLOY-BOUNDARY (module placed
     by conceptual grouping, not the deploy boundary), STUBBED-SEAM (GUARD below).
     Root: DONE declared on component-green INFERENCE. Ask: did ONE real run cross
     every seam to the real sink (deployed + wired + invoked)?
     Full: incidents#multi-seam-feature.
```

## two-methods-agreeing-validates-a-number-only-to-the

```
WHY: two methods agreeing validates a number ONLY to the degree they are
     INDEPENDENT. If both sit downstream of the SAME candidate gate (allowlist,
     detector set, parser, retrieval prefilter) they agree BY CONSTRUCTION on
     whatever passes it and are blind to the same drops — so agreement says
     NOTHING about recall. Confirmed 2x; a gateless census of the REJECTED set
     showed the shared gate missed 35-40%.
     Full: incidents#agreement-is-not-validation-when-a-gate-is-shared
```

## 2-silent-incidents-an-sso-token-expiring-mid-run

```
WHY: 2 silent incidents — an SSO token expiring mid-run turned every oracle
call into a false negative; a 10-min blip hard-dropped 34% of a day.
Full: incidents#transient-vs-auth-expiry-error-classes.
```

## 2026-07-31-cloudtrail-cost-estimate-reported-569-mo

```
WHY: 2026-07-31 CloudTrail cost estimate -- reported $569/mo from the MEDIAN events-per-file
(150). The true mean was 4,126, already computed by an earlier script in the same session and
never reconciled against it. Real cost ~$N thousand/mo: a 27.5x understatement that mis-ranked the
whole remediation plan, and it was caught only when the user attached a PDF
("I think you are miscounting the cloudtrail issue"). A self-consistent wrong number survives
review; the disagreement with my own earlier output was the available tell.
```

## 2026-07-31-docs-buildspec-a-3-state-lockfile

```
WHY: 2026-07-31 docs buildSpec — a 3-state lockfile guard whose middle probe was
mis-quoted exited 1 on EVERY input; 6 branches took the fallback for 3 days, npm ci
never ran, and the census reported all 6 corrupt including a provably clean one.
Full: incidents#n-branch-control-untested-branch
```

## 2026-07-31-three-self-written-checkers-for-one

```
WHY: 2026-07-31 — three self-written checkers for one generated HTML doc were each wrong
differently: (1) a line-anchored table-leak check reported 0 leaks vs 52 real ones
(false clean); (2) a doubled-escape bold check (`\\*\\*` matches nearly every <p> tag)
reported 260 leaks vs 4 real (false alarm); (3) an open-questions check grepped for a
label the generator never emits, reporting 0 of 35 items rendering when all 35 rendered
correctly under a different label. REQUIRED: assert every leak/format checker against a
known-positive fixture (content you KNOW should fail it) before trusting a 0-count.
```


## 2026-08-02 whole-session distill — THREE documented rules recurred; the gap is TIMING, not wording

A 7-compaction / 36.8 MB session recovered via /mega-distill produced 35 raw lessons. Reconciliation
against the rule corpus found that three of the most consequential were NOT new: each is a rule that
already exists, is well-worded, and was violated anyway.

| rule | recurrence |
|---|---|
| `diagnose-before-fix.md` "existence != applyability" | **5th+** instance (its own WHY already cites 4 in one plan) |
| `verify-before-assuming.md` aws:PrincipalArn GUARD | **3rd** instance — and this time the check STILL did not fire proactively; it self-corrected only after user pushback |
| `verify-effectiveness.md` "exercise every branch" | **5th unreached mechanism in ONE session** |

THE FINDING IS THE PATTERN, NOT THE INSTANCES. All three rules are correctly written. All three
fired REACTIVELY — after the claim shipped, or after the user objected — rather than before the
claim left the model. No amount of additional rule text fixes that: the text was already there and
already correct.

So do NOT respond to a recurrence of this shape by rewording the rule. A rule violated under load
with correct wording is evidence for a MECHANICAL GATE (a hook, a skill step, a required tool call
that must return before the claim can be made), not for stronger prose. Per
`verify-effectiveness.md`, a gate proposal still needs its historical-replay fire rate measured
(>10% block rate = DoS) before shipping — the recurrence justifies the investigation, not the hook.

WORKED EXAMPLE OF THE TIMING GAP, same session: the "existence != applyability" instance was a
production `s3:PutBucketPolicy` verified CORRECT (right statements, mirrored from a working sibling
policy) but never verified EXECUTABLE BY THE ACTING PRINCIPAL. Assuming
`OrganizationAccountAccessRole` into the target REPLACED the SCP-exempt AdministratorAccess SSO
principal with one the DataPerimeter SCP denies. The change was right; the identity was wrong; the
rule that covers this is five instances old.

## 2026-08-02 — an EXCLUSION fix makes the excluded set UNCHECKED, and the user caught it

**Recorded here rather than in the parent rule because `verify-effectiveness.md` is
38,633 bytes — already 633 over the 38,000 BLOCK before any append, so no addition of
any size lands until a descope ships (`rule-authoring.md`: measure BYTES, and an
over-budget rule accepts nothing).** The lesson is stated as a GUARD anyway so it can
be lifted verbatim into the parent the moment there is headroom.

### The shape

GUARD pattern="I fixed a false-positive by EXCLUDING the offending values from the
check" (a hold-out set, allowlist, exemption, `!= known_value` filter, `skip_if` — any
fix whose mechanism is REMOVING something from a comparison):
NAME WHAT NOW CHECKS THE EXCLUDED SET before calling the fix done. An exclusion does
not make a value correct — it makes it **UNCHECKED**, and those are indistinguishable
in the fix's own green output. The exclusion is the right fix AND it opens a second gap
in the same motion.

**Worse when the excluded values are the load-bearing ones.** An exclusion is derived
from what the primary check cannot see, and what a check cannot see skews toward what a
DIFFERENT consumer depends on — so the held-out set is disproportionately the values
whose silent change matters most.

REQUIRED: (a) print the held-out set with its OWN verdict class — a silent hold-out is
its own coverage lie, because a reader cannot tell a complete result from one carrying
N unchecked members; (b) name the second instrument covering them, or record its
absence as an open item; (c) check whether any consumer treats those values as a
CLOSED SET (`WHERE ... IN (...)`, an enum, a dispatch table) — a closed-set consumer
BREAKS on a change the exclusion now hides, where schema-on-read would absorb it.

### The incident

Fixing 25 phantom `REMOVED` rows in the `/gather-claude-endpoints` docs differ by
holding telemetry-sourced values out of the docs comparison (claude-config #1864/#1867)
was correct — and left exactly those values unchecked. The user caught it, verbatim:

> "The held-out values are now unchecked by design. `subagent_completed` and
> `claude_file_uploaded` (46,860 events) feed closed-set predicates that break on a
> rename rather than absorbing it — and no docs-based check can ever warn. Only the
> Athena leg can."

Two properties made it worse than a normal coverage gap:

1. **The held-out values were the closed-set ones.** Both feed
   `WHERE event_name IN (...)` predicates in live detectors
   (`otel_channel_detect.py`, `activity_signal_detect.py`), so a vendor rename breaks
   them rather than being absorbed — and the differ had already spent its `REMOVED`
   alarm claiming they were gone.
2. **The named compensating control had not run.** In the same turn: *"Step 2c's Athena
   leg did not run — no AWS credentials this session, so I ran `--probe-only`."* So the
   instrument I was pointing at as the thing that WOULD cover the held-out set was
   itself unexercised that session.

**Why this needed transcript recovery to find:** my own compaction summary recorded the
provenance fix as clean and listed the follow-up as a `/cc-monitor` handoff. The
correction — that the fix created a second gap — survived only in the raw transcript
(`slice_000:1127`). A summary compresses at the granularity of WORK DONE, not of
CORRECTIONS RECEIVED.

## 2026-08-02 — a stated coverage caveat is not a substitute for waiting

Published a session report assembled from **3 of 7** parallel extractors, carrying an
explicit and accurate caveat in its own text: *"the remaining 4 would add detail … and
could surface workstreams not listed."* When all 8 returned they surfaced the **single
largest cost item in the session** — a ~$N thousand/month commercial CloudTrail data-event storm
— plus 16 more workstreams and 19 more retractions. The report went from 7 workstreams to
23.

The existing GUARD (`declared the review/workflow clean … while only SOME of its lenses
had reported`) is scoped to *"irreversible or highest-blast-radius"* actions and so did
not fire: publishing a document is reversible, and I had waited for the majority. Both
mitigations were real and neither helped.

**The generalisation:** writing the caveat DISCHARGED the felt obligation without
discharging the actual one. A caveat is a statement about the artifact's limits; waiting
is a change to the artifact. They feel interchangeable at authoring time and are not.
When a fan-out is still running and its output is the deliverable's SUBSTANCE rather than
a cross-check on it, the caveat is not a mitigation — the wait is.

Cheapest test before publishing from a partial fan-out: *"if the remaining branches
returned something that changes the headline, would I have to retract?"* If yes, wait.

## 2026-08-02 — a self-written checker can OVER-fire, not just under-fire

The existing GUARD covers a self-written verifier reporting **clean** when the artifact is
dirty (a false negative). The inverse also happens and reads very differently: an
empty-heading checker for a generated report flagged **4 sections as empty** that were
legitimate — a heading whose first child is a SUBheading has no prose of its own and is
correct structure, not a hollow section.

A false positive costs less than a false negative but it costs something specific: it
trains you to dismiss the checker's output, which is how a real hit later gets waved past.
Here the noise arrived attached to a TRUE finding (one genuinely empty heading in the same
run), which is the worst mix — the signal and the noise are indistinguishable at a glance.

**Fix shape:** give the checker a SELF-TEST asserting BOTH directions on a fixture it
carries — a known-hollow section it MUST flag, and a known-legitimate
parent-with-subheading it must NOT. Run the self-test before the real scan and fail loudly
if either assertion breaks. A checker that has only ever been shown to fire is
half-verified.


## 2026-08-05 — a TEST FIXTURE supplied the step PRODUCTION omitted, so a tested guard was inert

**Shape.** `hooks/session_start_modules/repo_sync.py::_prune_gone_branches` existed, was
covered by 18 passing tests, carried a careful 3-guard safety design (ancestry check +
recovery ref + `-d` not `-D`), and was **effectively inert in production for its entire
life**. Neither of the two fetch paths that precede it (`_sync_one_repo` here, and
`hooks/sync-repo.py::cmd_pull`) passed `--prune`, so no branch on a real clone ever
acquired the `[gone]` marker the function keys on.

**Why it survived review.** Two independent reasons, and the second is the transferable one:

1. The function's own docstring ASSERTED the missing step was happening: "`git fetch
   --prune` (already run via the rebase below) marks them `[gone]`". A reviewer checking
   whether prune ran could read that sentence and stop. The claim was false on both paths.
2. **The tests hand-ran `git fetch -q --prune` in their setup** (`test_repo_sync.py` lines
   ~220 and ~368). So the harness supplied the exact step production skipped, and every
   test exercised the prune logic against an ALREADY-PRUNED repo. The suite was green,
   specific, and structurally incapable of detecting the defect.

**This is distinct from the generator-vs-checker guard in `verify-effectiveness.md`.** There
the guard is mounted in the wrong PLACE (generator instead of CI checker) and simply never
runs in the pipeline. Here the guard is mounted in the RIGHT place and runs on schedule —
its *precondition* is never established, and the tests manufacture that precondition
themselves. Sibling failure, different mechanism: **wrong place** vs **fabricated
precondition**.

**Cost.** Nine managed clones became simultaneously unsyncable, each reporting
`ERR <repo>: fetch failed: fatal: couldn't find remote ref chore/github-rename-you-s`
— a message indistinguishable from a network/auth fault, so it reads as nine separate
infrastructure problems rather than one hygiene gap. Plus hundreds of accumulated stale
local branches (claude-knowledge-base ~85, claude-config ~21) that the prune logic was
written to remove and never did.

**A `[gone]`-keyed cleanup would ALSO have missed all nine.** `git branch -vv` showed 0
`: gone]` matches on the affected clones, because the local `origin/<branch>` tracking ref
survives until something prunes. The marker the cleanup keys on is *produced by* the step
that was missing — so the absence was self-concealing in both directions.

**REQUIRED when a guard depends on a precondition another step must establish:**

1. Name the precondition and grep for the code that PRODUCES it, not just the code that
   consumes it. "Something upstream does this" in a docstring is a claim, not a fact —
   and a docstring is the least-maintained place to assert a cross-function contract.
2. Read the test SETUP for any step the harness performs that production does not. A setup
   line that establishes the guard's trigger condition is the tell: if the fixture has to
   create the state, ask who creates it in production.
3. Write at least one regression test that does NOT pre-establish the precondition — assert
   the marker is ABSENT before the fix runs, so the test proves the guard was previously
   unreachable. (Here: `test_prune_clears_the_stale_ref_and_marks_branch_gone` asserts
   `"[gone]" not in before.stdout` — that assertion is the whole point of the test.)
4. Mutation-verify by removing the precondition-establishing step, not only by breaking the
   guard. Removing the `--prune` line failed exactly the 2 new tests with the real error
   text; breaking `_prune_gone_branches` would have failed the 18 old ones and told you
   nothing about the gap.

**Fixture gotcha worth keeping.** `git push origin --delete <branch>` also drops the
PUSHING clone's own remote-tracking ref. A fixture that deletes the remote branch from the
work clone therefore leaves NOTHING stale and silently asserts against an already-clean
state. Delete from a SECOND clone so the work clone retains the stale ref — in production
GitHub's merge queue does the delete, which is why the divergence exists at all.

**Also refuted here:** `sync-repo.py` was correct to SKIP the two dirty repos, and the
nine ERRs were not nine problems. Classifying each dirty file against the git-hygiene
two-condition reconcile test (byte-equal to main OR additive-and-already-upstream) found
5 of 6 in `~/.claude` safe-to-revert but ONE (`agent-memory/topics/msgraph.md`) real
unshipped work — the aggregate "6 modified files" would have hidden that.

## 2026-08-29 — a PINNED pair passes the lockstep edit; only a DERIVED assertion fails
<a id="2026-08-29-pinned-pair-passes-lockstep"></a>
**Anchors:** the parent rule's "assert the RELATIONSHIP, not two literals" paragraph.
Recorded here because the ambient corpus was at its ledger ceiling; the imperative
stays in `rules/verify-effectiveness.md` and this is the measured backing.

Five instances in one session, all different artifact classes, and the pattern held
in every one: **every PINNED pair had drifted or was one edit from drifting; every
DERIVED assertion held.**

| pair | how it was asserted | state found |
|---|---|---|
| OWUI tool preset ↔ the Slack scope set that must serve it | two literals | drifted (15 vs 19 tools) |
| installer scope constant ↔ its committed record | two literals | drifted (8 vs 10 scopes) |
| mutation-path selector ↔ its state unit's declared backend | unasserted | 12 pairs, none checked |
| release-check origin pin ↔ the workflow env supplying it | two literals | one edit from breaking |
| terraform runtime entry ↔ the script it mirrors | comment only | drifted |

The mechanism: a test asserting `A == "x"` and `B == "x"` detects a single-sided
change and **passes the lockstep edit** — which is the normal way such a pair
changes, because whoever edits one knows about the other. Only reading one side and
comparing it to the other can fail then. This is the same shape as
`incidents/tdd-quality.md#2026-07-31-both-sides-literal`, reached from four new
artifact classes (a tool preset, an installer constant, a JSON registry selector,
a CI env pin) rather than a Terraform cap.

```python
# WRONG — two literals; updating both together satisfies it
assert preset == [...]; assert record == [...]
# RIGHT — one side derived from the other
assert record["tools"] == list(module.PRESET)
```

**The vacuity floor is the part usually missing.** A loop that iterates a collection
and asserts per item passes trivially when the collection is empty, and
`0 mismatches of 0 checked` prints identically to a clean run. `assert pairs >= 12`
makes an empty collection FAIL. A floor can only ever produce a false alarm, never
false assurance — which is the property that makes it worth having, and the reason
it is cheap to add to any per-item loop.

**A comment claiming two files "cannot drift" is not a check.** One such comment had
sat above the preset for weeks; the pairing it promised was never asserted. Same
class as `validate-to-improve.md`'s "I left a comment so the next person updates it"
GUARD, applied to a cross-file invariant instead of user-facing copy.

**Corollary for a magnitude literal kept deliberately** (a count, a total): say in the
comment that it is a TRIPWIRE, not a second pinning of the same fact, and name what
must be re-verified when it moves. Otherwise the next reader deletes it as redundant
with the derived check beside it. Two such literals were kept this session
(`len(terraform_tools) == 19`, `pairs >= 12`) and both needed that sentence.

### Rule text as of 2026-09-04 (relocated verbatim; the directive form stays in the rule)

A test asserting `A == "x"` and `B == "x"` detects a single-sided change and PASSES
the lockstep edit — the normal way such a pair changes. Derive one side from the
other instead (`assert record["tools"] == list(module.PRESET)`), and add a VACUITY
FLOOR to any per-item loop (`assert pairs >= 12`): an empty collection prints
`0 mismatches of 0 checked`, identical to a clean run. A comment claiming two files
"cannot drift" is not a check. For a magnitude literal kept deliberately, say in the
comment that it is a TRIPWIRE and name what to re-verify when it moves, or the next
reader deletes it as redundant. Measured 5/5 across different artifact classes:
`incidents#2026-08-29-pinned-pair-passes-lockstep`.

## 2026-08-15 — a local venv supplied the dependency CI omits (keyless-CI class, 5th instance)

NOT a new lesson, and the dedup pass is what established that. This is the 5th
documented instance of the dev-venv-masks-CI class, and the gate already exists:
`rules/tdd-quality.md` records it as "the 4th instance of the keyless-CI class"
and prescribes the fix verbatim — reproduce the CI job in a **pytest-only venv**
(`python3 -m venv /tmp/ci-venv`, `pip install pytest`, creds unset) rather than
trusting the dev venv. The 2026-07-07 detection-pipeline instance is the same
shape one layer down: a partial `sys.modules` stub missed a transitive `httpx`
because the dev venv HAS httpx, and a red PR merged onto main.

I did not run that gate. I built a venv and installed what I *assumed* was
needed — which is precisely the instrument the class warns about.

Verifying a `mcp<2` pin for `fxhoudinimcp`, I built a venv, installed
`pytest pytest-asyncio` plus the package, measured **144 passed**, and reported
that figure on the PR as evidence the fix worked. The real CI invoke installs a
hash-pinned lock containing only `iniconfig/packaging/pluggy/pygments/pytest`
and then runs `pip install -e .`, which resolves RUNTIME dependencies only —
`pytest-asyncio` lives in `[project.optional-dependencies].dev` and is never
installed. So CI has no asyncio plugin, `asyncio_mode = "auto"` is an unknown
option, and every async test fails.

The pin itself was correct and controlled (`mcp>=2.0.0` → rc=2, 5 collection
errors; pinned → collection clean). What was wrong was the *scope* of the claim:
"144 passed" described an environment that does not exist in CI. Post-merge the
check went from exit 2 to exit **1** — collection fixed, async tests still
failing — which is what the local run could never have shown.

Caught only after the PR was open, and only because the same session had just
written the annotation-reading habit into `pr-fix`. That is thin: nothing
structural forced the check.

REQUIRED before quoting a local test count as evidence about CI: diff the
INSTALLED SET, not just the command. `pip freeze` in the rehearsal venv versus
the packages the CI job actually installs, and name every package present
locally that CI does not install. A dev-extra is the usual one — `pip install
-e .` does not install it, and nothing in the local run announces the
difference.

## 2026-08-29 greening a red gate by narrowing its detector
<a id="2026-08-29-greening-a-red-gate-by-narrowing-its-detector"></a>

When a check is red and the available fix NARROWS what the detector looks at,
enumerate the FULL population before adopting it. A narrower detector turns the
gate green by reducing coverage — worse than the gap it closed, and it leaves no
signal that coverage moved.

REQUIRED: build the truth table over every member of the population, not the
offending subset. Adopt the narrowing only if it reproduces the intended
membership EXACTLY; if any legitimate member falls outside it, the narrowing is
refuted however principled the discriminator looks.

Where the offending members cannot be resolved in the same change — because
resolving them needs an owner decision or data you would have to invent —
BASELINE them explicitly and gate the DELTA: record the known set in a named
constant, print it on every run, and add a test that fails when an entry goes
stale. A silently-subtracted baseline is a coverage lie; a printed one is a
backlog. Never raise a threshold or delete an assertion to accommodate a write.

INCIDENT 2026-08-29 (mcp-servers #1362): a catalog-coverage gate was red on 4
uncatalogued dirs. All four were `requirements.lock`-only with no MCP entrypoint,
so requiring an entrypoint looked like the principled fix. A truth table over all
34 discovered dirs refuted it — EIGHT CATALOGUED servers are lock-only too,
including two unquestionably real ones, so the change would have dropped 8
servers from the audit while turning the gate green. `discover()` was left
untouched and the four were baselined in a printed constant instead.
Mutation-checked: emptying that constant takes the gate to exit 1, because a gate
that cannot fail is decorative.

## INCIDENT 2026-08-25 (source-vs-data diff is not exoneration)

When an exact-equality contract fails between a DATA artifact and CODE, the reflex is to
diff the artifact against SOURCE. If that comes back clean, the bug looks impossible.
Measured 2026-08-25: a drift-repair Lambda raised
`ValueError: desired OpenWebUI API environment is invalid` on every invocation for five
days. The stored S3 object's `managed_environment` matched `origin/main` EXACTLY — 0
missing, 0 extra, 0 value mismatches — so the first hypothesis (a stale object) was
refuted. The defect lived exclusively in the `deployed` rung: the deployed Lambda predated
its own contract by 8 keys (3 vs 11), so an exact-equality check compared an 11-key object
against a 3-key expectation. Both the data and the source were right the whole time.

## INCIDENT 2026-08-26 (a test that re-implements the path it verifies)

The "probe must exercise the deployed code path" rule above has a test-side twin that is
easier to miss, because the test looks like it covers the seam. Measured 2026-08-26: a
regression test for a plan/apply document-equality defect called the plan BUILDER twice and
compared the results — which SIMULATES what `apply` does. The mutation battery proved it
worthless by reintroducing the exact live defect (apply not carrying a marker into its
re-derived document) and leaving the test GREEN. Rewriting it to stub only the two external
boundaries and let the real `apply` run its own validation, readback and comparison turned
that mutation from MISSED to CAUGHT.

## INCIDENT 2026-08-12 (degrade-then-restore batched as two loops)

INCIDENT 2026-08-12: 6 GitHub PRs had auto-merge disarmed in one loop (all 6
succeeded), then a second loop to re-arm failed 7/7 on TLS handshake / i-o timeouts.
The turn ended there. The PRs had been stuck-but-armed and were now stuck-and-
unarmed — strictly worse — and the user had to re-prompt to resume. Per-target
iteration would have degraded one PR, not six.

## INCIDENT 2026-08-25 (re-measure between the fix and the next task)

Measured 2026-08-25, the most expensive mistake of a 62-hour incident: two MDM carriers
were realigned in the morning, the push returned HTTP 201, and the next ten hours went
into designing a follow-on architecture. Nobody re-read the ingress success ratio. It was
still 91% rejected — three OTHER carriers, unknown at the time, were still deploying the
evicted value. The realignment was necessary and insufficient, and the difference was one
read of a number already on a dashboard. Ten additional outage hours bought nothing.

## INCIDENT 2026-08-12 (a rehearsal supplied what the real invoke omits)

INCIDENT 2026-08-12: an alert lane's pre-enable dry run passed `since` explicitly, so
`read_state()`'s fallback never ran. Terraform SEEDS its watermark parameter as
`{"watermark": 0}`, which EXISTS and PARSES, so the `ParameterNotFound` guard never
fired and `0` meant "alert on everything since the epoch". The first real sweep posted
40 of 61 historical findings to a watched channel. An existing test asserted the bounded
lookback for the parameter-ABSENT case and passed throughout.

## INCIDENT 2026-08-12 (a reporting lane's first real output)

INCIDENT 2026-08-12, one lane, three defects, all past `plan`, `apply`, and 1,872 green
tests: (a) a helper returned markdown that the caller re-wrapped, nesting `*bold*` inside
`*bold*` so Slack terminated it early; (b) a "retention sweep" line reported whole-day
min/max times, which was TRUE and useless — the line existed to make a deviation
visible and the number could not do that; (c) 22 of 61 posted alerts were false by the
action's own name, visible only by reading what was actually sent. Two of the three were
found by reading the delivered message; the third by comparing a row count against what
had been ingested.

## 2026-08-28 — an INDETERMINATE cell tallied beside definitive ones, and a denominator nobody printed

A tenant-wide mail purge published **three separate "all clear" results in one
session**, each wrong, each the same class: an unfalsified instrument returning a
confident zero. Two shapes reached the reporting layer.

**Shape 1 — the errored cell.** A sweep recorded `{NOT_FOUND: 822, LOCATE_EXC: 1}`,
printed `items found: 0`, and **exited 0**. The exception was a TLS connection
failure: a cell where the answer is UNKNOWN, not a cell that came back clean. It was
counted as just another outcome, so the summary read as a completed sweep.

**Shape 2 — the wrong denominator.** An earlier run of the same tool graded **645 of
824** targets and also read as complete, because the summary counted what was
ATTEMPTED rather than what was EXPECTED. Every mailbox it touched was genuinely
clean; the defect was entirely in the denominator. Cause of the shortfall was
upstream — offset pagination over a live message-trace window silently dropped 179
mailboxes while the row count moved only 868→867, so the loss was invisible.

**Why a control cannot cover this layer.** Layers below the summary are probes, and a
known-positive catches them — one did, here, which is how the locator and target-set
defects were found. The reporting step is different in kind: it is where a control's
own result would be *read from*. So the fix is structural rather than another control:
DEFINITIVE vs INDETERMINATE as a type distinction, grading measured-against-expected,
and an indeterminate cell changing the process exit status.

**Third instance of the class, in three domains.** `github-ci-patterns.md` records
pytest exit 2/3/4 being suppressed, so a check asserted a result no test produced.
`verification-instrument-discipline.md` records a `refuses()` helper returning True on
any exception, so a transport error read as PASS. Same defect, different surface — the
recurrence is what promoted the ambient GUARD.

**Evidence:** claude-config #2190 (the `/mail-purge` skill encoding the gate; three
mutation tests assert the verdict flips to COMPLETE when each guard is disabled).
Writing those mutation tests found a real defect in the gate itself: a definitive
retry cleared `seen` but not the indeterminate record, so last-verdict-wins was
implemented in one direction only and a retried target would have stayed permanently
INCOMPLETE.


## 2026-08-28 (session d42ae003) — relocated from the ambient rule

## A read-back proves the TRANSPORT, not the freshness of your INPUT

Byte-identity on read-back after an upload compares the deployed artifact to what
you SENT. It cannot tell you the bytes you sent were the current ones. Measured
2026-08-28: an Intune script upload was built from `git show origin/main:<path>`
where `origin/main` had been fetched BEFORE the PR merged and never re-fetched, so
a superseded build shipped and the read-back reported `identical=True` on every
field. The upload was reported verified. The only thing that caught it was a
source-vs-deployed drift gate run afterwards, which compared the tenant against
git rather than against the payload.

So for any deploy that reads from a ref, refspec, tag, digest, or branch:

- `fetch` and re-resolve the ref in the SAME command sequence as the upload, and
  print the resolved commit/digest alongside the payload sizes.
- Assert a property of the CONTENT you expect from the new version — grep the new
  marker, count the new symbol — not only that source and destination agree.
- Treat "read-back identical" and "input current" as two separate claims. The
  first is cheap and nearly always true; the second is the one that fails.

A checkout that is permanently diverged from `origin/main` is also an invalid
BASELINE for any external comparison, not merely an unsafe base to ship from.
Diffing a deployed artifact against such a checkout overstates the delta and can
make a destructive "reconcile" look correct: measured the same day, comparing an
Intune script against the local 278-ahead `~/.claude` reported a 5,930 B source
against a 7,875 B deployment, when `origin/main` actually held 6,878 B — and the
reconciliation that difference implied would have deleted two merged PRs. Resolve
comparison baselines with `git show origin/main:<path>` explicitly.

GUARD pattern="read-back matched, the upload is verified":
  REFUSE. Name the resolved ref and re-fetch it in the same sequence. NO EXCEPTIONS.
GUARD pattern="I already fetched at the start of the session":
  REFUSE. Merges land between the fetch and the upload; re-resolve immediately before.

## 2026-08-15 source-and-live drift in both directions inside one session
<a id="2026-08-15-source-and-live-drift-in-both-directions"></a>

Relocated verbatim from the ambient rule body on 2026-09-03 (net-zero ambient
relocation; the GUARD that cites it stayed in the rule).

INCIDENT 2026-08-15, both directions inside one session: an IAM grant and an SCP
change were found committed-and-never-applied (a JSON document in a repository
is not an SCP), which was correctly recorded. Hours later the same session's own
WAF fix — a rule removed from a live web ACL and verified with a 130,154-byte
request returning 200 — turned out never to have been committed at all. The only
commit touching that file was the original deployment, so the next apply would
have re-added it. Recognising the pattern in one direction did not transfer.

### Mechanism (relocated 2026-09-04)

Relocated verbatim from `rules/verify-effectiveness.md`; the one-line form stays in the rule.

The ladder runs BOTH ways, and the downward direction is the one that gets
skipped. `source -> live` is the familiar failure ("I merged it, so it is
deployed"). `live -> source` is its mirror and just as expensive: an out-of-band
fix that WORKS is self-congratulating, so verification stops at the measured
outcome and nobody checks the change exists in source. The next apply reverts
it, and the revert looks like a fresh bug because the symptom's known fix is
"already done".

## 2026-08-16 a probe constructed its own connection and read the library default
<a id="2026-08-16-probe-constructed-its-own-connection"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

A probe must exercise the DEPLOYED CODE PATH, not a fresh equivalent of it. A
new client/connection/session constructed by the probe reports the LIBRARY DEFAULT
and says nothing about the configured runtime. Measured 2026-08-16: a verification
script called `sqlite3.connect()` itself and read `PRAGMA busy_timeout` = 5000,
which nearly shipped as "the 30s timeout fix did not apply" -- the setting is
applied inside the application's own `_get_conn()`, so the only honest measurement
imports the deployed module and asks IT (30000). Import the module and call its
accessor, or attach to the running process; never re-implement the setup you are
trying to verify.

## 2026-08-16 an ABSENT check read as passing
<a id="2026-08-16-absent-check-read-as-passing"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

An ABSENT check is not a passing check. A CI job that fails BEFORE creating any
job produces no logs and simply does not appear in the check list, which reads as
"not applicable to this repo" rather than broken. Measured 2026-08-16: reported
"tflint passed" from an all-green aggregate while tflint had never run in that
repo's history. Before citing a named check as passing, confirm that check appears
by name. Equally, when a linter job fails, separate ERROR from WARNING counts
before concluding a fix did not work -- a fix that took the error count 1 -> 0 was
briefly reported as failed because 16 pre-existing warnings kept the job red.

## 2026-08-26 a seam no instrument could cross (labs-portal importer)
<a id="2026-08-26-seam-no-instrument-can-cross"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

### 4th shape: a seam NO instrument you have can cross (n=4 for multi-seam)

The three recorded shapes -- seam-LOGIC, DEPLOY-BOUNDARY, STUBBED-SEAM -- all assume
you COULD have tested the seam. The fourth is the one where you cannot, and it is the
most dangerous because every layer you CAN test goes green.

Measured 2026-08-26 (labs-portal importer): the browser -> ALB -> Lambda hop was
crossable only by a human's authenticated browser. Everything else was verified --
31 offline tests, mutation batteries, a botocore-verified presigner, THREE green
end-to-end runs -- and **two consecutive production defects lived in that one hop**,
both found by the user: the shared WAF refusing the request body, then a malformed
response envelope. The ALB access log shows why the E2E could not see either: every
earlier attempt was `elb=403` or `302`, so **no request had ever reached the Lambda
through the ALB** until the user clicked.

THE MECHANISM IS REUSABLE, not AWS-specific: `aws lambda invoke` hands the response
OBJECT back to the caller. Only the ALB parses `statusDescription`, so a bare `"200"`
instead of `"200 OK"` is invisible to every direct invoke and is a bodyless 502 to the
browser. A probe that receives your output cannot validate a CONTRACT that a different
consumer enforces.

REQUIRED: when the last hop needs an instrument you do not have, say so as a BLOCKING
gap BEFORE claiming the feature works -- not as a footnote under a success report. I
flagged it both times and both times it read as a caveat beside green results, so the
user paid the round trip. The honest form is "this is unverified and needs you to click
it", above the summary, not below it.

## 2026-08-17 a transient known-positive control was not captured
<a id="2026-08-17-transient-control-not-captured"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

When the triggering condition is TRANSIENT, capture the known-positive control
WHILE it still holds. A degraded link, an outage, a load spike, or a race window
is the only cheap opportunity to observe a detector firing on the real condition;
once it clears you can construct synthetic controls but can no longer confirm the
detector fires on the genuine article, and the difference is not recoverable
later. Measured 2026-08-17: an auto-detect gate for a degraded-egress hang was
built while the link was bad, but the link recovered before the gate was
installed, so its positive branch rests on forced-timeout and DNS-failure
controls rather than a live observation — an honest gap that a five-second probe
during the window would have closed. Grab the control first, then build the fix.

## 2026-08-26 a placeholder probe tested only the first gate; a projection hid the discriminator
<a id="2026-08-26-placeholder-probe-tests-only-the-first-gate"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

A MULTI-GATE probe with a placeholder input tests only the FIRST gate, and its
output reads as coverage of all of them. Validation SHORT-CIRCUITS, so a dummy value
that fails gate 1 means gates 2..N were never reached -- while the report shows N
rows, N statuses, and N distinct-looking verdicts. Measured 2026-08-26: a probe of a
new endpoint's five refusal paths passed `upload_key: "x"`, which failed key-format
validation every time; four "different gates" were the SAME gate, and the two that
mattered (a repo-shape refusal, and a 404 whose hint must not blame the wrong
component) were never exercised. Reaching them required staging a REAL artifact.
REQUIRED: order the gates, then satisfy every earlier one so the probe arrives at the
gate under test; if two rows produce the same error text, they are one gate.

The INVERSE also misleads: a projection that omits the discriminating field
manufactures a finding. The same session's census printed `name` and `owner` per row
and reported a duplicate app; the rows differed in `road` and `url` -- one app on two
roads, deliberately. And a checker whose INPUT was never produced reports a confident
zero: an extractor copied 2 of 3 files out of an image, so the grep for a feature that
WAS present returned 0 with no error. Print the field that would DISTINGUISH the rows,
and assert the input exists before believing a count of it.

## 2026-08-25 a secret rotation revoked nothing
<a id="2026-08-25-secret-rotation-revoked-nothing"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

A REVOCATION rehearsal needs three observations, not one. A post-revocation 401
is uninterpretable alone — it is equally consistent with "the credential was
revoked" and "authentication is now broken for everyone". Required: (1) the SAME
credential accepted BEFORE the revocation, (2) that credential refused after,
and (3) a FRESHLY issued credential accepted after. Without (3) an outage reads
as a successful kill switch. Also test the INTERMEDIATE state, because that is
what falsifies a one-step runbook: measured 2026-08-25, rotating an ECS service's
Secrets Manager value revoked NOTHING — the token still returned 200 with ~59
minutes left on its exp, because ECS injects secrets at task start and the
running tasks held the old value; only `--force-new-deployment` completed the
revocation. The documented kill switch said rotation "invalidates every
outstanding token at once", so an operator following it during a leak would have
believed 914 users' tokens were dead while every one still worked.

## 2026-08-20 a viewer-local timezone in a shared report
<a id="2026-08-20-viewer-local-timezone-in-a-shared-report"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

An artifact that renders differently for different readers is not a shareable
artifact. PIN AND LABEL the timezone, locale, and any other host-derived
formatting an artifact resolves at view time; never leave a date to the viewer's
local zone. Two failure modes, and the second is worse: the same file states
different facts on different machines, and a single artifact contradicts ITSELF
when two of its code paths pick different zones. Measured 2026-08-20 — a mailbox
report formatted message times with `toLocaleTimeString` (viewer-local) and
thread-list dates with `toISOString` (UTC), so one message read `19 Aug 01:47 pm`
in Chicago and `20 Aug 03:47 am` in Tokyo while disagreeing with its own thread
list by a day, on a corpus whose subject was cross-timezone travel. The check is
cheap and belongs in the artifact's own test: render under two or more host zones
and assert the displayed values are byte-identical. Anchor relative windows
("last 6 months") to an explicit as-of date rather than to `max(data)`, or one
future-dated record silently moves the window for everything else.

## 2026-08-28 a skipped verification layer reported as passing
<a id="2026-08-28-skipped-layer-reported-as-passing"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

A verification layer that is SKIPPED because its dependency is missing reports the
same exit code as one that ran. Measured 2026-08-28: a portal DOM check fell back to
a weak id cross-check when jsdom was absent, counted that fallback as a PASSING
assertion, and exited 0 with `37 checks passed` — so a run with the entire DOM layer
missing, including a brand-new test that had never executed once, was
indistinguishable from a clean run. The only tell was one line of prose mid-output.
A missing dependency must FAIL and name the install command, not degrade. Do NOT add
a bypass flag: a flag set once in a shell profile restores exactly the hole it was
added to close. If a layer is genuinely optional, its absence must change the
reported COUNT and the exit status, never just a log line.

## 2026-08-28 a teardown verified by its end state
<a id="2026-08-28-teardown-verified-by-end-state"></a>

Relocated verbatim from the ambient rule body on 2026-09-04; the directive and a
pointer stay in `rules/verify-effectiveness.md`.

Verify a CLEANUP or teardown path by its END STATE, not by each step succeeding. A
delete against an already-absent resource is the EXPECTED condition on a retry, so a
step-wise fail-fast turns a partially-completed teardown into a permanently
unresumable one: the first delete errors and every remaining resource leaks forever.
Make each delete tolerant, then read the world back and fail on what SURVIVED
(measured 2026-08-28 — an `undeploy` verb was rewritten this way after a double
dispatch left an app half-torn-down and each retry aborted on step one). The verdict
is the post-read, not the sequence of API acknowledgements.

