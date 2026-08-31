"""Smoke tests for worktree-enforcement.py.

PreToolUse:Write|Edit|MultiEdit hook: blocks subagent writes to protected
repos unless running in a worktree. Main-session writes always pass.
"""
from pathlib import Path

from conftest import run_hook, windows_only

HOOK = "worktree-enforcement.py"

# Fixtures resolved via Path.home() so the test inputs match the hook's
# `os.path.expanduser("~/.claude")` resolution at runtime. Using a literal
# `$HOME` string here fails on Windows CI runners where the USERPROFILE is
# `C:\\Users\\runneradmin\\` rather than the author's local machine — the
# hook receives the literal `$HOME` and never matches it against the
# resolved protected-repo root.
_HOME = Path.home()
PROTECTED_FILE = str(_HOME / ".claude" / "hooks" / "example.py")
UNPROTECTED_FILE = str(_HOME.parent / "scratch" / "anything.py")
KB_RESEARCH_FILE = str(_HOME / "Documents" / "knowledge-base" / "research" / "2026-05-03-foo.md")
KB_PLANS_FILE = str(_HOME / "Documents" / "knowledge-base" / "plans" / "2026-05-03-bar.md")
KB_TOPICS_FILE = str(_HOME / "Documents" / "knowledge-base" / "topics" / "curated.md")


def _input(tool_name="Write", file_path=PROTECTED_FILE, agent_type=None,
           agent_id="test-agent", cwd=""):
    data = {
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path, "content": "x"},
        "cwd": cwd or str(Path.home()),
    }
    if agent_type is not None:
        data["agent_type"] = agent_type
        data["agent_id"] = agent_id
    return data


def test_non_write_tool_passes():
    rc, _, _ = run_hook(HOOK, {"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert rc == 0


def test_main_session_write_always_allowed():
    # No agent_type field → main session → always allow
    rc, _, _ = run_hook(HOOK, _input(agent_type=None))
    assert rc == 0


@windows_only
def test_subagent_write_to_protected_repo_blocked():
    rc, _, stderr = run_hook(HOOK, _input(agent_type="general-purpose"))
    assert rc == 2
    assert "worktree-guard" in stderr.lower() or "blocked" in stderr.lower()
    assert "claude-config" in stderr.lower()


def test_subagent_write_to_unprotected_path_allowed():
    rc, _, _ = run_hook(HOOK, _input(agent_type="general-purpose", file_path=UNPROTECTED_FILE))
    assert rc == 0


def test_subagent_write_with_skip_env_var_allowed(monkeypatch):
    monkeypatch.setenv("CLAUDE_SKIP_WORKTREE_CHECK", "1")
    rc, _, _ = run_hook(HOOK, _input(agent_type="general-purpose"))
    assert rc == 0


@windows_only
def test_subagent_write_from_worktree_path_allowed():
    # cwd contains ".claude/worktrees/" → _is_in_worktree short-circuits True
    rc, _, _ = run_hook(HOOK, _input(
        agent_type="general-purpose",
        cwd=str(_HOME / ".claude" / "worktrees" / "feat-test"),
    ))
    assert rc == 0


@windows_only
def test_edit_tool_also_enforced():
    rc, _, _ = run_hook(HOOK, _input(tool_name="Edit", agent_type="general-purpose"))
    assert rc == 2


@windows_only
def test_multiedit_tool_also_enforced():
    rc, _, _ = run_hook(HOOK, _input(tool_name="MultiEdit", agent_type="general-purpose"))
    assert rc == 2


def test_subagent_write_to_kb_research_allowed():
    rc, _, _ = run_hook(HOOK, _input(agent_type="general-purpose", file_path=KB_RESEARCH_FILE))
    assert rc == 0


def test_subagent_write_to_kb_plans_allowed():
    rc, _, _ = run_hook(HOOK, _input(agent_type="general-purpose", file_path=KB_PLANS_FILE))
    assert rc == 0


@windows_only
def test_subagent_write_to_kb_topics_still_blocked():
    rc, _, stderr = run_hook(HOOK, _input(agent_type="general-purpose", file_path=KB_TOPICS_FILE))
    assert rc == 2
    assert "knowledge-base" in stderr.lower()


def test_missing_file_path_passes():
    rc, _, _ = run_hook(HOOK, {
        "tool_name": "Write",
        "agent_type": "general-purpose",
        "agent_id": "a",
        "tool_input": {},
        "cwd": str(Path.home()),
    })
    assert rc == 0


def test_malformed_input_exits_cleanly():
    rc, _, _ = run_hook(HOOK, {})
    assert rc == 0


def _load_hook_module():
    import importlib.util
    import pathlib
    hook_path = pathlib.Path(__file__).resolve().parent.parent / "worktree-enforcement.py"
    spec = importlib.util.spec_from_file_location("worktree_enforcement_branchtest", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- check_shared_checkout_branch_state: the shared-checkout branch gate ---
# Unit-tested by monkeypatching _git_branch (the real `git branch` call against
# ~/.claude is non-deterministic in CI). Fires for main session AND subagent.

def _branch_input(file_path=None, tool_name="Write"):
    fp = file_path if file_path is not None else str(_HOME / ".claude" / "rules" / "foo.md")
    return {"tool_name": tool_name, "tool_input": {"file_path": fp, "content": "x"}, "cwd": str(_HOME)}


def test_branchgate_blocks_content_edit_on_feature_branch(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/something")
    code, stderr, _ = mod.check_shared_checkout_branch_state(_branch_input())
    assert code == 2
    assert "shared-checkout-guard" in stderr.lower()
    assert "feat/something" in stderr


def test_branchgate_allows_on_main(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "main")
    code, _, _ = mod.check_shared_checkout_branch_state(_branch_input())
    assert code == 0


def test_branchgate_allows_worktree_path_even_on_feature_branch(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/x")
    # EnterWorktree default lives UNDER ~/.claude/worktrees/ — exercises the
    # /worktrees/ exemption branch (path IS under claude_root, but is a worktree).
    wt = str(_HOME / ".claude" / "worktrees" / "cc-foo" / "rules" / "foo.md")
    code, _, _ = mod.check_shared_checkout_branch_state(_branch_input(file_path=wt))
    assert code == 0  # worktree edits are the correct isolated path


def test_branchgate_allows_transient_on_feature_branch(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/x")
    tr = str(_HOME / ".claude" / "settings.json")
    code, _, _ = mod.check_shared_checkout_branch_state(_branch_input(file_path=tr))
    assert code == 0  # session-state file, not gated


def test_branchgate_allows_non_claude_path(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/x")
    code, _, _ = mod.check_shared_checkout_branch_state(_branch_input(file_path=UNPROTECTED_FILE))
    assert code == 0


def test_branchgate_fail_open_when_branch_undeterminable(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: None)
    code, _, _ = mod.check_shared_checkout_branch_state(_branch_input())
    assert code == 0  # don't block legit work when git state is weird


def test_branchgate_skip_env_var_allows(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setenv("CLAUDE_SKIP_WORKTREE_CHECK", "1")
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/x")
    code, _, _ = mod.check_shared_checkout_branch_state(_branch_input())
    assert code == 0


def test_branchgate_non_write_tool_passes(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/x")
    code, _, _ = mod.check_shared_checkout_branch_state({"tool_name": "Bash", "tool_input": {}})
    assert code == 0


# --- WIRING: the branch-state gate must fire through check() (the DISPATCHED
# entry point — write-edit-dispatcher.py calls mod.check(), NOT main()). The
# original bug: the gate was wired into main() only, so the dispatcher never ran
# it. These tests fail if the gate ever regresses off the check() path. ---

def test_check_runs_branchgate_for_MAIN_session(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/x")
    # No agent_type → main session. The OLD check() returned 0 here (main
    # exempt); with the gate wired in, check() must BLOCK.
    code, stderr, _ = mod.check(_branch_input())
    assert code == 2
    assert "shared-checkout-guard" in stderr.lower()


def test_check_runs_branchgate_for_SUBAGENT(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "feat/x")
    data = dict(_branch_input())
    data["agent_type"] = "general-purpose"
    data["agent_id"] = "a"
    code, stderr, _ = mod.check(data)
    assert code == 2
    assert "shared-checkout-guard" in stderr.lower()


def test_check_allows_main_session_on_main(monkeypatch):
    mod = _load_hook_module()
    monkeypatch.setattr(mod, "_git_branch", lambda _d: "main")
    code, _, _ = mod.check(_branch_input())
    assert code == 0  # main session on main → both gates pass


def test_dispatcher_invokes_branchgate_end_to_end(monkeypatch):
    """End-to-end: the registered dispatcher (write-edit-dispatcher.py) _load()s
    worktree-enforcement and calls check() — confirm a feature-branch edit is
    blocked THROUGH the dispatcher, the real production path."""
    import importlib.util
    import pathlib
    disp_path = pathlib.Path(__file__).resolve().parent.parent / "write-edit-dispatcher.py"
    spec = importlib.util.spec_from_file_location("wed_test", disp_path)
    disp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(disp)
    wt = disp._load("worktree-enforcement", "worktree-enforcement.py")
    assert wt is not None and hasattr(wt, "check")
    monkeypatch.setattr(wt, "_git_branch", lambda _d: "feat/x")
    code, stderr, _ = wt.check(_branch_input())
    assert code == 2  # dispatcher's `mod.check(...)` path blocks the edit
    assert "shared-checkout-guard" in stderr.lower()


def test_protected_repos_loaded_from_json_not_hardcoded():
    """Regression: prior version hardcoded c:/users/you/... which
    silently no-op'd the guard on macOS/Linux. The map must now load from
    hooks/protected-repos.json so operator-portable paths work."""
    import importlib.util
    import pathlib
    import sys
    hook_path = pathlib.Path(__file__).resolve().parent.parent / "worktree-enforcement.py"
    spec = importlib.util.spec_from_file_location("worktree_enforcement_test", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    protected = mod.PROTECTED_REPOS
    # The JSON-driven map must contain at least the repos declared in
    # hooks/protected-repos.json local_paths (mcp-servers, mcp-infra, etc.).
    assert "mcp-servers" in protected
    assert "mcp-infra" in protected
    # And the resolved paths must not contain the hardcoded user name
    # — they must come from expanduser, which on this host resolves to
    # /home/user or similar, not c:/users/you.
    for repo, path in protected.items():
        if "you" in path.lower():
            # Only acceptable if HOME genuinely points there (i.e., we are
            # running on the original Windows machine).
            assert pathlib.Path.home().as_posix().lower().startswith("c:/users/you"), (
                f"PROTECTED_REPOS[{repo}] = {path} but HOME does not match — "
                "fallback hardcoded map is being used despite a valid JSON config"
            )
