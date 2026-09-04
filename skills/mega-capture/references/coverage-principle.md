# The core principle and the non-goals

Relocated verbatim from `skills/mega-capture/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md).

## The core principle: COVERAGE-complete, but NOT a census

There is an apparent contradiction to resolve up front, because getting it wrong produces either a truncated KB (the user's stated fear) or a 995-finding census (the retired anti-pattern mega-distill killed).

- mega-distill's law is **condense, don't census** — keep the FEW load-bearing lessons, drop ~99% noise.
- mega-capture's requirement is the opposite vector: **NOT a truncated KB — cover everything in the transcript.**

These reconcile on **different axes**, and this distinction is the whole skill:

> **"Coverage-complete" is breadth ACROSS themes; it is NOT transcription of every occurrence.** Every *distinct capturable THEME* in the session (a decision with rejected alternatives, a debugging breakthrough, a cross-cutting pattern, a strategic insight, a failed approach) must reach SOME KB entry — none silently dropped because it lived in the compacted-away head. That is the anti-truncation guarantee. But **dedup/merge still applies WITHIN a theme**: capture's normal judgment consolidates repeated mentions of one theme into one growing entry, never one-entry-per-occurrence. Anti-truncation operates across themes; consolidation operates within a theme.

So the entry COUNT scales to the THEME count (no fixed cap — the scope-proportional lesson from mega-distill, here applied to themes not lessons), and when a single theme's material exceeds the KB's 2,500-char chunk limit it **SPLITS** into multiple entries or a new topic page (per KB CLAUDE.md "prefer splitting over trimming"), it is **NEVER truncated**.

**The failure mode this skill must avoid is THEME-DROPPING** — a real strategic thread in the head that never reaches the KB. That is distinct from distill's failure mode (finding-count inflation). The coverage ledger (Step 2) is the structural guard against it.

---


## What This Skill Does NOT Do

- Does NOT emit a per-occurrence census (the retired 79-extractor mega-distill design — see mega-distill "What it is NOT"). Themes are consolidated threads; occurrences within a theme merge.
- Does NOT truncate to fit a chunk limit — a theme over 2,500c splits into multiple entries / a new page (KB CLAUDE.md "prefer splitting over trimming").
- Does NOT re-implement capture's dedup/tiering/contradiction judgment — it recovers the complete session into a slice capture can hold, THEN routes each theme through capture's gates.
- Does NOT run on uncompacted in-context-fitting sessions (Step 0 routes those to /capture).
- Does NOT do cross-SESSION strategic-theme recurrence (a corpus mode) — out of scope for v1; a separate future plan if cross-session theme recurrence is ever needed (mirroring mega-distill's corpus mode).

