#!/usr/bin/env python3
"""bin/skill-usage-report.py: invocation counts from transcripts, listing cost, proposal."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "skill-usage-report.py"
_spec = importlib.util.spec_from_file_location("skill_usage_report", TOOL)
sur = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sur
_spec.loader.exec_module(sur)


def _skills(tmp_path: Path) -> Path:
    skills = tmp_path / "skills"
    for name, desc in (("gather-alpha", "Gather alpha things."), ("gather-beta", "Gather beta things."),
                       ("capture", "Record decisions."), ("mega-capture", "Record decisions for compacted sessions."),
                       ("lonely", "A standalone skill nobody calls."), ("frame", "Write INTENT.md.")):
        d = skills / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: \"{desc}\"\nwhen_to_use: 'Use when {name}.'\n---\n# {name}\n",
                                    encoding="utf-8")
    (skills / "_shared").mkdir()
    return skills


def _transcripts(tmp_path: Path) -> Path:
    root = tmp_path / "t" / "proj"
    root.mkdir(parents=True)
    rows1 = [
        {"type": "user", "timestamp": "2026-08-01T10:00:00Z", "message": {"role": "user", "content": "<command-name>/gather-alpha</command-name> go"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "frame", "args": ""}}]}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/gather-alpha</command-name> again"}},
    ]
    rows2 = [
        {"type": "user", "timestamp": "2026-06-01T10:00:00Z", "message": {"role": "user", "content": "<command-name>/capture</command-name>"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "not-a-skill"}}]}},
    ]
    (root / "a.jsonl").write_text("\n".join(json.dumps(r) for r in rows1) + "\n", encoding="utf-8")
    (root / "b.jsonl").write_text("\n".join(json.dumps(r) for r in rows2) + "\n", encoding="utf-8")
    return tmp_path / "t"


def test_counts_families_budget_and_proposal(tmp_path):
    skills = _skills(tmp_path)
    root = _transcripts(tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"skillOverrides": {"capture": "name-only"}}), encoding="utf-8")
    rep = sur.build(root, None, settings, skills)
    by = {r["skill"]: r for r in rep["skills"]}
    assert by["gather-alpha"]["slash"] == 2 and by["gather-alpha"]["sessions"] == 1 and by["gather-alpha"]["first"] == "2026-08-01"
    assert by["frame"]["auto"] == 1 and by["frame"]["family"] is None
    assert by["capture"]["slash"] == 1 and by["capture"]["name_only"] is True
    assert by["gather-beta"]["invocations"] == 0 and by["gather-beta"]["family"] == "gather"
    assert rep["unknown_skill_names_seen"] == ["not-a-skill"]
    assert rep["transcripts"] == 2 and rep["sessions_in_window"] == 2
    # proposal: zero-use family members, keeping the most-used member of each family
    assert rep["proposed_overrides"] == {"capture": "name-only", "gather-beta": "name-only", "mega-capture": "name-only"}
    assert rep["unused_standalone_skills"] == ["lonely"], "standalone skills are reported, not proposed"
    assert rep["budget"]["listing_after_proposal"] < rep["budget"]["listing_now"]
    assert rep["budget"]["tokens"] == 6000


def test_since_filters_by_the_transcripts_first_timestamp(tmp_path):
    skills = _skills(tmp_path)
    root = _transcripts(tmp_path)
    rep = sur.build(root, "2026-07-01", tmp_path / "nope.json", skills)
    by = {r["skill"]: r for r in rep["skills"]}
    assert rep["sessions_in_window"] == 1
    assert by["capture"]["invocations"] == 0 and by["gather-alpha"]["invocations"] == 2


def test_render_prints_no_transcript_text(tmp_path):
    skills = _skills(tmp_path)
    root = _transcripts(tmp_path)
    text = sur.render(sur.build(root, None, tmp_path / "nope.json", skills), propose=True)
    assert "gather-alpha" in text and '"skillOverrides"' in text and "listing budget 6,000 tokens" in text
    assert "again" not in text and "go" not in text.split("skill usage over")[1].split("\n")[0]


def test_roundtable_audit_is_a_front_over_this_tool(tmp_path):
    """skills/roundtable/skill-usage-audit.py must not count on its own."""
    import subprocess
    from pathlib import Path as _P
    repo = _P(__file__).resolve().parents[1]
    front = repo / "skills" / "roundtable" / "skill-usage-audit.py"
    src = front.read_text(encoding="utf-8")
    assert "skill-usage-report.py" in src and "re.compile" not in src, "the counting lives in bin/, once"
    skills = _skills(tmp_path)
    root = _transcripts(tmp_path)
    res = subprocess.run([sys.executable, str(front), "--root", str(root), "--skills", str(skills),
                          "--settings", str(tmp_path / "none.json")], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    assert "gather-alpha" in res.stdout and "ZERO" in res.stdout
    assert res.stdout.splitlines()[0].startswith("Scanned 2 transcripts. 3 slash + 1 Skill-tool = 4 total")
