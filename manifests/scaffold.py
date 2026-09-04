"""Scaffold manifest.yaml files from existing SKILL.md, hook .py, and rule .md files.

Extracts what grep can answer mechanically:
  - Skills: MCP tool references, topic file mentions, frontmatter fields
  - Hooks: docstring metadata, exit codes, event/matcher from settings.json
  - Rules: section headers, applies-to patterns, incident references

Produces draft manifests with TODO markers for fields requiring judgment:
  - auth_constraint, threat_model, enforcement_coverage
  - preconditions, guardrails, side_effects

Usage:
  python scaffold.py                     # scaffold all unmanifested components
  python scaffold.py --skills            # skills only
  python scaffold.py --hooks             # hooks only
  python scaffold.py --rules             # rules only
  python scaffold.py --component triage  # single component by name
  python scaffold.py --dry-run           # show what would be created, don't write
"""
import argparse
import json
import re
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SKILLS_DIR = CLAUDE_DIR / "skills"
HOOKS_DIR = CLAUDE_DIR / "hooks"
RULES_DIR = CLAUDE_DIR / "rules"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"


def _load_settings():
    """Load settings.json for hook registrations."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _extract_frontmatter(text):
    """Extract YAML frontmatter from a markdown file."""
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).split("\n"):
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def _extract_mcp_tools(text):
    """Find MCP tool references in text."""
    tools = set()
    for match in re.finditer(r"mcp__[\w-]+__[\w*]+", text):
        ref = match.group()
        prefix = ref.rsplit("__", 1)[0] + "__*"
        tools.add(prefix)
    # Also find built-in tool references
    for builtin in ["Bash", "Read", "Write", "Edit", "Grep", "Glob", "Agent"]:
        if re.search(rf"\b{builtin}\b", text):
            tools.add(builtin)
    return sorted(tools)


def _extract_topics(text):
    """Find topic file references in text."""
    topics = set()
    for match in re.finditer(r"topics?/(\w[\w-]*\.md)", text):
        topics.add(match.group(1))
    # Also match "Load topics: X.md, Y.md" patterns
    for match in re.finditer(r"Load topics?:\s*([a-zA-Z0-9_\-.,\s]+\.md)", text, re.IGNORECASE):
        for t in match.group(1).split(","):
            t = t.strip()
            if t:
                topics.add(t)
    return sorted(topics)


def _extract_rule_refs(text):
    """Find rule file references in text."""
    rules = set()
    for match in re.finditer(r"rules?/(\w[\w-]*)\.md", text):
        rules.add(match.group(1))
    return sorted(rules)


def _extract_skill_refs(text):
    """Find skill references like /skill-name or requires: skill-name."""
    skills = set()
    for match in re.finditer(r"/(\w[\w-]+)", text):
        name = match.group(1)
        if (SKILLS_DIR / name / "SKILL.md").exists():
            skills.add(name)
    return sorted(skills)


def _guess_category(name, text):
    """Guess skill category from name and content."""
    if any(w in name for w in ["triage", "investigate", "alert", "monitor", "cc-monitor"]):
        return "operations"
    if any(w in name for w in ["stig", "semgrep", "codeql", "fp-check", "threat", "security",
                                "differential", "insecure", "sharp", "variant", "agentic"]):
        return "security"
    if any(w in name for w in ["plan", "brainstorm", "refine", "interview", "deep-dive",
                                "gather", "scout", "evaluate", "absorb", "dispatch", "council"]):
        return "planning"
    if any(w in name for w in ["capture", "distill", "recall", "garden", "review", "api-guard",
                                "api-ingest", "api-preflight"]):
        return "knowledge"
    if any(w in name for w in ["code-explore", "codebase", "index"]):
        return "code-intel"
    if any(w in name for w in ["ship", "pr-fix", "cross-repo", "sync"]):
        return "shipping"
    if any(w in name for w in ["healthcheck", "audit", "validate", "retro", "retrospective",
                                "handoff", "obsidian", "weekly", "systematic", "test-driven",
                                "verification", "writing-plan", "subagent-driven"]):
        return "maintenance"
    return "TODO_CATEGORY"


def scaffold_skill(name, dry_run=False):
    """Generate a draft manifest for a skill."""
    skill_md = SKILLS_DIR / name / "SKILL.md"
    manifest_path = SKILLS_DIR / name / "manifest.yaml"

    if manifest_path.exists():
        return None  # Already manifested

    if not skill_md.exists():
        return None

    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm = _extract_frontmatter(text)
    tools = _extract_mcp_tools(text)
    topics = _extract_topics(text)
    rule_refs = _extract_rule_refs(text)
    skill_refs = _extract_skill_refs(text)
    category = _guess_category(name, text)

    # Detect if it uses remote MCP (needs auth)
    has_remote = any("remote-" in t for t in tools)

    lines = [
        f"id: {name}",
        "type: skill",
        f'description: "{fm.get("description", "TODO_DESCRIPTION")[:200]}"',
        f"category: {category}",
        "",
        "requires_tools:",
    ]
    for t in tools:
        lines.append(f'  - "{t}"')
    if not tools:
        lines.append("  []")

    lines.append("requires_topics:")
    for t in topics:
        lines.append(f"  - {t}")
    if not topics:
        lines.append("  []")

    lines.append("requires_rules:")
    for r in rule_refs:
        lines.append(f"  - {r}")
    if not rule_refs:
        lines.append("  []")

    lines.append("requires_skills:")
    for s in skill_refs:
        lines.append(f"  - {s}")
    if not skill_refs:
        lines.append("  []")

    if has_remote:
        lines.append("requires_auth:  # TODO: fill in provider/scope/constraint")
        lines.append("  - provider: TODO_PROVIDER")
        lines.append("    scope: read")
        lines.append("    constraint: main_thread_only")
    else:
        lines.append("requires_auth: []")

    lines.extend([
        "",
        "input_contract:",
        "  parameters: {}  # TODO: define parameters",
        f"  scope_from: {'argument' if fm.get('argument-hint') else 'none'}",
        "output_contract:",
        "  produces: []  # TODO: what does this skill produce?",
        "  format: markdown_report",
        "",
        "side_effects: []  # TODO: none, writes_files, creates_pr, sends_message, modifies_memory",
        "execution_context: main_thread  # TODO: main_thread, worker, parallel_workers, agent_team",
        f"auth_constraint: {'main_thread_only' if has_remote else 'any'}",
        'estimated_turns: "TODO"',
        "",
        "preconditions: []  # TODO",
        "guardrails: []  # TODO: hook IDs",
        f"threat_model: {'TODO_HAS_REMOTE_MCP' if has_remote else 'read_only'}  # TODO: read_only, writes_local, writes_remote, destructive",
    ])

    content = "\n".join(lines) + "\n"

    if dry_run:
        return {"path": str(manifest_path), "content": content, "tools": len(tools), "topics": len(topics)}

    manifest_path.write_text(content, encoding="utf-8")
    return {"path": str(manifest_path), "tools": len(tools), "topics": len(topics)}


def scaffold_hook(name, dry_run=False):
    """Generate a draft manifest for a hook."""
    hook_py = HOOKS_DIR / f"{name}.py"
    manifest_dir = HOOKS_DIR / "manifests"
    manifest_path = manifest_dir / f"{name}.yaml"

    if manifest_path.exists():
        return None

    if not hook_py.exists():
        return None

    manifest_dir.mkdir(exist_ok=True)
    text = hook_py.read_text(encoding="utf-8", errors="replace")

    # Extract docstring
    doc_match = re.match(r'"""(.*?)"""', text, re.DOTALL)
    description = ""
    if doc_match:
        doc = doc_match.group(1).strip()
        # First line or first sentence
        description = doc.split("\n")[0].strip()[:200]

    # Find event and matcher from settings.json
    settings = _load_settings()
    event = "TODO_EVENT"
    matcher = "TODO_MATCHER"
    for evt_name, evt_hooks in settings.get("hooks", {}).items():
        for hook_group in evt_hooks:
            for h in hook_group.get("hooks", []):
                cmd = h.get("command", "")
                args = h.get("args", [])
                if (isinstance(cmd, str) and name in cmd) or (
                    isinstance(args, list) and hook_py.name in args
                ):
                    event = evt_name
                    matcher = hook_group.get("matcher", ".*")
                    break

    # Detect action type
    action_type = "guard"  # default
    if "additionalContext" in text:
        action_type = "injector"
    elif "PostToolUse" in event:
        if "decision" in text and "warn" in text:
            action_type = "fixer"
        else:
            action_type = "logger"
    elif "exit(2)" in text or "exit 2" in text:
        action_type = "guard"

    lines = [
        f"id: {name}",
        "type: hook",
        f"event: {event}",
        f'matcher: "{matcher}"',
        "if_condition: null",
        f"action_type: {action_type}",
        f'description: "{description}"',
        "enforces: []  # TODO: which rules does this hook enforce?",
        "blocks_patterns: []  # TODO: what does it block?",
        "injects: null  # TODO: what context does it inject?",
        "modifies: null",
        "depends_on_files: []",
        "depends_on_env: []",
        "exit_codes:",
        '  "0": "allow"',
        '  "2": "block"  # TODO: verify',
        "output_format: json",
        "incidents: []",
    ]

    content = "\n".join(lines) + "\n"

    if dry_run:
        return {"path": str(manifest_path), "content": content, "event": event, "action_type": action_type}

    manifest_path.write_text(content, encoding="utf-8")
    return {"path": str(manifest_path), "event": event, "action_type": action_type}


def scaffold_rule(name, dry_run=False):
    """Generate a draft manifest for a rule."""
    rule_md = RULES_DIR / f"{name}.md"
    manifest_dir = RULES_DIR / "manifests"
    manifest_path = manifest_dir / f"{name}.yaml"

    if manifest_path.exists():
        return None

    if not rule_md.exists():
        return None

    manifest_dir.mkdir(exist_ok=True)
    text = rule_md.read_text(encoding="utf-8", errors="replace")

    # Extract first heading as description
    heading_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    description = heading_match.group(1).strip()[:200] if heading_match else "TODO_DESCRIPTION"

    # Count incident references
    incident_count = len(re.findall(r"incident|2026-\d{2}-\d{2}", text, re.IGNORECASE))

    lines = [
        f"id: {name}",
        "type: rule",
        f'description: "{description}"',
        "applies_to: []  # TODO: what files/tools/actions does this rule cover?",
        "trigger_conditions: []  # TODO: when is this rule relevant?",
        "required_actions: []  # TODO: what must the agent do?",
        "prohibited_actions: []  # TODO: what must the agent NOT do?",
        "enforcement_coverage: none  # TODO: none, partial, full",
        f"incidents: []  # {incident_count} incident references found in source",
        'created_date: "TODO"',
        'last_validated: "TODO"',
    ]

    content = "\n".join(lines) + "\n"

    if dry_run:
        return {"path": str(manifest_path), "content": content, "incidents": incident_count}

    manifest_path.write_text(content, encoding="utf-8")
    return {"path": str(manifest_path), "incidents": incident_count}


def _build_parser() -> argparse.ArgumentParser:
    """Strict argparse — unknown flags fail with a usage line and non-zero exit.

    The prior hand-rolled sys.argv[1:] scan silently accepted any flag,
    including typos like `--skils` (missing l). SKILL.md documents
    behavior on bad flags ("--nonexistent should fail"); argparse's default
    behavior on unknown args matches that contract.
    """
    p = argparse.ArgumentParser(
        prog="scaffold.py",
        description="Scaffold manifest.yaml files for skills, hooks, and rules.",
    )
    p.add_argument("--all", action="store_true",
                   help="Scaffold all three (skills + hooks + rules). Same as no scope flag.")
    p.add_argument("--skills", action="store_true",
                   help="Scaffold skills only (default: all three).")
    p.add_argument("--hooks", action="store_true",
                   help="Scaffold hooks only (default: all three).")
    p.add_argument("--rules", action="store_true",
                   help="Scaffold rules only (default: all three).")
    p.add_argument("--component", default=None, metavar="NAME",
                   help="Scaffold a single named component (skill, hook, or rule).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be created without writing.")
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()
    dry_run = args.dry_run
    # --all is an explicit form of "all three"; functionally identical to passing no scope flag.
    # If no scope flag set, scaffold all three (preserve prior default behavior).
    any_scope = args.skills or args.hooks or args.rules
    do_skills = args.all or args.skills or not any_scope
    do_hooks = args.all or args.hooks or not any_scope
    do_rules = args.all or args.rules or not any_scope

    # Single component mode
    if args.component is not None:
        name = args.component
        result = scaffold_skill(name, dry_run) or scaffold_hook(name, dry_run) or scaffold_rule(name, dry_run)
        if result:
            print(f"{'Would create' if dry_run else 'Created'}: {result['path']}")
            if dry_run and "content" in result:
                print(result["content"])
        else:
            # Not-found must not exit 0: callers couldn't tell a typo'd
            # component name from a successful no-op (2026-06-12 finding).
            print(
                f"error: component '{name}' not found or already manifested.",
                file=sys.stderr,
            )
            print(
                "hint: check the name against skills/, hooks/, rules/ — or "
                "remove the existing manifest to re-scaffold.",
                file=sys.stderr,
            )
            sys.exit(2)
        return

    created = 0
    skipped = 0

    if do_skills:
        print("=== Skills ===")
        for d in sorted(SKILLS_DIR.iterdir()):
            if not d.is_dir() or d.name == "_shared" or not (d / "SKILL.md").exists():
                continue
            result = scaffold_skill(d.name, dry_run)
            if result:
                print(f"  {'[DRY]' if dry_run else '  OK '} {d.name} (tools:{result['tools']}, topics:{result['topics']})")
                created += 1
            else:
                skipped += 1

    if do_hooks:
        print("=== Hooks ===")
        for f in sorted(HOOKS_DIR.glob("*.py")):
            if f.name.startswith("_"):
                continue
            result = scaffold_hook(f.stem, dry_run)
            if result:
                print(f"  {'[DRY]' if dry_run else '  OK '} {f.stem} (event:{result['event']}, type:{result['action_type']})")
                created += 1
            else:
                skipped += 1

    if do_rules:
        print("=== Rules ===")
        for f in sorted(RULES_DIR.glob("*.md")):
            result = scaffold_rule(f.stem, dry_run)
            if result:
                print(f"  {'[DRY]' if dry_run else '  OK '} {f.stem} (incidents:{result['incidents']})")
                created += 1
            else:
                skipped += 1

    print(f"\n{'Would create' if dry_run else 'Created'}: {created} | Already manifested: {skipped}")
    if created and not dry_run:
        print(f"Next: review TODO markers, then run: python {CLAUDE_DIR / 'manifests' / 'compile.py'}")


if __name__ == "__main__":
    main()
