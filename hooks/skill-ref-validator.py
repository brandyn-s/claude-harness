"""PostToolUse hook for Edit|Write: warn on dead hook/script refs in SKILL.md.

Greps the edited SKILL.md body for `hooks/*.py` and `scripts/*.py` paths
and warns if any referenced file doesn't exist on disk. Advisory only —
always exits 0 (does not block save).

Why: PR #548 deleted sync-repo.py and sync-knowledge.py; skills referencing
them stayed stale for 6 days until /healthcheck surfaced it. Catching drift
at the moment of edit prevents this class of mistake.

Exits:
  0 = always (stderr = advisory warning shown to Claude)
"""

import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

_HOME = str(Path.home())
CLAUDE_DIR = Path(_HOME) / ".claude"

# Matches hooks/foo.py or scripts/foo.py with flexible separators.
REF_PATTERN = re.compile(r"\b(hooks|scripts)/([\w.-]+\.py)\b")


def strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks so refs inside examples/templates are ignored."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if hook_input.get("tool_name") not in ("Write", "Edit"):
        sys.exit(0)

    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    norm = os.path.normpath(file_path).replace("\\", "/")
    # Only fire on SKILL.md under skills/
    if "/skills/" not in norm or not norm.endswith("/SKILL.md"):
        sys.exit(0)

    if not os.path.isfile(file_path):
        sys.exit(0)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            body = f.read()
    except (OSError, UnicodeDecodeError):
        sys.exit(0)

    stripped = strip_code_blocks(body)
    refs = set(REF_PATTERN.findall(stripped))

    missing = []
    for kind, name in sorted(refs):
        target = CLAUDE_DIR / kind / name
        if not target.exists():
            missing.append(f"{kind}/{name}")

    if missing:
        skill_name = os.path.basename(os.path.dirname(norm))
        lines = [
            f"[skill-ref-validator] {skill_name}/SKILL.md references "
            f"{len(missing)} missing file(s):",
        ]
        for m in missing:
            lines.append(f"  - {m}")
        lines.append(
            "These files do not exist on disk. Either restore them, "
            "remove the references, or confirm this is intentional."
        )
        print("\n".join(lines), file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)