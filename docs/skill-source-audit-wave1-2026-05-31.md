# Skill Source-Code Audit — Wave 1 (Coded Skills)

**Date:** 2026-05-31
**Scope:** The 24 skills in `skills/` that ship executable Python/shell (plus the
oracle CLI `bin/audit-skill-oracle.py`). The ~66 prompt-only skills are Wave 2.
**Method:** Every code file under each skill read at source level; every SKILL.md
claim checked against the code path that implements it. Eight highest-severity
findings re-verified by hand against source (marked **[VERIFIED]**). Judged from
executable source, not SKILL.md prose.

## Verification-honesty rubric (V0–V4)

| V | Meaning |
|---|---------|
| **V0** | Theater — claims verification but does none / non-blocking / vacuous |
| **V1** | Schema-lint — validates shape, not truth |
| **V2** | Heuristic — grep/pattern/LLM-judge, authorship-correlated with the proposer |
| **V3** | Deterministic-grounded — real reproducer / exit-code contract / live probe that can actually fail |
| **V4** | Calibrated — V3 plus measured TPR/TNR/κ or equivalent release gates |

## Scoreboard

| Skill | V (as-shipped) | Code Q | One-line verdict |
|-------|----------------|--------|------------------|
| `sarif-parsing` | **V3** | A | Conservative deterministic PoC gate; correctly separates STALE/ERROR; never overclaims exploitability. Strongest security verifier. |
| `audit-skill` | **V4** | A− | Genuinely calibrated cascade (mutation+property+metamorphic+κ gates) — flawed only by a vacuous `discover` reproducer, tautological κ, and Windows drifts. |
| `audit-rules` | **V3→V4** | A− | Real transcript-grounded compliance auditor that drives the shared oracle; 0%-rate→ERROR conflation is the one hole. |
| `_shared/oracle` (lib) | **V3** (V4 contract) | B | Real calibrated cascade — undermined by a verdict-blind dispatch gate and an unguarded `python`/`grep_absent` specificity hole. |
| `bin/audit-skill-oracle.py` | **V3** (inherited) | B | Faithful CLI; propagates the library's ERROR-passes-dispatch hole; `act-on`/`validate` disagree on ERROR findings. |
| `garden` | **V3** | B+ | Real deterministic KB analyzer; computes every count from file contents; safe temp-only writes. No tests. |
| `mcp-forge-build` | **V3** | B+ | Real subprocess load oracle — but the one live-API check (8f) is an always-pass stub contradicting "Required/fail-the-build." |
| `vendor-breach` | **V3** | B+ | Live-probing, exit-code-checked supply-chain auditor; one hole: a non-zero `gh` exit flattens to "zero findings." |
| `mcp-diagnose` | **V2** | B+ | Clean, well-tested heuristic log-parser; the genuinely live checks are prose-only. |
| `scout-skills` | **V2** | B+ | Real decorrelated 2-model SKIP quorum with a correctly-defensive abstention rule; decision core untested. |
| `threat-model` | **V3** | B | Real self-match-proof grounding that fails on absent symbols; grounding is shallow; a record-name desync zeroes the history component. |
| `healthcheck` | **V3** (V2 prose) | B | Real FS/AST/git verifiers + one buried V4 recall gate that's never invoked; zero tests on the verifiers; dotdir false-FAIL. |
| `lab-deploy` | **V3** verify / **V1** deploy | B | `verify_waf.py` is the strongest fail-closed verifier here; but the Amplify build trigger reports "started" as success without polling. |
| `supergoal` | **V2** | B | Meticulous, honest *spec* — but the per-turn "deterministic evidence" gate is agent-interpreted prose, not code. |
| `persona` | **V2** | B | Statistically literate; κ math correct and the gate fires — but two author-correlated scorers, and tests miss a wrong-but-nontrivial κ. |
| `variant-analysis` | **V2** (V3 baseline) | B− | Runs real rg/semgrep with a sound baseline gate, but variant grounding self-matches its own spec and the FP cap is inert by default. |
| `semgrep` | **V1** | B | Not a verifier — a well-tested SARIF merge utility around an un-executable prose workflow; dedup can drop distinct findings. |
| `scout-frontier` | **V1** | B+ | Honestly-disclaimed draft generator; the "scoring" is a fixture self-consistency lint over hand-authored labels, not a measurement. |
| `roundtable` | **V1→V2** | C+ | Multi-vendor at the wire, fake at the verdict: silently collapses to one vendor; "consensus" is one Opus call narrating text. |
| `insecure-defaults` | **V1** + RCE | C | Fail-open "verdict" does not gate the run; dynamic probe is a `shell=True` RCE. A locate-linter dressed as a security oracle. |
| `gather-repos` | N/A (output-grounded) | C+ | "Score N/6" computed from real git trees, but a sloppy substring match disagrees with its own docs AND its own (live-network) tests. |
| `recall` | N/A (telemetry) | A− | Retrieval correctness is prose; the shipped telemetry analyzer is clean and honestly scoped (measures usage, not precision). |
| `audit-architecture` | **V1 as-shipped** (V3-V4 by design) | C | Real non-tautological calibration — **silently dead**: stale `audit-skill`→`_shared` path fails 37/39 tests at import. |
| `mcp-forge-audit` | **V0 as-shipped** (V3 by design) | D | Well-built calibration that's **completely dead** (3/3 fail at import); zero shipped detector code — prose playbook only. |
| `sca-review` | **V0** (honest) | D | Two NOT-IMPLEMENTED stubs + an all-prose review loop; no executable verification exists — but it says so. |

## Cross-cutting findings

### 1. The shared oracle is real — but two of its four consumers can't run their gates **[VERIFIED]**
`skills/_shared/oracle/` is a genuine V3–V4 deterministic verification library
(honest exit-code contract routing instrument failure→ERROR, static+empirical
vacuity guard, working CLI cascade). `audit-skill` (V4) and `audit-rules` (V3→V4)
wire into it correctly and their suites are green (266/266, 58/58). But
`audit-architecture` and `mcp-forge-audit` carry a **stale `skills/audit-skill`
→ `skills/_shared` import path** in every oracle test (8 `sys.path.insert` sites;
`skills/audit-skill/oracle` no longer exists). Result: their calibration/corpus
gates fail at import (37/39 and 3/3) and provide **zero regression protection**,
despite containing real, non-tautological, source-grounded calibration data
(both score TPR=1.0/TNR=1.0 when run against the correct path). The production
runtime path (`bin/audit-skill-oracle.py`) is correct for all three, so the
skills *work* when a human runs them — it is specifically their CI
verification-honesty gates that are silently disabled. This is the single most
actionable finding: a one-line path fix in 8 files restores both suites.

### 2. The dispatch gate is verdict-blind **[VERIFIED]**
`validate.py:122-200` indexes trace records by *timestamp only* and never
inspects the verdict, so an ERROR-verdict finding (broken instrument,
non-manual reproducer) passes `validate_for_dispatch`. `act_on.py:98` already
places ERROR findings in the worklist. Net: a finding whose reproducer *never
actually demonstrated the bug* can be certified "dispatchable," contradicting
SPEC's "acted on iff Layer A: STILL-FIRES." The CLI compounds it — `act-on`
exits 1 on ERROR while `validate` exits 0, so the two gates disagree.

### 3. The anti-gaming guard has two open reproducer types **[VERIFIED]**
The specificity control-run (`specificity.py:82`) is scoped to `("grep","bash")`
only, and `VACUOUS_COMMAND_PATTERNS` (`finding.py:112-119`) are grep/bash/test
shapes. So **`python` reproducers receive no specificity check at all** — a
vacuous `python` predicate (`raise SystemExit(1)`, `assert True`) is classified
SPECIFIC. `grep_absent` likewise escapes the control-run (documented as v1 scope).
`python` is a first-class executable reproducer type; this is the widest-open
proposer-grades-own-homework hole in the library.

### 4. "Verifier" vs "verification theater" splits cleanly by whether a check **gates**
The pattern across the corpus: skills earn V3 when a deterministic check's result
**flows into pass/fail**. They drop to V1/V2 when the check is *computed and
displayed but discarded*:
- `insecure-defaults` computes a fail-open verdict, prints it, and **gates on
  `located and not_fixture`** — the security determination is decorative.
- `roundtable` computes per-round self-similarity, then a single LLM narrates
  "consensus" — no quorum count gates anything.
- `mcp-forge-build` 8f returns `passed: True` with "probe not auto-executed"
  even when credentials are present — the live check it advertises never runs.
- `lab-deploy` `trigger-build` prints "job started" and returns — no poll on
  build success.
- `supergoal`'s entire per-turn verification decision tree is prose for a Stop
  hook, not code.

### 5. Honest self-labeling is widespread (a genuine strength)
Several skills are candid about their limits in-code: `sca-review` stubs exit 2
with "NOT IMPLEMENTED"; `recall` notes `num_results` is "logged but not yet
read"; `scout-frontier` disclaims "NOT a discovery oracle"; the oracle SPEC
marks Layer B soundness as `None` ("uncalibrated by design"). The dishonesty,
where it exists, is in SKILL.md *claims* outrunning code (mcp-forge-build 8f,
roundtable consensus, supergoal "deterministic evidence"), not in fabricated
verdicts.

### 6. Test suites under-cover the load-bearing path
A recurring shape: the pure parser is well-tested while the *decision/gate* is
not. `persona`'s κ tests use only κ∈{−1,+1,~0} (a wrong-but-nontrivial κ ships
green); `roundtable` tests a *copy* of path logic and greps for a source string;
`scout-skills`/`supergoal` leave the recently-bug-fixed decision core untested;
`healthcheck`/`garden`/`recall` have no tests for their riskiest analyzer.

## Verified critical bugs (re-confirmed at source)

| # | Location | Bug | Fix |
|---|----------|-----|-----|
| 1 | `_shared/oracle/validate.py:122-200` | Dispatch gate ignores verdict; ERROR findings pass | Capture latest verdict in `latest_by_id`; reject non-`STILL-FIRES` (new `REJECT_UNVERIFIED_VERDICT`); add negative test |
| 2 | `_shared/oracle/finding.py:271` | bash/grep path hardcodes `timeout=30`; override dead on its `wc -w` motivating case | `timeout=_reproducer_timeout()`; test that `fires()` honors the env override on a bash reproducer |
| 3 | `_shared/oracle/finding.py:385` | `transcript_pattern` uses literal `"bash"`, reintroducing WSL-bash bug | `[_BASH, "-c", …]` |
| 4 | `_shared/oracle/specificity.py:82` | `python` (and `grep_absent`) reproducers get no specificity guard | Add a `python` control-run (exec snippet against a benign tmp tree; reject unconditional `raise`/`sys.exit(1)`); add a bug-present control for `grep_absent` |
| 5 | `audit-architecture/tests/*` (7) + `mcp-forge-audit/tests/*` (1) | Stale `skills/audit-skill`→`_shared` path; suites fail at import | Replace `REPO/"skills"/"audit-skill"` with `REPO/"skills"/"_shared"` in 8 sites |
| 6 | `insecure-defaults/scripts/verify_defaults.py:202` | `shell=True` on `probe_cmd` from `findings.json` (RCE) | argv list + `shell=False`, or remove the probe if specs aren't trusted |
| 7 | `insecure-defaults/scripts/verify_defaults.py:251` | Fail-open classification doesn't gate the run | `per_pass = located and not_fixture and (verdict is None or classify_passed)`; thread the `passed` field out of `classify_fail_open` |
| 8 | `_shared/oracle/__init__.py:11-13` | Docstring references non-existent `oracle.consensus` | `oracle.ensemble` |

## Recommended fix batch (prioritized)

1. **Restore the dead gates** (finding 5) — one-line path fix in 8 files; immediately re-arms `audit-architecture` + `mcp-forge-audit` calibration (verified to pass under the correct path). Highest value/effort ratio.
2. **Close the security hole** (findings 6+7) — `insecure-defaults` `shell=True` RCE + non-gating verdict; both small, both squarely on the verification-honesty theme.
3. **Harden the oracle core** (findings 1–4) — verdict-blind gate, python/grep_absent specificity, timeout/bash drifts. These ripple across the 4 calibration suites, so they need the green-by-default discipline (run all four after each change).
4. **Claim-vs-code reconciliations** (no behavior change) — mcp-forge-build 8f "Required"→"plan-only"; roundtable add a quorum guard; supergoal extract the decision table into a tested `decide.py`; threat-model `calls_edge_grounding` history desync.
5. **Test the decision cores** — persona intermediate-κ assertion; scout-skills/supergoal/roundtable quorum/decision tests; healthcheck/garden/recall analyzer tests.

---

## Per-skill detail

> Each block: what it actually is (from code) · claim vs. code · verification
> posture · top correctness findings · security findings · test quality · code
> quality · top-3 fixes · verdict. `[VERIFIED]` marks claims re-confirmed at
> source during this audit.

### `_shared/oracle` (library)
**What it is:** A four-layer verification cascade over LLM-proposed findings.
`finding.py` is the keystone: `Reproducer.fires(repo_root)→(bool, evidence)` runs
a deterministic check (grep/grep_absent/bash/python/file_exists/file_missing/
transcript_pattern/manual) in a subprocess and classifies via an exit-code
contract. `reverify.py` (A) wraps `fires()` + writes a trace record;
`validate.py` is the dispatch gate; `specificity.py` is the anti-reward-hacking
guard; `fix_loop.py` (D) does pre/post-fix git-worktree verification feeding the
`subagent-stop.py` exit-2 block; `ensemble.py` (B) and `corpus.py` (C) round it
out; `kappa.py`/`profile.py`/`report.py`/`trace.py` support.
**Verification posture: V3** (V4 for the exit-code contract specifically — real
TPR/TNR/ERROR-TPR floors + κ≥0.7, pinned by genuine mutation+property tests).
**Top findings:**
1. **[VERIFIED]** ERROR-verdict findings pass `validate_for_dispatch`
   (`validate.py:122-200` is verdict-blind). Untested.
2. **[VERIFIED]** `python` reproducers have no specificity guard
   (`specificity.py:82` scopes control-run to grep/bash; `VACUOUS_COMMAND_PATTERNS`
   are grep/bash/test only) → vacuous python predicate classified SPECIFIC.
3. `grep_absent` vacuous predicates escape the control-run (documented v1 scope).
4. **[VERIFIED]** `finding.py:271` hardcodes `timeout=30` (override dead for
   bash/grep — its `wc -w` motivating case); `:385` uses literal `"bash"`
   (re-opens WSL bug for transcript_pattern).
5. `_parse_minimal_yaml` (`finding.py:632-771`) is a hand-rolled YAML parser the
   whole pipeline depends on — robust on single-line round-trips, fragile on
   multi-line/nested.
**Claim vs. code:** SPEC.md:508 calibration count stale (says N=38; actual 43:
18 true/17 false/8 ERROR). **[VERIFIED]** `__init__.py:13` references
`oracle.consensus` (renamed `ensemble`). SPEC's "acted on iff STILL-FIRES"
overstates the gate (finding 1).
**Security:** Reproducer execution is intentional arbitrary code exec by design;
findings YAML is the trusted boundary. Trace at `~/.claude/oracle-trace.jsonl`
is append-only *by convention* (`open("a")`) — no hash chain; an agent that can
write files can neutralize the subagent-stop gate by deleting/forging records.
No `shell=True` interpolation, no `eval`/`pickle`/`yaml.load`. `claim.py` uses
`O_CREAT|O_EXCL` correctly.
**Tests:** Strong, largely non-gamed. Real mutation testing (kills survivors),
43-finding calibration with controls, κ gate, gamed-stratum at ≥0.95/≤0.0,
property + metamorphic. Gaps: no negative test for ERROR/MANUAL verdict
rejection (finding 1 invisible); timeout-override test asserts the helper, not
that `fires()` uses it (finding 4 invisible); no python/grep_absent vacuity test.
**Code quality: B.** Clear boundaries, honest SPEC, real calibration; dragged by
the hand-rolled YAML, dead timeout path + misleading docstring, stale refs.
**Top fixes:** (1) verdict check in `validate.py:172`; (2) python/grep_absent
specificity; (3) `timeout=_reproducer_timeout()` + `_BASH` at `:271`/`:385`.
**Verdict:** Genuinely well-engineered, calibrated, mostly-honest deterministic
cascade (rare V3+) with three load-bearing holes.

### `bin/audit-skill-oracle.py` (CLI)
**What it is:** A ~900-line argparse front-end exposing the library (reverify,
act-on, validate, verify-fix, corpus, ensemble, ensemble-dispatch,
specificity-check, contract-check, profile, discover, …). Inserts `_shared` on
path, wraps `load_findings` in a clean exit-2 handler, maps subcommand results
to exit codes.
**Verification posture: V3** (inherited — faithful pass-through; exit codes wired
to real verdicts).
**Top findings:** (1) `act-on` exits 1 on ERROR while `validate` exits 0 — the
two gates disagree on broken-instrument findings (follows from the library hole).
(2) `cmd_corpus_check` mutates global module state with fragile restore. (3)
`cmd_validate` hardcodes `repo_root=REPO` — control-run targets the real tree,
not the worklist's tree; no `--repo-root`/`--no-specificity` flags.
**Claim vs. code:** Module docstring "every subcommand writes a TraceRecord" is
false for ~8 subcommands; `cmd_validate` docstring lists 4 rejection codes but
the gate emits 6.
**Security:** No `shell=True`/`eval`/`pickle`; same trusted-findings caveat;
UTF-8 reconfigure is correct hardening; no secret leakage.
**Tests:** Exercised indirectly via library tests; no process-level exit-code
test (the act-on/validate disagreement is untested).
**Code quality: B.** Clean argparse; dinged for overstated docstrings + the
exit-code disagreement.
**Verdict:** Faithful CLI that wires exit codes to real verdicts but propagates
the ERROR-passes-dispatch hole and disagrees with itself across `act-on`/`validate`.

### `audit-skill`
**What it is:** A three-phase skill-auditor. Phase-1 proposer `bin/audit-skill.py`
(3189 lines, pure regex/AST lint, no LLM, ~30 codes); Phase-3 verifier
`bin/audit-skill-oracle.py` over `_shared/oracle`. Real `hooks/subagent-stop.py`
enforces Layer-D verdicts (exit 2), wired in `settings.json`. Calibration harness
+ mutation/property/metamorphic siblings. **All 266 tests pass.**
**Verification posture: V4 (Calibrated).** Layer A genuinely decorrelated;
measured TPR/TNR=1.0, ERROR-TPR=1.0/FPR=0.0, gamed-detection=1.0; real KILL-all
mutation suite; property matrices at exit-code boundaries; metamorphic invariance.
**Top findings:**
1. `oracle/discover.py:88` emits `grep -rE '<tool>' <dir> || true` — always exits
   0 → always STILL-FIRES (self-certifying). `static_vacuity` misses it (the
   `|| true` is appended after a real grep); the control-run catches it, **but
   `discover`→`act_on`→`reverify` never invokes the specificity guard** — only
   the optional `validate` boundary does.
2. The κ gate (`test_oracle_calibration.py:183-217`) is **tautological** on the
   current set: TPR=TNR=1.0 forces κ=1.0, so it can only trip if TPR/TNR already
   tripped. SPEC frames κ as independent signal — overstated.
3. Calibration measures the *reproducer mechanism*, not proposer detection (the
   correct scope for Layer A, but worth stating explicitly).
4. `finding.py:271`/`:385` Windows-correctness drifts (shared with the library).
5. Layer-D-on-history ships with no committed `cases.json` — the "true
   VERIFIED-rate over real fix-PRs" is never actually computed.
**Security:** None material. `backfill_reproducers.py:70-79` correctly gates
shell interpolation behind a strict `_SAFE_PATH_RE` allowlist (real injection
defense). `pickle` only as the cross-process transport for string-only dataclasses.
**Tests:** Strong, behavior-driven, non-smoke. Gamed stratum genuinely caught
(G3/G5 fire against synthetic benign content, flagged NONSPECIFIC_CONTROL).
Weaknesses: tautological κ; gamed-control content co-designed with G3/G5
fixtures (somewhat self-fulfilling); no committed Layer-D-history cases.
**Code quality: A−.** Honest docstrings, thorough error paths; dinged for the
two Windows drifts, a stale `ensemble.py:154` path, and the discover gap.
**Verdict:** A rare genuinely-calibrated (V4) harness — let down only by a
vacuous reproducer in the `discover` path, a tautological κ gate, and two
Windows drifts.

### `audit-rules`
**What it is:** A transcript-compliance scanner + oracle adapter.
`references/scan_violations.py` parses `~/.claude/projects/*/*.jsonl`, runs 8
regex detectors (V1–V8) against real code content, emits per-rule session-rate
JSON. `scripts/scan_to_findings.py` genuinely imports the shared oracle
(`sys.path.insert(...,"skills/_shared")`; `from oracle.finding import …`) and
wraps each rule in a `transcript_pattern` Finding. **58/58 tests pass.**
**Verification posture: V3→V4** (V4 for the predicate engine via the
25-finding labeled calibration with 0.90/0.75/0.95 floors; V3 for the V1–V8
detectors, which are covered by example-based unit tests, not a labeled corpus).
**Top findings:**
1. When a rule has 0 violations the scanner omits its key, so the
   `transcript_pattern` reproducer's `metric_path` resolves to None →
   `RuntimeError` → **ERROR, not STALE**. A successfully-promoted (now-clean)
   rule perpetually shows ERROR — conflates success with instrument failure.
2. `classify_rules.py:88-92` returns `"warned"` as an unconditional fallback
   when neither block nor warn signal is found, but the docstring says such hooks
   should be `"unknown"` — inflates the warned layer.
3. `scan_violations.py:5` docstring says "SIX" detectors; 8 are implemented.
**Security:** None found — `json.loads` per line with try/except; no
`shell=True`/`eval`/`pickle`/`yaml.load`.
**Tests:** Real, not smoke. V7/V8 detectors have paired positive/negative + FP-
avoidance cases; calibration is non-tautological (boundary cases at threshold,
5 distinct ERROR modes) and skips honestly on Windows. Gap: no labeled
precision/recall corpus for V1–V8 against synthetic transcripts.
**Code quality: A−.** Clean, honest about limits; docstring count drift + the
classifier fallback are the only blemishes.
**Verdict:** Genuinely deterministic, transcript-grounded compliance auditor
that really drives the shared oracle; the 0%-rate→ERROR conflation is the one
material hole.

### `audit-architecture`
**What it is:** A discovery-driven architecture auditor with two real detectors
(`doc_accuracy_audit.py` checks docs against live disk; `skill_quality_audit.py`
scores skills from real SKILL.md contents) + a deterministic corpus grader
(`fixture_auditor.py`). SKILL.md drives Claude through Phases 0–7 and invokes the
shared oracle via the CLI.
**Verification posture: V1 as-shipped (the calibration/corpus gates DO NOT RUN);
V3-V4 by design.**
**Top findings:**
1. **[VERIFIED]** All 7 oracle test modules use stale
   `sys.path.insert(...,"skills"/"audit-skill")`; `skills/audit-skill/oracle`
   doesn't exist → 37/39 tests error at import. The skill's entire
   self-verification gate is red. (Re-run under the correct `_shared` path: loads
   62 findings, TPR=1.0/TNR=1.0 — the calibration *content* is real and
   non-tautological; it's just dead.)
2. `doc_accuracy_audit.py:262-264` uses raw substring membership
   (`if srv not in arch`) → the FP class the SKILL itself warns about.
3. `doc_accuracy_audit.py:268` — `doc_hook_mentions` computed then never used;
   the hook-count check SKILL.md Phase 3 advertises is unimplemented.
4. `skill_quality_audit.py:226-233` rating thresholds are hard-coded magic
   numbers (the "RUBRIC-ONLY" bias the SKILL flags).
**Security:** None found in skill code (subprocess list-form + timeouts;
`encoding=` everywhere).
**Tests:** Design is high quality (paired fixtures, deterministic grader, labeled
62-finding calibration with ERROR pathway) — but **non-functional**: 37/39 error
at import, so zero regression protection today. The worst kind of
theater-by-accident: a real calibration that silently never executes.
**Code quality: C.** A-grade detector/corpus design dragged down by a repo-wide
broken import that reds 95% of the suite, dead code, and an unimplemented
advertised check.
**Verdict:** Real detectors + genuinely non-tautological calibration, all
silently disabled by a stale import path — verification honesty is currently
aspirational, not enforced.

### `mcp-forge-audit`
**What it is:** A prose-only orchestration skill — **zero executable detector
code** (no `.py` outside `tests/`). SKILL.md instructs Claude to ad-hoc-write
introspection scripts and emit Finding YAML, then invoke the oracle CLI. The only
Python is the calibration test + fixture stubs.
**Verification posture: V0 as-shipped (calibration DOES NOT RUN); V3 by design.**
**Top findings:**
1. **[VERIFIED]** `test_mcp_forge_audit_calibration.py:35` stale
   `skills/audit-skill` path → all 3 tests error at import (confirmed via the
   repo's own `.pytest_cache/lastfailed`). Re-run under `_shared`: 32 findings,
   TPR=1.0/TNR=1.0, ERR-TPR=7/7 — genuinely decorrelated, source-grounded, but
   dead.
2. Ships no detector code: 100% of B1-B9/W1-W12/I1-I19/D1-D5 detection lives in
   SKILL.md prose for Claude to re-implement each run — no deterministic,
   regression-protected implementation of any "49 finding codes."
3. The `manual⟺unverified` contract is enforced only if Claude remembers to run
   `contract-check` (not in the Completion Checklist).
**Security:** A fixture contains a *deliberately-planted* `shell=True` injection
(a known-bad server the audit should flag) — appropriate; no issues in non-fixture
code (there is none).
**Tests:** Calibration content real and non-tautological, but **completely
non-functional** (3/3 fail at import per the skill's own cache). No tests for any
forge-audit-specific logic (none is implemented).
**Code quality: D.** Almost no code to grade; what exists is well-designed but
dead on arrival.
**Verdict:** A prose-only audit playbook with a genuinely well-built but
completely dead calibration and zero shipped detector code.

### `persona`
**What it is:** A CLI dispatch harness that samples framework personas from a
markdown inventory, fans them out as Anthropic API calls, scores each output two
ways (keyword/stance + LLM-judge), and `analyze.py` computes per-RC endorsement
rates plus a hand-rolled Cohen's κ between the two scorers with an opt-in
`--strict`/`--kappa-floor` gate.
**Verification posture: V2 (Heuristic, authorship-correlated).** κ math is
**correct** (binary form verified ±1.0, 0.615 on hand-checked cases) and the
gate genuinely fires (exit 1 at κ≈0.615 with floor 0.7). But the two "scorers"
both consume the *same* author-written `endorsement_criteria`
(`score_llm_judge.py:79`, `score_keyword.py:50-61`), so they're correlated by
construction — method-agreement, not inter-rater. No decorrelated ground truth.
**Top findings:**
1. `analyze.py:240` advisory flag uses hard-coded `kappa < 0.6` while the *gate*
   uses `args.kappa_floor` — report and exit code disagree at floor 0.8.
2. `score_keyword.py:50-61` only inspects a 30-char window before the keyword
   and returns on the first hit → high stance FP feeding directly into κ.
3. `score_llm_judge.py:146` judge JSON-parse failures stored as `ok:True` with
   `_parse_error` → `analyze.py` counts them as non-endorse, deflating judge
   endorsement and skewing κ (instrument failure conflated with a reject).
4. Duplicates `cohens_kappa` instead of importing `_shared/oracle/kappa.py`;
   they disagree on the degenerate case (persona NaN vs oracle 1.0).
**Security:** No `shell=True`/`eval`/`exec`/`pickle`; `yaml.safe_load`
throughout; API key env-only, never logged. None of concern.
**Tests:** `test_persona_kappa_gate.py` pins gate plumbing well but does **not**
test the κ arithmetic — all cases use κ∈{−1,+1,~0} where κ≈raw agreement. Verified
empirically that substituting raw agreement or dropping the `(1−p_a)(1−p_b)` term
**still passes every test** — only `return 1.0` is caught. A wrong-but-nontrivial
κ ships green. `test_persona_golden.py` is solid on lock-contention + the Article
VI exit-2 gate.
**Code quality: B.** Clean, honest docstrings; marred by κ duplication, the
floor-vs-flag inconsistency, and an orphan `_write_marker.py`.
**Verdict:** Statistically literate and the gate genuinely fires, but it's
method-agreement between author-correlated scorers (V2), and its tests would not
catch a non-trivially wrong κ.

### `roundtable`
**What it is:** A multi-vendor adversarial-review harness that fans one context
file out to three provider adapters (anthropic/xai/openai) over ≤5 rounds via a
ThreadPoolExecutor, with optional embedding auto-stop and a single-Opus-call
synthesizer. Post-hoc auditors: `audit_concessions.py` (regex) +
`validate_claims.py` (Tavily token-overlap).
**Verification posture: V1→V2.** Decorrelation is real only at the adapter layer
(three genuine vendors) — but nothing guarantees ≥2 ran, and the consensus
verdict is a single same-vendor LLM narrating text with zero deterministic tally.
**Top findings:**
1. **Ensemble silently collapses to one vendor.** `harness.py:372-421` never
   counts successes; `embed.should_stop(3,3,0.92,{"opus":0.95})` returns
   `(True,"all agents converged")` — verified. A run where Grok+GPT failed
   auto-stops as "converged" on one agent, and `synthesize.py` narrates
   "3-of-3 agreement." The biggest verification-theater failure.
2. SKILL.md Success Criterion "all 3 agents complete R1+R2" is **enforced
   nowhere** — no quorum check.
3. `synthesize.py:119` `rounds_completed - 1` underflows on early abort →
   "0 rounds of forced critique" / `-1`.
4. `validate_claims.grade_claim` corroboration is bag-of-token substring overlap;
   a fabricated claim "corroborates" when result pages echo its tokens, while a
   true claim with 0 hits FAILs and `--strict` exits 1 (conflates poor coverage
   with fabrication).
**Security:** Keys only in request headers, never logged; missing-key path clean.
`common.http_post_json` persists up to 500 chars of provider error bodies to
`transcript.jsonl` (low risk). No `shell=True`/`eval`/`pickle`.
**Tests:** `test_roundtable_golden.py` is smoke-only and partially tautological —
tests a *copy* of path logic, then asserts the string `'if r - 1 == 1:'` exists
via grep. Covers zero of: quorum/collapse, single-agent should_stop, synthesize
underflow, cosine, adapter degradation.
**Code quality: C+.** Clean uniform adapters; but the core "consensus" is an
unmeasured LLM narration, no quorum guard, mislabeled auto-stop, grep-shaped tests.
**Verdict:** Genuinely multi-vendor at the wire, but "consensus" is one
same-vendor LLM narrating concatenated text with no quorum guard and a
self-similarity auto-stop that fires on one surviving agent — impressive
scaffolding around verification theater.

### `threat-model`
**What it is:** `scripts/verify_claims.py` gates a `threat-model.md` on four
deterministic checks: structure, file-ref resolution, surface attribution, and
`probe_calls_edges` (Tier-2 source grounding of claims.json edges via grep).
**Verification posture: V3.** The probe runs real `grep -rIn --fixed-strings`
over source-only extensions; UNSUBSTANTIATED genuinely fails under `--strict`
(exit 1). Honest that GROUNDED is a necessary condition (symbol present), not
proof of the edge.
**Top findings:**
1. **[VERIFIED in prior session]** The central claim — grep restricted to source
   extensions so it can't self-match the model/claims — is TRUE (`_SOURCE_INCLUDES`
   excludes `.md`/`.json`). But `model_history.py:70-71` counts
   `calls_edge_verdict` while the verifier emits `calls_edge_grounding`, so the
   history **always reports 0 verified/0 unverified** — the "unverified rate >30%"
   failure-detection is dead.
2. `_searchable_token` picks the longest token; `.*Handler.*`→`Handler` grounds
   if `Handler` appears anywhere in any source file — shallow grounding.
3. `calls_across` GROUNDED on `any_present` (two unrelated present symbols ground
   with zero evidence the edge exists).
**Security:** grep via argv list (no `shell=True`); token passed after `--`
(can't inject flags). None found.
**Tests:** Real — `test_unsubstantiated_claim_fails` proves the absent-symbol→FAIL
path. Gap: no test covers `model_history.py` reading grounding records (why the
naming desync went unnoticed).
**Code quality: B.** Clean verdict semantics; undermined by the history desync.
**Verdict:** Real, self-match-proof grounding that fails on absent symbols (V3),
but grounding is shallow and a record-name desync zeroes the observability
component.

### `sarif-parsing`
**What it is:** `sarif_helpers.py` parses SARIF into `Finding` dataclasses;
`sarif_poc_gate.py` is the CLI. The gate routes each finding through the hardened
`_shared/oracle` `Reproducer(type="grep")` to check whether the region snippet
still exists at the cited file.
**Verification posture: V3.** Real decorrelated grep that can fail; instrument
failure→ERROR via the oracle's rc≥2 contract; conservative (only positive
staleness drops). All four probed claims verified empirically (imports the real
Reproducer; deleted file→STALE not ERROR; PRESENT honestly ≠ exploitability).
**Top findings:** (1) `_finding_snippet` uses only the first snippet line —
reflowed snippets could read STALE (the one place a true finding can be silently
dropped; low risk). (2) `compute_fingerprint` dedup key is filename-only →
cross-directory collisions. (3) `extract_location` reads only `locations[0]`.
**Security:** `gate_finding_presence` quotes both SARIF-derived values with
`shlex.quote` before the oracle's `bash -c`; a malicious snippet does not escape.
None found.
**Tests:** Strong, decorrelated — all four verdicts on a real tmp tree;
anti-exploitability-inflation guard. Gap: no sarif-layer ERROR-path test
(verified manually); no shlex-quoting test.
**Code quality: A.** Clean, conservative, honestly-scoped; reuses the hardened
oracle rather than reimplementing exit-code handling.
**Verdict:** A genuine, conservative deterministic PoC gate that correctly
distinguishes STALE/ERROR and never overclaims exploitability — the strongest
verifier of the security set.

### `variant-analysis`
**What it is:** `scripts/verify_variants.py` is an oracle over a `hunt-spec.json`
— per pattern it parses (regex/`semgrep --validate`), runs real `rg -n`/`semgrep
--json` over `--target`, checks the Level-0 baseline matches `seed_file:seed_line`,
and applies an FP gate.
**Verification posture: V2 (V3 baseline only).** The baseline check is a real
decorrelated gate (wrong seed line → exit 1, proven). But the headline "variant"
grounding is `rg` match-counting with no exploitability filter; the FP gate (the
only quality bound) is inert without a manual sample; self-matching inflates counts.
**Top findings:**
1. `run_pattern:102-115` has no `--include`/glob restriction and scans `--target`
   which contains the spec + live NDJSON output → counts self-polluted (proven
   `n_matches=2` on spec text).
2. `check_fp_gate:178-182` passes unconditionally when `sampled_fp` absent — the
   documented 50% cap is not machine-enforced by default.
3. `check_baseline:164-166` matches `seed_file` by `endswith` (suffix) — loose.
**Security:** rg/semgrep via argv list (no `shell=True`); but a `pattern`
beginning with `-` could be interpreted as an rg flag (no `--` terminator before
the pattern) — argument-injection surface on attacker-influenced specs.
**Tests:** `test_baseline_fail_when_seed_wrong` proves the decorrelated failure;
`test_fp_rate_gate_trips` only trips by hand-feeding `sampled_fp=100` (masks that
the gate is inert in normal use). No self-match or flag-injection test.
**Code quality: B−.** Runs real tools and the baseline gate is sound; the
self-match pollution and default-inert FP gate undercut the framing.
**Verdict:** Runs real rg/semgrep with a sound baseline gate, but the variant
grounding is heuristic match-counting that self-matches its own spec and whose
only quality bound is inert without manual sampling — V2 overall.

### `insecure-defaults`
**What it is:** `scripts/verify_defaults.py` is a per-finding oracle over
`findings.json` — `check_finding_locates` (the `file:line` still matches),
`check_not_test_fixture` (path exclusion), `classify_fail_open` (regex fail-open
classification), and an opt-in `startup_probe`.
**Verification posture: V1 (Schema-lint) for the security verdict, with a V3
island (locate).**
**Top findings:**
1. **[VERIFIED]** `verify_defaults.py:251` — `per_pass = located and not_fixture`
   **drops the fail-open classification AND probe verdict** from `all_passed`. A
   finding claiming `fail_secure` on code classified `fail_open` emits
   `"passed": false` per-check yet the run returns `all_passed: true, exit 0`. The
   security determination is computed, logged, and discarded for gating.
2. `classify_fail_open:54-63` decides fail-open by regex hints — misses JS
   nullish `??`, `os.getenv("X") or compute()` without a literal, multi-line
   fallbacks. Pure surface pattern, authorship-correlated.
3. `startup_probe:204-211` treats any non-zero as "fail-secure confirmed" — a
   crash for an unrelated reason is falsely fail-secure.
**Security:** **[VERIFIED]** `startup_probe:202` —
`subprocess.run(probe, shell=True, …)` executes `probe_cmd` straight from
`findings.json`. Proven RCE (a `probe_cmd` with `&&` created a file). Since
findings.json is model/possibly-untrusted-authored, this is arbitrary command
execution — the most serious security finding in the corpus.
**Tests:** Smoke-to-moderate, and **the tests entrap the bug** — they assert
`static_verdict` equals the expected string but never that a *contradicted* claim
flips `all_passed` to False; no test that `probe_cmd` is escaped.
**Code quality: C.** Locate/fixture gates clean, but the headline classifier is
non-gating theater and the probe is a `shell=True` RCE.
**Verdict:** The advertised "fail-open verdict" does not gate the run (proven) and
the dynamic probe is a `shell=True` RCE — a locate-linter dressed as a security
oracle (V1).

### `semgrep`
**What it is:** One executable file — `scripts/merge_sarif.py`, a SARIF merger
(SARIF Multitool via `npx --no-install` if present, else pure-Python union +
dedup-by-(ruleId,uri,startLine)). The actual scanning is entirely prose
(subagents run `semgrep … --metrics=off --json`).
**Verification posture: V1.** The only code merges and dedups; no oracle, no
grounding, no gate on finding truth.
**Top findings:** (1) dedup key ignores `startColumn`/`endLine` → distinct
same-line findings collapse (silent loss). (2) keeps only the first run's `tool`
info then overwrites its rules — merging different tools mislabels the driver.
(3) multitool vs pure-python paths produce differently-structured output
(non-deterministic across environments).
**Security:** `npx --no-install` (won't auto-fetch malicious package) + argv
lists; paths from `glob`, not user strings. None found in executable code.
**Tests:** Real for the merger (distinct-merge, dedup, skip/raise-on-unparseable,
empty). Zero coverage of the actual security workflow (it's prose).
**Code quality: B.** Clean, well-tested small utility.
**Verdict:** Not a verifier — a well-tested SARIF merge utility around an
un-executable prose scanning workflow; the dedup can silently drop distinct
findings (V1).

### `sca-review`
**What it is:** Both scripts are explicit NOT-IMPLEMENTED stubs (`return 2` with
a stderr message). All "review" is LLM prose. No oracle, no grounding.
**Verification posture: V0 — but honestly labeled** (the manifest/SKILL.md state
the helpers are stubs and the skill "is not yet end-to-end runnable").
**Top findings:** (1) core functionality unimplemented (declared, not hidden).
(2) the entire quality determination is described as Phase-1 script output, but
that script doesn't exist → high run-to-run variance. (3) no reproducer anywhere.
**Security:** Stubs use only argparse + print; none found.
**Tests:** `test_stubs.py` is a real contract test (asserts exit 2 + "NOT
IMPLEMENTED"); locks the "fail predictably" contract but tests zero review behavior.
**Code quality: D.** No engine; clean honest stubs.
**Verdict:** Two honest NOT-IMPLEMENTED stubs + an all-prose review loop — no
executable verification exists (V0), correctly self-declared.

### `vendor-breach`
**What it is:** `scripts/audit-org.py` (1026 lines) — a read-only GitHub exposure
scanner. Preflights core+code_search rate-limits, paginates repos per org, runs 6
breach + 6 CVE categories via `gh api`/`gh search code`, writes a findings JSON.
**Verification posture: V3.** Every `gh` invocation is exit-code-checked
(`gh_json` returns None on non-zero); probes live GitHub state; rate-limit
preflight exits 2; archived-repo guard forces exit 1.
**Top findings:**
1. **Silent zero-on-failure per category** (`:120-126`,`:142-163`): a non-zero
   `gh` exit (auth-scope loss mid-run, a single-org 403) yields `None`/`[]`
   indistinguishable from a true empty result; only Python exceptions reach
   `errors[]`. A run that lost `repo` scope could report "0 secrets" as healthy.
   The single most important honesty gap.
2. Search-cap heuristic (`SEARCH_LIMIT=100`) underestimates GitHub's real ~300
   cap — truncation above 100 isn't flagged.
3. `check_workflows` accepts any `.yml`/`.yaml` hit for a bare vendor-name query.
**Security:** No injection (all `gh` calls argv-list); only secret *names* read,
never values; `re.compile` on config caught by per-org except. None material.
**Tests:** Real for pure helpers (deploy-pattern, action-pin, query-string
pinning via monkeypatch); one end-to-end test with a stubbed `gh`. Gap: no test
for the swallow-on-non-zero path (finding 1).
**Code quality: B+.** Disciplined read-only design; held back by the silent-zero
conflation.
**Verdict:** A genuinely live-probing, exit-code-checked supply-chain auditor
(V3) whose one real honesty hole is that a non-zero `gh` exit in any single
category is silently flattened to "zero findings."

### `healthcheck`
**What it is:** SKILL.md orchestrates 11 checks; 5 externalized to real Python
helpers (`_check_skills.py`, `check_paths.py`, `_check_orphans.py`,
`_check_manifest.py` + two recall-probe runners). The other 6 are LLM-prose.
**Verification posture: V3 for the externalized checks; V2 for the prose checks.**
Live-run confirmed correct exit codes (skills exit 2, orphans exit 1, paths exit
1). The recall probe is **V4-flavored** (live Voyage embed → real FAISS → recall@5
gate exit 2) — but unwired.
**Top findings:**
1. `.pytest_cache` (and any dotdir) flagged as Tier-A FAIL (`_check_skills.py:160-167`
   only skips `_`-prefixed) — verified live (spurious "SKILL.md missing", exit 2).
2. The two recall probe-runners are **orphaned** — the only V4-grade measured gate
   is referenced by no check (dead capability).
3. `check_paths.py` resolves relative paths against two bases without recording
   which matched.
**Security:** `pickle.load` of `chunk_ids.pkl`/`metadata.db` from the user's own
local index (not attacker-controlled, but latent if shared); `yaml.safe_load`
everywhere; subprocess git calls list-form + returncode-checked. Low-risk pickle
noted.
**Tests:** **No tests for any helper** — exercised only by live run. For a skill
whose job is verification, the verifiers are unverified (the dotdir FP is exactly
what one test would have caught).
**Code quality: B.** Well-structured helpers, correct exit codes; dragged by zero
tests, the dotdir bug, and orphaned runners.
**Verdict:** Real FS/AST/git verifiers with correct exit codes (V3) + one buried
V4 recall gate that's never invoked — undermined by zero tests and a dotdir
false-FAIL.

### `mcp-forge-build`
**What it is:** `scripts/verify_server.py` (363 lines) AST-discovers `@mcp.tool`
functions, checks naming, and — the load test — spawns a subprocess that imports
the generated module and calls `list_tools()`, gating on returncode.
`build_history.py` accumulates NDJSON runs.
**Verification posture: V3, capped by the unimplemented live probe.** The 8b load
test genuinely executes the generated module — a real runtime probe. But the only
live-API check (8f enum probe) is a no-op.
**Top findings:**
1. **8f "passes" unconditionally — including with credentials present**
   (`:231-261` both branches return `passed: True`). SKILL.md:453 +
   verification-suite.md:264 say 8f is "Required when credentials available" and
   "Fail the build" — the live enum validation (the Ashby-incident guard) is
   prose-only, never enforced in code.
2. The 8b load test proves *import*, not tool registration — the test fixture
   hardcodes `_FakeProvider.list_tools()` returning 3 tools, so it verifies the
   oracle's plumbing, never that a real FastMCP decorator registers tools.
3. 8a coverage matches tool↔endpoint by `operationId == tool name`; renamed tools
   (the SKILL's own naming rules) silently skip → coverage passes vacuously.
**Security:** The load test imports generated code (arbitrary-code-exec-on-import
by design); `cwd` controlled. No `shell=True`/`eval`. Note the import-executes
property.
**Tests:** Strong plumbing tests, but the load test is **mocked, not real** — no
test runs against an actual `fastmcp`-backed server; no test asserts 8f does NOT
auto-probe.
**Code quality: B+.** Clean stratified oracle, honest tiering; the 8f mismatch +
fake-only load test are the dings.
**Verdict:** A real subprocess-based load oracle (V3) with solid mechanical
checks, but its one live-API verifier (8f) is an always-pass stub that
contradicts the SKILL's "required/fail-the-build" claim.

### `lab-deploy`
**What it is:** Two boto3 scripts. `verify_waf.py` (277 lines) — the verifier:
assumes into the labs account, finds the WAF on the Amplify app, asserts default
action == Block, recursively resolves IP sets and fails on `0.0.0.0/0`, then
HTTPS-probes domains (200=ALLOWED/403=BLOCKED). `amplify_setup.py` (355 lines) —
the provisioner, each mutation gated by `_confirm`.
**Verification posture: V3 (verify_waf) / V1 (deploy).** `verify_waf.py` queries
live WAF/ACL/IP-set state with exit-code gating (exit 2 on missing-WAF,
non-Block default, wildcard CIDR) — genuine fail-closed real-state verification.
But the build trigger does not confirm deploy state.
**Top findings:**
1. `cmd_trigger_build:301-314` calls `start_job`, prints "job started: {id}", and
   returns — it never polls `get_job` for `SUCCEED`/`FAILED`. An Amplify build
   that fails still reports "started." Classic deploy-reports-success-without-state.
2. `verify_waf.py` probes only from the operator's current egress IP — it can't
   test the "403 from non-allowlisted IP" pass-criterion unless the operator is
   off-allowlist; a WAF that wrongly allows everyone still shows 200=ALLOWED and
   does NOT fail.
3. `find_waf_for_app:138-146` calls boto3 bare (unlike `cmd_inspect`'s
   AccessDenied handlers) → raw traceback on AccessDenied.
**Security:** No injection (all boto3); credential handling is a **strength** —
same-account self-assume short-circuit, scoped assume-role, expired-token hints,
`_confirm` treats non-TTY-without-`--yes` as refusal (fails safe). None found.
**Tests:** Smoke-only and **skipped in this env** (importorskip boto3). The single
most safety-relevant logic (does verify fail closed?) is untested.
**Code quality: B.** `verify_waf.py` is genuinely fail-closed and the credential
UX is the best of the batch; pulled down by the unverified async build + smoke-only
tests.
**Verdict:** `verify_waf.py` is the strongest fail-closed real-state verifier
here (V3), but the Amplify build trigger reports "started" as success without
confirming the build landed.

### `mcp-diagnose`
**What it is:** One script, `analyze_startup.py` (324 lines): a pure-Python parser
for `claude --debug=mcp` logs — regex-extracts timestamps/server-names, classifies
FAIL→OK→START, reconstructs per-server durations + the `alwaysLoad` gate, renders
long-poles + an ASCII cascade + recommendations. Live diagnostics (curl/ECS/
CloudWatch/OPA) are LLM-prose.
**Verification posture: V2 for the coded parser.** It parses a log the operator
captured — no live probe. The genuinely live checks live in SKILL.md as Bash with
real exit semantics, but no code asserts them.
**Top findings:** (1) duration arithmetic uses a `(y*372)+(mo*31)+d` day
approximation + seconds-since-midnight; mixed shapes / midnight-cross / restart →
negative/huge duration silently nulled to "n/a" (a 33s hang can vanish from the
ranking). (2) greedy STATUS classification can leave a failed server PENDING and
excluded from recommendations. (3) no freshness check — a stale log yields
confident "restart required."
**Security:** Pure stdlib parser — no subprocess/network/eval; reads one log with
`errors="replace"`. None found.
**Tests:** Genuinely good incident-replay tests (exact `duration_ms==33050`,
hyphenated-name regression, empty→exit 2). Gaps: no test for the bad-duration
path, midnight wrap, or PENDING handling.
**Code quality: B+.** Clean, version-tolerant parser with strong replay tests.
**Verdict:** A clean, well-tested heuristic log-parser (V2); the genuinely live
checks exist only as prose, so the script itself proves nothing about current state.

### `supergoal`
**What it is:** A setup/bookkeeping wrapper around Claude Code's built-in `/goal`.
`parse_plan.py` regex-extracts plan fields → `state.json`; `check_prior_arcs.py`
refuses at 3+ arcs; `write_terminal.py` renders the exit doc + maps exit_reason →
exit code; `state_io.py` provides fcntl-locked atomic state. **The per-turn
verification loop is NOT code** — it's a prose checklist for a `type:agent` Stop hook.
**Verification posture: V2, aspiring to V3 but unproven.** The *design* describes
V3/V4; but every gate is prose interpreted by an agent at runtime. The only
deterministic, tested code is the parser, state I/O, and the setup-time exit codes.
**Top findings:**
1. `state_io.py:186` — `state.get('plan_sha256')[:12]` raises `TypeError` on
   `--resume` when the sha is null/missing (reproduced live).
2. `parse_plan.py:255-259` — `extract_metric_names` returns `[]` for the minimal
   golden plan (requires 3+-char ALLCAPS); since `check_prior_arcs.py` skips when
   empty, prior-arc protection silently no-ops for any plan whose metrics aren't
   ALLCAPS≥3char.
3. `write_terminal.py:140` — the terminal doc's "freshness verdict"/"Goodhart"
   sections are templated placeholders, not computed from measured data.
**Security:** git/gh via subprocess list-args (no `shell=True`); slug sanitized.
The hook prompt's `git commit -m "...$REASON"` is agent-Bash (prose, outside code
review). No eval/pickle. SHA attestation is integrity-only (detect, not prevent).
**Tests:** Real for the parser/state/exit-code mapping. **Zero tests exercise the
verification decision tree** (it isn't code) — the thing the skill is named for is
untested.
**Code quality: B.** Clean, cross-platform, atomic-write-aware; capped because the
load-bearing logic is unverifiable prose + two edge-case bugs.
**Verdict:** A meticulous, honest *spec* for tool-backed verification whose
deterministic core is real only at the parser/state layer; the per-turn
"deterministic evidence" gate is agent-interpreted prose (V2, not the V3/V4 it
implies).

### `scout-frontier`
**What it is:** `validate_constraint_trace.py` (YAML + regex schema-linter) +
`score_rubric.py` (reads a hand-authored fixture JSON, computes paradigm
"distance" as set-difference over 4 string axes, compares to the fixture's
hand-declared distance).
**Verification posture: V1.** `validate_constraint_trace.py` is a textbook schema
linter. `score_rubric.py` is a fixture self-consistency checker — it CAN fail
(exit 1 on FP/FN), but the ground truth is hand-declared in the same file, so it
verifies authoring discipline, not real-world validity. The 5-check real-grounding
suite is prose only. The "frontier/oracle" framing is explicitly disclaimed in
SKILL.md — **not overstated.**
**Top findings:** (1) `score_rubric.py:20-23` distance is pure set-difference over
human-assigned strings — "instrument valid" PASS is a tautology over hand-entered
data. (2) `MEASURABLE_PHRASES` accepts "improve the benchmark a lot" — keyword
presence, not measurability. (3) negative controls checked only for `distance!=0`,
axes never recomputed.
**Security:** `yaml.safe_load` (correct); no shell/eval/network. None found.
**Tests:** `test_validate_constraint_trace.py` is genuinely good (13 tests, real
subprocess, each FAIL condition + malformed/empty). **No test for `score_rubric.py`**
(the more consequential script).
**Code quality: B+.** Clean, safe YAML, good exit-code discipline; capped because
the headline "scoring" is a self-consistency lint with no test.
**Verdict:** Honestly-disclaimed draft generator whose two scripts are a safe YAML
schema-linter (V1) and a fixture self-consistency checker — no oracle overstatement,
but the "scoring" is grounded in hand-authored labels, not fetched data.

### `scout-skills`
**What it is:** Two scripts that dispatch to **live external LLMs** via the
sibling `roundtable/scripts/adapters`. `produce_card.py` → GPT-5.5-pro extracts a
technique card; `verify_skip.py` → both Grok-4.20 and GPT-5.5 in parallel, parses
verdicts, applies quorum.
**Verification posture: V2 — multi-model LLM quorum with a defensively-correct
abstention rule.** `verify_skip.py:214-233`: SKIP confirmed ONLY if ≥1 model
returns `CONFIRMED-COVERED`; any error/parse-error/ambiguity abstains (exit 20)
rather than defaulting to skip. The code documents that the *prior* version's
catch-all `else` defaulted to SKIP on partial failure (a real bug now fixed). Not
deterministic (external models), so V2 — but real grounding in fetched judgments
over actual files, not fabrication.
**Top findings:** (1) a clear GAP-EXISTS from one model + one transient error
yields ABSTAIN rather than REVIEW-NEEDED (under-escalates). (2) silent truncation
(`[:4000]`/`[:12000]`) can flip a verdict with no warning. (3) hardcoded model IDs
(graceful abstain if retired, but no version pin).
**Security:** Adapters POST over HTTPS with env bearer tokens, never logged; no
`shell=True`/eval/pickle. SSRF limited to two fixed API hosts. None material.
**Tests:** 6 tests on `parse_verdict` only. **The quorum decision logic — the
actual "verification," recently bug-fixed — is untested.**
**Code quality: B+.** Clean concurrency, honest fallbacks, well-reasoned abstention.
**Verdict:** A real, decorrelated two-model SKIP quorum with a correctly-defensive
abstention rule (V2 — grounded in live model judgments over actual files),
undermined by an untested decision core and silent truncation.

### `gather-repos`
**What it is:** The skill dir has only a live regression suite + references; the
scoring engine lives at `~/.claude/scripts/_gather_screen.py` — runs `gh api` to
fetch repo metadata + git tree, then `score_tree` counts how many of 6 buckets
appear as path substrings → "score N/6." `_gather_repos_archive.py` is a
deterministic markdown ledger-archiver. Discovery/triage/handoff are LLM prose.
The skill explicitly disclaims evaluation.
**Verification posture: N/A — not a verification skill. Output-grounding:
grounded (deterministic) but threshold-inconsistent.**
**Top findings:**
1. `_gather_screen.py:87` — `if "skill" in lines and ".md" in lines` is a
   tree-wide substring test (trips on `skill-ideas.md`), contradicting SKILL.md's
   "5+ SKILL.md" AND the test's `>=3`. Three definitions of one bucket; the
   primary routing signal isn't reproducible across doc/test/engine.
2. No depth/stub check despite the documented "Depth flag" — score inflates on
   echo-placeholder repos (the hatch3r case the doc says it prevents).
3. Tree fetch capped at 200 entries → large repos under-score silently.
4. `test-gather-repos.py` makes **live unconditional `gh api` calls** to real
   external repos — an integration test masquerading as a unit test, and it tests
   a *reimplementation* that doesn't match the shipping scorer.
**Security:** `gh api` via list-args (no `shell=True`); `_parse_args` rejects
flag-like input; `urllib.parse.quote` on queries. None material.
**Tests:** Mixed — genuine negative tests (hook-bias, memory-FP) but bolted to
live network against mutable repos, and testing a divergent reimplementation.
**Code quality: C+.** Clean archiver, sound test *intent*; sloppy substring scorer
+ non-hermetic live-API suite.
**Verdict:** "Score N/6" is genuinely computed from fetched git trees but rests on
a sloppy substring match that disagrees with its own docs and its own
(non-hermetic) tests — output-grounded yet not reproducible.

### `recall`
**What it is:** A retrieval skill whose actual search (Glob/Grep then memory-search
MCP, two-pass read, confidence tagging) is LLM-prose — no retrieval code. The only
Python is telemetry: `log_telemetry.py` (append one JSONL record per invocation)
+ `analyze_telemetry.py` (summarizes rates, top-1 cosine percentiles, slot
histogram, D2 verdict).
**Verification posture: N/A — telemetry analyzer. Output-grounding: grounded
(deterministic stats over real logged data).** Verified live: correct counts,
malformed-line skip, tz-aware filtering, percentiles, D2 verdict. **Retrieval
correctness itself is not measured by any code** — only usage patterns.
**Top findings:** (1) the central "is retrieval correct?" has no code answer
(prose thresholds). (2) `analyze_telemetry.py:87` treats a genuine `0.0` cosine as
falsy/absent. (3) `_parse_slots` silently drops malformed tokens.
**Security:** JSON-only writes to a fixed path; no shell/eval/network. None found.
**Tests:** 6 tests on the two pure parsers. **Zero tests for `analyze_telemetry.py`**
(the percentile/D2 logic).
**Code quality: A−.** Small, clean, exemplary honesty about instrumented-vs-
aspirational; capped by the untested analyzer.
**Verdict:** Retrieval correctness lives entirely in prose (unverified by code),
but the telemetry it ships is a clean, honestly-scoped deterministic analyzer
over real logged data — it measures usage, not precision, and says so.

### `garden`
**What it is:** `scripts/analyze.py` is a self-contained deterministic analyzer of
a KB `topics/` dir — parses frontmatter, counts dated H2 entries, extracts
wiki-links with code-fence masking, classifies files, computes stage mismatches,
broken/bare links, orphans, MoC gaps, leaf-chunk sizes (replicating the CI gate),
and writes a JSON report to a **temp path outside the staging repo.**
**Verification posture: V3 — the strongest output-grounding of its cluster.**
Every count/candidate is computed from actual file contents by code with checks
that genuinely fire (verified live: correct stage mismatches, the one real broken
link, correct backtick-masking, the MoC gap). Not V4 — thresholds are fixed design
constants, judgment steps are LLM prose.
**Top findings:** (1) `mask_for_links:106` non-greedy fence matching leaves an
unterminated code block / `~~~` fence unmasked → wiki-links inside treated as real.
(2) `stage_for_count` counts only *dated* H2 entries — undated section headers
flag a topic as seedling. (3) MoC `cssclasses` checked by substring (`"moc" in css`)
→ misclassification risk.
**Security:** **Read-only on topics; writes only to `tempfile.gettempdir()`**
(designed so it "can never trip the push"). Hand-rolled frontmatter parser, NOT
`yaml.load`. No subprocess/eval/network. None found.
**Tests:** **No tests exist** — the leaf-chunk algorithm is "load-bearing for
agreement with the CI gate" yet has no byte-alignment test; masking/classification
unverified.
**Code quality: B+.** Genuinely deterministic, safe (temp-only, no yaml.load),
excellent inline rationale; held from A only by masking edge cases + zero tests.
**Verdict:** A real V3 deterministic KB analyzer that computes every count from
actual file contents (verified live), writes safely to temp, and avoids yaml.load;
its only material gaps are masking edge cases and a total absence of tests for code
that must stay byte-aligned with the CI gate.

---

## Wave 2 preview (prompt-only skills)

The remaining ~66 skills carry no executable source — the SKILL.md *is* the
implementation. Wave 2 evaluates them on design quality (trigger precision,
altitude, claim honesty, tool-surface minimalism, chaining hygiene) rather than
code correctness, using the same "judged from what's actually written" discipline.
