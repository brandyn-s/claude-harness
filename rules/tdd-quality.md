---
paths:
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/test_*"
  - "**/tests/**"
  - "**/test-hooks/**"
---

# TDD Assertion Quality - Watch for AI Shortcutting

When tests fail during TDD cycles or after code changes:

## The Problem

AI agents (including Claude) take the "simplest path to green" when tests fail:
- Weakening assertions (`toBe` -> `toBeTruthy`, exact match -> partial match)
- Removing test cases that expose the real bug
- Patching the test to match wrong behavior instead of fixing the code
- Making mocks return the expected value instead of testing real logic

This happens silently. The test passes, CI goes green, but the test no longer validates what it was designed to validate.

## The Rules

1. **Review test changes separately from implementation changes.** If both tests and code changed in the same commit, read the test diff first. Ask: "Did the test get weaker or stronger?"

2. **Never auto-approve a test change that makes an assertion less specific.** If a test previously checked `result === 42` and now checks `result > 0`, that's a regression unless explicitly justified.

3. **Failing tests are signals for YOU to inspect, not just problems for the model to solve.** When a test fails, examine the test before asking the model to fix it. The test may be correct and the code may be wrong.

4. **Watch for these test anti-patterns after AI edits:**
   - `expect(result).toBeTruthy()` replacing a specific value check
   - Test cases deleted or commented out
   - Mock return values changed to match buggy output
   - Error case tests replaced with "skip" or "todo"
   - Assertion count reduced in a test that previously had multiple checks

Sources: r/ClaudeCode "The workflow that actually makes Claude Code fast" (2026-03), r/ClaudeCode "Six Claude Code Strategies" (2026-03)

## Absorbed testing-strategy reference (items 1-9)

Mock/assertion gate functions (microsoft/fluidframework) and test placement
and strategy (dtolnay, BurntSushi, alex, trailofbits) moved to
`rules/incidents/tdd-quality.md` — general testing guidance, read on demand.
The platform-specific gotchas that recur here stay ambient below.

## Cross-Platform Home Isolation in Tests (2026-06-12)

10. **Set BOTH `HOME` and `USERPROFILE` when a test isolates the home
    directory.** `Path.home()` / `os.path.expanduser("~")` read `HOME` on
    POSIX but `USERPROFILE` on Windows. An env overlay that sets only
    `HOME` passes on macOS/Linux and fails ONLY on the Windows CI leg —
    worse, the code under test silently writes to the runner's REAL
    profile, so the failure surfaces as a missing file in the tmp dir,
    not as an obvious env bug.

    ```python
    env={"HOME": td, "USERPROFILE": td}
    ```

    Incident: claude-config PR #1203 (2026-06-12) —
    `test_production_invocations_logged` failed 1/965 on windows-2022
    only; cost one disable-auto → fix → re-arm merge-queue cycle. The
    macOS and ubuntu legs structurally cannot catch this class: if a
    test overlays the home dir, the Windows leg is the only oracle.

11. **Platform-guard executable-bit assertions.** `os.chmod(path, 0o755)`
    is a no-op for the POSIX permission bits on Windows, so
    `path.stat().st_mode & 0o111` stays falsy and the assertion fails
    ONLY on the windows CI leg — while the chmod call itself is harmless
    everywhere. Keep the chmod; guard the assertion:

    ```python
    if sys.platform != "win32":
        assert created.stat().st_mode & 0o111
    ```

    Incident: claude-config PR #1224 (2026-06-12) —
    `test_apply_create_file_convention` failed 1/746 on windows-2022
    only; cost one CI round-trip. Same shape as item 10: a test
    asserting POSIX-only semantics has the Windows leg as its only
    oracle.

    **11b — the worse variant: a platform-unrunnable HARNESS makes assertions
    VACUOUS, not failing.** Guarding one assertion (above) is the benign case;
    the malignant one is when the POSIX-only construct is the test's *seam*.
    A fake CLI written as one file named `gh` with a shebang + `chmod 0o755`
    is unrunnable on Windows (no shebang honoured, no exec bit), so every
    invocation returns nothing, the code under test falls through to its
    timeout path, and the assertions run against an EMPTY command log. They
    do not error — they assert on nothing. Coverage disappears on the only
    leg that can catch a platform bug (item 11's own moral, inverted).

    Fix by giving the platform its own dispatch, never by skipping:
    write the logic to a `.py`, then a `gh.cmd` shim on Windows
    (`@echo off` + `"{sys.executable}" "{script}" %*` — cmd.exe resolves a
    bare `gh` via PATHEXT), shebang + exec bit on POSIX.

    And **verify the platform branch locally before pushing** — emulate the
    MECHANISM, not the platform string, and prove the emulation with a
    NEGATIVE CONTROL (run the OLD approach and confirm it produces nothing
    the platform could execute). Faking `sys.platform` alone is not a valid
    emulation: on macOS the file genuinely has the exec bit, so the
    assertion passes either way and the "emulation" proves nothing.

    Incident: claude-config #1748/#1753 (2026-07-28) — 5 windows-2022
    assertions were vacuous for a full CI cycle (`gh calls were: []` in
    every failure message was the tell: an empty log, not a wrong one).
    The mechanism-emulation + negative control ran in seconds locally; the
    round trip that found it cost ~4 min and blocked the PR chain.

12. **Scripts with side effects on real user paths need an env-overridable
    path, and their tests must set it.** A script that hardcodes
    `Path.home() / ...` as a write target pollutes the real directory on
    every test run — and half-measures rot: supergoal's RC4 fix
    (2026-05-29) stopped test runs from *committing* but left the local
    writes, which accumulated as B38-B52 ledger noise + terminal-doc
    rewrites in the production knowledge-base until /pr-fix dirty-tree
    discovery caught it (2026-06-12, fixed in #1230). The pattern:

    ```python
    override = os.environ.get("MYTOOL_OUTPUT_DIR")
    out_dir = Path(override) if override else Path.home() / "real" / "path"
    ```

    plus a test assertion that the override dir actually RECEIVED the
    artifacts (proves the redirect end-to-end, not just rc). Applied three
    times on 2026-06-12: `SUPERGOAL_PLANS_DIR` (#1230),
    `CLAUDE_RED_MAINS_STATE` (#1240, script + banner module), following
    the `CLAUDE_TOPICS_DIR` precedent in subagent-stop.py. A repo-wide
    sweep for further live instances came back clean (8 candidates, all
    already isolated or main()-only) — apply this at authoring time for
    any new home-path-writing script.

13. **A test preamble that sets a MODULE-GLOBAL via env leaks across files
    under `unittest discover`.** A new test file's import-time
    `os.environ.setdefault("REPORT_S3_PREFIX", "test")` ran BEFORE a sibling
    suite (alphabetical import order under `discover`), pinning the module
    global `Q.PREFIX="test"` for the WHOLE run — so the sibling's hardcoded
    `otel-detection-reports/...` fixture keys silently stopped matching and
    ~30 of its tests failed. Each suite passed ALONE; only `discover` (the
    real CI condition) surfaced it. Two fixes, both needed: (a) the preamble
    sets the REAL prefix the other suites expect (not a private "test"
    value), and (b) fakes/fixtures reference the module global
    (`Q.PREFIX`) instead of hardcoding the string, so they self-align with
    whatever the module uses. ALWAYS run `python3 -m unittest discover`
    (not just the new file) before declaring a multi-file test change green —
    a per-file green is blind to cross-file module-global drift. (mcp-infra
    #536, 2026-06-27. Fittingly, this is itself the producer/consumer-drift
    class — two test files validated in isolation, drifting at a shared
    contract.)

14. **A standalone script named `test_*.py` with a MODULE-LEVEL `sys.exit()`
    crashes pytest COLLECTION, not just its own run.** `pytest <dir>` IMPORTS
    every `test_*.py` to collect it — so a self-runner that computes a result
    and calls `sys.exit(...)` at module level raises `SystemExit` during import
    → pytest `INTERNALERROR`, exit code **3**, and the WHOLE run aborts (even
    tests that already passed). Guard a standalone-runnable script's execution
    with `if __name__ == "__main__":` so import (collection) is a no-op and
    direct `python3 scripts/test_X.py` still exits. A repo that runs
    `pytest scripts/` over a dir mixing real tests + self-runner scripts needs
    EVERY self-runner guarded — pytest collects **alphabetically**, so one
    unguarded file aborts before later ones run, and fixing only the first just
    advances the crash to the next (hunt all variants:
    `grep -lE '^sys\.exit' scripts/test_*.py`). (mcp-servers #716, 2026-06-27:
    3 unguarded self-runners among 52 guarded ones turned `Validate` red on
    main, blocking every PR; the tell was `unit-tests` logging "9 passed, 0
    failed" *then* `INTERNALERROR` — a collection crash, not a test failure.)

15. **A `test_*.py` that REPLACES an imported module's attributes without a
    `try/finally` restore poisons pytest collection of sibling files.** A
    standalone-runner test that does `import othermod as R` then
    `R.some_fn = lambda ...` inside a test function (or a module-level
    `_install_stubs()`) mutates the SHARED `sys.modules` object — every
    later-collected `test_*.py` importing the same module sees the stub, not the
    real function. Alphabetical collection order decides the victim:
    `test_daily_abuse_wiring.py` (d) set
    `otel_session_review.fetch_session_events = lambda day:` (signature lacks
    `since_ts`) and never restored it, so `test_fetch_session_events_shard.py`
    (f) saw 0 sharded queries + a `since_ts` TypeError — 3 failures that turned
    `unit-tests` red on main and blocked EVERY open PR. Each file passed ALONE
    and via its own `__main__` runner; only `pytest scripts/` (collection)
    surfaced it (same "run collection, not per-file" moral as #13). Fix: save
    the originals and restore in `try/finally` (or use `monkeypatch.setattr` /
    `addCleanup` when a fixture/TestCase is available). Hunt variants:
    `grep -nE '^\s*\w+\.\w+ *= *(lambda|fake_)' scripts/test_*.py` for
    unrestored module-attribute assignments. (mcp-servers #747, 2026-07-03 — a
    dependabot `setup-python` pin bump was blocked by this unrelated pre-existing
    breakage; failing FILE ≠ changed file was the tell it wasn't the bump.)
16. **A test that skips MUST use `pytest.skip()` — NEVER `sys.exit(0)` — when
    the suite is collected by pytest.** A CI "unit-tests" job typically runs
    `pytest <dir>/ -v`. pytest collects every `test_*` function; if one calls
    `sys.exit(0)` to "skip" (the idiom for a bare `python3 test_file.py`
    runner), pytest catches the resulting `SystemExit` and reports the test as
    a **FAILURE**, not a skip — turning the whole keyless job red. This is the
    **integration-test-in-a-keyless-suite** trap: a test that needs creds/boto3
    you want to skip cleanly when they're absent. Dual-runner-safe skip:

    ```python
    def _skip(reason):
        if "pytest" in sys.modules:        # pytest is driving collection
            import pytest; pytest.skip(reason)
        sys.exit(0)                         # bare `python3 test_file.py` runner
    ```

    **This is the 4th instance of the keyless-CI class** (mcp-servers #640
    boto3 `ModuleNotFoundError` on a SQL-shape test; #645 `boto3.resource`
    AttributeError on the dedup test; #647 this `sys.exit`-skip on the live-seam
    test). The class signature: a test passes in the dev venv (has boto3 /
    anthropic / creds) but fails the minimal keyless CI job. **Pre-push gate**:
    reproduce the keyless job locally in a pytest-only venv —
    `python3 -m venv /tmp/ci-venv && /tmp/ci-venv/bin/pip install pytest &&
    env -u <CRED_VARS> /tmp/ci-venv/bin/python -m pytest scripts/ -q` — before
    pushing any new `test_*.py` that imports boto3/anthropic or reads creds.
    Both the import (guard with `try/except ImportError: pytest.skip(...)`) AND
    the skip mechanism must be keyless-safe. (T0-hook candidate: a PreToolUse /
    pre-push check flagging `sys.exit(` inside a `def test_` body — deferred
    pending a historical-replay fire-rate check per verify-effectiveness.)

    **5th instance — DEAD-MOCK-FROM-RENAME (a new sub-mechanism, 2026-07-06,
    claude-config gather-vendor probe):** the test did NOT error keyless — it
    PASSED locally and FAILED keyless-CI. Cause: the test's `run()` helper did
    `setattr(probe, "keychain", lambda: "test-key")`, but the probe rewrite had
    RENAMED that resolver to `resolve_key`. The monkeypatch bound to a dead name
    → the REAL resolver ran → on the keyless runner it returned None → the probe
    exited early to STDERR → empty stdout → `assert 'TRIPWIRE' in ''` failed. It
    passed ONLY because the dev machine's real Keychain/env had the key (a
    self-confirming pass, Gate-4). Two prevention hooks, both already in this
    rule but not run: (a) the keyless pre-push repro above WOULD have caught it
    (run it, don't just document it); (b) **after renaming a function that tests
    mock, grep the tests for `setattr(<mod>, "<OLD_NAME>"` / `monkeypatch.setattr(...<OLD_NAME>...)`
    — a mock bound to a renamed symbol is a SILENT no-op, not an error.** Cost:
    ~15 turns of misdiagnosis (I first blamed a `.ruff_cache` marketplace-hash
    leak — a real but SEPARATE bug in the same PR — before a pristine-clone +
    python3.12-keyless repro isolated the dead mock).

17. **When adding retry/backoff to a client, make the sleep injectable at
    authoring time and no-op it suite-wide in conftest.** A retry wrapper's
    exponential backoff makes every EXISTING loud-failure test (asserting
    "5xx/429 raises") pay the real 1+2+4+8s waits — the failure path now
    retries before raising. Pattern: module-level `_sleep = asyncio.sleep`
    referenced by the wrapper, plus an autouse conftest fixture that
    monkeypatches `<client>._sleep` to a no-op (retry COUNTS still assert;
    only waits are skipped). Patch the module attribute, not `asyncio.sleep`
    globally — global patching masks unrelated timing behavior. Incident:
    compliance-access-framework PR #83 (2026-07-15) — adding 429/5xx retries
    to two clients took the 479-test suite from 1.4s to 92s (one test hit
    30s); caught same-session via `--durations`, fixed with the injectable
    `_sleep` + autouse fixture (back to 1.6s).

23. **A shared `sys.modules` stub whose RETURN VALUE differs between test files
    breaks whichever file imports second — and filename sort order picks the
    victim.** Item 13 covers a module-global set via env; item 15 covers an
    unrestored module attribute. This is the third member of that family and the
    one no `try/finally` can fix, because the divergence is in the stub's
    *fidelity*, not in cleanup: two files each install a `boto3` stub at import
    time under `if "boto3" not in sys.modules`, the FIRST importer wins, and its
    stub is what every later suite gets. A weaker stub is invisible in isolation
    and fatal under `discover`.

    Rule: **a shared-module stub must be as capable as the most demanding suite
    that will receive it**, not merely sufficient for the file that declares it.
    Return a mock-like object that accepts any attribute and any call — never
    `None`, which turns a later suite's `_s3.get_paginator(...)` into
    `AttributeError` on `NoneType`.

    INCIDENT 2026-07-27 (mcp-infra #714): a new `test_admin_usage_cost.py`
    stubbed `boto3.client` to return `None`. It passed alone, and broke **13
    tests** in `test_anthropic_audit_v2.py` under `python -m unittest discover`
    — because `test_ad*` sorts before `test_an*`, so the weaker stub won the
    `sys.modules` race over that file's Mock-returning `_DummyClient`. Same
    moral as item 13: **run `discover`, not the new file alone**, before
    declaring a multi-file test change green.


35. **Combining test directories into ONE pytest invocation collides same-named
    modules — and the failure reads as catastrophic damage to the code, not as a
    bad command.** Items 13/15/23 are the shared-`sys.modules` family where one
    file's state leaks into another. This is its import-time twin: `conftest.py`
    (and any duplicated `test_*.py` basename) has no package qualifier, so with
    rootdir-relative module naming the FIRST directory collected wins the name
    `conftest`, and every later directory importing `from conftest import X`
    resolves against the wrong file.

    ```
    ImportError: cannot import name 'PYTHON' from 'conftest'
      (/repo/a separate skill (not included in this export))   # ← wrong conftest entirely
    ```

    **The tell is the timing, not the message: 42 "errors" in 2.15 seconds.** No
    real suite fails that fast. A whole-directory error count that arrives faster
    than the tests could have run is a collection fault, and a collection fault
    from an invocation you just changed is the invocation's fault.

    **CI is the spec.** If CI runs the directories as SEPARATE steps, run them
    separately — combining them for convenience creates a failure mode CI cannot
    have. Measured 2026-08-21 (claude-config): `pytest skills/ hooks/test-hooks/
    tests/` produced 42 phantom collection errors that read as merge damage
    mid-reconciliation; the same three run separately gave 2,594 / 1,554 / 16
    passed. Cost: one wrong diagnosis of a 278-commit merge.

    Cross-cutting, confirmed in 2 repos: the same mechanism hit private-ai
    2026-08-13, where `network/test_contract.py` and `terraform/tests/test_contract.py`
    collided on the module name `test_contract` and pytest rejected the second as an
    import-file mismatch. **If a repo genuinely must collect duplicate basenames in
    one run, set pytest's import mode to `importlib`** (that repo's fix) — it gives
    each collected path an isolated module identity. Otherwise keep the runs split
    and give every `conftest.py` sibling a unique basename.

36. **"Passes in isolation, fails in the suite" is only evidence of order-dependence
    when both runs executed the SAME BYTES — check checkout/version skew FIRST.** On a
    host with multiple checkouts (deployed `~/.claude`, worktrees, clones), the reflex
    repro — run the failing test alone in whatever checkout is handy — can silently run a
    DIFFERENT version of the code under test. The isolation pass then reads as "the test
    is fine alone → a sibling polluted it" (items 13/15/23 family) when the truth is the
    two runs disagree about what the function does.

    Procedure, before any ordering bisect: (1) confirm the repro checkout's file matches
    the failing run's — `git log -1 --format=%h -- <file>` in both, or diff them;
    (2) prefer re-running in the checkout that FAILED; (3) read the captured failure
    output first — a stderr note or an assertion payload often names the mechanism
    outright and skips the bisect entirely.

    INCIDENT 2026-08-22 (claude-config doc_accuracy_audit): the full hook suite failed
    `test_returns_none_when_projects_dir_missing` in a worktree at origin/main, while the
    same test passed in isolation in `~/.claude` — which was BEHIND main and predated the
    #2054 deployed-tree fallback that caused the failure. Two wrong hypotheses (order
    dependence, unrestored os patches) were pursued before the stored failure output was
    read; its captured stderr line ("using deployed projects root …") named the fallback
    directly. The failure was real on every up-to-date checkout whose HOST has a deployed
    `~/.claude/projects` — a non-hermetic test, not pollution. Fixed by pinning the
    fallback root (`deployed_base`) in the tests, mutation-verified.

39. **A SKIPPED mutation is an UNVERIFIED test — never report it inside a
    caught/total ratio.** `rules/tdd-mutation-testing.md` item 1 already REQUIRES
    asserting the anchor's occurrence count before writing. This item is what
    happens when you don't: a harness that prints `SKIP (anchor not found)` and
    continues, then reports "4/5 CAUGHT", has verified four tests and left one
    with **no evidence at all** — yet the ratio reads like a 20% miss rate rather
    than a 20% blind spot, so it survives self-review.
    REQUIRED: treat a skipped mutation as a harness defect, not a result.
    Re-derive the anchor FROM THE FILE (`grep -n` the real line and copy it)
    rather than hand-typing indentation; re-run; report `caught/attempted` only
    where `attempted == intended`.
    INCIDENT 2026-08-27: a 5-mutation run over a Terraform contract test reported
    4/5 CAUGHT with one SKIP whose anchor differed from the real source by **one
    space of column alignment**. The skipped mutation was the projection-drift
    assertion — the single test the change's correctness rested on. Re-derived via
    `grep -n`, it CAUGHT. Same moral as mcp-infra's
    `check_otel_carrier_alignment.py` ("a SKIP is not a PASS"; "0 misaligned of 0
    found prints as PASS"), reached from the mutation-harness side instead of the
    fleet-census side. Filed here rather than in the sibling because
    `tdd-mutation-testing.md` sits at 35,555 B — past WARN with ~2.4 KB to BLOCK
    and three prior budget-repair PRs — while this file has ~15 KB of headroom;
    the item sequence is shared across both files, so numbering is unaffected.

## Mutation-testing verdicts live in a sibling rule

Items 18-22 and 24-26 — interpreting what a mutation's PASS or FAIL actually
indicts, and the harness defects that manufacture a false verdict — moved to
`rules/tdd-mutation-testing.md` (2026-07-31) when this file reached 37,872 of its
38,000-char block. **That file is path-scoped too**: this is a split along the
corpus's two real families, not an extraction behind a pointer. Claude loads it
on the code, test, or configuration surfaces where mutation verdicts are being
interpreted.

Item numbers are preserved across both files; the sequence is shared, not
restarted.

37. **Before writing `assertNotIn(token, whole_file)`, ask whether that token has a
    LEGITIMATE use elsewhere in the file.** A whole-file token assertion is a CATEGORY check
    standing in for a property that belongs to ONE CONSTRUCT, and it fails in both
    directions: it reddens a correct tree, or it passes while the construct is broken.

    THREE instances in a single change, 2026-08-26 — the recurrence is the finding, not any
    one of them:

    | Assertion | Outcome |
    |---|---|
    | `"${{ secrets." not in workflow` | RED on a correct tree — the legitimate cross-repo deploy key |
    | `"TMPDIR" not in launcher` | RED on a correct tree — a lock dir created with plain `mkdir`, never mounted |
    | `conditional in body.split(mount)[0]` | GREEN with the guard replaced by `if true` — the same string appears 3x earlier |

    The fix is the same every time: extract the construct and assert on THAT — a regex
    capture of the argument, an exact allowlist of permitted values, or an ADJACENCY pair
    (`"if <cond>\n  <the guarded line>"`). A prefix/suffix window is a category; adjacency
    is the identity.

    **Corollary for mutation batteries: mutate the VALUE a guard produces, not only the
    guard's control flow.** A battery that flips conditionals and deletes guards cannot see a
    path/constant defect at all. The same change shipped a bind-mount path bug through a
    17-mutation battery because every launcher mutation targeted whether the guard EXISTED,
    never which directory it named. Add one mutation per load-bearing VALUE (swap the path,
    the threshold, the URL) and require CAUGHT.

38. **A canary drawn from the feature's own vocabulary stops being a canary when the feature
    grows.** A tamper test used `confluence_delete_page` as its "must not survive" marker,
    which was sound while that client was read-only; enabling writes put all three write-tool
    names into the rendered output, so the absence assertion failed on a CORRECT tree and the
    obvious "fix" was to delete a real tamper test. Pick a marker that CANNOT legitimately
    appear (`attacker_tool_must_not_survive`), and when a canary fires on a clean tree, check
    whether the SUBJECT grew into the marker's namespace before touching the assertion.

40. **An ISOLATION mechanism can disable the very behaviour under test, and a harness
    that runs an artifact OUT OF PLACE breaks its sibling-file resolution.** Two
    distinct ways a replay/probe measures something other than the subject, both
    reporting a confident 0%.

    **(a) The isolation flag is a feature switch.** A hook or module that offers a
    "test mode" may gate its real work behind it, not merely its side effects. Setting
    it for cleanliness then measures the disabled path.

    ```python
    is_test = bool(os.environ.get("CLAUDE_HOOK_TEST"))
    if not is_test:          # BOTH the advisory AND the telemetry live here
        ...
    ```

    Measured 2026-08-27: `CLAUDE_HOOK_TEST=1` was set to keep session markers out of
    live state; `toolsearch-intercept.py` gates both its advisory and its telemetry
    behind `if not is_test`, so a 133-payload replay reported **0.00%** on a hook whose
    real rate is nonzero. Prefer a scratch session id / temp path for isolation, and
    grep the subject for the flag you are about to set BEFORE setting it.

    **(b) Sibling resolution dies when you relocate the artifact.** A module resolving
    a data file from its OWN directory (`os.path.join(SCRIPT_DIR, "rules.json")`) finds
    nothing when materialized into a temp dir, and typically fails SILENTLY —
    `_load_rules()` returned `[]`, `main()` exited at `if not rules`, and the probe read
    that as "the shape never recurs". Copy the siblings next to it or run it in place.

    THE GOVERNING CHECK for both: qualify the harness on a KNOWN-POSITIVE derived from
    the subject's SOURCE before reporting any zero. Measured the same day: 5 of 6 hooks
    replayed at exactly 0.00%; four separate instrument defects, zero real findings. The
    one hook that DID emit (6/877) is what made "the harness is broken" the right
    hypothesis instead of "these hooks are dead" — a single working control is worth
    more than five agreeing zeros.

    AND DERIVE THE POSITIVE FROM SOURCE, NOT FROM WHAT YOU ASSUME THE SUBJECT DOES.
    A known-positive of `"distil"` was fed to a hook believed to do fuzzy
    misspelling-correction; its source is a hardcoded 9-entry `ALIASES` map, so silence
    was CORRECT and the "broken instrument" verdict was mine (see item 34).

41. **Item 38's INVERSE, and the silent one: when the PRODUCT deletes the string a
    negative assertion names, that assertion becomes permanently unfalsifiable.** Item 38
    is the subject growing INTO the marker's namespace — the canary fires on a clean tree,
    which is loud and gets investigated. This is the subject growing OUT of it: the needle
    exists nowhere the product can emit it, so `assertNotIn`/`hasnot` passes forever. Nothing
    turns red, so nothing prompts a look.

    Measured 2026-08-30, claude-config `test-claude-gov-profile-guard.sh`. It asserted a
    discriminating PAIR on the launcher's message: CASE A `does NOT claim 'session expired'`
    and CASE C `reports 'session expired'`. PR #2041 (2026-08-19) reworded that message to
    "session not usable" — a deliberate fix distinguishing authorization failure from expiry
    — and did not touch the test. CASE C went RED on main and stayed red **11 days**; CASE A
    went VACUOUS in the same instant and could no longer fail at all.

    **The red half MASKED the vacuous half.** With the suite already failing, the second
    defect had no separate symptom — and the vacuous assertion was the one guarding the
    guard. Mutation-testing confirmed it: removing Pre-check 1 left CASE A green until the
    needle was repointed, after which the same mutation flipped it.

    - When rewording a user-facing string, grep the test corpus for the OLD literal **in the
      same change**. Item 16's 5th instance (dead-mock-from-rename) is the same mechanism for
      identifiers; it applies to STRINGS, and a string rename has no compiler to catch it.
    - A negative assertion needs a known-positive TWIN in the same suite, and the twin's
      needle must be a literal the product actually emits. If no test asserts the needle
      PRESENT anywhere, the absence assertion is unfalsifiable by construction.
    - A red suite is not a licence to stop looking. Fix the red, then re-check whether its
      sibling assertions still discriminate — mutate the pair, not just the failing half.

### A platform-unsupported API is a free FAULT INJECTOR (2026-08-28)

11b is the malignant case (unrunnable HARNESS -> VACUOUS assertions). The dual: an
unsupported CALL throws a real terminating error on a real error path, so it
exercises traps, exit codes, and messages for free.

GUARD pattern="it is Windows-only, so parse-checking is the honest limit":
  REFUSE until the script has been executed once and the error path observed.

Narrative: `rules/incidents/tdd-quality.md`.
