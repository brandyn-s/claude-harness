"""Tests for cklb-to-md.py (PreToolUse:Read)."""
import json
import os

from conftest import run_hook

HOOK = "cklb-to-md.py"

SAMPLE_CKLB = {
    "title": "Test STIG",
    "id": "abc-123",
    "stigs": [
        {
            "display_name": "Sample Application STIG",
            "stig_id": "Sample_App_STIG",
            "release_info": "Release 1 Benchmark 2026-01-01",
            "version": "1",
            "rules": [
                {
                    "group_id": "RULE-000000",
                    "rule_id": "SV-100001r1",
                    "rule_title": "Password complexity must be enforced.",
                    "severity": "high",
                    "status": "open",
                    "finding_details": "Password policy disabled.",
                    "check_content": "Run: cat /etc/pam.d/system-auth",
                    "fix_text": "Enable pwquality in PAM.",
                },
                {
                    "group_id": "RULE-000000",
                    "rule_id": "SV-100002r1",
                    "rule_title": "Idle timeout must be configured.",
                    "severity": "medium",
                    "status": "not_a_finding",
                },
                {
                    "group_id": "RULE-000000",
                    "rule_id": "SV-100003r1",
                    "rule_title": "Audit logging enabled.",
                    "severity": "low",
                    "status": "not_reviewed",
                },
            ],
        }
    ],
}


def test_non_cklb_passthrough():
    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": "$HOME/Documents/notes.txt"},
    })
    assert rc == 0
    assert err.strip() == ""


def test_non_read_tool_passthrough():
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_input": {"command": "cat stig.cklb"},
    })
    assert rc == 0


def test_nonexistent_file_passthrough():
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": "C:/nonexistent/stig.cklb"},
    })
    assert rc == 0


def test_conversion_blocks_with_redirect(tmp_path):
    src = tmp_path / "stig.cklb"
    src.write_text(json.dumps(SAMPLE_CKLB), encoding="utf-8")

    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": str(src)},
    }, timeout=60)

    assert rc == 2, f"Expected block (2), got {rc}. stderr={err}"
    assert "Read this file instead:" in err

    md_path = err.split("Read this file instead:")[-1].strip()
    assert os.path.isfile(md_path)
    content = open(md_path, "r", encoding="utf-8").read()
    assert content.startswith("<!-- cklb-to-md-hook -->")
    assert "Test STIG" in content
    assert "Sample Application STIG" in content
    assert "RULE-000000" in content
    # Open finding should appear in detail section
    assert "Open Findings Detail" in content
    assert "Password complexity" in content
    assert "Enable pwquality" in content

    try:
        os.remove(md_path)
    except OSError:
        pass


def test_cache_reused_on_second_call(tmp_path):
    src = tmp_path / "stig.cklb"
    src.write_text(json.dumps(SAMPLE_CKLB), encoding="utf-8")

    rc1, _out, err1 = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": str(src)},
    }, timeout=60)
    assert rc1 == 2
    md_path = err1.split("Read this file instead:")[-1].strip()
    first_mtime = os.path.getmtime(md_path)

    rc2, _out, err2 = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": str(src)},
    }, timeout=60)
    assert rc2 == 2
    assert "cached" in err2
    # mtime should NOT change (cache was reused, not rewritten)
    assert os.path.getmtime(md_path) == first_mtime

    try:
        os.remove(md_path)
    except OSError:
        pass
