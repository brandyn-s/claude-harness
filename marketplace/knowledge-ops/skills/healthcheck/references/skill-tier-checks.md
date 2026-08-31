# Check 3 Tier Definitions — what `_check_skills.py` enforces

The helper script is the single source of truth for the validation
iteration; this file documents the checks it runs, organized in three
tiers by source authority. Do NOT re-implement the iteration in ad-hoc
Python — INCIDENT 2026-05-29 surfaced two systematic divergences in
inline impls (missed underscore-dir exclusion + over-broad XML pattern
matching bare placeholders).

The helper iterates `${CLAUDE_PLUGIN_ROOT}/skills/*/SKILL.md`, **skipping directories
whose name starts with `_`** (convention for shared helper directories
like `_shared/` that hold cross-skill references rather than a single
skill).

## Tier A — Anthropic-authoritative (FAIL on violation)

These derive from Anthropic's official agent-skills best-practices docs
(verified 2026-05-12 at platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices):

1. File exists and is non-empty
2. YAML frontmatter parses (between `---` delimiters)
3. `name:` field present
4. `name:` max 64 characters
5. `name:` matches regex `^[a-z0-9-]+$` (lowercase letters, numbers, hyphens only)
6. `name:` does NOT contain reserved words `anthropic` or `claude` as substrings.
   **Documented exception (user-approved 2026-05-12)**: `gather-claude` — the
   skill's purpose is gathering upstream Anthropic / Claude Code intel; the
   name is semantically load-bearing and renaming would touch ~54 files.
   Add to `LOCAL_RESERVED_EXCEPTIONS = {"gather-claude"}` in the Tier-A
   checker. Any NEW skill name must comply with this rule.
7. `name:` matches the folder name exactly
8. `description:` field present, non-empty, max 1024 characters
9. No matched-pair XML tags (e.g. `<tag>…</tag>`) in `name` or `description`
   fields. The helper uses the regex `<([a-z][a-z0-9-]*)\b[^>]*>.*?</\1>` —
   matching opening + closing tag pairs explicitly. **Bare placeholders**
   like `<plan>`, `<slug>`, `<github-username>` are legitimate prose syntax
   and DO NOT match this pattern. Earlier ad-hoc impls flagged them as XML
   and produced 3 false-positive Tier-A findings on 2026-05-29.
10. `## Examples` section exists (Anthropic's canonical SKILL.md template
    shows `## Instructions` and `## Examples` — grep for `#+ Example`)

(SKILL.md body length is NOT a Tier-A check — it is a Tier-C SOFT advisory:
≤510 lines, WARN-only, never a FAIL. Reclassified 2026-06-28 per
`rules/skill-standards.md` — "500 lines is a SOFT guideline, NOT a hard cap …
do NOT tighten it to a hard 500." The helper emits over-length via tier B/C,
matching `validate-skills.py` C1. The real constraint is the Level-2 token
budget, for which the line count is only a proxy.)

## Tier B — Anthropic-recommended (WARN on violation)

12. `description:` written in third person, includes what-it-does + when-to-use
    triggers (Anthropic best-practices recommendation, but harder to validate
    mechanically — WARN if grep finds first-person patterns like "I will",
    "let me", "I'll")

## Tier C — Local conventions (WARN; clearly marked non-Anthropic)

These are NOT in Anthropic's published guidance. Surfaced as warnings so the
user can decide whether to apply them. Drop or revise if Anthropic guidance
ever conflicts.

13. **[LOCAL]** `## Success Criteria` section exists. Not in Anthropic's
    canonical SKILL.md template. We find it useful as a verification anchor;
    apply selectively.
14. **[LOCAL]** If `context: fork` is set, skill body does NOT reference
    `Agent` tool (our custom subagent isolation pattern).
15. **[LOCAL — empirical]** If `allowed-tools` is present and non-empty,
    `AskUserQuestion` should appear. Rationale: 2026-04-19 v5 rule-format
    testing found declaring `AskUserQuestion` in frontmatter raised triage
    skill compliance from 88.9% → 100%. Skills that legitimately never branch
    on user input (pure-pipeline) are exempted via the
    `PURE_PIPELINE_SKILLS` set in `_check_skills.py` (added 2026-06-12 —
    status readers, query pipelines, report-only sweeps); skills outside
    that set remain warned, which keeps the residue actionable.
Checks 16 (`metadata.author`/`metadata.version`) and 17 (`skills-ref
validate` exit code) were documented here as planned Tier-C additions
but were never implemented in `_check_skills.py` — no `metadata` or
`skills-ref` logic exists in the helper, so a skill missing those
fields passes clean. Removed from this doc rather than shipped as a
false coverage claim; re-add only alongside a matching implementation
in `_check_skills.py`.
