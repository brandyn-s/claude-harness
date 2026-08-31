---
name: test-driven-development
description: "Red-green-refactor TDD — write the failing test first, then minimal code to pass."
when_to_use: 'Use when implementing any feature or bugfix — write the failing test first, watch it fail, then write minimal code to pass. Enforces red-green-refactor discipline with strict rules against skipping steps. Trigger phrases: "TDD", "test first", "write tests", "implement with tests". Do NOT use for exploratory prototyping, one-off scripts, or when tests already exist and pass.'
argument-hint: "[feature or test-file]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.1"
allowed-tools: Bash Read Write Edit AskUserQuestion
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## When to Use

**Always:**
- New features
- Bug fixes
- Refactoring
- Behavior changes

**Exceptions (ask the user):**
- Throwaway prototypes
- Generated code
- Configuration files

Thinking "skip TDD just this once"? Stop. That's rationalization.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

**No exceptions:**
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete

Implement fresh from tests. Period.

## Anti-Pattern: Horizontal Slicing

**DO NOT write all tests first, then all implementation.**

This is "horizontal slicing" — treating RED as "write all tests" and GREEN as
"write all code." It produces bad tests because tests written in bulk test
*imagined* behavior, not *actual* behavior. You outrun your headlights,
committing to test structure before understanding the implementation.

```
WRONG (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

RIGHT (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
```

Each vertical slice responds to what you learned from the previous cycle.
(Pattern source: mattpocock/skills — Context7 registry evaluation 2026-04-05)

## Walking Skeleton First

The first vertical slice must be a **walking skeleton**: the thinnest
end-to-end path proving all architectural layers connect. It may use
hardcoded values or stubs. Build it before any other slice. It de-risks the
architecture and gives subsequent slices a proven wiring path to extend.
(Pattern source: jwilger/eventcore TDD — Context7 registry 2026-04-06)

## Outside-In TDD

Start from an acceptance test at the application boundary — the point where
external input enters the system. Drill inward through unit tests. The outer
acceptance test stays RED while inner unit tests go through their own
red-green-refactor cycles. The slice is complete only when the outer
acceptance test passes.

A test that calls internal functions directly is a unit test, not an
acceptance test — even if it asserts on user-visible behavior.
(Pattern source: jwilger/eventcore TDD — Context7 registry 2026-04-06)

### Identifying the boundary

The "application boundary" depends on what the deliverable is. Common cases:

| Deliverable | Boundary (acceptance-test target) |
|---|---|
| Web/HTTP endpoint | Documented HTTP request (path, headers, body) |
| Library function | Documented public API call from a consumer's perspective |
| CLI tool | Literal invocation string from `--help` / README |
| Slash command / skill | Literal command string from SKILL.md |
| Hook | Harness's documented invocation contract (env, stdin payload) |

**Test the surface as documented, not the helper underneath.** If a SKILL.md
says `cmd --pause t30`, the acceptance test runs `cmd --pause t30` — not
`cmd --pause /full/abs/path/state.json` because that's "equivalent." The
docs are the contract; divergence between docs and code is itself the bug
class this discipline catches.

### Parallel-surfaces drift

When a single task produces both a docs surface (SKILL.md, README, `--help`
text) AND a code surface (parser, script, function) written from a shared
spec, treat them as having drifted by default. Two surfaces written without
one acting as the test of the other will diverge at the first real
invocation — different defaults, different arg conventions, different
implicit assumptions. The boundary acceptance test closes the gap: copy-paste
from the docs, run as-is, watch it fail, fix, watch it pass. Then the docs
and the code are pinned to each other.

## The Five-Step Cycle

```
RED → DOMAIN → GREEN → DOMAIN → COMMIT → (REFACTOR)
```

1. **RED** — Write one failing test. Test files only.
2. **DOMAIN** — Review test for primitive obsession. Add type stubs.
3. **GREEN** — Minimal code to pass. Implementation files only.
4. **DOMAIN** — Review impl for domain violations. Types still clean?
5. **COMMIT** — Run full suite. Commit. Discipline gate (self-enforced) — no new RED until this commit exists. No pre-commit/Stop hook enforces the red-green sequence; the model self-polices it.
6. **REFACTOR** — (Optional) Clean up structure. Separate commit.

Full phase-by-phase detail (test examples, verification commands, domain
review checklists, assertion quality gate, commit gate, refactor rules)
lives in `references/five-step-cycle.md`. Read that before working through
your first cycle in a session.

(Cycle source: jwilger/eventcore TDD — Context7 registry 2026-04-06.
Adapted for Example: simplified DOMAIN to review-only, no agent teams.)

## Good Tests

**RED reachability gate:** the intended behavior must be reachable through production preconditions.
If an earlier validator rejects the fixture, or a mock supplies the verdict being
tested, the RED is not evidence for that behavior; repair the oracle before implementation.

| Quality | Good | Bad |
|---------|------|-----|
| **Minimal** | One thing. "and" in name? Split it. | `test('validates email and domain and whitespace')` |
| **Clear** | Name describes behavior | `test('test1')` |
| **Shows intent** | Demonstrates desired API | Obscures what code should do |

## Rationalizations, Why Order Matters, and Red Flags

Tempted to skip test-first, or the user is pushing back? Read
`references/rationalizations.md` for:

- Why test order matters (tests-after vs tests-first produce different
  tests — one proves behavior, the other documents it)
- The full table of common excuses with rebuttals (too simple, already
  manual-tested, sunk cost, pragmatic vs dogmatic)
- Red flag phrases that mean STOP and start over

Short version: if you find yourself thinking "just this once," "I'll test
after," or "keep it as reference" — delete the code and start over with
TDD.

## Example: Bug Fix

**Bug:** Empty email accepted

**RED**
```typescript
test('rejects empty email', async () => {
  const result = await submitForm({ email: '' });
  expect(result.error).toBe('Email required');
});
```

**Verify RED**
```bash
$ npm test
FAIL: expected 'Email required', got undefined
```

**GREEN**
```typescript
function submitForm(data: FormData) {
  if (!data.email?.trim()) {
    return { error: 'Email required' };
  }
  // ...
}
```

**Verify GREEN**
```bash
$ npm test
PASS
```

**REFACTOR**
Extract validation for multiple fields if needed.

## Verification Checklist

Before marking work complete:

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for expected reason (feature missing, not typo)
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass
- [ ] Output pristine (no errors, warnings)
- [ ] Tests use real code (mocks only if unavoidable)
- [ ] Edge cases and errors covered
- [ ] Each red-green-refactor cycle committed before starting the next
      (Pattern source: jwilger/eventcore TDD commit gate — Context7 registry 2026-04-06)
- [ ] If the deliverable has a user-facing surface (CLI args, slash command,
      API endpoint, library export), the final acceptance test runs the
      literal invocation as documented — not an "equivalent" full path, dev
      flag, or invented test arg

Can't check all boxes? You skipped TDD. Start over.

## When Stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write wished-for API. Write assertion first. Ask the user. |
| Test too complicated | Design too complicated. Simplify interface. |
| Must mock everything | Code too coupled. Use dependency injection. |
| Test setup huge | Extract helpers. Still complex? Simplify design. |

## Debugging Integration

Bug found? Write failing test reproducing it. Follow TDD cycle. Test proves fix and prevents regression.

Never fix bugs without a test.

## Legacy Code: Characterization Testing

For a simpler reference guide, see `references/legacy-code.md`.

When modifying existing **untested** code, use a different TDD variant. Standard TDD
writes a FAILING test first. Legacy code needs PASSING tests first — capturing current
behavior as a safety net before you change anything.

### The RGR Workflow for Legacy Code

```
1. RED ZONE  — Write tests that capture CURRENT behavior (should PASS immediately)
2. GREEN     — Verify those tests pass (confirms you captured reality correctly)
3. REFACTOR  — NOW you can safely modify with a safety net
```

**The critical difference from standard TDD:**
- Standard TDD: You know what the behavior SHOULD be → write test for ideal
- Legacy RGR: You DON'T know all behaviors → capture what EXISTS

### Behavior Classification

For each public method, classify to choose the right test strategy:

| Category | Example | Test Strategy |
|----------|---------|---------------|
| Pure computation | `calculate(a, b) -> c` | Input/output pairs |
| State mutation | `add_item(x)` modifies list | Before/after state checks |
| Async operation | `fetch_data() -> [Item]` | Mock external deps, verify results |
| Side effect | `save()` writes to disk | Verify mock was called correctly |
| Event emission | `on_change` callback fires | Capture callback invocations |
| Error path | Throws on invalid input | Verify correct error type |

(Table source: rshankras/claude-code-apple-skills `characterization-test-generator` — Context7 registry 2026-04-16)

### Process

1. **Read the code** — Identify all inputs, outputs, edge cases, side effects
2. **Write characterization tests** — Document what the code actually does, not what it should do
3. **Verify they pass** — If they don't, you misunderstood the behavior. Fix the test, not the code.
4. **Make your changes** — The characterization tests are your safety net
5. **Run tests** — Verify behavior preserved (or intentionally changed with documented reason)

### The Placeholder Algorithm

Don't predict behavior — let the test runner report it.

1. Use the function in a test harness
2. Write an assertion with a dummy value you KNOW will fail: `expect(formatPrice(1999)).toBe('PLACEHOLDER')`
3. Run the test; the failure message contains the actual value: `expected 'PLACEHOLDER' but received '$19.99'`
4. Change the test to expect the actual behavior: `expect(formatPrice(1999)).toBe('$19.99')`
5. Repeat for the next input

Step 2 is the trick. Predicting the right value first puts you back into "what should it do" territory — exactly what characterisation rejects. Failing on purpose extracts ground truth from the runner.

(Pattern source: citypaul/.dotfiles characterisation-tests — Context7 registry 2026-05-17)

### Naming Conventions

Characterisation tests must be visually distinguishable from behavior-driven tests, or future authors (and future-Claude) will "fix" them like permanent assertions.

- **Test names**: include `characterises` (not `should`):
  ```
  it('characterises premium customer discount for < 5 years', ...)
  ```
- **File suffix**: distinct from behaviour tests:
  ```
  pricing.characterisation.test.ts    # characterisation (temporary)
  pricing.test.ts                     # behaviour-driven (permanent)
  ```
- **File header comment**: state purpose and planned lifecycle:
  ```
  /**
   * CHARACTERISATION TESTS — documenting actual behavior, NOT asserting correctness.
   * These pin down current behavior so we can safely refactor. Replace with
   * behavior-driven tests as the code is understood.
   */
  ```

(Pattern source: citypaul/.dotfiles characterisation-tests — Context7 registry 2026-05-17)

### Suspicious Behavior Marker

All legacy code has bugs. When characterisation captures behavior that looks wrong, mark the test so the discovery survives later refactors:

```
it('characterises negative quantity handling -- SUSPICIOUS: returns negative discount', () => {
  // This may be a bug — negative quantities produce negative discounts.
  // Documented as-is; escalate before changing.
  expect(calculateDiscount(-5, 'premium', 3)).toBe(-0.75);
});
```

Without the marker, the next refactor "fixes" the test (matches it to the new code) and the bug discovery is lost.

(Pattern source: citypaul/.dotfiles characterisation-tests — Context7 registry 2026-05-17)

### When to Stop

You do not need 100% coverage. Stop when all three hold:

1. **Every branch your upcoming change touches** has a characterisation test exercising it
2. **One layer out** from the change point is covered (the branches that call into or are called by the code you're changing)
3. **Mutation testing** on the change area shows no surviving mutants in paths you'll modify

Coverage tells you which paths are *exercised*; mutation testing tells you which are *protected*. If you can't feel confident your tests would detect a mistake in the specific code you're about to change, add more tests.

(Pattern source: citypaul/.dotfiles characterisation-tests — Context7 registry 2026-05-17)

### Strangler Fig Pattern (for large untested systems)

For systems too large to test all at once:

1. **Wrap**: Add a new interface around the legacy code
2. **Test the boundary**: Write tests for the wrapper
3. **Replace internals**: Gradually move logic from legacy to new code
4. **Expand**: Repeat for the next function

The system stays working at every step. You can stop at any point.

### When to use this instead of standard TDD

- Code you're modifying has no existing tests
- Test coverage is below 80% for the code you're touching
- You inherited code from a previous developer/session
- Changing behavior in infrastructure code (Terraform, config, hooks)

(Pattern source: thebushidocollective/han `legacy-code-safety` — Context7 registry 2026-04-16)

## Testing Anti-Patterns

When adding mocks or test utilities, read `testing-anti-patterns.md` to avoid common pitfalls:
- Testing mock behavior instead of real behavior
- Adding test-only methods to production classes
- Mocking without understanding dependencies

## Final Rule

```
Production code → test exists and failed first
Otherwise → not TDD
```

No exceptions without the user's permission.

## Examples

**Example 1: TDD for a new utility function**
User says: "Write a function to parse vendor CSV exports, TDD style"
Actions: Writes failing test first (test_parse_cklb.py with expected structure). Runs pytest — confirms red. Writes minimal implementation to pass. Runs pytest — confirms green. Refactors for edge cases (malformed XML, missing fields), adds tests for each.
Result: parse_cklb() with 8 passing tests covering happy path, malformed input, and missing fields.

**Example 2: Bug fix with regression test**
User says: "Fix the encoding bug in export_report — use TDD"
Actions: Writes a test that reproduces the bug (non-ASCII characters causing cp1252 error). Confirms test fails on current code. Fixes the function (adds `encoding='utf-8'`). Confirms test passes. Runs full test suite to check for regressions.
Result: Bug fixed with regression test preventing recurrence.

## Phase Boundary Rules

Each phase edits only its own file types. This prevents drift.

| Phase | Can Edit | Cannot Edit |
|-------|----------|-------------|
| RED | Test files | Production code, type definitions |
| DOMAIN | Type definitions (stubs only) | Test logic, implementation bodies |
| GREEN | Implementation bodies | Test files, type signatures |
| COMMIT | Nothing — git operations only | All source files |
| REFACTOR | Any (tests must stay green) | Don't add behavior |

If blocked by a boundary, stop and re-evaluate which phase you're in.
(Pattern source: jwilger/eventcore phase-boundaries.md — Context7 registry 2026-04-06)

## Success Criteria

- No production code written without a failing test that exercises it
- Five-step cycle followed: RED → DOMAIN → GREEN → DOMAIN → COMMIT
- Domain review checks for primitive obsession after RED and domain violations after GREEN
- Committed after each cycle before starting the next RED phase
- Test assertions are specific (exact values, not just truthy/falsy)
- Assertion quality maintained after AI edits — no weakened assertions (per rules/tdd-quality.md)
- Edge cases covered: empty inputs, boundary values, error conditions
- **Walking Skeleton (mandatory at project/feature start)**: a thin end-to-end path connecting the major architectural layers ships before any vertical depth is added (see § Walking Skeleton First). Skip only when the project already has an end-to-end skeleton in place.
- **Characterization Testing (situational, mandatory when touching legacy code)**: when modifying untested legacy code, pin existing behavior with characterization tests before changing it (see § Legacy Code: Characterization Testing). Not required when the code is already covered by tests or when adding wholly new code.
