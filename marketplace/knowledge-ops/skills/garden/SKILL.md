---

name: garden
model: sonnet
description: "Curate the knowledge base — run a health check and auto-resolve every curation issue."
when_to_use: 'Use when the knowledge base needs curation. Runs a full health check and auto-resolves every check — stage promotion, broken wiki-link cleanup, orphan MoC assignment, MoC coverage gap fill, bare-link conversion, and merge candidates. No "human review needed" bucket — every check has an auto-resolution path. Trigger phrases: "garden", "tend the garden", "garden health", "curate knowledge base", "prune deprecated pages". Do NOT use for capturing new knowledge (use /capture), pushing to GitHub (use /capture push), operational memory audits (use /review-learnings), or harness workaround pruning (use /harness-prune).'
argument-hint: "[omit for full run, or 'audit' for dry-run preview]"
effort: medium
allowed-tools: Bash Edit Glob Grep Read Write mcp__memory-search__memory_search mcp__memory-search__memory_search_batch
metadata:
  author: example-security-engineering
  version: "2.4"
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


## garden

# Garden — Digital Garden Curation (Fully Automated)

Weekly curation skill. Reviews all topic pages, auto-resolves every detected
issue, and pushes a single PR. The user never performs "human review" — if a
check cannot be auto-resolved, the check is dropped.

**Staging directory:** `~/Documents/knowledge-base/topics/` (git checkout of
`example-org/claude-knowledge-base`)
**Push mechanism:** feature branch + PR + `gh pr merge --auto --squash
--delete-branch` from inside the staging directory.

---

## Modes

| Argument | Behavior |
|----------|----------|
| *(none)* | Full run: branch from origin/main, inventory, auto-resolve every check, push if anything changed. |
| `audit`  | Dry-run preview: branch, inventory, run detection only. Report what WOULD change. No edits, no push. |

In `audit` mode, skip Steps 4-fix (the actual writes) and Step 5 (push).
Emit the same report but prefix the auto-fix section with "Would apply:"
instead of "Applied:". Use this mode when garden hasn't run on a repo
recently or after a large `/capture` push — preview before committing.

---

## Step 1: Branch from origin/main

Garden never needs the staging checkout's local `main` — every run ships from
a feature branch, so cut it straight off the remote:

```bash
cd ~/Documents/knowledge-base && git fetch origin main && \
  git checkout -B "garden/$(date +%Y-%m-%d)" origin/main
```

This replaces the former stash/rebase-main sync entirely: branching from the
remote guarantees current content, never touches local `main` (which may be
held by another worktree), and makes the rebase-a-branch-that-is-AHEAD /
stash-pop-onto-a-moved-base failure mode unreachable (both measured; history
in [references/checks-staging.md](references/checks-staging.md) "Why Step 1
branches from origin/main").

**Inspect before the checkout, scoped to garden's own surfaces:**
`git status --short -- topics/ generated/` must be clean; dirty files there
that this run did not create belong to another session — stop and surface
them. Untracked files OUTSIDE those paths (`plans/`, `research/`) are
unrelated, survive the checkout untouched, and must NOT be stashed. If the
checkout itself is contended (a live session on another branch, `git checkout`
refuses), do NOT force it: cut a worktree off `origin/main`, point
`analyze.py` at its `topics/`, fix and ship from there, and say in the report
that the staging checkout was bypassed — everything downstream is
path-parameterized.

**Convergence fast-path.** Before running any checks, test whether the corpus
changed since the last garden run:

```bash
git log --oneline "$(git log --format=%H --grep='^garden:' -1 origin/main)..origin/main" -- topics/
```

Empty output means no commit has touched `topics/` since the last garden
merge, so the corpus is byte-identical to a state garden already converged on.
Still run the analyzer (cheap, and it PROVES convergence rather than assuming
it), but skip the merge-candidates memory-search entirely — its outcome is
deterministic on unchanged input and it is the most expensive check (~10s on
a cold index). Report "converged — unchanged since last garden run (<sha>)".
If the grep finds no prior garden commit, run everything.

## Step 2: Inventory

**Run the bundled analyzer first.** The mechanical analysis — inventory,
classification, dated-entry counting, wiki-link extraction, broken/bare/orphan/
MoC-gap detection, and leaf-chunk measurement — is deterministic and is
performed by `scripts/analyze.py` (relative to this skill directory):

```bash
python3 "<skill-dir>/scripts/analyze.py" ~/Documents/knowledge-base/topics
```

It writes a JSON report to a temp path (printed on stdout, e.g.
`<tempdir>/garden_report_<date>_<dirhash>.json` — namespaced by input dir so the
agent-memory sweep never clobbers the KB report; read the printed path, don't
assume the name) — NOT into the staging repo, so it can never trip the Step 5
push. Consume that JSON for every count and candidate
list below; you (the LLM) then apply the **judgment** parts: orphan/MoC-gap
fit-ladder placement, HIGH-confidence merge decisions, and concept-named
soft-chunk splitting. Do not re-derive the mechanical counts by hand — the
analyzer shares its dated-entry regex and its leaf-chunk algorithm with
`/capture` and the CI gate respectively, so consuming its output is what keeps
the three components from disagreeing (the disagreement class that produced
both the absorb stage flip-flop and phantom chunk counts).

If `analyze.py` is unavailable (older deployment, run from a context without
the script), fall back to performing the inventory by hand using the
definitions below.

The analyzer (and the hand fallback) computes per file: frontmatter, the
**dated H2 count** (regex `^## .* \(\d{4}-\d{2}-\d{2}\)`, shared with /capture
so promote/demote decisions agree — raw `## ` headers without a date suffix do
NOT count), all `[[wiki-links]]`, and a **classification** (moc / dashboard /
topic / suspect_moc). The exact classification rules — including the
load-bearing suspect_moc *shape* gate (zero dated entries also needs MoC
shape, link-list ratio ≥ 0.5) — are in
[references/procedures.md](references/procedures.md) "Step 2 classification
rules".

## Step 3: Auto-resolve every check

Run all checks in one pass. Every check has an auto-resolution path. NO
"flag for human review" buckets — that pattern accumulates noise and never
clears.

**Session attribution** — every edit garden makes (MoC additions, redirect
notes, frontmatter stage changes, broken-link strips, bare-link
conversions) must include an HTML comment immediately after the changed
line or block:

```
<!-- garden: YYYY-MM-DD action:<check-name> -->
```

For example, after stripping a broken link, the line gets the comment;
after adding an entry to a MoC, the new entry line gets it; after
promoting a stage in frontmatter, the line stays as `stage: budding` but
a sibling line `# garden: 2026-05-23 action:stage-promotion` is added
inside the frontmatter (YAML supports `#` comments). This lets future
audits trace any garden edit back to a specific run — invisible in
Obsidian, visible in git blame and grep.

### Stage Audit → auto-promote
- 1-2 dated entries → `seedling` (0-entry placeholder pages also seedling)
- 3-7 dated entries → `budding`
- 8+ dated entries → `evergreen`

Bands match `capture/SKILL.md` Step 4 exactly. The analyzer splits stage
findings into two lists with different dispositions:

- `stage_mismatches` (under-promoted or missing stage) → auto-fix: edit
  frontmatter directly.
- `stage_overstaged` (stage above what the dated count supports) →
  REPORT-ONLY. Recounting bands is not grounds for demotion (see Demotion
  below). The analyzer exempts two perpetual-noise shapes — **hubs**
  (`## Sub-topics` index) and **zero-dated reference topics with ≥3 `## `
  sections**; a near-empty mis-staged placeholder still surfaces. Exemption
  history and rationale:
  [references/checks-staging.md](references/checks-staging.md).

Topics tagged `maintenance` (and the hardcoded backlog files) are exempt
from the stage audit entirely — their dated headers are list items, not
capture events (KB CLAUDE.md "Garden maintenance").

**Curator pin:** a topic whose staging is a confirmed deliberate choice can
carry `stage_pinned: true` in frontmatter; the analyzer then exempts it from
the whole stage audit (no auto-promotion, no overstaged row, no demotion).
Use it once a human has confirmed an overstaged row is intentional, so it
stops re-appearing in every report.

**Demotion** is permitted but only fires after the Merge Candidates check
(which can shrink the smaller file's entry count to zero before deletion)
or after a manual user edit that removed entries. The Cross-File Fact
Duplication check (see below) no longer rewrites in-place, so it does NOT
cause demotion. A topic whose entry count shrunk into a lower band moves
down; this keeps stage truthful to current entry count rather than peak
historical state.

**Skip topics whose current `stage` is a NAMED non-promotion stage
(e.g. `retired`, `archived`, `deprecated`, `draft`).** These represent
deliberate lifecycle management — promoting a retired topic back to
evergreen because its entry count crossed a threshold would silently
un-retire it. The promotion bands apply ONLY to topics already in the
seedling/budding/evergreen progression, OR to topics with no stage set
yet (missing or empty `stage:` field — treat as "needs initial
assignment" and apply the band normally). Incident history:
[references/checks-staging.md](references/checks-staging.md).

### Broken Wiki-Links → auto-strip the `[[]]` wrapping
For each `[[slug]]` or `[[slug|text]]`, if no `{slug}.md` exists in topics/:
- `[[slug]]` → replace with `slug` text (kebab-case left as-is or humanized
  per context; default: leave as-is)
- `[[slug|Display Text]]` → replace with `Display Text` (the display text
  was the human-readable form already)

Skip if the wiki-link is inside backticks (documentation example).

**Strip the `#anchor` suffix before checking the slug.** Wiki-links of the
form `[[slug#section]]` or `[[slug#section|text]]` point to a section within
`{slug}.md`. The link is broken ONLY if `{slug}.md` doesn't exist — the
anchor portion is a section ID that Obsidian resolves at render time, not
a separate file. Same-page anchor links of the form `[[#section]]` (empty
slug before `#`) are always valid — they target a section in the current
file. Measured false-positive history:
[references/checks-wiki-links.md](references/checks-wiki-links.md).

**Detection regex must exclude documentation:** wiki-links inside ``` ` ``` or
inside fenced code blocks are documentation examples, not real links. Do not
flag them. Use the mask-then-scan walk (mask every backtick span, then scan
the masked line) — implementation in
[references/procedures.md](references/procedures.md).

### Orphan Topics → auto-add to most-relevant MoC (with no-fit floor)
For any topic with zero incoming wiki-links from any other page (including
MoCs), pick a placement using this fit ladder:

1. **Strong fit** — a MoC shares ≥2 tags with the orphan: add to that MoC
   under its most-relevant existing section.
2. **Weak fit** — a MoC shares exactly 1 tag, OR shares ≥2 title words
   with the orphan: add to that MoC under `## Recently Added`.
3. **No fit** — no MoC clears either gate: add an entry to
   `_moc-uncategorized.md`, creating that file if it doesn't exist. This
   is the explicit holding pen — one curated file the user can scan
   periodically — instead of splattering low-confidence cross-references
   across topical MoCs.

Never leave orphans, but never force a placement into an unrelated topical
MoC either — `_moc-uncategorized.md` is the explicit, bounded holding pen
(rationale: [references/checks-wiki-links.md](references/checks-wiki-links.md)).

**Strip `#anchor` suffix before counting incoming links** (same rule as
Broken Wiki-Links above). `[[foo#section]]` in topic B is an incoming
reference to `foo`, not to a separate file called `foo#section`. Without
this, a topic referenced ONLY via anchor links from other topics would
be falsely classified as orphan. Self-references (`[[foo]]` inside
foo.md) do NOT count as incoming.

### MoC Coverage Gaps → auto-add to MoC
For any topic not listed in any MoC, apply the same three-tier fit ladder
as orphans. Same anchor-stripping rule applies: `[[foo#section]]` in a MoC
counts as MoC coverage for `foo`.

### Bare Wiki-Links → auto-convert to display-text
`[[slug]]` → `[[slug|Title]]` using the target's frontmatter `title:` field.
If target doesn't exist, treat as broken link (auto-strip above).

**Anchor handling:** leave `[[slug#anchor]]` and `[[#anchor]]` unchanged.
A bare anchor link's natural display text is the section name, which
Obsidian renders correctly from the anchor. Adding `|Title` would
overwrite the section context with the page title, which is wrong.

### Generated Link Graph → recompile from markdown
Run this **after** all wiki-link edits above (broken-link strips, bare-link
conversions, orphan/MoC additions, merges) — they change the markdown, and
`generated/graph.json` must be recompiled from the new state:

```bash
python3 ~/Documents/knowledge-base/tools/kb.py build
python3 ~/Documents/knowledge-base/tools/kb.py check
```

`tools/kb.py` recomputes the graph from the markdown source of truth on every
build; `check` is the CI gate and compares every artifact byte for byte
(drift history: [references/checks-wiki-links.md](references/checks-wiki-links.md)).
Add `generated/`, `README.md`, and `Home.md` to this run's touched-files set
so Step 5 stages them. Run this recompile AFTER the orphan-adoption check,
not before — orphan adoption adds the inbound MoC links that the rebuild
then records.

### Stale Topics → DROPPED
Not run. Age-since-update is not a signal (rationale:
[references/procedures.md](references/procedures.md) "Dropped and relocated checks").

### Open-Status Markers → auto-flip resolved, auto-date undated, count the rest
NOT the age-based check dropped directly above — this one is deterministic and
marker-based. State-claim entries carry `> **STATUS:** OPEN (since DATE)` markers
(KB CLAUDE.md "Status markers for state-claims" convention). The analyzer
reports them as `open_markers` (dated, oldest first) and
`undated_open_markers` (no `(since YYYY-MM-DD)`).
- **Auto-date (deterministic):** for each undated marker, rewrite
  `(since ?)` / missing-since to `(since <suggested_since>)` using the
  analyzer's suggestion (the enclosing dated entry's date, else the file's
  `created:`). Apply it via the bundled `flip_status.py` mutator — do NOT
  hand-edit the marker line. Invocation flags in
  [references/procedures.md](references/procedures.md).
- **Reclassify obvious non-state-claims (judgment):** while editing an
  undated marker, apply the KB CLAUDE.md boundary rules — a roadmap/backlog
  aspiration ("we should build X", "adopt when Y") or an external-API quirk
  with a documented workaround is NOT a state-claim: convert the line to
  `> **Note:** ...` instead of dating it. When unsure, date it and keep it
  OPEN — a dated maybe-gap is recoverable; a wrongly-demoted gap is not
  greppable.
- **Auto-flip (deterministic, within-page only):** for each OPEN marker, if the
  SAME page already has a later dated entry OR an inline `[RESOLVED ...]` /
  `[Superseded]` annotation resolving that exact gap, flip the marker in place to
  `> **STATUS:** RESOLVED <date> — ... [details: <entry/PR>]` plus the garden
  attribution comment. Deciding WHICH marker the evidence resolves is your
  judgment; the rewrite itself is mechanical — apply it via `flip_status.py`
  (invocation in [references/procedures.md](references/procedures.md)), do
  NOT hand-edit. Within-page evidence only — no cross-page inference, so
  false-positives are near-zero.
- **Count the rest + age-band:** add `open-gap markers: N (M over-90d)` to the
  report. The analyzer tags each marker with `age_days`/`age_band` and emits
  `open_markers_over_90d` as the filtered ROW LIST (oldest first, same row
  shape as `open_markers` — it was a count-only int until 2026-08-22, which
  crashed the first consumer that iterated it); surface those rows directly
  (unlikely to self-resolve). Factual inventory — NOT a human-review bucket.
- **Out of scope — world-state reconciliation:** garden does NOT verify markers
  against the world nor flip *cross-page*/external-resolved ones. Within-page
  flipping (above) is the only safe auto-close; world-state reconciliation is
  a SEPARATE pass (boundary rationale:
  [references/checks-backlogs.md](references/checks-backlogs.md)).

### Merge Candidates → auto-merge HIGH confidence only
The analyzer pre-filters pairs into `merge_candidate_pairs` — (a **slug-prefix
relationship** (`litellm-llm-gateway` ⊂ `litellm-llm-gateway-next-steps`) OR
**≥3 distinctive shared title words**) AND **≥2 shared tags** — the tag bar is
applied at the source because the confirmation rule below requires it, so a
below-bar pair is unmergeable by construction. Confirm the pre-filtered pairs
in ONE `mcp__memory-search__memory_search_batch` call (one query per pair,
batched embedding, identical ranking to per-query `memory_search`), NOT
per-topic. Filter calibration history:
[references/checks-backlogs.md](references/checks-backlogs.md).

**Confirmation rule — rank-dominance, NOT an absolute-cosine gate.** Query with
the SMALLER topic's distinctive content; merge ONLY when the SIBLING surfaces
at/near rank 1 above unrelated hits — DOMINANCE across the topic's content,
not one lexically-matching entry. Do NOT gate on
an absolute cosine — `memory_search` returns a whole-corpus ranking (~0.3-0.5
even for related topics), so ">0.90" is unreachable (why neither tool gives a
pairwise cosine: [references/procedures.md](references/procedures.md) "Merge
confirmation"). This rarely fires, so **0 merges is the expected outcome**.

When the rule fires, auto-merge: insert entries from the smaller file into the
larger **in chronological order by entry date** (parsed from the
`(YYYY-MM-DD)` suffix on each dated H2). Naive append would create a
non-monotonic timeline that hurts narrative coherence. After insertion, add a
redirect note to the smaller file's body, then delete the smaller file. If the
sibling does not dominate rank 1 (or the pair shares <2 tags), drop silently.

**MCP fallback:** if the memory-search MCP is unavailable or the batch call
times out (fall back to per-pair `mcp__memory-search__memory_search` only if
the batch tool alone is missing), skip the merge-candidates check entirely
for this run and note "merge candidates skipped — memory-search MCP
unavailable" in the report. Do not retry across topics — one timeout
indicates the MCP is down and 100 retries waste turns. Garden must still
complete the rest of the checks; merge candidates are an optimization,
not a requirement.

### Cross-File Fact Duplication → append to canonicalization-candidates.md (no in-place rewrite)
Backlog-only since 2026-06-08 — the prior auto-rewrite caused semantic
inversions (history in [references/procedures.md](references/procedures.md)).

Scan for concrete identifiers (ARNs, IPv4/IPv6 addresses, fully-qualified
domain names) appearing in ≥3 topic files. For each, append an entry to
`canonicalization-candidates.md` (in `~/Documents/knowledge-base/topics/`)
with: the identifier, the files it appears in, and a one-line context
excerpt from each occurrence. The garden report notes the count only; the
user reviews the backlog manually.

Exclusions (do not flag):
- Port numbers, regex patterns, version numbers — high false-positive rate.
- Identifiers inside backticks or fenced code blocks.
- Identifiers in a line containing any of: "old", "former", "retired",
  "deprecated", "previous", "historical", "archived" within ±5 words.

### Soft-Chunk Sections → auto-split into concept-named `###` subsections

`scripts/analyze.py` reports every **leaf chunk** in the **2500–3000 character**
band (`soft_chunks`). **This is the only chunk band garden handles** — the CI
gate already hard-fails leaf chunks **>3000c** at PR time. Always use the
leaf-chunk counts from `analyze.py` (it shares the CI gate's algorithm);
computing chunk size any other way produces phantom violations — rationale in
[references/procedures.md](references/procedures.md).

Auto-resolution: split each soft-band leaf chunk into **concept-named `###`
subsections** per the KB CLAUDE.md remedy ("Split it into `###` sub-sections
with concept-named headers — not Part 1 / Part 2"). Add the garden attribution
comment on the first inserted `###` line. Only split where the section has a
natural conceptual seam; if a soft-band section is a single indivisible
concept (a table, one tightly-coupled argument), leave it — 2500–3000c is
advisory, not a CI failure, so an un-splittable soft chunk is acceptable and
is simply re-reported (count only) next run. Never split a chunk below 2500c
(no benefit) and never touch a >3000c chunk silently — those are CI hard
failures and must be surfaced loudly in the report, not buried as a soft fix.

**Disposition accounting is mandatory.** Every soft chunk in the analyzer's
`soft_chunks` list gets exactly one disposition this run: `split` or
`left-indivisible`. The report line must reconcile: split + left =
analyzer count. If the counts don't reconcile, the run is not done
(the silent-drop incident this prevents:
[references/checks-chunks.md](references/checks-chunks.md)).

### Non-Canonical Dated Headers → auto-normalize
The analyzer reports `noncanonical_dated_headers` — date-FIRST entry headers
(`## 2026-06-07: Title`, `## 2026-06-07 — Title`) that are invisible to the
shared dated-entry regex, corrupting both the stage count and the suspect-MoC
classification. Each row carries a deterministic `suggested` rewrite to the
canonical `## Title (YYYY-MM-DD) [marker]` shape (KB CLAUDE.md "Topic
structure"); apply it verbatim and add the attribution comment. A non-zero
count means a producer regressed — note the producing file pattern in the
report (normalization history:
[references/checks-chunks.md](references/checks-chunks.md)).

### Stale `updated:` → auto-bump
The analyzer reports `stale_updated` — files whose frontmatter `updated:` is
older than their newest dated entry. Set `updated:` to the newest entry date
(never lower it) and add the attribution comment inside the frontmatter.

### Current-Understanding Coverage → auto-synthesize missing, auto-regenerate stale
The analyzer reports `cu_missing` (topics with 8+ dated entries lacking a
`## Current understanding` section) and `cu_stale` (sections whose trailing
`<!-- current-understanding regenerated: DATE -->` comment predates the
topic's newest dated entry — /capture's Step 4a.2 missed a regeneration).
Auto-resolution for both: read the FULL topic and write/rewrite the section
per the KB CLAUDE.md "Current understanding (evergreen topics)" convention —
first `##` section, present tense, synthesized strictly from the entries (no
new claims), consistent with STATUS markers, ≤2,400 chars, regenerated
comment set to today. Hubs, `maintenance` trackers, and hook-managed logs are
exempt (the analyzer already filters them). This is judgment work the
analyzer cannot do — it is the one garden check where the fix is synthesis,
so apply the same faithfulness bar as /capture: every claim traceable to an
entry below, and when entries conflict unresolved, say so rather than pick.

### Hub-Split Candidates → append to hub-split-candidates.md (dedup) + surface
The analyzer reports `hub_split_candidates` — topics over ~30 `##` sections or
~80 KB, which bury their own concepts at the topic level even when every
chunk is size-compliant (KB CLAUDE.md "Garden maintenance"). Splitting one is
a dedicated session (hub + concept-named sub-topics, entries moved verbatim),
NOT a garden auto-fix. For each candidate NOT already listed in
`hub-split-candidates.md` (in `~/Documents/knowledge-base/topics/`, a
`maintenance`-tagged backlog matching `canonicalization-candidates.md`),
append a dated `## <slug> (YYYY-MM-DD)` entry with its section-count + KB size;
create the file if absent. Dedup by slug — a candidate already listed is not
re-appended (that is the fix for the re-flag-every-run accumulation). Still
list them in the report so the user can schedule the split; remove an entry
from the backlog once its split ships. Do not attempt the split in-run.

### Harness Pruning → run `/harness-prune`
Not in garden's scope (ownership history:
[references/procedures.md](references/procedures.md) "Dropped and relocated checks").

### Agent-Memory Topic Sweep → staleness + STATUS markers (report-only)

B7/F4 decision (2026-06-10): `~/.claude/agent-memory/topics/` follows the
same STATUS-marker convention as the KB but is NOT part of the KB staging
dir — this check reads it in place and only reports (no auto-edits, no
push; fixes go through normal claude-config commits).

1. **Staleness**: run `python3 "<skill-dir>/scripts/analyze.py"
   ~/.claude/agent-memory/topics` and report topics whose newest dated
   entry is >30 days old (count + worst three).
2. **Open STATUS markers**: `grep -rn 'STATUS:\*\* OPEN' ~/.claude/agent-memory/topics/`
   — list each open state-claim with its since-date. Flag any older than
   30 days as reconciliation candidates.
3. **Size cap** → covered by Step 3b's cross-surface sweep. Do not run a
   separate 8KB check.

## Step 3b: Size Sweep → structural split, NEVER trim

```bash
python3 "<skill-dir>/scripts/size_sweep.py"          # human report
python3 "<skill-dir>/scripts/size_sweep.py" --json   # machine-readable
```

When the sweep flags an over-cap file whose remedy is a MULTI-WAY split, plan it
with the companion script — it reports the decomposition, never writes:

```bash
python3 "<skill-dir>/scripts/split_plan.py" <file>          # proposed siblings + feasibility
python3 "<skill-dir>/scripts/split_plan.py" <file> --json   # machine-readable
```

`split_plan.py` answers the question `size_sweep.py` does not: *how many* siblings
does this file actually need, and is every one of them under cap? It emits a
PLAN and names what a human must decide — the subdomain taxonomy. Apply with
review; garden never auto-writes a file split (measured multi-way-split
evidence: [references/checks-chunks.md](references/checks-chunks.md)).

One pass over the four capped surfaces (`rules/`, `skills/*/SKILL.md`,
`agent-memory/topics/`, KB topics + its chunk gate). Reports; never edits.

**SPLIT, NEVER TRIM** — content behind a pointer costs **zero** until read,
so splitting preserves evidence *and* removes cost (source verification:
[references/checks-chunks.md](references/checks-chunks.md)).
Un-splittable → report `left-indivisible`.

**Dispositions**: KB chunks **AUTO-SPLIT** (Step 3's soft-chunk pass);
everything else **BACKLOG**. Multi-way splits are a dedicated session, like a
KB hub-split. Remedy shapes, per-surface rationale, exemptions:
[references/procedures.md](references/procedures.md) "Step 3b size sweep".

**Never report aggregate token load here** — `/context-budget` owns it and it
dominates (`rules/` ≈ 624 KB / 155K tokens **every** session, so descoping one
43 KB rule moves <1%). This step finds wrong *shape*, not total cost.

### Size is not the finding — DELIVERY PATH is

Triage by **what is silently truncated**, never by bytes. A cap is a defect only
where a mechanism enforces it: a hook-**injected** topic is capped at 10,000
chars (hard), while one reached by `Read` is merely a token cost. The sweep
stamps each row `INJECTED` / `read-only` / `DELIVERY UNKNOWN`.

Sort **severity before size**, never render UNKNOWN as safe, and verify every
cap against its vendor or enforcing hook. Full reasoning, measurements, and
the three failure modes:
[references/procedures.md](references/procedures.md) "Delivery path is the finding".

<!-- SKILL.md LENGTH: restructured 2026-08-22 into check-FAMILY references
     (checks-staging / checks-wiki-links / checks-chunks / checks-backlogs).
     Operative rules and eval-pinned literals stay HERE; measured history and
     incident rationale live in the family files. When adding to a check,
     keep the rule inline and put the narrative in its family reference —
     do not let incident prose re-accumulate in this file. -->

## Step 4: Output the report

Emit the `=== Garden Health Report ===` exactly per the template in
[references/procedures.md](references/procedures.md): inventory + stage +
the full per-check auto-fix breakdown (every check
above gets a count line, including the S/W/U placement breakdowns and the
soft-chunk split + left-indivisible reconciliation), the open-gap and
overstaged inventories, hub-split candidates, hard-chunk violations,
classification flags, and any skipped checks with reasons.

In `audit` mode, replace "Auto-fixes applied:" with "Would apply:" — the
same counts and the same breakdowns, but no edits or push happen.

That's the entire report. No "human review" section.

## Step 5: Push

In `audit` mode, skip this step entirely.

### Before pushing a SPLIT or RELOCATION: run the count-and-pin gate

A structural fix changes a **file count** and moves prose some other file
**pins** — both fail at CI, never at edit time.

**When a count claim breaks, DELETE the claim — do not bump it** (a
hand-maintained count in prose is a drift generator; removal is sanctioned).
Bump only a count that is genuinely load-bearing, and say why.

REQUIRED before the commit, **in the worktree holding the change**:

```bash
python3 bin/architecture-drift-check.py     # counts — a split adds a file
python3 bin/preflight-skill.py              # full tier; --fast skips 2 gates
python3 -m pytest scripts/ -q               # NOT a preflight gate; run it yourself
grep -rn "<the moved prose>" tests/ scripts/ bin/ .github/
```

**A test that reads `$HOME` cannot fail on this host** (`~/.claude` IS the
checkout, so `Path.home()` tests exercise the DEPLOYED copy). Reproduce the
runner before pushing: `HOME=/tmp/fakehome python3 -m pytest <the tests>`.

A relocation's last consumer is a **test asserting the literal text**. When you
find one, repoint it at the *invariant* (the boundary that must stay visible),
not the prose — else the next rewording breaks it again. Which gate catches
which failure, the delete-don't-bump rationale, and the measured instances:
[references/procedures.md](references/procedures.md) "Count-and-pin gate".

Otherwise, always push if any fix was applied. From
`~/Documents/knowledge-base/` (already on the `garden/<date>` branch cut in
Step 1): **stage only the touched-files list tracked during Steps 2-4**
(never `git add .`/`-A`; assert `git diff --cached --name-only` equals the
touched set) → commit → push → PR →
`gh pr merge --auto --squash --delete-branch`. Full
step-by-step flow in [references/procedures.md](references/procedures.md).

**Files a session hook re-dirtied mid-run are NOT garden-touched.** Session
hooks append to `session-friction-patterns.md` *while* garden runs; do NOT fold
it into the garden commit — stage only garden's own touched set (folding it in
breaks the `cached == touched set` assertion above; happened 2026-06-16).

**Fallback (narrow trigger):** if `gh pr merge --auto` fails AND the
stderr matches the literal phrase `cannot pull with rebase: unstaged
changes` (the known race with `session-friction-patterns.md`), retry once
without `--auto`. Do NOT widen this fallback to any other error — that
would bypass branch protection; surface the error and stop (detail in the
reference).

If no fixes were applied, skip the push — just emit the report.

---

## Success Criteria

- Every detected issue has an auto-resolution path (in-place fix OR backlog
  append); no "human review" bucket exists in the output
- Running garden twice on the same input converges — the second run is a
  no-op against the post-first-run state (idempotent in the
  "converges-after-one-run" sense, not "zero side-effects" — the first run
  writes fixes; the second run finds nothing more to do)
- Partial file errors do not abort the entire pass — skip the bad file,
  continue
- Push happens automatically when any fix was applied; no Y/n confirmation
- Broken-link and bare-link regexes correctly skip documentation examples
  (wiki-links inside backticks or fenced code blocks)
- Entry-counting regex matches `^## .* \(\d{4}-\d{2}-\d{2}\)` exactly, so
  /capture's stage-promotion decision and /garden's stage-audit decision
  agree on every topic file
- `audit` mode runs the full detection pass without any writes or PR
- Cross-file fact duplication appends candidates to a backlog only; never
  rewrites identifiers in-place
- Orphan/MoC-gap placement uses the strong/weak/uncategorized ladder; no
  topical MoC receives an entry with zero tag overlap and <2 shared title words
- Merge candidates are checked only on the analyzer's `merge_candidate_pairs`
  ((slug-prefix or ≥3 shared title words) and ≥2 shared tags), never
  once-per-topic across the corpus, and confirmed in one batched
  memory-search call
- Merge confirmation uses rank-dominance (sibling at/near rank 1, dominance
  not a single lexical entry hit), never an absolute-cosine gate (unreachable
  via `memory_search`); 0 merges expected
- `stage_pinned: true` topics never appear in stage_mismatches or
  stage_overstaged, and are never demoted
- The no-auto merge fallback fires only on the specific
  `cannot pull with rebase: unstaged changes` stderr — never on broader
  failures that would bypass branch protection
- All garden-authored edits include the `<!-- garden: YYYY-MM-DD
  action:<check-name> -->` attribution comment
- Soft-chunk dispositions reconcile: split + left-indivisible = the
  analyzer's `soft_chunks` count — no silent drops
- Stage demotion never fires from a band recount; `stage_overstaged` is
  report-only
- Zero-dated prose topics (absorb profiles, reference pages) are classified
  `topic` and flow through orphan/MoC-gap checks; `suspect_moc` requires
  MoC shape (link-list ratio ≥ 0.5)
- Every OPEN marker in the corpus ends the run dated (`since YYYY-MM-DD`) —
  `(since ?)` never survives a garden pass
- Open-gap markers >90 days old are surfaced explicitly (oldest first); garden
  never reconciles markers against world-state (no cross-page / external flips)
- `stage_overstaged` excludes hubs (`## Sub-topics`) and zero-dated reference topics (≥3 `## ` sections)

## Examples

See [references/examples.md](references/examples.md) for worked runs
(weekly tending, healthy garden, audit dry-run).
