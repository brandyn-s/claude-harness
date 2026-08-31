"""Auto-prune stale files/dirs at session start."""
import shutil
from datetime import datetime, timedelta
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"

PRUNE_TARGETS = [
    (CLAUDE_DIR / "debug", 3, True),
    (CLAUDE_DIR / "shell-snapshots", 3, True),
    (CLAUDE_DIR / "paste-cache", 3, True),
    (CLAUDE_DIR / "session-env", 3, False),
    (CLAUDE_DIR / "file-history", 7, True),
    (CLAUDE_DIR / "todos", 7, True),
    (CLAUDE_DIR / "plans", 14, True),
    (CLAUDE_DIR / "tool-offloads", 1, True),
]


def prune_directory(target_dir, max_age_days, _file_based):
    if not target_dir.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=max_age_days)
    cleaned = 0
    for entry in target_dir.iterdir():
        if entry.is_symlink():
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
            if mtime < cutoff:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink()
                cleaned += 1
        except Exception:
            pass
    return cleaned


def prune_glob_pattern(pattern, max_age_days):
    cutoff = datetime.now() - timedelta(days=max_age_days)
    cleaned = 0
    for f in CLAUDE_DIR.glob(pattern):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                else:
                    f.unlink()
                cleaned += 1
        except Exception:
            pass
    return cleaned


def run_auto_prune():
    total = 0
    for target_dir, max_age_days, fb in PRUNE_TARGETS:
        total += prune_directory(target_dir, max_age_days, fb)
    total += prune_glob_pattern("security_warnings_state_*.json", 7)
    total += prune_glob_pattern("plugins/cache/temp_git_*", 1)
    tasks_dir = CLAUDE_DIR / "tasks"
    if tasks_dir.exists():
        total += prune_directory(tasks_dir, 7, False)
    if total > 0:
        return f"Auto-pruned {total} stale files/dirs"
    return None
