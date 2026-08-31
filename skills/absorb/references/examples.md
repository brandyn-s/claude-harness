# Absorb — Worked Examples

Six walkthroughs showing how the five phases play out on different target types,
plus the Dustin-run calibration notes behind three of the Constraints.

## Calibration notes — Dustin test run (2026-04-04)

The first three Constraints in SKILL.md were calibrated by this run's misses:

- **Read actual code, not just structure** — Dustin test run 2026-04-04: directory
  structure was examined but no source files were read — missed dependency choices,
  error handling patterns, and test approach.
- **Check both review endpoints** — Dustin test run: only checked the `pulls/N/reviews`
  endpoint, missed potential inline comments on `pulls/N/comments`.
- **Persist profile AND rejections** — Dustin test run: neither the profile nor the
  rejection list was persisted, breaking deduplication for the next run.

**Example 1: Studying a prolific open source maintainer**
```
/absorb antirez
```
Phase 1 surfaces 50+ repos, Redis as primary project, blog at antirez.com. Phase 2 digs
into Redis commit messages (famously detailed, include benchmarks), PR review style (minimal,
trusts contributors), source architecture (single-file-heavy, C with minimal abstraction),
Cargo/Makefile dependency choices. Phase 3 extracts patterns: "commit messages as design
documents," "flat module structure over deep nesting," "performance numbers in commit
messages," "zero external dependencies in core." Phase 4 compares against git-hygiene.md —
the commit-as-design-doc pattern reinforces the WHY requirement. The flat module pattern
doesn't apply (different language, different domain). Performance numbers in commits is a
new pattern worth adopting for hook/skill changes.

**Example 2: Insufficient signal**
```
/absorb some-private-dev
```
Phase 1: 4 public repos, all forks with no original commits, last push 2 years ago.
Enterprise fallback finds 0 PRs across Example orgs. Signal assessment gate fires:
"Insufficient signal for some-private-dev. 0 non-fork public repos (of 4 total), 0
enterprise PRs. This target may use a different GitHub username." Skill stops.

**Example 3: Target contradicts existing rules**
```
/absorb mitchellh
```
Phase 3 finds: Mitchell Hashimoto commits directly to main on personal projects, uses
long-lived feature branches on team projects, writes Zig with zero dependencies. Phase 4:
direct-to-main contradicts git-hygiene.md universal rule #1. But the target only does this
on solo projects — the rule enforces feature-branch-plus-PR universally, with no standing per-repo exception. So the direct-to-main pattern would be rejected by policy even on solo projects. No gap. Zero-dependency
philosophy contradicts your pragmatic lodash/boto3 usage — but your context (Python
scripting, not systems programming) makes the pattern inapplicable. Rejected at gate 3:
no friction from current dependency approach.

**Example 4: Internal teammate (enterprise path, zero recommendations)**
```
/absorb dustin-w-example
```
Phase 1: 0 public repos. Enterprise fallback finds 25 PRs across example-org.
Phase 2 examines commits, PRs, reviews across Example-CTI and security-platform. Phase 3
extracts 8 patterns (large batched PRs, same-day merge, WHAT-focused commits, approve-only
reviews, etc.). Phase 4: all 8 rejected — same-team context means shared conventions.
Divergence analysis reveals: Dustin ships larger PRs (53 files) vs. your 1-file-per-behavior
rule; Dustin uses no PR descriptions vs. your `## Summary / ## Test plan` template. These
are contextual differences (solo dev vs. architecture operator), not gaps. Profile and
rejections persisted to `absorb-dustin-w-example.md`.

**Example 5: Budget wasted on low-signal streams (negative example)**
```
/absorb some-cc-config-author
```
Phase 1 surfaces 84 repos, but only 1 is a CC config repo — the rest are tutorial forks and
class assignments. Phase 2 spends 15 API calls on Tier 2 workflow analysis (commits, PRs,
reviews) across the tutorial repos, extracting patterns like "single-commit PRs" and "no
tests." These are artifacts of tutorial code, not engineering practice. Only 5 API calls
remain for Tier 1 code reading on the one repo that matters. **Lesson:** After Phase 1,
identify the 1-2 repos that represent the target's best work. Do not spread the budget
across repos that are clearly not representative (forks, tutorials, archived experiments).
Star count, recent activity, and original (non-fork) status are better signals than repo
count.

**Example 6: Tier 2 automation pattern survives gates + cross-validation (positive example)**
```
/absorb cc-config-dev
```
Phase 1 identifies a CC config author (primary repo is a `.claude/` configuration). Budget
adapts: Tier 1 30%, Tier 2 40%, Tier 3 30%. Phase 2 reads their `SKILL.md` files and
discovers a skill eval harness: CSV test cases with deterministic graders that validate
skill output against expected patterns. Phase 3 synthesizes: "CSV-driven skill eval
framework `[universal]`." Phase 4 maps to `Skill design & triggers` row — reads your
actual skills directory. Finds: 50+ skills, zero automated regression tests. Gate 1: not
covered. Gate 2: no current solution. Gate 3: no documented incident, but cross-developer
aggregation finds the same pattern in 2 other independent profiles `[cross-validated: 3]`.
The convergent evidence compensates. Gate 4: adoption cost is a new skill + CSV files per
existing skill, value is catching skill regressions before they ship. Recommendation:
build a skill eval framework. Revert trigger: "Revert if eval maintenance cost exceeds
2 hours/month within 3 months."
