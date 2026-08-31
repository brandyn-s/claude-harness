---
name: scout-skills
description: "Mine the Context7 skills registry for techniques and route adoptions across the architecture."
when_to_use: 'Use when mining Context7 skills registry for patterns, substantive techniques, or domain insights. Trigger phrases: "scout skills", "search context7 skills", "find skill patterns", "mine skills registry". Do NOT use for GitHub repo discovery (use /scout or /gather-repos) or developer profiling (use /absorb). Searches by category, fetches actual SKILL.md files, names the underlying technique BEFORE comparing, routes adoptions to skill / references / rule / topic / memory / KB — not only SKILL.md.'
argument-hint: "[optional: category focus e.g. 'security', 'testing', 'rust']"
effort: high
compatibility:
  requires:
    - cli: gh
    - cli: curl
    - cli: python3
  optional:
    - env_var: XAI_API_KEY
      fallback: "Step 3.5 quorum runs single-sided (GPT only) or skips entirely; note in report and downgrade SKIP confidence"
    - env_var: OPENAI_API_KEY
      fallback: "Step 3.5 quorum runs single-sided (Grok only) or skips entirely; note in report and downgrade SKIP confidence"
    - skill: roundtable
      fallback: "Step 3.5 quorum unavailable — roundtable adapter modules are reused here. Without them, fall back to single-model SKIP verdicts."
metadata:
  author: example-security-engineering
  version: "1.5"
allowed-tools: Bash Read Edit Skill AskUserQuestion
---

# Scout Skills — Context7 Registry Pattern Mining

Search the Context7 skills registry, fetch real SKILL.md files, compare
against our architecture, and incorporate what's useful. Designed against
two opposing failure modes: **over-evaluating** low-risk additions, and
**under-extracting** substantive techniques (collapsing them into
"editorial polish"). Rationale, evolution history, and counter-mechanisms:
[`references/anti-patterns.md`](references/anti-patterns.md).

| Change type | Risk | Evaluation | Action |
|-------------|------|------------|--------|
| **Additive** (new example/diagram/step/table) | Low | Side-by-side read | Incorporate |
| **Structural** (new file, frontmatter field, workflow phase) | Medium | Read + check 1 precedent | Incorporate with attribution |
| **Behavioral** (changes model routing/logic/format) | High | Full compare-by-need | Flag for user |

---

## Scope guard

Before searching, verify the request is in-scope. If the user wants:
- **GitHub config repo discovery** (not Context7 skills registry) → redirect to `/scout` or `/gather-repos`
- **Developer profiling** (a specific GitHub user's practices) → redirect to `/absorb`
- **Community patterns** from Reddit/HN/blogs → redirect to `/gather-intel`

Scout-skills mines the Context7 registry specifically — it does not search GitHub directly. If out-of-scope, tell the user which skill to use instead, then stop.

---

## Step 0: Choose Search Categories

If `$ARGUMENTS` specifies a focus, search that category with multiple
query variations. Otherwise search across the stack.

**Before searching, check what was already searched this session.** Skip
categories already covered (visible in conversation context). Report:
"Skipping N categories already covered this session."

**Minimum**: 8 categories per run when unscoped; 3+ query variations + 2-3
adjacent categories when scoped. Rotate strategies; don't sequence. A
strategy is exhausted only when 3+ creative query variations within it
return already-seen repos.

Six strategies (Category sweep, Gap-driven, Refinement, Suggest API,
Queue mining, Deep-dive expansion), 12 default categories, optional 4-6
technique-vocabulary queries, Context7 REST API usage:
[`references/search-strategies.md`](references/search-strategies.md).

**Boundary with /scout-frontier:** technique-vocabulary queries surface
techniques already encoded in Context7 skills. For paradigm-distinct
approaches NOT yet in Context7, hand off to `/scout-frontier`.

---

## Step 1: Filter and Select for Deep Dive

Sweet spot: **8-12 repos** per run (3-4 from known repos for yield,
4-8 from novel repos for discovery; above 15 → diminishing returns).

### Selection criteria (signal-ordered)

1. **Recurring repos** — repos in 3+ category searches are the strongest signal.
2. **Trust score ≥ 7.0**; skip Low/unscored unless from a known developer.
3. **Novel repos** — not in `~/.claude/assessed-repos.md` AND not already deep-dived this session.
4. **Skills not yet read from known repos** — deep-dived repos may have additional unread skills.

Full known-repo table (32 repos, patterns adopted per repo) and
deep-dive guidance: [`references/known-repos.md`](references/known-repos.md).

---

## Step 2: Fetch Actual SKILL.md Files

**YOU must read the SKILL.md files yourself.** Do not delegate to a
subagent and present findings as verified.

The Context7 `url` field is NOT a raw GitHub URL — it 404s when fetched
directly. Use the GitHub API:

```bash
# List skill paths
gh api 'repos/{owner}/{repo}/git/trees/HEAD?recursive=1' \
  --jq '.tree[].path' | grep -i "skill.md"

# Fetch content
content=$(gh api repos/{owner}/{repo}/contents/{path} --jq '.content' 2>&1)
if echo "$content" | grep -q "Not Found"; then
  echo "SKIP: {path} not found (404)"
else
  echo "$content" | tr -d '\n' | python3 ${CLAUDE_PLUGIN_ROOT}/skills/scout-skills/scripts/decode_contents.py
fi
```

Parallelize fetching (up to 5 concurrent) but **read sequentially**. For
each SKILL.md, note: frontmatter fields used, structural patterns,
concrete techniques, similarities and differences with our skills.

---

## Step 2.7: Technique Card (extract substance before comparing)

For each candidate, produce a **technique card** with four fields:
underlying technique, domain it serves, operationalizable atom, source.
Forces technique-naming BEFORE the Step 3 comparison gate so substance
doesn't collapse into the artifact's editorial shape. Create the technique
card file and save it to `${TMPDIR:-/tmp}/scout-skills/technique-cards/<id>.md`
for downstream consumption in Step 3.5. Full template, good-vs-bad examples,
and empty-card heuristic:
[`references/technique-card-template.md`](references/technique-card-template.md).

**Save the community skill to the temp directory first:**

```bash
echo "$content" | tr -d '\n' | python3 ${CLAUDE_PLUGIN_ROOT}/skills/scout-skills/scripts/decode_contents.py > ${TMPDIR:-/tmp}/scout-skills/scan-fetch-<repo>-<skill>.md
```

**Mandatory 3rd-party validation.** In parallel with your own card,
dispatch GPT on the same SKILL.md:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/scout-skills/scripts/produce_card.py \
  --input ${TMPDIR:-/tmp}/scout-skills/scan-fetch-<repo>-<skill>.md \
  --output ${TMPDIR:-/tmp}/scout-skills/gpt-card-<repo>-<skill>.md
```

Compare field-by-field. If one names a substantive technique the other
marked editorial-only, re-read the source. Cost: ~15 cents/card,
~1-2 dollars/session for 6-12 candidates. Missing `OPENAI_API_KEY` → fall back
to single-author with reduced-confidence flag in Step 5 report.

---

## Step 3: Architecture-Wide Comparison

Ask **where in our architecture the technique LIVES** — not "does our
matching skill cover it." Anchoring on "OUR SKILL" pre-narrows the
search and collapses techniques into the nearest editorial bucket.

For each technique card:

1. Read the community SKILL.md (done in Step 2).
2. Read across destinations the technique could live in. Use the
   per-domain candidate lists in
   [`references/routing-destinations.md`](references/routing-destinations.md)
   as starting points.
3. Answer: **where in our architecture would this LIVE, if adopted?**
4. **SKIP only when present at every plausible destination.** Step 3.5
   verifies SKIP architecture-wide.
5. Adoption candidates proceed to Step 4.

Seven destination buckets: `skill/SKILL.md` (Additive/Structural),
`skill/references/*.md` (Structural), `rules/<name>.md` (Domain Insight),
`knowledge-base/topics/<name>.md` (Domain Insight),
`agent-memory/topics/<name>.md` (Domain Insight), new skill (Novel),
drop (SKIP-candidate → Step 3.5).

---

## Step 3.5: Multi-Model SKIP Verification

Runs ONLY on SKIP-candidate verdicts. Compares the technique card
against an architecture-wide context set (skills + rules + topics +
memory) using a Grok + GPT quorum.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/scout-skills/scripts/verify_skip.py \
  --technique-card ${TMPDIR:-/tmp}/scout-skills/technique-cards/<id>.md \
  --community ${TMPDIR:-/tmp}/scout-skills/scan-fetch-<repo>-<skill>.md \
  --ours ${CLAUDE_PLUGIN_ROOT}/skills/<our-skill>/SKILL.md \
  --ours $HOME/.claude/rules/<related-rule>.md \
  --ours $HOME/Documents/knowledge-base/topics/<related-topic>.md
```

Exit codes: 0=SKIP-CONFIRMED, 10=REVIEW-NEEDED, 20=ABSTAIN, 30=bad input.

Skip the quorum when: 0 SKIP-candidates, empty technique card, missing
API keys, mechanical-implementation SKIP, domain-mismatch SKIP, or
generic-OWASP-rehash SKIP. Workflow, cost envelope, and three documented
failure modes addressed:
[`references/skip-verification.md`](references/skip-verification.md).

---

## Step 4: Present Findings, Then Act

**MANDATORY: Present ALL findings with narrative BEFORE any edits.** A
summary table is NOT a presentation. Each finding gets its own numbered
section with enough context for an adopt/defer decision without
follow-up questions.

### Presentation format (required for every finding)

```
### Finding N: {Descriptive title}

**Source:** {org/repo} `{skill-name}` (trust={score})
**Classification:** Additive | Structural | Behavioral | Hook | Domain Insight | Domain Insight (Harness) | Novel
**Technique card:** {one-line — the underlying technique, not the artifact}
**Destination:** {skill / references / rule / topic / memory / KB / hooks/staged / evals / new skill}
**Concrete diff:** {exact target file + before/after — NOT a prose description}

**What it does:** {2-3 sentences}
**What we do instead:** {cite our file and section — name ALL destinations checked}
**Why it matters:** {concrete scenario}
**Recommendation:** {Adopt / Defer / Build later} + rationale
```

**Mandatory concrete-diff requirement.** Every adoption recommendation
includes a real diff — target file path + before/after text. Prose-only
recommendations leak to SKILL.md polish even when the technique card
pointed to a rule or topic.

### After presenting ALL findings

Pause. State "Incorporating N additive patterns now — interrupt if any
should be skipped." For Behavioral/Novel/Hook, wait for explicit user
decision. Domain Insight proceeds without explicit approval (same risk
tier as Additive) BUT the diff destination is non-SKILL.md.

### Classification table

| Bucket | Risk | Destination | Approval |
|---|---|---|---|
| **Additive** | Low | Existing SKILL.md (new example/table/note) | Auto |
| **Structural** | Medium | `references/`, new frontmatter field | Auto if precedent exists |
| **Domain Insight** | Low-Med | Rule, topic, memory entry (NOT SKILL.md) | Auto |
| **Domain Insight (Harness)** | Low-Med | Topic file + runnable script (same PR) | Auto |
| **Behavioral** | High | SKILL.md execution change | User approval |
| **Hook** | High | Staged spec in `hooks/staged/` — never inline | User approval after replay |
| **Novel** | — | Propose new skill | User approval |

Full rubrics, examples, procedures, and Hook-vs-Behavioral axis:
[`references/finding-classification.md`](references/finding-classification.md).

**Apply `compare-by-need.md` Gates 1-4 only to Behavioral.** **Hook spec
must replay against 30 days of transcripts with <10% block rate before
recommending activation.** **Domain Insight: drop the "no overlap" gate
— partial overlap triggers refinement, not rejection.**

---

## Step 5: Ship

1. `git diff --stat` to verify changes.
2. Review each changed file's diff.
3. Invoke `/ship` with a commit message listing all incorporated
   patterns and sources.

### Step 5.5: Session Output Audit

**MANDATORY before declaring complete.** Tabulate this session's
adoption distribution by destination. When 100% of adoptions are
SKILL.md AND ≥3 adoptions total, surface the audit explicitly so the
user confirms intentional routing (genuine-editorial) vs bias
recurrence. Audit template, trigger conditions, and resolution options:
[`references/report-format.md`](references/report-format.md).

This guard catches the failure mode that drove the v1.2 overhaul:
silent reversion to editorial polish.

### Step 5.6: Update Known Repos Table

After shipping, update `references/known-repos.md`: increment counts
for existing repos or add new rows for novel repos with ≥1 adoption.
Update the `(Last updated: ...)` line. Skip if 0 adoptions.

Report format (SCOUT-SKILLS SUMMARY template):
[`references/report-format.md`](references/report-format.md).

---

## Anti-Patterns This Skill Prevents

15 documented anti-patterns and their counter-mechanisms
(over-evaluation, rejection bias, asymmetric evidentiary burden,
editorial-polish bias, single-surface quorum, silent bias recurrence,
hook misclassified as behavioral, executable methodology trapped in
prose, etc.): [`references/anti-patterns.md`](references/anti-patterns.md).

---

## Success Criteria

- ≥8 category searches; every candidate has a technique card (reader + GPT) before Step 3.
- Every gap verified architecture-wide (skill / references / rule / topic / memory) — not just OUR matching skill.
- Every judgmental SKIP-candidate passed through Step 3.5 quorum; mechanical SKIPs exempt and noted.
- Additive patterns incorporated in-session; Domain Insight lands in rule/topic/memory/KB.
- Behavioral patterns presented with concrete diff (file + before/after); never prose-only.
- Each pattern attributed to source at destination.
- Ship report lists all changes with sources AND destinations.
- Step 5.5 Session Output Audit completed; ≥3 SKILL.md-only adoptions explicitly resolved.
- Hook findings STAGED (`hooks/staged/<name>.spec.md`); installation deferred to `/ship-hook`.
- Domain Insight (Harness) produces BOTH topic prose AND runnable script in same PR.

## Examples

**Broad scan**: `/scout-skills` — all 12 categories, ~200 skills found, deep-dive 12 repos, 4 additive + 1 behavioral flagged.

**Focused scan**: `/scout-skills observability` — observability + adjacent categories, 5 repos, 2 patterns adopted.

**Ad-hoc repo**: `/scout-skills mattpocock/skills` — deep-dive specific repo's skills, compare and incorporate additive.
