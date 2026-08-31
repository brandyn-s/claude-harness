"""PostToolUseFailure hook: classify bash errors and suggest specific fixes."""
import json
import re
import sys

ERROR_PATTERNS = [
    (r"ModuleNotFoundError: No module named '(\w+)'",
     lambda m: f"[bash-fix] Module '{m.group(1)}' not found. Try: "
               f"python3 -m pip install {m.group(1)}"),
    (r"python3.*MSYS2",
     lambda m: "[bash-fix] python3 resolved to the MSYS2 interpreter (Windows-only). Use the full interpreter path; on macOS python3 is Homebrew /opt/homebrew/bin/python3."),
    (r"cannot rebase.*unstaged changes",
     lambda m: "[bash-fix] Dirty working tree. Run: git stash --include-untracked && git rebase && git stash pop"),
    (r"CONFLICT.*Merge conflict|error: could not apply",
     lambda m: "[bash-fix] Merge conflict. Run: git status, resolve, git add, git rebase --continue"),
    (r"HTTP 404.*Not Found.*github",
     lambda m: "[bash-fix] GitHub 404. Check repo name, org, --repo flag for forks, gh auth status"),
    (r"HTTP 403.*Forbidden",
     lambda m: "[bash-fix] GitHub 403. Run: gh auth status, maybe gh auth refresh"),
    (r"Unable to locate credentials|ExpiredToken|Token has expired",
     lambda m: "[bash-fix] AWS credentials expired. Run: export AWS_PROFILE=example && aws sso login --profile example"),
    (r"Cannot find module|MODULE_NOT_FOUND",
     lambda m: "[bash-fix] Node module not found. Run: npm install"),
    (r"EPERM|Permission denied|Access is denied",
     lambda m: "[bash-fix] Permission denied. Check if file is locked by another process."),
    (r"SyntaxError.*unexpected EOF|SyntaxError.*unterminated string",
     lambda m: "[bash-fix] Python syntax error from inline code. Write to a .py file first."),
]

def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        return
    if hook_input.get("tool_name") != "Bash":
        return
    # PostToolUse hook input — Claude Code's canonical field is `tool_response`;
    # older versions used `tool_result` and a few MCP-only paths use bare
    # `response`. Read all three to be schema-compatible across versions.
    tool_result = (
        hook_input.get("tool_response")
        or hook_input.get("tool_result")
        or hook_input.get("response")
        or ""
    )
    error_text = f"{hook_input.get('tool_error', '')} {tool_result}"
    for pattern, suggestion_fn in ERROR_PATTERNS:
        match = re.search(pattern, error_text, re.IGNORECASE)
        if match:
            print(json.dumps({"result": "info", "message": suggestion_fn(match)}))
            return

if __name__ == "__main__":
    main()
