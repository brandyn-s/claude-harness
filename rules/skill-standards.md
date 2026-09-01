---
paths:
  - "**/.claude/skills/**"
  - "**/SKILL.md"
  - "**/.claude/hooks/**"
---

# Skill Standards (from Anthropic Guide)

When creating or modifying skills in `~/.claude/skills/`:

- File name: `SKILL.md` (case-sensitive) — no variations
- Folder names: kebab-case `my-skill-name` — no spaces, underscores, or capitals
- Folder name matches the `name:` field in YAML frontmatter
- YAML frontmatter has `---` delimiters with `name:` and `description:` fields
- `description:` includes WHAT it does + WHEN to use it (trigger phrases) + Do NOT use for (negative triggers)
- No XML angle brackets (`<` `>`) in frontmatter — security restriction
- No bare dollar-numeral tokens (`$0`, `$1`, …) in SKILL.md prose or examples —
  the skill loader substitutes the invocation's arguments into them at load
  time, corrupting the text the model reads. Live instance (2026-06-12,
  audit-fix): a cost line containing the dollar-amount `~$0.50` rendered with
  the caller's full argument string injected where `$0` stood. Spell out
  amounts ("roughly 50 cents") or restructure the sentence.
- **QUOTE any frontmatter value containing a colon-space.** An unquoted YAML scalar
  is a *plain* scalar, and `: ` inside one is read as a mapping separator — so the
  whole frontmatter block fails to parse and every field silently disappears.
  Measured 2026-08-29: `when_to_use: Use when ... leaves the sender's Sent Items copy,
  every Re:/FW: derivative, ...` scored **0/14** on `validate-skills.py`. The trigger
  was `FW: derivative`. Common carriers of this shape in a `description` or
  `when_to_use`: reply prefixes (`Re:`, `FW:`), times (`21:27 UTC` is fine, `at 3: 00`
  is not), ratios, and quoted error strings (`400: Bad Request`). Wrap the value in
  double quotes and use single quotes inside it.
  **DIAGNOSTIC: a rubric score of 0/14 with `A1_frontmatter` among the failures means
  the block NEVER PARSED — it is one bug, not thirteen.** Do not start fixing the
  other twelve checks. Confirm with
  `python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]).read().split('---',2)[1])" <SKILL.md>`
  and read the reported line/column. A genuinely low-but-nonzero score (say 9/14) is
  the case where the individual checks really are failing.
- No `README.md` inside skill folders — all docs go in SKILL.md or `references/`
- No `claude` or `anthropic` in skill names — reserved
- Put the key use case first. Claude Code truncates the combined `description`
  and `when_to_use` listing text at 1,536 characters; keep the combined text at
  or below that current limit so routing evidence is not silently dropped.
- **Split trigger — 500 lines is a SOFT guideline, NOT a hard cap** (Anthropic,
  verified 2026-06-22 against the live best-practices page + the canonical
  `skill-creator` skill): keep the SKILL.md body under **500 lines for optimal
  performance**, splitting into `references/` via progressive disclosure when
  *approaching* the limit. But the cap is explicitly exceedable with cause —
  Anthropic's best-practices checklist says "under 500 lines **(or has clear
  reason to exceed)**" and `skill-creator` states verbatim: *"These are
  guidelines, not hard limits… if your instructions are genuinely complex, it's
  fine to exceed 500 lines."* The runtime constraint is lifecycle-specific:
  Claude Code loads the full rendered skill on initial invocation, but after
  auto-compaction it reattaches only the **first 5,000 tokens per invoked
  skill**, within a **25,000-token combined newest-first budget**. Older invoked
  skills can be omitted when that shared budget is exhausted. A long skill can
  therefore work initially while losing a load-bearing tail gate after
  compaction. So: prefer references, place invariants and recovery instructions
  near the top, and re-invoke a skill after compaction before relying on its
  tail. Anthropic explicitly documents re-invocation as restoring the full
  content. Our `validate-skills.py` C1 still treats **≤510 lines** as a soft
  readability guideline, not a runtime cutoff.

  Any active SKILL.md above the repository's conservative 4,000-token
  `chars/4` proxy must include a top-of-body **Compaction continuity** contract.
  It must tell Claude to re-invoke the skill after compaction before continuing;
  if `disable-model-invocation: true` prevents that, it must stop and ask the
  user to invoke the skill. This proxy leaves headroom below the documented
  5,000-token reattachment boundary and is a structural guard, not a claim
  about the target model's exact tokenizer.
  Sources: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
  + anthropics/skills `skill-creator/SKILL.md` (verified 2026-06-22), plus
  https://code.claude.com/docs/en/skills#skill-content-lifecycle (verified
  2026-08-08). SKILL.md is the overview / table of contents; reference files
  (FORMS.md, reference.md, examples.md, references/*.md) load on demand and
  carry no context cost until read.
- Community guidance (secondary, NOT authoritative): mattpocock/skills suggests
  ~100 lines as an aggressive split trigger. Use this as a NUDGE, not a rule.
  Anthropic's (soft) 500-line guideline takes precedence whenever the two disagree.
- Reference files in `references/` SHOULD lead with a "Critical Gotchas" section before showing correct patterns. Format: "Do not do X — it causes Y". This mirrors the architecture's most effective rule pattern. Skip for purely structural references. (okhlopkov — ton-analyst: 14 numbered critical gotchas from production SQL errors)
- Every skill has: Examples section (2+ concrete examples), Success Criteria section
- For detailed quality guidance, consult `memory/skill-development-patterns.md`
- When modifying a hook, add or update its test file in `hooks/test-hooks/`
- When choosing terminology in skills, consult `UBIQUITOUS_LANGUAGE.md` for canonical terms. Use "guard" not "blocker," "gate" not "checkpoint," "ship" not "deploy." Aliases to avoid are listed per term.

## Pre-push validation for a new/changed skill

**Run the aggregator, not a hand-picked subset:**

```bash
python3 bin/preflight-skill.py              # all current gates (~40s, measured)
python3 bin/preflight-skill.py --fast       # skips the two >10s gates (~10s; what pre-push runs)
python3 bin/preflight-skill.py --list       # every gate + the tests.yml step it mirrors
python3 bin/preflight-skill.py --only <key> # re-run one gate after fixing it
```

`bin/preflight-skill.py` mirrors `.github/workflows/tests.yml (this export ships gitleaks.yml, plugins.yml, tests.yml; the upstream tests.yml is not part of it)` step-for-step and
gates on each tool's EXIT CODE — never on grepping its output, because a changed
output prefix silently disables that kind of gate (CI itself was fixed away from
prefix-coupling on 2026-07-26). `.githooks/pre-push` runs `--fast` automatically on
any push touching `skills/`, `hooks/`, or `rules/`, so a push is already gated; the
full tier is the pre-PR check.

**"step-for-step" has THREE documented exceptions — do not read it as full parity:**

1. **`pytest scripts/` is NOT a gate.** CI's "Run scripts/ tests" step is not in the
   set. A change to `bin/` or `scripts/` can pass preflight and still fail CI —
   2026-07-29: `scripts/test_preflight_skill.py::test_no_gate_mutates_the_tree`
   failed on all 3 platforms after a green full-tier run. **Run
   `python3 -m pytest scripts/ -q` yourself before pushing anything under `bin/` or
   `scripts/`.**
   **Also run it for a `rules/` change.** The trigger is not the directory you
   edited — it is which suite tests what you edited, and `scripts/` tests the
   RULES CORPUS. `scripts/test_context_policy_contracts.py` enforces the
   ambient corpus against the DERIVED ceiling in `manifests/ambient-budget.json`
   (`baseline + sum(justified ledger entries)`), a growth gate distinct from
   `rule-size-guard.py`'s per-file WARN 35,000 / BLOCK 38,000. The former per-file
   caps (10,000 B / 5,000 B) are retired -- they were cliffs that repairs converged
   to. 2026-08-15: an append to
   `rules/verify-before-assuming.md` (10,714 B) passed **20/20 preflight** and
   turned `main` red, because the author checked the remembered budget rather
   than the enforcing one. Before pushing a `rules/` edit, measure
   `len(path.read_bytes())` against the cap the TEST asserts.
2. **Marketplace sync is deliberately NOT a gate** (it would write the tree, which
   `test_no_gate_mutates_the_tree` forbids). `.githooks/pre-push` owns it — but only
   in a clone where `core.hooksPath` is wired, which is per-clone and unmanaged for
   claude-config (see `git-hygiene`). For a one-off manual check:
   `python3 scripts/check-marketplace-sync.py`.
3. **`pytest skills/` is NOT a gate either, and it collects `test_*.py` from
   EVERYWHERE under `skills/` — not just `skills/*/tests/`.** The
   "Run per-skill golden tests" step's `find` guard looks in `*/tests/`, but the
   command it then runs is `pytest skills/ -q`. So a file named `test_*.py` in a
   skill's `scripts/` dir **is imported by pytest at collection time on a CI
   runner**. Verify before pushing a new `test_*.py` under `skills/`:

   ```bash
   python3 -m pytest skills/ -q --collect-only   # 0 collection errors required
   ```

   **`--collect-only` PROVES IMPORTS RESOLVE AND NOTHING ELSE. It is not a
   substitute for the run.** Collection imports each module; it never executes a
   single assertion. Measured 2026-08-21: `preflight-skill.py --fast` returned
   **18/18 PASS** and this exact `--collect-only` command exited 0 with 2,607 tests
   collected, while CI's "Run per-skill golden tests" step — which runs
   `pytest skills/ -q` for real — reported **18 failed, 2,575 passed**. Because
   `pytest skills/` is not a preflight gate (this list's own point 3), the only
   local signal that can see an assertion failure is running it yourself:

   ```bash
   python3 -m pytest skills/ -q     # the actual gate; ~3 min in CI, longer locally
   ```

   Budget for it: the same suite took 178s on a CI runner and **15m23s** locally, so
   run it in the background rather than substituting the cheap command for the real
   one. A `--collect-only` pass reported as verification is the same class of error
   as citing a plan instead of an apply.

   **NAMING RULE for skill scripts: an operator-run diagnostic must NOT be named
   `test_*.py`.** If it executes at module level, needs live credentials, or needs
   a repo/clone that CI does not have, pytest will run it during collection and
   fail the entire job. Name it `verify_*.py` or `check_*.py`, and have it print a
   SKIPPED message and `exit 0` when its prerequisites are absent.
   (2026-08-12: `skills/software-security-review/scripts/test_preflight_checks.py`
   did exactly this — module-level execution plus a required knowledge-base clone
   — and reddened the lane with `FileNotFoundError` during collection while the
   full local tier was green.)

   **A test file's BASENAME must be unique across all of `skills/`.** Neither
   `scripts/` nor `tests/` is a package, so pytest imports by module name and two
   same-named files collide: `import file mismatch`, collection **exit 2**, whole job
   red. A SCOPED run (`pytest skills/<one-skill>/scripts/`) cannot see it — only a
   run spanning both dirs can. 2026-08-30: adding
   `skills/gather-claude/scripts/test_parse_watching.py` beside the existing
   `tests/test_parse_watching.py` (there since 2026-07-05) broke collection on main,
   and a parallel session diagnosed it as "pre-existing". `--collect-only` over
   `skills/` DOES catch this class in ~2s; run it for every new `test_*.py`, and
   prefer merging into the existing file for that module over creating a second one.

   Do **not** "fix" the CI step by narrowing it to `skills/*/tests/`: measured
   2026-08-12, that drops **23 passing tests** across `skills/_shared/test_stats.py`,
   `skills/_shared/activation-eval/test_run_activation_eval.py`, and
   `skills/gather-claude/scripts/test_report_lifecycle.py`. The breadth is
   load-bearing; the guard's narrower path is what is misleading.

Also note `pre-push` filters on the pushed range touching `^(skills|hooks|rules)/` —
a `bin/`- or `scripts/`-only push runs NO pre-push checks and prints nothing, which
looks identical to "hooks not installed". Both exceptions land on the same class of
change, so a `bin/`/`scripts/` edit is the least-gated thing you can push.

**Why an aggregator instead of a list:** selecting a subset from memory is the
documented failure mode, and it has now recurred three times.

- 2026-06-14 `/lab-review` #1276 — **3 CI cycles**. Only `validate-skills` +
  `audit-skill` ran locally; the drift gate and cross-chain validator are separate
  Matrix-validate steps.
- 2026-07-26 — **1 cycle**. `validate-skill-chains.py` was run WITHOUT `--strict`,
  and without the flag a dangling target exits 0 (a literal `/connect` in prose
  parsed as a chain ref to a nonexistent skill; local green, ubuntu matrix red).
- 2026-07-28 `/gather-claude-endpoints` #1740 — **2 CI cycles**. (1) `guardrails:`
  is a *reference* field naming hook IDs; four prose sentences there produced four
  `DANGLING` errors. (2) Adding a skill moved the count 105 → 106, gated in
  `ARCHITECTURE.md` **and** `README.md`. Both catchable locally in under a second.

The aggregator encodes each of those flags and thresholds (`--strict`, `--gate 13`,
`--all`), which is exactly what a remembered list keeps getting wrong. Individual
commands, for when you need to run one directly:

```bash
python3 scripts/build-marketplace.py       # marketplace sync (pre-push also checks this)
python3 bin/audit-skill.py <skill-name>    # READ THE EXIT CODE — grepping output for "clean" misses a non-zero FAIL (2026-07-21)
python3 bin/audit-skill.py --all           # C3/D3c orphan-script drift; a single-skill audit does NOT catch it (2026-07-21 PR #1647 macos leg)
python3 manifests/compile.py --root . --check --no-reindex  # requires_rules/requires_skills must be BARE SLUGS, not .md filenames (2026-07-21 PR #1647 ubuntu leg)
```

- **Drift gate**: adding any skill increments the `skills/` count, so the claims
  in `ARCHITECTURE.md` (the "Skill manifests | … | N" row + "Current N skills"
  prose) and `README.md` ("N skills") drift — update both in the same PR. Fires
  for a `skills/`-only skill too; it is NOT gated on marketplace registration
  (the gate counts `skills/` dirs). See agent-memory `architecture.md`
  "registering a NEW skill touches four places".
- **Cross-chain validator**: a `/slash` reference in a SKILL.md is a chain edge
  to `skills/<name>/`. Only `/slash`-cite skills that EXIST in `skills/`;
  built-in / plugin skills (`/code-review`, `/simplify`, …) are not there and
  flag as dangling — reword without the slash.
- **Tool-declaration drift gate** (`bin/reconcile-skill-tools.py --all`; CI step
  "Skill tool-declaration drift gate"): string-matches every `mcp__…` token in a
  SKILL.md BODY against `allowed-tools`. A body token not in `allowed-tools` fails
  CI — INCLUDING a *cautionary* "this `mcp__x__tool` was retired" mention. Use the
  **wildcard** form (`mcp__x__*`) in retirement notes so the mention doesn't read as
  a grant. (2026-06-19: a retired-tool note tripped this on a research-skill edit; the
  gate was absent from this list, costing a fix-forward CI cycle.)

`references/*.md` are memory-search-indexed (the `ASI06` hook blocks a write
over the ~2500-char chunk cap) — keep each under 2500 / split with `##` headers.

## Standalone Skill vs Embedded Phase

When a capability could be either a new skill or a phase in an existing skill: does it have
use cases outside the host skill? If yes, standalone. Embedding a general capability inside
a specific workflow makes it invisible to other workflows.
(interview skill incident 2026-04-05: adversarial plan review embedded in /superplan was
invisible to skill drafts, architecture decisions, and proposals. Extracted to standalone.)

## Lesson Propagation

When a session discovers a general principle while working on a specific skill: if the lesson
would prevent the same mistake in a DIFFERENT skill, it belongs in a rule file, not just the
skill where it was found. A lesson trapped in one skill is half-learned.

## SKILL.md Step Format — Depends on Skill Type

The rule-format findings (see `rule-authoring.md` and
`knowledge-base/topics/rule-format-effectiveness.md`) partially transfer
to SKILL.md steps. Tested empirically on 4 skills with 5 variants (md,
dsl, hybrid, strongwording, constitutional) × 2 models × n=3 trials
(2026-04-19):

| Skill | Type | Opus (const vs md) | Haiku (const vs md) |
|---|---|---:|---:|
| /ship | mechanical | +0.8pp (flat) | 0.0pp (flat) |
| /distill | judgment | +2.8pp | **+13.9pp** |
| /capture | judgment | 0.0pp | **+15.3pp** |
| /retro | orchestration | **+15.3pp** | **+11.1pp** |

Full writeup: `knowledge-base/topics/skill-format-effectiveness.md`.

### What this means for skill authoring

**Classify the skill first:**

- **Mechanical skills** — clear tool-call sequences, forbidden commands
  explicitly named in prose. Examples: `/ship`, `/ship-hook`, `/pr-fix`.
  **Keep markdown.** Baseline is already at ceiling; format conversion
  is wasted tokens.

- **Judgment-heavy skills** — classification, narrative generation,
  sequential orchestration with mandatory steps, multi-phase planning.
  Examples: `/distill`, `/capture`, `/retro`, `/triage`, `/superplan`,
  `/investigate`, `/fp-check`. **Consider constitutional format** —
  especially if the skill may run on Haiku.

**High-leverage skill interventions (in all cases):**
1. Expose `AskUserQuestion` in `allowed-tools` when the skill has a
   decision gate (v5 finding: raised triage compliance 88.9% → 100%).
   Healthcheck Check 3 warns on non-empty `allowed-tools` missing this.
2. Write clear Examples and Success Criteria sections.
3. Keep SKILL.md under 500 lines (Anthropic guidance — extract references for longer skills via progressive disclosure).

### Why the transfer is partial

Skill invocation anchors the model into a scoped workflow. For
mechanical skills, the invocation anchor + clear tool sequences fully
determine behavior — format adds no headroom. For judgment-heavy skills,
the invocation anchor only partially resolves what to do; the unanchored
decisions (which tier? which topic to match? which mandatory step is
next?) are where format earns its keep. On Haiku specifically,
constitutional format lifts judgment-skill compliance 11-15pp — matching
the "strongwording is a floor normalizer" pattern from the rule work.

## Rule Integration Tiers

When a skill depends on a rule from `~/.claude/rules/`, choose the right integration tier:

| Tier | When to use | Example |
|------|------------|---------|
| **Ambient** (no reference) | Universal rules that apply everywhere | `git-hygiene.md`, `platform-constraints.md` |
| **Reference** (one-line pointer) | Informational rules the skill should follow | "Follow `web-search-preference.md` for tool selection" |
| **Embedded step** (explicit workflow step) | Critical rules where violation breaks output | Refine Step 2: "Scan ALL loaded rules semantically" |
| **Decision gate** (tool-based) | Steps where proceeding without user input is destructive or irreversible | `REQUIRED: Call AskUserQuestion` before PR creation with security findings |

Explicit skill steps are followed more reliably than ambient rules under cognitive load. For rules critical to a skill's correctness, embed as a step. For steps where skipping user input causes irreversible harm (security gates, destructive operations), use the Decision Gate tier — the `AskUserQuestion` tool call is binary (happened or didn't), making it auditable in JSONL transcripts. Apply selectively to high-stakes decision points, not broadly.

### Cross-Skill Pattern Enforcement

A rule embedded as a step in one skill (Tier 3: Embedded step) only fires
when that skill is invoked. If the violating pattern appears in code
generated across *multiple* skills, single-skill embedding will not
reduce the violation rate.

Signals that embedding in one skill is not enough:
- The violation pattern is language-level (e.g., Python `str.replace('\n', ...)`,
  missing `encoding='utf-8'`), not domain-specific
- `audit-rules` shows violations distributed across many skills' generated code
- Post-promotion audit shows <30% relative reduction from the pre-promotion rate

When these signals appear, escalate to **hook enforcement** (PreToolUse or
PostToolUse `decision: "block"`) or add a GUARD block to an **ambient rule
file** — do not just embed in another skill.

Evidence: `str-replace-crlf-risk` was embedded in `bulk-api-script` Step 5
(PR #641, 2026-04-17). Three days later `audit-rules` still measured 21.0%
session rate — the pattern appears in any Python-script-authoring skill,
not just `bulk-api-script`. Moved to a `post-write-edit.py` hook check
(PR #708, 2026-04-21).

## Community Comparison (for skills addressing common patterns)

When building a skill that addresses a commonly-solved problem (prompt improvement, code review, deployment, testing), run `/gather-intel [skill topic]` during the REFACTOR phase to compare with community approaches. This prevents reinventing existing solutions and discovers framing that strengthens the design. Skip for domain-specific or internal-only skills.

## Model Invocation Control

Claude Code exposes two official, independent controls (verified 2026-08-08):

- `disable-model-invocation: true`: user-only. Claude cannot invoke the skill,
  its description is removed from Claude's context, and it is not preloaded into
  subagents. The user can still invoke `/skill-name` explicitly. Use this for
  workflows with side effects, meaningful spend, or user-controlled timing.
- `user-invocable: false`: model-only. The skill is hidden from the `/` menu,
  but Claude can still discover and invoke it. Use this for background knowledge
  that is useful to Claude but is not a meaningful user command.
- Default (both omitted): both the user and Claude can invoke the skill.

These are independent controls, not aliases or migration equivalents.
`user-invocable: false` does not block Skill-tool access; use
`disable-model-invocation: true` when programmatic invocation must be blocked.
Avoid setting both restrictions unless making the skill intentionally inert is
the documented outcome. The `skill-routing-hint.py` hook may still suggest a
user-only skill, but the user decides whether to invoke it.

Source: https://code.claude.com/docs/en/skills#control-who-invokes-a-skill

## Naming Convention (new skills — ratified 2026-06-19)

Skill names are `kebab-case` and follow **`<domain>-<action>`** (action-suffix):
the noun/domain comes first, the action is the suffix. This groups related
skills alphabetically by domain and matches the largest established families.

| Family (suffix) | Members | A new sibling is… |
|---|---|---|
| `-review` | `lab-review`, `differential-review`, `sca-review`, `readiness-review`, `service-review` | `<domain>-review` |
| `-deploy` | `lab-deploy` | `<domain>-deploy` |
| `-diagnose` | `mcp-diagnose`, `plateau-diagnose` | `<domain>-diagnose` |

Rules:
1. **Action-suffix, not verb-first.** `service-review`, NOT `review-service`;
   `readiness-review`, NOT `assess-readiness`. (Verb-first names like
   `build-measurement-harness`/`index-repo` predate this convention — they are
   grandfathered, not a counter-pattern to follow.)
2. **Join an existing family by its suffix** when the action matches (`-review`
   for read-only assessment that emits a worklist; `-deploy`, `-diagnose`, etc.).
   A prefix family (`audit-*`, `gather-*`, `mcp-*`, `codebase-memory-*`,
   `supergoal-*`) is the exception where the SHARED SYSTEM is the prefix and the
   variant is the suffix — match the dominant pattern of the system you're
   extending, don't invent a third.
3. **No synonym duplicates.** Before naming, `ls skills/` for an existing
   synonym (the corpus already carries `retro`+`retrospective` — do not add more).
4. **Spell it out; abbreviate only for an established term** (`sca`, `fp`, `cc`,
   `mcp`, `stig` are domain terms; don't abbreviate ordinary words).

SCOPE: this convention binds **new** skills. The 97 existing skills are NOT
being renamed (rename churn — PR cost, muscle memory, cross-references — exceeds
the consistency benefit); a separate aliasing effort can normalize them later if
desired. (per `scope-discipline` — convention-now, retro-rename-separately.)

## Description Quality

When generating or rewriting tool descriptions, docstrings, or documentation at scale:

1. **Never use regex-based bulk rewriting** for descriptions — mechanical pattern matching produces worse output than the original
2. **Write domain-specific descriptions by hand** — explain what the tool returns, what changes it makes, and when an LLM should choose it
3. **Build a description mapping dict** with hand-crafted text, then apply via a single Python script
4. **Include consequences for write operations**: what changes, whether it's reversible, what breaks if used wrong
5. **Include return value context for reads**: what fields/structure the response contains

## Additional Frontmatter Fields (official docs, verified 2026-08-08)

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Local yes | Display name; Claude Code defaults to the directory name, while this repository requires an explicit matching name. |
| `description` | Local yes | What the skill does and when to use it. Officially recommended; this repository requires it. Combined with `when_to_use`, listings truncate at 1,536 chars. |
| `when_to_use` | No | Additional routing context appended to `description`; counts toward the combined 1,536-character listing cap. |
| `argument-hint` | No | Display hint for `/` menu (e.g., `[issue-number]`, `[filename] [format]`) |
| `arguments` | No | Named positional arguments for `$name` substitution, as a space-separated string or YAML list. |
| `user-invocable` | No | Official model-only control. Set to `false` to hide from the `/` menu while preserving Claude invocation. Default: `true`. |
| `allowed-tools` | No | Tools Claude can use without asking permission during this skill |
| `disallowed-tools` | No | Tools removed while the skill is active; the restriction clears on the next user message. |
| `model` | No | Model override for skill execution (e.g., `sonnet` for lightweight skills) |
| `context` | No | Set to `fork` to run in a forked subagent context |
| `agent` | No | Which subagent type to use when `context: fork` is set |
| `background` | No | With `context: fork`, set `false` to wait for the result in the invoking turn. Default: `true`. |
| `hooks` | No | Hooks scoped to this skill's lifecycle (same format as settings.json hooks) |
| `effort` | No | Effort level when this skill is active: `low`, `medium`, `high`, `xhigh`, `max`. Availability depends on the effective model. Overrides the session effort level. |
| `shell` | No | Shell to use for `!command` syntax in skill body: `bash` (default) or `powershell` (requires `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`). (v2.1.84+) |
| `paths` | No | YAML list of glob patterns. Skill only loads when working with files matching these patterns. More flexible than `globs:` single-string syntax. (v2.1.84+) |
| `disable-model-invocation` | No | Official user-only control. Set to `true` to block Claude invocation and hide the skill description from Claude until the user invokes it. Default: `false`. |
| `metadata` | No | Free-form YAML map for repository/catalog metadata; Claude Code does not act on its contents. |
| `license` | No | Agent Skills license field; accepted but not acted on by Claude Code. |
| `compatibility` | No | The Agent Skills field is a string up to 500 chars. This repository also uses a structured local dependency map described below; local tooling, not Claude Code, acts on that extension. |

For claude.ai uploads, the Skills API, and `package_skill.py`, portable
frontmatter is limited to `name`, `description`, `license`, `compatibility`,
`metadata`, and `allowed-tools`. Claude Code-only fields such as
`argument-hint`, invocation controls, and `context` cause those upload paths to
fail rather than being ignored. Plugin skills running in Claude Code may use
the full table above.

## Compatibility Declarations

Skills that depend on external tools (MCP servers, CLI commands, other skills)
should declare dependencies in a `compatibility:` frontmatter block. This lets
the skill check availability at runtime and degrade gracefully instead of
failing with confusing errors.

```yaml
compatibility:
  requires:
    - mcp: linear
      tools: [get_issue, list_comments, save_issue]
    - cli: gh
  optional:
    - mcp: slack
      fallback: "Skip Slack notification steps"
    - skill: recall
      fallback: "Skip knowledge base lookup"
```

**Fields:**
- `requires:` — tool is required. If missing, stop and tell the user.
- `optional:` — tool enhances the skill but isn't essential. If missing, skip
  those steps silently (or with a brief note).
- `mcp:` — MCP server name (matches the key in settings/`.mcp.json`)
- `cli:` — CLI command (checked via `which <command>`)
- `skill:` — another skill this skill chains into
- `tools:` — specific MCP tools used (documentation, not enforcement)
- `fallback:` — what to do when the optional dep is missing

**Runtime check pattern** (add to skill's Step 0 or Prerequisites):
```bash
# Check MCP availability
which gh >/dev/null 2>&1 || echo "MISSING: gh CLI"
```
For MCP servers, attempt a lightweight tool call and handle the error.

**When to use:** Skills that call MCP tools (`mcp__linear__*`, `mcp__remote-tailscale__*`),
shell commands (`gh`, `aws`, `terraform`), or chain into other skills (`/recall`, `/ship`).

**When to skip:** Skills that only use built-in tools (Read, Write, Edit, Grep, Glob, Bash).

(Pattern source: n8n-io/n8n linear-issue skill — Context7 registry 2026-04-06)
