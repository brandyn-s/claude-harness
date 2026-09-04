"""Tests for stale-checkout-before-analysis.py (PreToolUse:Read|Grep|Glob).

ADVISORY by design: exit 0 in every case. The discriminator is whether the advisory
text is present, never the exit code.

The fixtures build REAL git repos in a tmpdir rather than asserting against whatever
clone happens to be checked out, so the suite does not depend on any repo's current
behind-ness. The one exception is deliberate and marked.

The no-upstream case is the load-bearing one: 40 of 142 managed clones (28%) have no
upstream, `rev-list --count HEAD..@{upstream}` exits non-zero for them, and reading
that error as "0 behind" would silently disable the guard across a quarter of the
fleet while reading it as a fire would spam every one of them.
"""
import subprocess
from pathlib import Path

from conftest import make_glob_input, make_grep_input, run_hook

HOOK = "stale-checkout-before-analysis.py"
ADVISORY = "[stale-checkout-before-analysis] ADVISORY"
HOOKS_DIR = Path(__file__).resolve().parent.parent


def _run(payload: dict, session: str):
    """run_hook with a distinct session id so the per-repo cache never leaks."""
    return run_hook(HOOK, payload, env={"CLAUDE_SESSION_ID": session})


def _read_input(file_path: str) -> dict:
    return {"tool_name": "Read", "tool_input": {"file_path": file_path}}


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _commit(repo: Path, name: str, body: str):
    (repo / name).write_text(body, encoding="utf-8")
    _git("add", name, cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name, cwd=repo)


def _behind_repo(tmp_path: Path) -> Path:
    """A clone that is genuinely 2 commits behind its own upstream."""
    origin = tmp_path / "origin.git"
    _git("init", "-q", "--bare", str(origin))
    seed = tmp_path / "seed"
    _git("clone", "-q", str(origin), str(seed))
    _commit(seed, "a.txt", "1")
    _git("push", "-q", "-u", "origin", "HEAD", cwd=seed)

    work = tmp_path / "work"
    _git("clone", "-q", str(origin), str(work))
    _commit(seed, "b.txt", "2")
    _commit(seed, "c.txt", "3")
    _git("push", "-q", "origin", "HEAD", cwd=seed)
    _git("fetch", "-q", "origin", cwd=work)          # ref advances, HEAD does not
    return work


def test_advisory_fires_on_a_behind_checkout(tmp_path):
    work = _behind_repo(tmp_path)
    rc, _out, err = _run(_read_input(str(work / "a.txt")), "t-behind")
    assert rc == 0, "advisory must never block a read"
    assert ADVISORY in err
    assert "2 commit(s) behind" in err


def test_advisory_is_once_per_repo_per_session(tmp_path):
    """A 200-file sweep must produce one line, not two hundred."""
    work = _behind_repo(tmp_path)
    rc1, _o1, err1 = _run(_read_input(str(work / "a.txt")), "t-once")
    rc2, _o2, err2 = _run(_read_input(str(work / "a.txt")), "t-once")
    assert rc1 == 0 and rc2 == 0
    assert ADVISORY in err1
    assert ADVISORY not in err2, "second read in the same session must be cached"


def test_no_upstream_stays_silent(tmp_path):
    """rev-list exits non-zero -> UNKNOWN, which is neither '0 behind' nor a fire."""
    repo = tmp_path / "noupstream"
    repo.mkdir()
    _git("init", "-q", str(repo))
    _commit(repo, "f.txt", "x")
    rc, _out, err = _run(_read_input(str(repo / "f.txt")), "t-noup")
    assert rc == 0
    assert ADVISORY not in err


def test_repo_at_upstream_tip_stays_silent(tmp_path):
    origin = tmp_path / "o.git"
    _git("init", "-q", "--bare", str(origin))
    work = tmp_path / "attip"
    _git("clone", "-q", str(origin), str(work))
    _commit(work, "f.txt", "y")
    _git("push", "-q", "-u", "origin", "HEAD", cwd=work)
    rc, _out, err = _run(_read_input(str(work / "f.txt")), "t-tip")
    assert rc == 0
    assert ADVISORY not in err


def test_non_git_path_stays_silent(tmp_path):
    p = tmp_path / "plain"
    p.mkdir()
    (p / "f.txt").write_text("z", encoding="utf-8")
    rc, _out, err = _run(_read_input(str(p / "f.txt")), "t-plain")
    assert rc == 0
    assert ADVISORY not in err


def test_grep_and_glob_surfaces_also_fire(tmp_path):
    """Grep/Glob carry the path under `path`, not `file_path`."""
    work = _behind_repo(tmp_path)
    rc, _out, err = _run(make_grep_input("anything", str(work)), "t-grep")
    assert rc == 0
    assert ADVISORY in err
    rc, _out, err = _run(make_glob_input("*.txt", str(work)), "t-glob")
    assert rc == 0
    assert ADVISORY in err


def test_unrelated_tool_is_ignored(tmp_path):
    work = _behind_repo(tmp_path)
    rc, _out, err = _run(
        {"tool_name": "Write", "tool_input": {"file_path": str(work / "a.txt")}},
        "t-write")
    assert rc == 0
    assert ADVISORY not in err


def test_hook_never_blocks_even_on_malformed_input():
    for payload in ({}, {"tool_name": "Read"}, {"tool_name": "Read", "tool_input": {}},
                    {"tool_name": "Read", "tool_input": {"file_path": "relative/x"}}):
        rc, _out, _err = _run(payload, "t-malformed")
        assert rc == 0, payload


def test_hook_makes_no_network_call():
    """A fetch inside a Read hook is its own hazard; the source must not contain one."""
    src = (HOOKS_DIR / HOOK).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    # Comment lines legitimately mention `git fetch` in the remediation text; the
    # CODE must not invoke it. Checked after stripping comments for that reason.
    assert '"fetch"' not in code, "no fetch argument may appear in executed code"
    assert "GIT_TIMEOUT_S" in code, "git calls must be time-bounded"


def _load_hook_module():
    """Import the hook so its contract can be asserted directly, not just end-to-end."""
    import importlib.util
    import sys as _sys
    spec = importlib.util.spec_from_file_location("stale_checkout_probe", HOOKS_DIR / HOOK)
    assert spec is not None and spec.loader is not None, f"cannot load {HOOK}"
    mod = importlib.util.module_from_spec(spec)
    # Register under a THROWAWAY name and pop it in `finally`: a private copy leaves no
    # sys.modules state for sibling test files to inherit, and cannot be broken by one.
    _sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        _sys.modules.pop(spec.name, None)
    return mod


def test_behind_count_returns_None_not_zero_when_upstream_is_absent(tmp_path):
    """UNKNOWN must be None, distinct from a known 0.

    Mutation-driven: an earlier version of this file only asserted that the
    no-upstream case stays SILENT end-to-end. That assertion could not tell `None`
    from `0`, because both take the `n <= 0` branch — so a mutation returning 0 for
    the error case passed all nine tests. The spec is explicit that the error "must
    be treated as 'unknown, stay silent', NEVER as '0 behind'", and the distinction
    becomes load-bearing the moment anything downstream reports or thresholds on the
    count. Assert the contract at the function, where the two values differ.
    """
    mod = _load_hook_module()

    no_upstream = tmp_path / "noup"
    no_upstream.mkdir()
    _git("init", "-q", str(no_upstream))
    _commit(no_upstream, "f.txt", "x")
    assert mod.behind_count(no_upstream) is None, "absent upstream must be UNKNOWN"

    origin = tmp_path / "o2.git"
    _git("init", "-q", "--bare", str(origin))
    at_tip = tmp_path / "tip2"
    _git("clone", "-q", str(origin), str(at_tip))
    _commit(at_tip, "f.txt", "y")
    _git("push", "-q", "-u", "origin", "HEAD", cwd=at_tip)
    assert mod.behind_count(at_tip) == 0, "a real 0 must be 0, not None"

    behind = _behind_repo(tmp_path)
    assert mod.behind_count(behind) == 2


def test_registered_timeout_covers_the_worst_case(tmp_path):
    """The hook timeout and GIT_TIMEOUT_S are a RELATIONSHIP, not two literals.

    Pinning both sides as literals gives a change-DETECTOR, not an invariant-CHECKER:
    a lockstep edit walks straight through it (tdd-mutation-testing item 26). So DERIVE
    the bound from the hook's own constants and compare against the value actually
    registered in settings.json.

    History: this hook was first wired at 5s, which architecture-drift-check.py rejected
    against its 10s PreToolUse floor — the run-hook wrapper's start-up alone is a measured
    1.4-4.1s, before this hook makes a single git call. Raising GIT_TIMEOUT_S or adding a
    fifth git call must fail HERE rather than quietly eating the margin.
    """
    import json

    mod = _load_hook_module()
    worst_case = mod.WRAPPER_STARTUP_CEILING_S + mod.MAX_GIT_CALLS * mod.GIT_TIMEOUT_S
    assert mod.REGISTERED_TIMEOUT_S >= worst_case, (
        f"declared timeout {mod.REGISTERED_TIMEOUT_S}s < worst case {worst_case}s"
    )

    # The declared constant must match what is actually WIRED, in both files, or the
    # arithmetic above is describing a registration nobody uses.
    repo = HOOKS_DIR.parent
    for name in ("settings.json", "settings.example.json"):
        settings = json.loads((repo / name).read_text(encoding="utf-8"))
        wired = [
            h.get("timeout")
            for group in settings["hooks"]["PreToolUse"]
            for h in group.get("hooks", [])
            if h.get("args") == [HOOK]
        ]
        assert wired == [mod.REGISTERED_TIMEOUT_S], f"{name}: wired {wired}"
        assert wired[0] >= 10, f"{name}: below the drift gate's PreToolUse floor"

    # MAX_GIT_CALLS must not drift below the real call count, or the bound is too small.
    #
    # Count CALL SITES exactly rather than subtracting a guessed constant for the
    # definition line. The first version of this assertion did
    # `src.count("_git(") - 2`, which was off by one (there is 1 definition, not 2), so
    # it computed 3 <= 4 and a FIFTH git call would have computed 4 <= 4 and passed —
    # the drift guard would not have caught the drift it exists to catch.
    src = (HOOKS_DIR / HOOK).read_text(encoding="utf-8")
    call_sites = [
        line for line in src.splitlines()
        if "_git(" in line and not line.lstrip().startswith(("def ", "#"))
    ]
    assert len(call_sites) <= mod.MAX_GIT_CALLS, (
        f"{len(call_sites)} git call sites > MAX_GIT_CALLS={mod.MAX_GIT_CALLS} — raise "
        f"the constant and REGISTERED_TIMEOUT_S together:\n  "
        + "\n  ".join(s.strip() for s in call_sites)
    )
    assert len(call_sites) == mod.MAX_GIT_CALLS, (
        f"MAX_GIT_CALLS={mod.MAX_GIT_CALLS} overstates the {len(call_sites)} real call "
        "sites; an inflated bound silently pads the timeout margin"
    )
