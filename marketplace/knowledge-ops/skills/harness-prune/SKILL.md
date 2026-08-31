---
name: harness-prune
description: "Audit the harness for stale workarounds — model-version compensations and shipped library fixes."
when_to_use: 'Use when the harness (skills, hooks, rules) should be audited for stale workarounds — model-version compensations that newer models made unnecessary, and library workarounds whose upstream fix has shipped. Trigger phrases: "harness prune", "prune workarounds", "stale workarounds", "are these workarounds still needed". Do NOT use for knowledge-base curation (use /garden), operational memory audits (use /review-learnings), or rule-content audits (use /audit-rules).'
argument-hint: "[omit for full scan]"
effort: low
allowed-tools: Read Grep Bash Write
metadata:
  author: example-security-engineering
  version: "1.0"
---

# Harness Prune — Stale-Workaround Audit

Split out of /garden 2026-06-11 (B8c/F2): auditing the *harness* for rot
is conceptually distinct from curating the *knowledge base*. Ownership
boundary (B8c/F3): **this skill owns the skills/hooks/rules surface**;
/garden owns the KB plus the agent-memory topic sweep. Each run ends by
naming the other's surface so neither is assumed covered.

## Step 0: Reconcile existing backlog entries (before scanning for new ones)

Re-check every OPEN entry already in
`~/Documents/knowledge-base/topics/harness-pruning-candidates.md` against
current file state before looking for new candidates. Step 4 only ever
appends, so a backlog entry can go stale silently when the language it
describes is removed by an unrelated change (a rewrite, a different
cleanup pass) that never touched this file. (Found 2026-07-03: a
context-anxiety entry open since 2026-04-25 described language already
removed from both cited files, undetected for 10 weeks.)

For each `> **STATUS:** OPEN` entry that names specific file(s):
1. Grep the cited file(s) for the language/pattern the entry describes.
2. If the pattern is GONE from every cited file → flip the marker in
   place to `RESOLVED <today> — verified via direct grep of <files>:
   zero hits` (KB CLAUDE.md "Status markers" convention: flip in place,
   never just append a new entry on top).
3. If the pattern is STILL present in at least one cited file → leave
   OPEN, no action.
4. If the entry doesn't cite a specific file/line (judgment-only or
   `[unverified]`) → skip; nothing mechanical to re-check.

Within-page, evidence-only flip — same safety bar as /garden's own
Open-Status-Marker check. Only close an entry where fresh grep evidence
directly contradicts its OPEN claim; never guess.

## Step 1: Model-version workaround scan (scripted)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/harness-prune/scripts/scan_workarounds.py
```

Emits JSON candidates: versioned model references (Fable/Mythos/Sonnet/Opus/Haiku +
explicit version) within 2 lines of workaround language ("compensate",
"work around", "context anxiety", "context reset"). The scan finds
PAIRS deterministically across active skills, shared policy/reference files,
hooks, rules, agents, and docs; it does not judge staleness.

## Step 2: Judge each candidate

For each candidate, read the surrounding section and decide:
- **Still needed** — the workaround targets current-model behavior or a
  platform constraint that hasn't moved. Leave it; no entry.
- **Prune candidate** — the referenced model is superseded and the
  compensated behavior is documented-fixed (cite the changelog/release
  note you verified). Do NOT delete inline — append to the backlog
  (Step 4).
- **Unverifiable** — staleness depends on a measurement you can't run
  here. Append with an `[unverified]` tag and what would settle it.

## Step 3: Library workaround freshness

Scan `~/.claude/rules/platform-constraints.md` for library workarounds.
For each, check installed vs documented version with the host's package
manager (`python3 -m pip show <pkg>`; `pip show` in cloud execution).
If the installed version is at or past the documented upstream fix,
it's a prune candidate — include the relevant changelog snippet. If the
package-manager call fails (network, missing python), skip this source
and note "workaround freshness skipped — package manager unavailable"
in the report.

## Step 4: Append candidates to the backlog

Target: `~/Documents/knowledge-base/topics/harness-pruning-candidates.md`
(create if missing). Append dated entries — never edit the harness
in-place from this skill; pruning itself is a reviewed change through
the normal claude-config PR flow. If the KB staging checkout is
unavailable (worktree, cloud session), emit the entries in the report
instead and say where they belong.

## Step 5: Report

Counts only: reconciled/resolved (Step 0) / candidates found / judged-stale
/ appended / skipped, plus the boundary reminder: "KB + agent-memory
surfaces are /garden's — run it separately."

## Examples

**Example 1: Full scan finds a stale model workaround**

User says: `/harness-prune`

Actions:
1. Run the scanner — 3 candidates emitted (model refs near workaround language)
2. Judge each: one cites "Sonnet N.N context anxiety" compensation; current models document the fix in release notes → **prune candidate**. Two target live platform constraints → **still needed**.
3. Library pass: installed `fastmcp` is past the documented upstream fix for one workaround → second prune candidate, changelog snippet attached
4. Append both dated entries to the backlog topic in the knowledge base
5. Report: "3 candidates / 2 prune / 2 appended / 0 skipped. KB + agent-memory surfaces are /garden's — run it separately."

**Example 2: Scan runs clean, library check blocked**

User says: `/harness-prune`

Actions:
1. Scanner emits 0 candidates — no versioned model refs near workaround language
2. Library pass: `python3 -m pip show` fails (no network in this environment) → skip with "workaround freshness skipped — package manager unavailable"
3. Nothing to append; backlog untouched
4. Report: "0 candidates / 0 appended; library freshness skipped. /garden's surfaces not covered here."

## Success Criteria

- [ ] Every existing OPEN backlog entry citing a specific file was re-checked against current file state before any new scan (Step 0)
- [ ] Scanner ran (or its absence was reported, with the hand-scan fallback: grep the SCAN_GLOBS for model refs near workaround language)
- [ ] Every candidate received an explicit verdict (needed / prune / unverified)
- [ ] No in-place harness edits — backlog appends only; existing-entry reconciliation flips STATUS markers in place (KB convention), it does not edit harness files
- [ ] Report shows counts and names /garden's surfaces as not-covered-here
