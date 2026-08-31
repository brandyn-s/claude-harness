"""Unit tests for the --surface-map Phase-2 surface helper.

Locks the deterministic tier/category logic AND the artifact-prevention
invariant: bare ``` fences are NOT counted as bash blocks (only explicit
```bash/```sh/```shell/```zsh), so a prose skill with many bare fences is
not mis-tiered "deep". Regression guard for the 2026-06-16 build where the
bare-fence-inclusive counter over-counted api-preflight 11x (1 real ```bash
block, but 11 bare/markdown fences) and flipped 17 prose skills to "deep".
"""

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPO / "bin" / "audit-skill.py"


def _load_audit_module():
    if "audit_skill" in sys.modules:
        return sys.modules["audit_skill"]
    spec = importlib.util.spec_from_file_location("audit_skill", AUDIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["audit_skill"] = mod
    return mod


def _make_skill(root, name, skill_md, scripts=None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md, encoding="utf-8")
    for rel, body in (scripts or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return d


def test_bare_fences_not_counted_as_bash(tmp_path, monkeypatch):
    """ONE ```bash block + several bare ``` blocks => bash_block_count == 1."""
    audit = _load_audit_module()
    md = (
        "# x\n\n```bash\necho hi\n```\n\n"
        "```\njust output, not a command\n```\n\n"
        "```\nascii diagram\n```\n\n"
        "```json\n{}\n```\n"
    )
    _make_skill(tmp_path, "prose-skill", md)
    monkeypatch.setattr(audit, "SKILLS", tmp_path)
    s = audit._skill_surface("prose-skill")
    assert s["bash_block_count"] == 1, s
    assert s["has_scripts"] is False
    assert s["tier"] == "light"
    assert s["categories"]["A1"] == "applicable"      # >=1 bash block
    assert s["categories"]["B"].startswith("n-a")      # no CLI
    assert s["categories"]["D1"].startswith("n-a")     # no scripts
    assert s["categories"]["A3"] == "review"           # prose-claim dependent


def test_script_skill_is_deep_with_cli(tmp_path, monkeypatch):
    audit = _load_audit_module()
    md = "# y\n\nno fences here\n"
    scripts = {"scripts/run.py": "import sys\nif __name__ == '__main__':\n    print('hi')\n"}
    _make_skill(tmp_path, "tool-skill", md, scripts)
    monkeypatch.setattr(audit, "SKILLS", tmp_path)
    s = audit._skill_surface("tool-skill")
    assert s["has_scripts"] is True
    assert s["has_cli"] is True                        # __main__ present
    assert s["tier"] == "deep"                         # has scripts
    assert s["categories"]["B"] == "applicable"
    assert s["categories"]["D1"] == "applicable"
    assert s["categories"]["A1"].startswith("n-a")     # no bash blocks


def test_test_files_excluded_from_scripts(tmp_path, monkeypatch):
    """A skill whose only .py lives under tests/ has no real script surface."""
    audit = _load_audit_module()
    scripts = {"tests/test_thing.py": "def test_x():\n    assert True\n"}
    _make_skill(tmp_path, "test-only", "# prose\n", scripts)
    monkeypatch.setattr(audit, "SKILLS", tmp_path)
    s = audit._skill_surface("test-only")
    assert s["has_scripts"] is False, s
    assert s["tier"] == "light"


def test_five_bash_blocks_is_deep_boundary(tmp_path, monkeypatch):
    """Boundary: >=5 explicit shell fences => deep even without scripts."""
    audit = _load_audit_module()
    md = "# z\n" + ("\n```bash\necho x\n```\n" * 5)
    _make_skill(tmp_path, "command-heavy", md)
    monkeypatch.setattr(audit, "SKILLS", tmp_path)
    s = audit._skill_surface("command-heavy")
    assert s["bash_block_count"] == 5
    assert s["has_scripts"] is False
    assert s["tier"] == "deep"                         # boundary: == 5 -> deep


def test_four_bash_blocks_is_light_boundary(tmp_path, monkeypatch):
    """Boundary: 4 explicit shell fences, no scripts => light (off-by-one guard)."""
    audit = _load_audit_module()
    md = "# z\n" + ("\n```sh\necho x\n```\n" * 4)
    _make_skill(tmp_path, "almost-heavy", md)
    monkeypatch.setattr(audit, "SKILLS", tmp_path)
    s = audit._skill_surface("almost-heavy")
    assert s["bash_block_count"] == 4
    assert s["tier"] == "light"                        # boundary: 4 -> light


def test_references_drive_d4_applicability(tmp_path, monkeypatch):
    audit = _load_audit_module()
    d = _make_skill(tmp_path, "ref-skill", "# prose\n")
    (d / "references").mkdir()
    (d / "references" / "guide.md").write_text("ref\n", encoding="utf-8")
    monkeypatch.setattr(audit, "SKILLS", tmp_path)
    s = audit._skill_surface("ref-skill")
    assert s["references_count"] == 1
    assert s["categories"]["D4"] == "applicable"


def test_render_surface_map_summary(tmp_path, monkeypatch):
    audit = _load_audit_module()
    _make_skill(tmp_path, "a-deep", ("```bash\nx\n```\n" * 5))
    _make_skill(tmp_path, "b-light", "# prose only\n")
    monkeypatch.setattr(audit, "SKILLS", tmp_path)
    out = json.loads(audit._render_surface_map(["a-deep", "b-light"]))
    assert out["summary"] == {"total": 2, "deep": 1, "light": 1}
    names = {s["skill"]: s["tier"] for s in out["skills"]}
    assert names == {"a-deep": "deep", "b-light": "light"}
