"""Tests for bin/architecture-drift-check.py — the architecture drift gate."""
import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "arch_drift", str(REPO / "bin" / "architecture-drift-check.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ── pure parsers ──

def test_wired_hooks_parses_run_hook_invocations():
    txt = r'''"command": "\"$HOME/.claude/hooks/run-hook\" loop-detector.py"
    "command": "\"$HOME/.claude/hooks/run-hook\" bash-security-guard.py"
    "command": "\"$HOME/.claude/hooks/codebase-memory-orientation.sh\""'''
    w = _mod.wired_hooks(txt)
    assert "loop-detector.py" in w
    assert "bash-security-guard.py" in w
    assert "codebase-memory-orientation.sh" in w


def test_wired_hooks_parses_exec_form_args():
    txt = '''{
      "hooks": {
        "SessionEnd": [{"hooks": [{
          "type": "command",
          "command": "/absolute/config/hooks/run-hook",
          "args": ["session-end.py"]
        }]}],
        "PreToolUse": [{"hooks": [{
          "type": "command",
          "command": "/absolute/config/hooks/codebase-memory-orientation.sh",
          "args": []
        }]}]
      }
    }'''
    w = _mod.wired_hooks(txt)
    assert "session-end.py" in w
    assert "codebase-memory-orientation.sh" in w


def test_wired_hooks_parses_windows_bash_exec_form_args():
    txt = r'''{
      "hooks": {
        "SessionEnd": [{"hooks": [{
          "type": "command",
          "command": "C:/Program Files/Git/bin/bash.exe",
          "args": ["C:/Users/example/.claude/hooks/run-hook", "session-end.py"]
        }]}]
      }
    }'''
    assert "session-end.py" in _mod.wired_hooks(txt)


def test_layer5_documented_excludes_not_yet_used():
    arch = (
        "## Layer 5\n"
        "#### PreToolUse\n| x | `active-hook.py` | command | y |\n"
        "#### Not Yet Used\n| `PermissionRequest` | `should-be-ignored.py` |\n"
        "### Rules\n| `after-rules.py` |\n"
    )
    docd = _mod.layer5_documented_hooks(arch)
    assert "active-hook.py" in docd
    assert "should-be-ignored.py" not in docd   # excluded subsection
    assert "after-rules.py" not in docd          # outside Layer 5 segment


def test_norm_tokens():
    assert _mod._norm_tokens("150K tokens") == "150000"
    assert _mod._norm_tokens("100000") == "100000"
    assert _mod._norm_tokens(" 64K ") == "64000"


# ── check B: settings ──

def _settings(mode="auto", ts="auto:2", fr=None, workflow="small"):
    env = {
        "ENABLE_TOOL_SEARCH": ts,
        "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "8",
        "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION": "50",
        "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
    }
    if fr is not None:
        env["CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"] = fr
    return {
        "minimumVersion": "2.1.223",
        "skillListingBudgetFraction": 0.01,
        "workflowSizeGuideline": workflow,
        "permissions": {"defaultMode": mode},
        "env": env,
    }


_ARCH_SETTINGS = (
    "| Minimum version | 2.1.223 | x |\n"
    "| Permission mode | auto | x |\n"
    "| ToolSearch | auto:2 | x |\n"
    "| MCP output | native 25K-token default | x |\n"
    "| File read | platform default | x |\n"
    "| Skill listing | 1% context window | x |\n"
    "| Dynamic workflows | small guideline | x |\n"
    "| Agent budgets | 8 concurrent; 50 per session; depth 1 | x |\n"
)


def test_check_settings_passes_on_match():
    assert _mod.check_settings(_ARCH_SETTINGS, _settings()) == []


def test_check_settings_flags_permission_mode_drift():
    findings = _mod.check_settings(_ARCH_SETTINGS, _settings(mode="bypassPermissions"))
    assert len(findings) == 1 and "Permission mode" in findings[0]


def test_check_settings_flags_filed_read_drift_via_normalization():
    findings = _mod.check_settings(_ARCH_SETTINGS, _settings(fr="100000"))
    assert len(findings) == 1 and "File read" in findings[0]


def test_check_settings_flags_native_workflow_budget_mutation():
    findings = _mod.check_settings(_ARCH_SETTINGS, _settings(workflow="large"))
    assert len(findings) == 1 and "workflow" in findings[0].lower()


def test_check_settings_absent_claim_not_gated():
    # No matching table rows → nothing to compare → no findings (not brittle).
    assert _mod.check_settings("no relevant rows here", _settings()) == []


def test_model_runtime_contract_matches_settings_and_covers_runtime_dimensions():
    contract_path = REPO / "contracts" / "model-runtime.json"
    assert contract_path.is_file(), "machine-readable model runtime contract missing"

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    checker = getattr(_mod, "check_model_runtime_contract", None)
    assert callable(checker), "architecture drift gate does not validate model contract"
    assert checker(settings, contract) == []

    assert contract["settingsDefaults"]["effectiveModel"] == "runtime-unknown"
    assert contract["settingsDefaults"]["effectiveEffort"] == "runtime-unknown"
    assert contract["receiptContract"] == {
        "schemaVersion": 3,
        "object": "runtime_provenance",
        "unknownValue": "runtime-unknown",
        "capturePhases": {
            "SessionStart": ["effectiveModel"],
            "SessionEnd": [],
            "transcriptEnrichment": [
                "requestedModel",
                "effectiveModel",
                "switchReason",
                "refusalState",
                "cliVersion",
            ],
        },
        "limitations": contract["receiptContract"]["limitations"],
    }
    assert "reason" in contract["receiptContract"]["limitations"]
    required = {
        "id",
        "owner",
        "provider",
        "modelSource",
        "contextClass",
        "retentionClass",
        "retentionEvidence",
    }
    assert contract["entrypoints"]
    assert all(required <= entry.keys() for entry in contract["entrypoints"])


def test_model_runtime_contract_rejects_managed_only_key_in_user_settings():
    contract = json.loads(
        (REPO / "contracts" / "model-runtime.json").read_text(encoding="utf-8")
    )
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    settings["enforceAvailableModels"] = True

    findings = _mod.check_model_runtime_contract(settings, contract)

    assert any(
        "managed-only" in finding and "enforceAvailableModels" in finding
        for finding in findings
    )


def test_managed_model_policy_requires_a_nonempty_string_allowlist():
    checker = getattr(_mod, "check_managed_model_policy", None)
    assert callable(checker)
    assert checker({"enforceAvailableModels": True})
    assert checker(
        {"enforceAvailableModels": True, "availableModels": []}
    )
    assert checker(
        {"enforceAvailableModels": True, "availableModels": ["sonnet", 5]}
    )
    assert checker(
        {"enforceAvailableModels": "true", "availableModels": ["sonnet"]}
    )
    assert checker(
        {"enforceAvailableModels": True, "availableModels": ["sonnet"]}
    ) == []
    assert checker({"requiredMinimumVersion": "2.1.223"}) == []


def test_model_runtime_contract_detects_settings_and_provenance_mutations():
    contract = json.loads(
        (REPO / "contracts" / "model-runtime.json").read_text(encoding="utf-8")
    )
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))

    mutations = []
    changed_effort = copy.deepcopy(settings)
    changed_effort["effortLevel"] = "xhigh"
    mutations.append((changed_effort, contract, "requestedEffort"))

    # DERIVE the mutation from the contract instead of hardcoding a direction.
    # A pinned `= True` was INERT once the contract's own default became True:
    # the "mutation" then equalled the expected value, the checker correctly
    # reported nothing, and the test failed while the code was right. Flipping
    # whatever the contract declares can never go stale that way.
    changed_switch = copy.deepcopy(settings)
    changed_switch["switchModelsOnFlag"] = not contract["settingsDefaults"]["switchModelsOnFlag"]
    mutations.append((changed_switch, contract, "switchModelsOnFlag"))

    claimed_effective = copy.deepcopy(contract)
    # settings.json no longer pins a model (2026-09-03); any concrete claim of an
    # effective model must still be rejected because only the runtime knows it.
    claimed_effective["settingsDefaults"]["effectiveModel"] = "claude-fable-5-1"
    mutations.append((settings, claimed_effective, "runtime-unknown"))

    missing_retention = copy.deepcopy(contract)
    del missing_retention["entrypoints"][0]["retentionEvidence"]
    mutations.append((settings, missing_retention, "retentionEvidence"))

    for mutated_settings, mutated_contract, expected in mutations:
        findings = _mod.check_model_runtime_contract(
            mutated_settings, mutated_contract
        )
        assert any(expected in finding for finding in findings), (
            expected,
            findings,
        )


# ── check A: hooks ──

def test_check_hooks_documented_but_unwired_is_hard():
    arch = "## Layer 5\n#### PreToolUse\n| x | `ghost.py` | command | y |\n### Rules\n"
    settings_text = ""  # nothing wired
    hard, advisory = _mod.check_hooks(arch, settings_text)
    assert any("ghost.py" in h and "NOT wired" in h for h in hard)


def test_check_hooks_wired_but_undocumented_is_advisory_only():
    arch = "## Layer 5\n#### PreToolUse\n| x | (none) | command | y |\n### Rules\n"
    settings_text = r'"command": "\"$HOME/.claude/hooks/run-hook\" extra.py"'
    hard, advisory = _mod.check_hooks(arch, settings_text)
    assert hard == []
    assert any("extra.py" in a and "undocumented" in a for a in advisory)


def test_hook_timeouts_key_exec_form_by_script_not_dispatcher():
    cfg = {"hooks": {"PreToolUse": [{"hooks": [
        {
            "type": "command",
            "command": "/absolute/hooks/run-hook",
            "args": ["first.py"],
            "timeout": 11,
        },
        {
            "type": "command",
            "command": "/absolute/hooks/run-hook",
            "args": ["second.py"],
            "timeout": 22,
        },
    ]}]}}
    assert _mod._hook_timeouts(cfg, "PreToolUse") == {
        "first.py": 11,
        "second.py": 22,
    }


# ── global model gate: all three settings surfaces are 1P-format ──

def test_global_model_rejects_provider_prefixed_model_with_no_allowlist():
    # The 2026-08-09 SAVED_PROVIDER_DEFAULT allowlist (#1950) is removed: the
    # committed poison it protected is fixed in settings.json instead
    # (operator directive 2026-08-18 — 1P sessions use 1P models only).
    assert not hasattr(_mod, "SAVED_PROVIDER_DEFAULT")
    assert _mod.check_global_model({"model": "us.anthropic.claude-opus-5[1m]"})
    assert _mod.check_global_model({"model": "claude-opus-5"}) == []
    assert _mod.check_global_model({"model": "us.anthropic.claude-sonnet-5[1m]"})
    assert _mod.check_global_model({"model": "arn:aws:bedrock:us-east-1:model/other"})


def test_global_model_gates_fallback_model_list_and_string():
    assert _mod.check_global_model({"fallbackModel": ["claude-sonnet-5[1m]"]}) == []
    assert _mod.check_global_model(
        {"fallbackModel": ["us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"]}
    )
    assert _mod.check_global_model(
        {"fallbackModel": "us.anthropic.claude-sonnet-5[1m]"}
    )


def test_global_model_gates_env_block_provider_ids():
    # 2026-08-18 vector: settings.json env is injected by the CLI into EVERY
    # session after a launcher's subshell scrub, so a provider-prefixed
    # ANTHROPIC_*MODEL value here remaps 1P picker aliases onto Bedrock IDs.
    poisoned = {
        "env": {"ANTHROPIC_DEFAULT_OPUS_MODEL": "us-gov.anthropic.claude-opus-5"}
    }
    flags = _mod.check_global_model(poisoned)
    assert len(flags) == 1
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL" in flags[0]
    clean = {
        "env": {"MCP_TIMEOUT": "60000", "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}
    }
    assert _mod.check_global_model(clean) == []


# ── end-to-end smoke: the live repo must currently pass ──

def test_repo_currently_passes_the_gate():
    """If someone drifts ARCHITECTURE.md/README/settings, this fails here too."""
    r = subprocess.run(
        [sys.executable, str(REPO / "bin" / "architecture-drift-check.py")],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"drift gate failed on the current repo:\n{r.stdout}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All architecture-drift-check tests passed.")


# Retained from origin/main: the local file refactored these into finer
# cases, and keeping the originals is what PROVES no coverage was dropped.
def test_current_repository_retains_structured_runtime_and_model_guards():
    """The post-1949 policy must not discard the stronger live guard chain."""
    settings_text = (REPO / "settings.json").read_text(encoding="utf-8")
    settings = json.loads(settings_text)
    wired = _mod.wired_hooks(settings_text)

    assert {"session-end.py", "config-change-validate.py"} <= wired
    assert "ConfigChange" in _mod.BLOCKING_EVENTS
    contract_path = REPO / "contracts" / "model-runtime.json"
    assert contract_path.is_file()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert _mod.check_model_runtime_contract(settings, contract) == []
    assert _mod.check_settings(
        (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8"), settings
    ) == []

    completed = subprocess.run(
        [sys.executable, str(REPO / "bin" / "architecture-drift-check.py")],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

# Retained from origin/main: the local file refactored these into finer
# cases, and keeping the originals is what PROVES no coverage was dropped.
def test_wired_hooks_and_timeouts_parse_structured_exec_form():
    settings_text = json.dumps(
        {
            "hooks": {
                "ConfigChange": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/absolute/config/hooks/run-hook",
                                "args": ["config-change-validate.py"],
                                "timeout": 30,
                            }
                        ]
                    }
                ],
                "SessionEnd": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "C:/Program Files/Git/bin/bash.exe",
                                "args": [
                                    "C:/Users/example/.claude/hooks/run-hook",
                                    "session-end.py",
                                ],
                                "timeout": 5,
                            }
                        ]
                    }
                ],
            }
        }
    )

    assert {"config-change-validate.py", "session-end.py"} <= _mod.wired_hooks(
        settings_text
    )
    assert _mod._hook_timeouts(json.loads(settings_text), "ConfigChange") == {
        "config-change-validate.py": 30
    }
