# v2.1.80 Leverage & Retest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Retest 4 upstream subagent bugs on v2.1.80, add `effort` frontmatter to 8 skills, create a StopFailure hook for rate limit recovery, add rate_limits to statusline, and create an InstructionsLoaded validation hook.

**Architecture:** Two workstreams - (A) retests use the established probe-based methodology from 2026-03-14, and (B) new features are independent hooks/config changes. All hooks follow the existing pattern: Python 3.14 + pythonw.exe, JSON stdin via `$TOOL_INPUT`/`$HOOK_INPUT`, exit codes for decisions.

**Tech Stack:** Python 3.14, settings.json hooks, YAML frontmatter, git bash

---

## Workstream A: Upstream Bug Retests

### Task 1: Create probe hook script

**Files:**
- Create: `~/.claude/hooks/probe-hook-test.py`

**Step 1: Write the probe hook**

This script logs every PreToolUse:Bash call to a file so we can verify hooks fire for subagents.

```python
#!/usr/bin/env python3
"""Probe hook: logs PreToolUse calls to verify subagent hook enforcement."""
import json, sys, os, datetime

log_path = os.path.expanduser('~/probe-hook-test.log')
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

entry = {
    'timestamp': datetime.datetime.now().isoformat(),
    'tool_name': data.get('tool_name', 'unknown'),
    'agent_type': data.get('agent_type', 'unknown'),
    'agent_id': data.get('agent_id', 'unknown'),
    'session_id': os.environ.get('SESSION_ID', 'unknown'),
}

with open(log_path, 'a', encoding='utf-8') as f:
    f.write(json.dumps(entry) + '\n')

# Always allow - we're just observing
sys.exit(0)
```

**Step 2: Register the probe hook in settings.json**

Use Python atomic read-modify-write to add a PreToolUse:Bash entry. The hook must be FIRST in the PreToolUse list (before bash-security-guard) so it fires before any blocking.

```python
import json, os

path = os.path.expanduser('~/.claude/settings.json')
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)

probe_entry = {
    "matcher": "Bash",
    "hooks": [{
        "type": "command",
        "command": "C:/Users/you/AppData/Local/Programs/Python/Python314/pythonw.exe $HOME/.claude/hooks/probe-hook-test.py",
        "timeout": 3
    }]
}

# Insert at position 0 (before all other PreToolUse hooks)
cfg['hooks']['PreToolUse'].insert(0, probe_entry)

with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
```

**Step 3: Clear any old probe log**

Run: `rm -f ~/probe-hook-test.log`

**Step 4: Commit checkpoint**

No git commit yet - this is temporary test infrastructure.

---

### Task 2: Run probe tests for all 4 bugs

**Step 1: Baseline - main session Bash call**

Run: `echo "probe-baseline-test"` in main session via Bash tool.
Then check: `cat ~/probe-hook-test.log`
Expected: One entry with `agent_type: "unknown"` or `"main"` (main session).

**Step 2: Test #34240 + #32402 - background subagent**

Dispatch a background Agent tool call:
```
Agent tool:
  subagent_type: "general-purpose"
  run_in_background: true
  prompt: "Run this exact Bash command: echo 'probe-background-test'. Then use the Write tool to create a file at ~/probe-background-write.txt with content 'background-write-test'. Report what you did."
```

Wait for completion, then check:
- `cat ~/probe-hook-test.log` - should have an entry with `agent_type` containing "general" (confirms #34240: PreToolUse fires for background agents)
- `cat ~/probe-background-write.txt` - should contain "background-write-test" (confirms #32402: background agents can write)

**Step 3: Test #21460 - foreground subagent**

Dispatch a foreground Agent tool call:
```
Agent tool:
  subagent_type: "general-purpose"
  prompt: "Run this exact Bash command: echo 'probe-foreground-test'. Report what you did."
```

Then check: `cat ~/probe-hook-test.log`
Expected: Entry with `agent_type` containing "general" from the foreground agent.

**Step 4: Test #27755 - SubagentStart reliability**

Run tests 2 and 3 above. The SubagentStart hook (`subagent-start-context.py`) fires on every agent dispatch. If agents started successfully and received their tasks, SubagentStart fired. Run 3 foreground agents in sequence (same simple echo task) and verify all 3 complete.

**Step 5: Record results**

Count entries in `~/probe-hook-test.log`. Expected: at minimum 4 entries (1 baseline + 1 background + 1 foreground + 1 from step 4).

If any test fails:
- Missing background entry → #34240 regressed (document, add workaround)
- Background write file missing → #32402 regressed (revert worker.md guidance)
- Missing foreground entry → #21460 regressed (platform-dependent per #34692)
- Agent dispatch fails → #27755 regressed (investigate)

---

### Task 3: Clean up probe infrastructure and update docs

**Step 1: Deregister probe hook from settings.json**

```python
import json, os

path = os.path.expanduser('~/.claude/settings.json')
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)

# Remove the probe hook (first PreToolUse entry with probe-hook-test.py)
cfg['hooks']['PreToolUse'] = [
    h for h in cfg['hooks']['PreToolUse']
    if 'probe-hook-test' not in json.dumps(h)
]

with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
```

**Step 2: Delete probe artifacts**

Run:
```bash
rm -f ~/probe-hook-test.log
rm -f ~/probe-background-write.txt
rm -f ~/.claude/hooks/probe-hook-test.py
```

**Step 3: Update subagent-verification.md with results**

Replace the "retested v2.1.76" dates with "retested v2.1.80" and update any results that changed. Use Python atomic write since this is a `~/.claude/` file.

**Step 4: Update MEMORY.md retest line**

Change "Due for retest on v2.1.80" to "Retested v2.1.80 (2026-03-20) - all passing" (or note regressions).

**Step 5: Update knowledge-base topic**

Add a new entry to `~/Documents/knowledge-base/topics/claude-agent-architecture.md` documenting the v2.1.80 retest results and any behavioral changes observed.

**Step 6: Commit**

```bash
cd ~/.claude
git add rules/subagent-verification.md projects/<your-claude-project>/memory/MEMORY.md
git commit -m "$(cat <<'EOF'
chore: retest upstream subagent bugs on v2.1.80

Retested #34240, #32402, #21460, #27755 using probe methodology.
Results: [fill in based on actual results]
EOF
)"
```

---

## Workstream B: Leverage New Features

### Task 4: Add `effort` frontmatter to 8 skills

**Files:**
- Modify: `~/.claude/skills/superplan/SKILL.md` (lines 1-6)
- Modify: `~/.claude/a separate skill (not included in this export) (lines 1-6)
- Modify: `~/.claude/skills/deep-dive/SKILL.md` (lines 1-7)
- Modify: `~/.claude/skills/triage/SKILL.md` (lines 1-6)
- Modify: `~/.claude/skills/recall/SKILL.md` (lines 1-13)
- Modify: `~/.claude/skills/garden/SKILL.md` (lines 1-12)
- Modify: `~/.claude/skills/gather-intel/SKILL.md` (lines 1-7)
- Modify: `~/.claude/skills/gather-research/SKILL.md` (lines 1-8)

**Step 1: Write the batch update script**

Since `~/.claude/` files get reverted by hooks on sequential Edit calls, batch all 8 skill updates into one Python script. For each skill, insert `effort: max` or `effort: low` into the YAML frontmatter after `argument-hint` (if present) or after `description`.

Classification:
- `effort: max` → superplan, investigate, deep-dive, triage (multi-phase, cross-tool, iterative)
- `effort: low` → recall, garden, gather-intel, gather-research (single-domain, linear)

```python
import os, re

base = os.path.expanduser('~/.claude/skills')

updates = {
    'superplan': 'max',
    'investigate': 'max',
    'deep-dive': 'max',
    'triage': 'max',
    'recall': 'low',
    'garden': 'low',
    'gather-intel': 'low',
    'gather-research': 'low',
}

for skill, level in updates.items():
    path = os.path.join(base, skill, 'SKILL.md')
    with open(path, encoding='utf-8') as f:
        content = f.read()

    # Check if effort already present
    if f'effort: {level}' in content or 'effort:' in content.split('---')[1]:
        print(f"SKIP: {skill} already has effort field")
        continue

    # Find the end of frontmatter (second ---) and insert before it
    parts = content.split('---', 2)
    if len(parts) < 3:
        print(f"ERROR: {skill} - can't parse frontmatter")
        continue

    fm = parts[1]  # frontmatter content
    # Insert effort as last field before closing ---
    fm = fm.rstrip() + f'\neffort: {level}\n'
    new_content = '---' + fm + '---' + parts[2]

    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_content)
    print(f"OK: {skill} -> effort: {level}")
```

**Step 2: Run the script**

Run: `cd ~ && python tmp_effort_update.py`
Expected: 8 "OK" lines.

**Step 3: Verify frontmatter is valid**

For each skill, read the first 10 lines and confirm YAML is valid:
```bash
for skill in superplan investigate deep-dive triage recall garden gather-intel gather-research; do
  echo "=== $skill ===" && head -15 ~/.claude/skills/$skill/SKILL.md && echo
done
```

**Step 4: Clean up and commit**

```bash
rm -f ~/tmp_effort_update.py
cd ~/.claude
git add skills/*/SKILL.md
git commit -m "$(cat <<'EOF'
feat: add effort frontmatter to 8 skills

effort: max - superplan, investigate, deep-dive, triage
effort: low - recall, garden, gather-intel, gather-research

Leverages v2.1.80 effort field for per-skill compute allocation.
EOF
)"
```

---

### Task 5: Add rate_limits to statusline

**Files:**
- Modify: `~/.claude/statusline.py`

**Step 1: Read current statusline**

Current file is at `~/.claude/statusline.py` (29 lines). It shows: model, directory, branch, context bar, cost, duration.

**Step 2: Add rate limit display**

The `rate_limits` field is in the statusline input JSON under `data['rate_limits']` (if available). Structure: `{ "five_hour": { "used_percentage": N, "resets_at": "ISO" }, "seven_day": { "used_percentage": N, "resets_at": "ISO" } }`.

Add rate limit info to the second status line when available:

```python
#!/usr/bin/env python3
"""Claude Code status line: context %, cost, duration, model, rate limits."""
import json, sys, os, subprocess

data = json.load(sys.stdin)
model = data['model']['display_name']
directory = os.path.basename(data.get('workspace', {}).get('current_dir', '.'))
cost = data.get('cost', {}).get('total_cost_usd', 0) or 0
pct = int(data.get('context_window', {}).get('used_percentage', 0) or 0)
duration_ms = data.get('cost', {}).get('total_duration_ms', 0) or 0

GREEN, YELLOW, RED, CYAN, RESET = '\033[32m', '\033[33m', '\033[31m', '\033[36m', '\033[0m'

bar_color = RED if pct >= 70 else YELLOW if pct >= 50 else GREEN
filled = pct // 10
bar = '\u2588' * filled + '\u2591' * (10 - filled)

mins, secs = duration_ms // 60000, (duration_ms % 60000) // 1000

try:
    subprocess.check_output(['git', 'rev-parse', '--git-dir'], stderr=subprocess.DEVNULL)
    branch = subprocess.check_output(['git', 'branch', '--show-current'], text=True, stderr=subprocess.DEVNULL).strip()
    branch_str = f" | {branch}" if branch else ""
except Exception:
    branch_str = ""

# Rate limit indicator (v2.1.80+)
rate_str = ""
rl = data.get('rate_limits', {})
if rl:
    five_hr = rl.get('five_hour', {}).get('used_percentage', 0) or 0
    if five_hr >= 80:
        rate_str = f" | {RED}RL:{five_hr}%{RESET}"
    elif five_hr >= 50:
        rate_str = f" | {YELLOW}RL:{five_hr}%{RESET}"

print(f"{CYAN}[{model}]{RESET} {directory}{branch_str}")
print(f"{bar_color}{bar}{RESET} {pct}% | {YELLOW}${cost:.2f}{RESET} | {mins}m {secs}s{rate_str}")
```

**Step 3: Test the statusline**

The statusline is called by Claude Code on every render. After saving, it will automatically take effect. Watch the status bar - if rate_limits is not in the JSON input yet (pre-v2.1.80 session), the rate indicator simply won't appear (graceful degradation via the `if rl:` check).

**Step 4: Commit**

```bash
cd ~/.claude
git add statusline.py
git commit -m "feat: add rate limit indicator to statusline (v2.1.80)"
```

---

### Task 6: Create StopFailure hook for rate limit recovery

**Files:**
- Create: `~/.claude/hooks/stop-failure-handler.py`
- Modify: `settings.json` (add StopFailure hook entry)

**Step 1: Write the StopFailure hook**

This hook fires when a turn ends due to an API error. It logs the failure type and injects recovery guidance.

```python
#!/usr/bin/env python3
"""StopFailure hook: logs API failures and provides recovery guidance."""
import json, sys, os, datetime

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

failure_type = data.get('stop_reason', 'unknown')
log_path = os.path.expanduser('~/.claude/logs/stop-failures.jsonl')

os.makedirs(os.path.dirname(log_path), exist_ok=True)

entry = {
    'timestamp': datetime.datetime.now().isoformat(),
    'failure_type': failure_type,
    'session_id': os.environ.get('SESSION_ID', 'unknown'),
}

with open(log_path, 'a', encoding='utf-8') as f:
    f.write(json.dumps(entry) + '\n')

# Inject recovery guidance based on failure type
guidance = {
    'rate_limit': 'Rate limited. Wait 60s before retrying. Check statusline RL% indicator.',
    'authentication_failed': 'Auth failure. Check API key validity: claude --version && echo $ANTHROPIC_API_KEY | tail -c5',
    'max_output_tokens': 'Output token limit hit. Break the response into smaller chunks or increase MAX_OUTPUT_TOKENS.',
    'server_error': 'Anthropic server error. Transient - retry in 30s.',
    'billing_error': 'Billing issue. Check account status at console.anthropic.com.',
}

msg = guidance.get(failure_type, f'Unknown stop failure: {failure_type}. Check ~/.claude/logs/stop-failures.jsonl')
print(json.dumps({"message": msg}))
sys.exit(0)
```

**Step 2: Register the hook in settings.json**

Use Python atomic write to add a StopFailure event handler:

```python
import json, os

path = os.path.expanduser('~/.claude/settings.json')
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)

stop_failure_hook = [{
    "matcher": ".*",
    "hooks": [{
        "type": "command",
        "command": "C:/Users/you/AppData/Local/Programs/Python/Python314/pythonw.exe $HOME/.claude/hooks/stop-failure-handler.py",
        "timeout": 5
    }]
}]

cfg['hooks']['StopFailure'] = stop_failure_hook

with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
```

**Step 3: Verify registration**

Run: `python3 -c "import json; cfg=json.load(open(os.path.expanduser('~/.claude/settings.json'))); print('StopFailure' in cfg['hooks'])"` (import os too)
Expected: `True`

**Step 4: Verify hook file syntax**

Run: `python -c "import py_compile; py_compile.compile(os.path.expanduser('~/.claude/hooks/stop-failure-handler.py'), doraise=True)"`
Expected: No errors.

**Step 5: Commit**

```bash
cd ~/.claude
git add hooks/stop-failure-handler.py
# settings.json is already tracked
git commit -m "$(cat <<'EOF'
feat: add StopFailure hook for rate limit recovery

Logs all API failures to ~/.claude/logs/stop-failures.jsonl.
Injects recovery guidance based on failure type:
- rate_limit: wait and check RL% indicator
- auth/billing: diagnostic commands
- max_output_tokens: chunking suggestion
- server_error: retry guidance
EOF
)"
```

---

### Task 7: Create InstructionsLoaded validation hook

**Files:**
- Create: `~/.claude/hooks/instructions-loaded-validator.py`
- Modify: `settings.json` (add InstructionsLoaded hook entry)

**Step 1: Write the InstructionsLoaded hook**

This hook fires when CLAUDE.md or rules files are loaded. It validates they haven't been corrupted or drifted.

```python
#!/usr/bin/env python3
"""InstructionsLoaded hook: validates instruction files on load."""
import json, sys, os

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

file_path = data.get('file_path', '')
load_reason = data.get('load_reason', 'unknown')

# Only validate on session_start and compact (most important)
if load_reason not in ('session_start', 'compact'):
    sys.exit(0)

# Check file exists and is non-empty
if file_path and os.path.exists(file_path):
    size = os.path.getsize(file_path)
    if size == 0:
        print(json.dumps({
            "message": f"WARNING: Empty instruction file loaded: {file_path} (load_reason={load_reason})"
        }))
    elif size < 50:
        print(json.dumps({
            "message": f"WARNING: Suspiciously small instruction file: {file_path} ({size} bytes)"
        }))

sys.exit(0)
```

**Step 2: Register the hook in settings.json**

```python
import json, os

path = os.path.expanduser('~/.claude/settings.json')
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)

instructions_hook = [{
    "matcher": "session_start|compact",
    "hooks": [{
        "type": "command",
        "command": "C:/Users/you/AppData/Local/Programs/Python/Python314/pythonw.exe $HOME/.claude/hooks/instructions-loaded-validator.py",
        "timeout": 3
    }]
}]

cfg['hooks']['InstructionsLoaded'] = instructions_hook

with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
```

**Step 3: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile(os.path.expanduser('~/.claude/hooks/instructions-loaded-validator.py'), doraise=True)"`

**Step 4: Commit**

```bash
cd ~/.claude
git add hooks/instructions-loaded-validator.py
git commit -m "feat: add InstructionsLoaded hook for instruction file validation"
```

---

### Task 8: Update ARCHITECTURE.md with new hooks

**Files:**
- Modify: `~/.claude/ARCHITECTURE.md`

**Step 1: Move StopFailure from "Not Yet Used" to active**

Add a `#### StopFailure` section after `#### Stop` with the new hook entry.

**Step 2: Add InstructionsLoaded to active hooks (if Task 7 implemented)**

Add a `#### InstructionsLoaded` section after `#### Stop` / `#### StopFailure`.

**Step 3: Update PreCompact echo with new skills**

If any new skills were added, update the PreCompact echo string.

**Step 4: Commit**

```bash
cd ~/.claude
git add ARCHITECTURE.md
git commit -m "docs: update ARCHITECTURE.md with StopFailure and InstructionsLoaded hooks"
```

---

### Task 9: Ship all changes

**Step 1: Review all changes**

```bash
cd ~/.claude && git status && git log --oneline origin/main..HEAD
```

**Step 2: Squash into logical commits if needed**

If there are too many small commits, consider interactive rebase. Otherwise, push as-is.

**Step 3: Ship via PR**

```bash
cd ~/.claude
git push -u origin feat/v2180-leverage-and-retest
gh pr create --title "feat: v2.1.80 leverage and retest" --body "$(cat <<'EOF'
## Summary
- Retested 4 upstream subagent bugs (#34240, #32402, #21460, #27755) on v2.1.80
- Added `effort` frontmatter to 8 skills (4 max, 4 low)
- Added rate limit indicator to statusline
- Created StopFailure hook for API failure recovery
- Created InstructionsLoaded hook for instruction file validation
- Updated ARCHITECTURE.md and MEMORY.md with v2.1.80 findings

## Test plan
- [ ] Probe test results logged in ~/probe-hook-test.log
- [ ] All 8 skills load correctly with new frontmatter
- [ ] Statusline renders with and without rate_limits field
- [ ] StopFailure hook file passes py_compile
- [ ] InstructionsLoaded hook file passes py_compile
EOF
)"
gh pr merge --auto --squash --delete-branch
```

---

## Dependency Graph

```
Task 1 (probe hook) → Task 2 (run tests) → Task 3 (cleanup + update docs)
                                                      ↓
Task 4 (effort frontmatter) ─────────────────────→ Task 9 (ship)
Task 5 (rate_limits statusline) ──────────────────→ Task 9
Task 6 (StopFailure hook) ────────→ Task 8 ──────→ Task 9
Task 7 (InstructionsLoaded hook) ─→ Task 8 ──────→ Task 9
```

Tasks 4, 5, 6, 7 are fully independent and can run in parallel.
Tasks 1-3 are sequential (probe lifecycle).
Task 8 depends on 6 and 7.
Task 9 depends on everything.
