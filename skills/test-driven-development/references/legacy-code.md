# Legacy Code: Characterization Testing

Read this when modifying existing **untested** code. Standard TDD writes a
FAILING test first. Legacy code needs PASSING tests first — capturing
current behavior as a safety net before you change anything.

## The RGR Workflow for Legacy Code

```
1. RED ZONE  — Write tests that capture CURRENT behavior (should PASS immediately)
2. GREEN     — Verify those tests pass (confirms you captured reality correctly)
3. REFACTOR  — NOW you can safely modify with a safety net
```

**The critical difference from standard TDD:**
- Standard TDD: You know what the behavior SHOULD be → write test for ideal
- Legacy RGR: You DON'T know all behaviors → capture what EXISTS

## Behavior Classification

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

## Process

1. **Read the code** — Identify all inputs, outputs, edge cases, side effects
2. **Write characterization tests** — Document what the code actually does, not what it should do
3. **Verify they pass** — If they don't, you misunderstood the behavior. Fix the test, not the code.
4. **Make your changes** — The characterization tests are your safety net
5. **Run tests** — Verify behavior preserved (or intentionally changed with documented reason)

## Strangler Fig Pattern (for large untested systems)

For systems too large to test all at once:

1. **Wrap**: Add a new interface around the legacy code
2. **Test the boundary**: Write tests for the wrapper
3. **Replace internals**: Gradually move logic from legacy to new code
4. **Expand**: Repeat for the next function

The system stays working at every step. You can stop at any point.

## When to use this instead of standard TDD

- Code you're modifying has no existing tests
- Test coverage is below 80% for the code you're touching
- You inherited code from a previous developer/session
- Changing behavior in infrastructure code (Terraform, config, hooks)

(Pattern source: thebushidocollective/han `legacy-code-safety` — Context7 registry 2026-04-16)
