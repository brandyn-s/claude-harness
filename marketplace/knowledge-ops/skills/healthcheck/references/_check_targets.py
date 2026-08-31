"""Check 8: Skill output targets — designed-but-never-firing detector.

Verifies that output paths skills are supposed to produce actually exist.
Extracted from the _check_all.py orchestrator for a single home + standalone
`/healthcheck targets` + unit testability. Honors CLAUDE_CONFIG_DIR.

The /distill T3 pattern-files target was removed 2026-06-10 (PR #1160): T3 was
retired and ~/.claude/memory/*-patterns.md is no longer a feature.

The /distill history target was corrected 2026-07-03: `distill-history.jsonl`
has zero git history (never implemented under any distill design — confirmed
by grepping distill/SKILL.md, which only ever writes `last-distill.json`, a
single overwritten session-dedup marker, not an append-log). The row was a
permanent false WARN since it was written — same class of bug as the T3 row.

Exit 0 = PASS, 1 = WARN (a target is missing). Missing targets are WARN, not
FAIL — the skill still runs, it just produced no output for that step.
"""
import os
import sys
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
HOME = Path.home()


def _dir_has_md(d: Path) -> bool:
    return d.is_dir() and any(fn.endswith(".md") for _, _, fs in os.walk(d) for fn in fs)


def check_targets():
    """Return (status, message). status ∈ {PASS, WARN}."""
    kb = HOME / "Documents" / "knowledge-base" / "topics"
    targets = [
        ("/distill T0 staging", lambda: (CLAUDE_DIR / "hooks" / "staged").is_dir(), False),
        ("/distill last-run marker", lambda: (CLAUDE_DIR / "last-distill.json").is_file(), False),
        ("/capture KB topics", lambda: _dir_has_md(kb), False),
        ("/gather-repos ledger", lambda: (CLAUDE_DIR / "assessed-repos.md").is_file(), False),
    ]
    miss = [f"{n} ({'optional' if w else 'expected'})" for n, fn, w in targets if not fn()]
    if not miss:
        return "PASS", f"{len(targets)} output targets verified"
    return "WARN", f"{len(targets) - len(miss)}/{len(targets)} present — missing: " + "; ".join(miss)


def main():
    status, msg = check_targets()
    print(f"Targets: {status} — {msg}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
