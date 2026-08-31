"""PreToolUse:Read hook: deterministically enforce Read(...) permissions.deny rules.

Compensating control for anthropics/claude-code #88795 (+ #88770): on v2.1.239
with defaultMode "auto", Read-tool deny rules in settings.json are silently not
enforced (locally CONFIRMED 2026-08-22 — a Read of a path matching
Read(**/.env) returned file contents with no denial). This hook re-implements
the deny check at the hook layer, which fires independently of the permission
engine.

Behavior:
- Loads permissions.deny from ~/.claude/settings.json and
  ~/.claude/settings.local.json at every invocation (live state, no caching).
- Considers only Read(<pattern>) rules.
- Matches the requested file_path (expanded) AND its realpath (symlink evasion)
  against each pattern with **-aware glob semantics.
- On match: exit 2 with an explanation (blocks the Read).
- On any internal error: exit 0 (fail-open, consistent with sibling guards).

Retire when #88795 is fixed upstream AND a live probe confirms deny
enforcement (see gather-claude 2026-08-22 finding).

INTERRUPTION: safe — read-only; no state is written.
"""

import json
import os
import re
import sys

DEFAULT_SETTINGS_FILES = [
    os.path.expanduser("~/.claude/settings.json"),
    os.path.expanduser("~/.claude/settings.local.json"),
]


def settings_files():
    """Resolve settings paths at call time (live state, no caching).

    CLAUDE_READ_DENY_SETTINGS (os.pathsep-separated) overrides the default
    live paths. Required for hermetic tests: a CI runner has no
    ~/.claude/settings.json, so the 2026-08-22 E2E tests read zero deny
    patterns and failed on every runner while passing locally.
    """
    override = os.environ.get("CLAUDE_READ_DENY_SETTINGS")
    if override:
        return [os.path.expanduser(p) for p in override.split(os.pathsep) if p]
    return DEFAULT_SETTINGS_FILES


def _glob_regex(pat):
    """Translate a permissions-rule glob to an anchored regex.

    ** crosses directory separators (a leading `**/` also matches zero
    directories); * and ? stay within one path segment. Hand-rolled because
    PurePosixPath.full_match is Python 3.13+ and this hook must enforce on
    every interpreter the fleet runs (CI measured 2026-08-22: on older
    Pythons the AttributeError escaped path_matches and the guard silently
    failed OPEN).
    """
    out = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if pat.startswith("**/", i):
                out.append(r"(?:.*/)?")
                i += 3
            elif pat.startswith("**", i):
                out.append(r".*")
                i += 2
            else:
                out.append(r"[^/]*")
                i += 1
        elif c == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def load_read_deny_patterns():
    patterns = []
    for path in settings_files():
        try:
            with open(path, encoding="utf-8") as f:
                deny = json.load(f).get("permissions", {}).get("deny", [])
        except (OSError, json.JSONDecodeError):
            continue
        for rule in deny:
            if isinstance(rule, str) and rule.startswith("Read(") and rule.endswith(")"):
                patterns.append(rule[5:-1].strip())
    return patterns


def normalize(p):
    # posix-style, expanduser, absolute where possible
    p = os.path.expanduser(p)
    return p.replace("\\", "/")


def path_matches(file_path, pattern):
    pat = normalize(pattern)
    fp = normalize(file_path)
    candidates = {fp}
    try:
        candidates.add(os.path.realpath(fp).replace("\\", "/"))
    except OSError:
        pass
    # A bare relative pattern like **/.env must match at any depth, including
    # the top level; _glob_regex's `(?:.*/)?` translation of a leading `**/`
    # covers both.
    try:
        rx = _glob_regex(pat)
    except re.error:
        return False
    return any(rx.match(cand) for cand in candidates)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        hook_input = json.loads(raw)
    except Exception:
        sys.exit(0)

    if hook_input.get("tool_name", "Read") != "Read":
        sys.exit(0)
    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    try:
        patterns = load_read_deny_patterns()
        for pat in patterns:
            if path_matches(file_path, pat):
                print(
                    f"[read-deny-guard] BLOCKED: {file_path} matches permissions.deny rule "
                    f"Read({pat}). Deny rules are not enforced by the permission engine "
                    "on this build (claude-code #88795); this hook enforces them. "
                    "If this file is genuinely needed, ask the user for explicit "
                    "approval and access it through an approved path.",
                    file=sys.stderr,
                )
                sys.exit(2)
    except Exception:
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
