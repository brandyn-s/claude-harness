---
name: legacy-code-tdd
description: "Companion to superpowers:test-driven-development for untested code and multi-layer features: characterization tests that pin current behavior before a change, a walking-skeleton first slice, and acceptance tests that run the literal documented invocation."
when_to_use: 'Use with superpowers:test-driven-development when the code you are changing has no tests or under 80 percent coverage, when a feature spans several architectural layers, or when a deliverable has a user-facing surface (CLI flags, slash command, API endpoint, library export). Also when a mutation-testing result looks wrong (a mutant reported caught, a guard clause someone wants to delete) and the harness itself must be verified, or when an inherited module with no coverage must be refactored without breaking it. Trigger phrases: "characterization test", "legacy code", "no tests here", "zero test coverage", "refactor without breaking", "first slice", "prove the whole stack", "mutation testing", "is the harness lying", "walking skeleton", "outside-in", "strangler fig". Do NOT use for greenfield code with a clear spec — plain red-green-refactor covers it.'
allowed-tools: Read Grep Glob Bash Write Edit
---

# Legacy-code TDD

Companion to `superpowers:test-driven-development`, which owns the red-green-
refactor cycle and the Iron Law. This skill covers three situations that cycle
does not address on its own. Extracted on 2026-09-03 from this repository's
fork of superpowers v4.3.1.

## 1. Characterization tests for untested code

Standard TDD writes a failing test first. Legacy code needs passing tests
first: capture current behavior as a safety net, then change it.

```
1. RED ZONE  — write tests that capture CURRENT behavior (they should pass immediately)
2. GREEN     — verify they pass (confirms you captured reality, not intent)
3. REFACTOR  — now modify with a safety net
```

Standard TDD knows what the behavior should be. Legacy TDD does not know every
behavior, so it captures what exists.

Classify each public method to pick the test strategy:

| Category | Example | Test strategy |
|----------|---------|---------------|
| Pure computation | `calculate(a, b) -> c` | input/output pairs |
| State mutation | `add_item(x)` modifies a list | before/after state checks |
| Async operation | `fetch_data() -> [Item]` | mock external deps, verify results |
| Side effect | `save()` writes to disk | verify the mock was called correctly |
| Event emission | `on_change` callback fires | capture callback invocations |
| Error path | throws on invalid input | verify the error type |

(Table source: rshankras/claude-code-apple-skills
`characterization-test-generator`, Context7 registry 2026-04-16.)

Process: read the code and list inputs, outputs, edge cases, and side effects;
write characterization tests that document what the code does, not what it
should do; verify they pass, and if one fails, fix the test because you
misunderstood the behavior; make the change; run the tests and either preserve
behavior or document the intentional change.

For systems too large to test at once, use the strangler fig: wrap the legacy
code in a new interface, test the boundary, move logic across gradually, and
repeat. The system works at every step and you can stop at any point.

Use this instead of standard TDD when the code you touch has no tests or
coverage under 80 percent, when you inherited it from another session, or when
you are changing infrastructure code such as Terraform, config, or hooks.
(Pattern source: thebushidocollective/han `legacy-code-safety`, Context7
registry 2026-04-16.)

## 2. Walking skeleton first

The first vertical slice of a multi-layer feature is a walking skeleton: the
thinnest end-to-end path that proves every architectural layer connects. It
may use hardcoded values or stubs. Build it before any other slice; it
de-risks the architecture and gives later slices a proven wiring path to
extend. Never slice horizontally, writing all tests and then all code: tests
written in bulk test imagined behavior. (Pattern source: jwilger/eventcore,
Context7 registry 2026-04-06.)

## 3. Acceptance tests run the literal documented invocation

When the deliverable has a user-facing surface, the final acceptance test runs
the invocation exactly as documented: the real CLI arguments, the real slash
command, the real endpoint path or library export. Not an equivalent internal
call, a dev flag, or an invented test argument. If the documented invocation
cannot be exercised in the test environment, say so in the test name and
mark the claim as not live-verified.

## 4. Reading a mutation-testing verdict

Before believing a mutation score, or deleting a guard because a mutant
reported CAUGHT, this is a REQUIRED READ:
`docs/rule-reference/tdd-mutation-verdict-interpretation.md`. It catalogues
the verdict traps measured in this repository, such as a harness that passes
test names to `python -m unittest` and reports every mutant caught.

Return to `superpowers:test-driven-development` for the cycle itself and its
verification checklist.

## Examples

**Example 1: inherited module with no coverage**
User says: "Refactor `invoice_totals.py` — it has no tests."
Actions:
1. Write characterization tests first (step 1): feed the current inputs,
   record whatever the function returns today, including the rounding quirk
   that looks wrong.
2. Pin that behavior as the baseline — the tests assert current behavior, not
   intended behavior.
3. Refactor; any characterization test that flips is an unintended change.
Result: the rounding quirk was load-bearing for one caller. It surfaced as a
red test instead of a billing incident.

**Example 2: a feature spanning four layers**
User says: "Add a `--since` flag that filters the report by date."
Actions:
1. Walking skeleton first (step 2): the thinnest slice that runs CLI → parser
   → query → renderer end to end with one hardcoded date.
2. Prove the seam, then widen each layer behind passing tests.
3. Final acceptance test runs the literal documented invocation (step 3):
   `report --since 2026-01-01`, not an internal `build_report(since=...)` call.
Result: the CLI argument name was wrong in the docs. Only the literal-invocation
test could have caught it.

**Example 3: a mutation score that looks too good**
User says: "Mutation testing says 100% caught, so the guard clause is
redundant — delete it."
Actions:
1. Before believing the verdict, read
   `docs/rule-reference/tdd-mutation-verdict-interpretation.md` (step 4).
2. Find that the harness passes test names to `python -m unittest`, which
   reports every mutant caught regardless of the mutation.
3. Fix the harness, re-run, and re-read the score.
Result: the real score was 61%, and the guard clause was the only thing
covering a live branch. The harness was the bug.

## Success Criteria

- Characterization tests exist and pass against unmodified code before any
  refactor begins, asserting current behavior rather than intended behavior.
- For a multi-layer feature, a walking skeleton runs end to end through every
  layer before any layer is widened.
- Where the deliverable has a user-facing surface, an acceptance test invokes
  it exactly as documented — real flags, real command, real endpoint or export.
- A documented invocation that cannot be exercised is named in the test name
  and reported as not live-verified rather than substituted.
- No mutation-testing verdict is acted on, and no guard is deleted, before the
  verdict-interpretation reference has been read and the harness qualified.
- Control returns to `superpowers:test-driven-development` for the red-green-
  refactor cycle itself.
