# Garden — Extracted Procedures

Implementation detail consulted on demand by SKILL.md steps. Dispositions
(what each check does and when) live in SKILL.md; this file holds the
mechanical how.

## Step 2 classification rules (Inventory)

`scripts/analyze.py` does this automatically; the rules below are the hand-
fallback reference and the rationale behind the shape gate. For each `*.md`
file in topics/, classify in this order (first match wins):

- `_moc-*` filename prefix → **MoC**
- `dashboard-*` filename prefix → **dashboard** (excluded from all checks
  except inventory)
- filename ending `-moc.md` or equal to `index.md` → **MoC** (defensive
  backstop for MoCs that don't follow the prefix convention)
- frontmatter `cssclasses` containing `moc` or `index` → **MoC**
- zero dated H2 entries AND ≥3 `## ` section headers **AND link-list ratio
  ≥ 0.5** (fraction of non-empty body lines that are list items carrying a
  wiki-link — MoC shape) → **suspect MoC**: skip the stage check and flag in
  the report under "Classification ambiguous — rename to `_moc-<name>.md` or
  add `cssclasses: [moc]`"
- everything else → **topic**

**The shape gate (link-list ratio ≥ 0.5) is load-bearing.** Without it, every
zero-dated prose reference topic (absorb profiles, landscape reports) lands in
suspect_moc and silently drops out of the orphan AND MoC-gap checks — the
2026-06-08 run misclassified all 22 zero-dated `absorb-*` topics this way,
which is how 27 MoC-coverage gaps accumulated undetected until the 2026-06-10
audit. A file that is mostly prose is a `topic` regardless of dated-entry count.

The **dated H2 count** uses regex `^## .* \(\d{4}-\d{2}-\d{2}\)` — the same
regex /capture uses (`capture/SKILL.md` Step 4 + `capture/references/topic-
format.md`). Raw `## ` headers without a trailing date are structural and do
NOT count. Aligning the regex prevents run-to-run PR churn where /capture
promotes a topic and /garden demotes it on the next run.

## Wiki-link masking implementation (Broken Wiki-Links check)

The documentation-exclusion check must walk **every backtick pair on the
line independently** — a single line can contain both a backtick-wrapped
wiki-link AND a real wiki-link, e.g.

``` See `[[example]]` for structure; use [[real-topic]] to link. ```

The first is documentation; the second is a real link. Implementation:

```python
import re

def real_wiki_links(line: str) -> list[str]:
    # Mask every backtick-delimited span first, then scan the masked line.
    masked = re.sub(r'`[^`\n]*`', lambda m: ' ' * len(m.group(0)), line)
    return re.findall(r'\[\[([^\]]+)\]\]', masked)
```

Mask-then-scan keeps the regex paired-backtick aware without trying to
encode "outside of backticks" directly in one pattern (which is famously
brittle). Fenced code blocks are masked at the block level before the
per-line pass. The naive `re.search(r'\`.+?\`', line)` is correct on its
own (lazy, matches one backtick pair), but only as part of this
mask-then-scan walk.

## flip_status.py invocations (Open-Status Markers check)

Auto-date an undated marker (deterministic — uses the analyzer's
`suggested_since`):

```bash
python3 "<skill-dir>/scripts/flip_status.py" <topic-file> \
  --auto-date <suggested_since> --match "<marker substring>" \
  --garden-date <today>
```

`--garden-date` appends the garden attribution comment for you. The
script mutates exactly one line per invocation (exit 2 demands `--match`
when several markers are eligible) and is idempotent — an already-dated
marker is left untouched.

Auto-flip a within-page-resolved marker:

```bash
python3 "<skill-dir>/scripts/flip_status.py" <topic-file> \
  --resolved <resolution-date> --details "<entry pointer / PR>" \
  --match "<marker substring>" --garden-date <today>
```

The script carries the original OPEN description over to the RESOLVED
line (pass `--summary "<text>"` to replace it, e.g. "see entry below"),
puts the pointer in `[details: ...]`, preserves every other byte of the
file, and is idempotent (a second identical run is a no-op).

## Leaf-chunk algorithm rationale (Soft-Chunk check)

A leaf chunk is computed the SAME way the CI gate (`ci.yml`) computes
it — split each `## ` section on its `### ` sub-headers and measure each
`###` body (plus the pre-`###` portion) independently; a `##` section
with no `###` sub-headers is itself one leaf chunk. Computing chunk size
any other way (e.g. splitting on `##` only) over-counts whole sections
that are internally subdivided and produces phantom violations — always
use the leaf-chunk algorithm `analyze.py` shares with the gate. The CI
gate hard-fails leaf chunks >3000c at PR time and its comment delegates
the 2500–3000c band to garden passes (`ci.yml:43-45`).

## Cross-File Fact Duplication — why backlog-only (2026-06-08 downgrade)

The previous auto-rewrite was destructive: "longest file = canonical"
favored verbose history pages over precise reference pages, the backtick
exemption missed prose-embedded identifiers, and a historical context
("the *old* IP was 10.0.1.5") got silently rewritten to point at the
current IP topic — semantic inversion. Downgraded to backlog-only.

## Merge confirmation — why rank-dominance, not cosine (2026-07-24)

The Merge-Candidates check historically documented a ">0.90 cosine similarity"
auto-merge gate. No available tool can produce that number, so the gate was
unreachable and the SKILL.md overstated a precision it couldn't deliver:

- `memory_search` returns a **whole-corpus ranking** for one query, not a
  pairwise topic-A-vs-topic-B cosine. Its scores are **asymmetric**
  (Voyage query-embedding vs document-chunk-embedding), so absolute values top
  out ~0.3-0.5 even for strongly-related topics — verified 2026-07-24: querying
  `audit-skill.md`'s own distinctive title words scored the top corpus hit at
  0.42 and did not surface `audit-skill.md` itself in the top 5. A 0.90 gate is
  structurally unreachable through this tool.
- `memory_check_duplicate` returns a symmetric-ish cosine with skip/merge/append
  recommendations, but it is built for "is this NEW text a dup of stored
  content?" Garden's topics are **already indexed**, so the input self-matches
  its own chunks (the topic's own parts dominate the top-3) — it can't compare
  topic A against topic B either.

The measurable, tool-honest signal is therefore **rank dominance**, not an
absolute threshold: query with the smaller topic's distinctive content and merge
only when the sibling clearly dominates rank 1 above unrelated corpus hits, with
the ≥2-shared-tags corroborator. On a healthy corpus the sibling usually isn't
even in the top-K, so 0 merges is the correct outcome — the pre-filter casts
wide (slug-prefix / shared title words) precisely because most pre-filtered
pairs are related-by-design, not duplicates.

## Report template (Step 4)

```
=== Garden Health Report ===

Inventory: N topics, M MoCs, D dashboards
Stages: X seedling, Y budding, Z evergreen

Auto-fixes applied:
  - N stage promotions / N stage demotions (D topics missing frontmatter title/description/stage/updated)
  - N bare wiki-links converted to display-text
  - N broken wiki-links stripped to plain text
  - N orphan topics assigned (S strong-fit / W weak-fit / U uncategorized)
  - N MoC coverage gaps filled (S/W/U breakdown)
  - N HIGH-confidence merges
  - N soft-chunk sections split + K left indivisible (= analyzer's M soft chunks)
  - N non-canonical dated headers normalized
  - N stale updated: fields bumped
  - N undated OPEN markers dated / R reclassified to Note
  - N candidates appended to canonicalization-candidates.md
  - N Current-understanding coverage: M missing, S stale

Agent-Memory Topic Sweep (report-only):
  - N topics with newest dated entry >30 days old (worst: ...)
  - N open STATUS markers older than 30 days
  - N topics over 8KB

Open-gap inventory: N OPEN markers, M over-90d (oldest: file.md, since YYYY-MM-DD)
  (world-state reconciliation is out of scope — inventory + aging only; surface the over-90d markers, oldest first)
Overstaged (report-only): N topics whose stage exceeds their dated-entry band
  (zero-dated reference topics with ≥3 sections are exempt — not shown here)

Hub-split candidates (schedule a dedicated split session):
  - file.md | NN sections | NNN KB   (or "none")

Hard-chunk violations (>3000c leaf chunks — CI gate also fails these):
  - file.md | ## Section header | 3xxx chars   (or "none" — expected when CI is green)

Classification flags (if any):
  - Files that may be MoCs but lack the `_moc-` prefix or `cssclasses: [moc]`

Skipped checks (if any):
  - merge candidates — memory-search MCP unavailable
```

## Push flow detail (Step 5)

Standard flow from `~/Documents/knowledge-base/`:

1. The run is already on the `garden/YYYY-MM-DD` branch cut from
   `origin/main` in Step 1 — do not cut a second branch here.
2. **Stage only files this run touched**, derived from in-memory state, not
   from `git add .` or `git add -A`:
   - Build the touched-files list as garden makes edits (track every file
     path passed to Write/Edit during Steps 2-4).
   - `git add <each-tracked-path-explicitly>`.
   - Defensive check: run `git diff --cached --name-only` and assert the
     staged set equals the touched set. If any unexpected file is staged
     (e.g., `session-friction-patterns.md`, which `session-stop.py`
     rewrites between runs at `hooks/session-stop.py:236-239`), `git
     reset HEAD <unexpected-file>` and continue.
3. `git commit -m "garden: <summary of fixes>"`
4. `git push -u origin <branch>`
5. `gh pr create --title "garden: <summary>" --body "<auto-fix details>"`
6. `gh pr merge <num> --auto --squash --delete-branch`

**Fallback (narrow trigger):** if `gh pr merge --auto` fails AND the
stderr matches the literal phrase `cannot pull with rebase: unstaged
changes` (the known race with `session-friction-patterns.md`), retry
once with `gh pr merge <num> --squash --delete-branch` (without
`--auto`). This bypasses the rebase preflight while still using the
GitHub API.

Do NOT use the no-auto fallback for any other error (auth failure, branch
protection block, merge conflict, "Pull Request is not mergeable", etc.) —
those need user attention, not a bypass. Surface the error in the report
and stop. The no-auto fallback skips required-check waiting, so widening
its trigger would bypass the branch protection the repo was set up with.

## Step 3b size sweep — per-surface remedy shapes

`scripts/size_sweep.py` reports; it never edits. Each cap below was verified
against its OWN source on 2026-07-29 (two of the four turned out softer than
the codebase assumed), and each remedy is the one that source prescribes.

| Surface | Gate | Cap | Disposition |
|---|---|---|---|
| `agent-memory/topics/` | soft | 8 KB | **AUTO-SPLIT** → `<topic>-<subdomain>.md` siblings + pointer block in the core file |
| KB chunks | **hard** — `kb.py check` FAILS | 3,000 c | **AUTO-SPLIT** → concept-named `###` (Step 3's soft-chunk pass already does this) |
| `rules/*.md` | **hard** — `rule-size-guard.py` exits 2 | 38 KB | **BACKLOG** → extract old incidents to `rules/incidents/<name>` + one-line pointer |
| `skills/*/SKILL.md` | soft | 510 lines | **BACKLOG** → move detail to `references/<topic>.md`, ONE level deep |
| KB topic files | soft | 8 KB | none — `hub_split_candidates` already owns it |

### The agent-memory split shape — MEASURED not auto (2026-07-29)

**This was `auto` on paper and the first live run refuted it.** Recording the
measurement because the reasoning that produced the wrong answer is seductive:
the cap's own source (ARCHITECTURE.md) names the split shape, so auto-splitting
looked like a mechanical application of a documented remedy.

A one-level split of `claude-monitoring.md` (119 KB, 56 sections) into six
keyword-derived subdomains left **5 of 6 siblings still over the 8 KB cap**, the
largest at 48 KB — and one bucket came out at 953 B, too small to justify a file.
An arithmetic bound, independent of any bucket choice, shows the grouping was not
the problem:

| file | total | sections | min siblings (perfect packing) | single `##` over cap |
|---|---|---|---|---|
| `claude-monitoring.md` | 118,410 B | 56 | **15** | 0 |
| `github.md` | 86,652 B | 6 | **11** | **3** |
| `kaggle.md` | 64,954 B | 29 | **8** | 0 |
| `claude-code-config.md` | 59,974 B | 2 | **8** | **1** (59 KB) |

A file with a single `##` section already over cap is **unsplittable at that
granularity** — no grouping of whole sections can satisfy the cap, so the split
would have to cut *inside* a section. That is authorial work, not mechanical.

So: **BACKLOG**, and a multi-way split is a dedicated session (same posture as a
KB hub-split). The shape below is still the right shape when someone does it.

### The split shape, when a session takes it on

The cap exists because "a topic loads as one atomic injection" (ARCHITECTURE.md)
— a worker dispatched with a 119 KB topic pays ~29K tokens in one shot. Proven
shape, from the 2026-06-10 `aws-infra` split (73 KB → core + `-misc` + `-s3`):

1. Group the over-cap file's `##` sections into coherent subdomains.
2. Move each group to `<topic>-<subdomain>.md`, preserving entries verbatim.
3. Leave a pointer block in the core file naming each sibling and its scope.
4. Add the new siblings to `KNOWN_ARCHIVE_EXCEPTIONS` in `size_sweep.py` so the
   next run does not re-flag the products of this split as fresh findings.

Step 4 skipped is how a split becomes a recurring false positive.

### Why rules/ and skills/ are backlog, not auto

A deliberate exception to garden's "every check auto-resolves" contract. The
script prints the reason in its own output so it is never implicit:

- **`rules/`** — choosing WHICH incident narratives may be demoted is
  editorial. A still-firing GUARD's incident is load-bearing; an archived one
  is not; no heuristic separates them. An auto-extract would eventually demote
  a live guard's evidence. Append to `harness-pruning-candidates.md`.
- **`skills/`** — Anthropic explicitly sanctions exceeding 500 lines "with
  clear reason to exceed," so a breach is **not per se a defect**. All 9
  current breaches already HAVE a `references/` dir: they are *split and still
  large*, i.e. genuinely complex — the sanctioned case. The report's
  `refs/ present` flag distinguishes those from a skill that never split.

### Exemptions (each one mutation-verified as load-bearing)

- **Hook-managed rolling logs** (`session-friction-patterns.md`) — splitting
  fights the producer: the next run rewrites the file wholesale and the
  siblings orphan instantly.
- **Archive siblings** (`aws-infra-misc.md`, `aws-infra-s3.md`) — they exist
  BECAUSE a parent was split. Flagging them reports the fix as the problem.
  Disabling this exemption moves the real over-count 26 → 28.
- **`_moc-*` / `dashboard-*`** in the chunk sweep — generated navigation
  surfaces whose "Recently Added" sections legitimately exceed the chunk cap.
  Without the skip, 4 phantom hard-chunk violations appear.

### What this step deliberately does not measure

Aggregate ambient token load. `/context-budget` owns it and it dominates every
per-file cap: `rules/` totals ~624 KB (~155K tokens) loaded EVERY session, so
descoping one 43 KB file to 37 KB moves <1% of the real cost. Reporting only
breaches would imply per-file descoping is the win. It is not — read both.

## Delivery path is the finding (Step 3b)

Sort and triage by **which files are silently truncated**, never by bytes. A cap
is only a defect where a *mechanism enforces it*:

| how the file reaches context | cap | over-cap consequence |
|---|---|---|
| injected by a hook (`auto-topic-loader`) | **8,000 chars** per topic (platform cap 10,000, hard) | since 2026-09-04: sliced — summary + the sections matching the tool call are injected under the cap, the rest via a pointer to the file; before that, 85-98% silently absent |
| read explicitly (`Read`) | far higher | none — a token-cost question |

The sweep reads the loader's own route map (never a copy — a copy drifts) and
stamps each row `INJECTED` / `read-only` / `DELIVERY UNKNOWN`. Measured
2026-07-29: this narrows **21 over-cap agent-memory topics to 4** real defects.
The largest file in the corpus (`claude-monitoring.md`, 119 KB, 1248% of cap)
is **not** one of them; a 14.9 KB file is.

Three failure modes this ordering prevents, all found by probing the sweep's own
failure paths rather than its happy path:

1. **Biggest-first buries the signal.** The report prints 6 rows. Under a
   size-only sort, 3 of the 4 truncated topics fell below `… 15 more` while
   harmless giants led. Severity ranks before size.
2. **UNKNOWN must never render as safe.** When the route map cannot be read, an
   empty result reads as "nothing is routed" and every file gets stamped *no
   delivery penalty* — a failed read published as a safety claim. The probe
   returns `None`, and a banner fires. (`verify-before-assuming.md`: a verifier
   distinguishes PASS / FAIL / could-not-determine.)
3. **A cap taken from prose is a guess.** Verify each cap against its **vendor
   or enforcing hook**, and record the *bracket* (largest known-delivered,
   smallest known-truncated) — not a single inferred number. The prior figure
   here was ~16 KB, inferred from two persist events at 17-20 KB, i.e. bounded
   from one side only. Wrong by ~60%, in the direction that clears the entire
   8-16 KB band as healthy when every file in it is stubbed. **A threshold
   inferred from observations on one side of it is a bound, not a measurement.**

## Dropped and relocated checks
Rationale for checks garden no longer runs. Kept because the *reasoning* is the
reusable part — a future session proposing to re-add one needs the why, and
SKILL.md is not the place for history (progressive disclosure: zero cost until read).

### Stale Topics — why the staleness check was dropped

A topic that hasn't needed updates may be stable, not stale. The staleness
report consistently produced a long list of "needs human attention" items
that never got attended. Auto-promotion above handles the "still seedling
after lots of entries" case (the real signal). Pure age-since-update is not
actionable noise.

### Harness Pruning — relocated to /harness-prune

The harness-workaround audit (model-version compensations, library
workaround freshness) is conceptually distinct from KB curation and now
lives in `/harness-prune`, which owns the skills/hooks/rules staleness
surface (B8c/F3 ownership). Garden owns the KB and the agent-memory
sweep below. Run /harness-prune separately; its candidates land in the
same KB backlog file (harness-pruning-candidates.md).

## Count-and-pin gate (Step 5)

### A broken count claim is a claim to DELETE, not to bump

`architecture-drift-check.py` skips a contract whose regex does not match
(`if not m: continue`), so removing the number is a supported outcome rather than
a gate bypass. That matters for garden specifically: adding and relocating files
is what this skill DOES, so every hand-maintained count in prose is a drift
generator garden will trip again next run.

Before touching the number, ask whether it carries anything a reader needs. The
instance that prompted this was a mermaid node reading `Topic Files (70)`, whose
sibling nodes in the same diagram described themselves without counting
("Worker Agent / Generic executor / loads topic files"). `Topic Files` alone said
everything the count did and cannot go stale, so one of ~18 count contracts went
away instead of being serviced.

Bump only when the number is genuinely load-bearing — and record why, or the next
session deletes it.


A structural fix does two things CI checks and a content edit does not: it
**changes a file count**, and it **moves prose some other file pins**. Both fail
at CI, never at edit time — measured 2026-07-29, when 3 of 4 PRs from a single
sweep failed on this class after every local test passed:

| what the fix did | what broke | gate |
|---|---|---|
| split a topic (added a file) | a hardcoded `ARCHITECTURE.md` count claim | `bin/architecture-drift-check.py` |
| moved prose to `references/` | an eval fixture pinning its literal text | `bin/preflight-skill.py` |
| added a script | `audit-skill` D3c orphan (nothing referenced it) | `bin/audit-skill.py --all --strict` |

**REQUIRED before the commit, in the worktree that holds the change** — running a
gate in a *different* worktree proves nothing about this one (that is how the
70 → 71 drift shipped):

```bash
python3 bin/architecture-drift-check.py     # counts: splitting adds a file
python3 bin/preflight-skill.py              # full tier; --fast skips 2 gates
python3 -m pytest scripts/ -q               # NOT a preflight gate — see below
grep -rn "<the moved prose>" tests/ scripts/ bin/ .github/
```

Two traps, both documented and both hit:

- **`pytest scripts/` is not a preflight gate**, so a `bin/`- or `scripts/`-
  touching change can pass preflight and still fail CI. Run it yourself.
- **A relocation's last consumer is a test asserting the literal text.** Grep for
  the moved string across `tests/`, `scripts/`, `bin/`, `.github/` before
  pushing; when you find a fixture pinning it, repoint the assertion at the
  *invariant* (the scope boundary that must stay visible), not at the prose that
  explained it — otherwise the next legitimate rewording breaks it again.
