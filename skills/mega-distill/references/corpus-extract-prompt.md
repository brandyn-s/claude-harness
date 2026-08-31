# Corpus-mode per-session extraction prompt (Phase B2 map)

This is the SEMANTIC-layer map prompt. The retired per-chunk census prompt is not distributed.
One agent per session in the >1MB cohort. Each agent condenses ITS session, reads
the whole-session slice, and extracts the **FEW load-bearing PROSE lessons** — the meta-patterns the
deterministic friction spine (Phase A) structurally cannot see (a signature counts "tail-buffering
fired"; it cannot say "I optimized completeness over diagnosis"). Lossy in the right direction.

## Critical gotchas (the agent MUST obey)

- Do NOT emit a per-occurrence census. Target **3-8 lessons** for a large session, fewer for a
  smaller one. A session with no durable lesson legitimately returns an empty list — do NOT pad.
- Each lesson must be a PROSE PATTERN, not a single tool error (those are the friction spine's job).
  "Repeatedly assumed a tool was unavailable without ToolSearch" is a lesson; "ToolSearch returned
  empty once" is friction.
- Ground each lesson to the session id (provided) — you are reading a condensed slice of ONE session.
- Write to disk AND return; the orchestrator verifies the DISK file, not your return value (FLAW-7).
- Keep the prompt's session id in your reasoning so parallel agents stay distinct (Opus-4.8
  parallel-fanout duplication guard).

## Per-agent procedure

1. Condense the session (the orchestrator passes `__TRANSCRIPT_PATH__` and `__SID__`):
   ```bash
   python3 __CONDENSER_PATH__ __TRANSCRIPT_PATH__ \
     --out-dir __CORPUS_TMP__/semantic/__SID__ --max-tokens 180000
   ```
2. Read every `slice_NNN.txt` in that dir FULLY; use the manifest's bounded part count.
3. Extract the few load-bearing lessons and WRITE them to
   `__CORPUS_TMP__/semantic/lessons/lessons___SID__.json` (the orchestrator's `--lessons-dir`).

## Output schema (write to lessons_<SID>.json)

```json
{"session": "<SID>", "lessons": [
  {"summary": "<one sentence: the durable pattern/lesson, not a single event>",
   "kind": "error-pattern | abandoned-approach | recurring-friction | decision | insight | user-correction-pattern",
   "root_cause": "<why it kept happening — the underlying cause>",
   "proposed_fix": "<the concrete durable fix: a rule, a guard, a habit change>",
   "tier_hint": "T1-rule | T2-fact | T4-topic | SKILL:<name> | T0-hook | none",
   "evidence": "<brief: what in the session shows this — a phrase, an error class, a correction>"}
]}
```

`kind` drives clustering: lessons of the same kind + similar root_cause across sessions are what the
Phase B4 clustering pass groups into a cross-session recurring pattern. An empty `lessons` list is a
valid, honest result for a session whose large size was build-output, not diagnostic incident.
