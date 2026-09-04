"""End-to-end golden tests for persona/dispatch.py.

Covers the lock-contention fix from the May 2026 audit: concurrent
dispatches into the same `dispatch-runs/INDEX.md` should serialize via
the `.md.lock` sidecar (O_CREAT|O_EXCL atomic), never corrupting the
table, never deleting a peer's lock.

These tests do not require an Anthropic API key — they exercise
update_index() directly via threading, not the full dispatch flow.
"""

import argparse
import importlib.util
import os
import sys
import threading
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"


def _load_dispatch_module(run_base: Path):
    """Load dispatch.py with PERSONA_DISPATCH_RUNS pointed at run_base.
    Reload-safe: each call returns a fresh module bound to the env var
    in effect at import time. Stubs `anthropic` (heavy dep) so the
    test only exercises the lock/serialization path."""
    os.environ["PERSONA_DISPATCH_RUNS"] = str(run_base)
    os.environ.setdefault("PERSONA_INVENTORY", "/dev/null")
    if "anthropic" not in sys.modules:
        anthropic_stub = type(sys)("anthropic")
        anthropic_stub.Anthropic = object  # placeholder; tests don't call the API
        sys.modules["anthropic"] = anthropic_stub
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    if "dispatch" in sys.modules:
        del sys.modules["dispatch"]
    spec = importlib.util.spec_from_file_location("dispatch", SCRIPTS / "dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_update_index_serializes_concurrent_writes(tmp_path):
    """5 concurrent update_index calls must produce 5 well-formed rows
    in INDEX.md (header preserved, no garbled lines)."""
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    def _worker(slug):
        run_dir = run_base / slug
        run_dir.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(slug=slug, model="haiku", n=3,
                                   problem=f"problem-for-{slug}")
        dispatch.update_index(run_dir, args, [{"ok": True}] * 3, "discovery")

    threads = [threading.Thread(target=_worker, args=(f"slug-{i}",))
               for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    index = (run_base / "INDEX.md").read_text(encoding="utf-8")
    lines = index.splitlines()
    # 1 title + 1 blank + header + separator + 5 data rows = 9
    data_rows = [line for line in lines if line.startswith("| ") and "Date" not in line
                 and "---" not in line]
    assert len(data_rows) == 5, (
        f"expected 5 data rows, got {len(data_rows)}\n--- INDEX.md ---\n{index}"
    )
    for row in data_rows:
        # Each row must have 7 columns: Date | Slug | Mode | Problem | N | Model | Link
        cols = [c.strip() for c in row.strip("|").split("|")]
        assert len(cols) == 7, f"malformed row (got {len(cols)} cols): {row!r}"


def test_update_index_releases_lock_on_success(tmp_path):
    """After a successful update, the .md.lock sidecar must be removed."""
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    run_dir = run_base / "test-slug"
    run_dir.mkdir(parents=True)
    args = argparse.Namespace(slug="test-slug", model="haiku", n=1,
                               problem="lock-cleanup-check")
    dispatch.update_index(run_dir, args, [{"ok": True}], "discovery")

    lock = run_base / "INDEX.md.lock"
    assert not lock.exists(), (
        f"lock file {lock} was not cleaned up after a successful write"
    )


def test_article_vi_gate_refuses_with_zero_criteria(tmp_path):
    """Article VI gate must refuse dispatch when <2 of 5 criteria hold.

    Documented in SKILL.md Step 0: 'At least 2 must hold. If <2, exit
    and recommend conventional engineering. The skill refuses to dispatch
    on cargo-cult problems.' Prior to the gate fix, main() dispatched
    immediately without ever checking — this regression test pins the
    refusal behavior.
    """
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    args = argparse.Namespace(skip_article_vi=False, criteria_met=0)
    ok, msg = dispatch._check_article_vi(args)
    assert ok is False, "gate must refuse with 0 criteria met"
    assert "Article VI gate REFUSED" in msg, (
        f"denial message missing REFUSED marker: {msg!r}"
    )
    assert "0/5" in msg, f"denial should cite criteria count: {msg!r}"
    # Documented fallback recommendations
    assert "/code-explore" in msg
    assert "/scout-frontier" in msg
    assert "/fp-check" in msg
    assert "--skip-article-vi" in msg, (
        "denial must surface the bypass flag so the operator knows the escape hatch"
    )


def test_article_vi_gate_refuses_with_one_criterion(tmp_path):
    """1/5 criteria is still below the >=2 threshold — refuse."""
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    args = argparse.Namespace(skip_article_vi=False, criteria_met=1)
    ok, msg = dispatch._check_article_vi(args)
    assert ok is False
    assert "1/5" in msg


def test_article_vi_gate_passes_with_two_criteria(tmp_path):
    """At the >=2 threshold the gate passes (caller proceeds to dispatch)."""
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    args = argparse.Namespace(skip_article_vi=False, criteria_met=2)
    ok, msg = dispatch._check_article_vi(args)
    assert ok is True, f"2/5 should pass; got refusal: {msg!r}"


def test_article_vi_gate_skip_flag_bypasses(tmp_path):
    """--skip-article-vi opts the operator out (logged but allowed)."""
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    # Even with 0 criteria_met, the skip flag wins.
    args = argparse.Namespace(skip_article_vi=True, criteria_met=0)
    ok, msg = dispatch._check_article_vi(args)
    assert ok is True


def test_article_vi_gate_rejects_out_of_range(tmp_path):
    """--criteria-met must be 0-5; anything else is a usage error."""
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    args = argparse.Namespace(skip_article_vi=False, criteria_met=99)
    ok, msg = dispatch._check_article_vi(args)
    assert ok is False
    assert "0-5" in msg


def test_article_vi_gate_main_returns_2_on_refusal(tmp_path, monkeypatch, capsys):
    """End-to-end: main() must exit 2 with denial on stderr.

    This is the contract the operator sees from the shell — exit code 2
    + an actionable error message. CLAUDE.md instructs us to verify the
    external contract, not just the helper.
    """
    run_base = tmp_path / "dispatch-runs"
    run_base.mkdir()
    dispatch = _load_dispatch_module(run_base)

    monkeypatch.setattr(
        sys, "argv",
        [
            "dispatch.py", "discovery", "some problem",
            "--slug", "no-triage-test",
            "--criteria-met", "0",
        ],
    )
    rc = dispatch.main()
    assert rc == 2, f"main() must return 2 when gate refuses; got {rc}"
    captured = capsys.readouterr()
    assert "Article VI gate REFUSED" in captured.err, (
        f"refusal message must land on stderr; stderr was: {captured.err!r}"
    )
