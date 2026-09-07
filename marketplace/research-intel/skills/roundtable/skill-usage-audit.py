#!/usr/bin/env python3
"""Count both /skill-name invocations AND auto-fired Skill tool calls.

A thin front over bin/skill-usage-report.py, which owns the counting: the two
counters used to hold different regexes over different roots, and a disagreement
between them would quietly change which skills docs/skill-listing-decisions.md
hides. This keeps the roundtable's zero-first table and its default root (the
current project's transcript directory) and delegates everything else.

    python3 skills/roundtable/skill-usage-audit.py                 # this project's transcripts
    python3 skills/roundtable/skill-usage-audit.py --root DIR       # any transcript directory
    CLAUDE_PROJECT_DIR=... python3 skills/roundtable/skill-usage-audit.py
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load_counter():
    """bin/skill-usage-report.py from the harness checkout this file lives in, else the
    installed copy, else $CLAUDE_HARNESS_ROOT. A marketplace bundle ships this front
    without bin/, so the failure is a sentence, not a traceback."""
    candidates = [REPO / "bin", pathlib.Path.home() / ".claude" / "bin",
                  pathlib.Path(os.environ.get("CLAUDE_HARNESS_ROOT") or "/nonexistent") / "bin"]
    for base in candidates:
        tool = base / "skill-usage-report.py"
        if tool.is_file():
            spec = importlib.util.spec_from_file_location("skill_usage_report", tool)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    sys.exit("skill-usage-audit: the counter lives in bin/skill-usage-report.py of the claude-harness checkout; "
             "this copy has no bin/ beside it. Run it from a harness clone or set CLAUDE_HARNESS_ROOT.")


def _resolve_project_dir() -> pathlib.Path:
    """Resolve the per-project Claude Code dir at runtime (cwd encoding)."""
    if env_dir := os.environ.get("CLAUDE_PROJECT_DIR"):
        return pathlib.Path(env_dir)
    projects = pathlib.Path.home() / ".claude" / "projects"
    encoded = str(pathlib.Path.cwd().resolve()).replace("/", "-").replace(":", "-").strip("-")
    candidate = projects / encoded
    if candidate.exists():
        return candidate
    if projects.exists():
        subdirs = [p for p in projects.iterdir() if p.is_dir()]
        if subdirs:
            return max(subdirs, key=lambda p: p.stat().st_mtime)
    return projects / "_unresolved"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="transcript directory (default: this project's)")
    ap.add_argument("--skills", default=str(pathlib.Path.home() / ".claude" / "skills"))
    ap.add_argument("--settings", default=str(pathlib.Path.home() / ".claude" / "settings.json"))
    args = ap.parse_args()
    root = pathlib.Path(os.path.expanduser(args.root)) if args.root else _resolve_project_dir()
    skills = pathlib.Path(os.path.expanduser(args.skills))
    if not root.is_dir():
        print(f"skill-usage-audit: no transcript directory at {root}", file=sys.stderr)
        return 2
    if not skills.is_dir():
        skills = REPO / "skills"
    _sur = _load_counter()
    rep = _sur.build(root, None, pathlib.Path(os.path.expanduser(args.settings)), skills)
    rows = sorted(rep["skills"], key=lambda r: (r["invocations"], r["sessions"], r["skill"]))
    slash = sum(r["slash"] for r in rows)
    auto = sum(r["auto"] for r in rows)
    print(f"Scanned {rep['transcripts']} transcripts. {slash} slash + {auto} Skill-tool = {slash + auto} total\n")
    print(f"{'skill':<33}{'slash':>7}{'auto':>7}{'total':>7}{'sess':>6}")
    print("-" * 60)
    for r in rows:
        flag = "  ZERO" if r["invocations"] == 0 else ""
        print(f"{r['skill']:<33}{r['slash']:>7}{r['auto']:>7}{r['invocations']:>7}{r['sessions']:>6}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
