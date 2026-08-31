#!/usr/bin/env python3
"""Audit skill discovery cost separately from on-demand body size.

Claude Code advertises skill names and descriptions at discovery time; the
full SKILL.md body loads only when invoked. ``chars / 4`` is the portable
structural estimate. It is not an Anthropic token count. For qualification,
use the target model's token-counting endpoint and retain the model tag.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

SOFT_BODY_CAP = 6000
COMPACTION_REATTACH_PER_SKILL = 5000
COMPACTION_REATTACH_COMBINED = 25000
COMPACTION_RECOVERY_PROXY_CAP = 4000
COMPACTION_RECOVERY_RE = re.compile(
    r"\*\*Compaction continuity:\*\*"
    r"(?=.{0,1200}\bre-invoke\b)"
    r"(?=.{0,1200}\bstop and ask\b)",
    re.IGNORECASE | re.DOTALL,
)
LISTING_CHARACTER_CAP = 1536
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def frontmatter_from(text: str) -> dict:
    frontmatter = FRONTMATTER_RE.search(text)
    if not frontmatter:
        return {}
    value = yaml.safe_load(frontmatter.group(1)) or {}
    return value if isinstance(value, dict) else {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--over",
        type=int,
        default=0,
        help="only show skills with body estimate over N tokens",
    )
    parser.add_argument("--skill", help="one skill only")
    parser.add_argument(
        "--model",
        default="unqualified-proxy",
        help="model tag for the report; does not change proxy counting",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    all_rows = []
    for skill_md in sorted(Path("skills").glob("*/SKILL.md")):
        if args.skill and skill_md.parent.name != args.skill:
            continue
        skill_text = skill_md.read_text(encoding="utf-8")
        frontmatter = frontmatter_from(skill_text)
        description = str(frontmatter.get("description") or "").strip()
        when_to_use = str(frontmatter.get("when_to_use") or "").strip()
        combined_listing = " ".join(
            part for part in (description, when_to_use) if part
        )
        body_tokens = estimate_tokens(skill_text)
        intentionally_inert = (
            frontmatter.get("disable-model-invocation") is True
            and frontmatter.get("user-invocable") is False
        )
        advertised_to_model = (
            frontmatter.get("disable-model-invocation") is not True
        )
        effective_listing = combined_listing[:LISTING_CHARACTER_CAP]
        advertised_tokens = (
            estimate_tokens(f"{skill_md.parent.name}: {effective_listing}")
            if advertised_to_model
            else 0
        )
        row = {
            "skill": skill_md.parent.name,
            "lines": len(skill_text.splitlines()),
            "idle_loading": (
                "advertisement_only"
                if advertised_to_model
                else "not_advertised_to_model"
            ),
            "advertised_tokens_estimate": advertised_tokens,
            "listing_characters_before_cap": len(combined_listing),
            "listing_truncated_at_1536_chars": (
                len(combined_listing) > LISTING_CHARACTER_CAP
            ),
            "body_tokens_proxy": body_tokens,
            "body_loading": "on_demand",
            "over_soft_body_cap": body_tokens > SOFT_BODY_CAP,
            "compaction_reattach_limit_tokens": COMPACTION_REATTACH_PER_SKILL,
            "over_compaction_reattach_proxy": (
                body_tokens > COMPACTION_REATTACH_PER_SKILL
            ),
            "needs_compaction_recovery_contract": (
                body_tokens > COMPACTION_RECOVERY_PROXY_CAP
                and not intentionally_inert
            ),
            "intentionally_inert": intentionally_inert,
            "compaction_recovery_contract_present": (
                COMPACTION_RECOVERY_RE.search(skill_text[:20_000]) is not None
            ),
        }
        row["compaction_continuity_ok"] = (
            not row["needs_compaction_recovery_contract"]
            or row["compaction_recovery_contract_present"]
        )
        all_rows.append(row)

    all_rows.sort(key=lambda row: -row["body_tokens_proxy"])
    rows = [row for row in all_rows if row["body_tokens_proxy"] > args.over]
    report = {
        "model_tag": args.model,
        "counting_method": (
            "chars/4 structural proxy; qualify with target-model token counting"
        ),
        "compaction_contract": {
            "per_invoked_skill_reattach_tokens": COMPACTION_REATTACH_PER_SKILL,
            "combined_reattach_tokens": COMPACTION_REATTACH_COMBINED,
            "ordering": "newest_invoked_first",
            "recovery_proxy_cap": COMPACTION_RECOVERY_PROXY_CAP,
        },
        "total_skills": len(all_rows),
        "advertised_tokens_estimate_total": sum(
            row["advertised_tokens_estimate"] for row in all_rows
        ),
        "skills_hidden_from_model_discovery": sum(
            1 for row in all_rows if row["idle_loading"] == "not_advertised_to_model"
        ),
        "skills_with_truncated_listings": sum(
            1 for row in all_rows if row["listing_truncated_at_1536_chars"]
        ),
        "skills_over_soft_body_cap": sum(
            1 for row in all_rows if row["over_soft_body_cap"]
        ),
        "skills_over_compaction_reattach_proxy": sum(
            1 for row in all_rows if row["over_compaction_reattach_proxy"]
        ),
        "compaction_continuity_gaps": sum(
            1 for row in all_rows if not row["compaction_continuity_ok"]
        ),
        "skills": rows,
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"{'Skill':<35} {'Advertised':>10} {'Body proxy':>11} {'Lines':>7}")
    print("-" * 70)
    for row in rows:
        print(
            f"{row['skill']:<35} {row['advertised_tokens_estimate']:>10} "
            f"{row['body_tokens_proxy']:>11} {row['lines']:>7}"
        )
    print(f"\nModel tag: {args.model} (proxy only; no model tokenizer was invoked)")
    print(
        f"Skills over {SOFT_BODY_CAP}-token proxy body cap: "
        f"{report['skills_over_soft_body_cap']} of {report['total_skills']} audited"
    )
    print(
        "Post-compaction contract: first "
        f"{COMPACTION_REATTACH_PER_SKILL} tokens per invoked skill, "
        f"{COMPACTION_REATTACH_COMBINED} combined newest-first; "
        f"continuity gaps={report['compaction_continuity_gaps']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
