#!/usr/bin/env python3
"""Verify every hook script referenced in settings.json exists in hooks/.

Exits 0 if all good, 1 with a list of missing scripts otherwise. Designed
for CI: lifts the same logic that session-start.py uses at runtime so an
orphan hook registration (or an orphan test file pointing at a deleted
hook) fails the build instead of a session.

Usage: python scripts/validate-hook-paths.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / "settings.json"
HOOKS_DIR = REPO_ROOT / "hooks"
TEST_HOOKS_DIR = HOOKS_DIR / "test-hooks"
DECLARED_TARGET_PREFIX = "# validate-hook-paths-target:"


def extract_script(cmd: str, args: object = None) -> str | None:
    """Pull the .py script from exec-form args or a legacy shell command."""
    argv = args if isinstance(args, list) else []
    for part in [*argv, *cmd.split()]:
        if not isinstance(part, str):
            continue
        if part.endswith(".py") and "python" not in part.lower().replace(".py", ""):
            return part.strip('"').strip("'")
    return None


def check_registered_hooks() -> list[str]:
    """Each command in settings.json hooks must resolve to a file on disk."""
    errors: list[str] = []
    if not SETTINGS_PATH.exists():
        return [f"settings.json not found at {SETTINGS_PATH}"]
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    for event, entries in (settings.get("hooks") or {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            matcher = entry.get("matcher", "*")
            for hook in entry.get("hooks", []) or []:
                if hook.get("type") != "command":
                    continue
                script = extract_script(
                    hook.get("command", ""), hook.get("args")
                )
                if not script:
                    continue
                # Bare filenames dispatched via run-hook live in hooks/
                script_path = Path(script)
                if not script_path.is_absolute() and "/" not in script and "\\" not in script:
                    script_path = HOOKS_DIR / script
                else:
                    # Strip $HOME / ~ - we're validating relative to REPO_ROOT
                    s = script.replace("$HOME/.claude/", "").replace("~/.claude/", "")
                    script_path = REPO_ROOT / s
                if not script_path.exists():
                    errors.append(
                        f"MISSING HOOK: {Path(script).name} "
                        f"({event}:{matcher}) — registered in settings.json "
                        f"but not on disk"
                    )
    return errors


def check_dispatcher_commands() -> list[str]:
    """The `command` DISPATCHER must be canonical, not an authoring worktree path.

    `check_registered_hooks` above validates the `.py` named in `args` and never
    looks at `command` itself — so a dispatcher pointing at a REMOVED worktree's
    `run-hook` passes every gate while being silently dead. That is exactly the
    "fails open, logging nothing" mode this file exists to prevent, and it went
    unnoticed because the ARG half was healthy.

    Measured 2026-08-30: `mcp-truncation-signal-guard.py` was registered on
    PostToolUse matcher `mcp__.*` — the hottest matcher in the config — with
    `command: /Users/<u>/worktrees/cc-truncation-hook/hooks/run-hook`, the path of
    the worktree it was installed from. `worktree-by-default` Step 7 removes a
    worktree once its PR is terminal, so finishing the work broke the delivery.
    Every MCP call since invoked a missing binary; the guard never fired once, and
    a pagination gotcha it was built to catch recurred a 4th time.

    Two checks, both high-precision against the real command set (46 canonical
    `run-hook`, 2 `/usr/bin/afplay`, 1 `hooks/*.sh`):
      1. any `/worktrees/` segment is wrong by construction — worktrees are
         ephemeral, so no shipped registration may reference one;
      2. a dispatcher under `.claude/hooks/` must exist, resolved against
         REPO_ROOT the same way the script branch resolves.
    A command outside `.claude/hooks/` (a system binary) is left alone.
    """
    errors: list[str] = []
    if not SETTINGS_PATH.exists():
        return errors
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    for event, entries in (settings.get("hooks") or {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            matcher = entry.get("matcher", "*")
            for hook in entry.get("hooks", []) or []:
                if hook.get("type") != "command":
                    continue
                cmd = hook.get("command", "")
                if not isinstance(cmd, str) or not cmd:
                    continue
                if "/worktrees/" in cmd:
                    errors.append(
                        f"WORKTREE DISPATCHER: {event}:{matcher} — command "
                        f"{cmd!r} points into an ephemeral worktree. Register the "
                        f"deployed path (~/.claude/hooks/run-hook); a worktree is "
                        f"removed when its PR lands, leaving the hook silently dead."
                    )
                    continue
                norm = cmd.replace("$HOME/.claude/", "").replace("~/.claude/", "")
                marker = "/.claude/"
                if marker in norm:
                    norm = norm.split(marker, 1)[1]
                if not norm.startswith("hooks/"):
                    continue  # system binary or out-of-tree dispatcher
                if not (REPO_ROOT / norm).exists():
                    errors.append(
                        f"MISSING DISPATCHER: {event}:{matcher} — command "
                        f"{cmd!r} does not resolve to a file in this checkout"
                    )
    return errors


def _declared_test_target(test_file: Path) -> str | None:
    """Return an explicit non-script test target declared by the test file."""

    for line in test_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(DECLARED_TARGET_PREFIX):
            return stripped.removeprefix(DECLARED_TARGET_PREFIX).strip()
    return None


def declared_test_target_exists(test_file: Path) -> bool:
    """Resolve a declared target inside the repository, excluding test files.

    A declaration is reserved for contracts such as launchd plists that cannot
    be inferred from ``test_<script>.py`` naming. It must not become a generic
    orphan-test exemption: absolute paths, traversal, missing files, and files
    under the test directories all fail closed.
    """

    declared = _declared_test_target(test_file)
    if not declared:
        return False
    relative = Path(declared)
    if relative.is_absolute():
        return False
    root = REPO_ROOT.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    for tests_root in (TEST_HOOKS_DIR.resolve(), (REPO_ROOT / "tests").resolve()):
        try:
            candidate.relative_to(tests_root)
        except ValueError:
            continue
        return False
    return candidate.is_file()


def check_test_orphans() -> list[str]:
    """Each test_<name>.py in test-hooks/ must map to a real target script
    somewhere in the repo — a hook, a session module, a bin/ tool, a manifest
    tool, a skill helper (references/ or scripts/), or an explicitly declared
    repository-local non-script target — OR be a known parametric suite not
    named after one script.

    Resolving against all real target locations (rather than maintaining a
    per-name allowlist of "non-hook tests") keeps the check honest as the repo
    grows: a test for a new bin/ tool or skill helper just works, while a test
    pointing at a genuinely-deleted target still fails. The prior allowlist was
    accreting an entry per non-hook test — the over-broad-check smell.
    """
    errors: list[str] = []
    if not TEST_HOOKS_DIR.is_dir():
        return errors

    skills_dir = REPO_ROOT / "skills"
    # Directories that hold a single-file test target, searched by exact name.
    search_dirs = [
        HOOKS_DIR,
        HOOKS_DIR / "session_start_modules",
        REPO_ROOT / "bin",
        REPO_ROOT / "manifests",
        # Repo-root scripts/ holds real single-file targets too (verify-indexes.py,
        # build-marketplace.py, the validate-*.py family). It was omitted rather
        # than excluded: the docstring's "scripts/" meant SKILL helpers
        # (skills/<skill>/scripts/), handled separately below. Adding it can only
        # resolve more tests — a search root never creates a new orphan report.
        REPO_ROOT / "scripts",
    ]
    # Genuinely parametric suites: they exercise cross-cutting behavior over
    # many scripts and are not named after a single target file.
    parametric = {
        "audit_hook_matchers",   # parametrizes over every hook's matcher
        "crash_safety",          # parametric over all hooks (exit-0-on-crash)
        "atomic_writes",         # parametric over shared-state hooks
        "audit_rules",           # covers skills/audit-rules/references/*.py (several)
        "settings_permissions",  # pins settings.json permissions.deny invariants
        "fixtures",              # shared JSONL test-fixtures smoke test (not a hook)
        "evidence_guidance",     # cross-cuts a rule, skill/manifest, and eval contract
        "transcript_semantic",   # covers mega-distill corpus-mode semantic layer (transcript_cohort/
                                 # semantic_gate/cluster_input/cluster_from_assign) — several scripts
    }

    for test_file in sorted(TEST_HOOKS_DIR.glob("test_*.py")):
        base = test_file.stem[len("test_"):]
        if base in parametric:
            continue
        declared = _declared_test_target(test_file)
        if declared is not None:
            if declared_test_target_exists(test_file):
                continue
            errors.append(
                f"ORPHANED TEST: {test_file.name} — declared target is missing "
                f"or outside the permitted repository surface: {declared or '<empty>'}"
            )
            continue
        # Convention: test_foo_bar.py targets foo-bar.py or foo_bar.py. Some
        # targets are extensionless executables (hooks/run-hook, the shell
        # launcher every hook is invoked through), so try those spellings too
        # rather than exempting them in `parametric` — an exemption would hide
        # a genuinely-deleted target, which is what this check is for.
        names = (
            f"{base.replace('_', '-')}.py",
            f"{base}.py",
            base.replace("_", "-"),
            base,
        )
        found = any((d / n).exists() for d in search_dirs for n in names)
        if not found:
            # Skill helpers live under skills/<skill>/(references|scripts)/.
            found = any(
                (skills_dir / skill / sub / n).exists()
                for skill in (p.name for p in skills_dir.iterdir() if p.is_dir())
                for sub in ("references", "scripts")
                for n in names
            ) if skills_dir.is_dir() else False
        if not found:
            errors.append(
                f"ORPHANED TEST: {test_file.name} — no target script in hooks/, "
                f"bin/, manifests/, or skills/**/(references|scripts) "
                f"(looked for: {' / '.join(names)})"
            )
    return errors


def check_uncollectable_tests() -> list[str]:
    """Flag hyphen-named test files (test-foo.py) in pytest-scanned dirs.

    pytest only collects test_*.py (underscore), and the orphan check above
    only globs test_*.py — so a hyphen-named test file is invisible to BOTH:
    no runner ever executes it and no gate notices. Several such zombies
    accumulated before 2026-06-10; this check makes the class
    structurally impossible. Scoped to dirs CI points pytest at — skills may
    legitimately ship hyphen-named MANUAL scripts (documented as such in
    their SKILL.md), so skills/ is exempt.
    """
    errors: list[str] = []
    for scan_dir in (TEST_HOOKS_DIR, REPO_ROOT / "tests"):
        if not scan_dir.is_dir():
            continue
        for f in sorted(scan_dir.rglob("test-*.py")):
            errors.append(
                f"UNCOLLECTABLE TEST: {f.relative_to(REPO_ROOT)} — hyphen-named "
                f"test files are never collected by pytest. Rename to "
                f"{f.name.replace('test-', 'test_', 1).replace('-', '_')} "
                f"or delete."
            )
    return errors


def main() -> int:
    errors = (check_registered_hooks() + check_dispatcher_commands()
              + check_test_orphans() + check_uncollectable_tests())
    if errors:
        print(f"validate-hook-paths: {len(errors)} problem(s) found:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("validate-hook-paths: all hooks resolve, no orphan tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
