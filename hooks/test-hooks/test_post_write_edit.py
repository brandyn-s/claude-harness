"""Tests for post-write-edit.py.

Validates encoding checks, syntax checks, and secret scanning.
"""
import json
import shutil

import pytest
from conftest import run_hook

HOOK = "post-write-edit.py"

# check_ruff_lint swallows FileNotFoundError, so on a runner without ruff the
# hook silently does nothing. That makes a "the hook preserved my noqa" test
# pass VACUOUSLY -- it preserved it by never touching the file. ruff is NOT in
# requirements-dev.txt, so the tests.yml hook-test job has no ruff, and the
# vacuum is the normal CI condition rather than an edge case.
#
# Skip rather than pass: a green test that proves nothing is worse than an
# honest skip. Discovered by the negative-control test below, which failed in
# CI (F541 not auto-fixed) while its preservation sibling passed -- the exact
# asymmetry that reveals the instrument never ran.
requires_ruff = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason=(
        "ruff not on PATH -- the hook's ruff step no-ops via its "
        "except FileNotFoundError, so these assertions would be vacuous"
    ),
)


def make_write_result(file_path):
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path},
        "tool_result": "",
    }


# ── Encoding checks ──


def test_python_missing_encoding_blocks(tmp_path):
    """Upgraded 2026-04-21: warn → block for 35.8% violation rate.
    2026-06-27: cp1252 is Windows-only, so the hard block now fires only on
    win32 (or under CLAUDE_ENCODING_GUARD_FORCE, set globally by conftest) —
    this test exercises that forced/win32 block path. The non-win32 production
    WARN behavior is covered by test_python_missing_encoding_warns_off_windows."""
    py_file = tmp_path / "target.py"
    py_file.write_text("f = open('data.txt', 'r')\n", encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    assert stdout.strip(), "encoding violation should produce JSON decision output"
    out = json.loads(stdout.splitlines()[0])
    assert out.get("decision") == "block"
    assert "encoding" in out.get("reason", "").lower()


def test_python_missing_encoding_warns_off_windows(tmp_path):
    """2026-06-27: on non-win32 (cp1252 can't occur — macOS/Linux open()=UTF-8)
    the encoding check DOWNGRADES block → portability WARN; the write is
    allowed. Disable the conftest force-flag to assert the production behavior."""
    import sys
    if sys.platform == "win32":
        return  # genuinely blocks on Windows
    py_file = tmp_path / "warn.py"
    py_file.write_text("f = open('data.txt', 'r')\n", encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)),
                             env={"CLAUDE_ENCODING_GUARD_FORCE": "0"})
    assert rc == 0
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                assert out.get("decision") != "block", f"should warn, not block: {out}"
            except json.JSONDecodeError:
                pass
    assert "encoding" in stdout.lower(), "warn should still nudge about encoding="


def test_python_with_encoding_no_block(tmp_path):
    py_file = tmp_path / "clean.py"
    py_file.write_text(
        "f = open('data.txt', 'r', encoding='utf-8')\n", encoding="utf-8"
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    # No encoding block in any JSON decision output
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                if out.get("decision") == "block":
                    assert "encoding" not in out.get("reason", "").lower()
            except json.JSONDecodeError:
                pass


def test_python_binary_mode_no_block(tmp_path):
    py_file = tmp_path / "binary.py"
    py_file.write_text("f = open('data.bin', 'rb')\n", encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                assert out.get("decision") != "block"
            except json.JSONDecodeError:
                pass


def test_python_no_mode_open_blocks(tmp_path):
    """Regression: 2026-05-22 audit-rules probe showed `open('foo.json')`
    with no mode argument was the dominant 35% session-rate violation and
    bypassed the prior mode-literal check. Must now block."""
    py_file = tmp_path / "nomode.py"
    py_file.write_text(
        "import json\ndata = json.load(open('settings.json'))\n",
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    assert stdout.strip(), "no-mode open() must produce a block decision"
    out = json.loads(stdout.splitlines()[0])
    assert out.get("decision") == "block"
    assert "encoding" in out.get("reason", "").lower()


# ── Docstring / string-literal exclusions (2026-05-26) ──
#
# These ensure the hook agrees with bin/audit-skill.py's C5 detection on
# what counts as a real source-level call. The previous version false-fired
# on lint-of-lint code (audit-skill.py, its test fixtures) that legitimately
# has `open(` literals in docstrings and string args.
# Fixture content uses an _OPEN constant to avoid this test file ALSO
# false-firing the hook on its own fixture data when written to disk.


def test_python_open_in_module_docstring_no_block(tmp_path):
    """Module-level docstring describing `open(...)` — no executed code."""
    _OPEN = "o" + "pen("
    py_file = tmp_path / "doc.py"
    py_file.write_text(
        f'"""Module that opens files.\n\n'
        f'Example: {_OPEN}\'foo.txt\', \'r\').read()\n'
        f'"""\nx = 1\n',
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                if out.get("decision") == "block":
                    assert "encoding" not in out.get("reason", "").lower(), \
                        f"docstring should not block: {out}"
            except json.JSONDecodeError:
                pass


def test_python_open_in_function_docstring_no_block(tmp_path):
    """Function docstring with an `open(...)` example."""
    _OPEN = "o" + "pen("
    py_file = tmp_path / "fn.py"
    py_file.write_text(
        f'def foo():\n'
        f'    """Reads a file.\n\n'
        f'    Equivalent to: {_OPEN}path).read()\n'
        f'    """\n'
        f'    return 42\n',
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                if out.get("decision") == "block":
                    assert "encoding" not in out.get("reason", "").lower(), \
                        f"function docstring should not block: {out}"
            except json.JSONDecodeError:
                pass


def test_python_open_in_string_literal_arg_no_block(tmp_path):
    """`open(` appearing as content inside a string passed to .write_text."""
    _OPEN = "o" + "pen("
    py_file = tmp_path / "fixture.py"
    py_file.write_text(
        f'from pathlib import Path\n'
        f'Path("f.py").write_text("{_OPEN}\'x\').read()", encoding="utf-8")\n',
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                if out.get("decision") == "block":
                    assert "encoding" not in out.get("reason", "").lower(), \
                        f"string literal content should not block: {out}"
            except json.JSONDecodeError:
                pass


def test_python_open_after_docstring_still_blocks(tmp_path):
    """Regression guard: a docstring at top + a real `open()` after it
    must still block on the real call. The fix mustn't accidentally
    suppress code that follows a docstring."""
    _OPEN = "o" + "pen("
    py_file = tmp_path / "mixed.py"
    py_file.write_text(
        f'"""Module that {_OPEN}files."""\n'
        f'f = open(\'real.txt\')\n',
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    assert stdout.strip(), "real open() after docstring must still block"
    out = json.loads(stdout.splitlines()[0])
    assert out.get("decision") == "block"
    assert "encoding" in out.get("reason", "").lower()


# ── str.replace CRLF risk (promoted from bulk-api-script 2026-04-21) ──


def test_str_replace_crlf_with_file_read_warns(tmp_path):
    py_file = tmp_path / "xform.py"
    py_file.write_text(
        "with open('x.txt', 'r', encoding='utf-8') as f:\n"
        "    data = f.read()\n"
        "result = data.replace('\\n', ' ')\n",
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    found_warn = False
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                # advisory now emits systemMessage (not the invalid decision:"warn")
                if "crlf" in out.get("systemMessage", "").lower():
                    found_warn = True
            except json.JSONDecodeError:
                pass
    assert found_warn, "expected CRLF systemMessage advisory for str.replace near file read"


def test_str_replace_without_file_read_no_warn(tmp_path):
    py_file = tmp_path / "pure.py"
    py_file.write_text(
        "template = 'a\\nb\\nc'\n"
        "result = template.replace('\\n', ', ')\n",
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                if out.get("decision") == "warn":
                    assert "crlf" not in out.get("reason", "").lower()
            except json.JSONDecodeError:
                pass


def test_file_read_without_str_replace_no_warn(tmp_path):
    py_file = tmp_path / "read.py"
    py_file.write_text(
        "with open('x.txt', 'r', encoding='utf-8') as f:\n"
        "    data = f.read()\n"
        "print(data)\n",
        encoding="utf-8",
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    for line in stdout.splitlines():
        if line.strip():
            try:
                out = json.loads(line)
                if out.get("decision") == "warn":
                    assert "crlf" not in out.get("reason", "").lower()
            except json.JSONDecodeError:
                pass


# ── Syntax checks ──


def test_python_syntax_error_warns(tmp_path):
    py_file = tmp_path / "bad_syntax.py"
    py_file.write_text("def foo(\n", encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    if stdout.strip():
        out = json.loads(stdout)
        # advisory now emits systemMessage (not the invalid decision:"warn"/reason shape)
        assert "syntax" in out.get("systemMessage", "").lower()


def test_python_valid_syntax_no_warn(tmp_path):
    py_file = tmp_path / "valid.py"
    py_file.write_text("def foo():\n    return 42\n", encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    if stdout.strip():
        try:
            out = json.loads(stdout)
            assert "syntax" not in out.get("reason", "").lower()
        except json.JSONDecodeError:
            pass


# ── Secret scanning ──


def test_secret_detection_api_key(tmp_path):
    py_file = tmp_path / "secrets.py"
    py_file.write_text(
        'API_KEY = "sk-1234567890abcdefghijklmnopqrst"\n', encoding="utf-8"
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    if stdout.strip():
        out = json.loads(stdout)
        # Advisory now emits systemMessage (NOT the invalid decision:"warn" the PostToolUse
        # schema silently drops — mega-retro FLAW on eff98a2f, 16x recurrence). The advisory
        # content moved from "reason" into "systemMessage".
        msg = out.get("systemMessage", "")
        assert "secret" in msg.lower() or "key" in msg.lower(), f"expected systemMessage advisory, got {out}"


def test_secret_advisory_uses_systemmessage_not_warn(tmp_path):
    """Regression for the mega-retro-found bug: the secret/syntax/CRLF advisories emitted
    {"decision":"warn"}, which the PostToolUse hook-output schema (approve|block only) silently
    drops — so the warning never reached anyone (16x on eff98a2f). They must emit systemMessage."""
    py_file = tmp_path / "leak.py"
    py_file.write_text('key = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    assert stdout.strip(), "secret detection should produce advisory output"
    out = json.loads(stdout.splitlines()[0])
    # the invalid 'warn' decision must NOT appear; the advisory must be a systemMessage
    assert out.get("decision") != "warn", "decision:'warn' is invalid for PostToolUse — silently dropped"
    assert out.get("systemMessage"), f"advisory must use systemMessage, got keys {list(out.keys())}"


def test_secret_detection_aws_key(tmp_path):
    py_file = tmp_path / "aws_creds.py"
    py_file.write_text('key = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    if stdout.strip():
        out = json.loads(stdout)
        msg = out.get("systemMessage", "").lower()
        assert "aws" in msg or "key" in msg


def test_secret_skip_markdown(tmp_path):
    md_file = tmp_path / "readme.md"
    md_file.write_text(
        'API_KEY = "sk-1234567890abcdefghijklmnopqrst"\n', encoding="utf-8"
    )
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(md_file)))
    assert rc == 0
    assert not stdout.strip() or "secret" not in stdout.lower()


def test_secret_skip_test_file(tmp_path):
    test_file = tmp_path / "test_auth.py"
    test_file.write_text('token = "sk-faketoken12345678901234567"\n', encoding="utf-8")
    rc, stdout, _ = run_hook(HOOK, make_write_result(str(test_file)))
    assert rc == 0
    assert not stdout.strip() or "secret" not in stdout.lower()


# ── Edge cases ──


def test_nonexistent_file_exits_clean(tmp_path):
    rc, _, _ = run_hook(HOOK, make_write_result(str(tmp_path / "nonexistent.py")))
    assert rc == 0


def test_non_python_no_encoding_check(tmp_path):
    js_file = tmp_path / "app.js"
    js_file.write_text("const fs = require('fs');\n", encoding="utf-8")
    rc, _, stderr = run_hook(HOOK, make_write_result(str(js_file)))
    assert rc == 0
    assert "encoding" not in stderr.lower()


# ── noqa preservation (ruff auto-fix) ──


@requires_ruff
def test_ruff_autofix_preserves_noqa_directives(tmp_path):
    """The hook must never DELETE a `# noqa` comment.

    When the edited project has no ruff.toml / pyproject.toml, ruff falls back
    to its default select (E4, E7, E9, F). A noqa for any rule outside that set
    then looks unused to RUF100 and was silently auto-removed by the hook's
    `ruff check --fix`.

    Measured 2026-08-15 (ruff 0.16.1) before the fix: both directives below
    were stripped, and plain `ruff check` still reported "All checks passed",
    so nothing surfaced the deletion. Real consequence: usb-exemption-slack has
    no ruff config and its main relies on `# noqa: S105`, so any edit to that
    file turned CI red on a line the author never touched.

    Closed with --extend-unfixable RUF100.
    """
    py_file = tmp_path / "noqa_target.py"
    original = (
        'URL = "https://api.example.com/oauth/token"  # noqa: S105\n'
        "WIDE = 1  # noqa: E501\n"
    )
    py_file.write_text(original, encoding="utf-8")

    rc, _, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0

    after = py_file.read_text(encoding="utf-8")
    assert "# noqa: S105" in after, (
        "hook stripped `# noqa: S105` -- RUF100 auto-fix is deleting "
        "suppressions the project's real config depends on"
    )
    assert "# noqa: E501" in after, "hook stripped `# noqa: E501`"


@requires_ruff
def test_ruff_autofix_still_fixes_real_violations(tmp_path):
    """Negative control for the test above.

    A fix that simply disabled ruff's --fix would also pass the noqa test, so
    assert that a genuinely fixable default-selected violation (F541, f-string
    with no placeholders) is STILL auto-fixed with --extend-unfixable present.
    """
    py_file = tmp_path / "fixable_target.py"
    py_file.write_text(
        'GREET = f"no placeholders here"  # noqa: S105\n',
        encoding="utf-8",
    )

    rc, _, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0

    after = py_file.read_text(encoding="utf-8")
    assert 'f"no placeholders' not in after, (
        "F541 was NOT auto-fixed -- the noqa fix has disabled legitimate "
        "auto-fixing instead of narrowing it"
    )
    assert "# noqa: S105" in after, "noqa must survive alongside a real fix"


@requires_ruff
def test_ruff_configless_repo_does_not_sort_imports(tmp_path):
    """In a repo with no ruff config, the hook must not rewrite whole files.

    Homebrew ruff 0.16.4's default select (even under --isolated) resolves
    413 rules including I001 import sorting and SIM restructuring, so a bare
    `ruff check --fix` in a config-less repo rewrote entire files far beyond
    the edit (measured 2026-08-27: ~500 lines of review churn on a 370-line
    mcp-infra change). The hook pins --isolated --select E4,E7,E9,F when the
    file's project does not configure ruff.

    tmp_path has no ruff.toml / pyproject.toml and no .git, so this exercises
    the config-less branch.
    """
    py_file = tmp_path / "unsorted_imports.py"
    original = "import sys\nimport os\n\nprint(os.name, sys.argv)\n"
    py_file.write_text(original, encoding="utf-8")

    rc, _, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    assert py_file.read_text(encoding="utf-8") == original, (
        "the hook re-sorted imports in a repo that does not configure ruff -- "
        "the config-less select pin is not being applied"
    )


@requires_ruff
def test_ruff_repo_with_config_keeps_its_own_select(tmp_path):
    """A repo that DOES configure ruff keeps its config verbatim.

    Negative control for the config-less pin: with a ruff.toml selecting I,
    the same unsorted-import file MUST be sorted, proving the pin narrows only
    config-less repos rather than disabling project lint everywhere.
    """
    (tmp_path / "ruff.toml").write_text(
        'lint.select = ["I"]\n', encoding="utf-8"
    )
    py_file = tmp_path / "unsorted_imports.py"
    py_file.write_text(
        "import sys\nimport os\n\nprint(os.name, sys.argv)\n", encoding="utf-8"
    )

    rc, _, _ = run_hook(HOOK, make_write_result(str(py_file)))
    assert rc == 0
    assert py_file.read_text(encoding="utf-8").startswith("import os\nimport sys\n"), (
        "the project's own ruff config was not honored -- the config-less pin "
        "is over-applying"
    )
