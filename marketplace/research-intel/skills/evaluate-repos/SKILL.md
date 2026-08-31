---
name: evaluate-repos
description: "Evaluate external patterns against our architecture with advocate/skeptic agent pairs."
when_to_use: 'Use when evaluating external patterns against our architecture. Trigger phrases: "evaluate repos", "assess these patterns", "evaluate findings". Do NOT use for discovery (use /gather-repos) or community intel (use /gather-intel). Dispatches advocate/skeptic agent pairs for debiased evaluation — the advocate argues FOR adoption, the skeptic argues AGAINST. Both arguments presented to user.'
argument-hint: "[inventory source: repo name, finding description, or 'from last gather-repos']"
allowed-tools: Read Write Edit Grep Glob Agent Bash(git log:*, git diff:*) AskUserQuestion
user-invocable: true
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# Evaluate Repos — Advocate/Skeptic Debiased Assessment

> Designed to fix the self-evaluation bias documented across 22 runs of
> /gather-repos: a single agent evaluating its own architecture dismisses
> skill findings via label-matching while thoroughly evaluating hooks.
> Research basis: Arize self-evaluation bias study, AAAI DReaMAD bias
> reinforcement paper, Anthropic multi-agent code review pattern.

## The Problem This Solves

A single agent that built an architecture cannot objectively evaluate
alternatives to it. The bias manifests as:
- Hook findings evaluated thoroughly (unfamiliar = gaps visible)
- Skill findings label-matched and dismissed (familiar = "we have that")
- Quality-3 ratings used to SKIP instead of UPGRADE

The fix: two agents with opposite mandates. Neither needs to be unbiased.

---

## Scope guard

Before proceeding, verify the request is in-scope. If the user wants to:
- **Discover repos** without a specific target to evaluate → redirect to `/gather-repos`
- **Community intelligence** (patterns, tips, blog posts) → redirect to `/gather-intel`
- **Developer profiling** → redirect to `/absorb`

Evaluate-repos requires either structured inventories from /gather-repos, an ad-hoc pattern description, or "from last gather-repos". If none of these apply, redirect appropriately.

---

## Input

Either:
- Structured inventories from /gather-repos (repo name + per-bucket content)
- Ad-hoc: "evaluate [external pattern] against [our skill/hook/rule]"
- "from last gather-repos" — re-evaluate findings from the most recent run

## Step 0: Load Context (handoff + architecture topic)

Before Step 1, load the two context surfaces declared in `manifest.yaml`:

1. **Architecture topic** (`requires_topics: architecture.md`): Read
   `~/.claude/agent-memory/topics/architecture.md` — provides the canonical
   description of our skill/hook/rule architecture that the skeptic will
   compare against. If missing, log and continue without it (do not abort).
2. **gather-repos handoff** (`requires_skills: gather-repos`): If source is
   "from last gather-repos", read the `## Handoff to /evaluate-repos`
   section of `~/.claude/assessed-repos.md` (the file `/gather-repos`
   Step 4 overwrites each run). Parse the `Inventoried this run:` block
   — one `owner/repo` line per candidate, with bucket counts, a
   `Distinctive:` seed line, and a `Files read:` list. Use the
   `Distinctive:` line as the seed input to the advocate/skeptic agents
   and the `Files read:` list to avoid re-reading paths the inventory
   already covered. If the section is missing or `Inventoried this run: (none)`
   appears, prompt the user for a repo URL or ad-hoc pattern instead of
   proceeding. If source is an ad-hoc pattern, skip this load.

This step makes the manifest dependencies explicit in the procedure.

## Step 1: Identify Evaluation Pairs

For each candidate finding (from inventories or user input):

1. **Their approach**: Extract the external pattern with enough detail for
   an agent to understand it (methodology steps, key features, how it works)
2. **Our coverage surface**: Identify ALL files in our architecture that
   address the same problem space. Coverage is often distributed — a hook +
   a rule + a skill's references/ folder may all contribute. List candidates:
   - Primary file (most directly comparable)
   - Supporting files (rules, hooks, references that extend coverage)
   - Prior decisions: grep `assessed-repos.md` for the pattern name or repo
   Provide FULL PATHS so agents can Read them.
3. **Justify the match**: State in one line why this set of files is the
   right comparison. If the match is ambiguous, list alternatives and pick
   the strongest — a wrong comparison poisons both agents' arguments.

If no obvious coverage exists at all, note a coverage gap in the delta
table with HIGH magnitude — do not assign an AI quality score, and do
not skip the advocate/skeptic. The user decides whether the gap is
worth filling; the skill's job is to surface it. (Quality-number
labels and SKIP/UPGRADE verdicts are explicitly forbidden by the
Rules section below.)

## Step 1.5: Delta-Finder

Before dispatching advocate/skeptic pairs, dispatch a single **Delta-Finder
agent** to do structural comparison of ALL inventoried patterns against
our architecture. This replaces manual cherry-picking of findings.

**Agent prompt**:

```
You are the DELTA-FINDER. For each pattern in the inventory below,
identify the approach delta against our architecture.

INVENTORY: [all per-bucket findings from gather-repos]
OUR ARCHITECTURE FILES: [<repo-root>/ARCHITECTURE.md + relevant bucket dirs]
(resolve <repo-root> at dispatch time via `git rev-parse --show-toplevel`
from any directory inside the clone, or pass the absolute clone path
explicitly. On hosts where the repo is deployed at `~/.claude/`, the
repo root and source root coincide. assessed-repos.md is at
<repo-root>/assessed-repos.md.)

For each inventoried pattern:
1. Identify the closest equivalent in our architecture (file path)
2. Read BOTH files
3. Describe the approach delta in 1-2 sentences (what their approach
   does that ours does not — methodology, modes, gates, not labels)
4. Rate delta magnitude: HIGH (no equivalent or major methodology gap),
   MEDIUM (equivalent exists but theirs is structurally richer),
   LOW (cosmetic or equivalent coverage)
5. Classify implementation type: hook / skill / rule / config
6. Estimate target file and LOC change

Output format (one row per pattern; the `Delta summary` column is the
literal string `<MAGNITUDE>: <one-sentence delta>` — e.g.,
`HIGH: no equivalent staged-promotion gate; ours promotes on first match`):

| Pattern | Type | Target file | Est. LOC | Delta summary |
```

**Output**: A ranked table of ALL patterns sorted by delta magnitude
(HIGH first, parsed from the `Delta summary` prefix). This table feeds
Step 2 (top 3 go to advocate/skeptic) and Step 3 (remaining patterns
listed with metadata but not evaluated). The column shape is identical
to the Step 3 compact table so the pass-through is literal — no
transformation step.

## Step 2: Dispatch Advocate/Skeptic Pairs

**Scope rule**: Dispatch advocate/skeptic pairs ONLY for the **top 3
findings** from the delta-finder (Step 1.5), ranked by approach delta
magnitude. Remaining findings from the delta-finder table are listed
in Step 3 with their type, target file, and estimated LOC but do NOT
receive advocate/skeptic evaluation. This caps agent cost at 6 agents
per run (3 findings x 2 agents) instead of unbounded.

If fewer than 3 findings have HIGH or MEDIUM delta magnitude, evaluate
only those — do not pad with LOW-delta findings.

For each evaluation pair, dispatch 2 **foreground** Agent calls
(default model — Opus has the reasoning depth for architectural arguments):

### Advocate Agent

```
You are the ADVOCATE. Make the strongest possible case for adopting
this external pattern into our architecture.

EXTERNAL APPROACH: [their methodology steps, key features]
OUR FILES TO READ: [primary path + supporting paths]
PRIOR DECISIONS: [any relevant entries from assessed-repos.md, or "none"]

HARD CONSTRAINTS (apply to your output, not negotiable):
- Read EVERY file in "OUR FILES TO READ" before arguing. List the files
  you read at the top of your response as "Files read: <comma-separated
  paths>". If you cannot read a listed file, say so explicitly — do not
  argue from primary file alone or from memory.
- Cite a `path:section` (or path:line) anchor for every claim about our
  coverage. No anchor = the claim is invalid.
- Do NOT emit a quality number, score, rating, "Quality: N", "SKIP",
  "UPGRADE", or any numeric verdict. These are forbidden tokens in your
  response. Argue capability deltas in prose only.
- Do NOT recommend skipping the finding. The user, not you, decides
  adoption.

Then argue FOR adoption:
1. What specific capabilities does their approach have that ours lacks?
   (cite which of our files you checked and what's missing)
2. What failure modes would this prevent?
3. What would improve if we adopted this?
4. Where specifically would it integrate? (which file, which step)
5. What is the MINIMUM VIABLE change? (selective clone > full adoption
   — identify the smallest delta that captures the value)

Be concrete. Cite what you read. No vague claims.
```

### Skeptic Agent

```
You are the SKEPTIC. Make the strongest possible case that our current
architecture already handles this adequately.

EXTERNAL APPROACH: [their methodology steps, key features]
OUR FILES TO READ: [primary path + supporting paths]
PRIOR DECISIONS: [any relevant entries from assessed-repos.md, or "none"]

HARD CONSTRAINTS (apply to your output, not negotiable):
- Read EVERY file in "OUR FILES TO READ" before arguing. List the files
  you read at the top of your response as "Files read: <comma-separated
  paths>". If you cannot read a listed file, say so explicitly — do not
  argue from primary file alone or from memory.
- Cite a `path:section` (or path:line) anchor for every coverage claim.
  No anchor = the claim is invalid.
- Do NOT emit a quality number, score, rating, "Quality: N", "SKIP",
  "UPGRADE", or any numeric verdict. These are forbidden tokens in your
  response. Argue coverage in prose only.
- Do NOT recommend skipping the finding. The user, not you, decides
  whether your case is dispositive.

Then argue AGAINST adoption:
1. What in our files already covers this? (cite specific sections from
   EACH file you read — coverage is often distributed across multiple files)
2. What would the adoption cost be? (context budget, maintenance, complexity)
3. What could go wrong? (false positives, friction, conflicts)
4. Is the improvement marginal or substantial?

Be concrete. Cite what you read. No vague dismissals.
```

**Parallel**: Dispatch advocate and skeptic simultaneously for each finding.
**Batch**: Evaluate up to 3 findings in parallel (6 agents).

### Post-dispatch invariant check

After both agents return, before going to Step 3, verify each agent
response satisfies the hard constraints:

1. Response opens with a `Files read:` line that lists EVERY path from
   `OUR FILES TO READ`. If any listed path is absent, re-dispatch that
   agent with the message: "You did not list <path> in Files read. Read
   it and rewrite your argument."
2. Response contains zero of these forbidden tokens (case-insensitive):
   `Quality:`, `SKIP`, `UPGRADE`, `Score:`, `Rating:`, numeric ratings
   like `1/5`, `2/5`, ..., `5/5`. If present, re-dispatch with: "Remove
   the forbidden verdict token; argue in prose only."
3. Every claim about our coverage references a `path:section` anchor.
   If a claim has no anchor, re-dispatch with: "Add file:section
   anchors to each claim."

These checks are deterministic and live in the dispatching agent's
control flow — they make the Rules-section invariants enforceable in
the loop rather than just asserted in prose.

## Architecture Review Template

For deep assessments (when a single repo warrants comprehensive understanding
rather than pattern-by-pattern comparison), load
`references/architecture-review-template.md`. It provides a Staff Engineer
Guide format: executive summary, core insight, decision log with alternatives,
dependency rationale, tech debt, security model, and testing strategy.

Use the template when:
- A repo is high-trust (8+) and has 5+ skills worth evaluating as a system
- The user asks "give me a deep understanding of this repo"
- You need to reconstruct WHY a repo made its design choices, not just WHAT it did
(Pattern source: microsoft/skills wiki-onboarding — Context7 registry 2026-04-06)

## Step 3: Present Both Cases

For each finding, present side by side:

```
### Finding: [name]

**External**: [1-sentence description]
**Our coverage**: [primary file + supporting files checked]
**Match justification**: [why these files are the right comparison]
**Type**: [hook / skill / rule / config]
**Target file**: [path to file that would change]
**Estimated LOC**: [number]

| Advocate (case FOR) | Skeptic (case AGAINST) |
|--------------------|-----------------------|
| [condensed argument] | [condensed argument] |

**Advocate's minimum viable change**: [smallest delta that captures value]
**Skeptic's cost concern**: [what it costs]
```

For findings that did NOT receive advocate/skeptic evaluation (outside
the top 3 from delta-finder), present in a compact table:

```
| Pattern | Type | Target file | Est. LOC | Delta summary |
|---------|------|-------------|----------|---------------|
```

The user can request full advocate/skeptic evaluation for any compact-
listed finding by name.

Do NOT add your own judgment. Do NOT rate quality. Do NOT recommend
SKIP or UPGRADE. Present both cases and ask the user.

## Step 3.5: Red Team (post-presentation annotation pass)

A red-team annotation pass on each finding. Execution order: after
Step 3 (Present Both Cases) and before Step 4 (User Decides), as a
prep-the-user pass. Document order matches execution order. (Earlier
drafts framed this as a "pre-filter before presenting" pass; that
framing conflicted with the actual document sequence and has been
removed.)

For each finding that received advocate/skeptic arguments:

1. **Does the skeptic kill this?** If the skeptic's argument is
   unanswerable (our coverage is demonstrably equal or superior with
   cited evidence), tag the finding `[skeptic-wins]` inline as
   informative metadata. **Do not reorder.**
2. **Is the MVP worth the cost?** Compare the advocate's minimum viable
   change against the skeptic's cost concern. If LOC > 100 and the
   delta is MEDIUM or lower, tag `[high-cost-low-delta]` inline. **Do
   not reorder.**
3. **Implementation type**: Confirm or correct the type from delta-finder
   (hook / skill / rule / config). This determines where the change lands.

Red team does NOT remove or reorder findings — it annotates them.
**Findings remain in delta-magnitude order (highest first)** so the
user sees the highest-impact items regardless of skeptic verdict. The
annotations are informative metadata only; the user's eye should land
on the largest delta first, then decide whether the skeptic's case
overrides it. Reordering biased the review by hiding strong-delta
findings underneath skeptic-blessed ones — a violation of the "user
makes all decisions" rule below.

**Example output** (annotations inline, order preserved):

```
### Finding: aggregate-metric-plateau-detector  [skeptic-wins]
**External**: ...
Delta magnitude: HIGH
| Advocate | Skeptic |
| ...      | ...     |

### Finding: cross-bucket-orchestrator
**External**: ...
Delta magnitude: HIGH
| Advocate | Skeptic |
| ...      | ...     |

### Finding: prompt-versioning-store  [high-cost-low-delta]
**External**: ...
Delta magnitude: MEDIUM
| Advocate | Skeptic |
| ...      | ...     |
```

The first finding is presented first because its delta is highest, even
though the skeptic kills it. The user — not the skill — decides whether
the skeptic verdict is dispositive.

## Step 4: User Decides

Ask: "Which findings do you want to implement? For each, I'll classify
delivery (new artifact vs extend existing vs memory vs drop)."

The user picks. Then apply delivery classification.

**Over-dismissal guard (present this framing to the user):** DEFER is not a safe
default. For each high-delta should-adopt-looking finding, state whether the skeptic
named a CONCRETE blocker (cited redundancy / specific cost / specific conflict) or
merely argued the general "we might already cover this." Absent a named blocker, flag
"no concrete blocker — advocate case stands" so the user does not reflexively defer.
(Measured: an unguarded LLM auto-synthesis over-hedged to DEFER on ~85% of should-adopt
patterns — `harness/PROBLEM.md` §5. The guard is what keeps a decider — human or, in any
future automation, a synthesizer — from manufacturing dismissal.)

## Step 5: Validate Before Implementing

For each adoption the user approved, define a validation test BEFORE
implementing:

- **Hook adoption**: What historical command or scenario should it catch?
  Run against 1 recent session transcript to confirm it fires usefully.
- **Skill pattern adoption**: What workflow step changes? Describe the
  before/after and how you'll confirm the new step works.
- **Rule adoption**: What past incident would this have prevented?
  Cite the specific session or commit.

If you can't define a concrete validation, flag it: "No validation test
identified — implementing on user judgment alone."

Then implement.

---

## Rules

- **No quality numbers.** The advocate/skeptic arguments replace the 1-5 scale.
- **No SKIP verdicts from the AI.** Only the user can decide to skip.
- **Both agents must READ all listed files** — not argue from memory or primary file alone.
- **Advocate and skeptic get IDENTICAL inputs.** No priming one side.
- **Present ALL findings**, including ones where the skeptic is strong.
- **Step 2's post-dispatch invariant checks are MANDATORY** before accepting agent output and proceeding to Step 3 (Files-read manifest, forbidden-verdict tokens, file:section anchors). Re-dispatch on any failure.
- **NEVER auto-synthesize the adopt/reject decision with an LLM.** The human is the decider (Step 4). Live-arm measurement (`harness/PROBLEM.md` §5): an LLM that auto-synthesizes the advocate+skeptic into a verdict OVER-HEDGES to DEFER — false_dismissal 0.857 vs a decisive single self-eval's 0.286 — manufacturing the exact dismissal bias this skill exists to fight. Present both cases; the user decides.
- **A skeptic case existing is NOT a blocker.** The skeptic is REQUIRED to argue against, so a case always exists. DEFER/REJECT only on a NAMED concrete blocker (a cited redundancy, a specific unacceptable cost, or a specific conflict). Deferring a high-delta should-adopt pattern merely because "both sides have a case" IS a false dismissal — the failure mode this skill fights.

## Measured Efficacy (live arm)

**Verdict: `fix` — measured 2026-05-31, N=3, `claude-opus-4-8`, n=14; over-dismissal guard added + re-measured.**
The de-bias claim was A/B'd: advocate/skeptic vs a single self-eval pass over 14 patterns with known
hindsight dispositions (incl. real wrongly-dismissed-then-adopted cases). **Verified-real result:**
with an LLM SYNTHESIS standing in for the decider, the advocate/skeptic harness **BACKFIRED** —
false_dismissal 0.857 vs single-pass 0.286 (the mandatory skeptic case drove the synthesizer to
over-hedge/DEFER good patterns). **The fix** — an over-dismissal guard ("a skeptic case existing is
not a blocker; defer only on a NAMED blocker"), added to both the human-presentation and the
synthesis arm — HALVED the backfire (false_dismissal 0.857→0.524; hard-rejects of good patterns → 0)
but did NOT rescue it: the guarded synthesizer still over-hedges (0.524 > 0.286). **Critical validity
caveat:** the REAL skill keeps the **human** as decider; this harness measured an *auto-synthesis
proxy*. The post-guard result empirically grounds the design — even a guarded synthesizer over-hedges
— so the codified conclusion is "**never auto-synthesize the decision with an LLM; keep the human in
the loop**" (now a Rule). The guard still ships (it halves over-dismissal + protects Step 4). 0/84
decisions were parse-fallbacks (real, not instrument). Harness + CI gate:
`skills/evaluate-repos/harness/`, `tests/test_evaluate_repos_efficacy.py`; full arc in
`harness/PROBLEM.md` §5-6.

## Success Criteria

- [ ] Top-3 delta-finder findings (by magnitude) have both advocate and skeptic arguments
- [ ] Remaining findings listed compactly with type, target file, and est. LOC
- [ ] Both agents read ALL listed files (cited in output, not just primary)
- [ ] Both agents checked assessed-repos.md for prior decisions
- [ ] Architecture context loaded from `~/.claude/agent-memory/topics/architecture.md` (manifest requires_topics)
- [ ] Coverage surface justified for each finding (why these files?)
- [ ] Advocate proposes minimum viable change, not just "adopt it"
- [ ] Skeptic articulates cost concern (context/maintenance/complexity), not just "we already have it"
- [ ] No quality numbers or SKIP/UPGRADE verdicts
- [ ] User makes all adoption decisions
- [ ] Validation test defined for each approved adoption before implementing
- [ ] If invoked from `/gather-repos` (manifest requires_skills), Step 0 reads the `## Handoff to /evaluate-repos` section of `~/.claude/assessed-repos.md` before Step 1
## Examples

**Example 1: Post-gather evaluation**
User says: "/evaluate-repos" after running `/gather-repos`
Actions: Read inventory files from last gather-repos run, identify unique patterns, dispatch advocate/skeptic pairs for each, present both arguments side by side.
Result: Balanced evaluation of each pattern with adoption recommendation and validation test plan.

**Example 2: Ad-hoc pattern evaluation**
User says: "/evaluate-repos wshobson/agents team-composition-patterns"
Actions: Inventory the specific repo/pattern, read our architecture files that cover the same space, dispatch advocate (argues FOR adoption) and skeptic (argues AGAINST), present side by side.
Result: Evidence-based recommendation with concrete delta — what this adds that we don't already have.
