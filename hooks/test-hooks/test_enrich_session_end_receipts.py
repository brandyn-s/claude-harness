"""Acceptance tests for the offline SessionEnd receipt enricher."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "enrich-session-end-receipts.py"


def _module():
    spec = importlib.util.spec_from_file_location("session_end_enricher", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_enriches_model_fallback_and_refusal_without_prompt_content(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "message": {"content": "SECRET PROMPT MUST NOT PERSIST"},
                    }
                ),
                json.dumps(
                    {
                        "subtype": "model_refusal_fallback",
                        "originalModel": "claude-fable-5",
                        "fallbackModel": "claude-opus-5",
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-opus-5",
                            "stop_reason": "refusal",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = receipts / "session-1.json"
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "session_id": "session-1",
                "transcript_path": str(transcript),
                "runtime_provenance": {
                    "requestedModel": "runtime-unknown",
                    "effectiveModel": "claude-fable-5",
                    "requestedEffort": "runtime-unknown",
                    "effectiveEffort": "runtime-unknown",
                    "provider": "runtime-unknown",
                    "entrypoint": "runtime-unknown",
                    "contextClass": "runtime-unknown",
                    "switchReason": "runtime-unknown",
                    "refusalState": "runtime-unknown",
                    "cliVersion": "runtime-unknown",
                    "modelsUsed": ["claude-fable-5"],
                    "fieldSources": {"effectiveModel": "SessionStart.model"},
                    "evidenceStatus": "pending-transcript-enrichment",
                },
                "enrichment": {"status": "pending", "source": "transcript"},
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--receipts-dir", str(receipts)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        cwd=str(ROOT),
        check=False,
    )

    assert result.returncode == 0
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    provenance = receipt["runtime_provenance"]
    assert provenance["requestedModel"] == "claude-fable-5"
    assert provenance["effectiveModel"] == "claude-opus-5"
    assert provenance["modelsUsed"] == ["claude-opus-5"]
    assert provenance["switchReason"] == "model_refusal_fallback"
    assert provenance["refusalState"] is True
    assert provenance["effectiveEffort"] == "runtime-unknown"
    assert provenance["provider"] == "runtime-unknown"
    assert provenance["entrypoint"] == "runtime-unknown"
    assert provenance["contextClass"] == "runtime-unknown"
    assert provenance["fieldSources"]["effectiveModel"] == "transcript.message.model"
    assert provenance["evidenceStatus"] == "partially-enriched"
    assert receipt["enrichment"]["status"] == "complete"
    assert receipt["enrichment"]["refusal_count"] == 1
    assert receipt["enrichment"]["fallback_count"] == 1
    assert "SECRET PROMPT" not in receipt_text


def test_refusal_without_fallback_is_still_counted(tmp_path):
    transcript = tmp_path / "refusal.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"model": "claude-fable-5", "stop_reason": "refusal"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    metadata = _module()._transcript_metadata(transcript)
    assert metadata["refusal"] is True
    assert metadata["refusal_count"] == 1
    assert metadata["fallback_count"] == 0


def test_enriched_receipt_satisfies_the_declared_runtime_contract(tmp_path):
    module = _module()
    contract = json.loads((ROOT / "contracts" / "model-runtime.json").read_text())
    transcript = tmp_path / "contract.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "version": "2.1.223",
                "message": {"model": "claude-fable-5", "stop_reason": "end_turn"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt = tmp_path / "contract-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "session_id": "contract-session",
                "transcript_path": str(transcript),
                "runtime_provenance": {
                    field: "runtime-unknown"
                    for field in contract["requiredReceiptFields"]
                },
                "enrichment": {"status": "pending", "source": "transcript"},
            }
        ),
        encoding="utf-8",
    )

    assert module.enrich_receipt(receipt) is True
    enriched = json.loads(receipt.read_text())["runtime_provenance"]
    assert set(contract["requiredReceiptFields"]) <= set(enriched)
    assert enriched["effectiveModel"] == "claude-fable-5"
    assert enriched["cliVersion"] == "2.1.223"


def test_actual_start_end_and_enrichment_pipeline_matches_contract(tmp_path):
    contract = json.loads((ROOT / "contracts" / "model-runtime.json").read_text())
    transcript = tmp_path / "pipeline.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "version": "2.1.223",
                "message": {"model": "claude-fable-5", "stop_reason": "end_turn"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_dir = tmp_path / "receipts"
    seed_dir = tmp_path / "seeds"
    env = {
        "PATH": str(Path(sys.executable).parent),
        "HOME": str(tmp_path / "home"),
        "USERPROFILE": str(tmp_path / "home"),
        "CLAUDE_KEYCHAIN_SECRETS": "0",
        "CLAUDE_SESSION_RUNTIME_DIR": str(seed_dir),
        "CLAUDE_SESSION_END_RECEIPT_DIR": str(receipt_dir),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    start = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "session-start.py")],
        input=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "session_id": "pipeline-session",
                "model": "claude-fable-5",
            }
        ),
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )
    assert start.returncode == 0
    end = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "session-end.py")],
        input=json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "pipeline-session",
                "transcript_path": str(transcript),
                "reason": "other",
            }
        ),
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )
    assert end.returncode == 0
    receipt_path = receipt_dir / "pipeline-session.json"
    assert _module().enrich_receipt(receipt_path) is True

    receipt = json.loads(receipt_path.read_text())
    provenance = receipt["runtime_provenance"]
    assert set(contract["requiredReceiptFields"]) <= set(provenance)
    assert provenance["effectiveModel"] == "claude-fable-5"
    assert provenance["fieldSources"]["effectiveModel"] == "transcript.message.model"
    assert provenance["requestedEffort"] == "runtime-unknown"
