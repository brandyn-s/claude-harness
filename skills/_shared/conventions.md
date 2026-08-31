# Skill Authoring Conventions

This file is the canonical reference for how skills in this repo are
structured. New skills should follow these conventions; existing skills
get audited against them via `scripts/validate-skills.py` and
`scripts/run-skill-evals.py`.

## File layout

```
skills/<skill-name>/
├── SKILL.md                            # required: frontmatter + body
├── manifest.yaml                       # optional: requires_tools / compatibility
├── references/                         # optional: deeper content
│   ├── <topic>.md                      # cited by SKILL.md
│   ├── _<topic>.md                     # internal maintainer notes (NOT cited)
│   └── _runbook-deferred.md            # deferred-work tracking (NOT cited)
├── scripts/                            # optional: bundled helpers
│   ├── <name>.py
│   └── <name>.sh
├── fixtures/                           # optional: test fixtures
│   ├── README.md                       # documents the fixtures
│   └── <fixture>.{json,yaml,...}
└── examples/                           # optional: worked invocations
    └── <name>.md
```

## Naming

| File / dir | Convention | Example |
|---|---|---|
| Skill directory | lowercase + hyphens + digits | `mcp-forge-build` |
| `references/*.md` | lowercase-kebab-case | `failure-paths.md` |
| Internal maintainer notes (NOT cited from SKILL.md) | `_*.md` prefix | `_runbook-deferred.md` |
| Test fixtures | `<NN>-<name>.<ext>` | `01-deterministic.yaml` |
| Bundled scripts | snake_case | `parse_plan.py` |

**Underscore-prefix convention (`_*.md`)**: indicates the file is NOT part
of the skill's documented behavior — it's an internal maintainer artifact
(deferred-work tracking, improvement runbooks, design notes). The validator
ignores these files; they're maintainer-facing only.

**Reserved names**: skill `name:` cannot contain `anthropic` or `claude`
(Anthropic spec rule). Documented exception in this repo: `gather-claude`
(load-bearing semantic — "gather Claude-related intel"). Whitelisted in
`scripts/validate-skills.py:A6`.

## Frontmatter

Required:
- `name:` (≤64 chars, lowercase-kebab, gerund preferred)
- `description:` (≤1024 chars, third-person, no XML tags; include
  trigger phrases AND a "Do NOT use for X" clause)

Recommended:
- `argument-hint:` with a concrete example (>15 chars)
- `effort:` one of `low` / `medium` / `high` / `xhigh` / `max` (Example convention,
  not in Anthropic spec)
- `allowed-tools:` (Claude Code extension; informational only, not gated)
- `verified_on: YYYY-MM-DD` (last hand-verified date; warns past 90 days)

Optional:
- `metadata:` (`author`, `version`)
- `compatibility:` (`requires:` list — MCP servers, sibling skills)
- `disable-model-invocation: true` (user-invoke-only skills)

## Body structure

Conventions vary by skill size:

| Body lines | Required structure |
|---|---|
| <60 | At least 1 section heading OR 1 stepped item. Body itself is the example. |
| 60–150 | ≥2 section headings or ≥2 stepped items. Concrete example block. |
| 150–500 | ≥3 sections + ≥3 stepped items. Examples section. References for detail. |
| >500 | Same as above + progressive disclosure via `references/`. |

Stepped-item patterns recognized by the validator: `1.` at line start,
`## Step N`, `## Phase N`, `## ARTICLE V` (roman numerals), `### N.`
sub-headers.

## References

- One level deep only (`references/X.md`, not `references/sub/X.md`).
- Forward-slash paths (Windows backslashes break on POSIX runners).
- Each cited reference must resolve to a file that exists.
- Cross-skill cites use the form `<other-skill>/references/X.md` (relative
  to `skills/`) or `~/.claude/skills/<other-skill>/references/X.md` (deploy
  path, resolves at runtime from claude-knowledge-base + claude-config
  composition).

## Tokens (runtime-aware)

The Anthropic-published 500-line cap is approximate. The actual context
budget is model- and content-dependent. The validator's local estimate is an
advisory structural gate; current qualification should use Anthropic's token
counting endpoint for the exact target model. The validator enforces:

- **6000 tokens**: soft warning (`C1b` warns, doesn't fail)
- **8000 tokens**: hard cap (`C1b` fails; skill drops below S)

Heavy skills should use `references/` for procedural detail beyond the
core flow. `scripts/token-audit.py` measures any skill against this cap.

## Evaluations (Anthropic-recommended; gated by `D1_evaluations`)

Anthropic's best-practices doc: *"Create evaluations BEFORE writing
extensive documentation."* Skills must have at least one of:

1. **Documentation markers**: ≥N (size-aware: 1 / 2 / 3) `## Example N`,
   `**Eval N:**`, `> User: /skill-name`, or invocation lines.
2. **Runnable deterministic evals**: a `tests/<skill>/*.yaml` file with a
   `deterministic:` block. The harness (`scripts/run-skill-evals.py`)
   exercises these on every CI run. Strictly stronger signal than
   documentation markers — fast-path the D1 check.

The 5 pilot skills with runnable evals (as of 2026-05-27): `healthcheck`,
`audit-skill`, `insecure-defaults`, `recall`, `ship`. Expand coverage as
new skills mature.

## API compatibility

The `E1_no_deprecated_api` check fails skill bodies that invoke incompatible
API knobs outside of per-model documentation context. Consult the active
model overlay and current API documentation; do not generalize an old model's
parameter matrix into a universal rule.

- `thinking_budget` / `thinking: {type: "enabled", budget_tokens: N}` → 400
  on 4.7. Use `thinking: {type: "adaptive"}` + `output_config.effort` instead.
- `temperature` / `top_p` / `top_k` set to any non-default value → 400 on 4.7.
  Omit entirely; use `effort` + prompting.

`api-guardrails` is the documented exemption — its purpose IS to teach the
per-model rules.

See `skills/_shared/model-runtime-policy.md` for the active contract. The old
`opus-4-7-policy.md` is a frozen historical baseline.

## Cybersecurity safeguards

Skills that touch security-context work use the model-independent refusal and
authorization contract in
`~/.claude/skills/_shared/model-runtime-policy.md`. A refusal is a typed
runtime outcome; it is never hidden, bypassed, or silently scored as success.

## Validation

Every skill change should be checked against:

```bash
python3 scripts/validate-skills.py                # rubric (14-check)
python3 scripts/run-skill-evals.py                # deterministic harness
python3 scripts/token-audit.py --over 5000        # token budget
python3 scripts/validate-skills.py --triggers     # corpus trigger conflicts
```

CI runs all four on every PR. See `.github/workflows/validate.yml`.
