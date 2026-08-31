# Staged spec — extend `bash-tail-buffering-guard` auto-rewrite coverage

**Status:** STAGED, not installed. Install via `/ship-hook` only after the
historical-replay gate below passes.

**Type:** T0-hook (modification of an EXISTING PreToolUse guard, not a new one)

## Evidence

Measured on session `6a75b2f3` (2026-08-29), a 4,578-turn / 1,988-tool-call
session with a healthy 2% overall failure rate:

| count | family |
|---|---|
| 9 | `bash-tail-buffering-guard` — pipe to `head`/`tail`/`grep` |
| 6 | `write-edit-dispatcher` — memory entry >2500 chars |
| 4 | `inline-python-guard` — inline python >300 chars |
| 4 | `credential-guard` |
| 2 | `auto-merge-guard` |
| 1 each | `worktree`, `exfiltration-guard`, `process-listing-guard` |
| **28** | **TOTAL deterministic blocks = 47% of all 59 tool failures** |

The guards were CORRECT every time. The friction is that each block costs a full
turn, and `bash-tail-buffering-guard` alone fired 9 times against the same
composition reflex despite `platform-constraints.md` already carrying the rule
("A deterministic guard blocking the SAME shape twice in one session is a signal
about your own default"). A prior session measured 30 blocks from the same guard,
so strongwording plus hard-blocking has now failed to change the reflex twice.

## What is proposed

The guard ALREADY auto-rewrites some shapes — its own message says "This shape
could not be auto-rewritten safely (quoted pipe or existing producer-side
redirect)." Extend that coverage to the mechanical, unambiguous case:

```
<producer> | head -N        ->  <producer> > $TMP/out && sed -n '1,Np' $TMP/out
<producer> | tail -N        ->  <producer> > $TMP/out && tail -N $TMP/out
<producer> | grep <pat>     ->  <producer> > $TMP/out && grep <pat> $TMP/out
```

Rewrite ONLY when every condition holds, else keep blocking:
- exactly one pipe segment after the producer;
- the consumer is `head`/`tail`/`grep` with no `-f`, no `-q`, no `--line-buffered`;
- no existing producer-side redirect (`>`, `>>`, `2>&1` before the pipe);
- the pipe is not inside single/double quotes or a heredoc body;
- the pipeline's status does not gate an `&&`/`||` (that is the SEPARATE
  status-overwrite case the guard also catches — do NOT rewrite those, the
  verdict there is about exit-status semantics, not buffering).

Converting a blocked turn into a rewritten one preserves the guard's intent (the
producer is never starved of a flush) while removing the turn cost.

## Why this is not "weaken the guard"

The block/allow decision is unchanged for every shape that cannot be proven
mechanically safe. Nothing becomes permitted that is currently denied; a subset of
denials become *corrections*. The dangerous shapes — `grep -q` early-close, a
status-gated pipeline, a producer inside quotes — stay blocked with the same
message.

## REQUIRED gate before install (verify-effectiveness)

1. **Historical replay.** Run the candidate rewriter over the recorded Bash
   commands of the last ~20 sessions. Report: how many currently-blocked commands
   it would rewrite, and how many it would rewrite WRONGLY (changed semantics).
   A wrong-rewrite rate above 0 blocks the install — a silent semantic change is
   strictly worse than a block.
2. **Known-positive AND known-negative proof in the PR**, run through the same
   hook path that will execute: one command it correctly rewrites, and one
   quoted-pipe / status-gated command it still refuses. A gate never seen doing
   both is indistinguishable from one that does neither.
3. **No new bypass flag.** An env var to skip the rewrite would be set once in a
   shell profile and restore exactly the hole this closes.

## Explicitly NOT proposed

- A new rule. The rule exists and is correct; adding prose has now failed twice.
- Any change to `write-edit-dispatcher`'s 2500-char memory cap. That cap fired 6
  times this session and was right every time — including once on the distill
  entry describing this very finding. The lesson there is already `[confirmed]` in
  `agent-memory/topics/claude-code-config.md` (2026-06-12, "budget ~2,300 and
  split by concern up front"); the gap is compliance, not knowledge, and no hook
  change is warranted.
