# Report Format

## Step 5.6: SCOUT-SKILLS SUMMARY

```
SCOUT-SKILLS SUMMARY

Registry: {N} categories searched, {M} skills found
Deep-dive: {K} repos, {J} SKILL.md files read
Technique cards produced: {C} total
  Substantive (named operationalizable atom): {C1}
  Editorial-only: {C2}

Patterns found: {P} total
  Additive: {A} → SKILL.md prose
  Structural: {Sx} → references/ or frontmatter
  Domain Insight (prose): {Dp} → {Dp-rule} rules, {Dp-topic} topics, {Dp-mem} memory entries
  Domain Insight (Harness): {Dh} → topic prose + {Dh-script} scripts in skill/scripts/, skill/references/, or evals/
  Hook: {H} staged at hooks/staged/ for /ship-hook review (none installed inline)
  Behavioral: {B} flagged for user ({B2} adopted, {B3} deferred)
  Novel: {N} proposed as new skill
Skipped: {X} (covered) | {Y} (mechanical: not-a-pattern / domain mismatch / generic rehash)

Adoption destinations (counts by file):
  - {file1}: {n1} patterns from {repoX}
  - {file2}: {n2} patterns from {repoY}

Sources:
  - {repo1}: {pattern1} → {destination1}, {pattern2} → {destination2}
  - {repo2}: {pattern3} → {destination3}
```

## Step 5.5: Session Output Audit template

Surface when **100% of this session's adoptions are SKILL.md AND ≥3
adoptions total**. Single-finding sessions are too small to indicate a
pattern. The audit does not block — it forces explicit confirmation
that routing was intentional.

```
SESSION OUTPUT AUDIT — possible bias recurrence detected

This run produced N adoptions, all routed to SKILL.md:
  - {pattern1} → {skill}/SKILL.md
  - {pattern2} → {skill}/SKILL.md
  ...

The /scout-skills v1.2 overhaul (PR #903) added Domain Insight routing
specifically to land substantive techniques in rules/topics/memory.
A session with 0 non-SKILL.md adoptions may indicate:

  (a) Genuine: all surfaced patterns were Additive editorial (no
      substantive techniques in this category sweep). Validate by
      checking technique cards — if all are EDITORIAL-ONLY, this is
      the correct outcome.

  (b) Bias recurrence: technique cards were substantive but routing
      defaulted to SKILL.md. Re-read references/routing-destinations.md
      and re-classify.

Confirm intentional before proceeding to Step 6 (Linear breadcrumb).
```

**When the audit passes** (0 adoptions; ≥1 non-SKILL.md adoption; or
audit explicitly resolved to "genuinely all editorial"): proceed to
Step 5.6 and Step 6.

This guard catches the failure mode that drove the v1.2 overhaul:
silent reversion to editorial polish.
