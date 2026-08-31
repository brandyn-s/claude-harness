@rule validate_to_improve
@version 2026-04-20
@scope every test, validation, review, or "done" claim; every batch of changes; every function touching shared state

# ─── INVARIANTS (always-true) ───

INVARIANT validation_produces_fix_list_not_pass_fail
  # WHY: "all tests pass" with 6 unmentioned issues ships the issues.
  #   Full: incidents#all-tests-pass-with-6-unmentioned-issues-ships-the

INVARIANT metadata_and_behavior_changes_never_mix_in_same_PR
  # WHY: safe metadata batches drown out risky behavior changes.
  #      skills-polish (2026-03-20): 9 changes, 2 required corrective PR.

INVARIANT interruption_safety_is_documented_on_stateful_functions
  # WHY: partial writes leave dirty state. Hooks, async methods, and
  #      background agents all can be interrupted mid-execution.

# ─── PROCEDURE: after every test/validation cycle ───
ANSWER these 6 questions BEFORE declaring done:
STEP_1 Correctness: what failed? what's fragile? what's one edge case away?
STEP_2 Test quality: what has zero automated coverage? what depends on live DBs/network/real creds?
STEP_3 Thresholds/heuristics: are magic numbers calibrated or guesses? would real input expose a bad default?
STEP_4 Consistency: do counts match across related stores? do schemas stay in sync?
STEP_5 Resilience: what happens on crash, kill -9, power loss? journal mode right? writes atomic?
STEP_6 Typos/doc drift: did I misread something? docstrings match behavior?

REQUIRED output: fix list ranked by impact ALONGSIDE the test results
REQUIRED ask: "Want me to fix all of these?" — don't wait to be asked
FORBIDDEN: "fully functional and working as intended" with unspoken issues

# ─── PROCEDURE: a GENERATED VISUAL artifact is not verified until it is RENDERED ───
# Fires on any HTML/SVG/PNG/PDF deliverable whose value is visual — a chart, a report, a
# dashboard, a diagram. Applies even when every declarative check passed.
STEP_1 run the declarative checks (palette validator, tag balance, linter, schema). These
        are necessary and they are BLIND TO GEOMETRY — a colour validator scores hues, not
        whether a mark has area.
STEP_2 RENDER it and LOOK at the pixels. Headless is enough and needs no extra tooling:
          "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
            --disable-gpu --no-sandbox --hide-scrollbars \
            --screenshot=out.png --window-size=<w>,<h> "file://<abs-path>"
        Then READ the image. Crop/zoom the data region — a full-page shot at 1:3 scale
        hides a zero-height bar.
STEP_3 measure the document's REAL height and confirm nothing is CLIPPED: scan up from the
        bottom row for the last non-uniform row; if it equals the window height, the shot is
        truncated and the tail was never inspected. Re-render taller.
STEP_4 for a themed artifact, render EVERY theme. A dark-mode-only render cannot exercise a
        light-mode contrast finding, and vice versa.
FORBIDDEN: calling a visual artifact done on declarative checks plus a code read. The
            failure mode is an element that renders at ZERO AREA — no error, no console
            warning, no layout shift, and the markup reads correctly.
# WHY: 2026-08-01 gateway report — a `<span class="bar-fill">` inside a grid item stayed
#   Full: incidents#2026-08-01-gateway-report-a-span-class-bar-fill

# ─── PROCEDURE: a SCHEDULED job is not verified until its OUTPUT advanced ───
# Fires on any job run headless on a timer (launchd/cron/CI schedule) that invokes a
# SKILL, or any workflow containing a HUMAN GATE — an approval prompt, "Reply 'go'",
# an AskUserQuestion, a confirm-before-write step. Sibling of the rendered-artifact
# procedure above: there the declarative check passes while the pixels are blank; here
# the exit code is 0 while the product was never written.
STEP_1 BEFORE scheduling a skill headless, GREP IT FOR ITS GATES:
         grep -niE "user approval|reply .go|AskUserQuestion|confirm before|ask the user" SKILL.md
       A gate nobody can answer is not a PAUSE, it is a TERMINATION — and the process
       exits 0 on the way out.
STEP_2 verify the job by its OUTPUT's mtime and size, never by its exit code and never
       by the mere existence of a log file. A gated run still opens the log, writes a
       plausible preamble, and exits clean: the log EXISTS, and is STALE.
STEP_3 keep an UNGATED sibling job as the control. If job A's output is stale while
       job B's is fresh on the SAME scheduler, the scheduler is exonerated and the
       difference is inside the job — which is the whole diagnosis, for free.
FORBIDDEN: scheduling an approval-gated skill headless and reading exit 0 as success.

# ─── PROCEDURE: batch changes discipline ───
STEP_1 CLASSIFY each change:
         (a) METADATA-ONLY: descriptions, hints, docs, comments
         (b) BEHAVIOR: model, context mode, permissions, feature flags, execution path
STEP_2 Metadata-only changes ship TOGETHER (low-risk, high-volume)
STEP_3 Behavior changes ship INDIVIDUALLY or in a small group of 2-3
STEP_4 FORBIDDEN: mix metadata + behavior in one PR

# ─── PROCEDURE: interruption-safety documentation ───
REQUIRED for any non-trivial function touching shared state (files, DBs, git, network):
  Format: `// INTERRUPTION: [safe|unsafe] — [what happens if interrupted mid-execution]`

Non-interruption-safe methods MUST document WHY that's acceptable in context.
  Example: "connection is either terminated or recreated, never reused in a broken state"

APPLIES TO:
  - Python hooks (interrupted mid-hook → dirty state? half-written file? unreleased lock?)
  - Rust async methods (tokio::select! cancels → connection leaks? cancellation-safe?)
  - Background agents (killed mid-write → what's the disk state?)

# ─── USER OVERRIDE POLICY ───
# Validate-to-improve is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="tests pass, we're done":
  REFUSE. Answer the 6 questions before declaring done. Produce fix list.
  NO EXCEPTIONS.

GUARD pattern="let's batch all 9 changes into one PR":
  CLASSIFY first. IF 2 are behavior changes → split. NO EXCEPTIONS.

GUARD pattern="metadata + behavior can ship together, they're small":
  REFUSE. Behavior changes need check-before-change verification that
  metadata changes don't. NO EXCEPTIONS.

GUARD pattern="the scheduled job is configured and exits cleanly, so it is running":
  REFUSE. READ THE OUTPUT'S AGE. An approval-gated skill run headless is a SILENT
  NO-OP — it cannot receive the answer, so it stops at the gate and exits 0: no error,
  no alarm, and a log file that exists and looks plausible. Nothing distinguishes it
  from a healthy run except the age of what it produced. NO EXCEPTIONS for a job whose
  product nobody reads daily — that is exactly the job that can be dead for weeks.
  # WHY: 2026-08-01 — com.example.claude.gather-intel runs `claude -p "/gather-intel"`
  # on a timer, and /gather-intel requires "user approval on per-section" before it
  # writes anything. It had produced NOTHING for 5.7 days while exiting 0 every run.
  # The control settles it: com.example.claude.garden, SAME launchd mechanism, NO gate,
  # log fresh at 0.9 days. The gate is the discriminator, not the scheduler.

GUARD pattern="user didn't ask for a fix list":
  REFUSE silence. Surface the issues proactively. User expects the full
  picture, not pass/fail. NO EXCEPTIONS.

GUARD pattern="interruption doesn't apply, this function is simple":
  EVALUATE: does it touch files/DB/git/network? If yes → document
  interruption safety. NO EXCEPTIONS for shared-state functions.

# ─── FAILURE MODES to recognise ───

FAILURE declared_pass_with_6_unspoken_issues:
  # INCIDENT memory-search (2026-03-20): 8 tools, 22 tests, 6 issues in
  #   Full: incidents#memory-search-2026-03-20-8-tools-22-tests
  RECOVERY: present fix list, offer "fix all of these?"

FAILURE batched_behavior_changes_with_metadata:
  # INCIDENT skills-polish (2026-03-20): 9 changes, 7 safe metadata, 2
  #   Full: incidents#skills-polish-2026-03-20-9-changes-7-safe
  RECOVERY: split PRs by type; apply check-before-change to behavior ones.

FAILURE undocumented_interruption_behavior:
  # Shared-state function interrupted → dirty state requires recovery;
  # recovery logic is ad-hoc because behavior was never documented.
  RECOVERY: add INTERRUPTION comment; document recovery path.

# ─── WHAT COUNTS AS BEHAVIOR VS METADATA ───
METADATA (safe to batch):
  - description, argument-hint, docs, comments
  - new example section in skill body
  - doc links

BEHAVIOR (individual or 2-3 max):
  - model: frontmatter override
  - context: fork (subagent context)
  - allowed-tools: additions or removals
  - disable-model-invocation toggle
  - feature flags, hook configuration
  - permission changes
  - error handler changes

# ─── REFERENCE: jonhoo faktory-rs pattern (source) ───
Every async method in faktory-rs has explicit cancellation-safety docs.
Generalized beyond Rust to all languages: any function touching shared
state gets an INTERRUPTION comment.

# ─── PROCEDURE: a verifier must assert the BEHAVIOUR the change was FOR ───
# Fires on any change shipped behind a self-written verify/rollback wrapper — a
# configure-X script, a migration with auto-revert, a deploy with a health gate.
STEP_1 name the behaviour the change EXISTS to produce, in one sentence, BEFORE writing
        the verifier. That sentence is the assertion. If the verifier does not contain it,
        the verifier does not test the change.
STEP_2 forbid liveness-only assertions as the gate. "Still listed", "still returns 200",
        "process still up", "row readback matches what I wrote" are all TRUE while the
        feature under test emits garbage — they assert the system SURVIVED the change, a
        strictly weaker claim than the change WORKED. Readback is the seductive one: it
        confirms the write, never the effect.
STEP_3 EXERCISE THE ROLLBACK PATH before relying on it, on a throwaway target. A rollback
        only runs when something has already gone wrong, so the happy path never touches
        it — it is the least-tested code in the change and the code you need most.
STEP_4 treat NON-DETERMINISM as a stop signal, not a tuning signal. Two identical calls
        returning different results means the state is uncertain; stop iterating and
        return to the last DEFINITIVELY known-good state (delete the row, revert the
        deploy) rather than tuning against a moving target.
FORBIDDEN: shipping a change whose verifier's assertions would all still pass if the
           feature produced no output at all.

GUARD pattern="the config applied cleanly, the readback matches, and nothing broke — it works":
  REFUSE the works verdict. CONFIG-VERIFIED IS NOT BEHAVIOUR-VERIFIED. Run the behaviour the
  change was for and assert on ITS output. NO EXCEPTIONS for a user-facing capability.
  # WHY: 2026-08-02 Inkling workspace-model row — create_status=200, model still listed,
  #   chat still returning, readback showed exactly the intended capabilities: every check
  #   my own script made PASSED. The behaviour test then showed raw model control tokens
  #   (`<|message_model|>web_search<|content_invoke_tool_json|>...`) leaking into
  #   user-visible replies — strictly worse than the feature it replaced. Reverted.
  #   The auto-rollback ALSO failed when finally called: it POSTed /model/delete with no
  #   body and the endpoint requires a ModelIdForm (422). It had never fired, because the
  #   create had always succeeded. An unexercised rollback is a hypothesis.

GUARD pattern="my negative control returned zero findings, so the allowlist/filter I just added
  broke the scanner" — OR any fixture-based check whose result you are about to believe:
  SUSPECT THE FIXTURE BEFORE THE SYSTEM. Two measured shapes, both of which produce a
  confident wrong answer from a correctly-working tool:
   (a) A CONTROL BUILT FROM A VENDOR'S DOCUMENTATION EXAMPLE. Canonical sample values
       (AWS's `wJalrXUtnFEMI/K7MDENG...`, `AKIAIOSFODNN7EXAMPLE`, example.com, 555 numbers,
       RFC test vectors) are ALLOWLISTED BY DEFAULT in the very scanners you are testing —
       so a zero means "your fixture is famous", not "the scanner is dead". Use a freshly
       generated high-entropy value.
   (b) A FIXTURE BUILT BY REPETITION. Repeating one paragraph N times to reach a target size
       measures the COMPRESSOR, not the content: a .docx of 1,200 identical paragraphs
       compressed 122x, while varied prose of the same size compressed 5.4x — a 22x error,
       in the direction that would have driven the decision.
  REQUIRED: before trusting a control, prove it FIRES on a known-positive built the same way
  you built the negative. A clean scan and a dead scanner are indistinguishable without it.
  NO EXCEPTIONS for a control whose result gates a ship decision.
  # WHY: 2026-08-02, both in one session (gitleaks allowlist verification; docx ratio probe).

# ─── PROCEDURE: every seam in a multi-component feature needs a NAMED OWNER ───
# Fires when >=2 independently-authored components must meet — image + IaC, producer +
# consumer, template + renderer, module + environment — and hardest under PARALLEL
# authoring, where no author can see the other's interface. Sibling of the two procedures
# above: there a declarative check passes while the product is blank; here EVERY check
# passes and the product was never assembled at all.
STEP_1 list the seams and, for each, NAME THE FILE THAT OWNS IT. A seam whose owner you
        cannot name is unowned — that is the finding, not a gap in your notes.
STEP_2 read BOTH sides' comments at each seam. The dangerous shape is MUTUAL DISCLAIMER:
        side A says "X owns this", side B says "whoever owns Y does" — each internally
        correct, the composition holed. A well-reasoned disclaimer reads as a deliberate
        architectural decision, so reviewers stop there. THE RIGOR OF THE COMMENT IS WHAT
        HIDES THE HOLE; an undocumented boundary gets noticed when someone traces the
        wiring, a well-argued one does not.
STEP_3 for every value the design calls "pinned", grep it end to end and confirm a
        CONSUMER reads it. Declared + validated + re-emitted as an output is DECORATIVE,
        and a gate comparing an input to itself passes forever. Use a WIRED SIBLING as the
        control: if `image_digest` reaches the module and `config_sha256` does not, that
        asymmetry IS the bug — you do not need to reason about either one alone.
STEP_4 confirm any procedure the DOCS PRESCRIBE has been executed at least once. A
        documented runbook step can be structurally impossible (its network path or
        permission never existed) and nothing surfaces that until somebody runs it.
FORBIDDEN: reading `terraform validate` / `plan` / a green unit suite as evidence the
            seams are wired. None of them executes a seam.
# WHY: 2026-08-02/03 claude-gateway — the rendered config was NEVER DELIVERED to the
#   container: `config/README.md` assigned the `templatefile()` call to the Terraform
#   module, `ecs.tf` said it "deliberately does not render or mount gateway.yaml" and
#   deferred to "whichever module/build step owns the image", and the Dockerfile never
#   copied one. Every task would have crash-looped. `terraform validate`, `plan`, and 254
#   unit tests were all green. TWO more instances the same session: the Dockerfile shipped
#   an RDS CA bundle at a documented path that NOTHING referenced (TLS then failed at boot),
#   and the RDS security group had ingress only from the app SG — so the DOCUMENTED
#   migration procedure, which prescribes the migration SG, could never have run either.
#   `config_sha256` was the decorative pin; `image_digest` was the control that proved it.
