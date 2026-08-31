# Retro Opportunities Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close four improvement opportunities identified in the 7d retrospective (Mar 21-28): brainstorm routing collision, ToolSearch upstream issue, subagent friction audit, and file_not_found sub-classification.

**Architecture:** Four independent tasks with no dependencies between them. Each produces a discrete artifact (config change, GitHub issue, analysis report, or code change). Can be parallelized.

**Tech Stack:** Python (retro-extract.py, audit scripts), `gh` CLI (issue filing), settings.json config, skill YAML frontmatter.

---

### Task 1: Fix brainstorm naming collision

**Context:** `brainstorm` (5 invocations) and `superpowers:brainstorm` (4 invocations) split routing across 9 sessions. Both exist in the skill system prompt. The standalone `brainstorm` is the superpowers marketplace copy — there is no separate `~/.claude/skills/brainstorm/` directory. The collision is in the model's system prompt where both names appear.

**Files:**
- Modify: `~/.claude/plugins/cache/superpowers-marketplace/superpowers/4.3.1/skills/brainstorm/SKILL.md` (if exists — this is the marketplace copy)

**Step 1: Verify the brainstorm source**

Run:
```bash
find ~/.claude/plugins -name "SKILL.md" -path "*brainstorm*" 2>/dev/null
grep -r "brainstorm" ~/.claude/settings.json ~/.claude/settings.local.json 2>/dev/null | head -5
```

Expected: The standalone `brainstorm` comes from the superpowers marketplace plugin. There's no user-created skill.

**Step 2: Check if superpowers:brainstorm is the canonical version**

Run:
```bash
head -20 ~/.claude/plugins/cache/superpowers-marketplace/superpowers/*/skills/brainstorm/SKILL.md
```

Expected: This IS `superpowers:brainstorm` — the marketplace exposes it both as `brainstorm` and `superpowers:brainstorm`. The collision is in the plugin's own naming.

**Step 3: Determine fix approach**

Two options:
- **Option A**: If the marketplace plugin exposes both names, there's no local fix — file an issue on the superpowers marketplace repo.
- **Option B**: If `brainstorm` is a separate entry in settings.json or enabledPlugins, disable it so only `superpowers:brainstorm` remains.

Check:
```bash
python -c "
import json
with open('$HOME/.claude/settings.json', encoding='utf-8') as f:
    d = json.load(f)
# Check if brainstorm appears in any skill routing
print(json.dumps({k:v for k,v in d.items() if 'brainstorm' in str(v).lower()}, indent=2))
"
```

**Step 4: Apply the fix**

Based on Step 3 findings, either:
- Remove the duplicate entry from config
- Or document as "upstream marketplace issue, no local fix"

**Step 5: Verify**

Run: `/brainstorm test` and `superpowers:brainstorm test` — both should resolve to the same skill.

**Step 6: Commit (if config changed)**

```bash
git add <changed-files>
git commit -m "fix: resolve brainstorm skill naming collision"
```

---

### Task 2: File ToolSearch upstream issue

**Context:** ToolSearch has a 91.1% empty rate (399/438 calls) for 7 consecutive retros. The root cause is deferred tool loading — with 100+ MCP tools, the search index doesn't match natural language queries. `auto:2` (PR #367) improved it from 95.9% to 91.1% but the fundamental problem is architectural.

**Files:**
- Create: GitHub issue on `anthropics/claude-code`

**Step 1: Gather evidence**

Collect the key metrics from the retrospective data:
```bash
python -c "
import json
# Read the latest retro extract
with open('$HOME/.claude/retrospectives/extract-2026-03-28.json', encoding='utf-8') as f:
    data = json.load(f)
agg = data['aggregates']
friction = agg['friction']
print(f'ToolSearch empty: {friction[\"empty_results_by_tool\"].get(\"ToolSearch\", 0)}')
print(f'Total ToolSearch calls: {agg[\"tool_usage_ranking\"].get(\"ToolSearch\", 0)}')
print(f'Empty rate: {friction[\"empty_results_by_tool\"].get(\"ToolSearch\", 0) / max(agg[\"tool_usage_ranking\"].get(\"ToolSearch\", 1), 1) * 100:.1f}%')
print(f'Total MCP tools: count from /mcp output')
"
```

**Step 2: Count total MCP tools available**

Run:
```bash
# Count deferred tools from a recent session
grep -c "available-deferred-tools" ~/.claude/projects/<your-claude-project>/*.jsonl 2>/dev/null | tail -1
```

Or manually count from the `<available-deferred-tools>` block in any session.

**Step 3: Draft the issue**

```bash
MSYS_NO_PATHCONV=1 gh issue create --repo anthropics/claude-code \
  --title "Feature request: eager schema loading for MCP tools (ToolSearch 91% empty rate)" \
  --body "$(cat <<'BODY'
## Problem

ToolSearch returns empty results 91.1% of the time (399/438 calls over 93 sessions, 7 days). This has persisted for 7+ consecutive weekly retrospectives with minimal improvement.

## Environment

- Claude Code v2.1.86, Windows 11, Opus 4.6 [1m]
- 100+ MCP tools across 15+ servers (mix of local stdio and remote HTTP/SSE)
- `auto:2` configured (improved from 95.9% to 91.1%, but plateau reached)

## Root cause

Deferred tool loading means the model must guess tool names before schemas are loaded. With 100+ tools, the keyword-based search rarely matches. The model calls ToolSearch("memory search"), but the deferred tool name is `mcp__memory-search__memory_search` — a format the model can't predict.

## Impact

- 399 wasted tool calls per week (largest single friction source)
- Each empty ToolSearch adds ~500 tokens of overhead (query + empty response)
- Compounds in subagent sessions where agents need MCP tools but don't know names

## Proposed solution

Add a `preload_tools` config in settings.json (or `.claude.json`) that eagerly fetches schemas at session start:

```json
{
  "preload_tools": [
    "mcp__memory-search__*",
    "mcp__tavily__*",
    "mcp__remote-tailscale__*"
  ]
}
```

Alternatively, for power users with many MCP servers, provide a flag to eagerly load ALL tool schemas at session start, trading startup latency for eliminating ToolSearch entirely.

## Workarounds tried

- `auto:2` in settings: marginal improvement (95.9% → 91.1%)
- Rules instructing the model to batch-fetch tools: inconsistently followed
- SessionStart hook context injection: hooks can't invoke ToolSearch
BODY
)"
```

**Step 4: Record the issue number**

Save the issue URL for tracking.

**Step 5: No commit needed** (external action only)

---

### Task 3: Audit subagent-driven-development friction

**Context:** 7 sessions using superpowers:subagent-driven-development averaged 28.0 friction — highest of any frequently-used skill. Preliminary data shows empty results averaging 13.3/session, suggesting ToolSearch empties from agent dispatch are the primary driver, not task complexity.

**Files:**
- Read: Session transcripts (JSONL) for the top 3 friction sessions
- Create: `~/.claude/retrospectives/sdd-friction-audit.md` (analysis report)

**Step 1: Extract friction breakdown for the 7 SDD sessions**

```bash
python retro-extract-sdd-audit.py
```

Script content (write to `~/retro-extract-sdd-audit.py`):
```python
#!/usr/bin/env python3
"""Audit subagent-driven-development friction sources."""
import sys, json
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta
import importlib.util

sys.stdout.reconfigure(encoding='utf-8')

spec = importlib.util.spec_from_file_location(
    "retro_extract", str(Path.home() / '.claude' / 'scripts' / 'retro-extract.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PROJECTS_DIR = Path.home() / '.claude' / 'projects' / '<your-claude-project>'
cutoff = datetime.now() - timedelta(hours=168)

sessions = []
for fpath in sorted(PROJECTS_DIR.glob('*.jsonl'), key=lambda p: p.stat().st_mtime):
    if datetime.fromtimestamp(fpath.stat().st_mtime) < cutoff:
        continue
    s = mod.extract_session(str(fpath), deep=True)
    if s and 'superpowers:subagent-driven-development' in s.get('skills_invoked', []):
        sessions.append(s)

print(f"SDD sessions: {len(sessions)}")
print()

for s in sorted(sessions, key=lambda x: x['friction']['score'], reverse=True):
    sid = s['session_id'][:12]
    f = s['friction']
    e = s['errors']
    print(f"Session {sid} (friction={f['score']}, empty={f['empty_results']}, errors={e['count']})")
    print(f"  Duration: {s['duration_human']}")
    print(f"  Empty by tool: {dict(sorted(f['empty_results_by_tool'].items(), key=lambda x: -x[1]))}")

    # Error subcategories
    for cat, data in e['classified'].items():
        if cat == 'hook_block':
            continue
        for sub, count in data['subcategories'].items():
            print(f"  Error: {cat}/{sub} x{count}")

    # Agent calls
    agent_calls = s['tool_calls'].get('Agent', 0)
    toolsearch_calls = s['tool_calls'].get('ToolSearch', 0)
    print(f"  Agent calls: {agent_calls}, ToolSearch calls: {toolsearch_calls}")
    print()
```

**Step 2: Run the audit**

```bash
python ~/retro-extract-sdd-audit.py
```

Expected output: Per-session friction breakdown showing whether ToolSearch empties dominate or whether errors/retries dominate.

**Step 3: Classify the friction source**

For each session, determine:
- **ToolSearch overhead**: empty_results / friction_score > 50% → dispatch overhead is the problem
- **Error-driven**: errors / friction_score > 50% → task failures, not dispatch
- **Mixed**: neither dominates

**Step 4: Read the top-friction session transcript (0b9a4611904f)**

```bash
# Find the transcript file
ls ~/.claude/projects/<your-claude-project>/*0b9a4611904f* 2>/dev/null || \
ls ~/.claude/session-transcripts/*0b9a4611904f* 2>/dev/null
```

Read the first 200 lines to understand the pattern:
```bash
head -200 <transcript_file> | python -c "
import sys, json
for line in sys.stdin:
    try:
        r = json.loads(line)
        if r.get('type') == 'assistant':
            for b in r.get('message',{}).get('content',[]):
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    name = b.get('name','')
                    if name in ('ToolSearch', 'Agent'):
                        inp = b.get('input',{})
                        print(f'{name}: {json.dumps(inp)[:120]}')
    except: pass
"
```

**Step 5: Write the audit report**

Write findings to `~/.claude/retrospectives/sdd-friction-audit.md`:

```markdown
# Subagent-Driven Development Friction Audit (2026-03-27)

## Summary
- 7 sessions, 28.0 avg friction
- Primary friction source: [ToolSearch empties / errors / mixed]
- [X]% of friction is ToolSearch empty results from agent dispatch

## Per-Session Breakdown
[table from Step 1]

## Root Cause
[findings from Step 3-4]

## Recommendations
- If ToolSearch: blocked on upstream fix (Task 2). No local action.
- If errors: specific patterns to address in the skill
- If mixed: both
```

**Step 6: Clean up temp script**

```bash
rm ~/retro-extract-sdd-audit.py
```

---

### Task 4: Sub-classify file_not_found errors

**Context:** 94 file_not_found errors (76 bash + 18 tool) are the highest specific subcategory. Before building an auto-MSYS guard, we need to know what fraction are actually MSYS path mangling vs genuinely missing files, deleted paths, or typos.

**Files:**
- Create: `~/audit-file-not-found.py` (temp audit script)
- Modify: `~/.claude/scripts/retro-extract.py` (if new sub-classifiers warranted)
- Create: `~/.claude/retrospectives/file-not-found-audit.md` (analysis report)

**Step 1: Write the audit script**

```python
#!/usr/bin/env python3
"""Sub-classify file_not_found bash errors from last 7 days."""
import sys, json, re
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta
import importlib.util

sys.stdout.reconfigure(encoding='utf-8')

spec = importlib.util.spec_from_file_location(
    "retro_extract", str(Path.home() / '.claude' / 'scripts' / 'retro-extract.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PROJECTS_DIR = Path.home() / '.claude' / 'projects' / '<your-claude-project>'
cutoff = datetime.now() - timedelta(hours=168)

fnf_errors = []
for fpath in PROJECTS_DIR.glob('*.jsonl'):
    if datetime.fromtimestamp(fpath.stat().st_mtime) < cutoff:
        continue
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                except Exception:
                    continue
                if record.get('type') != 'user':
                    continue
                content = record.get('message', {}).get('content', [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get('type') == 'tool_result' and block.get('is_error'):
                        ec = block.get('content', '')
                        if isinstance(ec, list):
                            em = '; '.join(b.get('text','') for b in ec
                                          if isinstance(b,dict) and b.get('type')=='text')
                        elif isinstance(ec, str):
                            em = ec
                        else:
                            em = str(ec)
                        if 'Exit code' in em and mod.classify_bash_error(em) == 'file_not_found':
                            fnf_errors.append(em[:500])
    except Exception:
        continue

print(f'Total file_not_found bash errors: {len(fnf_errors)}')

# Sub-classify
subcats = Counter()
for err in fnf_errors:
    if '/c/Users' in err or 'C:/Program Files/Git' in err:
        subcats['msys_path_mangling'] += 1
    elif '.claude/hooks/' in err or '.claude/scripts/' in err:
        subcats['deleted_hook_or_script'] += 1
    elif 'worktree' in err.lower() or '.claude/worktrees/' in err:
        subcats['worktree_cleanup'] += 1
    elif 'pip' in err or 'site-packages' in err:
        subcats['python_package_path'] += 1
    elif '.git/' in err:
        subcats['git_internal'] += 1
    elif re.search(r'(\.ts|\.js|\.py|\.md)\b', err):
        subcats['source_file_missing'] += 1
    else:
        subcats['other_fnf'] += 1

print()
print('Sub-classification:')
for cat, count in subcats.most_common():
    pct = count / len(fnf_errors) * 100 if fnf_errors else 0
    print(f'  {count:3d} ({pct:4.1f}%)  {cat}')

# Print samples per category
for cat_name in ['msys_path_mangling', 'deleted_hook_or_script', 'other_fnf']:
    samples = []
    for err in fnf_errors:
        match = False
        if cat_name == 'msys_path_mangling' and ('/c/Users' in err or 'C:/Program Files/Git' in err):
            match = True
        elif cat_name == 'deleted_hook_or_script' and ('.claude/hooks/' in err or '.claude/scripts/' in err):
            match = True
        elif cat_name == 'other_fnf':
            if not any(p in err for p in ['/c/Users', 'C:/Program Files/Git',
                       '.claude/hooks/', '.claude/scripts/', 'worktree',
                       'pip', 'site-packages', '.git/']):
                if not re.search(r'(\.ts|\.js|\.py|\.md)\b', err):
                    match = True
        if match:
            samples.append(err[:250])
        if len(samples) >= 3:
            break
    if samples:
        print(f'\n--- {cat_name} samples ---')
        for i, s in enumerate(samples):
            print(f'  {i+1}. {s.strip()[:200]}')
```

**Step 2: Run the audit**

```bash
python ~/audit-file-not-found.py
```

**Step 3: Determine if MSYS guard expansion is warranted**

Decision matrix:
- If `msys_path_mangling` > 40%: Build the auto-MSYS guard expansion in bash-security-guard.py
- If `deleted_hook_or_script` > 30%: The problem is stale references, not path mangling. Fix: grep for deleted file references in hooks/settings during CI validation.
- If `source_file_missing` > 30%: The problem is architecture cleanup — files moved/renamed between sessions. Fix: better read-before-edit discipline (already a rule).
- If mixed: each category < 30%, no single fix warranted. Document and move on.

**Step 4: Write the audit report**

Write to `~/.claude/retrospectives/file-not-found-audit.md`:

```markdown
# file_not_found Sub-Classification Audit (2026-03-27)

## Summary
- N total file_not_found bash errors (7d window)
- Top sub-category: [name] at N%

## Sub-Classification
| Category | Count | % | Actionable? |
|----------|-------|---|-------------|
| msys_path_mangling | N | N% | Yes: auto-MSYS guard |
| deleted_hook_or_script | N | N% | Yes: CI validation |
| ... | | | |

## Recommendation
[Based on Step 3 decision matrix]
```

**Step 5: If MSYS guard warranted (>40%), implement it**

Add to `bash-security-guard.py` after the existing `check_msys_pathconv`:

```python
def auto_prepend_msys_no_pathconv(command):
    """Auto-prepend MSYS_NO_PATHCONV=1 for commands with Windows-style paths."""
    if 'MSYS_NO_PATHCONV' in command:
        return None  # Already has it
    # Detect Windows paths being passed to commands
    if re.search(r'(?:^|\s)/[cd]/Users/', command):
        return (
            "[msys-auto-fix] INFO: Auto-prepending MSYS_NO_PATHCONV=1 "
            "for command with Windows-style path."
        )
    return None
```

Note: This is a WARNING, not a block. The guard can't modify the command — it can only warn. The actual fix would need to be a PreToolUse hook that modifies the command input, which requires a different hook architecture.

**Step 6: Clean up and commit**

```bash
rm ~/audit-file-not-found.py
git add scripts/retro-extract.py retrospectives/file-not-found-audit.md
git commit -m "chore: file_not_found sub-classification audit"
```

---

## Execution Notes

- Tasks 1-4 are fully independent — can be parallelized
- Tasks 2 and 3 are read-only analysis + external actions (no repo code changes)
- Task 1 may result in "no local fix" (upstream marketplace issue)
- Task 4 may result in "no single fix warranted" (mixed sub-categories)
- Total estimated effort: ~2 hours across all 4 tasks
