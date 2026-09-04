#!/usr/bin/env python3
"""M1 -- install.sh menus were captured by command substitution.

THE DEFECT

`ask_choice()` printed the menu to STDOUT and then echoed the selection to
STDOUT, while all three callers captured it:

    choice=$(ask_choice "Install which rules?" "All" "Pick individually" "Skip")

Command substitution swallows stdout, so `$choice` was not "2" -- it was the
whole menu text with the digit glued on the end:

    $'\\nInstall which rules?\\n  1. All\\n  2. Pick individually\\n  3. Skip\\n2'

MEASURED consequence (probe, not inference): every `case "$choice" in 1)... 2)...`
dispatch fell through to `*)`, whose body is `info "Skipping rules"`. So the
installer prompted the user, accepted a choice, and then installed NOTHING --
for rules, skills AND hooks. The menu was also invisible while the user was
being asked to pick from it, because the substitution had eaten it.

THE FIX

Prompts and menus go to STDERR; only the machine-readable value goes to STDOUT.
That is the standard split for a function whose output is captured: stderr is
for the human, stdout is for the caller. `ask_yn` already worked because it
signals through its EXIT STATUS rather than stdout.

These tests drive the real `install.sh` functions in a subshell, so they assert
on observed behaviour rather than on the shape of the source.

Run: pytest scripts/test_install_menus.py -q
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
PROMPTS = REPO / "scripts" / "install_prompts.sh"

BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None or sys.platform == "win32",
    reason="install.sh is a bash script; no POSIX bash on this platform",
)


def run_snippet(snippet: str, stdin: str = "") -> subprocess.CompletedProcess:
    """Source the REAL prompt helpers, then run `snippet`.

    Sources scripts/install_prompts.sh -- the same file install.sh sources -- so
    these tests exercise production code, not a copy. install.sh itself cannot be
    sourced for this: it is a straight-line script with no main() guard, so
    sourcing it would perform a real install into ~/.claude. That untestability
    is why these two functions had no coverage and why the M1 defect survived.
    """
    assert BASH is not None  # guarded by pytestmark
    script = f'set -uo pipefail\nsource "{PROMPTS}"\n{snippet}\n'
    return subprocess.run(
        [BASH, "-c", script],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        cwd=str(REPO),
    )


def run_wire_hooks(settings: Path, *configs: str) -> subprocess.CompletedProcess:
    """Execute the same standalone wiring helper used by install.sh."""

    return subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "wire_hooks.py"),
            str(settings),
            *configs,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        cwd=str(REPO),
    )


DISPATCHER = "bash-pretooluse-dispatcher.py"
DISPATCHER_WIRING = "'PreToolUse|Bash|PowerShell|bash-pretooluse-dispatcher.py|30'"


def _dispatcher_hooks(src: str) -> list[str]:
    """The DISPATCHER_HOOKS array install.sh copies as one set."""
    m = re.search(r"\nDISPATCHER_HOOKS=\((.*?)\n\)", src, re.DOTALL)
    assert m, "install.sh no longer defines DISPATCHER_HOOKS"
    return m.group(1).split()


def _expand_dispatcher_hooks(names: list[str], src: str) -> list[str]:
    expanded = []
    for name in names:
        expanded.extend(_dispatcher_hooks(src) if name == '"${DISPATCHER_HOOKS[@]}"' else [name])
    return expanded


def _hosted_by_dispatcher() -> list[str]:
    """The six hook files hooks/bash-pretooluse-dispatcher.py runs in-process
    (its GUARDS table, in order)."""
    text = (REPO / "hooks" / DISPATCHER).read_text(encoding="utf-8")
    return re.findall(r'\(\s*"[a-z0-9_-]+"\s*,\s*"([a-z0-9_-]+\.py)"\s*,\s*"(?:closed|warn|open)"\s*\)', text)


def test_installer_sources_the_helpers_under_test():
    """Guard against the tests drifting onto a copy.

    If install.sh ever inlines its own ask_choice again, these tests would keep
    passing against an unused file -- a proxy assertion (rules/tdd-quality.md
    item 18). Pin the wiring instead.
    """
    src = INSTALLER.read_text(encoding="utf-8")
    assert "scripts/install_prompts.sh" in src, (
        "install.sh no longer sources scripts/install_prompts.sh, so these tests "
        "are validating a file the installer does not use"
    )
    assert "ask_choice() {" not in src, (
        "install.sh redefines ask_choice inline; the tested definition is shadowed"
    )


def test_installer_preflights_claude_version_and_sets_runtime_floor():
    src = INSTALLER.read_text(encoding="utf-8")
    assert "check_claude_version" in src
    assert 'scripts/check_claude_version.py' in src
    assert "ensure_runtime_floor" in src
    assert "--ensure-minimum-version" in src
    assert 'settings["minimumVersion"] = MINIMUM_VERSION' not in src


def test_installer_rejects_an_installed_claude_below_the_floor(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text("#!/usr/bin/env bash\necho '2.1.222 (Claude Code)'\n", encoding="utf-8")
    claude.chmod(0o755)
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [BASH, str(INSTALLER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        cwd=REPO,
        env=env,
    )

    assert result.returncode != 0
    assert "below the required architecture floor 2.1.223" in result.stdout


# ---------------------------------------------------------------------------
# the regression this fix exists for
# ---------------------------------------------------------------------------
def test_ask_choice_captures_only_the_selection():
    """THE core negative test: `$(ask_choice ...)` must yield just the digit.

    Pre-fix this captured the entire rendered menu plus the digit, so every
    numbered branch fell through to the skip default.
    """
    proc = run_snippet(
        'choice=$(ask_choice "Pick one" "Alpha" "Beta" "Gamma"); '
        'printf "CAPTURED[%s]" "$choice"',
        stdin="2\n",
    )
    assert "CAPTURED[2]" in proc.stdout, (
        "ask_choice leaked its menu into the captured value:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def test_numbered_branch_is_reachable_through_substitution():
    """The consequence test: the dispatch must actually reach branch 2.

    Asserting on the captured string alone would not prove the installer works;
    this exercises the same `case` shape the three callers use.
    """
    proc = run_snippet(
        'choice=$(ask_choice "Pick one" "Alpha" "Beta" "Gamma"); '
        'case "$choice" in '
        '1) echo "BRANCH_ONE" ;; '
        '2) echo "BRANCH_TWO" ;; '
        '*) echo "BRANCH_DEFAULT" ;; '
        'esac',
        stdin="2\n",
    )
    assert "BRANCH_TWO" in proc.stdout, (
        "numbered choice did not reach its branch (pre-fix: always default):\n"
        f"stdout={proc.stdout!r}"
    )
    assert "BRANCH_DEFAULT" not in proc.stdout


def test_menu_is_visible_to_the_user():
    """A prompt the user cannot see is not a prompt.

    The menu must reach the terminal (stderr) even while stdout is captured --
    otherwise the user is asked to choose from an invisible list.
    """
    proc = run_snippet(
        'choice=$(ask_choice "Install which rules?" "All" "Pick individually" "Skip")',
        stdin="1\n",
    )
    assert "Install which rules?" in proc.stderr, (
        "menu did not reach stderr, so it is invisible during capture:\n"
        f"stderr={proc.stderr!r}"
    )
    for label in ("All", "Pick individually", "Skip"):
        assert label in proc.stderr, f"option {label!r} missing from the menu"


def test_every_option_number_is_selectable():
    """Boundary check across the whole menu, not just one representative value.

    Threshold/branch code gets tested AT every boundary (rules/tdd-quality.md
    item 8): first and last options are where an off-by-one lives.
    """
    for n in (1, 2, 3):
        proc = run_snippet(
            'choice=$(ask_choice "Pick" "A" "B" "C"); printf "GOT[%s]" "$choice"',
            stdin=f"{n}\n",
        )
        assert f"GOT[{n}]" in proc.stdout, (
            f"option {n} not selectable: stdout={proc.stdout!r}"
        )


def test_empty_input_does_not_capture_the_menu():
    """A bare Enter must yield an empty value, not a menu-shaped string.

    Pre-fix an empty answer still captured the full menu text, so the `*)`
    default fired for a reason unrelated to what the user did -- indistinguishable
    from a deliberate skip.
    """
    proc = run_snippet(
        'choice=$(ask_choice "Pick" "A" "B"); printf "GOT[%s]" "$choice"',
        stdin="\n",
    )
    assert "GOT[]" in proc.stdout, (
        f"empty input captured non-empty value: stdout={proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# M2 -- the collision inventory checked fewer files than the copy wrote
# ---------------------------------------------------------------------------
def test_starter_collision_inventory_covers_every_copied_file():
    """The overwrite prompt must know about every file it is about to overwrite.

    The inventory and the copy loop were two hand-maintained lists and had
    drifted: 5 paths checked (1 rule + 4 hooks) versus 11 files written. A user
    with local edits to diagnose-before-fix.md or hook_input.py lost them
    silently -- and the guard could still report "existing files kept" having
    never looked at 6 of the files it clobbered.

    Asserting on the derivation (one manifest feeding both) rather than counting
    two lists, because equal counts would not prove the same SET.
    """
    src = INSTALLER.read_text(encoding="utf-8")
    assert "starter_files+=(\"rules/$rule\")" in src, (
        "collision inventory is no longer derived from the rules manifest"
    )
    assert "starter_files+=(\"hooks/$hook\")" in src, (
        "collision inventory is no longer derived from the hooks manifest"
    )
    # The copy loops must iterate the SAME arrays the inventory was built from.
    assert 'for rule in "${starter_rules[@]}"' in src, (
        "starter rule copy loop no longer iterates the shared manifest"
    )
    assert 'for hook in "${starter_hooks[@]}"' in src, (
        "starter hook copy loop no longer iterates the shared manifest"
    )
    # And no re-introduced hardcoded inventory.
    assert "for f in rules/check-before-change.md hooks/" not in src, (
        "a hardcoded collision inventory was reintroduced; it will drift again"
    )


def test_starter_kit_files_all_exist():
    """Every file the starter kit copies must exist in the repo.

    A missing source turns `cp` into a hard failure under `set -e`, aborting the
    install partway -- the same class as M3's dangling skill names.
    """
    src = INSTALLER.read_text(encoding="utf-8")
    missing = []
    duplicates = []
    for array, subdir in (("starter_rules", "rules"), ("starter_hooks", "hooks")):
        m = re.search(rf"{array}=\((.*?)\n    \)", src, re.DOTALL)
        assert m, f"could not parse the {array} manifest out of install.sh"
        names = _expand_dispatcher_hooks(m.group(1).split(), src)
        duplicates.extend(
            f"{subdir}/{name}" for name in names if names.count(name) > 1
        )
        for name in names:
            if not (REPO / subdir / name).is_file():
                missing.append(f"{subdir}/{name}")
    assert missing == [], f"starter kit references missing files: {missing}"
    assert duplicates == [], f"starter kit references duplicate files: {duplicates}"


def test_full_hook_install_deploys_and_wires_config_change_guard():
    """The full installer must preserve the runtime settings-integrity boundary."""

    src = INSTALLER.read_text(encoding="utf-8")
    full_bundle = re.search(
        r"2\) hooks=\((.*?)\)\s*# Timeouts below",
        src,
        re.DOTALL,
    )
    assert full_bundle, "could not parse the full hook bundle"
    assert "config-change-validate.py" in full_bundle.group(1)
    assert (
        "ConfigChange|user_settings|project_settings|local_settings|"
        "config-change-validate.py|30"
    ) in src


def test_full_hook_install_produces_self_validating_protected_registry(tmp_path):
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [BASH, str(INSTALLER)],
        input="n\nn\n3\n8\n2\ny\nn\nn\nn\nn\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        cwd=REPO,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    config_dir = tmp_path / ".claude"
    settings_path = config_dir / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    protected = (
        (
            "ConfigChange",
            "user_settings|project_settings|local_settings",
            "config-change-validate.py",
            30,
        ),
        # The two Bash guards are carried by the dispatcher (the shape the
        # repository's settings.json has used since 2026-09-03); the registry
        # in config-change-validate.py accepts either that or the direct form.
        ("PreToolUse", "Bash|PowerShell", "bash-pretooluse-dispatcher.py", 30),
        ("PreToolUse", "Write|Edit", "write-edit-dispatcher.py", 30),
        ("PostToolUse", "Write|Edit", "post-write-edit.py", 30),
        ("SessionStart", None, "session-start.py", 30),
        ("SessionEnd", ".*", "session-end.py", 5),
    )
    for event, matcher, script, timeout in protected:
        matching = [
            hook
            for group in settings["hooks"].get(event, [])
            if group.get("matcher") == matcher
            for hook in group.get("hooks", [])
            if hook.get("command") == str(config_dir / "hooks" / "run-hook")
            and hook.get("args") == [script]
            and hook.get("timeout") == timeout
        ]
        assert matching, f"missing protected registration: {event}/{script}"
        assert (config_dir / "hooks" / script).is_file(), script
    registered = {
        hook["args"][0]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    }
    assert not registered & {"bash-security-guard.py", "destructive-ops-guard.py"}, (
        "the guards run inside the dispatcher; wiring them directly too would run them twice"
    )
    for script in _dispatcher_hooks(INSTALLER.read_text(encoding="utf-8")):
        assert (config_dir / "hooks" / script).is_file(), f"dispatcher set incomplete: {script}"

    validator = subprocess.run(
        [sys.executable, str(config_dir / "hooks" / "config-change-validate.py")],
        input=json.dumps(
            {
                "hook_event_name": "ConfigChange",
                "source": "user_settings",
                "file_path": str(settings_path),
            }
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
        env=env,
    )
    assert validator.returncode == 0, validator.stderr
    assert validator.stdout == ""


def test_installer_wires_hooks_through_the_trusted_absolute_runner(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{}", encoding="utf-8")

    proc = run_wire_hooks(
        settings,
        "ConfigChange|user_settings|project_settings|local_settings|"
        "config-change-validate.py|30",
    )

    assert proc.returncode == 0, proc.stderr
    config = json.loads(settings.read_text(encoding="utf-8"))
    assert config["hooks"]["ConfigChange"] == [
        {
            "matcher": "user_settings|project_settings|local_settings",
            "hooks": [
                {
                    "type": "command",
                    "command": str(settings.parent / "hooks" / "run-hook"),
                    "args": ["config-change-validate.py"],
                    "timeout": 30,
                }
            ],
        }
    ]


def test_recommended_starter_installs_runnable_exec_form_hooks(tmp_path):
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [BASH, str(INSTALLER)],
        # fresh profile, skip operator overlay, starter core, wire hooks,
        # skip repo githooks, stop before optional components
        input="y\nn\ny\ny\nn\nn\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        cwd=REPO,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    config = tmp_path / ".claude"
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    assert settings["minimumVersion"] == "2.1.223"
    registrations = [
        (event, hook)
        for event, groups in settings["hooks"].items()
        for group in groups
        for hook in group["hooks"]
        if hook.get("type") == "command"
    ]
    assert len(registrations) == 4  # dispatcher, config-guard, read-deny-guard, result-injection-guard
    for event, hook in registrations:
        command = Path(hook["command"])
        assert command.is_file(), f"{event}: missing {command}"
        assert os.access(command, os.X_OK), f"{event}: not executable {command}"
        executed = subprocess.run(
            [hook["command"], *hook["args"]],
            input=json.dumps({"hook_event_name": event}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
            cwd=config,
            env={**env, "CLAUDE_CONFIG_DIR": str(config)},
        )
        assert executed.returncode == 0, (
            f"{event}: starter hook failed: stdout={executed.stdout!r} "
            f"stderr={executed.stderr!r}"
        )


def test_declined_partial_starter_collision_does_not_wire_missing_hooks(tmp_path):
    config = tmp_path / ".claude"
    (config / "rules").mkdir(parents=True)
    (config / "rules" / "outcome-over-verification.md").write_text(
        "local edit\n", encoding="utf-8"
    )
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [BASH, str(INSTALLER)],
        input="n\ny\nn\ny\nn\nn\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        cwd=REPO,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    assert settings.get("hooks", {}) == {}
    assert "not wiring starter hooks" in (result.stdout + result.stderr).lower()


def test_hook_autowiring_uses_absolute_exec_form():
    """Installed hooks must not depend on a shell expanding HOME.

    The installer embeds the merger as Python, so pin the generated object
    contract here: an absolute run-hook executable plus a separate argv list.
    This catches regressions back to ``python /path/hook.py`` shell strings.
    """
    src = INSTALLER.read_text(encoding="utf-8")
    assert '"$SCRIPT_DIR/scripts/wire_hooks.py"' in src
    assert '"$settings_file" "${configs[@]}"' in src
    assert 'command = f"{python_path} {hooks_dir}{hook_file}"' not in src


# ---------------------------------------------------------------------------
# M3 -- the skills menu advertised stale counts and dead skill names
# ---------------------------------------------------------------------------
def _roster(name: str) -> list[str]:
    src = INSTALLER.read_text(encoding="utf-8")
    m = re.search(rf"local {name}=\((.*?)\)\n", src, re.DOTALL)
    assert m, f"roster {name!r} not found in install.sh"
    return m.group(1).split()


ROSTERS = ("planning", "security", "knowledge", "codeintel", "research")


def test_every_offered_skill_exists():
    """The menu must not offer skills the repo does not have.

    Measured pre-fix: writing-plans, dispatching-parallel-agents and handoff
    (named in two categories) do not exist anywhere in the repo under any name,
    so those copies were guaranteed misses.
    """
    available = {p.parent.name for p in (REPO / "skills").glob("*/SKILL.md")}
    assert available, "no skills found; the fixture itself is wrong"
    dangling = {
        r: [s for s in _roster(r) if s not in available] for r in ROSTERS
    }
    offenders = {k: v for k, v in dangling.items() if v}
    assert offenders == {}, f"menu offers nonexistent skills: {offenders}"


def test_menu_counts_are_computed_not_hardcoded():
    """A hardcoded count is what drifted; the fix is to derive it.

    Pre-fix the menu advertised "All portable skills (51)" against a tree of
    105, plus three wrong category counts. Asserting the counts are DERIVED is
    stronger than asserting today's numbers, which would need editing every time
    a skill lands.
    """
    src = INSTALLER.read_text(encoding="utf-8")
    assert '"All portable skills (${#all_skills[@]})"' in src, (
        "the 'All' count is not computed from the discovered skill list"
    )
    for roster in ROSTERS:
        assert f"${{#{roster}[@]}} skills" in src, (
            f"category {roster!r} does not compute its own count"
        )
    # Scan only ask_choice ARGUMENT lines, not the whole file: this test's own
    # docstring quotes the retired hardcoded string, and a naive whole-file regex
    # matches that quotation and fails on a clean tree.
    arg_lines = [
        ln for ln in src.splitlines()
        if "portable skills" in ln and "#" not in ln.split('"')[0]
    ]
    offenders = [ln.strip() for ln in arg_lines if re.search(r"\(\d+\)", ln)]
    assert offenders == [], (
        "a hardcoded 'All portable skills (N)' count was reintroduced: " + str(offenders)
    )


def test_ask_yn_still_signals_through_exit_status():
    """Regression guard on the function that was already correct.

    `ask_yn` communicates via exit status, so it must NOT start echoing to
    stdout while ask_choice is being changed around it.
    """
    yes = run_snippet('if ask_yn "Proceed?"; then echo YES; else echo NO; fi', stdin="y\n")
    assert "YES" in yes.stdout, yes.stdout
    no = run_snippet('if ask_yn "Proceed?"; then echo YES; else echo NO; fi', stdin="n\n")
    assert "NO" in no.stdout, no.stdout
    # The prompt itself must not contaminate stdout beyond the branch marker.
    assert yes.stdout.strip() == "YES", (
        f"ask_yn leaked prompt text to stdout: {yes.stdout!r}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------------------
# Review 2026-09-03 -- shared skill assets and the Python floor
# ---------------------------------------------------------------------------
def test_shared_skill_assets_ship_with_any_skill_selection():
    """`skills/_shared/` is referenced by ~60 skills, but the copy was gated on
    three skills (stig-assess, stig-verify, security-alerts) that were removed
    from this export -- so no menu path ever installed it."""
    src = INSTALLER.read_text(encoding="utf-8")
    body = src[src.index("install_skills() {"):src.index("install_hooks() {")]
    assert "stig-assess" not in body and "security-alerts" not in body, (
        "the _shared copy is still gated on skills this repo does not ship"
    )
    lines = body.splitlines()
    copy_lines = [i for i, line in enumerate(lines) if 'files+=("skills/_shared")' in line]
    assert len(copy_lines) == 1, "expected exactly one _shared copy in install_skills"
    assert "${#files[@]}" in lines[copy_lines[0] - 1], (
        "the _shared copy must be conditioned on at least one skill being installed"
    )


def test_installer_states_the_real_python_floor():
    """install-profile.py imports datetime.UTC (3.11+) and the doctor requires
    3.10+; the installer told users 3.8+ and never checked."""
    src = INSTALLER.read_text(encoding="utf-8")
    assert "Python 3.8+" not in src
    assert "(3, 11)" in src


# ---------------------------------------------------------------------------
# 2026-09-03 -- every installer path wires the Bash dispatcher, never the guards
# ---------------------------------------------------------------------------
def test_dispatcher_hook_set_matches_the_dispatcher_and_exists():
    """install.sh copies the dispatcher and the six hooks it runs as ONE set.

    The list is hand-written in bash, so pin it to the dispatcher's own GUARDS
    table: a hook added to (or dropped from) the dispatcher without updating the
    installer would ship a dispatcher that crashes on a missing sibling.
    """
    src = INSTALLER.read_text(encoding="utf-8")
    hosted = _hosted_by_dispatcher()
    assert len(hosted) == 6, hosted
    assert _dispatcher_hooks(src) == [DISPATCHER, *hosted]
    for name in _dispatcher_hooks(src):
        assert (REPO / "hooks" / name).is_file(), name


def test_no_installer_path_wires_the_bash_guards_directly():
    """The starter kit, the fresh-laptop bundle and the author bundle all register
    the dispatcher on Bash|PowerShell at the live timeout; none registers
    bash-security-guard.py or destructive-ops-guard.py on its own (that shape is
    accepted from pre-dispatcher installs by config-change-validate.py, but no
    longer produced)."""
    src = INSTALLER.read_text(encoding="utf-8")
    assert "|bash-security-guard.py|" not in src
    assert "|destructive-ops-guard.py|" not in src
    assert src.count(DISPATCHER_WIRING) == 3, src.count(DISPATCHER_WIRING)


def test_every_hook_bundle_names_files_that_exist():
    """A missing source now aborts the copy (by design), so every name in the two
    fixed bundles and the always-shipped library list must exist in hooks/."""
    src = INSTALLER.read_text(encoding="utf-8")
    body = src[src.index("install_hooks() {"):src.index("wire_hooks() {")]
    names = []
    for bundle in ("1", "2"):
        m = re.search(rf"{bundle}\) hooks=\(([^)]*)\)", body)
        assert m, f"could not parse hook bundle {bundle}"
        names += _expand_dispatcher_hooks(m.group(1).split(), src)
        assert DISPATCHER in names, f"bundle {bundle} does not ship the dispatcher"
    shared = re.search(r"for shared in ([^;]+); do", body)
    assert shared, "could not parse the shared library list"
    names += shared.group(1).split()
    assert "manifest_metrics.py" in names, "three of the six dispatcher hooks import it"
    missing = [n for n in names if not (REPO / "hooks" / n).is_file()]
    assert missing == [], f"hook bundles name missing files: {missing}"


def test_fresh_laptop_hook_bundle_installs_a_working_dispatcher(tmp_path):
    """End to end: bundle 1 lands the dispatcher with its six hooks and their
    libraries, wires it on Bash|PowerShell, and the INSTALLED copy blocks a
    catastrophic command through run-hook (so the set really works together)."""
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("CLAUDE_BASH_POLICY_PACKS", None)  # fresh-laptop: catastrophic core only
    # skip profile, skip starter core, skip rules, skip skills, fresh-laptop hooks,
    # wire, no agents, no agent-memory, no ARCHITECTURE.md, no CLAUDE.md template
    result = subprocess.run(
        [BASH, str(INSTALLER)],
        input="n\nn\n3\n8\n1\ny\nn\nn\nn\nn\n",
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
        cwd=REPO, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    config = tmp_path / ".claude"
    src = INSTALLER.read_text(encoding="utf-8")
    for name in (*_dispatcher_hooks(src), "manifest_metrics.py", "bash_policy_tables.py",
                 "protected-repos.json", "hook_input.py", "run-hook"):
        assert (config / "hooks" / name).is_file(), name
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    bash_groups = [g for g in settings["hooks"]["PreToolUse"] if g.get("matcher") == "Bash|PowerShell"]
    assert [h["args"] for g in bash_groups for h in g["hooks"]] == [[DISPATCHER]]
    assert {h["timeout"] for g in bash_groups for h in g["hooks"]} == {30}

    def fire(command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(config / "hooks" / "run-hook"), DISPATCHER],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            cwd=config, env={**env, "CLAUDE_CONFIG_DIR": str(config)},
        )

    blocked = fire("rm -rf /")
    assert blocked.returncode == 2, blocked.stdout + blocked.stderr
    assert "BLOCKED" in blocked.stderr
    allowed = fire("ls -la")
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr


def test_pick_individual_skills_asks_per_skill_and_installs_the_chosen_one(tmp_path):
    """Skills menu option 7 ("Pick individually") must read each answer from the
    user. It used to prompt inside `while read ... < <(find ...)`, so ask_yn's read
    consumed the next find line as the answer: the user was never asked and no
    skill was installed (found 2026-09-03 by the manifest e2e test)."""
    # skills/<name>/SKILL.md only: the menu must not offer the SKILL.md fixtures
    # under skills/audit-skill/tests/, which can never install.
    skills = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md") if p.parent.name != "_shared")
    assert len(skills) > 2
    # `read -p` shows no prompt on piped stdin, so prompts cannot be counted;
    # instead answer yes to the FIRST and LAST skill: the last one lands only if
    # exactly one answer was consumed per skill, in menu order.
    per_skill = "y\n" + "n\n" * (len(skills) - 2) + "y\n"
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["LC_ALL"] = "C"  # the menu sorts with `sort`; make it agree with sorted()
    # skip profile, skip core, skip rules, pick skills individually, <one answer
    # per skill>, skip hooks, no agents, no agent-memory, no ARCHITECTURE.md,
    # no CLAUDE.md template
    result = subprocess.run(
        [BASH, str(INSTALLER)],
        input="n\nn\n3\n7\n" + per_skill + "4\nn\nn\nn\nn\n",
        capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
        cwd=REPO, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    installed = sorted(p.name for p in (tmp_path / ".claude" / "skills").iterdir())
    assert installed == sorted([skills[0], skills[-1], "_shared"]), installed
    assert "Installed 2 skills" in result.stdout
