"""Golden-fixture tests for the offline guardrail scanner and reporter.

Pins the behaviors the 2026-07-05 roundtable red-team
surfaced, so a future edit can't silently regress recall, egress deny-by-default,
dedup, or the freshness guard.

Run: pytest bin/test_guardrail.py -q   (wired into .github/workflows/tests.yml (this export ships gitleaks.yml, plugins.yml, tests.yml; the upstream tests.yml is not part of it))

Secret-shaped fixture values are ASSEMBLED FROM FRAGMENTS at runtime so the
sanitizer matches them while no contiguous secret literal sits in this file
(gitleaks / push-protection stay clean) — per rules/security-review-before-pr.md.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN))

import guardrail_corpus as gc  # noqa: E402 -- resolves via the sys.path insert above
import guardrail_report as gr  # noqa: E402 -- resolves via the sys.path insert above

# ---- fragment-assembled secret-shaped values (no literal secret in source) ----
GH_TOKEN = "gh" + "p_" + "A0B1C2D3E4F5G6H7I8J9K"          # gh[pousr]_[A-Za-z0-9]{20,}
AWS_KEY = "AK" + "IA" + "WXYZ1234567890ABCD"              # A(?:KIA..)[0-9A-Z]{12,}
HOSTNAME = "mcp." + "example" + ".com"                    # *.example.com


def _row(**kw):
    kw.setdefault("timestamp", "2026-07-01T00:00:00.000Z")
    return json.dumps(kw)


def _transcript(tmp, rows, name="s.jsonl"):
    p = tmp / name
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(p)


def _user(text, ts="2026-07-01T00:00:00.000Z"):
    return _row(type="user", uuid=f"u{abs(hash(text)) % 99999}", timestamp=ts,
                message={"role": "user", "content": [{"type": "text", "text": text}]})


# ---------- A1: recall of the stop_reason=="refusal" shape ----------
def test_a1_stop_reason_refusal_captured(tmp_path):
    tp = _transcript(tmp_path, [
        _user("review the auth flow"),
        _row(type="assistant", uuid="a1", requestId="req_STOPONLY",
             message={"model": "claude-fable-5", "stop_reason": "refusal",
                      "stop_details": {"type": "refusal", "category": "bio",
                                       "explanation": "blocked"}}),
    ])
    ev = gc.scan_file(tp, None, {"model_safeguard", "auto_mode_classifier", "hook_guardrail"})
    ms = [e for e in ev if e["tier"] == "model_safeguard"]
    assert len(ms) == 1
    assert ms[0]["category"] == "bio"
    assert ms[0]["request_id"] == "req_STOPONLY"


# ---------- A1: fallback-row + stop_reason-row for one block collapse to one ----------
def test_a1_collapse_one_per_request(tmp_path):
    tp = _transcript(tmp_path, [
        _user("audit RLS policies"),
        _row(type="assistant", uuid="a1", requestId="req_DUP",
             message={"model": "claude-fable-5", "stop_reason": "refusal",
                      "stop_details": {"type": "refusal", "category": "cyber"}}),
        _row(type="system", subtype="model_refusal_fallback", uuid="sys1",
             requestId="req_DUP", apiRefusalCategory="cyber",
             originalModel="claude-fable-5", fallbackModel="claude-opus-4-8"),
    ])
    ev = gc.scan_file(tp, None, {"model_safeguard"})
    ms = [e for e in ev if e["tier"] == "model_safeguard"]
    assert len(ms) == 1, f"expected 1 collapsed event, got {len(ms)}"
    assert ms[0]["request_id"] == "req_DUP"
    assert ms[0]["category"] == "cyber"


# ---------- msg.id must NOT be stored as an appealable request_id ----------
def test_msgid_not_used_as_request_id(tmp_path):
    tp = _transcript(tmp_path, [
        _user("debug storage"),
        _row(type="assistant", uuid="a1", id="msg_SHOULD_NOT_APPEAR",
             message={"model": "claude-fable-5", "id": "msg_SHOULD_NOT_APPEAR",
                      "stop_reason": "refusal",
                      "stop_details": {"type": "refusal", "category": "cyber"}}),
    ])
    ev = gc.scan_file(tp, None, {"model_safeguard"})
    ms = [e for e in ev if e["tier"] == "model_safeguard"]
    assert len(ms) == 1
    assert ms[0]["request_id"] is None, "msg.id leaked into request_id"


# ---------- egress: deny-by-default omits prompt bodies (no secret leak) ----------
def _corpus_with_secret(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    e = {"tier": "model_safeguard", "session_id": "s1", "uuid": "u1",
         "timestamp": "2026-07-01T00:00:00.000Z", "category": "cyber",
         "request_id": "req_LEAKTEST", "active_model": "claude-fable-5",
         "fallback_model": "claude-opus-4-8", "turn_index": 3,
         "minutes_into_session": 10.0,
         "prompt_context": f"review creds {GH_TOKEN} {AWS_KEY} on {HOSTNAME}",
         "explanation": "blocked"}
    corpus.write_text(json.dumps(e) + "\n", encoding="utf-8")
    return corpus


def test_egress_deny_by_default(tmp_path):
    corpus = _corpus_with_secret(tmp_path)
    events = gr.load_corpus(str(corpus))
    gr.cvp_evidence(events, str(tmp_path), "ORG", include_context=False, redactions=[])
    gr.fp_report(events, str(tmp_path), "ORG", include_context=False, redactions=[],
                 categories={"cyber", "unspecified"})
    blob = (tmp_path / "cvp-evidence.md").read_text(encoding="utf-8") + \
           (tmp_path / "cvp-evidence.csv").read_text(encoding="utf-8") + \
           (tmp_path / "fp-reports.md").read_text(encoding="utf-8")
    for secret in (GH_TOKEN, AWS_KEY, HOSTNAME, "review creds"):
        assert secret not in blob, f"leaked {secret!r} in default (whitelist) output"
    assert "req_LEAKTEST" in blob  # request id is intended to appear


def test_include_context_redacts(tmp_path):
    corpus = _corpus_with_secret(tmp_path)
    events = gr.load_corpus(str(corpus))
    gr.cvp_evidence(events, str(tmp_path), "ORG", include_context=True, redactions=[])
    md = (tmp_path / "cvp-evidence.md").read_text(encoding="utf-8")
    assert GH_TOKEN not in md and AWS_KEY not in md and HOSTNAME not in md
    assert "[GITHUB_TOKEN]" in md and "[AWS_KEY]" in md and "[HOSTNAME]" in md


# ---------- reporter robustness ----------
def test_load_corpus_missing_file_no_crash(tmp_path):
    assert gr.load_corpus(str(tmp_path / "nope.jsonl")) == []


def test_since_excludes_undated(tmp_path):
    corpus = tmp_path / "c.jsonl"
    corpus.write_text("\n".join([
        json.dumps({"tier": "model_safeguard", "session_id": "s", "uuid": "1",
                    "timestamp": "2026-07-02T00:00:00Z", "request_id": "req_A"}),
        json.dumps({"tier": "model_safeguard", "session_id": "s", "uuid": "2",
                    "timestamp": None, "request_id": "req_B"}),  # undated
    ]) + "\n", encoding="utf-8")
    since = datetime.fromisoformat("2026-07-01").replace(tzinfo=timezone.utc)
    ev = gr.load_corpus(str(corpus), since_dt=since)
    ids = {e["request_id"] for e in ev}
    assert ids == {"req_A"}, f"undated row leaked into --since pack: {ids}"


# ---------- freshness: the corpus is now produced only by offline scans ----------
def test_freshness_uses_offline_corpus_mtime(tmp_path):
    corpus = tmp_path / "c.jsonl"
    assert "NEVER" in gr.freshness_warning(str(corpus))

    corpus.write_text("{}\n", encoding="utf-8")
    assert gr.freshness_warning(str(corpus)) is None

    stale = datetime.now(timezone.utc).timestamp() - 3 * 86400
    os.utime(corpus, (stale, stale))
    warning = gr.freshness_warning(str(corpus))
    assert warning is not None and "offline" in warning.lower()


# ---------- drift: weekly DROP flag is implemented (docstring no longer lies) ----------
def test_drift_drop_flag(tmp_path):
    rows = []
    # week A: 5 blocks; week B: 0 -> a DROP
    for i in range(5):
        rows.append({"tier": "model_safeguard", "session_id": "s", "uuid": f"a{i}",
                     "timestamp": f"2026-06-0{i+1}T00:00:00Z", "category": "cyber",
                     "request_id": f"req_a{i}", "active_model": "claude-fable-5"})
    # a later week with a single block far out to create the empty intervening week
    rows.append({"tier": "model_safeguard", "session_id": "s", "uuid": "z",
                 "timestamp": "2026-06-20T00:00:00Z", "category": "cyber",
                 "request_id": "req_z", "active_model": "claude-fable-5"})
    corpus = tmp_path / "c.jsonl"
    corpus.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    events = gr.load_corpus(str(corpus))
    gr.drift(events, str(tmp_path))
    txt = (tmp_path / "drift.md").read_text(encoding="utf-8")
    assert "DROP" in txt, "weekly DROP flag not emitted"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
