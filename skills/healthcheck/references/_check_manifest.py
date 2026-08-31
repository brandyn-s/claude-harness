"""Healthcheck Check 10 + Check 12 helper: marketplace registration audit.

Check 10: every skill on disk is registered in `scripts/build-marketplace.py`,
no phantoms (registered but absent on disk).

Check 12: marketplace publish target is in lockstep with source. For every
(src, dst) tuple declared in PLUGINS, compare bytes between the source file
and its marketplace bundle copy. Drift = source and bundle differ —
typically a prior PR shipped source without rebuilding the marketplace.

Severity:
  FAIL (exit 2)  — manifest references a source file that doesn't exist
                   OR a registered skill is absent on disk (phantom).
                   The marketplace bundle is broken; installers will hit
                   missing files.
  WARN (exit 1)  — source and bundle bytes differ (drift only),
                   OR a skill on disk isn't in PLUGINS (unregistered).
                   Often resolvable with `python3 scripts/build-marketplace.py`.
  PASS (exit 0)  — everything lockstep.

Usage:
  python3 _check_manifest.py
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

# Honor CLAUDE_CONFIG_DIR like _check_skills.py — the healthcheck skill's
# contract is that every check reads from it (default ~/.claude).
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
SKILLS = CLAUDE_DIR / "skills"
MARKETPLACE = CLAUDE_DIR / "marketplace"
BUILD_SCRIPT = CLAUDE_DIR / "scripts" / "build-marketplace.py"
PLUGIN_MANIFEST = CLAUDE_DIR / ".claude-plugin" / "plugin.json"
DEPENDENCY_LOCK = CLAUDE_DIR / ".claude-plugin" / "dependency-lock.json"


def _locked_relative_path(raw: object, *, label: str) -> Path:
    """Validate a dependency-lock path before resolving it in the plugin."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a non-empty relative path")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} escapes the installed plugin: {raw!r}")
    return path


def check_installed_plugin() -> list[str]:
    """Validate an installed plugin from its generated dependency lock.

    Marketplace installs intentionally do not contain the repository's build
    script or source marketplace. Their trustworthy local invariant is that
    every dependency recorded at build time exists in the installed payload,
    no undeclared skill was substituted, and no locked path escapes through a
    symlink.
    """
    failures: list[str] = []
    try:
        lock = json.loads(DEPENDENCY_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"FAIL installed plugin: invalid dependency lock: {exc}"]
    if not isinstance(lock, dict) or lock.get("schema_version") != 1:
        return ["FAIL installed plugin: unsupported dependency-lock schema"]

    try:
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"FAIL installed plugin: invalid plugin manifest: {exc}")
        manifest = None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("name"), str):
        failures.append("FAIL installed plugin: manifest is missing a plugin name")

    packaged = lock.get("packaged_skills")
    edges = lock.get("requires_skills")
    roots = lock.get("root_skills")
    if not isinstance(packaged, list) or not all(
        isinstance(name, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
        for name in packaged
    ):
        failures.append("FAIL installed plugin: packaged_skills is malformed")
        packaged = []
    if len(packaged) != len(set(packaged)):
        failures.append("FAIL installed plugin: packaged_skills contains duplicates")
    packaged_set = set(packaged)

    actual_skills = {
        path.name
        for path in SKILLS.iterdir()
        if path.is_dir() and path.name != "_shared" and (path / "SKILL.md").is_file()
    } if SKILLS.is_dir() else set()
    for name in sorted(packaged_set - actual_skills):
        failures.append(f"FAIL installed plugin: locked skill is missing: {name}")
    for name in sorted(actual_skills - packaged_set):
        failures.append(f"FAIL installed plugin: undeclared skill is present: {name}")

    if not isinstance(roots, list) or not all(isinstance(name, str) for name in roots):
        failures.append("FAIL installed plugin: root_skills is malformed")
    else:
        for name in roots:
            if name not in packaged_set:
                failures.append(f"FAIL installed plugin: root skill is absent: {name}")

    if not isinstance(edges, dict):
        failures.append("FAIL installed plugin: requires_skills is malformed")
        edges = {}
    elif set(edges) != packaged_set:
        failures.append(
            "FAIL installed plugin: requires_skills keys do not match packaged_skills"
        )
    for source, dependencies in edges.items():
        if not isinstance(dependencies, list) or not all(
            isinstance(name, str) for name in dependencies
        ):
            failures.append(
                f"FAIL installed plugin: dependency list is malformed: {source}"
            )
            continue
        for dependency in dependencies:
            if dependency not in packaged_set:
                failures.append(
                    f"FAIL installed plugin: {source} requires missing {dependency}"
                )

    locked_paths: list[tuple[str, object, Path]] = []
    for key, root in (
        ("shared_assets", SKILLS / "_shared"),
        ("helpers", CLAUDE_DIR),
    ):
        values = lock.get(key)
        if not isinstance(values, list):
            failures.append(f"FAIL installed plugin: {key} is malformed")
            continue
        if len(values) != len(set(value for value in values if isinstance(value, str))):
            failures.append(f"FAIL installed plugin: {key} contains duplicates")
        locked_paths.extend((key, raw, root) for raw in values)

    plugin_root = CLAUDE_DIR.resolve()
    for label, raw, root in locked_paths:
        try:
            relative = _locked_relative_path(raw, label=label)
            target = root / relative
            resolved = target.resolve(strict=True)
            resolved.relative_to(plugin_root)
            if target.is_symlink() or not target.is_file():
                raise ValueError(f"not a regular packaged file: {raw!r}")
        except (OSError, ValueError) as exc:
            failures.append(f"FAIL installed plugin: {label} {raw!r}: {exc}")
    return failures


def parse_plugins() -> list[dict]:
    """Extract the PLUGINS list from build-marketplace.py via AST.

    Returns a list of {'name': str, 'files': [(src, dst), ...]} dicts.
    """
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"))
    plugins: list[dict] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "PLUGINS"):
            continue
        if not isinstance(node.value, ast.List):
            continue
        for entry in node.value.elts:
            if not isinstance(entry, ast.Dict):
                continue
            d = {}
            for k, v in zip(entry.keys, entry.values):
                if isinstance(k, ast.Constant) and k.value == "name" and isinstance(v, ast.Constant):
                    d["name"] = v.value
                if isinstance(k, ast.Constant) and k.value == "files" and isinstance(v, ast.List):
                    files = []
                    for tup in v.elts:
                        if isinstance(tup, ast.Tuple) and len(tup.elts) == 2:
                            src = tup.elts[0].value if isinstance(tup.elts[0], ast.Constant) else None
                            dst = tup.elts[1].value if isinstance(tup.elts[1], ast.Constant) else None
                            if src and dst:
                                files.append((src, dst))
                    d["files"] = files
            if "name" in d and "files" in d:
                plugins.append(d)
    return plugins


def parse_path_rewrites() -> list[tuple[str, str]]:
    """Extract the builder's path-rewrite table from build-marketplace.py via AST.

    `_rewrite_cached_paths` deliberately rewrites `$CONFIG_ROOT`-family paths to
    `${CLAUDE_PLUGIN_ROOT}` in the PUBLISHED copy only; the canonical source is
    left untouched. A raw byte compare therefore reports every such file as
    drift, and `build-marketplace.py` cannot "fix" it because the bundle is
    already correct — measured 2026-08-30: 64 differing files, 64 explained by
    this table, 0 real, and a rebuild changed 0 files.

    Parsed rather than duplicated so the table has ONE source. A local copy
    would drift silently the next time the builder gains a path form, which is
    the same failure this check exists to catch.
    """
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_rewrite_cached_paths":
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assign):
                continue
            if not (len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "replacements"):
                continue
            if not isinstance(stmt.value, ast.Tuple):
                continue
            pairs: list[tuple[str, str]] = []
            for pair in stmt.value.elts:
                if not (isinstance(pair, ast.Tuple) and len(pair.elts) == 2):
                    continue
                old, new = pair.elts
                if (isinstance(old, ast.Constant) and isinstance(new, ast.Constant)
                        and isinstance(old.value, str) and isinstance(new.value, str)):
                    pairs.append((old.value, new.value))
            return pairs
    return []


# Mirrors build-marketplace.py's `_PYTHON_EXPANDUSER_SKILL_RE` substitution.
# Python files get one narrow AST-safe rewrite instead of the shell-style table.
_PY_EXPANDUSER_RE = re.compile(
    r"os\.path\.expanduser\(\s*([\"'])~/\.claude/skills/([^\"']+)\1\s*\)"
)


def as_published(text: str, suffix: str, rewrites: list[tuple[str, str]]) -> str:
    """Apply the builder's transforms to SOURCE text, yielding expected bundle text."""
    if suffix == ".py":
        return _PY_EXPANDUSER_RE.sub(
            lambda m: ('os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "skills", '
                       + json.dumps(m.group(2)) + ")"),
            text,
        )
    for old, new in rewrites:
        text = text.replace(old, new)
    return text


LOCAL_ONLY_SKILLS = {"lab-deploy", "agentic-search", "audit-fix", "audit-skill"}


def check_registration() -> tuple[list[str], list[str]]:
    """Check 10: skills on disk vs PLUGINS list.

    Returns (warn_issues, fail_issues).
      warn — skill on disk but not in PLUGINS (might be intentionally local)
      fail — skill in PLUGINS but absent on disk (publishes a broken bundle)

    LOCAL_ONLY_SKILLS are skills intentionally not published to the marketplace
    (Example-specific or experimental). They appear on disk but not in PLUGINS
    by design — see the comment block after PLUGINS in build-marketplace.py.
    """
    warn: list[str] = []
    fail: list[str] = []
    on_disk = {p.name for p in SKILLS.iterdir() if (p / "SKILL.md").exists()}
    # Derive registered skills from the AST-parsed PLUGINS tuples, not a
    # regex over the script text — code-line glob patterns like
    # plugin_dir.glob("skills/*/SKILL.md") otherwise leak `*` in as a
    # phantom skill name (healthcheck false-FAIL, 2026-06-12).
    registered = set()
    for plugin in parse_plugins():
        for src, _dst in plugin.get("files", []):
            m = re.match(r"skills/([^/]+)/SKILL\.md$", src)
            if m:
                registered.add(m.group(1))
    unregistered = on_disk - registered - LOCAL_ONLY_SKILLS
    phantoms = registered - on_disk
    print(f"Manifest: {len(on_disk)} on disk, {len(registered)} registered, "
          f"{len(LOCAL_ONLY_SKILLS)} local-only.")
    for name in sorted(unregistered):
        warn.append(f"WARN manifest: skill '{name}' on disk but not in PLUGINS")
    for name in sorted(phantoms):
        fail.append(f"FAIL manifest: skill '{name}' registered but absent on disk (broken bundle)")
    if not (unregistered or phantoms):
        print("  PASS - no unregistered, no phantoms")
    return warn, fail


def check_marketplace_drift() -> tuple[list[str], list[str]]:
    """Check 12: per-tuple byte comparison between source and bundle.

    Returns (warn_issues, fail_issues).
      warn — source and bundle bytes differ (drift, usually fixable by rebuild)
      fail — source file referenced in PLUGINS doesn't exist (broken bundle ships
             missing files; rebuild won't fix it without manifest update)
    """
    warn: list[str] = []
    fail: list[str] = []
    plugins = parse_plugins()
    if not plugins:
        return [], ["FAIL drift: could not parse PLUGINS from build-marketplace.py"]
    drifted = 0
    checked = 0
    transformed = 0
    rewrites = parse_path_rewrites()
    if not rewrites:
        # Fail loud rather than silently degrading to a raw byte compare: without
        # the table EVERY path-rewritten file reads as drift, which is the exact
        # false-positive class this parse exists to remove.
        fail.append(
            "FAIL drift: could not parse the path-rewrite table from "
            "build-marketplace.py `_rewrite_cached_paths` — drift results would be "
            "false positives; repair the parse before trusting this check"
        )
        return warn, fail
    for plugin in plugins:
        plugin_dir = MARKETPLACE / plugin["name"]
        for src_rel, dst_rel in plugin["files"]:
            src_file = CLAUDE_DIR / src_rel
            tgt_file = plugin_dir / dst_rel
            if not src_file.exists():
                fail.append(f"FAIL drift: source missing: {src_rel} (referenced by plugin '{plugin['name']}')")
                drifted += 1
                continue
            if not tgt_file.exists():
                warn.append(f"WARN drift: bundle missing: {plugin['name']}/{dst_rel} (run build-marketplace.py)")
                drifted += 1
                continue
            # Count every file we attempted, so the denominator is the real
            # population rather than only the passing subset.
            checked += 1
            try:
                src_bytes = src_file.read_bytes()
                tgt_bytes = tgt_file.read_bytes()
                if src_bytes == tgt_bytes:
                    continue
                # Bytes differ: the bundle may still be correct, because the
                # builder rewrites `$CONFIG_ROOT`-family paths on the published
                # copy only. Compare against the EXPECTED published text.
                expected = as_published(
                    src_bytes.decode("utf-8"), src_file.suffix, rewrites
                )
                if expected == tgt_bytes.decode("utf-8"):
                    transformed += 1
                    continue
                warn.append(f"WARN drift: {src_rel} != marketplace/{plugin['name']}/{dst_rel}")
                drifted += 1
            except (OSError, UnicodeDecodeError) as e:
                warn.append(f"WARN drift: read error on {src_rel}: {e}")
                drifted += 1
                continue
    print(
        f"Marketplace drift: {checked} files compared, {drifted} drifted "
        f"({transformed} differ only by the builder's intended path rewrites)."
    )
    if drifted == 0:
        print("  PASS - source and marketplace are in lockstep")
    return warn, fail


def main():
    # Installed marketplace plugins do not ship the repository's source tree
    # or build script. Validate their generated dependency evidence directly
    # instead of misclassifying every source-only path as drift.
    if PLUGIN_MANIFEST.is_file() or DEPENDENCY_LOCK.exists():
        failures = check_installed_plugin()
        if failures:
            print(
                f"Manifest+Drift: FAIL - {len(failures)} installed-plugin "
                "dependency problem(s)"
            )
            for line in failures:
                print(f"  - {line}")
            sys.exit(2)
        print("Manifest+Drift: PASS - installed plugin dependency lock")
        sys.exit(0)

    # Preflight: both checks depend on BUILD_SCRIPT existing. Emit a clean
    # error rather than a raw FileNotFoundError traceback when it's absent.
    if not BUILD_SCRIPT.exists():
        print(f"Manifest+Drift: ERROR - build script not found: {BUILD_SCRIPT}")
        print("  Expected location: ~/.claude/scripts/build-marketplace.py")
        print("  If running outside a deployed ~/.claude, set HOME to the deployed root.")
        sys.exit(2)
    if not SKILLS.is_dir():
        print(f"Manifest+Drift: ERROR - skills directory not found: {SKILLS}")
        sys.exit(2)
    reg_warn, reg_fail = check_registration()
    drift_warn, drift_fail = check_marketplace_drift()
    all_warn = reg_warn + drift_warn
    all_fail = reg_fail + drift_fail
    total = len(all_warn) + len(all_fail)
    print()
    if total == 0:
        print("Manifest+Drift: PASS")
        sys.exit(0)
    severity = "FAIL" if all_fail else "WARN"
    print(f"Manifest+Drift: {severity} - {len(all_fail)} fail, {len(all_warn)} warn")
    for line in all_fail:
        print(f"  - {line}")
    for line in all_warn[:20]:
        print(f"  - {line}")
    if len(all_warn) > 20:
        print(f"  - ... and {len(all_warn) - 20} more warn-level findings")
    print()
    if all_fail:
        print("Remediation (FAIL): fix the manifest in scripts/build-marketplace.py")
        print("  - missing-source: PLUGINS references a file that no longer exists")
        print("  - phantom: registered skill was deleted; remove from PLUGINS")
    if drift_warn:
        print("Remediation (drift): run `python3 scripts/build-marketplace.py` and commit.")
    if reg_warn:
        # PLUGINS is a hand-written literal list (no glob-based auto-discovery —
        # confirmed by reading build-marketplace.py), so re-running the build
        # script does NOT register a new skill; it only re-syncs skills already
        # in PLUGINS. Following the drift remediation for this WARN type is a
        # silent no-op that leaves the WARN in place with no visible error.
        print("Remediation (unregistered skill): PLUGINS has no glob-based auto-discovery —")
        print("  running build-marketplace.py will NOT register it. Either add an explicit")
        print("  entry to PLUGINS in scripts/build-marketplace.py (name + description +")
        print("  version + files list), or, if intentionally local-only, add it to")
        print("  LOCAL_ONLY_SKILLS in this file.")
    sys.exit(2 if all_fail else 1)


if __name__ == "__main__":
    main()
