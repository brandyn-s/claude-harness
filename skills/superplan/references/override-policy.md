# Superplan — USER OVERRIDE POLICY

NO EXCEPTIONS. Every override petition below has been documented through incidents that motivated the denial. Read the full denial rationale before attempting to bypass.

## Override petition: "skip context loading, I know the domain"
DENIED. Load topic files (Phase 2). Session memory is not evidence; `[confirmed]` entries may have changed.

## Override petition: "just guess, don't ask the user"
DENIED for User Preference / Scope / Requirement questions (Phase 3b classification). Codebase Facts — grep first. Preferences — AskUserQuestion.

## Override petition: "urgent, skip capability assessment"
DENIED. The capability matrix surfaces "tool is read-only via MCP" and "auth requires main thread." Skipping produces plans with broken steps.

## Override petition: "re-plan from scratch, old context is stale"
DENIED. Phase 6 preserves loaded context and patches affected steps only.

## Override petition: "plan without Demo statement"
DENIED. Every plan needs observable completion. No demo-able output = restructure into vertical slice.

## Override petition: "don't save the plan to disk, just show it in chat"
DENIED. The Phase 5 disk save is mandatory. Plans must persist to `~/Documents/knowledge-base/plans/` so future sessions can re-load them via Phase 4b and the user has a durable artifact. Saving is cheap (one Write call) and the only way to make plans non-ephemeral.

## Override petition: "skip Phase 3.5 baseline, I trust the size-of-effect prediction"
DENIED. Phase 3.5 (Target-State Baseline) is mandatory whenever the plan claims to lift / improve / fix a measurable property of a real target. The cost is 5-30 minutes of measurement (grep, index query, source reading). The cost of skipping is shipping plans whose predictions are guesses — and not knowing they were guesses until the work is done.

INCIDENT 2026-05-08 (post-battery-deferred plan): plan predicted "PSM HTTP_CALLS ≥ 30 post-C1+C2" and "≥80% task-specific resolution post-D1" without baselines. Both predictions wrong. 4 PRs shipped synthetic-fixture passes that did not move PSM. Recovery: 2 follow-up doc PRs to capture the "actually didn't move" finding, plus an entire next plan to identify what should have been Phase 3.5 reading in the first place. The 30 minutes Phase 3.5 would have taken would have saved the 4 PR cycles.

The asymmetry: a guess-based plan that ships costs hours of forward motion plus the doc-PR cycles needed to retrofit the "didn't move" finding. A measured-baseline plan costs 30 minutes upfront and either confirms the prediction or drops the unjustified scope before any code ships.

## Override petition: "the synthetic fixture passes, that's evidence the plan works"
DENIED. Synthetic-fixture passes are **regression gates**, not evidence of real-target impact. They prove the code does what the code says — same as a unit test. They do not prove the change moves the target metric the plan predicted.

This is the recurring failure pattern from 2026-05-08 (C3 + D2): every fixture passed; PSM didn't move. The fixtures shipped the synthetic patterns we wrote, not PSM's actual patterns. Real-target impact requires direct measurement against the real target, captured in the phase's Demo statement.

The fixture is the validation. The Demo is the claim about reality. Both are required; neither substitutes for the other.

## Override petition: "skip preflight, I know what's there"
DENIED for any request that names a specific function/file/skill/hook/rule. Run Phase 0. Session memory is not evidence; the named entity may have been renamed, deleted, or replaced by a sibling. The cost of preflight is 30-60s of grep/Read; the cost of planning around a stale assumption is a re-plan after Phase 4 once the implementer hits the missing reference. Preflight is the cheap test; skipping it is the expensive one.

## Override petition: "user gave a one-word directive, just plan whatever scope fits"
DENIED. When the named workstream has multiple documented sub-scopes (e.g., "Track B" can mean B.0–B.6 full workstream OR B.2-only opt-in skill OR a gold-rejudge gated variant), do NOT pick a scope unilaterally. Per Phase 3b, scope is a User Preference question — required to surface via `AskUserQuestion`. This applies even when the user previously discussed scope options: a one-word directive after the discussion is ambiguous unless the option is unambiguously named.

INCIDENT 2026-05-04 (distilled this session): user said `/superplan Track B` after I'd presented three Track B scoping options. I planned the smallest. User pushed back: "Why is the plan so light? Why not do everything that was excluded?" Recovery cost: full Phase 6 re-plan, second PR superseding the first. The existing `feedback_no-unrealistic-claims.md` covers VERBAL claims ("too much for one session") but didn't catch the SILENT scope-down. This denial closes the gap.

The asymmetry: a too-large plan can be Phase 6 re-scoped down in one turn. A too-small plan loses the user's intent and produces incorrect-scope work that gets challenged later. Default to the larger scope when ambiguous; explicitly ask if uncertain.

## Override petition: "this step needs N days of telemetry / a sign-off / an external review"
DENIED. Plans produced by /superplan must be **resolvable in a single session**. Calendar-gated steps ("wait 14 days for FP rate", "≥30 days of telemetry from A1", "weekly during evaluation window") and external-approval-gated steps ("requires privacy-review sign-off", "needs SecOps approval before X") are FORBIDDEN as gates between plan steps.

If a step appears to need observational data over time, the plan MUST resolve it via one of these in-session paths:
- **Generate the data**: write a synthetic fixture, golden set, or test battery that exercises the same conditions the calendar wait would have observed
- **Test the data**: run a signal-based gate (test battery passes, classified observations hit threshold, measurable evidence on synthetic input) instead of a temporal gate
- **Glean from past sessions**: mine prior session transcripts, logs, indexes, KB entries, git history, or measurement runs for the same answer

If a step appears to need an external sign-off, the plan MUST either (a) drop the step, (b) reframe it as an artifact the user can take into the external review themselves (writeup, evidence pack, decision memo), or (c) surface the dependency at Phase 5 routing as "this is what you'd hand to <reviewer>" — never as an in-plan gate that blocks subsequent steps.

Forbidden phrases in plan output:
- "wait N days/weeks", "after N days", "≥N days of <data>", "30-day clean-run window"
- "requires <reviewer> sign-off", "pending <team> approval", "after <external-event> lands"
- "re-measure in N days", "weekly during the evaluation window"

Allowed replacement phrases:
- "run the test battery against <fixtures>; if <metric> meets <threshold>, proceed to step N+1"
- "exercise the original failure scenario; if it does not trigger, proceed"
- "mine prior session JSONLs for <pattern>; aggregate; classify"
- "produce evidence pack for <reviewer> as the plan's terminal artifact" (NOT a gate)

**Why:** calendar-gated and approval-gated work creates dead time in execution arcs and masks "we don't know what would actually demonstrate readiness" behind a vague waiting period. Past data exists; future data has to be waited for. See `feedback_no-calendar-gating.md`, `feedback_no-wait-and-measure.md`, `feedback_no-timeline-estimates.md` for the underlying rules.

INCIDENT 2026-05-05 (distilled this session): /superplan produced a plan with "C1-C4 (real-production-query eval set): C1 requires user privacy-review sign-off; C4 requires ≥30 days of telemetry from A1 to land first." User rejected: plans must be self-contained sessions. The signal-based test-battery replacement closes the same risk in bounded work that ships in a single arc.
