"""Layer A — re-verify findings against the live tree.

See SPEC.md §"Layer A" for verdict semantics. Briefly:
  - STILL-FIRES: the deterministic predicate returned True today.
    NOT "bug is real" — only the predicate returned True.
  - STALE: the predicate returned False. NOT "bug never existed" —
    only the predicate is not satisfied right now.
  - MANUAL: reproducer is type=manual; no automated check; human required.
  - ERROR: reproducer crashed; instrument problem, not a verdict.

Each invocation writes a TraceRecord to the oracle trace file (see
oracle/trace.py).
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path

from .finding import Finding
from .trace import finding_id, reproducer_command_sha, trace_invocation


@dataclasses.dataclass
class ReverifyResult:
    finding: Finding
    status: str  # STILL-FIRES | STALE | MANUAL | ERROR
    evidence: str


def reverify(findings: list[Finding], repo_root: Path) -> list[ReverifyResult]:
    """Run each finding's reproducer; return per-finding result list.
    Writes a TraceRecord per invocation to the oracle trace file."""
    results: list[ReverifyResult] = []
    for f in findings:
        fid = finding_id(f.skill, f.code, f.description)
        input_meta = {
            "reproducer_type": f.reproducer.type,
            "reproducer_command_sha": reproducer_command_sha(f.reproducer.command or f.reproducer.path),
            "label": f.label,
            "severity": f.severity,
            # Attribution for the enforced SubagentStop gate; "" when the
            # orchestrator hasn't exported it (gate is fail-safe-inert).
            "session_id": os.environ.get("AUDIT_SKILL_ORACLE_SESSION", ""),
        }
        with trace_invocation("A", f.skill, fid, input_meta) as tr:
            if f.reproducer.type == "manual":
                tr["verdict"] = "MANUAL"
                tr["evidence"] = "<manual reproducer; no automated check>"
                results.append(ReverifyResult(f, "MANUAL", tr["evidence"]))
                continue
            try:
                fires, evidence, breadth = f.reproducer.fires_with_breadth(repo_root)
                tr["breadth"] = breadth
            except subprocess.TimeoutExpired:
                tr["verdict"] = "ERROR"
                tr["evidence"] = "reproducer timed out (>30s)"
                results.append(ReverifyResult(f, "ERROR", tr["evidence"]))
                continue
            except Exception as e:
                tr["verdict"] = "ERROR"
                tr["evidence"] = f"reproducer raised: {e!r}"
                results.append(ReverifyResult(f, "ERROR", tr["evidence"]))
                continue
            status = "STILL-FIRES" if fires else "STALE"
            tr["verdict"] = status
            tr["evidence"] = evidence
            results.append(ReverifyResult(f, status, evidence))
    return results


def filter_stale(results: list[ReverifyResult]) -> list[Finding]:
    """Return only the findings that still fire (drop STALE; keep
    MANUAL + ERROR + STILL-FIRES — those still need a human or fix
    decision)."""
    return [r.finding for r in results if r.status != "STALE"]


def format_results(results: list[ReverifyResult]) -> str:
    """Pretty-print, one line per result."""
    out: list[str] = []
    for r in results:
        f = r.finding
        out.append(
            f"{r.status:<12} {f.skill}/{f.code} [{f.label}]  {f.description[:80]}"
        )
    return "\n".join(out)
