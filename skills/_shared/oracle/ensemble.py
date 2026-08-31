"""Layer B — N-agent ENSEMBLE (NOT a decorrelated oracle).

Renamed from "consensus" — see SPEC.md §"Layer B" for the honest
framing. The short version: this is Tier 3, same mechanism as the
proposer, Kim et al. ICML 2025 reports cross-vendor LLM judges
agree 60% of the time when both err. Ensembling buys modest
decorrelation against single-agent hallucination, NOT categorical
decorrelation against systematic misjudgment. Use as a pre-filter
for high-stakes [behavior-fix] findings, composed with Layer A,
never as the sole verdict.

An **AGREED** verdict from this layer means exactly: *≥M of N
agents independently produced a finding whose (skill, code,
description-tokens) cluster matched.* It does NOT mean the bug
is real.

Mechanism: dispatch happens at the orchestrator level via the
Agent tool — Python can't invoke it directly. This module
provides the AGGREGATION logic: given N finding lists (one per
agent), produce the ensemble retain-set.

Sameness rule between agents: same skill, same code, description
Jaccard token-overlap ≥ 0.4. Permissive on purpose — false negatives
(missing a real match) hurt the ensemble; the cost of false
positives (over-merging) is contained because the cluster's
representative is the lowest-agent-index finding, so the report
is deterministic.
"""
from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from pathlib import Path

from .finding import Finding


_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split(text.lower()) if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclasses.dataclass
class ConsensusFinding:
    """A finding agreed upon by ≥ M of N agents."""
    representative: Finding   # one agent's wording, used as the canonical text
    agent_count: int          # how many agents reported it (≥ M)
    n_total: int              # total agents that ran
    variants: list[Finding] = dataclasses.field(default_factory=list)
    # Distinct model vendors that reported this finding (populated when
    # aggregate() is given vendor_by_agent — cross-vendor dispatch).
    # Empty for same-vendor / vendor-unaware runs.
    vendors: list[str] = dataclasses.field(default_factory=list)

    @property
    def confidence(self) -> float:
        return self.agent_count / self.n_total if self.n_total else 0.0


def aggregate(
    agent_findings: list[list[Finding]],
    min_agreement: int | None = None,
    similarity_threshold: float = 0.4,
    vendor_by_agent: list[str] | None = None,
) -> list[ConsensusFinding]:
    """Aggregate N agents' finding lists into a consensus list.

    Args:
      agent_findings: list of length N; each element is one agent's
        list[Finding].
      min_agreement: minimum agreement count M. Defaults to majority
        (ceil(N/2) + 1).
      similarity_threshold: Jaccard token overlap threshold for
        considering two findings "the same".
    """
    n_total = len(agent_findings)
    if n_total == 0:
        return []
    if min_agreement is None:
        # Majority: at least (N // 2) + 1
        min_agreement = (n_total // 2) + 1

    # Flatten into (agent_id, finding) and group by skill+code first
    # — agents disagreeing on skill or code are by definition different.
    buckets: dict[tuple[str, str], list[tuple[int, Finding]]] = defaultdict(list)
    for agent_id, findings in enumerate(agent_findings):
        for f in findings:
            buckets[(f.skill, f.code)].append((agent_id, f))

    consensus: list[ConsensusFinding] = []
    for (skill, code), pairs in buckets.items():
        # Within a bucket, cluster by description-similarity.
        clusters: list[list[tuple[int, Finding]]] = []
        for agent_id, f in pairs:
            tok = _tokens(f.description)
            placed = False
            for cluster in clusters:
                # Compare against the cluster's first member.
                _, anchor = cluster[0]
                if _jaccard(tok, _tokens(anchor.description)) >= similarity_threshold:
                    cluster.append((agent_id, f))
                    placed = True
                    break
            if not placed:
                clusters.append([(agent_id, f)])
        for cluster in clusters:
            agent_ids = {aid for aid, _ in cluster}
            if len(agent_ids) >= min_agreement:
                # Pick the finding from the lowest-index agent as the
                # representative — deterministic, no ranking on prose.
                cluster_sorted = sorted(cluster, key=lambda p: p[0])
                rep_finding = cluster_sorted[0][1]
                vendors = sorted({
                    vendor_by_agent[aid] for aid in agent_ids
                    if vendor_by_agent is not None and aid < len(vendor_by_agent)
                }) if vendor_by_agent else []
                consensus.append(ConsensusFinding(
                    representative=rep_finding,
                    agent_count=len(agent_ids),
                    n_total=n_total,
                    variants=[f for _, f in cluster_sorted],
                    vendors=vendors,
                ))
    return consensus


def distinct_vendor_count(cf: ConsensusFinding) -> int:
    """Number of distinct model vendors that independently reported the
    finding. >1 means real cross-vendor decorrelation — stronger than
    same-vendor N-of-1, but still NOT a sound oracle (cross-vendor judges
    co-err; see SPEC §'Layer B')."""
    return len(set(cf.vendors))


def emit_dispatch_plan(skill_name: str, n: int) -> str:
    """Emit the orchestrator instructions for dispatching N Phase 2
    audits in parallel. The orchestrator (e.g., /audit-skill skill
    itself, running as an agent) reads this and dispatches accordingly."""
    return (
        f"# Phase 2 Ensemble Dispatch — {skill_name} (N={n})\n"
        f"\n"
        f"Dispatch {n} parallel Explore agents against `skills/{skill_name}/`,\n"
        f"each with the Phase 2 audit prompt from `skills/audit-skill/SKILL.md`.\n"
        f"Collect each agent's findings as a JSON list (using the schema in\n"
        f"`skills/audit-skill/oracle/finding.py`). Then:\n"
        f"\n"
        f"  python3 bin/audit-skill-oracle.py ensemble \\\n"
        f"    agent-0.json agent-1.json ... agent-{n-1}.json \\\n"
        f"    --min-agreement {(n // 2) + 1}\n"
        f"\n"
        f"Findings reported by ≥ ⌈{n}/2⌉ + 1 = {(n // 2) + 1} of {n} agents\n"
        f"are retained. The rest are demoted to `[unverified-low-ensemble]`\n"
        f"and surfaced separately for human review. NOTE: ensemble is a\n"
        f"Tier 3 soft evaluator that is NOT decorrelated from the proposer\n"
        f"(Kim et al. ICML 2025); use only as a pre-filter, not as the sole\n"
        f"verdict (see oracle/SPEC.md §'Layer B').\n"
    )
