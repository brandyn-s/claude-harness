"""Forensic check for the file-disappearance bug.

Scans recent Claude Code session transcripts (JSONL) for Write/Edit/MultiEdit
tool calls, then verifies whether those files exist on disk now. Surfaces
files that were successfully written but later vanished — useful for
post-incident triage when files seem to disappear between sessions.

Read-only. Does not modify any state.

Usage:
  python check-write-journal.py [--days N] [--path-prefix PREFIX]

Defaults: last 1 day, no prefix filter.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from collections import defaultdict


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


DEFAULT_TRANSCRIPTS = _resolve_project_dir()
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def find_jsonls(root: Path, since_ts: float) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*.jsonl") if p.stat().st_mtime >= since_ts)


def extract_writes(jsonl: Path) -> list[dict]:
    """Yield (path, tool, timestamp, session_id) for every Write/Edit/MultiEdit call."""
    out = []
    try:
        for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                tool = block.get("name", "")
                if tool not in WRITE_TOOLS:
                    continue
                inp = block.get("input", {})
                fp = inp.get("file_path") or inp.get("notebook_path")
                if not fp:
                    continue
                out.append({
                    "path": fp,
                    "tool": tool,
                    "ts": rec.get("timestamp", ""),
                    "session": jsonl.stem,
                })
    except OSError as e:
        print(f"  WARN: could not read {jsonl.name}: {e}", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1, help="how many days back to scan (default 1)")
    ap.add_argument("--path-prefix", default="", help="only check paths starting with this prefix")
    ap.add_argument("--transcripts", default=str(DEFAULT_TRANSCRIPTS), help="transcript directory")
    ap.add_argument("--show-extant", action="store_true", help="also list writes whose files still exist")
    args = ap.parse_args()

    since = time.time() - args.days * 86400
    root = Path(args.transcripts).expanduser()
    jsonls = find_jsonls(root, since)
    if not jsonls:
        print(f"No transcripts under {root} modified in the last {args.days}d")
        sys.exit(0)

    print(f"Scanning {len(jsonls)} transcript(s) under {root}")
    print(f"  filter: writes from last {args.days}d{', prefix ' + args.path_prefix if args.path_prefix else ''}")
    print()

    writes = []
    for jsonl in jsonls:
        writes.extend(extract_writes(jsonl))

    if args.path_prefix:
        writes = [w for w in writes if w["path"].startswith(args.path_prefix)]

    by_path = defaultdict(list)
    for w in writes:
        by_path[w["path"]].append(w)

    missing = []
    extant = []
    for path, ws in sorted(by_path.items()):
        last = ws[-1]
        p = Path(path)
        if p.exists():
            extant.append((path, len(ws), last))
        else:
            missing.append((path, len(ws), last))

    print(f"=== Files written then vanished ({len(missing)}) ===")
    if not missing:
        print("  (none — every recently-written file is on disk)")
    for path, n_writes, last in missing:
        print(f"  GONE  {path}")
        print(f"        last write: {last['tool']} at {last['ts']} (session {last['session'][:8]})")
        print(f"        total writes in window: {n_writes}")

    if args.show_extant:
        print()
        print(f"=== Files written and still present ({len(extant)}) ===")
        for path, n_writes, last in extant:
            print(f"  OK    {path} ({n_writes}x)")

    print()
    print(f"Summary: {len(by_path)} unique paths written, {len(missing)} missing, {len(extant)} present")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
