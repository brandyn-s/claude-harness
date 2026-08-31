"""Golden tests for validate_constraint_trace.py (scout-frontier Phase 0 gate).

Tests verify all FAIL conditions from SKILL.md Step 0 are enforced:
  - end_state must contain a measurable phrase
  - at least 1 friction entry must cite evidence
  - abstracted_constraints must have ≥1 non-empty entry
  - if 3+ friction entries, abstracted_constraints must be non-empty
  - structured friction dicts must have an 'id' field

Exit codes: 0 = pass, 1 = FAIL conditions violated, 2 = malformed YAML.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

VALIDATOR = Path(__file__).parent.parent / "scripts" / "validate_constraint_trace.py"


def run(trace_yaml: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        input=trace_yaml,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_LEGACY = textwrap.dedent("""\
    end_state: code-graph answers any architectural question with ≥90% accuracy.
    friction:
      - "graph misses Go-to-Rust FFI edges; measured on 12 test repos — 0/12 expected edges"
    abstracted_constraints:
      - incremental graph reconstruction under partial information
""")

VALID_STRUCTURED = textwrap.dedent("""\
    constraint_trace:
      end_state: call-graph query latency under 200ms at p99 for monorepo of 2M LOC.
      friction:
        - id: F1
          what: graph misses cross-language FFI edges
          measured: "0/12 expected edges in fleet-mgr crate"
        - id: F2
          what: incremental rebuild scans all files on any change
          measured: "45s rebuild for single-file edit on 500K LOC repo"
      abstracted_constraints:
        - incremental graph reconstruction under partial information
        - cross-language symbol resolution in polyglot context
""")

VALID_THREE_FRICTION = textwrap.dedent("""\
    end_state: precision ≥95% on call-graph queries across all supported languages.
    friction:
      - id: F1
        what: misses FFI edges
        measured: "0/12 correct"
      - id: F2
        what: slow rebuild
        measured: "45s for single change"
      - id: F3
        what: no streaming support
        measured: "full scan on every query"
    abstracted_constraints:
      - cross-language resolution under partial info
""")

ABSTRACT_END_STATE = textwrap.dedent("""\
    end_state: improve the code understanding capabilities of the system.
    friction:
      - "graph misses edges; measured on 12 repos"
    abstracted_constraints:
      - incremental reconstruction
""")

NO_EVIDENCE_IN_FRICTION = textwrap.dedent("""\
    end_state: code-graph answers queries with ≥90% accuracy.
    friction:
      - "graph is slow"
      - "misses some edges"
    abstracted_constraints:
      - incremental reconstruction
""")

MISSING_ABSTRACTED_CONSTRAINTS = textwrap.dedent("""\
    end_state: latency under 100ms at p99.
    friction:
      - "graph misses edges; measured on 12 repos"
    abstracted_constraints: []
""")

THREE_FRICTION_NO_ABSTRACTED = textwrap.dedent("""\
    end_state: precision ≥95% on call-graph queries.
    friction:
      - id: F1
        what: misses FFI edges
        measured: "0/12 correct"
      - id: F2
        what: slow rebuild
        measured: "45s for single change"
      - id: F3
        what: no streaming support
        measured: "full scan on every query"
    abstracted_constraints: []
""")

STRUCTURED_MISSING_ID = textwrap.dedent("""\
    end_state: latency under 100ms at p99.
    friction:
      - what: graph misses edges
        measured: "0/12 expected edges found"
    abstracted_constraints:
      - incremental reconstruction
""")

MALFORMED_YAML = "end_state: [unclosed bracket\nfriction:\n"

EMPTY_INPUT = ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_valid_legacy_trace_passes():
    code, out = run(VALID_LEGACY)
    assert code == 0, f"Expected 0, got {code}. Output: {out}"
    assert "PASS" in out


def test_valid_structured_trace_passes():
    code, out = run(VALID_STRUCTURED)
    assert code == 0, f"Expected 0, got {code}. Output: {out}"
    assert "PASS" in out


def test_valid_three_friction_entries_passes():
    code, out = run(VALID_THREE_FRICTION)
    assert code == 0, f"Expected 0, got {code}. Output: {out}"
    assert "PASS" in out


def test_abstract_end_state_fails():
    """end_state without a measurable phrase must exit 1."""
    code, out = run(ABSTRACT_END_STATE)
    assert code == 1, f"Expected 1 (FAIL), got {code}. Output: {out}"
    assert "end_state lacks measurable phrase" in out or "end_state" in out


def test_friction_without_evidence_fails():
    """Friction entries with no evidence phrase must exit 1."""
    code, out = run(NO_EVIDENCE_IN_FRICTION)
    assert code == 1, f"Expected 1 (FAIL), got {code}. Output: {out}"
    assert "friction" in out.lower() or "evidence" in out.lower()


def test_missing_abstracted_constraints_fails():
    """Empty abstracted_constraints must exit 1."""
    code, out = run(MISSING_ABSTRACTED_CONSTRAINTS)
    assert code == 1, f"Expected 1 (FAIL), got {code}. Output: {out}"
    assert "abstracted" in out.lower() or "constraint" in out.lower()


def test_three_friction_no_abstracted_fails():
    """3+ friction entries with empty abstracted_constraints must exit 1."""
    code, out = run(THREE_FRICTION_NO_ABSTRACTED)
    assert code == 1, f"Expected 1 (FAIL), got {code}. Output: {out}"
    assert "abstracted" in out.lower() or "constraint" in out.lower()


def test_structured_friction_missing_id_fails():
    """Structured friction dict missing 'id' field must exit 1."""
    code, out = run(STRUCTURED_MISSING_ID)
    assert code == 1, f"Expected 1 (FAIL), got {code}. Output: {out}"
    assert "id" in out.lower()


def test_malformed_yaml_exits_2():
    """Invalid YAML must exit 2."""
    code, out = run(MALFORMED_YAML)
    assert code == 2, f"Expected 2 (malformed), got {code}. Output: {out}"


def test_empty_input_exits_2():
    """Empty input must exit 2."""
    code, out = run(EMPTY_INPUT)
    assert code == 2, f"Expected 2 (malformed), got {code}. Output: {out}"


def test_measurable_phrase_percentage_accepted():
    """end_state with a percentage is valid."""
    trace = textwrap.dedent("""\
        end_state: query precision 95% on the benchmark suite.
        friction:
          - "graph misses edges; measured on 12 test repos"
        abstracted_constraints:
          - incremental reconstruction
    """)
    code, _ = run(trace)
    assert code == 0


def test_measurable_phrase_latency_accepted():
    """end_state referencing latency is valid."""
    trace = textwrap.dedent("""\
        end_state: p99 latency under 50ms for any query.
        friction:
          - "queries take 3s; observed in prod load test"
        abstracted_constraints:
          - bounded worst-case execution time
    """)
    code, _ = run(trace)
    assert code == 0


def test_structured_friction_measured_field_counts_as_evidence():
    """A non-empty 'measured' field satisfies the evidence requirement."""
    trace = textwrap.dedent("""\
        end_state: ≥90% accuracy on edge-detection benchmark.
        friction:
          - id: F1
            what: misses cross-language edges
            measured: "0 out of 12 expected edges found in fleet-mgr"
        abstracted_constraints:
          - cross-language resolution
    """)
    code, _ = run(trace)
    assert code == 0
