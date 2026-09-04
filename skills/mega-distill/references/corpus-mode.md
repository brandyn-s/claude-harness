# Corpus Mode — cross-session recurrence (`--corpus`)

Relocated verbatim from `skills/mega-distill/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md).
Step 0 of the skill routes `--corpus` runs here; the single-session path never reads this file.

## Corpus Mode — cross-session recurrence (`--corpus`)

Single-session mega-distill recovers ONE compacted session for /distill. **Corpus mode answers a
different question no per-session tool can:** *what friction do I hit REPEATEDLY across many
sessions?* /distill only ever sees its in-context session; /retrospective and /review-learnings read
already-distilled artifacts (the lossy <2% projection), not raw transcripts. Raw transcripts are the
only complete record, and corpus mode is the only thing that mines them across sessions.

**The deliverable is the BREADTH-RANKED recurrence table — not a per-session pile.** "Pattern X
recurs in N of M sessions," ranked by breadth. A friction in 175/1197 sessions (1-in-7) is a systemic
habit worth a rule or a hook; 200 occurrences in ONE session is just a bad day. Breadth is the signal,
and it exists ONLY cross-session. Concatenating per-session lessons would rebuild the retired census
(2026-06-21 red-team) — corpus mode is anti-census by construction: the ranking IS the diagnosis.

### Layer 1 — Friction spine (deterministic, FULL corpus, no LLM, no token cost)

The cheap fabrication-proof core. Streams every transcript, extracts friction events
(error `tool_result`s, hook/guard blocks, gate violations, user corrections, compaction boundaries)
into NORMALIZED SIGNATURES, and aggregates by breadth. Runs over all ~1209 sessions in ~2 seconds.

```bash
# cohort = ALL transcripts across ALL project dirs (recursive find — NOT a single dir; the corpus
# spans per-repo/per-tmp project dirs, only ~450 of 1209 live in the main project dir)
CORPUS_TMP="${TMPDIR:-${TEMP:-/tmp}}/claude-corpus"
mkdir -p "$CORPUS_TMP"
find ~/.claude/projects -name '*.jsonl' -type f | sort > "$CORPUS_TMP/cohort.txt"
python3 ~/.claude/bin/transcript_friction_corpus.py \
  --cohort "$CORPUS_TMP/cohort.txt" --out-dir "$CORPUS_TMP/friction-run" --min-breadth 2
# Gate the table (grounding + arithmetic + no-stray): MUST pass before trusting/shipping any of it.
python3 ~/.claude/bin/transcript_friction_gate.py \
  --recurrence "$CORPUS_TMP/friction-run/friction_recurrence.json" \
  --cohort "$CORPUS_TMP/cohort.txt"
```

**Instrument-validation gate (mandatory before acting on output):** `gate:read-before-edit` MUST
surface at top-tier breadth (the rules record it as the #1 self-inflicted friction, ~144 fires/14d).
If a known-positive friction is ABSENT, the extractor is broken — fix it before trusting any row
(validate-detection-on-known-positives). Also confirm the top signature exceeds ~5-10% breadth (else
signatures over-split) and the gate exits 0.

### Layer 2 — Semantic lessons (LLM, BOUNDED to >1MB cohort, gated)

The meta-pattern layer distill is prized for (e.g. "optimized completeness over diagnosis") is
*prose* — it under-clusters by signature, so it needs an LLM, which means cost + fabrication risk →
bounded + gated. The per-session map prompt is `references/corpus-extract-prompt.md` (extract the FEW
load-bearing prose lessons per session, NOT a census). Select the cohort, map one extract/session
(substitute the bundled condenser path and `$CORPUS_TMP` for the prompt's
`__CONDENSER_PATH__` and `__CORPUS_TMP__` placeholders), assert
findings-file-count == cohort-count (FLAW-7 completeness gate) BEFORE clustering, cluster by pattern,
then gate coverage + no-fabrication + recomputed breadth. Bound the semantic layer to the `>1MB`
cohort (~97 sessions); the friction spine already covers the full corpus. **Always print the coverage
line** — `Friction: 1209/1209 (100%). Semantic: 97/1209 (>1MB cohort); 1112 smaller sessions covered
by friction spine only.` No silent truncation.

### Ship: the cluster RANKING prioritizes; /distill JUDGES-AND-WRITES each cluster (NOT a summary)

CRITICAL — this is the step where corpus mode earns its keep or fails. The breadth-ranked cluster
table is **prioritization input, NOT the deliverable**. Clustering is a LOSSY aggregation — it is the
INVERSE of distill's per-item judgment: it answers "what recurs" by averaging specifics into a count,
which is exactly the wrong operation for "fix it". A cluster says "bash-antipattern-reflex, 50/97
sessions"; the FIX lives in its 56 member-lessons, each carrying a concrete `proposed_fix`. Summarizing
the cluster emits a frequency report and BURIES the shippable specifics
(`references/run-history.md`).

So: for each cluster, IN BREADTH-RANK ORDER (highest first — that is all the ranking is for), hand its
**member-lessons** (not the cluster summary) to /distill's judge-and-write loop, with the cross-session
breadth supplied as PRIORITIZATION + DEDUP context, and let /distill do what it does per-session:

1. **JUDGE the member-lessons** — distill decides: is this one durable fix or several? what tier? It
   does NOT treat the cluster as one finding — it reads the N specific `proposed_fix` fields and finds
   the distinct actionable items the cluster name flattened together (a "bash-antipattern" cluster
   contains a tail-buffering reflex AND a specific wrong hook-recovery-message AND a pipefail/grep-q
   gap — three different dispositions).
2. **DEDUP against `rules/` + memory** (distill Step 1d) — this is load-bearing: many cross-session
   lessons describe a gap that a LATER session already fixed. Distill's dedup drops the stale ones
   ("already covered by platform-constraints.md:141, no action") that a cluster summary would have
   re-reported as open.
3. **WRITE THE ACTUAL FIX per surviving item** — the concrete artifact, like distill always does:
   T1 rule edit (exact GUARD/procedure text), T2 memory fact, SKILL step, or a hook-message/code fix.
   Not "a reminder about X" — the diff. Auto-ship via /ship (branch + PR + auto-merge), same contract
   as single-session mega-distill Step 3.
4. **Breadth ≥25% AND already-ruled-but-still-recurring** → this is the one place a cluster-level
   output is itself the finding: it means a rule exists and is violated under load → PROPOSE hook /
   middle-tier enforcement (do NOT auto-build a blocking hook: verify-effectiveness HARD-REQUIRES the
   historical-replay gate, >10% block-rate = DoS; a UserPromptSubmit judgment-reminder needs its fire
   rate replayed to <~10% before shipping). The corpus run already produced the replay set the
   build needs. Emit as a ready next step, not an opt-in toggle.

The breadth number NEVER substitutes for the fix. It decides ORDER and informs DEDUP. The fix is always
distill's per-lesson write. If the output of this step is a table of counts rather than a set of shipped
diffs, the step FAILED — re-run it through distill's loop.
