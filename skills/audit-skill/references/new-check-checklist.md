# Adding a new check to audit-skill — required checklist

Every check added to `bin/audit-skill.py` must satisfy this contract.
The fixture-trigger test (`tests/test_audit_skill_fixtures.py::
test_every_finding_code_has_a_fixture_trigger`) and the alignment guard
(`tests/test_audit_skill_helpers.py::test_skill_md_documents_every_finding_code_emitted_by_audit_py`)
enforce most of these mechanically; the rest are reviewer discipline.

## 0. Required preamble — verify the existing mechanism first

Before declaring a "gap" that justifies a new check, write down:

1. **What does the surrounding system already do** for the concern
   you're addressing? Grep `scripts/`, `bin/`, `manifests/`,
   `.github/workflows/` for related logic.
2. **Why is that mechanism insufficient?** Concrete failure mode, not
   abstract concern.
3. **Could you extend an existing check** instead of adding a new code?
   M2 was extended (reference-scan) rather than splitting into M2a/M2b.

If you can't answer (1) and (2) in a sentence each, do that work first.
The `--include-marketplace` flag from this session was scrapped because
the answer to (1) was the freshness check, which I hadn't read.

## 1. Severity tier

Pick one. Document the choice in the check's comment block.

- `drift` — fixing changes user-visible runtime behavior. The skill's
  output, exit code, or invariants differ once the bug is repaired.
  Examples: H1 (broken citation), D3a (missing script path), T1
  (phantom MCP tool — call would 404), P1 (placeholder rendered raw).
- `info` — hygiene / consistency / dead-code lint. Fixing improves the
  skill but doesn't change observable runtime. Examples: H2 (orphan
  ref), D3c (dead-code script), M2 (dead MCP declaration), B1
  (no tests/), Q1/Q3 (doc quality).
- `error` — internal sentinel for "audit-skill itself can't proceed"
  (E0 = skill not found). New checks should NOT use this level.

## 2. Finding constructor must include path + line

```python
findings.append(Finding("XX", "drift",
    "message that names the offending construct + a remediation hint",
    path=str(skill_md.relative_to(REPO)),
    line=line_no))
```

`path` is required (so the reader can navigate). `line` is required
when the check fires on a specific line (most checks); `line=None` is
acceptable only for whole-skill findings (B1, M1, Q2, Q3).

## 3. Suppression key

If a check has known legitimate exceptions, it must be suppressable
via `audit-suppress.yaml`. Wire it in:

```python
if _suppressed(suppressed, "XX", target=concrete_target):
    continue
```

Where `concrete_target` is whatever uniquely identifies the suppression
scope (a tool name for M2/T1; a script path for D3c). Document the
suppression schema in `skills/audit-skill/SKILL.md` if it differs from
the existing convention.

## 4. Fixture trigger — REQUIRED

Add a fixture under `tests/fixtures/` that triggers the new code.
The fixture-trigger test will fail otherwise. Prefer extending
`dirty-skill` (catch-all for "things that should fire") over creating
a new fixture, unless the trigger conflicts with existing ones
(e.g., C3 requires no .py files in scripts/, so it lives in
`shell-only-skill/`).

The fixture's purpose is *only* to trigger the check; it doesn't have
to be a realistic skill. Comments explaining what each violation is
for help future maintainers.

## 5. Docstring entry in bin/audit-skill.py

The top-of-file docstring's `Categories` section MUST list the new
code with a one-line description. The alignment guard test runs
against this.

## 6. SKILL.md prose mention

`skills/audit-skill/SKILL.md` must mention the new code in the
Phase 1 categories paragraph. The same alignment guard checks this.

## 7. Severity-vs-fixture sanity

Run `python3 ~/.claude/bin/audit-skill.py --all` after adding the check. The
output should:

- NOT regress clean skills (no new findings on previously-OK skills
  unless those findings are real bugs you're now catching).
- DO fire on the targeted patterns (you'll see them as new findings).

If the new check produces a large finding count on the live tree,
that's a signal — either the rule is too broad (false positives, fix
the rule) or there's a real systemic gap (fix the skills). The
2026-05 audit's M2 fired 89 times initially; the fix was to extend
the scan to `references/`, dropping to 9.

## 8. Don't ship behind a flag without a CI exercise

If the check is gated on a flag like `--strict-tools`, the flag must
be exercised in CI or in tests. The `test_every_cli_flag_is_exercised_in_tests`
test enforces this — without it, the code path is latent and
regressions ship silently until someone enables the flag.

## 9. Document in changelog-style commit message

Commit messages should describe:
- What the new code catches (one line)
- What pattern instances it found in the live tree (concrete examples)
- Why severity is `drift` vs `info`

This forms the working memory of why each check exists. When a
maintainer asks "can we delete X?" two years from now, the commit is
the answer.

## 10. Reproducer authoring — match the shell the finding targets

The oracle executes `bash`/`grep`/`grep_absent` reproducers under
**bash** (`_resolve_bash()` → `shutil.which("bash")`), but the
production Bash tool on this host runs **zsh**. A finding about
shell-divergent behavior (zsh non-word-splitting, `${VAR:+...}`
differences, glob NOMATCH on unquoted `?`/`*`) can therefore NEVER
fire under the oracle's executor even while the bug is live in every
real session — it false-STALEs and gets dropped at the act-on gate.

Rule: when the finding's mechanism depends on which shell runs the
command, wrap the probe explicitly in the shell it targets:

```yaml
reproducer:
  type: bash
  command: zsh -c 'ORGS="--owner a --owner b"; gh search prs $ORGS --limit 1'
  expected_exit: 1
```

Use `bash -c '...'` the same way when asserting bash-specific behavior.
Observed 2026-06-12: 5 zsh-class A1 findings (pr-fix ×2, weekly-update,
security-alerts, mcp-create) false-STALE'd until rewrapped in `zsh -c`.

Beyond shell-divergence, three more couplings make a reproducer
false-STALE (so act-on/refresh-tracker drops a live bug) or false-fire
(so a correct fix never adjudicates STALE):

- **Worktree-couple the predicate.** Test repo-root-relative paths
  (`grep ... skills/<skill>/...`), NEVER a `~/.claude/...` path. A
  `~/.claude` reference scores the DEPLOYED checkout (often a stale
  branch), not the tree under test, so it can't flip when the worktree
  is fixed — and during a fix campaign it inflates the act-on
  STILL-FIRES count with already-fixed findings. (Same root cause as the
  "run the worktree's oracle copy for reverify" note in audit-fix Step 3.)
- **Never hardcode the bug's logic inline.** A reproducer that
  re-implements the buggy expression (e.g. `python3 -c "w=[...]; w['runs']"`)
  is decoupled from the artifact — it returns the same verdict whether or
  not the source is fixed. Probe the file under test instead.
- **Use a fresh `mktemp -d` per run, never a fixed `/tmp/...` path.** A
  reproducer that appends to a fixed file accumulates rows across the
  act-on AND reverify runs; the stale row keeps the predicate firing
  after the fix. (2026-06-16: idx11 roundtable false-fired exactly this
  way — act-on's pre-fix row stayed in the fixed runs.csv that reverify
  appended to.)
- **A mention-grep is an invalid oracle for a finding whose fix is a
  documented DENIAL.** `grep -q 'retired/path'` fires on ANY mention —
  and the natural fix for a stale-claim finding is prose that QUOTES the
  retired thing to deny it ("there is no `retired/path` fallback"), so
  the correct fix keeps the predicate firing forever. Target the CLAIM
  text ("falls back to `retired/path`"), never the bare token.
  (2026-08-22: mcp-forge-audit's fix re-fired its own finding exactly
  this way; same class as the self-referential-checker items 19/32 in
  `rules/tdd-mutation-testing.md`.)

And match the reproducer `type` to its fire-direction so "fires ==
bug-present": `grep` fires on a match (exit 0); `grep_absent` fires on NO
match (exit 1); `bash` fires when `rc == expected_exit` (default 0).
Inverting the direction is the single most common authoring error
(2026-06-16: 2 of 16 agent-proposed `updated_reproducer`s had it
backwards). Corollary: a re-baseline (`act-on`, `refresh-tracker`) is
only as trustworthy as these couplings — when it stamps a behavior-fix
STALE, spot-check the closure against source before trusting it; a
deployed-path or inline reproducer false-STALEs a still-live bug.
