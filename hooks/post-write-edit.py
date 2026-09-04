"""Consolidated PostToolUse:Write|Edit hook.

Checks on every file write/edit:
  - check-python-encoding: warn on open() without encoding='utf-8'
  - py-compile-check: syntax check .py files
  - ruff-lint-fix: auto-fix pyflakes errors (unused imports, f-string issues)
  - secret-scan-file: regex scan for secret patterns

Auto-checkpoint removed 2026-04-13 — Claude Code built-in session persistence
handles crash recovery. Checkpoint commits caused wrong-branch contamination,
squash confusion, and force-push risk. (44 checkpoint commits in 30 days,
0 crashes recovered.)
"""

import json
import os
import py_compile
import re
import subprocess
import sys

# Windows: suppress console windows for git subprocess calls
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _docstring_line_mask(lines):
    """Return list[bool] — True if line[i] is inside a triple-quoted
    string literal (module docstring, function docstring, or multi-line
    string assignment). Used by check_python_encoding to skip matches
    inside string contents — they're not executed Python.

    Mirrors the same logic in bin/audit-skill.py so the hook agrees with
    audit-skill's C5 detection on what counts as a real source-level call.
    """
    in_doc = [False] * len(lines)
    state = None  # None, '"""', or "'''"
    for i, line in enumerate(lines):
        if state is None:
            # Look for an opening triple quote that's not also closed.
            for delim in ('"""', "'''"):
                if delim in line:
                    # Count occurrences; odd = state flips at end of line.
                    if line.count(delim) % 2 == 1:
                        # Opening triple-quote: this line is partially in
                        # a string from the delim onward; mark next line.
                        state = delim
                        break
        else:
            in_doc[i] = True
            if state in line and line.count(state) % 2 == 1:
                state = None
    return in_doc


def _looks_like_string_literal(line, match_start):
    # Heuristic: True if `match_start` is inside a string literal on
    # the given `line`. Tracks four states (single, double,
    # triple-single, triple-double) so a same-line triple-quoted
    # assignment like `cmd = (triple)python -c "..." (triple)` is
    # correctly recognized as in-string. Without triple-quote
    # awareness, the 3 quote chars individually toggle a single-quote
    # state, ending in_double=True; a subsequent embedded " then flips
    # it off mid-string, mis-reporting the `open(` as outside any
    # literal.
    #
    # 2026-05-26 audit-rules A1 probe: test_bash_security_guard.py
    # has pre-existing `cmd = (triple)python -c "...open('foo')..."(triple)`
    # patterns this heuristic was mis-classifying, pinning the file
    # as un-editable on every Edit/Write.
    "Detect whether a position lies inside a Python string literal."
    state = None  # None | "'" | '"' | "'''" | '"""'
    i = 0
    while i < match_start:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        # Triple-quote detection takes precedence over single-quote.
        if state is None and line[i:i + 3] == '"""':
            state = '"""'
            i += 3
            continue
        if state is None and line[i:i + 3] == "'''":
            state = "'''"
            i += 3
            continue
        if state == '"""' and line[i:i + 3] == '"""':
            state = None
            i += 3
            continue
        if state == "'''" and line[i:i + 3] == "'''":
            state = None
            i += 3
            continue
        # Inside a triple-quote, lone " or ' do NOT toggle state.
        if state in ('"""', "'''"):
            i += 1
            continue
        if ch == "'" and state in (None, "'"):
            state = "'" if state is None else None
        elif ch == '"' and state in (None, '"'):
            state = '"' if state is None else None
        i += 1
    return state is not None


def check_python_encoding(file_path, content):
    """Block on open() calls without encoding='utf-8' in Python files.

    Upgraded from warn to block 2026-04-21 — audit-rules measured 35.8% session
    violation rate despite the warn-level notice. Silent cp1252 corruption on
    Windows is the exact fail-silent pattern hooks should enforce.

    2026-05-22: audit-rules synthetic-probe analysis (PR #947 then probe) showed
    the prior "require an explicit mode literal" gate missed no-mode opens like
    `open('settings.json')` — Python defaults to text-read, cp1252 still
    corrupts. All 5 sampled audit-rules excerpts were no-mode opens. Now fires
    on any open() that lacks `encoding=` and is not explicitly binary mode.

    2026-05-26: skip matches inside triple-quoted docstrings and single-line
    string literals. The previous version false-fired ~4 times per session on
    audit-skill.py / its test fixtures (lint-of-lint code that legitimately
    has `open(` literals in docstrings and test-fixture string args). Mirrors
    bin/audit-skill.py's C5 detection logic so the hook agrees with the
    canonical detector on what counts as a real source-level call.
    """
    missing = []
    binary_modes = (
        "'rb'", '"rb"', "'wb'", '"wb"', "'ab'", '"ab"',
        "'rb+'", '"rb+"', "'wb+'", '"wb+"', "'ab+'", '"ab+"',
        "'r+b'", '"r+b"', "'w+b'", '"w+b"', "'a+b'", '"a+b"',
    )
    lines = content.splitlines()
    in_doc = _docstring_line_mask(lines)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if in_doc[i - 1]:
            continue
        # `(?<![\w.])` rejects both `urlopen(` (preceded by word char) AND
        # `os.open(` / `Path.open(` (preceded by `.`). os.open returns a
        # file descriptor and never accepts encoding — flagging it is a
        # false positive (2026-05-26 audit-rules probe).
        for match in re.finditer(r"(?<![\w.])open\s*\(", line):
            if _looks_like_string_literal(line, match.start()):
                continue
            rest = line[match.start():]
            if any(m in rest for m in binary_modes):
                continue
            if "encoding" in rest:
                continue
            missing.append(i)
    if missing:
        lines_str = ", ".join(f"line {n}" for n in missing)
        # cp1252 corruption is WINDOWS-ONLY; macOS/Linux open() defaults to
        # UTF-8. On non-Windows, DOWNGRADE the hard block to a portability
        # WARN — the file is durable and could later run on Windows, so the
        # encoding= nudge is worth keeping, but blocking the write was ~73
        # false stops/14d on this macOS host (2026-06-27 friction audit).
        # The CLAUDE_ENCODING_GUARD_FORCE override keeps the block path
        # testable (signature-drift) on a non-Windows CI host.
        if sys.platform == "win32" or os.environ.get("CLAUDE_ENCODING_GUARD_FORCE") == "1":
            # Block reason MUST keep the exact substring "without encoding='utf-8' at"
            # — scan_violations RULE_BLOCK_SIGNATURES + the drift probe match it.
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": (
                            f"{os.path.basename(file_path)}: open() without "
                            f"encoding='utf-8' at {lines_str}. Windows defaults to "
                            f"cp1252 and silently corrupts non-ASCII content. "
                            f"Add encoding='utf-8' and re-save."
                        ),
                    }
                )
            )
        else:
            # WARN path deliberately AVOIDS the block-signature substring so the
            # transcript scanner correctly categorizes this as net-silent
            # (allowed), not block-then-fix.
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
                            f"[encoding] {os.path.basename(file_path)}: open() at "
                            f"{lines_str} lacks an explicit encoding=. Add "
                            f"encoding='utf-8' for Windows portability "
                            f"(harmless on macOS/Linux; cp1252-corrupts on Windows)."
                        )},
                    }
                )
            )


_CRLF_REPLACE_PATTERN = re.compile(r"\.replace\s*\(\s*['\"][^'\"]*\\n[^'\"]*['\"]")
_FILE_READ_PATTERN = re.compile(r"\b(?:open\s*\([^)]*['\"][wra][+b]?['\"]|\.read_text\s*\(|\.read\s*\()")


def check_str_replace_crlf(file_path, content):
    """Warn on .replace('\\n', ...) in Python files that also read text files.

    Risk: on Windows, text-mode reads translate CRLF→LF, but binary reads or
    non-UTF-8 reads leave CRLF intact; .replace('\\n', X) then silently fails.
    Promoted from bulk-api-script Step 5 after audit-rules (2026-04-21) showed
    21% session rate post-embedding — the rule needed broader surface.

    Heuristic: only flag when the same file also performs a file read, to
    reduce false positives on pure in-memory string manipulation.
    """
    if not _CRLF_REPLACE_PATTERN.search(content):
        return
    if not _FILE_READ_PATTERN.search(content):
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
                    f"{os.path.basename(file_path)}: .replace('\\n', ...) used "
                    f"alongside a file read. On Windows, CRLF endings in the "
                    f"source can make this silently no-op. Verify the read "
                    f"opened in binary mode or that line endings are known."
                )},
            }
        )
    )


def check_py_compile(file_path):
    """Check Python syntax with py_compile."""
    try:
        py_compile.compile(file_path, doraise=True)
    except py_compile.PyCompileError as e:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": f"Syntax error in {os.path.basename(file_path)}: {e.msg}"},
                }
            )
        )


def _repo_ruff_config_exists(file_path):
    """True if the edited file's own project configures ruff.

    Walks parent directories from the file up to (and including) the git root,
    or to the filesystem root when the file is not in a git repository.
    A pyproject.toml counts only if it contains a [tool.ruff] table.
    """
    directory = os.path.dirname(os.path.abspath(file_path))
    while True:
        for name in ("ruff.toml", ".ruff.toml"):
            if os.path.isfile(os.path.join(directory, name)):
                return True
        pyproject = os.path.join(directory, "pyproject.toml")
        if os.path.isfile(pyproject):
            try:
                with open(pyproject, encoding="utf-8") as handle:
                    if "[tool.ruff" in handle.read():
                        return True
            except OSError:
                pass
        if os.path.exists(os.path.join(directory, ".git")):
            return False
        parent = os.path.dirname(directory)
        if parent == directory:
            return False
        directory = parent


def check_ruff_lint(file_path):
    """Auto-fix lint errors using the project's ruff config.

    Runs `ruff check --fix` which auto-fixes any fixable violations.
    Excludes F401 (unused import) from auto-fix — sequential Edit calls
    can create intermediate states where a newly-added import appears
    unused because the code using it hasn't been changed yet.

    RUF100 is marked unfixable so this hook never DELETES a `# noqa`
    directive. When the edited project has no ruff.toml / pyproject.toml,
    ruff falls back to its default select (E4, E7, E9, F) — so a noqa for
    any rule outside that small set looks "unused" to RUF100 and gets
    auto-removed, even though the project's real CI config selects it.

    Measured 2026-08-15 with ruff 0.16.1, running this hook's exact command
    in a config-less directory:

        before:  X = "...oauth/token"  # noqa: S105
                 Y = 1                 # noqa: E501
        after:   X = "...oauth/token"
                 Y = 1

    Both directives silently removed, and `ruff check` WITHOUT --fix
    reported "All checks passed" — so nothing surfaced the deletion.

    Real consequence: example-org/usb-exemption-slack has no ruff
    config (its CI synthesizes select = E,W,F,I,B,S,UP) and main relies on
    `# noqa: S105` for LINEAR_TOKEN_URL. Any edit to services/linear.py
    dropped that suppression and turned CI red on a line the author never
    touched. Hit twice in one session, on two different files.

    --extend-unfixable (rather than --ignore) so a project that genuinely
    selects RUF100 still has a truly-unused noqa REPORTED by its own lint
    gate; only the destructive auto-fix is withheld. Verified with a
    negative control that a real fixable violation (F541) is still fixed
    with the flag present.

    CONFIG-LESS REPOS GET A PINNED SELECT (2026-08-27). The paragraph above
    assumed the config-less fallback is the narrow E4/E7/E9/F set. Measured
    on Homebrew ruff 0.16.4: `ruff check --isolated --show-settings` resolves
    413 enabled rules across 38 families (I, SIM, UP, PT, ...), and an
    unsorted-import control file is flagged I001 under --isolated. So in any
    repo without its own ruff config, --fix rewrote WHOLE files (import
    resorting, SIM117 restructuring) far beyond the edit — measured as
    ~500 lines of review churn on a 370-line change in mcp-infra, which has
    no ruff config. When the repo does not configure ruff, this hook now
    pins --isolated --select E4,E7,E9,F (the set this function was designed
    around); a repo that DOES configure ruff keeps its own config verbatim.
    """
    command = ["ruff", "check", "--fix", "--quiet",
               "--per-file-ignores", f"{file_path}:F401",
               "--extend-unfixable", "RUF100"]
    if not _repo_ruff_config_exists(file_path):
        command += ["--isolated", "--select", "E4,E7,E9,F"]
    command.append(file_path)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stderr:
            fixed_count = result.stderr.count("Fixed")
            if fixed_count:
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "PostToolUse",
                                "additionalContext": f"ruff auto-fixed {fixed_count} lint issue(s) in {os.path.basename(file_path)}; re-read before further edits",
                            }
                        }
                    )
                )
    except FileNotFoundError:
        pass
    except Exception:  # noqa: S110, BLE001 -- fail-open: the ruff advisory must never break the write
        pass  # fail-open: advisory only


_SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{20,}', "API key"),
    (
        r'(?i)(secret|password|passwd|token)\s*[=:]\s*["\'][^"\']{8,}',
        "Secret/password/token",
    ),
    (r"tskey-api-[A-Za-z0-9]+-[A-Za-z0-9]+", "Tailscale API key"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI/Anthropic API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r'(?i)fernet[_-]?key\s*[=:]\s*["\']?[A-Za-z0-9_\-]{43}=', "Fernet key"),
]

# JSON/YAML/TOML/cfg/ini files are NOT skipped for secret scanning —
# config files are exactly where secrets land in practice. The prior
# allowlist silenced the scanner on the highest-risk file types. Only
# pure documentation extensions stay exempt.
_SECRET_SKIP_EXT = {
    ".md", ".txt", ".lock",
}
_SECRET_SKIP_NAMES = {"example", "template", "sample", "test", "mock", "fake", "dummy"}

# Secret scanning reads the file via `f.read(SECRET_SCAN_BYTES_CAP)` at
# the call site. The cap exists so a 100MB binary or generated artifact
# can't blow the hook's memory; bumping from 50KB → 1MB keeps secret-
# scanning honest on common config files (kubeconfig, large terraform
# state, big .env files) without making the hook unbounded.
SECRET_SCAN_BYTES_CAP = 1_000_000


def check_secrets(file_path, content):
    """Scan for secret patterns in non-exempt files."""
    _, ext = os.path.splitext(file_path)
    if ext.lower() in _SECRET_SKIP_EXT:
        return
    basename = os.path.basename(file_path).lower()
    if any(p in basename for p in _SECRET_SKIP_NAMES):
        return
    findings = [
        desc for pattern, desc in _SECRET_PATTERNS if re.search(pattern, content)
    ]
    if findings:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": f"Possible secrets in {os.path.basename(file_path)}: {', '.join(findings)}"},
                }
            )
        )


_CLAUDE_DIR = os.path.expanduser("~/.claude")

# Patterns for files that have co-located manifests
_MANIFEST_COMPANIONS = [
    # (file pattern, manifest path template)
    (r"[/\\]skills[/\\]([^/\\]+)[/\\]SKILL\.md$", "skills/{}/manifest.yaml"),
    (r"[/\\]hooks[/\\]([^/\\]+)\.py$", "hooks/manifests/{}.yaml"),
    (r"[/\\]rules[/\\]([^/\\]+)\.md$", "rules/manifests/{}.yaml"),
]


def check_manifest_drift(file_path):
    """Warn when a skill, hook, or rule is edited but its manifest may be stale."""
    normalized = file_path.replace("\\", "/")
    for pattern, template in _MANIFEST_COMPANIONS:
        match = re.search(pattern, normalized)
        if match:
            name = match.group(1)
            # Skip non-component files
            if name.startswith("_") or name == "manifests":
                return
            manifest_rel = template.format(name)
            manifest_path = os.path.join(_CLAUDE_DIR, manifest_rel)
            if os.path.isfile(manifest_path):
                # Check if manifest is older than the source file
                try:
                    src_mtime = os.path.getmtime(file_path)
                    man_mtime = os.path.getmtime(manifest_path)
                    if src_mtime > man_mtime:
                        print(
                            f"NOTICE: {os.path.basename(file_path)} was modified — "
                            f"manifest at {manifest_rel} may be stale. "
                            f"Run: python ~/.claude/manifests/compile.py --check",
                            file=sys.stderr,
                        )
                except OSError:
                    pass
            return


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path or not os.path.isfile(file_path):
        return

    content = ""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(SECRET_SCAN_BYTES_CAP)
    except OSError:
        pass

    if file_path.endswith(".py"):
        check_python_encoding(file_path, content)
        check_str_replace_crlf(file_path, content)
        check_py_compile(file_path)
        check_ruff_lint(file_path)

    check_secrets(file_path, content)
    check_manifest_drift(file_path)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)