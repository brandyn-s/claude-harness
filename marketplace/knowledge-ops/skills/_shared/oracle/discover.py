"""Root-cause fix for cause 1 (static tracker / live-tree mismatch).

The May 2026 fix campaign used a static markdown tracker
(``AUDIT-TRACKERS/05-phase2-findings.md``) as the worklist source.
That tracker was a snapshot of what the 89-agent Phase 2 audit found
at one moment. Between that moment and any later fix-batch dispatch,
the tree moved — and 38% of "findings" the batches read were already
resolved.

The MITIGATION was reverify-before-action (``oracle.act_on``).
The ROOT FIX is to never have a static tracker as the worklist
source at all.

This module provides ``discover_worklist()`` — a one-shot that:

  1. Runs Phase 1 (mechanical lint via bin/audit-skill.py) inline.
  2. Surfaces the Phase 1 findings as structured Finding objects
     with grep-based Reproducers (most Phase 1 categories have an
     obvious deterministic predicate).
  3. Optionally dispatches Phase 2 agents (caller-provided, since
     Python can't dispatch agents directly) and accepts their
     structured YAML output.
  4. Runs Layer A reverify against the combined Phase 1 + Phase 2
     findings (the worklist's findings are already from THIS
     moment, so most should be STILL-FIRES — but the gate runs
     anyway as part of the same one-shot).

The worklist emitted by ``discover_worklist`` has a trace record
per finding from the inline reverify step, so it passes
``validate_for_dispatch`` immediately. The orchestrator never sees
a stale tracker because there is no tracker — discovery and
verification happen in the same call.

For users who want to inspect the Phase 1 findings only (skip Phase
2 agent dispatch), ``discover_phase1_only`` is the lighter call.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from .finding import Finding, Reproducer
from .reverify import reverify
from .act_on import act_on, ActOnReport


# Mapping from Phase 1 code → Reproducer template. For each code we
# emit a deterministic predicate that re-checks the finding against
# the live tree.
def _phase1_reproducer(code: str, skill: str, evidence: str) -> Reproducer:
    """Construct a Reproducer for a Phase 1 finding. The evidence
    string from bin/audit-skill.py output usually contains enough
    detail to re-check (file path, tool name, etc.); for codes whose
    evidence can't be reduced, fall back to type=manual."""
    skill_dir = f"skills/{skill}"

    if code == "H1":
        # "cited references/X.md does not exist"
        # evidence example: "cited references/missing.md does not exist"
        import re
        m = re.search(r"references/([a-z0-9._-]+\.md)", evidence)
        if m:
            return Reproducer(
                type="file_missing",
                path=f"{skill_dir}/references/{m.group(1)}",
            )

    if code == "H4":
        # cross-skill citation broken: pull both segments from evidence
        import re
        m = re.search(r"cross-skill citation ([a-z][a-z0-9-]+)/references/([a-z0-9._-]+\.md)", evidence)
        if m:
            return Reproducer(
                type="file_missing",
                path=f"skills/{m.group(1)}/references/{m.group(2)}",
            )

    if code == "T1":
        # known-phantom MCP tool — bin/audit-skill.py's evidence quotes
        # the tool name in single quotes.
        import re
        m = re.search(r"mcp__[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+", evidence)
        if m:
            return Reproducer(
                type="grep",
                command=f"grep -rqE '{re.escape(m.group(0))}' {skill_dir}",
            )

    if code == "P1":
        # Unresolved placeholder in SKILL.md
        if "{baseDir}" in evidence:
            return Reproducer(
                type="grep",
                command=f"grep -E '\\{{baseDir\\}}' {skill_dir}/SKILL.md",
            )
        if "<your-" in evidence:
            return Reproducer(
                type="grep",
                command=f"grep -E '<your-[a-z0-9-]+>' {skill_dir}/SKILL.md",
            )

    # Default: manual. The discover loop will surface these to the
    # caller as "needs human verification" — the same shape Layer A
    # already supports.
    return Reproducer(
        type="manual",
        description=f"{code}: {evidence}",
    )


def discover_phase1_only(repo_root: Path, skill: str | None = None) -> list[Finding]:
    """Run bin/audit-skill.py inline and convert its findings to
    Finding objects with Reproducers. Pass ``skill=None`` for --all.

    This is the lighter variant — no Phase 2 agent dispatch. Useful
    when the caller wants to act on Phase 1 alone (mechanical
    drift only)."""
    audit_script = repo_root / "bin" / "audit-skill.py"
    spec = importlib.util.spec_from_file_location("audit_skill", audit_script)
    audit_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_mod)

    if skill is None:
        skill_names = sorted(
            p.name for p in audit_mod.SKILLS.iterdir()
            if p.is_dir() and (p / "SKILL.md").exists()
        )
    else:
        skill_names = [skill]

    findings: list[Finding] = []
    for skill_name in skill_names:
        for raw in audit_mod.audit(skill_name):
            label = "behavior-fix" if raw.severity == "drift" else "doc-fix"
            findings.append(Finding(
                skill=skill_name,
                code=raw.code,
                severity=raw.severity,
                label=label,
                description=raw.msg,
                reproducer=_phase1_reproducer(raw.code, skill_name, raw.msg),
                source=f"{raw.path}:{raw.line}" if raw.path and raw.line else (raw.path or ""),
            ))
    return findings


def discover_worklist(
    repo_root: Path,
    skill: str | None = None,
    phase2_findings: list[Finding] | None = None,
) -> ActOnReport:
    """One-shot: Phase 1 lint + (optional) Phase 2 findings + Layer A
    reverify. Returns an ActOnReport whose ``worklist`` field is the
    dispatchable findings — already verified, with trace records.

    For Phase 2 input, the caller dispatches agents externally and
    passes their structured Finding output here. Python can't invoke
    the Agent tool directly; the orchestrator must do that.

    Returns the same ActOnReport shape as ``oracle.act_on`` — the
    orchestrator surfaces the stale-rate, applies the worklist,
    nothing extra to learn."""
    phase1 = discover_phase1_only(repo_root, skill)
    combined = phase1 + list(phase2_findings or [])
    report = act_on(combined, repo_root)
    return report
