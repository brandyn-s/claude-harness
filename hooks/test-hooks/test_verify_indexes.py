"""Contract test for `verify-indexes.py --json`.

This pins the FIELD NAMES that session_start_modules/code_graph_health.py reads.
Those two drifted for as long as the flag existed: the hook read a `mode` key the
script never emitted, and nothing caught it because the script ignored argv, so
the hook's JSON branch never ran at all. A stub-only test on the hook side cannot
catch that class — only asserting against the real script's real output can.

Runs the actual script (imported by path, since the filename is hyphenated) with
its cache dirs pointed at a temp tree, so a deliberately corrupt DB produces a
real finding rather than a hand-written payload.
"""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO / "scripts" / "verify-indexes.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_indexes_under_test", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _run_json(mod, capsys) -> dict:
    rc = mod.main(["--json"])
    out = capsys.readouterr().out
    return {"rc": rc, "data": json.loads(out)}


def test_script_exists():
    assert SCRIPT.exists(), f"{SCRIPT} missing — the hook invokes it by absolute path"


def test_clean_tree_emits_clean_status(tmp_path, capsys, monkeypatch):
    mod = _load()
    cache = tmp_path / "cg"
    cache.mkdir()
    monkeypatch.setattr(mod, "CG_CACHE", cache)
    monkeypatch.setattr(mod, "CS_PROJECTS", tmp_path / "no-cs")

    r = _run_json(mod, capsys)
    assert r["rc"] == 0
    assert r["data"]["status"] == "clean"
    assert r["data"]["code_graph_corruption"] == []


def test_corrupt_db_emits_the_fields_the_hook_reads(tmp_path, capsys, monkeypatch):
    """A real corrupt DB must yield project + detail + db_path.

    These are exactly the keys code_graph_health.py consumes. If a future edit
    renames one, this test fails instead of the hook silently rendering
    '<unknown>' at session start.
    """
    mod = _load()
    cache = tmp_path / "cg"
    cache.mkdir()
    # Not a SQLite file at all — the open/integrity check must report it.
    (cache / "brokenproj.db").write_bytes(b"this is not a sqlite database" * 20)
    monkeypatch.setattr(mod, "CG_CACHE", cache)
    monkeypatch.setattr(mod, "CS_PROJECTS", tmp_path / "no-cs")

    r = _run_json(mod, capsys)
    assert r["rc"] == 2, "a corrupt DB must exit 2 so the hook's fallback also triggers"
    assert r["data"]["status"] == "fail"

    found = r["data"]["code_graph_corruption"]
    # One unreadable file can trip several independent checks (integrity_check
    # AND table listing both fail on a non-SQLite file), so the count is an
    # implementation detail. What the hook depends on is that EVERY record is
    # correctly attributed and carries all three fields.
    assert found, "a corrupt DB must produce at least one finding"
    for rec in found:
        assert rec["project"] == "brokenproj", rec
        assert rec["detail"], "detail must be non-empty — the hook renders it verbatim"
        assert rec["db_path"] == str(cache / "brokenproj.db"), rec


def test_counts_are_reported(tmp_path, capsys, monkeypatch):
    mod = _load()
    cache = tmp_path / "cg"
    cache.mkdir()
    (cache / "brokenproj.db").write_bytes(b"nope" * 40)
    monkeypatch.setattr(mod, "CG_CACHE", cache)
    monkeypatch.setattr(mod, "CS_PROJECTS", tmp_path / "no-cs")

    r = _run_json(mod, capsys)
    assert r["data"]["counts"]["code_graph_dbs"] == 1
    assert r["data"]["counts"]["code_search_projects"] == 0


def test_unknown_flag_is_rejected(capsys):
    """The root cause of the dead branch was argv being ignored entirely."""
    mod = _load()
    try:
        mod.main(["--not-a-real-flag"])
    except SystemExit as e:
        assert e.code == 2
    else:  # pragma: no cover
        raise AssertionError("an unknown flag must not be silently accepted")


def test_human_output_has_no_json_and_still_works(tmp_path, capsys, monkeypatch):
    """Default invocation must stay the human report other callers display."""
    mod = _load()
    cache = tmp_path / "cg"
    cache.mkdir()
    monkeypatch.setattr(mod, "CG_CACHE", cache)
    monkeypatch.setattr(mod, "CS_PROJECTS", tmp_path / "no-cs")

    rc = mod.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Indexes:" in out
    try:
        json.loads(out)
    except json.JSONDecodeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("default output must NOT be JSON")
