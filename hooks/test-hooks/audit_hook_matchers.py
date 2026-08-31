"""Two-layer trigger-surface audit for Claude Code hooks.

Motivated by 2026-04-19 finding: auto-topic-loader.py had STATIC_MAP and
STATIC_RULE_MAP entries for 7 tool prefixes that its settings.json matcher
didn't cover. The inner logic knew about Tavily/Exa/WebSearch; the outer
registration didn't fire on them. PR #663 was dead for hours.

This script verifies, for every hook registered in settings.json:
  1. Extract the matcher regex
  2. Read the hook script; extract tool prefixes from ast dict assignments
     whose keys look like tool names (mcp__*, WebSearch, WebFetch, etc.)
  3. Check each prefix against the matcher regex
  4. Report mismatches (inner entry without outer match)

Exit code: 0 on clean audit, 1 on mismatch found.

Run via:
    python audit_hook_matchers.py
    python audit_hook_matchers.py --format json
"""
from __future__ import annotations
import argparse
import ast
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Default to the installed location (~/.claude/) so the script works
# in the deployed setting. Fall through to the repo root when no
# settings.json is at ~/.claude/ — covers CI runners and contributor
# checkouts where the repo isn't installed yet. Existing tests
# monkey-patch CLAUDE_ROOT after import, so the redirect still works.
_HOME_CLAUDE = Path.home() / ".claude"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CLAUDE_ROOT = _HOME_CLAUDE if (_HOME_CLAUDE / "settings.json").exists() else _REPO_ROOT
SETTINGS_PATH = CLAUDE_ROOT / "settings.json"
HOOKS_DIR = CLAUDE_ROOT / "hooks"

# Regex that identifies "tool-name-like" strings. Covers MCP prefixes and
# Claude Code built-in tools that can appear as dict keys in hook code.
TOOL_NAME_PATTERN = re.compile(
    r"^(mcp__[\w-]+__|WebSearch$|WebFetch$|Bash$|Read$|Write$|Edit$|Glob$|Grep$|Agent$|Skill$|ToolSearch$|Task$)"
)


def extract_hook_registrations(settings: dict) -> list[dict]:
    """Walk settings.json['hooks'] and extract (event, matcher, script) triples.

    Scripts are identified from exec-form ``args`` first, with legacy command
    strings retained for backwards compatibility.
    """
    out = []
    hooks_section = settings.get("hooks", {})
    for event_name, event_entries in hooks_section.items():
        if not isinstance(event_entries, list):
            continue
        for entry in event_entries:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher", "")
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                args = hook.get("args", [])
                script = next(
                    (
                        Path(arg).name for arg in args
                        if isinstance(arg, str) and arg.endswith(".py")
                    ),
                    None,
                ) if isinstance(args, list) else None
                if script is None:
                    # Legacy: "... hooks/run-hook script-name.py".
                    m = re.search(r"([\w\-]+\.py)\s*$", cmd)
                    script = m.group(1) if m else None
                if script:
                    out.append({
                        "event": event_name,
                        "matcher": matcher,
                        "script": script,
                        "command": cmd[:100],
                    })
    return out


def extract_tool_prefixes_from_script(script_path: Path) -> list[str]:
    """Parse a hook script; find dict literal assignments whose keys look
    like tool names. Return the flattened list of those keys.

    Specifically targets patterns like:
        STATIC_MAP = {"mcp__...": ..., "mcp__...": ...}
        STATIC_RULE_MAP = {...}
    """
    if not script_path.exists():
        return []
    try:
        src = script_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError):
        return []

    prefixes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not isinstance(node.value, ast.Dict):
                continue
            # Only consider dicts with purely string keys that match tool patterns
            tool_keys = []
            for key_node in node.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    if TOOL_NAME_PATTERN.match(key_node.value):
                        tool_keys.append(key_node.value)
            # Only count this dict if MOST of its keys look like tool names
            # (avoids false-positive on general dicts)
            if node.value.keys and tool_keys and len(tool_keys) / len(node.value.keys) >= 0.5:
                prefixes.extend(tool_keys)

    return prefixes


def matcher_covers(matcher: str, tool_name: str) -> bool:
    """Test whether a settings.json matcher regex matches a tool name.

    Claude Code matchers are anchored-start regexes; they match if the
    regex matches the start of the tool name. Use fullmatch-or-match
    semantics to be safe.
    """
    if not matcher:
        # No matcher = matches everything (some hooks omit matcher)
        return True
    try:
        p = re.compile(matcher)
    except re.error:
        return False
    return bool(p.match(tool_name))


def audit() -> tuple[list[dict], list[dict]]:
    """Run the audit. Return (findings, registrations).

    findings: list of {script, matcher, missing_prefix, event}
    registrations: all hook registrations considered
    """
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    registrations = extract_hook_registrations(settings)

    # Group by script: a script may be registered under multiple matchers
    # (rare but possible). We want to know: is at least ONE matcher covering
    # each inner-map prefix?
    by_script: dict[str, list[dict]] = {}
    for r in registrations:
        by_script.setdefault(r["script"], []).append(r)

    findings = []

    for script, regs in by_script.items():
        script_path = HOOKS_DIR / script
        prefixes = extract_tool_prefixes_from_script(script_path)
        if not prefixes:
            continue

        # For each prefix, does ANY of this script's matchers cover it?
        for prefix in prefixes:
            covered = False
            for r in regs:
                if matcher_covers(r["matcher"], prefix):
                    covered = True
                    break
            if not covered:
                # Report once per (script, prefix). If the script has multiple
                # registrations, pick the narrowest matcher as the "offending" one.
                narrowest = min(regs, key=lambda r: len(r["matcher"]))
                findings.append({
                    "script": script,
                    "event": narrowest["event"],
                    "matcher": narrowest["matcher"],
                    "missing_prefix": prefix,
                })

    return findings, registrations


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    findings, registrations = audit()

    if args.format == "json":
        print(json.dumps({
            "findings_count": len(findings),
            "registrations_considered": len(registrations),
            "findings": findings,
        }, indent=2))
    else:
        print(f"Audited {len(registrations)} hook registration(s) across "
              f"{len({r['script'] for r in registrations})} unique script(s).")
        if args.verbose:
            scripts_with_prefixes = set()
            for r in registrations:
                script_path = HOOKS_DIR / r["script"]
                if extract_tool_prefixes_from_script(script_path):
                    scripts_with_prefixes.add(r["script"])
            print(f"Scripts with tool-prefix maps: {len(scripts_with_prefixes)}")
            for s in sorted(scripts_with_prefixes):
                print(f"  - {s}")

        if not findings:
            print("\nAUDIT CLEAN: every internal tool-prefix entry is covered by "
                  "its hook's settings.json matcher.")
        else:
            print(f"\nFINDINGS: {len(findings)} inner-map entry/entries without "
                  "matching settings.json matcher (dead code):\n")
            by_script_findings: dict[str, list[dict]] = {}
            for f in findings:
                by_script_findings.setdefault(f["script"], []).append(f)
            for script, fs in sorted(by_script_findings.items()):
                print(f"  {script}:")
                print(f"    matcher: {fs[0]['matcher']!r}")
                print(f"    event: {fs[0]['event']}")
                print(f"    dead prefixes ({len(fs)}):")
                for f in fs:
                    print(f"      - {f['missing_prefix']}")
                print()
            print("Fix: broaden the matcher regex OR remove the dead inner-map "
                  "entry. See PR #669 for an example.")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
