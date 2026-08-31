# Eval Harness Roadmap

Current state (reconciled 2026-08-08):
- **Tier 1 (deployed):** Deterministic structural assertions
  (`scripts/run-skill-evals.py`). 27/90 skills, 121 assertions, runs in
  <1s on the full corpus. No LLM API calls, no network. CI-gated.
- **Tier 2 (implemented, opt-in):** LLM-driven sandboxed invocation per
  skill through `scripts/run-skill-llm-evals.py`. The requested model resolves
  from an explicit argument, `CLAUDE_MODEL`, or current repository settings;
  result rows preserve requested/effective runtime receipts.
- **Tier 3 (frozen pre-registration, not current policy):** The unexecuted
  Opus 4.7 activation-rate study remains a dated experimental design below.
  Reuse its method only through a separately pre-registered current-model study.

## Tier 2 — LLM-driven sandboxed eval (M2)

**Goal**: catch behavior regressions that deterministic structural
assertions can't — e.g., "the skill fires when the user says X" or
"the output includes the documented sections."

**Approach**: borrow Scott Spence's sandboxed-eval pattern
([source](https://scottspence.com/posts/measuring-claude-code-skill-activation-with-sandboxed-evals)):
spawn a sandboxed Claude Code instance via `claude -p` with a controlled
prompt, parse the JSONL output, compare against expected artifacts.

**Per-skill YAML schema** (extension of the existing `tests/<skill>/*.yaml`):

```yaml
skill: <name>
name: <eval-name>
trigger: <natural-language prompt to fire the skill>

llm_eval:
  invocation:
    prompt: "<user prompt that should activate this skill>"
    expected_skill_fires: true        # or false (negative test)
    timeout_s: 120
    # model is optional; omit it to use the current repository request.
    # Pin only for a dated, explicitly labelled historical comparison.
  expected_artifacts:
    # Files the skill should create / modify
    creates: ["~/.claude/captures/*.md"]
    modifies: ["claude-config/skills/*/SKILL.md"]    # explicit allowlist
  expected_output_contains:
    # Substrings the response should include (case-insensitive)
    - "extracted N entries"
    - "pushed to knowledge base"
  forbidden_output:
    # Substrings the response must NOT include
    - "I cannot help with that"     # refusal heuristic
    - "as an AI language model"     # generic-LLM fallback
  side_effect_assertions:
    # Programmatic checks against the sandboxed filesystem after the run
    - file_exists: ~/.claude/agent-memory/topics/expected-topic.md
    - file_modified_since_baseline: claude-config/CHANGELOG.md
```

**Cost estimate**: Spence reports $0.022/invocation. 27 skills × 2 evals each
× $0.022 = ~$1.20/run. CI cost: trivial.

**Risks**:
- Non-determinism — LLM activation is probabilistic. Mitigation: run each
  eval N times (3-5) and accept ≥80% success rate.
- Model-version drift — activation changes across model generations.
  Mitigation: record requested/effective models in every result, use the
  current repository default for operational evaluation, and pin only dated
  baselines that will not be misread as current policy.
- Refusal noise — safeguard-capable models may refuse legitimate security
  skills. Preserve refusal as a typed outcome; do not fold it into activation
  failure or weaken the request to bypass it.

**Implementation steps**:
1. Maintain `scripts/run-skill-llm-evals.py` — sandboxed `claude -p`
   invocation + JSONL parsing + runtime receipt.
2. Pilot on 3 skills with low refusal risk: `capture`, `recall`, `refine`.
3. Add per-skill `llm_eval:` blocks to existing YAML.
4. Run nightly (not per-PR) in CI to control cost; expose `--full` mode
   for on-demand.
5. Aggregate pass rates over time; alert if any skill drops below 80%.

## Tier 3 — Historical Opus 4.7 activation-rate design (L3)

> **HISTORICAL PRE-REGISTRATION:** The exact model ID and hypotheses below are
> preserved as a dated design artifact. They are not the active model default
> and do not qualify Fable 5, Opus 5, Sonnet 5, or a later Claude Code release.

**Goal**: Replicate Seleznov's 650-trial activation study on Opus 4.7.
Most recent published study (Bara/Seleznov 2026) ran on Sonnet 4.5;
4.7's "more literal instruction following" should amplify directive
language even more, but no controlled measurement exists.

**Design**:

- **Factorial design**: 3 description styles × 4 trigger types × 5 skills ×
  3 prompt-prefix conditions = 180 cells. Each cell = 4 trials = 720
  total invocations.
- **Description styles**: passive ("Use when X"), directive ("ALWAYS
  invoke when X"), directive-with-do-NOT ("ALWAYS invoke when X. Do
  NOT do Y directly.").
- **Trigger types**: exact-phrase match, near-phrase match,
  semantic-equivalent (no overlap), unrelated.
- **Prompt-prefix conditions**: no prefix, "Use available skills",
  hook-injected skill-recommendation.
- **Skills**: 5 pilot skills with varied content (capture, recall,
  refine, ship, audit-skill).
- **Metric**: did the skill fire? (per the JSONL transcript).

**Cost**: 720 × $0.022 = ~$16. One-time.

**Hypothesis** (pre-registered):
- H1: directive + do-NOT style has higher activation than passive on 4.7
  (replicate Seleznov's finding).
- H2: the effect size on 4.7 is *larger* than on Sonnet 4.5 (because of
  literal-instruction-following).
- H3: hook-injected recommendations approach 100% activation across all
  styles (replicate Seleznov's hook condition).

**Publishability**: research agent confirmed this is unpublished work.
Even an n=720 single-author study would close a real literature gap.

**Implementation steps**:
1. Author 5 skill variants per style × 5 skills = 25 SKILL.md files
   (without permanently changing the corpus — use a separate test
   directory).
2. Author 4 trigger prompts per type × 4 types = 16 prompts.
3. Build the 3×4×5×3=180 factorial cell matrix.
4. Run 4 trials per cell via `claude -p` in a sandboxed env.
5. Parse activation outcomes from JSONL transcripts.
6. Compute Cochran-Mantel-Haenszel odds ratios + 95% CIs.
7. Report with effect sizes per style and per condition.

## Why both are deferred

- **Engineering cost**: ~1 day each.
- **API access**: Tier 2 requires the Claude Code CLI in a sandbox
  context, plus Anthropic API credits. Not feasible in the current
  session sandbox.
- **Risk of premature optimization**: Tier 1 (deterministic) catches
  the bugs we know how to catch. Tier 2 catches behavior regressions
  but at the cost of test flakiness. The cost-benefit is favorable
  only once Tier 1's gaps are quantified.

When to revisit:
- A skill ships and *immediately* breaks despite Tier 1 passing →
  build Tier 2 for that skill first.
- Onboarding a new Opus version (4.8 or Mythos) → re-run Tier 3 to
  verify activation behavior didn't regress.
- Publishing the calibration finding ([anthropics/skills](https://github.com/anthropics/skills)
  audit) → including a Tier 3 study would strengthen the report.
