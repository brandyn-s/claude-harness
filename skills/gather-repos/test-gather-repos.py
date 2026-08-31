#!/usr/bin/env python3
"""Regression tests for /gather-repos skill methodology.

Modes:
  python test-gather-repos.py          # Run all regression tests
  python test-gather-repos.py --audit  # Post-run audit: verify last run's bucket coverage

Verifies:
  1. Discovery finds new repos every search
  2. Repos evaluated across all buckets (not just hooks)
  3. Each bucket evaluated for transferable patterns
  4. NEGATIVE: detects when only hooks are read from multi-bucket repos
  5. AUDIT: post-run verification against ledger entries
"""
import base64
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}

LEDGER_PATH = Path.home() / ".claude" / "assessed-repos.md"

passed = 0
failed = 0


# ═══════════════════════════════════════════════════════════════
# INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════
def gh_api(endpoint: str, timeout: int = 30) -> dict | list | None:
    r = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        timeout=timeout,
        env=ENV,
    )
    if r.returncode != 0:
        return None
    return json.loads(r.stdout.decode("utf-8", "replace"))


def read_gh_file(repo: str, path: str) -> str | None:
    data = gh_api(f"/repos/{repo}/contents/{path}")
    if not isinstance(data, dict) or "content" not in data:
        return None
    raw = data["content"].replace("\n", "")
    return base64.b64decode(raw).decode("utf-8", "replace")


def load_ledger_repos() -> set[str]:
    if not LEDGER_PATH.exists():
        return set()
    text = LEDGER_PATH.read_text(encoding="utf-8")
    repos = set()
    for m in re.finditer(r"###\s+\[.*?\]\s+(\S+/\S+)", text):
        repos.add(m.group(1))
    return repos


def phase1_tree_check(repo: str) -> dict[str, list[str]]:
    """Run Phase 1 tree check. Returns {bucket_name: [file_paths]}."""
    tree = gh_api(f"/repos/{repo}/git/trees/HEAD?recursive=1")
    if not isinstance(tree, dict) or "tree" not in tree:
        return {}
    paths = [e["path"] for e in tree["tree"]]
    buckets: dict[str, list[str]] = {}

    hooks = [p for p in paths if "hooks/" in p and p.endswith((".py", ".sh", ".ts"))]
    if hooks:
        buckets["hooks"] = hooks

    rules = [p for p in paths if "rules/" in p and p.endswith(".md")]
    if rules:
        buckets["rules"] = rules

    settings = [p for p in paths if "settings.json" in p]
    if settings:
        buckets["config"] = settings

    skills = [p for p in paths if p.endswith("SKILL.md")]
    if len(skills) >= 3:
        buckets["skills"] = skills

    agents = [p for p in paths if "agents/" in p and p.endswith(".md")]
    if agents:
        buckets["agents"] = agents

    # Memory: exclude SKILL.md files that happen to have "knowledge" in path
    memory = [
        p for p in paths
        if any(x in p for x in ["memory/", "topics/"])
        and not p.endswith("SKILL.md")
    ]
    if memory:
        buckets["memory"] = memory

    return buckets


def phase2_route(buckets: dict[str, list[str]]) -> str:
    """Return which bucket Phase 2 should read from (highest count, tie-break non-hook)."""
    if not buckets:
        return ""
    scored = [(name, len(files)) for name, files in buckets.items()]
    hook_penalty = {"hooks": 1, "config": 0, "rules": 0, "skills": 0, "agents": 0, "memory": 0}
    scored.sort(key=lambda x: (-x[1], hook_penalty.get(x[0], 0)))
    return scored[0][0]


def pick_file_for_bucket(bucket_name: str, files: list[str]) -> str | None:
    """Pick the best file to read from a bucket."""
    generic = {"commit", "format", "review", "test", "debug", "plan"}
    if bucket_name == "skills":
        for f in files:
            dirname = os.path.basename(os.path.dirname(f)).lower()
            if dirname not in generic:
                return f
        return files[0] if files else None
    if bucket_name == "rules":
        return files[0] if files else None
    if bucket_name == "memory":
        md_files = [f for f in files if f.endswith(".md")]
        return md_files[0] if md_files else (files[0] if files else None)
    return files[0] if files else None


def check(condition: bool, msg: str):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


# ═══════════════════════════════════════════════════════════════
# TEST 1: Discovery finds new repos
# ═══════════════════════════════════════════════════════════════
def test_discovery():
    print("\nTest 1: Discovery effectiveness")
    print("-" * 50)

    known = load_ledger_repos()
    queries = [
        '"PreCompact" "SessionStart" path:.claude',
        '"updatedInput" "PostToolUse" filename:.py path:hooks',
        '"success criteria" "workflow" filename:SKILL.md',
    ]
    all_new: set[str] = set()
    used: set[str] = set()

    for i, q in enumerate(queries):
        check(q not in used, f"Query {i+1} is unique")
        used.add(q)
        encoded = urllib.parse.quote(q)
        data = gh_api(f"/search/code?q={encoded}&per_page=10", timeout=60)
        items = data.get("items", []) if isinstance(data, dict) else []
        repos = {item["repository"]["full_name"] for item in items if "repository" in item}
        new_repos = repos - known
        all_new.update(new_repos)
        check(len(repos) > 0, f"Query {i+1} returned {len(repos)} repos ({len(new_repos)} new)")

    check(len(all_new) > 0, f"At least 1 new repo across all queries ({len(all_new)} total)")


# ═══════════════════════════════════════════════════════════════
# TEST 2: Repos evaluated across all buckets
# ═══════════════════════════════════════════════════════════════
FIXTURES = [
    {"repo": "wasikarn/devflow", "min_score": 4, "hooks_should_win": False},
    {"repo": "aj-geddes/claude-code-bmad-skills", "min_score": 2, "hooks_should_win": False},
    {"repo": "LevNas/ccmemo", "min_score": 2, "hooks_should_win": True},  # hooks(4) > memory(0 after FP fix)
]


def test_bucket_coverage():
    print("\nTest 2: Bucket coverage")
    print("-" * 50)

    for fix in FIXTURES:
        repo = fix["repo"]
        buckets = phase1_tree_check(repo)
        score = len(buckets)

        check(score >= fix["min_score"], f"{repo} Phase 1 score {score}/6 (>= {fix['min_score']})")
        all_have = all(len(f) > 0 for f in buckets.values())
        check(all_have, f"{repo} all {score} scored buckets have file targets")

        routed = phase2_route(buckets)
        if fix["hooks_should_win"]:
            check(routed == "hooks", f"{repo} routes to hooks (correct — genuinely highest)")
        else:
            check(
                routed != "hooks",
                f"{repo} routes to '{routed}' ({len(buckets.get(routed, []))}), not hooks ({len(buckets.get('hooks', []))})",
            )


# ═══════════════════════════════════════════════════════════════
# TEST 3: Each bucket evaluated for transferable patterns
# ═══════════════════════════════════════════════════════════════
def test_bucket_depth():
    print("\nTest 3: Bucket evaluation depth")
    print("-" * 50)

    for fix in FIXTURES:
        repo = fix["repo"]
        buckets = phase1_tree_check(repo)

        for bname, files in buckets.items():
            target = pick_file_for_bucket(bname, files)
            if not target:
                check(False, f"{repo} {bname}: no file to read")
                continue

            # Verify file is from the RIGHT bucket directory
            if bname == "skills":
                check(target.endswith("SKILL.md"), f"{repo} skills reads SKILL.md not hook file")
            elif bname == "rules":
                check("rules/" in target and target.endswith(".md"), f"{repo} rules reads rules/*.md")
            elif bname == "memory":
                check(
                    any(x in target for x in ["memory/", "topics/"]) and not target.endswith("SKILL.md"),
                    f"{repo} memory reads memory/topics file (not SKILL.md in knowledge path)",
                )
            elif bname == "hooks":
                check("hooks/" in target, f"{repo} hooks reads hooks/* file")

            content = read_gh_file(repo, target)
            check(
                content is not None and len(content) > 10,
                f"{repo} {bname} readable ({len(content) if content else 0} chars)",
            )


# ═══════════════════════════════════════════════════════════════
# TEST 4: NEGATIVE — detect hook-only assessment
# ═══════════════════════════════════════════════════════════════
def test_negative_hook_bias():
    print("\nTest 4: Negative — detect hook-only assessment")
    print("-" * 50)

    # Simulate the OLD broken behavior: only read hooks from a multi-bucket repo
    repo = "wasikarn/devflow"
    buckets = phase1_tree_check(repo)
    non_hook_buckets = {k: v for k, v in buckets.items() if k != "hooks"}

    # If we only read hooks, we miss these buckets
    check(
        len(non_hook_buckets) >= 3,
        f"{repo} has {len(non_hook_buckets)} non-hook buckets that would be missed by hook-only assessment",
    )

    # Verify the routing algorithm DOES NOT pick hooks when better options exist
    routed = phase2_route(buckets)
    hooks_count = len(buckets.get("hooks", []))
    best_count = max(len(v) for v in buckets.values())
    check(
        routed != "hooks" or hooks_count == best_count,
        f"Routing picks '{routed}' ({len(buckets.get(routed, []))}) — hooks ({hooks_count}) is not falsely favored",
    )

    # Simulate hook-only reads and verify it would be INCOMPLETE
    hooks_only_coverage = 1  # only hooks bucket
    total_buckets = len(buckets)
    coverage_pct = hooks_only_coverage / total_buckets * 100
    check(
        coverage_pct < 50,
        f"Hook-only assessment covers {coverage_pct:.0f}% ({hooks_only_coverage}/{total_buckets}) — below 50% threshold (INCOMPLETE)",
    )

    # Verify that for a skills-heavy repo, a skill was actually picked
    skill_target = pick_file_for_bucket("skills", buckets.get("skills", []))
    check(
        skill_target is not None and skill_target.endswith("SKILL.md"),
        f"Skills bucket target is a SKILL.md: {os.path.basename(os.path.dirname(skill_target)) if skill_target else 'NONE'}",
    )

    # Verify agents bucket has a target
    agent_target = pick_file_for_bucket("agents", buckets.get("agents", []))
    check(
        agent_target is not None and "agents/" in (agent_target or ""),
        f"Agents bucket target is in agents/: {os.path.basename(agent_target) if agent_target else 'NONE'}",
    )


# ═══════════════════════════════════════════════════════════════
# TEST 5: NEGATIVE — memory bucket false positive detection
# ═══════════════════════════════════════════════════════════════
def test_negative_memory_fp():
    print("\nTest 5: Negative — memory bucket false positives")
    print("-" * 50)

    # ccmemo has skills with "knowledge" in path — old code counted these as memory
    repo = "LevNas/ccmemo"
    buckets = phase1_tree_check(repo)
    memory_files = buckets.get("memory", [])

    # Verify no SKILL.md files leaked into memory bucket
    skill_leaks = [f for f in memory_files if f.endswith("SKILL.md")]
    check(
        len(skill_leaks) == 0,
        f"{repo} memory bucket has 0 SKILL.md leaks (was {len(skill_leaks)})",
    )

    # Verify memory files are actually in memory/ or topics/ directories
    for f in memory_files:
        is_real = any(x in f for x in ["memory/", "topics/"])
        check(is_real, f"Memory file '{os.path.basename(f)}' is in memory/ or topics/ (not path-keyword false positive)")


# ═══════════════════════════════════════════════════════════════
# AUDIT MODE: Post-run verification
# ═══════════════════════════════════════════════════════════════
def audit_last_run():
    """Verify the most recent gather-repos run covered all buckets."""
    print("\nAUDIT: Post-run bucket coverage verification")
    print("=" * 60)

    if not LEDGER_PATH.exists():
        print(f"error: no ledger found at {LEDGER_PATH}", file=sys.stderr)
        print("hint: run /gather-repos to create the ledger before auditing", file=sys.stderr)
        sys.exit(2)

    text = LEDGER_PATH.read_text(encoding="utf-8")

    # Find the most recent Active Run
    active_match = re.search(r"### Run \d{4}-\d{2}-\d{2} \((\d+)(?:th|st|nd|rd)", text)
    if not active_match:
        print("error: no runs found in ledger (no '### Run YYYY-MM-DD (Nth ...' heading)", file=sys.stderr)
        print("hint: complete a /gather-repos run so the ledger has a Run Log entry to audit", file=sys.stderr)
        sys.exit(2)

    run_num = active_match.group(1)
    print(f"  Auditing run {run_num}")

    # Find all repos assessed in the most recent run
    # Look for entries with the same date as the latest run.
    # Verdict vocab is the UNION of:
    #   - gather-repos writers: inventoried, queued, auto-skip, dup, low-signal, qualified
    #   - evaluate-repos writers: adopted, upgraded, skip, bookmark, forked
    # Keep both groups in sync with SKILL.md "Ledger verdict vocabulary" table
    # and references/repo-assessment.md "Ledger Schema".
    latest_entries = re.findall(
        r"### \[(skip|adopted|upgraded|qualified|inventoried|queued|auto-skip|dup|low-signal|bookmark|forked)\] (\S+/\S+) \((\d{4}-\d{2}-\d{2})\)\n(.*?)(?=\n###|\Z)",
        text,
        re.DOTALL,
    )

    if not latest_entries:
        print("error: no assessed entries found in ledger", file=sys.stderr)
        print("hint: complete a /gather-repos run that writes '### [verdict] owner/repo (YYYY-MM-DD)' entries before auditing", file=sys.stderr)
        sys.exit(2)

    # Get entries from today (most recent run date)
    dates = [e[2] for e in latest_entries]
    latest_date = max(dates)
    recent = [(v, r, d, body) for v, r, d, body in latest_entries if d == latest_date]

    print(f"  Found {len(recent)} entries from {latest_date}")

    # Check each inventoried repo for bucket coverage
    for verdict, repo, date, body in recent:
        # Inventoried repos should have bucket information
        has_bucket_mention = any(
            b in body.lower()
            for b in ["hooks", "rules", "skills", "agents", "memory", "config", "bucket"]
        )

        if verdict == "inventoried":
            # This was inventoried — verify bucket information is present
            check(
                has_bucket_mention,
                f"{repo}: ledger entry mentions bucket information (score, per-bucket counts, or files read)",
            )
        else:
            print(f"  SKIP: {repo} (verdict: {verdict}, not an inventory entry)")

    # Check that the run log mentions bucket-neutral methodology
    run_section = text[text.index(active_match.group(0)):]
    has_bucket_neutral = (
        "bucket" in run_section.lower()
        or "skills" in run_section.lower()
        or "Phase 2" in run_section
    )
    check(has_bucket_neutral, "Run log mentions bucket-based methodology")


# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if "--audit" in sys.argv:
        audit_last_run()
    else:
        print("=" * 60)
        print("  /gather-repos Regression Test Suite")
        print("=" * 60)

        test_discovery()
        test_bucket_coverage()
        test_bucket_depth()
        test_negative_hook_bias()
        test_negative_memory_fp()

        print("\n" + "=" * 60)
        total = passed + failed
        print(f"  {passed}/{total} passed, {failed} failed")
        print("=" * 60)

    sys.exit(1 if failed > 0 else 0)
