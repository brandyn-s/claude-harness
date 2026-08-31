"""Unit tests for garden/scripts/size_sweep.py — the structural size sweep.

Pins the 2026-07-29 findings and the design decisions that came out of
verifying each cap against its own source:

- SPLIT, NEVER TRIM. Every remedy string prescribes relocation; none says
  "trim" or "shorten". The KB's own rule says "do not trim load-bearing
  evidence" verbatim, and Anthropic's docs say reference files cost zero
  tokens until read — so trimming is strictly worse than splitting.
- HARD vs SOFT caps are distinguished. A skill over 500 lines is NOT per se a
  defect (Anthropic: "or has clear reason to exceed"); a rule over 38,000
  bytes is blocked by a live hook. Conflating them would either under-report a
  real block or manufacture 9 false defects.
- Exemptions are load-bearing, not decorative. Hook-managed rolling logs and
  deliberate archive siblings must not be flagged — mutation-verified: with
  the archive exemption disabled the agent-memory over-count goes 26 -> 28.
- Counts reconcile (over + near + ok == total), so a silently-dropped file
  cannot hide inside a plausible-looking summary.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "garden_size_sweep",
    Path(__file__).resolve().parent.parent / "scripts" / "size_sweep.py")
sweep = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sweep)


# ── The central invariant: no remedy may ever be "trim" ─────────────────────

def test_no_remedy_prescribes_trimming():
    """The whole point of the sweep. Both cap sources prescribe relocation.

    knowledge-base/.claude/rules/topic-authoring.md:36 says "do not trim
    load-bearing evidence"; Anthropic says bundled reference files carry "no
    context penalty until accessed". A remedy that trims destroys evidence AND
    is unnecessary, so the string must never appear.
    """
    banned = ("trim", "shorten", "delete", "truncate", "cut down")
    remedies = [s["remedy"] for s in sweep.SURFACES.values()]
    remedies.append(sweep.sweep_kb_chunks()["remedy"])
    for r in remedies:
        low = r.lower()
        for word in banned:
            # "do not trim" is the documented quote — allowed only as a negation.
            if word in low:
                assert "do not " + word in low or "never " + word in low, (
                    f"remedy prescribes {word!r}: {r}")


def test_every_surface_names_a_structural_remedy():
    """A cap with no remedy is a nag. Each must name WHERE content goes."""
    structural = ("references/", "incidents/", "###", "-subdomain", "sibling",
                  "topic", "hub-split", "<topic>-<subdomain>")
    for name, spec in sweep.SURFACES.items():
        assert any(k in spec["remedy"] for k in structural), (
            f"{name} remedy names no destination: {spec['remedy']}")


def test_every_surface_cites_its_source():
    """A cap without provenance cannot be audited — and one of these turned out
    to be softer than assumed precisely because its source was checked."""
    for name, spec in sweep.SURFACES.items():
        assert spec["source"] and len(spec["source"]) > 20, name


# ── HARD vs SOFT must not be conflated ──────────────────────────────────────

def test_hard_and_soft_caps_are_distinguished():
    """Anthropic explicitly sanctions exceeding the skill line cap with cause,
    so it is SOFT. rule-size-guard.py exits 2 at 38,000, so rules is HARD.
    Reporting a soft breach with the same weight as a hard one manufactures
    false defects (9 of them, for skills)."""
    assert sweep.SURFACES["rules"]["kind"] == "hard"
    assert sweep.SURFACES["skills"]["kind"] == "soft"
    assert sweep.sweep_kb_chunks()["kind"] == "hard"


def test_soft_surfaces_have_no_hard_ceiling():
    for name, spec in sweep.SURFACES.items():
        if spec["kind"] == "soft":
            assert spec["hard_ceiling"] is None, f"{name} soft cap has a ceiling"


def test_non_auto_surfaces_explain_why():
    """`auto=False` without a reason is indistinguishable from an unfinished
    implementation, and garden's contract is 'every check has an
    auto-resolution path' — so declining one needs a stated justification."""
    for name, spec in sweep.SURFACES.items():
        if not spec["auto"]:
            assert spec["why_not_auto"], f"{name} declines auto with no reason"
        else:
            assert spec["why_not_auto"] is None, f"{name} auto but gives a reason"


# ── Measurement + classification ───────────────────────────────────────────

def _surface(tmp_path, unit="bytes", cap=100, warn=80):
    return {"glob": str(tmp_path / "*.md"), "unit": unit, "warn": warn,
            "cap": cap, "hard_ceiling": None, "kind": "soft",
            "source": "test fixture source string, long enough to pass",
            "remedy": "split into <topic>-<subdomain>.md siblings",
            "auto": True, "why_not_auto": None}


def test_classifies_over_near_and_ok(tmp_path):
    (tmp_path / "big.md").write_text("x" * 250, encoding="utf-8")
    (tmp_path / "near.md").write_text("x" * 90, encoding="utf-8")
    (tmp_path / "fine.md").write_text("x" * 10, encoding="utf-8")
    r = sweep.sweep_surface("t", _surface(tmp_path))
    assert [x["file"] for x in r["over"]] == ["big.md"]
    assert [x["file"] for x in r["near"]] == ["near.md"]
    assert r["counts"]["ok"] == 1


def test_counts_always_reconcile(tmp_path):
    """A dropped file must not hide inside a plausible summary."""
    for i in range(7):
        (tmp_path / f"f{i}.md").write_text("x" * (i * 40), encoding="utf-8")
    c = sweep.sweep_surface("t", _surface(tmp_path))["counts"]
    assert c["over"] + c["near"] + c["ok"] == c["total"] == 7


def test_over_list_is_sorted_worst_first(tmp_path):
    for n, size in (("a", 150), ("b", 400), ("c", 220)):
        (tmp_path / f"{n}.md").write_text("x" * size, encoding="utf-8")
    over = sweep.sweep_surface("t", _surface(tmp_path))["over"]
    assert [x["file"] for x in over] == ["b.md", "c.md", "a.md"]


def test_breach_ceiling_outranks_over_cap(tmp_path):
    spec = _surface(tmp_path)
    spec.update(kind="hard", hard_ceiling=300)
    (tmp_path / "ceiling.md").write_text("x" * 350, encoding="utf-8")
    (tmp_path / "overcap.md").write_text("x" * 150, encoding="utf-8")
    over = {x["file"]: x["severity"] for x in sweep.sweep_surface("t", spec)["over"]}
    assert over["ceiling.md"] == "BREACH-CEILING"
    assert over["overcap.md"] == "OVER-CAP"


def test_line_unit_counts_lines_not_bytes(tmp_path):
    """Skills are capped in LINES. A 3-line file of long lines must not read as
    over-cap just because its byte count is large."""
    (tmp_path / "s.md").write_text("y" * 5000 + "\n" + "z" * 5000 + "\n",
                                   encoding="utf-8")
    spec = _surface(tmp_path, unit="lines", cap=10, warn=8)
    r = sweep.sweep_surface("t", spec)
    assert r["counts"]["over"] == 0, "byte size leaked into a line-unit measure"
    assert r["counts"]["ok"] == 1


# ── Exemptions (mutation-verified as load-bearing) ──────────────────────────

def test_hook_managed_file_is_exempt(tmp_path):
    """Splitting a rolling log fights its producer: the next run rewrites the
    file wholesale and any siblings orphan instantly."""
    name = sorted(sweep.HOOK_MANAGED)[0]
    (tmp_path / name).write_text("x" * 9999, encoding="utf-8")
    r = sweep.sweep_surface("t", _surface(tmp_path))
    assert r["counts"]["over"] == 0
    assert r["counts"]["ok"] == 1


def test_archive_sibling_is_exempt(tmp_path):
    """MUTATION-PINNED: disabling this exemption moves the real agent-memory
    over-count 26 -> 28. These files exist BECAUSE a parent was already split;
    re-flagging them reports the fix as the problem."""
    name = sorted(sweep.KNOWN_ARCHIVE_EXCEPTIONS)[0]
    (tmp_path / name).write_text("x" * 9999, encoding="utf-8")
    (tmp_path / "ordinary.md").write_text("x" * 9999, encoding="utf-8")
    r = sweep.sweep_surface("t", _surface(tmp_path))
    assert [x["file"] for x in r["over"]] == ["ordinary.md"]


# ── KB chunk gate (the one HARD gate that already passes) ───────────────────

def test_kb_chunk_measurement_matches_analyze_py():
    """leaf_chunks is duplicated deliberately (see its docstring). If the two
    copies drift, the sweep and the CI gate disagree and one of them lies."""
    a_spec = importlib.util.spec_from_file_location(
        "garden_analyze_cmp",
        Path(__file__).resolve().parent.parent / "scripts" / "analyze.py")
    a = importlib.util.module_from_spec(a_spec)
    a_spec.loader.exec_module(a)
    sample = ("---\ntitle: t\n---\n\n# T\n\n## One\nbody one\n\n"
              "## Two\npre text\n### Sub A\naaa\n### Sub B\nbbb\n")
    assert sweep.leaf_chunks(sample) == a.leaf_chunks(sample)


def test_moc_dashboards_skipped_in_chunk_sweep():
    """_moc-* files are generated navigation surfaces whose 'Recently Added'
    sections legitimately exceed the chunk cap; analyze.py skips them too.
    Without this, 4 phantom hard-chunk violations appear."""
    assert "_moc-" in sweep.KB_CHUNK_SKIP_PREFIXES
    assert "dashboard-" in sweep.KB_CHUNK_SKIP_PREFIXES


def test_kb_chunk_hard_cap_is_3000():
    """Pinned to knowledge-base/.claude/rules/topic-authoring.md:36 and the
    kb.py check gate. A drift here silently changes what CI enforces."""
    assert sweep.KB_CHUNK_HARD == 3000
    assert sweep.KB_CHUNK_SOFT == 2500


# ── Output contract ─────────────────────────────────────────────────────────

def test_json_output_is_parseable_and_shaped(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["size_sweep.py", "--json"])
    assert sweep.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert "surfaces" in payload
    names = {s["surface"] for s in payload["surfaces"]}
    assert {"rules", "skills", "agent-memory", "kb-chunks"} <= names
    for s in payload["surfaces"]:
        for key in ("kind", "cap", "unit", "source", "remedy",
                    "auto_resolvable", "counts", "over", "near"):
            assert key in s, f"{s['surface']} missing {key}"


def test_report_names_the_aggregate_it_does_not_measure(capsys, monkeypatch):
    """The per-file caps are a rounding error against ~155K tokens/session of
    ambient rules. A sweep that reported only breaches would imply per-file
    descoping is the win; it is under 1%. The report must say so and point at
    /context-budget, which owns the aggregate."""
    monkeypatch.setattr(sys, "argv", ["size_sweep.py"])
    assert sweep.main() == 0
    out = capsys.readouterr().out
    assert "context-budget" in out
    assert "NEVER trim" in out or "never trim" in out.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# CI has no deployed ~/.claude corpus, and `size_sweep` resolves its globs from
# HOME — so any test asserting a FINDING (rather than pure logic) is asserting
# the corpus exists. Those skip on CI; the logic tests run everywhere. Verified
# by reproducing the runner locally:
#   HOME=/tmp/fakehome python3 -m pytest skills/garden/tests/test_size_sweep.py
def _has_over_cap_topic() -> bool:
    """Do any deployed topics actually EXCEED the cap?

    Gate on the PRECONDITION, not a proxy for it. The first version of this gate
    checked whether the topics DIRECTORY exists — which is not what these tests
    need. CI has the directory (the checkout lands under it) but nothing over
    cap, so the skip did not fire and the assertions failed on an empty finding
    list, on all three platforms.
    
    The local `HOME=/tmp/fakehome` reproduction could not catch that either: a
    fake home has NO directory at all, so it exercised the one branch the proxy
    got right. Emulating a mechanism only tests the mechanism you emulated —
    here the real CI condition was "dir present, corpus small", a third state
    neither environment covered.
    """
    cap = SURFACES_CAP = sweep.SURFACES["agent-memory"]["cap"]
    topics = Path.home() / ".claude" / "agent-memory" / "topics"
    if not topics.is_dir():
        return False
    try:
        return any(f.stat().st_size > cap for f in topics.glob("*.md"))
    except OSError:
        return False


needs_corpus = pytest.mark.skipif(
    not _has_over_cap_topic(),
    reason="no deployed agent-memory topic exceeds the cap, so there is no "
           "finding to assert on (CI runner); pure-logic assertions still run",
)


# ── Regression tests for defects found by probing this script's OWN failure paths
# (2026-07-29). Both were found the same way the session's other bugs were: by
# asking "what does this report when its input is missing?" rather than by
# reading the happy path.

@needs_corpus
def test_unreadable_route_map_reports_UNKNOWN_never_safe(monkeypatch):
    """A failed read must not become the positive claim 'no delivery penalty'.

    `_loader_routed_topics` originally returned an empty set on failure, and the
    caller read empty as "nothing is routed" — so with the loader unreadable the
    sweep stamped all 21 over-cap topics 'read-only — no delivery penalty'. That
    is a two-state verifier reporting UNKNOWN as PASS, which is exactly the
    failure class `verify-before-assuming.md` names: a verifier must distinguish
    PASS / FAIL / could-not-determine, because an unreadable input and a
    genuinely-empty one are indistinguishable from the output.
    """
    monkeypatch.setattr(sweep, "_loader_routed_topics", lambda: None)
    r = sweep.sweep_surface("agent-memory", sweep.SURFACES["agent-memory"])
    assert r["over"], "fixture expects at least one over-cap topic"
    for row in r["over"]:
        assert row["loader_routed"] is None, "UNKNOWN must not collapse to False"
        assert "UNKNOWN" in row["severity_reason"]
        assert "no delivery penalty" not in row["severity_reason"], (
            "an unreadable route map was reported as safe"
        )


@needs_corpus
def test_findings_sort_by_severity_before_size(monkeypatch):
    """A truncated topic must outrank a larger topic that is merely read-only.

    The human report prints only the top 6 rows, so a size-only sort lets
    harmless files push real findings below the '… N more' line. Measured
    2026-07-29: claude-monitoring.md (119 KB, read-only, zero delivery cost) led
    the list while 3 of the 4 genuinely-truncated topics were hidden.
    """
    routed = {"confluence.md"}  # small-but-injected
    monkeypatch.setattr(sweep, "_loader_routed_topics", lambda: routed)
    r = sweep.sweep_surface("agent-memory", sweep.SURFACES["agent-memory"])
    injected = [i for i, row in enumerate(r["over"]) if row["loader_routed"]]
    readonly = [i for i, row in enumerate(r["over"]) if row["loader_routed"] is False]
    if injected and readonly:
        assert max(injected) < min(readonly), (
            "a read-only topic outranked an INJECTED one; size is beating severity"
        )


@needs_corpus
def test_human_report_names_the_delivery_status(capsys, monkeypatch):
    """Delivery status must be visible in the HUMAN report, not only the JSON.

    The injected-vs-read-only distinction is the entire reason this surface
    narrows 21 findings to 4. A reader who only sees byte counts re-derives the
    wrong priority order (biggest first), which is what the JSON-only version
    invited.
    """
    monkeypatch.setattr("sys.argv", ["sweep.py", "--surface", "agent-memory"])
    sweep.main()
    out = capsys.readouterr().out
    # All THREE stamps count. The negative control (a synthetic HOME with an
    # over-cap topic but no loader) renders "DELIVERY UNKNOWN", which is the
    # correct output for that state — asserting only the two happy-path stamps
    # made a CORRECT report look like a missing one.
    assert any(k in out for k in ("INJECTED", "read-only", "DELIVERY UNKNOWN")), (
        "human report omits delivery status entirely; only the JSON carries it"
    )


def test_loader_probe_itself_returns_None_when_the_hook_is_unreadable(monkeypatch, tmp_path):
    """Exercise the REAL `_loader_routed_topics`, not a stub of it.

    The first version of the UNKNOWN test monkeypatched the whole function, so it
    verified only that the CALLER handles None — it could not catch either of the
    function's own `return set()` failure paths. Mutation-testing proved it: with
    the fix reverted, all tests still passed. So this test redirects HOME to a
    tree with no hooks/ dir and asserts the probe reports UNKNOWN.

    Two paths must both return None: spec-is-None (no such file) and the
    exception handler (import/attribute failure). A `set()` on either one is the
    original defect.
    """
    monkeypatch.setattr(sweep, "HOME", tmp_path)  # no ~/.claude/hooks here
    assert sweep._loader_routed_topics() is None, (
        "an unreadable loader must yield UNKNOWN (None), never an empty set"
    )


def test_loader_probe_returns_None_when_the_hook_raises(monkeypatch, tmp_path):
    """The exception path, exercised by planting a hook that raises on import."""
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "auto-topic-loader.py").write_text(
        "raise RuntimeError('simulated import failure')\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "HOME", tmp_path)
    assert sweep._loader_routed_topics() is None, (
        "a raising loader must yield UNKNOWN (None), never an empty set"
    )


def test_loader_probe_returns_a_set_when_the_hook_is_healthy(monkeypatch, tmp_path):
    """Negative control: a WORKING loader must yield a set, not None.

    Without this, a function that returned None unconditionally would satisfy
    both tests above — so the pair would pass while the sweep reported every
    topic as UNKNOWN forever, which is a different kind of useless.
    """
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "auto-topic-loader.py").write_text(
        "STATIC_MAP = {'mcp__x__': 'x.md'}\n"
        "def _build_server_to_topic_map():\n"
        "    return STATIC_MAP\n", encoding="utf-8")
    monkeypatch.setattr(sweep, "HOME", tmp_path)
    got = sweep._loader_routed_topics()
    assert got == {"x.md"}, f"healthy loader should yield its topics, got {got!r}"
