# Eval: /goal vs custom never-stop-early orchestration

**Date:** 2026-05-23
**Status:** design — needs interactive execution
**Outcome owner:** you (only person who can run an interactive session)

## Hypothesis

Anthropic's `/goal` command (v2.1.139, May 11 2026) provides a native
completion-condition mechanism. The question this eval answers:

> Does `/goal` reliably replace any of `rules/never-stop-early.md` +
> `hooks/promise-checker.py` for the kind of multi-turn tasks where
> those custom layers currently fire?

Concretely, the custom orchestration we'd potentially retire:

| Component | Current behavior |
|---|---|
| `rules/never-stop-early.md` | Ambient rule — prohibits session-closure phrases ("let's continue in a new session", etc.). Loaded every turn. |
| `hooks/promise-checker.py` | `Stop` hook — scans the last assistant turn for `BANNED_PHRASES` and `PROMISE_PATTERNS` without matching write-tool use. Returns exit 2 to keep the model working. |

`/superplan` is NOT in scope — it's a planning skill, structurally
different from a completion-condition guard.

## Test design

### Tasks (3, of different shape)

Each task is a single prompt chosen to be at the edge of where the
custom orchestration currently fires. Same prompt in both arms.

**T1 — Mechanical, easy to cut short:**
> "Add a `--dry-run` flag to `scripts/build-marketplace.py` that
> prints what would be built without writing files. Cover both
> per-plugin builds and the root `marketplace.json` write. Verify by
> running with `--dry-run`, then without, and comparing the resulting
> file tree to confirm no writes when `--dry-run` is set."

Watch for: does Claude stop after writing the flag without running
the verification step?

**T2 — Exploratory with a clear endpoint:**
> "Audit the 53 hook scripts in `hooks/*.py` for any that read stdin
> without handling JSON decode errors. Produce a list of file:line
> findings. Don't fix anything — the deliverable is the audit
> report itself, ranked by likely impact."

Watch for: does Claude stop after a partial scan ("here are some I
found, let me know if you want more")?

**T3 — Iterative until success criterion:**
> "Run `pytest hooks/test-hooks/` until it passes clean
> (0 failures, only env-dependent skips). Each failure is a real
> bug to fix, not a flake. Stop only when the suite is green."

Watch for: does Claude declare "done" after one fix that doesn't
fully clear the suite?

### Conditions (A/B per task)

**Arm A — Native `/goal`:**
1. Disable the custom layer for the session:
   ```bash
   # Backup and remove the rule
   mv rules/never-stop-early.md rules/never-stop-early.md.bak
   # Set the env var the promise-checker honors (if added — see "Setup needed" below)
   export CLAUDE_SKIP_PROMISE_CHECKER=1
   ```
2. Open Claude Code session. Prompt:
   ```
   /goal <task verbatim>
   ```
3. Let it run.
4. Restore at the end:
   ```bash
   mv rules/never-stop-early.md.bak rules/never-stop-early.md
   unset CLAUDE_SKIP_PROMISE_CHECKER
   ```

**Arm B — Custom layer (control):**
1. Custom layer active (default state).
2. Same prompt, but without `/goal` — just the task text directly.
3. Let it run.

Run order: alternate A then B per task to avoid order-of-day bias.
Different sessions for each (no shared context).

### Setup needed (one-time)

`hooks/promise-checker.py` currently has no skip env var. Add at the
top of `main()`:

```python
if os.environ.get("CLAUDE_SKIP_PROMISE_CHECKER") == "1":
    sys.exit(0)
```

(Without this, Arm A's "no custom layer" condition is contaminated
by promise-checker still firing.) This is a one-line change, can
ship in the same PR as this eval doc.

## Metrics

Per task, per arm, record:

| Metric | How to measure |
|---|---|
| **Completed in 1 session** | Did the task actually finish, or did Claude stop mid-way? |
| **Turns to completion** | Count assistant turns from start to "done" |
| **Premature stop attempts** | Did Claude attempt session-closure phrases? Count them |
| **Verification performed** | For T1/T3, did Claude run the verification step the task asked for? Y/N |
| **Output quality** | Subjective 1-5: did the deliverable match the goal? |

Approximate token use is fine if usage data is available; not required.

## Decision rules

After all 3 × 2 = 6 runs:

- **`/goal` replaces never-stop-early entirely** if Arm A completes
  3/3 tasks with **zero** premature-stop attempts and same-or-better
  output quality than Arm B.
- **`/goal` replaces never-stop-early for some shapes** if Arm A
  completes mechanical/iterative (T1, T3) cleanly but underperforms
  on exploratory (T2). Action: keep `never-stop-early.md` but
  document that `/goal` is the preferred mechanism for narrowly-
  scoped tasks.
- **`/goal` doesn't replace either** if Arm A has ≥1 premature stop
  per task. Keep both; don't churn.

`promise-checker.py` evaluated independently: if Arm A has 0
premature-stop attempts across all 3 tasks even with the hook
skipped, the hook is redundant in `/goal` mode and can be gated on
"non-`/goal` sessions only."

## What this eval is NOT

- Not a load test (n=3 per arm is the minimum signal, not statistical proof).
- Not measuring `/goal`'s capabilities in general — only its overlap
  with our custom orchestration.
- Not blocking adoption of `/goal` for other use cases. Even if this
  eval concludes "keep both," `/goal` may still be the right tool
  for explicit goal-seeking tasks.

## Cost estimate

- 6 sessions × ~15-30 min each = 1.5-3 hours of interactive time.
- Token cost depends on tasks; T3 (iterative pytest) is the most
  expensive. Budget $5-15 for the full eval.

## Pre-registration

Once a run starts, do not adjust the prompt or success criteria
mid-eval. If a prompt turns out to be flawed (e.g., T3's pytest
suite happens to be green at session start so there's nothing to
fix), abort the run cleanly and replace the prompt before the next
attempt. Document the change in this file.

## Artifacts to capture

For each of the 6 runs, save a single markdown file:

```
docs/plans/2026-05-23-goal-eval/<task-id>-<arm>-<timestamp>.md
```

Containing:
- The exact prompt used
- The arm (A/B) and whether the custom layer was disabled
- Turn count and final state
- Premature-stop attempt count
- Output-quality score and one-paragraph rationale
- A copy of the deliverable

Aggregate at the end into a summary table in this file under a new
`## Results` section. Decision then follows the rules above.
