# `$CLAUDE_PROJECT_ID` — Resolving the per-project directory

Claude Code stores per-project state (memory, settings, session transcripts)
under `~/.claude/projects/<encoded-cwd>/`, where `<encoded-cwd>` is the
absolute working-directory path with every `/`, `:`, and `.` replaced by
`-` — the leading `/` becomes a leading `-`, which is KEPT (not stripped).

Examples:

| Working directory | Encoded project ID |
|---|---|
| `C:/Users/Alice` | `C--Users-Alice` |
| `/home/bob/projects/foo` | `-home-bob-projects-foo` |
| `C:/Users/you` | `C--Users-you` |
| `$HOME` (macOS) | `-Users-you` |

## Resolution recipe

Skills and scripts should resolve the project dir at runtime — never
hardcode an encoded ID. Older sites used the literal placeholder
`<your-claude-project>` as if it were a directory name; that string
never resolved to a real path. Either use the `$CLAUDE_PROJECT_ID`
convention below (which the agent and the helper functions resolve
at runtime) or use the explicit Bash/Python recipes that follow.

### Bash

```bash
PROJECTS="$HOME/.claude/projects"
PROJECT_DIR=""

# 1. Explicit override always wins.
if [ -n "${CLAUDE_PROJECT_ID:-}" ] && [ -d "$PROJECTS/$CLAUDE_PROJECT_ID" ]; then
  PROJECT_DIR="$PROJECTS/$CLAUDE_PROJECT_ID"
# 2. AUTHORITATIVE — the dir holding THIS session's transcript. Positive
#    identification, so cwd drift cannot fool it.
elif [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  t=$(find "$PROJECTS" -maxdepth 2 -name "${CLAUDE_CODE_SESSION_ID}.jsonl" 2>/dev/null | head -1)
  [ -n "$t" ] && PROJECT_DIR=$(dirname "$t")
fi

# 3. Last resort: the pwd encoding. A hit here is UNVERIFIED, never confirmation.
if [ -z "$PROJECT_DIR" ]; then
  PROJECT_DIR="$PROJECTS/$(pwd | tr '/:.' '---')"
fi
[ -d "$PROJECT_DIR" ] || { echo "cannot resolve project dir: $PROJECT_DIR" >&2; exit 1; }
```

**The `pwd` fallback silently misresolves when the shell cwd has DRIFTED.**
`pwd` is the *shell's* current directory, not the session's primary working
directory, and a long session that `cd`s into a scratch or worktree path leaves
them different. The encoded ID is then computed from the wrong directory and
names a project dir that **does not exist** — so a write creates an orphan
`projects/<wrong-id>/memory/` instead of appending to the real one, and the
mistake is invisible because both the `tr` and the write succeed.

Measured 2026-08-12: a session whose primary cwd was `$HOME`
had drifted to `/private/tmp/claude`. The recipe produced
`PROJECT_ID=-private-tmp-claude` instead of `-Users-you` (162 files,
the MEMORY.md actually loaded into that session's context). A `/distill` T2
write would have gone to the wrong dir.

~~So: always test `-d "$PROJECT_DIR"` before writing … A nonexistent project dir
is a resolution bug, never a first-run condition.~~ **CORRECTED same day — the
`-d` test does NOT catch this.** Re-measured on the same host: the drifted
`projects/-private-tmp-claude/` **exists and holds 26 entries** (13 prior
sessions that really did run from `/private/tmp/claude`, since the Bash tool's
cwd persists across calls). So `[ -d "$PROJECT_DIR" ]` returns TRUE and the
guard never fires — on precisely the case documented above. The earlier
"nonexistent, 0 files" reading was wrong.

The failure is therefore WORSE than an orphan write: the wrong dir is a real,
populated project, so a `/distill` T2 write lands in another project's memory
rather than in an obviously-empty stub anyone would notice.

**Existence is not the discriminator; identity is.** Resolve positively from
`$CLAUDE_CODE_SESSION_ID` — the correct project dir is the one containing
`<session-id>.jsonl` — and treat the `pwd` encoding as an unverified last
resort, as the recipe above now does. Note the Python recipe below has the same
hole: its `candidate.exists()` branch also passes on a populated wrong dir.

### Python

```python
import os
from pathlib import Path

def project_dir() -> Path:
    """Resolve the per-project Claude Code dir at runtime."""
    if env_dir := os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(env_dir)
    projects = Path.home() / ".claude" / "projects"
    encoded = str(Path.cwd().resolve()).replace("/", "-").replace(":", "-").replace(".", "-")
    candidate = projects / encoded
    if candidate.exists():
        return candidate
    # Fallback: pick the most recently modified projects/ subdir.
    if projects.exists():
        subdirs = [p for p in projects.iterdir() if p.is_dir()]
        if subdirs:
            return max(subdirs, key=lambda p: p.stat().st_mtime)
    return projects / "_unresolved"
```

## In skill bodies

When a SKILL.md needs to reference a project-scoped path, write
`$CLAUDE_PROJECT_ID` (uppercase, in `${...}` form where appropriate) and
expect the agent to resolve it via the bash recipe above. Do not revive
the old `<your-claude-project>` literal — that string never resolved at
runtime and silently produced empty paths in every site that read it.

Examples of correct usage in a SKILL.md:

```
Read `~/.claude/projects/$CLAUDE_PROJECT_ID/CLAUDE.md`.
```

```bash
PROJECT_ID="${CLAUDE_PROJECT_ID:-$(pwd | tr '/:.' '---')}"
cat "$HOME/.claude/projects/$PROJECT_ID/memory/MEMORY.md"
```

## Why this matters

Searches show 100+ historical sites used the literal `<your-claude-project>`
template marker as if it were a directory name. Every `Read`/`Glob`/`open`
against that path returned nothing because no such directory ever existed.
The 2026-05-23 sweep replaced all runtime sites with the resolution recipe
above; only historical artifacts in `docs/plans/` and `agent-memory/topics/`
were left intact (they describe past intent, not active behavior).
