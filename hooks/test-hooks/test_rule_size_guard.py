"""Boundary tests for rule-size-guard.py.

Contract: PreToolUse:Write|Edit. Fires on `<root>/rules/*.md` for any
claude-config checkout — the deployed ~/.claude/rules, the main checkout, and
every worktree (excluding rules/incidents/, the extraction target). Thresholds
are on projected UTF-8 BYTE length, not character count:
WARN 35,000 (exit 0 + stderr), BLOCK 38,000 (exit 2). Bypass via
CLAUDE_RULE_SIZE_OVERRIDE=1. Boundaries tested at the exact `>` edges.
"""
import importlib.util
from pathlib import Path

from conftest import make_write_input, run_hook

HOOK = "rule-size-guard.py"
RULE = "~/.claude/rules/__audit_test_rule_size__.md"
INCIDENT = "~/.claude/rules/incidents/__audit_test_rule_size__.md"


def _write(path, n):
    return make_write_input(path, "x" * n)


def _guard_module():
    """Import the hyphenated hook so its pure predicates can be tested directly."""
    path = Path(__file__).resolve().parents[1] / HOOK
    spec = importlib.util.spec_from_file_location("rule_size_guard", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── boundary: BLOCK is `projected > 38000`, WARN is `> 35000` ──────────
#
# These run against an ISOLATED fake checkout, never the deployed
# ~/.claude/rules. The guard gained a corpus-wide ambient-budget ledger gate
# that is evaluated BEFORE the per-file thresholds, and the deployed corpus is
# live shared state (measured 2026-08-30: 188,539 of a 202,083 B ceiling, with
# concurrent sessions editing rules mid-run). Pointed at the deployed path these
# tests measured the WORLD, not the boundary:
#   - three failed, because the ledger gate blocked a 34,000 B write; and
#   - `test_block_just_over_threshold` PASSED FOR THE WRONG REASON — exit 2 came
#     from the ledger ceiling, so it could not have detected a broken per-file
#     threshold at all (tdd-quality item 20).
# `_fake_config_root` supplies a deliberately enormous ledger baseline so the
# delta gate stays out of the way and these keep measuring what they were
# written to measure. Deployed-path RECOGNITION is covered separately below, as
# a pure predicate with no live-state dependency.

def test_block_just_over_threshold(tmp_path):
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_block__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 38001))
    assert code == 2
    assert "BLOCKED" in err
    # Must be the PER-FILE verdict, not the corpus/ledger gate.
    assert "rule corpus" not in err, f"blocked by the wrong gate; stderr={err!r}"


def test_at_block_threshold_is_warn_not_block(tmp_path):
    # 38000 is NOT > 38000 → WARN path (exit 0), not BLOCK.
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_at_block__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 38000))
    assert code == 0
    assert "WARN" in err


def test_warn_just_over_threshold(tmp_path):
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_warn__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 35001))
    assert code == 0
    assert "WARN" in err


def test_under_warn_is_silent(tmp_path):
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_silent__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 34000))
    assert code == 0
    assert err.strip() == ""


# ── deployed-path recognition (pure predicate, no live corpus) ──────────

def test_deployed_rules_path_is_recognised():
    """The deployed fast path must still resolve; asserted without a live write.

    This is what the boundary tests above used to cover incidentally. Keeping it
    as a predicate check means a regression in the deployed fast path still fails
    loudly, without the assertion depending on the shared corpus's size.
    """
    guard = _guard_module()
    assert guard.is_rules_file(RULE)
    assert not guard.is_rules_file(INCIDENT)
    assert not guard.is_rules_file("~/.claude/rules/__audit_test__.txt")
    assert not guard.is_rules_file("/tmp/__audit_test__.md")


# ── scope: only rules/*.md, not incidents/, not other files ────────────

def test_incidents_subdir_excluded():
    # Big content under rules/incidents/ must NOT block (extraction target).
    code, _o, _e = run_hook(HOOK, _write(INCIDENT, 39000))
    assert code == 0


def test_non_rules_file_ignored():
    code, _o, _e = run_hook(HOOK, _write("/tmp/__audit_test__.md", 39000))
    assert code == 0


def test_non_md_rules_file_ignored():
    code, _o, _e = run_hook(HOOK, _write("~/.claude/rules/__audit_test__.txt", 39000))
    assert code == 0


# ── bypass override ────────────────────────────────────────────────────

def test_override_allows_oversize(monkeypatch):
    monkeypatch.setenv("CLAUDE_RULE_SIZE_OVERRIDE", "1")
    code, _o, _e = run_hook(HOOK, _write(RULE, 39000))
    assert code == 0


# ── scope: NON-deployed checkouts (worktrees, second clones) ───────────
# worktree-by-default MANDATES that rule edits happen in a worktree, and
# worktree-enforcement.py BLOCKS them in the ~/.claude main checkout on a
# non-main branch — so scoping this guard to the deployed path alone made it
# a no-op for rule authoring. Assert on the block REASON, not just a
# non-zero exit, so a block for an unrelated cause cannot read as a pass.

def _ledger(root, baseline=10_000_000, entries=None):
    """Write an ambient-budget ledger into a fake checkout.

    The guard fails LOUDLY without one (a default would make deleting the ledger
    indistinguishable from the gate passing), so every fake root needs it. The
    default baseline is deliberately enormous so the DELTA gate stays out of the way
    of the tests written for the ABSOLUTE 35,000/38,000 and 225,000/250,000
    thresholds -- those tests must keep measuring what they were written to measure.
    Tests that exercise the delta gate pass an explicit small baseline.
    """
    import json as _json

    (root / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "manifests" / "ambient-budget.json").write_text(
        _json.dumps(
            {
                "baseline_unconditional_bytes": baseline,
                "baseline_measured_at": "2026-08-26",
                "ledger": entries or [],
            }
        ),
        encoding="utf-8",
    )
    return root


def _fake_config_root(tmp_path, marker=True, ledger_baseline=10_000_000):
    """Build a checkout that looks like claude-config (or deliberately not)."""
    root = tmp_path / "cc-checkout"
    (root / "rules" / "incidents").mkdir(parents=True)
    if marker:
        (root / ".claude-plugin").mkdir()
    _ledger(root, baseline=ledger_baseline)
    return root


def test_worktree_rules_path_blocks_when_over(tmp_path):
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_wt__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 38001))
    assert code == 2, f"worktree rules path must be gated; got exit {code}, stderr={err!r}"
    assert "BLOCKED" in err


def test_worktree_rules_under_budget_is_silent(tmp_path):
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_wt__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 34000))
    assert code == 0
    assert err.strip() == ""


def test_worktree_incidents_subdir_excluded(tmp_path):
    # incidents/ is the extraction TARGET — it must stay ungated in a
    # worktree exactly as it is on the deployed path.
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "incidents" / "__audit_test_wt__.md"
    code, _o, _e = run_hook(HOOK, _write(str(target), 39000))
    assert code == 0


def test_unrelated_repo_rules_dir_not_gated(tmp_path):
    # A repo that merely ships a rules/ dir, with no claude-config marker,
    # must NOT be gated — this is what keeps the ancestor walk from
    # over-reaching.
    root = _fake_config_root(tmp_path, marker=False)
    target = root / "rules" / "__audit_test_wt__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 39000))
    assert code == 0, f"unrelated repo must not be gated; stderr={err!r}"


def test_settings_json_also_marks_a_config_root(tmp_path):
    # Second accepted marker, so a checkout without .claude-plugin/ (e.g.
    # the deployed dir shape) is still recognised.
    root = tmp_path / "cc-alt"
    (root / "rules").mkdir(parents=True)
    (root / "settings.json").write_text("{}")
    target = root / "rules" / "__audit_test_alt__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 38001))
    assert code == 2, f"settings.json marker must count; stderr={err!r}"
    assert "BLOCKED" in err


# ── BLOCK gates on "over budget AND non-decreasing", not size alone ─────
#
# A non-increasing edit to an already-over file is the REMEDY (extract to
# rules/incidents/, leave a pointer). Blocking it made the prescribed fix
# reachable only through CLAUDE_RULE_SIZE_OVERRIDE=1 — a remedy behind a
# bypass. Measured 2026-07-30: a -2,508 B extraction edit on
# verify-before-assuming.md (42,670 -> 40,162) was refused.

def _existing(root, name, n):
    """Create a real rules file of n bytes so current_byte_size() is nonzero."""
    target = root / "rules" / name
    target.write_text("y" * n, encoding="utf-8")
    return target


def _ambient_corpus(root, *, files=10, bytes_each=24800):
    """Create many individually-safe rules to exercise aggregate accounting."""
    for index in range(files):
        _existing(root, f"ambient-{index:02d}.md", bytes_each)


def test_reducing_edit_on_over_budget_file_is_allowed(tmp_path):
    root = _fake_config_root(tmp_path)
    target = _existing(root, "__audit_test_reduce__.md", 42670)
    # Still over BLOCK afterwards, but strictly smaller — the extraction shape.
    code, _o, err = run_hook(HOOK, _write(str(target), 40162))
    assert code == 0, f"a reducing edit must be allowed; got exit {code}, stderr={err!r}"
    assert "ALLOWED (reducing)" in err
    assert "-2,508" in err, f"advisory must name the delta; stderr={err!r}"


def test_reducing_edit_reports_remaining_distance_to_block(tmp_path):
    root = _fake_config_root(tmp_path)
    target = _existing(root, "__audit_test_reduce2__.md", 42000)
    code, _o, err = run_hook(HOOK, _write(str(target), 39000))
    assert code == 0
    assert "1,000" in err, f"must name bytes still over BLOCK; stderr={err!r}"


def test_reducing_below_block_is_only_a_warn(tmp_path):
    root = _fake_config_root(tmp_path)
    target = _existing(root, "__audit_test_reduce3__.md", 42000)
    code, _o, err = run_hook(HOOK, _write(str(target), 36000))
    assert code == 0
    assert "WARN" in err and "leaves" in err, f"stderr={err!r}"


def test_reducing_below_warn_is_silent(tmp_path):
    root = _fake_config_root(tmp_path)
    target = _existing(root, "__audit_test_reduce4__.md", 42000)
    code, _o, err = run_hook(HOOK, _write(str(target), 30000))
    assert code == 0
    assert not err.strip(), f"fully-resolved file must be silent; stderr={err!r}"


# NEGATIVE CONTROLS — the exemption must not swallow real violations.

def test_increasing_edit_on_over_budget_file_still_blocks(tmp_path):
    root = _fake_config_root(tmp_path)
    target = _existing(root, "__audit_test_grow__.md", 39000)
    code, _o, err = run_hook(HOOK, _write(str(target), 39500))
    assert code == 2, f"growing an over-budget file must still block; stderr={err!r}"
    assert "BLOCKED" in err


def test_crossing_block_from_under_still_blocks(tmp_path):
    root = _fake_config_root(tmp_path)
    target = _existing(root, "__audit_test_cross__.md", 30000)
    code, _o, err = run_hook(HOOK, _write(str(target), 38001))
    assert code == 2, f"crossing BLOCK must still block; stderr={err!r}"
    assert "BLOCKED" in err


def test_new_file_over_block_still_blocks(tmp_path):
    # current == 0 for a file that does not exist, so it can never be
    # "reducing" — otherwise every new oversize rule would slip through.
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_new__.md"
    code, _o, err = run_hook(HOOK, _write(str(target), 38001))
    assert code == 2, f"a NEW oversize rule must block; stderr={err!r}"
    assert "BLOCKED" in err


def test_write_projects_utf8_bytes_not_characters(tmp_path):
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_utf8_write__.md"

    code, _o, err = run_hook(
        HOOK, make_write_input(str(target), "é" * 19_001)
    )

    assert code == 2, f"38,002 UTF-8 bytes must block; stderr={err!r}"
    assert "38,002 bytes" in err


def test_edit_projects_utf8_bytes_not_characters(tmp_path):
    root = _fake_config_root(tmp_path)
    target = _existing(root, "__audit_test_utf8_edit__.md", 1)
    edit_input = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "y",
            "new_string": "é" * 19_001,
            "replace_all": False,
        },
    }

    code, _o, err = run_hook(HOOK, edit_input)

    assert code == 2, f"38,002 projected UTF-8 bytes must block; stderr={err!r}"
    assert "38,002 bytes" in err


def test_edit_preserves_crlf_bytes_when_deciding_whether_growth_is_reducing(tmp_path):
    root = _fake_config_root(tmp_path)
    target = root / "rules" / "__audit_test_crlf_edit__.md"
    target.write_bytes(b"y\r\n" * 19_000)  # 57,000 raw bytes on disk.
    edit_input = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "y",
            "new_string": "y" + ("x" * 1_000),
            "replace_all": False,
        },
    }

    code, _o, err = run_hook(HOOK, edit_input)

    assert code == 2, (
        "a CRLF-preserving edit that grows 57,000 -> 58,000 bytes must block; "
        f"stderr={err!r}"
    )
    assert "58,000 bytes" in err


# ── aggregate always-loaded corpus budget ──────────────────────────────

def test_many_small_rules_cannot_grow_corpus_past_aggregate_block(tmp_path):
    root = _fake_config_root(tmp_path)
    _ambient_corpus(root)  # 248,000 B; every individual file is below WARN.
    target = root / "rules" / "one-more-small-rule.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 3000))

    assert code == 2, f"aggregate growth past block must fail; stderr={err!r}"
    assert "always-loaded rule corpus" in err
    assert "251,000" in err
    assert "aggregate block" in err


def test_path_scoped_rule_does_not_consume_aggregate_budget(tmp_path):
    root = _fake_config_root(tmp_path)
    _ambient_corpus(root)
    target = root / "rules" / "scoped.md"
    scoped = "---\npaths:\n  - '**/*.py'\n---\n" + ("s" * 10_000)

    code, _o, err = run_hook(HOOK, make_write_input(str(target), scoped))

    assert code == 0
    assert "always-loaded rule corpus" not in err


def test_exact_aggregate_block_boundary_is_allowed(tmp_path):
    root = _fake_config_root(tmp_path)
    _ambient_corpus(root)  # 248,000 B
    target = root / "rules" / "boundary.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 2_000))

    assert code == 0, f"exactly 250,000 bytes must be allowed; stderr={err!r}"
    assert "250,000 bytes" in err
    assert "BLOCKED" not in err


def test_nested_rule_reference_is_excluded_from_aggregate_budget(tmp_path):
    root = _fake_config_root(tmp_path)
    _ambient_corpus(root)  # Close enough that an accidental inclusion matters.
    references = root / "rules" / "references"
    references.mkdir()
    target = references / "detail.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 3_000))

    assert code == 0, f"nested reference must not be aggregate-gated; stderr={err!r}"
    assert err.strip() == ""


def test_aggregate_reduction_is_allowed_while_still_over_block(tmp_path):
    root = _fake_config_root(tmp_path)
    _ambient_corpus(root, bytes_each=26_000)  # 260,000 B
    target = root / "rules" / "ambient-00.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 25_000))

    assert code == 0, f"aggregate remediation must be allowed; stderr={err!r}"
    assert "ALLOWED (aggregate reducing)" in err
    assert "260,000 -> 259,000" in err


def test_unmeasurable_aggregate_blocks_rule_edit(tmp_path):
    root = _fake_config_root(tmp_path)
    (root / "rules" / "broken.md").write_text(
        "---\npaths:\n  - '**'\n", encoding="utf-8"
    )
    target = root / "rules" / "new.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 100))

    assert code == 2
    assert "could not measure" in err


def test_manifest_records_dispatcher_wiring_and_budget_dependency():
    repo = Path(__file__).resolve().parents[2]
    manifest = (repo / "hooks" / "manifests" / "rule-size-guard.yaml").read_text(
        encoding="utf-8"
    )
    dispatcher = (repo / "hooks" / "write-edit-dispatcher.py").read_text(
        encoding="utf-8"
    )

    assert "NOT registered" not in manifest
    assert "hooks/rule_context_budget.py" in manifest
    assert '"rule-size-guard", "rule-size-guard.py"' in dispatcher


# ── ambient-budget delta gate ──────────────────────────────────────────
#
# The absolute thresholds above bound the corpus. These bound its GROWTH, which is
# the failure the delta gate exists for: a ceiling is a cliff, so repairs converge to
# just under it and the next append breaches it again. Measured before this shipped --
# git-hygiene.md went breach -> repair FOUR times in 16 days at ~9,800 of 10,000,
# across 13 dedicated cap-repair PRs.


def test_growth_past_the_ledger_ceiling_is_blocked(tmp_path):
    # baseline sits exactly at current usage, so any growth must be refused.
    root = _fake_config_root(tmp_path, ledger_baseline=20_000)
    _existing(root, "a.md", 10_000)
    _existing(root, "b.md", 10_000)
    target = root / "rules" / "c.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 500))

    assert code == 2, f"growth past the ledger ceiling must block; stderr={err!r}"
    assert "ledger ceiling" in err
    assert "20,000" in err
    # The refusal must carry the cheap way out, not just the verdict.
    assert "relocate" in err


def test_net_zero_relocation_is_allowed(tmp_path):
    """The escape hatch. Without this the gate is a wall, not a gate."""
    root = _fake_config_root(tmp_path, ledger_baseline=20_000)
    _existing(root, "a.md", 10_000)
    target = _existing(root, "b.md", 10_000)

    # Shrinking an ambient file can never breach a growth gate.
    code, _o, err = run_hook(HOOK, _write(str(target), 8_000))

    assert code == 0, f"a reducing edit must pass; stderr={err!r}"
    assert "ledger ceiling" not in err


def test_a_justified_ledger_entry_raises_the_ceiling(tmp_path):
    """Promotion works -- growth is possible, just explicit and recorded."""
    root = _fake_config_root(tmp_path, ledger_baseline=20_000)
    _ledger(
        root,
        baseline=20_000,
        entries=[
            {
                "date": "2026-08-26",
                "rule": "c.md",
                "reason": "second occurrence; must be ambient",
                "bytes": 1_000,
            }
        ],
    )
    _existing(root, "a.md", 10_000)
    _existing(root, "b.md", 10_000)
    target = root / "rules" / "c.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 500))

    assert code == 0, f"a justified promotion must be allowed; stderr={err!r}"


def test_a_negative_entry_ratchets_the_ceiling_down(tmp_path):
    """A relocation's savings become permanent rather than silently reusable."""
    root = _fake_config_root(tmp_path, ledger_baseline=20_000)
    _ledger(
        root,
        baseline=20_000,
        entries=[
            {
                "date": "2026-08-26",
                "rule": "relocated.md",
                "reason": "moved to a skill step; do not reuse the bytes",
                "bytes": -5_000,
            }
        ],
    )
    _existing(root, "a.md", 7_000)
    target = root / "rules" / "b.md"

    # Ceiling is now 15,000; 7,000 + 8,001 would exceed it.
    code, _o, err = run_hook(HOOK, _write(str(target), 8_001))

    assert code == 2, f"ratcheted ceiling must still bind; stderr={err!r}"
    assert "15,000" in err


def test_missing_ledger_warns_here_but_is_hard_in_ci(tmp_path):
    """Deliberate asymmetry: advisory in the hook, enforced in CI.

    The deployed ~/.claude can sit behind origin/main for days, so it may lack a
    ledger this change only just introduced. Blocking there would refuse EVERY rule
    edit on a stale checkout -- the >10% block-rate DoS verify-effectiveness forbids.
    Enforcement lives in scripts/test_context_policy_contracts.py, which runs where
    the ledger provably exists and RAISES without it, so the gate cannot be disabled
    by deleting the file. Asserted directly below.
    """
    root = _fake_config_root(tmp_path)
    (root / "manifests" / "ambient-budget.json").unlink()
    target = root / "rules" / "a.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 100))

    # ABSENT is SILENT: a not-yet-synced checkout would otherwise emit this warning
    # on every single rule write, which is alarm fatigue rather than information.
    assert code == 0, f"a stale checkout must not be DoS'd; stderr={err!r}"
    assert "ledger" not in err.lower(), f"absent ledger must be silent; stderr={err!r}"


def test_ci_side_loader_raises_on_a_missing_ledger(tmp_path):
    """The other half of the asymmetry: deleting the ledger cannot pass CI."""
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import rule_context_budget as rb

    missing = tmp_path / "nope" / "ambient-budget.json"
    try:
        rb.load_ambient_budget(missing)
    except rb.RuleContextBudgetError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("a missing ledger must raise, not default")


def test_unjustified_ledger_entry_is_rejected(tmp_path):
    """An entry with no reason is the same unreviewable bump the ledger prevents."""
    root = _fake_config_root(tmp_path)
    _ledger(
        root,
        baseline=20_000,
        entries=[{"date": "2026-08-26", "rule": "x.md", "reason": "   ", "bytes": 9_000}],
    )
    target = root / "rules" / "a.md"

    code, _o, err = run_hook(HOOK, _write(str(target), 100))

    # MALFORMED warns (present-but-broken is a real defect worth surfacing), and the
    # CI-side loader raises on it -- see test_ci_side_loader_raises_on_a_missing_ledger
    # and the unjustified-entry rejection in load_ambient_budget.
    assert code == 0, f"advisory in the hook; stderr={err!r}"
    assert "WARN" in err and "reason" in err.lower()
