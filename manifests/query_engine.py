"""Query engine for machine-first architecture manifests.

Loads YAML manifests from co-located paths across the architecture,
builds an in-memory dependency graph, and answers typed queries.

Manifest locations (root defaults to ~/.claude, override with --root):
  - Skills: <root>/skills/*/manifest.yaml
  - Hooks:  <root>/hooks/manifests/*.yaml
  - Rules:  <root>/rules/manifests/*.yaml

Or reads from compiled graph.json if available and fresh.

Usage:
  python query_engine.py depends_on triage
  python query_engine.py depended_on_by bash-security-guard
  python query_engine.py enforcement_chain "Edit settings.json"
  python query_engine.py auth_requirements triage
  python query_engine.py impact_of_removal auto-topic-loader
  python query_engine.py unenforced_rules
  python query_engine.py skills_requiring_auth
  python query_engine.py hooks_for_tool "Bash"
  python query_engine.py skills_by_category operations
  python query_engine.py constraint_check "dispatch subagent for CrowdStrike"
  python query_engine.py full_session_hooks
  python query_engine.py coverage
  python query_engine.py --root /path/to/repo coverage  # operate on a checkout instead of ~/.claude
"""
import argparse
import json
import sys
from pathlib import Path

import yaml


def _default_root() -> Path:
    """Pick the most sensible default root.

    Prefer the claude-config checkout containing this script (manifests/ lives
    inside the repo). Fall back to ~/.claude for legacy deployments. Matches
    compile.py's behavior so the documented commands work without --root.
    """
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    if (repo_root / "skills").is_dir() and (repo_root / "hooks").is_dir():
        return repo_root
    return Path.home() / ".claude"


# Default root; can be overridden via --root. Resolved at parse time in main().
# Module-level constant kept for back-compat with external importers.
CLAUDE_DIR = _default_root()


def _manifest_sources(root: Path):
    return [
        ("skill", root / "skills", "*/manifest.yaml"),
        ("hook", root / "hooks" / "manifests", "*.yaml"),
        ("rule", root / "rules" / "manifests", "*.yaml"),
    ]


# Back-compat module-level constants (some external callers import these).
GRAPH_PATH = CLAUDE_DIR / "manifests" / "graph.json"
MANIFEST_SOURCES = _manifest_sources(CLAUDE_DIR)


def load_all(root: Path = None):
    """Load manifests from co-located paths or compiled graph.

    If ``root`` is None, falls back to ``CLAUDE_DIR`` (i.e. ~/.claude) for
    backward compatibility with callers that imported and called load_all()
    with no arguments.
    """
    if root is None:
        root = CLAUDE_DIR
    graph_path = root / "manifests" / "graph.json"
    sources = _manifest_sources(root)

    # Try compiled graph first (faster)
    if graph_path.exists():
        graph_mtime = graph_path.stat().st_mtime
        # Check if any manifest is newer than graph
        stale = False
        for _, base, pattern in sources:
            if not base.exists():
                continue
            for f in base.glob(pattern):
                if f.stat().st_mtime > graph_mtime:
                    stale = True
                    break
            if stale:
                break

        if not stale:
            with open(graph_path, encoding="utf-8") as fh:
                return json.load(fh)

    # Load from individual manifests
    components = {}
    for comp_type, base, pattern in sources:
        if not base.exists():
            continue
        for f in base.glob(pattern):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if data and "id" in data:
                    data["_source"] = str(f.relative_to(root))
                    components[data["id"]] = data
            except Exception:
                pass
    return components


def depends_on(components, component_id):
    """All dependencies of a component."""
    c = components.get(component_id)
    if not c:
        return {"error": f"Component '{component_id}' not found"}
    deps = {}
    for field in [
        "requires_tools", "requires_topics", "requires_rules",
        "requires_skills", "requires_auth", "enforces",
        "enforced_by", "guardrails", "depends_on_files",
        "depends_on_env",
    ]:
        val = c.get(field, [])
        if val:
            deps[field] = val
    return deps


def depended_on_by(components, component_id):
    """Reverse dependency: what depends on this component."""
    dependents = []
    for cid, c in components.items():
        if cid == component_id:
            continue
        for field in [
            "requires_tools", "requires_topics", "requires_rules",
            "requires_skills", "enforces", "enforced_by", "guardrails",
        ]:
            val = c.get(field, [])
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and component_id in item:
                        dependents.append({"id": cid, "type": c["type"], "via": field})
                        break
                    elif isinstance(item, dict) and component_id in str(item):
                        dependents.append({"id": cid, "type": c["type"], "via": field})
                        break
    return dependents



def _matcher(c) -> str:
    """A hook's matcher as a STRING, never None.

    `dict.get("matcher", "")` returns None when the key EXISTS with a null value --
    the default only covers a MISSING key. Valid hook manifests legitimately carry
    `matcher: null` (git_lock and macos_notify are matcher-less components), so
    every containment check against a raw `.get` crashed:

        TypeError: argument of type 'NoneType' is not a container or iterable

    That made both documented queries (`enforcement_chain`, `hooks_for_tool`) exit 1
    on a correct manifest set -- audit finding M5, fixed 2026-07-26. A null matcher
    means "this event has no matcher", which is semantically the match-all/empty
    case, so normalizing to "" is correct rather than merely defensive.
    """
    m = c.get("matcher")
    return "" if m is None else str(m)

def enforcement_chain(components, action_desc):
    """Which hooks fire for a given action description."""
    action_lower = action_desc.lower()
    tool_hints = {
        "bash": "Bash", "edit": "Edit", "write": "Write", "read": "Read",
        "glob": "Glob", "grep": "Grep", "agent": "Agent", "skill": "Skill",
        "settings.json": "Write|Edit", "mcp": "mcp__",
    }
    matched_matchers = set()
    for keyword, matcher in tool_hints.items():
        if keyword in action_lower:
            matched_matchers.add(matcher)

    chain = []
    for cid, c in components.items():
        if c.get("type") != "hook":
            continue
        hook_matcher = _matcher(c)
        for m in matched_matchers:
            if m in hook_matcher or hook_matcher in m:
                chain.append({
                    "hook": cid,
                    "event": c.get("event"),
                    "action_type": c.get("action_type"),
                    "description": c.get("description", "")[:80],
                })
                break

    event_order = {"PreToolUse": 0, "PostToolUse": 1, "PostToolUseFailure": 2}
    chain.sort(key=lambda h: event_order.get(h["event"], 99))
    return chain


def auth_requirements(components, skill_id):
    """Auth requirements for a skill."""
    c = components.get(skill_id)
    if not c or c.get("type") != "skill":
        return {"error": f"Skill '{skill_id}' not found"}
    return {
        "auth_providers": c.get("requires_auth", []),
        "auth_constraint": c.get("auth_constraint", "any"),
        "subagent_safe": c.get("auth_constraint", "any") != "main_thread_only",
    }


def impact_of_removal(components, component_id):
    """What breaks if this component is removed."""
    dependents = depended_on_by(components, component_id)
    c = components.get(component_id, {})
    impact = {
        "component": component_id,
        "type": c.get("type", "unknown"),
        "direct_dependents": len(dependents),
        "dependents": dependents,
    }
    if c.get("type") == "hook":
        rules_losing = []
        for cid, comp in components.items():
            if comp.get("type") == "rule":
                enforced = comp.get("enforced_by", [])
                if component_id in enforced:
                    remaining = [e for e in enforced if e != component_id]
                    rules_losing.append({
                        "rule": cid,
                        "remaining_enforcement": remaining or "NONE",
                    })
        if rules_losing:
            impact["rules_losing_enforcement"] = rules_losing
    return impact


def unenforced_rules(components):
    """Rules with no mechanical enforcement."""
    return [
        {"rule": cid, "description": c.get("description", "")[:80]}
        for cid, c in components.items()
        if c.get("type") == "rule" and c.get("enforcement_coverage") == "none"
    ]


def skills_requiring_auth(components):
    """Skills needing authenticated remote MCP access."""
    return [
        {
            "skill": cid,
            "providers": [a["provider"] if isinstance(a, dict) else a for a in c.get("requires_auth", [])],
            "constraint": c.get("auth_constraint", "any"),
        }
        for cid, c in components.items()
        if c.get("type") == "skill" and c.get("requires_auth")
    ]


def hooks_for_tool(components, tool_name):
    """All hooks that fire for a given tool name."""
    return [
        {
            "hook": cid,
            "event": c.get("event"),
            "action_type": c.get("action_type"),
            "matcher": _matcher(c),
        }
        for cid, c in components.items()
        if c.get("type") == "hook"
        and (tool_name in _matcher(c) or _matcher(c) == ".*")
    ]


def skills_by_category(components, category):
    """All skills in a given category."""
    return [
        {"skill": cid, "description": c.get("description", "")[:80]}
        for cid, c in components.items()
        if c.get("type") == "skill" and c.get("category") == category
    ]


def constraint_check(components, proposed_action):
    """Which rules and hooks would flag a proposed action."""
    action_lower = proposed_action.lower()
    flags = []
    for cid, c in components.items():
        if c.get("type") == "rule":
            for pa in c.get("prohibited_actions", []):
                if any(word in action_lower for word in pa.lower().split()[:3]):
                    flags.append({"type": "rule", "id": cid, "violation": pa})
        elif c.get("type") == "hook" and c.get("action_type") == "guard":
            for bp in c.get("blocks_patterns", []):
                if any(word in action_lower for word in bp.lower().split()[:3]):
                    flags.append({"type": "hook", "id": cid, "blocks": bp})
    return flags


def full_session_hooks(components):
    """Hooks organized by lifecycle event."""
    lifecycle = {}
    for cid, c in components.items():
        if c.get("type") != "hook":
            continue
        event = c.get("event", "unknown")
        lifecycle.setdefault(event, []).append({
            "hook": cid,
            "action_type": c.get("action_type"),
            "matcher": _matcher(c),
        })
    event_order = [
        "SessionStart", "UserPromptSubmit", "PreToolUse",
        "PostToolUse", "PostToolUseFailure",
        "SubagentStart", "SubagentStop",
        "PreCompact", "Stop", "StopFailure",
    ]
    ordered = {}
    for event in event_order:
        if event in lifecycle:
            ordered[event] = lifecycle[event]
    for event, hooks_list in lifecycle.items():
        if event not in ordered:
            ordered[event] = hooks_list
    return ordered


def coverage(components, root: Path = None):
    """Report manifest coverage across the architecture.

    ``root`` defaults to ``CLAUDE_DIR`` (~/.claude) for back-compat with
    callers that pass only ``components``. CLI passes the parsed --root.
    """
    if root is None:
        root = CLAUDE_DIR
    skills_dir = root / "skills"
    hooks_dir = root / "hooks"
    rules_dir = root / "rules"

    # Count actual components
    skill_dirs = [d for d in skills_dir.iterdir()
                  if d.is_dir() and (d / "SKILL.md").exists()
                  and d.name != "_shared"]
    hook_files = [f for f in hooks_dir.glob("*.py")
                  if f.name != "__init__.py"
                  and not f.name.startswith("_")]
    rule_files = list(rules_dir.glob("*.md"))

    # Count manifested components
    skill_manifests = list(skills_dir.glob("*/manifest.yaml"))
    hook_manifests = list((hooks_dir / "manifests").glob("*.yaml")) if (hooks_dir / "manifests").exists() else []
    rule_manifests = list((rules_dir / "manifests").glob("*.yaml")) if (rules_dir / "manifests").exists() else []

    # Find unmanifested
    manifested_skills = {m.parent.name for m in skill_manifests}
    unmanifested_skills = sorted(d.name for d in skill_dirs if d.name not in manifested_skills)

    manifested_hooks = {m.stem for m in hook_manifests}
    unmanifested_hooks = sorted(f.stem for f in hook_files if f.stem not in manifested_hooks)

    manifested_rules = {m.stem for m in rule_manifests}
    unmanifested_rules = sorted(f.stem for f in rule_files if f.stem not in manifested_rules)

    total = len(skill_dirs) + len(hook_files) + len(rule_files)
    manifested = len(skill_manifests) + len(hook_manifests) + len(rule_manifests)

    return {
        "summary": f"{manifested}/{total} components manifested ({100*manifested//total if total else 0}%)",
        "skills": f"{len(skill_manifests)}/{len(skill_dirs)}",
        "hooks": f"{len(hook_manifests)}/{len(hook_files)}",
        "rules": f"{len(rule_manifests)}/{len(rule_files)}",
        "unmanifested_skills": unmanifested_skills[:20],
        "unmanifested_hooks": unmanifested_hooks[:20],
        "unmanifested_rules": unmanifested_rules[:10],
    }


def context_for_task(components, task_description):
    """Composite query: given a task description, return the full context
    package a planner needs — matching skills, their dependencies, auth
    requirements, applicable hooks, enforcement gaps, and relevant topics.

    Replaces 4-5 individual queries in superplan Phase 3 with one call.
    Inspired by codemap's context tool pattern.
    """
    import re as _re
    task_lower = task_description.lower()
    result = {
        "task": task_description,
        "matching_skills": [],
        "auth_summary": {},
        "topics_to_load": [],
        "enforcement_gaps": [],
        "applicable_hooks": [],
    }

    # Find skills whose description or id matches the task
    matched_skills = []
    for cid, c in components.items():
        if c.get("type") != "skill":
            continue
        desc = c.get("description", "").lower()
        # Match on skill name in task, or keyword overlap with description
        name_match = _re.search(rf"\b{_re.escape(cid)}\b", task_lower)
        # Score keyword overlap between task and description
        task_words = set(task_lower.split())
        desc_words = set(desc.split())
        overlap = len(task_words & desc_words)
        if name_match or overlap >= 3:
            score = (10 if name_match else 0) + overlap
            matched_skills.append((cid, c, score))

    matched_skills.sort(key=lambda x: -x[2])
    top_skills = matched_skills[:3]  # Top 3 most relevant

    all_topics = set()
    all_rules = set()

    for cid, c, score in top_skills:
        skill_info = {
            "skill": cid,
            "match_score": score,
            "description": c.get("description", "")[:100],
            "auth_constraint": c.get("auth_constraint", "any"),
            "execution_context": c.get("execution_context", "main_thread"),
            "requires_auth": c.get("requires_auth", []),
            "requires_tools": c.get("requires_tools", []),
            "side_effects": c.get("side_effects", []),
            "threat_model": c.get("threat_model", "unknown"),
            "estimated_turns": c.get("estimated_turns", "unknown"),
            "preconditions": c.get("preconditions", []),
        }
        result["matching_skills"].append(skill_info)

        # Collect topics and rules
        for t in c.get("requires_topics", []):
            all_topics.add(t)
        for r in c.get("requires_rules", []):
            all_rules.add(r)

        # Auth summary
        if c.get("auth_constraint") == "main_thread_only":
            providers = [
                p["provider"] if isinstance(p, dict) else p
                for p in c.get("requires_auth", [])
            ]
            result["auth_summary"][cid] = {
                "constraint": "main_thread_only",
                "providers": providers,
                "subagent_safe": False,
            }

    result["topics_to_load"] = sorted(all_topics)

    # Check enforcement coverage for relevant rules
    for rule_id in sorted(all_rules):
        rule = components.get(rule_id)
        if rule and rule.get("enforcement_coverage") == "none":
            result["enforcement_gaps"].append({
                "rule": rule_id,
                "description": rule.get("description", "")[:80],
                "enforced_by": "NONE (prose only)",
            })

    # Find hooks that fire for the tools used by matched skills
    tool_matchers = set()
    for _, c, _ in top_skills:
        for tool in c.get("requires_tools", []):
            if tool.startswith("mcp__"):
                tool_matchers.add("mcp__")
            elif tool in ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent"):
                tool_matchers.add(tool)

    for cid, c in components.items():
        if c.get("type") != "hook":
            continue
        hook_matcher = _matcher(c)
        for tm in tool_matchers:
            if tm in hook_matcher:
                result["applicable_hooks"].append({
                    "hook": cid,
                    "event": c.get("event"),
                    "action_type": c.get("action_type"),
                    "description": c.get("description", "")[:60],
                })
                break

    return result


def _build_commands(root: Path):
    """Build the command dispatch table bound to a specific root.

    ``coverage`` needs the root so it can locate skills/, hooks/, and rules/
    against a non-default checkout. Other queries only need ``components``.
    """
    return {
        "depends_on": lambda c, arg: depends_on(c, arg),
        "depended_on_by": lambda c, arg: depended_on_by(c, arg),
        "enforcement_chain": lambda c, arg: enforcement_chain(c, arg),
        "auth_requirements": lambda c, arg: auth_requirements(c, arg),
        "impact_of_removal": lambda c, arg: impact_of_removal(c, arg),
        "unenforced_rules": lambda c, _: unenforced_rules(c),
        "skills_requiring_auth": lambda c, _: skills_requiring_auth(c),
        "hooks_for_tool": lambda c, arg: hooks_for_tool(c, arg),
        "skills_by_category": lambda c, arg: skills_by_category(c, arg),
        "constraint_check": lambda c, arg: constraint_check(c, arg),
        "full_session_hooks": lambda c, _: full_session_hooks(c),
        "coverage": lambda c, _: coverage(c, root),
        "context_for_task": lambda c, arg: context_for_task(c, arg),
    }


# Back-compat: keep the module-level COMMANDS dict for external importers.
COMMANDS = _build_commands(CLAUDE_DIR)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Query the architecture manifest graph.",
        # Use a custom usage line so the legacy two-positional form
        # (command + free-text argument) is preserved.
        usage="python query_engine.py [--root PATH] <command> [argument...]",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=CLAUDE_DIR,
        help="Root directory containing skills/, hooks/, rules/, manifests/ "
             "(default: ~/.claude)",
    )
    parser.add_argument("command", nargs="?",
                        help=f"Query name. One of: {', '.join(sorted(_build_commands(CLAUDE_DIR).keys()))}")
    parser.add_argument("argument", nargs="*", default=[],
                        help="Optional argument passed to the query (e.g. a component id).")
    args = parser.parse_args()

    if not args.command:
        parser.print_usage()
        print(f"Commands: {', '.join(sorted(_build_commands(args.root).keys()))}")
        sys.exit(1)

    cmds = _build_commands(args.root)
    if args.command not in cmds:
        print(f"Unknown command: {args.command}")
        print(f"Available: {', '.join(sorted(cmds.keys()))}")
        sys.exit(1)

    arg = " ".join(args.argument)
    components = load_all(args.root)
    result = cmds[args.command](components, arg)
    print(json.dumps(result, indent=2, default=str))
