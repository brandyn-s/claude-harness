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
these fails the decision rule and starts the bisect.

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
| **P1** completion-evidence rate: share of completion claims carrying evidence | transcript proxy in `bin/lean-core-ab.py` (a claim = an assistant message matching the fixed claim regex; evidence = a code block, a path, a count, or a tool result within three records) | not lower |
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
