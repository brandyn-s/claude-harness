"""Consistency checks for SessionStart."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from _environment_catalog import load_section

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

CLAUDE_DIR = Path.home() / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"
AGENTS_DIR = CLAUDE_DIR / "agents"
SKILLS_DIR = CLAUDE_DIR / "skills"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
MCP_JSON = Path.home() / ".mcp.json"
CLAUDE_JSON = Path.home() / ".claude.json"


def _resolve_project_dir() -> Path:
    """Resolve the per-project Claude Code directory at runtime.

    Encodes cwd → slashes/colons replaced with dashes, the way Claude
    Code names project subdirs under ~/.claude/projects. Falls back to
    the most recently modified projects/ subdir if the encoding doesn't
    match a real path (e.g., when running from an unexpected cwd).
    """
    if env_dir := os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(env_dir)
    projects = CLAUDE_DIR / "projects"
    encoded = str(Path.cwd().resolve()).replace("/", "-").replace(":", "-").strip("-")
    candidate = projects / encoded
    if candidate.exists():
        return candidate
    if projects.exists():
        subdirs = [p for p in projects.iterdir() if p.is_dir()]
        if subdirs:
            return max(subdirs, key=lambda p: p.stat().st_mtime)
    return projects / "_unresolved"


PROJECT_DIR = _resolve_project_dir()
PROJECT_MEMORY = PROJECT_DIR / "memory"
IGNORED_STUBS = {"nixos-patterns.md"}


def _startupinfo():
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si

def get_all_server_names():
    servers = set()
    if MCP_JSON.exists():
        try:
            with open(MCP_JSON, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for name in cfg.get("mcpServers", {}):
                servers.add(name)
        except Exception:
            pass
    if CLAUDE_JSON.exists():
        try:
            with open(CLAUDE_JSON, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for name in cfg.get("mcpServers", {}):
                servers.add(name)
            for _proj_key, proj_val in cfg.get("projects", {}).items():
                if isinstance(proj_val, dict):
                    for name in proj_val.get("mcpServers", {}):
                        servers.add(name)
        except Exception:
            pass
    return servers



def server_to_prefix(server_name):
    return f"mcp__{server_name.replace('.', '_')}__"



def get_agent_files():
    if not AGENTS_DIR.exists():
        return []
    return [
        f for f in AGENTS_DIR.glob("*.md") if f.name not in ("TEMPLATE.md", "README.md")
    ]



# Built-in (non-MCP) tools that are legitimate `disallowedTools` entries. A
# denial of any of these must NOT be reported as a phantom MCP prefix.
#
# The prior list held only {Write, Edit, NotebookEdit}, so a correct
# `disallowedTools: [Agent]` — the documented way to stop an agent from
# dispatching subagents, per agents/README.md and agents/TEMPLATE.md — was
# reported CRITICAL. Keep this in sync with the tool names the harness exposes.
BUILTIN_TOOLS = {
    "Agent", "Task", "Bash", "BashOutput", "Edit", "Glob", "Grep", "KillShell",
    "NotebookEdit", "Read", "SlashCommand", "Skill", "TodoWrite", "Write",
    "WebFetch", "WebSearch", "AskUserQuestion", "ExitPlanMode", "EnterPlanMode",
    "ToolSearch", "Workflow", "SendMessage", "ListMcpResourcesTool",
    "ReadMcpResourceTool", "LSP", "Artifact",
}


def extract_denied_prefixes(agent_path):
    """Return the tool patterns an agent denies via `disallowedTools`.

    Handles BOTH YAML shapes, because agents legitimately use either:

        disallowedTools: [Agent, Write]   # inline flow
        disallowedTools:                  # block sequence
          - Agent

    The prior implementation was `re.search(r"disallowedTools:\\s*(.+)")`, which
    on the block form skipped the empty remainder of the key's own line and
    matched the NEXT line, capturing the literal `"- Agent"` — leading dash
    included. That never equals any MCP prefix, so `worker.md` (the only agent
    using block style) drew a permanent CRITICAL that no correct configuration
    could clear. Verified live on 2026-07-29: the capture was exactly '- Agent'.
    """
    try:
        with open(agent_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    # Inline flow form: value is on the same line as the key. `[^\S\n]*` matches
    # spaces/tabs but NOT a newline, so an empty value cannot bleed to line 2.
    inline = re.search(r"^disallowedTools:[^\S\n]*(\S.*)$", content, re.MULTILINE)
    if inline:
        raw = inline.group(1).strip().strip("[]")
        return [p.strip().strip("\"'") for p in raw.split(",") if p.strip()]

    # Block sequence form: collect the `- item` lines that follow the key.
    block = re.search(
        r"^disallowedTools:[^\S\n]*\n((?:[^\S\n]+-[^\S\n]*.+\n?)+)",
        content,
        re.MULTILINE,
    )
    if not block:
        return []
    items = re.findall(r"^[^\S\n]+-[^\S\n]*(.+)$", block.group(1), re.MULTILINE)
    return [i.strip().strip("\"'") for i in items if i.strip()]



def check_1_agent_denylists():
    findings = []
    servers = get_all_server_names()
    valid_prefixes = {server_to_prefix(s) for s in servers}
    for agent_file in get_agent_files():
        denied = extract_denied_prefixes(agent_file)
        for pattern in denied:
            if pattern in BUILTIN_TOOLS:
                continue
            prefix = pattern.rstrip("*")
            if not any(prefix == vp for vp in valid_prefixes):
                findings.append(
                    f"[CRITICAL] {agent_file.name}: denies '{pattern}' but no server with prefix '{prefix}' exists"
                )
    return findings



def check_4_stub_topic_files():
    findings = []
    if not PROJECT_MEMORY.exists():
        return []
    for pattern_file in PROJECT_MEMORY.glob("*-patterns.md"):
        if pattern_file.name in IGNORED_STUBS:
            continue
        try:
            with open(pattern_file, "r", encoding="utf-8") as f:
                content = f.read()
            if "not yet documented" in content.lower():
                findings.append(
                    f"[MEDIUM] {pattern_file.name} is a stub (contains 'not yet documented')"
                )
        except Exception:
            pass
    return findings



def check_5_memory_bounds():
    findings = []
    MAX_LINES = 50
    agent_memory_dir = CLAUDE_DIR / "agent-memory"
    if not agent_memory_dir.exists():
        return []
    for agent_dir in agent_memory_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        memory_file = agent_dir / "MEMORY.md"
        if memory_file.exists():
            try:
                with open(memory_file, "r", encoding="utf-8") as f:
                    line_count = sum(1 for _ in f)
                if line_count > MAX_LINES:
                    findings.append(
                        f"[MEDIUM] {agent_dir.name}/MEMORY.md has {line_count} lines (max {MAX_LINES})"
                    )
            except Exception:
                pass
    return findings



def check_7_no_dead_pipeline():
    findings = []
    dead_files = [
        CLAUDE_DIR / "session-metrics.jsonl",
        CLAUDE_DIR / "pending-curation.json",
        HOOKS_DIR / "session-end.py",
    ]
    for f in dead_files:
        if f.exists():
            findings.append(
                f"[LOW] Dead pipeline artifact exists: {f.name} — delete it"
            )
    return findings



def check_8_memory_staleness():
    findings = []
    agent_memory_dir = CLAUDE_DIR / "agent-memory"
    if not agent_memory_dir.exists():
        return []
    today = datetime.now().date()
    operational_stale = 30
    operational_archive = 90
    for agent_dir in agent_memory_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        memory_file = agent_dir / "MEMORY.md"
        if not memory_file.exists():
            continue
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                content = f.read()
            for match in re.finditer(
                r"###\s+\[observed\](.*?)\((\d{4}-\d{2}-\d{2})\)", content
            ):
                entry_middle = match.group(1).lower()
                date_str = match.group(2)
                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    age_days = (today - entry_date).days
                    entry_title = match.group(0).strip()[:80]
                    if "tool-gotcha" in entry_middle:
                        continue
                    if age_days >= operational_archive:
                        findings.append(
                            f"[MEDIUM] {agent_dir.name}: stale entry ({age_days}d, archive candidate): {entry_title}"
                        )
                    elif age_days >= operational_stale:
                        findings.append(
                            f"[LOW] {agent_dir.name}: aging entry ({age_days}d): {entry_title}"
                        )
                except ValueError:
                    pass
        except Exception:
            pass
    return findings



def check_10_stale_component_references():
    """Grep all skills for references to agents/directories that no longer exist."""
    findings = []
    # Known current agents
    current_agents = set()
    if AGENTS_DIR.exists():
        for f in AGENTS_DIR.iterdir():
            if f.suffix == ".md" and f.name not in ("TEMPLATE.md", "README.md"):
                current_agents.add(f.stem)

    # Known current agent-memory directories
    agent_memory_dir = CLAUDE_DIR / "agent-memory"
    current_memory_dirs = set()
    if agent_memory_dir.exists():
        for d in agent_memory_dir.iterdir():
            if d.is_dir():
                current_memory_dirs.add(d.name)

    # Old agent names that were retired in the topic-indexed redesign
    retired_agents = {
        "security-ops",
        "finance-ops",
        "recruiting-ops",
        "project-ops",
        "runbook-dev",
    }

    # Scan all skill files for references to retired agents
    if SKILLS_DIR.exists():
        for skill_dir in SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    text = f.read()
                for old_agent in retired_agents:
                    # Match as path component or standalone reference, but not in
                    # "legacy" or "remnant" context (those are intentional references)
                    pattern = rf"(?<!legacy )(?<!remnant ){re.escape(old_agent)}(?:/MEMORY|\.md|\b)"
                    if re.search(pattern, text):
                        # Double check it's not in a "detect legacy" context
                        lines = [l for l in text.split("\n") if old_agent in l]
                        stale_lines = [
                            l
                            for l in lines
                            if "legacy" not in l.lower() and "remnant" not in l.lower()
                        ]
                        if stale_lines:
                            findings.append(
                                f"[MEDIUM] skills/{skill_dir.name}/SKILL.md references retired agent '{old_agent}'"
                            )
            except Exception:
                pass
    return findings



def check_11_memory_md_overflow():
    """Check that project MEMORY.md doesn't exceed 200-line cap."""
    findings = []
    memory_file = PROJECT_MEMORY / "MEMORY.md"
    if memory_file.exists():
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            if line_count > 200:
                findings.append(
                    f"[HIGH] MEMORY.md has {line_count} lines (cap: 200). "
                    f"Content beyond line 200 is truncated at load time. "
                    f"Move detailed content to topic files or pattern files."
                )
        except Exception:
            pass
    return findings



def check_13_untrusted_repo_config():
    """CVE mitigation: Warn if CWD has .claude/ dir from a non-Example repo.

    CVE-2025-59536 and CVE-2026-21852 exploit malicious hooks and settings
    in cloned repos. This check warns when working in a repo that has its
    own .claude/ directory that isn't from a known-safe Example org repo.
    """
    findings = []
    cwd = Path.cwd()
    local_claude_dir = cwd / ".claude"

    # Skip if no .claude/ in CWD
    if not local_claude_dir.is_dir():
        return findings

    # Skip if CWD is the home directory (our own config)
    if cwd == Path.home():
        return findings

    # Check if this is a Example repo (safe)
    safe_orgs = {"example-org", "you-s"}
    is_protected_org = False
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd),
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
        )
        if result.returncode == 0:
            origin = result.stdout.strip()
            for org in safe_orgs:
                if org.lower() in origin.lower():
                    is_protected_org = True
                    break
    except Exception:
        pass

    if not is_protected_org:
        # Check for potentially dangerous files
        dangerous = []
        settings_file = local_claude_dir / "settings.json"
        if settings_file.exists():
            dangerous.append("settings.json (may override env vars)")
        hooks_dir = local_claude_dir / "hooks"
        if hooks_dir.is_dir():
            hook_count = len(list(hooks_dir.glob("*")))
            if hook_count > 0:
                dangerous.append(f"hooks/ ({hook_count} files - may execute code)")
        if dangerous:
            findings.append(
                f"[HIGH] UNTRUSTED REPO CONFIG: CWD has .claude/ with: "
                f"{', '.join(dangerous)}. "
                "This is a potential CVE-2025-59536/CVE-2026-21852 vector. "
                "Review these files before proceeding."
            )
        else:
            findings.append(
                "[MEDIUM] UNTRUSTED REPO CONFIG: CWD has .claude/ directory "
                "from a non-Example repo. Verify contents are safe."
            )
    return findings



# The MCP servers this environment expects to see configured (global and
# project mcpServers in .claude.json plus .mcp.json): the `expected_servers`
# section of the environment catalog (hooks/_environment_catalog.py). An
# empty list disables the never-configured summary below; the per-machine
# disappeared-server CRITICAL needs no list at all.
EXPECTED_MCP_SERVERS = {
    name for name in load_section("expected_servers")
    if isinstance(name, str) and name.strip()
}



MCP_BASELINE_PATH = Path.home() / ".claude" / ".mcp-server-baseline.json"

# Last-reported never-configured set (banner-noise gate, 2026-07-05): the
# LOW "N expected servers never configured" line fired identically every
# session since the macOS migration. Report only when the SET changes.
NEVER_CONFIGURED_STATE = Path.home() / ".claude" / ".last-never-configured-mcp-report.json"


def check_14_mcp_server_inventory():
    """Detect MCP servers that DISAPPEARED from this machine's config.

    Redesigned 2026-06-11 (mac-port session-start triage): the old check
    diffed the configured set against one global EXPECTED list, which on a
    freshly-provisioned machine screamed a 29-server CRITICAL every session
    for the entire migration. Now a per-machine TOFU baseline
    (~/.claude/.mcp-server-baseline.json) records every server ever seen
    configured HERE:

      - in baseline but no longer configured -> CRITICAL (it existed on
        this machine and vanished — the actual inadvertent-deletion signal)
      - in the global EXPECTED set but never seen here -> one LOW summary
        line (informational: new machine / in-progress migration)

    Removing a server ON PURPOSE: delete its entry from the baseline file
    (the finding says so).
    """
    findings = []
    configured = get_all_server_names()

    baseline = {}
    try:
        baseline = json.loads(MCP_BASELINE_PATH.read_text(encoding="utf-8"))
        if not isinstance(baseline, dict):
            baseline = {}
    except (OSError, ValueError):
        baseline = {}

    disappeared = sorted(set(baseline) - configured)
    if disappeared:
        findings.append(
            f"[CRITICAL] MCP servers disappeared from this machine's config: "
            f"{', '.join(disappeared)}. Each was previously configured here "
            f"(first seen per {MCP_BASELINE_PATH.name}). Check .claude.json "
            f"and .mcp.json for inadvertent deletions — or, if removal was "
            f"deliberate, delete the entry from {MCP_BASELINE_PATH}."
        )

    never_seen = sorted(EXPECTED_MCP_SERVERS - configured - set(baseline))
    prev_reported = None
    try:
        prev_reported = json.loads(NEVER_CONFIGURED_STATE.read_text(encoding="utf-8"))
        if not isinstance(prev_reported, list):
            prev_reported = None
    except (OSError, ValueError):
        prev_reported = None
    if never_seen and never_seen != prev_reported:
        findings.append(
            f"[LOW] {len(never_seen)} expected MCP server(s) have never been "
            f"configured on this machine (new machine or in-progress "
            f"migration): {', '.join(never_seen[:6])}"
            f"{', …' if len(never_seen) > 6 else ''}. Informational — port "
            f"them when ready (`expected_servers` in the environment catalog "
            f"is the reference list). Shown once; re-reports only when this set "
            f"changes (delete {NEVER_CONFIGURED_STATE.name} to re-show)."
        )
    if never_seen != prev_reported:
        try:
            NEVER_CONFIGURED_STATE.write_text(
                json.dumps(never_seen, indent=2) + "\n",
                encoding="utf-8", newline="\n")
        except OSError:
            pass  # state write failure must not break session start

    # TOFU update: every configured server joins this machine's baseline.
    newly_seen = configured - set(baseline)
    if newly_seen:
        from datetime import date
        for name in newly_seen:
            baseline[name] = date.today().isoformat()
        try:
            MCP_BASELINE_PATH.write_text(
                json.dumps(baseline, indent=2, sort_keys=True) + "\n",
                encoding="utf-8", newline="\n")
        except OSError:
            pass  # baseline write failure must not break session start

    return findings






def check_15_hook_path_slashes():
    """Validate hook command paths use forward slashes only (no backslashes).

    Mixed backslash/forward-slash paths trigger MSYS path rewriting on Windows,
    silently corrupting the path (e.g., hooks/script.py -> Usersyou.claudehooks/script.py).
    Confirmed 2026-03-22: prompt-secret-scan.py blocked on every session due to backslash in path.
    """
    findings = []
    if not SETTINGS_FILE.exists():
        return []
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except Exception:
        return []
    hooks_config = settings.get("hooks", {})
    for event, event_hooks in hooks_config.items():
        if not isinstance(event_hooks, list):
            continue
        for hook_group in event_hooks:
            for hook in hook_group.get("hooks", []):
                cmd = hook.get("command", "")
                if not cmd:
                    continue
                # After JSON parsing, backslashes in the command string are literal.
                # Check if any path component contains backslash.
                if "\\" in cmd:
                    # Find the offending segment for the error message
                    bad_parts = [p for p in cmd.split() if "\\" in p and ":" in p]
                    for bp in bad_parts[:1]:
                        short = bp if len(bp) <= 80 else bp[:77] + "..."
                        findings.append(
                            f"[HIGH] Hook in {event} has backslash path: {short}. "
                            "Use forward slashes only to prevent MSYS path rewriting."
                        )
    return findings



def run_bounds_enforcement():
    curate_script = HOOKS_DIR / "curate-memory.py"
    if not curate_script.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(curate_script), "--enforce-bounds"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
        )
        if result.stdout.strip():
            output = json.loads(result.stdout.strip())
            pruned = output.get("pruned", 0)
            if pruned > 0:
                return f"Bounds enforcement: {pruned} entries pruned"
        return None
    except Exception:
        return None



def check_16_manifest_coverage():
    """Check manifest coverage across skills, hooks, rules."""
    findings = []
    manifests_dir = CLAUDE_DIR / "manifests"
    graph_path = manifests_dir / "graph.json"

    # Count actual components
    skill_dirs = [
        d for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists() and d.name != "_shared"
    ]
    # Shared helper modules imported BY hooks, not hooks themselves — they are
    # not registered against any event, so they cannot have a hook manifest and
    # must not inflate the denominator. `startswith("_")` catches the
    # underscore-prefixed helpers (`_platform.py`) but not the ones that predate
    # that convention, which is why coverage read 61/64 while only two real
    # manifests were missing (precompact-ledger, postcompact-audit — both now
    # written). Verified 2026-07-29: `session_ledger` appears nowhere in
    # settings.json, while both of those hooks do.
    HOOK_HELPER_MODULES = {"session_ledger.py"}
    hook_files = [
        f for f in HOOKS_DIR.glob("*.py")
        if f.name != "__init__.py"
        and not f.name.startswith("_")
        and f.name not in HOOK_HELPER_MODULES
    ]
    rule_files = list((CLAUDE_DIR / "rules").glob("*.md"))

    # Count manifested
    skill_manifests = list(SKILLS_DIR.glob("*/manifest.yaml"))
    hook_manifests_dir = HOOKS_DIR / "manifests"
    hook_manifests = list(hook_manifests_dir.glob("*.yaml")) if hook_manifests_dir.exists() else []
    rule_manifests_dir = CLAUDE_DIR / "rules" / "manifests"
    rule_manifests = list(rule_manifests_dir.glob("*.yaml")) if rule_manifests_dir.exists() else []

    total = len(skill_dirs) + len(hook_files) + len(rule_files)
    manifested = len(skill_manifests) + len(hook_manifests) + len(rule_manifests)
    pct = 100 * manifested // total if total else 0

    if pct < 100:
        findings.append(
            f"[LOW] Manifest coverage: {manifested}/{total} ({pct}%) — "
            f"skills {len(skill_manifests)}/{len(skill_dirs)}, "
            f"hooks {len(hook_manifests)}/{len(hook_files)}, "
            f"rules {len(rule_manifests)}/{len(rule_files)}"
        )

    # Auto-regen graph.json if missing or stale. graph.json is gitignored (deterministic
    # from manifests), so on a fresh checkout it's always missing — this rebuilds silently.
    needs_regen = False
    if not graph_path.exists() and manifested > 0:
        needs_regen = True
    elif graph_path.exists():
        graph_mtime = graph_path.stat().st_mtime
        for m in skill_manifests + hook_manifests + rule_manifests:
            if m.stat().st_mtime > graph_mtime:
                needs_regen = True
                break

    if needs_regen:
        try:
            result = subprocess.run(
                [sys.executable, str(CLAUDE_DIR / "manifests" / "compile.py"),
                 "--root", str(CLAUDE_DIR), "--quiet", "--no-reindex"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                tail = (result.stdout or result.stderr or "").strip().splitlines()
                hint = tail[-1] if tail else "(no output)"
                findings.append(f"[MEDIUM] graph.json regen failed: {hint[:200]}")
        except Exception as e:
            findings.append(f"[MEDIUM] graph.json regen error: {e}")

    return findings


# Memory-review nag throttle (banner-noise gate, 2026-07-05): once past the
# overdue threshold the reminder fired every session, growing by one day
# each time. Signal once, then re-remind at most weekly.
MEMORY_REVIEW_OVERDUE_DAYS = 14
MEMORY_REVIEW_RENAG_DAYS = 7
MEMORY_REVIEW_NAG_STATE = Path.home() / ".claude" / ".last-memory-review-nag.json"


def check_memory_review_overdue():
    """One-line reminder when /review-learnings is overdue, throttled to
    at most one reminder per MEMORY_REVIEW_RENAG_DAYS. Returns None when
    not overdue, recently nagged, or on any read error."""
    try:
        if not CLAUDE_JSON.exists():
            return None
        with open(CLAUDE_JSON, "r", encoding="utf-8") as f:
            cj = json.load(f)
        last_review = (
            cj.get("skillUsage", {})
            .get("review-learnings", {})
            .get("lastUsedAt", 0)
        )
        if not last_review:
            return None
        now_s = datetime.now().timestamp()
        days_since = (now_s * 1000 - last_review) / (1000 * 86400)
        if days_since <= MEMORY_REVIEW_OVERDUE_DAYS:
            return None
        try:
            state = json.loads(MEMORY_REVIEW_NAG_STATE.read_text(encoding="utf-8"))
            last_nag_s = float(state.get("last_nag_ts", 0))
        except (OSError, ValueError, TypeError):
            last_nag_s = 0.0
        if now_s - last_nag_s < MEMORY_REVIEW_RENAG_DAYS * 86400:
            return None
        try:
            MEMORY_REVIEW_NAG_STATE.write_text(
                json.dumps({"last_nag_ts": now_s}) + "\n",
                encoding="utf-8", newline="\n")
        except OSError:
            pass  # state write failure must not break session start
        return (
            f"Memory review overdue: /review-learnings last run "
            f"{int(days_since)} days ago. Consider running it to prune stale "
            f"entries and promote confirmed patterns. (Reminds at most every "
            f"{MEMORY_REVIEW_RENAG_DAYS} days.)"
        )
    except Exception:
        return None


def run_consistency_check():
    all_findings = []
    # bounds_enforcement runs in parallel with checks below

    checks = [
        ("Agent denylists", check_1_agent_denylists),
        ("Stub topic files", check_4_stub_topic_files),
        ("Memory bounds", check_5_memory_bounds),
        ("Dead pipeline", check_7_no_dead_pipeline),
        ("Memory staleness", check_8_memory_staleness),
        ("Stale component refs", check_10_stale_component_references),
        ("MEMORY.md overflow", check_11_memory_md_overflow),
        ("Untrusted repo config", check_13_untrusted_repo_config),
        ("MCP server inventory", check_14_mcp_server_inventory),
        ("Hook path slashes", check_15_hook_path_slashes),
        ("Manifest coverage", check_16_manifest_coverage),
    ]

    from concurrent.futures import ThreadPoolExecutor

    def _run_check(name_fn):
        name, fn = name_fn
        try:
            return fn()
        except Exception as e:
            return [f"[ERROR] Check '{name}' failed: {e}"]

    with ThreadPoolExecutor(max_workers=6) as executor:
        bounds_future = executor.submit(run_bounds_enforcement)
        check_futures = [executor.submit(_run_check, item) for item in checks]
        bounds_msg = bounds_future.result()
        for f in check_futures:
            all_findings.extend(f.result())

    parts = []
    if bounds_msg:
        parts.append(bounds_msg)
    if all_findings:
        critical = sum(1 for f in all_findings if "[CRITICAL]" in f)
        high = sum(1 for f in all_findings if "[HIGH]" in f)
        medium = sum(1 for f in all_findings if "[MEDIUM]" in f)
        low = sum(1 for f in all_findings if "[LOW]" in f)
        # Severity-sorted: the 2026-06-11 mac-port triage showed a CRITICAL
        # buried under five LOWs — module order is not actionability order.
        _rank = {"[ERROR]": 0, "[CRITICAL]": 1, "[HIGH]": 2, "[MEDIUM]": 3, "[LOW]": 4}

        def _sev(f):
            for tag, r in _rank.items():
                if tag in f:
                    return r
            return 5

        all_findings.sort(key=_sev)
        summary = f"Consistency check: {len(all_findings)} finding(s) ({critical}C/{high}H/{medium}M/{low}L)"
        details = "\n".join(f"  {f}" for f in all_findings)
        parts.append(f"{summary}\n{details}")
    else:
        parts.append("Consistency check: all checks passed.")

    nag = check_memory_review_overdue()
    if nag:
        parts.append(nag)

    return parts


