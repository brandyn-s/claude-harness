"""Golden plan-structure tests for superplan (AUDIT-TRACKERS/02-golden-tests.md,
B8a F6: "riskiest coupling in the family").

superplan's Phase 4 output — the plan document — is consumed by supergoal's
scripts/parse_plan.py. superplan/references/planning-framework.md states the
Plan Structure Template "is the **literal shape** supergoal's parse_plan.py
consumes". Until now a malformed plan was only caught at runtime (exit 20 when
/supergoal is invoked). These tests pin the coupling at CI time by
round-tripping golden plan fixtures — written by following superplan's
SKILL.md / planning-framework.md emission instructions — through supergoal's
ACTUAL parser, invoked the same way supergoal's own golden tests invoke it
(subprocess, ``--reset --state-dir <tmp>``; see
skills/supergoal/tests/test_supergoal_golden.py).

The cross-skill read of supergoal's script is deliberate — it IS the pinned
contract. PARSE_PLAN below is computed relative to this test file, so if
supergoal moves or renames parse_plan.py the coupling test fails loudly
instead of the contract silently rotting.

Fixtures (tests/golden/):
    representative.plan.md  Full Plan Structure Template: every section the
                            prose mandates (Demo, Effort, Session Context,
                            Goal, Target-State Baseline + Phase 3.5 Baseline,
                            Domains, Constraints, Execution Path, phased
                            Steps with per-step fields, Dependency Summary,
                            Verification with Metric/Guard/Artifact-Probe/
                            Forbidden-Actions subsections, Falsifiers,
                            Execution).
    edge.plan.md            Minimal-but-valid: only the parser's required
                            trio — Demo line, ## Falsifiers (H2) with a list
                            item, and a fenced command block under the legacy
                            ``## Verification`` H2 fallback (which the
                            template documents as still supported).
    malformed.plan.md       Structure-critical headings at the wrong level
                            (Falsifiers at H1, Metric Commands at H2) —
                            forbidden by the template ("Do not silently drop
                            sections"); must be REJECTED.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
GOLDEN = TESTS_DIR / "golden"

# Cross-skill coupling pin: skills/superplan/tests/ -> skills/ ->
# supergoal/scripts/parse_plan.py. Relative path computed from this file.
SKILLS_ROOT = TESTS_DIR.parent.parent
PARSE_PLAN = SKILLS_ROOT / "supergoal" / "scripts" / "parse_plan.py"


def _run(*args, env=None, cwd=None):
    """Run a Python script; return (rc, stdout, stderr).
    Same invocation style as skills/supergoal/tests/test_supergoal_golden.py."""
    e = os.environ.copy()
    if env:
        e.update(env)
    r = subprocess.run(
        [sys.executable, *args],
        capture_output=True, text=True, env=e, cwd=cwd,
    )
    return r.returncode, r.stdout, r.stderr


def _parse(fixture_name, tmp_path):
    """Copy a golden fixture into tmp_path (parse_plan.py writes .attestation
    and .status.json siblings next to the plan — never pollute golden/), then
    run supergoal's parser against it with an isolated --state-dir.
    Returns (rc, stdout, stderr, plan_path, state_root)."""
    state_root = tmp_path / "supergoal-state"
    state_root.mkdir()
    plan = tmp_path / fixture_name
    shutil.copy(GOLDEN / fixture_name, plan)
    rc, out, err = _run(
        str(PARSE_PLAN), str(plan), "--reset", "--state-dir", str(state_root),
    )
    return rc, out, err, plan, state_root


def _load_state(state_root, plan):
    state_path = state_root / plan.stem / "state.json"
    assert state_path.exists(), f"state.json not created at {state_path}"
    return json.loads(state_path.read_text(encoding="utf-8"))


def test_cross_skill_coupling_target_exists():
    """The coupling this suite pins: supergoal's parser must live where
    superplan's contract says it does. If supergoal moves/renames
    scripts/parse_plan.py, this fails before any fixture test confuses the
    matter with a misleading FileNotFoundError."""
    assert PARSE_PLAN.exists(), (
        f"supergoal's parse_plan.py not found at {PARSE_PLAN} — the "
        f"superplan→supergoal plan-structure coupling target moved; update "
        f"both this suite and superplan/references/planning-framework.md"
    )


def test_representative_plan_round_trip(tmp_path):
    """A plan following the full Plan Structure Template parses with every
    field populated and ZERO warnings — the template's claim that it is 'the
    literal shape supergoal's parse_plan.py consumes' holds section by
    section."""
    rc, out, err, plan, state_root = _parse("representative.plan.md", tmp_path)
    assert rc == 0, f"parse_plan.py failed: rc={rc}\nstdout={out}\nstderr={err}"

    # The template includes every recommended section, so the parser must not
    # warn (warnings would mean the template's section names drifted from
    # what the parser greps for).
    assert "WARN:" not in err, f"template-conformant plan produced warnings:\n{err}"

    state = _load_state(state_root, plan)

    # Demo: the plan-level Demo line (first in the file) wins. The fixture
    # also carries per-step `Demo:` lines (SKILL.md Phase 4 "Demo statement
    # (for each task)") — pinned contract: parse_plan.py takes the FIRST
    # `Demo:` match, so per-step demos never shadow the plan-level one.
    assert state["demo"] == (
        "Indexed PSM graph reports METRIC HTTP_CALLS=30 (baseline 17) via "
        "bench/count_http_calls.py — observable by re-running the Metric "
        "Commands fenced block below."
    )

    # ## Falsifiers — one list item per phase.
    assert len(state["falsifiers"]) == 2, state["falsifiers"]
    assert "Phase A" in state["falsifiers"][0]
    assert "Phase B" in state["falsifiers"][1]

    # ### Metric Commands — both non-comment lines of the fenced block,
    # in order.
    assert state["metric_commands"] == [
        "go test ./internal/pipeline/ -run TestHTTPLinks -count=1",
        'echo "METRIC HTTP_CALLS=$(python3 bench/count_http_calls.py --repo psm)"',
    ]

    # ### Guard Commands / ### Artifact Probe / ### Forbidden Actions.
    assert state["guard_commands"] == ["go test ./... -count=1"]
    assert state["artifact_probe"] == [
        "python3 bench/dump_edges.py --type HTTP_CALLS --repo psm --limit 5"
    ]
    assert state["forbidden_actions"] == [
        "Bash(rm *)",
        "Edit(file_path=/etc/*)",
        "Bash(git push --force *)",
    ]

    # ### Phase 3.5 Baseline — "currently 17, expected 30" extracted as
    # numeric anchors.
    assert state["baseline"] == {"currently_N": 17.0, "expected_M": 30.0}

    # Effort: L → bounded supergoal budget table (L = 40 turns / 7200 s).
    assert state["effort"] == "L"
    assert state["turn_budget_total"] == 40
    assert state["time_budget_seconds"] == 7200

    # The declared metric name must be discoverable for prior-arc checks.
    assert "HTTP_CALLS" in state["metric_names"]

    # Side artifacts of a successful parse: SHA-256 attestation sibling
    # (SKILL.md Step 5a.1) and the .active pointer.
    attestation = plan.with_suffix(plan.suffix + ".attestation")
    assert attestation.exists(), "plan .attestation sibling not written"
    assert (state_root / ".active").exists(), ".active pointer not written"


def test_edge_minimal_plan_parses_with_warnings(tmp_path):
    """Minimal-but-valid: the fewest sections the parser contract allows —
    Demo line + ## Falsifiers + a command block under the LEGACY
    `## Verification` H2 heading (planning-framework.md: 'The legacy
    `Verification:` label-form is still supported'; parse_plan.py extends
    that to the H2-heading form the template itself uses). Pinned defaults:
    effort falls back to M (20 turns / 3600 s), baseline is None, and every
    recommended-but-missing section produces a WARN, not an error."""
    rc, out, err, plan, state_root = _parse("edge.plan.md", tmp_path)
    assert rc == 0, f"parse_plan.py failed: rc={rc}\nstdout={out}\nstderr={err}"

    state = _load_state(state_root, plan)

    assert state["demo"] == (
        "parse_plan.py accepts this fixture with only the required trio present"
    )
    assert len(state["falsifiers"]) == 1, state["falsifiers"]

    # Metric command extracted via the legacy ## Verification H2 fallback.
    assert state["metric_commands"] == ['echo "METRIC EDGE_OK=1"']
    assert "EDGE_OK" in state["metric_names"]

    # No Effort line → default M budgets; no Phase 3.5 Baseline → None.
    assert state["effort"] == "M"
    assert state["turn_budget_total"] == 20
    assert state["time_budget_seconds"] == 3600
    assert state["baseline"] is None

    # Recommended sections absent → exactly the three documented warnings
    # (degraded-but-running is the pinned contract for these).
    assert "no ### Guard Commands block" in err
    assert "no ### Artifact Probe block" in err
    assert "no ### Forbidden Actions block" in err


def test_malformed_wrong_heading_levels_rejected(tmp_path):
    """PINNED CONTRACT: a plan whose structure-critical headings are at the
    wrong level (Falsifiers at H1 instead of the mandated H2; Metric Commands
    at H2 instead of the mandated H3) is REJECTED outright — parse_plan.py
    exits 20 (EXIT_PARSE_FAILED, the 'parse-failed' row of
    supergoal/references/headless.md) and writes NO state, NO attestation,
    NO .active pointer. It does not degrade to a partial parse: a loop
    started with zero falsifiers and zero metric commands could never
    terminate on evidence, so refusal at setup time is the contract."""
    rc, out, err, plan, state_root = _parse("malformed.plan.md", tmp_path)
    assert rc == 20, f"expected exit 20 (parse-failed), got rc={rc}\nstderr={err}"

    # The rejection names exactly the two sections the wrong heading levels
    # hid — and does NOT complain about the Demo line (which is present and
    # well-formed; the failure is specifically the heading-level violation).
    assert "not supergoal-ready" in err
    assert "## Falsifiers section with list items" in err
    assert "### Metric Commands or Verification: code block" in err
    assert "Demo: line" not in err

    # Rejection happens before any state is bootstrapped.
    assert not (state_root / plan.stem).exists(), \
        "state dir must not be created for a rejected plan"
    assert not (state_root / ".active").exists(), \
        ".active pointer must not be written for a rejected plan"
    attestation = plan.with_suffix(plan.suffix + ".attestation")
    assert not attestation.exists(), \
        "attestation sibling must not be written for a rejected plan"
