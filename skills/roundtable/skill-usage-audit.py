"""Count both /skill-name invocations AND auto-fired Skill tool calls."""
import os
import pathlib
import re
from collections import Counter


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


PROJECTS = _resolve_project_dir()
SKILLS = pathlib.Path.home() / ".claude/skills"

skill_names = sorted([d.name for d in SKILLS.iterdir() if d.is_dir() and d.name != "_shared"])

# Slash-invocation pattern
pat_slash = re.compile(r"<command-name>/?([a-z][a-z0-9-]+)</command-name>")
# Auto-fire via Skill tool: "name":"Skill" with "skill":"foo" in input
pat_skill_tool = re.compile(r'"name"\s*:\s*"Skill"[^}]*?"skill"\s*:\s*"([a-z][a-z0-9-]+)"')

counts = Counter()
auto_counts = Counter()
total_files = 0
total_invocations = 0
files_per_skill = {s: set() for s in skill_names}

for jsonl in PROJECTS.glob("*.jsonl"):
    total_files += 1
    try:
        text = jsonl.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    for m in pat_slash.finditer(text):
        name = m.group(1)
        counts[name] += 1
        total_invocations += 1
        if name in files_per_skill:
            files_per_skill[name].add(jsonl.name)
    for m in pat_skill_tool.finditer(text):
        name = m.group(1)
        auto_counts[name] += 1
        if name in files_per_skill:
            files_per_skill[name].add(jsonl.name)

# Sessions count per skill (deduped)
sessions = {s: len(files_per_skill[s]) for s in skill_names}

# Output: name, invocations, sessions, "ZERO" flag
rows = []
for s in skill_names:
    slash = counts.get(s, 0)
    auto = auto_counts.get(s, 0)
    ses = sessions[s]
    total = slash + auto
    rows.append((s, slash, auto, total, ses))

# Sort by total invocations ascending so the zeros surface first
rows.sort(key=lambda r: (r[3], r[4], r[0]))

print(f"Scanned {total_files} transcripts. {total_invocations} slash + {sum(auto_counts.values())} Skill-tool = {total_invocations + sum(auto_counts.values())} total\n")
print(f"{'skill':<33}{'slash':>7}{'auto':>7}{'total':>7}{'sess':>6}")
print("-" * 60)
for name, slash, auto, total, ses in rows:
    flag = "  ZERO" if total == 0 else ""
    print(f"{name:<33}{slash:>7}{auto:>7}{total:>7}{ses:>6}{flag}")
