"""Oracle trace infrastructure (SPEC §"Trace contract").

Every layer invocation logs one JSONL record. The trace is the
single source of truth for drift detection, audit-the-auditor,
and recalibration. Anything not in the trace did not happen for
the harness's correctness story.

Records are append-only to ``~/.claude/oracle-trace.jsonl`` by
default (overridable via AUDIT_SKILL_ORACLE_TRACE env var, which
tests use to redirect to a tmpdir).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Schema version: bump when the trace record shape changes incompatibly.
TRACE_SCHEMA_VERSION = "1.0"


def trace_path() -> Path:
    """Return the configured trace JSONL path. Default location:
    ``~/.claude/oracle-trace.jsonl``. Override via env."""
    override = os.environ.get("AUDIT_SKILL_ORACLE_TRACE")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "oracle-trace.jsonl"


def procedure_version() -> str:
    """Identify the audit-skill.py version used. We use the git sha
    of the file when available; falls back to file mtime."""
    repo_root = _resolve_repo_root()
    if repo_root is None:
        return "unknown"
    audit_file = repo_root / "bin" / "audit-skill.py"
    if not audit_file.exists():
        return "no-audit-skill-py"
    try:
        r = subprocess.run(
            ["git", "log", "-n", "1", "--pretty=format:%h", "--", "bin/audit-skill.py"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    # Fall back to file mtime if git unavailable.
    return f"mtime-{int(audit_file.stat().st_mtime)}"


def _resolve_repo_root() -> Path | None:
    """Walk up from this file to find the repo root (directory with
    bin/audit-skill.py)."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "bin" / "audit-skill.py").exists():
            return parent
    return None


def finding_id(skill: str, code: str, description: str) -> str:
    """Stable hash of the (skill, code, description) tuple. Used as
    a join key across trace records and as a primary key in the
    calibration sets."""
    h = hashlib.sha256()
    h.update(skill.encode("utf-8"))
    h.update(b"\x1f")
    h.update(code.encode("utf-8"))
    h.update(b"\x1f")
    h.update(description.encode("utf-8"))
    return h.hexdigest()[:16]


def reproducer_command_sha(command: str) -> str:
    """Stable hash of the reproducer command so trace records can
    detect when the predicate definition itself changes (a separate
    drift signal from procedure_version)."""
    return hashlib.sha256(command.encode("utf-8")).hexdigest()[:16]


@dataclasses.dataclass
class TraceRecord:
    """One record per oracle layer invocation. SPEC §"Trace contract"."""
    ts: str
    layer: str            # "A" | "B" | "C" | "D"
    finding_id: str
    skill: str
    verdict: str
    evidence: str
    procedure_version: str
    model_version: str | None  # for Layer B; None otherwise
    latency_ms: int
    cost_usd: float | None     # for Layer B; None otherwise
    input: dict[str, Any]
    schema_version: str = TRACE_SCHEMA_VERSION
    # Predicate-breadth signal for drift detection (SPEC §"Trace
    # contract"). Defaulted so old records (and the 4 calibration
    # suites' schema asserts) stay valid. Populated by Layer A/D from
    # Reproducer.fires_with_breadth(); None for layers that don't run a
    # reproducer (B, C).
    breadth: dict | None = None

    def to_jsonl(self) -> str:
        return json.dumps(dataclasses.asdict(self), separators=(",", ":")) + "\n"


def write_record(record: TraceRecord) -> None:
    """Append one record to the trace file. Creates parent dirs as needed."""
    path = trace_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(record.to_jsonl())


@contextmanager
def trace_invocation(
    layer: str,
    skill: str,
    finding_id_: str,
    input_metadata: dict[str, Any],
    model_version: str | None = None,
):
    """Context manager that captures latency, then writes a trace
    record when the body sets `result['verdict']` and
    `result['evidence']`. Usage:

        with trace_invocation("A", skill, fid, {"reproducer_type": "grep",
                                                  "reproducer_command_sha": sha}) as result:
            verdict, evidence = ...
            result["verdict"] = verdict
            result["evidence"] = evidence

    The verdict + evidence are written to the trace on context exit
    (even on exception — in that case verdict="ERROR" with the
    exception message as evidence)."""
    result: dict[str, Any] = {"verdict": "ERROR", "evidence": "<no result set>"}
    start = time.monotonic()
    try:
        yield result
    except Exception as e:  # pragma: no cover — safety net
        result["verdict"] = "ERROR"
        result["evidence"] = f"context-manager caught: {type(e).__name__}: {e}"
        raise
    finally:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        record = TraceRecord(
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            layer=layer,
            finding_id=finding_id_,
            skill=skill,
            verdict=result["verdict"],
            evidence=result["evidence"],
            procedure_version=procedure_version(),
            model_version=model_version,
            latency_ms=elapsed_ms,
            cost_usd=result.get("cost_usd"),
            input=input_metadata,
            breadth=result.get("breadth"),
        )
        try:
            write_record(record)
        except OSError:  # pragma: no cover — trace write failure shouldn't crash the layer
            pass


def read_records(path: Path | None = None) -> list[TraceRecord]:
    """Read the trace file as a list of TraceRecord (useful for
    drift analysis + tests)."""
    if path is None:
        path = trace_path()
    if not path.exists():
        return []
    out: list[TraceRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            out.append(TraceRecord(**{k: d.get(k) for k in TraceRecord.__dataclass_fields__}))
        except (json.JSONDecodeError, TypeError):
            continue
    return out
