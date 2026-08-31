# Technique Card — Detail Reference

The Step 2.7 technique card forces extraction of substantive technique
BEFORE the comparison gate in Step 3. This reference holds the detailed
template, examples, and authoring heuristics.

## The four required fields

```
TECHNIQUE CARD: <one-line title>

Underlying technique:
  What is the operationalizable mechanism this skill encodes?
  Name it as a noun phrase that survives extraction from this SKILL.md.

Domain it serves:
  Threat modeling? Legacy code testing? Async error handling? Be specific.

Operationalizable atom:
  What is the smallest unit a reader could USE? An algorithm with
  inputs/outputs, a heuristic with a stopping rule, a rubric with
  thresholds, a classification scheme with mutually-exclusive categories.

Source of the technique:
  Industry (TRIZ, FMEA, chaos engineering, fuzzing, property-based testing)?
  Research (specific paper, methodology)? Production experience (cite the
  incident)? Or a Claude Code coordination pattern invented in the SKILL.md
  itself?
```

## Good cards vs bad cards

| GOOD underlying-technique names | BAD underlying-technique names |
|---|---|
| "per-interaction STRIDE threat-analysis methodology" | "STRIDE matrix" |
| "characterisation-test placeholder-driven extraction algorithm" | "characterisation tests" |
| "steady-state-gated blast-radius-controlled chaos experiment loop" | "chaos engineering" |
| "domain-token injection dictionary generation for coverage-guided fuzzing" | "fuzzing dictionary" |
| "proximate-vs-contributing cause distinction + 5 Whys + trigger criteria" | "postmortem methodology" |

The "BAD" column entries are **the artifact or the topic**, not the
technique. They tell you what the skill is *about*; they don't tell you
the *operationalizable mechanism* the skill encodes.

## "Empty card" handling

If after honest reading no operationalizable atom exists — the skill is
a layout convention, a section template, a polished example — the card
is **empty**. Mark each field with `EDITORIAL-ONLY: <one-sentence reason>`
rather than fabricating substance.

Empty cards are valid outputs. They route the candidate to **Additive**
in Step 4 (SKILL.md prose addition) without Step 3.5 quorum cost.

The bias the v1.2 overhaul corrected is forcing-substance-into-cards-
that-have-none. Treat editorial-only as a first-class outcome, not a
failure.

## The 3rd-party validation requirement (mandatory in v1.3)

For every candidate, dispatch `scripts/produce_card.py` to GPT-5.5-pro
in parallel with the reader's own card production. Compare:

| My card field | GPT card field | Verdict |
|---|---|---|
| Underlying technique = "<X>" | Underlying technique = "<Y>" | Match (paraphrase OK) / Diverge (escalate) |
| Domain = "<A>" | Domain = "<B>" | Match / Diverge |
| Operationalizable atom names | atom names | Match / Diverge |
| Source attribution | Source attribution | Match / Diverge |

**Divergence handling**:
- If GPT names a substantive technique I marked as editorial-only:
  re-read the source, the technique probably exists.
- If GPT marks something editorial-only that I named substantively:
  the technique probably isn't operationalizable — my card may be
  over-claiming.
- If both agree (matching or both editorial): proceed.

The cost is ~$1/session for ~6-12 cards. The check converts "reader
judgment" into "two-author quorum" — same forcing function as Step
3.5's external quorum, applied one stage earlier.

## Heuristic: when the card looks "interesting but mismatched"

Some skills encode substantive techniques in domains we don't operate
in (smart-contract assertions, regulated-industry QMS, etc.). The
card itself can be SUBSTANTIVE while routing decision is DROP-DOMAIN-
MISMATCH. Don't conflate "substantive technique" with "applicable to
us" — they're separate axes.

This distinction is important because forcing every substantive card
into adoption would over-route; dropping every domain-mismatch card
as "editorial" loses the future-reference value.

(Pattern: phylaxsystems/agent-skills mapping-invariants is genuinely
substantive — protocol-invariant mapping algorithm for blockchain
assertions — but routed as drop-with-rationale because Example
doesn't write smart contracts. The technique card itself is preserved
in the validation log.)

## Card examples from the 2026-05-17 validation run

See `~/Documents/scout-skills-validation/2026-05-17-v1.2-replay/`:
- Hand-authored cards: `tc-stride.md`, `tc-postmortem.md`,
  `tc-threat-mitigation.md`
- GPT-authored independent cards: `gpt-card-tob-harness-writing.md`,
  `gpt-card-jeffallan-chaos-engineer.md`,
  `gpt-card-davila7-supply-chain-guard.md`, `gpt-card-phylax-mapping-
  invariants.md`, `gpt-card-tob-cargo-fuzz.md`, `gpt-card-tob-fuzzing-
  dictionary.md`

GPT and reader-authored cards agreed on substantive-vs-editorial
classification on all 6 of 6 from the fresh-test fetch.
