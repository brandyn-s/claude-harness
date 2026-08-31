"""Healthcheck Check 3 helper: skill frontmatter validation in three tiers.

The spec lives in `skills/healthcheck/SKILL.md` Check 3. Every prior
implementation was inline ad-hoc Python — INCIDENT 2026-05-29 surfaced
that those ad-hoc impls diverged from the spec in two systematic ways:

  1. Forgetting the underscore-prefixed-directory convention. `_shared/`
     is not a skill — it holds cross-skill references. Implementations
     that glob `skills/*/SKILL.md` blindly flag `_shared/` as missing.

  2. Treating the spec's "no XML tags in description" check as "no
     `<word>` substring", which false-flags every placeholder like
     `<plan>`, `<slug>`, `<user>`, `<github-username>`. The spec
     explicitly says "narrow scope to opening/closing tag patterns" —
     i.e., matched pairs like `<tag>...</tag>`, not bare placeholders.

This helper codifies the spec, fixes both bugs by construction, and
gives Check 3 a testable single source of truth. Future invocations
should run this script rather than re-implement the logic inline.

Read-only. Exit 0 = all pass, 1 = WARN-only, 2 = at least one Tier-A FAIL.

Usage:
  python _check_skills.py
"""
import os
import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    print("Skills: SKIP — pyyaml not installed", file=sys.stderr)
    sys.exit(2)

sys.stdout.reconfigure(encoding="utf-8")

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
SKILLS_DIR = CLAUDE_DIR / "skills"

RESERVED_WORDS = {"anthropic", "claude"}

# Reserved-word exceptions. CI's scripts/validate-skills.py `EXEMPT_NAMES` is
# the source of truth — a hand-copied second list drifted (2026-08-22:
# gather-claude-endpoints passed CI for weeks while this checker FAILed it).
# AST-parse the literal from the validator; the baked-in set is only the
# fallback when the validator is absent/unparseable.
_FALLBACK_RESERVED_EXCEPTIONS = {"gather-claude", "gather-claude-endpoints"}


def _ci_exempt_names() -> set[str]:
    import ast
    validator = CLAUDE_DIR / "scripts" / "validate-skills.py"
    try:
        tree = ast.parse(validator.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "EXEMPT_NAMES":
                        val = ast.literal_eval(node.value)
                        if isinstance(val, (set, frozenset, list, tuple)) and val:
                            return set(val)
    except (OSError, SyntaxError, ValueError):
        pass
    return _FALLBACK_RESERVED_EXCEPTIONS


LOCAL_RESERVED_EXCEPTIONS = _ci_exempt_names()

# Tier-C check 15 exemptions: pure-pipeline skills that never branch on
# user input (status readers, query pipelines, report-only sweeps). The
# check's own spec says these "can be left alone" — without this set they
# re-warn on every healthcheck run forever (25 warns/run before 2026-06-12).
# Skills NOT listed here that carry allowed-tools without AskUserQuestion
# remain warned — that residue is the actionable signal.
PURE_PIPELINE_SKILLS = {
    "cc-monitor",                # read-routing only
    "code-explore",              # query pipeline
    "codebase-memory-exploring", # query pipeline
    "codebase-memory-quality",   # query pipeline
    "codebase-memory-tracing",   # query pipeline
    "harness-prune",             # report-only by design (no in-place edits)
    "pull-repos",                # mechanical fetch+rebase sweep
    "supergoal-pause",           # state-flip utility
    "supergoal-resume",          # state-flip utility
    "superplan-loop",            # read-only cadence monitor
    "superplan-status",          # read-only status report
    "work",                      # worktree create + emit cd
    "api-guardrails",            # read-only checklist/review (Read/Grep/Glob)
    "garden",                    # full-automation by directive (no human-review bucket)
    "gather-intel",              # research sweep, report-only
    "plateau-diagnose",          # diagnostic analysis, no in-run branch
    "refine",                    # prompt-enrichment transform
    "sharp-edges",               # footgun analysis report
    "threat-model",              # produces a threat-model artifact (report)
}

# Matched-pair XML tag pattern. Only flag `<tag>...</tag>` where the
# opening and closing tag names match — that's a real XML tag. Bare
# placeholders like `<plan>`, `<slug>`, `<github-username>` are
# legitimate prose syntax in descriptions and DON'T match this pattern.
# See Check 3 rule #9: "narrow scope to opening/closing tag patterns".
_XML_TAG_PAIR = re.compile(r"<([a-z][a-z0-9-]*)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)

# First-person phrases that suggest a non-third-person description (Tier B).
_FIRST_PERSON = re.compile(r"\b(I will|let me|I'll|I am|I'm going)\b", re.IGNORECASE)


def _parse_frontmatter(content: str) -> tuple[dict | None, str]:
    """Extract YAML frontmatter and body. Returns (None, '') on parse failure."""
    m = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not m:
        return None, ""
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, ""
    body = content[m.end():]
    return (fm if isinstance(fm, dict) else None), body


def _check_one_skill(skill_dir: Path) -> tuple[list[str], list[str]]:
    """Validate a single skill. Returns (tier_a_fail, tier_bc_warn) issue lists."""
    skill_name = skill_dir.name
    tier_a: list[str] = []
    tier_bc: list[str] = []

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        tier_a.append(f"{skill_name}: SKILL.md missing")
        return tier_a, tier_bc

    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as e:
        tier_a.append(f"{skill_name}: cannot read SKILL.md ({e})")
        return tier_a, tier_bc

    if not content.strip():
        tier_a.append(f"{skill_name}: SKILL.md empty")
        return tier_a, tier_bc

    fm, body = _parse_frontmatter(content)
    if fm is None:
        tier_a.append(f"{skill_name}: frontmatter missing or unparseable")
        return tier_a, tier_bc

    # ── Tier A: Anthropic-authoritative (FAIL) ───────────────────────
    name = fm.get("name")
    if not name:
        tier_a.append(f"{skill_name}: missing `name`")
    else:
        if len(name) > 64:
            tier_a.append(f"{skill_name}: name too long ({len(name)} > 64)")
        if not re.match(r"^[a-z0-9-]+$", name):
            tier_a.append(f"{skill_name}: name has invalid chars: {name!r}")
        if name not in LOCAL_RESERVED_EXCEPTIONS:
            for res in RESERVED_WORDS:
                if res in name.lower():
                    tier_a.append(f"{skill_name}: name contains reserved word {res!r}")
        if name != skill_name:
            tier_a.append(f"{skill_name}: name {name!r} != folder {skill_name!r}")

    desc = fm.get("description")
    if not desc:
        tier_a.append(f"{skill_name}: missing `description`")
    elif len(str(desc)) > 1024:
        tier_a.append(f"{skill_name}: description too long ({len(str(desc))} > 1024)")

    # XML tag pairs (only flag matched <tag>...</tag>, not bare <placeholder>).
    for field, val in (("name", name), ("description", desc)):
        if val and _XML_TAG_PAIR.search(str(val)):
            tier_a.append(f"{skill_name}: {field} has XML tag pair")

    line_count = body.count("\n")
    # SOFT cap (rules/skill-standards.md: ≤510, non-failing — "do NOT tighten to a
    # hard 500"). A long body is a WARN (tier B/C), NOT a Tier-A FAIL; 510 lines is
    # a proxy for the real Level-2 token budget, and Anthropic sanctions exceeding
    # it with cause. Aligns with validate-skills.py C1 (advisory).
    if line_count > 510:
        tier_bc.append(f"{skill_name}: body {line_count} lines (>510 soft cap — extract to references/ if no clear reason to exceed; advisory)")

    # Aligned with CI's validate-skills.py EXAMPLE_HEADER_RE (`^#{1,3}\s.*example`,
    # IGNORECASE): any heading CONTAINING the word counts — `## Worked example`
    # is a valid Examples section. The old `^#+\s+Example` prefix-anchor was
    # STRICTER than CI, so this checker FAILed skills CI shipped (2026-08-22).
    if not re.search(r"^#{1,3}\s.*\bexamples?\b", body, re.MULTILINE | re.IGNORECASE):
        tier_a.append(f"{skill_name}: no `## Examples` section")

    # ── Tier B/C: WARN ───────────────────────────────────────────────
    if desc and _FIRST_PERSON.search(str(desc)):
        tier_bc.append(f"{skill_name}: description uses first person (Tier B)")

    if not re.search(r"^#+\s+Success\s+Criteria", body, re.MULTILINE | re.IGNORECASE):
        tier_bc.append(f"{skill_name}: no `## Success Criteria` section (Tier C / local)")

    if fm.get("context") == "fork" and re.search(r"\bAgent\s+tool\b", body):
        tier_bc.append(f"{skill_name}: context:fork but body references Agent tool (Tier C / local)")

    allowed = fm.get("allowed-tools")
    if allowed and skill_name not in PURE_PIPELINE_SKILLS:
        tools_str = " ".join(map(str, allowed)) if isinstance(allowed, list) else str(allowed)
        if "AskUserQuestion" not in tools_str:
            tier_bc.append(f"{skill_name}: allowed-tools missing AskUserQuestion (Tier C / empirical)")

    return tier_a, tier_bc


def check_skills() -> int:
    """Iterate skills, return exit code (0 pass, 1 WARN-only, 2 Tier-A FAIL)."""
    if not SKILLS_DIR.is_dir():
        print(f"Skills: SKIP — {SKILLS_DIR} doesn't exist", file=sys.stderr)
        return 2

    pass_count = 0
    total = 0
    tier_a_failures: list[str] = []
    tier_bc_warnings: list[str] = []
    skipped_helpers: list[str] = []

    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        # Underscore-prefixed dirs are shared helper directories by convention
        # (e.g. _shared/). Dot-prefixed dirs are tooling debris (.pytest_cache,
        # .DS_Store, .ipynb_checkpoints) — never a skill. Skip both: flagging a
        # hidden dir as "SKILL.md missing" is a false Tier-A FAIL (the
        # .pytest_cache incident, 2026-06-13).
        if d.name.startswith(("_", ".")):
            skipped_helpers.append(d.name)
            continue
        a, bc = _check_one_skill(d)
        # Report BOTH tiers for a skill — the old `elif` masked every Tier-B/C
        # finding on a skill with a Tier-A FAIL, so fixing the FAIL "revealed"
        # warnings that read as regressions (2026-08-22: +4 phantom-new warns).
        tier_a_failures.extend(a)
        tier_bc_warnings.extend(bc)
        if not a and not bc:
            pass_count += 1
        total += 1

    if tier_a_failures:
        print(f"Skills: FAIL — {pass_count}/{total} pass, "
              f"{len(tier_a_failures)} Tier-A issues, {len(tier_bc_warnings)} Tier-B/C issues")
    elif tier_bc_warnings:
        print(f"Skills: WARN — {pass_count}/{total} pass, "
              f"{len(tier_bc_warnings)} Tier-B/C issues")
    else:
        print(f"Skills: PASS — {pass_count}/{total} validated"
              + (f" (skipped {len(skipped_helpers)} helper dirs: {', '.join(skipped_helpers)})"
                 if skipped_helpers else ""))

    if tier_a_failures:
        print("Tier A (FAIL):")
        for issue in tier_a_failures:
            print(f"  {issue}")
    if tier_bc_warnings:
        print("Tier B/C (WARN):")
        for issue in tier_bc_warnings:
            print(f"  {issue}")

    return 2 if tier_a_failures else (1 if tier_bc_warnings else 0)


if __name__ == "__main__":
    sys.exit(check_skills())
