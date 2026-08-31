# Anti-Pattern Remediation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Address 3 architectural anti-patterns: ARCHITECTURE.md manual sync, ship gate overhead, and PR fragmentation.

**Architecture:** All 3 tasks are independent. Changes touch a new generator script, the ship skill, and the sync-repo skill. No MCP server, hook, or agent changes.

**Tech Stack:** Python (generator script, test scripts), Markdown (skills)

**Methodology:** Tests-first for every task. Write the test script that defines success criteria BEFORE writing any implementation. The test must fail initially (proving it tests something real), then pass after implementation.

---

## Task 1: Auto-generate ARCHITECTURE.md tables from disk state

**Problem:** ARCHITECTURE.md is 771 lines of manually-synchronized documentation. Tables listing MCP servers, hooks, rules, skills, and topics drift every time a component is added.

**Files:**
- Create: `~/.claude/hooks/generate-architecture.py`
- Create: `~/.claude/tests/test-generate-architecture.py`
- Modify: `~/.claude/ARCHITECTURE.md` (add generation markers)
- Modify: `~/.claude/skills/sync-repo/SKILL.md` (integrate generation)

### Step 1: Write the test script

Create `tests/test-generate-architecture.py` that validates the generator's contract. The test must be runnable BEFORE the generator exists (it will fail, proving it tests something real).

```python
"""Tests for generate-architecture.py. Run BEFORE implementation to verify tests fail."""
import subprocess, sys, os, json, tempfile, shutil

GENERATOR = os.path.expanduser("~/.claude/hooks/generate-architecture.py")
ARCH_MD = os.path.expanduser("~/.claude/ARCHITECTURE.md")
RULES_DIR = os.path.expanduser("~/.claude/rules")
HOOKS_DIR = os.path.expanduser("~/.claude/hooks")
TOPICS_DIR = os.path.expanduser("~/.claude/agent-memory/topics")

results = []

def test(name, condition, detail=""):
    results.append((name, condition, detail))
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))

# T1: Generator script exists and runs without error
def test_generator_runs():
    r = subprocess.run([sys.executable, GENERATOR], capture_output=True, text=True, timeout=30)
    test("Generator exits 0", r.returncode == 0, f"exit={r.returncode}, stderr={r.stderr[:200]}")

# T2: ARCHITECTURE.md has generation markers after running
def test_markers_present():
    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        content = f.read()
    markers = ["BEGIN:GENERATED:", "END:GENERATED:"]
    for m in markers:
        test(f"Marker '{m}' exists in ARCHITECTURE.md", m in content)

# T3: All configured MCP servers appear in generated tables
def test_mcp_completeness():
    # Build config inventory (same logic as audit discovery)
    config_servers = set()
    claude_json = os.path.expanduser("~/.claude.json")
    with open(claude_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    config_servers.update(data.get('mcpServers', {}).keys())
    for proj_cfg in data.get('projects', {}).values():
        if isinstance(proj_cfg, dict):
            config_servers.update(proj_cfg.get('mcpServers', {}).keys())
    for mcp_path in [os.path.expanduser("~/.mcp.json"), os.path.expanduser("~/.claude/.mcp.json")]:
        if os.path.exists(mcp_path):
            with open(mcp_path, 'r', encoding='utf-8') as f:
                config_servers.update(json.load(f).get('mcpServers', {}).keys())

    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        arch_content = f.read()
    missing = [s for s in config_servers if f'`{s}`' not in arch_content]
    test("All config servers in ARCHITECTURE.md", len(missing) == 0, f"missing: {missing}")

# T4: All rule files on disk appear in generated rules table
def test_rules_completeness():
    disk_rules = {f for f in os.listdir(RULES_DIR) if f.endswith('.md')}
    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        arch_content = f.read()
    missing = [r for r in disk_rules if f'`{r}`' not in arch_content]
    test("All disk rules in ARCHITECTURE.md", len(missing) == 0, f"missing: {missing}")

# T5: All topic files on disk appear in generated topic table
def test_topics_completeness():
    disk_topics = {f for f in os.listdir(TOPICS_DIR) if f.endswith('.md')}
    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        arch_content = f.read()
    missing = [t for t in disk_topics if t not in arch_content]
    test("All disk topics in ARCHITECTURE.md", len(missing) == 0, f"missing: {missing}")

# T6: Narrative sections are preserved (not overwritten)
def test_narrative_preserved():
    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        content = f.read()
    # These phrases exist in narrative sections that must survive generation
    narratives = [
        "Three principles drive every design decision",
        "Work is task-based, not domain-siloed",
        "Safety through automation, not discipline",
    ]
    for phrase in narratives:
        test(f"Narrative preserved: '{phrase[:40]}...'", phrase in content)

# T7: Adding a fake component and regenerating picks it up
def test_addition_detected():
    fake_rule = os.path.join(RULES_DIR, "test-fake-rule.md")
    try:
        with open(fake_rule, 'w') as f:
            f.write("# Fake rule for testing\n")
        subprocess.run([sys.executable, GENERATOR], capture_output=True, timeout=30)
        with open(ARCH_MD, 'r', encoding='utf-8') as f:
            content = f.read()
        test("Fake rule appears after regeneration", "test-fake-rule.md" in content)
    finally:
        os.remove(fake_rule)
        # Regenerate to clean up
        subprocess.run([sys.executable, GENERATOR], capture_output=True, timeout=30)

# T8: Removing a component and regenerating drops it
def test_removal_detected():
    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        content = f.read()
    test("Fake rule gone after cleanup regeneration", "test-fake-rule.md" not in content)

# T9: Idempotency — running twice produces identical output
def test_idempotent():
    subprocess.run([sys.executable, GENERATOR], capture_output=True, timeout=30)
    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        first = f.read()
    subprocess.run([sys.executable, GENERATOR], capture_output=True, timeout=30)
    with open(ARCH_MD, 'r', encoding='utf-8') as f:
        second = f.read()
    test("Idempotent: two runs produce identical output", first == second)

# Run all tests
print("=== generate-architecture.py test suite ===\n")
test_generator_runs()
test_markers_present()
test_mcp_completeness()
test_rules_completeness()
test_topics_completeness()
test_narrative_preserved()
test_addition_detected()
test_removal_detected()
test_idempotent()

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n{'='*50}")
print(f"Results: {passed}/{total} passed")
if passed < total:
    print("FAILED tests:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
```

### Step 2: Run the test — verify it fails

```bash
python tests/test-generate-architecture.py
```

Expected: T1 fails (generator doesn't exist). T2 fails (no markers). T7/T8 fail (can't run generator). T3-T6 and T9 may pass or fail depending on current state. The important thing is T1 fails — the generator is not yet built.

### Step 3: Identify derivable vs narrative sections in ARCHITECTURE.md

Read ARCHITECTURE.md. Mark sections as GENERATE or KEEP per the analysis in Step 1's description above.

### Step 4: Add generation markers to ARCHITECTURE.md

Insert `<!-- BEGIN:GENERATED:section -->` and `<!-- END:GENERATED:section -->` around each derivable table. Sections to mark:
- `mcp-remote` (remote server table)
- `mcp-local` (local stdio table)
- `mcp-hosted` (hosted/remote utility table)
- `hooks-pretooluse` (PreToolUse hooks table)
- `hooks-posttooluse` (PostToolUse hooks table)
- `hooks-posttooluseFailure` (PostToolUseFailure table)
- `hooks-other` (UserPromptSubmit, SubagentStart, SubagentStop, Stop, StopFailure, InstructionsLoaded, PreCompact tables)
- `rules-table` (rules table)
- `topics-table` (topic files table)
- `skills-operations` through `skills-maintenance` (skill inventory tables)
- `file-map` (file map code block)

### Step 5: Write the generator script

Create `hooks/generate-architecture.py` following the spec in Step 3's description. Key design decisions:
- Read existing hand-written descriptions from the current file before regenerating
- Merge discovered components with existing descriptions
- New components get `(description needed)` placeholder
- Removed components are dropped silently
- Everything outside markers is preserved byte-for-byte

### Step 6: Run the test — verify all pass

```bash
python tests/test-generate-architecture.py
```

Expected: All 9+ tests pass. If any fail, fix the generator before proceeding.

### Step 7: Integrate into sync-repo skill

Update sync-repo SKILL.md to run `python hooks/generate-architecture.py` as its first step before any ARCHITECTURE.md diffing.

### Step 8: Commit

```bash
git add hooks/generate-architecture.py tests/test-generate-architecture.py ARCHITECTURE.md skills/sync-repo/SKILL.md
git commit -m "feat: auto-generate ARCHITECTURE.md tables from disk state"
```

---

## Task 2: Fast pre-filter for ship gates

**Problem:** The ship skill runs 6 gates on every PR regardless of diff content. For single-file markdown changes, 5 of 6 gates are no-ops.

**Files:**
- Modify: `~/.claude/skills/ship/SKILL.md`
- Create: `~/.claude/tests/test-gate-prefilter.py`

### Step 1: Write the test script

Create `tests/test-gate-prefilter.py` that validates the classification logic against known file lists. This test is self-contained — it tests the classification function, not the ship skill itself.

```python
"""Tests for ship gate pre-filter classification logic."""
import sys
sys.stdout.reconfigure(encoding='utf-8')

results = []

def test(name, condition, detail=""):
    results.append((name, condition, detail))
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def classify_diff(file_list):
    """Classify a diff file list into docs-only, config-only, component, or mixed.
    This is the function the ship skill's Gate Pre-Filter should implement."""
    component_patterns = [
        'skills/', 'rules/', 'agents/', 'agent-memory/',
        'hooks/', '.github/workflows/', 'Dockerfile',
        'scripts/', 'templates/', 'auth', 'middleware', 'opa',
    ]
    config_files = {'settings.json', 'settings.local.json', '.claude.json', '.mcp.json'}

    has_docs = False
    has_config = False
    has_component = False

    for f in file_list:
        basename = f.split('/')[-1]
        if basename in config_files:
            has_config = True
        elif any(p in f for p in component_patterns):
            has_component = True
        elif f.endswith('.md'):
            has_docs = True
        else:
            has_component = True  # unknown files are conservative

    if has_component:
        return 'mixed' if (has_docs or has_config) else 'component'
    if has_config:
        return 'mixed' if has_docs else 'config-only'
    if has_docs:
        return 'docs-only'
    return 'docs-only'  # empty diff

# Test cases from real PRs in this session
def test_classifications():
    # PR #391: audit skill changes (component)
    test("PR391 audit skill = component",
         classify_diff(['skills/audit-architecture/SKILL.md',
                        'skills/audit-architecture/references/probe-targets.md']) == 'component')

    # PR #393: ship skill gate (component)
    test("PR393 ship skill = component",
         classify_diff(['skills/ship/SKILL.md']) == 'component')

    # PR #394: ARCHITECTURE.md only (docs-only)
    test("PR394 ARCHITECTURE.md = docs-only",
         classify_diff(['ARCHITECTURE.md']) == 'docs-only')

    # PR #396: audit skill only (component)
    test("PR396 audit skill = component",
         classify_diff(['skills/audit-architecture/SKILL.md']) == 'component')

    # PR #397: topic file (component — it's in agent-memory/)
    test("PR397 topic file = component",
         classify_diff(['agent-memory/topics/architecture.md']) == 'component')

    # Hypothetical: only settings.json (config-only)
    test("settings.json only = config-only",
         classify_diff(['settings.json']) == 'config-only')

    # Hypothetical: docs/plans/ markdown (docs-only)
    test("docs/plans/ markdown = docs-only",
         classify_diff(['docs/plans/2026-03-28-plan.md']) == 'docs-only')

    # Hypothetical: CI workflow (component)
    test("CI workflow = component",
         classify_diff(['.github/workflows/validate.yml']) == 'component')

    # Hypothetical: hook + docs (mixed)
    test("hook + ARCHITECTURE.md = mixed",
         classify_diff(['hooks/new-hook.py', 'ARCHITECTURE.md']) == 'mixed')

    # Hypothetical: new rule file (component)
    test("new rule = component",
         classify_diff(['rules/new-rule.md']) == 'component')

    # Edge case: .md file inside skills/ IS component, not docs
    test("skills/*.md = component (not docs)",
         classify_diff(['skills/new-skill/SKILL.md']) == 'component')

    # Edge case: MEMORY.md in projects/ is docs, not component
    test("projects/ MEMORY.md = docs-only",
         classify_diff(['projects/<your-claude-project>/memory/MEMORY.md']) == 'docs-only')

def test_gate_routing():
    """Verify correct gates are selected per classification."""
    gate_map = {
        'docs-only': [],
        'config-only': ['Pre-Ship Consistency Check'],
        'component': 'pattern-match',  # depends on specific files
        'mixed': 'pattern-match',
    }
    test("docs-only skips all gates", gate_map['docs-only'] == [])
    test("config-only runs only consistency", len(gate_map['config-only']) == 1)

def test_this_session_savings():
    """Quantify: how many gate evaluations would this save for the 6 PRs in this session?"""
    session_prs = [
        ('PR391', ['skills/audit-architecture/SKILL.md', 'skills/audit-architecture/references/probe-targets.md'], 'component'),
        ('PR393', ['skills/ship/SKILL.md'], 'component'),
        ('PR394', ['ARCHITECTURE.md'], 'docs-only'),
        ('PR396', ['skills/audit-architecture/SKILL.md'], 'component'),
        ('PR397', ['agent-memory/topics/architecture.md'], 'component'),
        ('PR398', ['skills/audit-architecture/SKILL.md', 'projects/<your-claude-project>/memory/MEMORY.md', 'projects/<your-claude-project>/memory/feedback_skills-over-rules.md'], 'mixed'),
    ]
    total_gates_before = 6 * 6  # 6 PRs x 6 gates each
    gates_after = 0
    for name, files, expected_class in session_prs:
        actual = classify_diff(files)
        test(f"{name} classified as {expected_class}", actual == expected_class)
        if actual == 'docs-only':
            gates_after += 0
        elif actual == 'config-only':
            gates_after += 1
        else:
            gates_after += 6  # conservative: all gates for component/mixed

    savings_pct = (total_gates_before - gates_after) * 100 // total_gates_before
    test(f"Gate evaluations reduced: {total_gates_before} -> {gates_after} ({savings_pct}% savings)",
         gates_after < total_gates_before,
         f"{savings_pct}% reduction")

print("=== Ship Gate Pre-Filter Test Suite ===\n")
test_classifications()
test_gate_routing()
test_this_session_savings()

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n{'='*50}")
print(f"Results: {passed}/{total} passed")
```

### Step 2: Run the test — verify it passes with the reference implementation

```bash
python tests/test-gate-prefilter.py
```

The test embeds the classification function. All tests should pass — this validates the LOGIC before we put it into the skill. If any fail, fix the classification function in the test until the contract is correct.

### Step 3: Add the Gate Pre-Filter to ship SKILL.md

Insert a new section after Phase 3 (commit message) and before the Security Review Gate. Use the exact classification logic from the tested function. Add the routing table:

```markdown
## Gate Pre-Filter

Before running gates, classify the diff:

1. Run `git diff --cached --name-only` to get the file list
2. Classify:
   - **docs-only**: All files are `.md` outside of `skills/`, `rules/`, `agents/`, `agent-memory/`, `hooks/`
   - **config-only**: Only `settings.json`, `settings.local.json`, or `.claude.json`
   - **component**: Files match any gate trigger pattern
   - **mixed**: Combination

3. Route:
   - **docs-only**: Skip all gates. Proceed to PR creation.
   - **config-only**: Run only Pre-Ship Consistency Check.
   - **component**: Run only gates whose trigger patterns match the diff.
   - **mixed**: Run all applicable gates.
```

### Step 4: Re-run the test to confirm logic matches

```bash
python tests/test-gate-prefilter.py
```

Expected: All tests still pass. The test validates the classification contract; the skill implements it.

### Step 5: Commit

```bash
git add skills/ship/SKILL.md tests/test-gate-prefilter.py
git commit -m "feat: add gate pre-filter to ship skill for fast-path on small changes"
```

---

## Task 3: Batch mode for ship — accumulate then ship once

**Problem:** Incremental shipping creates 1 PR per logical sub-task. This session had 6 PRs for 1 logical task. Each PR has fixed overhead (~6 git ops + CI wait).

**Files:**
- Modify: `~/.claude/skills/ship/SKILL.md`
- Create: `~/.claude/tests/test-ship-batch.py`

### Step 1: Write the test script

Create `tests/test-ship-batch.py` that validates the batch/flush workflow in a temporary git repo (not the real claude-config). This is a simulation test — it creates a throwaway repo, runs the workflow steps, and verifies the results.

```python
"""Tests for ship batch/flush mode. Uses a temp git repo to simulate the workflow."""
import sys, os, subprocess, tempfile, shutil
sys.stdout.reconfigure(encoding='utf-8')

results = []

def test(name, condition, detail=""):
    results.append((name, condition, detail))
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def run(cmd, cwd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=30)
    return r

# Create temp repo
tmpdir = tempfile.mkdtemp(prefix="ship-batch-test-")
try:
    # Init repo with a main branch
    run("git init -b main", tmpdir)
    run("git config user.email test@test.com && git config user.name Test", tmpdir)
    with open(os.path.join(tmpdir, "README.md"), 'w') as f:
        f.write("# Test repo\n")
    run("git add README.md && git commit -m 'initial'", tmpdir)

    # === Test batch mode ===
    print("=== Batch Mode Tests ===\n")

    # T1: After /ship batch, changes are committed but NOT pushed
    # Simulate: create feature branch, make a change, commit
    run("git checkout -b feat/batch-test", tmpdir)
    with open(os.path.join(tmpdir, "file1.py"), 'w') as f:
        f.write("# change 1\n")
    run("git add file1.py && git commit -m 'feat: first change'", tmpdir)

    r = run("git log --oneline feat/batch-test", tmpdir)
    test("Batch: commit exists on feature branch",
         "first change" in r.stdout)

    r = run("git log --oneline main..feat/batch-test", tmpdir)
    commits_after_batch1 = r.stdout.strip().count('\n') + 1
    test("Batch: 1 commit ahead of main after first batch",
         commits_after_batch1 == 1, f"commits={commits_after_batch1}")

    # T2: Second batch adds another commit to SAME branch
    with open(os.path.join(tmpdir, "file2.py"), 'w') as f:
        f.write("# change 2\n")
    run("git add file2.py && git commit -m 'feat: second change'", tmpdir)

    r = run("git log --oneline main..feat/batch-test", tmpdir)
    commits_after_batch2 = len(r.stdout.strip().splitlines())
    test("Batch: 2 commits ahead of main after second batch",
         commits_after_batch2 == 2, f"commits={commits_after_batch2}")

    # T3: Branch is still local (no remote tracking)
    r = run("git config branch.feat/batch-test.remote", tmpdir)
    test("Batch: branch has no remote (not pushed)",
         r.returncode != 0 or r.stdout.strip() == "")

    # === Test flush mode ===
    print("\n=== Flush Mode Tests ===\n")

    # T4: Flush should see all accumulated commits in the diff
    r = run("git diff main..feat/batch-test --stat", tmpdir)
    test("Flush: diff shows both files",
         "file1.py" in r.stdout and "file2.py" in r.stdout)

    # T5: Combined commit log has both messages
    r = run("git log --oneline main..feat/batch-test", tmpdir)
    test("Flush: log has both commit messages",
         "first change" in r.stdout and "second change" in r.stdout)

    # T6: Squash merge produces single commit on main
    run("git checkout main", tmpdir)
    run("git merge --squash feat/batch-test", tmpdir)
    run("git commit -m 'feat: combined batch (squash)'", tmpdir)

    r = run("git log --oneline -3 main", tmpdir)
    test("Flush: squash merge = 1 commit on main",
         "combined batch" in r.stdout)

    # T7: Both files exist after merge
    test("Flush: file1.py exists after merge",
         os.path.exists(os.path.join(tmpdir, "file1.py")))
    test("Flush: file2.py exists after merge",
         os.path.exists(os.path.join(tmpdir, "file2.py")))

    # === Test default mode unchanged ===
    print("\n=== Default Mode (no batch) Tests ===\n")

    # T8: Plain /ship still creates branch + single commit
    run("git checkout -b feat/normal-ship", tmpdir)
    with open(os.path.join(tmpdir, "file3.py"), 'w') as f:
        f.write("# normal ship\n")
    run("git add file3.py && git commit -m 'feat: normal ship change'", tmpdir)

    r = run("git log --oneline main..feat/normal-ship", tmpdir)
    test("Default: single commit on feature branch",
         len(r.stdout.strip().splitlines()) == 1)

finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n{'='*50}")
print(f"Results: {passed}/{total} passed")
```

### Step 2: Run the test — verify it passes

```bash
python tests/test-ship-batch.py
```

This test validates the GIT WORKFLOW (batch accumulates commits, flush squash-merges them). All tests should pass because they're testing git operations, not the skill text. This proves the workflow is sound before encoding it in the skill.

### Step 3: Add batch/flush arguments to ship SKILL.md

Update the Arguments table and add the Batch Mode and Flush Mode sections per the spec. Key rules:
- `/ship batch`: commit on current feature branch (create if on main), do NOT push/PR/gate
- `/ship flush`: run gates against full `origin/main..HEAD` diff, push, PR with combined summary, auto-merge
- `/ship` (no args): unchanged behavior

### Step 4: Re-run the test to confirm workflow contract holds

```bash
python tests/test-ship-batch.py
```

Expected: All tests still pass. The test validates the git workflow; the skill directs Claude to execute it.

### Step 5: Commit

```bash
git add skills/ship/SKILL.md tests/test-ship-batch.py
git commit -m "feat: add batch/flush mode to ship skill for multi-commit PRs"
```

---

## Execution Order

Recommended order:

1. **Task 2** (gate pre-filter) — self-contained test + skill edit, lowest risk, immediate value
2. **Task 3** (batch ship) — self-contained test + skill edit, workflow improvement
3. **Task 1** (auto-generate ARCHITECTURE.md) — most complex, test validates 9 properties of the generator

For each task: write test → run test (verify fails where expected) → implement → run test (verify all pass) → commit.

## Risk Assessment

| Task | Risk | Mitigation |
|------|------|------------|
| 1 (auto-generate) | Generator overwrites hand-written descriptions | T6 (narrative preserved) catches this. Marker-based approach preserves everything outside markers. |
| 1 (auto-generate) | Generator produces different output on each run | T9 (idempotency) catches this. Two consecutive runs must produce byte-identical output. |
| 2 (gate pre-filter) | Security file in a "docs-only" diff gets miscategorized | 12 test cases including edge cases (`.md` inside `skills/` = component). Classification is conservative — unknown files are treated as component. |
| 2 (gate pre-filter) | Savings are trivial | T_savings quantifies against this session's actual PRs — must show measurable reduction. |
| 3 (batch ship) | Batch commits lost during flush | T4-T7 verify both files survive squash merge. Git operations are tested in a real (temp) repo, not mocked. |
| 3 (batch ship) | Forgetting to flush | Dirty repo scan in `/retro` catches unbatched branches. Could add session-stop warning. |
