#!/usr/bin/env python3
"""Step-0 worklist validation gates for /audit-fix.

Mechanical extraction of the three validate gates SKILL.md Step 0
describes. The prose defines WHAT the gates mean; this script is the
HOW. Per SKILL.md, the gates refuse worklists where:

  Gate 1 (malformed) — the worklist violates the act-on format:
      unparseable / not a structured YAML worklist (raw markdown
      trackers included), a finding is missing required fields
      (skill, code, description, reproducer.type, plus
      reproducer.command — or reproducer.path for the
      file_exists / file_missing types), the file contains no
      findings at all, or a finding's reproducer is ``type: manual``
      (no auto-check possible).

  Gate 2 (stale) — the trace record is older than 30 minutes
      (TTL expired). Re-run ``act-on`` to refresh.

  Gate 3 (no-trace) — no trace record exists (act-on wasn't run).
      The dispatch path requires fresh Layer-A verification.

  Gate 4 (error-verdict) — the latest Layer-A verdict for the finding
      is ERROR (the reproducer itself is broken). Repair the
      reproducer before dispatch; a fix-agent cannot flip a predicate
      that errors on every run.

Exit codes:
  0 — all gates pass; JSON dispatch summary on stdout.
  1 — operator error (worklist file not found / oracle missing).
  2 — a gate tripped; JSON rejection report on stdout, one
      ``<gate-name>: <where>: <reason>`` line per rejection on stderr.

Stdlib only. The finding loader, trace reader, and finding-id join key
are reused from ``skills/_shared/oracle`` (itself stdlib-only) rather
than reimplemented, so the trace join key always matches what
``audit-skill-oracle.py act-on`` writes. The trace file defaults to
``~/.claude/oracle-trace.jsonl`` and honors the
``AUDIT_SKILL_ORACLE_TRACE`` env var (tests point it into a tmpdir).

Usage:
    python3 validate_worklist.py <worklist.yaml> [--max-age-seconds N]
                                 [--trace PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# SKILL.md Step 0: "The trace record is older than 30 minutes (TTL
# expired)". Mirrors oracle.validate.MAX_REVERIFY_AGE_SECONDS.
DEFAULT_MAX_AGE_SECONDS = 30 * 60

GATE_1_MALFORMED = "gate-1-malformed"
GATE_2_STALE = "gate-2-stale"
GATE_3_NO_TRACE = "gate-3-no-trace"
GATE_4_ERROR_VERDICT = "gate-4-error-verdict"
ALL_GATES = (GATE_1_MALFORMED, GATE_2_STALE, GATE_3_NO_TRACE,
             GATE_4_ERROR_VERDICT)
GATE_NUMBER = {GATE_1_MALFORMED: 1, GATE_2_STALE: 2, GATE_3_NO_TRACE: 3,
               GATE_4_ERROR_VERDICT: 4}

# Required per the manifest input_contract (oracle/SPEC.md "Finding"):
# [skill, code, reproducer.type, reproducer.command, description].
# file_exists / file_missing reproducers carry a `path` instead of a
# `command`; both spellings of "the predicate's target" are accepted.
PATH_REPRODUCER_TYPES = ("file_exists", "file_missing")


def _load_oracle():
    """Import the shared oracle helpers (loader, trace reader, join key).

    Located relative to this file: skills/audit-fix/scripts/ →
    skills/_shared/. Reuse instead of reimplementation guarantees the
    finding_id computed here is byte-identical to the one act-on wrote
    into the trace — a private hash copy would silently desynchronize
    and turn every worklist into a gate-3 false rejection.
    """
    shared = Path(__file__).resolve().parents[2] / "_shared"
    if not (shared / "oracle").is_dir():
        return None
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    from oracle.finding import load_findings, FindingsParseError  # noqa: E402
    from oracle.trace import read_records, finding_id, trace_path  # noqa: E402
    return load_findings, FindingsParseError, read_records, finding_id, trace_path


def _rejection(gate: str, reason: str, skill: str = "", code: str = "",
               fid: str = "") -> dict:
    return {
        "gate": gate,
        "gate_number": GATE_NUMBER[gate],
        "skill": skill,
        "code": code,
        "finding_id": fid,
        "reason": reason,
    }


def validate_worklist(worklist: Path, max_age_seconds: int,
                      trace_override: Path | None,
                      oracle) -> tuple[list[dict], list[dict], str]:
    """Apply the three Step-0 gates. Returns (rejections, finding_summaries,
    trace_path_used)."""
    load_findings, FindingsParseError, read_records, finding_id, trace_path = oracle
    rejections: list[dict] = []
    summaries: list[dict] = []

    trace_file = trace_override if trace_override is not None else trace_path()

    # ---- Gate 1: malformed (violates the act-on worklist format) ----
    if worklist.suffix == ".md":
        rejections.append(_rejection(
            GATE_1_MALFORMED,
            f"input is a markdown tracker ({worklist.name}), not a "
            f"structured YAML worklist. Run `audit-skill-oracle.py "
            f"act-on <tracker> --out <worklist.yaml>` first.",
        ))
        return rejections, summaries, str(trace_file)

    try:
        findings = load_findings(worklist)
    except FindingsParseError as e:
        rejections.append(_rejection(
            GATE_1_MALFORMED, f"failed to parse worklist: {e}",
        ))
        return rejections, summaries, str(trace_file)

    if not findings:
        rejections.append(_rejection(
            GATE_1_MALFORMED,
            "worklist contains no findings — not a dispatchable act-on "
            "worklist (nothing to dispatch).",
        ))
        return rejections, summaries, str(trace_file)

    # Trace index: latest Layer-A (reverify) record per finding_id.
    # Only Layer A gates dispatch — the question is "when did act-on
    # last verify this finding, and what did it say?"
    latest_by_id: dict[str, tuple[datetime, str]] = {}
    for rec in read_records(trace_file):
        if rec.layer != "A":
            continue
        try:
            ts = datetime.fromisoformat(rec.ts)
        except (ValueError, TypeError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        existing = latest_by_id.get(rec.finding_id)
        if existing is None or ts > existing[0]:
            latest_by_id[rec.finding_id] = (ts, rec.verdict)

    now = datetime.now(timezone.utc)
    for f in findings:
        # ---- Gate 1 (per-finding): required fields + manual type ----
        missing = [name for name, val in (
            ("skill", f.skill), ("code", f.code), ("description", f.description),
            ("reproducer.type", f.reproducer.type),
        ) if not (val or "").strip()]
        if f.reproducer.type in PATH_REPRODUCER_TYPES:
            if not (f.reproducer.path or "").strip():
                missing.append("reproducer.path")
        elif f.reproducer.type != "manual":
            if not (f.reproducer.command or "").strip():
                missing.append("reproducer.command")
        if missing:
            rejections.append(_rejection(
                GATE_1_MALFORMED,
                f"finding is missing required field(s): {', '.join(missing)} "
                f"(input contract: skill, code, description, reproducer.type, "
                f"reproducer.command).",
                skill=f.skill, code=f.code,
            ))
            continue

        fid = finding_id(f.skill, f.code, f.description)

        if f.reproducer.type == "manual":
            rejections.append(_rejection(
                GATE_1_MALFORMED,
                "finding's reproducer is `type: manual` (no auto-check "
                "possible) — route to human review, not to a fix-batch.",
                skill=f.skill, code=f.code, fid=fid,
            ))
            continue

        # ---- Gate 3: no trace record exists (act-on wasn't run) ----
        latest = latest_by_id.get(fid)
        if latest is None:
            rejections.append(_rejection(
                GATE_3_NO_TRACE,
                "no trace record exists for this finding (act-on wasn't "
                "run). Run `audit-skill-oracle.py act-on` to produce a "
                "verified worklist before dispatch.",
                skill=f.skill, code=f.code, fid=fid,
            ))
            continue
        latest_ts, latest_verdict = latest

        # ---- Gate 2: trace record older than the TTL (stale) ----
        age_seconds = int((now - latest_ts).total_seconds())
        if age_seconds > max_age_seconds:
            rejections.append(_rejection(
                GATE_2_STALE,
                f"trace record is stale: latest reverify was {age_seconds}s "
                f"ago, older than the {max_age_seconds}s TTL. Re-run "
                f"`audit-skill-oracle.py act-on` before dispatch.",
                skill=f.skill, code=f.code, fid=fid,
            ))
            continue

        # ---- Gate 4: latest verdict is ERROR (broken reproducer) ----
        # A worklist row whose instrument errors on every run cannot be
        # verified fixed; dispatching it wastes a fix-agent and the
        # batch gate then reports an unexplainable non-STALE. Observed
        # 2026-08-22: two ERROR-verdict rows passed validation and had
        # to be hand-filtered before dispatch.
        if latest_verdict == "ERROR":
            rejections.append(_rejection(
                GATE_4_ERROR_VERDICT,
                "latest oracle verdict is ERROR (the reproducer itself "
                "failed to run) — repair the reproducer and re-run act-on "
                "before dispatching this finding.",
                skill=f.skill, code=f.code, fid=fid,
            ))
            continue

        summaries.append({
            "skill": f.skill,
            "code": f.code,
            "finding_id": fid,
            "reproducer_type": f.reproducer.type,
            "trace_age_seconds": age_seconds,
            "verdict": latest_verdict,
        })

    return rejections, summaries, str(trace_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an /audit-fix worklist against the four Step-0 "
            "gates: gate 1 (malformed worklist), gate 2 (stale trace "
            "record, default TTL 30 minutes), gate 3 (no trace record), "
            "gate 4 (latest verdict is ERROR — broken reproducer). "
            "Exit 0 with a JSON dispatch summary when all gates pass; "
            "exit 2 naming the tripped gate plus reason otherwise."
        ),
    )
    parser.add_argument(
        "worklist",
        help="Path to a STILL-FIRES worklist YAML produced by "
             "`audit-skill-oracle.py act-on`",
    )
    parser.add_argument(
        "--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS,
        help="Trace-record TTL for gate 2 (default: 1800 = 30 minutes)",
    )
    parser.add_argument(
        "--trace", default=None,
        help="Override the oracle trace JSONL path (default: "
             "AUDIT_SKILL_ORACLE_TRACE env var, else "
             "~/.claude/oracle-trace.jsonl)",
    )
    args = parser.parse_args(argv)

    oracle = _load_oracle()
    if oracle is None:
        print("error: skills/_shared/oracle not found relative to this "
              "script; run from a full claude-config checkout", file=sys.stderr)
        return 1

    worklist = Path(args.worklist)
    if not worklist.is_file():
        print(f"error: worklist file not found: {worklist}", file=sys.stderr)
        return 1

    trace_override = Path(args.trace) if args.trace else None
    rejections, summaries, trace_used = validate_worklist(
        worklist, args.max_age_seconds, trace_override, oracle,
    )

    if rejections:
        tripped = sorted({r["gate"] for r in rejections},
                         key=lambda g: GATE_NUMBER[g])
        print(json.dumps({
            "status": "rejected",
            "worklist": str(worklist),
            "gates_tripped": tripped,
            "rejections": rejections,
            "trace_path": trace_used,
            "max_age_seconds": args.max_age_seconds,
        }, indent=2))
        for r in rejections:
            where = f"{r['skill']}/{r['code']}" if r["skill"] else worklist.name
            print(f"{r['gate']}: {where}: {r['reason']}", file=sys.stderr)
        return 2

    print(json.dumps({
        "status": "ok",
        "worklist": str(worklist),
        "finding_count": len(summaries),
        "gates": {gate: "pass" for gate in ALL_GATES},
        "max_age_seconds": args.max_age_seconds,
        "trace_path": trace_used,
        "findings": summaries,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
