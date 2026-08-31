"""Tests for nessus-to-md.py (PreToolUse:Read)."""
import os

from conftest import run_hook

HOOK = "nessus-to-md.py"

SAMPLE_NESSUS = """<?xml version="1.0" ?>
<NessusClientData_v2>
  <Policy><policyName>Test</policyName></Policy>
  <Report name="test-scan">
    <ReportHost name="host1.example">
      <HostProperties>
        <tag name="host-ip">10.0.0.1</tag>
        <tag name="operating-system">Linux 6.1</tag>
      </HostProperties>
      <ReportItem port="22" svc_name="ssh" protocol="tcp" severity="3" pluginID="99999" pluginName="Sample High Finding">
        <cve>CVE-2024-99999</cve>
        <cvss3_base_score>8.1</cvss3_base_score>
      </ReportItem>
      <ReportItem port="80" svc_name="www" protocol="tcp" severity="0" pluginID="10107" pluginName="HTTP Server Type">
      </ReportItem>
    </ReportHost>
  </Report>
</NessusClientData_v2>
"""


def test_non_nessus_passthrough():
    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": "$HOME/Documents/notes.txt"},
    })
    assert rc == 0
    assert err.strip() == ""


def test_non_read_tool_passthrough():
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_input": {"command": "cat scan.nessus"},
    })
    assert rc == 0


def test_nonexistent_file_passthrough():
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": "C:/nonexistent/scan.nessus"},
    })
    assert rc == 0


def test_conversion_blocks_with_redirect(tmp_path):
    src = tmp_path / "scan.nessus"
    src.write_text(SAMPLE_NESSUS, encoding="utf-8")

    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": str(src)},
    }, timeout=60)

    assert rc == 2, f"Expected block (2), got {rc}. stderr={err}"
    assert "Read this file instead:" in err
    assert ".md" in err

    # Extract the md path from the stderr and verify contents
    md_path = err.split("Read this file instead:")[-1].strip()
    assert os.path.isfile(md_path), f"md not written: {md_path}"
    content = open(md_path, "r", encoding="utf-8").read()
    assert content.startswith("<!-- nessus-to-md-hook -->")
    assert "test-scan" in content
    assert "host1.example" in content
    assert "Sample High Finding" in content
    assert "CVE-2024-99999" in content
    # cleanup
    try:
        os.remove(md_path)
    except OSError:
        pass


def test_foreign_md_not_overwritten(tmp_path):
    """If a .md exists without our sentinel, skip (warn) instead of overwriting."""
    src = tmp_path / "scan.nessus"
    src.write_text(SAMPLE_NESSUS, encoding="utf-8")

    # Run once to create the cached md
    rc1, _out, err1 = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": str(src)},
    }, timeout=60)
    assert rc1 == 2
    md_path = err1.split("Read this file instead:")[-1].strip()

    # Overwrite the md with foreign content (no sentinel)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("user-authored notes")

    rc2, _out, err2 = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": str(src)},
    }, timeout=60)
    assert rc2 == 0
    assert "not auto-generated" in err2

    try:
        os.remove(md_path)
    except OSError:
        pass
