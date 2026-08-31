---
paths:
  - "**/rules/tdd-quality.md"
  - "**/rules/tdd-mutation-testing.md"
  - "**/rules/incidents/tdd-quality.md"
---

# Incident narratives and extended reference — tdd-quality

Serves BOTH `rules/tdd-quality.md` and `rules/tdd-mutation-testing.md` (split
2026-07-31). Extracted from the original to keep that ambient rule under the
rule-size-guard budget. Nothing here is trimmed; the rule carries a
pointer to each section below. This file is NOT ambient — it is read on
demand.

The `paths:` gate above is what MAKES that true, and it was missing when this
file was created (claude-config #1802, 2026-07-30) — every one of the 8 sibling
incident files carries it, and the extraction script that authored this one did
not check the directory's convention. Without the gate the file loads ambiently
(~8.4 KB), which is the exact double-load `claude-agent-self-monitoring`
documents and #1207 re-tiered away. A new file in `rules/incidents/` MUST carry
this frontmatter or the extraction it exists to serve saves nothing.

These sections were absorbed from external repositories as general
testing-strategy guidance. They were moved out of the ambient rule in
favour of the platform-specific, incident-derived gotchas (items 10-25),
which are the class that actually recurs here. No item in the rule
cross-references items 1-9 (verified before the move).

## Absorbed testing-strategy reference (items 1-9)

## Mock and Assertion Gate Functions (absorbed from microsoft/fluidframework — 2026-04-08)

Pre-action decision checkpoints. Execute these BEFORE the action, not after.

**Gate 1 — Mock assertion gate:**
BEFORE asserting on any mock element, ask: "Am I testing real component
behavior or just mock existence?" IF testing mock existence → STOP. Delete
the assertion or unmock the component. Test real behavior instead.

**Gate 2 — Production method gate:**
BEFORE adding any method to a production class, ask: "Is this only used by
tests?" IF yes → STOP. Put it in test utilities instead. Also ask: "Does
this class own this resource's lifecycle?" IF no → wrong class for this
method.

**Gate 3 — Mock understanding gate:**
BEFORE mocking any method: (1) What side effects does the real method have?
(2) Does this test depend on any of those side effects? (3) Do I fully
understand what this test needs? IF depends on side effects → mock at lower
level (the actual slow/external operation), not the high-level method the
test depends on. IF unsure what test depends on → run test with real
implementation FIRST, observe what needs to happen, THEN add minimal mocking.

Red flags that a gate should have fired: mock setup >50% of test, mocking
"just to be safe", assertion checks for `*-mock` test IDs, can't explain
why mock is needed.

**Gate 4 — Guessed-constant gate (verify third-party constants LIVE, not in a mock):**
BEFORE a test asserts on — OR a mock returns — a specific THIRD-PARTY constant
you did not read from the vendor's live API or docs (an error string, status
code, enum value, field name, response key), ask: "Did I VERIFY this constant,
or GUESS it?" IF guessed → STOP. A mock that returns your guess AND a test that
asserts your guess are **self-confirming**: they pass by construction because
you authored both sides of the same guess, so the test proves the guess matches
itself, not the API. The bug hides until the first LIVE call returns the real
constant. This is the mock-level twin of `verify-effectiveness.md`'s
stubbed-seam guard (a stub never executes the real boundary).

Two required practices when the constant drives control flow:
1. **Verify the constant against the live API** (one real call / read the vendor
   doc) before writing the assertion — never seed the mock with a guess.
2. **For "is-absent / already-done" idempotency detection, classify by error
   FAMILY (substring), not an exact allowlist of guessed constants.** An exact
   allowlist is one unknown string away from breaking; any `not_found` /
   `not_linked` / `not_in_` variant means "already gone = idempotent success,"
   while real errors (`missing_scope`, `ratelimited`, `restricted_action`)
   still raise. Also test idempotency under the STRICT already-gone state
   (upstream resources also deleted), not just an immediate re-run.

Red flag: an idempotent-teardown/absent-detection wrapper whose test passes but
was never exercised against a real already-done state. INCIDENT 2026-07-05
(compliance-access-framework): a Slack unlink wrapper's exact-allowlist missed
the real error string TWICE — `link_not_found` (unit test asserted the guessed
`group_not_linked`, passed green), then `group_not_found` under the fully-torn-
down state — each surfaced only by a LIVE re-run. Family-match fixed it. The
Slack-specific instance is in `agent-memory/topics/slack.md`; this gate is the
cross-API generalization so it fires when mocking ANY third-party API.

RECURRENCE 2026-07-26 (3rd instance) — carries a sharper fix for the CREATE
direction. A multi-step apply script's step 1 (`POST orgs/{org}/teams`) guarded
re-runs by matching `"already exists"` in the error body; GitHub's actual message
is **`"Name must be unique for this org"`**, so the guessed substring never
matched and the second run of an idempotent-by-design script ABORTED at step 1.
For an "is it already created?" check the robust test is not a better substring —
it is **GET the resource and branch on 200-vs-404**. Existence is directly
observable; the error prose is a vendor string you are guessing at. Keep
family-matching for the DELETE/absent direction (where a 404 IS the signal); use
existence-checks for the CREATE direction.

## Test Placement and Strategy (absorbed from dtolnay, BurntSushi, alex — 2026-04-04)

5. **Co-locate tests with the code they test.** Place `#[cfg(test)]` blocks or
   `if __name__ == "__main__"` test code immediately below the code being tested,
   not in a separate directory. When you edit the code, the test is right there — you
   can't forget it exists. Separate test directories (like `test-hooks/`) are acceptable
   for integration tests that span multiple modules, but unit tests belong next to the
   code. (BurntSushi — every flag in ripgrep has its test immediately below the impl)

6. **Roundtrip property testing for any encode/decode or transform code.** If you write
   a function that transforms data (serialize, encrypt, compress, format), the first test
   should be `assert(decode(encode(x)) == x)`. This catches asymmetric bugs where one
   direction silently drops or transforms data. More valuable than specific input/output
   pairs for transformation code. (alex — relish, fernet-rs)

7. **Test vectors from specifications for protocol/crypto code.** When implementing a
   standard (STIX, FERNET, TLS, SAML), use the specification's test vectors, not
   hand-crafted examples. External JSON/YAML files consumed via `include_str!` (Rust)
   or `json.load()` (Python). This tests conformance to the spec, not conformance to
   your assumptions about the spec. (alex — fernet-rs/src/generate.json)

8. **Boundary testing for classification code.** When code classifies inputs by
   numeric thresholds (severity levels, risk scores, confidence bins), test AT
   every boundary value — not just representative samples from each range.
   Document the expected math in test comments. Off-by-one errors in threshold
   comparisons (`>=` vs `>`) are invisible without boundary tests.
   (blakecrosley — downf411/tests/test_rules.py: every squeeze classification
   threshold tested at exact boundary, with score math in comments)

9. **Property-based testing for pattern-rich code.** When code exhibits any of
   these patterns, prefer property-based tests over example-based tests:

   **Auto-detection triggers** (when to suggest PBT):

   | Pattern | Property to test | Priority |
   |---------|-----------------|----------|
   | encode/decode, serialize/deserialize, toJSON/fromJSON | Roundtrip | HIGH |
   | Pure functions (no side effects, deterministic) | Multiple properties | HIGH |
   | Validators (`is_valid`, `validate`, `check_*`) | Valid after normalize | MEDIUM |
   | Sorting/ordering, comparators | Idempotence + ordering | MEDIUM |
   | Normalization (`normalize`, `sanitize`, `clean`) | Idempotence | MEDIUM |
   | Builder/factory patterns | Output invariants | LOW |

   **Property catalog** (weakest → strongest):

   | Property | Formula | When to use |
   |----------|---------|-------------|
   | No Exception | No crash on valid input | Baseline — weakest guarantee |
   | Type Preservation | `type(f(x)) == expected_type` | Any transformation |
   | Invariant | Property holds before AND after | Any state change |
   | Idempotence | `f(f(x)) == f(x)` | Normalization, formatting, sorting |
   | Roundtrip | `decode(encode(x)) == x` | Serialization, conversion pairs |

   Always push for the strongest property the code supports. "No exception"
   is the weakest guarantee — if a stronger property applies, use it.
   (trailofbits/skills property-based-testing — Context7 registry 2026-04-06)


## 2026-07-31 both-sides-literal: a "relationship" test that asserted none
<a id="2026-07-31-both-sides-literal"></a>

mcp-infra #764 -> #765. A content-size-cap test was described in the PR as "the test
asserts the relationship so it can't silently drift". It asserted:

    assertEqual(cap, 1 GiB)                          # a literal
    assertLessEqual(cap, 2048 * 1024 * 1024)         # HARDCODED, not read from the artifact
    assertIn("CONTENT_MAX_BYTES = tostring(1024 * 1024 * 1024)", tf)
    assertIn("size = 2048", tf)                      # whole-file substring

Four independent literals. Two mutations, opposite verdicts:

| Mutation | Verdict |
|---|---|
| ephemeral_storage 2048 -> 1024 MB | **FAILS** — caught by the `size = 2048` substring |
| cap -> 2 GiB, /tmp unchanged, literals updated in lockstep | **ALL FOUR PASS** — ships a zero-headroom cap |

So it worked as a change-DETECTOR and not as an invariant-CHECKER. The replacement parses
`ephemeral_storage.size` and `CONTENT_MAX_BYTES` out of the content function's OWN resource
block (a whole-file substring is satisfied by any sibling resource's identical literal) and
asserts the derived bound `cap * 2 <= tmp`.

**The critique was also wrong on first pass.** The initial account — "dropping /tmp to
512 MB left every assertion green" — was false; the substring catches that. Running the
mutation, rather than reasoning about it, produced the accurate characterisation. Both the
test and the critique of the test failed the same way: a confident claim about what a check
covers, unverified.

**Corollary from the same session.** A reordering "fix" was authored with a comment
attributing a 71-hour outage to the ordering. Writing the test revealed the reorder was
behaviour-neutral — with poison in the DLQ, checking the DLQ first defers on `dlq_busy`
exactly as checking the queue first defers on `queue_busy`. The code was reverted to
byte-identical and only the comment kept, inverted to record why NOT to "fix" it.

## 2026-08-04 fixture contamination: `git add -A` staged the artifact-under-test INTO the fixture repo

A test for "a governance-only commit must not mark the binary stale" built a
throwaway git repo, wrote a `fake-deployed-binary` stub INSIDE it as the
deployed artifact, committed the governance files with `git add -A`, and
asserted no warning fired. It failed. The stub is not governance metadata, so
`git add -A` made the commit genuinely contain a shipped path — the assertion
was correct and the FIXTURE was wrong.

**The dangerous half was the control, not the failure.** The paired
known-negative ("a source file named `CODEOWNERS.go` must STILL warn") used the
same `git add -A` + in-repo stub, so it would have PASSED — driven by the stub,
not by `CODEOWNERS.go`. A green control that is green for an unrelated reason
is worse than a missing one: it certifies the exact over-suppression it was
written to catch. Same class as item 20 ("a mutation that FAILS proves the test
bites, not that it bites for the reason you think"), reached from the fixture
side instead of the assertion side.

Rule: any stub representing the ARTIFACT UNDER TEST lives OUTSIDE the fixture
repo (`tmp_path`, not `tmp_path/repo`), and fixtures stage explicit paths
(`git add CODEOWNERS .github`) rather than `-A`. Then re-run the mutation: both
tests must still flip. Diagnosing this took one debug script printing the
actual `git log --name-only` output — the parsed path list named
`fake-deployed-binary` immediately, where reading the test did not.

## 2026-08-04 the docstring was right and the fixture was wrong (item 18 sub-shape)
<a id="2026-08-04-docstring-right-fixture-wrong"></a>
**Anchors:** `rules/tdd-mutation-testing.md` item 18 (a mutation that PASSES is a verdict
on your FIXTURE). Filed here rather than inline: tdd-mutation-testing.md was 37,643 B
against a 38,000 B BLOCK — 357 B headroom, under the ~500 B "does not fit" floor.

Shipping a change-volume quarantine to `netsuite-paycom-sync-daily`. Eight mutations run,
seven CAUGHT, one MISSED: "write ratio measured on the ORIGINAL proposal, not survivors."

The test existed, was well-named, and its DOCSTRING stated the correct discriminating
arithmetic — "260 updates + 46 non-cohort creates = 30.6% of 1000, over the 25% cap." The
fixture passed **200**. 200 + 46 = 246, under the 250 cap on BOTH implementations, so the
assertion never reached the mutated line. Item 18's diagnosis exactly (fixture unreachable),
but with a tell item 18 does not name.

**The tell: the prose and the code disagreed, and the prose was correct.** I had worked out
the right number while writing the docstring and then typed a different one into the fixture
— an interpolation between narrative and code, the same class as grading-discipline's
"reporting a quantity you obtained by INTERPOLATING between measured points," landing inside
a test instead of a deliverable. It is invisible to review because both halves read as
deliberate: the docstring is specific and correct, the fixture is a plausible round number.

**Check, mechanical and cheap:** when a test docstring cites specific quantities, assert the
fixture uses those exact quantities before trusting a PASS. If a mutation targeting that
test's logic comes back MISSED, diff the docstring's numbers against the fixture's FIRST —
before suspecting the code.

Fix: fixture corrected to 240 updates (240 ≤ 250 max_updates, and 240 + 46 = 286 > 250 ratio
cap, so the two implementations diverge), plus a docstring line stating WHY the margins are
tight: "240 must sit under 250 and 286 must sit over 250, or the test cannot distinguish the
two implementations." Re-run: 8/8 CAUGHT.

## 2026-08-12 — a fifth mutation-verdict cause: the GUARD's bound is unreachable at the current config

**Recorded here rather than in `rules/tdd-mutation-testing.md` because that rule is
37,952 bytes — 48 bytes below the 38,000 BLOCK, and `rule-authoring.md` says treat a
computed headroom under ~500 B as "does not fit" (the append itself carries multi-byte
characters).** Lift it into the parent when a descope lands.

Existing causes for "mutation passed": the fixture never reaches the mutated line;
the mutation is inert (`x if False else None`); the assertion inspects only a prefix
of the artifact; the mutation is invalid syntax. This is a fifth, and it grades the
CODE rather than the harness:

**The mutated expression is behaviorally identical to the original because the guard's
bound cannot be reached at the current configuration.**

```python
HTTP_RETRIES = 5
time.sleep(min(2 ** attempt, 30))   # attempt in 0..4 -> max 16
```

`min(2**attempt, 30)` and `2**attempt` compute the same value for every reachable
`attempt`, so mutating away the clamp changes nothing and no fixture can distinguish
them. The fixture DID reach the line, the mutation WAS valid, and the guard was
nevertheless dead code — a cap written against a retry count the module does not use.

**Diagnostic, in order:** (1) does the fixture reach the line? (2) is the mutation
inert? (3) **can the guard's bound bind at all under the current constants?** Compute
the operand's actual range from the configured limits before concluding the test is
weak. Step 3 is the one that was missing, and skipping it points the repair at the
harness when the defect is in the code.

**Fix shape:** raise the relevant constant IN THE TEST so the bound becomes reachable
and the mutation is detectable, AND add a permanent reachability assertion
(`assert 2 ** (HTTP_RETRIES - 1) > CLAMP`) so the guard cannot silently become dead
again when someone lowers the retry count. Without the second half, the test passes
vacuously the moment the config drifts back.

## 2026-08-27 — item 28's trigger is ANY test-file change in a shared dir, and `importorskip` is FOOLED by a sibling's fake module

**Recorded here because `rules/tdd-mutation-testing.md` is 37,952 bytes — 48 from
the 38,000 BLOCK, so no ambient addition lands. Item 28 names "a NEW pytest
file"; both of this incident's teeth sit outside that literal trigger.**

Appending tests to an EXISTING file (`confluence/test_confluence_tools.py`,
mcp-servers #1349) and running only that file (17/17 green) proved nothing about
CI, which runs `pytest confluence/` — the whole directory. There, a PRE-EXISTING
test failed with `'_FastMCP' object has no attribute 'instructions'`: five
sibling files stub fastmcp via

```python
sys.modules.setdefault("fastmcp", types.ModuleType("fastmcp"))
```

which also fires when fastmcp is INSTALLED but not yet imported — an
installed-but-unimported package is absent from `sys.modules`. Two teeth beyond
item 28's wording:

1. **You can be the VICTIM, not the polluter.** The leg had been red since #1336
   (a day earlier); every confluence PR inherited it, and each merged anyway
   because only gitleaks was ruleset-required. Single-file green + red-merges =
   nobody's change looks responsible.
2. **`pytest.importorskip("fastmcp")` is satisfied by the FAKE** — the module IS
   in `sys.modules` — so the guard that exists to keep the suite honest about
   missing deps instead certifies a stub with no real attributes.

Fixes (mcp-servers #1351): stub preambles now engage only under
`try: import fastmcp / except ImportError:` — never bare
`sys.modules.setdefault`, which shadows the installed package. Pre-ship gate
widened in practice: for ANY change to a test file in a shared directory,
reproduce the CI leg locally — its exact install set (lock + pytest) + the
whole-directory run — before pushing. Reproduction recipe that worked:
`python3.12 -m venv; pip install -r <svc>/requirements.lock pytest…; pytest <dir>/ -q`
(1 failed/108 passed = exact CI verdict, then 109/109 after the fix).


## 2026-08-28 (session d42ae003) — relocated from the ambient rule

### A platform-unsupported API is a free FAULT INJECTOR (2026-08-28)

Entry 11b above covers the malignant case: a platform-unrunnable harness makes
assertions VACUOUS. The constructive dual is worth naming, because "this cannot
be tested here" is asserted far more often than it is checked.

Measured 2026-08-28: two Windows-only PowerShell scripts were declared
untestable on macOS because they call
`[Security.Principal.WindowsIdentity]::GetCurrent()`. Running them showed that
call throws `PlatformNotSupportedException` — which is a REAL terminating error
arriving at a REAL error path. That made it a no-cost fault injector: it proved
a newly added top-level `trap` fired, emitted an actionable message naming the
exception type and line, and returned the two distinct exit codes the two
scripts were supposed to return. A mutation check against the pre-`trap` version
on the identical fault produced a bare ANSI framework error instead, which is
the comparison that establishes the fix did something.

The same session also found `$env:USERPROFILE` is empty on macOS, so
`Join-Path $env:USERPROFILE ...` reproduced the exact production bind error
(`argument is null`) that had broken 8 devices under Windows SYSTEM context.

So before recording "untestable on this platform":

- EXECUTE it once. An exception is an observation; a refusal to run is not.
- Ask which platform DIFFERENCE can stand in for the failure you want to induce
  (unsupported API, empty environment variable, absent path, missing binary).
- Scope the claim to what remains genuinely unexercised — here, the SYSTEM
  branch and the happy path — rather than to the whole script.

GUARD pattern="it is Windows-only, so parse-checking is the honest limit":
  REFUSE until the script has been executed once and the error path observed.

## 2026-08-25 — a sibling test EVICTS the module from sys.modules, so `importlib.reload` passes or fails purely by test ORDER

**Recorded here rather than in the parent rule because `rules/tdd-mutation-testing.md`
is 37,952 bytes — 48 from the 38,000 BLOCK, so no addition of any size lands.** Item 28
already covers the shared-`sys.modules` CLASS and its procedure (run a new file with its
siblings in ≥2 orderings); this is the sub-mechanism and the FIX, which item 28 does not
name.

A new `test_guardrail_config_degrade.py` needed to prove that a malformed
`GUARDRAIL_CONFIG` no longer crash-loops at MODULE IMPORT — the actual production
failure — so it did `importlib.reload(claude_proxy)`. Measured across four orderings:

```
pytest (alphabetical)                                  213 passed
test_guardrail... FIRST                                 96 passed
test_token_page, test_signed_bearer, test_guardrail...   1 FAILED
```

The failure was `ImportError: module claude_proxy not in sys.modules`. Sibling files in
that directory reload `claude_proxy` under their own environments and **evict it from
`sys.modules`**, so the module-level reference this file captured at import time is no
longer the registered module, and `importlib.reload` refuses it. Nothing about the
file's own logic is order-dependent; only its reload is.

**Fix — a spec-based fresh import under a throwaway name, not `reload`:**

```python
spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("claude_proxy.py"))
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
try:
    spec.loader.exec_module(module)   # runs module-level code = the crash surface
finally:
    sys.modules.pop(name, None)       # leave no state for siblings to inherit
```

This executes module-level code (which is where the crash-loop lived) without touching
the shared `sys.modules` entry, so it is order-independent in both directions — it
cannot be broken by a sibling and cannot break one.

**Generalization:** when a test must exercise IMPORT-time behavior of a module other
tests also reload, do not reload the shared entry — import a private copy. `reload`
asserts a relationship with the registry that a sibling can invalidate; a fresh
`spec_from_file_location` asserts nothing about it. Item 28's ≥2-orderings procedure is
what surfaced this; it is worth keeping because a single ordering was green.
