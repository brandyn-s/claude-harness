#!/usr/bin/env python3
"""Enrich bounded SessionEnd receipts outside the SessionEnd latency path.

The processor reads only model/stop metadata from transcript JSONL. It never
copies prompts, assistant text, tool input, or tool output into a receipt.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))
from atomic_write import atomic_write  # noqa: E402 -- resolves via the sys.path insert above

MODEL_REFUSAL_SUBTYPES = {
    "model_refusal_fallback",
    "model_refusal_no_fallback",
}


def _transcript_metadata(path: Path) -> dict:
    requested_model = ""
    effective_model = ""
    fallback_model = ""
    switch_reason = ""
    stop_reason = ""
    fallback_count = 0
    no_fallback_count = 0
    refusal_stop_count = 0
    models_used: list[str] = []
    cli_version = ""

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue

            version = row.get("version")
            if version:
                cli_version = str(version)

            subtype = row.get("subtype")
            if subtype in MODEL_REFUSAL_SUBTYPES:
                switch_reason = subtype
                requested_model = str(row.get("originalModel") or requested_model)
                fallback = row.get("fallbackModel")
                if fallback:
                    fallback_model = str(fallback)
                if subtype == "model_refusal_fallback":
                    fallback_count += 1
                else:
                    no_fallback_count += 1

            message = row.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            if model and model != "<synthetic>":
                effective_model = str(model)
                if effective_model not in models_used:
                    models_used.append(effective_model)
            current_stop = message.get("stop_reason")
            if current_stop:
                stop_reason = str(current_stop)
            stop_details = message.get("stop_details")
            is_refusal = current_stop == "refusal" or (
                isinstance(stop_details, dict) and stop_details.get("type") == "refusal"
            )
            if is_refusal:
                refusal_stop_count += 1

    refusal_count = max(fallback_count + no_fallback_count, refusal_stop_count)
    return {
        "requested_model": requested_model,
        "effective_model": effective_model,
        "fallback_model": fallback_model,
        "switch_reason": switch_reason,
        "stop_reason": stop_reason,
        "refusal": refusal_count > 0,
        "refusal_count": refusal_count,
        "fallback_count": fallback_count,
        "models_used": models_used,
        "cli_version": cli_version,
    }


def enrich_receipt(path: Path) -> bool:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(receipt, dict):
        return False
    enrichment = receipt.get("enrichment")
    if not isinstance(enrichment, dict) or enrichment.get("status") != "pending":
        return False
    transcript_value = receipt.get("transcript_path")
    if not isinstance(transcript_value, str) or not transcript_value:
        return False
    transcript = Path(transcript_value)
    if not transcript.is_file():
        return False

    metadata = _transcript_metadata(transcript)
    provenance = receipt.get("runtime_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    sources = provenance.get("fieldSources")
    if not isinstance(sources, dict):
        sources = {}
    if metadata["requested_model"]:
        provenance["requestedModel"] = metadata["requested_model"]
        sources["requestedModel"] = "transcript.model_refusal.originalModel"
    if metadata["effective_model"]:
        provenance["effectiveModel"] = (
            metadata["effective_model"]
            if len(metadata["models_used"]) <= 1
            else "mixed"
        )
        sources["effectiveModel"] = "transcript.message.model"
    if metadata["switch_reason"]:
        provenance["switchReason"] = metadata["switch_reason"]
        sources["switchReason"] = "transcript.model_refusal.subtype"
    provenance["refusalState"] = bool(metadata["refusal"])
    sources["refusalState"] = "transcript.stop_reason_or_refusal_subtype"
    if metadata["cli_version"]:
        provenance["cliVersion"] = metadata["cli_version"]
        sources["cliVersion"] = "transcript.version"
    provenance["modelsUsed"] = metadata["models_used"]
    provenance["fieldSources"] = sources
    provenance["evidenceStatus"] = (
        "complete"
        if all(
            provenance.get(field) not in (None, "", "runtime-unknown")
            for field in (
                "requestedModel",
                "effectiveModel",
                "requestedEffort",
                "effectiveEffort",
                "provider",
                "entrypoint",
                "contextClass",
                "switchReason",
                "refusalState",
                "cliVersion",
            )
        )
        else "partially-enriched"
    )
    receipt["runtime_provenance"] = provenance
    receipt["enrichment"] = {
        "status": "complete",
        "source": "transcript",
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "refusal_count": metadata["refusal_count"],
        "fallback_count": metadata["fallback_count"],
    }
    atomic_write(path, json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich pending SessionEnd receipts with transcript metadata."
    )
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=Path.home() / ".claude" / "session-end-receipts",
    )
    args = parser.parse_args()

    processed = 0
    if args.receipts_dir.is_dir():
        for receipt in sorted(args.receipts_dir.glob("*.json")):
            processed += int(enrich_receipt(receipt))
    print(f"processed={processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
