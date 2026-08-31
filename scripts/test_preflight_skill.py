#!/usr/bin/env python3
"""Structural guard: bin/preflight-skill.py must stay in parity with validate.yml.

WHY THIS TEST EXISTS

`bin/preflight-skill.py` exists so a skill author runs every CI gate locally with
one command instead of picking a subset from memory. That only holds while the
aggregator MIRRORS the workflow. The moment CI grows a gate the aggregator lacks,
the tool becomes actively harmful: it reports "All gates passed" while a gate it
never ran is red in CI -- a false-clean, which is worse than no tool at all
(the author now has a reason NOT to check).

So the load-bearing assertion here is not "the script runs". It is:

  every validator command in validate.yml that a skills/ change can break
  is also a gate in preflight-skill.py, invoked with the SAME flags.

The flags matter as much as the command. Documented instances where a
flag-less local run went green while CI went red:
  - `validate-skill-chains.py` without `--strict`  -> dangling target exits 0
    (2026-07-26, one wasted cycle)
  - `validate-skills.py` without `--gate 13`       -> below-threshold skill passes
  - `audit-skill.py <one-skill>` instead of `--all` -> orphan-script drift missed
    (2026-07-21 PR #1647, macos leg)

Run: pytest scripts/test_preflight_skill.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO / "bin" / "preflight-skill.py"
WORKFLOW = REPO / ".github" / "workflows" / "validate.yml"
PRE_PUSH = REPO / ".githooks" / "pre-push"


def _load_gates():
    """Import the gate registry without executing main()."""
    sys.path.insert(0, str(REPO / "bin"))
    import importlib.util

    spec = importlib.util.spec_from_file_location("preflight_skill", PREFLIGHT)
    assert spec is not None and spec.loader is not None, f"cannot load {PREFLIGHT}"
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module: on Python 3.14, @dataclass
    # resolves string annotations by looking the module up in sys.modules, and a
    # module loaded under a synthetic name that isn't registered raises
    # AttributeError inside dataclasses._is_type.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return mod


# ---------------------------------------------------------------------------
# the file exists, is executable, and self-describes
# ---------------------------------------------------------------------------


def test_preflight_script_exists_and_is_executable():
    assert PREFLIGHT.is_file(), "bin/preflight-skill.py missing"
    # The pre-push hook invokes it via "$PY <path>", so the exec bit is not
    # strictly required -- but a non-executable CLI is a papercut for humans.
    #
    # PLATFORM-GUARDED: Windows has no POSIX permission bits, so st_mode & 0o111
    # is always falsy there and this assertion fails on the windows-2022 leg ONLY
    # (macOS + ubuntu pass). Exactly the shape rules/tdd-quality.md item 11
    # documents -- keep the assertion, guard it.
    if sys.platform != "win32":
        assert PREFLIGHT.stat().st_mode & 0o111, "preflight-skill.py is not executable"


def test_list_mode_runs_and_names_ci_steps():
    p = subprocess.run(
        [sys.executable, str(PREFLIGHT), "--list"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr
    # --list must map each gate to the CI step it mirrors; that mapping is how a
    # future maintainer notices drift at all.
    assert "CI STEP" in p.stdout
    assert "Architecture drift gate" in p.stdout


# ---------------------------------------------------------------------------
# PARITY: every skills-relevant CI validator is a gate, with matching flags
# ---------------------------------------------------------------------------

#: (substring that must appear in some gate's cmd, human name).
#: Each entry is a validator that validate.yml runs and that a skills/ change
#: can break. Flags are included deliberately -- see the module docstring.
REQUIRED_GATES = [
    ("scripts/validate-version-floor.py", None),
    ("scripts/runtime-qualification/validate_cross_session_settings.py", None),
    ("manifests/compile.py", "--check"),
    ("bin/reconcile-skill-tools.py", "--all"),
    ("scripts/validate-hook-paths.py", None),
    ("scripts/check-rule-context-budget.py", None),
    ("scripts/validate-agent-frontmatter.py", None),
    ("bin/architecture-drift-check.py", None),
    ("bin/audit-skill.py", "--strict"),
    ("scripts/validate-skills.py", "--gate"),
    ("scripts/validate-skills.py", "--triggers"),
    ("scripts/run-skill-evals.py", None),
    ("scripts/mutation-check-evals.py", "--all"),
    ("scripts/validate-skill-chains.py", "--strict"),
    ("pytest scripts/", "--collect-only"),
]


def test_every_required_ci_validator_is_a_gate():
    mod = _load_gates()
    flat = [" ".join(g.cmd) for g in mod.GATES]
    joined = "\n".join(flat)
    missing = []
    for script, flag in REQUIRED_GATES:
        hits = [c for c in flat if script in c]
        if not hits:
            missing.append(f"{script} (no gate invokes it)")
            continue
        if flag and not any(flag in c for c in hits):
            missing.append(f"{script} present but never with {flag!r}")
    assert not missing, (
        "preflight-skill.py has drifted from validate.yml:\n  "
        + "\n  ".join(missing)
        + f"\n\ncurrent gate commands:\n{joined}"
    )


def test_required_validators_are_actually_in_the_workflow():
    """Guard the guard: if CI drops a validator, REQUIRED_GATES must be updated.

    Without this, REQUIRED_GATES could pin a validator CI no longer runs, and the
    parity test above would enforce a stale contract forever.
    """
    wf = WORKFLOW.read_text(encoding="utf-8")
    absent = [s for s, _ in REQUIRED_GATES if s not in wf]
    assert not absent, (
        "REQUIRED_GATES names validators absent from validate.yml "
        f"(CI changed; update this test): {absent}"
    )


def test_gate_keys_are_unique():
    mod = _load_gates()
    keys = [g.key for g in mod.GATES]
    assert len(keys) == len(set(keys)), "duplicate gate key breaks --only selection"


def test_every_gate_records_the_ci_step_it_mirrors():
    mod = _load_gates()
    for g in mod.GATES:
        assert g.ci_step, f"gate {g.key} has no ci_step -- drift becomes untraceable"


def test_fast_tier_is_a_strict_subset_and_not_empty():
    mod = _load_gates()
    fast = [g for g in mod.GATES if not g.slow]
    slow = [g for g in mod.GATES if g.slow]
    assert fast, "fast tier is empty -- the pre-push hook would gate on nothing"
    assert slow, "no gate marked slow -- the fast/full split is then meaningless"
    assert len(fast) < len(mod.GATES)


# ---------------------------------------------------------------------------
# verdicts come from EXIT CODES, never from grepping a tool's prose
# (the durable rule from scripts/test_ci_gates_use_exit_codes.py, applied here)
# ---------------------------------------------------------------------------


def test_preflight_does_not_grep_tool_output_to_decide_pass_fail():
    src = PREFLIGHT.read_text(encoding="utf-8")
    # A gate decided by scanning stdout for a word is coupled to formatting.
    for bad in ('if "FAIL" in ', "if 'FAIL' in ", '.startswith("FAIL")'):
        assert bad not in src, (
            f"preflight-skill.py appears to gate on output text ({bad!r}); "
            "gate on returncode instead"
        )
    assert "returncode" in src, "preflight-skill.py must inspect returncode"


def test_no_gate_mutates_the_tree():
    """Preflight must be READ-ONLY -- the hook's ordering rationale depends on it.

    `audit-skill.py --all` implies --check-marketplace, whose freshness probe RUNS
    build-marketplace.py and thus WRITES marketplace/ + .claude-plugin/. Observed
    live 2026-07-28: a --fast run left 4 modified files behind, falsifying the
    "read-only, so a failure needs no cleanup" claim in both the hook and the test
    below. --no-marketplace-check restores it.
    """
    mod = _load_gates()
    for g in mod.GATES:
        cmd = " ".join(g.cmd)
        if "audit-skill.py" in cmd and "--all" in cmd:
            assert "--no-marketplace-check" in cmd, (
                "audit-skill --all implies --check-marketplace, which WRITES the tree; "
                "pass --no-marketplace-check to keep preflight read-only"
            )
        assert not g.mutates, (
            f"gate {g.key} is marked mutates=True; a mutating gate breaks the "
            "read-only contract the pre-push ordering relies on"
        )


def test_read_only_claim_holds_when_actually_run():
    """Empirical check: a real --fast run must leave `git status` unchanged.

    The assertion above is structural (reads the flags). This one RUNS the tool and
    compares git status before/after -- the only evidence that catches a NEW gate
    that mutates for some other reason.
    """
    before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout
    subprocess.run(
        [sys.executable, str(PREFLIGHT), "--fast", "--quiet-on-pass"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    after = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout
    assert before == after, (
        "a --fast preflight run CHANGED the working tree -- some gate mutates.\n"
        f"before:\n{before}\nafter:\n{after}"
    )


def test_missing_gate_script_is_a_failure_not_a_silent_skip():
    """A gate whose script vanished must FAIL, not quietly pass.

    This is the failure mode that turns a green run into a lie.
    """
    src = PREFLIGHT.read_text(encoding="utf-8")
    assert "FileNotFoundError" in src
    # the handler must return a falsy (failing) verdict
    m = re.search(r"except FileNotFoundError.*?return (\w+)", src, re.DOTALL)
    assert m, "no FileNotFoundError handler found in run_gate"
    assert m.group(1) == "False", (
        "a missing gate script must return False (fail), not True -- "
        f"got return {m.group(1)}"
    )


# ---------------------------------------------------------------------------
# the pre-push hook actually wires it up
# ---------------------------------------------------------------------------


def _hook_code() -> str:
    """The hook's EXECUTABLE lines only.

    Scanning the whole file is self-referential: the header comment block
    describes both checks by name, so a naive `.find()` lands in prose and any
    ordering / exit-code assertion becomes meaningless (this bit on first run).
    See rules/tdd-mutation-testing.md item 19 — scope the scan to the construct.
    """
    return "\n".join(
        ln for ln in PRE_PUSH.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_hook_code_extraction_excludes_comments():
    """Guard the helper: if this stops stripping comments, the two tests below lie."""
    code = _hook_code()
    assert "Bypass (rare, last resort)" not in code, "_hook_code() leaked a comment line"
    assert "set -e" in code, "_hook_code() stripped real code"


def test_preflight_is_not_gated_on_an_unrelated_scripts_existence():
    """The preflight check must not sit behind `[ -f scripts/build-marketplace.py ]`.

    REGRESSION GUARD. The hook originally early-exited 0 when build-marketplace.py
    was absent -- a guard written before preflight existed. That made the preflight
    check UNREACHABLE whenever that unrelated file was missing: a silently
    non-gating gate, which is worse than no gate (the author trusts a green push).
    Caught by this test on its first run, 2026-07-28.
    """
    code = _hook_code()
    i_pre = code.find("bin/preflight-skill.py")
    assert i_pre != -1, "no executable line invokes preflight-skill.py"
    before = code[:i_pre]
    # Any bare `-f <marketplace script> || exit 0` ahead of preflight re-introduces it.
    assert not re.search(
        r"\[\s*!?\s*-f\s+scripts/build-marketplace\.py\s*\][^\n]*exit 0", before
    ), (
        "an early-exit guard on build-marketplace.py precedes the preflight check, "
        "making preflight unreachable when that unrelated file is absent"
    )


def test_pre_push_hook_invokes_preflight_fast():
    """Assert on the EXECUTED line, not the file.

    Scanning the whole file passes on the header comment that merely *describes*
    `bin/preflight-skill.py --fast` -- proven by mutation: replacing the real
    invocation with a flag-less one left this test green until it was scoped to
    executable lines. (rules/tdd-mutation-testing.md item 19.)
    """
    code = _hook_code()
    m = re.search(r'"\$PY"\s+bin/preflight-skill\.py([^\n]*)', code)
    assert m, "no executable line invokes bin/preflight-skill.py via $PY"
    flags = m.group(1)
    assert "--fast" in flags, (
        "pre-push must invoke preflight with --fast so it stays ~10s; a ~40s hook "
        f"gets bypassed with --no-verify. Got flags: {flags!r}"
    )


#: The INVOCATION of each check -- not a mention of its path. Existence guards
#: (`[ -f bin/preflight-skill.py ]`) and remediation `echo`s also contain the
#: filenames, and anchoring on a bare filename silently matched the guard instead
#: of the call. That made the two tests below pass via an unintended path: the
#: slice swallowed the dirty-tree check's unrelated `exit 1`. Proven by mutation
#: (rules/tdd-mutation-testing.md item 20 -- a mutation that fails for the wrong reason,
#: here one that did not fail at all).
_RE_RUN_PREFLIGHT = re.compile(r'"\$PY"\s+bin/preflight-skill\.py')
_RE_RUN_MARKETPLACE = re.compile(r'"\$PY"\s+scripts/build-marketplace\.py')


def _invocations(code: str) -> tuple[re.Match[str], re.Match[str]]:
    pre = _RE_RUN_PREFLIGHT.search(code)
    mkt = _RE_RUN_MARKETPLACE.search(code)
    assert pre, "no executable line INVOKES bin/preflight-skill.py via $PY"
    assert mkt, "no executable line INVOKES scripts/build-marketplace.py via $PY"
    return pre, mkt


def test_pre_push_runs_preflight_before_the_mutating_marketplace_probe():
    """Order matters: the read-only check should precede the tree-mutating one."""
    pre, mkt = _invocations(_hook_code())
    assert pre.start() < mkt.start(), (
        "preflight must run before build-marketplace.py: preflight is read-only, so a "
        "failure leaves the tree untouched and needs no cleanup"
    )


def test_pre_push_hook_failure_path_exits_nonzero():
    """The preflight failure branch must `exit 1`, or the push is not gated."""
    code = _hook_code()
    pre, mkt = _invocations(code)
    seg = code[pre.start() : mkt.start()]
    assert "exit 1" in seg, (
        "no `exit 1` between the preflight invocation and the marketplace probe -- "
        "a failing preflight would print its error and let the push proceed"
    )


if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
