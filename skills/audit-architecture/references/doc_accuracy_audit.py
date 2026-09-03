"""Documentation accuracy audit: verify .md files match actual disk state.

Checks ARCHITECTURE.md, CLAUDE.md, and MEMORY.md against the filesystem.
Run from audit-architecture Phase 3 or standalone:
  python ~/.claude/skills/audit-architecture/references/doc_accuracy_audit.py

Outputs JSON to stdout, human-readable to stderr.
Exit code: 0 if all checks pass, 1 if drift found.
"""
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

base = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')

# Deployed tree used as the projects/ fallback when `base` is a repo
# worktree (see discover_project_dir). Module-level so tests can pin it —
# reading expanduser inline made discover_project_dir's result depend on
# whether the HOST has a deployed ~/.claude/projects, which is exactly the
# state a hermetic test cannot control (failed locally / passed on CI,
# 2026-08-22).
deployed_base = os.path.expanduser('~/.claude')


def discover_project_dir():
    """Return the path of the active Claude project under <base>/projects/.

    Claude Code stores the project as a directory whose name encodes the
    project path (e.g. 'C--Users-you'). The audit doesn't know
    that name ahead of time, so pick the most-recently-modified project
    directory that contains CLAUDE.md. Returns None if none exists.
    """
    projects_root = os.path.join(base, 'projects')
    if not os.path.isdir(projects_root):
        # CLAUDE_CONFIG_DIR often points at a repo worktree (stale-base
        # redirect), which never contains projects/ — that's runtime state,
        # not versioned content. Fall back to the deployed tree so the
        # MEMORY.md check runs against reality instead of silently no-oping.
        fallback = os.path.join(deployed_base, 'projects')
        if fallback != projects_root and os.path.isdir(fallback):
            print(f'note: {projects_root} absent; using deployed projects '
                  f'root {fallback} for MEMORY.md check', file=sys.stderr)
            projects_root = fallback
        else:
            return None
    candidates = []
    for entry in os.listdir(projects_root):
        proj_path = os.path.join(projects_root, entry)
        if not os.path.isdir(proj_path):
            continue
        if not os.path.isfile(os.path.join(proj_path, 'CLAUDE.md')):
            continue
        candidates.append((os.path.getmtime(proj_path), proj_path))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def list_tracked_files(subdir):
    """Return basenames of git-tracked files in `<base>/<subdir>`.

    Respects .gitignore by way of `git ls-files`. Files that exist on disk
    but are gitignored (e.g. auto-generated `recent-sessions.md`,
    `session-strategic-summaries.md`) are excluded — they aren't expected
    to be documented in ARCHITECTURE.md.

    Falls back to filesystem listing if git isn't available.
    """
    try:
        r = subprocess.run(
            ['git', '-C', base, 'ls-files', subdir],
            capture_output=True, text=True, timeout=5, encoding='utf-8',
        )
        if r.returncode == 0:
            return sorted({
                os.path.basename(line)
                for line in r.stdout.splitlines()
                if line.strip()
            })
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    abs_path = os.path.join(base, subdir)
    if os.path.isdir(abs_path):
        return sorted(os.listdir(abs_path))
    return []


def _safe_listdir(path):
    """os.listdir(path) but returns [] if the directory doesn't exist."""
    try:
        return os.listdir(path)
    except FileNotFoundError:
        return []


def load_actual_state():
    """Discover actual components on disk."""
    state = {}

    # Skills
    skills_dir = f'{base}/skills'
    state['skills'] = sorted([d for d in _safe_listdir(skills_dir)
                              if os.path.isdir(f'{skills_dir}/{d}')
                              and os.path.isfile(f'{skills_dir}/{d}/SKILL.md')])

    # Agents
    state['agents'] = sorted([f[:-3] for f in _safe_listdir(f'{base}/agents')
                              if f.endswith('.md') and f not in ('TEMPLATE.md', 'README.md')])

    # Topics — gitignore-aware (excludes auto-generated session-strategic-summaries.md,
    # recent-sessions.md, etc. that aren't expected to appear in ARCHITECTURE.md)
    state['topics'] = list_tracked_files('agent-memory/topics')

    # Rules
    state['rules'] = sorted([f for f in _safe_listdir(f'{base}/rules') if f.endswith('.md')])

    # Hooks
    settings_path = f'{base}/settings.json'
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: settings.json not found at {settings_path}", file=sys.stderr)
        settings = {}
    except json.JSONDecodeError as e:
        print(f"ERROR: settings.json malformed ({e})", file=sys.stderr)
        settings = {}
    hooks = set()
    hook_count = 0
    events = set()
    for event, entries in settings.get('hooks', {}).items():
        events.add(event)
        for entry in entries:
            for hook in entry.get('hooks', []):
                hook_count += 1
                if hook.get('type') == 'command':
                    command = hook.get('command', '')
                    parts = command.split() if isinstance(command, str) else []
                    args = hook.get('args', [])
                    if isinstance(args, list):
                        parts.extend(arg for arg in args if isinstance(arg, str))
                    for part in parts:
                        if part.endswith('.py'):
                            hooks.add(os.path.basename(part))
    state['hook_scripts'] = sorted(hooks)
    state['hook_count'] = hook_count
    state['hook_events'] = len(events)

    # Project directory (auto-discovered — Claude encodes the project path as
    # the directory name, so we don't know it ahead of time).
    project_dir = discover_project_dir()
    state['project_dir'] = project_dir

    # MCP servers
    mcp = set()
    # MCP config is runtime HOME state (not repo content), so it defaults to
    # ~/.claude.json even when CLAUDE_CONFIG_DIR redirects repo content to a
    # worktree. CLAUDE_JSON_PATH overrides it for worktree/test runs.
    claude_json_path = os.environ.get('CLAUDE_JSON_PATH') or os.path.expanduser('~/.claude.json')
    try:
        with open(claude_json_path, 'r', encoding='utf-8') as f:
            cj = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: ~/.claude.json not found ({claude_json_path})", file=sys.stderr)
        cj = {}
    except json.JSONDecodeError as e:
        print(f"ERROR: ~/.claude.json malformed ({e})", file=sys.stderr)
        cj = {}
    mcp.update(cj.get('mcpServers', {}).keys())
    for p, pd in cj.get('projects', {}).items():
        if isinstance(pd, dict):
            mcp.update(pd.get('mcpServers', {}).keys())
    if project_dir:
        proj_settings = os.path.join(project_dir, 'settings.json')
        if os.path.exists(proj_settings):
            with open(proj_settings, 'r', encoding='utf-8') as f:
                mcp.update(json.load(f).get('mcpServers', {}).keys())
    mcp_json = os.environ.get('MCP_JSON_PATH') or os.path.expanduser('~/.mcp.json')
    if os.path.exists(mcp_json):
        with open(mcp_json, 'r', encoding='utf-8') as f:
            mcp.update(json.load(f).get('mcpServers', {}).keys())
    for srv in settings.get('enabledMcpjsonServers', []):
        mcp.add(srv)
    state['mcp_servers'] = sorted(mcp)

    # Routing rules
    skill_rules_path = f'{base}/hooks/skill-rules.json'
    try:
        with open(skill_rules_path, 'r', encoding='utf-8') as f:
            state['routing_count'] = len(json.load(f).get('rules', []))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {skill_rules_path}: {e}", file=sys.stderr)
        state['routing_count'] = 0

    # Plugins
    state['plugins'] = settings.get('enabledPlugins', {})

    # Reverse inventory: hook files on disk not registered in settings.json AND
    # not referenced by any test, other hook, skill, or manifest script.
    # A file is a true orphan only if nothing reaches it.
    hooks_dir = f'{base}/hooks'
    hook_helpers = {'atomic_write.py', '__init__.py'}
    all_hook_files = {f for f in _safe_listdir(hooks_dir)
                      if f.endswith('.py') and not f.startswith('_')
                      and os.path.isfile(os.path.join(hooks_dir, f))}
    candidates = all_hook_files - hooks - hook_helpers

    # Build one inverted index over the reference dirs: read each file once,
    # mark every candidate (or its stem) that appears in its body. This
    # replaces the previous O(candidates × dirs × files) re-walk per
    # candidate, which scaled badly as the hook directory grew.
    reference_dirs = [
        f'{base}/hooks/test-hooks',
        f'{base}/hooks',
        f'{base}/manifests',
        f'{base}/skills',
    ]
    candidate_to_stem = {c: c[:-3] for c in candidates}
    own_file_abspaths = {
        os.path.abspath(os.path.join(hooks_dir, c)) for c in candidates
    }
    referenced = set()
    seen_files = set()
    for d in reference_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if not fn.endswith(('.py', '.md', '.json', '.yaml')):
                    continue
                fp = os.path.abspath(os.path.join(root, fn))
                if fp in seen_files or fp in own_file_abspaths:
                    continue
                seen_files.add(fp)
                try:
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                        body = f.read()
                except Exception:
                    continue
                for candidate, stem in candidate_to_stem.items():
                    if candidate in referenced:
                        continue
                    if candidate in body or stem in body:
                        referenced.add(candidate)
    state['orphan_hooks'] = sorted(candidates - referenced)

    return state


def audit_architecture_md(state):
    """Check ARCHITECTURE.md against actual state."""
    findings = []
    arch_path = f'{base}/ARCHITECTURE.md'
    try:
        with open(arch_path, 'r', encoding='utf-8') as f:
            arch = f.read()
    except FileNotFoundError:
        findings.append(('ARCHITECTURE.md', f'ARCHITECTURE.md not found at {arch_path}'))
        return findings

    # 1. Skills: check every skill on disk is mentioned somewhere in ARCHITECTURE.md
    for skill in state['skills']:
        if skill not in arch:
            findings.append(('ARCHITECTURE.md', f'Skill `{skill}` not mentioned anywhere'))

    # 2. Agents: verify count claim
    m = re.search(r'has (\d+) agents? defined', arch)
    if m and int(m.group(1)) != len(state['agents']):
        findings.append(('ARCHITECTURE.md', f'Agent count: doc says {m.group(1)}, actual {len(state["agents"])}'))

    # 3. Rules: check every rule file is in the rules table
    for rule in state['rules']:
        if rule not in arch:
            findings.append(('ARCHITECTURE.md', f'Rule `{rule}` not documented'))

    # 4. Topic files: check every topic is in the Tier 1 table
    tier1_section = arch[arch.find('Tier 1: Topic files'):arch.find('Tier 2: Pattern files')]
    for topic in state['topics']:
        if topic not in tier1_section:
            findings.append(('ARCHITECTURE.md', f'Topic `{topic}` not in Tier 1 table'))

    # 5. MCP servers: check each actual server is mentioned
    for srv in state['mcp_servers']:
        if srv not in arch:
            findings.append(('ARCHITECTURE.md', f'MCP server `{srv}` not documented'))

    # 6. Hook count accuracy
    # The doc has hook tables per event type — just verify total is reasonable
    doc_hook_mentions = len(re.findall(r'\| `[a-z-]+\.py`', arch))

    return findings


def audit_claude_md(state):
    """Check CLAUDE.md for stale references."""
    findings = []
    if not state.get('project_dir'):
        return findings
    claude_path = os.path.join(state['project_dir'], 'CLAUDE.md')
    if not os.path.isfile(claude_path):
        return findings
    with open(claude_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Check skill references in delegation table exist on disk
    delegation_section = content[content.find('Trigger keywords'):] if 'Trigger keywords' in content else ''
    for m in re.finditer(r'`([a-z][a-z0-9-]+)`', delegation_section):
        name = m.group(1)
        # Skip known non-skill references (tool names, file extensions, etc.)
        if name in state['skills'] or name in ('worker',):
            continue
        if name.endswith('.md') or name.startswith('mcp-') or ':' in name:
            continue
        # Check if it looks like a skill reference that doesn't exist
        skill_path = f'{base}/skills/{name}/SKILL.md'
        if not os.path.exists(skill_path) and len(name) > 3:
            # Might be a skill reference — check if it's in the skill table column
            if re.search(rf'\|\s*`{re.escape(name)}`\s*\|', delegation_section):
                findings.append(('CLAUDE.md', f'Delegation table references `{name}` — skill not found on disk'))

    # `superpowers:<skill>` references are valid: the installed plugin owns
    # brainstorming, TDD, debugging, subagent-driven development and completion
    # verification (this repo's same-named forks were removed 2026-09-03).
    return findings


def _is_intentionally_local_memory(path: str) -> bool:
    """Return True if `path` is intentionally local-only personal state
    (matches a .gitignore pattern AND is not tracked in git).

    Memory files under `projects/*/memory/*.md` are intentionally
    gitignored as personal local-only state — `.gitignore:86` excludes
    them by design. When MEMORY.md references one but the file doesn't
    exist in the current checkout, that's usually "this checkout hasn't
    accumulated this entry yet," not real documentation drift.

    Two checks combined to avoid false-negatives on a previously-tracked
    file that was deleted from disk:
      1. `ls-files --error-unmatch` — if the file IS in the index, this
         is a real broken link (deleted from disk but still committed).
      2. `check-ignore --no-index` — if the file matches a gitignore
         pattern (whether or not it exists), skip the broken-link check.
    """
    try:
        # If the path is tracked in the index, treat as real broken link.
        ls_files = subprocess.run(
            ['git', '-C', base, 'ls-files', '--error-unmatch', path],
            capture_output=True, timeout=3
        )
        if ls_files.returncode == 0:
            return False  # tracked — real drift
        # Untracked: skip only if it matches a gitignore pattern.
        check_ignore = subprocess.run(
            ['git', '-C', base, 'check-ignore', '--no-index', '--quiet', path],
            capture_output=True, timeout=3
        )
        return check_ignore.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def audit_memory_md(project_dir):
    """Check MEMORY.md links and orphans.

    Gitignored memory entries — local-only personal state per
    .gitignore — are excluded from the broken-link finding because
    their absence in a given checkout is by design, not drift.
    """
    findings = []
    if not project_dir:
        return findings, 0, 0
    mem_dir = os.path.join(project_dir, 'memory')
    mem_path = os.path.join(mem_dir, 'MEMORY.md')
    if not os.path.isfile(mem_path):
        # Under a CLAUDE_CONFIG_DIR redirect (stale-base worktree), the
        # project dir exists (CLAUDE.md is versioned) but memory/ does not —
        # it is gitignored runtime state. Fall back to the deployed tree's
        # memory for the same project instead of silently no-oping.
        deployed_dir = os.path.join(
            os.path.expanduser('~/.claude'), 'projects',
            os.path.basename(project_dir), 'memory')
        deployed_path = os.path.join(deployed_dir, 'MEMORY.md')
        if deployed_path != mem_path and os.path.isfile(deployed_path):
            print(f'note: {mem_path} absent (gitignored runtime state); '
                  f'using deployed {deployed_path}', file=sys.stderr)
            mem_dir, mem_path = deployed_dir, deployed_path
        else:
            return findings, 0, 0

    with open(mem_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.count('\n') + 1

    linked = set(re.findall(r'\[.*?\]\(([^)]+\.md)\)', content))
    actual = {f for f in os.listdir(mem_dir)
              if f.endswith('.md') and f != 'MEMORY.md'
              and os.path.isfile(os.path.join(mem_dir, f))}

    # Cross-directory links (~/... or absolute paths) are intentional pointers
    # to KB topics or other resources outside the memory dir; verify those
    # against the actual filesystem instead of the memory dir listing.
    local_links = {l for l in linked if not l.startswith('~') and not l.startswith('/') and ':' not in l}
    cross_links = linked - local_links

    for link in sorted(local_links - actual):
        full_path = os.path.join(mem_dir, link)
        if _is_intentionally_local_memory(full_path):
            # Intentionally local-only memory entry (auto-memory captures);
            # not real drift. Skip without warning.
            continue
        findings.append(('MEMORY.md', f'Broken link: {link} (referenced but not on disk)'))
    for link in sorted(cross_links):
        resolved = os.path.expanduser(link)
        if not os.path.isfile(resolved):
            findings.append(('MEMORY.md', f'Broken cross-dir link: {link} (resolved to {resolved}, not on disk)'))
    for orphan in sorted(actual - local_links):
        findings.append(('MEMORY.md', f'Orphaned file: {orphan} (on disk but not indexed)'))
    if lines > 180:
        findings.append(('MEMORY.md', f'Approaching 200-line cap: {lines}/200'))

    return findings, lines, len(linked)


def main():
    state = load_actual_state()

    arch_findings = audit_architecture_md(state)
    claude_findings = audit_claude_md(state)
    mem_findings, mem_lines, mem_links = audit_memory_md(state.get('project_dir'))

    # Reverse inventory: orphan hook files on disk
    orphan_findings = []
    for orphan in state.get('orphan_hooks', []):
        orphan_findings.append(('REVERSE', f'Orphan hook: {orphan} exists in hooks/ but is not registered in settings.json'))

    all_findings = arch_findings + claude_findings + mem_findings + orphan_findings

    # Human-readable output
    print('=== DOCUMENTATION ACCURACY AUDIT ===', file=sys.stderr)
    print(file=sys.stderr)
    print(f'ARCHITECTURE.md: {len(arch_findings)} issues', file=sys.stderr)
    for _, f_msg in arch_findings:
        print(f'  {f_msg}', file=sys.stderr)

    print(file=sys.stderr)
    print(f'CLAUDE.md: {len(claude_findings)} issues', file=sys.stderr)
    for _, f_msg in claude_findings:
        print(f'  {f_msg}', file=sys.stderr)

    print(file=sys.stderr)
    if mem_lines == 0 and mem_links == 0 and not mem_findings:
        # audit_memory_md returns zeros when no project dir / MEMORY.md was
        # found — that is a skipped check, not a clean one. Say so loudly.
        print('MEMORY.md: SKIP — no MEMORY.md found (check did not run)', file=sys.stderr)
    else:
        print(f'MEMORY.md: {len(mem_findings)} issues ({mem_lines}/200 lines, {mem_links} links)', file=sys.stderr)
    for _, f_msg in mem_findings:
        print(f'  {f_msg}', file=sys.stderr)

    if orphan_findings:
        print(file=sys.stderr)
        print(f'Reverse inventory: {len(orphan_findings)} orphan hooks', file=sys.stderr)
        for _, f_msg in orphan_findings:
            print(f'  {f_msg}', file=sys.stderr)

    print(file=sys.stderr)
    if all_findings:
        print(f'Total: {len(all_findings)} documentation drift issues', file=sys.stderr)
    else:
        print('All documentation matches disk state.', file=sys.stderr)

    # JSON output
    output = {
        'architecture_md': {'issues': len(arch_findings), 'findings': [{'msg': m} for _, m in arch_findings]},
        'claude_md': {'issues': len(claude_findings), 'findings': [{'msg': m} for _, m in claude_findings]},
        'memory_md': {'issues': len(mem_findings), 'lines': mem_lines, 'links': mem_links,
                      'findings': [{'msg': m} for _, m in mem_findings]},
        'orphan_hooks': {'issues': len(orphan_findings), 'findings': [{'msg': m} for _, m in orphan_findings]},
        'total_issues': len(all_findings),
    }
    json.dump(output, sys.stdout, indent=2)

    return 0 if not all_findings else 1


if __name__ == '__main__':
    sys.exit(main())
