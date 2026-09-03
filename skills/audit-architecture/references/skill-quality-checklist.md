# Skill Quality Evaluation Checklist

Evaluate each skill discovered in `~/.claude/skills/*/SKILL.md` against these criteria. Score as PASS / FAIL / PARTIAL.

## Structure Checks

| # | Check | How to evaluate | Pass criteria |
|---|---|---|---|
| S1 | Folder naming | Folder name is kebab-case | No spaces, underscores, or capitals |
| S2 | SKILL.md exists | Exact file name | Case-sensitive match |
| S3 | Frontmatter format | Has `---` delimiters, `name:`, `description:` | Both required fields present |
| S4 | Name matches folder | `name:` field == folder name | Exact match |
| S5 | No XML in frontmatter | Scan for `<` or `>` between `---` delimiters | None found |
| S6 | No README.md | Check for README.md in skill folder | Not present |
| S7 | Description length | Character count of `description:` value | Under 1024 characters |

## Content Quality Checks

| # | Check | How to evaluate | Pass criteria |
|---|---|---|---|
| C1 | Trigger phrases | Description includes "Use when..." with specific phrases | At least 2 specific trigger phrases |
| C2 | Negative triggers | Description includes "Do NOT use for..." | At least 1 negative trigger with redirect |
| C3 | Examples section | `## Examples` heading exists with concrete examples | At least 2 examples with User says / Actions / Result |
| C4 | Success Criteria | `## Success Criteria` heading exists | At least 3 measurable criteria |
| C5 | Error handling | Instructions address failure modes | At least 1 error/failure scenario documented |
| C6 | Progressive disclosure | Large reference tables in `references/` not inline | SKILL.md body under ~5,000 words (the Level-2 token-budget proxy — this is what fails C6); a >510-line body is SOFT guidance only (advisory, never FAIL — `skill-standards.md`: "do NOT tighten to a hard 500"); or no large tables to extract |
| C7 | Instructions clarity | Steps are specific and actionable | No vague instructions like "validate properly" |

## Composability Checks

| # | Check | How to evaluate | Pass criteria |
|---|---|---|---|
| X1 | No exclusive assumption | Skill doesn't assume it's the only one active | No "disable other skills" language |
| X2 | Cross-references | Negative triggers redirect to specific alternative skills | Named skill in each "Do NOT" clause |

## Scoring

Per skill: count PASS / FAIL / PARTIAL across all checks.

| Score | Rating | Action |
|---|---|---|
| 15-16 PASS | Excellent | No action needed |
| 12-14 PASS | Good | Note gaps for next iteration |
| 8-11 PASS | Needs Work | Flag specific failures for remediation |
| <8 PASS | Poor | Recommend rewrite using skill-development-patterns.md |
