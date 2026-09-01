"""Healthcheck Check 9 helper: reverse-inventory orphan detection.

Covers sub-checks 9a-9f from check-9-orphans.md:
  9a — orphan hook scripts (cross-ref settings.json + skill bodies + hook bodies)
  9b — orphan scripts in scripts/
  9c — stale plans (>30 days since last commit)
  9d — CI workflow integrity (referenced .py files exist)
  9e — stale local branches (merged into main)
  9f — skill body dead references (hooks/scripts paths that don't exist)

Exists because PR #548 deleted sync-repo.py and sync-knowledge.py as
"orphans" — but both were skill-invoked CLI utilities. Inline regex-only
checks against settings.json miss cross-references in skill bodies, hook
bodies, and CI workflows. This helper does the full cross-reference.

Read-only. Exit 0 = clean. Exit 1 = orphans found.

Usage:
  python _check_orphans.py
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
HOOKS_DIR = CLAUDE_DIR / "hooks"
SCRIPTS_DIR = CLAUDE_DIR / "scripts"
SKILLS_DIR = CLAUDE_DIR / "skills"
PLANS_DIR = CLAUDE_DIR / "plans"
# CI workflows live at the REPO root's .github/workflows, not under
# CLAUDE_DIR. If CLAUDE_DIR is the deployed ~/.claude (no .git, no
# workflows), fall back to the source repo's workflows dir so the
# 9d CI workflow integrity check isn't silently skipped.
_WF_CLAUDE = CLAUDE_DIR / ".github" / "workflows"
_WF_REPO = Path(__file__).resolve().parent.parent.parent.parent / ".github" / "workflows"
WORKFLOWS_DIR = _WF_CLAUDE if _WF_CLAUDE.is_dir() else _WF_REPO
SETTINGS_JSON = CLAUDE_DIR / "settings.json"

# Files that are helper modules imported by other hooks, not hooks themselves.
# Underscore-prefixed files are also treated as helpers by convention.
KNOWN_HELPERS = {
    "atomic_write.py",
    "manifest_metrics.py",
    "__init__.py",
}


def load_settings_hooks() -> set[str]:
    """Return basenames of hook scripts registered in settings.json."""
    hooks: set[str] = set()
    with open(SETTINGS_JSON, encoding="utf-8") as f:
        settings = json.load(f)
    for entries in settings.get("hooks", {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                if hook.get("type") == "command":
                    for arg in hook.get("args", []) or []:
                        if isinstance(arg, str) and arg.endswith(".py"):
                            hooks.add(os.path.basename(arg))
                    # shlex.split honors quoted args like
                    # `python3 "C:/path with spaces/foo.py"`. Naive
                    # str.split would split on the space inside the
                    # quoted path and pick up the wrong token as ".py".
                    try:
                        tokens = shlex.split(hook.get("command", ""), posix=True)
                    except ValueError:
                        tokens = hook.get("command", "").split()
                    for part in tokens:
                        if part.endswith(".py"):
                            hooks.add(os.path.basename(part))
    return hooks


def file_references_basename(file_path: Path, basenames: set[str]) -> set[str]:
    """Return the subset of `basenames` that appear in `file_path`'s contents."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    return {b for b in basenames if b in text or b[:-3] in text}


def collect_referenced(
    candidates: set[str],
    search_dirs: list[Path],
    extensions: tuple[str, ...] = (".py", ".md", ".json", ".yaml", ".yml"),
    skip_self_path: Path | None = None,
) -> set[str]:
    """Walk search_dirs, return basenames in `candidates` that appear in any file."""
    referenced: set[str] = set()
    for d in search_dirs:
        if not d.is_dir():
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if not fn.endswith(extensions):
                    continue
                fp = Path(root) / fn
                if skip_self_path and fp.resolve() == skip_self_path.resolve():
                    continue
                hits = file_references_basename(fp, candidates - referenced)
                referenced.update(hits)
                if candidates == referenced:
                    return referenced
    return referenced


def check_orphan_hooks() -> list[str]:
    """9a: hook scripts not registered AND not referenced anywhere."""
    issues: list[str] = []
    registered = load_settings_hooks()
    on_disk = {
        f.name for f in HOOKS_DIR.iterdir()
        if f.suffix == ".py" and not f.name.startswith("_") and f.is_file()
    }
    candidates = on_disk - registered - KNOWN_HELPERS
    if not candidates:
        return issues
    # Cross-reference against skills, other hooks, manifests, scripts, workflows
    search_dirs = [SKILLS_DIR, HOOKS_DIR, SCRIPTS_DIR, WORKFLOWS_DIR, CLAUDE_DIR / "manifests"]
    referenced: set[str] = set()
    for candidate in sorted(candidates):
        # Skip the candidate's own file when searching (a hook referencing itself
        # in a docstring doesn't count as another component using it).
        own = HOOKS_DIR / candidate
        for d in search_dirs:
            if not d.is_dir():
                continue
            found = False
            for root, _, files in os.walk(d):
                for fn in files:
                    if not fn.endswith((".py", ".md", ".json", ".yaml", ".yml")):
                        continue
                    fp = Path(root) / fn
                    try:
                        if fp.resolve() == own.resolve():
                            continue
                    except OSError:
                        pass
                    try:
                        text = fp.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    if candidate in text or candidate[:-3] in text:
                        referenced.add(candidate)
                        found = True
                        break
                if found:
                    break
            if found:
                break
    orphans = candidates - referenced
    for o in sorted(orphans):
        issues.append(f"9a orphan hook: {o} not registered and not referenced")
    return issues


# Manually-invoked CLI utilities — standalone tools the user runs from the
# shell (typically with a `Usage:` docstring) that aren't called by any skill
# or hook. The orphans check would otherwise flag these as "unreferenced"
# because no programmatic consumer exists; this allowlist documents them as
# intentional operator tools. Same convention as LOCAL_ONLY_SKILLS in
# _check_manifest.py.
#
# To remove an entry: confirm the script is truly obsolete via the docstring
# + `git log` history, then delete both the script and the entry here.
KNOWN_CLI_UTILITIES = {
    "check-write-journal.py",      # Forensic check for file-disappearance bug; manual triage tool
    "session-cost-breakdown.py",   # Per-activity transcript cost analysis; manual debug
}


_PYTEST_RE = re.compile(r"\bpytest\b([^\n|&;]*)")
# `path:` under an actions/checkout step — the runtime clone directory.
_CHECKOUT_PATH_RE = re.compile(r"^\s*path:\s*(\S+)\s*$", re.MULTILINE)


def pytest_collected_targets() -> set[str]:
    """Repo-relative paths that a CI `pytest` invocation collects.

    A `test_*.py` under scripts/ is consumed by pytest AUTO-COLLECTION, not by
    any file naming it — `.github/workflows/tests.yml (this export ships gitleaks.yml, plugins.yml, tests.yml; the upstream tests.yml is not part of it)` runs `pytest scripts/`.
    A basename cross-reference cannot see that consumer, so all 34 such files
    read as orphans (measured 2026-08-30). Deleting one on that evidence would
    silently drop a test, which is the same class of mistake as PR #548
    deleting two skill-invoked CLIs from a settings.json-only check.
    """
    targets: set[str] = set()
    if not WORKFLOWS_DIR.is_dir():
        return targets
    for wf in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        try:
            text = wf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _PYTEST_RE.finditer(text):
            for token in match.group(1).split():
                if token.startswith("-") or token.startswith("$"):
                    continue
                path = token.split("::")[0].strip("'\"").rstrip("/")
                if path:
                    targets.add(path)
    return targets


def _pytest_consumes(name: str, targets: set[str]) -> bool:
    """True if a CI pytest invocation collects scripts/<name>."""
    if not (name.startswith("test_") or name == "conftest.py"):
        return False
    return bool({"scripts", ".", f"scripts/{name}"} & targets)


def check_orphan_scripts() -> list[str]:
    """9b: scripts/ files not referenced by any skill, hook, or workflow.

    Files in KNOWN_CLI_UTILITIES are excluded — they're operator-invoked
    tools whose only consumer is the user running them from the shell.
    Test files collected by a CI pytest run are excluded too: their consumer
    is the collector, which names no file.
    """
    if not SCRIPTS_DIR.is_dir():
        return []
    issues: list[str] = []
    candidates = {
        f.name for f in SCRIPTS_DIR.iterdir()
        if f.suffix == ".py" and not f.name.startswith("_") and f.is_file()
    }
    candidates -= KNOWN_CLI_UTILITIES
    pytest_targets = pytest_collected_targets()
    candidates = {c for c in candidates if not _pytest_consumes(c, pytest_targets)}
    # A consumer can live anywhere in the repo, not only in these four trees.
    # bin/, rules/, tests/ and docs/ each held a real reference to a script
    # reported as an orphan (check-marketplace-sync.py, measure-eval-coverage.py).
    search_dirs = [
        SKILLS_DIR, HOOKS_DIR, WORKFLOWS_DIR, SCRIPTS_DIR,
        CLAUDE_DIR / "bin", CLAUDE_DIR / "rules", CLAUDE_DIR / "tests",
        CLAUDE_DIR / "docs", CLAUDE_DIR / "agent-memory", CLAUDE_DIR / "manifests",
    ]
    referenced: set[str] = set()
    for candidate in sorted(candidates):
        own = SCRIPTS_DIR / candidate
        for d in search_dirs:
            if not d.is_dir():
                continue
            found = False
            for root, _, files in os.walk(d):
                for fn in files:
                    if not fn.endswith((".py", ".md", ".json", ".yaml", ".yml")):
                        continue
                    fp = Path(root) / fn
                    try:
                        if fp.resolve() == own.resolve():
                            continue
                    except OSError:
                        pass
                    try:
                        text = fp.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    if candidate in text or candidate[:-3] in text:
                        referenced.add(candidate)
                        found = True
                        break
                if found:
                    break
            if found:
                break
    for o in sorted(candidates - referenced):
        issues.append(f"9b orphan script: scripts/{o} not referenced anywhere")
    return issues


def check_stale_plans() -> list[str]:
    """9c: plans/ files >30 days old (git mtime)."""
    if not PLANS_DIR.is_dir():
        return []
    issues: list[str] = []
    import time
    threshold = time.time() - (30 * 86400)
    for f in sorted(PLANS_DIR.iterdir()):
        if f.suffix not in (".md", ".json"):
            continue
        try:
            r = subprocess.run(
                ["git", "-C", str(CLAUDE_DIR), "log", "-1", "--format=%ct", "--", str(f)],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0 or not r.stdout.strip():
                continue
            ts = int(r.stdout.strip())
            if ts < threshold:
                days = int((time.time() - ts) / 86400)
                issues.append(f"9c stale plan: plans/{f.name} last touched {days}d ago")
        except (subprocess.SubprocessError, ValueError):
            continue
    return issues


def check_ci_workflow_integrity() -> list[str]:
    """9d: CI workflows reference .py files — verify they exist."""
    if not WORKFLOWS_DIR.is_dir():
        return []
    issues: list[str] = []
    pattern = re.compile(r"(?:python\s+|run:\s+python\s+|run:\s+)([\w./-]+\.py)")
    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")):
        try:
            text = wf.read_text(encoding="utf-8")
        except OSError:
            continue
        # `actions/checkout` with `path: <dir>` clones INTO that dir at runtime,
        # so a later `python <dir>/skills/.../x.py` is repo-relative underneath
        # it. Resolving such a ref literally against the repo root reports a
        # file that exists as missing (measured 2026-08-30: 4 phantom 9d refs
        # under trusted-config/ and candidate-config/, target present in
        # skills/_shared/).
        checkout_dirs = {
            p.strip().strip("'\"").rstrip("/")
            for p in _CHECKOUT_PATH_RE.findall(text)
        }
        checkout_dirs.discard("")
        for m in pattern.finditer(text):
            ref = m.group(1).lstrip("./")
            head, _, tail = ref.partition("/")
            if tail and head in checkout_dirs:
                ref_repo = tail
            else:
                ref_repo = ref
            if (CLAUDE_DIR / ref_repo).exists():
                continue
            # Basename fallback across every tree that legitimately holds an
            # executable referenced by CI, not just hooks/ and scripts/.
            base = os.path.basename(ref_repo)
            fallbacks = (
                HOOKS_DIR, SCRIPTS_DIR, CLAUDE_DIR / "bin",
                SKILLS_DIR / "_shared",
            )
            if any((d / base).exists() for d in fallbacks):
                continue
            issues.append(f"9d CI ref missing: {wf.name} → {ref}")
    return issues


def check_stale_branches() -> tuple[list[str], int]:
    """9e: count local branches merged into main."""
    issues: list[str] = []
    try:
        r = subprocess.run(
            ["git", "-C", str(CLAUDE_DIR), "branch", "--merged", "main"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return issues, 0
        branches = [
            b.strip().lstrip("* ").strip()
            for b in r.stdout.splitlines()
            if b.strip() and "main" not in b.strip().lstrip("* ").strip().split("/")[0]
        ]
        # Filter out 'main' itself
        branches = [b for b in branches if b != "main"]
        if branches:
            issues.append(f"9e stale branches: {len(branches)} merged into main (safe to delete)")
            for b in branches[:5]:
                issues.append(f"    - {b}")
        return issues, len(branches)
    except (subprocess.SubprocessError, OSError):
        return issues, 0


EXAMPLE_PLACEHOLDERS = {"foo.py", "bar.py", "baz.py", "<name>.py", "X.py", "Y.py", "name.py"}


_FENCED_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_BACKTICK = re.compile(r"`[^`\n]+`")


def _strip_illustrative_text(text: str) -> str:
    """Remove fenced code blocks and inline backtick spans before 9f scanning.

    Hook/script paths that appear inside ```...``` blocks or `...` inline
    spans are overwhelmingly illustrative (example flows, sample warnings,
    hypothetical filenames), not live references. The 9f check is for
    finding leftover references to deleted files in skill *prose*, so
    stripping these illustrative wrappers eliminates a recurring class of
    false positives.

    Trade-off: a real dead-ref inside a backtick span would no longer
    surface. That's acceptable because (a) live references typically
    execute through Claude Code's tool orchestration rather than appearing
    in SKILL.md prose, and (b) markdown links `[text](path.py)` and bare
    plain-prose mentions still match the 9f regex.
    """
    text = _FENCED_CODE_BLOCK.sub("", text)
    text = _INLINE_BACKTICK.sub("", text)
    return text


def check_skill_body_dead_refs() -> list[str]:
    """9f: skills reference hooks/X.py or scripts/X.py that don't exist.

    Checks skill-local subdirs (skills/<name>/scripts/, skills/<name>/references/,
    skills/<name>/) FIRST, then global ~/.claude/hooks/ and ~/.claude/scripts/.
    A reference is "dead" only if it doesn't resolve in ANY of those locations.
    Example placeholders (foo.py, bar.py, <name>.py) are skipped. References
    inside fenced code blocks or inline backtick spans are also skipped — see
    _strip_illustrative_text for rationale.
    """
    issues: list[str] = []
    # Match references in body to scripts/*.py, hooks/*.py, AND references/*.py
    # (some skills like healthcheck place executable helpers under references/).
    # Negative lookbehind excludes matches preceded by `/` or word chars (e.g.
    # `audit-architecture/references/foo.py` should NOT be classified as a
    # healthcheck-local `references/foo.py` reference — it's a cross-skill
    # absolute path that this 9f check is not responsible for resolving).
    pattern = re.compile(r"(?<![\w/-])(hooks|scripts|references)/([\w.-]+\.py)\b")
    seen: set[tuple[str, str, str]] = set()  # (skill, kind, fname) dedup
    if not SKILLS_DIR.is_dir():
        return []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        text = _strip_illustrative_text(text)
        for m in pattern.finditer(text):
            kind, fname = m.group(1), m.group(2)
            key = (skill_dir.name, kind, fname)
            if key in seen:
                continue
            seen.add(key)
            if fname in EXAMPLE_PLACEHOLDERS:
                continue
            # Resolution order: skill-local subdir, skill-local root, global
            candidates = [
                skill_dir / kind / fname,
                skill_dir / "scripts" / fname,
                skill_dir / "references" / fname,
                skill_dir / fname,
                (HOOKS_DIR if kind == "hooks" else SCRIPTS_DIR) / fname,
            ]
            if not any(c.exists() for c in candidates):
                issues.append(f"9f dead ref: skills/{skill_dir.name}/SKILL.md → {kind}/{fname}")
    return issues


def main() -> int:
    # Preflight: surface a clean error rather than a raw FileNotFoundError
    # traceback if CLAUDE_CONFIG_DIR (or the default ~/.claude) is missing
    # the components every sub-check needs.
    if not CLAUDE_DIR.is_dir():
        print(f"Orphans: ERROR - claude config dir not found: {CLAUDE_DIR}")
        print("  Set CLAUDE_CONFIG_DIR to the deployed ~/.claude root.")
        return 2
    if not HOOKS_DIR.is_dir():
        print(f"Orphans: ERROR - hooks dir not found: {HOOKS_DIR}")
        print(f"  Expected at: {CLAUDE_DIR}/hooks/")
        return 2
    if not SETTINGS_JSON.exists():
        print(f"Orphans: ERROR - settings.json not found: {SETTINGS_JSON}")
        print(f"  Expected at: {CLAUDE_DIR}/settings.json")
        return 2
    all_issues: list[tuple[str, list[str]]] = []
    all_issues.append(("9a orphan hooks", check_orphan_hooks()))
    all_issues.append(("9b orphan scripts", check_orphan_scripts()))
    all_issues.append(("9c stale plans", check_stale_plans()))
    all_issues.append(("9d CI workflow integrity", check_ci_workflow_integrity()))
    branch_issues, _ = check_stale_branches()
    all_issues.append(("9e stale branches", branch_issues))
    all_issues.append(("9f skill body dead refs", check_skill_body_dead_refs()))

    total = sum(len(v) for _, v in all_issues)
    if total == 0:
        print("Orphans: PASS — no unreferenced files found")
        return 0

    print(f"Orphans: WARN — {total} finding(s)")
    for name, issues in all_issues:
        if not issues:
            continue
        print(f"  [{name}]")
        for line in issues:
            print(f"    {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
