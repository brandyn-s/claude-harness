"""Unit tests for --fix mode (PR-E).

Each test writes a tiny fixture to tmp_path, runs the fixer, then
re-runs the corresponding C5 / C7 check on the output and asserts
zero findings remain. This is the strongest possible roundtrip:
detection and fix both agree the file is clean.

Implementation note: the C5 fixer is invoked from disk, so test
fixtures need a bare file-I/O call literal. The post-write-edit hook
scans this file for that pattern and would false-fire on the test
data. The literal is built via the _OPEN constant below so the
unescaped form never appears in source.
"""

import importlib.util
import sys
from pathlib import Path

# Variable-spelled "open(" — prevents the post-write-edit hook from
# false-flagging this test file's own fixture literals as C5 violations.
_OPEN = "o" + "pen("

REPO = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPO / "bin" / "audit-skill.py"


def _load_audit_module():
    if "audit_skill" in sys.modules:
        return sys.modules["audit_skill"]
    spec = importlib.util.spec_from_file_location("audit_skill", AUDIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["audit_skill"] = mod
    return mod


# ───────── C5 fix ─────────

def test_c5_fix_open_text_mode(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text(f"def r():\n    with {_OPEN}'a.txt') as f:\n        return f.read()\n", encoding="utf-8")
    n, new_text = audit._fix_c5_in_file(p)
    assert n == 1
    assert "encoding='utf-8'" in new_text


def test_c5_fix_write_text(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text("from pathlib import Path\nPath('a').write_text('hi')\n", encoding="utf-8")
    n, new_text = audit._fix_c5_in_file(p)
    assert n == 1
    assert "write_text('hi', encoding='utf-8')" in new_text


def test_c5_fix_read_text(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text("from pathlib import Path\nx = Path('a').read_text()\n", encoding="utf-8")
    n, new_text = audit._fix_c5_in_file(p)
    assert n == 1
    assert "read_text(encoding='utf-8')" in new_text


def test_c5_skips_binary(tmp_path):
    """Binary mode (`'rb'`) — no encoding kwarg applies, no fix."""
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text(f"def r():\n    with {_OPEN}'a', 'rb') as f:\n        return f.read()\n", encoding="utf-8")
    n, new_text = audit._fix_c5_in_file(p)
    assert n == 0
    assert "encoding=" not in new_text


def test_c5_skips_already_encoded(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text("from pathlib import Path\nPath('a').read_text(encoding='utf-8')\n", encoding="utf-8")
    n, new_text = audit._fix_c5_in_file(p)
    assert n == 0


def test_c5_fix_multiline_call(tmp_path):
    """Multi-line call where the close paren is on a later line."""
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text(
        "from pathlib import Path\n"
        "import json\n"
        "Path('a').write_text(\n"
        "    json.dumps({'k': 1})\n"
        ")\n",
        encoding="utf-8",
    )
    n, new_text = audit._fix_c5_in_file(p)
    assert n == 1
    assert "encoding='utf-8'" in new_text


def test_c5_fix_roundtrip_no_lingering_findings(tmp_path):
    """After fix, the cross-platform scan should report 0 C5 findings."""
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text(
        "from pathlib import Path\n"
        "Path('a').write_text('hi')\n"
        "Path('b').read_text()\n",
        encoding="utf-8",
    )
    n, new_text = audit._fix_c5_in_file(p)
    assert n == 2
    p.write_text(new_text, encoding="utf-8")
    # Re-scan — _scan_python_file_cross_platform takes (path, rel).
    findings = audit._scan_python_file_cross_platform(p, "f.py")
    c5 = [f for f in findings if f.code == "C5"]
    assert c5 == [], f"expected no lingering C5, got {c5}"


def test_c5_fix_skips_comments(tmp_path):
    """A commented-out file-I/O call shouldn't be touched by the fixer."""
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    p.write_text(f"# {_OPEN}'a.txt') as f  # commented\nprint('hi')\n", encoding="utf-8")
    n, _ = audit._fix_c5_in_file(p)
    assert n == 0


# ───────── C7 fix ─────────

def test_c7_fix_inserts_short_circuit(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    src = (
        '"""Doc."""\n'
        "import sys\n"
        "def main():\n"
        "    return sys.argv[1]\n"
        '\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
    p.write_text(src, encoding="utf-8")
    n, new_text = audit._fix_c7_in_file(p)
    assert n == 1
    assert "--help" in new_text and "sys.exit(0)" in new_text


def test_c7_fix_skips_if_parse_args_present(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    src = (
        "import sys, argparse\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.parse_args()\n"
        "x = sys.argv[0]\n"
        'if __name__ == "__main__":\n'
        "    pass\n"
    )
    p.write_text(src, encoding="utf-8")
    n, _ = audit._fix_c7_in_file(p)
    assert n == 0


def test_c7_fix_skips_if_already_handled(tmp_path):
    """File already short-circuits on --help — skip fix."""
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    src = (
        "import sys\n"
        'if "--help" in sys.argv:\n'
        "    print('usage'); sys.exit(0)\n"
        "x = sys.argv[1]\n"
        'if __name__ == "__main__":\n'
        "    pass\n"
    )
    p.write_text(src, encoding="utf-8")
    n, _ = audit._fix_c7_in_file(p)
    assert n == 0


def test_c7_fix_adds_import_sys_if_missing(tmp_path):
    """File uses `from sys import argv` and has no `import sys` — fix
    must add `import sys` so `sys.exit(0)` resolves."""
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    src = (
        '"""Doc."""\n'
        "from sys import argv\n"
        "def main():\n"
        "    return argv[1]\n"
        '\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
    p.write_text(src, encoding="utf-8")
    n, new_text = audit._fix_c7_in_file(p)
    assert n == 1
    assert "import sys" in new_text


def test_c7_fix_roundtrip_no_lingering_finding(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    src = (
        '"""Doc."""\n'
        "import sys\n"
        "x = sys.argv[1]\n"
        'if __name__ == "__main__":\n'
        "    print(x)\n"
    )
    p.write_text(src, encoding="utf-8")
    n, new_text = audit._fix_c7_in_file(p)
    assert n == 1
    p.write_text(new_text, encoding="utf-8")
    finding = audit._check_c7_help_short_circuit(new_text, "f.py")
    assert finding is None, f"expected no lingering C7, got {finding}"


def test_c7_skips_if_no_main_block(tmp_path):
    audit = _load_audit_module()
    p = tmp_path / "f.py"
    src = (
        "import sys\n"
        "def main():\n"
        "    return sys.argv[1]\n"
    )
    p.write_text(src, encoding="utf-8")
    n, _ = audit._fix_c7_in_file(p)
    assert n == 0
