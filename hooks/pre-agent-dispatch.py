"""PreToolUse hook for Agent tool: warn when dispatching workers that need
authenticated remote MCPs.

Agent tool workers (separate processes) cannot authenticate to remote MCP servers
(they appear as 'anonymous'). This does NOT apply to context:fork skill sub-agents
which inherit parent MCP connections.

Auth detection (2026-04-15): now reads graph.json manifests to identify skills
with auth_constraint: main_thread_only, supplemented by keyword fallback for
prompts that don't reference a specific skill.

Exit codes:
  0 = continue (with optional additionalContext warning to the model)
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _environment_catalog import load_section

GRAPH_PATH = Path.home() / ".claude" / "manifests" / "graph.json"

# ── PHASE F: per-subagent git-worktree isolation (OPT-IN) ───────────────
# The `work` skill + worktree-enforcement.py isolate a *session* into its
# own worktree, but parallel SUBAGENTS dispatched from one session still
# share that session's working tree — a shared-HEAD race when two agents
# Edit/Write concurrently. This block OPTIONALLY provisions a per-subagent
# worktree so each writing agent gets its own HEAD.
#
# CRITICAL CONTRACT:
#   * Gated entirely behind the env var SUBAGENT_WORKTREE_ISOLATION_ENV.
#     When unset, EVERY code path below is skipped and dispatch behavior is
#     byte-for-byte identical to before this block existed.
#   * Fail-open: any error (git missing, not a repo, worktree add fails,
#     budget exceeded) logs a warning and proceeds with the normal,
#     un-isolated dispatch. We never block a dispatch on isolation failure.
SUBAGENT_WORKTREE_ISOLATION_ENV = "SUBAGENT_WORKTREE_ISOLATION"

# Per-cohort budget cap: maximum number of concurrent per-subagent worktrees
# we will provision before refusing further isolation (fail-open to a
# non-isolated dispatch). This bounds disk/inode pressure from a fan-out that
# spawns many writing agents at once. Enforcement here is intentionally light
# (a count of live agent-* worktrees under the worktrees dir); the constant is
# the scaffold a future phase can tighten into hard admission control.
MAX_PARALLEL_SUBAGENT_WORKTREES = 8

# Where per-subagent worktrees live — same root the `work` skill and
# worktree-enforcement.py use, so the existing `.claude/worktrees/` detection
# in those tools recognizes them as isolated.
_WORKTREES_ROOT = Path.home() / ".claude" / "worktrees"
_SUBAGENT_CLAIM_DIR = Path.home() / ".claude" / "state" / "subagent-worktree-claims"

# Both lists below are ENVIRONMENT DATA from the catalog's `agent_dispatch`
# section (hooks/_environment_catalog.py): which remote MCPs need auth, and
# which repos are protected, are facts about the operator's setup, not about
# this hook. Empty lists leave the corresponding check inert.
_AGENT_DISPATCH = load_section("agent_dispatch")

# Fallback keyword regex — used when graph.json unavailable or prompt
# doesn't match any manifested skill name. Whole-word, case-insensitive match
# on the catalog's `auth_mcp_keywords`; None when none are configured.
_AUTH_TERMS = [
    t.strip() for t in (_AGENT_DISPATCH.get("auth_mcp_keywords") or [])
    if isinstance(t, str) and t.strip()
]
AUTH_MCP_KEYWORDS = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _AUTH_TERMS) + r")\b",
    re.IGNORECASE,
) if _AUTH_TERMS else None

# Module-level cache
_graph = None
_graph_mtime = 0


def _load_graph():
    """Load compiled graph.json, cached per process."""
    global _graph, _graph_mtime
    if not GRAPH_PATH.exists():
        return None
    mtime = GRAPH_PATH.stat().st_mtime
    if _graph is not None and mtime == _graph_mtime:
        return _graph
    try:
        with open(GRAPH_PATH, encoding="utf-8") as f:
            _graph = json.load(f)
        _graph_mtime = mtime
        return _graph
    except Exception:
        return None


def check_auth_from_manifest(prompt):
    """Check if the prompt references a skill with main_thread_only auth.

    Returns (warning_message, matched_providers) or (None, []).
    """
    graph = _load_graph()
    if not graph:
        return None, []

    prompt_lower = prompt.lower()
    # Check if any skill name appears in the prompt
    for comp_id, comp in graph.items():
        if comp.get("type") != "skill":
            continue
        if comp.get("auth_constraint") != "main_thread_only":
            continue
        # Match skill name in prompt (e.g., "triage", "/triage", "run triage")
        if re.search(rf"\b{re.escape(comp_id)}\b", prompt_lower):
            providers = comp.get("requires_auth", [])
            provider_names = [
                p["provider"] if isinstance(p, dict) else str(p)
                for p in providers
            ]
            msg = (
                f"Auth warning: Skill /{comp_id} requires main_thread_only auth "
                f"({', '.join(provider_names)}). Sub-agents cannot authenticate "
                f"to these remote MCP servers. Run this skill from the main thread "
                f"or use Python scripts with direct API calls."
            )
            return msg, provider_names

    return None, []




# ── FILE OVERLAP DETECTION ──────────────────────────────────────────

_ACTIVE_AGENTS_FILE = Path.home() / ".claude" / ".active-agent-files.json"


def check_file_overlap(prompt):
    """Warn when a new agent targets files already being edited by another agent."""
    # Extract file paths mentioned in the prompt
    file_patterns = re.findall(
        r"(?:edit|modify|create|write|update)\s+[`\"']?([\w./-]+\.\w+)",
        prompt, re.IGNORECASE
    )
    if not file_patterns:
        return None

    # Check against active agent files
    active = {}
    try:
        if _ACTIVE_AGENTS_FILE.exists():
            active = json.loads(_ACTIVE_AGENTS_FILE.read_text(encoding="utf-8"))
            # Prune entries older than 30 minutes
            import time
            now = time.time()
            active = {k: v for k, v in active.items() if now - v.get("ts", 0) < 1800}
    except Exception:
        active = {}

    # Check for overlap
    overlapping = []
    for fp in file_patterns:
        fp_norm = fp.replace("\\", "/").lower()
        for agent_id, info in active.items():
            for existing_fp in info.get("files", []):
                if fp_norm in existing_fp.lower() or existing_fp.lower() in fp_norm:
                    overlapping.append((fp, agent_id))

    # Register this agent's files
    import time
    agent_id = f"agent_{int(time.time())}"
    active[agent_id] = {"files": file_patterns, "ts": time.time()}
    try:
        # Atomic write — concurrent agent dispatches would otherwise
        # interleave and corrupt the JSON.
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from atomic_write import atomic_write as _aw
            _aw(_ACTIVE_AGENTS_FILE, json.dumps(active, indent=2))
        except ImportError:
            _ACTIVE_AGENTS_FILE.write_text(
                json.dumps(active, indent=2), encoding="utf-8"
            )
    except Exception:  # noqa: S110, BLE001 -- fail-open: overlap tracking is advisory; never block a dispatch
        pass  # fail-open: overlap warnings degrade, dispatch proceeds

    if overlapping:
        files_str = ", ".join(f[0] for f in overlapping[:3])
        return (
            f"File overlap warning: {files_str} may be targeted by another active agent. "
            "Consider sequential processing or different file assignments to avoid overwrites."
        )
    return None

# ── WORKTREE ISOLATION ENFORCEMENT ─────────────────────────────────────
# Protected repos that require worktree isolation for subagent writes: the
# lowercase path fragments in the catalog's `protected_repo_paths` (e.g.
# "code/my-tooling", ".claude"), matched against repo paths mentioned in
# agent prompts. Slashes are normalised so a Windows path still matches.

PROTECTED_REPO_PATHS = [
    p.strip().lower().replace("\\", "/")
    for p in (_AGENT_DISPATCH.get("protected_repo_paths") or [])
    if isinstance(p, str) and p.strip()
]

# Gitignored RUNTIME paths under ~/.claude that are NOT repo content. A prompt
# that only references these (session transcripts, saved tool results, runtime
# state) is not a config-repo write — masking them prevents the false
# positive where a read-only transcript-mining agent that writes its OUTPUT
# elsewhere (e.g. /tmp) gets blocked on the ".claude" substring match.
# Measured 2026-08-16: a weekly-update transcript miner reading
# ~/.claude/projects/ and writing to /tmp/claude/ was blocked twice; worktree
# isolation then failed anyway (cwd not a git repo), forcing inline mining.
RUNTIME_NON_REPO_SUBPATHS = (
    ".claude/projects",
    ".claude/session-transcripts",
    ".claude/tool-results",
    ".claude/state",
    ".claude/logs",
)

# Patterns indicating the agent will write files (not just read/research)
WRITE_INDICATORS = re.compile(
    r"\b(edit|modify|create|write|update|add|change|fix|refactor|implement|delete|remove)\b.*"
    r"\b(file|script|hook|skill|rule|config|settings|SKILL\.md|\.py|\.ts|\.rs|\.md)\b",
    re.IGNORECASE | re.DOTALL,
)


def check_worktree_isolation(tool_input, prompt):
    """Block subagent writes to protected repos without worktree isolation.

    Returns (block_message, should_block) tuple. should_block=True means exit 2.
    """
    isolation = tool_input.get("isolation", "")
    if isolation == "worktree":
        return None, False  # Already isolated

    # Check if the prompt references a protected repo path. Mask gitignored
    # runtime paths first so ".claude/projects/..." (transcripts) does not
    # satisfy the ".claude" repo match — only remaining repo-content mentions
    # (skills/, hooks/, rules/, settings, ...) should trigger isolation.
    prompt_lower = prompt.lower().replace("\\", "/")
    masked_prompt = prompt_lower
    for runtime_path in RUNTIME_NON_REPO_SUBPATHS:
        masked_prompt = masked_prompt.replace(runtime_path, "<runtime-path>")
    matched_repo = None
    for repo_path in PROTECTED_REPO_PATHS:
        if repo_path in masked_prompt:
            matched_repo = repo_path
            break

    if not matched_repo:
        return None, False  # Not targeting a protected repo

    # Check if this looks like a write task (not just research/exploration)
    if not WRITE_INDICATORS.search(prompt):
        return None, False  # Read-only task — isolation not needed

    msg = (
        f"BLOCKED: Subagent targets protected repo '{matched_repo}' with write operations "
        f"but isolation: \"worktree\" is not set. Add isolation: \"worktree\" to the Agent "
        f"tool call and retry. Without worktree isolation, subagents share the main session's "
        f"branch state and can corrupt git HEAD or commit to the wrong branch."
    )
    return msg, True


# ── PHASE F implementation helpers ──────────────────────────────────────

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Best-effort detection that a dispatched subagent will Edit/Write (vs. a
# pure read/research agent). Reuses the same write-intent vocabulary as
# WRITE_INDICATORS above but is broader (intent alone, no file-type anchor)
# because isolation is cheap to over-provision and the budget cap bounds it.
_AGENT_WILL_WRITE = re.compile(
    r"\b(edit|modify|create|write|update|add|append|change|fix|refactor|"
    r"implement|delete|remove|rename|patch|generate|commit)\b",
    re.IGNORECASE,
)


def _git(args, cwd=None, timeout=10):
    """Run a git command, returning the CompletedProcess or None on failure.
    Never raises — callers treat None as 'git unavailable / failed'."""
    try:
        return subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, cwd=cwd, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _isolation_enabled():
    """True only when the opt-in env var is set to a truthy value."""
    val = os.environ.get(SUBAGENT_WORKTREE_ISOLATION_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _count_live_subagent_worktrees():
    """Light budget probe: count existing per-subagent worktree dirs
    (named '*-agent-*') under the worktrees root. Returns 0 on any error."""
    try:
        if not _WORKTREES_ROOT.exists():
            return 0
        return sum(
            1 for p in _WORKTREES_ROOT.iterdir()
            if p.is_dir() and "-agent-" in p.name
        )
    except OSError:
        return 0


def _next_agent_index(session_suffix):
    """Pick a per-session agent index by counting existing worktrees for this
    session. Best-effort and racy under heavy concurrency, but the worktree
    path collision is itself caught (git worktree add fails -> fail-open)."""
    try:
        if not _WORKTREES_ROOT.exists():
            return 1
        n = sum(
            1 for p in _WORKTREES_ROOT.iterdir()
            if p.is_dir() and f"-{session_suffix}-agent-" in p.name
        )
        return n + 1
    except OSError:
        return 1


def provision_subagent_worktree(tool_input, prompt, session_id, cwd):
    """OPT-IN: provision a per-subagent git worktree for a writing agent.

    Returns a dict describing the provisioned worktree (for an additionalContext
    injection) or None when isolation is not applied (disabled, read-only agent,
    not a git repo, budget exceeded, or any failure). NEVER raises — every
    failure path returns None so dispatch proceeds normally (fail-open).

    Branch naming follows the plan's convention: claude/<session>-agent-<n>,
    placed under ~/.claude/worktrees/ so the existing '.claude/worktrees/'
    isolation detection in worktree-enforcement.py / the work skill recognizes
    it as isolated.
    """
    if not _isolation_enabled():
        return None  # default-off: identical to pre-Phase-F behavior

    # Already explicitly isolated by the caller — nothing to add.
    if tool_input.get("isolation") == "worktree":
        return None

    # Best-effort write-intent detection: only isolate agents that will write.
    if not prompt or not _AGENT_WILL_WRITE.search(prompt):
        return None

    try:
        # Resolve the repo we'd branch from. Prefer the dispatch cwd; fall
        # back to the hook process cwd.
        base_cwd = cwd or os.getcwd()
        toplevel = _git(["rev-parse", "--show-toplevel"], cwd=base_cwd)
        if not toplevel or toplevel.returncode != 0:
            sys.stderr.write(
                "[pre-agent-dispatch] worktree-isolation: not a git repo "
                f"(cwd={base_cwd}); proceeding without isolation.\n"
            )
            return None
        repo_root = toplevel.stdout.strip()
        repo_name = os.path.basename(repo_root)

        # Budget cap (light enforcement): refuse new worktrees past the cap.
        live = _count_live_subagent_worktrees()
        if live >= MAX_PARALLEL_SUBAGENT_WORKTREES:
            sys.stderr.write(
                f"[pre-agent-dispatch] worktree-isolation: budget cap "
                f"({MAX_PARALLEL_SUBAGENT_WORKTREES}) reached "
                f"({live} live); proceeding without isolation.\n"
            )
            return None

        suffix = (session_id or "")[:8] or f"{os.getpid()}"
        idx = _next_agent_index(suffix)
        branch = f"claude/{suffix}-agent-{idx}"
        wt_dir = _WORKTREES_ROOT / f"{repo_name}-{suffix}-agent-{idx}"

        # Determine the base ref to branch from. Prefer current HEAD of the
        # dispatch repo so the agent sees the session's in-progress state;
        # fall back to creating from whatever HEAD resolves to.
        head = _git(["rev-parse", "HEAD"], cwd=repo_root)
        base_ref = head.stdout.strip() if (head and head.returncode == 0) else "HEAD"

        _WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
        add = _git(
            ["worktree", "add", "-b", branch, str(wt_dir), base_ref],
            cwd=repo_root, timeout=30,
        )
        if not add or add.returncode != 0:
            err = (add.stderr.strip() if add else "git unavailable")
            sys.stderr.write(
                "[pre-agent-dispatch] worktree-isolation: worktree add failed "
                f"({err}); proceeding without isolation.\n"
            )
            return None

        # Write a claim file so subagent-stop.py can find and GC the worktree.
        claim = {
            "session_id": session_id,
            "session_suffix": suffix,
            "agent_index": idx,
            "repo_name": repo_name,
            "repo_root": repo_root,
            "worktree_path": str(wt_dir),
            "branch": branch,
            "base_ref": base_ref,
        }
        try:
            _SUBAGENT_CLAIM_DIR.mkdir(parents=True, exist_ok=True)
            claim_path = _SUBAGENT_CLAIM_DIR / f"{suffix}-agent-{idx}.json"
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from atomic_write import atomic_write as _aw
                _aw(claim_path, json.dumps(claim, indent=2))
            except ImportError:
                claim_path.write_text(json.dumps(claim, indent=2), encoding="utf-8")
        except OSError:
            pass  # claim is best-effort; the worktree itself is the source of truth

        return claim
    except Exception:
        # Absolute fail-open guard: any unexpected error -> no isolation.
        try:
            sys.stderr.write(
                "[pre-agent-dispatch] worktree-isolation: unexpected error; "
                "proceeding without isolation.\n"
            )
        except Exception:  # noqa: S110, BLE001 -- fail-open: even the fallback notice must not raise
            pass  # fail-open: the notice is best-effort
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Claude Code's PreToolUse hook input uses `tool_input`. Legacy hooks
    # read `input`, which silently no-op'd every check in this file.
    # Prefer the canonical key; fall back for backwards compat.
    tool_input = data.get("tool_input") or data.get("input") or {}
    prompt = tool_input.get("prompt", "")

    if not prompt:
        sys.exit(0)

    session_id = data.get("session_id", "")
    cwd = data.get("cwd", "")

    warnings = []
    extra_context = None

    # PHASE F (OPT-IN, fail-open): provision a per-subagent worktree when
    # SUBAGENT_WORKTREE_ISOLATION=1 and the agent is expected to write. When
    # the env var is unset, provision_subagent_worktree() returns None on its
    # first line and this block is a no-op — default behavior unchanged.
    try:
        wt_claim = provision_subagent_worktree(tool_input, prompt, session_id, cwd)
    except Exception:
        wt_claim = None  # belt-and-suspenders fail-open
    if wt_claim:
        extra_context = (
            "WORKTREE ISOLATION: You have been assigned a dedicated git "
            f"worktree at {wt_claim['worktree_path']} (branch "
            f"{wt_claim['branch']}). Work ONLY in this worktree — cd into it "
            "before editing or writing files, and make all commits on this "
            "branch. Do NOT edit files in the parent session's working tree; "
            "doing so re-introduces the shared-HEAD race this isolation "
            "prevents."
        )

    # Check auth from manifests first (precise, names specific providers)
    manifest_warning, manifest_providers = check_auth_from_manifest(prompt)
    if manifest_warning:
        warnings.append(manifest_warning)
        try:
            from manifest_metrics import log_manifest_query
            log_manifest_query(
                "pre-agent-dispatch", "auth_check",
                f"manifest-first: providers={manifest_providers}",
            )
        except Exception:  # noqa: S110, BLE001 -- fail-open: telemetry must never break the dispatch
            pass  # fail-open: telemetry only
    else:
        # Fallback: keyword regex for prompts that don't match a skill name
        # (inert when the catalog names no authenticated MCPs).
        matches = AUTH_MCP_KEYWORDS.findall(prompt) if AUTH_MCP_KEYWORDS else []
        if matches:
            unique = sorted({m.lower() for m in matches})
            try:
                from manifest_metrics import log_manifest_query
                log_manifest_query(
                    "pre-agent-dispatch", "auth_check",
                    f"keyword-fallback: keywords={list(unique)}",
                    used_fallback=True,
                )
            except Exception:  # noqa: S110, BLE001 -- fail-open: telemetry must never break the dispatch
                pass  # fail-open: telemetry only
            warnings.append(
                f"Auth warning: This task references authenticated MCPs ({', '.join(unique)}). "
                "Sub-agents cannot authenticate to remote MCP servers - they appear as 'anonymous'. "
                "Consider running authenticated queries in the main thread or via Python scripts instead."
            )

    # Check file overlap with active agents
    overlap_warning = check_file_overlap(prompt)
    if overlap_warning:
        warnings.append(overlap_warning)

    # Check worktree isolation for protected repo writes (BLOCKING)
    worktree_msg, should_block = check_worktree_isolation(tool_input, prompt)
    if should_block:
        print(json.dumps({
            "decision": "block",
            "reason": worktree_msg,
        }))
        sys.exit(2)

    # Build the hook output. The warnings `message` and the Phase-F
    # additionalContext are independent: either, both, or neither may be set.
    # When neither is set we print nothing (identical to pre-Phase-F output).
    # Warnings and the Phase-F worktree instruction both go to the model through
    # additionalContext; the former top-level "message" was undocumented and
    # never reached it (probed 2026-09-03).
    parts = []
    if warnings:
        parts.append(" | ".join(warnings))
    if extra_context:
        parts.append(extra_context)
    if parts:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": "\n\n".join(parts)}}))
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)