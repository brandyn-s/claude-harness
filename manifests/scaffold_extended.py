"""Scaffold manifests for extended domains: sessions, MCP tools, Terraform.

Usage:
  python scaffold_extended.py --sessions            # session transcripts (last 7 days)
  python scaffold_extended.py --mcp                 # MCP server tools
  python scaffold_extended.py --terraform           # Terraform modules
  python scaffold_extended.py --all                 # everything
  python scaffold_extended.py --dry-run --sessions  # preview without writing

The `--kb` domain is RETIRED. claude-knowledge-base #1239 made `topics/*.md` the
sole authored source, compiled by that repo's `tools/kb.py`; its `check` now
fails if per-topic manifests reappear. Use:
  python3 ~/Documents/knowledge-base/tools/kb.py build
  python3 ~/Documents/knowledge-base/tools/kb.py check
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SESSION_DIR = Path.home() / ".claude" / "session-transcripts"
SESSION_MANIFEST_DIR = Path.home() / ".claude" / "manifests" / "sessions"
MCP_DIR = Path.home() / "Documents" / "GitHub" / "mcp-servers"
MCP_MANIFEST_DIR = MCP_DIR / "manifests" if MCP_DIR.exists() else Path.home() / ".claude" / "manifests" / "mcp-tools"
TF_DIR = Path.home() / "Documents" / "GitHub" / "mcp-infra"
TF_MANIFEST_DIR = TF_DIR / "manifests" if TF_DIR.exists() else Path.home() / ".claude" / "manifests" / "terraform"


# ============================================================
# DOMAIN 2: Session Transcripts (last N days)
# ============================================================
def scaffold_sessions(dry_run=False, days=7):
    """Generate manifests for recent session transcripts."""
    if not SESSION_DIR.exists():
        print("Session transcript directory not found")
        return 0

    if not dry_run:
        SESSION_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now() - timedelta(days=days)
    created = 0

    for f in sorted(SESSION_DIR.glob("*.jsonl")):
        # Parse date from filename: 2026-04-15-12-00-abc123.jsonl
        parts = f.stem.split("-")
        if len(parts) < 3:
            continue
        try:
            file_date = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            continue
        if file_date < cutoff:
            continue

        manifest_path = SESSION_MANIFEST_DIR / f"{f.stem}.yaml"
        if manifest_path.exists():
            continue

        # Quick scan of transcript for metadata
        tools_used = set()
        skills_invoked = set()
        errors = 0
        line_count = 0

        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line_count += 1
                    if '"tool_name"' in line:
                        match = re.search(r'"tool_name"\s*:\s*"([^"]+)"', line)
                        if match:
                            tools_used.add(match.group(1))
                    if '"skill"' in line or '/skill' in line.lower():
                        match = re.search(r'(?:skill["\s:]+|/)(\w[\w-]+)', line)
                        if match:
                            skills_invoked.add(match.group(1))
                    if '"error"' in line or '"Error"' in line:
                        errors += 1
        except Exception:
            continue

        character = "clean" if errors < 3 else ("mixed" if errors < 10 else "rough")

        lines = [
            f"id: {f.stem}",
            "type: session",
            f"date: \"{parts[0]}-{parts[1]}-{parts[2]}\"",
            "duration_minutes: 0  # TODO: compute from timestamps",
            f"skills_invoked: [{', '.join(sorted(skills_invoked)[:10])}]",
            f"tools_used: [{', '.join(sorted(tools_used)[:15])}]",
            "hooks_fired: {}  # populated by manifest_metrics.py",
            "repos_touched: []  # TODO: extract from git commands",
            "prs_created: []  # TODO: extract from gh pr create",
            f"errors_encountered: {errors}",
            "tokens_consumed: 0  # TODO: extract from /stats",
            "distill_lessons: 0  # TODO: extract from distill output",
            f"character: {character}",
        ]
        content = "\n".join(lines) + "\n"

        if not dry_run:
            manifest_path.write_text(content, encoding="utf-8")
        created += 1
        print(f"  {'[DRY]' if dry_run else '  OK '} {f.stem[:30]}... (tools:{len(tools_used)}, skills:{len(skills_invoked)}, errors:{errors}, {character})")

    return created


# ============================================================
# DOMAIN 3: MCP Server Tools
# ============================================================
def scaffold_mcp_tools(dry_run=False):
    """Generate manifests for MCP server tools from mcp-catalog.json or source."""
    catalog_path = MCP_DIR / "mcp-catalog.json"

    if not MCP_DIR.exists():
        print("MCP servers directory not found")
        return 0

    if not dry_run:
        MCP_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    created = 0

    # Try catalog first (structured tool definitions)
    if catalog_path.exists():
        try:
            with open(catalog_path, encoding="utf-8") as f:
                catalog = json.load(f)
            total_catalog_tools = sum(len(v.get("tools", [])) for v in catalog.values())
            if total_catalog_tools > 0:
                for server_name, server_info in catalog.items():
                    for tool in server_info.get("tools", []):
                        tool_id = f"{server_name}__{tool['name']}"
                        manifest_path = MCP_MANIFEST_DIR / f"{tool_id}.yaml"
                        if manifest_path.exists():
                            continue
                        op_type = "read"
                        name_lower = tool["name"].lower()
                        if any(w in name_lower for w in ["create", "add", "assign", "update", "set", "block"]):
                            op_type = "write"
                        elif any(w in name_lower for w in ["delete", "remove", "revoke"]):
                            op_type = "delete"
                        lines = [
                            f"id: {tool_id}",
                            "type: mcp_tool",
                            f"server: {server_name}",
                            f"tool_name: {tool['name']}",
                            f'description: "{tool.get("description", "TODO")[:150]}"',
                            f"operation_type: {op_type}",
                            "auth_provider: TODO",
                            "opa_policy: TODO",
                            "rate_limit: TODO",
                            f"parameters: [{', '.join(list(tool.get('inputSchema', {}).get('properties', {}).keys())[:5])}]",
                            "response_size: TODO",
                            f"side_effects: [{'mutates_state' if op_type != 'read' else 'none'}]",
                            "gov_cloud: TODO",
                        ]
                        content = "\n".join(lines) + "\n"
                        if not dry_run:
                            manifest_path.write_text(content, encoding="utf-8")
                        created += 1
                        print(f"  {'[DRY]' if dry_run else '  OK '} {tool_id} ({op_type})")
                return created
            else:
                print("  Catalog has 0 tools, falling back to source scan")
        except Exception as e:
            print(f"  Catalog parse error: {e}, falling back to source scan")

    # Fallback: scan for tool definitions using multiple patterns
    # Pattern 1: @decorator.tool() def name
    # Pattern 2: Dynamic proxy tools from proxy.py files
    server_dirs = [
        d for d in MCP_DIR.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_"))
        and d.name not in ("docs", "shared", "scripts", "templates")
    ]
    for server_dir in sorted(server_dirs):
        for py_file in server_dir.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            # Pattern 1: decorated tools
            for match in re.finditer(r'@[\w.]+\.tool\(\)\s*\n(?:async )?def (\w+)', text):
                tool_name = match.group(1)
                _create_mcp_manifest(server_dir.name, tool_name, MCP_MANIFEST_DIR, dry_run)
                created += 1
            # Pattern 2: register_tool("name", ...) calls
            for match in re.finditer(r'register_tool\(\s*["\'](\w+)["\']', text):
                tool_name = match.group(1)
                _create_mcp_manifest(server_dir.name, tool_name, MCP_MANIFEST_DIR, dry_run)
                created += 1

    return created


def _create_mcp_manifest(server_name, tool_name, manifest_dir, dry_run):
    """Create a single MCP tool manifest."""
    tool_id = f"{server_name}__{tool_name}"
    manifest_path = manifest_dir / f"{tool_id}.yaml"
    if manifest_path.exists():
        return

    op_type = "read"
    name_lower = tool_name.lower()
    if any(w in name_lower for w in ["create", "add", "assign", "update", "set", "block", "contain", "suppress"]):
        op_type = "write"
    elif any(w in name_lower for w in ["delete", "remove", "revoke"]):
        op_type = "delete"

    lines = [
        f"id: {tool_id}",
        "type: mcp_tool",
        f"server: {server_name}",
        f"tool_name: {tool_name}",
        "description: TODO",
        f"operation_type: {op_type}",
        "auth_provider: TODO",
        "opa_policy: TODO",
        "rate_limit: TODO",
        "parameters: []  # TODO",
        "response_size: TODO",
        f"side_effects: [{'mutates_state' if op_type != 'read' else 'none'}]",
        "gov_cloud: TODO",
    ]
    content = "\n".join(lines) + "\n"
    if not dry_run:
        manifest_path.write_text(content, encoding="utf-8")
    print(f"  {'[DRY]' if dry_run else '  OK '} {tool_id} ({op_type})")
    return True


# ============================================================
# DOMAIN 4: Terraform Modules
# ============================================================
def scaffold_terraform(dry_run=False):
    """Generate manifests for Terraform .tf files."""
    if not TF_DIR.exists():
        print("Terraform directory not found")
        return 0

    if not dry_run:
        TF_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    created = 0

    for tf_file in sorted(TF_DIR.glob("*.tf")):
        name = tf_file.stem
        manifest_path = TF_MANIFEST_DIR / f"{name}.yaml"
        if manifest_path.exists():
            continue

        try:
            text = tf_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # Extract resource types
        resources = sorted(set(re.findall(r'resource\s+"(\w+)"', text)))

        # Sensitivity requires reading HCL resource config, not just type names.
        # Auto-classifying from type names gets composite modules wrong
        # (e.g., aws_iam_role for ECS execution != admin role).
        # Mark as TODO for human/agent review.
        sensitivity = "TODO"

        # Find module/variable references for dependency detection
        var_refs = sorted(set(re.findall(r'var\.(\w+)', text)))
        local_refs = sorted(set(re.findall(r'local\.(\w+)', text)))

        lines = [
            f"id: {name}",
            "type: terraform_module",
            'description: "TODO"',
            f"resources: [{', '.join(resources[:10])}]",
            "depends_on_modules: []  # TODO: which .tf files this references",
            "consumers: []  # TODO: which MCP servers use these resources",
            f"variables_required: [{', '.join(var_refs[:10])}]",
            "outputs_produced: []  # TODO",
            f"sensitivity: {sensitivity}",
            'change_impact: "TODO"',
        ]
        content = "\n".join(lines) + "\n"

        if not dry_run:
            manifest_path.write_text(content, encoding="utf-8")
        created += 1
        print(f"  {'[DRY]' if dry_run else '  OK '} {name} (resources:{len(resources)}, sensitivity:{sensitivity})")

    return created


def _build_parser() -> argparse.ArgumentParser:
    """Strict argparse — unknown flags fail with a usage line and non-zero exit.

    The prior hand-rolled sys.argv[1:] scan silently accepted any flag,
    including typos like `--ssions` (missing e). SKILL.md documents
    behavior on bad flags ("--nonexistent should fail"); argparse's default
    behavior on unknown args matches that contract.
    """
    p = argparse.ArgumentParser(
        prog="scaffold_extended.py",
        description="Scaffold manifests for extended domains: sessions, MCP tools, Terraform.",
        epilog="--kb was retired: the knowledge base compiles topics/*.md with "
               "tools/kb.py; per-topic manifests no longer exist.",
    )
    p.add_argument("--all", action="store_true",
                   help="Scaffold every extended domain (sessions + MCP + Terraform).")
    p.add_argument("--sessions", action="store_true",
                   help="Scaffold session transcript manifests (last N days).")
    p.add_argument("--mcp", action="store_true",
                   help="Scaffold MCP server tool manifests.")
    p.add_argument("--terraform", action="store_true",
                   help="Scaffold Terraform module manifests.")
    p.add_argument("--days", type=int, default=7, metavar="N",
                   help="Look back N days for session transcripts (default: 7).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be created without writing.")
    p.add_argument("--force", action="store_true",
                   help="Accepted for compatibility and currently a no-op: it was "
                        "scoped to the retired --kb domain. The remaining domains "
                        "keep create-only semantics to protect hand-filled fields.")
    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()
    dry_run = args.dry_run
    do_all = args.all

    if not (do_all or args.sessions or args.mcp or args.terraform):
        # No domain selected used to fall through every branch and print
        # "Created: 0 manifests" with exit 0 — false success
        # indistinguishable from "all domains manifested" (2026-06-12
        # finding). Require an explicit domain flag or --all.
        parser.print_usage(sys.stderr)
        print(
            "error: no domain selected — pass --all or at least one of "
            "--sessions / --mcp / --terraform",
            file=sys.stderr,
        )
        sys.exit(2)

    total = 0

    if args.sessions or do_all:
        print(f"\n=== Session Transcripts (last {args.days} days) ===")
        total += scaffold_sessions(dry_run, args.days)

    if args.mcp or do_all:
        print("\n=== MCP Server Tools ===")
        total += scaffold_mcp_tools(dry_run)

    if args.terraform or do_all:
        print("\n=== Terraform Modules ===")
        total += scaffold_terraform(dry_run)

    verb = "Would write" if dry_run else ("Wrote" if args.force else "Created")
    print(f"\n{verb}: {total} manifests")


if __name__ == "__main__":
    main()
