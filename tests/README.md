# Golden Test Cases

Pre-defined test scenarios for validating architecture changes. Used by
`/validate-changes` to run structured regression and effectiveness testing
instead of constructing tests ad-hoc.

## Structure

Each skill directory contains YAML test scenarios:

```
tests/
  {skill-name}/
    01-{scenario}.yaml
    02-{scenario}.yaml
```

## Scenario Format

```yaml
name: Human-readable test name
skill: skill-name
trigger: "What the user says to invoke this scenario"

must_happen:
  - "Ordered checklist of expected behaviors"

must_not_happen:
  - "Anti-patterns that indicate regression"

output_contains:
  - "Strings or patterns that should appear in output"

guards:
  - "Conditional checks that should fire (e.g., index status)"

skip_ab: false  # Set true for metadata-only changes
```

## The `deterministic:` block — the ONLY part CI enforces

The keys above (`must_happen`, `must_not_happen`, `output_contains`, `guards`) are
**documentation of intent**. Nothing executes them. `scripts/run-skill-evals.py`
returns `[]` and **skips the file silently** when it has no `deterministic:` block —
so a fixture without one contributes **zero** enforcement while still making the
coverage count look complete.

Measure real coverage with `scripts/measure-eval-coverage.py`, which separates
`deterministic` (enforced) / `qualitative` (silently skipped) / `uncovered`.

```yaml
deterministic:
  - frontmatter_equals:                      # exact equality
      name: my-skill
  - frontmatter_contains:                    # substring in the value
      allowed-tools: "AskUserQuestion"
  - frontmatter_matches:                     # regex over the value
      description: "(audit|verify)"
  - body_contains: "a named invariant"       # str OR list (list = ALL must be present)
  - body_not_contains: "a known-bad string"
  - body_matches: "regex \\(escaped\\)"
  - ref_resolves: "some-reference.md"        # references/<name> exists
  - script_exists: "scripts/helper.py"       # path relative to the skill dir
  - script_runs: "python3 scripts/helper.py --help"   # exits 0, cwd = skill dir
  - references_resolve: true                 # EVERY ref cited in the body exists
  - examples_count: ">=2"
  - tests_count: ">=1"
```

Run it: `python3 scripts/run-skill-evals.py --skill <name> --verbose`

### Three sharp edges (each one has cost a broken fixture)

**1. Each list item must have EXACTLY ONE key.** Attaching rationale as a sibling key
makes the whole assertion `malformed` — the harness reports it and runs **none** of
them. Put rationale in a YAML comment.

```yaml
# WRONG — 2 keys; this assertion never runs
- body_contains: "the thing"
  pins_what: "why this matters"

# RIGHT
# pins: why this matters
- body_contains: "the thing"
```

Related: if `deterministic:` is written as a **mapping** instead of a list, YAML keeps
only the **last** duplicate key — most assertions vanish with no error at all.
It must be a list (every item starts with `-`).

**2. `body_contains` does NOT see frontmatter.** `parse_frontmatter()` splits the file;
`body` is everything *after* the closing `---`. A skill that declares a hook prompt or
long config in frontmatter (e.g. `supergoal`'s `type:agent` Stop hook) needs
`frontmatter_contains` for those strings. A `body_contains` on frontmatter text always
fails.

**3. A list-valued assertion reports only the FIRST miss.** `body_contains: [a, b, c]`
fails on `a` and never tells you `c` is also absent. Verify each string against the
live file (`grep -c`) before adding it — paraphrased strings ("do NOT invoke /goal" vs
the real ``do NOT invoke `/goal` ``) are the common cause.

## Assertions must be able to FAIL

An assertion that cannot fail is worse than no assertion: it makes CI green and the
coverage number look complete while gating nothing.

The **non-vacuity gate** proves each assertion is COUPLED to its target — it breaks the
pinned content, confirms the assertion fails, then restores:

```
python3 scripts/mutation-check-evals.py --skill <name>
python3 scripts/mutation-check-evals.py --all     # whole corpus, ~13s
```

Verdicts: `BITES` (coupled) / `TAUTOLOGICAL` (still passed after its target was fully
removed — rewrite it) / `MALFORMED` (see edge 1 — never runs at all) / `UNMUTATABLE`
(pinned string not found) / `SKIPPED` (counting assertions).

### What it uniquely catches: vacuous assertions

The harness above cannot detect an assertion that passes because its scope is *empty*.
Proven 2026-07-25 on `gather-vendor` (3 files in `references/`, zero cited in the body):

```
- references_resolve: true     # harness: exit 0, "1 passing"  ← looks like coverage
                               # gate:    exit 1, TAUTOLOGICAL
```

`references_resolve` checks that every reference *cited in the body* exists. Cite
nothing and it passes trivially, forever, on any skill. This is the class that silently
manufactures fake coverage as the corpus scales — which is why the gate runs in CI.

(`MALFORMED` is also reported, but the harness already hard-fails on it, so that is not
unique to this gate.)

### Coupling is not meaningfulness — the gate cannot judge this for you

Measured 2026-07-25: `body_contains: "## Examples"` is reported **BITES**, because
deleting `## Examples` genuinely does fail the assertion — even though no realistic
edit would ever delete it. Same for `body_contains: "e"` (BITES, after the mutator
removed all 2,847 occurrences).

So the gate catches assertions that **never run** or are **decoupled**. It cannot tell
you an assertion is worth having. That judgment is yours, at authoring time — two
questions, and a good assertion answers both well:

1. **"Would a plausible regression remove this string?"** If only a deliberate rewrite
   would, it is structure the skill-rubric validator already covers. Pin *behavior*
   instead: thresholds, routing rules, guard names, script paths, corrected-bug
   strings, hard-won measured numbers.
2. **"Would an innocent copy-edit break this?"** If yes, it is over-pinned prose.

Empirical calibration for #2: PR #1704 added 88 lines to `cc-monitor/SKILL.md` and all
9 of that fixture's assertions still passed — they pin contracts, not narrative.

**Pin the fix, not the hole.** When sourcing assertions from `AUDIT-FINDINGS.md`, check
whether the finding is already fixed — many are. Assert the *corrected* state so the fix
cannot silently regress; asserting the historical bug fails immediately and invites
weakening the assertion into a tautology.

**Don't over-pin prose.** If a copy-edit would break the assertion, it's pinning
narrative wording rather than a contract.

## How /validate-changes Uses These

1. Detect which skills were modified (from git diff)
2. Load all test scenarios for those skills
3. For each scenario, verify the skill's behavior matches assertions
4. Report pass/fail per scenario with specific failures

## Growing the Suite

When a production bug is found:
1. Add a test case that would have caught it
2. Name it with the next sequence number
3. Include the bug description in the `name` field
