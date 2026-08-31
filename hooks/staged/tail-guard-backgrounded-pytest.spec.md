# Staged hook spec: tail-guard — add pytest/unittest to VERDICT_COMMANDS, scoped to BACKGROUNDED runs

Target: `hooks/bash-tail-buffering-guard.py` (already installed; this extends
`VERDICT_COMMANDS` / `check_trailing_status_swallow`'s sibling pipe check).

## Problem

`hooks/bash-tail-buffering-guard.py` exists precisely for this mechanism, and its
own docstring already states the failure verbatim:

> Under `run_in_background` the CONSUMER is the harness: the task-completion
> notification reports the filter's exit code as the task's, so a verdict
> command that FAILED is announced to the model as `exit code 0`.

But `VERDICT_COMMANDS` (line ~170) is:

```
pr-merge-verified\.py
terraform\s+(plan|apply)
cargo\s+(test|build)
npm\s+(test|run\s+build)
```

`pytest` and `python3 -m unittest` are **absent** — deliberately. The v8 docstring
records why:

> NARROWED vs the spec: `pytest` / `python3 -m unittest` were dropped because they
> failed `test_allows_grep_on_log_named_after_pytest`, which pins the routine
> pytest-then-grep idiom as allowed. That took the rate from 3.547% to 1.225% and
> lost no measured coverage (all 5 incidents were the merge verifier). See
> VERDICT_COMMANDS before adding an entry back.

**"Lost no measured coverage" is now falsified by a measured incident.**

2026-08-06: `pytest hooks/test-hooks/ -q 2>&1 | tail -6` was launched with
`run_in_background: true`. The output file was **empty** (the pipe buffers until
exit) and the task notification reported **`exit code 0`** — which was `tail`'s
status. That was read as "full hook suite green" and came within one turn of
shipping into a PR body as the verification claim. Two independent rules
(`platform-constraints.md` FORBIDDEN ×2, `verify-effectiveness.md` line ~342
"Re-check exit codes UNPIPED") already cover the mechanism in prose. The hook
built to enforce it could not fire, because the verdict command was pytest.

## Why prose has not fixed this

The mechanism is documented at **three** ambient sites and still fired. That is the
standard signal for enforcement over wording. The hook is already installed, already
handles `run_in_background`, and already has the right architecture — the gap is one
missing entry in a tuple, gated on a measurement nobody has re-run since the FP
finding.

## Why the original narrowing was right, and what changes

The FP that forced the removal is the **interactive** idiom:
`pytest ... | grep -i fail` to filter output when you do NOT depend on the exit code.
That is legitimate and common (hence `test_allows_grep_on_log_named_after_pytest`).

The dangerous shape is strictly narrower: **backgrounded** + piped + verdict-bearing.
When `run_in_background` is true the harness becomes the exit-code consumer, so the
laundering is structural rather than merely possible. Scoping the new entries to
backgrounded invocations therefore:

- catches the 2026-08-06 incident (background + `| tail`), and
- leaves the pinned interactive idiom untouched, so the FP rate that drove the
  removal should be ~unchanged.

## Detection / decision logic

Add to the existing check, NOT as a new hook:

1. Extend `VERDICT_COMMANDS` with `pytest` and `python3\s+-m\s+(unittest|pytest)`,
   but tag the two new entries as **background-only**.
2. Fire only when ALL hold:
   - the command matches a background-only verdict command at the COMMAND position
     (reuse the existing token-anchoring + `WRAPPER_PREFIXES` skipping),
   - it is piped to a buffering filter (`tail` without `-f`, `grep`, `head`),
   - `tool_input.run_in_background` is `true`.
3. Message must name BOTH consequences, since they are separate: the output file
   will be empty until exit, AND the reported exit code is the filter's.
4. Suggested remedy in the message: `cmd > /tmp/out.txt 2>&1; echo $?` — redirect,
   read the file, read the code unpiped.

## Before installing — required measurement

Per `verify-effectiveness.md` (<10% block rate) and the v8 precedent of replaying
against the historical corpus:

1. **Replay** the new predicate over the ~49.5K-command historical Bash corpus the
   v8 measurement used. Report the true-delta fire rate (commands that newly fire).
2. **Assert the pinned FP test still passes** —
   `test_allows_grep_on_log_named_after_pytest` must stay green. If the
   background-only scoping is implemented correctly this test is untouched, and its
   passing is the control proving the narrowing held.
3. **Add a known-positive fixture** reproducing the 2026-08-06 command shape
   (background + `pytest | tail -6`) and confirm it FIRES.
4. **Mutation-verify**: (a) drop the `run_in_background` condition → the FP test
   must FAIL (proving the scoping is load-bearing, not decorative); (b) remove the
   new entries → the known-positive must stop firing.
5. If the true-delta rate exceeds ~1pp over the current 1.225%, stop and report
   rather than installing — the FP finding that removed pytest was measured, and
   this spec does not authorize regressing it on argument.

## Escalation path

If the measured rate is unacceptable even when scoped to backgrounded runs, the
fallback is NOT more prose (three sites already failed). It is to make the harness
surface the real status: have the guard rewrite the command to append
`; echo "RC=${PIPESTATUS[0]}"`, so the true producer status reaches the transcript
even when the pipeline's own exit code is the filter's.
