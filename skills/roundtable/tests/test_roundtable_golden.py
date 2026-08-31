"""End-to-end golden tests for roundtable/harness.py.

Covers the May 2026 audit bug at harness.py round_2 convergence path:
the prior version computed prior_path as `round_{r-1}/main/{a}.md` for
all r >= 2, but round_1 writes directly to `round_1/{a}.md` (no main/
subdir). The fix special-cases r-1 == 1.

These tests reproduce the file-tree shape (without running adapters)
and assert the path-selection logic still resolves real files.
"""

import importlib.util
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"


def _stub_adapter_modules():
    """Stub the three adapter modules + xai/openai/anthropic SDKs so the
    harness imports cleanly without provider deps installed."""
    for name in ("anthropic", "openai", "xai_sdk"):
        if name not in sys.modules:
            sys.modules[name] = type(sys)(name)

    if "adapters" not in sys.modules:
        adapters_pkg = type(sys)("adapters")
        adapters_pkg.__path__ = []
        sys.modules["adapters"] = adapters_pkg
    for name in ("anthropic_adapter", "xai_adapter", "openai_adapter"):
        mod_name = f"adapters.{name}"
        if mod_name not in sys.modules:
            stub = type(sys)(mod_name)
            stub.call = lambda *a, **kw: ("", 0.0)
            sys.modules[mod_name] = stub
            setattr(sys.modules["adapters"], name, stub)


def _build_run_tree(tmp_path: Path, rounds: int = 3) -> Path:
    """Create a round_1, round_2/main, round_3/main file structure
    mirroring what the harness actually writes during a real run."""
    out = tmp_path / "run"
    out.mkdir()
    for a in ("opus", "grok", "gpt"):
        (out / "round_1").mkdir(parents=True, exist_ok=True)
        (out / "round_1" / f"{a}.md").write_text(f"round 1 {a} output", encoding="utf-8")
        for r in range(2, rounds + 1):
            (out / f"round_{r}" / "main").mkdir(parents=True, exist_ok=True)
            (out / f"round_{r}" / "main" / f"{a}.md").write_text(
                f"round {r} {a} main output", encoding="utf-8")
    return out


def _resolve_prior_path(out: Path, agent: str, r: int) -> Path:
    """Replicates the path-selection logic from harness.py main() (the
    round-1 special case). If this drifts from harness.py, the
    convergence check will silently no-op as it did before the fix."""
    if r - 1 == 1:
        return out / "round_1" / f"{agent}.md"
    return out / f"round_{r-1}" / "main" / f"{agent}.md"


def test_round_2_convergence_paths_resolve(tmp_path):
    """For r=2 (the bug case), prior_path must point at round_1/{a}.md
    (no main/ subdir). Verifies the path resolves to a real file."""
    out = _build_run_tree(tmp_path, rounds=2)
    for a in ("opus", "grok", "gpt"):
        prior = _resolve_prior_path(out, a, r=2)
        curr = out / "round_2" / "main" / f"{a}.md"
        assert prior.exists(), (
            f"round 2 prior path {prior} does not exist — convergence will "
            f"silently no-op (this was the audit bug)"
        )
        assert curr.exists(), f"round 2 current path {curr} does not exist"
        # The pre-fix path is the wrong one for r=2; assert it does NOT
        # accidentally exist (otherwise the test wouldn't catch a regression
        # if someone created round_1/main/{a}.md by mistake).
        assert not (out / "round_1" / "main" / f"{a}.md").exists()


def test_round_3plus_uses_main_subdir(tmp_path):
    """For r >= 3, prior path uses /main/ subdir."""
    out = _build_run_tree(tmp_path, rounds=3)
    for a in ("opus", "grok", "gpt"):
        prior = _resolve_prior_path(out, a, r=3)
        assert prior == out / "round_2" / "main" / f"{a}.md"
        assert prior.exists()


def test_harness_path_selection_matches_test_helper(tmp_path):
    """Read harness.py and confirm the path-selection logic still has
    the round-1 special case. Catches accidental regressions where the
    `if r - 1 == 1:` branch is removed during a refactor."""
    text = (SCRIPTS / "harness.py").read_text(encoding="utf-8")
    # The fix introduces this exact pair of branches; the prior bug
    # had only the `round_{r-1}/main/{a}.md` branch.
    assert 'if r - 1 == 1:' in text, (
        "round-1 special case missing from harness.py — convergence will "
        "silently no-op at r=2"
    )
    assert 'output_dir / "round_1" / f"{a}.md"' in text, (
        "round-1 prior path form missing from harness.py path selection"
    )
