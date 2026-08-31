---
paths:
  - "**/rules/symmetric-evidentiary-burden.md"
  - "**/rules/incidents/symmetric-evidentiary-burden.md"
---

# symmetric-evidentiary-burden: Incident Narratives

Extracted from `rules/symmetric-evidentiary-burden.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## when-assessing-a-proposal-treating-proposal-claims-as-needing

```
WHY: when assessing a proposal, treating proposal-claims as needing
     multi-source citation while accepting your own counter-claims on
     a single citation is asymmetric and biases toward refusal.
     2026-04-29 incident: original chat audit used 1 paper per
     refutation (Salvi single-source for hyperpolation AND abduction;
     Becattini 2019 pre-LLM for distance lever; uncited assertion for
     Dada/Surrealism). User correctly pushed back — second-pass research
     reversed 4 of 7 refutations and weakened 2 more.
```

## i-haven-t-read-about-this-is-a-property

```
WHY: "I haven't read about this" is a property of your search, not
     the world. Genuine refutation requires positive counter-evidence.
     Absence of evidence is uncharted territory — see uncharted-vs-refuted.md.
```

## pre-llm-human-engineering-studies-becattini-2019-pre-claude

```
WHY: pre-LLM human-engineering studies (Becattini 2019), pre-Claude
     analogical-reasoning work tested only on GPT-3/3.5/4 (Lewis-Mitchell
     2024), 2013 review papers — these cannot refute claims about
     Opus 4.5+ behavior in 2026. Citation freshness AND domain-match
     both matter for load-bearing claims.
```

## a-single-primary-source-is-evidence-consistent-with-refutation

```
WHY: a single primary source is "evidence consistent with refutation,"
     pending corroboration. Multiple independent sources reaching the
     same conclusion is the bar for "refuted."
```

## 2026-04-29-chat-audit-refuted-hyperpolation-ceiling-abduction

```
INCIDENT 2026-04-29 chat-audit: refuted hyperpolation ceiling, abduction-in-LLMs,
oblique-strategies-for-LLMs, TRIZ+LLM, Dada/Surrealism transfer, distance-lever-for-LLMs
— each based on single citation or no citation. Second-pass research
found multiple independent 2024-2026 sources REVERSING 4 refutations
(abduction is active field, abstract reasoning has emergent symbolic mechanisms,
oblique-strategies has community implementations, TRIZ+LLM has active toolchain)
and WEAKENING 2 more (transformational-creativity is tradeoff curve not ceiling,
distance lever evidence is mixed not refuted).
```

## 2026-04-29-becattini-2019-human-engineering-design-study

```
INCIDENT 2026-04-29: Becattini 2019 (human engineering design study)
cited to refute "distance lever produces novelty in LLM-generated
analogies." Pre-LLM evidence cannot refute LLM-era behavioral claim.
Lewis-Mitchell 2024 (tested GPT-3/3.5/4) cited to refute claims
about Opus 4.7 — wrong model class.
```

## 2026-04-29-claimed-dada-surrealism-doesn-t-transfer

```
INCIDENT 2026-04-29: claimed "Dada/Surrealism doesn't transfer to LLMs"
with no citation. Second pass found Springer 2025 paper on AI+avant-garde,
Berkeley course "Literary AI," multiple practitioner guides. The
uncited assertion was not just wrong — it was the type of claim
that should never have been made without evidence.
```

## 2026-07-30-airlock-a-controlled-test-proved

```
INCIDENT 2026-07-30 Airlock: a CONTROLLED TEST proved
`POST /group/settings/selfservice` returns 400 on a NO-OP write (re-issuing a value a
group already had). The test was sound. Carrying that verified rule to the sibling
`POST /group/settings/trusted_upload` was FALSE — a read-back showed the value still
`0` after its 400, i.e. a real failure. Had the rule been assumed to transfer, the run
would have shipped as a clean 30/30 with 10 silent failures.
The generalization is seductive precisely BECAUSE the original finding was verified;
rigor on the instance produces false confidence about the class.
```

## 2026-06-20-accuracy-measurement-p4-claimed-the-llm

```
INCIDENT 2026-06-20 accuracy-measurement P4: claimed "the LLM judge emits no
severity, only flag/no-flag" — and SHIPPED it as a flaw-log entry — after reading
ONE of TWO judges (the per-tool-action judge in otel_detect_audit; the session-level
judge in otel_session_review DOES emit severity). The claim was retracted same-session.
This is symmetric-burden applied to CODE: a claim about "the X" built from the FIRST
instance of X found in the source is single-source. A system with N instances of a
role (2 judges, 3 resolvers, several handlers) needs ALL N enumerated before
generalizing one instance's contract — exactly the multi-source bar this rule sets
for literature, now for source-reading. The brief's per-session severity (already in
front of me) should have been the tell that SOME judge emits it.
```

## source-type-discipline-is-this-config-telemetry-or-transcript

```
WHY: source-type discipline (is this CONFIG, TELEMETRY, or TRANSCRIPT?) answers WHAT
     KIND of artifact a claim rests on. It does NOT answer WHO WROTE THE INSTRUMENT —
     and a counter authored by the party under review measures that party's own tool,
     not your controls. Telemetry is the most seductive form because it is machine-
     written, numeric, and internally consistent: everything that normally signals
     "independent evidence" is present except independence.
```

## 2026-08-01-an-insider-threat-report-led-with

```
INCIDENT 2026-08-01: an insider-threat report led with "79,465 guard refusals,
     recorded by the fleet's own journal — the strongest single artefact in the case."
     `fak` was the SUBJECT'S OWN published product, public 3 weeks BEFORE he joined.
     The counter was his guard refusing his own fleet. The control that actually
     governed him — the vendor permission system — rejected 1,238 of 333,850 (0.37%)
     with ZERO privilege escalations. The headline finding inverted on one doc read.
```

## 2026-08-01-9-findings-files-generated-sizes-reported

```
WHY: 2026-08-01 — 9 findings files generated, sizes reported as the coverage answer,
ZERO read. Surfaced only because the user asked "is there anything else in the dataset
you haven't analyzed?" The largest unread file was the ONLY collection run that had
succeeded as root — the single highest-value artifact in the set, cited zero times.
```
