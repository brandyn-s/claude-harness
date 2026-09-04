# Research skills A/B: root cause of "no lift" (2026-09-03)

**Question (owner).** The five research skills (`deep-dive`, `gather-intel`,
`gather-research`, `triage`, `evaluate-repos`) showed no lift over a plain model with
web search in the 2026-09-03 rerun on `claude-fable-5-1`, and their frozen 2026-05-31
baselines on `claude-opus-4-8` were already `trim`/`fix`. Is this better models, or
are the skills doing something wrong?

**Short answer.** Mostly neither. Every record of both runs was re-scored with each
skill's own `grade.py` and laid side by side per question. On four of the five skills
the harness cannot distinguish the arms: the baseline is at ceiling on the fixture
under both models, and every headline delta today, including both `fix` verdicts,
traces to the instrument (a stale answer key, a phrase-cue list that misses correct
rejections, a bootstrap CI that is degenerate at N=3, a `fix` rule fired by one record
at N=1). The one skill whose records show a mechanism at work, `evaluate-repos`, shows
it on both models: the LLM synthesis step over-hedges to DEFER regardless of model, and
the over-dismissal guard turns "no concrete blocker" into ADOPT on patterns whose
rejection rationale the arms cannot see. On all five, the "framework arm" is a
700-1,700-character distillation of the skill's epistemic rules injected as a system
prompt; the skill's multi-wave procedure is never run, so "no lift" is a statement about
that paragraph, not about the skill.

## 1. Verdict table

| Skill | Today (`ab/*.json`) | Frozen 2026-05-31 | Model / skill defect / both | Mechanism | Recommendation |
|---|---|---|---|---|---|
| deep-dive | `fix` (disc -0.0513) | `trim` (disc 0.0) | Neither: grader artifact + ceiling. Skill-side: counterfactual layer is boilerplate by construction | All 7 grader-"wrong" records (2 framework, 5 baseline) are correct answers: stale `current-anthropic-model` key (3), rejection-cue miss on `cot-faithfulness-solved` (4). True accuracy 90/90 both arms, both dates. 88/88 counterfactuals say COLLAPSES | Fix the grader (section 8), re-grade the existing transcripts; keep the confidence layer; make the counterfactual conditional |
| gather-intel | BLOCKED (CI [0, 0.2]) | `trim` (+0.045) | Model (May edge gone) + oracle (today's delta) | May's +0.095 refutation_recall was one claim (`taskoutput`); today both arms get it. Today's +0.067 grounding_precision is one CONTESTED on `three-workers-sweetspot`, a claim no arm has ever grounded (0/11) | Retire the A/B at this fixture (baseline 45/45); keep the skill as an audit/report format; if re-measured, fix the oracle term and the primary metric |
| gather-research | BLOCKED (CI [0, 0]) | `trim` (0.00) | Neither: fixture ceiling on both models | 180/180 correct, 0 ungrounded, both arms, both dates. Only difference: UNCHARTED with 0 citations vs FALSE with citations on all 18 fabricated records, unscored | Stop rerunning until a discriminating fixture exists; fix the UNCHARTED rule for named-artifact existence claims; grade the label taxonomy |
| triage | BLOCKED (CI [-0.07, 0.007]) | `trim` (+0.019) | Neither: noise, plus one format-induced deviation | Paired Spearman deltas +0.007 / -0.070 / 0.0; the -0.070 run follows the worked example in SYSTEM_WITH. Correlation groups identical across arms in all 12 records | Harness tests a 2-sentence prompt, not the constitution; keep the skill as a report format; if kept, drop the worked example and run N>=10 |
| evaluate-repos | `fix` (over-adoption 0.143, N=1) | `fix` (backfire +0.238) | Both | Skill: synthesis DEFERs 67% (May) / 50% (today) regardless of model; guard adopts `checklist-imperatives` in 2/4 runs. Model: the Fable single pass hedges (DEFER 8/14 vs 4/42), so baseline false-dismissal went 0.286 to 0.714 while accuracy tied 6/14. Today's `fix` is one record at N=1 | Harness measures an auto-synthesis proxy the SKILL.md forbids; retire the decision A/B or change the unit to the arguments; N>=3; score should_reject only where the rationale is public (2/7) |

## 2. Method and inputs

- Metrics and receipts: `/tmp/claude-review/ab/{deep-dive,gather-intel,gather-research,triage,evaluate-repos}.json`, driver `/tmp/claude-review/ab/run-ab.sh` (model `claude-fable-5-1`, `--max-tokens 4000` for both arms, runs 3/3/3/3/1).
- Today's records: `skills/<skill>/harness/runs/transcripts-20260903T{205439,211607,212244,212334,212614}Z.json` (gitignored). No `sample-records-2026-09-03.json` exists for any skill. The two `transcripts-20260903T210656Z.json` files under `gather-intel` and `gather-research` are 30/30 `CALL_ERROR` (`AttributeError: module 'anthropic' has no attribute 'Anthropic'`) from an aborted first driver pass; they are not results.
- Frozen records: `skills/<skill>/harness/runs/sample-records-2026-05-31.json` (gather-* have `_text` stripped), `harness/results.json`, `harness/PROBLEM.md`.
- Arm prompts: `harness/run_live.py` (`SYSTEM_WITH`/`SYSTEM_BASE`; `SYS_ADVOCATE`/`SYS_SKEPTIC`/`SYS_SYNTH` for evaluate-repos). Graders: `harness/grade.py`, `skills/_shared/stats.py`.
- Procedure: import each `grade.py`, call `score_run` per arm per run on both record sets, tabulate per item. The re-grade reproduces `results.json` and `ab/*.json` exactly. Every record the grader marked wrong was read in full; every record where the arms disagree was read.
- Record ids below are `<skill>/<date>/run<i>/<arm>/<item-id>`.

## 3. What the A/Bs actually compare

| Skill | WITH arm | BASE arm | Calls per item | Search | System prompt (chars) | Asserted `COST_RATIO` | Measured output ratio (today) |
|---|---|---|---|---|---|---|---|
| deep-dive | 4 steps: search + reject false premise, answer, HIGH/MEDIUM/LOW with rules, counterfactual with SURVIVES/COLLAPSES/AMBIGUOUS | answer + HIGH/MEDIUM/LOW | 1 | web_search max_uses 4, both | 950 vs 250 | 4.0 | answer 938 vs 548 chars (1.7x); 2.8x including the 595-char counterfactual |
| gather-intel | T1-T5 authority, adversarial counter-search, version awareness, SUPPORTED/OUTDATED/REFUTED/UNCHARTED(/CONTESTED), cite only specific pages | TRUE/FALSE/OUTDATED/NONEXISTENT with citations | 1 | max_uses 5, both | 1,690 vs 570 | 5.0 | 2,814 vs 1,918 chars (1.47x); 6.4 vs 5.7 URLs |
| gather-research | PRIMARY/ADJACENT/OFF-DOMAIN, freshness windows, verdict bars (>=2 / >=3 PRIMARY), UNCHARTED rule, symmetric burden | free-form TRUE/FALSE/OUTDATED/UNVERIFIED with citations | 1 | max_uses 5, both | 1,555 vs 385 | 5.0 | 1,533 vs 1,837 chars (0.83x); 4.7 vs 4.6 URLs |
| triage | severity rule with a worked example + explicit cross-tool correlation pass | "rank by priority and note shared root causes" | 1 | none | 696 vs 333 | 5.0 | not stored (only ranking/groups kept) |
| evaluate-repos | advocate (730) + skeptic (703) + synthesis with over-dismissal guard (1,278) | single self-eval (727) | 3 vs 1 | none | see left | 3.0 | structural 3x |

Two consequences frame everything below. First, none of the WITH arms loads `SKILL.md`,
`references/`, topics, or runs a search wave; the arms differ only in the system prompt,
and in four of five harnesses they make the same number of calls with the same search
budget. Second, the `COST_RATIO` constants are asserted in each `run_live.py`, not
measured: receipts and `_response_provenance` carry no token usage. The "not worth ~5x
cost" clause in every verdict refers to the real skills' multi-wave ceremony, which the
harness does not run. The measured input-side difference is 2.1-4.0x system-prompt
length; the output side is 0.83-1.7x.

## 4. deep-dive

### 4.1 Where the arms differ on the same inputs

| | 2026-05-31 Opus 4.8 (45 records/arm) | 2026-09-03 Fable 5.1 (45 records/arm) |
|---|---|---|
| Grader accuracy | WITH 45/45, BASE 45/45 | WITH 43/45, BASE 40/45 |
| True accuracy (records read) | 45/45, 45/45 | 45/45, 45/45 |
| Confidence labels WITH | 43 HIGH, 2 "MEDIUM" (both are empty-confidence parse fallbacks) | 39 HIGH, 2 MEDIUM, 4 LOW |
| Confidence labels BASE | 45 HIGH | 44 HIGH, 1 MEDIUM |
| Counterfactual verdicts (WITH) | 43 present, 43 contain COLLAPSES (39 only COLLAPSES); 0 SURVIVES-only | 45/45 contain COLLAPSES (42 only COLLAPSES, 3 + AMBIGUOUS); 0 SURVIVES-only |
| Answer length | 848 vs 521 chars | 938 vs 548 chars |

The two arms give the same substantive answer on all 15 questions in all 3 runs on both
dates. The framework arm's only behavioral differences are six non-HIGH labels today
(`holographic-memory` run0/run1 LOW, `anthropic-selfreview-stat` run0/run2 LOW,
`current-openai-flagship` run1/run2 MEDIUM; all six answers correct) versus one for the
baseline (`anthropic-selfreview-stat` run0 MEDIUM), plus the counterfactual text.

### 4.2 Source of every grader-flagged error today

| Records | Grader | Actual answer | Class |
|---|---|---|---|
| `deep-dive/2026-09-03/run1/with_skill/current-anthropic-model`; `.../run0/baseline/...`; `.../run1/baseline/...` | wrong (no `expected_terms` "opus 4") | "Mythos-class tier ... Claude Fable 5 (announced June 9, 2026)". Consistent across all 6 records and with the model id under test. The key written 2026-05-31 encodes the answer the question was designed to catch as stale | Grader artifact: stale currency key |
| `.../run0/with_skill/current-anthropic-model`; `.../run2/with_skill/...`; `.../run2/baseline/...` | correct | Same Fable-5 answer; passes only because "Opus 4.8" appears in a caveat ("fall back to Opus 4.8", "during which Opus 4.8 was the most capable available") | Grader artifact, favorable direction; verbosity-dependent |
| `.../run0/with_skill/cot-faithfulness-solved`; `.../run0,run1,run2/baseline/cot-faithfulness-solved` | wrong (no rejection cue) | "None. No 2025 result definitively solved ... the premise is false." `grade._REJECTION_CUES` contains "false premise" but not "premise is false", "no 2025 result", or "none." | Grader artifact: cue-list miss (4 correct rejections failed) |
| `.../run1,run2/with_skill/cot-faithfulness-solved` | correct | Same rejection, opens with "No such result exists" | Cue matched |
| 4 LOW labels on false-premise rejections (WITH) | counted as non-HIGH-correct, lowering `calibration_discrimination` | Follows `SYSTEM_WITH` step 3: "LOW when ... the premise is dubious". The grader scores a rejection as correct, so a framework arm that obeys its own prompt is structurally pushed to negative discrimination | Format-induced, prompt/grader conflict |
| `deep-dive/2026-05-31/run2/with_skill/current-anthropic-model` and `.../current-openai-flagship` | correct, confidence '' | JSON cut mid-counterfactual at `max_tokens=1500` (the answer ends "...the most capable *"); scored on the last 600 chars | Format-induced (verbose arm hit the budget); 0 today at 4000. These are the "2 of 45 not HIGH" in PROBLEM.md section 5 |

Category counts today: grader artifact 10 records (7 false-fails, 3 false-passes);
format-induced 4 (LOW-on-rejection); boilerplate 45/45 counterfactuals; calibration
noise: not measurable (no true errors to discriminate); retrieval: 0 identifiable (search
results are not stored); genuine reasoning difference: 0.

### 4.3 Same pattern on Opus 4.8

Yes. Ceiling on both dates; counterfactuals 100% COLLAPSES on both dates; the grader was
brittle to the framework arm's verbosity on both dates (May: the v1 `wrong_terms` bug in
PROBLEM.md section 6 penalized WITH; today: the stale key and cue list penalized BASE).
The direction of the artifact flipped, the artifact did not.

### 4.4 Verdict machinery

- The `fix` fired by a margin of 0.0013 (discrimination -0.0513 vs floor -0.05). Its two
  "HIGH + wrong" inputs are the grader-failed correct answers in 4.2.
- Had the anti-calibration check not fired, `decide_verdict` falls through to
  `stats.ci_verdict` on `accuracy`, which returns `keep`: the three paired deltas are
  0.0666 / 0.0666 / 0.0667, so the bootstrap CI is [0.0666, 0.0667] and "excludes zero".
  The same grader artifacts would have produced a `keep`.
- Cost: asserted 4.0; measured 3.8x system prompt, same calls, same search budget, 1.7x
  answer text plus a counterfactual that never once survived. What the framework buys is
  6 non-HIGH labels on the 8 questions where hedging is appropriate (currency and false
  premise) versus 1 for the baseline. That is directionally sensible and unmeasurable at
  100% accuracy.

## 5. gather-intel

### 5.1 Where the arms differ

| Claim (category) | 2026-05-31 WITH | 2026-05-31 BASE | 2026-09-03 WITH | 2026-09-03 BASE |
|---|---|---|---|---|
| `three-workers-sweetspot` (true_primary) | CONTESTED / SUPPORTED-ungrounded / SUPPORTED-ungrounded | TRUE-ungrounded x3 | SUPPORTED-ungrounded x2 / CONTESTED | TRUE-ungrounded x3 |
| `taskoutput-community-workaround` (outdated) | CONTESTED / CONTESTED / SUPPORTED+grounded | TRUE+grounded x3 | OUTDATED x3 | OUTDATED x3 |
| other 13 claims | identical disposition to BASE, all runs | | identical, all runs | |

Totals: May WITH 43/45 vs BASE 42/45 correct; today WITH 44/45 vs BASE 45/45. Label
vocabularies today: WITH 14 SUPPORTED / 6 OUTDATED / 18 REFUTED / 6 UNCHARTED / 1
CONTESTED; BASE 15 TRUE / 6 OUTDATED / 18 FALSE / 6 NONEXISTENT. Fabricated claims:
WITH 6 UNCHARTED with empty `cited_urls` plus 3 REFUTED (`fab-contextzip`); BASE 3 FALSE
plus 6 NONEXISTENT, all with citations.

### 5.2 Source of every arm-specific error

| Records | Class | Evidence |
|---|---|---|
| `gather-intel/2026-09-03/run2/with_skill/three-workers-sweetspot` CONTESTED; `.../2026-05-31/run0/with_skill/...` CONTESTED | Format-induced (CONTESTED option + adversarial step) | Today's transcript: the adversarial pass surfaced sources claiming 4-8, 5-8 and 10 as the sweet spot, so the arm chose CONTESTED. The fixture calls this claim "a community-reported heuristic"; PROBLEM.md section 6 already attributed all May noise to it |
| all 11 supported-but-ungrounded records across both dates (WITH 4, BASE 7), all `three-workers-sweetspot` | Oracle defect | `grounding_terms` are `["three parallel workers", "sweet spot"]`, the verbatim phrase from one repo (`p3nchan/cc-orchestrator`). No arm cited that repo in any of the 11 records; the term check cannot pass on any other page |
| `gather-intel/2026-05-31/run0,run1,run2/baseline/taskoutput-community-workaround` TRUE (3 genuine baseline errors) vs WITH CONTESTED x2 | Retrieval, prompt-induced (May); closed by the model (today) | May baseline cited GitHub issues and a how-to page; the framework's version-awareness step led it to CONTESTED. Today both arms cite the CHANGELOG (`.../v2.1.90/CHANGELOG.md`, a changelog guide) and answer OUTDATED. May `_text` is stripped from the committed sample, so model vs retrieval cannot be separated further |

Counts today: WITH-only errors 1 (format-induced); BASE-only 0; oracle-ungroundable 5;
grader artifact 0; genuine reasoning difference 0.

### 5.3 Same pattern on Opus 4.8

The CONTESTED on `three-workers-sweetspot` recurs 1/3 runs on both models: a prompt
effect. The `taskoutput` edge existed only on Opus: the entire May refutation_recall gain
(+0.095 = 2 of 3 runs on 1 of 7 claims) and 2/3 of the verdict_accuracy gain came from it.

### 5.4 Metric and cost

- `grounding_precision` is computed over asserted-SUPPORTED items, so abstaining
  (CONTESTED/UNCHARTED) on the one un-groundable claim raises it: today's whole delta is
  4/4 vs 4/5 in run2 (paired deltas 0.0 / 0.0 / 0.2). A primary metric that rewards
  abstention on the fixture's weakest item is not measuring the framework.
- Cost asserted 5.0; measured 3.0x system prompt, 1.47x output, same calls and search
  budget. With the baseline at 45/45 today, there is nothing left to buy on this fixture.

## 6. gather-research

Both dates, both arms: 45/45 verdicts correct per run, 5/5 supported records grounded,
180/180 overall, 0 issues. The arms differ only in vocabulary: WITH SUPPORTED / REFUTED /
OUTDATED / UNCHARTED; BASE TRUE / FALSE / OUTDATED. On the 3 fabricated claims the
framework answered UNCHARTED with empty `cited_urls` in 18/18 records across both dates
and the baseline answered FALSE with citations in 18/18 (e.g.
`gather-research/2026-09-03/run0/baseline/constitutional-scaling-laws` cites the real
Lawfare "Scaling Laws & Claude's Constitution" piece and the Anthropic constitutional
classifiers page while arguing the claim is false). Both normalize to `not_supported`.

Error classification: none in either arm on either date. The unscored format effect cuts
against the framework: for a specific named paper that a search shows does not exist,
"UNCHARTED, no citations" is a weaker and less useful verdict than "FALSE, here is the
adjacent real work" (PROBLEM.md section 5 already made this point). The framework arm is
also shorter (0.83x output) precisely because UNCHARTED emits nothing.

Cost asserted 5.0; measured 4.0x system prompt, 0.83x output. Two full runs (180 records,
about 180 web-search calls) have produced zero bits about the framework; the fixture has
no discriminating power for a searching frontier model of either generation.

## 7. triage

### 7.1 Rankings, both dates (expert order f1 f2 f3 f4 f5 f6 f9 f12 f7 f11 f10 f8; true groups {f1,f2} {f4,f5} {f7,f11})

| Record | Spearman | Ranking | Groups |
|---|---|---|---|
| `triage/2026-05-31/run0/with_skill` | 0.972 | f1 f2 f3 f5 f4 f6 f9 f7 f11 f12 f10 f8 | {f1,f2,f3} {f4,f5} {f7,f11} |
| `.../run0/baseline` | 0.937 | f1 f2 f3 f4 f5 f6 f7 f11 f9 f12 f8 f10 | same |
| `.../run1/with_skill` | 0.965 | f1 f2 f3 f5 f4 f9 f6 f7 f11 f12 f10 f8 | same |
| `.../run1/baseline` | 0.937 | f1 f2 f3 f5 f4 f6 f7 f11 f9 f12 f10 f8 | same |
| `.../run2/with_skill` | 0.937 | f1 f2 f3 f5 f4 f6 f7 f11 f9 f12 f10 f8 | same |
| `.../run2/baseline` | 0.944 | f1 f2 f3 f4 f5 f6 f7 f11 f9 f12 f10 f8 | same |
| `triage/2026-09-03/run0/with_skill` | 0.965 | f1 f2 f3 f5 f4 f9 f6 f7 f11 f12 f10 f8 | {f1,f2} {f4,f5} {f7,f11} |
| `.../run0/baseline` | 0.958 | f1 f2 f3 f5 f4 f6 f7 f9 f11 f12 f10 f8 | same |
| `.../run1/with_skill` | 0.853 | f1 f2 f3 **f6 f7** f5 f4 f11 f9 f12 f10 f8 | same |
| `.../run1/baseline` | 0.923 | f1 f2 f3 f4 f5 f7 f6 f11 f9 f12 f10 f8 | same |
| `.../run2/with_skill` | 0.958 | f1 f2 f3 f5 f4 f6 f7 f9 f11 f12 f10 f8 | same |
| `.../run2/baseline` | 0.958 | identical to with_skill | same |

### 7.2 Error sources

- The single framework loss today (`run1/with_skill`, 0.853) ranks f6 (UnicodeDecodeError
  crash) and f7 (YAML lint failure) above the IPv6 pair f4/f5. f4's text says "a
  documented IPv4 workaround exists"; `SYSTEM_WITH`'s worked example says "a latency issue
  with a known workaround" ranks below an active leak and above a cosmetic nudge. The
  prompt's own example anchors the demotion. Format-induced, 1 of 3 runs. (`run1/baseline`
  also lifted f7 above f6, so part of the f7 movement is model noise.)
- Everything else is local swaps (f4/f5, f9 vs f7/f11, f8/f10) that appear in both arms on
  both dates. Paired deltas today +0.007 / -0.070 / 0.0; the run-to-run stdev of the
  framework arm (0.051) exceeds the arm delta (0.021). N=3 runs of a 12-item ranking
  cannot resolve a 0.02 Spearman difference.
- Groups: identical across arms in all 12 records. Opus over-grouped f3 with f1,f2 in 6/6
  records (F1 0.75); Fable did not in 6/6 (F1 1.0). Model effect, same in both arms.

### 7.3 Same pattern on Opus 4.8

Yes: +0.019 in May, -0.021 today, both inside the run-to-run spread. The May advantage
came from placing f9 before f7/f11 in 2/3 WITH runs; today that placement appears in both
arms. Noise.

### 7.4 What is measured

The `with_skill` arm is two sentences. Phase 0 topic loading, FP verification, the
devil's-advocate subagent, adversarial validation, the composite scoring table, and the
tool-status footer, i.e. the 14-article constitution the SKILL.md "Measured Efficacy"
section says was A/B'd, are not exercised. Cost asserted 5.0; measured 2.1x system prompt,
same single call.

## 8. evaluate-repos

### 8.1 Per-pattern decisions

| Pattern (disposition, look_dismissable) | 2026-05-31 WITH (3 runs) | 2026-05-31 BASE | 2026-09-03 WITH | 2026-09-03 BASE |
|---|---|---|---|---|
| listwise-rerank (adopt, yes) | DEFER ADOPT DEFER | REJECT DEFER REJECT | DEFER | DEFER |
| behavioral-labels (adopt, yes) | DEFER DEFER DEFER | ADOPT x3 | DEFER | DEFER |
| blinded-judge-pool (adopt, yes) | ADOPT x3 | ADOPT x3 | **ADOPT** | DEFER |
| noise-aware-significance (adopt) | ADOPT ADOPT DEFER | ADOPT x3 | ADOPT | ADOPT |
| per-finding-counterfactual (adopt) | DEFER DEFER ADOPT | ADOPT x3 | DEFER | DEFER |
| held-out-grader (adopt) | DEFER ADOPT ADOPT | ADOPT x3 | **ADOPT** | DEFER |
| ship-binary-not-optin (adopt, yes) | ADOPT DEFER DEFER | REJECT x3 | ADOPT | ADOPT |
| xml-rule-format (reject) | DEFER x3 | REJECT x3 | DEFER | **REJECT** |
| auto-learn-loop (reject) | REJECT REJECT DEFER | REJECT x3 | REJECT | REJECT |
| checklist-imperatives (reject) | DEFER **ADOPT** DEFER | REJECT x3 | **ADOPT** | DEFER |
| context-fork-dispatch (reject) | DEFER x3 | DEFER x3 | DEFER | DEFER |
| downgrade-orchestration-model (reject) | DEFER x3 | REJECT x3 | DEFER | **REJECT** |
| parallel-worktree-cleanup (reject) | DEFER x3 | REJECT x3 | DEFER | DEFER |
| toon-format (reject) | DEFER REJECT DEFER | REJECT x3 | REJECT | REJECT |
| Decision counts | DEFER 28 / ADOPT 11 / REJECT 3 | REJECT 23 / ADOPT 15 / DEFER 4 | DEFER 7 / ADOPT 5 / REJECT 2 | DEFER 8 / ADOPT 2 / REJECT 4 |

Parse fallbacks: 0/84 (May), 0/28 (today); every decision is a clean token.

### 8.2 Error sources

| Mechanism | Class | Evidence |
|---|---|---|
| Synthesis hedges to DEFER | Debate bias (skill) | WITH DEFER share 67% (May) and 50% (today); baseline 10% and 57%. `hard_reject_rate` on should_adopt is 0/21 (May) and 0/7 (today): the synthesis never rejects a good pattern, it defers it. Replicates across models |
| Guard converts "no named blocker" to ADOPT | Debate bias, over-correction (skill) | `checklist-imperatives` ADOPT in `evaluate-repos/2026-05-31/run1/with_skill` and `.../2026-09-03/run0/with_skill` (2 of 4 runs). The pattern's blocker is an internal adversarial format trial the arms never see, so the skeptic cannot name it and `SYS_SYNTH` instructs ADOPT |
| Baseline decisiveness collapsed | Model | Opus single pass: ADOPT 15/42, REJECT 23/42, DEFER 4/42. Fable: ADOPT 2/14, REJECT 4/14, DEFER 8/14. Baseline false_dismissal 0.286 to 0.714; that swing, not a framework change, is why the debate arm now scores lower false-dismissal while `decision_accuracy` ties at 6/14 |
| Oracle needs private knowledge | Oracle validity | 5/7 should_reject dispositions rest on internal experiments or incidents (`xml-rule-format`, `auto-learn-loop`, `checklist-imperatives`, `downgrade-orchestration-model`, `toon-format`); only `context-fork-dispatch` and `parallel-worktree-cleanup` follow from public facts. With no search, a cold REJECT on the other five is a prior. Opus's prior matched the labels; Fable's did not |
| N=1 | Measurement | `run-ab.sh` sets `RUNS[evaluate-repos]=1`. `over_adoption 0.143 > max(0.05, stdev=0)` fires on one record. In May the same record flipped in 1/3 runs and the mean (0.048) stayed under the floor |

Today's arm-vs-arm differences: 5/14 patterns. The debate helped on 2 should_adopt
(`blinded-judge-pool`, `held-out-grader`: ADOPT vs DEFER) and hurt on 3 should_reject
(two REJECTs softened to DEFER, one flipped to ADOPT). Net accuracy 0. On the four
`look_dismissable` patterns: WITH dismissed 2/4, BASE 3/4.

### 8.3 Same pattern on Opus 4.8

The synthesis DEFER-heaviness and the `checklist-imperatives` over-adoption both appear
in the May records; what changed is the baseline. Both models show the skill mechanism,
so it is the skill. The SKILL.md already codifies "NEVER auto-synthesize the adopt/reject
decision with an LLM"; the harness measures the proxy the skill forbids, and does not
score the advocate/skeptic arguments that the skill actually ships.

Cost 3.0 is the one structural, real ratio among the five.

## 9. The instruments

1. **Answer keys with a shelf life.** `deep-dive/harness/fixture.json` `current-*`
   questions encode the mid-2026 answer as of 2026-05-31. By 2026-09-03 the key was the
   stale answer. Any currency question needs a `key_valid_until` or a per-run key refresh,
   and a stale key should fail the run, not the arm.
2. **Phrase-cue graders are brittle in both directions and arm-biased.** May:
   `wrong_terms` false-failed correct verbose answers (fixed in PROBLEM.md section 6).
   Today: `_REJECTION_CUES` false-failed 4 correct rejections and `expected_terms`
   false-passed 3 answers on an incidental mention. Because the framework arm is 1.7x more
   verbose, cue-list artifacts hit the two arms at different rates.
3. **Paired bootstrap at N=3 is not a significance test.** Three runs give at most 10
   distinct resample means; when the three paired deltas coincide the CI has zero width and
   "excludes zero" trivially. deep-dive today would have been `keep` on artifacts (4.4).
   `ci_verdict` should return BLOCKED when n < 5 or when the deltas have zero spread.
4. **`fix` rules fire on single records.** deep-dive by 0.0013; evaluate-repos on one
   ADOPT at N=1 with an undefined stdev. Both `fix` verdicts today are single-record events.
5. **Precision-over-asserted metrics reward abstention.** gather-*'s primary metric drops
   CONTESTED/UNCHARTED items from the denominator; gather-intel's whole delta today is one
   abstention on the fixture's un-groundable claim.
6. **Ceiling.** True accuracy: deep-dive 180/180, gather-research 180/180, gather-intel
   baseline 45/45 today, triage groups 12/12 today. Rerunning a saturated fixture yields
   BLOCKED forever and reads as "no lift" when it means "no test".
7. **Cost is asserted, not measured.** `COST_RATIO` is a constant in each `run_live.py`;
   receipts and provenance carry no `usage`. In four harnesses both arms make the same
   calls with the same search budget. The only measured differences are system-prompt
   length (2.1-4.0x) and output length (0.83-1.7x).
8. **The framework arms are prompt distillations.** What is measured is whether a
   700-1,700-character summary of a skill's epistemic rules changes a single-call answer.
   It mostly does not, on either model, because the model already applies those rules.
   That is a finding about the rules as prompt text, and it is consistent with the skills
   being redundant for single-question fact checks, but it says nothing about the
   multi-wave, multi-provider, human-in-the-loop procedures the SKILL.md files describe.

## 10. Recommendations and how to verify each with the existing harness

| Skill | Recommendation | Verification (no new API calls unless stated) |
|---|---|---|
| deep-dive | Fix the grader: (a) add `"premise_holds": true/false` to both arms' output schema and score false-premise questions on that field, dropping `_REJECTION_CUES`; (b) give `current-*` questions a `key_valid_until` and fail the run when expired, or drop them; (c) compute `calibration_discrimination` over `fact` questions only, or count LOW-on-rejection as calibrated; (d) make `ci_verdict` BLOCKED at n < 5 or zero-spread deltas. Skill: keep the confidence layer (rule-required, cheap); make the counterfactual conditional on findings with a comparative or causal claim, or require the report to state when no finding is falsifiable by inversion (88/88 COLLAPSES is a boilerplate signature the grader's verbatim-duplicate check cannot see) | Re-grade `runs/transcripts-20260903T205439Z.json` with the patched `grade.py` (PROBLEM.md section 6 did exactly this in May): expect accuracy 1.0/1.0, `fix` gone, verdict BLOCKED or `trim`. Then a harder fixture (questions a searching model gets wrong) before any further claim about calibration |
| gather-intel | Retire the A/B at this fixture; keep the skill as the audit/report format it is (Phase A, the four-section report, user decision point), none of which is measured. If re-measured: replace `three-workers-sweetspot` `grounding_terms` with terms any supporting page contains (or drop the claim), make `verdict_accuracy` primary, and use a fixture where the baseline is below 1.0 | Re-grade both record sets with the oracle fix: expect grounding_precision 1.0/1.0 and delta 0 on both dates, confirming the reported delta was the oracle |
| gather-research | Stop rerunning until a discriminating fixture exists (subtle CONTESTED cases, claims inside the 12-month window). Fix the named rule in `SKILL.md` step 6c and `references/citation-domain-freshness.md`: for a specific named artifact (title, author, venue) that search shows does not exist, allow REFUTED (nonexistent) with the adjacent real work cited, instead of UNCHARTED with no citations. Add label-level accuracy (exact category) as a secondary metric so the taxonomy is graded at all | Re-grade existing transcripts with a label-level metric: today WITH is UNCHARTED 9/9 on fabricated and OUTDATED 6/9 on outdated (`claude-code-no-hooks` REFUTED x3); the binary metric hides both |
| triage | Keep the skill as a report format; the harness cannot inform it. If the harness is kept: delete the worked example from `SYSTEM_WITH` (it leaks a ranking rule that collides with f4), run N >= 10 (2 calls per run, no search: cheap), and state in `SKILL.md` that what was A/B'd is a two-sentence severity prompt, not the constitution | Re-run at N=10 after the prompt edit (about 20 calls); expect the Spearman CI to narrow below 0.03 and the f4/f5 demotion to disappear |
| evaluate-repos | Either retire the decision A/B and keep the skill as the manual advocate/skeptic report the SKILL.md already mandates, or change the measured unit to the arguments (e.g. does the advocate cite a real coverage gap; does the skeptic name a concrete blocker) with a human-label oracle. If the decision A/B stays: N >= 3 in `run-ab.sh`, score should_reject only on the 2/7 patterns with public rationale or give both arms the evidence a human decider would have, and keep the guard (it did remove hard rejects of good patterns on both models) | Re-run at N=3 (about 168 calls, no search); expect the `fix` to revert to the May `backfire` shape or BLOCKED, since the over-adoption record flips in 2/4 runs so far |

Cross-cutting: record token `usage` per call in the runners so `cost_ratio` is measured;
persist the web_search result blocks (or at least URLs surfaced) so retrieval differences
can be classified; and treat `ci_verdict` as advisory below n=5.

## 11. What could not be determined from the records

- Token usage and cost per arm: not recorded anywhere (receipts, provenance, transcripts).
- Retrieval differences: web_search results are not stored, only the model's text blocks;
  whether the arms saw different evidence cannot be established. May `_text` is stripped
  from the committed gather-* samples, so the `taskoutput` edge cannot be split into model
  vs retrieval.
- Whether the skills as shipped (multi-wave, three providers, topic loading, human
  decider) add value: no harness runs them.
- Ground truth for `current-anthropic-model` today was not independently verified here; the
  analysis relies on all six records agreeing and on the model id under test.
- Whether Opus 4.8 would have emitted LOW on false-premise rejections under the same
  instruction (it emitted 0 LOW labels in 45 records); the prompt/grader conflict in 4.2
  only became visible with a model that follows the instruction literally.
- triage arm text was not stored, so the reasoning behind the run1 demotion is inferred
  from the prompt and the finding text, not read.
