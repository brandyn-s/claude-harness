---
name: debugging-hypotheses
description: "Companion to superpowers:systematic-debugging for bugs whose cause is not obvious after the first evidence pass: enumerate the code's unusual mechanisms, form two or more hypotheses across six failure categories, rank them by evidence tier, and run bounded parallel investigators."
when_to_use: 'Use INSIDE superpowers:systematic-debugging, between its evidence-gathering and hypothesis phases, when the stack trace does not point straight at the bug, when a first fix did not hold, or when you notice you have only one theory. Trigger phrases: "second hypothesis", "what else could cause this", "rank the hypotheses", "investigate in parallel", "enumerate mechanisms". Do NOT use for typos, missing imports, or syntax errors, and do NOT use instead of systematic-debugging — it supplies the hypothesis discipline that skill leaves to judgment.'
allowed-tools: Read Grep Glob Bash Agent AskUserQuestion
---

# Debugging hypotheses

Companion to `superpowers:systematic-debugging`. That skill owns the four-phase
process; this one owns the step it leaves to judgment: how hypotheses are
generated, ranked, and tested when the cause is not obvious. Extracted on
2026-09-03 from this repository's fork of superpowers v4.3.1 so the installed
plugin keeps its name and routing while these additions stay available.

## 1. Enumerate mechanisms before hypothesizing

Before forming any theory, read the affected component's code and list every
unusual operation. Trace forward from the code, not backward from the error
message.

- Read initialization, setup, and teardown paths with the same scrutiny as the
  execution path. Connection setup is where extensions load, modes change, and
  state mutates.
- List everything non-obvious: loaded extensions, monkey-patches, global state
  mutations, background threads, signal handlers, atexit hooks, imported but
  unused modules.
- For each, write yes / no / maybe against "could this cause or contribute to
  the observed error?"

The anti-pattern this prevents is matching the error text against training
data. In a 2026-03-28 session, 30 "bad parameter" SQLite errors were blamed on
concurrent access because the message matched that pattern; the cause was an
unused C extension loaded on every connection, eight lines in a 2,000-line
file that had been read but never connected to the error because the theory
was already formed.

## 2. Form at least two hypotheses

Generate candidates across all six failure categories so one plausible story
cannot end the search:

| Category | What to check |
|----------|---------------|
| Logic error | wrong conditional, off-by-one, missing edge case, wrong algorithm |
| Data issue | invalid input, type mismatch, null where a value was expected, encoding or serialization |
| State problem | race, stale cache, wrong initialization, unintended mutation |
| Integration failure | API contract violation, version incompatibility, config mismatch, missing env var |
| Resource issue | memory leak, connection pool exhaustion, file handle leak, disk or quota |
| Environment | missing dependency, wrong library version, platform-specific behavior, permissions |

(Pattern source: wshobson/agents parallel-debugging ACH framework, Context7
registry 2026-04-06.)

For each: "I think X is the root cause because Y." Write them all down before
testing any. If you can only think of one, you have not read the code
thoroughly enough: return to step 1.

## 3. Rank by evidence tier, not plausibility

| Tier | Type | Example | Weight |
|------|------|---------|--------|
| 1 | Direct | the code shows the mechanism; you traced the data flow | strongest, test first |
| 2 | Correlational | the symptom correlates with a change: blame, timing, config diff | moderate, verify causation |
| 3 | Testimonial | the error message pattern-matches a remembered bug | weak, the most common source of wrong hypotheses |
| 4 | Absence | "nothing else could cause this" | weakest, valid only after tiers 1 and 2 are exhausted |

A tier-1 hypothesis beats a tier-3 one even when the tier-3 story feels more
likely. In the incident above, "concurrent access" was tier 3 and "unused
extension modifies the connection" was tier 1; tier 1 was correct and tier 3
cost 30 turns.

## 4. Investigate in parallel when there are three or more

When three or more hypotheses survive ranking and the problem is not a simple
typo, import, or syntax error, dispatch one subagent per hypothesis rather
than testing them serially. Each investigator receives the hypothesis, the
relevant file paths, what evidence would confirm or refute it, and a budget of
at most five tool calls. Each reports Confirmed, Refuted, or Inconclusive with
the specific evidence. Merge the results into the hypothesis table.

Skip parallel dispatch when one or two hypotheses exist and the stack trace
points directly at the bug, or when the hypotheses are sequential.

Budget: at most two parallel rounds. If every hypothesis is refuted after two
rounds, present the findings and ask for direction instead of generating more
hypotheses autonomously. (Pattern source: tobihagemann/turbo `/investigate`,
adapted with budgets and a merge protocol.)

## 5. Prevention checklist after the fix

1. Test: is there a regression test that would catch this bug?
2. Documentation: does a runbook, topic file, or inline comment need the lesson?
3. Tooling: could a lint rule, hook, or CI check catch this earlier?
4. Pattern: is this a recurring class? Should it inform a rule or a skill?

(Pattern source: chriswiles/claude-code-showcase, Context7 registry 2026-04-06.)

Then return to `superpowers:systematic-debugging` Phase 4 to fix with a failing
test first.

## Examples

**Example 1: stack trace does not point at the bug**
User says: "The upload handler throws `KeyError: 'etag'` but the dict is
populated two lines above."
Actions:
1. Enumerate mechanisms (step 1): retry wrapper re-enters the handler; the
   response is a lazy proxy; a sibling thread mutates the dict.
2. Form three hypotheses across categories (step 2): state (mutation),
   concurrency (thread), boundary (lazy proxy).
3. Rank by evidence tier (step 3): the retry wrapper is Tier 1 — the traceback
   shows two frames of the same function.
Result: retry-on-partial-failure re-entered with a consumed body. One
hypothesis, ranked first by evidence rather than plausibility.

**Example 2: the first fix did not hold**
User says: "I added the null check and it still fails in staging."
Actions:
1. Treat the failed fix as a refutation, not a starting point — the mechanism
   was wrong, so re-enumerate (step 1) instead of hardening the same guard.
2. Three surviving hypotheses, each answerable by a bounded read on a
   different surface → dispatch parallel investigators (step 4).
3. Merge findings; two hypotheses are refuted by config, one confirmed.
Result: staging read a different config key. Two parallel rounds maximum,
then back to `superpowers:systematic-debugging` Phase 4.

**Example 3: only one theory exists**
User says: "It's obviously the cache."
Actions:
1. Notice the single-hypothesis condition and refuse to act on it (step 2).
2. Produce a second and third mechanism before touching the cache.
3. Rank all three; the cache falls to Tier 3 (plausible, no evidence).
Result: the ranking, not the hunch, chooses what gets investigated first.

## Success Criteria

- At least two hypotheses exist before any fix is attempted, drawn from
  different failure categories.
- Every hypothesis carries an explicit evidence tier, and the investigation
  order follows the tiers rather than plausibility.
- Parallel investigation is used only when three or more hypotheses are
  independent and each is answerable by a bounded read.
- No more than two parallel rounds run before findings are presented to the
  user for direction.
- After the fix, all four prevention-checklist items are answered.
- Control returns to `superpowers:systematic-debugging` Phase 4 for the fix
  itself, with a failing test written first.
