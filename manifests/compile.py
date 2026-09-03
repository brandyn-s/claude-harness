"""Compile all co-located manifests into a single graph.json.

Reads manifests from:
  - <root>/skills/*/manifest.yaml
  - <root>/hooks/manifests/*.yaml
  - <root>/rules/manifests/*.yaml

Validates references and produces:
  - <root>/manifests/graph.json (compiled graph for query engine)
  - Validation report (dangling references, missing manifests, placeholders)

Usage:
  python compile.py                    # compile and validate (root=~/.claude)
  python compile.py --check            # validate only, don't write (exits non-zero on hard issues)
  python compile.py --check --strict-semantic  # also fail on source/manifest drift
  python compile.py --root <path>      # operate on a different checkout (e.g., a worktree or CI)
  python compile.py --quiet            # suppress success output (only print on issues)
"""
import argparse
import re
import json
import sys
from pathlib import Path

import yaml


def manifest_sources(root: Path):
    return [
        ("skill", root / "skills", "*/manifest.yaml"),
        ("hook", root / "hooks" / "manifests", "*.yaml"),
        ("rule", root / "rules" / "manifests", "*.yaml"),
    ]


def load_manifests(root: Path):
    """Load all manifests into a dict keyed by id."""
    components = {}
    for _, base, pattern in manifest_sources(root):
        if not base.exists():
            continue
        for f in base.glob(pattern):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if data and "id" in data:
                    # Use forward slashes regardless of platform so downstream
                    # path-prefix checks ("skills/") work the same on Windows
                    # and Linux. Without this, validate_semantic silently
                    # skips every skill on Windows.
                    data["_source"] = f.relative_to(root).as_posix()
                    components[data["id"]] = data
            except Exception as e:
                print(f"  ERROR loading {f}: {e}", file=sys.stderr)
    return components


# ── ENFORCEMENT-EDGE DERIVATION ───────────────────────────────────────────
# `enforced_by` on a rule manifest used to be a hand-maintained back-reference
# to the hooks that enforce it. Measured 2026-08-31 across this repository: 20
# drift edges, 19 of them in the same direction -- a wired hook declaring
# `enforces: [rule]` while that rule's manifest did not name it back, four of
# those rules reporting `coverage: none` while a hook actively enforced them.
#
# The ratio is the diagnosis. Hook manifests are written when the hook is built,
# so `enforces` is accurate; the rule-side back-reference is the unmaintained
# half, and a one-way hand-maintained edge decays toward the unmaintained side.
# It is now a graph OUTPUT only: derive it from the hook side intersected with
# actual wiring. Rule source manifests no longer carry a second editable copy.
#
# This is what makes `unenforced_rules` and `enforcement_chain` trustworthy:
# before, both keyed off self-declared metadata that no gate compared to
# settings.json.

_HOOK_NAME_RX = re.compile(r"([A-Za-z0-9_./-]+\.py)")
_RUN_HOOK_RX = re.compile(r"run-hook\s+([A-Za-z0-9_-]+)")


def wired_hook_ids(root):
    """Hook ids actually reachable at runtime: settings.json + dispatcher guards.

    A hook present on disk but absent from settings.json enforces nothing, and a
    guard invoked inside a wired dispatcher enforces something even though it
    has no settings entry of its own. Both cases are why "does the file exist"
    is the wrong question.
    """
    ids = set()
    settings_path = Path(root) / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, encoding="utf-8") as fh:
                settings = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  WARNING: settings.json unreadable ({exc}); enforcement "
                  f"derivation skipped", file=sys.stderr)
            return None
        for _event, groups in (settings.get("hooks") or {}).items():
            for group in groups:
                for handler in group.get("hooks", []):
                    blob = json.dumps(handler)
                    for m in _HOOK_NAME_RX.finditer(blob):
                        ids.add(Path(m.group(1)).stem)
                    for m in _RUN_HOOK_RX.finditer(blob):
                        ids.add(m.group(1))
    dispatcher = Path(root) / "hooks" / "write-edit-dispatcher.py"
    if dispatcher.exists():
        text = dispatcher.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"GUARDS\s*[:=].*?\n(?=\S)", text, re.S)
        for g in re.findall(r"[\"']([a-z0-9][a-z0-9_-]+)\.py[\"']",
                            m.group(0) if m else text):
            ids.add(g)
    return ids


def derive_enforced_by(components, root):
    """Return {rule_id: sorted[hook_id]} implied by wiring + hook manifests."""
    wired = wired_hook_ids(root)
    if wired is None:
        return None
    derived = {}
    for cid, c in components.items():
        if c.get("type") != "hook" or cid not in wired:
            continue
        for rid in c.get("enforces") or []:
            if isinstance(rid, str) and components.get(rid, {}).get("type") == "rule":
                derived.setdefault(rid, set()).add(cid)
    return {k: sorted(v) for k, v in derived.items()}


def validate_enforcement_edges(components, root):
    """Reject legacy back-references and coverage labels contradicted by wiring."""
    derived = derive_enforced_by(components, root)
    if derived is None:
        return ["  ENFORCEMENT-UNMEASURABLE: settings.json could not be read"]
    issues = []
    for cid, c in sorted(components.items()):
        if c.get("type") != "rule":
            continue
        if "enforced_by" in c:
            issues.append(
                f"  DERIVED-FIELD: {cid}.enforced_by is declared in source; "
                "remove it because compile.py derives this graph edge"
            )
        hooks = derived.get(cid, [])
        coverage = c.get("enforcement_coverage", "none")
        if hooks and coverage == "none":
            issues.append(
                f"  COVERAGE-DRIFT: {cid} has derived hooks {hooks} but "
                "enforcement_coverage is 'none'; classify it as partial or full"
            )
        if not hooks and coverage != "none":
            issues.append(
                f"  COVERAGE-DRIFT: {cid} has no derived hooks but "
                f"enforcement_coverage is {coverage!r}; classify it as none"
            )
    return issues
# ── end ENFORCEMENT-EDGE DERIVATION ───────────────────────────────────────


def validate(components, root="."):
    """Validate cross-references between manifests. Returns list of issues."""
    issues = []
    known_ids = set(components.keys())

    for cid, c in components.items():
        for field in ["requires_rules", "requires_skills", "guardrails"]:
            refs = c.get(field, [])
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, str) and ref not in known_ids:
                        issues.append(
                            f"  DANGLING: {cid}.{field} references '{ref}' "
                            f"(not in manifest set)"
                        )

        for ref in c.get("enforces", []):
            if isinstance(ref, str) and ref not in known_ids:
                issues.append(
                    f"  DANGLING: {cid}.enforces references '{ref}' "
                    f"(not in manifest set)"
                )

    issues.extend(validate_placeholders(components))
    issues.extend(validate_enforcement_edges(components, root))
    return issues


#: Scaffold placeholders. A manifest carrying one of these has never been filled in,
#: so any query over it returns a confident wrong answer.
_PLACEHOLDER_VALUES = ("TODO_EVENT", "TODO_MATCHER", "TODO", "FIXME", "CHANGEME")


def validate_placeholders(components):
    """Reject scaffold placeholders left in manifest VALUES.

    Audit finding M5, fixed 2026-07-26. `manifests/compile.py --check` exited 0 with
    five hook manifests still carrying `event: TODO_EVENT` / `matcher: "TODO_MATCHER"`
    from the scaffolder. That matters more than ordinary staleness because the
    manifest graph is cited as the authoritative enforcement topology: a query for
    "which hooks fire on Write" silently omits or misreports a hook whose event is a
    placeholder, and the caller has no way to tell.

    Placeholders inside COMMENTS are fine -- `enforces: []  # TODO: which rules?` is
    an honest open question, not a false fact. This checks parsed VALUES only, which
    is exactly the distinction that makes the rule safe to enforce.
    """
    issues = []
    for cid, c in sorted(components.items()):
        if not isinstance(c, dict):
            continue
        for field, value in sorted(c.items()):
            if isinstance(value, str) and value.strip() in _PLACEHOLDER_VALUES:
                issues.append(
                    f"  PLACEHOLDER: {cid}.{field} is '{value}' — a scaffold value "
                    f"that was never filled in. Set the real value, or if this "
                    f"component is not a registered hook, correct its type."
                )
    return issues


def validate_semantic(root: Path, components):
    """Cross-reference manifest content against source files.

    Returns list of issues (warnings, not errors — manifests may
    intentionally differ from prose if the prose is aspirational).
    """
    import re as _re

    issues = []

    for cid, c in components.items():
        source = c.get("_source", "")

        if c.get("type") == "skill" and "skills/" in source:
            skill_md = root / "skills" / cid / "SKILL.md"
            if not skill_md.exists():
                issues.append(f"  MISSING_SOURCE: {cid} manifest exists but SKILL.md not found")
                continue

            try:
                body = skill_md.read_text(encoding="utf-8")
            except Exception:
                continue

            def _server_prefix(tool_ref: str) -> str:
                """Normalize an MCP tool reference to `mcp__<server>__*`.

                Handles both exact (`mcp__server__foo`) and wildcard
                (`mcp__server__*`) forms so source-side and manifest-side
                comparisons happen at the same granularity. Without this,
                a manifest listing the exact tool was reported as drift
                against a source body that the compiler had normalized
                to wildcard — a 40-of-53 false-positive rate (2026-05-23).
                """
                return tool_ref.rsplit("__", 1)[0] + "__*"

            source_tools = set()
            for match in _re.finditer(r"mcp__[\w-]+__[\w*]+", body):
                source_tools.add(_server_prefix(match.group()))

            manifest_tools = set()
            for tool in c.get("requires_tools", []):
                if tool.startswith("mcp__"):
                    manifest_tools.add(_server_prefix(tool))

            prose_only_tools = set()
            for tool in c.get("prose_only_tools", []):
                if isinstance(tool, str) and tool.startswith("mcp__"):
                    prose_only_tools.add(_server_prefix(tool))

            in_source_not_manifest = source_tools - manifest_tools - prose_only_tools
            for missing_tool in sorted(in_source_not_manifest):
                server_name = missing_tool.split("__")[1]
                issues.append(
                    f"  DRIFT: {cid}/SKILL.md references {missing_tool} "
                    f"but manifest requires_tools doesn't include it "
                    f"(server: {server_name})"
                )

        elif c.get("type") == "hook":
            hook_py = root / "hooks" / f"{cid}.py"
            if not hook_py.exists():
                pass  # hook script missing is allowed (some hooks are inline)

        elif c.get("type") == "rule":
            # THREE valid homes, in descending delivery strength:
            #   rules/<name>.md                 ambient -- loaded every session
            #   skills/_shared/<name>.md        skill-scoped -- delivered by a
            #                                   REQUIRED-READ pointer in each owner
            #                                   skill's body (same mechanism as
            #                                   skills/_shared/model-runtime-policy.md,
            #                                   read by 18+ skills)
            #   agent-memory/rules/<name>.md    lazy -- HISTORICAL ONLY. The injector
            #                                   was RETIRED 2026-07-29 (see the comment
            #                                   in hooks/auto-topic-loader.py); nothing
            #                                   reads this path today. Accepted here so
            #                                   an old manifest does not hard-fail, but
            #                                   it is NOT a live destination: a rule
            #                                   moved there is deleted with extra steps.
            #
            # skills/_shared/ was added 2026-08-26 when output-grounding was relocated
            # out of ambient (relocation pilot: EXPOSED=0 over 438 transcripts). Without
            # it, relocating a rule forces a choice between a MISSING_SOURCE error and
            # deleting a REAL declared dependency from an owner skill's requires_rules --
            # so the reduction path had no legal exit. This is that exit.
            rule_md = root / "rules" / f"{cid}.md"
            shared_md = root / "skills" / "_shared" / f"{cid}.md"
            lazy_md = root / "agent-memory" / "rules" / f"{cid}.md"
            if not (rule_md.exists() or shared_md.exists() or lazy_md.exists()):
                issues.append(f"  MISSING_SOURCE: {cid} manifest exists but {cid}.md not found")

    return issues


def compile_graph(
    root: Path,
    check_only=False,
    quiet=False,
    no_reindex=False,
    strict_semantic=False,
):
    """Compile manifests into graph.json. Returns issue count."""
    components = load_manifests(root)
    graph_path = root / "manifests" / "graph.json"

    skills = sum(1 for c in components.values() if c.get("type") == "skill")
    hooks = sum(1 for c in components.values() if c.get("type") == "hook")
    rules = sum(1 for c in components.values() if c.get("type") == "rule")
    total = len(components)

    if not quiet:
        print(f"Loaded {total} manifests: {skills} skills, {hooks} hooks, {rules} rules")

    struct_issues = validate(components, root)
    sem_issues = validate_semantic(root, components)

    if struct_issues:
        print(f"\nStructural issues ({len(struct_issues)}):")
        for issue in struct_issues:
            print(issue)
    elif not quiet:
        print("Structural validation: OK (no dangling references)")

    # Split semantic results: MISSING_SOURCE is always a hard error (manifest
    # points at a file that doesn't exist); DRIFT stays advisory for ordinary
    # interactive runs but becomes fatal under --strict-semantic in CI and
    # release qualification.
    sem_errors = [i for i in sem_issues if "MISSING_SOURCE" in i]
    sem_warnings = [i for i in sem_issues if "DRIFT" in i]

    if sem_errors:
        print(f"\nSemantic errors ({len(sem_errors)}):")
        for issue in sem_errors:
            print(issue)
    if sem_warnings:
        print(f"\nSemantic drift warnings ({len(sem_warnings)}):")
        for issue in sem_warnings:
            print(issue)
    if not sem_issues and not quiet:
        print("Semantic validation: OK (manifests match source files)")

    # Hard issues always block. CI/release qualification opts into semantic
    # drift as a gate now that the checked-in baseline is clean; interactive
    # callers retain the advisory default for backwards compatibility.
    issues = struct_issues + sem_errors
    if strict_semantic:
        issues += sem_warnings

    if not check_only:
        derived_enforcement = derive_enforced_by(components, root) or {}
        graph = {}
        for cid, c in components.items():
            entry = {k: v for k, v in c.items() if not k.startswith("_")}
            if c.get("type") == "rule":
                entry["enforced_by"] = derived_enforcement.get(cid, [])
            graph[cid] = entry

        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(graph_path, "w", encoding="utf-8") as fh:
            json.dump(graph, fh, indent=2, default=str)
        if not quiet:
            print(f"\nCompiled graph written to {graph_path}")
            print(f"  Size: {graph_path.stat().st_size:,} bytes")

        if not no_reindex and not quiet:
            print("  Reindex: graph.json updated — code-search will pick up changes on next incremental index")
    elif not quiet:
        print("\n--check mode: no files written")

    return len(issues)


def _default_root() -> Path:
    """Pick the most sensible default root.

    Prefer the claude-config checkout containing this script (manifests/ lives
    inside the repo). Fall back to ~/.claude for legacy deployments. Resolving
    via this script's location, not cwd, keeps behavior stable regardless of
    where the user invokes from.
    """
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    if (repo_root / "skills").is_dir() and (repo_root / "hooks").is_dir():
        return repo_root
    return Path.home() / ".claude"


def main():
    parser = argparse.ArgumentParser(description="Compile manifests into graph.json with validation.")
    parser.add_argument(
        "--root",
        type=Path,
        default=_default_root(),
        help="Root directory containing skills/, hooks/, rules/, manifests/ "
             "(default: the claude-config checkout containing this script, "
             "or ~/.claude if no checkout is detected)",
    )
    parser.add_argument("--check", action="store_true", help="Validate only; don't write graph.json. Exits non-zero on issues.")
    parser.add_argument(
        "--strict-semantic",
        action="store_true",
        help="Treat source/manifest semantic drift as an error (for CI and release qualification).",
    )
    parser.add_argument("--no-reindex", action="store_true", help="Skip the code-search reindex notification.")
    parser.add_argument("--quiet", action="store_true", help="Suppress success output; only print on issues.")
    args = parser.parse_args()

    if not args.root.exists():
        print(f"ERROR: root does not exist: {args.root}", file=sys.stderr)
        sys.exit(2)

    issue_count = compile_graph(
        args.root,
        check_only=args.check,
        quiet=args.quiet,
        no_reindex=args.no_reindex,
        strict_semantic=args.strict_semantic,
    )
    sys.exit(1 if issue_count > 0 else 0)


if __name__ == "__main__":
    main()
