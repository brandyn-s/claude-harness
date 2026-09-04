---

name: capture
description: "Record session decisions, lessons, and breakthroughs as dated entries in the digital garden."
when_to_use: 'Use when the session produced decisions, lessons, debugging breakthroughs, failed approaches, or cross-cutting patterns worth preserving. Extracts knowledge from conversation context, matches to existing topic pages in the digital garden, and appends dated entries. Trigger phrases: "capture", "document this", "lesson learned", "write up", "ADR", "add to knowledge base". Do NOT use for API reference patterns (use topic files), or task state (use checkpoint skill).'
argument-hint: "[omit for auto-capture, or 'push' to sync, or 'list' to browse]"
effort: medium
allowed-tools: Read Write Edit Bash Grep Glob mcp__memory-search__memory_search mcp__memory-search__memory_search_batch AskUserQuestion
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires memory-search MCP for knowledge base append and dedup check.
  requires:
    - mcp: memory-search
    - cli: git
    - cli: gh

---

## capture

# Capture -- Digital Garden Knowledge Base

A digital garden where knowledge grows organically. Each topic is a living
page that accumulates decisions, lessons, patterns, and failed approaches
as dated entries over time.

**Staging directory:** `~/Documents/knowledge-base/topics/` (this is a git checkout of the `example-org/claude-knowledge-base` repo)
**Push mechanism:** standard `git add / commit / push` + `gh pr create` + `gh pr merge --auto --squash` from inside the staging directory

---

## Step 0 — Preconditions (run before any mode)

Before doing anything else, verify the local environment:

1. **Staging directory present**: `test -d ~/Documents/knowledge-base/topics`.
   If absent, stop and tell the user:
   "Knowledge-base staging dir missing at `~/Documents/knowledge-base/`.
   Clone it first: `git clone git@github.com:example-org/claude-knowledge-base.git ~/Documents/knowledge-base`."
   Do NOT attempt to create the directory automatically — the user must opt
   into cloning a remote repo.
2. **`gh` CLI present** (only required when push is in scope — auto-capture
   Step 5 and the `push` mode): `command -v gh >/dev/null 2>&1`. If absent,
   complete the local write (Steps 1-4) but stop before Step 5's PR commands
   and tell the user: "Wrote entries to `~/Documents/knowledge-base/topics/`
   but `gh` CLI is missing — install it (https://cli.github.com/) then run
   `/capture push` to open the PR."
3. **`git` CLI present**: assumed; if absent the staging directory clone
   wouldn't exist.
4. **In-flight prior-session work**: from inside the staging dir, run
   `git status --short` and `git rev-parse --abbrev-ref HEAD`. If the
   working tree has uncommitted modifications on a non-`main` branch
   AND the most-recent modification mtime is more than 2 hours old,
   the repo is mid-flight from a prior session that didn't push-and-merge.

   Surface the state to the user before proceeding:
   > "Knowledge-base repo has stale uncommitted work on branch `<branch>`
   > from <hours>h ago. /capture would either co-mingle this session's
   > entries with that work (messy PR) or work around it in a worktree
   > (clean PR but the prior work stays stale). Pick: (a) merge or
   > abandon the prior branch first, (b) proceed with a worktree off
   > origin/main, isolating new work."

   Default to (b) — create a worktree at
   `~/worktrees/kb-capture-<date>-<session-id-prefix>` off `origin/main`
   (`git -C ~/Documents/knowledge-base worktree add ...` — always `-C`, never
   bare, so a cwd left in a sibling repo cannot retarget it), write all new
   entries there, push + PR from the worktree. The prior branch is left
   untouched; the user can resolve it on their schedule.

   **Include the session-id prefix in the name.** A date-only name collides
   with any concurrent session doing the same thing, and `worktree add` then
   fails on a path another live session owns. The date alone is not unique;
   sessions are. Also branch-name the worktree for the *content*, not the date
   (`capture/<topic-slug>`), so two same-day captures don't collide at the
   branch level either. (Both collisions on record: `references/run-history.md`.)

Skipping Step 0 leaves the user with an orphan branch pushed to origin and
no PR — the failure mode this gate exists to prevent.

---

## Modes

### No arguments -- Auto-Capture (primary mode)

This is the main interaction. The skill reads the conversation context and
does the work.

**Step 1: Extract knowledge from conversation**

> **Compaction awareness**: If the conversation starts with a compaction boundary
> (summary of earlier messages), early-session learnings may be missing from
> context. Tool results and debugging details are not preserved in compaction
> summaries. If the session was long and context seems thin, supplement by
> reading the session transcript JSONL on disk.
>
> **Compaction boundary detection**: the boundary appears as the first message
> in context and begins with the literal sentence "This session is being
> continued from a previous conversation that ran out of context." (in the
> underlying transcript it is a JSONL entry with `isCompactSummary: true`,
> but only the rendered text is visible in conversation context). The boundary
> message does NOT contain an inline transcript path. To find the source
> transcript, glob `~/.claude/projects/*/*.jsonl` and select the file named for
> THIS session's id (`$CLAUDE_CODE_SESSION_ID`, authoritative) — do NOT pick the
> most-recent-by-mtime: under concurrent sessions that is frequently a DIFFERENT
> session's transcript. mtime is a fallback only.
> If `$CLAUDE_PROJECT_ID` is set, scope the glob to
> `~/.claude/projects/<project-id>/*.jsonl` (the project ID encodes the working
> directory with `/` replaced by `-`, e.g. `-home-user-claude-config`).

Read the current conversation history. Identify what was learned, decided,
discovered, or tried-and-failed in this session. Look for:

- Architectural decisions and why they were made
- Debugging breakthroughs and what led to them
- Failed approaches and why they didn't work
- Cross-cutting patterns or meta-observations
- Strategic insights about the system

If the conversation is long, focus on the most significant learnings -- not
every minor detail.

**Capture-worthy** (always capture):
- Decisions with alternatives rejected
- Debugging breakthroughs (>30 min investigation)
- Cross-cutting patterns (applies to 2+ systems)
- Failed approaches (someone else could repeat the mistake)
- Strategic insights about the system

**Not capture-worthy** (skip):
- Routine config changes, typo fixes
- One-liner bug fixes with obvious causes
- Information that belongs in code comments
- Facts already documented in topic pattern files or agent memory

**Step 2: Scan existing topic pages and build link index**

Build the index from the **generated catalog, not the bodies**: read
`~/Documents/knowledge-base/generated/catalog.json` in one pass — each topic
entry carries `id`, `title`, `tags`, and `description` — instead of globbing and
opening ~300 topic markdown files. Read `generated/graph.json` for `links_to`
edges when you need the link structure. Both are compiled from `topics/*.md` by
`tools/kb.py`, so they are small, structured, and current. Exclude `_moc-*`
(dashboards are already absent from the catalog). If `generated/` is absent
(older checkout), fall back to globbing `topics/*.md` and reading H1 titles.

Graph edges are forward-only (`links_to`); there is no `linked_from` field —
reverse links are derived at query time by inverting the edge list.

Build a **link index** — a mapping of topic slugs to their H1 titles:
```
obo-authentication → "OBO Authentication"
mcp-gateway-architecture → "MCP Gateway Architecture"
hook-design-patterns → "Hook Design Patterns"
```
This index is used in Step 4 for wiki-linking.

**Step 3: Match knowledge to topics**

For each piece of knowledge extracted in Step 1:

- Compare keywords/concepts against existing topic filenames and titles
- In addition to filename/title keyword matching, search semantically. When
  the session yielded **multiple** pieces of knowledge, collect one query per
  piece (the knowledge summary) and issue them in a **single**
  `mcp__memory-search__memory_search_batch(queries=[...], scope='all', limit=5)`
  call — the queries are independent of each other's results, so one batched
  round-trip replaces N serial `memory_search` calls at identical quality. (For
  a single piece, plain `memory_search` is fine.) Filter each result set to
  `knowledge-base/topics/` sources. A semantic match > 0.7 cosine is a
  candidate even if keywords don't overlap.
- If a strong match exists: plan to append a new dated H2 entry to that page
- If no match: plan to create a new topic page with a descriptive slug

For each matched topic page, assess its maturity before reading:
- **Seedling** (1-2 H2 entries): read the last 2 entries — full orientation is quick.
- **Budding** (3-7 H2 entries): read the FULL page. Entries 1-3 may cover the
  same insight from an earlier angle that the last 2-3 entries don't reveal.
- **Evergreen** (8+ H2 entries): read the FULL page. Semantic dedup (cosine
  threshold) misses restatements in different terminology; reading the full
  narrative catches what thresholds miss.

When several pages matched, issue their full-page Reads **in parallel** (one
batch of Read calls in a single turn), not one at a time.

Draft the new entry to build on -- not repeat -- what's already there.

**Dedup gate** (combined keyword + semantic). The dedup query below and the
Step 4a contradiction query are both derived from the proposed entry and are
independent of each other's results, so when multiple entries are proposed,
collect all their dedup + contradiction queries and issue them in **one**
`mcp__memory-search__memory_search_batch` call, then apply the per-entry gates
to each result set. This replaces up to 2×(entries) serial searches with a
single round-trip. For each proposed entry:
1. Read the existing H2 entry titles on the matched page. If any title has
   significant keyword overlap, it's a candidate duplicate.
2. Run `mcp__memory-search__memory_search(query=<entry summary>, limit=5)`.
   If a result scores > 0.85 cosine similarity covering the same concept:
   **skip** and report "Skipped: [title] — equivalent to [matched title]
   in [file] (similarity: X.XX)." *(See `references/tuning-notes.md` for
   the 0.7 / 0.85 / 0.65 threshold rationale and how to log evidence
   when adjusting them.)*
3. If similarity is 0.55-0.85: read the matched entry. Only proceed if
   the proposed content adds genuinely new information. Otherwise skip or
   update the existing entry.
4. If similarity < 0.55 and no keyword title overlap: proceed normally.

**Fallback when `mcp__memory-search__memory_search` is unavailable** (tool errors,
not declared in this session, or returns no `score` field) — run the script, do
NOT hand-roll it and do NOT drop straight to Grep:

```bash
python3 ~/.claude/bin/kb-dedup.py "<entry summary>" "<second entry summary>" ...
```

`bin/kb-dedup.py` queries the SAME index the MCP server wraps
(`~/.claude/memory-search.db`) over FTS5/BM25, so ranking survives; Grep is a
needless further downgrade. It accepts multiple queries in one invocation (the
batch equivalent), takes `--scope all` for distill's rules/agent-memory/skills
sweep, and `--json` for post-processing. Exit 3 means the index itself is
unusable — only then fall back to Grep across
`~/Documents/knowledge-base/topics/**/*.md`.

Two things the script exists to stop you re-deriving: the index is a local
SQLite DB (so it is directly queryable), and FTS5 treats bare punctuation as
syntax — a query containing `re-read` or `read:analytics` raises
`no such column: read`, which reads like a schema bug and is really a tokenizer
one. The script quotes every term.

BM25 is not cosine: **the 0.85 / 0.7 / 0.65 thresholds do not transfer.** Judge
by rank and by reading the matched entry. Report in the final summary that
semantic dedup ran in DEGRADED mode so the user knows which gate was weakened.

A single invocation may propose updates to multiple pages.

**Step 4: Draft the update (with wiki-links)**

For each topic page being updated or created, draft the content:

- **Existing page**: Draft a new H2 section with today's date and a descriptive
  title. The entry is free-form -- it can describe a decision (with alternatives),
  a lesson, a pattern, or a failed approach. Keep it concise but complete.

- **New page**: Draft the full file with YAML frontmatter, an H1 title, a
  one-line description (as a blockquote), a horizontal rule, and the first
  dated H2 entry.

- **State-claim entries** — an entry asserting a *mutable open state* (a gap,
  blind spot, "X is broken / empty / not yet wired / pending"): add a greppable
  status line as the entry's first body line, per the KB CLAUDE.md "Status
  markers for state-claims" convention:
  `> **STATUS:** OPEN (since YYYY-MM-DD) — <what's unresolved + the resolution trigger>`.
  Timeless lessons/decisions get NO marker. The marker is what lets the Step 4a.1
  resolution sweep and /garden's open-marker audit find and flip this entry when
  the state is later fixed — instead of it rotting as stale "it's broken" prose.

**Oversized entry (>2,500c) → PREFER SPLITTING over TRIMMING** — promote a distinct
concept/case-study to its OWN new topic with a parent pointer (1st choice), then `###`
sub-sections, then a follow-up dated entry; trim only as a last resort, never deleting
load-bearing detail. Full preference order in `references/topic-format.md` "Oversized Entry".

**Run the pre-write budget BEFORE the Write, not `kb.py check` after it.** You are
holding the drafted entry text and you already read the page in Step 3, so every
number the checker will complain about is computable now:

```bash
python3 ~/.claude/bin/kb-entry-budget.py <topic-slug> --entry-file /tmp/claude/<draft>.md
```

The helper resolves `tools/kb.py` and `topics/` from the invoking knowledge-base
Git worktree, so its budget applies to the same bytes you will edit. Outside a
KB worktree it falls back to `~/Documents/knowledge-base`; use `--kb-root
<checkout>` to bind a non-Git or scripted invocation explicitly.

It reports, per drafted entry: the resulting **retrieval-chunk size** against the
3,000c HARD limit `kb.py` enforces (measured per H2/H3 section — an H3 starts a new
chunk, which is *why* `###` splitting is a real fix and not cosmetic), the resulting
**dated-entry count** and whether it crosses the stage threshold or the 8-entry
`## Current understanding` requirement, and the size of that section if it exists.
Exit 1 means a `kb.py check` failure is already guaranteed — restructure the draft
now, while the content is still in your head.

WHY: discovering the limits from `kb.py check` costs a rewrite of finished prose,
and every number it checks is knowable before the first Write
(`references/run-history.md`).

See `references/topic-format.md` for the full topic page format,
wiki-linking rules, alias generation, confidence tags, and session comment format.

When appending to an existing page, also update the `updated` field in the
YAML frontmatter to today's date. If the entry count crosses a stage
threshold, update `stage`:
- 1-2 entries → seedling
- 3-7 entries → budding
- 8+ entries → evergreen

**These bands set a NEW page's INITIAL stage too — count its own entries, never
default to `seedling`.** A new page is routinely born with several dated entries
(a session's findings on one theme), so `seedling` is wrong the moment it is
written. Authoring pages via a script to dodge the 2,500-char write guard bypasses
this checklist — re-read before committing (`references/run-history.md`).

**Recovery when YAML frontmatter is broken** (missing `---` fence, unparseable YAML,
or missing required fields like `updated`/`stage`): do NOT append silently — a write
on top of malformed frontmatter compounds the corruption. Instead:
1. Report the parse error to the user with the offending lines.
2. Offer to repair the frontmatter (regenerate from the topic-format reference)
   before appending the new entry.
3. If the user declines repair, append the new H2 entry to the body but leave
   the frontmatter untouched and surface "frontmatter unrepaired" in the summary
   so downstream `/garden` runs can catch it.

After writing, verify the entry count by counting dated H2 lines matching
the pattern `^## .* \(\d{4}-\d{2}-\d{2}\)` — only dated entries, not
structural headings. Cross-check against the stage threshold. Do not rely
on mental counting or raw H2 counts (which include non-entry headings).

**Step 4a: Contradiction check (mandatory gate before Step 5)**

For each proposed entry, BEFORE writing:

1. Run `mcp__memory-search__memory_search(query=<entry's central claim phrased as the OPPOSITE>, limit=5)`. The query phrasing matters — search for entries that would CONTRADICT the new finding, not entries that match it. **For a multi-claim entry, run ONE opposite-query per DISTINCT factual claim, not just the headline** — a single entry-level query misses contradictions to secondary claims (`references/run-history.md`).
2. For each result with cosine > 0.65 sourced from the SAME topic page being updated:
   - Read the matched entry's full text
   - Determine whether the new entry's claim contradicts the prior entry's claim (not merely refines or extends it)
3. If contradiction confirmed, REQUIRE one of the following before proceeding to Step 5:
   - **(a) Inline annotation on the prior entry**: edit the prior entry to insert `[Superseded — see entry from YYYY-MM-DD: <new-entry-title>]` immediately after its title, AND append the new entry with title `Correction: <topic> (YYYY-MM-DD)`
   - **(b) Refinement framing**: if the contradiction is partial (the prior entry was scope-correct but the new one extends/qualifies it), title the new entry `Refinement: <topic> (YYYY-MM-DD)` and add `[Refined by entry from YYYY-MM-DD below]` annotation on the prior
4. If neither (a) nor (b) is applied, do NOT write the new entry. Surface the contradiction to the user and ask which framing fits.

**External vendor-behavior claims need a SOURCE check, not just a contradiction query.** A claim about how a third-party system behaves (AWS/IAM/API/deploy-pipeline semantics, condition-key resolution, response shapes) can be confidently wrong AND have no same-page entry that happens to contradict it — so it sails through the cosine gate and ships. Before writing such a claim, verify it against the vendor doc or a 30s live test (per `verify-before-assuming.md` "asserting vendor-system behavior"). The incidents behind this gate: `references/run-history.md`.

**Skip when**: the new entry's claim is genuinely orthogonal to all prior entries (no contradiction surfaced by the memory_search). Most entries skip 4a; the gate only fires when contradiction is detected. (The external-vendor-fact source check above is NOT skippable for vendor-behavior claims.)

**Step 4a.1: Resolution sweep (mandatory when this session RESOLVED something)**

Step 4a catches a stale state-claim only when you happen to write a new entry on the SAME page — it's opportunistic. This step is the proactive complement: when the session RESOLVED something (closed a gap, fixed a documented bug, shipped a blind-spot fix — including resolutions carried in from a /retro distill bridge), reconcile the KB's open-state claims BEFORE Step 5:

1. `grep -rn 'STATUS:\*\* OPEN' ~/Documents/knowledge-base/topics/` — lists every gap the KB currently claims is open (deterministic; the marker convention exists for exactly this).
2. `mcp__memory-search__memory_search(query=<the thing resolved>, limit=5)` — catches legacy entries that predate the marker convention (un-tagged prose blind-spots).
3. For each match describing something THIS session resolved: flip its `STATUS:** OPEN` line in place to `STATUS:** RESOLVED YYYY-MM-DD — <how> [details: PR/entry]` (for a legacy un-tagged entry, add the RESOLVED marker plus a one-line annotation on the prior claim). Same (a)/(b) discipline as Step 4a.
4. Stage the flipped files alongside the new entries in Step 5.

**Skip when**: the session resolved nothing (pure new-knowledge capture). This fires on fix/close/resolve sessions — which /retro-after-/distill almost always is.

WHY: a distill-only pass persists the FIX but leaves the stale "it's broken" description standing — the rot behind this corpus's many reactive `[Superseded]`/`[RESOLVED]` annotations (`references/run-history.md`).

**Step 4a.2: Regenerate `## Current understanding` (topics with 8+ dated entries)**

For each topic page you are appending to, after drafting the new entry:

1. If the page HAS a `## Current understanding` section (first `##` section,
   per KB CLAUDE.md "Current understanding (evergreen topics)"): regenerate it
   IN PLACE so it reflects the post-append state — present tense, synthesized
   strictly from the entries (including the one you are adding), consistent
   with the STATUS markers, ≤2,400 chars, and update the trailing
   `<!-- current-understanding regenerated: YYYY-MM-DD -->` comment to today.
   You already read the full page in Step 3, so this costs no extra reads.
2. If the page LACKS the section and your append takes it to **8+ dated
   entries**: create it (same rules; insert immediately after the `---` under
   the blockquote). Hubs, `maintenance` trackers, and hook-managed logs are
   exempt.
3. Never let the section contradict an entry or a marker — when uncertain,
   say less and point at the entry.
4. **Re-run `kb-entry-budget.py <slug>` (no `--entry-file`) AFTER regenerating.**
   The pre-write budget in Step 4 measured the drafted ENTRY; regenerating the CU
   is a SECOND write to the same page, and on a soft-split CU it lands inside one
   `###` sub-section rather than spreading across them — it can push that
   sub-section past the 3,000c hard limit on its own (`references/run-history.md`).
   The checker names the sub-section to grow and its exact headroom, so read that
   line BEFORE choosing where the paragraph goes.

WHY: dated entries are history; retrieval needs state. The synthesis section
is the chunk a model should land on first (memory-search boosts the exact
title `Current understanding` when `MEMORY_SEARCH_STATE_BOOST` is enabled),
and an append without regeneration leaves it ranking ABOVE the newer entry it
no longer reflects — worse than no section at all. /garden flags staleness
deterministically via the `regenerated:` comment date.

**Step 4b: Link reciprocally and place in a MoC (new pages only)**

A new topic that only links *out* is born an orphan — nothing links back to
it, so it never surfaces via graph navigation and reads as an orphan in the
typed graph until a later /garden run adopts it. For every NEW topic page:

1. **Reciprocal link**: pick the single most-related existing topic among the
   pages this new page links to, and add a one-line `[[new-slug|Title]]` "see
   also" reference back from that page (in its most relevant existing entry or
   a trailing "Related" line). One inbound link is enough to clear orphan
   status — do not spray links across many pages.
2. **MoC placement**: add the new page to the best-fit MoC using the same fit
   ladder /garden uses — a MoC sharing ≥2 tags (strong fit), exactly 1 tag or
   ≥2 title words (weak fit, under `## Recently Added`), else
   `_moc-uncategorized.md`. This is the inbound link of record.

This does at write time what /garden's orphan-adoption pass otherwise has to
clean up later. Appending to an EXISTING page needs neither step — it already
has inbound links.

**Step 4c: Persist credential identifiers to Keychain (conditional, macOS only)**

Fires only when this session surfaced a credential identifier set or the Keychain incomplete-triplet
sweep finds a fillable gap — most captures skip it, and it never stores a secret VALUE.
Procedure: `references/push-flow.md` "Step 4c".

**Step 5: Write, push, and summarize**

No further approval gate after Step 4a — write immediately (Step 4a is the
only approval gate in the write path, and surfaces a user prompt only when
contradiction is detected; separate prompts fire in Step 0 for stale work and
Step 4 for broken frontmatter):

1. When creating new topic pages AND appending entries that link to them in
   the same invocation, create the new topic files FIRST, then append to
   existing pages that reference them. This prevents broken wiki-links from
   referencing files that don't exist yet.
2. For existing pages: append the new H2 section(s) at the end of the file
3. For new pages: create the file
4. **Run the canonical compiler, then push.** Run, in order:
   `python3 ~/Documents/knowledge-base/tools/kb.py build` then
   `python3 ~/Documents/knowledge-base/tools/kb.py check`
   — `tools/kb.py` is the KB's single parser, validator, generator, and drift
   checker (its CLAUDE.md "Canonical commands"). `build` regenerates
   `generated/*.json` plus the marked regions of `README.md` and `Home.md`;
   `check` re-validates and compares every artifact byte for byte. The
   pre-commit hook and Docs CI run the same `check`, so skipping it just fails
   the commit. Stage `generated/`, `README.md`, and `Home.md` alongside your
   topic files. Do NOT create `topics/manifests/` — per-topic sidecars were
   retired and `check` fails if they reappear. Then the standard git flow — as
   FOUR separate Bash calls, never one chained command (the PreToolUse git
   guards evaluate the whole string against PRE-command state: a chain mixing
   `git checkout -b` with `git commit`, or `git push -u` with `gh pr create`,
   is blocked by `hooks/bash-security-guard.py`; see `rules/git-hygiene.md`):
   first `cd ~/Documents/knowledge-base && git checkout -b capture/<short-slug>`,
   then `git add <files> generated/ README.md Home.md && git commit -m "<subject>"`,
   then `git push -u origin <branch>`,
   finally `gh pr create && gh pr merge --auto --squash --delete-branch`.

   **If you wrote in a worktree (Step 0 path b), drop `--delete-branch`** — use bare
   `gh pr merge --auto --squash`. From a worktree, gh's post-merge "switch to main" step
   fails (`'main' is already used by worktree at <main checkout>`) even though the merge
   itself SUCCEEDS. Verify via `gh pr view <N> --json state` (expect `MERGED`) — do NOT
   trust the command's error — then clean up from the main checkout:
   `git -C <main> worktree remove <wt> --force` + `git -C <main> branch -D <branch>`.

   **Fast-forward preflight (run BEFORE `git checkout -b`), append-vs-append conflicts on a topic
   file, and `mergeStateStatus: DIRTY` recovery:** `references/push-flow.md` "Step 5 push playbook".
5. Summarize: (a) which topics were updated vs created, (b) how many
   outgoing wiki-links were inserted, (c) the growth stage each modified
   page is now at, (d) PR URL if pushed.
6. After completing capture, note in the conversation: "Captured knowledge
   up to this point. If you invoke /capture again in this session, I will
   focus on new content from after this message."

The `claude-knowledge-base` repo requires a PR (org ruleset blocks direct
push to main). Auto-merge queues the merge; GitHub merges once required
checks pass.

### `push` -- Push Only

1. `cd ~/Documents/knowledge-base` and run the standard git+PR flow above
   for any uncommitted changes under `topics/`.
2. Report the PR URL.

### `list` -- Browse Topics

1. Glob `~/Documents/knowledge-base/topics/*.md` and read the H1 title of
   each file. Exclude `dashboard-*.md` files.
2. Present the topic list to the user.
3. Ask if they want to read a specific topic page.

---

## Topic Naming Conventions

- Filenames are kebab-case slugs: `obo-authentication.md`, `hook-design-patterns.md`
- H1 titles are human-readable: "OBO Authentication", "Hook Design Patterns"
- Prefer specific topics over broad ones: `obo-authentication` not `authentication`
- If a topic grows very large (30+ entries), consider splitting it

---

## Success Criteria

- Auto-capture reads conversation context and writes updates with zero questions in the common case; approval gates fire when prior-session work is stale (Step 0), frontmatter is broken (Step 4), or a new entry contradicts existing knowledge (Step 4a) — otherwise zero questions
- Knowledge about the same concept consolidates into a single growing page
- Multi-page updates work (one invocation touches 2-3 pages)
- New topic pages are created when no existing page matches
- Push succeeds with auto-generated README
- No interference with agent memory or pull-repos
- When deleting or renaming topic/pattern files, check for stale `> Deep reference:` pointers in other topic files

## References & Assets

- `assets/topic-page-template.md` — bare markdown template for new topic pages (fill placeholders)
- `references/topic-format.md` — wiki-linking rules, alias generation, confidence tags, session comment format

## Examples

**Example 1: After a debugging session about OBO tokens**
User says: "/capture"
Actions:
1. Read conversation -- find OBO token debugging and a FastMCP logger workaround
2. Scan topics -- find existing `obo-authentication.md`
3. Append new H2 entry, write + push
Result: `obo-authentication.md` grows by one entry

**Example 2: After designing a new system component**
User says: "/capture"
Actions:
1. Read conversation -- find knowledge capture system design decisions
2. Scan topics -- no match for "knowledge capture"
3. Create `knowledge-capture-system.md` with the design decisions as the
   first dated H2 entry, then push via the standard PR flow
Result: New topic page created at `seedling` stage with one entry; PR
opened and queued for auto-merge

**Example 3: Multi-page invocation**
User says: "/capture"
Actions:
1. Read conversation -- find two distinct learnings (one OBO refinement,
   one cross-cutting hook pattern)
2. Match OBO refinement to existing `obo-authentication.md`; match hook
   pattern to existing `hook-design-patterns.md`
3. Append a dated H2 to each page, update `updated:` frontmatter, push
Result: Two pages updated in one PR, wiki-links inserted between them
where the entries reference each other
