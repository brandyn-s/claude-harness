---
paths:
  - "**/rules/tdd-mutation-testing.md"
  - "**/rules/incidents/tdd-mutation-testing.md"
---

# tdd-mutation-testing: Incident Narratives

Extracted from `rules/tdd-mutation-testing.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-07-31-claude-config-1834-find-session-pid

```
WHY: 2026-07-31 claude-config #1834 — `find_session_pid()` walks process
ancestry via `ps` and documents `None` as legitimate (pid<=1, unreadable
comm, or >8 hops). Its test asserted `isinstance(spid, int)`
unconditionally and ran green / 1-failed / green across three full-suite
runs of the IDENTICAL committed tree, while passing 20/20 in isolation
every time. Mutating the shell-skipping branch MISSED — yet the parent
`zsh` (pid 64434) was readable on one probe and had already EXITED on the
next, in the same session, so each run walked a different ancestry. After
pinning (two maps: parent-of-pid and comm-of-pid — a single
`(parent, comm)` tuple conflates them and is off by one, which the new
test caught in its own first fixture), the SAME mutation CAUGHT, 3/3 with
stable verdicts. Both the test AND the mutation of it were reading
unpinnable state; only pinning fixed either.
```

## 2026-08-02 assumption-written test pins the wrong depth

Closing a mutation-found privilege hole in the claude-gateway spend-control reconciler
(`example-org/claude-gateway` PR #3). Mutation testing had shown that removing the
`org-terraform may only submit organization-scope` check failed **no test** — 86 tests were green
over that privilege boundary and simply had no case for that cell.

Writing the replacement — a full 2-caller x 3-scope caller-scope matrix, since plan section 2.3
defines the grid and only part of it was covered — produced **three failures on first run**, and
two of them were my test being wrong rather than more findings. The code is STRICTER than assumed,
and rejects at different depths:

1. `rbac_group` scope is rejected at **schema-parse** time (`scope.type must be one of
   ('organization','user')`) — it never reaches the authorization layer I was testing. The gateway
   API itself accepts `rbac_group`, so this is a deliberate narrowing in the reconciler.
2. `exception-workflow` + `organization` hits `EnrollmentVerificationError` **first**: an
   unverifiable identity artifact refuses EVERY exception-workflow request before scope is
   considered. Fail-closed, and correct.

So the real boundary is **three distinct outcome classes**, not the two I had assumed. The
corrected matrix ran 7 passed / 6 skipped (each skip a cell owned by a different assertion), and
re-running the previously-surviving mutation then failed **exactly one** test — the new cross-scope
case — which is precision rather than collateral damage.

The generalizable point: an assumption-written assertion can pass while pinning a boundary that
does not exist. The first-run failure is the code disclosing its real structure, and the wrong move
is to adjust the test until it matches what you expected.

<!-- extracted 2026-08-12: descope below the 38,000-byte BLOCK -->

## 2026-07-26-claude-config-cc-monitor-fact-ch

```text
INCIDENT 2026-07-26 (claude-config cc-monitor fact-checker): 2 of 4
mutations PASSED. Both fixtures were the wrong shape. (a) An unclosed-
strikethrough suppressor was "verified" by a fixture whose `~~...~~` span
was CLOSED — caught by the span-overlap path instead, so reverting the
tilde-count-to-`match.end()` fix changed nothing. (b) A value-list gate was
"verified" by a prose fixture the entry regex never matched at all, so the
gate was never entered. Replacing both with the real breaking inputs (a
markdown-line-WRAPPED strike whose closing `~~` is on the next line; a
`group_by[]=speed` mention followed by a `[[wiki-link]]` whose brackets
parse as a value array) made both mutations fail correctly. Had I trusted
the passing mutations, I would have deleted two live guards — each of which
had caused a real false positive minutes earlier.
```

## 2026-07-27-code-graph-pr-416-cypher-edge-pr

```text
INCIDENT 2026-07-27 (code-graph PR #416, Cypher edge-predicate pushdown):
the regression tests set `expandLimit` in the `&Executor{...}` literal to
force a tiny row cap. But `Execute()` overwrites `e.expandLimit` per run
from `bindingCap(plan.ReturnSpec)` (= `maxRows()*2`), so the literal value
was discarded, no truncation ever occurred, and BOTH row-cap tests passed
with the fix mutated OFF. Switching to `MaxRows` (which `bindingCap` derives
from) made the mutation fail correctly — 0 rows at caps 1/2/5, right answer
at 500. Without the mutation check the PR would have shipped regression
tests structurally incapable of detecting the regression.
```

## 2026-07-27-code-graph-416-retracted-in-418

```text
INCIDENT 2026-07-27 (code-graph #416 → retracted in #418): while shipping the
Cypher pushdown I reported a "separate pre-existing defect — target-node OR
drops a branch" in a shipped test comment, having confirmed it by stashing
the pushdown and re-running against `origin/main`. There was NO bug. The
probe asked for `b.name = "decoyA0"`, but my fixture named every decoy node
plain `"decoy"` and varied only the QUALIFIED name — so that branch matched
zero nodes by construction and `needle OR decoyA0 -> 1 row` was the CORRECT
answer. Instrumenting each branch (needle=1, decoy=3, OR=4, source-OR=4)
refuted it in one turn. The false claim shipped to main and needed a
retraction PR; the wrong-shaped fixture was one I had written myself minutes
earlier for a different test.
```

## 2026-07-27-reverting-a-shadow-mode-mutation

```text
INCIDENT 2026-07-27: reverting a `SHADOW MODE` mutation with
`git checkout -- anthropic-audit-v2-core.tf` also wiped the uncommitted
feature-flag edit under test; it had to be rewritten from scratch. Separately
the same session's watch script printed `RESULT=ERRORED errors=0` because it
string-compared the API's `0` against `"0.0"` — a false failure verdict from
the monitor, not the system.
```

## 2026-07-29-mcp-infra-per-hook-lane-8-mutati

```text
INCIDENT 2026-07-29 (mcp-infra per-hook lane): 8 mutations run, 2 initially
passed — one was the inert `[] if False else` edit above (my mutation was
wrong), one was the repeated-`GREATEST` weak assertion (the test was wrong).
Same symptom, opposite diagnoses. Had I read both as weak tests I would have
"fixed" a correct guard; had I read both as bad mutations I would have shipped
an assertion that cannot fail.
```

## 2026-07-31-mcp-infra-764-765-four-independe

```text
INCIDENT 2026-07-31 (mcp-infra #764 -> #765): four independent literals described as
"asserts the relationship"; the single-value mutation FAILED it but the lockstep
mutation PASSED ALL FOUR and shipped a zero-headroom cap. The critique of the test was
also wrong on first pass — running the mutation, not reasoning about it, produced the
accurate account. Full: incidents/tdd-quality.md#2026-07-31-both-sides-literal
2nd INSTANCE, same day, DATA not code (mcp-servers #931): a report freeze file carried
`lanes: {api: 837308, chat: 374978, bedrock: 67700}` beside `true_total_90d: 1277873`.
The total is DERIVED (= sum(lanes)) but was stored as a co-equal literal, so updating
ONE lane from a fresh pull left it stale by +2,113 and the pipeline published
`coverage_pct=100.2` — attributing more than the stated total. The existing contract
test asserted the key was PRESENT, which is not a relationship. Generalises past code:
**any config/freeze/manifest field that is a FUNCTION of its siblings needs a derived
assertion, not a pinned one** — and the tolerance must be probed from BOTH sides (±100
here accepted the benign rounding delta and rejected at +101).
```

## 2026-08-02-claude-config-1874-zsh-dialect-g

```text
INCIDENT 2026-08-02 (claude-config #1874, `zsh-dialect-guard`): 8 mutations, 2
initially MISSED — the left boundary (covered incidentally by the quote-strip) and
the heredoc-strip (its fixture's glob was single-quoted, so the quote-strip covered
it too). Both fixtures were rewritten to be single-mechanism; both mutations then
CAUGHT. Separately, the FIRST mutation batch that session ran against a RED
baseline and reported 3/3 CAUGHT — a verdict set that means nothing, since with a
red baseline everything fails. **Assert a GREEN baseline before reading any
verdict**, and treat a batch whose baseline was never checked as unrun.
```

## 2026-07-31-08-01-gold-flatten-import-time-binding

```text
INCIDENT 2026-07-31/08-01 (gold-table flatten job): running the new file FIRST failed 5
tests in `test_gold_schema_drift.py`; running it LAST passed all 24 — caught only because two
orderings happened to be tried. Root cause: `SOURCE_VIEW`/`GOLD_TABLE` bind at import time, so
whichever file imports first binds them for both. Separately
`test_daily_correlator_wiring.py:35` does `R.reconstruct = lambda evs: ...` and never restores
it, so alphabetically-later files in a full-suite run silently inherit the stub.
(Same family as items 13/15/23 — the shared-`sys.modules` state class.)
```

## 2026-07-31-mcp-infra-927-judge-transcript-o

```text
INCIDENT 2026-07-31 (mcp-infra #927, judge-transcript ordering), verbatim: "'monotone by
construction — no detection can regress' | Overstated. True for the accessor in isolation,
false for its one real consumer. `seq` resets mid-session, so ~1% of sessions now scramble
chronologically... pre-fix, `seq` was uniformly 0, so the sort was mathematically identical to
a pure-timestamp sort... I made ordering deterministic for the 94% and inverted
cause-and-effect for the 1%."
```

## 2026-08-02-mcp-infra-800-a-test-asserting-n

```text
INCIDENT 2026-08-02 (mcp-infra #800): a test asserting no `tier =` argument on an SSM
parameter resource. The mutation `tier = "Advanced"` inserted after `key_id` **survived** —
the suite stayed green while the resource carried the forbidden argument. Verified the
mechanism directly: `re.search(r'^\s*tier\s*=', code)` → `False`, the same pattern with
`re.MULTILINE` → `True`. Caught only because the mutation was run; reading the test could
not surface it, because the pattern LOOKS right.
```

## 2026-08-15-an-assert-raises-predicate-that-accepts-any-exception

```text
INCIDENT 2026-08-15 (claude-config #2007, /snow verify_guards.py): a guard-verification
harness whose `refuses(fn)` helper returned True on ANY SnowError. Ten guard cases; eight
make live reads. On a transient live failure the three cases expecting a REFUSAL (another
approver's row, an out-of-scope record, a 401 table) each CAUGHT the transport error and
reported PASS, while the three known-negatives expecting NO refusal plus the pin check
reported FAIL. That is exactly 4 FAIL / 6 PASS — the observed verdict on one run, against
10/10 on the three runs before and after it.

So the harness passed its three most important guards for the WRONG REASON in the one run
where it was under stress, which is the worst possible correlation: the predicate degrades
toward "pass" precisely when the environment is degraded.

This is item 20's "the test bites, but not for the reason you think" applied to the
PREDICATE rather than the assertion. An `assertRaises`-shaped check has TWO exception
sources — the behaviour under test, and the infrastructure it runs on — and accepting the
union silently converts an infrastructure failure into evidence of correct behaviour.

FIX: discriminate by a marker the guard itself emits. Every genuine refusal in that
codebase is prefixed `REFUSED:`; transport and lookup errors are not (`'<table> <id> not
found'`, `'... -> HTTP 500'`). A non-refusal exception is now re-raised as "this case was
never exercised" rather than counted. A separate `raises_http(401, ...)` predicate covers
the one case that legitimately asserts an HTTP raise, pinning the exact status — a
transient 500 previously satisfied "it raised" while proving nothing about the 401 claim.
Verified by 7 offline checks with synthetic raisers plus a mutation restoring the old
predicate (CAUGHT, hitting exactly the two transport checks).

TWO ADJACENT DEFECTS from the same run, both worth copying:
1. The summary reprinted `why` only for SKIPPED cases (`for name, got, _ in results`), so
   a FAILED case showed a count with no cause. The reason had scrolled past the captured
   window and nothing re-stated it, which is why the 6/10 was undiagnosable at all. A
   verdict whose cause cannot be recovered from the summary is not actionable.
2. The verdict's own exit code was masked by `| tail -3` — the pipeline reports the
   FILTER's status. So a run with 4 real failures reported exit 0. Do not read a verdict
   command through a pipe (`platform-constraints.md`, and the repo's own
   bash-tail-buffering-guard blocks the shape).

GENERAL RULE: for any predicate of the form "assert this raises", name WHICH exception
counts and reject the rest. If the predicate cannot distinguish the subject's failure from
the environment's, it is an availability probe wearing a correctness assertion's clothes.
```

## 2026-08-28-self-reference-detectors-five-surfaces

Five instances in one session, four distinct surfaces:
- a corpus scan for cap-friction matched sessions that merely LOADED the ambient
  rules quoting "headroom" / "10,000-byte" (breadth inflated from a real ~48% to 75%);
- a transcript probe's KNOWN-NEGATIVE matched 1 session — its own authoring session,
  because writing the probe put the bogus marker literal into the live transcript;
- `assert "budget_seconds=" in source` was satisfied by a mutation's own COMMENT
  mentioning the token, so restoring the retired construct passed;
- `assert "subagent-tool-discipline.md" in hook_src` was satisfied by the hook's
  comment about the relocation, so pointing the path at a nonexistent file passed;
- an `api-doc-lookup` activity detector fired in 98.6% of sessions because that
  rule's own text names `/api-ingest` and the rule is ambient.

## 2026-08-27-claude-config-2169-tautological-fixture

INCIDENT 2026-08-27 (claude-config #2169): a tombstone entry asserting an obsolete
staged spec would be re-detected if re-staged. 5 mutations run; M4 "point the
tombstone at a symbol that never shipped" **passed all 23 tests**, because
`_fake_repo` wrote the marker into the file it then searched. Adding the
real-artifact assertion killed it. Same session, same class as an off-by-one drift
guard (`src.count("_git(") - 2` computing `3 <= 4`, so a fifth call would pass at
`4 <= 4`) — both are guards blind to the drift they exist to catch.

## 2026-08-26-claude-config-basename-backup-collision

`BACKUP / t.name` collides for `rules/X.md` and `docs/rule-reference/X.md` — the
ambient rule and its own reference doc, which is EXACTLY the pair a
rule-relocation change touches. The second `copy2` overwrote the first, so
"restore" wrote the REFERENCE prose into the ambient RULE. Had the sha check not
been there, every subsequent verdict in the batch would have been measured against
a corrupted tree while `git diff` looked plausible.

## 2026-08-29-mcp-servers-1359-bare-test-name-false-caught

A 7-mutation run over the new slack-gov write/search contracts reported **7/7
CAUGHT** with a green baseline and a clean post-restore check. Every verdict was
false: the harness invoked `python -m unittest <bare_test_name>`, unittest
resolved each name as a MODULE, all seven runs died in the loader, and the
non-zero exits were scored as catches. Zero mutations were ever evaluated.

What made it survive self-review is that every surrounding signal looked right --
baseline green, verdicts unanimous, restore clean, post-restore baseline green
again. The exit code is the only channel the harness read, and a loader failure
and a caught mutation are indistinguishable through it.

Detected by printing the failure message for two of the seven, which read
`ERROR: <name> (unittest.loader._FailedTest.<name>)` rather than naming any
assertion. Rewritten to run the whole module and match the expected test name
against the parsed failure set, the same mutations scored 8/8 CAUGHT (one added),
each naming its own assertion, and two carried legitimate collateral failures
that the earlier run could not have shown.

Later in the same session the corrected harness earned its keep twice more: a
wrong-selector mutation was caught ONLY by a byte-level hash pin (a change
detector, not a semantic check), which is what motivated
`test_terraform_selectors_match_the_state_unit_they_claim`; and a vacuity
mutation -- renaming all 12 selector kinds so the new guard collected zero pairs
-- was caught only because that guard carries a `pairs >= 12` floor.
