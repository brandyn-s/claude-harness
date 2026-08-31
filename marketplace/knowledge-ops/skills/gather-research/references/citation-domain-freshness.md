# Citation-Domain Freshness Check

Before treating a source as primary evidence on an LLM-era behavioral claim, verify the source's domain and era match the claim's domain and era. Cross-domain or pre-LLM citations are ADJACENT prior work, not primary evidence — useful for context, not for refutation.

This check fires in two places:
- **Phase B Step 6 (Evaluate and Rank)** — for SUPPORTING evidence
- **Phase B Step 6b (Adversarial Search)** — for COUNTER-evidence (refutations need same bar as claims)

Asymmetric application — strict on supporting evidence, lax on counter-evidence — is the failure mode this check exists to prevent (see ~/.claude/rules/symmetric-evidentiary-burden.md).

## Critical Gotchas

- **DO NOT cite Becattini 2019 to refute LLM analogical-reasoning claims** — pre-LLM human-engineering-design study. Use Lewis-Mitchell 2024 / Qin et al. ACL 2025 / Salvi 2026 / Padmakumar 2025 / Yang ICML 2025 instead.
- **DO NOT cite Lewis-Mitchell 2024 to refute Opus 4.7 behavior** — tested GPT-3, GPT-3.5, GPT-4. Wrong model class.
- **DO NOT cite Sciencedirect 2013 TRIZ review to refute 2026 LLM+TRIZ tooling** — pre-LLM era.
- **DO NOT treat "I haven't searched this" as "no research exists"** — see uncharted-vs-refuted.md.
- **Multi-source convergence still requires source-domain match** — three pre-LLM papers don't refute an LLM-era claim, even if they all agree.

## Domain dimensions to check

| Dimension | Question | Mismatch implication |
|---|---|---|
| **Model class** | Does the source test the model class in the claim? | Source claims about GPT-3 do not refute claims about Opus 4.5+. |
| **Era** | Was the source published in the relevant LLM-era window? | Pre-LLM (pre-2022) cannot refute LLM-era behavioral claims. |
| **Behavior surface** | Does the source measure the same task/behavior? | Source on summarization quality cannot refute claims about creative ideation. |
| **Architecture class** | Does the source test the architecture class in the claim? | Encoder-only / encoder-decoder findings may not transfer to decoder-only LLMs without verification. |
| **Modality** | Voice mode vs text mode? Image vs text? | Voice-mode behavior delta is documented (~/Documents/knowledge-base/topics/voice-mode-vs-text-mode-behavior.md); cross-modality citations need flagging. |

## Freshness windows by claim domain

| Claim domain | Freshness window | Rationale |
|---|---|---|
| LLM behavioral claims about specific frontier model class (Opus 4.5+, GPT-5+, Gemini 3+) | ≤12 months OR tested on the model class itself | Frontier model behavior changes meaningfully per minor version |
| LLM behavioral claims, generic | ≤18 months | Field moves quickly; older work is "needs corroboration" |
| Agent architecture patterns | ≤24 months | Patterns evolve more slowly than model behavior |
| Foundational theory (analogical reasoning, abstraction, scientific method) | No fixed limit | Theory transfers; cite as adjacent prior work |
| Engineering design / cognitive psychology | No fixed limit BUT flag explicitly when transferring to LLM context | Pre-LLM human-subject findings are NOT primary evidence on LLM behavior |

## Procedure

For each source cited as primary evidence in a finding (whether supporting or counter-evidence):

**STEP 1**: Identify the claim's domain (use table above).

**STEP 2**: Check the source against the relevant dimensions:
- Was the source published within the freshness window?
- Does the source's evaluation cover the model class in the claim?
- Does the source measure the same behavior surface?
- Same architecture class?
- Same modality?

**STEP 3**: Classify the source:
- **PRIMARY**: All dimensions match. Counts toward the multi-source bar.
- **ADJACENT**: At least one dimension is off (older era, different model class, related-but-not-same behavior). Cite for context, but flag as "adjacent prior work" — does NOT count toward the multi-source bar for the original claim.
- **OFF-DOMAIN**: Multiple dimensions off (pre-LLM + different behavior + cross-modality). Do not cite as evidence on the claim. Mention as historical context only if relevant.

**STEP 4**: Apply to the multi-source bar:
- Need ≥2 PRIMARY sources for HIGH-priority findings.
- Need ≥3 PRIMARY sources before declaring REFUTED on a load-bearing claim.
- Single PRIMARY + multiple ADJACENT = CONTESTED, not REFUTED. Document the freshness/domain mismatch in the finding.

**STEP 5**: When PRIMARY sources are absent:
- Tag the claim UNCHARTED (see uncharted-vs-refuted.md).
- Document the search you ran (queries, date range, sources scanned).
- DO NOT use ADJACENT or OFF-DOMAIN sources to fill the gap and claim REFUTED.

## Worked examples (from the 2026-04-29 chat-audit incident)

These are real failure cases the rule was created to prevent. Each shows the original (incorrect) refutation and the correct verdict after applying the freshness check.

### Example 1 — Hyperpolation ceiling

**Original refutation**: cited Salvi et al. arXiv:2604.13242 (April 2026) — single source.

- Source domain check: PRIMARY (LLM-era, generic LLM creativity). PASSES dimension check.
- Multi-source check: only 1 source. **FAILS** the ≥3-PRIMARY bar for REFUTED.

**Correct verdict (after second-pass research)**: CONTESTED. Two PRIMARY sources support the ceiling (Salvi 2026, Padmakumar arXiv:2504.09389 April 2025); HuggingFace community discussion + arXiv:2511.07448 survey present counter-evidence. Tag CONTESTED with both sides documented.

### Example 2 — LLMs cannot do abduction

**Original refutation**: cited same Salvi et al. for the abduction claim (single source, doubled-up).

- Source domain check: PRIMARY for hyperpolation, but the abduction-specific claim is a different behavior surface within the same paper. Dimension check is shaky — the paper's primary contribution is hyperpolation framing, not an abduction benchmark.
- Multi-source check: 1 source. **FAILS** the ≥3 bar.

**Correct verdict**: REVERSED. Multi-source second-pass found 6 PRIMARY sources establishing that LLMs DO perform abduction (imperfectly): arXiv:2604.08016 unified survey, arXiv:2503.21248 ResearchBench, arXiv:2504.12976 HypoGen, OpenReview biomedical paper, DiscoveryBench, EACL 2026 survey. The original refutation was wrong.

### Example 3 — Distance lever for LLM-generated analogies

**Original refutation**: cited Becattini 2019 (n=84 human engineering design study).

- Source domain check: ADJACENT/OFF-DOMAIN. Pre-LLM (2019), human subjects (not LLM), engineering design (not creative ideation). **FAILS** model-class and era dimensions for an LLM-era claim.
- Multi-source check: 0 PRIMARY sources for the LLM-era claim.

**Correct verdict**: UNCHARTED for LLM-generated analogies specifically. The actual LLM-era evidence (Qin et al. ACL 2025) is mixed and doesn't support a strong "near beats far" claim. The original refutation cited an OFF-DOMAIN source.

### Example 4 — Dada/Surrealism doesn't transfer to LLMs

**Original refutation**: NO citation. Asserted as "untested premise."

- Source domain check: 0 sources. **FAILS** every dimension.
- This is the worst class of error: refutation by assertion.

**Correct verdict**: UNCHARTED for measured effect on LLM novelty output, but NOT REFUTED — multi-source second-pass found Springer 2025 paper on AI+avant-garde, Berkeley course on Literary AI, multiple practitioner guides. Active engagement, just no measured effect studies.

## Integration with existing skill phases

| Phase | Current step | Apply freshness check to |
|---|---|---|
| Phase A Step 2 | Currency audit of baseline | Existing recommendations cited from older sources — flag for re-verification with PRIMARY-class sources |
| Phase B Step 6 | Evaluate findings | Each new finding's supporting source — confirm PRIMARY before assigning HIGH priority |
| Phase B Step 6b | Adversarial search | Each counter-evidence source — same PRIMARY bar as supporting evidence (see symmetric-evidentiary-burden.md) |
| Phase C Step 10 | Report synthesis | Verdict labels — REFUTED requires ≥3 PRIMARY; CONTESTED if mixed PRIMARY/ADJACENT; UNCHARTED if no PRIMARY |

## When to skip this check

- Foundational theory citations (Aristotle on rhetoric, Gentner SME, Holyoak analogy structure) — these are adjacent prior work by design; cite for context without claiming primary evidence on LLM behavior.
- Mathematical proofs / definitions (no era applies).
- Reporting facts about a source (e.g., "the paper says X") — different from claiming that what the paper says applies to your model class.
- Fast-moving frontier where no source is more than 6 months old — every source is PRIMARY by era; only domain-match still applies.

## Related rules and references

- `~/.claude/rules/symmetric-evidentiary-burden.md` — refutations need same source bar as claims
- `~/.claude/rules/uncharted-vs-refuted.md` — when PRIMARY sources are absent, tag UNCHARTED not REFUTED
- `references/research-evaluation-framework.md` — the broader rigor/evidence/applicability scoring
- `references/search-waves.md` — query construction for finding PRIMARY sources
