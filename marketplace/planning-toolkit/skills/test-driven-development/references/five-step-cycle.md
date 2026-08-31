# The Five-Step Cycle — Detailed Phase Guide

Read this when working through a TDD cycle and you need the full
phase-by-phase detail (test examples, verification commands, domain review
checklists, assertion quality gate, commit gate, refactor rules).

```
RED → DOMAIN → GREEN → DOMAIN → COMMIT → (REFACTOR)

┌─────────────────────────────────────────────────────────────────────┐
│  1. RED       Write one failing test. Test files only.              │
│  2. DOMAIN    Review test for primitive obsession. Add type stubs.  │
│  3. GREEN     Minimal code to pass. Implementation files only.      │
│  4. DOMAIN    Review impl for domain violations. Types still clean? │
│  5. COMMIT    Run full suite. Commit. Discipline gate (self-enforced)  │
│               — no new RED until this commit exists.                │
│  6. REFACTOR  (Optional) Clean up structure. Separate commit.       │
└─────────────────────────────────────────────────────────────────────┘
```
(Cycle source: jwilger/eventcore TDD — Context7 registry 2026-04-06.
Adapted for Example: simplified DOMAIN to review-only, no agent teams.)

## RED - Write Failing Test

Write one minimal test showing what should happen.

<Good>
```typescript
test('retries failed operations 3 times', async () => {
  let attempts = 0;
  const operation = () => {
    attempts++;
    if (attempts < 3) throw new Error('fail');
    return 'success';
  };

  const result = await retryOperation(operation);

  expect(result).toBe('success');
  expect(attempts).toBe(3);
});
```
Clear name, tests real behavior, one thing
</Good>

<Bad>
```typescript
test('retry works', async () => {
  const mock = jest.fn()
    .mockRejectedValueOnce(new Error())
    .mockRejectedValueOnce(new Error())
    .mockResolvedValueOnce('success');
  await retryOperation(mock);
  expect(mock).toHaveBeenCalledTimes(3);
});
```
Vague name, tests mock not code
</Bad>

**Requirements:**
- One behavior
- Clear name
- Real code (no mocks unless unavoidable)

## Verify RED - Watch It Fail

**MANDATORY. Never skip.**

```bash
npm test path/to/test.test.ts
```

Confirm:
- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)

**Test passes?** You're testing existing behavior. Fix test.

**Test errors?** Fix error, re-run until it fails correctly.

## DOMAIN (after RED) - Review Test for Type Quality

Before implementing, review the test you just wrote:

1. **Primitive obsession check**: Does the test use `string` where it should
   use `EmailAddress`, `UserId`, `Severity`? Does it pass raw numbers where
   a typed wrapper would prevent invalid states?
2. **Invalid-state prevention**: Could the types make bad inputs
   unrepresentable? If the test accepts `{ email: '' }`, should the type
   system reject empty strings at construction?
3. **Create type stubs**: If the review reveals missing types, create them
   now with stub bodies (`todo!()`, `raise NotImplementedError`, `pass`).
   Do NOT implement logic — just signatures and constructors.

**Done when**: Tests compile (or import) but still FAIL at runtime.
Compilation failure IS a test failure — don't pre-create types to avoid it.

**Skip DOMAIN when**: Test is trivially simple (single assertion on a
primitive return value) or you're in a rapid bug-fix cycle. Use judgment.

## GREEN - Minimal Code

Write simplest code to pass the test.

<Good>
```typescript
async function retryOperation<T>(fn: () => Promise<T>): Promise<T> {
  for (let i = 0; i < 3; i++) {
    try {
      return await fn();
    } catch (e) {
      if (i === 2) throw e;
    }
  }
  throw new Error('unreachable');
}
```
Just enough to pass
</Good>

<Bad>
```typescript
async function retryOperation<T>(
  fn: () => Promise<T>,
  options?: {
    maxRetries?: number;
    backoff?: 'linear' | 'exponential';
    onRetry?: (attempt: number) => void;
  }
): Promise<T> {
  // YAGNI
}
```
Over-engineered
</Bad>

Don't add features, refactor other code, or "improve" beyond the test.

## Verify GREEN - Watch It Pass

**MANDATORY.**

```bash
npm test path/to/test.test.ts
```

Confirm:
- Test passes
- Other tests still pass
- Output pristine (no errors, warnings)

**Test fails?** Fix code, not test.

**Other tests fail?** Fix now.

## `[EXAMPLE]` Assertion Quality Gate

Before proceeding to REFACTOR, verify no assertion was weakened to achieve green:

- `toBe` → `toBeTruthy` (specific → vague)
- Exact value check → range/partial check
- Test cases deleted or commented out
- Mock return values changed to match buggy output
- Error case tests replaced with skip/todo
- Assertion count reduced from prior version

**If any assertion was weakened**: the test is lying, not passing. Restore the original assertion and fix the code instead. See `rules/tdd-quality.md`.

## DOMAIN (after GREEN) - Review Implementation for Domain Violations

Before committing, review the implementation you just wrote:

1. **Anemic model check**: Did you put behavior in a service that belongs
   on the domain object? If `OrderService.calculateTotal(order)` could be
   `order.total()`, the model is anemic.
2. **Leaked validation**: Is validation scattered across callers instead
   of enforced by the type? `if amount > 0` in three places means
   `PositiveAmount` should be a type.
3. **Primitive obsession that slipped through**: Did the GREEN phase
   introduce `string` parameters where a domain type was stubbed in DOMAIN?
   If so, use the stubs.

**Done when**: Types are clean, validation is in constructors not callers,
and tests still pass.

**If violations found**: Fix them now while the context is fresh. Don't
defer to a refactor step — domain purity degrades once you move on.

## COMMIT - Discipline Gate (Self-Enforced)

**No new RED phase may begin until this commit exists.** No pre-commit or Stop hook enforces this; the model self-polices it.

1. Run the full test suite (not just the file you changed)
2. `git add` only files from this cycle
3. `git commit` with a message referencing what behavior was added
4. Verify clean: `git status` shows no uncommitted changes from this cycle

This gate prevents accumulating multiple untested cycles. If the full
suite fails, fix it before committing — don't start a new RED phase on
top of a broken suite.
(Pattern source: jwilger/eventcore TDD commit gate — Context7 registry 2026-04-06)

## REFACTOR - Clean Up (Optional, Separate Commit)

After COMMIT only:
- Remove duplication
- Improve names
- Extract helpers

Keep tests green. Don't add behavior. If you refactor, commit separately
from the feature commit.

## Repeat

Next failing test for next feature.
