"""Phase 4 report generation — combine Phase 1 (mechanical lint) and
Phase 2/3 (agent + oracle) findings into a single actionable report.

Closes the gap called out in the 2026-05-27 self-assessment: the
audit-skill procedure ends with "combine findings into one numbered
list" but the bundling was prose-assembled by the calling agent.
This module does it mechanically so the final artifact has the same
guarantees as the gating steps.

Inputs:
- Phase 1 NDJSON (one record per finding, emitted by --ndjson=PATH)
  OR a list[dict] in memory.
- Phase 2/3 worklist YAML (output of `oracle.py act-on --out`) — the
  STILL-FIRES + MANUAL + ERROR findings that survived the gate.

Either input is optional, but at least one is required.

Output: a markdown report (default) or a JSON envelope.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
from pathlib import Path
from typing import Iterable, Optional

from .finding import Finding, load_findings
from .profile import render_profiles, PROFILES


@dataclasses.dataclass
class ReportEntry:
    """One numbered row in the Phase 4 report. Shared shape so the
    markdown and JSON renderers don't drift on schema."""
    phase: str            # "1" or "2/3"
    skill: str
    code: str
    severity: str         # drift | info | error | behavior-bug
    label: str            # doc-fix | behavior-fix | unverified | ""
    path: str
    line: Optional[int]
    message: str
    oracle_verdict: str   # "STILL-FIRES" | "MANUAL" | "ERROR" | "" (Phase 1)
    reproducer_kind: str  # "" if none
    reproducer_payload: str  # short hint (path or command)
    triage_status: str
    triage_note: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def load_phase1_ndjson(path: Path) -> list[dict]:
    """Load Phase 1 NDJSON — one JSON object per line, each shaped like
    {"run_id": ..., "skill": ..., "code": ..., "severity": ...,
     "msg": ..., "path": ..., "line": ...}.
    Skips blank lines. Raises FileNotFoundError if path missing."""
    records: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        records.append(json.loads(raw))
    return records


def _phase1_to_entries(records: Iterable[dict]) -> list[ReportEntry]:
    out: list[ReportEntry] = []
    for r in records:
        out.append(ReportEntry(
            phase="1",
            skill=r.get("skill", ""),
            code=r.get("code", ""),
            severity=r.get("severity", ""),
            label="",  # Phase 1 doesn't label
            path=r.get("path", ""),
            line=r.get("line"),
            message=r.get("msg", ""),
            oracle_verdict="",
            reproducer_kind="",
            reproducer_payload="",
            triage_status="",
            triage_note="",
        ))
    return out


def _phase2_to_entries(findings: Iterable[Finding]) -> list[ReportEntry]:
    """Convert Phase 2/3 surviving Findings to report rows. The worklist
    coming out of act_on contains STILL-FIRES + MANUAL + ERROR — the
    verdict isn't stored on the Finding itself; we infer it from the
    reproducer type. (`manual` → MANUAL; everything else that's still
    in the worklist is STILL-FIRES from act_on's perspective.)"""
    out: list[ReportEntry] = []
    for f in findings:
        rep = f.reproducer
        # Prefer the verdict act_on stamped into the worklist row; only
        # fall back to type-inference for worklists produced before the
        # stamp existed. The inference cannot represent ERROR, which is
        # exactly the row class that must NOT render as needs-fix.
        verdict = str(f.extra.get("oracle_verdict") or "") or (
            "MANUAL" if rep.type == "manual" else "STILL-FIRES")
        payload = rep.command or rep.path or rep.description or ""
        payload = payload.strip().splitlines()[0][:120] if payload else ""
        # path:line locator. Prefer Finding.source (when set by load); fall
        # back to scraping a path-line pair out of any extras the loader
        # routed.
        src = f.source or ""
        path = src
        line = None
        if ":" in src:
            head, _, tail = src.rpartition(":")
            if tail.isdigit():
                path, line = head, int(tail)
        out.append(ReportEntry(
            phase="2/3",
            skill=f.skill,
            code=f.code,
            severity=f.severity,
            label=f.label,
            path=path,
            line=line,
            message=f.description.strip(),
            oracle_verdict=verdict,
            reproducer_kind=rep.type,
            reproducer_payload=payload,
            triage_status=f.triage_status,
            triage_note=f.triage_note,
        ))
    return out


def build_report(
    phase1_path: Optional[Path] = None,
    phase2_path: Optional[Path] = None,
) -> tuple[list[ReportEntry], dict]:
    """Load inputs, return (entries, header_stats). entries are numbered
    in caller order: Phase 1 first, then Phase 2/3.

    Either argument may be None; at least one must be provided."""
    if phase1_path is None and phase2_path is None:
        raise ValueError("at least one of phase1_path/phase2_path required")

    phase1_entries: list[ReportEntry] = []
    if phase1_path is not None:
        phase1_entries = _phase1_to_entries(load_phase1_ndjson(phase1_path))

    phase2_entries: list[ReportEntry] = []
    if phase2_path is not None:
        findings = load_findings(phase2_path)
        # Keep only actionable rows — closed-triage findings shouldn't
        # appear in the final report.
        actionable = [f for f in findings if f.is_actionable()]
        phase2_entries = _phase2_to_entries(actionable)

    entries = phase1_entries + phase2_entries

    p1_drift = sum(1 for e in phase1_entries if e.severity == "drift")
    p1_info = sum(1 for e in phase1_entries if e.severity == "info")
    p1_err = sum(1 for e in phase1_entries if e.severity == "error")
    p2_still = sum(1 for e in phase2_entries if e.oracle_verdict == "STILL-FIRES")
    p2_manual = sum(1 for e in phase2_entries if e.oracle_verdict == "MANUAL")
    p2_error = sum(1 for e in phase2_entries if e.oracle_verdict == "ERROR")

    header = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "phase1_total": len(phase1_entries),
        "phase1_drift": p1_drift,
        "phase1_info": p1_info,
        "phase1_error": p1_err,
        "phase2_total": len(phase2_entries),
        "phase2_still_fires": p2_still,
        "phase2_manual": p2_manual,
        "phase2_error": p2_error,
    }
    return entries, header


def render_markdown(entries: list[ReportEntry], header: dict) -> str:
    lines: list[str] = []
    lines.append(f"# audit-skill report — {header['generated_at']}")
    lines.append("")
    if header["phase1_total"]:
        lines.append(
            f"**Phase 1** (mechanical lint): {header['phase1_total']} findings "
            f"— {header['phase1_drift']} drift, {header['phase1_info']} info, "
            f"{header['phase1_error']} error"
        )
    if header["phase2_total"]:
        err_part = (
            f", {header['phase2_error']} ERROR (instrument)"
            if header.get("phase2_error") else ""
        )
        lines.append(
            f"**Phase 2/3** (agent + oracle): {header['phase2_total']} findings "
            f"— {header['phase2_still_fires']} STILL-FIRES, "
            f"{header['phase2_manual']} MANUAL{err_part}"
        )
    if not entries:
        lines.append("")
        lines.append("_No findings._")
        return "\n".join(lines) + "\n"
    lines.append("")
    lines.append("---")
    lines.append("")
    for i, e in enumerate(entries, start=1):
        verdict = f" {e.oracle_verdict}" if e.oracle_verdict else ""
        label = f" [{e.label}]" if e.label else ""
        lines.append(
            f"## {i}. `{e.skill}` {e.code} [{e.severity}]{label}{verdict} — Phase {e.phase}"
        )
        lines.append("")
        loc = e.path or "(no location)"
        if e.line is not None:
            loc = f"{loc}:{e.line}"
        lines.append(f"**Location**: `{loc}`")
        lines.append("")
        lines.append("> " + e.message.replace("\n", "\n> "))
        lines.append("")
        if e.reproducer_kind:
            kind = e.reproducer_kind
            payload = e.reproducer_payload
            if payload:
                lines.append(f"**Reproducer**: `{kind}` — `{payload}`")
            else:
                lines.append(f"**Reproducer**: `{kind}`")
            lines.append("")
        if e.triage_status and e.triage_status not in ("", "open"):
            note = f" — {e.triage_note}" if e.triage_note else ""
            lines.append(f"**Triage**: {e.triage_status}{note}")
            lines.append("")
        if e.oracle_verdict == "ERROR":
            lines.append("**Action**: instrument problem — fix the "
                         "reproducer before acting (do NOT dispatch a fix)")
        elif e.label == "unverified" or e.oracle_verdict == "MANUAL":
            lines.append("**Action**: needs-human-judgement")
        elif e.severity in ("drift", "error"):
            lines.append("**Action**: needs-fix")
        else:
            lines.append("**Action**: info — track for hygiene")
        lines.append("")
    # Appendix: the oracle's own layer profiles — how much to trust each
    # verdict class in this report (the corrected framework's replacement
    # for the Tier ladder; see SPEC.md §"Layer profiles").
    lines.append("---")
    lines.append("")
    lines.append("## Layer profiles")
    lines.append("")
    lines.append(render_profiles("markdown").rstrip())
    lines.append("")
    return "\n".join(lines) + "\n"


def render_json(entries: list[ReportEntry], header: dict) -> str:
    return json.dumps(
        {
            "header": header,
            "findings": [e.to_dict() for e in entries],
            "layer_profiles": [PROFILES[k].as_dict() for k in ("A", "B", "C", "D")],
        },
        indent=2,
        sort_keys=False,
    ) + "\n"
