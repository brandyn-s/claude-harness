# Retrospective Deficiency Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 5 deficiencies identified in the 48h retrospective (Mar 7-8, 2026): WebSearch enforcement, ToolSearch empty rate, auto-learn zero entries, pre-deploy incompatibility checks, and bash error classification.

**Architecture:** Four hooks (1 new, 3 modified), one skill update, and one rule addition. All changes are to `~/.claude/` config files - no application code.

**Tech Stack:** Python hooks, JSON config (settings.json, skill-rules.json), markdown rules/skills

---

### Task 1: Block WebSearch with PreToolUse hook

The `web-search-preference.md` rule says "NEVER use WebSearch" but has no enforcement. 13 violations in 48h. We already have `guard-webfetch.py` for WebFetch - need to add WebSearch to the same matcher or create a parallel hook.

**Files:**
- Modify: `~/.claude/settings.json` (add WebSearch to guard-webfetch matcher)
- Modify: `~/.claude/hooks/guard-webfetch.py` (handle WebSearch tool, not just URL-based WebFetch)

**Step 1: Update settings.json matcher**

The current matcher is `"WebFetch"`. Change it to `"WebFetch|WebSearch"` so the hook fires for both tools.

Use a Python script for atomic JSON modification (settings.json is actively written by Claude Code):

```python
import json

path = "$HOME/.claude/settings.json"
with open(path, "r", encoding="utf-8") as f:
    settings = json.load(f)

# Find the guard-webfetch hook and update its matcher
for hook_group in settings["hooks"].get("PreToolUse", []):
    if hook_group.get("matcher") == "WebFetch":
        hook_group["matcher"] = "WebFetch|WebSearch"
        break

with open(path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
```

**Step 2: Update guard-webfetch.py to handle WebSearch**

Add WebSearch handling at the top of `main()`, before the URL-based checks. When the tool is WebSearch (not WebFetch), check if Tavily is available:

```python
# In main(), after reading data:
tool_name = data.get("tool_name", "")

# WebSearch: always block if Tavily available, allow as fallback if not
if tool_name == "WebSearch":
    if _tavily_available(data):
        msg = "Blocked WebSearch: Use mcp__tavily__tavily_search instead. Tavily provides better results with relevance scoring."
        print(msg, file=sys.stderr)
        sys.exit(2)
    else:
        msg = "WARNING: Tavily MCP unavailable. Allowing WebSearch as degraded fallback."
        print(json.dumps({"systemMessage": msg}))
        sys.exit(0)

# Existing WebFetch URL-based logic continues below...
```

**Step 3: Test the hook**

```bash
# Test WebSearch blocked when Tavily available (default)
echo '{"tool_name": "WebSearch", "tool_input": {"query": "test"}}' | pythonw ~/.claude/hooks/guard-webfetch.py 2>&1
# Expected: exit 2, "Blocked WebSearch" message

# Test WebSearch allowed when Tavily unavailable
export TAVILY_MCP_AVAILABLE=0
echo '{"tool_name": "WebSearch", "tool_input": {"query": "test"}}' | pythonw ~/.claude/hooks/guard-webfetch.py 2>&1
# Expected: exit 0, "WARNING: Tavily MCP unavailable" message
unset TAVILY_MCP_AVAILABLE

# Test WebFetch still works as before
echo '{"tool_input": {"url": "https://www.reddit.com/r/ClaudeCode"}}' | pythonw ~/.claude/hooks/guard-webfetch.py 2>&1
# Expected: exit 2, "Reddit blocks scraping"
```

**Step 4: Verify effectiveness**

This hook fires for every WebSearch/WebFetch call. The 13 violations from the retro would all be blocked. Verify: `grep -c "WebSearch\|WebFetch" ~/.claude/settings.json` should show the matcher.

**Step 5: Commit**

```bash
cd ~/.claude && git add hooks/guard-webfetch.py settings.json
git commit -m "feat: block WebSearch via PreToolUse hook (13 retro violations)"
```

---

### Task 2: Fix ToolSearch 91% empty rate

52 of 57 ToolSearch calls returned empty because of vague semantic queries. The fix has two parts: a rule update (teach correct syntax) and a PostToolUseFailure-style prompt hint.

**Files:**
- Modify: `~/.claude/rules/platform-constraints.md` or create new rule
- Modify: `~/.claude/projects/<your-claude-project>/CLAUDE.md` (ToolSearch guidance already exists at line 32)

**Step 1: Read the existing ToolSearch guidance**

Read `~/.claude/projects/<your-claude-project>/CLAUDE.md` line 32 which has:
```
- For ToolSearch, use the MCP service name as the keyword (e.g., "hologram" not "device management", "tailscale" not "VPN"). Use `select:mcp__service__tool_name` for exact matches. MCP tool names follow the pattern `mcp__server-name__tool_name`.
```

This guidance exists but isn't being followed. The fix is to make it more prominent and add concrete examples.

**Step 2: Strengthen the ToolSearch guidance in CLAUDE.md**

Replace the existing ToolSearch line with expanded guidance:

```markdown
- **ToolSearch** (91% empty rate in retro - fix this):
  - ALWAYS use `select:mcp__server__tool1,mcp__server__tool2` when you know the tool name
  - For discovery, use the MCP server name as keyword: "hologram", "tavily", "crowdstrike" - NOT semantic descriptions like "device management" or "web search"
  - Use `+server_name` prefix to require a match: `+hologram list` finds hologram tools matching "list"
  - Tool name pattern: `mcp__server-name__tool_name` (double underscores, hyphens in server name)
  - If ToolSearch returns empty, retry with the server name, not a broader description
```

**Step 3: Test effectiveness**

Run sample ToolSearch calls to verify the guidance would have prevented the 52 empty results:

```bash
# Vague query (would have been empty):
# "device management" -> 0 results
# Correct query:
# "select:mcp__hologram__list_devices" -> 1 result
# Or: "+hologram list" -> hologram tools matching "list"
```

This is behavioral guidance, not a hook. Effectiveness depends on the model following the rule. The retro showed the previous single-line guidance wasn't sufficient - the expanded version with examples and the "91% empty rate" callout should be more memorable.

**Step 4: Commit**

```bash
cd ~/.claude && git add -f projects/<your-claude-project>/CLAUDE.md
git commit -m "docs: strengthen ToolSearch guidance (91% empty rate in retro)"
```

---

### Task 3: Fix auto-learn zero entries (lower delta threshold)

26 launches, 0 entries written. The 3MB delta threshold is too aggressive for iterative sessions.

**Files:**
- Modify: `~/.claude/hooks/session-stop.py:413` (change `3_000_000` to `1_000_000`)

**Step 1: Lower the delta threshold**

In `session-stop.py`, find line 413:
```python
            if delta < 3_000_000:
```

Change to:
```python
            if delta < 1_000_000:
```

And update the skip message on the next line:
```python
                _write_skip_marker(session_id, f"insufficient delta ({delta} bytes < 1MB since last run)", ...)
```

**Step 2: Verify the change**

```bash
grep "delta.*_000_000" ~/.claude/hooks/session-stop.py
# Expected: "if delta < 1_000_000:"
```

**Step 3: Assess effectiveness**

The retro showed 26 launches with most skipped for "insufficient delta." With 1MB threshold instead of 3MB, more launches will proceed to the Opus analysis step. The actual entry generation depends on the Opus subprocess finding actionable patterns - but at least it will get the chance to look.

To verify Opus is actually running when it gets past the threshold, check for the "launched" marker:

```bash
cat ~/.claude/last-auto-learn.json
# Should show "status": "launched" after the next qualifying session
```

**Step 4: Commit**

```bash
cd ~/.claude && git add hooks/session-stop.py
git commit -m "fix: lower auto-learn delta threshold from 3MB to 1MB (0 entries in 26 launches)"
```

---

### Task 4: Add pre-deploy incompatibility check to superplan

BiFrost SQLite-on-EFS corruption was a known pattern in `platform-constraints.md` but wasn't consulted before deploying. 3 hours wasted.

**Files:**
- Modify: `~/.claude/skills/superplan/SKILL.md` (add incompatibility check step)

**Step 1: Read the current superplan skill structure**

Read `~/.claude/skills/superplan/SKILL.md` to find where to insert the check. Look for the planning phase where technology choices are made.

**Step 2: Add a pre-deploy checklist step**

After the step where the plan identifies technology choices (databases, storage, auth), add:

```markdown
### Pre-Deploy Incompatibility Check

Before finalizing any plan that deploys new infrastructure, check `~/.claude/rules/platform-constraints.md` for known incompatibilities:

| Technology | Known Incompatibility | Source |
|---|---|---|
| SQLite | Does NOT work on EFS/NFS - causes corruption | platform-constraints.md |
| Redis | Requires `ssl=True` hardcoded for ElastiCache | platform-constraints.md |
| OIDC | GCC High uses `.us` endpoints, not `.com` | msgraph-patterns.md |
| Docker health checks | Wolfi/Chainguard images lack curl - use Python | infrastructure.md |
| ECR tags | IMMUTABLE blocks CI `:latest` re-tagging | infrastructure.md |

**Action**: For each technology in the plan, grep `platform-constraints.md` and `infrastructure.md` for the technology name. If a known incompatibility exists, either choose an alternative or document the mitigation in the plan.

This check takes 30 seconds and prevents multi-hour debugging of documented issues.
```

**Step 3: Verify the check would have caught BiFrost**

The BiFrost issue was SQLite on EFS. The table above includes "SQLite does NOT work on EFS/NFS." A grep for "SQLite" in platform-constraints.md returns the documented incompatibility. This check would have caught it.

**Step 4: Commit**

```bash
cd ~/.claude && git add skills/superplan/SKILL.md
git commit -m "feat: add pre-deploy incompatibility check to superplan (BiFrost SQLite lesson)"
```

---

### Task 5: Expand bash error classification regexes

29 of 66 bash errors (44%) classified as "other." The retrospective extractor needs more patterns.

**Files:**
- Modify: `~/.claude/hooks/session-stop.py` or the retrospective skill's error classifier

**Step 1: Find the error classification code**

The retrospective skill extracts errors from transcripts. Find where bash errors are classified. Check both:
- `~/.claude/skills/retrospective/SKILL.md` (if classification is in the skill instructions)
- `~/.claude/hooks/session-stop.py` (if classification is in the hook)

```bash
grep -rn "other.*bash\|bash.*classif\|error.*categor\|subcategor" ~/.claude/skills/retrospective/ ~/.claude/hooks/session-stop.py
```

**Step 2: Read the current classification patterns**

Find the regex patterns used to classify bash errors into subcategories (python_exception, file_not_found, dirty_working_tree, etc.) and identify what the "other" bucket is catching.

**Step 3: Add missing patterns**

Based on the retro data, the 29 "other" errors likely include:
- Permission denied errors
- Command not found (aws CLI, npm, etc.)
- JSON parse errors from jq or Python
- Git errors not covered by existing patterns (merge conflicts, detached HEAD)
- Network timeouts

Add regex patterns for these common bash error types. The exact patterns depend on the classifier's structure - read the code first, then add patterns that match the unclassified errors.

**Step 4: Test against known transcripts**

Run the updated classifier against session 27b23906 (which had 13 "other" bash errors) and verify the count drops:

```bash
# Before: 13 "other" in session 27b23906
# After: should be <5 "other" (most reclassified)
```

**Step 5: Commit**

```bash
cd ~/.claude && git add <modified-files>
git commit -m "fix: expand bash error classification (44% unclassified in retro)"
```

---

### Task 6: Ship all changes

**Files:** None (git operations only)

**Step 1: Create feature branch**

```bash
cd ~/.claude
git checkout -b feat/retro-deficiency-fixes
```

**Step 2: Squash or batch commit**

If tasks were committed individually during implementation, the branch should have 5 commits. Ship as-is (squash merge will combine them).

**Step 3: Push, PR, CI, merge**

```bash
git push -u origin feat/retro-deficiency-fixes
gh pr create --title "feat: fix 5 retrospective deficiencies (WebSearch, ToolSearch, auto-learn, pre-deploy, error classification)"
sleep 12
gh pr checks <number> --watch
git stash
gh pr merge <number> --squash --delete-branch --admin
git checkout main && git fetch origin main && git rebase origin/main
git stash pop
```

---

## Expected Impact

| Deficiency | Current | Expected After |
|---|---|---|
| WebSearch violations | 13/48h | 0 (hook blocks) |
| ToolSearch empty rate | 91% | <50% (stronger guidance + examples) |
| Auto-learn entries | 0/26 launches | >0 (lower threshold lets Opus analyze) |
| Known-incompatibility misses | 1 (3h wasted) | 0 (pre-deploy check in superplan) |
| Unclassified bash errors | 44% | <20% (expanded patterns) |

## Risk Register

| Risk | Mitigation |
|---|---|
| WebSearch block prevents fallback when Tavily is down | Hook checks TAVILY_MCP_AVAILABLE env var (already implemented in guard-webfetch.py) |
| ToolSearch guidance still ignored | Guidance is behavioral - but the "91% empty rate" callout is specific enough to be memorable. If rate doesn't improve, add a PreToolUse hook. |
| Lower auto-learn threshold causes too many Opus launches | Each launch costs ~$0.50-2.00. At 1MB threshold, expect 2-3x more launches per day. Cost is bounded by $5 max budget per launch. |
| Pre-deploy check adds latency to superplan | The check is a single grep against 2 files. <30 seconds. |
| Error classification changes affect retrospective comparisons | Old retros used old categories. Note the change in the next retro header. |
