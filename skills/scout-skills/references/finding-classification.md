# Finding Classification (Step 4 detail)

For each technique card that survived Step 3, classify by change type.

## Additive (Low risk) — Just do it

Patterns that ADD to an existing skill without changing its behavior:
- New example or diagram (horizontal-slicing ASCII art)
- New FAIL/PASS code block (wrong→right examples)
- New table (evidence-strength tiers)
- New step that doesn't alter existing steps (scope-detection Step 0)
- New guidance note (durable issue language)

**Action**: Edit the skill, add the pattern, attribute the source in an
inline comment. No user approval needed. No incident-evidence gate.
The change IS the test.

## Structural (Medium risk) — Do it with precedent check

Patterns that change how a skill is organized or add new files:
- New reference file in `references/`
- New frontmatter field (`model:`, `effort:`, `paths:`)
- New companion file (mocking.md, deep-modules.md)
- Rules overview table pointing to rule files

**Action**: Check if we have precedent for the structural pattern in any
existing skill. If yes, apply it. If no, flag it in the report for user
review. One precedent is sufficient — not every skill needs to use it.

## Domain Insight (Low-Medium risk) — Substantive technique, non-SKILL.md destination

A substantive technique, heuristic, framework, or methodology that the
community skill encodes — adopted into a rule, topic file, or memory
entry rather than a SKILL.md. **Drop the "no overlap" gate for this
bucket.** A partial overlap between the community technique and an
existing rule/topic does not disqualify adoption; it triggers
*incremental refinement* of the existing destination rather than
rejection.

Examples (from techniques the 2026-05-17 run should have caught):
- "per-interaction STRIDE threat-analysis methodology" → addition to
  `rules/security-critical-search-verification.md` or new topic file
  `knowledge-base/topics/stride-methodology.md`
- "control-coverage scoring with defense-in-depth criteria" → new section
  in `skills/threat-model/references/` OR addition to
  `agent-memory/topics/security.md`
- "postmortem proximate-vs-contributing-cause distinction" → addition to
  `rules/diagnose-before-fix.md` or new topic file
  `knowledge-base/topics/postmortem-methodology.md`

**Action**: Produce the concrete diff at the chosen destination. Attribute
the source in the destination file. No user approval needed for Domain
Insight adoptions to rules/topics/memory — same risk tier as Additive.
If multiple destinations apply, choose the one with the broadest reach
(rule > topic > skill reference > memory).

**Bias correction:** the 2026-05-17 roundtable identified Domain Insight
as a critical bucket the skill lacked. Without it, techniques with
genuine substance kept getting routed into Additive (SKILL.md prose) by
default, because every existing bucket targeted file-shape rather than
technique-substance.

### Sub-classification: Domain Insight (Harness)

When the technique has an **executable atom** (algorithm with concrete
inputs/outputs, harness template, eval script) alongside the
methodology, route as **Domain Insight (Harness)** — produces BOTH the
topic prose AND a runnable script.

| Domain Insight (prose) | Domain Insight (Harness) |
|---|---|
| Methodology documented in topic file | Methodology documented + runnable script |
| Single destination: `knowledge-base/topics/<name>.md` | Two destinations: topic file + script |
| Examples: STRIDE methodology, postmortem proximate-vs-contributing | Examples: three-stream validation harness, fuzzing harness template, chaos experiment script |

**Script destinations:**
- **Skill-scoped** (used by one skill only):
  `~/.claude/skills/<skill>/references/<name>.py` or `<skill>/scripts/<name>.py`
- **Cross-skill** (used by multiple skills or as standalone eval):
  `~/.claude/evals/<methodology>/<name>.py`
- **One-shot template** (user copies and adapts): include as fenced
  code block in the topic file with `<!-- template -->` marker

**Mandatory: both artifacts in the same PR.** The topic prose captures
the WHY/WHEN; the script captures the HOW. Splitting them across PRs
loses the cross-reference.

**Examples from this architecture**:
- Three-stream validation methodology → topic prose at
  `engineering-assessment-methodology.md` + `verify_skip.py` and
  `produce_card.py` in `skills/scout-skills/scripts/`
- Coverage-guided fuzzing → topic prose at `coverage-guided-fuzzing.md`
  + (planned) cargo-fuzz template at `evals/fuzzing/`

See `routing-destinations.md` Harness section for the full
procedure and examples.

## Behavioral (High risk) — Flag for user

Patterns that would change execution behavior:
- Different model routing (`model: sonnet` on a skill that currently uses Opus)
- Different workflow (replacing sequential with parallel, changing phase order)
- New enforcement (hooks, gates, blocks)
- Removing or replacing existing logic

**Action**: Present to user with:
- What the community skill does differently
- What our skill currently does
- The specific behavioral delta
- Your recommendation (adopt/defer/investigate)

Apply `compare-by-need.md` Gates 1-4 only for behavioral changes.

## Hook (High risk, distinct lifecycle from Behavioral)

A pattern that enforces a constraint (block / fix / warn) on tool use
**across all sessions**, not within one skill's invocation. Examples:
"block Bash commands matching `pip install --upgrade all-outdated`",
"PostToolUse fix to normalize CRLF on Edit", "warn when settings.json
write removes a required field". These are fundamentally different from
Behavioral changes — see `routing-destinations.md` for the
full Hook-vs-Behavioral axis table.

**Why a separate bucket:**

| Axis | Behavioral | Hook |
|---|---|---|
| Trigger | Specific skill invoked | Tool call matched by name |
| Scope | One skill | All sessions |
| Test requirement | Run the skill, observe new behavior | Replay against historical transcript, measure block rate |
| Risk profile | Misbehavior on next skill invocation | DoS across all sessions if matcher too broad |
| Rollback | Revert SKILL.md | Restore settings.json AND remove hook script |

**Action**: STAGE the spec — never install inline. Mirrors /distill
T0-hook discipline:

1. Write `hooks/staged/<name>.spec.md` with: hook event (PreToolUse /
   PostToolUse), matcher (tool name pattern), behavior (block vs fix),
   enforcement logic pseudocode, concrete test case (known-bad input
   → expected block/fix).
2. **Replay against ~30 days of historical transcripts** before
   recommending activation. Target <10% block rate; higher means the
   matcher is too broad and would DoS routine work.
3. Report: staged spec path, event, matcher, proposed behavior,
   replay block/allow stats.
4. Do NOT modify `settings.json` or write the hook script inline.
   Installation happens via `/ship-hook` in a separate session.

The staging discipline separates "decide what to enforce" from "modify
live infrastructure." Hook installation during /scout-skills risks
partial install (script exists but settings.json not updated, or vice
versa), which leaves broken enforcement.

## Novel capability — Propose new skill

A community skill that solves a problem we don't address at all — no
existing skill covers it, even differently. This is NOT a pattern to add
to an existing skill; it's a whole new capability.

Signs:
- Step 3 search for a corresponding skill returns nothing
- The capability doesn't fit as a step in any existing skill
- It addresses a workflow or domain we currently handle ad-hoc

**Action**: Present to user with:
- What the community skill does (1-2 sentences)
- What we currently do instead (often: nothing, or ad-hoc)
- Estimated size (would our version be <50 lines or >100 lines?)
- Your recommendation: build it now, or note it for a future session

Don't build the skill inline during a scout-skills run — that's scope
creep. The scout discovers; a separate session builds. Exception: if the
user says "build it," proceed.

(Added after ubiquitous-language discovery, 2026-04-06 — the skill had
no path for novel capabilities and could only flag them as "structural
for user review," which undersells genuinely new ideas.)
