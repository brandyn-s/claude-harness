# Search Efficiency

BOUND: discover filenames first; narrow path/type and cap output before reading spans. Truncated output is not exhaustive.

ZSH_ZERO: unquoted *, ?, or [ can abort before execution. Quote patterns/URL queries (or use tool fields), and verify exit status + stderr before any zero-hit claim.

INSTRUMENT_DIALECT: a tool's DIALECT can return 0 while the match is present, so COUNT_OVER_SILENCE's control is necessary but not sufficient. Measured 2026-08-29: BSD `grep` bails on a Mach-O binary (0 where `strings -a` finds 12); `git grep -E` has no `\b`, so every `\b` pattern returns 0 repo-wide, retro-invalidating two earlier "confirmation passes".

ONE_SIDED_OUTPUT: truncation also manufactures FALSE POSITIVES. A CLI-rewritten config REORDERS keys, so `git diff | head -N` shows `-key` with its `+key` far below the cut, reading as deletion. Compare KEY SETS, never a line diff.

HANDOFF: hooks cannot inspect commands pasted to the user. Before handoff:
1. Quote arguments containing [, *, ?, or = (example: -F 'environment_ids[]=N').
2. Resolve placeholders; never ship literal <id>.
3. Verify flags/types against the API contract.
4. Prefer forms without shell-active characters or use documented stdin/input.
5. Each `!` bash-input runs a FRESH shell: exported env/credentials from one
   handed-over command never reach the next. Hand ONE self-contained command
   (or a staged script) — never a sequence assuming shell state persists.
   Measured 2026-08-22: a cosign sign+attest ceremony failed 3 operator runs
   because the `eval export-credentials` and the attest were separate `!` lines.
5. Confirm the command can reach its target from the user's shell; name the
   required bastion, exec path, or in-network runner when direct access is absent.
6. LENGTH is a correctness property: a one-liner long enough to WRAP can be pasted
   as two lines, and the break lands between a flag and its argument — not a
   quoting error the earlier items catch, since every value was quoted correctly.
   Beyond roughly one terminal width, stage a script and hand over the short
   invocation (`bash ~/path/verify-thing.sh`), which is also re-runnable and
   reviewable; verify it by RUNNING it first. Narrative:
   `rules/incidents/search-efficiency.md#2026-08-26-wrapped-query-flag`.

GUARD pattern="this is illustrative; they will replace the placeholder":
  REFUSE. Angle-bracket placeholders are shell-active in zsh. Resolve every
  value or state that you cannot; do not hand over a command that cannot parse
  or cannot reach its target.

FORBIDDEN: treat aborted/truncated output as absence OR as a positive finding, read a zero from an instrument with no positive control, or cite hook coverage for a handed-over command.

SEMANTIC_ZERO: before "not documented," search the bare entity, run qualified queries only additionally, and corroborate by deterministic topic-filename search.

CONTEXT_WINDOW_ZERO: `grep -oE '.{60}TOKEN.{20}'` returns EMPTY when TOKEN sits <60 chars from its line start — `.` never crosses newlines, so a fixed-width context prefix is line-bound even though a Python `text[i-60:i]` slice spans lines. Measured 2026-08-22: plain grep counted 4 hits, the context form returned 0, and the wrong diagnosis ("huge lines defeat BSD grep") survived until re-examined at distill. For cross-line context around a match, slice in Python; never infer tool breakage from a context-window regex's zero.

FRAMEWORK_FIRST: for broad code analysis, discover the declaration mechanism, search its structural idioms, then use generic value patterns as confirmation. Follow skills/code-explore/SKILL.md.

JSON_FIELD: never grep serialized JSON for a field value — spacing is serializer-dependent (`"k":"v"` compact vs `"k": "v"` pretty), so a literal pattern silently reports 0 against the other format. Test fields with a parser predicate (`jq -r '.k'`, json.loads). Measured 2026-08-22: a compact-format grep over pretty-printed hydration files reported 0 UNKNOWN merge states while 21 existed; the jq re-poll reclassified 5 PRs.


JSON_ABSENCE: the parser predicate can be wrong too. `jq '.k // "MISSING"'`
cannot detect key ABSENCE — `//` coalesces on null-or-false, so an explicit
`null` and a missing key return the SAME value. Whenever null and absent mean
different things, test `has("k")` and branch on that. Measured 2026-08-25:
probing `mergeQueueEntry` with `// "ABSENT"` reported ABSENT for all 31 PRs,
collapsing the distinction the merge-safety logic depends on — explicit null
means NOT QUEUED, a missing key means queue state was never observed and CLEAN
must not be read as ready. The `has()` re-probe showed all 31 were real nulls.

COUNT_OVER_SILENCE: prefer a predicate that emits a NUMBER over one that emits nothing, and
pair every zero with a known-positive control in the SAME command. FOUR predicates in one
session (2026-08-24) returned empty output that was read as a negative result: `grep -qv`
(BSD, 109 non-matching lines present), `sed -n '/a\|b/p'` (BSD BRE, matched the literal
`a|b` on a passing run), `grep … | head -5 || echo "no matches"` (the `||` binds to `head`,
which exits 0 on empty input), and a hand-typed epoch that widened a log window by 365 days
so PRE-EXISTING errors read as new ones. The shared defect is one habit, not four bugs. A
zero is trustworthy when the same command also reports a nonzero it should find — e.g.
`0 errors / 169 total events`.

DERIVE_TIME_WINDOWS: never hand-type an epoch. `git-hygiene` forbids hand-typing an object ID
because 40 hex characters carry no checksum; an epoch is worse — it is plausible at every
magnitude, so a year-off value returns a SUCCESSFUL query instead of an error. Measured: a
hand-typed `--start-time` put a post-deploy error search 364.97 days early and returned real
tracebacks from 16 days before the deploy. Compute the window in the same shell from
`datetime`.

RECALL_NEVER_CAPPED: never `| head`/`tail` a grep over a KNOWLEDGE source
(`agent-memory/topics/`, `rules/`, `knowledge-base/topics/`). Elsewhere truncation
distorts a COUNT and the rule above catches it; on a recall grep it silently
removes the entry you are looking for, and there is no tell — you cannot miss what
you never saw, so you act as if the knowledge does not exist. Use `grep -c` to size
the match set, then read all of it. Narrative:
`rules/incidents/search-efficiency.md#2026-08-30-capped-recall-grep`.

Incidents: rules/incidents/search-efficiency.md. Patterns: skills/code-explore/references/search-strategies.md.
