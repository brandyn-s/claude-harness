@rule uncharted_vs_refuted
@version 2026-04-29
@scope every claim assessment where the relevant research literature is
       sparse, absent, or not surveyed; every gap analysis; every "no one
       has done this" claim

# ─── INVARIANTS (always-true) ───

INVARIANT refutation_requires_positive_counter_evidence
  # WHY: refutation is an active claim that something is false. It
  #   Full: incidents#refutation-is-an-active-claim-that-something-is-false

INVARIANT absence_of_evidence_in_a_search_is_a_property_of_the_search
  # WHY: "I searched and didn't find" reveals the search's coverage, not
  #   Full: incidents#i-searched-and-didn-t-find-reveals-the-search

INVARIANT uncharted_is_an_invitation_to_investigate_not_a_wall
  # WHY: "no published evidence" doesn't mean the claim is wrong. It
  #   Full: incidents#no-published-evidence-doesn-t-mean-the-claim-is

# ─── PROCEDURE: when assessing a claim with sparse/absent literature ───

STEP_1 classify the search outcome explicitly:
         (a) Multiple sources support → SUPPORTED
         (b) Multiple sources contradict → REFUTED
         (c) Sources on both sides → CONTESTED
         (d) No sources found in your search → UNCHARTED — pending search-completeness
             evaluation
         (e) Sources exist but are out of domain/era → UNCHARTED for this domain;
             cite the closest-relevant sources as adjacent prior work

STEP_2 for UNCHARTED, document the search you ran:
         - queries used
         - sources scanned (Exa, Tavily, Firecrawl, arXiv, Google Scholar, etc.)
         - date range
         - domain filters applied
       This makes the search auditable. Future-you (or another session)
       can verify the gap is real or fill it.

STEP_3 for UNCHARTED, suggest investigation paths:
         - what experiment or measurement would generate evidence
         - what adjacent literature might transfer
         - who else might be working on this (research labs, practitioner
           communities)
       Uncharted is generative; refutation closes the door.

STEP_4 distinguish claims about (a) the world from claims about (b) the
       state of literature. "LLMs cannot do X" is a claim about the world.
       "No published study measures X" is a claim about literature. They
       have different evidentiary requirements.

# ─── USER OVERRIDE POLICY ───
# This rule is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="I haven't seen any research on this so it's not real":
  REFUSE the inference. Tag UNCHARTED. List the queries you ran. NO EXCEPTIONS.

GUARD pattern="if it worked someone would have done it by now":
  REFUSE. That's an availability-heuristic argument, not evidence. Many
  things work that no one has done. Tag UNCHARTED. NO EXCEPTIONS.

GUARD pattern="extraordinary claims need extraordinary evidence so I default to refutation":
  REFUSE the asymmetric framing. Default to UNCHARTED in the absence of
  evidence either way. The ordinariness of the claim doesn't shift the
  burden — same-bar applies (see symmetric-evidentiary-burden.md). NO EXCEPTIONS.

GUARD pattern="this is speculative so I'll just call it refuted":
  REFUSE. Speculation is a property of the proposer's confidence, not the
  claim's truth value. Tag UNCHARTED if no evidence either way. NO EXCEPTIONS.

GUARD pattern="the user wants a clean answer not nuance":
  REFUSE false certainty. UNCHARTED is a clean answer; "the experiment
  hasn't been run" is more useful than a fabricated refutation. NO EXCEPTIONS.

GUARD pattern="I'll flag it UNCONFIRMED and ask the user" when a first-party
      surface can answer it (GraphQL introspection, an OpenAPI/JSON schema, a
      live read of the setting, vendor docs not yet fetched, source you can
      grep):
  REFUSE. UNCHARTED is a verdict about the LITERATURE after a documented
  search; it is NOT a label for a fact you did not look up. Query the surface
  FIRST, then tag whatever genuinely remains. Handing the user a list of
  UNCONFIRMEDs they cannot resolve either is not honesty — it is delegating
  your own unrun query. NO EXCEPTIONS.
  # 2026-08-15, verbatim user directive after exactly this: "don't ask
  # questions and hypothesize, you must always investigate and attempt to
  # find an answer." I had presented a risk table with two UNCONFIRMED rows
  # marked "decides the whole verdict" and asked how to proceed. Both were
  # answerable from the endpoint's own introspection, which I had not run.
  # Running it REVERSED two of my published claims (a "binary toggle" was a
  # 5-value role threshold; "audit coverage unconfirmed" was in fact complete),
  # corrected a population from ">=487" to a paginated 674, and surfaced 19
  # live Member-held credentials that no amount of reasoning about policy
  # would have found. The rule this fires on: an UNCONFIRMED that is
  # load-bearing is a WORK ITEM, not a caveat to ship.

# ─── DISTINGUISH: no evidence exists, vs. you have not looked ───

Before tagging UNCHARTED, state which of these applies:
  (a) a first-party surface could answer it and you have NOT queried it
      -> not UNCHARTED. Query it. This is the common case for anything
         with introspection, a schema, an admin API, or a settings read.
  (b) you queried the authoritative surface and it is silent
      -> UNCHARTED for that surface; name the surface and the query.
  (c) no authoritative surface exists
      -> UNCHARTED; STEP_2 documentation applies in full.

Corollary — an ABSENCE claim needs every relevant surface, not the first one.
"There is no API for X" was asserted twice from Query fields and types alone;
only the third pass checked MUTATIONS, the one surface that could have
overturned it. It did not (0 of 361), which is exactly what makes the claim
citable now: 0/361 mutations + 0/1,144 types + 0/161 root queries is
exhaustive, and either of the first two alone was partial.

# ─── FAILURE MODES to recognise ───

FAILURE asserted_refutation_filling_in_for_uncharted_territory:
  # INCIDENT 2026-04-29 chat-audit: claimed "Dada/Surrealism doesn't
  #   Full: incidents#2026-04-29-chat-audit-claimed-dada-surrealism-doesn
  RECOVERY: when called out, retract the refutation. Mark as UNCHARTED
  pending search. Do the search. Then either upgrade verdict or document
  the genuine gap.

FAILURE search_failure_treated_as_world_truth:
  # SAME INCIDENT, different framing: "I haven't read about LLMs +
  # Oblique Strategies" was treated as "no one has done this" was treated
  # as "this doesn't work." Three category errors in a row, each
  # invisible until the user pushed back.
  RECOVERY: separate "I haven't searched" from "I searched and found
  nothing" from "no one has done this" from "it doesn't work." These are
  four different statements with four different evidentiary requirements.

FAILURE conflated_speculation_with_refutation:
  # SAME INCIDENT: the chat's claim "Oblique Strategies for LLMs would
  # break creative blocks" is speculative — that's a property of the
  # proposer's confidence. I treated speculative-proposal as
  # refutable-claim and refuted it without evidence. The correct
  # response was UNCHARTED with experimental design suggested.
  RECOVERY: speculative ≠ false. Speculative + evidence-light = UNCHARTED.

# ─── INTEGRATION ===

This rule pairs with:
  - symmetric-evidentiary-burden.md: refutations need same source bar
    as claims. Uncharted is what you tag when no source bar is met
    either way.
  - gather-research Phase 6c (citation-domain freshness): when the
    freshness check filters out all sources, the claim is UNCHARTED for
    the current model era — not refuted.
  - /interview: when stress-testing assessments, "did you tag UNCHARTED
    where appropriate?" is a standard probe.

# ─── WHAT DOES NOT REQUIRE THIS RULE ===

- Claims with abundant supporting OR contradicting literature (verdict is
  clear)
- Mathematical/logical assertions provable from definitions
- Claims about your own configuration / state (you have direct access)
- Established scientific consensus (e.g., gravity, evolution)

The rule fires when sparse-literature claims need honest verdict.
