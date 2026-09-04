@rule grading_discipline
@version 2026-05-11
@scope every system grade, accuracy assessment, "is X working" evaluation, or letter-grade output where the user is asking for a verdict on a measured system

# ─── INVARIANTS (always-true) ───

INVARIANT memory_search_runs_before_any_grade
  # WHY: 2026-05-10 incident — graded code-graph against an "accuracy
  #   Full: incidents#2026-05-10-incident-graded-code-graph-against-an

INVARIANT every_cited_number_stamps_its_source_mtime
  # WHY: a grade table without per-row mtime is indistinguishable from
  #   Full: incidents#a-grade-table-without-per-row-mtime-is-indistinguishable

INVARIANT rubric_thresholds_are_pre_registered_not_inferred
  # WHY: without explicit "A− if F1 >= 0.95, B+ if 0.85-0.95, D if <0.5"
  #   Full: incidents#without-explicit-a-if-f1-0-95-b-if

INVARIANT axis_table_precedes_aggregate_letter
  # WHY: a single-letter grade collapses 4+ meaningful axes (absolute
  #   Full: incidents#a-single-letter-grade-collapses-4-meaningful-axes-absolute

# ─── PROCEDURE: before producing a grade ───

STEP_1 memory_search the system being graded
  - query: "<system-name> evaluation accuracy posture snapshot grading"
  - read the top 3 results — they may include same-day updates the
    file-based search missed
  - if a "posture snapshot," "current state," or similar more-recent
    measurement exists, prefer it over older docs in the same directory

STEP_2 sort candidate source docs by mtime
  - `ls -lt <baselines>/<topic-files>/<reports>/`
  - read the newest one first as the authoritative current-state source
  - older docs are trajectory context, NOT current-state evidence
  - if two docs cover the same fixture and are <24h apart, read both
    and reconcile — they may have been written before and after a
    same-day shipping PR

STEP_3 pre-register the rubric
  - state the threshold per axis BEFORE looking at the numbers
  - example: "If scope-aligned F1 ≥ 0.95 → A; 0.85-0.95 → B; 0.70-0.85
    → C; <0.70 → D. Production fixtures and adversarial fixtures graded
    separately."
  - thresholds are public in the grade output, not implicit in the
    grader's head

STEP_4 produce the axis table first
  - rows: each meaningful axis (absolute accuracy, worst-case,
    trajectory, ceiling, operational readiness)
  - columns: metric, value, source_file, source_mtime, freshness_band,
    grade_for_this_axis
  - the aggregate letter (if any) appears AFTER the table, with the
    collapse rule named

STEP_5 currency-stamp every metric
  - format: `[FRESH ≤1d]`, `[STALE 1-7d]`, `[OLD >7d]`, `[UNKNOWN]`
  - freshness band is computed from `max(source_mtime - binary_mtime, 0)`
    when a binary is involved, OR from `now - source_mtime` for
    binary-independent metrics
  - STALE/OLD metrics MUST trigger an explicit "this number may not
    reflect today's state" disclaimer in the grade prose

STEP_6 separate "what's open" from "what's the state"
  - gap-inventory / leverage / "to-fix" docs describe the OPEN gaps
    after the latest fixes — they are NOT the current accuracy state
  - posture-snapshot / current-state / CURRENT.md docs describe the
    measured state
  - never cite a leverage doc as if it were a state doc

# ─── USER OVERRIDE POLICY ───
# Grading discipline is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="just give me a letter grade" or "skip the axis table":
  REFUSE producing a single letter without the axis table first. The
  axis table is the evidence; the letter is a collapse over it. The
  user can ask for a collapse on a specific axis after seeing the
  table. NO EXCEPTIONS.

GUARD pattern="I trust the latest doc, skip memory search":
  REFUSE. The file-based view is not the only source — topic files,
  posture snapshots, and capture entries in the knowledge base may
  hold same-day updates. Memory search is one tool call; the failure
  mode of skipping it is publishing a stale grade. NO EXCEPTIONS.

GUARD pattern="thresholds are obvious, don't bother stating them":
  REFUSE. Without explicit thresholds, the grader picks the most
  pessimistic anchor by default — and the disagreement is unresolvable
  without re-deriving them. State the thresholds in the grade output.
  NO EXCEPTIONS.

GUARD pattern="all the data is from today, freshness stamps are
  unnecessary":
  EVALUATE: is the binary that produced the measurement also from
  today? If the binary mtime is >24h newer than the baseline mtime,
  the data is stale relative to the system being graded. Stamp anyway.
  NO EXCEPTIONS for letter-grade output.

GUARD pattern="N failures in the window, so this is failing" or
  "X/Y failed, that's an active problem" (any count drawn from a
  retention/lookback window — job history, alert counts, error tallies):
  REFUSE the active-problem verdict until you plot the count's TIME
  DISTRIBUTION. A window total cannot distinguish an ongoing fault from
  a closed cluster, and the closed cluster is common: a deploy day, a
  since-retired schedule, a fixed bug. REQUIRED before reporting: the
  timestamp of the FIRST and LAST occurrence, and what has happened
  SINCE the last one. If every occurrence predates a known change and
  the interval after it is clean, the finding is CLOSED HISTORY — say
  so, do not report it as a live gap. Also check WHICH invoker produced
  them (a schedule/job id that no longer exists is the tell).
  NO EXCEPTIONS for a count you will report as a problem.
  # WHY: 2026-07-28 govslack-user-deprovision — reported "35 of 59 failed,
  #   Full: incidents#2026-07-28-govslack-user-deprovision-reported-35-of

GUARD pattern="the total went N -> N+1 and THIS record is newly visible, so it is new"
  — any claim about a POPULATION whose enumeration is INCOMPLETE (a paginated pull, a
  filtered list, a renderer that drops records, a page-capped response):
  REFUSE the attribution. When enumeration is partial, the TOTAL and the SET THAT RENDERS
  are two INDEPENDENT variables, and a count delta cannot tell you which one moved. The
  newly-visible record is the salient candidate and usually the wrong one — visibility
  churn is far more common than creation, and the two are indistinguishable from the
  count alone.
  REQUIRED before calling anything new: read that record's OWN creation timestamp. And
  whenever the enumerator is incomplete, state BOTH numbers in the same breath ("18
  counted, 14 renderable") — a bare total from a partial enumerator reads as a census, and
  every downstream reader will treat it as one.
  NO EXCEPTIONS for a "this was just created" claim drawn from a count delta.
  # WHY: 2026-08-01 Atlassian token inventory — the org count moved 17 -> 18 while a
  #   Full: incidents#2026-08-01-atlassian-token-inventory-the-org-count

GUARD pattern="a FILTERED COUNT used to prove a FIELD, ATTRIBUTE, or CAPABILITY EXISTS"
  (`WHERE u_custom_field != NULL` -> N rows, so the field is deployed; `?tag=x` -> N, so
  tagging works; any existence/population claim drawn from a query's row count):
  RUN AN IMPOSSIBLE-VALUE CONTROL IN THE SAME BREATH, or the number is not evidence. A count
  CANNOT distinguish "the filter matched everything" from "the filter was silently DROPPED" —
  both return N, and many APIs discard an unknown-field clause rather than erroring. The wrong
  reading is the one that survives review, because a large plausible number reads as a
  populated field while a 400 would have read as a bug.
  REQUIRED: issue the identical query against a field/value that CANNOT exist. Identical count
  => nothing is filtering => the probe is vacuous, whatever it returned. Then re-probe with a
  mechanism that fails LOUDLY on a bad name — a PROJECTION (`sysparm_fields`, `--query`,
  `SELECT col`) returns a KEY for a real field even when empty and OMITS a nonexistent one,
  which is a discriminator a count can never be.
  A LOUD FAILURE IS THE GOOD BEHAVIOUR: NetCloud answers an unknown `fields=` column with 409;
  ServiceNow silently drops the clause. Prefer the interface that errors, and never infer
  deployment state from the silent one.
  NO EXCEPTIONS for an existence/deployment claim that reaches a recommendation, a ticket, or a
  KB entry.
  # WHY: 2026-08-03 ServiceNow — probing whether RiskRadar's four write-back fields were
  #   deployed, `u_risk_score!=NULL` returned 13,765 rows on `sc_req_item`. A control on a
  #   field that CANNOT exist returned the IDENTICAL 13,765; so did the bare table. The
  #   filter was discarded, not matched. `sysparm_fields` settled it in one call — the four
  #   fields were ABSENT, so a complete integration existed in the repo and had never been
  #   deployed. The count had briefly supported the opposite conclusion in a ticket
  #   recommendation. Same mechanism measured in 4 independent domains: Airlock (a filter
  #   whose absurd-param control returned the same rows), NetCloud (409 — the loud version),
  #   engineering-assessment-measurement-validity, and ServiceNow.

GUARD pattern="reporting a POPULATION COUNT ('144 keys', 'N users', 'M devices') that you
  did not measure THIS session with an EXHAUSTIVE pull":
  NAME THE COUNT'S PROVENANCE BEFORE ITS FIRST USE — measured-exhaustively / measured-capped /
  inherited-from-memory / vendor-stated. A count is the most quotable thing in an analysis and
  the least likely to be re-derived, so an unmeasured one gets repeated verbatim into every
  downstream table and both report formats, gaining apparent authority at each hop while never
  acquiring evidence.
  THE TELL IS A SHAPE PROBE READ AS A CENSUS. A call written to inspect an OBJECT
  (`{"limit": 3}` to see which fields exist, `head -1`, a single-record fetch) answers "what
  does this look like", NEVER "how many are there" — but its output sits in the transcript
  looking like an enumeration, so a remembered total attaches itself to it and the pair reads
  as measured. Distinct from the partial-enumerator GUARD below: there the pull was intended
  as a census and fell short; here NO census was ever attempted.
  REQUIRED before any count reaches a deliverable: page to exhaustion (`has_more`/`last_id`
  until false) and state the exhaustion condition, or label it INHERITED and unverified. A
  count is cheap to measure and expensive to retract — it is load-bearing for sizing,
  recommendations, and every ratio derived from it.
  NO EXCEPTIONS for a count that will appear in a report, a plan, or a recommendation.
  # WHY (2nd instance, 2026-08-02, THE CLI-FLAG SHAPE): reported "5 stale canary runs
  #   parked at the gate" from a `gh run list --limit 6` probe. The API's own
  #   `total_count` said **31**, and pagination exhausted on page 1 — so the real
  #   figure was 6x higher and the OLDEST parked run dated to the first fire after the
  #   change that caused it, which re-dated the whole outage. THE TELL IS A `--limit`
  #   / `--max-items` / `head -N` IN THE COMMAND THAT PRODUCED THE NUMBER: a display
  #   cap and a population are indistinguishable in the output, and the capped figure
  #   is the one that reads as a finding. Cheapest fix, one call: ask the API for its
  #   OWN total (`gh api ...?status=waiting --jq .total_count`) or page until a batch
  #   returns < page_size, and STATE THE EXHAUSTION CONDITION next to the count.
  #   Corollary: a count that moves 5 -> 31 on re-measurement invalidates every
  #   downstream claim derived from it (here: "the gate blocked 6 scheduled runs"
  #   became "it blocked every fire for 6 days").
  # WHY: 2026-08-01 gateway assessment — "144 personal API keys" was carried from stale
  #   Full: incidents#2026-08-01-gateway-assessment-144-personal-api-keys

GUARD pattern="I sampled N and M of them show the problem" — when the sample is a
  PREFIX of an ordered list (`items[:12]`, the first page, `head -20`, the top of a
  `list_*` API response, or a paginated pull that hit a page cap):
  REFUSE the population claim. A prefix of an id-ordered or creation-ordered list is ONE
  CONTIGUOUS BATCH, not a sample — consecutive ids were provisioned together, so they
  share a plan, config, deploy and lifecycle stage, and therefore share their defects AND
  their idleness. The slice is maximally correlated on exactly the variable you are trying
  to generalise over, so its agreement rate is an artifact — and it presents as a clean,
  alarming, fleet-wide finding, which is why it survives self-review.
  REQUIRED before reporting: (a) STRATIFY — step across the population
  (`items[::len//N]`) and state the sample's id SPAN and its count of distinct
  name/batch groups; (b) name the BENIGN condition that produces the SAME observation and
  find the field that discriminates it — "all zero" is also what NEVER-DEPLOYED looks
  like, so "has it EVER done X" separates broken from idle; (c) confirm the entity you are
  actually investigating is IN the sample — its absence is the tell that the pull was
  truncated. NO EXCEPTIONS for a count you will report as a population problem.
  # WHY: 2026-07-29 Hologram fleet census — the SAME error twice in one session, both
  #   Full: incidents#2026-07-29-hologram-fleet-census-the-same-error

GUARD pattern="I spot-checked SOME of the ambiguous operations and they had landed, so the
  rest did too" (a batch of writes/invokes/uploads that reported a CLIENT-side error —
  read timeout, connection reset, cancelled — where the work may still have completed
  server-side):
  RE-CHECK EVERY AMBIGUOUS OPERATION, NOT A SAMPLE. This is the sibling of the prefix
  GUARD above, and it is easier to walk into because the sample is not lazy — you DID
  verify, the evidence WAS real, and the verified ones genuinely landed. The error is the
  quantifier. An ambiguous-completion batch is not a homogeneous population: whether each
  call finished depends on that call's own size, duration and the service's state at that
  moment, so the earlier/smaller ones completing predicts nothing about the later/larger
  ones. Worse, a partial landing is INVISIBLE by construction — the artifacts exist for
  the ones that worked, so a spot check returns a clean bill of health for the batch.
  REQUIRED: verify the ambiguous set EXHAUSTIVELY, and verify the PROPERTY you actually
  care about, not merely that an object appeared (object-exists != column-populated !=
  row-count-correct). Prefer a single grouped query over the whole range that would expose
  a hole (`GROUP BY day` + `count_if(col IS NOT NULL)`) to N per-item existence checks.
  THEN fix the ambiguity itself: raise the client timeout above the server's real runtime
  so a completion is OBSERVED rather than inferred. NO EXCEPTIONS when a later step will
  treat the batch as complete.
  # WHY: 2026-07-31 gold-table `principal` backfill — `aws lambda invoke` (default 60s CLI
  #   Full: incidents#2026-07-31-gold-table-principal-backfill-aws-lambda

GUARD pattern="this fires only on a NEW / never-seen-before / first-time X, so it is a
  discrete STATE CHANGE and safe to alarm on" (any boolean predicate you are about to
  wire to an alarm, a page, or a findings count):
  REFUSE until you PLOT THE PREDICATE'S FIRING RATE over the retained history — one
  row per day, "on how many of the last N days would this have been non-empty, and
  how many items each day?". A BOOLEAN PREDICATE HAS A FIRING RATE exactly like a
  numeric threshold does, and measure-before-threshold applies to it identically.
  "Never seen before" phrasing does NOT make an OPEN-VOCABULARY set discrete: if the
  vocabulary keeps growing (principals, servers, plugins, hostnames, IPs, user-agents,
  file paths), first-sightings ARE a rate. The tell is the vocabulary, not the wording.
  A predicate that fires on most days is not a noisy alarm — it is a MUTED one, and it
  mutes every OTHER finding sharing that alarm's metric.
  REQUIRED before shipping: (a) the per-day firing distribution (not a total, not one
  sampled day); (b) for each shape reaching the alarm, the measured baseline that makes
  it alarmable — a shape with a genuine ZERO baseline is alarmable, a shape with a
  nonzero daily rate is REPORTED; (c) if any shape fires on >~10% of days, split it out
  of the alarm's metric rather than tuning it.
  NO EXCEPTIONS for a predicate wired to an alarm/page/findings count.
  # WHY: 2026-07-28 mcp-infra #737 → #739 (+ sibling mcp-servers #891) — a shipped
  #   Full: incidents#2026-07-28-mcp-infra-737-739-sibling-mcp

GUARD pattern="the check is expensive, so materialise / cache / index it" (when the
  check itself has not been validated as correct):
  EVALUATE CORRECTNESS FIRST. Optimising the COST of a wrong check is the comfortable
  wrong fix: it produces real measurable progress (21x, 500x) while leaving the defect
  in place, and it converts a loud problem into a cheap silent one. Ask "should this
  check exist, and does it fire at a defensible rate?" BEFORE "how do I make it fast?"
  If the answer to the first is no, the correct fix is DELETION, and the optimisation
  work is wasted in the most persuasive possible way.
  # WHY: 2026-07-28 — my own differential review of #737 named "materialise the
  #   Full: incidents#2026-07-28-my-own-differential-review-of-737

GUARD pattern="adversarial fixtures show worst case, that should be
  the grade":
  REFUSE letting the worst-case stress-test drive the aggregate.
  Adversarial fixtures are designed to surface FP-prone patterns;
  their F1 is not directly comparable to production. Grade
  production and adversarial on separate axes. NO EXCEPTIONS.

GUARD pattern="trajectory is irrelevant, only current state matters":
  EVALUATE: does the user's question imply a comparison ("why are
  these so low NOW" — implies vs prior)? If yes, trajectory is on
  the user's axis list. Include it. NO EXCEPTIONS when the question
  contains a temporal anchor word ("now," "still," "yet," "since").

GUARD pattern="this is a quick assessment, no need for the protocol":
  REFUSE for any letter-grade output. The protocol is six STEPs that
  total <2 minutes. The failure mode it prevents (publishing an
  80%-stale grade) costs the rest of the session to recover from.
  NO EXCEPTIONS for letter-grade output.

GUARD pattern="reporting a quantity you obtained by INTERPOLATING between measured points"
  — a value BETWEEN two rows of your own probe, a round number "near" a measured one, or any
  figure carrying a hedge (`~`, "about", "roughly", "approximately"):
  RE-RUN THE MEASUREMENT AT THE VALUE YOU ACTUALLY CHOSE. A probe sweeps a CANDIDATE LIST; the
  value that reaches the deliverable is frequently NOT in it, and the gap is invisible because
  the neighbouring rows are real. THE HEDGE IS THE TELL: a measured number needs no
  approximation marker, so `~N` in a deliverable is usually an admission that N was derived,
  not observed.
  REQUIRED before any quantity ships: the chosen value must appear in the candidate list of the
  run that produced it, or the run is repeated with it added. One command.
  MECHANICAL CHECK (do not rely on remembering this):
    python3 bin/number-provenance-check.py <deliverable> --evidence <run artifacts> --strict
  It flags hedged quantities and any currency / `N of M` / percentage absent from the cited
  evidence. Mutation-verified 4/4; 17 tests in `scripts/test_number_provenance.py`.
  NO EXCEPTIONS for a number that reaches a plan, a report, or an AskUserQuestion option.
  # WHY: 2026-08-02 gateway deploy plan — a blast-radius probe swept caps of 500..20000 CENTS
  #   ($5..$200) and the plan asserted "$N/day -> ~5 of 96 people touched". $500 was NEVER
  #   TESTED; the figure was interpolated from the $200 row. Measured: 13 of 96 (2.6x off), and
  #   19 of 348 person-days. It shipped into the plan AND into the option text of a decision the
  #   user then made, so the wrong number selected the cap posture. An adversarial cross-model
  #   review caught it; no gate did.
  # WHY THE AMBIENT RULE WAS NOT ENOUGH: the count-provenance GUARD above was authored FOUR HOURS
  #   EARLIER in that same session, by the same author, and was loaded ambiently the whole time.
  #   It did not fire. That is the argument for the mechanical check rather than stronger wording
  #   — and the reason authoring a guard is itself a risk: it creates a FEELING of coverage, so a
  #   number produced afterwards feels provenance-checked. Third documented recurrence of the
  #   class (2026-05-05 threshold-from-distribution, 2026-08-01 re-measure-at-final-grain "twice,
  #   same root cause", now this) — and the first two lived only in KB topics that never load.

GUARD pattern="a THRESHOLD, CAP, TIER BOUNDARY, or SEVERITY BREAKPOINT chosen as a round number"
  ($N/day, 0.8 = high, 100 rows, 30 days):
  DERIVE IT FROM THE DISTRIBUTION, AND STATE THE PERCENTILE IT LANDS ON. A breakpoint picked by
  intuition looks calibrated and almost never matches the input distribution. REQUIRED: report
  P50/P90/P95/P99 and name which one the value sits at, plus the BLAST RADIUS in affected units
  (people, requests, rows) — not the value alone. A cap is a decision about WHO gets interrupted,
  so affected-people is the honest unit.
  ALSO: a right-skewed distribution makes the MEAN the wrong estimator — measured 2026-08-02,
  per-user daily spend had mean $155.54 against P50 $52.00, a 3x gap, so any mean-derived cap
  blocks the top decile while leaving everyone else unbounded.
  NO EXCEPTIONS for a threshold that gates production behaviour.
  # WHY: promoted to T1 2026-08-02 from KB `engineering-assessment-measurement-validity`
  #   ("Threshold values must come from the distribution, not round numbers", 2026-05-05). It sat
  #   KB-only for ~3 months, never loaded, and did not fire on the gateway cap design.

# ─── EXAMPLES ───

## GOOD: axis table + pre-registered thresholds + currency stamps

Threshold: scope-aligned F1 ≥ 0.95 → A; 0.85-0.95 → B; 0.70-0.85 → C;
<0.70 → D. Production and adversarial fixtures graded separately.

| Axis | Metric | Source | Mtime | Freshness | Grade |
|---|---|---|---|---|---|
| Production Python | mcp-servers F1 SA = 0.989 | baselines/2026-05-10-mcp-servers-report.json | 2026-05-10 13:11 | [FRESH] | A |
| Production Go | code-graph-go F1 SA = 0.975 | baselines/2026-05-10-code-graph-go-report.json | 2026-05-10 13:18 | [FRESH] | A |
| Production Rust | PSM F1 SA = 0.913 | baselines/2026-05-10-example-monorepo-rust-report.json | 2026-05-10 | [FRESH] | B+ |
| Adversarial Python floor | Flask F1 SA = 0.492 | baselines/2026-05-10-flask-adversarial-report.json | 2026-05-10 | [FRESH] | D (stress-test, not production) |

Aggregate (collapse on production axis): **A−** for code-graph CALLS.

## BAD: single letter from one doc

"code-graph CALLS Python: D+ (Flask 0.49)" — anchors on the worst case
without naming the axis, without stamping freshness, without
disclosing that mcp-servers production is A.

# ─── FAILURE MODES to recognise ───

FAILURE graded_gap_doc_as_state_doc:
  # INCIDENT 2026-05-10 code-graph grade: cited accuracy-gap-inventory.md
  #   Full: incidents#2026-05-10-code-graph-grade-cited-accuracy-gap
  RECOVERY: re-read the newest doc when same-day docs disagree.
  Apply STEP_6 — gap docs and state docs are different artifacts.

FAILURE single_letter_without_axis_table:
  RECOVERY: produce the axis table retroactively, surface which axis
  the letter was collapsing on, let the user pick.

FAILURE pessimistic_anchor_from_worst_fixture:
  RECOVERY: separate production-fixture grade from adversarial-fixture
  grade. Adversarial is a stress-test floor, not the production grade.

FAILURE stale_metric_cited_without_freshness_stamp:
  RECOVERY: add the stamp + disclaimer. If the metric is OLD (>7d), say
  "this needs re-baselining before citation."

# ─── INTEGRATION WITH OTHER RULES ───

- `verify-effectiveness.md` ("Verify the instrument before fixing the subject"; its own rule until 2026-09-03) — "baselines decay between authoring
  and execution" is the parent failure mode. This rule is the
  grading-output-side specialization.
- `red-team-rubric-discipline.md` — multi-mode artifacts need explicit
  per-mode severity. Same applied to grading: multi-axis systems need
  explicit per-axis grades.
- `eval-shipping-discipline.md` — significance evidence for ship
  decisions. This rule is the analogous discipline for grade-output
  decisions.
- `symmetric-evidentiary-burden.md` — refutations need same source bar
  as claims. Same applied to grading: a low grade needs same evidence
  bar as a high grade.

GUARD pattern="the measurement is clean, so <N> is THE LIMIT / the ceiling / what the platform
  can do" (reporting a measured floor or cap as a CAPABILITY boundary):
  SEPARATE THE MEASUREMENT FROM THE INFERENCE AND GRADE THEM AGAINST DIFFERENT BARS. A
  measurement is falsifiable by better method ("was the instrument sound and unsuppressed?");
  an INFERENCE from it is falsifiable by DOCUMENTATION ("does the mechanism I just asserted
  actually exist?"). Grading them together hides the common case where the number is right and
  the conclusion drawn from it is wrong.
  THE TELL: a measured boundary landing on a ROUND NUMBER, or on a value matching a documented
  DEFAULT (366d ~= 1 year, 180d, 30d, 90d, 100, 1000). A default and a ceiling produce the
  IDENTICAL observation, so the measurement cannot distinguish them — only the vendor doc can.
  REQUIRED before publishing any "X is the limit" claim: read the vendor's own doc for the
  knob, and state which you measured — a DEFAULT (changeable), a POLICY (changeable, possibly
  already customised), a LICENSE gate (buyable), or a HARD limit (immovable). "Configured
  value" and "platform maximum" are different claims and only the last closes off the user's
  goal.
  ALSO FORBIDDEN: `-ErrorAction SilentlyContinue` / `2>/dev/null` / `|| true` on the probe
  whose ZEROS you will interpret — suppression makes a failed query and an empty result
  identical, and the interpretation is the whole deliverable. Re-run capturing warnings and
  errors before the zero becomes a finding.
  NO EXCEPTIONS for a limit/ceiling claim that reaches the user or shapes a recommendation.
  # WHY: 2026-07-31 Purview audit retention — measured "0 AAD records past ~366 days" with
  #   Full: incidents#2026-07-31-purview-audit-retention-measured-0-aad

# ─── WHAT DOES NOT REQUIRE THIS RULE ───

- Casual "how's the system doing?" with no letter-grade output
- Internal debugging of a specific failing test (the grade isn't the
  output)
- Pure factual queries ("what's the current F1 on X?") — answer with
  number + mtime, no grade collapse
- User explicitly framed it as a gut check / opinion

GUARD pattern="grade a capability ABSENT / list 'build X' as an open item / PROPOSE A FIX
  for a defect you just diagnosed / answer 'what should we do about X'" (any gap claim
  inside a grade, AND any remediation proposal — the trigger is proposing work that does
  not exist yet, however the sentence is phrased):
  GREP THE REPO FOR X BEFORE GRADING IT MISSING. STEP_1's memory_search is necessary and
  NOT sufficient: memory returns TOPIC PROSE, and a built-but-never-run tool leaves no
  prose because nobody wrote about it — the tool IS the record. So the single artifact
  that would refute the gap is invisible to the mandated check.
  REQUIRED, one command, before any "absent" verdict:
    git ls-tree -r --name-only origin/main | grep -iE '<capability nouns>'
  plus `ls bench/ scripts/ tools/` for the domain. If it exists, the finding is not
  "build X" — it is "X exists and has never been RUN", a different grade and a far
  cheaper fix.
  NO EXCEPTIONS for a gap reported as an open item.
  # WHY: 2026-07-30 detection-accuracy grade — graded it C ("UNCHARTED;
  #   Full: incidents#2026-07-30-detection-accuracy-grade-graded-c
  # WHY THE TRIGGER MISSED: the framing was "what should we fix?", not "grade this
  #   Full: incidents#the-trigger-missed-the-framing-was-what-should-we


GUARD pattern="gate a destructive action on a counter or flag" ('skip removals if errors>0',
  'abort when unmatched>0', 'only proceed if the set is complete'):
  MEASURE THE GATE SIGNAL'S STEADY-STATE FLOOR BEFORE SHIPPING THE GATE. The ALARM form of
  this is the firing-rate GUARD above (a predicate that fires most days is MUTED). The GATE
  form is its mirror and is WORSE, because it fails SILENT instead of loud: an interlock whose
  signal has a nonzero floor is permanently ENGAGED, so the guarded action NEVER RUNS while
  its enabling flag still reads "on". Nobody gets an alarm — they get a feature that appears
  configured and quietly does nothing.
  REQUIRED before shipping: (a) COUNT the signal over real data and state its floor; (b) if
  the floor is nonzero, SPLIT the signal — the PERMANENT population must not gate, only the
  TRANSIENT one may; (c) assert the gate's own PASS-RATE, not merely that its logic is correct.
  NO EXCEPTIONS for a gate on a destructive or irreversible action.
  # WHY: 2026-07-31 azure-automations `cui-entra-sync-daily` — group removals were hard-blocked
  #   Full: incidents#2026-07-31-azure-automations-cui-entra-sync-daily

# Append concrete technique to the existing "grade a capability ABSENT ... GREP THE REPO"
# GUARD in grading-discipline.md:
# CONCRETE RECIPE (2026-07-31, 3rd same-session recurrence): a diagnosis that starts from a
# SYMPTOM surface (a firing alarm, an anomalous number) never intersects a search over the
# CODE surface (test filenames, docstrings) — so "I diagnosed it myself" carries no evidence
# the finding is novel. Before treating any diagnosis as new: `ls scripts/test_* | grep -i
# <noun>` (or grep test files/docstrings for the mechanism's noun). This would have caught
# all 3 instances this session (a bearer-token-rotation fix, a gold/bronze event_name
# mapping, an attribute-subfield coalescing bug — all already shipped and tested).

GUARD pattern="setting a CAP/LIMIT in unit A to bound a constraint denominated in unit B"
  (a BYTE upload cap to bound a TOKEN context window; a row cap to bound bytes; a request
  cap to bound spend; a file-count cap to bound anything):
  MEASURE THE FULL CONVERSION CHAIN, AND STATE ITS WORST-CASE RATIO — a cap is only as sound
  as its least-measured hop. Deriving ONE hop rigorously and assuming the rest is the trap:
  the rigor on the measured hop makes the whole number feel derived, so nobody re-checks the
  hop you skipped. The tell is a chain with more arrows than you took measurements.
  REQUIRED: enumerate every hop (bytes -> extracted text -> tokens), measure EACH across the
  real input MIX, and report the WORST ratio, not a typical one. A hop whose ratio SPANS
  formats (1x for .txt, 5.4x for .docx — measured 2026-08-02) cannot be bounded by a single
  cap at all; say so instead of picking a value that is safe for one format and wrong for
  another.
  IF the chain is unboundable, the cap is a USABILITY control, NOT a safety control — set it
  for usability, say which it is, and let the real constraint fail loudly at its own layer.
  A cap sold as "makes overflow structurally impossible" when it does not is worse than no
  cap: it retires the question.
  NO EXCEPTIONS for a cap described to the user as preventing a failure.
  # WHY: 2026-08-02 Inkling upload cap — THREE sequential wrong claims shipped to the user,
  #   each corrected by the next: (1) "50 MB is ~12x the window" [bytes read as tokens];
  #   (2) "3 MB + COUNT=1 makes overflow structurally impossible" [true ONLY for plain text];
  #   (3) "a byte cap cannot bound context at all" [correct]. The tokenizer hop WAS measured
  #   properly (6.45 / 4.62 / 2.71 / 2.00 chars-per-tok by content type) — which is exactly
  #   why (2) felt derived. The unmeasured hop was file->extracted-text, and a .docx expands
  #   5.4x, so a 3 MB Word file blew the 1M window while sitting under the "safe" cap.
  #   Bounding a .docx structurally needs ~600 KB — unusable. Final: 25 MB for usability.

GUARD pattern="counting occurrences of a STRUCTURED FIELD as evidence its ACTION was performed"
  (`grep -c '**CVE check**'` -> 12, so 12 reviews ran one; N records carry `reviewed_by`, so N
  were reviewed):
  READ THE VALUES, NOT THE KEYS. A well-formed field can RECORD A NEGATIVE — `NOT RUN`, `none`,
  `n/a`, `pending` — so presence proves the field was FILLED IN, never that the work happened.
  The grep is honest and the inference is not, which is why it survives review.
  INVERSE of the counter trap in KB `engineering-assessment-measurement-validity` ("a counter
  answers 'has it acted?', never 'does it exist?'") — same axis, opposite direction; neither
  covers the other.
  REQUIRED: print the VALUES beside the count and subtract the negatives, or state the claim as
  "N records carry the field", which is what you measured.
  NO EXCEPTIONS for a count offered as evidence that a process ran.
  # WHY: 2026-08-04 software-approval review — "12 of the recorded decisions ran an explicit CVE
  #   check" came from `grep -c` = 12. Values: 11 ran; the 12th read `CVE check: NOT RUN for this
  #   vendor` — the MCT entry that was that same answer's centerpiece. Off by one toward
  #   flattering the process, inside a paragraph arguing the CVE gate earns its keep.

GUARD pattern="pre-registering thresholds MID-SESSION, after already reading the evidence in
  earlier turns" (a conversational grade request routinely arrives AFTER turns of exploring the
  artifact, so STEP_3's "state them BEFORE looking at the numbers" is already unsatisfiable):
  DECLARE THEM POST-EXPOSURE AND NAME THE AXES YOU HAD ALREADY SEEN. Presenting post-exposure
  thresholds as pre-registered claims an anti-anchoring property the grade does not have, so the
  reader cannot discount for it. Anchoring risk is HIGHEST on the axes you explored first — their
  evidence shaped the threshold they were then graded against.
  REQUIRED: one line, e.g. "thresholds set after reading Gates 4/12; pre-registered for the other
  five." Then hold them fixed for the rest of the grade.
  NO EXCEPTIONS for a graded output produced later in a session than its evidence.
  # WHY: 2026-08-04 software-approval rubric grade — wrote "stated before I look at the numbers"
  #   while Gates 4, 9b and 12 had been read two turns earlier for a different question. The A-
  #   may be sound, but its strongest axes were the pre-read ones and the output hid that.

GUARD pattern="reporting a SURVEY / CENSUS / 'I checked all N' from a loop that was KILLED BY A
  TIMEOUT" (exit 143 or 124, "Command timed out", a harness-truncated background task):
  A TIMED-OUT LOOP EMITS PARTIAL OUTPUT THAT READS AS A FINISHED ONE. The rows it printed are
  CORRECT — they are just not all of them — so the transcript shows a clean table and nothing
  in it says "stopped early". This is the count-provenance GUARD above with the cap IMPOSED
  rather than requested: no `--limit` / `head -N` appears in the command, so the usual tell is
  absent and the output looks like a completed enumeration.
  REQUIRED before any completeness claim: confirm the loop REACHED ITS LAST ITEM — echo a
  terminal sentinel after the loop, or compare the output row count to the input list's length.
  A survey whose last input never appears in its output is UNFINISHED, not empty.
  NO EXCEPTIONS for an enumeration a determination rests on.
  # WHY: 2026-08-04 mirror rollout — a loop grepping 214+85 test files for a guard-form
  #   assertion hit the 2-minute Bash timeout (exit 143) partway through the FIRST repo. Its
  #   partial output said "2 enforcing tests"; the real count was 4, and the 2 it missed pinned
  #   the same string inside UNRELATED contracts (a credential-free-job check, a
  #   concurrency-group check). That truncated survey shipped as a finding and drove a
  #   recommendation to the user that then had to be retracted twice — once as wrong, once as
  #   wrong in the opposite direction.
