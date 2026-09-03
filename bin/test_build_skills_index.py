#!/usr/bin/env python3
"""skills/README.md claims to be generated from SKILL.md frontmatter. Prove it.

Measured 2026-09-03: no generator existed in the repo and one row was stale
(verification-before-completion's description predated its v2.0 rewrite). This
pins the index to a real generator so the claim in the file header is true.

Run: pytest bin/test_build_skills_index.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_skills_index", REPO / "bin" / "build-skills-index.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skills_index_matches_generated_output():
    module = _load()
    expected = module.render(REPO)
    actual = (REPO / "skills" / "README.md").read_text(encoding="utf-8")
    assert actual == expected, "skills/README.md is stale; run bin/build-skills-index.py"


def test_generator_reads_every_skill(tmp_path):
    """Known-positive: a fixture with two skills yields two rows with the right flags."""
    module = _load()
    for name, extras in (("alpha", ("references",)), ("beta", ("scripts", "tests"))):
        d = tmp_path / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Does {name} things.\n---\nbody\n", encoding="utf-8"
        )
        for extra in extras:
            (d / extra).mkdir()
    out = module.render(tmp_path)
    assert "2 skills." in out
    assert "| [`alpha`](./alpha/SKILL.md) | Does alpha things. | references |" in out
    assert "| [`beta`](./beta/SKILL.md) | Does beta things. | scripts, tests |" in out
