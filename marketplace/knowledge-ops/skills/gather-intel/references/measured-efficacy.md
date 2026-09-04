# Measured Efficacy (live arm)

**Verdict: `trim` — measured 2026-05-31, N=3, `claude-opus-4-8`, n=15 (vs fair baseline).**
The source-authority + adversarial framework was A/B'd vs a strong baseline (same
model + web_search, no framework) over 15 community claims (existence/currency +
false-specifics; effectiveness/hype is NOT deterministically gradeable — see
`harness/PROBLEM.md` §0). Result: the framework is **directionally net-positive**
(verdict_accuracy 0.956 vs 0.933, refutation_recall 0.952 vs 0.857, grounding 0.878
vs 0.833) but **every delta is within the N=3 noise floor** (stdev 0.03–0.09), so it
does not clearly earn its ~5× cost → trim. The one fuzzy "consensus heuristic" claim
drove all the noise (concrete demo that consensus/effectiveness isn't cleanly
gradeable). Harness + oracle + frozen results: `skills/gather-intel/harness/`; CI
gate: `tests/test_gather_intel_efficacy.py`. (Caveat: n=15 directional.)

**Trim candidate (actionable, evidence-gated — not yet removed):** the framework is
directionally net-POSITIVE but swamped by N=3 noise (stdev 0.03–0.09), so the verdict is
"not clearly worth ~5× cost," NOT "harmful" — and the deltas point the RIGHT way, so removal
on this evidence would be backwards (and would violate `eval-shipping-discipline`: behavior
changes need their own before/after). The path: re-run at higher N (≥10) or a larger corpus
and compute a paired bootstrap CI on verdict_accuracy / refutation_recall — **if the
+0.02–0.095 edge clears zero this flips to `keep`**; only if the CI includes zero, trim the
heaviest ceremony (per-finding adversarial search) with that CI as the evidence.
