# Phase 3.5 + 3.6: Size-of-Effect Baseline and Tiered Opportunity Gate

These phases fire only when the plan claims to lift / improve / fix a
measurable property of a real target — a codebase, indexed graph,
service, metric, or extractor.

**Skip when** the plan is purely greenfield (no existing baseline),
purely structural (file moves, refactors with no observable target
metric), or operational (one-shot tasks with binary success).

---

## Phase 3.5: Target-State Baseline (mandatory for size-of-effect plans)

### Mandatory before Phase 4

For each metric the plan will predict AND each pattern the plan claims to handle:

1. **Measure current value.** Run the actual query / index inspection / grep that
   produces the metric. Document the count and the command. Examples:
   - `MATCH (a)-[r:HTTP_CALLS]->(b) RETURN count(r)` on the indexed PSM → "currently 17"
   - `grep -rE "reqwest::.*\.(get|post)" PSM | wc -l` → "currently N call sites"
   - `eval_locbench_compare.py --baseline` → "currently File Acc@10 = 82.5%"

2. **Read the source.** For each pattern the plan claims to extract / parse / resolve,
   open the target codebase and read ≥5 actual occurrences. Document:
   - The file:line of each occurrence
   - The shape (literal vs const vs format!() vs custom-macro vs framework)
   - Whether the existing code already handles it

   **AND read the proposed-mechanism source.** When the plan claims "add X to existing Y" or
   "fix Z in W", open Y/W (the existing implementation) and read the relevant function /
   keyword list / regex / data structure FIRST. Confirm:
   - The proposed change isn't already there (avoids no-op plans)
   - The proposed change would actually take effect (avoids "this is 1-line" plans that
     turn out to need 3 file changes when downstream code paths don't accept the new shape)
   - The mechanism's existing behavior matches the plan's mental model

   INCIDENT 2026-05-09 (D1 plan): predicted "add Python+shell URL extraction to extractFunctionCallSites
   for +7-10 HTTP_CALLS." Reading the existing httpClientKeywords list at httplink.go:1316 would have
   shown Python idioms (requests.get, httpx., aiohttp., urllib.request) ALREADY present — the proposed
   mechanism was a no-op for Python. Substrate counting + URL-target verification would have caught
   the substrate gap; mechanism-source reading would have caught the no-op gap. Both checks needed.

   INCIDENT 2026-05-09 ("1-line curl-keyword fix"): predicted "add `curl ` to httpClientKeywords for
   +1-2 HTTP_CALLS." Reading the urlRe regex at httplink.go:156 would have shown the host-group
   pattern `[a-zA-Z0-9.\-]+` doesn't accept `:port`, so URLs like `http://localhost:9090/...` fail to
   match even when the keyword check passes. The "1-line" fix needed 2 file changes (keyword + regex).
   Mechanism-source reading at plan time would have caught this BEFORE writing the test.

2a. **Verify on-disk language composition when the plan names a project as "<language>-heavy".**
   When a plan scopes work to a project on a language qualifier ("Rust-heavy",
   "Python-heavy", "TS-heavy", "Nix-heavy"), the substrate qualifier must be
   verified on disk — not inferred from indexed-graph node/edge counts (those
   surfaces conflate languages and don't expose composition). Required:
   - `find <repo> -name "*.<ext>" | wc -l` for the asserted language extension
   - `find <repo> -name "Cargo.toml" / package.json / pyproject.toml` for project type markers
   - `grep -c "^impl " <repo>/**/*.rs` (or analog) when the plan depends on language-specific constructs (impl blocks, hook calls, JSX components, etc.)
   If the on-disk count is zero or negligible relative to the plan's predictions, **drop the project from scope** or rewrite the plan against a different target. This is a Phase 0 / Phase 3.5 boundary case — it's a substrate verification step the plan can only do once it has a concrete project named.
   INCIDENT 2026-05-08 (PR #467 Phase A): plan named `example-compliance-repo` and `example-sbom-tool` as Rust-heavy targets based on `mcp__code-graph__list_projects` showing 4311 / 6265 nodes. Both had ZERO `.rs` files on disk. Pivoted at execution to `~/code/sbom-rs` (126 .rs / 25 crates) and `~/code/example-sbom-tool/v2` (18 .rs / 5 crates). 30 seconds of `find -name "*.rs" | wc -l` would have caught the gap during planning.

3. **Drop unjustified scope.** If a planned fix targets a pattern that doesn't appear
   in the target in load-bearing counts, drop the fix — or scope it to "synthetic-
   fixture-only, no real-target claim" with that limitation surfaced in the demo.

3a. **Mechanism-correctness verification (mandatory when a phase relies on an existing mechanism's documented behavior).** When a plan step says "leverage X to do Y" or "X already handles this case" or "rely on X's behavior" — where X is an EXISTING mechanism whose behavior the plan trusts — write a 1-query synthetic test that exercises X in isolation and asserts the documented behavior matches reality.

   **The test**: construct input that exercises the cited mechanism contract, run it, assert the output matches what the docstring/comment/prior measurement says. Different from regression tests (which assume current behavior is correct); this asserts behavior matches the **advertised contract**.

   Examples:
   - Plan says "sonnet reranker falls back to hybrid order when score < threshold." Synthetic test: construct candidates with known boost-sorted order, set threshold high enough to force fallback, assert result equals `sort_by_similarity(candidates)[:k]`.
   - Plan says "QN-extractor handles `Self::method()` syntax." Synthetic test: construct a Rust source string with `Self::foo()`, run the extractor, assert the emitted QN matches the expected `Module::Type::foo` form.
   - Plan says "the `_PATH_OVERRIDES` env var raises threshold on prefix-match." Synthetic test: pass a candidate list with a single matching path, assert `_effective_threshold` returns the override value.

   **When to skip**: the SYNTHETIC-TEST form of this step fires when an existing mechanism's behavior is **load-bearing** for the plan's predicted lift. If the plan is replacing the mechanism, skip — the plan's own tests cover correctness.

   **Applicability is wider than this gate, though.** A non-lift plan (pure capability / BUILD) skips Phase 3.5 entirely but can still have a phase trusting a mechanism's contract. For that case, SKILL.md Phase 4's "Load-bearing-mechanism verification" subsection fires the LIGHTER form — **read the mechanism at file:line before presenting** (assert contract == reality) — Phase-4-wide, gated on mechanism-dependency not lift-claim. When the plan IS size-of-effect, escalate from that read to this gate's full synthetic contract test.

   INCIDENT 2026-05-10 (Phase H in code-search roadmap): plan trusted that `_PATH_OVERRIDES` "falls back to hybrid order when triggered." Behavioral reality: `candidates` at that point was the RRF-fused-rank order BEFORE the explicit `candidates.sort(key=similarity_score)` that `RERANKER=off` applies. So fallback ≠ hybrid order. A 5-minute synthetic test would have surfaced this at plan-authoring time.

   INCIDENT 2026-06-22 (v4.1 credential-detector plan, doc 42 — the non-lift miss this gate's trigger didn't cover): Phase C's value-lane step said "for every CONFIRMED, re-read the blob and run `extract_values()`." That function's own docstring (f4_adjudicate.py:54) says "gitleaks/judge carry no span → []" — it returns nothing for judge-only confirmations, which a same-session measurement (D9) had just proven were the load-bearing recall arm (+62.5pp aws_secret_key). The plan was a capability BUILD with NO lift claim, so Phase 3.5 / step 3a never fired; the defect shipped in the presented plan and was caught only by a LATER red-team that read the source. Fix: SKILL.md Phase 4 now runs the lighter "read-the-mechanism-before-presenting" check Phase-4-wide (trigger = mechanism-dependency, not lift-claim), so the same class is caught at authoring time on non-lift plans too. The deeper lesson (the red-team is a design-layer instrument, structurally blind to reality≠listing flaws unless it reads source): do that source read at plan-authoring, not only at red-team.

4. **Save the baseline as a plan artifact.** Write findings to
   `~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>-baseline.md` (sibling of the
   plan file). Phase 4 cites this artifact; Phase 5 ships them together.

### Stop-gate: cannot enter Phase 4 without baselines

If any phase of the plan predicts size-of-effect ("lift to N", "≥ M%", "reduces X
by half") and no baseline measurement exists for the same metric on the same
target, /superplan refuses to write Phase 4. Either run the measurement now, or
remove the prediction.

---

## Phase 3.6: Tiered Opportunity Gate (mandatory for size-of-effect plans)

**Fires when** Phase 3.5 fired. Phase 3.5 catches zero-substrate; Phase 3.6 catches wrong-layer / recoverable-denominator-miss / metric-ladder-break.

Source: 2026-05-08 roundtable (Opus 4.7 + Grok 4.20-reasoning + GPT-5.5-pro, 5 rounds). Convergent finding across all 3 agents: the four historical pre-PR-854 failure modes are mechanistically distinct and each requires its own check.

### Mandatory before Phase 4 — six fields per implementation phase

For each phase that proposes a mechanism intended to move a metric, the plan MUST declare:

1. **Substrate count** — *"How many real-target instances of this mechanism's input shape exist? Cite the query."* Zero substrate → reframe the phase as synthetic-only or drop it.

   **For HTTP_CALLS-class metrics specifically: substrate count must verify URL TARGETS, not just call sites.** Counting `requests.get()` / `curl ...` / `fetch()` invocations without checking what HOST+PATH they target produces 5-10x overestimates because a large fraction of HTTP traffic in any codebase goes to EXTERNAL services. The metric's denominator is INTERNAL routes only.

   INCIDENT 2026-05-09 (D1 plan): predicted +7-10 HTTP_CALLS lift on PSM from Python+shell extraction. Substrate count was 19 + 13 = 32 raw call sites. Phase B investigation read URL targets: Python = 0 PSM-internal, shell = 1-2 PSM-internal. Plan's prediction was 5-10x off.

2. **Layer / prerequisite check** — *"Does the proposed diagnosis point at the layer where the bug actually lives? What's upstream / downstream that must hold?"* Examples:
   - "Diagnosis: traitQN-empty in `extractImplementsRust`. But traitQN is populated in the IMPORTS resolver layer upstream. The fix at the extractor layer doesn't help if the resolver layer fails to populate."

3. **Max recoverable lift, end-to-end** — *"Given (a) the substrate count, (b) what already resolves correctly, and (c) downstream propagation, what is the absolute ceiling on lift this phase can produce?"*
   - "Phase A predicted IMPLEMENTS lift ≥600. Actual recoverable max: of 889 traitQN-empty cases, 16 are internal+name-unique+class-like-labeled. Remaining 873 are external std/external-crate traits. **Recoverable ceiling = 16. Prediction was 37× the ceiling — a denominator miss.**"

4. **Local→terminal metric ladder** — *"Local pass = N (synthetic fixture, unit test). Terminal metric = M. What's the propagation chain between them, and what filters / dependencies sit on the chain?"*

5. **Prior-plan-attribution check** — *"Has a prior plan in this arc proposed a different mechanism for the same metric and not moved it? Cite the Phase 2d ledger."* If yes, the current plan must explain — with new evidence, not new confidence — why this mechanism would succeed.

6. **n-power budget (mandatory for predictions on a bootstrap-CI holdout).** *"Given holdout size N and per-query metric variance, is the predicted Δ at least 1.5× the CI half-width?"*

   **Back-of-envelope formula** (paired bootstrap, 95% CI):
   ```
   CI half-width ≈ 1.96 × (per-query rr std) / sqrt(N)
   ```
   Typical per-query rr std for retrieval evals: ~0.4. For n=100, CI half-width ≈ ±0.08. For n=200, ≈ ±0.055. For n=500, ≈ ±0.035.

   **The check**: predicted Δ ≥ 1.5 × CI half-width? If yes, plan has a fighting chance. If no, expand n, target larger lift, or rescope to experimental env-var.

   INCIDENT 2026-05-10 (Phase F borderline ship gate): plan predicted `{"nix/modules/":20}` would lift aggregate golden MRR. Measured: +0.049 [-0.002, +0.100]. CI lower bound is -0.002 — just barely includes zero. An n-power check would have predicted "borderline ship gate likely" and either expanded n OR rescoped BEFORE running the eval.

**Plus on every phase falsifier:** a derivation label.

| Label | Meaning |
|---|---|
| `Derived from: measured` | Bound comes from a counted real-world value (substrate count, prior PR's measured outcome). |
| `Derived from: extrapolated` | Bound is computed from measured value via a documented assumption. |
| `Derived from: estimated` | Bound is a guess. Treat the falsifier as low-confidence. |

Plans that stamp every falsifier "estimated" reveal the author has not done the substrate / layer / ceiling work. Send back to Phase 3.5 / 3.6.

### Stop-gate: cannot enter Phase 4 without all 6 fields per implementation phase

Fields can be marked `N/A` only with explicit justification.

### Historical failure modes Phase 3.5 + 3.6 cover

| Mode | Catches in | Example |
|---|---|---|
| Zero-substrate | Phase 3.5 + Phase 3.6 field 1 | PR #255 reqwest, PR #247 Trait label |
| Wrong-layer | Phase 3.6 field 2 | PR #257 D1 (HandlerRef-only fix) |
| Recoverable-denominator-miss | Phase 3.6 field 3 | PR #265 Phase A (≥600 predicted with 16 recoverable) |
| Metric-ladder-break | Phase 3.6 field 4 | PR #264 Phase B (97.6% local → +30 HTTP_CALLS via propagation) |
| Mechanism-contract-mismatch | Phase 3.5 step 3a | 2026-05-10 Phase H (override fallback path) |
| Sub-noise-prediction | Phase 3.6 field 6 | 2026-05-10 Phase F (+0.049 [-0.002, +0.100]) |

### Field gotchas observed in production (2026-05-08)

1. **Field 2 must enumerate IMMEDIATE downstream consumers.** PR #266 named the resolver layer correctly but shipped a synthetic-QN return. The next layer (`implements.go::emitImpl` calling `findNodeByQN(traitQN)`) silently dropped all 640 rescued cases. **Refinement:** when filling field 2, list the IMMEDIATE next consumer of the modified output and verify it accepts the new shape — OR plan a layer-2 fix in the same plan.

2. **Field 1 substrate must be MEASURED FRESH on mirror plans, not extrapolated.** PR #268 (struct-side registry) mirrored PR #266+#267 (trait-side). I assumed struct-side substrate composition would mirror trait-side coverage (89% external on trait side → expected similar). Actual struct-side coverage was 16% — fundamentally different composition. **Refinement:** when applying a "mirror" mechanism, require fresh substrate count for the NEW substrate.

3. **Field 1 substrate measurement must verify the EVAL HOLDOUT's candidate-pool composition, not just the source-of-finding holdout.** PR #467 Phase B (B3 chunk-type boost retune) cited PR #145's substrate (4 demote misses on n=20 TS golden) as evidence for predicted lift on the n=183 multitarget holdout. A 4-arm sweep at rerank=off produced bit-identical per-query records across all arms. Root cause: PSM is Nix-dominated; the n=183 holdout's top-15 candidate pool contains essentially no `hook` or `component` chunks. **Refinement:** when a plan extrapolates substrate evidence from holdout A to holdout B, Field 1 must include a check that holdout B's candidate-pool surfaces the same chunk types.
