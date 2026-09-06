#!/usr/bin/env python3
"""bin/lean-core-ab.py: arms, switching, and the fixed decision rule, offline."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "lean-core-ab.py"
_spec = importlib.util.spec_from_file_location("lean_core_ab", TOOL)
ab = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ab
_spec.loader.exec_module(ab)

UTC = dt.timezone.utc


def _rules(tmp_path: Path) -> Path:
    cdir = tmp_path / "claude"
    rules = cdir / "rules"
    (rules / "incidents").mkdir(parents=True)
    (rules / "incidents" / "x.md").write_text("# incident\n", encoding="utf-8")
    for name in ab.LEAN_KEEP[:4]:
        (rules / name).write_text(f"# {name}\n\ncontract text\n", encoding="utf-8")
    (rules / "grading-discipline.md").write_text("# grading\n" + "x" * 500, encoding="utf-8")
    (rules / "tdd-quality.md").write_text("---\npaths:\n  - 'tests/**'\n---\n# tdd\n", encoding="utf-8")
    return cdir


def test_build_lean_keeps_the_keep_list_and_path_scoped_rules(tmp_path):
    cdir = _rules(tmp_path)
    res = ab.build_lean(cdir)
    lean = cdir / "rules.lean"
    assert sorted(res["kept"]) == sorted(ab.LEAN_KEEP[:4])
    assert res["dropped_from_ambient"] == ["grading-discipline.md"]
    assert res["path_scoped"] == ["tdd-quality.md"]
    assert (lean / "tdd-quality.md").exists() and not (lean / "grading-discipline.md").exists()
    assert (lean / "incidents" / "x.md").exists(), "subtrees that are not loaded ambiently travel unchanged"
    assert res["ambient_bytes_lean"] < res["ambient_bytes_full"]
    assert set(res["missing_keepers"]) == set(ab.LEAN_KEEP[4:])


def test_switch_preserves_the_live_set_and_alternates(tmp_path):
    cdir = _rules(tmp_path)
    ab.build_lean(cdir)
    t0 = dt.datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    res = ab.switch(cdir, "B", now=t0)
    rules = cdir / "rules"
    assert rules.is_symlink() and rules.resolve() == (cdir / "rules.lean").resolve()
    assert (cdir / "rules.full" / "grading-discipline.md").exists(), "the first switch preserves the live set as rules.full"
    assert (cdir / "run" / "rules-arm.env").read_text(encoding="utf-8") == "CLAUDE_RULES_ARM=B\n"
    ab.switch(cdir, "a", now=t0 + dt.timedelta(days=1))
    assert rules.resolve() == (cdir / "rules.full").resolve()
    log = ab.load_arm_log(cdir)
    assert [r["arm"] for r in log] == ["B", "A"]
    assert ab.arm_for(t0 + dt.timedelta(hours=3), log) == "B"
    assert ab.arm_for(t0 + dt.timedelta(days=1, hours=3), log) == "A"
    assert ab.arm_for(t0 - dt.timedelta(hours=1), log) is None
    assert res["arm"] == "B"


def test_switch_refuses_without_a_lean_arm(tmp_path):
    cdir = _rules(tmp_path)
    try:
        ab.switch(cdir, "B")
    except SystemExit as exc:
        assert "build-lean" in str(exc)
    else:
        raise AssertionError("switch without rules.lean must refuse")


def _metrics(sessions_a, sessions_b, p1a, p1b, p2a, p2b, s1a, s1b, days=6):
    def arm(n, p1, p2, s1):
        return {"sessions": n, "arm_days": days, "flagged_model_sessions": 0,
                "P1_completion_evidence_rate_pct": p1, "P2_corrections_per_100_prompts": p2,
                "S1_safety_blocks_per_100_bash": s1, "S2_actions_per_prompt": 4.0,
                "S3_compactions_per_session": 1.0, "S5_abandonment_pct": 10.0, "_counts": {}}
    return {"A": arm(sessions_a, p1a, p2a, s1a), "B": arm(sessions_b, p1b, p2b, s1b)}


def test_decision_rule_is_the_pre_registered_one():
    assert ab.decide(_metrics(20, 20, 80, 76, 5.0, 5.9, 2.0, 2.3))["decision"] == "ADOPT"        # within every margin
    v = ab.decide(_metrics(20, 20, 80, 74, 5.0, 5.0, 2.0, 2.0))
    assert v["decision"] == "BISECT" and v["failing"] == ["1 P1(B) >= P1(A) - 5"]
    assert [s["family"] for s in v["order"]] == ["verification", "epistemics", "security-search"]
    assert ab.decide(_metrics(20, 20, 80, 80, 5.0, 6.1, 2.0, 2.0))["decision"] == "BISECT"     # corrections > 1.2x
    assert ab.decide(_metrics(20, 20, 80, 80, 5.0, 5.0, 2.0, 2.5))["decision"] == "BISECT"     # safety blocks > 1.2x
    assert ab.decide(_metrics(20, 12, 80, 80, 5.0, 5.0, 2.0, 2.0))["decision"] == "INSUFFICIENT DATA"
    assert ab.decide(_metrics(20, 20, 80, 80, 5.0, 5.0, 2.0, 2.0, days=4))["decision"] == "INSUFFICIENT DATA"


def test_payoff_is_recorded_when_a_secondary_metric_moves_15_percent():
    m = _metrics(20, 20, 80, 80, 5.0, 5.0, 2.0, 2.0)
    m["B"]["S3_compactions_per_session"] = 0.8
    v = ab.decide(m)
    assert v["decision"] == "ADOPT" and v["payoff"] == ["S3_compactions_per_session"]


def test_report_assigns_sessions_and_fires_by_arm_day(tmp_path):
    cdir = _rules(tmp_path)
    ab.build_lean(cdir)
    day1 = dt.datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
    ab.switch(cdir, "A", now=day1)
    ab.switch(cdir, "B", now=day1 + dt.timedelta(days=1))
    receipts = cdir / "session-end-receipts"
    receipts.mkdir()
    transcripts = tmp_path / "t"
    transcripts.mkdir()

    def transcript(name, corrected: bool):
        p = transcripts / f"{name}.jsonl"
        rows = [
            {"type": "user", "timestamp": "2026-09-07T09:00:00Z", "message": {"role": "user", "content": "please do the thing"}},
            {"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-5", "content": [
                {"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done: 12 passed in tests/test_x.py"}]}},
        ]
        if corrected:
            rows.append({"type": "user", "message": {"role": "user", "content": "No, that's not what I asked"}})
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return p

    for i, (day, corrected) in enumerate([(day1, False), (day1, True), (day1 + dt.timedelta(days=1), False)]):
        tp = transcript(f"s{i}", corrected)
        text = tp.read_text(encoding="utf-8").replace("2026-09-07T09:00:00Z", (day + dt.timedelta(hours=2)).isoformat())
        tp.write_text(text, encoding="utf-8")
        (receipts / f"s{i}.json").write_text(json.dumps({
            "session_id": f"s{i}", "transcript_path": str(tp), "ended_at": (day + dt.timedelta(hours=3)).isoformat(),
            "runtime_provenance": {"session_start_model": "claude-opus-5"}}), encoding="utf-8")
    (cdir / "run" / "compaction-budget").mkdir(parents=True, exist_ok=True)
    (cdir / "run" / "compaction-budget" / "s2.json").write_text(json.dumps({"count": 2}), encoding="utf-8")
    fires = cdir / "audit" / "hook-fires-20260907.jsonl"
    fires.write_text("\n".join(json.dumps(r) for r in [
        {"ts": (day1 + dt.timedelta(hours=1)).isoformat(), "hook": "bash-pretooluse-dispatcher.py", "exit": 0},
        {"ts": (day1 + dt.timedelta(hours=1)).isoformat(), "hook": "bash-pretooluse-dispatcher.py", "exit": 2},
        {"ts": (day1 + dt.timedelta(hours=1)).isoformat(), "hook": "bash-security-guard.py", "exit": 2},
    ]) + "\n", encoding="utf-8")
    rep = ab.build_report(cdir, None)
    a, b = rep["arms"]["A"], rep["arms"]["B"]
    assert a["sessions"] == 2 and b["sessions"] == 1
    assert a["P2_corrections_per_100_prompts"] == 33.33 and b["P2_corrections_per_100_prompts"] == 0.0   # 1 correction in 3 prompts
    assert a["P1_completion_evidence_rate_pct"] == 100.0
    assert a["S1_safety_blocks_per_100_bash"] == 50.0 and b["S1_safety_blocks_per_100_bash"] is None
    assert b["S3_compactions_per_session"] == 2.0
    assert rep["verdict"]["decision"] == "INSUFFICIENT DATA"
    text = ab.render_report(rep)
    assert "verdict: INSUFFICIENT DATA" in text and "please do the thing" not in text


def test_retro_reads_transcripts_directly_and_joins_rule_bytes(tmp_path):
    import subprocess
    root = tmp_path / "backup" / "proj"
    root.mkdir(parents=True)

    def write(name, day, model, corrected, blocked, compact):
        rows = [
            {"type": "user", "sessionId": name, "timestamp": f"{day}T09:00:00Z", "version": "2.1.260",
             "message": {"role": "user", "content": "please do the thing"}},
            {"type": "assistant", "message": {"role": "assistant", "model": model, "content": [
                {"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "[credential-guard] BLOCKED: no" if blocked else "ok"}]}},
            {"type": "assistant", "message": {"role": "assistant", "model": model, "content": [
                {"type": "text", "text": "Done: 3 passed in tests/test_x.py"}]}},
        ]
        if compact:
            rows.append({"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": "summary"}})
        if corrected:
            rows.append({"type": "user", "message": {"role": "user", "content": "No, that's not what I asked"}})
        (root / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    write("s1", "2026-08-20", "claude-opus-5", corrected=True, blocked=True, compact=False)
    write("s2", "2026-08-21", "claude-opus-5", corrected=False, blocked=False, compact=True)
    write("s3", "2026-09-04", "claude-fable-5-1", corrected=False, blocked=False, compact=False)
    # a sidechain file must not count as a session
    (root / "agent.jsonl").write_text(json.dumps({"type": "user", "isSidechain": True, "timestamp": "2026-09-04T10:00:00Z",
                                                  "message": {"role": "user", "content": "sub"}}) + "\n", encoding="utf-8")
    # a configuration clone whose rules shrink on 2026-09-03
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.x")
    git = lambda *a, **kw: subprocess.run(["git", "-C", str(cfg), *a], check=True, capture_output=True, env={**env, **kw})  # noqa: E731
    git("init", "-q", "-b", "main")
    (cfg / "rules").mkdir()
    (cfg / "rules" / "big.md").write_text("# big\n" + "x" * 1000, encoding="utf-8")
    (cfg / "rules" / "scoped.md").write_text("---\npaths:\n  - 'a/**'\n---\n" + "y" * 5000, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "full", GIT_AUTHOR_DATE="2026-08-01T12:00:00Z", GIT_COMMITTER_DATE="2026-08-01T12:00:00Z")
    (cfg / "rules" / "big.md").write_text("# big\n" + "x" * 100, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "trim", GIT_AUTHOR_DATE="2026-09-03T12:00:00Z", GIT_COMMITTER_DATE="2026-09-03T12:00:00Z")

    r = ab.retro(tmp_path / "backup", dt.datetime(2026, 9, 3, tzinfo=UTC), cfg, None)
    assert r["sessions"] == 3
    assert set(r["by_model"]) == {"claude-opus-5", "claude-fable-5-1"}
    assert r["all"]["S1_safety_blocks_per_100_bash"] == round(100 / 3, 2)
    assert r["all"]["S3_compactions_per_session"] == round(1 / 3, 2)
    assert r["split"]["before"]["sessions"] == 2 and r["split"]["after"]["sessions"] == 1
    assert r["split"]["before"]["P2_corrections_per_100_prompts"] == round(100 / 3, 2)
    assert r["ambient_bytes_by_day"]["2026-08-20"] == 1006 and r["ambient_bytes_by_day"]["2026-09-04"] == 106
    ranges = [b["ambient_bytes_range"] for b in r["by_ambient_bytes"]]
    assert ranges == [[106, 106], [1006, 1006]]
    assert r["split"]["decision_rule_applied_observationally"]["decision"] == "INSUFFICIENT DATA"
    text = ab.render_retro(r)
    assert "OBSERVATIONAL" in text and "please do the thing" not in text
    plan_only = ab.retro(tmp_path / "backup", None, None, None, plan_models_only=True)
    assert plan_only["sessions"] == 3
