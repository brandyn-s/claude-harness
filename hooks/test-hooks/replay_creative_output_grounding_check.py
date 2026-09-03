#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Historical replay of creative-output-grounding-check.py against session transcripts.

Per verify-effectiveness.md: hook retroactive testing requires replaying
the hook against real transcripts and verifying warn rate < 10%.

Usage: python replay_creative_output_grounding_check.py [--days N]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

HOOK = Path(__file__).resolve().parents[1] / "creative-output-grounding-check.py"


def _resolve_project_dir() -> Path:
    """Resolve the per-project Claude Code dir at runtime (cwd encoding)."""
    if env_dir := os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(env_dir)
    projects = Path.home() / ".claude" / "projects"
    encoded = str(Path.cwd().resolve()).replace("/", "-").replace(":", "-").strip("-")
    candidate = projects / encoded
    if candidate.exists():
        return candidate
    if projects.exists():
        subdirs = [p for p in projects.iterdir() if p.is_dir()]
        if subdirs:
            return max(subdirs, key=lambda p: p.stat().st_mtime)
    return projects / "_unresolved"


TRANSCRIPTS_DIR = _resolve_project_dir()
TARGET_SKILLS = {"scout-frontier", "design-evidence-first", "deep-dive", "refine"}


def find_skill_invocations(transcript_path: Path):
    """Yield (skill_name, tool_result_text) for each target Skill invocation."""
    try:
        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                # Tool-use entries vary by Claude Code version; handle both shapes.
                # Newer transcripts: {"type": "tool_use", "name": "Skill", "input": {...}}
                # Or assistant message containing tool_use blocks.
                if entry.get("type") == "tool_use" and entry.get("name") == "Skill":
                    skill = (entry.get("input") or {}).get("skill") or ""
                    skill = skill.lstrip("/")
                    if skill in TARGET_SKILLS:
                        yield skill, entry
                # Try the assistant-message-with-content shape
                msg = entry.get("message") or {}
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, list):
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("name") == "Skill"
                        ):
                            skill = (block.get("input") or {}).get("skill") or ""
                            skill = skill.lstrip("/")
                            if skill in TARGET_SKILLS:
                                yield skill, block
    except OSError:
        return


def find_tool_result_for(transcript_path: Path, tool_use_id: str) -> str | None:
    """Find the matching tool_result block by tool_use_id."""
    try:
        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = entry.get("message") or {}
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, list):
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "tool_result"
                            and block.get("tool_use_id") == tool_use_id
                        ):
                            res = block.get("content")
                            if isinstance(res, str):
                                return res
                            if isinstance(res, list):
                                # Sometimes content is a list of {type:text, text:"..."}
                                texts = [
                                    b.get("text", "")
                                    for b in res
                                    if isinstance(b, dict) and b.get("type") == "text"
                                ]
                                return "\n".join(texts)
    except OSError:
        return None
    return None


def run_hook(skill_name: str, tool_result: str) -> bool:
    """Return True if hook emits a warning."""
    payload = {
        "tool_name": "Skill",
        "tool_input": {"skill": skill_name},
        "tool_result": tool_result,
    }
    try:
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False
    return bool(proc.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    cutoff = time.time() - args.days * 86400
    candidates = list(TRANSCRIPTS_DIR.glob("*.jsonl")) + list(TRANSCRIPTS_DIR.glob("*/*.jsonl"))
    transcripts = sorted(
        (p for p in candidates if p.stat().st_mtime >= cutoff),
        key=lambda p: p.stat().st_mtime,
    )
    if not transcripts:
        print(f"No transcripts found in last {args.days} days under {TRANSCRIPTS_DIR}")
        return 1

    print(f"Scanning {len(transcripts)} transcripts (last {args.days} days)...")

    invocations = 0
    warns = 0
    per_skill: dict[str, dict[str, int]] = {
        s: {"invoked": 0, "warned": 0} for s in TARGET_SKILLS
    }
    examples: list[tuple[str, str, str]] = []  # (skill, transcript, snippet)

    for tp in transcripts:
        for skill, block in find_skill_invocations(tp):
            tool_use_id = block.get("id")
            if not tool_use_id:
                continue
            result_text = find_tool_result_for(tp, tool_use_id)
            if not result_text:
                continue
            invocations += 1
            per_skill[skill]["invoked"] += 1
            if run_hook(skill, result_text):
                warns += 1
                per_skill[skill]["warned"] += 1
                if len(examples) < 5:
                    examples.append((skill, tp.name, result_text[:160].replace("\n", " ")))

    if invocations == 0:
        print("No Skill invocations of target skills in window. Hook will be silent on history.")
        return 0

    rate = warns / invocations
    print(f"\nResults across {len(transcripts)} transcripts:")
    print(f"  total target-skill invocations: {invocations}")
    print(f"  warned: {warns} ({rate:.1%})")
    for skill, stats in per_skill.items():
        if stats["invoked"]:
            r = stats["warned"] / stats["invoked"]
            print(f"  /{skill}: {stats['warned']}/{stats['invoked']} warned ({r:.1%})")

    if examples:
        print("\nExample warned outputs (first 5, truncated to 160 chars):")
        for skill, transcript, snippet in examples:
            print(f"  /{skill} in {transcript}: {snippet}")

    threshold = 0.10
    if rate > threshold:
        print(f"\nFAIL: warn rate {rate:.1%} > {threshold:.0%} threshold")
        print("Tune detection criteria before keeping the hook on (verify-effectiveness.md).")
        return 2
    print(f"\nPASS: warn rate {rate:.1%} <= {threshold:.0%} threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
