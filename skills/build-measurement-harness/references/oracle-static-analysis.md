# Oracle design — static analysis

> Phase 1 reference for measurement projects in the **static-analysis** class: rule precision, vulnerability finding precision/recall, lint detection accuracy, custom matcher quality. Examples: semgrep rule precision, CodeQL query accuracy, custom STIG check correctness.

## What you're measuring

Per-rule (or per-query) precision and recall on a labeled corpus of true positives and false positives.

Common metrics:
- **Precision** per rule: of findings the rule emits, how many are real?
- **Recall** per rule: of real instances of the bug class, how many does the rule catch?
- **F1** per rule: harmonic mean
- **Aggregate precision** across the rule pack
- **Defect rate**: real bugs found per N lines of code (signal vs noise indicator)

The oracle is hand-triaged labels. There is no compiler-frontend equivalent because rule precision is fundamentally about whether the rule's *intent* matches the *finding*, which is human judgment.

## Oracle source

### Hand-triaged TP/FP corpus

Label individual findings as TP (true positive — real instance of the bug class the rule targets) or FP (false positive — finding that doesn't match the rule's intent).

**Minimum viable corpus per rule**:
- 50+ findings labeled per rule before claiming a precision number
- Findings drawn from realistic codebases, not synthetic test cases
- Multi-labeler review for borderline findings (Cohen's Kappa ≥0.7 vs ≥2 reviewers)

**FORBIDDEN**: claiming a rule's precision based on <20 labeled findings. The 95% CI is too wide to distinguish real differences. A rule with 18/20 TP could be 60-99% precision at 95% confidence.

**FORBIDDEN**: labeling your own rule's findings as the rule's author. Confirmation bias is severe; precision claims will be inflated. Use a different reviewer.

### Existing labeled datasets

For vulnerability detection:
- **OWASP Benchmark** — Java-only, synthetic, well-known
- **Juliet Test Suite** — C/C++/Java, NIST-curated, synthetic
- **CWE-bench** — varied, hand-curated CVE-mapped instances
- **CodeXGLUE Defect Detection** — graph-based, real-world

For general lint / pattern detection: usually nothing exists; build your own.

**Caveat**: synthetic benchmarks (OWASP, Juliet) measure pattern-matching capability against textbook vulnerabilities. Real-world precision often differs by 30-50pp because production code has structure synthetic benchmarks lack. Use synthetic for sanity check; hand-triaged real-world for shipping decisions.

## Two-source pattern

For static analysis, the "two sources" are:
- The rule (system under measurement)
- The hand-triaged labels (oracle)

Disagreement reveals either rule error (FP/FN) or label error (label is wrong about whether the finding is real). Sample disagreements at Phase 9.

**Triple-source pattern for high-stakes rules**: have 2 reviewers independently label the same findings, then a third reviewer adjudicates disagreements. Used for production CVE-detection rules where label quality must be ≥95%.

## Stratification dimensions for static analysis

Pick from this menu:

- **rule_id**: which rule emitted the finding (per-rule precision is the primary metric)
- **severity**: critical / high / medium / low / info
- **language** (multi-language scanners): rust / go / python / etc.
- **file_kind**: source / test / config / generated
- **finding_location**: function-body / class-attribute / module-level / config-value
- **confidence_band** (if rule emits confidence): high / medium / low
- **codebase_size**: small / medium / large (precision often varies — large codebases have more legitimate exceptions)
- **finding_age**: new (just introduced) / pre-existing (already in main) — different consumer use cases

Most important stratification dimension: `rule_id`. Aggregate precision across rules is misleading because rules with high false-positive rates can dominate. Per-rule precision is the actionable view; aggregate is descriptive.

## Tiny known-truth fixture for static analysis

Build a 10-finding hand-verifiable fixture per rule:
- 5 hand-written code samples that DO match the rule's intent (expected TP)
- 5 hand-written code samples that DON'T match the rule's intent (expected FP)
- Run rule against fixture
- Verify rule emits exactly 5 findings (the TPs) and 0 findings on the FPs

**Required gate**: per-rule recall = 1.0 on TPs, per-rule false positive rate = 0.0 on FPs.

If the rule fails the tiny fixture, it's broken. Fix before measuring on real code.

## Synthetic negative fixtures for static analysis

Build 3-5 small cases per rule, each isolating ONE failure pattern:

1. **Near-miss positive**: code that LOOKS like the bug but isn't (e.g., for SQL injection rule: `db.execute("SELECT * FROM users WHERE id = " + sanitize(id))` — sanitization makes it safe). Tests that the rule's positive matcher is precise.
2. **Multi-step path**: code where the bug requires reasoning across functions/files. Tests interprocedural capability.
3. **Sanitizer-aware**: bug with a sanitizer applied. Rule should suppress.
4. **Test-file scope**: same bug shape inside a `*_test.py` or `tests/` directory. Many rules suppress in tests; verify behavior.
5. **Generated-file scope**: same bug shape inside a generated file (`*.pb.go`, `*_pb2.py`). Generated code should typically be excluded.

These complement the tiny fixture by exercising the rule's *negative* capability — what it correctly does NOT flag.

## Truncation audit for static analysis

Specific to static-analysis pipelines:

- **Scanner output cap**: many scanners limit findings per file or per rule by default. Document the cap; ensure baseline runs are not artificially capped.
- **File-list cap**: scanner may skip files past a length threshold (e.g., minified JS). Verify what's being silently skipped.
- **Rule-pack cap**: when running a rule pack, some scanners disable rules above a complexity threshold. Verify the rule under measurement actually executed.
- **SARIF output**: result files may truncate at 100 findings per rule by default in some implementations. Always verify SARIF-to-baseline pipeline by counting findings in source vs baseline.

For semgrep specifically: `--max-target-bytes`, `--max-memory`, and `--timeout` all silently drop findings. Document defaults; pin in CI.

## Freshness gate for static analysis

Specific staleness sources:

- **Rule definition** version (semgrep YAML, CodeQL .ql file)
- **Scanner binary** version
- **Rule pack** version (e.g., r2c-security-audit)
- **Codebase under measurement** SHA
- **Sanitizer/excluder configuration**

Pin all five in baseline files. Rule precision is highly sensitive to sanitizer config — a change to "what counts as sanitization" can move precision by 20-30pp without any rule change.

## Two operating points for static analysis

- **All-bands** (recall-sensitive): every finding the rule emits, regardless of confidence. Useful for security-sensitive rules where missing a TP is much worse than reviewing an FP.
- **High-confidence** (precision-sensitive): only findings with confidence ≥ threshold. Useful for "auto-create issue" or "block PR" workflows where FP rate matters.

For semgrep / CodeQL: the natural split is `metadata.confidence: HIGH` vs all bands. For custom rules, define the confidence boundary explicitly per rule.

## CI regression gate for static analysis

Per-subset thresholds:
- **Per-rule precision**: don't allow precision drop > 5pp on shipped rules
- **Per-rule recall** (if measurable on labeled corpus): don't allow recall drop > 3pp
- **Per-severity precision**: critical/high rules have tighter thresholds
- **Aggregate FP rate**: total FPs across the rule pack — proxy for "does this scanner produce noise?"

Aggregate-only gates miss when one rule's FP rate explodes while others stay stable. Per-rule is the actionable view.

## High-stakes rule additional gates

For rules that gate PRs, block deploys, or trigger paging:

1. **Calibration corpus** of ≥200 findings labeled by ≥2 reviewers (Kappa ≥0.7).
2. **Production-shadow run**: rule runs in observe-only mode for ≥30 days before becoming blocking. Measure real-world precision on actual emitted findings.
3. **Suppression policy**: documented procedure for FP suppression with auditable history.
4. **Author-vs-reviewer separation**: rule author cannot also be the precision reviewer.

These gates exist because shipping a noisy rule destroys consumer trust faster than shipping no rule. A rule with 50% precision blocking PRs gets ignored by week 2.

## Code-search-relevant note

If code-search measurement is being treated as a "search rule" with quality measurement (i.e., did the search return relevant results), that's retrieval-class measurement, not static-analysis-class. See `oracle-retrieval.md` for the right reference.

Static-analysis-class measurement applies to code-search only if you're measuring "did our query parser correctly classify this query as a code-search query vs a graph query vs a documentation query" or similar classification tasks where TP/FP labels are appropriate.
