"""Compile all co-located manifests into a single graph.json.

Reads manifests from:
  - <root>/skills/*/manifest.yaml
  - <root>/hooks/manifests/*.yaml
  - <root>/rules/manifests/*.yaml

Validates references and produces:
  - <root>/manifests/graph.json (compiled graph for query engine)
  - Validation report (dangling references, missing manifests, dangling routes)

Usage:
  python compile.py                    # compile and validate (root=~/.claude)
  python compile.py --check            # validate only, don't write (exits non-zero on hard issues)
  python compile.py --check --strict-semantic  # also fail on source/manifest drift
  python compile.py --root <path>      # operate on a different checkout (e.g., a worktree or CI)
  python compile.py --quiet            # suppress success output (only print on issues)
"""
import argparse
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


def validate(components):
    """Validate cross-references between manifests. Returns list of issues."""
    issues = []
    known_ids = set(components.keys())

    for cid, c in components.items():
        for field in ["requires_rules", "requires_skills", "enforced_by", "guardrails"]:
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


def validate_skill_rules(root: Path):
    """Validate that hooks/skill-rules.json routes point at real skill folders.

    Returns list of issues. Skips silently if skill-rules.json doesn't exist.
    """
    issues = []
    rules_path = root / "hooks" / "skill-rules.json"
    if not rules_path.exists():
        return issues

    try:
        with open(rules_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        issues.append(f"  ERROR loading {rules_path}: {e}")
        return issues

    skills_dir = root / "skills"

    for i, rule in enumerate(data.get("rules", [])):
        skill_ref = rule.get("skill")
        if skill_ref and not (skills_dir / skill_ref / "SKILL.md").exists():
            issues.append(
                f"  DANGLING_ROUTE: skill-rules.json[{i}] routes to '{skill_ref}' "
                f"(no skills/{skill_ref}/SKILL.md found)"
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

    struct_issues = validate(components)
    route_issues = validate_skill_rules(root)
    sem_issues = validate_semantic(root, components)

    if struct_issues:
        print(f"\nStructural issues ({len(struct_issues)}):")
        for issue in struct_issues:
            print(issue)
    elif not quiet:
        print("Structural validation: OK (no dangling references)")

    if route_issues:
        print(f"\nRouting issues ({len(route_issues)}):")
        for issue in route_issues:
            print(issue)
    elif not quiet:
        print("Routing validation: OK (skill-rules.json points at real skills)")

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
    issues = struct_issues + route_issues + sem_errors
    if strict_semantic:
        issues += sem_warnings

    if not check_only:
        graph = {}
        for cid, c in components.items():
            graph[cid] = {k: v for k, v in c.items() if not k.startswith("_")}

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
