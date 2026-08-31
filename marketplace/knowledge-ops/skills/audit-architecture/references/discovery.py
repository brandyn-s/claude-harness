"""Architecture discovery for /audit-architecture Phases 1, 2, and 6.

Emits ONE JSON document covering the deterministic parts of the audit:
MCP server inventory, per-server coverage matrix, hook matchers, agent
frontmatter, routing stats, self-improvement loop checks, and scaling
numbers. Replaces ~200 lines of per-run ad-hoc Python (measured
2026-08-22, where hand-rolled matchers also produced two false coverage
gaps).

Path semantics match doc_accuracy_audit.py:
- REPO content (agents/, skills/, hooks/skill-rules.json, settings.json,
  agent-memory/topics/) resolves under CLAUDE_CONFIG_DIR when set (the
  stale-base worktree redirect), else ~/.claude.
- RUNTIME state (~/.claude.json, ~/.mcp.json, projects/<dir>/ memory and
  CLAUDE.md, agent-memory accumulation) always resolves under HOME —
  it is not versioned, so a worktree never contains it.

Usage:
  python3 discovery.py > discovery.json
  python3 discovery.py --route "why is the tenable scan failing"
      # simulate the ACTUAL router dispatch (skip patterns first, then
      # all matches sorted by (priority, match.start())) — NOT first-match.

Exit code: 0 on success (findings are data, not exit status); 2 on a
config parse failure that makes discovery incomplete.
"""
import argparse
import glob
import json
import os
import re
import sys

BASE = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')
HOME = os.path.expanduser('~')

# Server-name -> topic/routing alias. Explicit beats fuzzy: a loose prefix
# match ("pa" -> palantir-foundry.md) manufactured a false paloalto-covered
# row on 2026-08-22. Extend this map rather than loosening the matcher.
ALIASES = {
    'linear-server': 'linear',
    'slack-user': 'slack',
    'claude_platform': 'claude-platform',
    'sec-automations-query': 'sec-automation',
    'box-admin': 'box',
    'confluence-gov': 'confluence-gov',
    'palantir-mcp': 'palantir-foundry',
    'claude-compliance': 'claude-monitoring',
    'memory-search': 'memory-search-dev',
    'compliance-access-framework': 'compliance-access',
    'workspace-provisioner': 'provision',
}

PRIORITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}


def _load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, 'absent'
    except json.JSONDecodeError as e:
        return None, f'parse error: {e}'


def load_servers():
    """Runtime MCP inventory: ~/.claude.json (+ projects) and ~/.mcp.json."""
    servers, errors = {}, []
    cj, err = _load_json(os.path.join(HOME, '.claude.json'))
    if err:
        errors.append(f'~/.claude.json: {err}')
    cj = cj or {}
    for name, cfg in (cj.get('mcpServers') or {}).items():
        servers[name] = {
            'scope': 'user',
            'type': cfg.get('type', 'stdio'),
            'url': cfg.get('url', ''),
            'command': cfg.get('command', ''),
        }
    for proj, pcfg in (cj.get('projects') or {}).items():
        if not isinstance(pcfg, dict):
            continue
        for name, cfg in (pcfg.get('mcpServers') or {}).items():
            if name in servers:
                servers[name].setdefault('also_project', []).append(proj)
            else:
                servers[name] = {
                    'scope': f'project:{proj}',
                    'type': cfg.get('type', 'stdio'),
                    'url': cfg.get('url', ''),
                    'command': cfg.get('command', ''),
                }
    mj, _mj_err = _load_json(os.path.join(HOME, '.mcp.json'))
    if mj:
        for name, cfg in (mj.get('mcpServers') or {}).items():
            servers.setdefault(name, {
                'scope': 'mcp.json',
                'type': cfg.get('type', 'stdio'),
                'url': cfg.get('url', ''),
                'command': cfg.get('command', ''),
            })
    return servers, errors


def name_variants(server):
    """Candidate names for topic/routing lookups. Explicit + mechanical only."""
    out = [server]
    if server in ALIASES:
        out.append(ALIASES[server])
    out.append(server.replace('_', '-'))
    out.append(server.replace('-mcp', ''))
    first = server.split('-')[0]
    if len(first) >= 5:  # short prefixes over-match (the "pa" incident)
        out.append(first)
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def discover_project_dir():
    root = os.path.join(HOME, '.claude', 'projects')
    if not os.path.isdir(root):
        return None
    cands = []
    for entry in os.listdir(root):
        p = os.path.join(root, entry)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, 'CLAUDE.md')):
            cands.append((os.path.getmtime(p), p))
    return sorted(cands, reverse=True)[0][1] if cands else None


def build(route_prompts):
    result = {'base': BASE, 'errors': []}

    servers, errs = load_servers()
    result['errors'].extend(errs)
    result['mcp_servers'] = servers

    # --- Routing rules (repo) ---
    sr, err = _load_json(os.path.join(BASE, 'hooks', 'skill-rules.json'))
    if err:
        result['errors'].append(f'skill-rules.json: {err}')
    sr = sr or {'rules': [], 'skip_patterns': []}
    rules = sr.get('rules', [])
    invalid = []
    for i, r in enumerate(rules):
        try:
            re.compile(r.get('pattern') or '')
        except re.error as e:
            invalid.append({'index': i, 'error': str(e)})
    rules_blob = json.dumps(sr).lower()

    # --- Hooks (repo settings.json; deployed may differ — see banner) ---
    st, err = _load_json(os.path.join(BASE, 'settings.json'))
    if err:
        result['errors'].append(f'settings.json: {err}')
    st = st or {}
    hooks = st.get('hooks', {})
    result['hooks'] = {
        'settings_path': os.path.join(BASE, 'settings.json'),
        'events': {ev: sum(len(e.get('hooks', [])) for e in entries)
                   for ev, entries in hooks.items()},
        'pre_tool_use_matchers': [e.get('matcher', '') for e in hooks.get('PreToolUse', [])],
        'post_tool_use_failure_matchers': [e.get('matcher', '') for e in hooks.get('PostToolUseFailure', [])],
        'subagent_stop_matchers': [e.get('matcher', '') for e in hooks.get('SubagentStop', [])],
        'enabled_plugins': list(st.get('enabledPlugins') or {}),
    }
    pre_matchers = result['hooks']['pre_tool_use_matchers']

    # --- Agents (repo) ---
    agents = {}
    for f in sorted(glob.glob(os.path.join(BASE, 'agents', '*.md'))):
        b = os.path.basename(f)
        if b in ('TEMPLATE.md', 'README.md'):
            continue
        txt = open(f, encoding='utf-8').read()
        fm = txt.split('---')[1] if txt.startswith('---') else ''
        mem = re.search(r'^memory:\s*(\S+)', fm, re.MULTILINE)
        agents[b[:-3]] = {
            'has_tools': bool(re.search(r'^tools:', fm, re.MULTILINE)),
            'has_disallowed_tools': bool(re.search(r'^disallowedTools:', fm, re.MULTILINE)),
            'memory': mem.group(1) if mem else None,
            'has_hooks': bool(re.search(r'^hooks:', fm, re.MULTILINE)),
        }
    result['agents'] = agents

    # --- Skills (repo) ---
    skills = sorted(os.path.basename(os.path.dirname(f))
                    for f in glob.glob(os.path.join(BASE, 'skills', '*', 'SKILL.md')))
    result['skills'] = {'count': len(skills), 'names': skills}

    # --- Topics (repo) + stubs ---
    topics, stubs = {}, []
    for t in glob.glob(os.path.join(BASE, 'agent-memory', 'topics', '*.md')):
        name = os.path.basename(t)[:-3]
        head = open(t, encoding='utf-8', errors='replace').read(400)
        topics[name] = len(head)
        if len(head) < 200 or 'stub' in head[:100].lower():
            stubs.append(name)
    result['topics'] = {'count': len(topics), 'stubs': sorted(stubs)}

    # --- Runtime accumulation + project docs ---
    project_dir = discover_project_dir()
    result['project_dir'] = project_dir
    claude_md = ''
    mem_lines = 0
    if project_dir:
        cm_path = os.path.join(project_dir, 'CLAUDE.md')
        if os.path.isfile(cm_path):
            claude_md = open(cm_path, encoding='utf-8').read().lower()
        mem_path = os.path.join(project_dir, 'memory', 'MEMORY.md')
        if os.path.isfile(mem_path):
            mem_lines = open(mem_path, encoding='utf-8').read().count('\n') + 1

    agent_mem = {}
    am_root = os.path.join(HOME, '.claude', 'agent-memory')
    if os.path.isdir(am_root):
        for d in sorted(os.listdir(am_root)):
            p = os.path.join(am_root, d)
            if os.path.isdir(p):
                agent_mem[d] = len([x for x in os.listdir(p)
                                    if x.endswith(('.md', '.yaml', '.json'))])
    result['agent_memory_entry_counts'] = agent_mem

    # --- Coverage matrix ---
    def pre_covered(server):
        probe = f'mcp__{server}__sometool'
        for m in pre_matchers:
            if not m:
                continue
            try:
                if re.search(m, probe):
                    return True
            except re.error:
                if f'mcp__{server}' in m:
                    return True
        return False

    matrix = {}
    for s in sorted(servers):
        variants = name_variants(s)
        topic = next((v for v in variants if v in topics), None)
        routing = any(v.lower() in rules_blob for v in variants)
        matrix[s] = {
            'topic_file': topic,
            'routing_keyword_hit': routing,
            'pre_tool_use': pre_covered(s),
            'claude_md_mention': any(v.lower() in claude_md for v in variants),
        }
    result['coverage'] = matrix

    # --- Phase 6 loop checks ---
    ptuf = result['hooks']['post_tool_use_failure_matchers']
    substop = result['hooks']['subagent_stop_matchers']
    result['loops'] = {
        'error_learning_universal': any('mcp' in m and 'Bash' in m for m in ptuf),
        'subagent_stop_wildcard': '.*' in substop,
        'agents_with_memory': sorted(a for a, v in agents.items() if v['memory']),
        'gather_skills_present_and_routed': {
            sk: {'exists': sk in skills, 'routed': sk in rules_blob}
            for sk in ('gather-intel', 'gather-internal-intel')
        },
    }

    # --- Scaling ---
    result['scaling'] = {
        'memory_md_lines': mem_lines,
        'routing_rules': len(rules),
        'skip_patterns': len(sr.get('skip_patterns', [])),
        'invalid_rule_regexes': invalid,
        'topic_files': len(topics),
        'topic_stubs': len(stubs),
    }

    # --- Optional router simulation (the ACTUAL dispatch semantics) ---
    if route_prompts:
        result['routes'] = {p: simulate_route(sr, p) for p in route_prompts}
    return result


def simulate_route(sr, prompt):
    """Mirror hooks/skill-routing-hint.py: skip patterns hard-exit, then all
    matches sorted by (priority, match.start()). NOT first-match-wins."""
    for s in sr.get('skip_patterns', []):
        try:
            if re.search(s, prompt, re.IGNORECASE):
                return {'result': 'SKIPPED', 'skip_pattern': s}
        except re.error:
            continue
    matches = []
    for i, r in enumerate(sr.get('rules', [])):
        pat = r.get('pattern') or ''
        try:
            m = re.search(pat, prompt, re.IGNORECASE)
        except re.error:
            continue
        if m:
            matches.append((PRIORITY_ORDER.get(r.get('priority', 'medium'), 2),
                            m.start(), i, r, m.group()[:40]))
    if not matches:
        return {'result': 'NO-MATCH'}
    matches.sort(key=lambda x: (x[0], x[1]))
    _, _, idx, rule, frag = matches[0]
    return {
        'result': rule.get('skill') or rule.get('agent'),
        'rule_index': idx,
        'priority': rule.get('priority', 'medium'),
        'matched': frag,
        'total_matches': len(matches),
    }


def main():
    ap = argparse.ArgumentParser(description='Architecture discovery for /audit-architecture')
    ap.add_argument('--route', action='append', default=[],
                    help='simulate router dispatch for a prompt (repeatable)')
    args = ap.parse_args()
    result = build(args.route)
    json.dump(result, sys.stdout, indent=1)
    sys.stdout.write('\n')
    return 2 if result['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
