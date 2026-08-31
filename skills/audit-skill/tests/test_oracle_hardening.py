"""Regression tests for the 2026-06-12 campaign-11 toolchain hardening.

Covers, in order of the incidents that motivated each:

1. PyYAML-primary findings loader — folded flow scalars load FULL via
   load_findings (the minimal parser truncated them: 68 commands cut at
   the fold point -> ~90 false STALEs in one reverify), and garbage
   raises FindingsParseError instead of reading as an empty worklist.
2. Union-of-fields round-trip — _to_yaml -> load_findings preserves
   EVERY field including extras (the location-drop escaped a six-field
   whitelist diff; this property test compares the union).
3. Advisory reproducer-smell warnings — deployed-path probes and
   stateful appends are flagged, run-scoped appends are not.
4. STALE-by-rc evidence buckets in the act-on summary — the bash-rc=2
   instrument-failure cluster is surfaced instead of silently dropped.
5. Surgical triage updates — set-triage-status changes ONLY the matched
   blocks' triage lines; every other byte is preserved (the full
   re-emit it replaces deleted 451 location fields in one call).
6. --fix=M1 — manifest required:true follows a bracketed argument-hint
   to required:false; multi-required manifests are skipped for human
   judgment.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills" / "_shared"))

from oracle.finding import (  # noqa: E402
    Finding,
    FindingsParseError,
    Reproducer,
    load_findings,
)
from oracle.tracker import _to_yaml, update_triage_surgical  # noqa: E402
from oracle.validate import advisory_warnings  # noqa: E402


# ── 1. PyYAML-primary loader ─────────────────────────────────────────

FOLDED = """findings:
  - skill: x
    code: B
    severity: info
    label: doc-fix
    description: d
    reproducer:
      type: bash
      command: echo aaaa && [ -n "x"
        ]
"""


def test_load_findings_unfolds_flow_scalars(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text(FOLDED, encoding="utf-8")
    cmd = load_findings(p)[0].reproducer.command
    assert cmd.rstrip() == 'echo aaaa && [ -n "x" ]'


def test_load_findings_rejects_garbage(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("not: valid: yaml: [unclosed\n", encoding="utf-8")
    with pytest.raises(FindingsParseError):
        load_findings(p)


def test_load_findings_accepts_findings_less_valid_doc(tmp_path):
    # The calibration corpus depends on valid-but-findings-less docs
    # loading as empty (see test_oracle_validate's missing-key test).
    p = tmp_path / "empty.yaml"
    p.write_text("# just a comment\nnotes: nothing here\n", encoding="utf-8")
    assert load_findings(p) == []


def test_every_findings_fixture_is_valid_yaml():
    """Every golden findings fixture in the repo must parse under real
    YAML semantics. The minimal parser tolerated invalid YAML (unquoted
    `key: value` colons inside scalars), so latently-broken fixtures
    accumulated — the pyyaml-primary loader surfaced one in
    mcp-forge-audit on its first CI run (97 unquoted descriptions)."""
    import yaml as _yaml

    patterns = [
        "skills/*/tests/golden-findings/**/*.yaml",
        "skills/*/tests/golden/**/*.yaml",
        "AUDIT-TRACKERS/*.yaml",
    ]
    checked = 0
    for pat in patterns:
        for p in REPO.glob(pat):
            if not p.is_file():
                continue
            checked += 1
            try:
                _yaml.safe_load(p.read_text(encoding="utf-8"))
            except _yaml.YAMLError as e:
                raise AssertionError(f"{p} is not valid YAML: {e}") from e
    assert checked > 0, "fixture glob matched nothing — patterns stale?"


# ── 2. Union-of-fields round-trip ────────────────────────────────────

ROUND_TRIP_CASES = [
    Finding(
        skill="alpha", code="A1", severity="drift", label="behavior-fix",
        description='quotes "double" and \'single\' and a \\ backslash',
        reproducer=Reproducer(type="grep", command="grep -q 'x[]' skills/alpha/SKILL.md"),
        extra={"location": "skills/alpha/SKILL.md:7", "oracle_verdict": "STILL-FIRES"},
    ),
    Finding(
        skill="beta", code="D2", severity="behavior-bug", label="behavior-fix",
        description="multi-line python reproducer survives the worklist round-trip",
        reproducer=Reproducer(
            type="python",
            command="import sys\nif True:\n    sys.exit(1)",
            expected_exit=1,
        ),
        triage_status="FIXED", triage_note="note with: colon and \"quotes\"",
        extra={"location": "skills/beta/scripts/run.py:42"},
    ),
    Finding(
        skill="gamma", code="F2", severity="info", label="doc-fix",
        description="unicode — em-dash and ≥ comparisons",
        reproducer=Reproducer(type="file_missing", path="skills/gamma/references/x.md"),
        extra={"verified_at": "2026-06-12T18:00:00+00:00", "campaign": "11"},
    ),
]


def _field_union_dict(f: Finding) -> dict:
    rep = f.reproducer
    return {
        "skill": f.skill, "code": f.code, "severity": f.severity,
        "label": f.label, "description": f.description,
        "triage_status": f.triage_status, "triage_note": f.triage_note,
        "rep.type": rep.type,
        "rep.command": (rep.command or "").rstrip(),
        "rep.path": rep.path or "",
        "rep.expected_exit": int(rep.expected_exit or 0),
        **{f"extra.{k}": str(v) for k, v in sorted(f.extra.items())},
    }


def test_to_yaml_round_trip_preserves_field_union(tmp_path):
    p = tmp_path / "rt.yaml"
    p.write_text(_to_yaml(ROUND_TRIP_CASES), encoding="utf-8")
    loaded = load_findings(p)
    assert len(loaded) == len(ROUND_TRIP_CASES)
    for orig, back in zip(ROUND_TRIP_CASES, loaded):
        a, b = _field_union_dict(orig), _field_union_dict(back)
        # Compare the UNION of keys — a whitelist diff is exactly what let
        # the location-drop ship (2026-06-12).
        assert set(a) == set(b), (set(a) ^ set(b))
        for k in a:
            av, bv = a[k], b[k]
            if k == "description":
                # The single-line emitter flattens newlines by design.
                av = " ".join(str(av).split())
                bv = " ".join(str(bv).split())
            assert av == bv, (orig.skill, k, av, bv)


# ── 3. Advisory warnings ─────────────────────────────────────────────

def _f(cmd: str) -> Finding:
    return Finding(skill="s", code="A1", severity="drift", label="behavior-fix",
                   description="d", reproducer=Reproducer(type="bash", command=cmd))


def test_advisory_flags_deployed_path_probe():
    warns = advisory_warnings([_f("python3 ~/.claude/skills/s/scripts/x.py")])
    assert len(warns) == 1 and "DEPLOYED_PATH_PROBE" in warns[0]


def test_advisory_flags_stateful_append():
    warns = advisory_warnings([_f("echo x >> /tmp/claude/persistent.ndjson; grep -q x /tmp/claude/persistent.ndjson")])
    assert any("STATEFUL_APPEND" in w for w in warns)


def test_advisory_quiet_on_run_scoped_append_and_repo_paths():
    # The mktemp fixture is quiet for the DEPLOYED_PATH/STATEFUL_APPEND
    # checks it pins (it IS flagged DOC_DECOUPLED_SUSPECT — a predicate
    # that never touches the repo is exactly that check's target).
    warns = advisory_warnings(
        [_f("T=$(mktemp -d) && echo x >> \"$T/log\" && grep -q x \"$T/log\"")])
    assert not any("DEPLOYED_PATH" in w or "STATEFUL_APPEND" in w for w in warns)
    # A repo-coupled predicate is fully quiet.
    assert advisory_warnings([_f("grep -q pattern skills/s/SKILL.md")]) == []


def test_advisory_flags_doc_decoupled_suspect():
    """A predicate that never references its own skill directory can't
    see the artifact under test — 38 of 81 findings in the 2026-08-22
    close-out were already-fixed ghosts kept alive by this class."""
    warns = advisory_warnings([_f("test ! -e \"$HOME/some-tool/x.py\"")])
    assert any("DOC_DECOUPLED_SUSPECT" in w for w in warns)
    # Referencing ANOTHER skill's dir still flags (wrong artifact).
    warns = advisory_warnings([_f("grep -q x skills/other/SKILL.md")])
    assert any("DOC_DECOUPLED_SUSPECT" in w for w in warns)
    # Own-skill reference is quiet.
    assert not any(
        "DOC_DECOUPLED_SUSPECT" in w
        for w in advisory_warnings([_f("grep -q x skills/s/SKILL.md")]))


# ── 4. STALE-by-rc buckets in the act-on summary ─────────────────────

def test_summary_buckets_stale_evidence():
    from oracle.act_on import ActOnReport, format_act_on_summary
    from oracle.reverify import ReverifyResult

    def stale(cmd_type, rc):
        f = Finding(skill="s", code="B", severity="info", label="doc-fix",
                    description="d", reproducer=Reproducer(type=cmd_type, command="true"))
        return ReverifyResult(finding=f, status="STALE",
                              evidence=f"{cmd_type} rc={rc}; expected_exit=0; fires=False")

    report = ActOnReport(
        worklist=[], stale=[stale("bash", 2), stale("bash", 2), stale("bash", 2),
                            stale("grep", 1)],
        still_fires=[], manual=[], error=[], triage_filtered=[],
        verified_at="2026-06-12T00:00:00+00:00",
    )
    out = format_act_on_summary(report)
    assert "stale evidence:" in out
    assert "bash rc=2: 3" in out
    assert "WARNING" in out and "bash rc=2" in out


# ── 5. Surgical triage updates ───────────────────────────────────────

TRACKER_2SPACE = """findings:
  - skill: one
    code: A1
    severity: drift
    label: doc-fix
    description: "first finding"
    location: skills/one/SKILL.md:1
    reproducer:
      type: grep
      command: "grep -q x skills/one/SKILL.md"
  - skill: two
    code: B
    severity: info
    label: doc-fix
    description: "second finding"
    location: skills/two/SKILL.md:2
    reproducer:
      type: manual
"""


def test_surgical_triage_touches_only_matched_block(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(TRACKER_2SPACE, encoding="utf-8")
    before = p.read_text(encoding="utf-8").splitlines(keepends=True)

    n = update_triage_surgical(p, [1], "FIXED", note="done")
    assert n == 1

    after = p.read_text(encoding="utf-8").splitlines(keepends=True)
    added = [ln for ln in after if ln not in before]
    assert sorted(x.strip() for x in added) == [
        'triage_note: "done"', "triage_status: FIXED"]
    # Every original byte is preserved (location: fields included — the
    # full re-emit this replaces dropped them).
    for ln in before:
        assert ln in after
    # And the result still loads, with the status attached to finding 2.
    loaded = load_findings(p)
    assert loaded[0].triage_status == "" and loaded[1].triage_status == "FIXED"


def test_surgical_triage_column0_indent(tmp_path):
    p = tmp_path / "t0.yaml"
    p.write_text(TRACKER_2SPACE.replace("  - skill:", "- skill:")
                 .replace("    ", "  "), encoding="utf-8")
    n = update_triage_surgical(p, [0], "DEFER")
    assert n == 1
    assert load_findings(p)[0].triage_status == "DEFER"


def test_surgical_triage_refuses_index_drift(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(TRACKER_2SPACE, encoding="utf-8")
    with pytest.raises(ValueError):
        update_triage_surgical(p, [5], "FIXED")


# ── 6. --fix=M1 ──────────────────────────────────────────────────────

def _load_audit_module():
    if "audit_skill_hardening" in sys.modules:
        return sys.modules["audit_skill_hardening"]
    spec = importlib.util.spec_from_file_location(
        "audit_skill_hardening", REPO / "bin" / "audit-skill.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_skill_hardening"] = mod
    spec.loader.exec_module(mod)
    return mod


def _skill_fixture(tmp_path, hint, manifest_body):
    d = tmp_path / "fixskill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: fixskill\ndescription: x\nargument-hint: \"{hint}\"\n---\nBody.\n",
        encoding="utf-8")
    (d / "manifest.yaml").write_text(manifest_body, encoding="utf-8")
    return d


def test_fix_m1_flips_single_required(tmp_path):
    m = _load_audit_module()
    d = _skill_fixture(tmp_path, "[target]",
                       "input_contract:\n  - name: target\n    required: true\n")
    n, notice = m._fix_m1_for_skill(d)
    assert n == 1 and notice is None
    assert "required: false" in (d / "manifest.yaml").read_text(encoding="utf-8")


def test_fix_m1_skips_multi_required(tmp_path):
    m = _load_audit_module()
    d = _skill_fixture(
        tmp_path, "[target]",
        "input_contract:\n"
        "  - name: target\n    required: true\n"
        "  - name: mode\n    required: true\n")
    n, notice = m._fix_m1_for_skill(d)
    assert n == 0 and notice and "human judgment" in notice
    assert "required: false" not in (d / "manifest.yaml").read_text(encoding="utf-8")


def test_fix_m1_noop_without_brackets(tmp_path):
    m = _load_audit_module()
    d = _skill_fixture(tmp_path, "<target>",
                       "input_contract:\n  - name: target\n    required: true\n")
    n, notice = m._fix_m1_for_skill(d)
    assert n == 0 and notice is None
