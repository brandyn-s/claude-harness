"""Unit tests for healthcheck/references/_check_routing.py.

Pins the null-handling fix. Each skill-rules.json rule carries BOTH `skill`
and `agent` keys with one set to null; an earlier inline version treated
`"skill": null` as a reference to a skill dir named "None" and reported 85
phantom dead refs (2026-06-16). A null/empty value must NOT be a dead ref.
"""
import json
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_routing",
    Path(__file__).resolve().parent.parent / "references" / "_check_routing.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def _setup(tmp_path, rules, skills=(), agents=()):
    """Build a fake ~/.claude with skill-rules.json + skills/ + agents/ and
    point the helper's module constants at it."""
    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    (claude / "skills").mkdir()
    (claude / "agents").mkdir()
    for s in skills:
        (claude / "skills" / s).mkdir()
    for a in agents:
        (claude / "agents" / f"{a}.md").write_text("x", encoding="utf-8")
    rules_path = claude / "hooks" / "skill-rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    return claude, rules_path


def _run(monkeypatch, tmp_path, rules, capsys, skills=(), agents=()):
    claude, rules_path = _setup(tmp_path, rules, skills, agents)
    monkeypatch.setattr(hc, "H", str(claude))
    monkeypatch.setattr(hc, "RULES_PATH", str(rules_path))
    rc = hc.main()
    return rc, capsys.readouterr().out


def test_null_skill_and_agent_are_not_dead_refs(tmp_path, monkeypatch, capsys):
    # THE BUG: one of skill/agent is null per rule. Null must be ignored.
    rules = {
        "skip_patterns": [],
        "rules": [
            {"pattern": "a", "skill": "realskill", "agent": None, "priority": 1},
            {"pattern": "b", "skill": None, "agent": "realagent", "priority": 1},
        ],
    }
    rc, out = _run(monkeypatch, tmp_path, rules, capsys,
                   skills=["realskill"], agents=["realagent"])
    assert rc == 0, f"expected PASS, got rc={rc}\n{out}"
    assert "PASS" in out
    assert "None" not in out  # never resolve a dir/file literally named "None"


def test_real_dead_skill_ref_flagged(tmp_path, monkeypatch, capsys):
    rules = {"skip_patterns": [],
             "rules": [{"pattern": "a", "skill": "ghostskill", "agent": None}]}
    rc, out = _run(monkeypatch, tmp_path, rules, capsys)  # no skills created
    assert rc == 1
    assert "dead skill ref: ghostskill" in out


def test_real_dead_agent_ref_flagged(tmp_path, monkeypatch, capsys):
    rules = {"skip_patterns": [],
             "rules": [{"pattern": "a", "skill": None, "agent": "ghostagent"}]}
    rc, out = _run(monkeypatch, tmp_path, rules, capsys)  # no agents created
    assert rc == 1
    assert "dead agent ref: ghostagent" in out


def test_duplicate_pattern_flagged(tmp_path, monkeypatch, capsys):
    rules = {"skip_patterns": [], "rules": [
        {"pattern": "dup", "skill": "s", "agent": None},
        {"pattern": "dup", "skill": "s", "agent": None},
    ]}
    rc, out = _run(monkeypatch, tmp_path, rules, capsys, skills=["s"])
    assert rc == 1
    assert "duplicate pattern" in out


def test_legacy_bare_array_is_structure_fail(tmp_path, monkeypatch, capsys):
    rc, out = _run(monkeypatch, tmp_path, [{"pattern": "x"}], capsys)
    assert rc == 1
    assert "FAIL" in out and "expected dict" in out
