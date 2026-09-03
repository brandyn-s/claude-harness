---
name: absorb
description: "Study how a builder works — repos, commits, PRs, reviews — to extract practices worth adopting into the architecture."
when_to_use: "Use when studying how a builder works to extract what's better than the team's current practices and integrate improvements into the architecture. Trigger phrases: \"absorb\", \"absorb this builder\", \"study this engineer\", \"learn from [user]\". Invoked as /absorb [github-username]. Core evidence is repos, commits, PRs, code reviews, and issue triage — not interviews. Applies compare-by-need to filter recommendations down to genuine gaps with documented friction. Do NOT use for repo evaluation (/evaluate-repos), community intel (/gather-intel), or tool comparison (/deep-dive)."
argument-hint: "[github-username]  (e.g., \"jdoe\" or \"mitchellh\")"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Agent AskUserQuestion Bash Edit Glob Grep Read Write mcp__exa__* mcp__memory-search__*
---

# absorb

Study how a builder works. Extract what's better than what you do. Integrate it.

## Overview

Takes a GitHub username as input. Produces architecture improvements as output. The developer
is the input, not the deliverable — the deliverable is concrete changes to your rules, hooks,
routing, and workflow grounded in evidence from their code practices.

The skill follows five phases: Surface → Evidence → Synthesize → Compare → Integrate. Each
phase gates the next. No phase is skippable.

**N=1 warning:** This is fundamentally a single-developer analysis. Every pattern extracted
reflects one person's context (team size, role, repo type, language). Patterns that work for
a solo Rust systems programmer may not transfer to a Python-scripting architecture operator.
The Phase 4 gates exist to catch this, but keep the N=1 nature in mind throughout — especially
when a pattern feels compelling but lacks friction evidence in your own workflow.

**Evidence limitations:** The profile is a sample of artifacts, not a complete picture, and
recent commits may reflect AI-assisted output rather than the developer's natural style. Full
blind-spot list + AI-attribution tells: [references/evidence-streams.md](references/evidence-streams.md).

## Invocation

```
/absorb <github-username>
```

The argument is a GitHub username (e.g., `bcherny`, `mitchellh`, `antirez`) whose public
code practices the skill profiles into actionable improvements to your architecture.

## Subagent Dispatch Template

When dispatching `/absorb` via Agent tool, subagents do NOT load SKILL.md automatically — include
the ABSORB SKILL SUMMARY block from [references/subagent-dispatch.md](references/subagent-dispatch.md)
verbatim in the agent prompt.

## Scope guard

Before proceeding, verify the request is in-scope. If the user is asking about:
- **Evaluating external repos** without a specific developer target → redirect to `/evaluate-repos`
- **General community intelligence** (not a specific developer) → redirect to `/gather-intel`
- **Tool or technology comparison** (not a developer profile) → redirect to `/deep-dive`

Absorb requires a GitHub username as argument (`/absorb <github-username>`). If no username provided, ask for one before proceeding.

---

## Phase 1 — Surface (signal assessment)

**Goal:** Build a map of the target's public footprint. Determine if there's enough signal
to proceed.

**Tools:** `gh api` for GitHub profile + repos, Exa web search for supplementary context.

**Steps:**
1. `gh api users/<username>` — profile, bio, company, blog URL, public repo count, followers
2. `gh api 'users/<username>/repos?sort=updated&per_page=30'` — recent repos with stars, language, push dates
3. `gh api users/<username>/orgs` — discover org memberships (many developers' best work lives under org repos, not personal repos)
4. Exa web search (1-2 queries max) — "<name> software engineer" to find role, talks, blog, book

**Signal routing (automatic):**
After steps 1-3, assess where the target's work lives:

- **Public repos exist (10+ non-fork):** Proceed with public evidence. Standard path.
- **Public repos sparse but org memberships found:** The target may work in private org
  repos that `gh` can access. Proceed to the enterprise fallback (below).
- **Public repos sparse, no orgs, but username contains an org name or the user specified
  a known internal org:** Try the enterprise fallback.
- **All sources empty:** Fire the insufficient signal gate.

**Enterprise fallback (for internal/private developers):**
When public repos return <10 non-fork but `gh` authenticates against enterprise orgs:
discover accessible orgs dynamically with `gh api user/orgs --jq '.[].login'` (do NOT
hardcode org names), then run `gh search prs` / `gh search commits` filtered to those orgs.
If PRs or commits are found, proceed to Phase 2 using those org repos as the evidence
source, noting "enterprise org activity, not public repos" in the Phase 3 preamble; if not,
fire the insufficient signal gate. Full query sequence:
[references/enterprise-fallback.md](references/enterprise-fallback.md).

**Signal assessment gate (fires only after both public and enterprise paths are exhausted):**
Report "Insufficient signal for [username]. [N] public repos, [M] enterprise PRs found.
This target may use a different GitHub username or work in orgs not accessible to the
current `gh` token." Do NOT proceed to Phase 2.

**Budget:** 6 `gh api/search` calls + 2 Exa searches max for Phase 1 (the extra 2 cover
enterprise fallback queries).

## Phase 2 — Evidence (code-level analysis)

**Goal:** Extract verifiable patterns from their actual code practices. This is the core
of the skill. Everything here must be citable.

**Tools:** `gh api` and `gh search` for commits/PRs/issues/reviews, Exa crawling for
source files and PR discussions.

**Temporal weighting:** Prefer recent evidence — weight the last 12 months most heavily,
prefer repos pushed in the last 6 months, and flag patterns sourced exclusively from stale
repos (>18 months since last push). Full guidance in
[references/evidence-streams.md](references/evidence-streams.md) ("Temporal weighting").

**Evidence is organized into three tiers:**
- **Tier 1 (Code — PRIMARY):** Source code, architecture, coding style. This is where
  adoptable patterns live. Read actual files.
- **Tier 2 (Automation Artifacts — SECONDARY):** Skills, hooks, agents, settings,
  CLAUDE.md — the developer's automation infrastructure.
- **Tier 3 (Workflow — TERTIARY):** Commits, PRs, reviews, issues. These show how
  someone ships but rarely produce adoptable patterns for same-team targets.

**Dynamic budget split (adapt after Phase 1):**

| Target type (from Phase 1) | Tier 1 | Tier 2 | Tier 3 |
|---------------------------|--------|--------|--------|
| **CC config author** (primary repos are `.claude/` configs) | 30% | 40% | 30% |
| **Hybrid** (has both app code AND CC config) | 40% | 25% | 35% |
| **Pure coder** (no `.claude/` directory) | 60% | 0% | 40% |
| **Default** (unclear from Phase 1) | 50% | 20% | 30% |

(Split calibration history — Boris 2026-04-04, 9-developer batch 2026-04-05 — is in
[references/evidence-streams.md](references/evidence-streams.md), "Why the tier split exists".)

**Detailed evidence-stream instructions (2a-2h for Tiers 1+3, 2i-2m for Tier 2 automation
artifacts) live in `references/evidence-streams.md`.** Read that file when executing
Phase 2 — it is the collection procedure for every stream.

**Budget:** 30 `gh` API calls + 7 Exa crawls max across all of Phase 2. Tier 1 code reads
and Tier 2 automation reads via Exa crawling (not `gh api` contents endpoint) do NOT count
against the gh budget — use Exa for public repo file reading when possible to preserve gh
calls for workflow queries. Suggested split: 15 gh + 4 Exa for Tier 1, 6 gh + 2 Exa for
Tier 2, 9 gh + 1 Exa for Tier 3.

## Phase 3 — Synthesize (pattern extraction)

**Goal:** Distill Phase 2 evidence into named patterns. Every pattern must cite a specific
commit, PR, issue comment, or source file.

**Pattern entry format, target length (50-100 lines), and the seven groupings** (coding
style & practices — PRIMARY, architecture & design, automation & tooling, engineering
discipline, workflow practices, collaboration style, documentation & communication) are
specified in [references/profile-format.md](references/profile-format.md) — follow that
format for every pattern, grouped in that code-first order.

**Mandatory check:** For each pattern, explicitly flag if it **contradicts** an existing rule.
Contradictions beat confirmations — they indicate a rules gap or a context difference worth understanding.

**No vibes rule:** If a pattern can't be tied to a specific artifact, it doesn't survive
Phase 3. "They seem to prefer functional programming" is not a pattern. "tsoption implements
Fantasy Land Monad/Functor/Applicative — compile-time None.get() error" is a pattern.
For prompt engineering patterns (2m), quote the specific skill/agent text — worked example
in [references/profile-format.md](references/profile-format.md).

**Language tagging (MANDATORY):** If the target's primary language differs from your stack
(Python/TypeScript/Bash), tag each pattern at one of three levels:

- `[universal]` — the pattern is language-independent (commit style, PR sizing, review depth)
- `[principle-transferable]` — the mechanism is language-specific but the underlying
  principle applies everywhere; extract the principle explicitly (worked examples in
  [references/profile-format.md](references/profile-format.md))
- `[language-specific]` — both mechanism AND principle are tied to the language (e.g., Rust
  lifetime elision rules, Go goroutine patterns with no async equivalent in your stack)

Only `[language-specific]` patterns get the extra Phase 4 gate. `[principle-transferable]`
patterns survive the language gate but must include an explicit "translated principle" in
the recommendation — what does this look like in your stack?

**Cross-developer pattern aggregation:** After synthesizing, check if the same pattern
appeared in prior absorb profiles. Search `knowledge-base/topics/absorb-*.md` for the
pattern's keywords. If 3+ developers independently exhibit the same pattern, note it as
`[cross-validated: N developers]` — this is stronger signal than any single developer.
Cross-validated patterns should get extra weight at Gate 3 (the convergent evidence
partially compensates for lack of a documented incident in your own architecture).

**Independence check (MANDATORY for cross-validation):** Developers count as independent
sources only if they are NOT forking each other's configs, starring/contributing to each
other's repos, or citing the same tutorial/template as their source. Check: do any of the
matching profiles share repos (forked or contributed)? If yes, they count as ONE source,
not N. A pattern found in 5 developers who all forked the same template is N=1, not N=5.

**Deduplication check:** Before synthesizing, check if `knowledge-base/topics/absorb-<username>.md`
exists from a prior run. If it does, read it, skip patterns already evaluated, focus on new
evidence (repos updated since the prior run, new PRs), and note the prior run date and what changed.

**Persist the profile (MANDATORY — do not skip):** After synthesis, save the full Phase 3
output (all patterns with citations) to `~/Documents/knowledge-base/topics/absorb-<username>.md`
with proper frontmatter — template in [references/kb-persistence.md](references/kb-persistence.md).
Run `mkdir -p ~/Documents/knowledge-base/topics` before the first write (the directory may
be absent on a fresh deployment — create it rather than failing). Include a signal source
disclaimer at the top ("public repos" or "enterprise org activity"). This is the persistent
record `/recall` finds and future runs deduplicate against — **this step is not optional**.

Two frontmatter field rules CI enforces (full rationale + incident history in
[references/kb-persistence.md](references/kb-persistence.md)):
- `description:` is **MANDATORY** — a retrieval synopsis (searchable terms), not a title
  restatement. The KB `Docs CI` gate hard-requires it; omitting it turned `main` red on 2026-06-07.
- `stage: seedling`, never `evergreen` — `/garden` counts dated entries; a one-entry
  profile marked `evergreen` gets demoted next run (flip-flop churn).

### Finalize the KB artifact (MANDATORY — the CI gates that block the PR)

A topic `.md` alone is **not** a complete KB artifact — an uncompiled profile fails the
KB-wide `Docs CI` lint and blocks every other KB PR until fixed. Run the KB's canonical
compiler after writing the profile (or run `/garden`); rationale + the
2026-06-07 incident: [references/kb-persistence.md](references/kb-persistence.md):

```bash
python3 ~/Documents/knowledge-base/tools/kb.py build   # regenerate catalog, graph, evidence, health, README, Home
python3 ~/Documents/knowledge-base/tools/kb.py check   # verify (exit 0 = green PR)
```

`build` regenerates the *generated* artifacts (`generated/*.json` plus the marked regions
of README and Home). It will BLOCK
on a missing `description:` or an oversized chunk (>3000c) — those are authored content you
must fix in the topic itself. Run it yourself so the PR is born green; the KB's pre-commit
hook is the backstop, not the plan.

## Phase 4 — Compare (gap analysis)

**Goal:** Map each Phase 3 pattern against your architecture. Apply `rules/compare-by-need.md`
rigorously. Only patterns that survive all five gates become recommendations.

**Same-team detection:** If the target contributes to the same repos as you, the
compare-by-need gates will filter most patterns because you share conventions. After the
standard gates, add a **divergence analysis** — where does the target diverge from your
practice within the same environment? (Full procedure in
[references/gate-procedures.md](references/gate-procedures.md).) This turns "zero
recommendations" into "zero gaps but here are the divergences worth discussing."

**Steps for each pattern:**

1. **Identify the relevant architecture files.** Map the pattern's domain to specific
   files — don't read everything. See `references/phase4-file-mapping.md` for the full
   domain → architecture-file mapping table and fallback guidance.

2. **Apply the five gates** (from `rules/compare-by-need.md`):

   | Gate | Question | If NO → |
   |------|----------|---------|
   | 1. Read existing tools | What in your setup already covers this? | Proceed — genuine gap |
   | 2. Check the workflow | How do you solve this today? | Proceed — no current solution |
   | 3. Verify the problem | Does this gap cause real friction? How often? Cite incidents. | See 3-alt below |
   | 3b. Language gate | If tagged `[language-specific]`: does this translate to your stack? `[principle-transferable]` passes with an explicit translated principle. | **STOP** — inapplicable across languages |
   | 4. Assess adoption cost | Is the value > cost of the change? | **STOP** — cost exceeds value |
   | 5. Recommend the delta | Frame as: "X adds Y that current tools don't cover, and Y matters because Z" — not "adopt X". | Proceed to step 3 (formulate recommendation) |

   **Gate 3-alt (latent gap):** If a pattern passes Gates 1-2 (genuine gap, no current
   solution) but has no documented incident at Gate 3, it may still be valuable. Instead
   of STOP, classify as a **latent gap** — a problem you likely have but haven't hit yet.
   Latent gaps are persisted in the profile under `## Latent Gaps` (not rejected, not
   recommended). They become recommendations when an incident surfaces in their domain.
   Rationale + promote/prune/review lifecycle rules:
   [references/gate-procedures.md](references/gate-procedures.md).

3. **For patterns that pass all gates**, formulate a recommendation:
   - The exact file(s) to edit
   - The specific change
   - WHY — linking to your documented incidents where the gap caused friction
   - A **revert trigger**: "Revert if [measurable condition] within [timeframe]"

4. **For patterns that fail a gate**, note which gate stopped them and why. Present
   these as "Considered but rejected" — this prevents re-evaluating the same pattern
   in future `/absorb` runs.

4b. **Challenge every DEFER/REJECT verdict (MANDATORY).** After reaching an initial
   verdict of DEFER or REJECT, actively argue the opposite position before finalizing,
   using the four challenge questions in
   [references/gate-procedures.md](references/gate-procedures.md) (strawman deferral
   reasoning; incidents relabeled under a different root cause; "no documented incident"
   ≠ "no problem"; inflated implementation cost). If the challenge flips the verdict,
   upgrade to IMPLEMENT. If the verdict holds, note "challenged and confirmed" in the
   rejection entry. (Why this exists — the 2026-04-05 batch flipped 3 of 3 challenged
   deferrals — is in the reference.)

5. **Persist rejections (MANDATORY).** Append the "Considered but rejected" list to
   `knowledge-base/topics/absorb-<username>.md` (created in Phase 3) under a
   `## Rejected Patterns` heading. Include: pattern name, which gate stopped it,
   date, and model version. Future runs check this section before re-evaluating.
   **This step is not optional** — skipping it means the next run re-evaluates the
   same patterns and wastes the same turns.

   **Staleness window:** Rejections older than 6 months are eligible for re-evaluation,
   especially if new incidents have been documented in the pattern's domain since the
   rejection date. A pattern rejected at Gate 3 ("no friction") in January may be valid
   in July after a related incident. When re-evaluating, note "re-evaluated from [date]
   rejection" in the updated entry.

**N=1 contextualization (MANDATORY):** For every recommendation, include: "This pattern works
for [target] in [their context: team size, repo type, role]. Your context differs in [specific
ways]. The recommendation adapts it as follows: [how you translated it]."

## Phase 5 — Integrate (implement changes)

**Goal:** Ship the recommendations. Every change follows existing rules.

**For each recommendation:**

1. Follow `rules/check-before-change.md` — search memory and git for prior decisions on this topic
2. Edit the target file(s)
3. Commit messages follow the WHY requirement: `<what> — <why, citing target's pattern>`
4. If the change is to `claude-config` and alters execution behavior, it gets its own PR
   (per `rules/git-hygiene.md` config repo exception)
5. For audit artifacts (like the hook bitter lesson audit), write to
   `knowledge-base/topics/` with proper frontmatter

**Revert triggers:** Each recommendation's revert trigger must be documented either
in the commit message or in the knowledge base entry. Not optional.

**Output:** Present a summary table:

| # | Recommendation | File changed | Revert trigger | Source pattern |
|---|---------------|-------------|----------------|---------------|

**If zero recommendations survived the gates**, the output is still valuable.
Present:
1. The divergence analysis (for same-team targets)
2. The "Considered but rejected" table with gate citations
3. Any patterns that **reinforce** existing rules (confirmation has value)

**Effectiveness tracking (append to profile):** Add a `## What Shipped` section to the
persisted profile — template in [references/profile-format.md](references/profile-format.md).
It records recommendations made / implemented / reverted and latent gaps promoted; future
sessions update it (not this run), closing the loop on whether recommendations actually ship.

## Constraints

- **Evidence over inference.** Every claim must cite a specific commit, PR, file, or quote.
  "[INFERRED]" claims do not become recommendations.
- **Read actual code, not just structure.** Directory listings, file names, and repo
  metadata are insufficient for source code architecture patterns (2e). Read at least the
  manifest, one entry point, and one test file.
- **Check both review endpoints.** `pulls/N/reviews` shows approve/reject actions.
  `pulls/N/comments` shows inline line-level discussion. Both are required for 2c.
- **Persist profile AND rejections.** Phase 3 and Phase 4 step 5 both write to
  `knowledge-base/topics/absorb-<username>.md`. This is mandatory. Skipping breaks
  deduplication and wastes future runs.
  (These three constraints were calibrated by the 2026-04-04 Dustin test run's misses —
  notes in [references/examples.md](references/examples.md).)
- **compare-by-need is mandatory.** No feature-list comparisons. No "they have X, you should
  too." Every recommendation must survive the five gates.
- **Incident grounding.** Where possible, link recommendations to your documented incidents
  (auto-learn incident, skills-polish incident, claude-hud audit, etc.). A recommendation
  without incident grounding is weaker but not disqualified — it just needs stronger evidence
  from the target's practices.
- **check-before-change for edits.** Search memory and git before modifying any existing
  behavior. If a prior decision contradicts the recommendation, present the conflict to the
  user — don't silently override.
- **Budget hard caps.** Phase 1: 6 gh + 2 Exa. Phase 2: 30 gh + 7 Exa (Exa file reads
  exempt from gh count). Phase 4 reads are scoped to pattern domains (see mapping table).
  No speculative file reads.
- **Rate limiting.** If GitHub returns 403 (rate limit) or repeated 502s during Phase 2,
  pause collection. Present what you have so far and ask: "Rate-limited at [N] of [budget]
  API calls. Proceed with reduced evidence, or wait and retry?" Do not silently skip
  evidence streams — the user should know the profile is incomplete.
- **Revert triggers on every recommendation.** "Revert if [condition] within [timeframe]."
  Not optional.
- **Signal source disclosure.** State the evidence source in the Phase 3 preamble: "public
  repos" or "enterprise org activity (example-org, example-apps-org)." For
  enterprise profiles, note that the analysis covers org-visible work only — the target
  may have personal projects or prior-employer code not captured.

## Examples

Six worked examples (antirez, insufficient signal, mitchellh, internal teammate,
low-signal budget waste, Tier 2 automation cross-validation) live in
`references/examples.md`. Read that when reasoning about edge cases or calibrating
what passing/failing gates look like in practice.

## Success Criteria

- Zero recommendations that are already covered by existing architecture
- Every recommendation grounded in BOTH external evidence AND internal friction
- Every recommendation has a revert trigger with measurable condition and timeframe
- Concrete file edits shipped by end of skill execution, not deferred as advice
- Considered-but-rejected patterns documented to prevent re-evaluation
- Profile AND rejections persisted to knowledge base (verifiable: file exists after run)
- KB artifact is CI-compliant and born-green (verifiable: frontmatter has `description:`;
  the topic appears in `generated/catalog.json`;
  `python3 ~/Documents/knowledge-base/tools/kb.py check` exits 0
  locally before the PR is opened)
- Source code actually read, not just directory structure (verifiable: citations include
  file contents, not just filenames)
- Engineering discipline dimensions assessed: test-first behavior, refactoring isolation,
  revert/recovery patterns (verifiable: Phase 3 includes patterns in "Engineering discipline"
  grouping, or explicitly notes "insufficient data" for streams that returned nothing)
- Review response behavior checked (2c-b) — not just how they review others, but how they
  receive feedback on their own PRs
- Automation artifacts examined (Tier 2): skills, hooks, agents, CLAUDE.md, settings compared
  against actual implementations (not just rules). Verifiable: Phase 3 includes patterns in
  "Automation & tooling" grouping, or explicitly notes "no automation artifacts found"
- Cross-developer patterns flagged when 3+ profiles share the same pattern
