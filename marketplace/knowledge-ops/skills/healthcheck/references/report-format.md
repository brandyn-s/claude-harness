# Report Format

Present a summary table. **Check 0 (freshness) appears first**:

```
=== Architecture Health Check ===

Freshness: PASS — on main (59fad0b = origin/main, 0 ahead)
Hooks:     PASS — 408 tests passed, 42/44 hooks covered
Config:    PASS — 6 files valid
Skills:    PASS — 68 skills validated
Memory:    PASS — 24 entries, all consistent
Paths:     PASS — 52 paths verified
Drift:     PASS — counts match, no phantoms
Routing:   PASS — 47 rules valid, no dead references
Targets:   PASS — 8 output targets verified
Orphans:   PASS — no unreferenced files found
Manifest:  PASS — 81 skills registered, no duplicates or phantoms
Indexes:   PASS — 11 code-graph DBs + 22 code-search projects clean

Overall: HEALTHY
```

**When Check 0 WARNs**, prepend a one-line banner and stamp each subsequent
result with `[POSSIBLY STALE]`:

```
=== Architecture Health Check ===

⚠ STALE CHECKOUT — main on 'checkpoint/20260527000921', 27 commits behind origin/main.
   All findings below may reflect stale state. See _check_freshness.py output above.

Freshness: WARN — on 'checkpoint/20260527000921' instead of main (27 behind)
Hooks:     FAIL [POSSIBLY STALE] — 7 failed, 659 passed
Skills:    FAIL [POSSIBLY STALE] — 16 Tier-A violations
...

Overall: UNHEALTHY — but check freshness first; many findings may resolve after `git pull --ff-only`.
```

If any check is FAIL: `"Overall: UNHEALTHY — {N} checks failed"`
If any check is WARN: `"Overall: HEALTHY (with warnings)"`

**WIP-FAIL under staleness** (Check 0 = WARN): a FAIL is *WIP-induced* when it
is a drift-gate failure (ARCHITECTURE.md count vs disk, settings.json vs
settings.example.json — i.e. `test_architecture_drift_check`) or a manifest
FAIL, AND the checkout is stale. These clear after `git pull --ff-only` +
committing local WIP, so they should NOT alone drive a hard UNHEALTHY. Label
them `FAIL (WIP)` and, when the ONLY failures are WIP-induced, report
`"Overall: HEALTHY-with-warnings (the only FAIL is WIP/stale — reconcile to
main + re-run to confirm)"`. A non-WIP FAIL on a stale checkout (e.g. a hook
test unrelated to drift) is still a real UNHEALTHY — do NOT down-weight it; the
`[POSSIBLY STALE]` stamp already flags that reconciling may resolve it.
`_check_all.py` implements this distinction; relay its verdict directly.

**Severity precedence**: `Manifest+Drift: FAIL` (exit 2 from `_check_manifest.py`)
counts as a real FAIL — the marketplace bundle is shipping missing files.
`Manifest+Drift: WARN` (exit 1) is rebuild-fixable drift.

For failures, list actionable fix suggestions. Offer to fix auto-safe issues
(orphan memory entries, missing MEMORY.md references, dead routing rules,
orphan hook/script deletion, stale branch cleanup).
