#!/usr/bin/env python3
"""One-shot: generate skill-variant SKILL.md files and trigger-prompt files from design.yaml.

Outputs:
  skill-variants/<skill>-<style>/SKILL.md       (15 files: 5 skills × 3 styles)
  trigger-prompts/<skill>-<trigger_type>.txt    (20 files: 5 skills × 4 trigger types)
"""
import yaml
from pathlib import Path

ROOT = Path(__file__).parent
design = yaml.safe_load((ROOT / "design.yaml").read_text())

# --- Skill variants ---
variants_dir = ROOT / "skill-variants"
for skill in design["pilot_skills"]:
    for style in design["description_styles"]:
        skill_dir = variants_dir / f"{skill['id']}-{style['id']}"
        skill_dir.mkdir(parents=True, exist_ok=True)
        # Render the description from the style template + skill-specific values
        # Replace {do_not_clause} only for styles that use it; safe even if absent.
        desc = style["template"].format(
            when_clause=skill["when_clause"],
            triggers=skill["triggers"],
            do_not_clause=skill.get("do_not_clause", ""),
        ).strip()

        # Body keeps each variant minimal — we're measuring activation, not body.
        # All three variants share the same body so any activation difference is
        # attributable to the description alone.
        body = f"""# {skill['id']} (study variant: {style['id']})

This is an activation-study variant of `{skill['id']}`. Body is intentionally
minimal so the only manipulated variable is the description style.

## Procedure

1. Acknowledge the user's request.
2. Perform the documented action.
3. Report what was done.

## Examples

- Worked example placeholder for activation measurement.
"""
        frontmatter = f"""---
name: {skill['id']}-{style['id']}
description: |
  {desc}
argument-hint: "[input or context]"
allowed-tools: Read Write Edit Bash AskUserQuestion
---

"""
        (skill_dir / "SKILL.md").write_text(frontmatter + body)

# --- Trigger prompts ---
# Per-skill per-trigger-type prompts. Authored by hand for each skill — this
# matters more than the variant code, since trigger fidelity drives the
# measurement.
PROMPTS = {
    "capture": {
        "exact":     'capture',
        "near":      'save this insight',                              # paraphrased trigger
        "semantic":  "I want to write down today's lessons learned",   # no lexical overlap
        "unrelated": "what's the weather in Austin tomorrow",          # negative control
    },
    "recall": {
        "exact":     'recall',
        "near":      "what did we learn about retry logic",
        "semantic":  "find prior context on the timeout work we did",
        "unrelated": "convert this image to grayscale",
    },
    "refine": {
        "exact":     'refine',
        "near":      "improve this prompt",
        "semantic":  "this prompt is too vague before running it",
        "unrelated": "explain the difference between TCP and UDP",
    },
    "ship": {
        "exact":     'ship',
        "near":      "commit and push",
        "semantic":  "land this change in main",
        "unrelated": "draw a flowchart of OAuth",
    },
    "audit-skill": {
        "exact":     "audit skill",
        "near":      "lint this skill",
        "semantic":  "is the format of this SKILL.md correct",
        "unrelated": "tell me a fun fact about octopuses",
    },
}

prompts_dir = ROOT / "trigger-prompts"
prompts_dir.mkdir(parents=True, exist_ok=True)
for skill_id, by_type in PROMPTS.items():
    for trigger_type, prompt_text in by_type.items():
        path = prompts_dir / f"{skill_id}-{trigger_type}.txt"
        path.write_text(prompt_text + "\n")

# --- Prefix conditions ---
prefix_dir = ROOT / "prefix-conditions"
prefix_dir.mkdir(parents=True, exist_ok=True)
for prefix in design["prefix_conditions"]:
    (prefix_dir / f"{prefix['id']}.txt").write_text(prefix["system_prompt"] + "\n")

print("Generated:")
print(f"  {sum(1 for _ in variants_dir.rglob('SKILL.md'))} skill variants in {variants_dir.relative_to(ROOT.parent.parent)}")
print(f"  {sum(1 for _ in prompts_dir.glob('*.txt'))} trigger prompts in {prompts_dir.relative_to(ROOT.parent.parent)}")
print(f"  {sum(1 for _ in prefix_dir.glob('*.txt'))} prefix conditions in {prefix_dir.relative_to(ROOT.parent.parent)}")
