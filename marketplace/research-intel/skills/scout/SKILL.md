---
name: scout
description: "Discover and evaluate community Claude Code config repos end-to-end in one pass."
when_to_use: 'Full pipeline: discover → inventory → delta-find → red-team → advocate/skeptic (survivors only). Use when community Claude Code config repos should be discovered and evaluated end-to-end in one pass. Chains /gather-repos → /evaluate-repos, which now embeds three selection-bias guards: paradigm-name search over incumbent-keyword search, source-first for repos under 5K LOC, and stars/recency as tiebreakers not gates. The asymmetric-rigor smell-check (Step 2.5) remains an operator-level consideration. Scoped to Claude Code config repos (hooks/skills/rules/agents/memory/ config buckets). Trigger phrases: "scout", "scout repos", "find and evaluate repos". Do NOT use for discovery-only (/gather-repos), evaluation-only (/evaluate-repos), or paradigm-distance scouting across other technical domains (use /scout-frontier — different approach to the same outcome, not better implementation of the same approach).'
argument-hint: "[optional: repo URL for ad-hoc scout]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Bash Skill AskUserQuestion
---

# Scout -- Discover and Evaluate Community Repos

Chains `/gather-repos` (discovery + inventory) and `/evaluate-repos`
(delta-find → red-team → advocate/skeptic for top findings) into a
single command.

---

## Step 1: Gather

Invoke `/gather-repos` using the Skill tool. Pass `$ARGUMENTS` through
(supports ad-hoc repo URLs).

Wait for it to complete fully — it will produce inventories in
`~/.claude/assessed-repos.md` and present a discovery summary.

## Step 2: Evaluate

If gather produced any inventoried repos (check the summary for
"Inventoried: N repos"), invoke `/evaluate-repos` using the Skill tool.

**Handoff contract:** `/scout` invokes `/evaluate-repos` with the literal
source argument `from last gather-repos` (the required `source` parameter
documented in `skills/evaluate-repos/manifest.yaml` and its `argument-hint`).
`/evaluate-repos` then reads the `## Handoff to /evaluate-repos` section
that `/gather-repos` wrote to `~/.claude/assessed-repos.md` in Step 1.
That section lists each inventoried repo with verdict `inventoried`
(lowercase) and per-bucket counts. No JSON contract is exchanged between
the skills — coordination is via that markdown section in the shared
ledger file.

This triggers the full evaluation pipeline: delta-finder scans all
inventoried patterns, top 3 by delta magnitude get advocate/skeptic
pairs, red team annotates survivors, and remaining findings are listed
with type/file/LOC metadata.

If gather produced zero inventories (all duplicates or auto-SKIP types),
report "Nothing new to evaluate" and stop.

## Step 2.5: Selection-bias guards (for the operator invoking /scout)

`/scout` anchors on incumbent-keyword search and GitHub stars by default. Three
of the four selection-bias guards are now embedded in `/gather-repos`' pipeline:

- **Paradigm-name search** — /gather-repos fires queries on paradigm names (not
  just incumbent-keyword searches) to surface novel candidates beyond same-paradigm
  peers. See `/gather-repos` Step 1 for the query template.
- **Source-first for repos under 5K LOC** — /gather-repos reads manifest and
  key implementation files before README when inventorying small repos, ensuring
  claims are corroborated by code.
- **Stars and recency as tiebreakers, not gates** — /gather-repos uses commit
  velocity, issue resolution time, and PR merge rate as tie-breakers when
  score-4+ candidates exceed inventory budget, deprioritizing dormant repos
  only when all other signals are equal.

One guard remains an operator-level consideration:

- **Asymmetric rigor is a smell.** When `/evaluate-repos` runs the
  skeptic agent on community claims, also run it on the corresponding
  claim in our own marketing. SECURE-856 (code-graph token-savings
  benchmark) was created exactly because of this. Read the `/evaluate-repos`
  output with this lens and consider whether to re-run with different framing
  if asymmetric rigor appears.

## Step 3: Report

Present combined results:

```
SCOUT SUMMARY

Discovery: N repos screened, M inventoried
Evaluation: K findings assessed (J via advocate/skeptic, L listed)
  Type breakdown: H hooks, S skills, R rules, A agents, MEM memory, C config
Red team: N [skeptic-wins], M [high-cost-low-delta]
User decisions (per /evaluate-repos Step 4 vocabulary):
  N new artifact, M extend existing, P memory, Q drop
```

---

## Success Criteria

- gather-repos runs to completion before evaluate-repos starts
- Arguments pass through to gather-repos (ad-hoc URLs work)
- Zero inventories = early stop (no empty evaluate-repos invocation)
- Combined summary covers both phases

## Examples

**Example 1: Full pipeline**
```
/scout
```
Discovers 300+ repos, inventories 8, evaluates all 8 with advocate/skeptic
pairs, presents combined summary with adoption proposals.

**Example 2: Ad-hoc repo**
```
/scout https://github.com/someone/interesting-config
```
Inventories the single repo, evaluates its findings, presents results.
