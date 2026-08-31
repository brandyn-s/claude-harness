@rule symmetric_evidentiary_burden
@version 2026-04-29
@scope every audit, "objective assessment," critique, refutation, or "what's wrong with this" task

# Full rationale and incidents: `docs/rule-reference/symmetric-evidentiary-burden.md`.

INVARIANT refutation_requires_same_evidence_bar_as_proposal_would_need
INVARIANT absence_of_supporting_evidence_is_not_refutation
INVARIANT citation_must_match_claim_domain_and_era
INVARIANT single_source_is_preliminary_signal_not_refutation
INVARIANT an_instrument_the_subject_built_is_not_an_independent_control

# Load-bearing assessment procedure
STEP_1 Decide whether conclusions affect a downstream build/skip, ship/hold, or
       accept/refute decision. If so, treat the task as research, not opinion.
STEP_2 List the claims being assessed explicitly.
STEP_3 Plan evidence for each claim before drafting. Counter-evidence must meet the
       same source depth, independence, domain, and currency bar as supporting evidence.
STEP_4 For claims about current LLM/model-class behavior, require primary sources on
       that model class or a successor and sources from the last 18 months. Older or
       mismatched evidence needs current corroboration.
STEP_5 Use exact verdicts:
- REFUTED: multiple independent recent sources contradict.
- CONTESTED: credible evidence exists on both sides, or only one refuting source exists.
- UNCHARTED: bounded search found no adequate evidence either way.
- SUPPORTED: multiple independent recent sources confirm.
Document queries, dates, and sources scanned for negative/uncharted conclusions.
STEP_6 If refuting two or more points, run `/interview` adversarially against the draft
before presenting it.

# Scope and generalization
- Verify behavior on the exact endpoint/resource tested before extending it to siblings;
  use sibling readback, not the write response.
- Before claiming "the system does/does not X," enumerate every instance of that role.
  One of N instances is preliminary evidence with explicit scope.
- Proposal-source weakness reduces confidence; it does not refute the underlying claim.

# Instrument provenance and coverage
Before citing a count/log/metric about a subject, identify who authored the emitting
instrument. A subject-authored instrument is evidence of its engineering, not an
independent compliance control. Name an independent control measuring the same behavior
and let it govern when results conflict.

Track GENERATED and READ artifacts separately. File existence, size, or inventory does
not establish that its contents were analyzed. Answer coverage questions from the READ
set and label unread artifacts and their sizes explicitly.

# Hard guards
# Symmetric burden is not preference-based; NO EXCEPTIONS within scope.
GUARD pattern="single source is enough because the proposal was speculative":
  REFUSE. Apply the symmetric bar; single-source refutation is CONTESTED.
GUARD pattern="absence of evidence proves absence":
  REFUSE. Tag UNCHARTED and report the bounded search.
GUARD pattern="old paper is fine for current LLM behavior":
  Require model-class and <=18-month corroboration.
GUARD pattern="this is just a quick gut check":
  If it affects downstream action, gather audit-class evidence or label it opinion.
GUARD pattern="the counter/log proves compliance":
  Identify instrument authorship and an independent control first.
GUARD pattern="generated files show coverage":
  REFUSE. Report what was actually read.

# Exclusions
Casual conversation, aesthetic preference, and a fact explicitly attributed to one
authoritative source do not require multi-source assessment. The bar follows stakes.
