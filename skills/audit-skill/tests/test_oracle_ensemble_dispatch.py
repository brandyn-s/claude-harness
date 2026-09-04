"""Layer B cross-vendor dispatch tests (hermetic — mock adapters, no API
keys, no network)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

FINDING_JSON = (
    '```json\n[{"code":"D2","severity":"drift","label":"behavior-fix",'
    '"description":"missing repo map file",'
    '"reproducer":{"type":"grep","command":"grep -q repo-map f"}}]\n```'
)


@pytest.fixture(autouse=True)
def _isolate_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "oracle-trace.jsonl"))


def _load():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for m in ("oracle", "oracle.finding", "oracle.ensemble",
              "oracle.ensemble_dispatch", "oracle.trace"):
        sys.modules.pop(m, None)
    from oracle import finding as f_mod  # noqa: E402
    from oracle import ensemble_dispatch as ed  # noqa: E402
    from oracle import ensemble as en  # noqa: E402
    return f_mod, ed, en


def _mock(text, ok=True, model="m"):
    def _call(prompt, max_tokens=4000):
        return {"ok": ok, "text": text, "model": model}
    return _call


def test_three_agreeing_vendors_yield_cross_vendor_consensus():
    _f, ed, en = _load()
    adapters = {
        "anthropic": _mock(FINDING_JSON, model="claude-x"),
        "openai": _mock(FINDING_JSON, model="gpt-x"),
        "xai": _mock(FINDING_JSON, model="grok-x"),
    }
    consensus, used = ed.ensemble_cross_vendor(
        "audit foo", "foo", adapters=adapters, min_agreement=2)
    assert sorted(used) == ["anthropic", "openai", "xai"]
    assert len(consensus) == 1
    cf = consensus[0]
    # REAL cross-vendor decorrelation: 3 distinct vendors reported it.
    assert en.distinct_vendor_count(cf) == 3
    assert sorted(cf.vendors) == ["anthropic", "openai", "xai"]
    assert cf.representative.skill == "foo"  # skill auto-tagged on parse


def test_graceful_degrade_to_available_vendors():
    """Missing key (adapter None) or import failure (vendor absent from the
    map) is recorded as ok:False, never fatal; vendors_used excludes them."""
    _f, ed, _en = _load()
    adapters = {"anthropic": _mock(FINDING_JSON), "openai": None}  # xai absent
    results = ed.dispatch_cross_vendor(
        "p", "foo", vendors=["anthropic", "openai", "xai"],
        adapters=adapters, trace=False)
    by = dict(results)
    assert by["anthropic"]["ok"] is True
    assert by["openai"]["ok"] is False
    assert by["xai"]["ok"] is False
    # Only the available vendor contributes to the ensemble.
    consensus, used = ed.ensemble_cross_vendor(
        "p", "foo", adapters=adapters, min_agreement=1)
    assert used == ["anthropic"]


def test_adapter_exception_is_contained():
    _f, ed, _en = _load()
    def boom(prompt, max_tokens=4000):
        raise RuntimeError("network down")
    results = ed.dispatch_cross_vendor(
        "p", "foo", vendors=["anthropic"], adapters={"anthropic": boom}, trace=False)
    assert results[0][1]["ok"] is False
    assert "adapter raised" in results[0][1]["error"]


def test_parse_findings_fenced_bare_and_invalid():
    _f, ed, _en = _load()
    fenced = ('```json\n[{"code":"A","severity":"info","label":"doc-fix",'
              '"description":"d","reproducer":{"type":"manual"}}]\n```')
    assert len(ed.parse_findings_from_text(fenced, "s")) == 1
    bare = ('prose before [{"code":"A","severity":"info","label":"doc-fix",'
            '"description":"d","reproducer":{"type":"manual"}}] prose after')
    assert len(ed.parse_findings_from_text(bare, "s")) == 1
    assert ed.parse_findings_from_text("no json at all", "s") == []
    assert ed.parse_findings_from_text("[not valid json}", "s") == []


def test_layer_b_trace_records_written(tmp_path, monkeypatch):
    """Dispatch writes one layer:'B' trace record per vendor with the
    vendor's model_version — the first code to emit Layer-B trace."""
    import json
    trace = tmp_path / "b-trace.jsonl"
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(trace))
    _f, ed, _en = _load()
    adapters = {"anthropic": _mock(FINDING_JSON, model="claude-x"),
                "openai": _mock("", ok=False)}
    ed.dispatch_cross_vendor("p", "foo", vendors=["anthropic", "openai"],
                             adapters=adapters, trace=True)
    recs = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
    b = [r for r in recs if r.get("layer") == "B"]
    assert len(b) == 2
    by_model = {r.get("model_version"): r for r in b}
    assert "claude-x" in by_model and by_model["claude-x"]["verdict"] == "DISPATCHED"
    assert any(r["verdict"] == "VENDOR_UNAVAILABLE" for r in b)
