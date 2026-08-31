"""Qualify the managed, nondeveloper Helm operator policy source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
POLICY_ROOT = ROOT / "templates" / "helm-operator"


def _json(name: str) -> dict:
    return json.loads((POLICY_ROOT / name).read_text(encoding="utf-8"))


def test_helm_operator_profile_merge_contract_is_fail_closed() -> None:
    settings = _json("managed-settings.fragment.json")
    contract = _json("profile-merge-contract.json")
    packet = _json("deployment.packet.json")

    assert settings["permissions"]["defaultMode"] == "dontAsk"
    assert settings["permissions"]["disableBypassPermissionsMode"] == "disable"
    assert settings["allowManagedPermissionRulesOnly"] is True
    assert settings["allowManagedHooksOnly"] is True
    assert settings["allowManagedMcpServersOnly"] is True
    assert contract["preference_domain"] == "com.anthropic.claudecode"
    assert contract["duplicate_profile_forbidden"] is True
    assert contract["pilot_scope"] == "helm-nondeveloper-operator"
    assert packet["status"] == "source_ready_not_deployed"
    assert packet["required_receipts"] == [
        "source_revision_and_sha256",
        "mdm_profile_revision_and_scope",
        "device_profile_install_status",
        "fresh_session_managed_source",
        "policy_qualification_12_of_12",
    ]

    for name, expected in packet["sources"]["sha256"].items():
        actual = hashlib.sha256((POLICY_ROOT / name).read_bytes()).hexdigest()
        assert actual == expected


def test_helm_operator_policy_passes_twelve_executable_cases() -> None:
    hook_uri = (POLICY_ROOT / "helm-tool-policy.mjs").as_uri()
    script = f"""
      import {{ evaluateHelmTool }} from {json.dumps(hook_uri)};
      const root = process.argv[1];
      const trusted = {{ repoRoot: root, trustedRepository: true }};
      const untrusted = {{ repoRoot: root, trustedRepository: false }};
      const verdict = (tool_name, tool_input, context = trusted) =>
        evaluateHelmTool({{ tool_name, tool_input }}, context).hookSpecificOutput.permissionDecision;
      const cases = [
        ['allow', 'Bash', {{command: 'npm run operator:doctor'}}],
        ['allow', 'Bash', {{command: 'npm run operator:sandbox'}}],
        ['allow', 'Read', {{file_path: 'README.md'}}],
        ['allow', 'Edit', {{file_path: 'docs/features.md'}}],
        ['deny', 'Bash', {{command: 'git push'}}],
        ['deny', 'Bash', {{command: 'npm run operator:doctor && git push'}}],
        ['deny', 'Bash', {{command: 'terraform apply'}}],
        ['deny', 'Read', {{file_path: '.env.production'}}],
        ['deny', 'Write', {{file_path: '.github/workflows/release.yml'}}],
        ['deny', 'Edit', {{file_path: 'operator/claude/helm-tool-policy.mjs'}}],
        ['deny', 'WebFetch', {{url: 'https://example.com'}}],
        ['deny', 'Read', {{file_path: 'README.md'}}, untrusted],
      ];
      for (const [expected, tool, input, context] of cases) {{
        const actual = verdict(tool, input, context);
        if (actual !== expected) throw new Error(`${{tool}}: expected ${{expected}}, received ${{actual}}`);
      }}
      process.stdout.write(`qualified=${{cases.length}}/12\\n`);
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(ROOT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "qualified=12/12\n"
