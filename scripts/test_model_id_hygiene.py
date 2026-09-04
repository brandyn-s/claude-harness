"""Exact model ids do not belong in active guidance.

Prose that names `claude-opus-5` (or a dated snapshot such as
`claude-haiku-4-5-20251001`) goes stale at every rollover and reads as current when
it is not. Active surfaces -- skill bodies, rules, hooks, agents -- use moving
aliases or point at contracts/model-capabilities.json. Exact ids stay where they are
evidence (measurement harnesses, frozen results, contracts, run-history references)
or are allowlisted next to this test, one reason per entry.

Run as a script to list findings:  python3 scripts/test_model_id_hygiene.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "scripts" / "model_id_allowlist.json"

# claude-<family>-<n>[-<n>...][-YYYYMMDD]   e.g. claude-opus-5, claude-haiku-4-5-20251001
# claude-<n>[-<n>]-<family>-YYYYMMDD         e.g. claude-3-5-sonnet-20241022 (older form)
# `\b` keeps "claude-config-1834" (an incident slug) and "claude-hud" out.
EXACT_MODEL_ID = re.compile(
    r"claude-[a-z]+-\d{1,2}(?:-\d{1,2})*(?:-\d{8})?\b|claude-\d(?:-\d)?-[a-z]+-\d{8}\b"
)
# A measurement verdict citing the frozen run's model, e.g. "measured 2026-05-31, claude-opus-4-8".
MEASURED_LINE = re.compile(r"measured 2026-", re.IGNORECASE)
SCAN_GLOBS = ("skills/*/SKILL.md", "rules/**/*", "hooks/*.py", "agents/*.md")
GENERATED_BEGIN = "<!-- model-capabilities:begin -->"
GENERATED_END = "<!-- model-capabilities:end -->"
EVIDENCE_REFERENCE_STEMS = {"history", "run-history", "measured-efficacy"}


def allowed_by_construction(rel: str) -> bool:
    """Paths where exact ids are evidence, not guidance."""
    parts = PurePosixPath(rel).parts
    if parts[0] == "contracts":
        return True
    if parts[0] == "skills" and len(parts) > 2:
        if parts[2] == "harness":
            return True
        if parts[1] == "_shared" and any(p.endswith("-eval") for p in parts[2:-1]):
            return True
    return "references" in parts and PurePosixPath(rel).stem in EVIDENCE_REFERENCE_STEMS


def scannable_lines(rel: str, text: str):
    """(line_no, line) pairs that count: no frontmatter, no generated block, no measured verdicts."""
    lines = text.splitlines()
    in_frontmatter = rel.endswith("SKILL.md") and lines[:1] == ["---"]
    in_generated = False
    for number, line in enumerate(lines, start=1):
        if in_frontmatter:
            if number > 1 and line.strip() == "---":
                in_frontmatter = False
            continue
        if line.strip() == GENERATED_BEGIN:
            in_generated = True
            continue
        if line.strip() == GENERATED_END:
            in_generated = False
            continue
        if in_generated or MEASURED_LINE.search(line):
            continue
        yield number, line


def scan(root: Path) -> list[tuple[str, int, str]]:
    """Every (relative path, line, exact id) in the active surfaces under root."""
    findings = []
    for pattern in SCAN_GLOBS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if allowed_by_construction(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for number, line in scannable_lines(rel, text):
                for match in EXACT_MODEL_ID.finditer(line):
                    findings.append((rel, number, match.group(0)))
    return sorted(findings)


def load_allowlist(path: Path = ALLOWLIST) -> dict[str, dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    by_path = {}
    for entry in entries:
        assert {"path", "ids", "reason"} <= entry.keys(), entry
        assert entry["reason"].strip() and "\n" not in entry["reason"], entry["path"]
        assert entry["path"] not in by_path, f"duplicate allowlist entry {entry['path']}"
        by_path[entry["path"]] = entry
    return by_path


def violations(findings, allowlist) -> list[tuple[str, int, str]]:
    return [f for f in findings if f[2] not in set(allowlist.get(f[0], {}).get("ids", []))]


def test_active_surfaces_name_no_unallowlisted_exact_model_ids():
    found = violations(scan(ROOT), load_allowlist())
    assert not found, (
        "exact model ids in active guidance (use an alias, point at "
        "contracts/model-capabilities.json, or add a one-line reason to "
        "scripts/model_id_allowlist.json):\n" + "\n".join(f"  {p}:{n}: {m}" for p, n, m in found)
    )


def test_allowlist_entries_are_all_still_needed():
    """A stale entry is a hole: it would let the id back in silently."""
    present = {(rel, model_id) for rel, _, model_id in scan(ROOT)}
    for rel, entry in load_allowlist().items():
        assert (ROOT / rel).is_file(), f"allowlist names a missing file: {rel}"
        for model_id in entry["ids"]:
            assert (rel, model_id) in present, f"stale allowlist entry: {rel} no longer names {model_id}"


def test_pattern_matches_exact_ids_and_not_prose():
    for text in ("claude-opus-5", "claude-fable-5-1", "claude-haiku-4-5-20251001",
                 "us.anthropic.claude-fable-5[1m]", "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"):
        assert EXACT_MODEL_ID.search(text), text
    for text in ("claude-config-1834-find-session-pid", "claude-hud", "claude-review", "opus", "haiku",
                 "Claude Opus 5", "claude-api"):
        assert not EXACT_MODEL_ID.search(text), text


def test_known_positive_control_and_every_exemption(tmp_path):
    """A seeded id in a skill body is caught; frontmatter, the generated block,
    measured verdict lines, and evidence paths are not."""
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\nmodel: claude-opus-5\n---\n"
        "Body pins claude-sonnet-5 here.\n"
        f"{GENERATED_BEGIN}\n| Claude Opus 5 (`claude-opus-5`) |\n{GENERATED_END}\n"
        "Measured 2026-05-31, N=3, `claude-opus-4-8`: trim.\n",
        encoding="utf-8",
    )
    harness = tmp_path / "skills" / "demo" / "harness"
    harness.mkdir()
    (harness / "PROBLEM.md").write_text("claude-opus-4-8\n", encoding="utf-8")
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "x.md").write_text("Route heavy work to claude-fable-5.\n", encoding="utf-8")
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "h.py").write_text('MODEL = "claude-haiku-4-5-20251001"\n', encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a.md").write_text("---\nmodel: opus\n---\nUses the opus alias.\n", encoding="utf-8")

    findings = scan(tmp_path)

    assert findings == [
        ("hooks/h.py", 1, "claude-haiku-4-5-20251001"),
        ("rules/x.md", 1, "claude-fable-5"),
        ("skills/demo/SKILL.md", 5, "claude-sonnet-5"),
    ]
    allow = {"rules/x.md": {"ids": ["claude-fable-5"], "reason": "test"}}
    assert violations(findings, allow) == [
        ("hooks/h.py", 1, "claude-haiku-4-5-20251001"),
        ("skills/demo/SKILL.md", 5, "claude-sonnet-5"),
    ]
    for rel in ("contracts/model-capabilities.json", "skills/x/harness/run_live.py",
                "skills/_shared/description-eval/corpus.json", "skills/x/references/run-history.md",
                "skills/x/references/measured-efficacy.md"):
        assert allowed_by_construction(rel), rel
    for rel in ("skills/x/SKILL.md", "rules/y.md", "hooks/z.py", "agents/a.md",
                "skills/x/references/setup.md", "skills/_shared/model-runtime-policy.md"):
        assert not allowed_by_construction(rel), rel


def main() -> int:
    found = violations(scan(ROOT), load_allowlist())
    for rel, number, model_id in found:
        print(f"{rel}:{number}: {model_id}")
    print(f"{len(found)} unallowlisted exact model id(s) in active surfaces")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
