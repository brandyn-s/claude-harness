"""
Classify rules by defense layer.
Reads rules/*.md and settings.json to determine enforcement status.

Hook classification uses two signals:
  1. The hook's wiring in settings.json (PreToolUse vs PostToolUse).
  2. The hook's SOURCE — whether it can emit a block decision
     (`decision: "block"`, `sys.exit(2)`, etc).
A PostToolUse hook that emits `decision: "block"` is hook-enforced, not warned.
This corrects the prior heuristic that conflated event type with strength.

Usage:
  classify_rules.py                # table
  classify_rules.py --json
  classify_rules.py --rule <name>  # focus one rule
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')


def _resolve_config_root():
    """Find the config root (the directory containing skills/, hooks/, rules/).

    The script lives at <root>/skills/audit-rules/references/classify_rules.py
    in both ~/.claude/ installs and repo checkouts. Walk three parents up to
    locate <root>, then validate the layout. Fall back to ~/.claude/ if the
    derived root is missing expected subdirectories — useful when the script
    is symlinked.

    Set AUDIT_RULES_CONFIG_ROOT to override for isolated testing.
    """
    override = os.environ.get("AUDIT_RULES_CONFIG_ROOT")
    if override:
        return Path(override)
    derived = Path(__file__).resolve().parents[3]
    if (derived / "rules").is_dir() or (derived / "hooks").is_dir():
        return derived
    fallback = Path(os.path.expanduser("~/.claude"))
    return fallback


CONFIG_ROOT = _resolve_config_root()
RULES_DIR = str(CONFIG_ROOT / "rules")
HOOKS_DIR = str(CONFIG_ROOT / "hooks")
SKILLS_DIR = str(CONFIG_ROOT / "skills")
# Prefer the settings.json that lives next to the hooks we're classifying —
# they're a pair. Only fall back to ~/.claude/settings.json if the config
# root doesn't have its own (e.g., a partial checkout).
_repo_settings = CONFIG_ROOT / "settings.json"
if _repo_settings.is_file():
    SETTINGS_PATH = str(_repo_settings)
else:
    SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")


def _load_demotions():
    """Load AUDIT-TRACKERS/demotions.yaml if present.

    Tiny home-grown loader (no PyYAML dep, matching _load_suppressions in
    scan_violations.py). Returns a list of entry dicts; a missing file or
    empty list returns []. Malformed entries (missing scanner_rule, hook,
    date, or rationale) are dropped.
    """
    path = CONFIG_ROOT / "AUDIT-TRACKERS" / "demotions.yaml"
    if not path.is_file():
        return []
    entries = []
    current = None
    in_list = False
    fields = ("scanner_rule", "classifier_rule", "hook", "scope",
              "date", "pr", "rationale")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("demotions:", "demotions: []"):
            in_list = True
            continue
        if not in_list:
            continue
        if stripped.startswith("- "):
            if current is not None:
                entries.append(current)
            current = {}
            stripped = stripped[2:]
        m = re.match(r'^([a-zA-Z_]+):\s*(.*)$', stripped)
        if m and current is not None:
            k, v = m.group(1), m.group(2).strip().strip('"').strip("'")
            if k in fields:
                current[k] = v
    if current is not None:
        entries.append(current)
    return [
        e for e in entries
        if e.get("scanner_rule") and e.get("hook")
        and e.get("date") and e.get("rationale")
    ]


def _demotion_effective(entry, platform=None):
    """Is this demotion in effect on the given platform?

    Supported scopes: "all" (demoted everywhere) and "non-win32" (block
    retained on Windows, demoted elsewhere). An unrecognized scope returns
    False — the entry still appears in the JSON `demotions` list so the
    operator can see it, but it never silently reclassifies a layer.
    """
    plat = platform if platform is not None else sys.platform
    scope = entry.get("scope", "all")
    if scope == "all":
        return True
    if scope == "non-win32":
        return plat != "win32"
    return False


_BLOCK_SIGNAL = re.compile(
    r'"decision"\s*:\s*"block"'           # JSON block emission
    r'|sys\.exit\(\s*2\s*\)'               # PreToolUse exit-2 block
    r'|"permissionDecision"\s*:\s*"deny"'  # permissionDecision API
)
_WARN_SIGNAL = re.compile(r'"decision"\s*:\s*"warn"')

# A "rule" for total_rule_lines counting purposes is one independently-
# nameable behavioral unit within a rules/*.md file. Two conventions are
# in use across the corpus:
#   1. Legacy markdown: a bold bullet or numbered item ("- **Do X**").
#   2. DSL/constitutional (the current majority, per rule-authoring.md):
#      a top-level INVARIANT, GUARD, or FAILURE block.
# Prior to this fix, only (1) was recognized — a file written entirely in
# DSL form (INVARIANT/GUARD/FAILURE, no bold bullets) counted as having
# ZERO rules, undercounting total_rule_lines and therefore understating
# prompt_only_estimated (a residual: total - enforced - warned - skill).
# Deliberately NOT counted as separate rules: PROCEDURE headers and
# STEP_N lines. A PROCEDURE describes HOW to apply the INVARIANTs/GUARDs
# already declared in the same file — counting it too would double-count
# the same behavioral constraint once declaratively (INVARIANT) and once
# operationally (PROCEDURE). STEP_N lines are sub-parts of one procedure,
# not separate rules, the same way a bullet's sub-bullets aren't separate
# bold-bulleted rules under convention (1).
_RULE_UNIT = re.compile(
    r'^[-*]\s+\*\*'          # legacy: "- **bold rule**"
    r'|^\d+\.\s+\*\*'        # legacy: "1. **bold rule**"
    r'|^INVARIANT\b'         # DSL: INVARIANT <name>
    r'|^GUARD\s+pattern='    # DSL: GUARD pattern="...":
    r'|^FAILURE\s+\S+:'      # DSL: FAILURE <name>:
)


def hook_strength(script_name):
    """Return ('enforced', 'warned', 'unknown') by reading the hook source.

    A hook emitting `decision: "block"`, `sys.exit(2)`, or
    `permissionDecision: "deny"` is enforced. A hook that ONLY emits
    `decision: "warn"` is warned. Missing or unreadable hooks are 'unknown'.
    """
    if script_name == "permissions.deny":
        return "enforced"
    path = os.path.join(HOOKS_DIR, script_name)
    if not os.path.isfile(path):
        return "unknown"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return "unknown"
    if _BLOCK_SIGNAL.search(src):
        return "enforced"
    if _WARN_SIGNAL.search(src):
        return "warned"
    return "warned"


def validate_hook_map(hook_map):
    """Warn on entries in HOOK_RULE_MAP that reference non-existent hooks."""
    stale = []
    for script in hook_map:
        if script == "permissions.deny":
            continue
        if not os.path.isfile(os.path.join(HOOKS_DIR, script)):
            stale.append(script)
    if stale:
        print(f"WARN: HOOK_RULE_MAP references {len(stale)} hook(s) not on disk:",
              file=sys.stderr)
        for s in stale:
            print(f"  - {s}", file=sys.stderr)
        print(f"  HOOKS_DIR resolved to {HOOKS_DIR}", file=sys.stderr)
        print("  Update HOOK_RULE_MAP in classify_rules.py.", file=sys.stderr)
    return stale


def discover_uncovered_hooks(hook_map):
    """List on-disk hooks that have block/warn signals but no curated rule.

    A coverage signal — the curated map represents a subset of total enforcement.
    Excludes UTILITY_MODULES, which contain block/warn signal strings to help
    other hooks emit decisions but are not themselves wired hook entry points.
    """
    if not os.path.isdir(HOOKS_DIR):
        return []
    uncovered = []
    for path in sorted(glob.glob(os.path.join(HOOKS_DIR, "*.py"))):
        name = os.path.basename(path)
        if name in hook_map or name in UTILITY_MODULES:
            continue
        strength = hook_strength(name)
        if strength in ("enforced", "warned"):
            uncovered.append((name, strength))
    return uncovered


def load_hook_config():
    """Extract referenced hook scripts from settings.json.

    Used only to know which hooks are wired in at all. Strength (enforce/warn)
    is determined from the hook source via hook_strength().
    """
    wired = set()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"wired": wired, "permissions_deny": False}

    hook_events = settings.get("hooks", {})
    # Hook commands take two shapes:
    #   "python /path/to/hooks/foo.py ..."          → direct invocation
    #   "$HOME/.claude/hooks/run-hook foo.py ..."   → dispatcher (this repo)
    # Capture every .py token in the command and keep only basenames that
    # exist in HOOKS_DIR.
    py_token = re.compile(r'(?:^|[\s"\'\\/])([A-Za-z0-9_-]+\.py)(?:[\s"\'?]|$)')
    for event_type, entries in hook_events.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                for match in py_token.findall(cmd):
                    if match == "run-hook.py":
                        continue
                    wired.add(match)

    perms = settings.get("permissions", {})
    return {"wired": wired, "permissions_deny": bool(perms.get("deny"))}


# Utility modules in hooks/ that import shared code but are NOT themselves
# wired as hooks. The classifier finds enforcement-signal regex hits in
# their source (because they help other hooks emit decisions), but they
# aren't entry points and shouldn't appear in the "uncurated hooks"
# warning list. Verified 2026-05-26 — these files contain no `def main()`
# or `if __name__ == "__main__"` block.
UTILITY_MODULES = {
    "atomic_write.py",
    "hook_input.py",
    "manifest_metrics.py",
}

# Curated rule→hook map. Updated 2026-05-23: strength is no longer encoded
# here — call hook_strength() on the script to derive it from source.
# 2026-05-26 sweep: added 41 previously-uncurated entry-point hooks so the
# defense-layer classifier reports a complete picture (no more "44 uncurated"
# warning in audit-rules output).
HOOK_RULE_MAP = {
    "bash-security-guard.py": [
        "Never write to example-technologies",
        "Block settings.json staging warning",
        # Added 2026-06-12 audit-rules wave: these three checks existed in
        # the hook but were absent from this map, so the joined report
        # mislabeled their rules prompt-only/skill-enforced and recommended
        # promotions for already-hook-enforced rules.
        "Block git commit on main/master in protected repos (commit-guard)",
        "Block complex inline python -c >300 chars (inline-python-guard)",
        "Block inline/heredoc python open() missing encoding= (encoding guards)",
    ],
    "search-path-guard.py": [
        "Block glob/grep outside project scope",
    ],
    "prompt-secret-scan.py": [
        "Scan prompts for secrets",
    ],
    "tavily-search-cap.py": [
        "Cap tavily_search max_results",
    ],
    "memory-write-guard.py": [
        "Prevent concurrent memory index corruption",
    ],
    "loop-detector.py": [
        "Detect and break infinite loops",
    ],
    "result-injection-guard.py": [
        "Scan MCP results for injection",
    ],
    "post-merge-sync.py": [
        "Post-merge branch sync",
    ],
    "pdf-to-text.py": [
        "Convert PDF Read to text",
    ],
    "post-write-edit.py": [
        "Block Python scripts missing encoding='utf-8' in open()",
        "Syntax check .py files",
        "Scan for secret patterns in files",
        "Warn on str.replace('\\n') near file reads (CRLF risk)",
    ],
    "permissions.deny": [
        "Block writes to .env/.aws/.ssh",
        "Block WebFetch/WebSearch",
    ],
    # 2026-05-26 additions — previously uncurated entry-point hooks.
    "assessment-class-detector.py": [
        "Inject symmetric-evidentiary-burden + /interview for assessment prompts",
    ],
    "auto-topic-loader.py": [
        "Auto-load topic and rule context when MCP tools are called",
    ],
    "bash-error-classifier.py": [
        "Classify bash errors and suggest specific fixes",
    ],
    "bash-security-audit.py": [
        "Log every Bash security decision to JSONL",
    ],
    "bash-tail-buffering-guard.py": [
        "Block long-running Bash piped to filtering tools (tail/head)",
    ],
    "block-partial-read.py": [
        "Block partial Reads of protected config files",
    ],
    "cklb-to-md.py": [
        "Auto-convert .cklb STIG checklist to Markdown on Read",
    ],
    "config-guard.py": [
        "Block disabling/removing hooks in settings.json",
    ],
    "context-monitor.py": [
        "Warn at 60/80/90% context-window usage",
    ],
    "creative-output-grounding-check.py": [
        "Check creative-skill outputs for grounding signals",
    ],
    "destructive-ops-guard.py": [
        "Block destructive Bash/PowerShell patterns",
    ],
    "git-empty-push-guard.py": [
        "Block git push of 0-commits-ahead branches",
    ],
    "config-change-validate.py": [
        "Validate ConfigChange settings preserve required runtime controls",
    ],
    "mcp-output-trimmer.py": [
        "Trim large MCP tool responses to reduce context use",
    ],
    "nessus-to-md.py": [
        "Auto-convert .nessus Tenable XML to Markdown on Read",
    ],
    "post-failure-guide.py": [
        "Emit diagnostic guidance on tool-call failures",
    ],
    "pre-agent-dispatch.py": [
        "Warn when dispatching workers needing remote MCPs",
    ],
    "precompact-checkpoint.py": [
        "Save structured context state before compaction",
    ],
    "promise-checker.py": [
        "Catch performative compliance + banned session-closure phrases",
    ],
    "query-routing-log.py": [
        "Log code-search/code-graph/memory-search calls for routing analysis",
    ],
    "rule-size-guard.py": [
        "Refuse writes pushing rules/*.md past the ambient-load budget",
    ],
    "security-write-confirm.py": [
        "Require user confirmation before security write operations",
    ],
    "session-start.py": [
        "Consolidated SessionStart: env-loader, auto-prune, repo sync, MCP zombie cleanup",
    ],
    "session-end.py": [
        "Record a bounded SessionEnd receipt for offline lifecycle enrichment",
    ],
    "skill-alias.py": [
        "Map common skill-name misspellings to canonical names",
    ],
    "skill-ref-validator.py": [
        "Warn on dead hook/script refs in SKILL.md",
    ],
    "skill-routing-hint.py": [
        "Suggest skill/agent routing on user prompt",
    ],
    "stop-failure-handler.py": [
        "Log API failures and print recovery guidance",
    ],
    "subagent-start-context.py": [
        "Inject topic-file content into worker agents",
    ],
    "subagent-stop.py": [
        "Surface agent work and capture learnings",
    ],
    "sync-repo.py": [
        "Sync architecture files to GitHub backup repo",
    ],
    "task-completed.py": [
        "Verify task results before marking complete",
    ],
    "tavily-research-poll.py": [
        "Poll tavily_research async results",
    ],
    "teammate-idle.py": [
        "Quality gate when Agent Teams teammate finishes work",
    ],
    "toolsearch-intercept.py": [
        "Intercept vague keyword ToolSearch queries",
    ],
    "verify-before-assuming.py": [
        "Detect 'unavailable' claims without prior verification",
    ],
    "worktree-enforcement.py": [
        "Enforce worktree isolation for subagent writes to protected repos",
    ],
    "write-edit-dispatcher.py": [
        "Dispatcher running four Write/Edit guards in one process",
    ],
    "xlsx-to-md.py": [
        "Auto-convert .xlsx workbooks to Markdown on Read",
    ],
}

# Rules embedded as explicit steps in skills. Discovered by scanning SKILL.md
# files for the markers below. Keep the marker → rule mapping explicit so the
# audit output names rules consistently across runs.
SKILL_STEP_MARKERS = {
    r"git\s+branch\s+--show-current": "Check branch before commit",
    r"\bsecurity[- ]review\b": "Run security review before PR",
    r"memory_search.*?(prior|behavior|change)": "Search memory before changing behavior",
    r"\bvalidate-changes\b|consistency validator": "Run consistency validator before PR",
    r"\bload\b.*\b(topic|kb)\b.*\bcontext\b|topic files? and KB": "Load topic files and KB context before planning",
    r"encoding\s*=\s*['\"]utf-8": "Use encoding='utf-8' when opening files",
    r"sys\.stdout\.reconfigure": "Reconfigure stdout encoding for Python scripts",
    r"diagnose[- ]before[- ]fix": "Diagnose before fix",
    r"verify[- ]effectiveness|two[- ]part validation": "Verify effectiveness (two-part validation)",
}


def discover_skill_rules():
    """Scan every skills/*/SKILL.md for embedded-rule markers."""
    if not os.path.isdir(SKILLS_DIR):
        return {}
    skill_map = {}
    for skill_dir in sorted(os.listdir(SKILLS_DIR)):
        skill_md = os.path.join(SKILLS_DIR, skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        for pattern, rule_name in SKILL_STEP_MARKERS.items():
            if re.search(pattern, content, re.IGNORECASE):
                skill_map.setdefault(skill_dir, []).append(rule_name)
    return skill_map


def classify_rules():
    """Classify rules using curated map + auto-detected skill embeddings.

    Consults AUDIT-TRACKERS/demotions.yaml: a rule whose demotion is
    effective on this platform is reported hook-warned, not hook-enforced,
    even though the hook source still carries a (platform-gated) block
    signal. Without this, a deliberate demotion reads as a broken block —
    the 2026-08-22 audit misdiagnosis this ledger exists to prevent.
    """
    rules = []
    hook_config = load_hook_config()
    wired_scripts = hook_config["wired"]
    demotions = _load_demotions()
    # (hook, classifier_rule) -> ledger entry, for effective demotions only.
    demoted = {
        (d.get("hook"), d.get("classifier_rule")): d
        for d in demotions
        if _demotion_effective(d) and d.get("classifier_rule")
    }

    for script, rule_list in HOOK_RULE_MAP.items():
        if script == "permissions.deny":
            layer = "hook-enforced" if hook_config["permissions_deny"] else "hook-warned"
        else:
            layer = f"hook-{hook_strength(script)}" if script in wired_scripts \
                    else f"hook-{hook_strength(script)} (unwired)"
        for rule in rule_list:
            entry = {
                "rule": rule,
                "source": script,
                "layer": layer,
                "hook_or_skill": script,
            }
            demotion = demoted.get((script, rule))
            if demotion and layer.startswith("hook-enforced"):
                entry["layer"] = (
                    f"hook-warned (demoted {demotion['date']}, "
                    f"see AUDIT-TRACKERS/demotions.yaml)"
                )
                entry["demotion"] = demotion
            rules.append(entry)

    skill_map = discover_skill_rules()
    for skill, rule_list in sorted(skill_map.items()):
        for rule in rule_list:
            rules.append({
                "rule": rule,
                "source": f"skills/{skill}",
                "layer": "skill-enforced",
                "hook_or_skill": skill,
            })

    total_rule_lines = 0
    if os.path.isdir(RULES_DIR):
        for rule_file in sorted(glob.glob(os.path.join(RULES_DIR, "*.md"))):
            try:
                with open(rule_file, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if _RULE_UNIT.match(line):
                            total_rule_lines += 1
            except OSError:
                continue

    enforced_count = sum(1 for r in rules if r["layer"].startswith("hook-enforced"))
    warned_count = sum(1 for r in rules if r["layer"].startswith("hook-warned"))
    skill_count = sum(1 for r in rules if r["layer"] == "skill-enforced")
    prompt_only_est = max(0, total_rule_lines - enforced_count - warned_count - skill_count)

    return rules, {
        "total_rule_lines": total_rule_lines,
        "hook_enforced": enforced_count,
        "hook_warned": warned_count,
        "skill_enforced": skill_count,
        "prompt_only_estimated": prompt_only_est,
        "config_root": str(CONFIG_ROOT),
        "settings_path": SETTINGS_PATH,
    }


def main():
    parser = argparse.ArgumentParser(description="Classify rules by defense layer")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--rule", help="Filter to entries whose rule name contains this string")
    args = parser.parse_args()

    validate_hook_map(HOOK_RULE_MAP)
    # Stale-ledger guard: a demotion entry naming a hook that no longer
    # exists means the ledger drifted from the hooks/ tree.
    for d in _load_demotions():
        if not os.path.isfile(os.path.join(HOOKS_DIR, d.get("hook", ""))):
            print(
                f"WARN: AUDIT-TRACKERS/demotions.yaml references missing hook "
                f"{d.get('hook')!r} (rule {d.get('scanner_rule')!r})",
                file=sys.stderr,
            )
    uncovered = discover_uncovered_hooks(HOOK_RULE_MAP)
    rules, summary = classify_rules()

    if args.rule:
        needle = args.rule.lower()
        rules = [r for r in rules if needle in r["rule"].lower()]

    if args.json:
        demotions = [
            {**d, "effective_here": _demotion_effective(d)}
            for d in _load_demotions()
        ]
        print(json.dumps({
            "rules": rules,
            "summary": summary,
            "uncovered_hooks": [{"hook": h, "strength": s} for h, s in uncovered],
            "demotions": demotions,
            "platform": sys.platform,
        }, indent=2))
        return

    print(f"Config root: {summary['config_root']}")
    print(f"Settings: {summary['settings_path']}")
    print(f"Rule files scanned: {len(glob.glob(os.path.join(RULES_DIR, '*.md')))}")
    print(f"Total rule-like lines found: {summary['total_rule_lines']}")
    print("\nDefense Layer Distribution:")
    for layer, key in [
        ("hook-enforced", "hook_enforced"),
        ("hook-warned", "hook_warned"),
        ("skill-enforced", "skill_enforced"),
        ("prompt-only (est.)", "prompt_only_estimated"),
    ]:
        print(f"  {layer:<24s} {summary[key]:4d}")

    if uncovered:
        print(f"\nUncurated hooks with enforcement signals ({len(uncovered)}):")
        for name, strength in uncovered:
            print(f"  {name:<40s} hook-{strength}")
        print("  → Consider adding these to HOOK_RULE_MAP for full coverage.")

    print("\nEnforced/Warned Rules:")
    print(f"  {'Rule':<55s} {'Layer':<22s} {'By':<30s}")
    print("  " + "-" * 109)
    for r in rules:
        print(f"  {r['rule']:<55s} {r['layer']:<22s} {r['hook_or_skill']:<30s}")


if __name__ == "__main__":
    main()
