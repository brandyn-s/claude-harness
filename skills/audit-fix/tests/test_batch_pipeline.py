"""Tests for the batch fix-pipeline scripts promoted from the campaign-11
orchestration (apply_fixes / patch_worklist / batch_verdicts).

The pipeline contract these pin:
  apply_fixes — exact+unique old/new application, skill-dir scope guard,
    create-file convention, note/field-mismatch warning
  patch_worklist — updated-reproducer install + loader-safe emission
    (multi-line commands as block literals)
  batch_verdicts — expected-vs-actual gate (applied ⟹ STALE; unfixed ⟹
    not STALE; exemptions for deliberate non-fixes)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    key = f"audit_fix_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


# ── apply_fixes ──────────────────────────────────────────────────────

def _results(skill, fixes, skipped=()):
    return [{"skill": skill, "fixes": fixes, "skipped": list(skipped),
             "notes": ""}]


def test_apply_exact_unique_replacement(tmp_path):
    m = _load("apply_fixes")
    f = tmp_path / "skills" / "demo" / "SKILL.md"
    f.parent.mkdir(parents=True)
    f.write_text("alpha\nbroken line\nomega\n", encoding="utf-8")
    applied, failed, reps, skip_reps, skipped, warns = m.apply_all(_results("demo", [{
        "idx": 0, "file": "skills/demo/SKILL.md", "note": "",
        "edits": [{"old_string": "broken line", "new_string": "fixed line"}],
    }]), tmp_path)
    assert applied and not failed
    assert f.read_text(encoding="utf-8") == "alpha\nfixed line\nomega\n"


def test_apply_rejects_nonunique_and_out_of_scope(tmp_path):
    m = _load("apply_fixes")
    f = tmp_path / "skills" / "demo" / "SKILL.md"
    f.parent.mkdir(parents=True)
    f.write_text("dup\ndup\n", encoding="utf-8")
    applied, failed, *_ = m.apply_all(_results("demo", [
        {"idx": 0, "file": "skills/demo/SKILL.md", "note": "",
         "edits": [{"old_string": "dup", "new_string": "x"}]},
        {"idx": 1, "file": "skills/other/SKILL.md", "note": "",
         "edits": [{"old_string": "a", "new_string": "b"}]},
    ]), tmp_path)
    assert not applied
    assert failed[0][0][1] == "old_string count=2"
    assert failed[1][0][1] == "outside skill dir"
    # Nothing was written on the non-unique failure.
    assert f.read_text(encoding="utf-8") == "dup\ndup\n"


def test_apply_create_file_convention(tmp_path):
    m = _load("apply_fixes")
    (tmp_path / "skills" / "demo").mkdir(parents=True)
    applied, failed, *_ = m.apply_all(_results("demo", [{
        "idx": 0, "file": "skills/demo/scripts/new.py", "note": "",
        "edits": [{"old_string": "", "new_string": "#!/usr/bin/env python3\n"}],
    }]), tmp_path)
    assert applied and not failed
    created = tmp_path / "skills" / "demo" / "scripts" / "new.py"
    assert created.exists()
    if sys.platform != "win32":
        # os.chmod's executable bit is a POSIX concept; on the Windows CI
        # leg chmod(0o755) is a no-op for 0o111 and the assertion would
        # fail there while the create itself is fine.
        assert created.stat().st_mode & 0o111, "create-file should set +x for .py"


def test_apply_collects_skip_side_updated_reproducer(tmp_path):
    """A SKIPPED finding may carry a corrected predicate (already-fixed
    in-tree, tracker reproducer decoupled). apply_all must collect it
    into the separate skip_updated_reps channel — and warn when the
    skip reason only DESCRIBES a predicate without the structured field
    (the 2026-08-22 failure shape: predicates trapped in prose)."""
    m = _load("apply_fixes")
    (tmp_path / "skills" / "demo").mkdir(parents=True)
    rep = {"type": "grep", "command": "grep -q x skills/demo/SKILL.md",
           "expected_exit": 0}
    applied, failed, reps, skip_reps, skipped, warns = m.apply_all(
        _results("demo", [], skipped=[
            {"idx": 3, "reason": "appears already fixed; corrected predicate attached",
             "updated_reproducer": rep},
            {"idx": 4, "reason": "already fixed; the replacement predicate is grep -q y ..."},
        ]), tmp_path)
    assert skip_reps == {3: rep}
    assert not applied and not failed and not reps
    assert len(skipped) == 2
    assert any("SKIP_NOTE_REPRODUCER" in w and "idx4" in w for w in warns)


def test_apply_warns_on_note_field_mismatch(tmp_path):
    m = _load("apply_fixes")
    f = tmp_path / "skills" / "demo" / "SKILL.md"
    f.parent.mkdir(parents=True)
    f.write_text("x\n", encoding="utf-8")
    *_, warns = m.apply_all(_results("demo", [{
        "idx": 0, "file": "skills/demo/SKILL.md",
        "note": "supplying a doc-state predicate as updated reproducer",
        "edits": [{"old_string": "x", "new_string": "y"}],
    }]), tmp_path)
    assert warns and "NOTE_FIELD_MISMATCH" in warns[0]


# ── patch_worklist ───────────────────────────────────────────────────

def test_patch_worklist_installs_and_block_literalizes(tmp_path):
    m = _load("patch_worklist")
    wl = tmp_path / "wl.yaml"
    wl.write_text(
        "findings:\n"
        "  - skill: demo\n    code: A1\n    severity: drift\n"
        "    label: behavior-fix\n    description: d\n"
        "    reproducer:\n      type: bash\n      command: old probe\n",
        encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"updated_reps": {"0": {
        "type": "grep", "command": "grep -q 'a'\\nsecond line",
        "expected_exit": 0}}}), encoding="utf-8")
    out = tmp_path / "patched.yaml"
    rc = m.main([str(wl), str(state), "--out", str(out)])
    assert rc == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["findings"][0]["reproducer"]["type"] == "grep"


def test_patch_worklist_installs_skip_side_reproducers(tmp_path):
    """skip_updated_reps install identically to updated_reps — the
    finding wasn't edited but its tracker predicate was dishonest."""
    m = _load("patch_worklist")
    wl = tmp_path / "wl.yaml"
    wl.write_text(
        "findings:\n"
        "  - skill: demo\n    code: A1\n    severity: drift\n"
        "    label: behavior-fix\n    description: d\n"
        "    reproducer:\n      type: bash\n      command: old probe\n",
        encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"skip_updated_reps": {"0": {
        "type": "grep_absent", "command": "grep -q ok skills/demo/SKILL.md",
        "expected_exit": 1}}}), encoding="utf-8")
    out = tmp_path / "patched.yaml"
    assert m.main([str(wl), str(state), "--out", str(out)]) == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["findings"][0]["reproducer"]["type"] == "grep_absent"


def test_patch_worklist_rejects_out_of_range_state(tmp_path):
    m = _load("patch_worklist")
    wl = tmp_path / "wl.yaml"
    wl.write_text("findings:\n  - skill: demo\n    code: A1\n"
                  "    severity: drift\n    label: doc-fix\n"
                  "    description: d\n    reproducer:\n      type: manual\n",
                  encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"updated_reps": {"7": {
        "type": "grep", "command": "grep -q x f"}}}), encoding="utf-8")
    rc = m.main([str(wl), str(state), "--out", str(tmp_path / "o.yaml")])
    assert rc == 2


# ── batch_verdicts ───────────────────────────────────────────────────

def _verdict_fixture(tmp_path, statuses, applied_indices, n=None):
    n = n if n is not None else len(statuses)
    rev = tmp_path / "rev.json"
    rev.write_text(json.dumps([
        {"skill": "demo", "code": "A1", "label": "behavior-fix",
         "status": s, "evidence": "", "description": "d"}
        for s in statuses]), encoding="utf-8")
    wl = tmp_path / "wl.yaml"
    wl.write_text("findings:\n" + "".join(
        "  - skill: demo\n    code: A1\n    severity: drift\n"
        "    label: behavior-fix\n    description: d\n"
        "    reproducer:\n      type: bash\n      command: c\n"
        for _ in range(n)), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps(
        {"applied": {str(i): [["f", 1]] for i in applied_indices}}),
        encoding="utf-8")
    return rev, wl, state


def test_batch_verdicts_clean_pass(tmp_path):
    m = _load("batch_verdicts")
    rev, wl, state = _verdict_fixture(tmp_path, ["STALE", "STILL-FIRES"], [0])
    assert m.main([str(rev), str(wl), str(state)]) == 0


def test_batch_verdicts_expects_stale_for_skip_side_reproducers(tmp_path):
    """A skipped-as-already-fixed finding with a corrected predicate is
    expected to adjudicate STALE — without this, installing the honest
    predicate trips the 'unfixed but STALE' deviation."""
    m = _load("batch_verdicts")
    rev, wl, state = _verdict_fixture(tmp_path, ["STALE", "STILL-FIRES"], [])
    state2 = tmp_path / "state-skip.json"
    state2.write_text(json.dumps({
        "applied": {},
        "skip_updated_reps": {"0": {"type": "grep", "command": "c"}},
    }), encoding="utf-8")
    assert m.main([str(rev), str(wl), str(state2)]) == 0
    # and if the corrected predicate STILL fires, that's a deviation:
    rev2, _, _ = _verdict_fixture(tmp_path, ["STILL-FIRES", "STILL-FIRES"], [])
    assert m.main([str(rev2), str(wl), str(state2)]) == 1


def test_batch_verdicts_flags_unflipped_and_exempts(tmp_path):
    m = _load("batch_verdicts")
    rev, wl, state = _verdict_fixture(
        tmp_path, ["STILL-FIRES", "STILL-FIRES"], [0])
    # idx 0 applied but still fires -> deviation -> exit 1
    assert m.main([str(rev), str(wl), str(state)]) == 1
    # ...unless exempted (deliberate non-fix, e.g. FALSE_POSITIVE)
    state2 = tmp_path / "state2.json"
    state2.write_text(json.dumps({"applied": {}}), encoding="utf-8")
    assert m.main([str(rev), str(wl), str(state2),
                   "--expect-fires", "0,1"]) == 0


# ── direction_check ──────────────────────────────────────────────────

def _direction_fixture(tmp_path):
    """Two trees: pre carries the bug text, post carries the fix."""
    pre = tmp_path / "pre"
    post = tmp_path / "post"
    for root, body in ((pre, "the retired claim\n"), (post, "the corrected text\n")):
        d = root / "skills" / "demo"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(body, encoding="utf-8")
    return pre, post


def _wl_with_reproducer(tmp_path, rep_type, command, expected_exit=0):
    wl = tmp_path / "wl.yaml"
    wl.write_text(
        "findings:\n"
        "  - skill: demo\n    code: A1\n    severity: drift\n"
        "    label: behavior-fix\n    description: d\n"
        "    reproducer:\n"
        f"      type: {rep_type}\n"
        f"      command: {command}\n"
        f"      expected_exit: {expected_exit}\n",
        encoding="utf-8")
    return wl


def _state(tmp_path, applied=("0",)):
    s = tmp_path / "state.json"
    s.write_text(json.dumps({"applied": {i: [["f", 1]] for i in applied}}),
                 encoding="utf-8")
    return s


def test_direction_check_passes_fire_pre_quiet_post(tmp_path):
    m = _load("direction_check")
    pre, post = _direction_fixture(tmp_path)
    wl = _wl_with_reproducer(tmp_path, "grep",
                             "grep -q 'retired claim' skills/demo/SKILL.md")
    rc = m.main([str(wl), str(_state(tmp_path)), str(pre), str(post)])
    assert rc == 0


def test_direction_check_flags_inverted_direction(tmp_path):
    """grep_absent on the retired string fires only AFTER the fix — the
    2-of-18 / 2-of-16 authoring error this gate exists to catch."""
    m = _load("direction_check")
    pre, post = _direction_fixture(tmp_path)
    wl = _wl_with_reproducer(tmp_path, "grep_absent",
                             "grep -q 'retired claim' skills/demo/SKILL.md")
    rc = m.main([str(wl), str(_state(tmp_path)), str(pre), str(post)])
    assert rc == 1


def test_direction_check_flags_mention_grep_still_firing_post(tmp_path):
    """A predicate matching text present in BOTH trees (e.g. a fix that
    quotes the retired string to deny it) is STILL-FIRES-POST."""
    m = _load("direction_check")
    pre, post = _direction_fixture(tmp_path)
    wl = _wl_with_reproducer(tmp_path, "grep",
                             "grep -q 'the' skills/demo/SKILL.md")
    rc = m.main([str(wl), str(_state(tmp_path)), str(pre), str(post)])
    assert rc == 1


def test_direction_check_flags_stale_pre(tmp_path):
    """A predicate that never fired on the pre-fix tree is STALE-PRE."""
    m = _load("direction_check")
    pre, post = _direction_fixture(tmp_path)
    wl = _wl_with_reproducer(tmp_path, "grep",
                             "grep -q 'never present' skills/demo/SKILL.md")
    rc = m.main([str(wl), str(_state(tmp_path)), str(pre), str(post)])
    assert rc == 1


def test_direction_check_covers_skip_side_reproducers(tmp_path):
    m = _load("direction_check")
    pre, post = _direction_fixture(tmp_path)
    wl = _wl_with_reproducer(tmp_path, "grep",
                             "grep -q 'retired claim' skills/demo/SKILL.md")
    s = tmp_path / "state.json"
    s.write_text(json.dumps({
        "applied": {},
        "skip_updated_reps": {"0": {"type": "grep", "command": "x"}},
    }), encoding="utf-8")
    assert m.main([str(wl), str(s), str(pre), str(post)]) == 0
