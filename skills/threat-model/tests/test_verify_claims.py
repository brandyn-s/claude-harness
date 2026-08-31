"""Tests for skills/threat-model/scripts/verify_claims.py.

Exercise the Tier-1 oracle (structure_check, file_refs_resolve,
surface_attribution) and the Tier-2 calls-edge intent emitter against
synthetic threat-model.md inputs. The code-graph queries themselves
are out of scope here — we just verify the intents are emitted in
the right shape for the orchestrator to consume.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

ORACLE = Path(__file__).resolve().parents[1] / "scripts" / "verify_claims.py"


GOOD_MODEL = textwrap.dedent("""
# Threat Model: example

## Section 1: Overview

Small MCP server. Source: `src/main.rs`.

## Section 2: Trust Boundaries and Assumptions

**Assets**: secrets.

**MCP boundary**: clients send args (src/main.rs).

## Section 3: Attack Surface, Mitigations, and Attacker Stories

### 3.1 JWT signing

**Surface**: signs tokens (src/main.rs).

**Mitigations**
- Secret loaded from env.

**Attacker stories**
- Attacker reads env: forges tokens.

## Section 4: Criticality Calibration

- **Critical**: JWT secret compromise.
""").lstrip()

MISSING_SECTION = textwrap.dedent("""
# Bad model

## Section 1: Overview

Just one section.
""").lstrip()

MISSING_ATTRIBUTION = textwrap.dedent("""
# Model

## Section 1: Overview

Text.

## Section 2: Trust Boundaries and Assumptions

Text.

## Section 3: Attack Surface, Mitigations, and Attacker Stories

### 3.1 Surface without blocks

Just a description, no Mitigations or Attacker stories headings.

## Section 4: Criticality Calibration

- **Low**.
""").lstrip()


def _run(model_path, root, ndjson, claims=None, strict=True):
    cmd = [sys.executable, str(ORACLE), str(model_path),
           "--root", str(root), "--ndjson", str(ndjson), "--json"]
    if claims:
        cmd += ["--claims", str(claims)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _load_ndjson(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_good_model_all_pass(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    model = tmp_path / "threat-model.md"
    model.write_text(GOOD_MODEL, encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(model, tmp_path, ndjson)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["all_passed"] is True
    assert out["structure"] is True
    assert out["attribution"] is True


def test_missing_section_fails(tmp_path):
    model = tmp_path / "tm.md"
    model.write_text(MISSING_SECTION, encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(model, tmp_path, ndjson)
    assert r.returncode == 1
    events = _load_ndjson(ndjson)
    structure = [e for e in events if e.get("check") == "structure_check"]
    assert structure and structure[0]["passed"] is False
    assert structure[0]["missing_sections"] == [2, 3, 4]


def test_missing_attribution_fails(tmp_path):
    model = tmp_path / "tm.md"
    model.write_text(MISSING_ATTRIBUTION, encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(model, tmp_path, ndjson)
    assert r.returncode == 1
    events = _load_ndjson(ndjson)
    attr = [e for e in events if e.get("check") == "surface_attribution"]
    assert attr and attr[0]["passed"] is False
    assert attr[0]["n_issues"] >= 2  # Missing Mitigations + Attacker stories


def test_missing_file_ref_fails(tmp_path):
    model = tmp_path / "tm.md"
    bad = GOOD_MODEL.replace("src/main.rs", "src/does_not_exist.rs")
    model.write_text(bad, encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(model, tmp_path, ndjson)
    assert r.returncode == 1
    events = _load_ndjson(ndjson)
    refs = [e for e in events if e.get("check") == "file_refs_resolve"]
    assert refs and refs[0]["passed"] is False
    assert refs[0]["n_missing"] >= 1


def test_claims_emit_calls_edge_intents(tmp_path):
    (tmp_path / "src").mkdir()
    # Source contains the claimed endpoint symbols so both claims ground
    # (GROUNDED) and the run stays green — while still emitting the intents.
    (tmp_path / "src" / "main.rs").write_text(
        "struct Handler;\n"
        "impl Handler {\n"
        "    fn execute(&self) { let _s = JWT_SECRET; }\n"
        "}\n"
        "const JWT_SECRET: &str = \"x\";\n"
        "fn main() {}\n",
        encoding="utf-8")
    model = tmp_path / "tm.md"
    model.write_text(GOOD_MODEL, encoding="utf-8")
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps({
        "model_id": "t",
        "claims": [
            {"id": "h-to-e", "kind": "calls_across",
             "from_pattern": ".*Handler.*", "to_pattern": ".*execute.*",
             "boundary": "mcp"},
            {"id": "use-secret", "kind": "usage",
             "to_pattern": "JWT_SECRET", "boundary": "config"},
        ],
    }), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(model, tmp_path, ndjson, claims=claims)
    assert r.returncode == 0, r.stderr
    events = _load_ndjson(ndjson)
    intents = [e for e in events if e.get("check") == "calls_edge_intent"]
    assert len(intents) == 2
    by_id = {e["claim_id"]: e for e in intents}
    assert "CALLS|HTTP_CALLS" in by_id["h-to-e"]["cypher"]
    assert "USAGE" in by_id["use-secret"]["cypher"]
    # New: deterministic grounding ran and both claims are GROUNDED (their
    # endpoint symbols exist in source), so the probe passed.
    grounding = {e["claim_id"]: e for e in events if e.get("check") == "calls_edge_grounding"}
    assert grounding["h-to-e"]["verdict"] == "GROUNDED"
    assert grounding["use-secret"]["verdict"] == "GROUNDED"
    out = json.loads(r.stdout)
    assert out["calls_edges"] is True


def test_unsubstantiated_claim_fails(tmp_path):
    """A claimed edge whose callee symbol is ABSENT from source is
    UNSUBSTANTIATED -> the probe fails (returncode 1 under --strict).
    This is the whole point of the fix: the old probe always returned True."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    model = tmp_path / "tm.md"
    model.write_text(GOOD_MODEL, encoding="utf-8")
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps({"model_id": "t", "claims": [
        {"id": "ghost", "kind": "usage",
         "to_pattern": "NoSuchSymbolXyzzy", "boundary": "config"},
    ]}), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(model, tmp_path, ndjson, claims=claims)
    assert r.returncode == 1, r.stdout
    events = _load_ndjson(ndjson)
    g = [e for e in events if e.get("check") == "calls_edge_grounding"]
    assert g and g[0]["verdict"] == "UNSUBSTANTIATED"
    probe = [e for e in events if e.get("check") == "calls_edge_probe"]
    assert probe and probe[0]["passed"] is False and probe[0]["unsubstantiated"] == 1


def test_ambiguous_pattern_is_manual_not_fail(tmp_path):
    """A pattern too regex-ambiguous to search is MANUAL (human-required),
    NOT a FAIL — the harness refuses rather than fabricating a verdict."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    model = tmp_path / "tm.md"
    model.write_text(GOOD_MODEL, encoding="utf-8")
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps({"model_id": "t", "claims": [
        {"id": "vague", "kind": "usage", "to_pattern": ".*", "boundary": "x"},
    ]}), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(model, tmp_path, ndjson, claims=claims)
    assert r.returncode == 0, r.stdout
    events = _load_ndjson(ndjson)
    g = [e for e in events if e.get("check") == "calls_edge_grounding"]
    assert g and g[0]["verdict"] == "MANUAL"


def test_clean_stderr_no_deprecation_warnings(tmp_path):
    """Documented happy-path run keeps stderr free of DeprecationWarning
    noise (regression guard for the removed datetime.utcnow() calls)."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    model = tmp_path / "threat-model.md"
    model.write_text(GOOD_MODEL, encoding="utf-8")
    r = _run(model, tmp_path, tmp_path / "run.ndjson")
    assert r.returncode == 0, r.stderr
    assert "DeprecationWarning" not in r.stderr
