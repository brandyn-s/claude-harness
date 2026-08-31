"""CI gate for the round-level sycophancy metric in audit_concessions.py.

Sycophancy detection complements the Agent-D null-control: it flags a round
where CONCEDE/PARTIAL position-changes overwhelmingly lack new evidence
(agents caving to each other without citing anything new). The threshold is
SYCOPHANCY_THRESHOLD (0.5).

Pins two cases:
  - 3 unjustified flips out of 4 (0.75 > 0.5) MUST flag CORRELATED-SYCOPHANCY
  - a round of mostly evidence-backed flips MUST NOT flag
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# Path-load under a unique module name to avoid sys.modules collisions when
# pytest imports across multiple skills (same pattern as
# test_consensus_integrity.py / test_roundtable_golden.py).
_spec = importlib.util.spec_from_file_location(
    "roundtable_audit_concessions", SCRIPTS / "audit_concessions.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
compute_round_sycophancy = _mod.compute_round_sycophancy
SYCOPHANCY_THRESHOLD = _mod.SYCOPHANCY_THRESHOLD


def _concession(round_num: int, citation_ok: bool) -> dict:
    """Minimal audit-result dict as produced by audit_block() + round tagging.

    compute_round_sycophancy only reads `round` and `citation_ok`.
    """
    return {"round": round_num, "citation_ok": citation_ok}


def test_threshold_value():
    assert SYCOPHANCY_THRESHOLD == 0.5


def test_three_unjustified_of_four_flags():
    # 3 of 4 concessions lack new evidence (citation_ok=False) -> 0.75 > 0.5.
    results = [
        _concession(3, citation_ok=False),
        _concession(3, citation_ok=False),
        _concession(3, citation_ok=False),
        _concession(3, citation_ok=True),
    ]
    rounds = compute_round_sycophancy(results)
    assert len(rounds) == 1
    r = rounds[0]
    assert r["round"] == 3
    assert r["n_concessions"] == 4
    assert r["n_unjustified"] == 3
    assert abs(r["unjustified_fraction"] - 0.75) < 1e-9
    assert r["flag"] == "CORRELATED-SYCOPHANCY"


def test_mostly_evidence_backed_does_not_flag():
    # 1 of 4 lacks evidence -> 0.25 <= 0.5; no flag.
    results = [
        _concession(4, citation_ok=True),
        _concession(4, citation_ok=True),
        _concession(4, citation_ok=True),
        _concession(4, citation_ok=False),
    ]
    rounds = compute_round_sycophancy(results)
    assert len(rounds) == 1
    r = rounds[0]
    assert r["n_unjustified"] == 1
    assert r["flag"] is None


def test_exactly_half_does_not_flag():
    # Boundary: 1 of 2 -> 0.5, NOT > 0.5, so no flag (strictly-greater gate).
    results = [
        _concession(3, citation_ok=False),
        _concession(3, citation_ok=True),
    ]
    rounds = compute_round_sycophancy(results)
    assert rounds[0]["flag"] is None


def test_rounds_are_grouped_independently():
    results = [
        # Round 3: all unjustified -> flagged.
        _concession(3, citation_ok=False),
        _concession(3, citation_ok=False),
        # Round 4: all evidence-backed -> clean.
        _concession(4, citation_ok=True),
        _concession(4, citation_ok=True),
    ]
    rounds = {r["round"]: r for r in compute_round_sycophancy(results)}
    assert rounds[3]["flag"] == "CORRELATED-SYCOPHANCY"
    assert rounds[4]["flag"] is None


def test_fully_malformed_transcript_exits_2(tmp_path):
    """Error path: a transcript with zero parseable JSON lines must fail
    loudly (exit 2, clean error on stderr, no traceback) instead of
    reporting a clean '0 concessions' audit (2026-06 audit finding)."""
    import subprocess
    import sys

    (tmp_path / "transcript.jsonl").write_text(
        'NOT JSON AT ALL\n{"broken\n', encoding="utf-8"
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_concessions.py"), str(tmp_path)],
        capture_output=True,
    )
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 2
    assert "Traceback" not in stderr
    assert "error: no parseable JSON lines" in stderr
