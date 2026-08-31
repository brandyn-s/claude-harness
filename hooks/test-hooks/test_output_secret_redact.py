"""Tests for output-secret-redact.py — PostToolUse Bash output secret redaction.

Contract: scans Bash tool_response stdout/stderr for HIGH-CONFIDENCE secret
patterns and replaces only the secret substring via updatedToolOutput,
preserving surrounding output + the {interrupted, isImage} fields. No-op (no
stdout, exit 0) when clean. Non-Bash passes through. Fails open on error.
The false-positive tests are load-bearing: over-redacting hashes/UUIDs/base64
the model needs would be worse than the narrow leak this prevents.
"""
import json

import pytest

from conftest import run_hook

HOOK = "output-secret-redact.py"


def _resp(stdout="", stderr="", interrupted=False, isImage=False):
    return {"tool_name": "Bash",
            "tool_response": {"stdout": stdout, "stderr": stderr,
                              "interrupted": interrupted, "isImage": isImage}}


def _run(payload):
    rc, out, _err = run_hook(HOOK, payload)
    return rc, (json.loads(out) if out.strip() else None)


def _uo(out):
    return out["hookSpecificOutput"]["updatedToolOutput"]


def test_redacts_aws_and_github_keys():
    rc, out = _run(_resp(stdout="key=AKIA1234567890ABCDEF\ntok=ghp_" + "a" * 36))
    assert rc == 0 and out is not None
    s = _uo(out)["stdout"]
    assert "AKIA1234567890ABCDEF" not in s and "[REDACTED:AWS Access Key ID]" in s
    assert "ghp_" + "a" * 36 not in s and "GitHub PAT" in s
    assert "AWS Access Key ID" in out["systemMessage"]


def test_redacts_anthropic_key_and_preserves_structure():
    rc, out = _run(_resp(stdout="K=sk-ant-" + "x" * 30, interrupted=True))
    uo = _uo(out)
    assert "sk-ant-" + "x" * 30 not in uo["stdout"]
    assert uo["interrupted"] is True and uo["isImage"] is False


def test_redacts_pem_block_preserving_context():
    pem = ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc123\ndef456\n"
           "-----END OPENSSH PRIVATE KEY-----")
    rc, out = _run(_resp(stdout="before\n" + pem + "\nafter"))
    s = _uo(out)["stdout"]
    assert "BEGIN OPENSSH" not in s and "[REDACTED:Private key]" in s
    assert s.startswith("before") and s.rstrip().endswith("after")


def test_noop_when_clean():
    rc, out = _run(_resp(stdout="built 247 files OK in 3.2s"))
    assert rc == 0 and out is None  # no interference with clean output


@pytest.mark.parametrize("s", [
    "installing sk-learn and skipping sk-image",            # scikit refs
    "commit a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",      # git sha
    "id: 11111111-1111-1111-1111-111111111111",             # uuid
    "data: aGVsbG8gd29ybGQgdGhpcyBpcyBub3QgYSBzZWNyZXQ=",   # base64
    "sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",  # hex
])
def test_false_positives_not_redacted(s):
    rc, out = _run(_resp(stdout=s))
    assert out is None, f"false-positive redaction on: {s}"


def test_stderr_redacted():
    rc, out = _run(_resp(stderr="error: AKIAABCDEFGHIJKLMNOP leaked"))
    assert out is not None and "AKIAABCDEFGHIJKLMNOP" not in _uo(out)["stderr"]


def test_uncovered_tool_passthrough():
    # Bash/Read/MCP are covered (see below); every OTHER tool passes through.
    rc, out = _run({"tool_name": "Glob", "tool_response": {"filenames": ["AKIAABCDEFGHIJKLMNOP"]}})
    assert rc == 0 and out is None


def test_malformed_input_exits_zero():
    import subprocess
    from conftest import HOOKS_DIR, PYTHON
    r = subprocess.run([PYTHON, str(HOOKS_DIR / HOOK)], input="not json{",
                       capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert r.returncode == 0


# --- Read + MCP surface coverage (2026-07-21 extension) ---
# Read carried 23 of 55 real secret-bearing tool outputs/week (fleet replay);
# Bash-only left them unredacted. Read tool_response shape is undocumented, so
# the hook recurses string leaves and preserves structure.

def test_read_nested_content_redacted():
    rc, out = _run({"tool_name": "Read", "tool_response": {"file": {
        "filePath": "/x/cfg.py", "content": "TOKEN = 'ghp_" + "b" * 36 + "'\nx = 1",
        "numLines": 2}}})
    assert rc == 0 and out is not None
    upd = _uo(out)
    assert "ghp_" + "b" * 36 not in json.dumps(upd)
    assert upd["file"]["numLines"] == 2  # structure preserved
    assert "[REDACTED:GitHub PAT]" in upd["file"]["content"]


def test_read_flat_text_shape_redacted():
    rc, out = _run({"tool_name": "Read", "tool_response": {
        "type": "text", "text": "anthropic=sk-ant-" + "c" * 30}})
    assert rc == 0 and out is not None
    assert "sk-ant-" + "c" * 30 not in json.dumps(_uo(out))


def test_read_clean_passthrough():
    rc, out = _run({"tool_name": "Read", "tool_response": {"file": {"content": "no secrets here"}}})
    assert rc == 0 and out is None


def test_read_surrounding_content_preserved():
    rc, out = _run({"tool_name": "Read", "tool_response": {"file": {
        "content": "before AKIA1234567890ABCDEF after"}}})
    c = _uo(out)["file"]["content"]
    assert c.startswith("before ") and c.endswith(" after") and "AKIA1234567890ABCDEF" not in c


def test_mcp_output_redacted_via_mcp_field():
    rc, out = _run({"tool_name": "mcp__slack__conversations_history",
                    "tool_response": {"messages": [{"text": "tok xoxb-111111111-abcdefGHIJKL"}]}})
    assert rc == 0 and out is not None
    hso = out["hookSpecificOutput"]
    assert "updatedMCPToolOutput" in hso  # MCP field, not updatedToolOutput
    assert "xoxb-111111111-abcdefGHIJKL" not in json.dumps(hso["updatedMCPToolOutput"])


def test_write_output_untouched():
    # Write content originated from the model; redacting it protects nothing.
    rc, out = _run({"tool_name": "Write",
                    "tool_response": {"filePath": "/x", "content": "AKIA1234567890ABCDEF"}})
    assert rc == 0 and out is None
