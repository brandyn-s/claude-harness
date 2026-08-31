"""The audit-skill oracle — verification scaffolding around Phase 2 findings.

Four layers, each addressing a specific failure mode observed in the
May 2026 audit:

A. reverify — Before acting on a finding, re-run its reproducer against
   the live tree. Catches stale findings that have already been fixed
   elsewhere (the "batch B false-positive" pattern: agent re-fixes
   something that was already fixed). See ``oracle.reverify``.

B. ensemble — Dispatch N independent Phase 2 agents against the same
   skill; retain only findings ≥ M of them report. Reduces single-agent
   hallucinated findings. See ``oracle.ensemble``.

C. golden corpus — Curated expected-findings per fixture skill;
   precision/recall measured against live agent output. Catches
   detection-logic regressions in the Phase 2 procedure itself. See
   ``oracle.corpus``.

D. fix-loop — For each proposed fix, run the reproducer pre-fix (must
   fire) and post-fix (must NOT fire). Catches "the fix didn't fix it"
   plus stale findings (pre-fix already not firing). See
   ``oracle.fix_loop``.

Layer A is the cheapest gate; D is the strictest. The CLI
``bin/audit-skill-oracle.py`` exposes all four.
"""

from .finding import Finding, Reproducer, load_findings, dump_findings  # noqa: F401
