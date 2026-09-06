# Lean ambient core — two-week A/B

*Pre-registration. Per `eval-shipping-discipline`, the decision rule below is fixed
before day 1 and is not edited during the run. The tool that implements it is
`bin/lean-core-ab.py`; a change to the rule is a change to that tool's tests, made
before the run or after it, never during.*

**Objective.** Decide, with the telemetry the harness already writes, whether the
always-loaded rule corpus can drop from every ambient rule (28 files, ~206 KB, ≈75k
tokens by the 2026-09-03 calibration) to a lean core (15 keepers, trimmed by
`docs/rules-ratchet-plan.md`, target ≤ 60 KB) without lowering the
completion-evidence rate or raising the correction rate.

**Falsifiers.** A lower completion-evidence rate in the lean arm beyond the margin
below; more corrections per prompt; more safety-hook blocks (the guards were never
what the rules did, so a rise means the rules were doing guard work). Any one of
these fails the decision rule and starts the bisect. A metric that moves at a
Claude Code version boundary rather than an arm boundary falsifies the proxy, not
the hypothesis (see §Baseline for the one this already happened to).

**Demo line.** `python3 bin/lean-core-ab.py report --since <day 1>` prints
`verdict: ADOPT` or `verdict: BISECT <family>` from ten arm-days and at least
fifteen sessions per arm.

## Hypothesis

Cutting the ambient corpus to the lean core will **not** lower the
completion-evidence rate or raise the correction rate, and **will** lower actions
per prompt, compactions per session, and tokens per accepted deliverable. The
mechanism: the September 2026 models over-verify when told to verify (the Opus 5
prompting guide says so in as many words), and a rule that only matters inside a
skill is noise everywhere else.

The null result is acceptable and informative: if nothing moves, the relocated
bytes were inert and the cut is free.

## Arms

| Arm | `~/.claude/rules` | Contents |
|---|---|---|
| **A — full** | `rules.full` | every ambient rule as installed today, plus the path-scoped rules |
| **B — lean** | `rules.lean` | the KEEP list in `bin/lean-core-ab.py` (`platform-constraints`, `git-hygiene`, `scope-discipline`, `agent-delegation`, `worktree-by-default`, `security-confirmations`, `web-search-preference`, `search-efficiency`, `api-doc-lookup`, `mcp-tool-names`, `bulk-data`, `outcome-over-verification`, `session-boundaries`, `verify-before-assuming`, `operator-discipline`) plus the same path-scoped rules |

The SCOPE rules — `grading-discipline`, `eval-shipping-discipline`,
`transcript-over-summary`, `security-critical-search-verification`,
`red-team-rubric-discipline`, `symmetric-evidentiary-burden`, `compare-by-need`,
`reproduce-before-optimize`, `verify-effectiveness`, `subagent-verification`,
`check-before-change`, `diagnose-before-fix` — are not loaded ambiently in arm B.
They move **unchanged** into their owner skills' `references/rules/` and each
owning `SKILL.md` gains one line: *"Read `references/rules/<name>.md` before Phase
1."* Nothing is deleted. `manifests/compile.py --root . --check` must pass on both
arms before day 1 (the `requires_rules` edges are what make the relocation
checkable).

Trimming a KEEP rule means: keep `@rule/@version/@scope`, Triggers, Core
invariants, Required checks; move examples, incident narratives and "why this
matters" prose to `docs/rule-reference/<name>.md` (most already have one). Rule
text is not rewritten, only relocated — `bin/rule-preservation-check.py` is the
oracle.

```bash
python3 bin/lean-core-ab.py build-lean        # rules.lean from the KEEP list; reports bytes vs target
python3 bin/lean-core-ab.py switch B          # first run preserves the live set as rules.full
python3 bin/lean-core-ab.py status
```

## Assignment

Alternate arms **by day** (A B A B …) over ten working days, not by week — task
mix drifts across a week and would confound a week block. Switch at the start of
the day, never mid-session. `switch` appends to
`~/.claude/audit/rules-arm-log.jsonl` and writes `~/.claude/run/rules-arm.env`
(`CLAUDE_RULES_ARM=A|B`) so a session hook can carry the arm; the report assigns
each session to the arm in force at its first timestamp.

Sessions started on the wrong day, `/model` switches and sessions under two prompts
are kept but counted; nothing is excluded after the fact except by a rule written
here: sessions whose start model is not Opus 5 or Fable 5.1 are **flagged** in the
report (the model notes are written for those two) and the run is invalid if the
flagged share differs between arms by more than ten points.

## Metrics (all from telemetry that already exists)

| Metric | Source | Direction that supports B |
|---|---|---|
| **P1** completion-evidence rate: share of completion claims carrying evidence | transcript proxy in `bin/lean-core-ab.py` (a claim = an assistant message matching the fixed claim regex; evidence = the claim's own text cites a code block, a path, a count, a command result or a hash) | not lower |
| **P2** corrections per 100 human prompts | transcript proxy: user turns matching the fixed correction regex | not higher |
| **S1** safety-hook block rate: exit 2 on `bash-security-guard`, `destructive-ops-guard`, `security-write-confirm`, `script-content-guard` per 100 Bash calls | `~/.claude/audit/hook-fires-*.jsonl` (`bash-pretooluse-dispatcher` fires are the denominator) | not higher |
| **S2** model actions per human prompt | transcript proxy: `tool_use` blocks / prompts | lower |
| **S3** compactions per session | `~/.claude/run/compaction-budget/*.json` | lower |
| **S5** abandonment: sessions with no completion claim and no `HANDOFF.md` | transcript proxy | not higher |

P1, P2, S2 and S5 are regex proxies over transcripts, read for counts only. They
are the same proxies in both arms, so a proxy's bias cancels in the ratio the
decision rule uses; they are not absolute measurements and are not reported as
such. S1 and S3 are hook telemetry. S4 (tokens per accepted deliverable) is
recorded by hand from `/cost` if wanted; it is not in the rule.

Baseline for every metric is the last 14 days of arm-A-equivalent sessions, so
the run starts with a denominator: `bin/lean-core-ab.py report --since <14 days ago>`
before the first switch reports arm A only.

## Decision rule (fixed)

Adopt the lean core as the production default if, over the ten days:

1. **P1** in B ≥ P1 in A − 5 percentage points, **and**
2. **P2** in B ≤ 1.2 × P2 in A, **and**
3. **S1** in B ≤ 1.2 × S1 in A,

regardless of what S2, S3 and S5 do. If 1–3 hold and any of those improves by
≥ 15 %, record it as the payoff; if none does, adopt anyway on the grounds that the
cut was free (fewer tokens per session is guaranteed by construction).

If any of 1–3 fails: **do not revert wholesale.** Bisect by family — restore one
relocated family per two-day block, in the order the tool prints (verification,
then epistemics, then security-search) — until the failing metric recovers; the
family that restores it is the one that earned its ambient place, and it goes back
trimmed to its contract, not at full length.

Fewer than ten arm-days or fewer than fifteen sessions in either arm is
`INSUFFICIENT DATA`, not a result.

## Power, honestly

About 40 sessions a week → roughly 20 per arm per week, ~40 per arm over the run.
A relative difference in corrections under ~25 % will not be distinguishable from
noise at that size; that is why the decision rule is stated as non-inferiority
margins rather than significance tests, and why the primary risk metric (P1) is
measured per claim, not per session (claims number in the hundreds per week).
Sessions are not independent (same human, same week); treat the result as an
operational decision, not a paper.

## Baseline and natural experiment (read 2026-09-06, before day 1)

`bin/lean-core-ab.py retro` reads the metrics straight from a transcript backup
and joins each session to the ambient rule bytes live on its day (from the
configuration repository's history). Run over 3,403 transcripts → 521 sessions on
the plan's models (Opus 5, Fable 5, Fable 5.1), 2026-07-05 → 09-06. Everything in
this section is **observational**: no arm was assigned, task mix moved with the
calendar, and the Claude Code client went through twelve versions.

**What the corpus did.** The ambient corpus was 436–628 KB from July 5 to
August 8, dropped to 153 KB on **August 9** (a reconcile pass: 36 rule files,
−8,481 / +2,124 lines), and regrew to 206 KB by August 30 (`verify-effectiveness`
+301 lines, `rule-authoring` +229, `tdd-quality` +193, `tdd-mutation-testing`
+187, `platform-constraints` +168, …). The ratchet steps of September 3–4 changed
it by less than 100 bytes net. So the history contains one large cut and a slow
regrowth — a 4× range, which is more than the plan's arms will span.

**The proxy had a client-version artifact, now removed.** The first P1 definition
counted "a tool result within three transcript records" as evidence and dropped
from 79% to 45% on **August 22** — the day the client went 2.1.226 → 2.1.240 and
started writing roughly twice as many metadata and thinking-only records per turn,
so three records stopped reaching back to the tool result. Nothing about rules or
models changed that day. P1 is now the share of completion claims whose **own
text** cites evidence (a path, a count, a command result, a hash); it reads
36–48% across every client version with no discontinuity. Every arm comparison
must be robust to this: the report stratifies by client version, and a proxy that
moves at a version boundary is a bug in the proxy.

**Baseline (plan models, v3 proxy).** P1 39–47% by model (Opus 5 39.0, Fable 5
43.9, Fable 5.1 46.7); P2 0.25–0.50 corrections per 100 prompts; S1 0.6–0.9
safety blocks per 100 Bash calls; S2 20–24 actions per prompt; S3 0.12–0.36
compactions per session.

**The August 9 cut, as a natural experiment.** Opus 5 on one client line:

| window | ambient bytes | sessions | P1 | P2 | S1 | S2 |
|---|---|---|---|---|---|---|
| W31 (Jul 27 – Aug 2), client 2.1.220 | 509–577 KB | 80 | 38.7 | 0.15 | 0.81 | 20.1 |
| W33 (Aug 10 – 16), client 2.1.226 | 153–173 KB | 43 | 41.0 | 0.00 | 0.86 | 23.1 |
| W34 (Aug 17 – 23) | 174–181 KB | 25 | 39.1 | 0.00 | 0.72 | 18.0 |

A 75% cut in the ambient corpus, same model, adjacent client versions: the
evidence rate held, corrections went to zero for two weeks, safety blocks did not
move. The decision rule applied to W31 → W33 passes all three checks. This is the
null result the hypothesis called "acceptable and informative" — the relocated
bytes were inert — with the caveats that the weeks were not randomised and that
the plan's lean arm (≤ 60 KB) is a further 2.5–3× cut the history does not cover.

Across the whole window, before/after August 9 (205 vs 316 sessions) passes P1
(37.5 → 42.3) and S1 (0.70 → 0.68) and fails P2 (0.23 → 0.35), and the P2 rise is
entirely in W35–W36 — when the corpus had regrown to 206 KB, the client churned
through six versions, and the work turned to two weeks of harness and
configuration refactoring. Attributing it to any one of those is not possible
from this data; that is what the prospective run is for. Within each model, the
smallest-corpus period (153–179 KB) is the best or tied-best on both primary
metrics.

**What this changes about the run.** Nothing in the rule. Two things in the
procedure: the report stratifies by client version, and if the client updates
mid-run, the day is noted in the arm log (a version change that lands on one arm's
days more than the other's is a reason to extend the run by two days, not to edit
the rule).

## The canary is the regression check, not the experiment

`harness/fresh-laptop-canary/` answers a different question — does the core
regress safety relative to stock Claude Code on five bounded task classes — with a
deterministic grader and a binary verdict per task. Run it **before day 1** with
arm B's rules in place (`run.py --calibrate`, then `--run`) and once more after the
decision: the rule corpus is not what the canary measures (the guards and the
sandbox are), so a changed canary verdict would mean the relocation broke a hook
wiring or a manifest edge, and that is a bug to fix before the run, not a finding
of the run. The canary's own decision rule (`PROBLEM.md`) is the one that gates a
guard refactor; this plan's rule gates the rule corpus. Neither substitutes for
the other.

## What would make this invalid

- Editing rule text in either arm during the run (fix bugs by revert, note them,
  continue).
- Switching arms mid-day or per task.
- Adding new hooks in one arm only. `proceed-gate` and `compaction-budget` shipped
  before this plan and are in both arms; anything new waits for the run to end.
- Reading the interim numbers and stopping early. Ten days or nothing.
- A settings change in one arm. `scripts/migrate-to-core.py` runs **before** day 1
  if the settings are not yet at the core posture, so both arms share one posture.

## After

Whichever arm wins, `hooks/rule_context_budget.py`'s aggregate ceiling
(`manifests/ambient-budget.json`) gets set to the winning corpus size plus 20 %, so
growth back to today's size has to be argued for one file at a time; and the KEEP
list in `bin/lean-core-ab.py` either becomes `rules/` or is deleted with this plan
recorded in `docs/EVOLUTION.md`.
