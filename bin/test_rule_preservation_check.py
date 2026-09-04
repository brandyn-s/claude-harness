"""Tests for bin/rule-preservation-check.py, the literal-preservation oracle.

Every test builds its own rule directory under tmp_path. The oracle's contract:
`extract` records the load-bearing literals of each rule; `verify` exits 1 naming
every recorded literal that no longer appears anywhere in the rule set. Moving text
between files or rewrapping it is not a loss; deleting it is.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent
SCRIPT = BIN / "rule-preservation-check.py"
_spec = importlib.util.spec_from_file_location("rule_preservation_check", SCRIPT)
assert _spec and _spec.loader
rpc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rpc)

RULE_A = """# Alpha Rule

This paragraph is ordinary prose that a reflow may
rewrap at a different column without changing meaning.

## Budget
NEVER exceed 38,000 bytes per file; the guard warns at 35,000 bytes.
Read `manifests/ambient-budget.json` and set CLAUDE_HOOK_TEST=1 before running.
See https://example.com/docs/rules for the contract.

```bash
python3 bin/preflight-skill.py --fast
```
"""

RULE_B = """# Beta Rule

- ALWAYS quote the heredoc delimiter.
- Wait at most 45 minutes before stopping.
"""


def _write_rules(root: Path, files: dict[str, str]) -> Path:
    rules = root / "rules"
    rules.mkdir(exist_ok=True)
    for name, text in files.items():
        (rules / name).write_text(text, encoding="utf-8")
    return rules


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, check=False)


# --------------------------------------------------------------------- extract

def test_extract_records_every_literal_class(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A, "beta.md": RULE_B})
    manifest = rpc.extract(rules)
    alpha = manifest["rules"]["alpha.md"]

    assert "Alpha Rule" in alpha["headings"]
    assert "Budget" in alpha["headings"]
    assert any(b.startswith("NEVER exceed 38,000 bytes") for b in alpha["banners"])
    assert "manifests/ambient-budget.json" in alpha["code"]
    assert "python3 bin/preflight-skill.py --fast" in alpha["code"]
    assert "CLAUDE_HOOK_TEST" in alpha["env_vars"]
    assert "manifests/ambient-budget.json" in alpha["paths"]
    assert "bin/preflight-skill.py" in alpha["paths"]
    assert "https://example.com/docs/rules" in alpha["urls"]
    assert "38,000 bytes" in alpha["numbers"]
    assert "35,000 bytes" in alpha["numbers"]

    beta = manifest["rules"]["beta.md"]
    assert any(b.startswith("ALWAYS quote") for b in beta["banners"])
    assert "45 minutes" in beta["numbers"]


def test_extract_skips_subdirectories_and_writes_json(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A})
    (rules / "incidents").mkdir()
    (rules / "incidents" / "alpha.md").write_text("# Not a rule\nNEVER read me.\n", encoding="utf-8")
    out = tmp_path / "manifest.json"
    proc = _run("extract", "--rules", str(rules), "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["rules"]) == {"alpha.md"}
    assert data["literal_count"] == sum(len(v) for kinds in data["rules"].values() for v in kinds.values())


# ---------------------------------------------------------------------- verify

def test_verify_passes_on_reflow_and_merge(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A, "beta.md": RULE_B})
    manifest = rpc.extract(rules)

    # Reflow alpha at a different column and merge beta into it, demoting its heading.
    reflowed = RULE_A.replace(
        "This paragraph is ordinary prose that a reflow may\nrewrap at a different column",
        "This paragraph is ordinary prose that a reflow may rewrap\nat a different column",
    ).replace("NEVER exceed 38,000 bytes per file; the guard warns at 35,000 bytes.",
              "NEVER exceed 38,000 bytes per file;\nthe guard warns at 35,000 bytes.")
    merged = reflowed + "\n" + RULE_B.replace("# Beta Rule", "## Beta Rule", 1)
    (rules / "alpha.md").write_text(merged, encoding="utf-8")
    (rules / "beta.md").unlink()

    lost = rpc.verify(rules, manifest)
    assert lost == [], lost


def test_verify_fails_naming_the_deleted_literal(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A, "beta.md": RULE_B})
    manifest_path = tmp_path / "manifest.json"
    assert _run("extract", "--rules", str(rules), "--out", str(manifest_path)).returncode == 0

    (rules / "beta.md").write_text("# Beta Rule\n\n- Wait at most 45 minutes before stopping.\n",
                                   encoding="utf-8")
    proc = _run("verify", "--rules", str(rules), "--manifest", str(manifest_path))
    assert proc.returncode == 1
    assert "ALWAYS quote the heredoc delimiter." in proc.stdout
    assert "beta.md" in proc.stdout
    # The surviving literal is not reported.
    assert "45 minutes" not in proc.stdout


def test_allow_drop_silences_a_named_literal_but_requires_a_reason(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A, "beta.md": RULE_B})
    manifest_path = tmp_path / "manifest.json"
    _run("extract", "--rules", str(rules), "--out", str(manifest_path))
    (rules / "beta.md").write_text("# Beta Rule\n\n- Wait at most 45 minutes before stopping.\n",
                                   encoding="utf-8")

    allow = tmp_path / "allow-drop.json"
    allow.write_text(json.dumps([
        {"literal": "ALWAYS quote the heredoc delimiter.", "reason": "enforced by post-write-edit.py"},
    ]), encoding="utf-8")
    proc = _run("verify", "--rules", str(rules), "--manifest", str(manifest_path),
                "--allow-drop", str(allow))
    assert proc.returncode == 0, proc.stdout + proc.stderr

    allow.write_text(json.dumps([{"literal": "ALWAYS quote the heredoc delimiter."}]),
                     encoding="utf-8")
    proc = _run("verify", "--rules", str(rules), "--manifest", str(manifest_path),
                "--allow-drop", str(allow))
    assert proc.returncode == 2
    assert "reason" in proc.stderr


def test_file_level_allow_drop_covers_a_deleted_rule_and_reports_the_count(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A, "beta.md": RULE_B})
    manifest_path = tmp_path / "manifest.json"
    _run("extract", "--rules", str(rules), "--out", str(manifest_path))
    (rules / "beta.md").unlink()

    proc = _run("verify", "--rules", str(rules), "--manifest", str(manifest_path))
    assert proc.returncode == 1 and "beta.md" in proc.stdout

    allow = tmp_path / "allow-drop.json"
    allow.write_text(json.dumps([{"file": "beta.md", "reason": "deleted per plan step 3"}]),
                     encoding="utf-8")
    proc = _run("verify", "--rules", str(rules), "--manifest", str(manifest_path),
                "--allow-drop", str(allow))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "dropped 3 literals from beta.md: deleted per plan step 3" in proc.stdout
    assert "LOST" not in proc.stdout

    allow.write_text(json.dumps([{"file": "beta.md"}]), encoding="utf-8")
    assert _run("verify", "--rules", str(rules), "--manifest", str(manifest_path),
                "--allow-drop", str(allow)).returncode == 2


def test_verify_counts_a_literal_relocated_to_an_also_path(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A, "beta.md": RULE_B})
    manifest = rpc.extract(rules)
    incidents = tmp_path / "incidents"
    incidents.mkdir()
    (incidents / "beta.md").write_text("## 2026-09-03\nALWAYS quote the heredoc delimiter.\n",
                                       encoding="utf-8")
    (rules / "beta.md").write_text("# Beta Rule\n\n- Wait at most 45 minutes before stopping.\n",
                                   encoding="utf-8")

    assert rpc.verify(rules, manifest) != []
    assert rpc.verify(rules, manifest, also=[incidents]) == []


def test_verify_rejects_a_manifest_for_a_different_layout(tmp_path):
    rules = _write_rules(tmp_path, {"alpha.md": RULE_A})
    proc = _run("verify", "--rules", str(rules), "--manifest", str(tmp_path / "missing.json"))
    assert proc.returncode == 2
