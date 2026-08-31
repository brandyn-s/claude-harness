#!/usr/bin/env python3
"""Mechanical lint of a skill's external contract and content hygiene.

Usage:
    bin/audit-skill.py <skill-name> [--strict]
    bin/audit-skill.py --all [--strict]

Runs structural checks that don't require execution. The agent slash
command `/audit-skill` wraps this and adds the runtime checks that
need interpretation (literal command execution, invariant verification,
writer/reader format alignment).

Categories (see also: session test-battery characterization):
    H1  references/X.md cited in SKILL.md but missing
    H2  files in references/ never cited anywhere
    (H3 was here — see comment in audit() body for why it was removed.)
    H4  cross-skill citation like `supergoal/references/foo.md` — the
        target skill or ref file must exist (catches typos that H1
        doesn't see because they don't match the bare-form shape).
    H5  backtick-wrapped `<dir>/<...>.md` documentation citation that
        is NOT covered by H1/H4 (i.e., doesn't follow the references/
        convention) must resolve against the skill dir, the skills/
        tree, or the repo root. Caught the 2026-05-27 audit-skill
        self-test finding where SKILL.md cited `oracle/SPEC.md` (which
        actually lives at `_shared/oracle/SPEC.md`).
    M4  SKILL.md frontmatter `allowed-tools` and manifest.yaml
        `requires_tools` should list the same set of tools (modulo
        wildcards) — info severity (doc-consistency; requires_tools
        feeds topic auto-loading, not runtime tool gating). Caught the
        ~12-skill mismatch class surfaced by the 2026-05-28 corpus-wide
        Phase 2 audit.

    Systemic-pattern checks (catch the lessons distilled in
    agent-memory/topics/engineering-philosophy.md "Audit + dev-tooling"
    discipline — i.e., not bugs but structural-discipline gaps):
    B1  Skill ships executable scripts/*.py but has no tests/ — the
        "reasoned-about ≠ tested" gap. Info severity; tracker 02 is the
        canonical worklist.
    P1  SKILL.md uses an unresolved template placeholder ({baseDir},
        <your-X>, ${SCRIPTS} outside of declarations). The {baseDir}
        bug we shipped in this session; drift severity.
    Q1  SKILL.md exceeds 5000 words (skill-authoring rule). Info; large
        skills bloat the agent's context budget.
    Q2  Frontmatter `description:` exceeds 1024 chars (Claude Code
        hard limit). Drift; the harness truncates silently above this.
    Q3  Frontmatter `description:` doesn't include WHEN + Do NOT
        use for sections (skill-authoring convention). Info; the
        routing hook needs all three to disambiguate trigger phrases.
    D3a script paths in extracted commands exist
    D3b extracted commands use the deployed convention (~/.claude/skills/...)
        rather than ${CLAUDE_SKILL_DIR} or other inconsistent forms
    D3c every scripts/*.py is referenced somewhere in SKILL.md or
        another script (otherwise: dead-code lint)
    M1  manifest.yaml `required: true` vs SKILL.md `argument-hint:`
        bracket convention (brackets = optional). A repeating contract
        drift pattern in the 2026-05 audit.
    M2  MCP tool declared in frontmatter `allowed-tools` but never
        invoked in the body. Dead tool declaration; complements
        reconcile-skill-tools.py which adds missing declarations.
    T1  Reference to a known-phantom MCP tool name (e.g.,
        `mcp__code-graph__index_status`). The registry of phantom
        names lives at `skills/audit-skill/known-tools.yaml`.
        With --strict-tools, also flags any `mcp__*__*` reference
        not in known_real.

Exit codes:
    0   no findings (or findings only at info level)
    1   one or more findings (only with --strict)

Top-level flags:
    --check-marketplace      runs scripts/build-marketplace.py and asserts
                             marketplace/ + .claude-plugin/ have zero diff.
                             Runs alongside --all by default; suppress with
                             --no-marketplace-check. This is the canonical
                             defense against marketplace drift; a separate
                             "audit each marketplace copy" pass was tried
                             and removed because the builder intentionally
                             prunes references/ and manifests, making the
                             pruned copies fail H1/D3a even when correct.
    --strict-tools           T1 escalation: also flag `mcp__*__*` references
                             not in known_real (the canonical registry).
                             Off by default (registry is incomplete; would
                             false-positive on tools from per-user MCP configs).
"""

import filecmp
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
MARKETPLACE = REPO / "marketplace"

DEPLOYED_PREFIX = "~/.claude/skills/"
# `~/.claude/` is this repo's deployed root, so a citation under it maps onto
# the repo tree and is verifiable without depending on host filesystem state.
DEPLOYED_ROOT = "~/.claude/"
# Template / glob markers that mean a cited path is a pattern, not a real file.
# Mirrors the exclusion find_doc_citations already applies to `.md` citations.
_PATH_PATTERN_MARKER = re.compile(r"[{}\[\]*?<>]|\$\w|\$\{")
INCONSISTENT_PREFIXES = [
    r"\$\{CLAUDE_SKILL_DIR\}",
    r"\$CLAUDE_SKILL_DIR",
]

# Cross-platform compatibility (skills should work on Windows, Mac, Linux).
POSIX_ONLY_PYTHON_MODULES = {
    "fcntl",       # Linux/Mac only; Windows uses msvcrt or filelock
    "pwd",         # Unix user-database; Windows uses different API
    "grp",         # Unix group-database
    "termios",     # Unix terminal control
    "resource",    # Unix resource limits
    "syslog",      # Unix syslog
    "posix",       # explicit POSIX module
}
WINDOWS_INCOMPAT_PATH_PATTERNS = [
    (re.compile(r"(?<![\w/])/tmp/"), "/tmp/ is POSIX-only; use Python tempfile.gettempdir() or pathlib"),
    (re.compile(r"%[A-Z_]+%"), "%VAR% is cmd.exe-only; use $VAR or ~/ for cross-shell compatibility"),
]


# --- C5 / C6 / C7 / C9 / C10 / C8 module-level patterns + helpers.
#
# Lifted from the inner-function scope of `_audit_cross_platform` so the
# repo-wide audit (`_audit_repo_python`, `_audit_repo_shell`) can reuse
# the same logic on bin/, hooks/, root *.py, and *.sh — closing the
# scope gap that let PR #977's 5 sites in `bin/audit-skill.py` ship
# (the per-skill audit never touched bin/). One canonical pattern set
# means new variants get caught in every scope.

C5_READ_TEXT_PAT = re.compile(r"\.read_text\s*\(")
C5_WRITE_TEXT_PAT = re.compile(r"\.write_text\s*\(")
# Bare `open(` or method-call `.open(`. Exclude any dotted method whose
# receiver looks like an OS/socket/IO module with its own open semantics
# (os.open is a low-level fd; no encoding kwarg).
C5_OPEN_PAT = re.compile(r"(?<!\w)open\s*\(|(?<![\w.])\.open\s*\(")
C5_OS_OPEN_PREFIX = re.compile(r"(?:os|socket|posix|nt)\.open\s*\(")
# Binary-mode markers — if any appears in the call's argument list
# (possibly across continuation lines), treat the open as binary.
C5_BINARY_MODES = (
    "'rb'", '"rb"', "'wb'", '"wb"', "'ab'", '"ab"',
    "'rb+'", '"rb+"', "'wb+'", '"wb+"', "'ab+'", '"ab+"',
    "'r+b'", '"r+b"', "'w+b'", '"w+b"', "'a+b'", '"a+b"',
    "'xb'", '"xb"',
)
# Multi-line continuation lookahead: when a write_text / read_text /
# open call doesn't close on the same line, scan forward this many
# lines for the matching close paren before deciding the call is
# missing encoding=. Covers the
# `(run_dir / "x").write_text(\n    json.dumps(...), encoding="utf-8")`
# idiom that single-line scanning misses.
C5_MULTILINE_LOOKAHEAD = 6

C6_ARGPARSE_HELP_PAT = re.compile(
    r"""help\s*=\s*(['"])(.*?)\1""",
    re.DOTALL,
)
# Any `%` that isn't `%%` (escaped) or `%(` (named-format start).
# Python's `string % dict` formatting fires on `%` + flag chars + letter
# — including `% c` (space-flag, c-conversion). The roundtable bug was
# `~25% cheaper` which crashes with `TypeError: %c requires int or
# char` because Python sees the space as a flag and `c` as the
# conversion type. Anything that isn't `%%` or `%(name)X` is a
# potential argparse-help bomb.
C6_UNESCAPED_PCT = re.compile(r"%(?![%(])")

C9_TMP_LIT_PAT = re.compile(r"['\"]/tmp/[^'\"\s]+['\"]")

C10_BASH_SUBP_PAT = re.compile(
    r"subprocess\.(?:run|check_output|Popen)\s*\(\s*\[\s*['\"]bash['\"]"
)

C8_SED_INLINE_PAT = re.compile(r"\bsed\s+-i\s+(?!['\"])")
C8_DATE_D_PAT = re.compile(r"\bdate\s+-d\b")
C8_XARGS_R_PAT = re.compile(r"\bxargs\s+(-[a-zA-Z]*r[a-zA-Z]*|--no-run-if-empty)\b")


def _call_misses_encoding(lines, idx, match_start):
    """Return True if the call starting at `lines[idx][match_start:]`
    spans through its closing `)` with no `encoding=` token visible.
    Walks forward up to MULTILINE_LOOKAHEAD lines, paren-depth-counting
    to find the matching close. Conservative: returns False (no flag)
    when the close paren isn't found within lookahead.
    """
    depth = 0
    seen_open = False
    for j in range(idx, min(idx + C5_MULTILINE_LOOKAHEAD, len(lines))):
        seg = lines[j][match_start:] if j == idx else lines[j]
        for ch in seg:
            if ch == "(":
                depth += 1
                seen_open = True
            elif ch == ")":
                depth -= 1
                if seen_open and depth <= 0:
                    spanned = (
                        lines[idx][match_start:] +
                        "\n" + "\n".join(lines[idx + 1 : j + 1])
                    )
                    return "encoding" not in spanned
    return False


def _call_is_binary_open(lines, idx, match_start):
    depth = 0
    seen_open = False
    for j in range(idx, min(idx + C5_MULTILINE_LOOKAHEAD, len(lines))):
        seg = lines[j][match_start:] if j == idx else lines[j]
        for ch in seg:
            if ch == "(":
                depth += 1
                seen_open = True
            elif ch == ")":
                depth -= 1
                if seen_open and depth <= 0:
                    spanned = (
                        lines[idx][match_start:] +
                        "\n" + "\n".join(lines[idx + 1 : j + 1])
                    )
                    return any(m in spanned for m in C5_BINARY_MODES)
    return False


def _looks_like_string_literal(line, match_start):
    """Heuristic: is the match position inside a string literal on
    this line? Counts unescaped quotes before match_start; odd → inside.
    Skips '#'-comment lines (caller filters those). False negatives on
    triple-quoted docstrings spanning lines — `_docstring_line_mask`
    covers those.
    """
    before = line[:match_start]
    clean = re.sub(r"\\.", "", before)
    d = clean.count('"')
    s = clean.count("'")
    return (d % 2 == 1) or (s % 2 == 1)


def _docstring_line_mask(lines):
    # Return a list[bool] parallel to `lines`. True means the line is
    # INSIDE a triple-quoted docstring (so its content is prose, not
    # code). Tracks the two triple-quote tokens (double and single,
    # spelled at runtime to avoid breaking out of this function's own
    # docstring). Multi-line companion to _looks_like_string_literal.
    # bash-security-guard.py:894 has the literal text "open()" as prose
    # in a docstring; without this filter the lint matches the
    # docstring text and false-flags.
    triple_dq = '"' * 3
    triple_sq = "'" * 3
    in_doc = [False] * len(lines)
    state = False
    state_quote = None
    for i, ln in enumerate(lines):
        in_doc[i] = state
        j = 0
        while j < len(ln):
            if not state and ln[j:j+3] in (triple_dq, triple_sq):
                state = True
                state_quote = ln[j:j+3]
                j += 3
                continue
            if state and ln[j:j+3] == state_quote:
                state = False
                state_quote = None
                j += 3
                continue
            j += 1
    return in_doc


def _check_c7_help_short_circuit(text, rel):
    """AST-based C7 check: __main__ + sys.argv access without proper
    --help handling.

    The pre-2026-05-26 string-based check skipped any file containing
    `ArgumentParser(` anywhere, which missed the class:

        import argparse
        ap = argparse.ArgumentParser()  # built but never .parse_args()
        target = sys.argv[1]            # hand-rolled positional
        # ... no --help short-circuit, --help becomes positional

    AST detection: returns a Finding iff
      1. The module has an `if __name__ == "__main__":` block
      2. That block (transitively) accesses `sys.argv` (subscript)
      3. The file has NO `parse_args()` call (argparse handles --help
         automatically only if parse_args is actually invoked)
      4. The file has NO `"--help"` / `'--help'` / `"-h"` / `'-h'`
         literal anywhere (signals an explicit short-circuit)
    """
    import ast
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    main_block = _find_main_block(tree)
    if main_block is None:
        return None

    # Walk the main block + any functions transitively called via
    # `main()` style indirection. Simpler approach: scan the WHOLE
    # module body for argv subscript access AFTER the __main__ block
    # exists (the indirection class catches `if __name__ == "__main__":
    # main()` where main() lives at module level).
    has_argv = False
    has_parse_args_call = False
    for node in ast.walk(tree):
        # sys.argv access (Subscript on Attribute or Name)
        if isinstance(node, ast.Subscript):
            val = node.value
            if isinstance(val, ast.Attribute):
                # sys.argv[...]
                if (isinstance(val.value, ast.Name)
                        and val.value.id == "sys"
                        and val.attr == "argv"):
                    has_argv = True
            elif isinstance(val, ast.Name) and val.id == "argv":
                # bare argv (imported via `from sys import argv`)
                has_argv = True
        # parse_args() call — accept any callable whose attribute is
        # `parse_args`. Most argparse usages call this exactly once,
        # via ap.parse_args() or parser.parse_args().
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "parse_args":
                has_parse_args_call = True

    if not has_argv:
        return None
    if has_parse_args_call:
        # argparse handles --help automatically when parse_args fires.
        return None
    if ('"--help"' in text or "'--help'" in text or
            '"-h"' in text or "'-h'" in text):
        # Explicit hand-rolled short-circuit detected via string match;
        # author has handled --help.
        return None

    line = main_block.lineno
    return Finding("C7", "info",
        "script has `__main__` + `sys.argv` access but no "
        "`--help` / `-h` short-circuit (and no `parse_args()` call). "
        "Running `script.py --help` will treat `--help` as a "
        "positional argument. Add a short-circuit "
        "`if any(a in ('-h', '--help') for a in sys.argv[1:]):` "
        "or call argparse's `parse_args()`.",
        path=rel, line=line)


def _find_main_block(tree):
    """Return the `if __name__ == "__main__":` If node, or None."""
    import ast
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Match `__name__ == "__main__"` OR `"__main__" == __name__`.
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        names = {test.left, *test.comparators}
        has_dunder_name = any(
            isinstance(n, ast.Name) and n.id == "__name__" for n in names
        )
        has_main_string = any(
            isinstance(n, ast.Constant) and n.value == "__main__" for n in names
        )
        if has_dunder_name and has_main_string:
            return node
    return None


def _scan_python_file_cross_platform(script, repo_root=None):
    """Run C5/C6/C7/C9/C10 against a single Python file. Returns
    list[Finding] with `path` set to the repo-relative path (or
    absolute if `repo_root` doesn't contain the script).

    Centralizes the per-file detection logic so the per-skill audit
    (`_audit_cross_platform`) and the repo-wide audit
    (`_audit_repo_python`) stay in sync.
    """
    if repo_root is None:
        repo_root = REPO
    findings = []
    try:
        text = script.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings
    try:
        rel = str(script.relative_to(repo_root))
    except ValueError:
        rel = str(script)
    rel_norm = rel.replace("\\", "/")

    lines = text.splitlines()
    in_doc = _docstring_line_mask(lines)

    # C5 — file-I/O without encoding=. Line-by-line scan with multi-line
    # paren-depth lookahead for the call's closing `)` and `encoding=`
    # token. Skip: comment lines, matches inside same-line string
    # literals, AND matches inside multi-line triple-quoted docstrings.
    for line_no, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if in_doc[line_no - 1]:
            continue
        for m in C5_READ_TEXT_PAT.finditer(line):
            if _looks_like_string_literal(line, m.start()):
                continue
            if not _call_misses_encoding(lines, line_no - 1, m.start()):
                continue
            findings.append(Finding("C5", "info",
                "`.read_text(...)` without `encoding='utf-8'` — crashes "
                "on Windows (cp1252 default) for any non-ASCII byte. "
                "Violates platform-constraints.md python_open_always_utf8",
                path=rel, line=line_no))
        for m in C5_WRITE_TEXT_PAT.finditer(line):
            if _looks_like_string_literal(line, m.start()):
                continue
            if not _call_misses_encoding(lines, line_no - 1, m.start()):
                continue
            findings.append(Finding("C5", "info",
                "`.write_text(...)` without `encoding='utf-8'` — "
                "silently mangles non-ASCII on Windows",
                path=rel, line=line_no))
        for m in C5_OPEN_PAT.finditer(line):
            # Skip os.open / socket.open / etc. (no encoding kwarg).
            prefix_text = line[max(0, m.start() - 8):m.end()]
            if C5_OS_OPEN_PREFIX.search(prefix_text):
                continue
            if _looks_like_string_literal(line, m.start()):
                continue
            if _call_is_binary_open(lines, line_no - 1, m.start()):
                continue
            if not _call_misses_encoding(lines, line_no - 1, m.start()):
                continue
            # Variable-spelled message so this file's own source doesn't
            # false-fire the post-write-edit hook on `open(...)` literals.
            _o = "o"
            _msg = f"`{_o}pen(...)` / `.{_o}pen(...)`"
            findings.append(Finding("C5", "info",
                f"{_msg} in text mode without `encoding='utf-8'` — "
                f"crashes on Windows cp1252",
                path=rel, line=line_no))

    # C6 — argparse help= containing literal unescaped `%X`.
    for m in C6_ARGPARSE_HELP_PAT.finditer(text):
        body = m.group(2)
        if C6_UNESCAPED_PCT.search(body):
            line_no = text[:m.start()].count("\n") + 1
            findings.append(Finding("C6", "drift",
                "argparse `help=` contains literal `%X` (unescaped "
                "percent) — `--help` will raise `TypeError: %X requires "
                "int or char`. Escape as `%%` (e.g. `~25%%` not `~25%`)",
                path=rel, line=line_no))

    # C7 — `__main__` + `sys.argv` access without proper `--help` handling.
    # Detection uses AST so a partial-argparse script (imports argparse,
    # builds an ArgumentParser, but also hand-rolls sys.argv processing
    # without calling parse_args() OR with a short-circuit before
    # parse_args()) is correctly flagged. The previous string-based
    # check skipped any file containing `ArgumentParser(` anywhere,
    # missing this class (user-noted "rare but real" in #988 review).
    c7_finding = _check_c7_help_short_circuit(text, rel)
    if c7_finding is not None:
        findings.append(c7_finding)

    # C9 — `/tmp/` literal in Python source. Self-exempt for audit-skill.py
    # (the file contains the lint regex as a string literal).
    if "audit-skill.py" not in rel_norm and "audit_skill.py" not in rel_norm:
        for m in C9_TMP_LIT_PAT.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            if line_end < 0:
                line_end = len(text)
            if text[line_start:line_end].lstrip().startswith("#"):
                continue
            line_no = text[:m.start()].count("\n") + 1
            findings.append(Finding("C9", "info",
                "`/tmp/` literal in Python source — POSIX-only path; "
                "use `tempfile.gettempdir()` or `pathlib.Path.home() / "
                "'tmp'` for cross-platform compatibility",
                path=rel, line=line_no))

    # C10 — bare `subprocess.run(['bash', ...])` without `_resolve_bash`.
    if "_resolve_bash(" not in text:
        for m in C10_BASH_SUBP_PAT.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            if line_end < 0:
                line_end = len(text)
            if text[line_start:line_end].lstrip().startswith("#"):
                continue
            line_no = text[:m.start()].count("\n") + 1
            findings.append(Finding("C10", "drift",
                "`subprocess.run(['bash', ...])` without resolving via "
                "a path-filtering helper — Windows resolves `bash` to "
                "`C:\\Windows\\System32\\bash.exe` (WSL launcher) which "
                "can't read `C:/...` paths. Use "
                "`skills/audit-skill/oracle/finding.py:_resolve_bash` "
                "or equivalent",
                path=rel, line=line_no))
    return findings


def _scan_shell_file_bsd_divergence(sh, repo_root=None):
    """Run C8 against a single *.sh file."""
    if repo_root is None:
        repo_root = REPO
    findings = []
    try:
        text = sh.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings
    try:
        rel = str(sh.relative_to(repo_root))
    except ValueError:
        rel = str(sh)
    for pat, msg in (
        (C8_SED_INLINE_PAT,
         "`sed -i <pattern>` without a backup arg — macOS BSD sed "
         "requires `sed -i '' <pattern>`. Either use the empty-string "
         "backup form or sponge to a temp file"),
        (C8_DATE_D_PAT,
         "`date -d` is GNU-only — macOS uses `date -v`. Either compute "
         "the date offset in a portable language (Python datetime, "
         "$(($(date +%s) - N))) or branch on uname"),
        (C8_XARGS_R_PAT,
         "`xargs -r` / `--no-run-if-empty` is GNU-only — BSD xargs "
         "doesn't accept it. Guard the entire xargs invocation behind "
         "a non-empty check instead"),
    ):
        for m in pat.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            if line_end < 0:
                line_end = len(text)
            if text[line_start:line_end].lstrip().startswith("#"):
                continue
            line_no = text[:m.start()].count("\n") + 1
            findings.append(Finding("C8", "info", msg,
                path=rel, line=line_no))
    return findings


class Finding:
    def __init__(self, code, severity, msg, path=None, line=None):
        self.code = code
        self.severity = severity
        self.msg = msg
        self.path = path
        self.line = line

    def __str__(self):
        loc = ""
        if self.path:
            loc = f" [{self.path}"
            if self.line:
                loc += f":{self.line}"
            loc += "]"
        return f"  {self.code} [{self.severity}]{loc}\n      {self.msg}"


def extract_bash_blocks(md_text):
    """Yield (line_no, command_line) for every command-shaped line
    inside ```bash or ```sh fenced blocks."""
    for _block_assignments, lines in _iter_bash_blocks(md_text):
        for ln, cmd in lines:
            yield ln, cmd


def _iter_bash_blocks(md_text):
    """Yield (var_assignments, [(line_no, command), ...]) per bash block.
    Tracks ANY fenced block boundary (```python, ```yaml, ```bash, ...)
    so non-bash blocks don't confuse close-markers as new bash blocks
    (a prior bug confused line 277 of a markdown doc with a bash command
    because the prose between ```python ... ``` and the next fence was
    misclassified). Only yields content from blocks whose opening fence
    declared a bash-ish language (or no language, treated as bash by
    default — matches the common pattern of bare ``` for shell).

    Bash line-continuations (`\\` at end of line) are joined into a
    single logical command keyed off the first physical line — so
    `python foo.py \\\n  --arg val` yields one entry, not two. Without
    this join, downstream checks (D3a script-path detection, C2 /tmp
    detection) miss content that wraps across lines."""
    fence_open_pat = re.compile(r"^```(\w*)\s*$")
    in_block = False
    is_bash_block = False
    current = []
    pending_line = None    # line_no where the continuation started
    pending_text = ""      # accumulated text across continuations
    for i, line in enumerate(md_text.splitlines(), start=1):
        stripped = line.strip()
        if not in_block:
            m = fence_open_pat.match(stripped)
            if m:
                lang = m.group(1).lower()
                in_block = True
                is_bash_block = lang in ("", "bash", "sh", "shell")
                current = []
                pending_line, pending_text = None, ""
            continue
        # in_block — look for close
        if stripped == "```":
            # Flush any unterminated continuation as-is.
            if pending_line is not None and pending_text:
                current.append((pending_line, pending_text.strip()))
                pending_line, pending_text = None, ""
            if is_bash_block and current:
                yield _collect_assignments(current), current
            in_block = False
            is_bash_block = False
            current = []
            continue
        if is_bash_block:
            if not stripped or stripped.startswith("#"):
                # Comments break a pending continuation only if non-blank.
                if stripped.startswith("#") and pending_line is not None:
                    current.append((pending_line, pending_text.strip()))
                    pending_line, pending_text = None, ""
                continue
            # Strip the trailing `\` if present (line continues).
            continues = stripped.endswith("\\")
            payload = stripped[:-1].rstrip() if continues else stripped
            if pending_line is None:
                pending_line = i
                pending_text = payload
            else:
                pending_text += " " + payload
            if not continues:
                current.append((pending_line, pending_text.strip()))
                pending_line, pending_text = None, ""
    if in_block and is_bash_block:
        if pending_line is not None and pending_text:
            current.append((pending_line, pending_text.strip()))
        if current:
            yield _collect_assignments(current), current


def _collect_assignments(block_lines):
    """Pull `VAR=value` / `export VAR=value` assignments out of a bash
    block. Quote-stripped; no shell expansion attempted."""
    out = {}
    assign_pat = re.compile(r"^(?:export\s+)?([A-Z_][A-Z0-9_]*)=(\S+)$")
    for _ln, cmd in block_lines:
        m = assign_pat.match(cmd)
        if m:
            out[m.group(1)] = m.group(2).strip("'\"")
    return out


def _substitute_vars(raw, var_assignments):
    """Replace $VAR and ${VAR} in `raw` with their values from
    `var_assignments`. Also expands $HOME → ~ if HOME is unset
    (so downstream classification can be path-based)."""
    def replace(m):
        name = m.group(1) or m.group(2)
        if name in var_assignments:
            return var_assignments[name]
        if name == "HOME":
            return "~"
        return m.group(0)
    pat = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)")
    return pat.sub(replace, raw)


def _normalize_path(raw):
    """Strip surrounding quotes and normalize $HOME → ~ so downstream
    classification can be path-based. Returns None for paths that should
    be skipped (template placeholders)."""
    p = raw.strip().strip("'\"")
    if "<" in p and ">" in p:
        return None
    if p.startswith("$HOME/"):
        p = "~/" + p[len("$HOME/"):]
    elif p.startswith("${HOME}/"):
        p = "~/" + p[len("${HOME}/"):]
    return p


def find_script_paths_in_commands(md_text):
    """Yield (line_no, raw_path) for every script path referenced inside
    bash blocks. Looks for python3/bash/sh invocations and bare
    ~/.claude/skills/... paths. Substitutes shell variables defined
    in any earlier block in the same document (`SCRIPTS=...` →
    `$SCRIPTS` becomes that value) so env-var-resolved paths can be
    classified correctly. Doc-wide carryover models how readers
    sequence the tutorial top-to-bottom.

    Skips relative paths inside blocks that `cd` to an external
    absolute path — that changes the shell cwd, so relative paths
    no longer point inside this skill's tree."""
    pat = re.compile(
        r"(?:python3?|bash|sh|uv\s+run|uvx)\s+(\"[^\"\s]+\.(?:py|sh)\"|'[^'\s]+\.(?:py|sh)'|[^\s]+\.(?:py|sh))"
        r"|(~/\.claude/skills/[^\s]+\.(?:py|sh))"
        r"|(\$HOME/\.claude/skills/[^\s]+\.(?:py|sh))"
        r"|(\{baseDir\}/[^\s]+\.(?:py|sh))"
    )
    cd_pat = re.compile(r"^\s*cd\s+(\S+)")
    accumulated_vars = {}
    cwd_changed = False  # doc-wide: once a cd to an external abs path
                         # has occurred, subsequent relative paths are
                         # unverifiable (matches how readers sequence
                         # the tutorial top-to-bottom)
    for var_assignments, block_lines in _iter_bash_blocks(md_text):
        accumulated_vars.update(var_assignments)
        for ln, cmd in block_lines:
            cd_match = cd_pat.match(cmd)
            if cd_match:
                cd_target = _substitute_vars(cd_match.group(1).strip("'\""), accumulated_vars)
                if cd_target.startswith(("/", "~/", "$")):
                    cwd_changed = True
                continue
            for m in pat.finditer(cmd):
                raw = (m.group(1) or m.group(2) or m.group(3) or m.group(4))
                substituted = _substitute_vars(raw, accumulated_vars)
                # {baseDir}/scripts/X.py → scripts/X.py (resolves against
                # the skill's own directory)
                substituted = substituted.removeprefix("{baseDir}/")
                normalized = _normalize_path(substituted)
                if normalized is None:
                    continue
                if "$" in normalized:
                    continue
                if cwd_changed and not normalized.startswith(("/", "~/")):
                    continue
                yield ln, normalized


def find_inconsistent_path_prefixes(md_text):
    """Yield (line_no, prefix) for any non-canonical skill-path prefix
    inside bash blocks. Flags ${CLAUDE_SKILL_DIR} and repo-relative
    skills/<name>/ forms (which break the moment the skill is invoked
    from a deployed ~/.claude/skills/ symlink)."""
    canonical_relative_pat = re.compile(r"(?<![~\w/.\-])skills/[a-z0-9-]+/[\w./-]+\.(?:py|sh)")
    for ln, cmd in extract_bash_blocks(md_text):
        for pat_re in INCONSISTENT_PREFIXES:
            if re.search(pat_re, cmd):
                yield ln, pat_re
        if canonical_relative_pat.search(cmd):
            yield ln, "skills/<name>/... (repo-relative; use ~/.claude/skills/...)"


def find_inline_script_paths(md_text):
    """Yield (line_no, raw_path) for script paths inside single-backtick
    inline code in prose. Matches the same path forms as
    find_script_paths_in_commands but outside fenced bash blocks. This
    catches doc snippets like `python "$SCRIPTS/foo.py" -f <x>` that
    are demonstrated in prose rather than in a fenced ```bash block —
    a real-world pattern in sca-review/SKILL.md line 387 that the
    fenced-block scanner missed. Applies the same variable substitution
    map collected from bash blocks (so $SCRIPTS defined earlier in a
    fenced block expands in prose mentions too)."""
    # Build doc-wide var_assignments from every bash block
    doc_vars = {}
    for var_assignments, _ in _iter_bash_blocks(md_text):
        doc_vars.update(var_assignments)

    inline_pat = re.compile(r"`([^`\n]+)`")
    script_pat = re.compile(
        r"(?:python3?|bash|sh|uv\s+run|uvx)\s+(\"[^\"]+?\.(?:py|sh)\"|'[^']+?\.(?:py|sh)'|\S+?\.(?:py|sh))"
        r"|(~/\.claude/skills/\S+?\.(?:py|sh))"
        r"|(\$HOME/\.claude/skills/\S+?\.(?:py|sh))"
        r"|(\{baseDir\}/\S+?\.(?:py|sh))"
    )
    # Build a per-line index of which lines are inside fenced blocks
    in_block = set()
    fence_open_pat = re.compile(r"^```")
    is_open = False
    for i, line in enumerate(md_text.splitlines(), start=1):
        stripped = line.strip()
        if fence_open_pat.match(stripped):
            if is_open:
                in_block.add(i)
                is_open = False
            else:
                is_open = True
                in_block.add(i)
            continue
        if is_open:
            in_block.add(i)
    for i, line in enumerate(md_text.splitlines(), start=1):
        if i in in_block:
            continue
        for inline_m in inline_pat.finditer(line):
            content = inline_m.group(1)
            for m in script_pat.finditer(content):
                raw = m.group(1) or m.group(2) or m.group(3) or m.group(4)
                substituted = _substitute_vars(raw, doc_vars)
                substituted = substituted.removeprefix("{baseDir}/")
                normalized = _normalize_path(substituted)
                if normalized is None:
                    continue
                if "$" in normalized:
                    continue
                yield i, normalized


def find_reference_citations(md_text):
    """Yield (line_no, ref_path_relative) for every local `references/X.md`
    citation in SKILL.md. Skip cross-skill refs like
    `supergoal/references/X.md` — those are validated by
    find_cross_skill_citations / the H4 check.

    Excludes citations inside fenced code blocks: those are examples
    (YAML snippets demonstrating audit-suppress syntax, bash blocks
    showing how a command renders), not citations the agent will Read.
    Without this guard, a SKILL.md that includes a YAML example
    mentioning `references/example.md` produces a false-positive H1."""
    pat = re.compile(r"(?<![\w/])references/([a-z0-9._-]+\.md)")
    in_fence = False
    for i, line in enumerate(md_text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in pat.finditer(line):
            yield i, m.group(1)


def find_cross_skill_citations(md_text):
    """Yield (line_no, skill_name, ref_filename) for citations that
    reference another skill's tree, like `supergoal/references/foo.md`
    or `skills/supergoal/references/foo.md`. These resolve against
    SKILLS/<skill_name>/references/<ref_filename> — the H4 check
    verifies they exist.

    The lookbehind excludes `\\w` and `-` so the matcher doesn't fire
    in the middle of a hyphenated skill name (e.g., the substring
    `memory-exploring/references/...` inside `codebase-memory-exploring/...`
    would otherwise produce a false positive). It DOES allow `/` so
    `~/.claude/skills/persona/references/X.md`-style absolute paths
    still match starting at the `skills/` prefix; finditer's
    non-overlapping behavior prevents the cross-skill match from
    double-firing inside the same path."""
    # Two shapes: bare `<skill>/references/<ref>.md` and
    # `skills/<skill>/references/<ref>.md` (some docs use the absolute form).
    pat = re.compile(
        r"(?<![\w\-])(?:skills/)?([a-z][a-z0-9-]+)/references/([a-z0-9._-]+\.md)"
    )
    in_fence = False
    for i, line in enumerate(md_text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in pat.finditer(line):
            skill_name, ref_name = m.group(1), m.group(2)
            # The bare `references/X.md` form is captured by
            # find_reference_citations — skip it here so we don't
            # double-fire on local refs.
            if skill_name in ("references",):
                continue
            yield i, skill_name, ref_name


# A backtick-wrapped path is a real citation (something the agent
# should Read) only if the prose says so. Without a read-verb marker
# the same backtick syntax shows up for output paths ("Save as
# `X.md`"), example filenames in tables, illustrative names in
# explanations ("strictly more relevant than `topics/security.md`"),
# etc. — those are not bugs even when the path doesn't resolve.
H5_READ_VERB_RE = re.compile(
    r"(?i)\b(see|read|consult|reference[sd]?|cit(?:e|es|ed|ation)|"
    r"documented\s+in|described\s+in|listed\s+in|defined\s+in|"
    r"specified\s+in)\b"
)


def find_doc_citations(md_text):
    """Yield (line_no, raw_cite) for backtick-wrapped `<segment>/<...>.md`
    documentation citations in SKILL.md prose that are NOT already
    covered by H1/H4.

    H5 territory — citations the agent will try to Read, that follow
    a path-shape but aren't through the `references/` convention.

    Excludes:
    - citations inside fenced code blocks (examples, not refs)
    - bare `references/X.md` (H1 handles)
    - `<skill>/references/X.md` and `skills/<skill>/references/X.md` (H4)
    - absolute / home paths (start with `/` or `~`)
    - paths containing template / glob markers (`$ { } [ ] * ? < >`)
    - single-segment filenames (no `/` — those are usually local names
      already addressed by H2 or live in the skill dir itself)
    - cites with no read-verb (See/Read/Consult/documented-in/...)
      earlier on the same line — those are output paths or illustrative
      names, not references the agent will try to Read."""
    pat = re.compile(r"`([a-zA-Z0-9_./-]+\.md)`")
    lines = md_text.splitlines()
    in_fence = False
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in pat.finditer(line):
            cite = m.group(1)
            if "/" not in cite:
                continue
            if cite.startswith(("/", "~")):
                continue
            if any(c in cite for c in "${}[]*?<>"):
                continue
            parts = cite.split("/")
            # Skip H1 territory: bare `references/X.md`
            if parts[0] == "references" and len(parts) == 2:
                continue
            # Skip H4 territory: `<skill>/references/X.md` and
            # `skills/<skill>/references/X.md`
            if len(parts) >= 3 and parts[-2] == "references":
                continue
            # Read-verb gate, scoped to the current sentence. Build a
            # multi-line context (the cite's line plus up to 2 prior
            # non-blank lines for wrapped sentences), then trim back
            # to the start of the current sentence — anything before
            # the last `.`/`!`/`?` belongs to a different sentence and
            # its verbs don't govern this cite.
            context = line[: m.start()]
            for back in range(1, 3):
                prev_idx = (i - 1) - back
                if prev_idx < 0:
                    break
                prev = lines[prev_idx]
                if not prev.strip():
                    break  # paragraph boundary
                context = prev + "\n" + context
                if re.search(r"[.!?]\s*$", prev.rstrip()):
                    break  # the cite's sentence starts after this line
            # Trim to the current sentence: drop everything up to and
            # including the last terminal-punct boundary.
            sentence_starts = list(re.finditer(r"[.!?](?=\s|\n)", context))
            if sentence_starts:
                context = context[sentence_starts[-1].end():]
            if not H5_READ_VERB_RE.search(context):
                continue
            yield i, cite


def find_marketplace_copies(skill_name):
    """Return list of marketplace/<plugin>/skills/<skill_name>/ paths."""
    copies = []
    for plugin in sorted(MARKETPLACE.iterdir()):
        if not plugin.is_dir():
            continue
        candidate = plugin / "skills" / skill_name
        if candidate.exists():
            copies.append(candidate)
    return copies


def _dir_diverges(src, dst):
    cmp = filecmp.dircmp(str(src), str(dst))
    if cmp.left_only or cmp.right_only or cmp.diff_files:
        return True
    for sub in cmp.subdirs.values():
        if _dir_diverges_recursive(sub):
            return True
    return False


def _dir_diverges_recursive(cmp):
    if cmp.left_only or cmp.right_only or cmp.diff_files:
        return True
    for sub in cmp.subdirs.values():
        if _dir_diverges_recursive(sub):
            return True
    return False


def audit(skill_name, strict_tools=False):
    """Return list[Finding] for one skill. Empty list = clean."""
    findings = []
    skill_dir = SKILLS / skill_name
    if not skill_dir.is_dir():
        findings.append(Finding("E0", "error",
            f"skill directory not found: {skill_dir}"))
        return findings

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        findings.append(Finding("E0", "error",
            f"missing SKILL.md in {skill_dir}"))
        return findings

    md_text = skill_md.read_text(encoding="utf-8")
    refs_dir = skill_dir / "references"

    # H1: phantom citations. Fires whether or not refs_dir exists —
    # a citation to references/X.md is broken regardless of whether
    # the references/ subdir is empty or absent.
    cited_refs = set()
    for ln, ref_name in find_reference_citations(md_text):
        cited_refs.add(ref_name)
        target = refs_dir / ref_name
        if not target.exists():
            findings.append(Finding("H1", "drift",
                f"cited references/{ref_name} does not exist",
                path=str(skill_md.relative_to(REPO)), line=ln))

    # H4: cross-skill citation must resolve. Catches typos like
    # `supergaol/references/...` that H1 doesn't see because they don't
    # match the bare `references/X.md` shape.
    for ln, cross_skill, cross_ref in find_cross_skill_citations(md_text):
        # Skip self-cites (a skill may reference its own canonical name).
        if cross_skill == skill_name:
            continue
        target = SKILLS / cross_skill / "references" / cross_ref
        if not target.exists():
            findings.append(Finding("H4", "drift",
                f"cross-skill citation {cross_skill}/references/{cross_ref} "
                f"does not exist (target skill or ref file missing)",
                path=str(skill_md.relative_to(REPO)), line=ln))

    # H5: backtick-wrapped `<dir>/<file>.md` doc citations that don't
    # follow the references/ convention. Resolve against the skill
    # dir, the skills/ root, and the repo root. Skip paths matched by
    # the known-external-paths registry (sibling repos / user-data
    # caches). 2026-05-27 self-test surfaced this gap: SKILL.md cited
    # `oracle/SPEC.md` (lives at `_shared/oracle/SPEC.md`); H1/H4 only
    # check the references/ shape.
    for ln, cite in find_doc_citations(md_text):
        if _path_is_external(cite):
            continue
        candidates = [
            skill_dir / cite,
            SKILLS / cite,
            REPO / cite,
        ]
        if any(c.exists() for c in candidates):
            continue
        findings.append(Finding("H5", "drift",
            f"documentation citation `{cite}` does not resolve "
            f"against skill dir, skills/, or repo root",
            path=str(skill_md.relative_to(REPO)), line=ln))

    # H2: orphan files in references/
    # Uses a permissive check: a file is "cited" if its name appears anywhere
    # in SKILL.md text (including in templated forms like
    # `[name]({baseDir}/references/X.md)` or `consult references/X.md`
    # as guidance for agent-loaded refs) OR appears in any other reference
    # file (cross-references within the references set).
    if refs_dir.is_dir():
        actual_refs = {p.name for p in refs_dir.iterdir()
                       if p.is_file() and p.suffix == ".md"}
        ref_texts = {r: (refs_dir / r).read_text(encoding="utf-8", errors="ignore")
                     for r in actual_refs}
        for ref in sorted(actual_refs):
            # Convention: __<name>.md is "private" (consulted by hand, not
            # surfaced via SKILL.md citations). Skip silently.
            if ref.startswith("__"):
                continue
            if ref in md_text:
                continue
            cross_referenced = any(ref in text
                                   for name, text in ref_texts.items()
                                   if name != ref)
            if cross_referenced:
                continue
            findings.append(Finding("H2", "info",
                f"references/{ref} exists but is not cited in SKILL.md "
                f"or any other reference file",
                path=str((refs_dir / ref).relative_to(REPO))))

    # H3 was previously here — a check that marketplace/<plugin>/skills/<name>/
    # bit-for-bit mirrors skills/<name>/. That was wrong: the canonical
    # builder `scripts/build-marketplace.py` uses a selective PLUGIN_MANIFEST
    # that copies specific files per plugin (omitting manifest.yaml,
    # internal references, etc.). The validate CI workflow checks
    # marketplace freshness by running build-marketplace.py and asserting
    # `git diff --quiet marketplace/ .claude-plugin/` — that's the
    # correct check. H3 here was redundant with that and produced false
    # positives whenever the builder legitimately excluded a file.

    # D3a: script paths in extracted commands exist (only verifies paths
    # rooted at ~/.claude/skills/, since other deployed locations like
    # ~/.claude/manifests/ or ~/.claude/rules/ aren't part of this repo's
    # ground-truth and we can't authoritatively flag them). Scans both
    # fenced bash blocks AND inline-code (single backticks) in prose, so
    # doc snippets like `python "$SCRIPTS/foo.py"` in narrative get checked
    # too — sca-review/SKILL.md:387 was a documented-but-missing script
    # cited only inline-in-prose that the fenced-block scanner missed.
    referenced_script_paths = set()
    script_path_sources = list(find_script_paths_in_commands(md_text))
    script_path_sources.extend(find_inline_script_paths(md_text))
    for ln, raw_path in script_path_sources:
        if _PATH_PATTERN_MARKER.search(raw_path):
            # Template placeholder, not a real path — e.g. ship-hook documents
            # `python3 ~/.claude/hooks/{name}.py` where {name} is filled in at
            # install time. Same exclusion find_doc_citations already applies.
            continue
        if raw_path.startswith(f"~/.claude/skills/{skill_name}/"):
            suffix = raw_path[len(f"~/.claude/skills/{skill_name}/"):]
            check_path = skill_dir / suffix
        elif raw_path.startswith("~/.claude/skills/"):
            suffix = raw_path[len("~/.claude/skills/"):]
            check_path = SKILLS / suffix
        elif raw_path.startswith(DEPLOYED_ROOT):
            # `~/.claude/<x>` is THIS repo's deployed form, so it maps straight
            # onto the repo tree and is verifiable without any filesystem
            # assumption (works identically on a fresh clone and in CI). The
            # older code lumped these in with genuinely-external paths and
            # skipped them; bin/, hooks/, scripts/, and manifests/ are all in
            # the repo now, so they get the same existence check as a relative
            # citation.
            check_path = REPO / raw_path[len(DEPLOYED_ROOT):]
        elif raw_path.startswith("~/") or raw_path.startswith("/"):
            # Out-of-repo absolute path. Skipping these SILENTLY is how a
            # cross-repo break hides: claude-knowledge-base #1239 deleted
            # .github/scripts/finalize_topics.py and five skills kept citing it
            # by absolute path for a full day, because a same-repo grep looked
            # clean and D3a never examined the citation at all (fixed in #1710).
            #
            # Two outcomes, which must not be conflated:
            #   registry hit + absent on disk -> provisioning gap (owning repo
            #     not cloned here). Info: the citation itself is correct.
            #   registry miss                 -> unregistered dependency. Drift:
            #     either the path is wrong, or the registry needs an entry
            #     naming the repo that owns it.
            if _skill_authors_path(md_text, raw_path):
                # The skill writes this file itself before running it (e.g.
                # mcp-create writes an AST analysis script to ~/Documents/temp/
                # then executes it). It's an OUTPUT, not a dependency.
                continue
            if _path_is_external(raw_path):
                if not Path(os.path.expanduser(raw_path)).exists():
                    findings.append(Finding("D3a", "info",
                        f"external script not present on this host: {raw_path} "
                        f"(registered in known-external-paths.yaml; clone the "
                        f"owning repo — the citation itself is correct)",
                        path=str(skill_md.relative_to(REPO)), line=ln))
            else:
                findings.append(Finding("D3a", "drift",
                    f"command references unregistered out-of-repo script: "
                    f"{raw_path} — verify the path, or add its owning repo to "
                    f"skills/audit-skill/known-external-paths.yaml",
                    path=str(skill_md.relative_to(REPO)), line=ln))
            continue
        elif "/" not in raw_path:
            # Bare filename — typically appears after a `cd` to a directory
            # outside the skill tree (e.g., `cd $HOME/Documents/X && python foo.py`).
            # Tracking shell cwd through a bash block is out of scope; skip.
            continue
        else:
            # Relative path; try skill_dir first, then repo root
            # (some docs reference repo-root paths like `bin/X.py`).
            skill_relative = skill_dir / raw_path
            repo_relative = REPO / raw_path
            if skill_relative.exists():
                check_path = skill_relative
            elif repo_relative.exists():
                check_path = repo_relative
            else:
                check_path = skill_relative  # report against skill_dir form
        if not check_path.exists():
            findings.append(Finding("D3a", "drift",
                f"command references nonexistent script: {raw_path}",
                path=str(skill_md.relative_to(REPO)), line=ln))
        else:
            referenced_script_paths.add(check_path.resolve())

    # D3b: inconsistent path prefixes
    for ln, prefix in find_inconsistent_path_prefixes(md_text):
        findings.append(Finding("D3b", "drift",
            f"command uses non-canonical prefix {prefix!r}; "
            f"use literal {DEPLOYED_PREFIX}<skill>/ for consistency",
            path=str(skill_md.relative_to(REPO)), line=ln))

    # D3c: scripts/ files that are unreferenced (dead-code lint).
    # A script is "referenced" if any of these hold:
    #   - it's the target of a documented command (D3a tracked it)
    #   - its name appears anywhere in SKILL.md (prose, code, or comment)
    #   - its name appears in any references/*.md file
    #   - it's imported / called from another script in the same dir
    #   - it's invoked by a CI workflow under .github/workflows/
    #   - it's imported / called from this skill's tests/
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        # Pre-load workflow files + this skill's tests/ + references/ once per audit.
        # references/ scan added 2026-05-28 — mcp-forge-build's `build_history.py`
        # was getting a false-positive D3c because it's documented in
        # references/harness-pattern.md and references/verification-suite.md
        # but never directly in SKILL.md or another script.
        workflows_dir = REPO / ".github" / "workflows"
        workflow_text = ""
        if workflows_dir.is_dir():
            for wf in workflows_dir.glob("*.yml"):
                workflow_text += wf.read_text(encoding="utf-8", errors="ignore") + "\n"
            for wf in workflows_dir.glob("*.yaml"):
                workflow_text += wf.read_text(encoding="utf-8", errors="ignore") + "\n"
        tests_dir = skill_dir / "tests"
        tests_text = ""
        if tests_dir.is_dir():
            for tf in tests_dir.rglob("*.py"):
                tests_text += tf.read_text(encoding="utf-8", errors="ignore") + "\n"
        refs_text = ""
        if refs_dir.is_dir():
            for rf in refs_dir.rglob("*.md"):
                refs_text += rf.read_text(encoding="utf-8", errors="ignore") + "\n"
        for script in scripts_dir.iterdir():
            if not script.is_file():
                continue
            if script.suffix not in (".py", ".sh"):
                continue
            if script.resolve() in referenced_script_paths:
                continue
            # Prose mention in SKILL.md? (e.g., `scripts/X.py — smoke tests for ...`)
            if script.name in md_text:
                continue
            # Prose mention in any references/*.md?
            if script.name in refs_text:
                continue
            # Invoked by a CI workflow? (e.g. validate.yml marker round-trip)
            if script.name in workflow_text:
                continue
            # Imported / called from this skill's tests/ ? (golden-test
            # round-tripping commonly references scripts by stem.)
            if script.name in tests_text or script.stem in tests_text:
                continue
            # Imported / called from another script?
            referenced_elsewhere = False
            for other in scripts_dir.iterdir():
                if other == script or not other.is_file():
                    continue
                if script.stem in other.read_text(encoding="utf-8", errors="ignore"):
                    referenced_elsewhere = True
                    break
            if not referenced_elsewhere:
                findings.append(Finding("D3c", "info",
                    f"scripts/{script.name} not referenced in SKILL.md "
                    f"or any other script (dead-code candidate)",
                    path=str(script.relative_to(REPO))))

    # C1-C3: cross-platform compatibility (Windows + Mac + Linux)
    findings.extend(_audit_cross_platform(skill_dir, md_text))

    # One shared suppression list for the whole skill audit so match
    # bookkeeping (`__matched`) accumulates across the emission-time
    # checks AND the final path/line filter — that's what makes the S2
    # orphan check below sound (B9/F3).
    suppressed = _load_suppressions(skill_dir)

    # M1, M2, T1: manifest contract / dead-declaration / phantom-tool checks
    findings.extend(_audit_manifest_contract(skill_dir, skill_md, md_text,
                                              strict_tools=strict_tools,
                                              suppressions=suppressed))

    # Systemic-pattern checks (B1, P1, Q1, Q2, Q3).
    findings.extend(_audit_systemic_patterns(skill_dir, skill_md, md_text))

    # Apply suppressions with `path:` / `line:` discriminators as a final
    # filter against the full finding set. Checks that DON'T already call
    # _suppressed() at emission time (the C/H/B/P/Q families) are handled
    # here. Checks that DO call _suppressed() at emission (M1/M2/M3/T1)
    # never make it into the list, so they're not double-filtered.
    findings = _apply_path_line_suppressions(findings, suppressed)

    # Suppression hygiene (B9/F3): expired entries no longer suppress (S1),
    # and entries that matched nothing this run are removal candidates (S2).
    # S2 only applies to codes THIS script emits — audit-suppress.yaml is
    # also read by agent-driven audit passes (/audit-fix campaign codes like
    # A1/D4/G1), and the script cannot know whether those still match.
    sup_path = skill_dir / "audit-suppress.yaml"
    for s in suppressed:
        ident = s.get("code", "?") + (f" target={s['target']}" if s.get("target") else "") \
                + (f" path={s['path']}" if s.get("path") else "")
        if s.get("__expired"):
            findings.append(Finding("S1", "info",
                f"suppression expired ({s.get('expires')}): {ident} — it no "
                f"longer suppresses; remove it or extend `expires:` after "
                f"re-confirming the reason still holds",
                path=str(sup_path.relative_to(REPO))))
        elif not s.get("__matched") and s.get("code") in MECHANICAL_CODES:
            findings.append(Finding("S2", "info",
                f"orphaned suppression: {ident} matches no finding in this "
                f"run — removal candidate (note: C5-C10 cross-platform checks "
                f"only run under --all on other OSes; confirm before removing)",
                path=str(sup_path.relative_to(REPO))))

    return findings


def _audit_manifest_contract(skill_dir, skill_md, md_text, strict_tools=False,
                             suppressions=None):
    """Manifest/SKILL.md contract consistency checks.

    M1: argument-hint brackets vs manifest required:true
        Repo convention: `argument-hint: "[X]"` means X is optional.
        If the manifest declares the corresponding parameter
        required:true, the harness will reject no-arg invocations
        before the body's documented fallback can run. The audit found
        this drift in 10+ skills.

    M2: MCP tool declared in frontmatter `allowed-tools` but never
        invoked in the body OR in any `references/` file. Reconcile-skill-tools.py
        covers the missing-from-declaration direction; this covers the inverse
        (declared but unused — dead-tool grant widens the permission
        surface without runtime use). The references/ scan prevents
        false-positives on skills that delegate tool invocation to
        a reference doc (gather-research → search-waves.md → Exa).

    M4: SKILL.md frontmatter `allowed-tools` set should equal the
        manifest's `requires_tools` set (modulo wildcards). The
        2026-05-28 corpus-wide Phase 2 audit surfaced ~12 skills
        where one side carried a tool the other didn't — typically
        AskUserQuestion, occasionally an MCP tool. requires_tools
        drives topic auto-loading (auto-topic-loader.py), NOT runtime
        tool gating — nothing denies a call for being absent from the
        manifest — so a mismatch is doc-consistency (info severity),
        not runtime drift. Sync the two lists for manifest accuracy.
    """
    findings = []
    fm_text, body_text = _split_frontmatter(md_text)
    if not fm_text:
        return findings

    # Collect search-text: SKILL.md body + all references/*.md content.
    # This avoids M2 false-positives on skills that delegate invocations
    # to a reference document. Single-pass concatenation via str.join is
    # ~O(refs) vs the prior repeated += which was quadratic on the
    # accumulator and matters on skills with 10+ references.
    refs_dir = skill_dir / "references"
    parts = [body_text]
    if refs_dir.is_dir():
        for ref in refs_dir.rglob("*.md"):
            try:
                parts.append(ref.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    search_text = "\n".join(parts)

    # Suppression config: prefer the caller-shared list (so `__matched`
    # bookkeeping survives for the S2 orphan check); load locally only
    # when called standalone.
    # Schema: {suppressions: [{code: "M2", target: "<MCP-name or pattern>", reason: "...", expires?: "YYYY-MM-DD"}]}
    suppressed = suppressions if suppressions is not None else _load_suppressions(skill_dir)

    # M1: argument-hint bracket-form + manifest required:true
    hint_match = re.search(r"^argument-hint:\s*[\"']?\s*\[([^]]+)\][\"']?\s*$",
                           fm_text, re.MULTILINE)
    manifest = skill_dir / "manifest.yaml"
    if hint_match and manifest.is_file() and not _suppressed(suppressed, "M1"):
        m_text = manifest.read_text(encoding="utf-8")
        # Look for any "required: true" inside input_contract or parameters.
        if re.search(r"required:\s*true", m_text):
            findings.append(Finding("M1", "info",
                "argument-hint uses `[...]` brackets (repo convention = optional) "
                "but manifest.yaml declares a `required: true` parameter; "
                "either remove brackets (signal required) or set required:false "
                "(signal optional with documented fallback in body)",
                path=str(skill_md.relative_to(REPO))))

    # M2: MCP tools in allowed-tools but not invoked in body OR references.
    # Bodies often use bare tool names (`list_initiatives(...)`) instead
    # of the full `mcp__server__tool` form. Treat a declared tool as
    # "used" if EITHER the full prefixed form OR the trailing short name
    # appears anywhere in search_text (body + references/*.md). The
    # references inclusion prevents false positives on skills that
    # delegate invocations to a reference doc.
    allowed_line_m = re.search(r"^allowed-tools:\s*(.+)$", fm_text, re.MULTILINE)
    if allowed_line_m:
        declared_mcps = set(re.findall(r"mcp__[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+",
                                        allowed_line_m.group(1)))
        for full in sorted(declared_mcps):
            if _suppressed(suppressed, "M2", target=full):
                continue
            if full in search_text:
                continue
            short = full.rsplit("__", 1)[-1]
            # Word-boundary match for the bare tool name — avoid
            # false-matching on substring inside an English word.
            if re.search(rf"\b{re.escape(short)}\b", search_text):
                continue
            # ALSO match the short name glued to a DIFFERENT mcp__x__ prefix
            # (e.g. the GUID-form `mcp__93acadff-...__save_status_update` is
            # only ever invoked in prose via its named-host sibling
            # `mcp__linear-server__save_status_update`). `\b` never fires
            # here — underscore is a word character, so there's no boundary
            # between "server" and "__save_status_update". This is the
            # documented cross-platform dual-listing convention
            # (mcp-tool-names.md: "skills dual-list both forms"), not drift.
            if re.search(rf"__{re.escape(short)}\b", search_text):
                continue
            findings.append(Finding("M2", "info",
                f"MCP tool {full!r} declared in allowed-tools but "
                f"never invoked in body or references (neither full form "
                f"nor bare `{short}` appears)",
                path=str(skill_md.relative_to(REPO))))

    # M3: manifest.yaml contains `# TODO` placeholders. The scaffold
    # generator emits TODO markers for fields the author hasn't filled
    # in (parameters, produces, side_effects, execution_context,
    # estimated_turns, preconditions, guardrails, threat_model). Shipped
    # TODOs are a tells-no-one schema gap: downstream tooling that reads
    # manifest contracts treats placeholders as missing data. Surfaced
    # by PR #977 in the audit-skill self-audit (B-AUDIT-3).
    if manifest.is_file() and not _suppressed(suppressed, "M3"):
        m_text = manifest.read_text(encoding="utf-8")
        # Count TODO lines so a single finding can summarize the count.
        # Don't false-flag legit "TODO" usage inside a YAML string value
        # (rare); the marker convention is `# TODO`-as-comment.
        todo_lines = [
            (ln_no, line) for ln_no, line in enumerate(m_text.splitlines(), 1)
            if "# TODO" in line
        ]
        if todo_lines:
            first_ln = todo_lines[0][0]
            count = len(todo_lines)
            findings.append(Finding("M3", "info",
                f"manifest.yaml contains {count} `# TODO` placeholder(s) "
                f"— scaffold artifacts that escaped author cleanup. "
                f"Downstream tooling (manifest-gen, audit-rules) treats "
                f"these as missing data. Fill in the real contract.",
                path=str(manifest.relative_to(REPO)), line=first_ln))

    # M4: allowed-tools (SKILL.md frontmatter) ⟺ requires_tools (manifest).
    # The two declarations should list the same tools for consistency.
    # NOTE (verified 2026-05-28): requires_tools does NOT gate tool
    # invocation. The only consumer is hooks/auto-topic-loader.py, which
    # maps requires_tools → requires_topics to choose which topic files to
    # auto-load. Runtime tool permission comes from SKILL.md `allowed-tools`
    # (the Claude Code primitive); nothing in settings.json or any hook
    # denies a call because it's absent from the manifest. So an M4 mismatch
    # is doc-consistency (info severity), NOT runtime drift. Skews surfaced
    # in the 2026-05-28 corpus audit were ~12 skills missing AskUserQuestion
    # (a builtin, always available) or an MCP tool from one side. Wildcards
    # (`mcp__firecrawl__*`) in allowed-tools are honored: any matching
    # concrete tool in requires_tools satisfies the wildcard, and vice versa.
    if manifest.is_file() and not _suppressed(suppressed, "M4"):
        allowed_match = re.search(r"^allowed-tools:\s*(.+)$", fm_text, re.MULTILINE)
        if allowed_match:
            allowed_tokens = _parse_allowed_tools(allowed_match.group(1))
            m_text_for_m4 = manifest.read_text(encoding="utf-8")
            required_tokens = _parse_manifest_required_tools(m_text_for_m4)
            missing_from_manifest = _diff_modulo_wildcards(
                allowed_tokens, required_tokens
            )
            missing_from_allowed = _diff_modulo_wildcards(
                required_tokens, allowed_tokens
            )
            for tool in sorted(missing_from_manifest):
                if _suppressed(suppressed, "M4", target=tool):
                    continue
                findings.append(Finding("M4", "info",
                    f"tool {tool!r} in SKILL.md `allowed-tools` but missing "
                    f"from manifest.yaml `requires_tools` (or covering wildcard) "
                    f"— manifest drives topic auto-loading (auto-topic-loader.py), "
                    f"not runtime tool gating; sync for consistency",
                    path=str(skill_md.relative_to(REPO))))
            for tool in sorted(missing_from_allowed):
                if _suppressed(suppressed, "M4", target=tool):
                    continue
                findings.append(Finding("M4", "info",
                    f"tool {tool!r} in manifest.yaml `requires_tools` but "
                    f"missing from SKILL.md `allowed-tools` (or covering "
                    f"wildcard) — declared dependency without documented "
                    f"surface",
                    path=str(manifest.relative_to(REPO))))

    # T1: phantom / unknown MCP tool references.
    # Scan body + references + frontmatter for `mcp__server__tool` refs.
    # Flag phantom (always); flag non-real (only under strict_tools).
    # The line number reported is into source_text; for body+refs scans
    # the line number is the merged-text offset, which may not match the
    # original file but still gives readers a navigable anchor.
    phantoms, reals = _load_known_tools()
    if phantoms or reals:
        seen = set()  # (source_label, name) — dedupe repeated mentions
        skill_md_rel = str(skill_md.relative_to(REPO))
        for source_text, source_label in (
            (fm_text, "frontmatter"),
            (body_text, "body"),
        ):
            for ln, tool_name in _find_tool_references(source_text):
                key = (source_label, tool_name)
                if key in seen:
                    continue
                seen.add(key)
                if _suppressed(suppressed, "T1", target=tool_name):
                    continue
                # frontmatter line numbers are relative to fm_text; the
                # frontmatter sits at lines 2..(end-1) of the file, so add 1
                # for the leading `---` line.
                file_line = ln + 1 if source_label == "frontmatter" else None
                if _phantom_match(tool_name, phantoms):
                    findings.append(Finding("T1", "drift",
                        f"reference to known-phantom MCP tool {tool_name!r} "
                        f"(in {source_label}); see "
                        f"skills/audit-skill/known-tools.yaml for replacements",
                        path=skill_md_rel, line=file_line))
                    continue
                if strict_tools and reals and not _tool_is_known_real(tool_name, reals):
                    findings.append(Finding("T1", "info",
                        f"unknown MCP tool {tool_name!r} (in {source_label}); "
                        f"verify the tool exists and add to "
                        f"skills/audit-skill/known-tools.yaml `known_real`",
                        path=skill_md_rel, line=file_line))
        # References pass: scan each ref file independently so line numbers
        # are file-local (more useful than merged-text offsets).
        if refs_dir.is_dir():
            for ref in sorted(refs_dir.rglob("*.md")):
                try:
                    ref_text = ref.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                ref_rel = str(ref.relative_to(REPO))
                for ln, tool_name in _find_tool_references(ref_text):
                    key = (ref_rel, tool_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    if _suppressed(suppressed, "T1", target=tool_name):
                        continue
                    if _phantom_match(tool_name, phantoms):
                        findings.append(Finding("T1", "drift",
                            f"reference to known-phantom MCP tool {tool_name!r} "
                            f"(in references); see "
                            f"skills/audit-skill/known-tools.yaml for replacements",
                            path=ref_rel, line=ln))
                        continue
                    if strict_tools and reals and not _tool_is_known_real(tool_name, reals):
                        findings.append(Finding("T1", "info",
                            f"unknown MCP tool {tool_name!r} (in references); "
                            f"verify the tool exists and add to "
                            f"skills/audit-skill/known-tools.yaml `known_real`",
                            path=ref_rel, line=ln))

    return findings


def _strip_yaml_quotes(s):
    """Strip a single pair of matching surrounding quotes (single or
    double) from a YAML scalar. No-op if not quoted."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_manifest_required_tools(manifest_text):
    """Return the set of tools listed under `requires_tools:` in a
    manifest.yaml body. Handles two YAML styles:
      block:  requires_tools:
                - Bash
                - "Read"
      inline: requires_tools: [Bash, "Read", 'Write']
    Quoted strings have their surrounding quotes stripped. Returns
    set() if the key isn't found or its value is `[]`/empty."""
    lines = manifest_text.splitlines()
    tools: set[str] = set()
    in_block = False
    for line in lines:
        if not in_block:
            m_inline = re.match(r"^requires_tools:\s*\[(.*)\]\s*(?:#.*)?$", line)
            if m_inline:
                inner = m_inline.group(1).strip()
                if inner:
                    for token in inner.split(","):
                        token = _strip_yaml_quotes(token.strip())
                        if token:
                            tools.add(token)
                return tools  # inline form is self-contained
            if re.match(r"^requires_tools:\s*(#.*)?$", line):
                in_block = True
            continue
        # Inside block-list. Match "  - <name>" with optional quotes / comment.
        m = re.match(r"^\s+-\s+(.+?)\s*(?:#.*)?$", line)
        if m:
            tok = _strip_yaml_quotes(m.group(1).strip())
            if tok:
                tools.add(tok)
            continue
        # Blank line: still inside.
        if not line.strip():
            continue
        # New top-level key ends the block.
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:", line):
            break
    return tools


def _parse_allowed_tools(value):
    """Normalize a SKILL.md `allowed-tools:` frontmatter value into a set
    of bare tool tokens. Handles the three formats present in the corpus:
      - space-separated:  Read Write Bash mcp__x__*
      - comma-separated:  Bash, Read, Write
      - JSON / flow array: ["Bash", "Read", "mcp__x__y"]
    A permission-scoped Bash entry like `Bash(git log:*, git diff:*)`
    collapses to the bare tool name `Bash` — the manifest lists the bare
    tool; the arg-scope is a Claude Code permission detail, not a separate
    tool. (Without this, the naive `.split()` produced garbage tokens like
    `["Bash",`, `Bash(git`, and `diff:*)`, which spuriously fired M4 —
    deep-dive alone produced 25 false M4 findings this way.)
    Quotes, brackets, and stray commas are stripped. Tool names never
    contain `[](),'"`, so stripping those characters is lossless."""
    s = value.strip()
    # Remove parenthesized permission scopes BEFORE splitting, so the
    # commas inside `Bash(git log:*, git diff:*)` aren't read as separators.
    s = re.sub(r"\([^)]*\)", "", s)
    tokens = set()
    for raw in re.split(r"[,\s]+", s):
        tok = raw.strip(" \t\"'[]")
        if tok:
            tokens.add(tok)
    return tokens


def _wildcard_covers(pattern, name):
    """True if `pattern` (a string optionally containing `*`) matches
    the literal `name`. `*` is treated as a shell-glob wildcard. Plain
    strings match only when equal."""
    if "*" not in pattern:
        return pattern == name
    import fnmatch
    return fnmatch.fnmatchcase(name, pattern)


def _diff_modulo_wildcards(left, right):
    """Return entries in `left` that are not "covered" by any entry in
    `right`. Coverage is symmetric: a literal in `left` is covered if
    `right` contains it OR contains a wildcard pattern that matches it;
    a wildcard in `left` is covered if `right` contains it literally
    OR contains any literal it would match (mirror direction)."""
    out: set[str] = set()
    right_literals = {t for t in right if "*" not in t}
    right_patterns = [t for t in right if "*" in t]
    for token in left:
        if "*" in token:
            # Covered if the same wildcard exists OR any right literal
            # matches the pattern.
            if token in right:
                continue
            if any(_wildcard_covers(token, lit) for lit in right_literals):
                continue
            out.add(token)
        else:
            if token in right_literals:
                continue
            if any(_wildcard_covers(pat, token) for pat in right_patterns):
                continue
            out.add(token)
    return out


_KNOWN_TOOLS_CACHE = {}  # keyed by str(SKILLS) so test SKILLS swaps don't poison


def _phantom_match(tool_name: str, phantoms) -> str | None:
    """Return the phantom entry `tool_name` matches, or None.

    Two entry shapes:
      * exact tool name  -- `mcp__code-graph__index_status`
      * SERVER PREFIX    -- any entry ending in `__`, e.g. `mcp__remote-airlock__`,
        which matches EVERY tool on that server.

    The prefix form exists because a server RENAME kills an unbounded set of
    tool names at once (`mcp__remote-airlock__*` was ~109 tools). Enumerating
    them is impossible, so before this the registry could not express the very
    category its own comments call "Class B: server-rename casualties" -- and an
    entry written as a prefix silently matched nothing.
    """
    if tool_name in phantoms:
        return tool_name
    for entry in phantoms:
        if entry.endswith("__") and tool_name.startswith(entry):
            return entry
    return None


def _load_known_tools():
    """Read skills/audit-skill/known-tools.yaml once and return
    (phantom_names, real_patterns) where:
      - phantom_names is a set of exact tool names known to be wrong,
        or SERVER PREFIXES ending in `__` (see _phantom_match).
      - real_patterns is a list of (kind, pattern) tuples; kind is
        either "literal", "glob" (fnmatch), or "regex".
    Returns (set(), []) if file missing or malformed.

    The cache is keyed by SKILLS so test fixtures that swap SKILLS to
    a tmp-tree don't accidentally serve a cached load from the canonical
    tree, and vice versa."""
    key = str(SKILLS)
    if key in _KNOWN_TOOLS_CACHE:
        return _KNOWN_TOOLS_CACHE[key]
    path = SKILLS / "audit-skill" / "known-tools.yaml"
    phantoms = set()
    reals = []
    if not path.is_file():
        _KNOWN_TOOLS_CACHE[key] = (phantoms, reals)
        return _KNOWN_TOOLS_CACHE[key]
    section = None
    current_phantom = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "known_phantom:":
            section = "phantom"
            current_phantom = None
            continue
        if stripped == "known_real:":
            section = "real"
            current_phantom = None
            continue
        if section == "phantom":
            if stripped.startswith("- name:"):
                name = stripped[len("- name:"):].strip().strip("'\"")
                phantoms.add(name)
                current_phantom = name
            elif stripped.startswith("- "):
                # Bare-name entry
                name = stripped[2:].strip().strip("'\"")
                if name and not name.endswith(":"):
                    phantoms.add(name)
            # other keys (replaced_by, note) ignored — informational only
        elif section == "real":
            if stripped.startswith("- "):
                val = stripped[2:].strip().strip("'\"")
                if not val:
                    continue
                if "*" in val and "[" not in val and "(" not in val:
                    reals.append(("glob", val))
                elif "[" in val or "(" in val or "+" in val or "{" in val:
                    reals.append(("regex", val))
                else:
                    reals.append(("literal", val))
    _KNOWN_TOOLS_CACHE[key] = (phantoms, reals)
    return _KNOWN_TOOLS_CACHE[key]


def _tool_is_known_real(name, real_patterns):
    """True if `name` matches any pattern in real_patterns."""
    import fnmatch
    for kind, pat in real_patterns:
        if kind == "literal" and name == pat:
            return True
        if kind == "glob" and fnmatch.fnmatch(name, pat):
            return True
        if kind == "regex":
            if re.fullmatch(pat, name):
                return True
    return False


def _find_tool_references(text):
    """Yield (line_no, full_tool_name) for every `mcp__server__tool`
    reference in `text`. Picks up both backticked and bare forms."""
    pat = re.compile(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+")
    for m in pat.finditer(text):
        ln = text[:m.start()].count("\n") + 1
        yield ln, m.group(0)


_KNOWN_EXTERNAL_PATHS_CACHE = {}


def _load_known_external_paths():
    """Read skills/audit-skill/known-external-paths.yaml once and return
    a list of pattern strings. Each pattern is matched as a substring
    against cited paths (after no normalization — both `~/...` and
    `$HOME/...` forms are stored as-is in the registry).

    Returns [] if file missing or malformed.

    The cache is keyed by SKILLS so test fixtures that swap SKILLS to
    a tmp-tree get an independent load, same pattern as _KNOWN_TOOLS_CACHE.

    Background: 2026-05-25 KB-citation incident. Fix-agents treated
    `~/Documents/knowledge-base/*` paths as phantom because the files
    aren't in this repo's tree. This registry names the paths that
    legitimately resolve outside the repo (sibling repos + local
    user-data caches) so audit checks and fix-agent prompts can
    consult it.
    """
    key = str(SKILLS)
    if key in _KNOWN_EXTERNAL_PATHS_CACHE:
        return _KNOWN_EXTERNAL_PATHS_CACHE[key]
    path = SKILLS / "audit-skill" / "known-external-paths.yaml"
    patterns: list[str] = []
    if not path.is_file():
        _KNOWN_EXTERNAL_PATHS_CACHE[key] = patterns
        return patterns
    in_external = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "external_paths:":
            in_external = True
            continue
        if not in_external:
            continue
        # Look for `- pattern: "..."` entries
        m = re.match(r'-\s*pattern:\s*["\']?(.+?)["\']?\s*$', stripped)
        if m:
            patterns.append(m.group(1))
    _KNOWN_EXTERNAL_PATHS_CACHE[key] = patterns
    return patterns


_AUTHORS_VERB = r"(?:writes?|write|creates?|generates?|saves?|emits?|scaffolds?)"


def _skill_authors_path(md_text, cited_path):
    """True if the SKILL.md documents CREATING `cited_path` itself.

    A script the skill authors at runtime (an AST analyzer written to a temp
    dir, a smoke-test file) is an OUTPUT, not a dependency — flagging it as a
    missing script is a false positive. Matches an authoring verb on the same
    line as the path, e.g. "Write an AST analysis script to
    `~/Documents/temp/analyze_source.py`".
    """
    if not cited_path:
        return False
    needle = re.escape(cited_path)
    pattern = re.compile(rf"(?i){_AUTHORS_VERB}\b[^\n]*{needle}")
    return bool(pattern.search(md_text))


def _path_is_external(cited_path):
    """True if `cited_path` matches any pattern in the known-external-
    paths registry. Substring match — `cited_path` contains the registry
    pattern. This is the structural fix for the 2026-05-25 KB-citation
    incident: callers can short-circuit phantom-path flagging when a
    citation resolves to an external sibling repo or user-data cache."""
    if not cited_path:
        return False
    patterns = _load_known_external_paths()
    for pat in patterns:
        if pat in cited_path:
            return True
    return False


SUPPRESSION_VALID_KEYS = {"code", "target", "reason", "path", "line", "expires"}
SUPPRESSION_REQUIRED_KEYS = {"code", "reason"}

# Finding codes emitted by THIS script. The S2 orphaned-suppression check
# only fires for these — suppress files also carry agent-campaign codes
# (A*/D1/D2/D4/G*/F* from /audit-fix taxonomies) whose matching happens in
# agent passes the script can't observe (B9/F3).
MECHANICAL_CODES = {
    "H1", "H2", "H4", "H5", "D3a", "D3b", "D3c",
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10",
    "M1", "M2", "M3", "M4", "T1", "B1", "B2", "P1", "Q1", "Q2", "Q3",
}


def _load_suppressions(skill_dir, on_invalid=None):
    """Read skill_dir/audit-suppress.yaml if present. Returns a list of
    suppression dicts {code, target?, reason}. Missing file = empty list.

    Schema validation: each entry must include `code` and `reason`; may
    include `target`. Unknown keys (typos like `target_pattern:`) are
    treated as schema errors. When `on_invalid` is provided, it's called
    with (line_no, message) for each problem; otherwise problems are
    printed to stderr. Either way, problem entries are dropped — they
    silently fail to suppress, which is the worst case (a typo lets the
    finding fire) so we surface it loudly.

    Tiny home-grown YAML parser to avoid a pyyaml dependency."""
    path = skill_dir / "audit-suppress.yaml"
    if not path.is_file():
        return []
    if on_invalid is None:
        def on_invalid(ln, msg):
            print(f"WARN: {path.relative_to(REPO)}:{ln}: {msg}",
                  file=sys.stderr)
    result = []
    current = {}
    current_start_line = 0
    in_list = False
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "suppressions:":
            in_list = True
            continue
        if not in_list:
            continue
        if stripped.startswith("- "):
            if current:
                _finalize_suppression(current, current_start_line, on_invalid, result)
            current = {}
            current_start_line = line_no
            stripped = stripped[2:]
        m = re.match(r"^([a-zA-Z_]+)\s*:\s*(.*)$", stripped)
        if m:
            k, v = m.group(1), m.group(2).strip().strip("'\"")
            if k not in SUPPRESSION_VALID_KEYS:
                on_invalid(line_no, f"unknown suppression key {k!r} (valid: "
                                    f"{sorted(SUPPRESSION_VALID_KEYS)})")
                # Mark this entry as invalid so _finalize drops it.
                current["__invalid"] = True
            else:
                current[k] = v
    if current:
        _finalize_suppression(current, current_start_line, on_invalid, result)
    return result


def _finalize_suppression(entry, line_no, on_invalid, result):
    """Validate a parsed suppression entry; append to result if valid."""
    if entry.pop("__invalid", False):
        return
    missing = SUPPRESSION_REQUIRED_KEYS - set(entry.keys())
    if missing:
        on_invalid(line_no,
                   f"suppression missing required keys: {sorted(missing)} "
                   f"(have: {sorted(entry.keys())})")
        return
    # `line:` without `path:` is ambiguous (which file is line 42 in?).
    # Surface as a schema error so authors notice typos, rather than
    # silently failing to match findings.
    if "line" in entry and "path" not in entry:
        on_invalid(line_no,
                   "suppression has `line:` but no `path:` — line "
                   "discriminator requires a path to be unambiguous. "
                   "Add `path: <glob-or-literal>`.")
        return
    # Validate `line:` shape now so a malformed value doesn't silently
    # disable the suppression at match time.
    sl = entry.get("line")
    if sl is not None:
        try:
            if "-" in sl:
                lo, hi = sl.split("-", 1)
                int(lo); int(hi)
            else:
                int(sl)
        except (ValueError, TypeError):
            on_invalid(line_no,
                       f"suppression `line: {sl!r}` is not a valid int or "
                       f"range (e.g. `line: 42` or `line: 40-45`).")
            return
    # Optional `expires: YYYY-MM-DD` (B9/F3). A suppression written for a
    # temporary condition stops suppressing after this date — the underlying
    # finding fires again, and the audit emits an S1 hygiene finding so the
    # author either removes the entry or consciously extends it.
    exp = entry.get("expires")
    if exp is not None:
        import datetime as _dt
        try:
            exp_date = _dt.date.fromisoformat(exp)
        except (ValueError, TypeError):
            on_invalid(line_no,
                       f"suppression `expires: {exp!r}` is not a valid "
                       f"YYYY-MM-DD date.")
            return
        if exp_date < _dt.date.today():
            entry["__expired"] = True
    result.append(entry)


def _apply_path_line_suppressions(findings, suppressions):
    """Filter `findings` against suppressions that carry `path:` or
    `line:` discriminators. Used at the end of `audit()` to cover
    findings emitted by checks that don't call `_suppressed()` at
    emission time (the cross-platform C-checks, H-checks, etc.).

    A suppression matches a finding when:
      - codes match AND
      - if suppression has `path:`, finding.path matches it (glob) AND
      - if suppression has `line:`, finding.line matches it (int or range)

    Suppressions WITHOUT `path:` AND WITHOUT `line:` are intentionally
    left to the existing emission-site `_suppressed()` calls so we
    don't double-suppress already-filtered findings or accidentally
    expand the scope of existing target-only suppressions.
    """
    if not suppressions:
        return findings
    # Only suppressions that introduce path/line discriminators apply
    # here. Pure code+reason or code+target suppressions are handled at
    # emission time (the M1/M2/M3/T1 paths).
    pl_suppressions = [s for s in suppressions if "path" in s or "line" in s]
    if not pl_suppressions:
        return findings
    kept = []
    for f in findings:
        if _suppressed(pl_suppressions, f.code, path=f.path, line=f.line):
            continue
        kept.append(f)
    return kept


def _suppressed(suppressions, code, target=None, path=None, line=None):
    """True if a suppression matches code (and optionally target / path / line).

    All declared discriminators on the suppression must match the finding.
    Missing-discriminator on the suppression = wildcard (e.g., a suppression
    with only `code` matches every finding with that code).

      - target: literal match OR shell-glob via fnmatch (existing behavior).
      - path: shell-glob match against the finding's normalized forward-
        slash path. Paths are matched relative to the skill or repo root
        (whichever the caller passes), so `path: scripts/build.py` and
        `path: scripts/*.py` both work.
      - line: single int (`line: 42`) OR range string (`line: 40-45`).
        Match is inclusive on both bounds.

    The line discriminator only fires when `path` is ALSO declared on the
    suppression — a line without a path is ambiguous (which file?). We
    enforce this at finalize-time so an authoring mistake surfaces as a
    schema error, not a silent miss.
    """
    import fnmatch
    for s in suppressions:
        if s.get("__expired"):
            continue  # past `expires:` date — no longer suppresses (B9/F3)
        if s.get("code") != code:
            continue
        # target
        t = s.get("target")
        if t is not None:
            if target is None:
                continue
            if not (t == target or fnmatch.fnmatch(target, t)):
                continue
        # path
        sp = s.get("path")
        if sp is not None:
            if path is None:
                continue
            norm = path.replace("\\", "/")
            if not (sp == norm or fnmatch.fnmatch(norm, sp)):
                continue
        # line
        sl = s.get("line")
        if sl is not None:
            if line is None:
                continue
            try:
                if "-" in sl:
                    lo, hi = sl.split("-", 1)
                    if not (int(lo) <= int(line) <= int(hi)):
                        continue
                else:
                    if int(sl) != int(line):
                        continue
            except (ValueError, TypeError):
                # Malformed `line:` slipped past schema check — drop the
                # match (don't suppress if we can't verify).
                continue
        s["__matched"] = True  # orphan-detection bookkeeping (B9/F3)
        return True
    return False


def _split_frontmatter(md_text):
    """Return (frontmatter_text, body_text) — empty fm if no YAML frontmatter."""
    if not md_text.startswith("---\n"):
        return "", md_text
    end = md_text.find("\n---\n", 4)
    if end < 0:
        return "", md_text
    return md_text[4:end], md_text[end + 5:]


def _audit_cross_platform(skill_dir, md_text):
    """Cross-platform compatibility checks. Skills should work on
    Windows, Mac, and Linux without crashing on imports or
    falling back to POSIX-only paths."""
    findings = []
    scripts_dir = skill_dir / "scripts"
    skill_md_path = skill_dir / "SKILL.md"
    skill_name = skill_dir.name

    # C1: Python scripts import POSIX-only modules without fallback.
    # C4: Python source uses literal "$HOME/..." strings — shell-style
    # variable references that Python does NOT expand. healthcheck's
    # _check_manifest.py and _check_orphans.py had this exact bug:
    # Path("$HOME/.claude") creates a Path with literal "$HOME" as the
    # first component, then crashes with FileNotFoundError. The correct
    # idiom is Path.home() / ".claude" or os.path.expanduser("~").
    refs_dir = skill_dir / "references"
    scan_dirs = []
    if scripts_dir.is_dir():
        scan_dirs.append(scripts_dir)
    if refs_dir.is_dir():
        scan_dirs.append(refs_dir)
    if scan_dirs:
        import_pat = re.compile(r"^\s*(?:import|from)\s+(\w+)", re.MULTILINE)
        home_literal_pat = re.compile(r"""['"]\$\{?HOME[}/]""")
        for d in scan_dirs:
            for script in d.glob("*.py"):
                text = script.read_text(encoding="utf-8", errors="ignore")
                # C1
                for m in import_pat.finditer(text):
                    module = m.group(1)
                    if module in POSIX_ONLY_PYTHON_MODULES:
                        if ("sys.platform" in text
                                or "platform.system" in text
                                or ("try:" in text and "ImportError" in text)):
                            continue
                        line_no = text[:m.start()].count("\n") + 1
                        findings.append(Finding("C1", "drift",
                            f"imports POSIX-only module {module!r} without "
                            f"sys.platform / try-except fallback "
                            f"(will crash on Windows)",
                            path=str(script.relative_to(REPO)), line=line_no))
                # C4 — suppress false positives:
                #   - line is a comment (literal $HOME inside a code block
                #     showing what hook-command shapes look like)
                #   - line contains explicit expansion: .replace("$HOME", ...)
                #     or expandvars (the script is correctly handling
                #     user-supplied literals)
                lines = text.splitlines()
                # Track triple-quote balance to detect docstring context.
                # Lines inside a """...""" or '''...''' block contain prose
                # not code; a literal "$HOME" inside such a block is an
                # example, not a real path-construction bug.
                in_docstring = [False] * len(lines)
                state = False
                state_quote = None
                for i, ln in enumerate(lines):
                    in_docstring[i] = state
                    j = 0
                    while j < len(ln):
                        if not state and ln[j:j+3] in ('"""', "'''"):
                            state = True
                            state_quote = ln[j:j+3]
                            j += 3
                            continue
                        if state and ln[j:j+3] == state_quote:
                            state = False
                            state_quote = None
                            j += 3
                            continue
                        j += 1
                for m in home_literal_pat.finditer(text):
                    line_no = text[:m.start()].count("\n") + 1
                    line_text = lines[line_no - 1] if line_no <= len(lines) else ""
                    stripped = line_text.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if 'replace("$HOME"' in line_text or "replace('$HOME'" in line_text:
                        continue
                    if "expandvars" in line_text:
                        continue
                    # Inside a docstring block — example/prose, not code
                    if line_no - 1 < len(in_docstring) and in_docstring[line_no - 1]:
                        continue
                    # $HOME wrapped in backticks on the line — markdown-style
                    # code example inside a docstring/comment
                    col = m.start() - text.rfind("\n", 0, m.start()) - 1
                    before = line_text[:col]
                    after = line_text[col + len("$HOME"):]
                    if "`" in before and "`" in after:
                        continue
                    findings.append(Finding("C4", "drift",
                        "literal \"$HOME\" string in Python source — "
                        "Python does NOT expand shell vars; "
                        "this becomes a literal path component. "
                        "Use Path.home() / ... or os.path.expanduser(...)",
                        path=str(script.relative_to(REPO)), line=line_no))

    # C2: hardcoded POSIX paths or Windows-only patterns in SKILL.md.
    # Severity is info (not drift): Claude Code on Windows typically
    # runs via WSL or Git Bash, where /tmp/ does exist. But hardcoded
    # /tmp/ in docs that users will copy-paste into PowerShell will
    # break, so it's worth surfacing. Likewise %VAR% breaks bash.
    for ln, cmd in extract_bash_blocks(md_text):
        for pat_re, msg in WINDOWS_INCOMPAT_PATH_PATTERNS:
            if pat_re.search(cmd):
                findings.append(Finding("C2", "info", msg,
                    path=str(skill_md_path.relative_to(REPO)), line=ln))

    # C3: shell-only scripts (.sh) without cross-platform alternative
    # Only flag if the skill ships .sh scripts that aren't a small
    # bootstrap (setup-githooks-style); core skill scripts should
    # be Python for portability.
    if scripts_dir.is_dir():
        py_count = len(list(scripts_dir.glob("*.py")))
        sh_count = len(list(scripts_dir.glob("*.sh")))
        if sh_count > 0 and py_count == 0:
            for sh in scripts_dir.glob("*.sh"):
                findings.append(Finding("C3", "drift",
                    "scripts/ contains only .sh scripts; "
                    "rewrite in Python for Windows compatibility",
                    path=str(sh.relative_to(REPO))))

    # C5 / C6 / C7 / C9 / C10 delegated to `_scan_python_file_cross_platform`,
    # the module-level helper shared with the repo-wide audit
    # (`_audit_repo_python`). Centralizing the detection logic closes
    # the historic scope gap that let PR #977's 5 sites in
    # `bin/audit-skill.py` ship: the per-skill audit never touched bin/.
    # Adding a new check to the helper catches it in both per-skill and
    # repo-wide passes uniformly.
    #
    # C8 likewise delegated to `_scan_shell_file_bsd_divergence`.
    if scan_dirs:
        for d in scan_dirs:
            for script in d.glob("*.py"):
                findings.extend(_scan_python_file_cross_platform(script, REPO))
            for sh in d.glob("*.sh"):
                findings.extend(_scan_shell_file_bsd_divergence(sh, REPO))

    return findings


# Systemic-pattern detection. These checks codify the lessons distilled
# in agent-memory/topics/engineering-philosophy.md "Audit + dev-tooling
# discipline" — encoded as machine-checkable rules so the disciplines
# don't drift back into prose-only over time.

PLACEHOLDER_PATTERNS = [
    # ({baseDir}, {projectRoot}, etc.) — template variables that look like
    # they should be substituted but no substitution mechanism exists in
    # the harness. We hit {baseDir} in test-driven-development/SKILL.md
    # during the 2026-05 audit (the link rendered literally and broke).
    (re.compile(r"\{baseDir\}"), "{baseDir}"),
    (re.compile(r"\{projectRoot\}"), "{projectRoot}"),
    (re.compile(r"\{skillDir\}"), "{skillDir}"),
]

# `<your-X>` placeholders. The historical `<your-claude-project>`
# resolved to nothing — every Read/Glob against it silently returned
# empty. Catch this class.
LITERAL_PLACEHOLDER_PAT = re.compile(r"<your-[a-z0-9\-]+>")

# Q1 threshold (skill-authoring rule). Bodies over this dominate the
# agent's context budget; the agent should be able to load the SKILL.md
# without crowding out other context.
WORD_LIMIT = 5000
# Q2 threshold — Claude Code's hard frontmatter limit. The harness
# silently truncates beyond this so the agent never sees the full
# description.
DESCRIPTION_LIMIT = 1024


# Repo-wide audits — these run under `--all` and cover the Python +
# shell surface that the per-skill audit never touches.
#
# The per-skill audit's `_audit_cross_platform` scans
# `<skill>/scripts/` + `<skill>/references/`. That's correct for
# user-facing skills but leaves the entire tooling surface uncovered:
# `bin/*.py` (audit-skill, audit-skill-oracle, reconcile-skill-tools,
# sync-marketplace), `hooks/*.py` (every PreToolUse / PostToolUse hook
# Claude Code runs), and root-level `*.py` (statusline.py).
#
# PR #977 surfaced this gap empirically — 5 of its 6 bugs lived in
# `bin/audit-skill.py`, which the per-skill audit could never have
# caught. The repo-wide audit is the structural fix: same C5-C10
# patterns, broader scan path.

# Exclude vendored / generated / archive trees from the repo-wide scan.
# These contain code we don't own (plugins/cache, plugins/marketplaces)
# or generated copies of code we already lint at its canonical source
# (marketplace/ mirrors skills/*).
REPO_SCAN_EXCLUDED_PREFIXES = (
    "agent-memory/",
    "backups/",
    ".git/",
    "marketplace/",
    "plugins/",
    "scripts/build-marketplace.py",  # exempted: its own scan would loop
)
# Test-hook subtree is excluded from the Python repo-scan because hook
# tests legitimately contain bad-pattern fixtures as string literals
# (the hook-test files BUILD inputs that should trigger detection in
# the hook under test). The per-skill audit doesn't reach test-hooks
# either, so the historic boundary is preserved.
REPO_SCAN_EXCLUDED_DIRS_PYTHON = (
    "hooks/test-hooks/",
    "skills/",  # already covered by per-skill audit
)
# *.sh exclusions: skills/audit-skill/tests/fixtures/ contains
# intentional bad-pattern *.sh files that the per-skill audit picks up
# through the dirty-skill fixture; the repo-wide scan would double-flag
# them and obscure real findings.
REPO_SCAN_EXCLUDED_DIRS_SHELL = (
    "skills/audit-skill/tests/fixtures/",
    "skills/",  # per-skill audit handles skill-local *.sh
    "tests/golden-findings/",
)


def _repo_scan_python_files():
    """Yield paths to Python files under repo-wide audit scope:
    `bin/*.py`, `hooks/*.py` (non-test), `manifests/*.py`,
    `scripts/*.py`, and root-level `*.py`."""
    bin_dir = REPO / "bin"
    hooks_dir = REPO / "hooks"
    manifests_dir = REPO / "manifests"
    scripts_dir = REPO / "scripts"
    if bin_dir.is_dir():
        for p in sorted(bin_dir.glob("*.py")):
            yield p
    if hooks_dir.is_dir():
        # Top-level hooks/*.py only; test-hooks/ deliberately excluded.
        for p in sorted(hooks_dir.glob("*.py")):
            yield p
    if manifests_dir.is_dir():
        for p in sorted(manifests_dir.glob("*.py")):
            yield p
    if scripts_dir.is_dir():
        for p in sorted(scripts_dir.glob("*.py")):
            try:
                rel = str(p.relative_to(REPO)).replace("\\", "/")
            except ValueError:
                rel = str(p)
            if any(rel.startswith(x) for x in REPO_SCAN_EXCLUDED_PREFIXES):
                continue
            yield p
    for p in sorted(REPO.glob("*.py")):
        yield p


def _repo_scan_shell_files():
    """Yield paths to *.sh files in scope for the repo-wide C8 scan."""
    for sh in sorted(REPO.rglob("*.sh")):
        try:
            rel = str(sh.relative_to(REPO)).replace("\\", "/")
        except ValueError:
            continue
        if any(rel.startswith(x) for x in REPO_SCAN_EXCLUDED_PREFIXES):
            continue
        if any(rel.startswith(x) for x in REPO_SCAN_EXCLUDED_DIRS_SHELL):
            continue
        yield sh


def _audit_repo_python():
    """C5/C6/C7/C9/C10 repo-wide scan. Returns list[Finding] with
    repo-relative paths."""
    findings = []
    for script in _repo_scan_python_files():
        findings.extend(_scan_python_file_cross_platform(script, REPO))
    return findings


def _audit_repo_shell():
    """C8 repo-wide scan on *.sh files outside the skill tree."""
    findings = []
    for sh in _repo_scan_shell_files():
        findings.extend(_scan_shell_file_bsd_divergence(sh, REPO))
    return findings


# Utility modules in hooks/ that other hooks import but are NOT themselves
# wired hook entry points. They don't need their own test_<name>.py files;
# their behavior is exercised via the hooks that import them. Verified
# 2026-05-26 via grep for `def main()` / `if __name__ == "__main__"`.
# Kept in sync with classify_rules.py's UTILITY_MODULES.
_B2_UTILITY_MODULES = {
    "atomic_write.py",
    "hook_input.py",
    "manifest_metrics.py",
}


def _audit_hook_test_coverage():
    """B2: every `hooks/<name>.py` must have a corresponding
    `hooks/test-hooks/test_<name>.py`. Parallel to B1 (skill ships
    scripts/ but no tests/) but scoped to hooks.

    Hooks gate Claude Code's tool calls (PreToolUse / PostToolUse).
    An untested hook regression silently changes behavior for every
    user. The state-of-the-repo evaluation found 54 of 55 hooks
    lacking tests — making the gap visible as tracked findings is
    the first step toward closing it.

    Mapping convention: `<hook-name>.py` → `test_<hook-name>.py`.
    The basename of the hook (without `.py`) is prefixed with `test_`.
    Dashes in hook names become underscores in test names (matching
    Python module-name rules for pytest discovery). Both forms are
    accepted to cover hooks named with either convention.

    Excludes _B2_UTILITY_MODULES — shared helpers imported by other
    hooks but not themselves wired as entry points.
    """
    findings = []
    hooks_dir = REPO / "hooks"
    test_hooks_dir = hooks_dir / "test-hooks"
    if not hooks_dir.is_dir():
        return findings
    if not test_hooks_dir.is_dir():
        # No test-hooks/ at all — flag the whole directory once rather
        # than emitting 55+ findings. Operator should bootstrap the
        # test-hooks/ tree before per-hook fixes apply.
        findings.append(Finding("B2", "info",
            "hooks/ exists but hooks/test-hooks/ is missing — no hook "
            "is covered by tests. Create `hooks/test-hooks/` and add "
            "test files following the `test_<hookname>.py` convention",
            path="hooks/"))
        return findings
    for hook in sorted(hooks_dir.glob("*.py")):
        if hook.name in _B2_UTILITY_MODULES:
            continue
        name = hook.stem
        # Accept either dashed or underscored test names. Hooks like
        # `bash-security-guard.py` map to `test_bash_security_guard.py`
        # (dashes → underscores for pytest module-name compatibility).
        # Some test files may keep the dashed form via filename-only
        # collection — accept both.
        underscored = "test_" + name.replace("-", "_") + ".py"
        dashed = "test_" + name + ".py"
        if (test_hooks_dir / underscored).exists():
            continue
        if (test_hooks_dir / dashed).exists():
            continue
        try:
            rel = str(hook.relative_to(REPO)).replace("\\", "/")
        except ValueError:
            rel = str(hook)
        findings.append(Finding("B2", "info",
            f"hook ships without a regression test — expected "
            f"`hooks/test-hooks/{underscored}` (or the dashed form). "
            f"Hooks gate Claude Code's tool calls; an untested hook "
            f"regression silently changes behavior. State-of-the-repo "
            f"2026-05-26 found 54 of 55 hooks lacked tests.",
            path=rel))
    return findings


def _audit_systemic_patterns(skill_dir, skill_md, md_text):
    """Systemic-pattern checks: B1 (scripts without tests), P1 (template
    placeholders), Q1/Q2/Q3 (quality/length limits + description
    completeness)."""
    findings = []
    try:
        skill_md_rel = str(skill_md.relative_to(REPO))
    except ValueError:
        # Skill is outside REPO (test fixtures in tmp_path) — use the
        # absolute path so the finding still has a navigable location.
        skill_md_rel = str(skill_md)
    fm_text, body_text = _split_frontmatter(md_text)

    # B1: skill ships scripts/ but no tests/. The "reasoned-about ≠
    # tested" gap. Info severity — the skill maintainer may have a
    # reason (LLM-only skill, scripts trivially stub-ish); the check
    # surfaces the candidate, doesn't force a fix.
    scripts_dir = skill_dir / "scripts"
    tests_dir = skill_dir / "tests"
    if scripts_dir.is_dir():
        py_scripts = [p for p in scripts_dir.glob("*.py")
                      if not p.name.startswith("_")]
        if py_scripts and not tests_dir.is_dir():
            findings.append(Finding("B1", "info",
                f"skill ships {len(py_scripts)} Python script(s) in "
                f"scripts/ but has no tests/ directory — behavior is "
                f"unverified beyond reading + reasoning. See "
                f"AUDIT-TRACKERS/02-golden-tests.md for the pattern",
                path=skill_md_rel))

    # P1: unresolved template placeholders. Skip matches inside fenced
    # code blocks (those are example snippets, not real renderings).
    # Do NOT skip inline backticks: the historical bug pattern was
    # `~/.claude/projects/<your-claude-project>/CLAUDE.md` — a backticked
    # path with the placeholder in the middle. Stripping all inline
    # spans would mask that real-bug case.
    body_lines = body_text.splitlines()
    in_fence = False
    scrubbed_lines = []
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            scrubbed_lines.append("")
            continue
        if in_fence:
            scrubbed_lines.append("")
            continue
        scrubbed_lines.append(line)
    scrubbed_body = "\n".join(scrubbed_lines)

    for pat, label in PLACEHOLDER_PATTERNS:
        for m in pat.finditer(scrubbed_body):
            ln = scrubbed_body[:m.start()].count("\n") + 1
            file_line = ln + fm_text.count("\n") + 2 if fm_text else ln
            findings.append(Finding("P1", "drift",
                f"unresolved template placeholder {label!r} in SKILL.md body "
                f"— this string is not substituted at agent-load time and "
                f"will appear literally to readers",
                path=skill_md_rel, line=file_line))
    for m in LITERAL_PLACEHOLDER_PAT.finditer(scrubbed_body):
        ln = scrubbed_body[:m.start()].count("\n") + 1
        file_line = ln + fm_text.count("\n") + 2 if fm_text else ln
        findings.append(Finding("P1", "drift",
            f"placeholder {m.group(0)!r} in SKILL.md body — "
            f"the agent will use this verbatim and the resulting path "
            f"won't resolve",
            path=skill_md_rel, line=file_line))

    # Q1: SKILL.md word count > WORD_LIMIT.
    word_count = len(body_text.split())
    if word_count > WORD_LIMIT:
        findings.append(Finding("Q1", "info",
            f"SKILL.md body is {word_count} words (limit {WORD_LIMIT} per "
            f"skill-authoring rules); move detail into references/*.md "
            f"so the agent's context isn't dominated by one skill",
            path=skill_md_rel))

    # Q2: description field exceeds Claude Code hard limit.
    # Boundary must recognize underscore-containing keys (e.g. `when_to_use:`)
    # as the next field — `[a-z-]+:` excludes `_`, so the description capture
    # bleeds through `when_to_use` and over-counts the length (Q2 false drift).
    desc_match = re.search(r"^description:\s*(.+?)(?=\n[\w-]+:|\Z)",
                            fm_text, re.MULTILINE | re.DOTALL)
    wtu_match = re.search(r"^when_to_use:\s*(.+?)(?=\n[\w-]+:|\Z)",
                           fm_text, re.MULTILINE | re.DOTALL)
    if desc_match:
        desc = desc_match.group(1).strip().strip("'\"")
        wtu = wtu_match.group(1).strip().strip("'\"") if wtu_match else ""
        if len(desc) > DESCRIPTION_LIMIT:
            findings.append(Finding("Q2", "drift",
                f"frontmatter description is {len(desc)} chars (limit "
                f"{DESCRIPTION_LIMIT} per Claude Code); content past the "
                f"limit is silently truncated and the agent never sees it",
                path=skill_md_rel))

        # Q3: description should signal WHEN to use the skill AND when
        # NOT to. Two acceptable forms for the WHEN side:
        #   (a) explicit "use when X" / "use to X" / similar imperative
        #   (b) "Trigger phrases:" section (the routing hook reads these
        #       directly; explicit WHEN is redundant for skills that
        #       enumerate triggers)
        # The NOT side needs a "Do NOT use for" / similar disambiguator
        # so the routing hook can negative-match against trigger phrases
        # from neighboring skills.
        # Trigger/when signals may live in `description` OR `when_to_use`
        # (the model reads both for routing), so check the combined text.
        desc_lower = (desc + "\n" + wtu).lower()
        has_when = ("use when" in desc_lower or "use to" in desc_lower
                    or "use this when" in desc_lower
                    or "use before" in desc_lower
                    or "use after" in desc_lower
                    or "trigger phrases" in desc_lower
                    or "trigger words" in desc_lower
                    or "triggers on" in desc_lower
                    or "invoked as" in desc_lower
                    or "invoked when" in desc_lower
                    or "you must use" in desc_lower
                    or "when " in desc_lower)
        has_dont = ("do not use" in desc_lower or "don't use" in desc_lower
                    or "not for" in desc_lower or "do not " in desc_lower
                    or "skip when" in desc_lower
                    or "not when" in desc_lower)
        if not (has_when and has_dont):
            missing_parts = []
            if not has_when:
                missing_parts.append("WHEN to use (or 'Trigger phrases:' section)")
            if not has_dont:
                missing_parts.append("Do NOT use for")
            findings.append(Finding("Q3", "info",
                f"frontmatter description missing {' / '.join(missing_parts)} "
                f"— the routing hook needs both a positive trigger signal "
                f"(when to fire) and a negative disambiguator (when NOT to "
                f"fire, to avoid mis-routing from neighboring skills)",
                path=skill_md_rel))

    return findings


def report(skill_name, findings):
    if not findings:
        print(f"OK   {skill_name}")
        return 0
    drift_count = sum(1 for f in findings if f.severity == "drift")
    error_count = sum(1 for f in findings if f.severity == "error")
    info_count = sum(1 for f in findings if f.severity == "info")
    summary = f"{skill_name}: {drift_count} drift, {error_count} error, {info_count} info"
    print(f"FAIL {summary}" if (drift_count or error_count) else f"INFO {summary}")
    for f in findings:
        print(f)
    return drift_count


def report_json(skill_name, findings):
    """Machine-readable counterpart to report(). Emits a JSON object
    per skill with the same data shape the human report carries. Used
    by --json for CI tooling that can't parse the prose output.
    Returns drift count (mirrors report's contract). The caller computes
    error count separately so the final summary line doesn't conflate them."""
    import json
    drift_count = sum(1 for f in findings if f.severity == "drift")
    error_count = sum(1 for f in findings if f.severity == "error")
    info_count = sum(1 for f in findings if f.severity == "info")
    obj = {
        "skill": skill_name,
        "status": ("OK" if not findings
                   else ("FAIL" if (drift_count + error_count) else "INFO")),
        "counts": {
            "drift": drift_count,
            "info": info_count,
            "error": error_count,
        },
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "msg": f.msg,
                "path": f.path,
                "line": f.line,
            }
            for f in findings
        ],
    }
    print(json.dumps(obj))
    return drift_count


MARKETPLACE_BUILD_TIMEOUT_SECONDS = int(os.environ.get(
    "AUDIT_SKILL_MARKETPLACE_TIMEOUT", "60"))


def check_marketplace_freshness():
    """Run scripts/build-marketplace.py and assert no diff. Returns
    (ok: bool, message: str). Used by --check-marketplace and by --all
    by default. Replaces the removed H3 check with the correct gate
    (the canonical builder, not a bit-for-bit mirror assumption).

    The builder timeout defaults to 60s and is overridable via the
    `AUDIT_SKILL_MARKETPLACE_TIMEOUT` env var for larger repos."""
    import subprocess
    builder = REPO / "scripts" / "build-marketplace.py"
    if not builder.exists():
        return True, "scripts/build-marketplace.py not present — skipping freshness check"
    print(f"  (running build-marketplace.py with {MARKETPLACE_BUILD_TIMEOUT_SECONDS}s timeout)",
          file=sys.stderr)
    try:
        subprocess.run([sys.executable, str(builder)],
                       cwd=str(REPO), capture_output=True, check=True,
                       timeout=MARKETPLACE_BUILD_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as e:
        return False, f"build-marketplace.py exited {e.returncode}: {e.stderr.decode(errors='replace')[:200]}"
    except subprocess.TimeoutExpired:
        return False, (
            f"build-marketplace.py timed out after "
            f"{MARKETPLACE_BUILD_TIMEOUT_SECONDS}s — raise "
            f"AUDIT_SKILL_MARKETPLACE_TIMEOUT if this is a larger repo "
            f"or the builder is genuinely slow"
        )
    # `git status --porcelain` covers BOTH modified tracked files AND newly
    # created untracked files. The old `git diff --quiet` form only saw
    # tracked modifications — so when the builder created a NEW file in
    # marketplace/ that had never been committed, the gate stayed green and
    # the file silently never shipped (B9 review 2026-06-10; the PR #1151
    # garden test was the live instance of this blind spot).
    status = subprocess.run(
        ["git", "status", "--porcelain", "marketplace/", ".claude-plugin/"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    files = [l for l in status.stdout.splitlines() if l.strip()]
    if not files:
        return True, "marketplace/ + .claude-plugin/ are in sync with build-marketplace.py"
    return False, (
        f"marketplace/ diverges from build-marketplace.py output "
        f"({len(files)} files, incl. untracked). Run "
        f"`python3 scripts/build-marketplace.py` and commit. "
        f"Sample: {files[:3]}"
    )


def _fix_c5_in_file(path):
    """Mechanically fix C5 violations in `path`: insert `, encoding='utf-8'`
    immediately before the closing `)` of every text-mode file-I/O call
    that's flagged by the C5 check (bare `o`+`pen`/`.read_text`/`.write_text`).
    Skips:
      - binary opens (mode token rb/wb/...) via _call_is_binary_open
      - calls already passing encoding= via _call_misses_encoding == False
      - matches inside string literals or docstrings

    Returns (fixes_applied: int, new_text: str). The caller writes
    `new_text` back to disk if `fixes_applied > 0`.

    Implementation note: edits are computed back-to-front (highest offset
    first) so earlier offsets remain valid as we splice. We use byte
    offsets within `text`, NOT line numbers, because a single line may
    contain multiple calls and a single call may span multiple lines.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    in_doc = _docstring_line_mask([l.rstrip("\n") for l in lines])

    # (line_idx, match_start_col, kind) tuples for every call to fix.
    targets = []
    for line_no, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if line.lstrip().startswith("#"):
            continue
        if in_doc[line_no - 1]:
            continue
        idx = line_no - 1
        clean_lines = [l.rstrip("\n") for l in lines]

        for m in C5_READ_TEXT_PAT.finditer(line):
            if _looks_like_string_literal(line, m.start()):
                continue
            if not _call_misses_encoding(clean_lines, idx, m.start()):
                continue
            targets.append((idx, m.start(), "read_text"))
        for m in C5_WRITE_TEXT_PAT.finditer(line):
            if _looks_like_string_literal(line, m.start()):
                continue
            if not _call_misses_encoding(clean_lines, idx, m.start()):
                continue
            targets.append((idx, m.start(), "write_text"))
        for m in C5_OPEN_PAT.finditer(line):
            prefix_text = line[max(0, m.start() - 8):m.end()]
            if C5_OS_OPEN_PREFIX.search(prefix_text):
                continue
            if _looks_like_string_literal(line, m.start()):
                continue
            if _call_is_binary_open(clean_lines, idx, m.start()):
                continue
            if not _call_misses_encoding(clean_lines, idx, m.start()):
                continue
            targets.append((idx, m.start(), "open"))

    if not targets:
        return 0, text

    # For each target, walk paren-depth forward to find the matching close
    # paren's (line, col). Record (close_line, close_col) per target.
    close_positions = []
    clean_lines = [l.rstrip("\n") for l in lines]
    for idx, ms, _kind in targets:
        depth = 0
        seen_open = False
        found = None
        for j in range(idx, min(idx + C5_MULTILINE_LOOKAHEAD, len(clean_lines))):
            seg = clean_lines[j][ms:] if j == idx else clean_lines[j]
            start_offset = ms if j == idx else 0
            for k, ch in enumerate(seg):
                if ch == "(":
                    depth += 1
                    seen_open = True
                elif ch == ")":
                    depth -= 1
                    if seen_open and depth <= 0:
                        found = (j, start_offset + k)
                        break
            if found:
                break
        if found is None:
            # Should not happen since _call_misses_encoding already
            # required closing paren to be found. Defensive fallback.
            continue
        close_positions.append(found)

    # Build edit list: insert ", encoding='utf-8'" before each close paren.
    # Sort back-to-front so earlier inserts don't shift later positions.
    edits = sorted(set(close_positions), key=lambda lc: (lc[0], lc[1]), reverse=True)
    insert_text = ", encoding='utf-8'"
    new_lines = [l for l in lines]
    for (line_idx, col) in edits:
        raw = new_lines[line_idx]
        # Skip if the call already gained encoding= via an earlier insert
        # in this same line (defensive against duplicate targets).
        # Check: scan the call body. Simplest is: only insert if no
        # ", encoding=" is present in a 80-char window immediately before col.
        window_start = max(0, col - 80)
        if "encoding=" in raw[window_start:col]:
            continue
        # Look back from `col` for the previous non-whitespace char.
        # If it's a `,` or `(`, no extra comma needed; otherwise insert
        # the comma. The standard idiom `f("x")` needs `, encoding=...`;
        # the call `f("x",)` already has a trailing comma.
        prev_non_ws = ""
        for i in range(col - 1, -1, -1):
            if not raw[i].isspace():
                prev_non_ws = raw[i]
                break
        if prev_non_ws == "(":
            # Empty call like `f()` → no comma, no leading space.
            ins = "encoding='utf-8'"
        elif prev_non_ws == ",":
            # Trailing comma like `f(a,)` → just a space before the kwarg.
            ins = " encoding='utf-8'"
        else:
            ins = insert_text
        new_lines[line_idx] = raw[:col] + ins + raw[col:]

    return len(close_positions), "".join(new_lines)


def _fix_c7_in_file(path):
    """Insert a `--help` short-circuit immediately after the
    `if __name__ == "__main__":` line. The inserted block is:

        if any(a in ("-h", "--help") for a in sys.argv[1:]):
            print(__doc__ or "<usage TBD>"); sys.exit(0)

    Preconditions (must hold for fix to apply, mirroring the C7 detection):
      - `if __name__ == "__main__":` block exists
      - sys.argv subscript exists somewhere in the module
      - NO `parse_args()` call anywhere
      - NO existing `"--help"` / `"-h"` literal anywhere

    Returns (fixes_applied: int, new_text: str). At most one fix per file
    (one __main__ block per Python module is conventional).

    Requires `sys` imported; appends `import sys` after the last
    existing import if not present.
    """
    import ast
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0, text
    main_block = _find_main_block(tree)
    if main_block is None:
        return 0, text

    # Re-check the C7 conditions to avoid clobbering files where the
    # finding is stale.
    has_argv = False
    has_parse_args_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            val = node.value
            if isinstance(val, ast.Attribute):
                if (isinstance(val.value, ast.Name)
                        and val.value.id == "sys"
                        and val.attr == "argv"):
                    has_argv = True
            elif isinstance(val, ast.Name) and val.id == "argv":
                has_argv = True
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "parse_args":
                has_parse_args_call = True
    if not has_argv or has_parse_args_call:
        return 0, text
    if ('"--help"' in text or "'--help'" in text or
            '"-h"' in text or "'-h'" in text):
        return 0, text

    lines = text.splitlines(keepends=True)
    main_line_idx = main_block.lineno - 1  # 0-based index of `if __name__ ...`

    # Detect indentation of the line AFTER the if (which is the first
    # body statement). Fallback: indent of `if` + 4 spaces.
    indent = ""
    for j in range(main_line_idx + 1, len(lines)):
        s = lines[j]
        if s.strip() and not s.lstrip().startswith("#"):
            indent = s[:len(s) - len(s.lstrip())]
            break
    if not indent:
        outer = lines[main_line_idx][:len(lines[main_line_idx]) - len(lines[main_line_idx].lstrip())]
        indent = outer + "    "

    short_circuit = (
        f"{indent}if any(a in (\"-h\", \"--help\") for a in sys.argv[1:]):\n"
        f"{indent}    print(__doc__ or \"<usage TBD>\"); sys.exit(0)\n"
    )

    # Insert immediately AFTER the if-line (above the existing body).
    new_lines = lines[:main_line_idx + 1] + [short_circuit] + lines[main_line_idx + 1:]
    new_text = "".join(new_lines)

    # Ensure `import sys` is present.
    if not re.search(r"^\s*import\s+sys\b", new_text, re.MULTILINE):
        # Insert `import sys` after the last existing top-level import,
        # or at the top of the file (after shebang/docstring) if none.
        import_lines = []
        for i, l in enumerate(new_lines):
            if re.match(r"^\s*(?:from|import)\s+\w", l):
                import_lines.append(i)
        if import_lines:
            ins_idx = import_lines[-1] + 1
        else:
            # Find first non-shebang, non-docstring, non-blank line.
            ins_idx = 0
            in_doc = False
            for i, l in enumerate(new_lines):
                if l.startswith("#!"):
                    ins_idx = i + 1
                    continue
                stripped = l.strip()
                if stripped.startswith(('"""', "'''")):
                    in_doc = not in_doc
                    if not in_doc:
                        ins_idx = i + 1
                    continue
                if in_doc:
                    continue
                if stripped == "":
                    continue
                ins_idx = i
                break
        new_lines = new_lines[:ins_idx] + ["import sys\n"] + new_lines[ins_idx:]
        new_text = "".join(new_lines)

    return 1, new_text


def _fix_m1_for_skill(skill_dir):
    """Mechanical M1 fix: when SKILL.md's argument-hint uses the bracket
    (optional) convention but manifest.yaml declares `required: true`,
    flip the manifest to `required: false`.

    Direction rationale: the frontmatter hint is the AUTHOR-written
    contract; manifest.yaml is derived metadata (it feeds topic
    auto-loading, not runtime gating — see the M4 check's docs). When the
    two disagree, the manifest follows the hint.

    Safety: only fires when the manifest contains EXACTLY ONE
    `required: true` occurrence — multi-parameter manifests may have
    legitimately-required parameters the bracket hint says nothing
    about; those are skipped with a notice for human judgment.

    Returns (n_fixed, notice_or_None).
    """
    skill_md = skill_dir / "SKILL.md"
    manifest = skill_dir / "manifest.yaml"
    if not (skill_md.is_file() and manifest.is_file()):
        return 0, None
    md_text = skill_md.read_text(encoding="utf-8")
    fm = re.match(r"\A---\n(.*?)\n---", md_text, re.DOTALL)
    fm_text = fm.group(1) if fm else ""
    if not re.search(r"^argument-hint:\s*[\"']?\s*\[([^]]+)\][\"']?\s*$",
                     fm_text, re.MULTILINE):
        return 0, None
    m_text = manifest.read_text(encoding="utf-8")
    occurrences = re.findall(r"required:\s*true", m_text)
    if not occurrences:
        return 0, None
    if len(occurrences) > 1:
        return 0, (
            f"M1 fix skipped for {skill_dir.name}: manifest has "
            f"{len(occurrences)} `required: true` parameters — needs "
            f"human judgment on which one the bracket hint refers to."
        )
    fixed = re.sub(r"required:(\s*)true", r"required:\1false", m_text, count=1)
    manifest.write_text(fixed, encoding="utf-8")
    return 1, None


def _apply_fixes(skill_names, codes_to_fix):
    """Walk each skill (and __repo__ if requested via "__repo__" in
    skill_names) and apply mechanical fixes for the listed codes.
    Returns dict {skill_name: {code: count}} summarizing changes per file.

    codes_to_fix is an iterable of strings drawn from {"C5", "C7", "M1"}.
    Other codes are silently ignored (they have no mechanical fixer).
    """
    summary = defaultdict(lambda: defaultdict(int))

    # M1 operates per-skill on manifest.yaml (not per .py file).
    if "M1" in codes_to_fix:
        for sn in skill_names:
            if sn == "__repo__":
                continue
            skill_dir = SKILLS / sn
            if not skill_dir.is_dir():
                continue
            n, notice = _fix_m1_for_skill(skill_dir)
            if n:
                summary[sn]["M1"] += n
            if notice:
                print(notice, file=sys.stderr)

    files_to_scan = []

    for sn in skill_names:
        if sn == "__repo__":
            # Repo-wide Python files (same scope as _audit_repo_python).
            for relbase in ("bin", "hooks", "manifests", "scripts"):
                d = REPO / relbase
                if not d.is_dir():
                    continue
                for p in d.rglob("*.py"):
                    if "test" in p.name.lower() or "/tests/" in str(p).replace("\\", "/"):
                        continue
                    files_to_scan.append(("__repo__", p))
            # Root-level *.py
            for p in REPO.glob("*.py"):
                files_to_scan.append(("__repo__", p))
            continue
        skill_dir = SKILLS / sn
        if not skill_dir.is_dir():
            continue
        for p in skill_dir.rglob("*.py"):
            if "/tests/" in str(p).replace("\\", "/"):
                continue
            files_to_scan.append((sn, p))

    for skill_name, p in files_to_scan:
        applied = {}

        # C5 then C7: each reads from disk. They don't overlap (C5
        # touches text-mode I/O calls; C7 inserts a help short-circuit
        # at the top of the __main__ block), so writing between them
        # is safe.
        if "C5" in codes_to_fix:
            n, text_after = _fix_c5_in_file(p)
            if n > 0:
                p.write_text(text_after, encoding="utf-8")
                applied["C5"] = n

        if "C7" in codes_to_fix:
            n, text_after = _fix_c7_in_file(p)
            if n > 0:
                p.write_text(text_after, encoding="utf-8")
                applied["C7"] = n

        for code, n in applied.items():
            summary[skill_name][code] += n

    return summary


USAGE = (
    "usage: audit-skill.py {<skill-name>|--all} "
    "[--strict] [--check-marketplace|--no-marketplace-check] "
    "[--strict-tools] [--json|--sarif] [--changed[=BASE]] [--fix[=CODES]] "
    "[--parallel[=N]] [--ndjson=PATH] [--surface-map]\n"
    "\n"
    "Phase 1 mechanical lint for a skill (or all skills under ~/.claude/skills).\n"
    "\n"
    "Positional:\n"
    "  <skill-name>            audit one skill by name (matches ~/.claude/skills/<name>/)\n"
    "  --all                   audit every skill that has a SKILL.md\n"
    "\n"
    "Flags:\n"
    "  --strict                exit non-zero on any drift finding (default: only on errors)\n"
    "  --check-marketplace     also verify marketplace/ is in sync (implied by --all)\n"
    "  --no-marketplace-check  skip the marketplace freshness check\n"
    "  --strict-tools          flag MCP tools not in known-tools.yaml known_real list\n"
    "  --json                  emit one JSON object per skill on stdout\n"
    "  --sarif                 emit SARIF 2.1 (single run, one result per finding)\n"
    "                          for GitHub code-scanning / VS Code Problems pane\n"
    "  --changed[=BASE]        narrow to skills touched in `git diff BASE...HEAD`\n"
    "                          (default BASE=origin/main; falls back to full set\n"
    "                          if git fails)\n"
    "  --fix[=CODES]           apply mechanical fixes for the listed codes,\n"
    "                          comma-separated (default: C5,C7; also: M1 —\n"
    "                          manifest required:true follows a bracketed\n"
    "                          argument-hint to required:false). Writes files\n"
    "                          in place; re-run audit afterward to verify\n"
    "  --parallel[=N]          run --all audits in N parallel processes (default 4\n"
    "                          when bare; back-compat: 1 if --parallel omitted).\n"
    "                          Uses ProcessPoolExecutor so CPU-bound work\n"
    "                          (regex+AST) actually scales; output is still\n"
    "                          ordered.\n"
    "  --ndjson=PATH           also append one JSON record per finding to PATH.\n"
    "                          Replayable event log for cross-run analysis;\n"
    "                          consumed by skills/audit-skill/scripts/audit_history.py.\n"
    "  --surface-map           emit the deterministic Phase-2 surface map as JSON\n"
    "                          and exit (no lint): per-skill tier (deep/light),\n"
    "                          has_scripts/has_cli, bash_block_count, references_count,\n"
    "                          and which A1/B/D1/D2/D4 categories are applicable vs\n"
    "                          n-a (A3/F2/F3 are 'review' — prose-claim dependent).\n"
    "  -h, --help              show this help message and exit\n"
)


def _skills_touched_since(base_ref):
    """Return set[str] of skill names whose `skills/<name>/...` files
    changed in `git diff --name-only <base_ref>...HEAD`. Returns None
    if git fails (unknown ref, not in a repo, etc.) so the caller can
    fall back to the full skill list.
    """
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=str(REPO), capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    touched = set()
    for line in r.stdout.splitlines():
        line = line.strip().replace("\\", "/")
        if line.startswith("skills/"):
            parts = line.split("/", 2)
            if len(parts) >= 2 and parts[1]:
                touched.add(parts[1])
    return touched


def _render_sarif(findings_by_skill):
    """Render audit-skill findings as SARIF 2.1.0 (single run, one
    result per finding). Integrates with GitHub code-scanning, VS
    Code Problems pane, and any SARIF consumer.

    SARIF 2.1.0 spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/

    Severity mapping:
      drift  → 'warning'  (contract violation; can ship but flagged)
      info   → 'note'     (hygiene; no immediate action required)
      error  → 'error'    (skill not found / unparseable)
    """
    rules_seen = {}
    results = []
    for skill_name, f in findings_by_skill:
        rule_id = f.code
        if rule_id not in rules_seen:
            rules_seen[rule_id] = {
                "id": rule_id,
                "name": rule_id,
                "shortDescription": {"text": f"audit-skill {rule_id}"},
                "fullDescription": {"text": f.msg.split("—")[0].strip()[:200]},
                "defaultConfiguration": {
                    "level": {"drift": "warning", "info": "note", "error": "error"}.get(f.severity, "note")
                },
            }
        loc_path = (f.path or skill_name).replace("\\", "/")
        location = {
            "physicalLocation": {
                "artifactLocation": {"uri": loc_path},
            }
        }
        if f.line is not None:
            location["physicalLocation"]["region"] = {"startLine": f.line}
        results.append({
            "ruleId": rule_id,
            "level": {"drift": "warning", "info": "note", "error": "error"}.get(f.severity, "note"),
            "message": {"text": f.msg},
            "locations": [location],
            "properties": {"skill": skill_name, "severity": f.severity},
        })
    sarif = {
        "$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cs01/schemas/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "audit-skill",
                    "informationUri": "https://github.com/brandyn-s/claude-harness",
                    "rules": list(rules_seen.values()),
                }
            },
            "results": results,
        }],
    }
    return json.dumps(sarif, indent=2)


def _skill_surface(skill_name):
    """Deterministic Phase-2 surface map for one skill: which audit
    categories have a real surface vs are N/A. Lets `--all` Phase 2 tier
    effort (deep scenario audit where scripts/commands exist; light
    A3 + prose-drift pass for prose-only skills) instead of re-deriving
    N/A for every prose skill. See SKILL.md "Dispatching Phase 2
    (execution model)". The map is advisory: A3/F2/F3 depend on prose
    claims and cannot be ruled out mechanically, so they are tagged
    "review", not applicable / n-a."""
    sdir = SKILLS / skill_name
    scripts = sorted(
        str(p.relative_to(sdir)).replace("\\", "/")
        for p in sdir.rglob("*")
        if p.is_file()
        and p.suffix in (".py", ".sh")
        and "test" not in str(p.relative_to(sdir)).lower()
    )
    has_scripts = bool(scripts)
    has_cli = any(
        "__main__" in (sdir / s).read_text(encoding="utf-8", errors="replace")
        for s in scripts
        if s.endswith(".py")
    )
    md_path = sdir / "SKILL.md"
    md_text = md_path.read_text(encoding="utf-8", errors="replace") if md_path.exists() else ""
    # Count only EXPLICIT shell-tagged fences (```bash/```sh/```shell/```zsh),
    # NOT bare ``` blocks. _iter_bash_blocks treats a bare fence as bash, which
    # over-counts a prose skill's command surface — api-preflight has ONE real
    # ```bash block but 11 bare/markdown fences, so the inclusive count
    # mis-tiered it "deep". An explicit shell tag is an unambiguous A1 signal
    # and matches the SKILL.md "fenced bash blocks" wording + the original
    # surface analysis (~a third of the corpus is script-bearing).
    bash_block_count = len(re.findall(r"(?m)^[ \t]*```(?:bash|sh|shell|zsh)\b", md_text))
    refs_dir = sdir / "references"
    references_count = sum(1 for _ in refs_dir.glob("*.md")) if refs_dir.is_dir() else 0
    # Tier mirrors the SKILL.md heuristic: a skill with executable scripts
    # OR >=5 fenced bash blocks has real A1/B/D/F surface (deep); otherwise
    # only A1 (the few commands), A3, and prose-drift apply (light).
    tier = "deep" if (has_scripts or bash_block_count >= 5) else "light"
    categories = {
        "A1": "applicable" if bash_block_count > 0 else "n-a:no-bash-blocks",
        "A3": "review",  # invariant claims are prose — agent must scan
        "B": "applicable" if has_cli else "n-a:no-CLI",
        "D1": "applicable" if has_scripts else "n-a:no-scripts",
        "D2": "applicable" if has_scripts else "n-a:no-scripts",
        "D4": "applicable" if references_count > 0 else "n-a:no-references",
        "F2": "review",  # documented thresholds are prose — agent must scan
        "F3": "review",  # discrete output modes are prose — agent must scan
    }
    return {
        "skill": skill_name,
        "tier": tier,
        "has_scripts": has_scripts,
        "has_cli": has_cli,
        "bash_block_count": bash_block_count,
        "references_count": references_count,
        "scripts": scripts,
        "categories": categories,
    }


def _render_surface_map(skill_names):
    """Emit the per-skill Phase-2 surface map as JSON on stdout. Read-only;
    runs no lint and writes nothing."""
    skills = [_skill_surface(s) for s in skill_names]
    summary = {
        "total": len(skills),
        "deep": sum(1 for s in skills if s["tier"] == "deep"),
        "light": sum(1 for s in skills if s["tier"] == "light"),
    }
    return json.dumps({"summary": summary, "skills": skills}, indent=2)


def main(argv):
    args = argv[1:]
    # Short-circuit --help / -h before any skill-name resolution; otherwise
    # "--help" would be treated as a positional <skill-name> and produce
    # the "skill directory not found" error.
    if any(a in ("-h", "--help") for a in args):
        print(USAGE)
        return 0
    strict = False
    check_marketplace = False
    no_marketplace_check = False
    strict_tools = False
    json_output = False
    sarif_output = False
    changed_base = ""  # if set, audit only skills touched since this ref
    fix_codes = None  # None = no fix mode; set = codes to apply
    parallel = 1  # 1 = serial (default; back-compat). >1 enables ProcessPoolExecutor.
    ndjson_path = None  # if set, append one record per finding to this NDJSON file.
    surface_map = False  # if set, emit the Phase-2 surface map as JSON and exit (no lint).
    for f in list(args):
        if f == "--strict":
            strict = True
            args.remove(f)
        elif f == "--check-marketplace":
            check_marketplace = True
            args.remove(f)
        elif f == "--no-marketplace-check":
            no_marketplace_check = True
            args.remove(f)
        elif f == "--strict-tools":
            strict_tools = True
            args.remove(f)
        elif f == "--json":
            json_output = True
            args.remove(f)
        elif f == "--sarif":
            sarif_output = True
            args.remove(f)
        elif f == "--surface-map":
            surface_map = True
            args.remove(f)
        elif f.startswith("--parallel="):
            # --parallel=N runs the per-skill audits via ProcessPoolExecutor.
            # The per-skill audit is CPU-bound (regex + AST parse + file
            # reads under the page cache), so processes — not threads —
            # give real speedup; the GIL would serialize threads.
            # Findings are still reported in deterministic skill_names
            # order; the parallelism only changes WHERE the work
            # happens, not WHAT is printed. Default 1 preserves
            # byte-for-byte serial output.
            try:
                parallel = max(1, int(f.split("=", 1)[1]))
            except ValueError:
                sys.exit(f"--parallel: expected integer, got {f.split('=', 1)[1]!r}")
            args.remove(f)
        elif f == "--parallel":
            parallel = 4
            args.remove(f)
        elif f.startswith("--ndjson="):
            # --ndjson=PATH appends one record per finding to PATH. Each line
            # is a standalone JSON object — replayable, grep-able, suitable
            # for cross-run analysis via skills/audit-skill/scripts/audit_history.py.
            # This is component 8 (observability) of the eight-component
            # harness framework — see skills/audit-skill/SKILL.md "Eight-component map".
            ndjson_path = f.split("=", 1)[1]
            args.remove(f)
        elif f.startswith("--changed="):
            changed_base = f.split("=", 1)[1] or "origin/main"
            args.remove(f)
        elif f == "--changed":
            changed_base = "origin/main"
            args.remove(f)
        elif f.startswith("--fix="):
            raw = f.split("=", 1)[1]
            fix_codes = set(c.strip().upper() for c in raw.split(",") if c.strip())
            args.remove(f)
        elif f == "--fix":
            fix_codes = {"C5", "C7"}
            args.remove(f)
    if not args:
        sys.exit(USAGE)
    # Reject empty-string args explicitly — otherwise an empty arg would
    # resolve under SKILLS root and produce an obscure "missing SKILL.md"
    # error rather than a usage hint.
    for a in args:
        if not a.strip():
            sys.exit(USAGE)

    if args[0] == "--all":
        skill_names = sorted(p.name for p in SKILLS.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
        # --all implies marketplace freshness check by default; opt out with --no-marketplace-check
        if not no_marketplace_check:
            check_marketplace = True
    else:
        skill_names = args

    # --surface-map mode: emit the deterministic Phase-2 surface map as
    # JSON and exit. Read-only — runs no lint, writes nothing. Lets the
    # operator tier `--all` Phase 2 effort without re-deriving which
    # categories are N/A per skill. Returns before the marketplace check
    # (--all sets check_marketplace above, but the map never needs it).
    if surface_map:
        print(_render_surface_map(skill_names))
        return 0

    # --fix mode: apply mechanical fixes for the listed codes (default
    # C5,C7). Runs BEFORE the audit pass so the audit reports the
    # post-fix state. Skips SARIF + JSON output — fix mode emits a
    # human-readable per-file summary on stdout.
    if fix_codes is not None:
        if args[0] == "--all":
            targets = list(skill_names) + ["__repo__"]
        else:
            targets = list(skill_names)
        summary = _apply_fixes(targets, fix_codes)
        total_files = 0
        total_count = 0
        for skill_name, by_code in sorted(summary.items()):
            file_count = sum(by_code.values())
            total_files += 1
            total_count += file_count
            codes_str = ", ".join(f"{c}={n}" for c, n in sorted(by_code.items()))
            print(f"FIX {skill_name}: {codes_str}")
        if total_count == 0:
            print(f"--fix={','.join(sorted(fix_codes))}: no fixes applied "
                  f"(no eligible findings on the targeted skills).")
        else:
            print(f"--fix={','.join(sorted(fix_codes))}: applied "
                  f"{total_count} fix(es) across {total_files} skill(s). "
                  f"Re-run audit to verify and commit the diff.")
        return 0

    # --changed filter: narrow skill_names to those touched in the
    # git diff against `changed_base`. Useful for PR CI to audit
    # only what the PR modifies (~2s vs ~30s for --all on 89 skills).
    # Falls back to the full list on git failure / unknown ref.
    if changed_base:
        touched = _skills_touched_since(changed_base)
        if touched is None:
            print(f"warn: --changed={changed_base} couldn't resolve via git; "
                  f"auditing the original set", file=sys.stderr)
        else:
            filtered = [s for s in skill_names if s in touched]
            print(f"--changed={changed_base}: "
                  f"narrowed to {len(filtered)} of {len(skill_names)} skill(s) "
                  f"touched in the diff",
                  file=sys.stderr)
            skill_names = filtered

    # SARIF output: collect findings instead of printing per-skill.
    # SARIF 2.1.0 spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/
    if sarif_output:
        all_findings: list[tuple[str, Finding]] = []
        for skill_name in skill_names:
            for f in audit(skill_name, strict_tools=strict_tools):
                all_findings.append((skill_name, f))
        if args[0] == "--all":
            for f in _audit_repo_python() + _audit_repo_shell():
                all_findings.append(("__repo__", f))
        print(_render_sarif(all_findings))
        # exit codes mirror normal mode:
        total_errors = sum(1 for _, f in all_findings if f.severity == "error")
        total_drift = sum(1 for _, f in all_findings if f.severity == "drift")
        if total_errors:
            return 1
        if total_drift and strict:
            return 1
        return 0

    total_drift = 0
    total_errors = 0
    reporter = report_json if json_output else report

    # NDJSON writer setup (component 8 — observability). Opens the file in
    # append mode and emits one record per finding as the loop progresses.
    # This is the replayable event log; it does NOT replace the human/JSON
    # report — it's an additional emission for cross-run analysis.
    ndjson_handle = None
    ndjson_run_id = None
    if ndjson_path:
        import datetime
        # timezone-aware now(): utcnow() is deprecated since 3.12 and the
        # DeprecationWarning landed on the documented Phase 4 command path.
        ndjson_run_id = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        ndjson_handle = open(ndjson_path, "a", buffering=1, encoding="utf-8")

    def _emit_ndjson(skill_name, findings):
        if ndjson_handle is None:
            return
        import json as _json
        for f in findings:
            ndjson_handle.write(_json.dumps({
                "run_id": ndjson_run_id,
                "skill": skill_name,
                "code": f.code,
                "severity": f.severity,
                "msg": f.msg,
                "path": f.path,
                "line": f.line,
            }) + "\n")

    if parallel > 1 and len(skill_names) > 1:
        # Parallel branch (component 5 — orchestration). Use processes
        # rather than threads: the per-skill audit is CPU-bound (regex,
        # AST parse, dataclass construction), so the GIL serializes
        # ThreadPoolExecutor; ProcessPoolExecutor gets real speedup.
        # Findings ship back via pickle; Finding is a dataclass with
        # string fields so it pickles cleanly. Report in deterministic
        # skill_names order so output is identical to the serial branch
        # modulo parallelism artifacts.
        from concurrent.futures import ProcessPoolExecutor
        findings_by_skill = {}
        with ProcessPoolExecutor(max_workers=parallel) as pool:
            futures = {pool.submit(audit, name, strict_tools=strict_tools): name
                       for name in skill_names}
            for fut in futures:
                name = futures[fut]
                findings_by_skill[name] = fut.result()
        for skill_name in skill_names:
            findings = findings_by_skill[skill_name]
            _emit_ndjson(skill_name, findings)
            drift = reporter(skill_name, findings)
            total_drift += drift
            total_errors += sum(1 for f in findings if f.severity == "error")
    else:
        # Serial branch (back-compat). Single-skill or --parallel=1.
        for skill_name in skill_names:
            findings = audit(skill_name, strict_tools=strict_tools)
            _emit_ndjson(skill_name, findings)
            drift = reporter(skill_name, findings)
            total_drift += drift
            total_errors += sum(1 for f in findings if f.severity == "error")

    # Repo-wide audit — only under --all. Runs C5/C6/C7/C9/C10 against
    # `bin/`, `hooks/` (non-test), `manifests/`, `scripts/`, root *.py
    # AND C8 against *.sh repo-wide. The per-skill audit only covers
    # the skill's own scripts/+references/; the surface OUTSIDE that
    # (the entire CI tool surface, every production hook, statusline,
    # etc.) had no coverage. PR #977's bugs lived in `bin/audit-skill.py`,
    # which was reachable only via this pass.
    #
    # Findings appear under the synthetic skill name `__repo__` so the
    # existing report machinery handles them uniformly.
    if args[0] == "--all":
        repo_findings = (
            _audit_repo_python()
            + _audit_repo_shell()
            + _audit_hook_test_coverage()
        )
        repo_drift = reporter("__repo__", repo_findings)
        # The event log must carry the repo-wide pass too: audit_history.py
        # and `oracle report --phase1` read ONLY the NDJSON, so without this
        # emission every __repo__ finding silently vanished from history
        # rows and Phase 4 reports (2026-06-12 campaign: 2 B2 rows present
        # on stdout, absent from the 26-row NDJSON).
        _emit_ndjson("__repo__", repo_findings)
        total_drift += repo_drift
        total_errors += sum(1 for f in repo_findings if f.severity == "error")

    marketplace_failed = False
    if check_marketplace:
        ok, msg = check_marketplace_freshness()
        prefix = "OK  " if ok else "FAIL"
        print(f"\n{prefix} marketplace freshness: {msg}")
        if not ok:
            marketplace_failed = True

    # Errors (E0: skill not found) always exit non-zero. Drift only does so
    # under --strict. Without this, a caller doing
    #   `audit-skill.py myskill && deploy` would deploy even when the
    # Close the NDJSON handle if we opened one. Idempotent if None.
    if ndjson_handle is not None:
        ndjson_handle.close()

    # skill directory is missing entirely.
    if total_errors:
        if total_drift:
            print(f"\n{total_errors} error(s) + {total_drift} drift across {len(skill_names)} skill(s)")
        else:
            print(f"\n{total_errors} error(s) across {len(skill_names)} skill(s)")
        return 1
    if marketplace_failed:
        return 1
    if total_drift and strict:
        print(f"\n{total_drift} drift finding(s) across {len(skill_names)} skill(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
