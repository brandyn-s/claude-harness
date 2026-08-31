"""Check 5: Stale File Paths.

Verify that all script paths referenced in settings.json and MCP configs
exist on disk. Fixes the buggy ad-hoc regex that produced false positives
by picking up partial path matches.

Invoke: python check_paths.py
Exits 0 if clean, 1 if bad paths found (prints them to stdout).
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
HOME = str(Path.home()).replace("\\", "/")


def _normalize(path_str):
    """Expand $HOME, ~, backslashes to a checkable absolute POSIX path."""
    p = path_str.replace("\\", "/")
    p = p.replace("$HOME", HOME).replace("${HOME}", HOME)
    if p.startswith("~"):
        p = os.path.expanduser(p)
    # Strip surrounding quotes left over from shell tokens
    p = p.strip('"\'')
    return p


def _extract_script_paths(command):
    """Extract .py/.ps1 paths from a hook command string.

    Splits on shell tokens (not raw regex) so we only pick up whole argv
    entries, not substrings inside quoted names. The old regex greedily
    matched `hooks/foo.py` inside `"$HOME/.claude/hooks/foo.py"` and then
    resolved it against the wrong base, causing false positives.
    """
    paths = []
    # posix=True handles both $HOME and quoted tokens correctly
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for tok in tokens:
        if tok.endswith(".py") or tok.endswith(".ps1"):
            paths.append(tok)
    return paths


def walk_hooks(obj, paths):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "command" and isinstance(v, str):
                paths.extend(_extract_script_paths(v))
            elif k == "args" and isinstance(v, list):
                paths.extend(
                    arg for arg in v
                    if isinstance(arg, str)
                    and (arg.endswith(".py") or arg.endswith(".ps1"))
                )
            else:
                walk_hooks(v, paths)
    elif isinstance(obj, list):
        for item in obj:
            walk_hooks(item, paths)


def walk_mcp_args(obj, paths):
    """Walk MCP server configs; script paths live in args: [...] arrays."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "args" and isinstance(v, list):
                for arg in v:
                    if isinstance(arg, str) and (arg.endswith(".py") or arg.endswith(".ps1")):
                        paths.append(arg)
            else:
                walk_mcp_args(v, paths)
    elif isinstance(obj, list):
        for item in obj:
            walk_mcp_args(item, paths)


def check_file(path, walker):
    if not os.path.exists(path):
        return [], []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"error: cannot parse {path}: {e}", file=sys.stderr)
        print("hint: fix the JSON syntax (or remove the file) and re-run Check 5", file=sys.stderr)
        sys.exit(2)
    raw = []
    walker(data, raw)
    bad = []
    for p in raw:
        resolved = _normalize(p)
        if not os.path.isabs(resolved):
            # Hook commands use `run-hook <name>.py` — the name is looked up
            # relative to ~/.claude/hooks/, not the cwd.
            candidate = os.path.join(CLAUDE_DIR, "hooks", resolved)
            if os.path.exists(candidate):
                continue
            resolved = os.path.join(CLAUDE_DIR, resolved)
        if not os.path.exists(resolved):
            bad.append((p, resolved))
    return raw, bad


def main():
    targets = [
        (str(CLAUDE_DIR / "settings.json"), walk_hooks),
        (str(CLAUDE_DIR / "settings.local.json"), walk_hooks),
        (str(Path.home() / ".mcp.json"), walk_mcp_args),
        (str(Path.home() / ".claude.json"), walk_mcp_args),
    ]
    total = 0
    all_bad = []
    targets_found = 0
    for path, walker in targets:
        if os.path.exists(path):
            targets_found += 1
        raw, bad = check_file(path, walker)
        total += len(raw)
        all_bad.extend((path, p, r) for p, r in bad)

    # No-silent-skip: if every documented config target is missing, surface
    # a WARN rather than silently reporting "0 paths verified". This honors
    # SKILL.md Success Criteria ("All 11 checks run to completion -- no
    # silent skips") -- a check with zero inputs should explain why.
    if targets_found == 0:
        print(f"Paths: WARN — 0/{len(targets)} config targets found; nothing to verify")
        for path, _ in targets:
            print(f"  missing: {path}")
        sys.exit(1)

    if all_bad:
        print(f"Paths: FAIL - {len(all_bad)}/{total} broken paths")
        for config, original, resolved in all_bad:
            print(f"  {config}: {original} -> {resolved} (not found)")
        sys.exit(1)
    print(f"Paths: PASS - {total} paths verified")


if __name__ == "__main__":
    main()
