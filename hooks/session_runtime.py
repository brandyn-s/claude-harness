"""Bounded runtime-evidence state shared by SessionStart and SessionEnd.

Claude Code's hook contract exposes the active model only on SessionStart.
SessionEnd receives no model or effort fields.  This module persists the
official SessionStart value in a private per-session seed so SessionEnd never
has to invent provenance from unsupported payload keys.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from atomic_write import atomic_write

SEED_SCHEMA_VERSION = 1
UNKNOWN = "runtime-unknown"
MAX_FIELD_CHARS = 8192
REQUIRED_PROVENANCE_FIELDS = (
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


def bounded(value: object) -> str:
    if value is None:
        return ""
    return str(value)[:MAX_FIELD_CHARS]


def safe_session_filename(session_id: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", session_id).strip(".-")[:80]
    if readable:
        return f"{readable}.json"
    digest = hashlib.sha256(session_id.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"unknown-{digest}.json"


def runtime_dir() -> Path:
    override = os.environ.get("CLAUDE_SESSION_RUNTIME_DIR")
    return Path(override) if override else Path.home() / ".claude" / "session-runtime-seeds"


def write_session_start_seed(event: dict) -> Path | None:
    """Persist only documented SessionStart metadata; return the path if written."""

    session_id = bounded(event.get("session_id"))
    if not session_id:
        return None
    model = bounded(event.get("model"))
    requested_model = bounded(os.environ.get("ANTHROPIC_MODEL"))
    payload = {
        "schema_version": SEED_SCHEMA_VERSION,
        "session_id": session_id,
        "session_start_model": model,
        "session_start_source": bounded(event.get("source")),
        "agent_type": bounded(event.get("agent_type")),
        "requested_model_env": requested_model,
    }
    directory = runtime_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / safe_session_filename(session_id)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def read_session_start_seed(session_id: str) -> dict:
    if not session_id:
        return {}
    try:
        payload = json.loads(
            (runtime_dir() / safe_session_filename(session_id)).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("session_id") != session_id:
        return {}
    return payload


def initial_runtime_provenance(seed: dict) -> dict:
    provenance = {field: UNKNOWN for field in REQUIRED_PROVENANCE_FIELDS}
    sources: dict[str, str] = {}
    requested = bounded(seed.get("requested_model_env"))
    active = bounded(seed.get("session_start_model"))
    if requested:
        provenance["requestedModel"] = requested
        sources["requestedModel"] = "SessionStart.environment.ANTHROPIC_MODEL"
    if active:
        provenance["effectiveModel"] = active
        sources["effectiveModel"] = "SessionStart.model"
    provenance.update(
        {
            "modelsUsed": [active] if active else [],
            "fieldSources": sources,
            "evidenceStatus": "pending-transcript-enrichment",
        }
    )
    return provenance
