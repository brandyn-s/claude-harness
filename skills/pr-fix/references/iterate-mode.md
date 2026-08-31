# Iterate Until Green (Phase 5, --iterate mode)

When `--iterate` flag is set or the user requests continuous fixing ("keep going until green"), the skill loops through diagnose → fix → wait → re-check up to 3 times per item.

## 5a: Wait for a complete, affirmative result

After pushing, wait 90 seconds, capture the complete check snapshot, and use
the deterministic state classifier:

```bash
gh pr checks <number> --repo <org/repo> \
  --json name,state,bucket > <checks-json>

CHECK_STATE=$(python3 "$PR_FIX_DIR/scripts/pr_fix_state.py" \
  checks --input <checks-json>)
```

Handle every state explicitly:

- `PENDING`: wait 30 seconds and recapture; stop after 10 polls.
- `PASSED`: report green. This requires at least one passing check and no
  failure, cancellation, pending, or unknown bucket.
- `FAILED`: continue to 5b.
- `NO_CHECKS`: CI has not registered. Continue polling within the same cap;
  if it stays empty, report non-green and stop.
- `CANCELLED`: report cancelled, not green. Rerun only when the user has
  authorized reruns.
- `NO_PASS_EVIDENCE` or `INDETERMINATE`: report non-green and stop.

Never infer success merely because pending and failing arrays are empty.

## 5b: Compare content-aware failures

Re-read every current failed check's log. Build a JSON array containing
`name`, `bucket: "fail"`, and `failureDetail`. `failureDetail` is the current
actionable error or assertion excerpt—not the check name and not an old run's
log:

```json
[
  {
    "name": "test",
    "bucket": "fail",
    "failureDetail": "AssertionError: expected alpha, got beta"
  }
]
```

Compute a content-aware signature:

```bash
FAILURE_SIG=$(python3 "$PR_FIX_DIR/scripts/pr_fix_state.py" \
  failure-signature --input <failures-json>)
```

The helper sorts check identity plus normalized diagnostic content and removes
common timestamp/run-ID noise. Stop only when this complete signature equals
`PREV_FAILURE_SIG`. The same check name with a different error is progress,
not repetition. Save a changed signature, increment the cycle, and loop to
Phase 2c up to the three-cycle cap.

## 5c: Iteration report

After each cycle, log:

```
Iteration 2/3: mcp-servers #201
  Previous fix: added missing import (cycle 1)
  New failure: type error in hologram/server.py line 42
  Fix: corrected return type annotation
  Pushed: commit abc1234
  Waiting for CI...
```

## Iteration caps and rules

- **Max 3 cycles per item** — after the third failed cycle, stop and report for manual review.
- **90s initial wait + 30s polls, max 10 polls** — caps the per-item wait at ~5 min.
- **Stop on green** — do not attempt to merge; let auto-merge handle it.
- **New error per cycle** — if the same error repeats across cycles, the fix isn't landing; stop and report instead of looping.
