@rule symmetric_evidentiary_burden
@version 2026-04-29
@scope every audit, "objective assessment," critique, refutation, or "what's wrong with this" task

# ─── INVARIANTS (always-true) ───

INVARIANT refutation_requires_same_evidence_bar_as_proposal_would_need
  # WHY: when assessing a proposal, treating proposal-claims as needing
  #   Full: incidents#when-assessing-a-proposal-treating-proposal-claims-as-needing

INVARIANT absence_of_supporting_evidence_is_not_refutation
  # WHY: "I haven't read about this" is a property of your search, not
  #   Full: incidents#i-haven-t-read-about-this-is-a-property

INVARIANT citation_must_match_claim_domain_and_era
  # WHY: pre-LLM human-engineering studies (Becattini 2019), pre-Claude
  #   Full: incidents#pre-llm-human-engineering-studies-becattini-2019-pre-claude

INVARIANT single_source_is_preliminary_signal_not_refutation
  # WHY: a single primary source is "evidence consistent with refutation,"
  #   Full: incidents#a-single-primary-source-is-evidence-consistent-with-refutation

# ─── PROCEDURE: when asked for "objective assessment" / audit / critique ───

STEP_1 classify the task: is this a load-bearing assessment that affects
       downstream decisions? If yes, treat as research task, not opinion prompt.
STEP_2 identify the claims being assessed. List them explicitly.
STEP_3 for each claim, plan the evidence search before drafting any
       conclusion. Apply the same depth standard you would expect of the
       claim's proposer.
STEP_4 for LLM-behavior claims about specific model classes (Opus 4.5+,
       GPT-5+, Gemini 3+), require:
         (a) primary sources tested on that model class or successor, and
         (b) sources from the last 18 months.
       Sources outside this window are "needs corroboration" — do not
       treat as primary evidence.
STEP_5 distinguish four verdict categories explicitly:
         REFUTED — multiple independent recent sources contradict the claim
         CONTESTED — evidence on both sides; document both
         UNCHARTED — no published evidence either way (see uncharted-vs-refuted.md)
         SUPPORTED — multiple independent recent sources confirm
       Single-source "refutations" go in CONTESTED with the source noted as
       preliminary.
STEP_6 before presenting the assessment, run /interview against your
       own draft. Adversarial stress-test of your refutations, not just the
       proposal's claims.

# ─── USER OVERRIDE POLICY ───
# Symmetric burden is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="single source is enough because the claim was speculative":
  REFUSE. The bar for refutation is symmetric to the bar a careful
  proposer would meet. Speculation in the proposal does not lower the bar
  on counter-evidence. NO EXCEPTIONS.

GUARD pattern="I'm confident even without corroboration" or "I know this is wrong":
  REFUSE confident assertion without multi-source citation. Confidence is
  not evidence. Run the searches. NO EXCEPTIONS.

GUARD pattern="absence of evidence is evidence of absence":
  REFUSE. That's a known logical fallacy. Tag as UNCHARTED, not REFUTED.
  Cite the search you ran (queries, dates, sources scanned) so future-you
  can tell what you actually checked. NO EXCEPTIONS.

GUARD pattern="this old paper is fine for an LLM-era claim":
  REFUSE pre-LLM citation as primary evidence on LLM-era behavior. Becattini
  2019 (human design) cannot refute Opus 4.7 analogical performance. 2013
  TRIZ review cannot refute 2026 LLM+TRIZ tooling. Sources outside the
  18-month / model-class window are flagged "needs corroboration." NO EXCEPTIONS.

GUARD pattern="user is asking for my opinion not a research task":
  EVALUATE: does the assessment affect a downstream decision (build/skip,
  refute/accept, ship/hold)? If yes → research task, gather-research depth.
  If purely conversational/curiosity → opinion is fine. When in doubt,
  treat as research task. NO EXCEPTIONS for downstream-affecting assessments.

GUARD pattern="this is just a quick gut check" or "I'll add citations later":
  REFUSE. Refutations published without citations don't get retroactively
  validated; they get propagated. Cite or reframe as CONTESTED. NO EXCEPTIONS.

GUARD pattern="the chat was wrong because voice mode escalates":
  EVALUATE: is the proposal-source weakness an argument against the
  proposal's CLAIMS, or just against the proposal-author's confidence
  level? Proposal weakness reduces claim-confidence but does not
  refute the underlying ideas. Don't conflate. NO EXCEPTIONS.

# ─── FAILURE MODES to recognise ───

FAILURE single_source_refutation_propagated_as_consensus:
  # INCIDENT 2026-04-29 chat-audit: refuted hyperpolation ceiling, abduction-in-LLMs,
  #   Full: incidents#2026-04-29-chat-audit-refuted-hyperpolation-ceiling-abduction
  RECOVERY: when called out, run multi-source verification BEFORE doubling
  down. Acknowledge over-claimed refutations. Update verdict matrix.
  Better: don't get there in the first place — gather-research depth on
  every audit-class request.

FAILURE pre_llm_citation_for_llm_behavioral_claim:
  # INCIDENT 2026-04-29: Becattini 2019 (human engineering design study)
  #   Full: incidents#2026-04-29-becattini-2019-human-engineering-design-study
  RECOVERY: replace with current-era sources (≤18 months, model-class match).
  If none exist, downgrade to UNCHARTED.

FAILURE asserted_refutation_without_citation:
  # INCIDENT 2026-04-29: claimed "Dada/Surrealism doesn't transfer to LLMs"
  #   Full: incidents#2026-04-29-claimed-dada-surrealism-doesn-t-transfer
  RECOVERY: every refutation in the published assessment must trace to a
  cited source. Remove or cite. UNCHARTED is fine; bare assertion is not.

FAILURE verified_behaviour_of_ONE_endpoint_generalized_to_its_SIBLINGS:
  # INCIDENT 2026-07-30 Airlock: a CONTROLLED TEST proved
  #   Full: incidents#2026-07-30-airlock-a-controlled-test-proved
  RECOVERY: state the SCOPE of a behavioural finding as the exact endpoint/resource tested.
  Before applying it to a sibling, re-verify by READ-BACK on that sibling — the write's own
  return value is not evidence. Same-family API endpoints routinely differ in no-op,
  partial-object and validation semantics (measured same day:
  `/group/settings/updateall` rejects PARTIAL settings objects; `custom_otp` caps at 5 values).

FAILURE single_instance_generalized_to_a_class_in_a_SYSTEM (the same failure, internal):
  # INCIDENT 2026-06-20 accuracy-measurement P4: claimed "the LLM judge emits no
  #   Full: incidents#2026-06-20-accuracy-measurement-p4-claimed-the-llm
  RECOVERY: when about to claim "the system does/doesn't do X", grep for ALL instances of
  the role first; cite which instance(s) the claim covers. A diagnosis from instance #1 of
  N is preliminary, not a verdict. Pairs with `diagnose-before-fix.md` (read the decision
  function's contract) and `verify-before-assuming.md` (enumerate every surface).

# ─── INTEGRATION WITH EXISTING SKILLS ───

When invoked alongside:
  - /gather-research: this rule applies to BOTH the proposal claims and
    your refutations of them. Run searches symmetrically.
  - /interview: this rule fires automatically — /interview should
    stress-test YOUR claims with the same rigor as the proposal's claims.
    If you've refuted >=2 proposal points, /interview is mandatory before
    presenting.
  - /evaluate-repos: advocate/skeptic agents both inherit this rule —
    skeptic cannot refute on single source any more than advocate can
    propose adoption on single source.
  - /fp-check: same. False-positive verdicts need same source bar as
    true-positive verdicts.

# ─── WHAT DOES NOT REQUIRE THIS RULE ───

- Casual conversation / curiosity questions (no downstream decision)
- Reporting facts/numbers from a single authoritative source (e.g., "the
  Anthropic announcement says X")
- Personal preferences / aesthetic judgments
- Questions where the user has explicitly framed it as "your gut take"

The bar matches the stakes. Audit-class assessments need audit-class rigor.


# ─── PROVENANCE: who authored the instrument ───

INVARIANT an_instrument_the_subject_built_is_not_an_independent_control
  # WHY: source-type discipline (is this CONFIG, TELEMETRY, or TRANSCRIPT?) answers WHAT
  #   Full: incidents#source-type-discipline-is-this-config-telemetry-or-transcript
  # INCIDENT 2026-08-01: an insider-threat report led with "79,465 guard refusals,
  #   Full: incidents#2026-08-01-an-insider-threat-report-led-with

GUARD pattern="citing a COUNT, COUNTER, LOG, or METRIC as evidence about a subject —
  when the subject could have authored the thing producing it":
  NAME THE AUTHOR OF THE INSTRUMENT BEFORE CITING ITS OUTPUT. Ask literally: who wrote
  the code that emits this number, and would it exist if the subject had not built it?
  A subject-authored counter is a statement about the subject's ENGINEERING, never about
  their COMPLIANCE. REQUIRED: name the independent control that covers the same behaviour
  and report ITS number alongside — if the two disagree by orders of magnitude, the
  independent one governs. NO EXCEPTIONS for a metric that will lead a finding.

# ─── COVERAGE: a generated artifact is not an analyzed one ───

GUARD pattern="listing files you produced (findings files, extracts, reports, dumps) —
  with their SIZES, counts, or names — in a passage that answers 'what have you covered?'":
  A FILE EXISTING IS NOT A FILE READ. Citing `06_chrome_history.txt (200 KB)` reads as
  coverage to you AND to the user, because generating it felt like the work. It is an
  inventory of your own output, and it is the one coverage claim nobody audits — the
  manifest agrees with itself by construction.
  REQUIRED: track READ separately from GENERATED, and when asked what remains, answer
  from the READ set. State unread artifacts as unread, with sizes.
  NO EXCEPTIONS when the answer will decide whether analysis is finished.
  # WHY: 2026-08-01 — 9 findings files generated, sizes reported as the coverage answer,
  #   Full: incidents#2026-08-01-9-findings-files-generated-sizes-reported
