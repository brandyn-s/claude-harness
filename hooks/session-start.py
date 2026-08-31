"""Consolidated SessionStart hook — runs all startup tasks in a single process.

Replaces several separate hooks (env-loader, auto-prune, consistency-check,
linear-ops-reminder) to eliminate multiple console window flashes on Windows.

Module implementations live in session_start_modules/.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Add hooks dir to path for module imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from session_start_modules.auto_prune import run_auto_prune
from session_start_modules.code_graph_health import check_code_graph_health
from session_start_modules.code_search_stale_project_guard import cleanup_stale_projects
from session_start_modules.concurrent_session import (
    prune_stale_markers,
    write_session_marker,
)
from session_start_modules.consistency import run_consistency_check
from session_start_modules.env_loader import run_env_loader
from session_start_modules.index_corruption import check_index_corruption
from session_start_modules.index_staleness import check_index_staleness
from session_start_modules.index_autoheal import autoheal_indexes
from session_start_modules.mcp_binary_staleness import check_mcp_binary_staleness
from session_start_modules.mcp_oauth_heal import heal_mcp_oauth_clients
from session_start_modules.mcp_zombie_cleanup import cleanup_stale_mcps
from session_start_modules.repo_sync import sync_tracked_repos
from session_start_modules.stale_config_checkout import check_stale_config_checkout
from session_start_modules.worktree_gc import prune_worktrees

# red-mains banner disabled at session start 2026-06-28 (user request): the
# standing-red list re-printed all ~30 long-broken workflows every session
# (wallpaper). The daily launchd sweep (com.example.red-main-sweep, runs
# WITHOUT --quiet) still records ~/.claude/red-mains.json AND fires a macOS
# notification for NEW reds, so new breakage is still surfaced — only the
# per-session standing-list banner is suppressed. session_start_modules/
# red_mains.py + its tests are intact; re-enable by restoring the import,
# the executor.submit(check_red_mains) below, its .result(), and the
# `if red_main_messages` extend block.

# linear-ops command menu removed from session start 2026-06-11 (mac-port
# triage): a static menu is not a status check — it cost attention every
# session with zero diagnostic value. The commands are discoverable via
# /linear-status and the skills catalog.


def check_concurrent_session_risk():
    """Detect if ~/.claude repo is in a state suggesting another session is active.

    If the repo is on a feature branch or has uncommitted changes, a concurrent
    session will share the same branch/index and risk corrupting each other's
    git state. Recommend --worktree for isolation.

    Returns a warning string or None.
    """
    import subprocess
    claude_dir = Path.home() / ".claude"
    try:
        # Check current branch
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
            cwd=str(claude_dir),
            creationflags=0x08000000 if __import__("sys").platform == "win32" else 0,
        )
        branch = result.stdout.strip()
        if branch and branch != "main" and not branch.startswith("worktree-"):
            return (
                f"ACTION REQUIRED: claude-config is on branch '{branch}' (not main). "
                f"Another session left the repo on a feature branch. Before doing "
                f"any work, call EnterWorktree to isolate this session. Do NOT "
                f"create files or edit code until you are in a worktree."
            )

        # Check for dirty state (uncommitted changes from another session)
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
            cwd=str(claude_dir),
            creationflags=0x08000000 if __import__("sys").platform == "win32" else 0,
        )
        dirty_lines = [
            l for l in result.stdout.strip().split("\n")
            if l.strip() and not l.strip().startswith("??")
        ]
        if len(dirty_lines) > 3:
            return (
                f"ACTION REQUIRED: claude-config has {len(dirty_lines)} uncommitted "
                f"changes from another session. Before doing any work, call "
                f"EnterWorktree to isolate this session. Do NOT create files or "
                f"edit code until you are in a worktree."
            )
    except Exception:
        pass  # Never block session start
    return None


def check_global_model_default():
    """Heal (or warn) if settings.json `model` (the global default) is a
    provider-specific ID.

    The global `model` applies to every launcher. The 1P launchers (claude,
    claude-ws) inherit it unless they pin their own ANTHROPIC_MODEL, so a
    Bedrock/GovCloud-namespaced ID there silently routes them onto the wrong
    backend. `/model` records the picked model in the namespace of the session
    it was run from, so selecting a model while in a Bedrock session plants a
    `us.anthropic.*` ID as everyone's default. INVARIANT: the global default
    must be a 1P-format `claude-*` ID; provider-prefixed IDs belong only in a
    launcher's own ANTHROPIC_MODEL. (iterm-config launchers + reference-
    claude-code-launchers memory; profile-misroute incident 2026-06-18.)

    SELF-HEAL: a region-prefixed inference-profile id
    ((us|us-gov|eu|apac).anthropic.claude-*) is rewritten in place to its
    1P form (the region prefix + any trailing `-vN:M` Bedrock version stripped),
    so a poisoned global fixes itself at the next session start instead of
    lingering until someone reverts it by hand. IDs that can't be confidently
    mapped to a `claude-*` 1P form (arn:aws, or a strip that doesn't yield
    claude-*) are warned, not rewritten. The write is atomic (tempfile +
    os.replace) and surgical (only the model VALUE changes; formatting
    preserved); it never raises and never blocks session start.

    Returns a status string (healed or warn) or None.
    """
    import re
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return None
    try:
        raw = settings_path.read_text(encoding="utf-8")
        model = json.loads(raw).get("model")
        if not isinstance(model, str):
            return None
        provider_prefixes = (
            "us.anthropic.", "us-gov.anthropic.",
            "eu.anthropic.", "apac.anthropic.", "arn:aws",
        )
        if not model.startswith(provider_prefixes):
            return None

        # Attempt to self-heal a region-prefixed id -> its 1P `claude-*` form.
        m = re.match(r'^(?:us-gov|apac|eu|us)\.anthropic\.(.+)$', model)
        healed = None
        if m:
            candidate = re.sub(r'-v\d+:\d+', '', m.group(1))  # drop Bedrock -vN:M
            if candidate.startswith("claude-") and candidate != model:
                healed = candidate
        if healed:
            try:
                new_raw = re.sub(
                    r'("model"\s*:\s*")' + re.escape(model) + r'(")',
                    lambda mm: mm.group(1) + healed + mm.group(2),
                    raw, count=1,
                )
                if new_raw != raw:
                    import tempfile
                    fd, tmp = tempfile.mkstemp(
                        dir=str(settings_path.parent),
                        prefix=".settings-heal-", suffix=".json",
                    )
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(new_raw)
                    os.replace(tmp, settings_path)
                    return (
                        f"HEALED GLOBAL MODEL DEFAULT: settings.json `model` was "
                        f"provider-specific '{model}' (that Bedrock/GovCloud ID is "
                        f"every launcher's default and misroutes the 1P launchers); "
                        f"rewrote it to 1P-format '{healed}'. Provider-specific "
                        f"models belong only in a launcher's own ANTHROPIC_MODEL."
                    )
            except Exception:
                pass  # rewrite failed -> fall through to the warn below

        # Couldn't heal (arn:aws, non-claude strip, or the write failed): warn.
        return (
            f"GLOBAL MODEL DEFAULT IS PROVIDER-SPECIFIC: settings.json "
            f"`model` = '{model}'. That Bedrock/GovCloud-format ID is the "
            f"default for ALL launchers; the 1P launchers (claude, claude-ws) "
            f"inherit it and misroute. Reset it from a plain `claude` (1P) "
            f"session via /model, or remove the key — launchers that need a "
            f"provider-specific model already set their own ANTHROPIC_MODEL."
        )
    except Exception:
        pass  # Never block session start
    return None


def validate_hook_paths():
    """Verify all registered hook script paths in settings.json exist on disk.

    Returns list of warning strings for missing scripts.
    (2026-04-05: blast-radius-info.py was registered but missing, blocking
    all Write/Edit operations until diagnosed. This check catches that at
    session start instead of at first tool use.)
    """
    warnings = []
    hooks_dir = Path.home() / ".claude" / "hooks"
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return warnings
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        hooks = settings.get("hooks", {})
        for event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") != "command":
                        continue
                    cmd = hook.get("command", "")
                    # Extract script path (after the Python executable or run-hook launcher)
                    parts = cmd.split()
                    script = None
                    for p in parts:
                        if p.endswith(".py") and "pythonw" not in p and "python" not in p.lower().replace(".py", ""):
                            script = p
                            break
                    if not script:
                        continue
                    # Strip surrounding quotes
                    script = script.strip('"').strip("'")
                    # Resolve: bare filenames dispatched via run-hook live in ~/.claude/hooks/
                    script_path = Path(script)
                    if not script_path.is_absolute() and "/" not in script and "\\" not in script:
                        script_path = hooks_dir / script
                    else:
                        # Expand $HOME / ~ in absolute paths
                        expanded = os.path.expandvars(script).replace("$HOME", str(Path.home()))
                        script_path = Path(expanded).expanduser()
                    if not script_path.exists():
                        name = Path(script).name
                        matcher = entry.get("matcher", "*")
                        warnings.append(
                            f"MISSING HOOK: {name} ({event}:{matcher}) — "
                            f"registered in settings.json but file not found. "
                            f"This will cause {event} hook errors on {matcher} tool calls."
                        )
    except Exception:
        pass
    return warnings


def check_orphan_worktrees():
    """Detect directories under ~/worktrees/ that look like worktrees but
    are no longer registered with any git repo.

    Background (RC6 from 2026-05-28 retro): `git worktree remove --force` on
    Windows often fails with Permission denied when a process holds a
    handle in the worktree. The worktree IS detached at the git level
    (gone from `git worktree list`) but the directory remains on disk.
    Over many sessions these accumulate — /retro counted 7+ orphans
    persisting across sessions. This check surfaces the count so the
    user can `rm -rf` them after a reboot.

    Returns: list of warning strings (empty if no orphans).
    """
    warnings = []
    worktrees_dir = Path.home() / "worktrees"
    if not worktrees_dir.exists():
        return warnings
    orphans = []
    for sub in worktrees_dir.iterdir():
        if not sub.is_dir():
            continue
        # A live worktree has a .git file (not dir) pointing at the main
        # repo's worktree metadata. An orphan has no .git or a .git that
        # points at a now-removed metadata directory.
        git_marker = sub / ".git"
        if not git_marker.exists():
            # Directory under ~/worktrees/ with no .git — probably not a
            # worktree at all (or already cleaned). Skip.
            continue
        # Probe: does git still register this as a working tree?
        try:
            result = subprocess.run(
                ["git", "-C", str(sub), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode != 0 or result.stdout.strip() != "true":
                orphans.append(sub.name)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            # Treat probe failure as "unknown" — don't claim orphan
            continue
    if orphans:
        sample = ", ".join(orphans[:3])
        more = f" (+{len(orphans) - 3} more)" if len(orphans) > 3 else ""
        warnings.append(
            f"Orphan worktree directories: {len(orphans)} under ~/worktrees/ "
            f"— {sample}{more}. These are detached at the git level but "
            f"survived `git worktree remove` due to file locks. Safe to "
            f"`rm -rf` after closing editors/processes that had them open."
        )
    return warnings


def main():
    from concurrent.futures import ThreadPoolExecutor

    # Read session_id from hook input stdin (used by concurrent-session marker
    # and passed through to repo_sync for the same-session filter).
    # `source` is also captured: its documented values are
    # startup|resume|clear|compact|fork, and the acceptance-ledger rehydration
    # below only applies to the sources that CONTINUE an existing conversation.
    session_id = None
    session_source = ""
    try:
        if sys.stdin and not sys.stdin.closed:
            hook_input = json.load(sys.stdin)
            session_id = hook_input.get("session_id")
            session_source = hook_input.get("source") or ""
    except Exception:
        pass

    # Write our session marker BEFORE the parallel work; prune stale markers
    # left over from crashed sessions in the same call.
    write_session_marker(session_id)
    prune_stale_markers()

    # 1. Env loader (writes to CLAUDE_ENV_FILE, must be first)
    run_env_loader()

    # 2. Run independent startup tasks in parallel
    with ThreadPoolExecutor(max_workers=8) as executor:
        fut_sync = executor.submit(sync_tracked_repos, session_id)
        fut_prune = executor.submit(run_auto_prune)
        fut_consistency = executor.submit(run_consistency_check)
        fut_hooks = executor.submit(validate_hook_paths)
        fut_staleness = executor.submit(check_index_staleness)
        fut_autoheal = executor.submit(autoheal_indexes)
        fut_corruption = executor.submit(check_index_corruption)
        fut_mcp_staleness = executor.submit(check_mcp_binary_staleness)
        fut_mcp_zombies = executor.submit(cleanup_stale_mcps)
        fut_oauth_heal = executor.submit(heal_mcp_oauth_clients)
        fut_cg_health = executor.submit(check_code_graph_health)
        fut_cs_projects = executor.submit(cleanup_stale_projects)
        fut_orphans = executor.submit(check_orphan_worktrees)
        fut_worktree_gc = executor.submit(prune_worktrees)
        fut_stale_config = executor.submit(check_stale_config_checkout)

        sync_warnings = fut_sync.result()
        prune_msg = fut_prune.result()
        consistency_parts = fut_consistency.result()
        hook_warnings = fut_hooks.result()
        staleness_warnings = fut_staleness.result()
        autoheal_messages = fut_autoheal.result()
        corruption_warnings = fut_corruption.result()
        mcp_staleness_warnings = fut_mcp_staleness.result()
        mcp_zombie_messages = fut_mcp_zombies.result()
        oauth_heal_messages = fut_oauth_heal.result()
        cg_health_messages = fut_cg_health.result()
        cs_project_messages = fut_cs_projects.result()
        orphan_warnings = fut_orphans.result()
        worktree_gc_messages = fut_worktree_gc.result()
        stale_config_warnings = fut_stale_config.result()

    messages = []

    # Check for concurrent session risk on claude-config repo
    worktree_warning = check_concurrent_session_risk()
    if worktree_warning:
        messages.append(worktree_warning)

    # Self-heal (or warn) if the global default model is a provider-specific
    # (Bedrock/Gov) ID — the 1P launchers inherit it and misroute; a region-
    # prefixed id is rewritten to its 1P form in place (profile-misroute 2026-06-18).
    model_default_warning = check_global_model_default()
    if model_default_warning:
        messages.append(model_default_warning)

    # Stale ~/.claude = stale enforcement. Emitted before the hook-path
    # warnings because a stale tree can also make THOSE warnings wrong.
    if stale_config_warnings:
        messages.extend(stale_config_warnings)

    if hook_warnings:
        messages.extend(hook_warnings)
    if staleness_warnings:
        messages.extend(staleness_warnings)
    # Immediately after the staleness list on purpose: the reader should see
    # WHAT is stale and WHETHER it is already being fixed in one glance.
    if autoheal_messages:
        messages.extend(autoheal_messages)
    if corruption_warnings:
        messages.extend(corruption_warnings)
    if mcp_staleness_warnings:
        messages.extend(mcp_staleness_warnings)
    if mcp_zombie_messages:
        messages.extend(mcp_zombie_messages)
    if oauth_heal_messages:
        messages.extend(oauth_heal_messages)
    if cg_health_messages:
        messages.extend(cg_health_messages)
    if cs_project_messages:
        messages.extend(cs_project_messages)
    if orphan_warnings:
        messages.extend(orphan_warnings)
    if worktree_gc_messages:
        messages.extend(worktree_gc_messages)
    if sync_warnings:
        messages.append("Repo sync: " + "; ".join(sync_warnings))
    if prune_msg:
        messages.append(prune_msg)
    messages.extend(consistency_parts)

    # Surface a banner if a parallel session-start hook recently checkpointed
    # uncommitted edits onto a branch. Active session can recover via
    # `git -C <repo> checkout <branch> -- <file>`.
    last_ckpt = Path.home() / ".claude" / ".last-auto-checkpoint.json"
    if last_ckpt.exists():
        try:
            ckpt = json.loads(last_ckpt.read_text(encoding="utf-8"))
            # Only surface if recent (< 1h) — older artifacts are stale.
            ckpt_ts = ckpt.get("timestamp", "")
            if ckpt_ts and len(ckpt_ts) >= 14:
                from datetime import datetime
                try:
                    ckpt_dt = datetime.strptime(ckpt_ts[:14], "%Y%m%d%H%M%S")
                    age_secs = (datetime.now() - ckpt_dt).total_seconds()
                    if 0 <= age_secs < 3600:
                        files = ckpt.get("files", [])
                        files_preview = (
                            ", ".join(files[:3])
                            + (f" (+{len(files) - 3} more)" if len(files) > 3 else "")
                            if files else "(no files captured)"
                        )
                        messages.append(
                            f"AUTO-CHECKPOINT RECOVERY: parallel session-start "
                            f"hook preserved {len(files)} file(s) on branch "
                            f"{ckpt.get('branch', '?')} in {ckpt.get('repo', '?')}. "
                            f"Files: {files_preview}. "
                            f"Recover with: {ckpt.get('recovery_hint', '')}"
                        )
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass

    # Check friction alert from previous session
    friction_alert = Path.home() / ".claude" / "friction-alert.txt"
    if friction_alert.exists():
        try:
            alert_text = friction_alert.read_text(encoding="utf-8").strip()
            if alert_text:
                messages.append(f"FRICTION ALERT: {alert_text}")
        except Exception:
            pass

    # Check for handoff from previous session
    handoff_file = Path.home() / ".claude" / "HANDOFF.md"
    if handoff_file.exists():
        try:
            handoff_text = handoff_file.read_text(encoding="utf-8").strip()
            if handoff_text:
                # Show the handoff, then delete so it doesn't persist forever
                messages.append(f"HANDOFF FROM PREVIOUS SESSION:\n{handoff_text}")
                handoff_file.unlink()
        except Exception:
            pass

    # Inject the active platform's rules (macos/windows/linux) as additionalContext.
    # Claude Code has no native OS-conditional rule loading, so cross-platform
    # rules load natively from ~/.claude/rules/ while OS-specific rules live in
    # ~/.claude/platform-rules/<os>/ and are conditionally injected here.
    from session_start_modules.platform_rules import load_platform_rules
    platform_ctx, platform_summary = load_platform_rules()
    if platform_summary:
        messages.append(platform_summary)

    # Rehydrate the acceptance ledger after a compaction (audit Phase 4).
    #
    # This is the CONSUMER that never existed: precompact-checkpoint.py has been
    # writing ~/.claude/.precompact-state.json with no reader, so there was no
    # rehydration path at all. `PostCompact` cannot inject model context, so
    # SessionStart with source=="compact" is the correct injection point.
    # Scoped to continuation sources only -- injecting a prior conversation's
    # requirements into a fresh `startup` session would misrepresent them as this
    # session's.
    ledger_ctx = ""
    try:
        from session_start_modules.ledger_rehydrate import run_ledger_rehydrate
        ledger_ctx, ledger_summary = run_ledger_rehydrate(session_id, session_source)
        if ledger_summary:
            messages.append(ledger_summary)
    except Exception:
        pass

    # Emit systemMessage (banner) + platform rules and/or ledger as additionalContext.
    # Both are concatenated: overwriting one with the other would silently drop the
    # platform rules on exactly the sessions (post-compaction) that most need them.
    out = {"systemMessage": "\n".join(messages)}
    combined_ctx = "\n\n".join(p for p in (platform_ctx, ledger_ctx) if p)
    if combined_ctx:
        out["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": combined_ctx,
        }
    print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)