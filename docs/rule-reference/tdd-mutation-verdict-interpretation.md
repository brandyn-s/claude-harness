# Mutation-verdict interpretation — the numbered case corpus

Moved out of `rules/tdd-mutation-testing.md` on 2026-08-31. That
rule was the single largest ambient cost in the corpus at **13,540
tokens measured with Anthropic's own tokenizer**, and its `paths:`
frontmatter listed 28 globs including `**/*.json`, so it loaded on
essentially every edit — for a procedure that only applies while
you are actually running a mutation.

The rule keeps the contract (invariants, the verdict table, the
guards) and is now scoped to test files. This file keeps the case
corpus, which is the part you read WHILE interpreting a specific
verdict. Item numbers are preserved, so a cross-reference written
as "item 20 §4" still resolves.

---
18. **A mutation that PASSES is a verdict on your FIXTURE, not on your code.**
    Mutation testing (revert the guard, re-run the test, assert it fails) is the
    only way to prove a test actually exercises the branch it claims to. When a
    mutation PASSES, the reflex is "the guard is redundant, delete it" — that is
    backwards. The far more common cause is that the fixture never reaches the
    mutated line: it matches an EARLIER branch, fails the entry regex, or is
    suppressed by a different code path that produces the same visible outcome.
    Two same-shape fixtures can cover two DIFFERENT paths, so "I have a test for
    that case" is not evidence.

    Procedure when a mutation passes:
    1. Assert the fixture REACHES the mutated code — `assertIsNotNone(PAT.search(line))`
       on the entry predicate, or a print/log at the branch — BEFORE concluding
       anything about the guard.
    2. If it does not reach: the fixture is wrong. Replace it with the input that
       ACTUALLY broke in production, verbatim. Do not synthesize a "similar" one.
    3. Only if it provably reaches AND still passes is the guard genuinely dead.

    Encode the reachability assertion in the test permanently, alongside the
    behavior assertion, with a docstring naming which mutation it kills. A test
    whose only assertion is the outcome cannot tell a future reader whether it
    covers the path.

    Full: incidents#2026-07-26-claude-config-cc-monitor-fact-ch

19. **A source-text checker matches its OWN file, so a whole-file scan fires on
    the forbidden string quoted in its docstring, its assertion message, or a
    warning comment.** The check then FAILS on a clean tree — which reads as a
    real finding until you look at what matched. (Item 18's inverse: there a
    mutation passes and the fixture is at fault; here the tree is fine and the
    PROBE is self-referential.)

    **Five instances in one session** (2026-07-26 claude-config audit
    remediation), each on a *different* checker, all self-inflicted:

    | Probe | Matched (wrongly) |
    |---|---|
    | C10 scan for a bare shell subprocess | the literal `subprocess.run(["bash"…])` in the test that exercises C10 |
    | a docstring describing the removed pattern | the description itself |
    | whole-file regex for `"All portable skills (N)"` | the retired string quoted in the test's own docstring |
    | whole-file check for `push --mirror` | the workflow COMMENT warning against `--mirror` |
    | an `"inside /ship"` gate-attribution scan | the prose sentence FORBIDDING that attribution |

    It also fires OUTSIDE your own tests: `grep -E "def (evaluate_journal)"`
    reported a duplicate definition in shipped code that did not exist —
    `evaluate_journal` and `evaluate_journal_path` share a prefix. Anchor the
    pattern (`\(` or `$`) before believing a structural claim about source.

    **Fixes, in preference order:**
    - **Scope the scan to the construct, not the file** — executed command lines
      only (skip `#`-comments), argument lines only, or a parsed AST rather than
      raw text.
    - **Exempt a documented RETRACTION explicitly, per-sentence.** A retraction
      must quote the false claim to name it, and a repo whose practice is
      recording corrected errors needs that to stay legal. Then prove the
      exemption is not a loophole: mutation-test that re-asserting the claim
      WITHOUT a retraction marker still fails.
    - **Assemble the probe from fragments** (`shell = "ba" + "sh"`) when the
      checker must contain a violating literal — the same defanging technique
      `security-review-before-pr.md` uses for secret-shaped fixtures.

    **The tell:** a checker fails on a tree you believe is clean, and the
    reported hit sits inside the checker or inside prose *about* the rule.
    Before "fixing" the tree, grep the hit's own line for `#`, `"""`, or an
    assertion message.

20. **A mutation that FAILS proves the test bites; it does NOT prove the test
    bites for the REASON you think.** Item 18 covers a mutation that passes
    (fixture unreachable). This is the third failure mode: the assertion is
    *malformed* or the *stub models the wrong contract*, so it either matches
    nothing or passes via an unintended path. Both look like coverage.

    Three instances in one session (2026-07-26/27, mcp-infra + mcp-servers
    Codex-finding remediation), each caught ONLY by mutation testing:

    | Shape | What happened |
    |---|---|
    | **Malformed assertion** | `assertNotRegex(block, r'\$\.event\s*=\s*\\"TOKEN\\"')` against HCL containing backslash-escaped quotes. Over-escaped → matched NOTHING → passed with the fix reverted. Rewrote as a plain `assertNotIn`. |
    | **Stub raises where production returns** | A guard test stubbed `_dispatch_render` to RAISE. Removing the guard still yielded 0 dispatches (via the exception path), so the test could not detect the guard's absence. Fixed by making the stub RECORD-AND-RETURN, faithfully modelling the real silent-return. |
    | **Assertion on the algorithm, not the identity** | `assert SSE == "aws:kms"` passed the entire time objects were landing on the WRONG KMS key — the algorithm string is identical either way. Only `SSEKMSKeyId` distinguishes them. There WAS a test; it asserted the half that could not fail. |

    **Procedure — when a mutation FAILS, confirm it failed for the right reason:**
    1. Read the failure MESSAGE, not just the exit code. If the mutation was
       "revert guard X" but the failing assertion is about something else, the
       test bit for an unrelated reason.
    2. For a regex assertion against generated/escaped text (HCL, JSON-in-string,
       YAML), first prove the pattern MATCHES the un-mutated text. A pattern that
       matches nothing satisfies every `assertNotRegex`. Prefer plain substring
       (`assertIn`/`assertNotIn`) over regex whenever the target is a literal.
    3. For a stubbed collaborator, ask: does the stub's behaviour on the
       FAILURE path match production's? A stub that raises where production
       returns silently inverts the very distinction under test.
    4. Assert the IDENTITY, not the CATEGORY: the key id, not the algorithm; the
       resolved digest, not "an image exists"; the token, not "a beacon fired".

    **The tell:** the mutation fails, but reverting a DIFFERENT line fails the
    same test — or the assertion's target string never appears in the artifact
    at all. Grep the un-mutated artifact for the literal you are asserting on
    before trusting a `assertNot*`.

21. **A test that CONFIGURES the condition it tests must prove the setting took
    effect — the code under test may overwrite it.** Items 18/20 cover a
    mutation that passes (fixture unreachable) and one that fails for the wrong
    reason. This is the fourth mode: the fixture reaches the line fine, but the
    KNOB the test set to create the failing condition is reset by the production
    code before it is read, so the condition never exists and the test passes
    with the fix disabled.

    **The tell:** a mutation PASSES, and the reachability check from item 18
    also passes — the code IS reached; it just isn't in the state you thought
    you put it in. Item 18's procedure ("assert the fixture reaches the mutated
    line") returns a clean bill of health here, which is exactly why this needs
    its own entry.

    **Procedure:**
    1. For any field the test sets to create the condition, grep for OTHER
       writers of that field (`grep -n 'e\.field =' `). A per-request/per-call
       assignment in the entry point beats a struct-literal initialiser set once.
    2. Prefer the knob the production path DERIVES from over the derived value.
       If `Execute()` computes `cap = maxRows()*2`, set `MaxRows`, not `cap`.
    3. Assert the condition EXISTS before asserting the behaviour: if the test
       needs truncation, assert the result is truncated (or that N > cap) in the
       same test. A condition-creating test with no condition assertion cannot
       distinguish "fix works" from "condition never happened".

    Full: incidents#2026-07-27-code-graph-pr-416-cypher-edge-pr

22. **"I stashed my change and it still reproduced" proves your change is
    innocent — it does NOT prove the bug is real.** Before reporting a
    pre-existing defect found while working on something else, verify the FIXTURE
    actually contains what the failing query/probe asked for. A fault in the
    PROBE reproduces identically with and without your change, so the stash-test
    returns a confident false confirmation.

    **Procedure before filing/reporting a "separate pre-existing bug":**
    1. Run each branch/clause of the failing probe ALONE and state its expected
       count. A branch returning 0 when you expected N is a probe bug, not a
       code bug.
    2. Confirm the field you queried is the field the fixture VARIES. Hand-built
       fixtures commonly hold one field constant and vary another (a uniform
       `name` with a unique `qualified_name`); querying the constant field
       returns the wrong cardinality by construction.
    3. Derive the expected result from the parts, don't assert a remembered
       number: `want = len(branch_a) + len(branch_b)`.
    4. Only then is "stashed and still reproduces" meaningful.

    Full: incidents#2026-07-27-code-graph-416-retracted-in-418

24. **Never revert a mutation with `git checkout -- <file>` when the file also
    holds uncommitted work.** Mutation testing (items 18/20/21/22) means
    deliberately breaking a file and restoring it. `git checkout --` restores
    from the INDEX, so it discards the mutation *and* every uncommitted edit in
    that file — including the change you were testing. Back up with `cp` to a
    temp path first and restore from that copy; the backup is one command and
    the loss is silent.

    Also, when a mutation's verdict comes from a wrapper script you wrote, the
    wrapper is an untested instrument: prove it reports correctly on a KNOWN
    input before trusting a verdict from it (`verify-effectiveness.md`, prove
    the instrument).

    **21b — three harness defects that each manufacture a FALSE verdict.**
    Items 18/20/21 grade the fixture and the assertion; these grade the
    mutation *harness*. All three were hit repeatedly in one session
    (2026-07-28, mcp-infra #718/#720/#721/#722), and each produced a verdict
    that pointed at the wrong thing:

    1. **A mutation that never applied reports MISSED.** If the `replace()`
       anchor does not match the real source, the harness rewrites nothing and
       the still-passing suite reads as "the guard is dead." REQUIRED: assert
       the anchor's occurrence count before writing —
       `assert src.count(OLD) == 1` — so a non-match (or an ambiguous
       multi-match) fails LOUD instead of yielding a silent no-op. Three false
       MISSED verdicts in that session traced to this; one anchor was
       ambiguous across 3 sites and the assert correctly refused.
    2. **A mutation can make the code NON-TERMINATING, so the suite HANGS
       instead of failing.** Removing a page cap turned a paginator into an
       infinite loop and the run sat at 300s. REQUIRED: bound every mutation
       run with a per-mutation timeout and treat a TIMEOUT as **CAUGHT** — a
       hang is the test detecting the defect, not an inconclusive result. (The
       hang was itself a real production finding: the un-capped loop shipped.)
    3. **A harness killed mid-run leaves the tree MUTATED.** Restore is the
       last step, so a timeout/kill skips it — and the next "clean" run then
       measures a mutated tree (here: a 120s timeout on the *unmutated* suite,
       which was actually still carrying the previous mutation). REQUIRED:
       after any aborted mutation run, restore from the `cp` backup and prove
       the baseline is green BEFORE trusting another verdict; `git diff --stat`
       against the pre-run state is the check.
    4. **A BYTE-PERFECT restore still runs the MUTATED code, because
       `__pycache__` is keyed on (mtime, size) — not content.** A restore that
       rewrites the same size within the same mtime granularity leaves the
       stale `.pyc` looking valid, so Python loads the MUTATED bytecode and the
       "restored" baseline FAILS. The verdict is maximally misleading: the diff
       is clean, `cmp` says identical, and the suite still fails — which reads
       as a real regression you just introduced, and sends you hunting a bug
       that does not exist. REQUIRED: delete `__pycache__` (or the specific
       `.pyc`) as part of every restore, not just the source rewrite —
       `find <dir> -name __pycache__ -prune -exec rm -rf {} +`. A same-size
       mutation (flipping `>` to `<`, `True` to `False`, one digit) is the
       common case, so this fires on the mutations most likely to be used.
       (2026-07-28: several turns spent chasing a phantom post-restore FAIL
       whose only cause was cached bytecode. Note `rm -rf __pycache__` has its
       own hazard — some repos TRACK their `.pyc`; see
       `agent-memory/topics/github.md`. Prefer deleting the one stale `.pyc`.)

    Shell hazard while you are at it: an unquoted backtick in a mutation string
    gets interpolated by the shell before Python sees it — quote heredocs
    (`<<'PY'`) for any mutation payload containing backticks or `$`.

    Full: incidents#2026-07-27-reverting-a-shadow-mode-mutation

25. **A mutation that passes may be an INVALID MUTATION — validate the mutation
    itself before it indicts anything.** Item 18 attributes a passing mutation to
    an unreachable FIXTURE; item 20 to a malformed ASSERTION. This is the fourth
    cause and the only one where nothing about the test or fixture is wrong: the
    edit you made **did not change behaviour**, so of course the test still
    passes. It is the mutation-testing equivalent of a no-op patch, and it reads
    identically to a weak test — you will "discover" a coverage gap that does not
    exist, and may delete a live guard to fix it.
    Two shapes seen: a semantically-inert edit (`per_hook = [] if False else [...]`
    evaluates to `[...]` — the error still raises), and a SYNTACTICALLY BROKEN
    edit (a bare `try:` with no `except`), which fails for the wrong reason and
    reads as a caught mutation.
    REQUIRED before trusting any mutation verdict: prove the mutated artifact is
    (a) syntactically valid — `ast.parse()` / `py_compile` / `terraform validate`
    the mutated text, and (b) semantically different — the mutated line must
    actually alter control flow or output, not just look different. If you cannot
    state what behaviour the mutation changes, you do not have a mutation.

    **Corollary — assert the COUNT, not the presence, when the token repeats.**
    `assertIn("GREATEST", SQL)` passed while the guard was stripped from the
    SELECT clause, because the same expression also appears in `HAVING`. A
    substring assertion is satisfied by ANY occurrence, so a one-sided regression
    ships green. Use `assertEqual(text.count(TOKEN), N)` when the requirement is
    "every clause is guarded". (Item 20 §4's "identity not category" in its
    repeated-token form; the sibling mutator bug is in
    `topics/engineering-assessment-verification-discipline.md` — a mutator that
    replaced only the FIRST occurrence condemned two valid assertions.)

    Full: incidents#2026-07-29-mcp-infra-per-hook-lane-8-mutati

26. **Pinning BOTH SIDES of an invariant as literals is a change-DETECTOR, not an
    invariant-CHECKER — a lockstep update walks straight through it.** Items 18/20/21/25
    grade a mutation's verdict; this grades a test that never expressed a relationship at
    all, and it survives review because every assertion looks specific.

    The shape: an invariant relates two values (`cap <= tmp`, `timeout < lock_ttl`,
    `batch * workers <= quota`). The test asserts each equals a literal, plus a HARDCODED
    bound that happens to equal the current other side. Any single-value drift fails it, so
    it feels rigorous. But a maintainer legitimately raising one side updates the literals
    IN LOCKSTEP, and nothing then compares the two: green on an unsafe configuration.

    Also check the SCOPE of any whole-file substring used as one side. `assertIn("size =
    2048", tf)` is satisfied by ANY resource's `size = 2048` in that file, so the value can
    be reduced on the resource under test while a sibling's identical literal keeps the
    assertion green (item 20 section 4's identity-not-category, applied to config files).

    Procedure: PARSE both numbers out of the artifact, scoped to the one resource block
    that owns them, and DERIVE the bound (`assertLessEqual(cap * 2, tmp)`). Then
    mutation-test the LOCKSTEP case, not only the single-value case — they give opposite
    verdicts, and only the lockstep one distinguishes the two kinds of test.

    Corollary: **the test you write for a fix is the cheapest refutation of that fix's
    premise — write it BEFORE shipping the fix's explanatory comment.** A mechanism claim
    in a comment ships as documentation and is harder to retract than code.

    Full: incidents#2026-07-31-mcp-infra-764-765-four-independe

27. **A mutation whose observable effect depends on LIVE EXTERNAL STATE cannot
    produce a stable verdict — pin the state, do not mutate the reader.** Items
    18/25/21 attribute a passing mutation to an unreachable FIXTURE, an inert
    MUTATION, or an overwritten KNOB. This is the fourth cause and the only one
    where the fixture reaches the line, the mutation is genuinely
    behaviour-changing, and no knob is involved: the WORLD the assertion reads
    moved between the baseline run and the mutated run, so the two runs were not
    comparing the same thing.

    **The tell:** re-running the identical mutation gives a different verdict, or
    a mutation MISSES while you can demonstrate by hand that it changes the
    returned value. Candidate sources of unpinnable state: process ancestry
    (`ps`), pids, wall-clock, network reachability, a queue's depth, "is this host
    in the allowlist right now", anything read from a service. **That list is
    hypothesised, not observed** — only the ancestry case below is measured, so
    treat the rest as where to look first rather than as known instances.

    **Measured scope, so the evidence base is not overstated: n=1.** A scan of
    `hooks/test-hooks/` for the shape (an ASSERTION whose value comes from a live
    read, not a setup mtime) found exactly three, of which two are the pinned
    tests this item produced and the third is benign (`test_git_lock` asserts the
    lockfile records `os.getpid()` — the test's OWN pid, stable for its lifetime,
    not external state that can move). So this is one measured case generalised on
    mechanism, not a corpus-wide pattern. `time.time()` in a SETUP helper writing
    an mtime is NOT this shape.

    **Procedure:**
    1. Before trusting ANY verdict on such a test, run the mutation TWICE. Two
       different verdicts means the harness is measuring the environment, not the
       code — stop and pin before continuing.
    2. Pin the dependency at its seam (`monkeypatch.setattr` the reader function,
       not the OS call underneath it) and assert the LOGIC on the pinned input.
       A pinned test also runs on platforms where the live probe cannot —
       previously the walk's logic was only testable where `ps` exists.
    3. Keep the live test, but make it CONDITIONAL on the documented degradation
       path rather than deleting it: the success path still matters. A live test
       that asserts a property the function's own docstring says is not
       guaranteed is the flake, and the docstring is the spec.
    4. Re-run the mutation against the PINNED test. If it now CAUGHT, the
       original MISS was the environment; if it still MISSES, you have a real
       item-18/20/25 defect underneath.

    # WHY: 2026-07-31 claude-config #1834 — `find_session_pid()` walks process
    #   Full: incidents#2026-07-31-claude-config-1834-find-session-pid

30. **When two defences OVERLAP, a fixture both cover cannot tell you whether
    EITHER works — and the mutation that removes one reports MISSED.** Items 18/25/21
    attribute a passing mutation to an unreachable fixture, an inert mutation, or an
    overwritten knob. This is the fourth cause and the only one where the fixture IS
    reachable, the mutation IS behaviour-changing, and no knob is involved: a second,
    independent mechanism silently supplies the same protection, so removing the first
    changes nothing the suite measures. The defence then LOOKS redundant while being
    the sole protection for a case no fixture exercises.

    Procedure: for each mechanism, write a fixture that EXACTLY ONE mechanism covers.
    Derive it by asking what the other mechanisms do NOT touch — an unquoted token
    when the sibling defence is a quote-strip; a token outside a heredoc when the
    sibling is a heredoc-strip. Then mutate each mechanism SEPARATELY and require
    CAUGHT for every one. A mechanism whose mutation is MISSED has no isolating
    fixture, whatever the overall pass count says.

    **The same defect scales up to the HARNESS, where it is worse.** A replay harness
    that (a) DUPLICATED the detector's regexes instead of importing them and (b) had
    every fixture double-covered reported `GATE PASSED (0.13%)` with the detector's
    left boundary REMOVED. It could not fail. Two fixes, both needed: import the live
    detector (a copy is two-source drift — the same class as a baseline fed by two
    sources and diffed against one), and route through its real ENTRY POINT, because
    disabling a BRANCH inside the entry point leaves the raw regexes untouched and
    invisible to a harness keyed on them. Verified by requiring all 6 mechanisms to
    fail the harness when broken.

    A harness that cannot fail is not an instrument. This is
    `verify-effectiveness`'s zero-drift-needs-a-negative-control rule applied to the
    INSTRUMENT rather than the thing measured — and the negative control is the only
    thing that surfaced it.

    Full: incidents#2026-08-02-claude-config-1874-zsh-dialect-g

28. **A new pytest file sharing an imported module with sibling tests must be run WITH those
    siblings, in >=2 orderings, before shipping.** Module-level mutable state — a monkeypatched
    attribute, or an env-derived constant re-bound via `importlib.reload()` — is shared across
    every test file importing that module in one process. A file that passes in isolation, or in
    one arbitrary order, is no evidence a sibling's leaked state does not corrupt it.

    Procedure: before shipping a new test file into a shared test directory, run it alongside its
    siblings in at least two orderings, not just isolation. After fixing one leaked
    monkeypatch/module-global, grep sibling test files for the same unrestored pattern.

    Full: incidents#2026-07-31-08-01-gold-flatten-import-time-binding

29. **"Monotone by construction" in the immediate return value does not imply monotone or safe in
    the downstream property that actually matters.** A fix can be correctly monotone for the
    ACCESSOR in isolation — it can only add non-null values, never remove correct ones — while
    being unsafe for its one real CONSUMER, if that consumer treats the field as something the
    field's own semantics do not guarantee (a counter that resets; a key that is not unique within
    its grouping).

    Procedure: when claiming a fix is "safe" or "monotone", state explicitly WHICH property is
    monotone — the raw field, or the decision/ordering it feeds — then separately verify the
    consumer's use of that field against edge cases the field's semantics do not cover.

    Full: incidents#2026-07-31-mcp-infra-927-judge-transcript-o

31. **`assertNotRegex` does NOT pass `re.MULTILINE`, so a `^`-anchored pattern anchors to the
    START OF THE STRING — it cannot see the construct on any line but the first.** The
    assertion then passes on a tree that contains exactly what it forbids. Distinct from item
    20's malformed-assertion shape: there the regex was over-escaped and matched nothing; here
    the regex is well-formed and correct, and the *flag default* is the defect. Same for
    `assertRegex`, and for a bare `re.search` without the flag.

    ```python
    # WRONG — sees line 1 only
    self.assertNotRegex(block, r'^\s*tier\s*=')
    # RIGHT — \n-anchored, needs no flag
    self.assertNotRegex(block, r'\n\s*tier\s*=')
    ```

    Prefer the `\n`-anchor over adding `re.MULTILINE`: it survives someone later switching to
    a helper that drops kwargs, and it reads as obviously line-scoped.

    Full: incidents#2026-08-02-mcp-infra-800-a-test-asserting-n

32. **A test that asserts on source it is DOCUMENTED INSIDE must strip comments before
    asserting.** Item 19 covers a source-text CHECKER matching its own file; this is the test
    variant, and it fires in both directions:

    - **False FAILURE on a clean tree** — the forbidden string appears in the very comment
      explaining why the code does not do that thing.
    - **Masked mutation** — a whole-block substring scan matches the prose and passes for the
      wrong reason.

    ```python
    code = "\n".join(l for l in block.split("\n") if not l.lstrip().startswith("#"))
    ```

    Then target the SELECTION, not the legitimate read: `max(imgs` is the defect; a
    `str(det["imagePushedAt"])` that populates a column is not.

    TWO INSTANCES IN ONE SESSION, 2026-08-02, both on mcp-infra and both on tests I had just
    written: (a) `test_the_newest_image_heuristic_is_gone` failed on a CORRECT tree because the
    function's comment documents the removed `max(imagePushedAt)` heuristic by name;
    (b) `test_the_parameter_is_still_standard_tier` matched the word `tier` inside the comment
    explaining why no tier is set. **The recurrence is the point:** this file already warned
    about the mechanism at item 19, and the warning did not transfer because item 19's subject
    is a *checker* and mine were *tests*. Naming the surface is what makes it fire.

33. **To prove a cache HIT, do NOT restore the cache key with `utimes` — make the source
    UNREADABLE instead.** A cache keyed on `(mtime, size)` invites the obvious test:
    rewrite the source, restore its timestamps, assert the stale value is served. That
    test is unsound on APFS (and any ns-resolution filesystem). `fs.utimesSync` takes a
    `Date`, i.e. MILLISECOND precision, while the recorded `mtimeMs` carries sub-ms
    detail — so the restore does not round-trip, the key legitimately busts, and the
    assertion fails **for a reason that has nothing to do with the cache**. Chasing that
    failure means debugging correct code.

    Cheaper and precision-independent: `chmod 0o000` the source after the first read.
    `statSync` still succeeds (it needs only directory traversal), so the cache KEY still
    matches — a HIT returns the stored value, while a re-parse hits `EACCES` and falls
    through to the empty/default path. The two outcomes are unambiguous and no clock is
    involved. Guard it with a probe (`try { readFileSync } catch`) so the assertion is
    skipped rather than inverted under root or a permissive filesystem.

    **Mutation-test the cache separately from the behaviour**, because the two mutations
    that matter here do NOT change behaviour: "never write the cache" and "ignore one
    component of the key" both leave a CORRECT system, just a slower one. Measured
    2026-08-02: both were MISSED on the first pass with the whole suite green. A
    PERFORMANCE property with no test is one that regresses with nothing to notice —
    the optimisation can be deleted entirely and CI stays green.

    Include `size` alongside `mtime` in any such key: two writes can land inside the same
    millisecond, and mtime alone then serves the stale entry. That guard is itself
    untestable by racing the clock — forge the cache entry directly (correct mtime,
    wrong size, a value that differs from the file) and assert the file wins.

34. **A test written from ASSUMPTION pins the wrong boundary — while passing.** Items 18/20/21/25
    grade a mutation's VERDICT; this grades the test you write to CLOSE a gap a mutation found.
    Code often rejects at a different **DEPTH** than the layer you meant to exercise, so an
    assumption-derived assertion passes for the wrong reason and guards nothing.
    REQUIRED: derive every expected rejection from an OBSERVED failure — run the input, read the
    exception TYPE and message — then assert at THAT depth, and re-run the original mutation to
    confirm it fails EXACTLY the new cell, not collaterally.
    THE TELL: your new test fails on first run with an error you did not predict. That is the code
    telling you where the boundary really is; do NOT "fix" the test toward your assumption.
    Full: incidents#2026-08-02-assumption-written-test-pins-the-wrong-depth

35. **A mutation harness that backs files up by BASENAME silently swaps their contents
    when two targets share a name — and the sha256 restore-check from item 24 is the
    only thing that turns that into a loud abort.** Item 24 says restore from a `cp`
    copy and verify; this is the failure mode of doing that with a colliding key.

    The colliding key is a rule + its own reference doc, which is exactly the pair a
    rule-relocation change touches; the second copy overwrites the first, so
    "restore" writes reference prose into the ambient rule.
    Full: incidents#2026-08-26-claude-config-basename-backup-collision

    ```python
    def slot(t: Path) -> Path:                       # flatten the RELATIVE path
        return BACKUP / str(t.relative_to(ROOT)).replace("/", "__")
    assert len({slot(t) for t in targets}) == len(targets), "backup slots collide"
    ```

    Key on the flattened relative path and ASSERT the slots are unique before the first
    mutation. This is also `platform-constraints`' "use unique temporary filenames"
    rule, in the one place where violating it corrupts the artifact under test rather
    than just clashing.

    INCIDENT 2026-08-26 (claude-config, relocating `rule-authoring`): batch aborted at
    P1 with `RESTORE FAILED rule-authoring.md`; the on-disk rule contained
    `# rule-authoring: Empirical Reference`. Recovered from context and byte-size
    confirmed. n=1, but the collision is structural for any rule + reference pair.

36. **A check can match the PROSE that describes the thing instead of the thing —
    and this is not confined to checkers (item 19) or tests (item 32). It fires on
    CORPUS and TRANSCRIPT detectors too, where the corpus contains the rule text.**

    Five instances in one session across four distinct surfaces (corpus scan,
    transcript probe, two source asserts, activity detector).
    Full: incidents#2026-08-28-self-reference-detectors-five-surfaces

    So the rule generalises: **whenever the corpus you grep can contain a description
    of what you are grepping for, the detector needs a control that excludes
    self-reference.** Concretely:
    - DEFANG every literal in the probe (assemble from fragments) so no searchable
      copy exists in the probe's own source;
    - strip comment lines before asserting on source (`item 32`);
    - anchor on the ENVELOPE an event emits, not on the body text a Read could also
      produce — and then verify the envelope is actually persisted (it may not be);
    - require BOTH controls: a known-negative that must return 0 AND a known-positive
      that must return >0. Two of these five were caught only because one control
      failed while the other passed.

40. **A fixture that BUILDS its expected content FROM the value under test cannot
    detect a wrong value.** Items 18/25 attribute a passing mutation to an unreachable
    fixture or an inert edit; item 30 to an overlapping defence. This is a fifth cause,
    and the only one where the fixture is *parameterised by the thing it is supposed to
    verify* — so every value passes, including a wrong one.

    ```python
    # WRONG — the fake target is generated from the marker, so ANY marker matches
    root = _fake_repo([spec], decl["target"], f"def {decl['marker']}(x): pass")
    assert audit(root).stale == [spec]          # passes for a marker that never shipped
    ```

    The tell is that the mutation you expect to be caught is one that changes the
    PARAMETER rather than the code: repoint the identifier at something else and the
    fixture repoints with it. A test built this way is a tautology wearing a fixture.

    FIX: assert the value against the REAL artifact, where its presence is the claim
    being made. Here the marker had to name a symbol that genuinely shipped, so the
    non-tautological assertion is `assertIn(decl["marker"], real_target.read_text())`
    against the actual guard — not against a file the test just wrote.

    Full: incidents#2026-08-27-claude-config-2169-tautological-fixture

41. **A mutation harness that judges by EXIT CODE reports CAUGHT when the test
    never ran.** `python -m unittest <bare_test_name>` resolves the argument as a
    MODULE name; the import fails, unittest synthesises
    `unittest.loader._FailedTest`, and the non-zero exit reads as a catch. Nothing
    about the fixture, assertion, mutation or restore is wrong — the TARGET never
    resolved, which is why items 18/20/21/24/25/30 do not cover it.

    REQUIRED: judge by WHICH test failed, never by exit status.
    - run the whole module and assert the EXPECTED TEST NAME is in the parsed
      failure set;
    - require `ran >= baseline_ran`; fewer means the suite did not fully execute,
      so the verdict is INVALID, not CAUGHT;
    - treat `_FailedTest` / `INTERNALERROR` / a collection error as a harness
      defect and repair it before reading any verdict.

    THE TELL, and it costs one run: print the actual failure MESSAGE for a single
    mutation before trusting a batch. A real catch names your assertion; a false
    one reads `ERROR: <name> (unittest.loader._FailedTest.<name>)`. Unanimity
    across a batch is itself weak evidence — a real batch usually surfaces at
    least one MISSED or SKIP.

    Full: incidents#2026-08-29-mcp-servers-1359-bare-test-name-false-caught
