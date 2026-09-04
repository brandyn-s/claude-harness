"""Deterministic tests for bin/skill-trigger-faithful.py (no claude binary, no network).

Covers the stream parser on a synthetic stream and on a saved real stream
(scripts/fixtures/skill-trigger-faithful-stream.jsonl, one `claude -p` session
recorded 2026-09-04 with long text blocks shortened), the sample-selection rule,
the isolation flags of the command line, the environment scrubbing, the dry-run
path (nothing may be executed) and the proxy-vs-faithful summary math.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "scripts" / "fixtures" / "skill-trigger-faithful-stream.jsonl"


def _load():
    spec = importlib.util.spec_from_file_location("skill_trigger_faithful", REPO / "bin" / "skill-trigger-faithful.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stf = _load()


# --------------------------------------------------------------------------- parser

def _synthetic_stream(skill_input: dict, hook: bool = False, subtype: str = "success") -> list[str]:
    events = [
        {"type": "system", "subtype": "init", "model": "claude-fable-5-1", "permissionMode": "plan",
         "claude_code_version": "2.1.260", "apiKeySource": "/login managed key", "tools": ["Read", "Skill", "Grep"],
         "slash_commands": ["capture", "codeql", "compact"], "skills": ["capture", "codeql"], "mcp_servers": [],
         "agents": ["Explore"], "plugins": []},
        {"type": "system", "subtype": "thinking_tokens", "tokens": 12},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Let me use the skill."},
            {"type": "tool_use", "id": "toolu_1", "name": "Skill", "input": skill_input}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                                                   "content": "skill loaded"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Read", "input": {"file_path": "/x"}}]}},
        {"type": "result", "subtype": subtype, "is_error": subtype != "success", "num_turns": 2, "duration_ms": 9000,
         "total_cost_usd": 0.31, "stop_reason": "end_turn", "permission_denials": []},
    ]
    if hook:
        events.insert(1, {"type": "system", "subtype": "hook_started", "hook_event": "UserPromptSubmit",
                          "hook_name": "x.py"})
    lines = [json.dumps(e) for e in events]
    lines.insert(2, "")                    # blank line
    lines.insert(3, "not json at all")     # a stray non-JSON line must be counted, not fatal
    return lines


def test_parse_stream_finds_the_skill_tool_use_and_the_result():
    parsed = stf.parse_stream(_synthetic_stream({"skill": "capture", "args": ""}))
    assert parsed["skill_calls"] == ["capture"]
    assert parsed["tool_calls"] == ["Skill", "Read"]
    assert parsed["hook_events"] == []
    assert parsed["init"]["permissionMode"] == "plan" and "Skill" in parsed["init"]["tools"]
    assert parsed["init"]["skills"] == ["capture", "codeql"]
    assert parsed["result"]["subtype"] == "success" and parsed["result"]["total_cost_usd"] == 0.31
    assert parsed["malformed"] == 1 and parsed["events"] == 6


def test_parse_stream_counts_hook_events_and_normalizes_skill_names():
    parsed = stf.parse_stream(_synthetic_stream({"command": "/codeql --full"}, hook=True))
    assert parsed["skill_calls"] == ["codeql"]
    assert parsed["hook_events"] == [{"subtype": "hook_started", "hook_event": "UserPromptSubmit", "hook_name": "x.py"}]
    assert stf.normalize_skill({"skill": "superpowers:brainstorming"}) == "brainstorming"
    assert stf.normalize_skill({"skill": "/capture some args"}) == "capture"
    assert stf.normalize_skill({}) == ""


def test_run_failed_treats_max_turns_as_a_completed_run():
    assert not stf.run_failed({"result": {"subtype": "success"}})
    assert not stf.run_failed({"result": {"subtype": "error_max_turns"}})
    assert stf.run_failed({"result": {"subtype": "error_during_execution"}})
    assert stf.run_failed({"result": None})


@pytest.mark.skipif(not FIXTURE.exists(), reason="saved stream fixture not present")
def test_parse_saved_real_stream():
    parsed = stf.parse_stream(FIXTURE.read_text(encoding="utf-8").splitlines())
    assert parsed["init"] is not None
    assert parsed["init"]["permissionMode"] == "plan"
    assert parsed["init"]["claude_code_version"] == "2.1.260"
    assert parsed["init"]["mcp_servers"] == 0 and parsed["init"]["plugins"] == 0
    assert "Skill" in parsed["init"]["tools"]
    assert parsed["hook_events"] == [], "user-level hooks must not have fired"
    assert parsed["result"]["subtype"] in stf.OK_RESULT_SUBTYPES
    assert parsed["skill_calls"] == ["codeql"]
    assert "codeql" in parsed["init"]["skills"]
    assert parsed["malformed"] == 0


# --------------------------------------------------------------------------- sample

PER_SKILL = {
    "zeta": {"recall": 0.0, "hits": 0, "captured": 1},        # hidden below -> excluded
    "alpha": {"recall": 1 / 3, "hits": 1, "captured": 0},
    "beta": {"recall": 2 / 3, "hits": 2, "captured": 0},
    "gamma": {"recall": 2 / 3, "hits": 2, "captured": 0},
    "delta": {"recall": 1.0, "hits": 3, "captured": 1},       # perfect but captured others -> not "strong"
    "eps": {"recall": 1.0, "hits": 3, "captured": 0},
    "kappa": {"recall": 1.0, "hits": 3, "captured": 0},
    "mu": {"recall": 1.0, "hits": 3, "captured": 0},
    "omega": {"recall": 1.0, "hits": 3, "captured": 0},
    "rho": {"recall": 1.0, "hits": 3, "captured": 0},
}


def test_select_sample_is_deterministic_excludes_hidden_and_spreads_strong_picks():
    visible = set(PER_SKILL) - {"zeta"}
    sample = stf.select_sample(PER_SKILL, visible, weakest=3, strong=3, source="r.json")
    assert sample["weakest"] == ["alpha", "beta", "gamma"]          # recall asc, then hits, then name
    assert sample["strong"] == ["eps", "mu", "rho"]                 # first, middle, last of the clean list
    assert sample["excluded_not_visible"] == ["zeta"]
    assert sample == stf.select_sample(PER_SKILL, visible, weakest=3, strong=3, source="r.json")
    assert "r.json" in sample["rule"]
    everything = stf.select_sample(PER_SKILL, visible, weakest=2, strong=10)
    assert everything["strong"] == ["eps", "kappa", "mu", "omega", "rho"]


# --------------------------------------------------------------------------- command

def test_build_command_carries_the_isolation_flags():
    cmd = stf.build_command("/usr/local/bin/claude", "Scan this repo", "claude-fable-5-1", 2, 3.0)
    assert cmd[:3] == ["/usr/local/bin/claude", "-p", "Scan this repo"]
    joined = " ".join(cmd)
    for flag in ("--output-format stream-json", "--verbose", "--max-turns 2", "--permission-mode plan",
                 "--setting-sources project", "--no-session-persistence", "--strict-mcp-config",
                 "--include-hook-events", "--model claude-fable-5-1", "--max-budget-usd 3.00"):
        assert flag in joined, flag
    with pytest.raises(ValueError):
        stf.build_command("claude", "--not-a-request", "m", 2, 1.0)


def test_subprocess_env_removes_api_credentials_only():
    env = stf.subprocess_env({"ANTHROPIC_API_KEY": "sk-secret", "ANTHROPIC_AUTH_TOKEN": "t", "PATH": "/bin", "HOME": "/h"})
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == "/bin" and env["HOME"] == "/h"


# --------------------------------------------------------------------------- dry run

def _results_with_report(names: list[str], hits: dict[str, int], answers: dict[str, str] | None = None) -> dict:
    routes = []
    for name in names:
        for n in range(1, 4):
            item_id = f"{name}-{n}"
            answer = (answers or {}).get(item_id, name if n <= hits.get(name, 3) else "none")
            routes.append({"id": item_id, "request": f"please {name} {n}", "expected": name, "kind": "positive",
                           "answer": answer})
    per_skill = {name: {"positives": 3, "hits": hits.get(name, 3), "recall": hits.get(name, 3) / 3,
                        "to_none": 3 - hits.get(name, 3), "refused": 0, "captured": 0} for name in names}
    return {"meta": {"effort": "low", "skills": names}, "routes": routes, "report": {"per_skill": per_skill}}


@pytest.fixture
def eval_inputs(tmp_path):
    names = ["alpha", "beta", "gamma", "delta"]
    skills = tmp_path / "skills"
    for name in names:
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name} things\n---\n# {name}\n",
                                                encoding="utf-8")
    (skills / "hidden").mkdir()
    (skills / "hidden" / "SKILL.md").write_text("---\nname: hidden\ndescription: h\ndisable-model-invocation: true\n---\n",
                                                encoding="utf-8")
    results = _results_with_report(names + ["hidden"], {"alpha": 1, "beta": 2, "hidden": 0})
    results_path = tmp_path / "results-low.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    corpus = {"meta": {}, "items": [{"id": r["id"], "request": r["request"], "expected": r["expected"], "kind": "positive"}
                                    for r in results["routes"]]}
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    return {"skills": skills, "results": results_path, "corpus": corpus_path, "names": names}


def test_dry_run_prints_the_plan_and_executes_nothing(eval_inputs, tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise AssertionError("dry-run must not start a subprocess")

    monkeypatch.setattr(stf.subprocess, "run", boom)
    rc = stf.main(["--skills-dir", str(eval_inputs["skills"]), "run", "--dry-run", "--project", str(tmp_path / "proj"),
                   "--sample-from", str(eval_inputs["results"]), "--corpus", str(eval_inputs["corpus"]),
                   "--proxy", f"low={eval_inputs['results']}", "--weakest", "2", "--strong", "1",
                   "--claude-bin", "/nonexistent/claude"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True
    assert plan["sample"]["weakest"] == ["alpha", "beta"] and plan["sample"]["strong"] == ["delta"]
    assert plan["sample"]["excluded_not_visible"] == ["hidden"]
    assert [r["id"] for r in plan["runs"]] == ["alpha-1", "alpha-2", "alpha-3", "beta-1", "beta-2", "beta-3",
                                               "delta-1", "delta-2", "delta-3"]
    assert plan["runs"][0]["argv"][:3] == ["/nonexistent/claude", "-p", "please alpha 1"]
    assert not (tmp_path / "proj").exists(), "dry-run must not create the project directory"


def test_setup_project_symlinks_every_visible_skill_and_prunes_stale_links(eval_inputs, tmp_path):
    project = tmp_path / "proj"
    visible = [{"name": n} for n in eval_inputs["names"]]
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".claude" / "skills" / "stale").symlink_to(eval_inputs["skills"] / "alpha", target_is_directory=True)
    info = stf.setup_project(project, visible, eval_inputs["skills"])
    assert info["skills_linked"] == 4 and info["stale_links_removed"] == ["stale"]
    assert (project / ".claude" / "skills" / "beta" / "SKILL.md").read_text(encoding="utf-8").startswith("---")
    assert not (project / ".claude" / "skills" / "hidden").exists()
    assert info["settings_json_present"] is False and info["claude_md_present"] is False
    again = stf.setup_project(project, visible, eval_inputs["skills"])
    assert again["skills_linked"] == 4 and again["stale_links_removed"] == []


# --------------------------------------------------------------------------- summary

def _run(item_id, expected, skill_calls, failed=False):
    return {"id": item_id, "expected": expected, "request": item_id, "triggered": expected in skill_calls,
            "skill_calls": skill_calls, "failed": failed}


def test_summarize_builds_the_proxy_vs_faithful_table_and_agreement():
    sample = {"weakest": ["alpha", "beta"], "strong": ["delta"], "excluded_not_visible": [], "rule": "r"}
    low = _results_with_report(["alpha", "beta", "delta"], {"alpha": 1, "beta": 2})
    xhigh = _results_with_report(["alpha", "beta", "delta"], {"alpha": 2, "beta": 2},
                                 answers={"delta-3": "beta"})
    runs = [_run("alpha-1", "alpha", ["alpha"]), _run("alpha-2", "alpha", []), _run("alpha-3", "alpha", ["gamma"]),
            _run("beta-1", "beta", ["beta"]), _run("beta-2", "beta", ["beta"]), _run("beta-3", "beta", [], failed=True),
            _run("delta-1", "delta", ["delta"]), _run("delta-2", "delta", ["delta"]), _run("delta-3", "delta", ["delta"])]
    summary = stf.summarize(runs, sample, [{"label": "low", "results": low}, {"label": "xhigh", "results": xhigh}])
    assert summary["proxy_labels"] == ["low", "xhigh"]
    rows = {r["skill"]: r for r in summary["per_skill"]}
    assert rows["alpha"] == {"skill": "alpha", "group": "weakest", "positives": 3, "faithful_hits": 1, "failed_runs": 0,
                             "proxy_hits": {"low": 1, "xhigh": 2}, "other_skills_fired": ["gamma"]}
    assert rows["beta"]["faithful_hits"] == 2 and rows["beta"]["failed_runs"] == 1
    assert rows["delta"]["group"] == "strong" and rows["delta"]["faithful_hits"] == 3
    agree = summary["agreement"]
    # xhigh proxy: alpha-1,2 hit, alpha-3 miss; beta-1,2 hit, beta-3 miss; delta-1,2 hit, delta-3 miss (-> beta)
    assert agree == {"proxy_label": "xhigh", "n": 9, "both_hit": 5, "both_miss": 2, "proxy_only": 1,
                     "faithful_only": 1, "rate": pytest.approx(7 / 9, abs=1e-4)}
    assert [m["id"] for m in summary["misses"]] == ["alpha-2", "alpha-3", "beta-3"]
    assert summary["faithful_hits"] == 6 and summary["runs"] == 9


def test_parse_subcommand_prints_counts(tmp_path, capsys):
    stream = tmp_path / "s.jsonl"
    stream.write_text("\n".join(_synthetic_stream({"skill": "capture"})), encoding="utf-8")
    assert stf.main(["parse", str(stream)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["skill_calls"] == ["capture"] and out["init"]["tools"] == 3


def test_module_help_runs():
    proc = subprocess.run([sys.executable, str(REPO / "bin" / "skill-trigger-faithful.py"), "--help"],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0 and "Faithful trigger check" in proc.stdout
