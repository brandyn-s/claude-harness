# Step 3 Routing — Architecture-Wide Destinations Reference

The Step 3 question is "where in our architecture would this technique
LIVE?" — not "does our skill cover this?". This reference holds:

1. The full routing table mapping technique-shape to destination-type
2. **Pre-populated candidate destinations per domain** (the v1.3
   feature that addresses the "requires architecture knowledge"
   weakness)
3. Examples of routing decisions from the 2026-05-17 validation run

## Routing table (technique shape → destination)

| Shape of the technique | Adoption destination | Step 4 classification |
|---|---|---|
| Belongs in an existing skill's workflow as a step or check | `skill/SKILL.md` | Additive / Structural |
| Belongs in an existing skill but as a deep reference | `skill/references/*.md` | Structural |
| **Belongs as a runtime enforcement that fires across all sessions** | `hooks/staged/<name>.spec.md` (then `/ship-hook`) | **Hook** |
| Belongs as an ambient rule applied across many skills | `rules/<name>.md` | **Domain Insight** |
| Belongs as a knowledge-base topic (durable explanatory content) | `knowledge-base/topics/<name>.md` | **Domain Insight** (prose) |
| **Has an executable atom (script template, harness, eval) alongside the methodology** | `knowledge-base/topics/<name>.md` + `evals/<name>/` OR `skill/references/<name>.py` | **Domain Insight (Harness)** |
| Belongs in worker-agent memory for a specific dispatch topic | `agent-memory/topics/<name>.md` | **Domain Insight** |
| Truly novel capability with no architectural home | (new skill) | Novel |
| No technique in the card — pure editorial polish | `skill/SKILL.md` | Additive |
| Already covered everywhere it would fit | (drop) | SKIP-candidate → Step 3.5 |

### When the technique routes to Hook (not Behavioral)

Both Hook and Behavioral are runtime concerns, but they have different
lifecycles and risk profiles. Use Hook when **all** of these hold:

- The technique enforces a constraint (block / fix / warn) on tool use
  regardless of which skill is active
- The natural matcher is a tool name pattern (Bash, Edit, Write,
  specific MCP), not a skill invocation
- Misbehavior would fire across ALL sessions, not just within one skill
- The fix is mechanical (string match + block/transform), not requiring
  judgment

| Axis | Behavioral | Hook |
|---|---|---|
| Trigger | Specific skill invoked | Tool call matched by name |
| Scope | One skill | All sessions |
| Test requirement | Run the skill, observe new behavior | Replay against historical transcript, measure block/allow rate |
| Deployment | Edit one SKILL.md | Modify `settings.json` + write hook script + cross-test |
| Risk profile | Misbehavior on next skill invocation | DoS across all sessions if matcher too broad |
| Rollback | Revert SKILL.md | Restore settings.json AND remove hook script |
| Approval gate | User-gated (high risk) | User-gated AFTER staged spec (highest risk) |

**Hook adoption procedure** (mirrors /distill T0-hook):

1. **Stage a spec, do NOT install inline.** Write
   `hooks/staged/<name>.spec.md` containing: hook event (PreToolUse /
   PostToolUse), matcher (tool name pattern), behavior description
   (block vs fix), enforcement logic pseudocode, concrete test case
   (known-bad input → expected block/fix).
2. **Replay against historical transcripts** before activation —
   target <10% block rate against the prior 30 days of tool calls.
   Higher block rate indicates the matcher is too broad and would DoS
   normal work.
3. **Report**: staged spec path, event, matcher, proposed behavior,
   historical block/allow stats.
4. **Do NOT write the hook script, register in settings.json, or test
   inline.** Hook installation happens via `/ship-hook` in a separate
   session — separates "decide what to enforce" from "modify live
   infrastructure."

The Hook bucket exists because **runtime enforcement is a different
deployment problem from workflow changes.** The /distill T0-hook
discipline (staged spec → replay test → manual install) applies to
community-skill-imported hooks too.

### When the technique routes to Domain Insight (Harness) — not just topic prose

Both Domain Insight (prose) and Domain Insight (Harness) capture a
substantive technique, but Harness applies when **the technique has an
executable atom** that should land as a runnable script alongside the
prose. Use Harness when:

- The technique includes an algorithm with concrete inputs/outputs
  that could be implemented as a function
- The community skill ships a script, code snippet, or harness template
- The methodology produces a measurable output (passes/fails, score,
  classification)
- Reuse value is higher with a runnable artifact than with prose alone

**Harness adoption procedure**:

1. Write the topic prose to `knowledge-base/topics/<name>.md` per the
   standard Domain Insight flow — captures the WHY, the WHEN-TO-USE,
   and the algorithm description.
2. **Also write the runnable artifact**:
   - **Skill-scoped** (used by one skill only): `~/.claude/skills/<skill>/references/<name>.py` or `<skill>/scripts/<name>.py`
   - **Cross-skill** (used by multiple skills or as a standalone eval):
     `~/.claude/evals/<methodology>/<name>.py`
   - **One-shot template** (user copies and adapts): include as a
     fenced code block in the topic file itself with `<!-- template -->`
     marker
3. Cross-reference: topic file links to the script path; script's
   docstring cites the topic file as the methodology source.
4. **Concrete diff for BOTH artifacts** (per Step 4 mandatory-diff rule)
   — the topic file AND the script land in the same PR.

**Examples** (from today's session):
- Three-stream validation methodology → topic prose AT
  `engineering-assessment-methodology.md` + `verify_skip.py` and
  `produce_card.py` in `skills/scout-skills/scripts/`
- Coverage-guided fuzzing → topic prose at `coverage-guided-fuzzing.md`
  + (future) cargo-fuzz template at `evals/fuzzing/cargo-fuzz-template.toml`
- Chaos engineering experiment loop → topic prose at
  `chaos-engineering-methodology.md` + (future) experiment template
  at `evals/chaos/experiment-template.sh`

**Why split prose from script**: prose is for understanding (read once,
load into context on /recall); scripts are for running (executable when
needed). Conflating them in a topic file makes the topic file long and
the script invisible to discovery. Splitting them lets each artifact
serve its purpose.

The "executable artifact lives separately" pattern is the same as our
existing `/scout-skills/scripts/verify_skip.py` — the methodology is
documented in SKILL.md + references, but the script lives in scripts/
where it can be invoked.

## Per-domain candidate destinations

When the technique-card domain matches one of these, the candidate
destinations are pre-identified. Use these as the `--ours` arguments
to `verify_skip.py`, and as routing-decision starting points.

### Security / threat modeling

- `skills/threat-model/SKILL.md` + `skills/threat-model/references/`
- `skills/differential-review/SKILL.md`
- `skills/agentic-actions-auditor/SKILL.md`
- `skills/vendor-breach/references/`
- `rules/security-critical-search-verification.md`
- `knowledge-base/topics/mcp-server-security-audit.md`
- `knowledge-base/topics/threat-intel-source-architecture.md`
- `knowledge-base/topics/supply-chain-security.md`
- `knowledge-base/topics/cellular-infrastructure-threats.md`
- `knowledge-base/topics/dns-security-hardening.md`
- `agent-memory/topics/security.md`

### Testing / TDD / test methodology

- `skills/test-driven-development/SKILL.md` + `references/`
- `rules/diagnose-before-fix.md` (root-cause testing)
- `rules/eval-shipping-discipline.md`
- `rules/verify-effectiveness.md`
- `knowledge-base/topics/coverage-guided-fuzzing.md`
- `agent-memory/topics/testing.md`

### Debugging / root cause analysis

- `skills/systematic-debugging/SKILL.md` + `references/`
- `skills/investigate/SKILL.md`
- `rules/diagnose-before-fix.md`
- `rules/verify-before-assuming.md`
- `rules/verify-instrument-before-fix.md`
- `knowledge-base/topics/engineering-assessment-methodology.md`

### Observability / monitoring

- `knowledge-base/topics/claude-telemetry-coverage.md`
- `agent-memory/topics/observability.md` (if exists)
- *Note*: Example has weaker coverage here — new techniques likely
  warrant new topic files

### Code review / PR review

- `skills/differential-review/SKILL.md`
- `skills/fp-check/SKILL.md`
- `rules/symmetric-evidentiary-burden.md`
- `skills/_shared/output-grounding.md`
- `agent-memory/topics/code-review.md` (if exists)

### Incident response / postmortem

- `rules/diagnose-before-fix.md`
- `knowledge-base/topics/engineering-assessment-methodology.md`
- `knowledge-base/topics/retrospective-analysis.md`
- `knowledge-base/topics/session-friction-patterns.md`

### SRE / resilience / chaos

- `knowledge-base/topics/chaos-engineering-methodology.md`
- `knowledge-base/topics/aws-deployment-patterns.md`
- `knowledge-base/topics/mcp-fleet-governance.md`

### Rust development

- `rules/platform-constraints.md` (Rust Conventions section)
- `knowledge-base/topics/absorb-rust-developers.md`
- `knowledge-base/topics/coverage-guided-fuzzing.md`

### Documentation / technical writing

- `skills/docgen/SKILL.md`
- `rules/skill-standards.md`
- `knowledge-base/topics/digital-garden-content-model.md`

### Git / CI / workflow

- `rules/git-hygiene.md`
- `rules/worktree-by-default.md`
- `knowledge-base/topics/git-workflow-guardrails.md`
- `knowledge-base/topics/github-ci-patterns.md`
- `knowledge-base/topics/github-actions-discipline.md`

### Skill design / architecture meta

- `rules/skill-standards.md`
- `rules/rule-authoring.md`
- `rules/check-before-change.md`
- `knowledge-base/topics/skill-design-patterns.md`
- `knowledge-base/topics/skill-red-teaming.md`
- `knowledge-base/topics/skill-format-effectiveness.md`
- `knowledge-base/topics/community-skill-mining.md`

### LLM / agent architecture / prompt design

- `skills/api-guardrails/SKILL.md`
- `skills/_shared/output-grounding.md`
- `knowledge-base/topics/llm-creativity-ceiling.md`
- `knowledge-base/topics/knowledge-asymmetric-collaboration.md`
- `knowledge-base/topics/opus-4-7-creative-tradeoffs.md`
- `knowledge-base/topics/adversarial-validation-research.md`

### Memory / knowledge management

- `skills/capture/SKILL.md` + `references/`
- `skills/distill/SKILL.md` + `references/`
- `knowledge-base/topics/knowledge-capture-system.md`
- `knowledge-base/topics/digital-garden-content-model.md`
- `knowledge-base/topics/memory-search-optimization.md`

## Concrete routing decisions from 2026-05-17 fresh validation

How the 6 GPT-card-validated candidates were routed:

| Technique | Domain | Destination chosen |
|---|---|---|
| trailofbits harness-writing methodology | Fuzz testing harness design | `knowledge-base/topics/coverage-guided-fuzzing.md` (new file) |
| trailofbits cargo-fuzz workflow | Rust fuzz testing | same destination as above |
| trailofbits fuzzing-dictionary construction | Coverage-guided fuzzing | same destination as above |
| jeffallan chaos-engineer methodology | SRE resilience | `knowledge-base/topics/chaos-engineering-methodology.md` (new file) |
| davila7 supply-chain-guard (IOC database) | Software supply-chain | `skills/vendor-breach/references/ioc-multi-ecosystem-audit.md` (extends existing skill) |
| phylax mapping-invariants (smart-contract) | Blockchain security | **drop — domain mismatch** (Example doesn't write smart contracts) |

Substantive technique recognition rate: 6 of 6. Non-SKILL.md routing
rate: 5 of 5 substantive (the 6th dropped). Mandatory 3rd-party card
production (Step 2.7 v1.3) was used; cards agreed with reader cards on
substantive-vs-editorial classification.

## Updating this reference

When a new topic file lands in `knowledge-base/topics/` or a new rule
lands in `rules/`, add it to the appropriate domain bucket above. The
per-domain candidate lists should track actual architecture state to
preserve their pre-populated-hint value.

This is the structural fix for the "requires architecture knowledge"
weakness: a fresh session without /scout-skills priming can read this
reference and immediately see candidate destinations per the candidate's
domain — not just abstract destination types.
