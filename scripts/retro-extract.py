#!/usr/bin/env python3
"""Extract metrics from Claude Code session transcripts for retrospective analysis.

Scans ~/.claude/session-transcripts/ for JSONL transcripts within a time window,
extracts per-session metrics, computes aggregates, and outputs JSON.

Two modes:
  --depth shallow  (original: is_error counts only)
  --depth deep     (default: classified errors, friction score, user corrections)

Usage:
    python retro-extract.py --window 48 --focus crowdstrike
    python retro-extract.py --window 168 --depth shallow
"""

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

TRANSCRIPTS_DIR = Path.home() / ".claude" / "session-transcripts"


def _latest_transcript_mtime(d: Path) -> float:
    """Newest *.jsonl mtime under a project dir, or 0.0 if it holds none.

    Ranking by transcript recency (not dir mtime) is deliberate: an empty
    stub dir can win a dir-mtime race just by being touched, and a
    cwd-encoded stub with zero transcripts must never be preferred over the
    real session dir. See the 2026-07-24 retro Pass-0 finding."""
    try:
        return max((f.stat().st_mtime for f in d.glob("*.jsonl")), default=0.0)
    except OSError:
        return 0.0


def _resolve_project_dir() -> Path:
    """Resolve the per-project Claude Code dir at runtime (cwd encoding).

    An explicit CLAUDE_PROJECT_DIR always wins. Otherwise pick the project
    dir with the MOST-RECENTLY-WRITTEN transcript — NOT the cwd-encoded dir
    just because it exists. A cwd of /tmp/claude encodes to
    `-private-tmp-claude`, a stub that may hold a STALE transcript;
    preferring it by existence (or by dir-mtime) shadowed the real session
    dir and produced the 2026-07-24 "No transcripts found in the last 336h"
    bug. Transcript recency is the only reliable "which project is this
    session in" signal. The cwd-encoded candidate breaks exact ties and is
    the last resort when no dir holds any transcript."""
    if env_dir := os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(env_dir)
    projects = Path.home() / ".claude" / "projects"
    encoded = str(Path.cwd().resolve()).replace("/", "-").replace(":", "-").replace(".", "-")
    candidate = projects / encoded
    if projects.exists():
        subdirs = [p for p in projects.iterdir() if p.is_dir()]
        with_transcripts = [(p, _latest_transcript_mtime(p)) for p in subdirs]
        with_transcripts = [(p, m) for p, m in with_transcripts if m > 0.0]
        if with_transcripts:
            best_mtime = max(m for _, m in with_transcripts)
            # Break an exact tie in favor of the cwd-encoded candidate.
            if candidate.exists() and _latest_transcript_mtime(candidate) == best_mtime:
                return candidate
            return max(with_transcripts, key=lambda pm: pm[1])[0]
        # No dir holds transcripts — last-resort fallbacks (pre-fix behavior).
        if candidate.exists():
            return candidate
        if subdirs:
            return max(subdirs, key=lambda p: p.stat().st_mtime)
    return projects / "_unresolved"


PROJECTS_DIR = _resolve_project_dir()
OUTPUT_DIR = Path.home() / ".claude" / "retrospectives"

_GH = Path.home() / "Documents" / "GitHub"
KNOWN_REPOS = [
    str(_GH / "mcp-servers"),
    str(_GH / "mcp-infra"),
    str(Path.home() / ".claude"),
    str(_GH / "example-monorepo"),
    str(_GH / "example-compliance-repo"),
    str(_GH / "example-sbom-tool"),
]

# User correction/frustration phrases
USER_CORRECTION_PHRASES = [
    "no, ",
    "that's wrong",
    "that's not",
    "i said",
    "i meant",
    "you're wrong",
    "incorrect",
    "not what i asked",
    "try again",
    "do it again",
    "that didn't work",
    "stop",
    "don't do that",
    "i already told you",
    "wrong approach",
    "wrong file",
    "wrong path",
]

# Substrings that mark a message as NOT a genuine user correction, even when a
# USER_CORRECTION_PHRASE matches inside it. The phrase list is deliberately
# broad ("stop", "no, ", "incorrect"), so these markers strip the boilerplate
# and pasted-content false positives that inflated the metric to ~85% noise
# across four consecutive retrospectives (2026-06-30 → 2026-07-24). All matched
# case-insensitively. See the 2026-07-24-14d retro "user_corrections" caveat.
USER_CORRECTION_EXCLUSIONS = [
    "this session is being continued",  # compaction-boundary summary paste
    "stop hook feedback",               # supergoal Stop-hook "condition not met" lines
    "<teammate-message",                # inter-agent messages (not the user)
    "<local-command",                   # slash-command stdout echoes
    "<command-name>",
    "<command-message>",
    "<system-reminder>",
    "<bash-stdout",                     # bash-input command echoes
    "<bash-stderr",
    "the user doesn't want to proceed", # tool-rejection boilerplate
    "the user wants to clarify",        # AskUserQuestion clarify boilerplate
    "[request interrupted",             # interrupt boilerplate
]

# Model backtracking phrases
# Expanded 2026-04-21 retro (item 2): prior list caught 0 approach changes in
# an 8d window despite "try again" appearing 4x in user corrections. Added
# short-form phrases that Claude actually uses when pivoting.
APPROACH_CHANGE_PHRASES = [
    "let me try a different approach",
    "let me try another approach",
    "that didn't work, let me",
    "failed, so let me",
    "instead, i'll",
    "instead, let me",
    "let me reconsider",
    "that approach won't work",
    "wait, that's",
    "actually, let me",
    "hmm, let me",
    "on second thought",
    "let me rethink",
    "different approach",
    "let me take a different",
    "that won't work because",
]

# Tools where empty results indicate wasted turns (search/query tools)
# Exclude Bash, Write, Edit, TaskUpdate, etc. which legitimately produce no stdout
SEARCH_TOOLS = {
    "Grep",
    "Glob",
    "Read",
    "Agent",
    "ToolSearch",
    "AskUserQuestion",
    "mcp__tavily__tavily_search",
    "mcp__tavily__tavily_extract",
    "mcp__tavily__tavily_crawl",
    "mcp__tavily__tavily_research",
    "mcp__memory-search__memory_search",
    "mcp__remote-confluence__confluence_search",
    "mcp__arxiv-mcp-server__search_papers",
}

# Recurring task patterns for skill gap detection
TASK_PATTERNS = {
    "deploy": ["docker", "ecs", "deploy", "fargate", "terraform apply"],
    "ci_workflow": ["gh pr create", "gh pr checks", "gh pr merge", "git push"],
    "research": ["tavily_search", "tavily_extract", "deep-dive", "deep-research"],
    "bulk_ops": ["for ", "while ", "xargs", "batch", "bulk"],
    "mcp_debug": ["mcp", "stdio", "transport", "health check"],
}

# Filename pattern: YYYY-MM-DD-HH-MM-{session_id}.jsonl
FILENAME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-([a-f0-9]+)\.jsonl$"
)


def parse_filename_timestamp(filename):
    """Extract a datetime from a transcript filename (local time, converted to UTC)."""
    m = FILENAME_RE.match(filename)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    try:
        # Filenames use local time (America/Chicago), not UTC
        local_dt = datetime(year, month, day, hour, minute)
        return local_dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_iso_timestamp(ts_str):
    """Parse an ISO 8601 timestamp string to a datetime."""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def classify_bash_error(err_text):
    """Classify a bash non-zero exit error into a category."""
    if "No such file or directory" in err_text:
        return "file_not_found"
    if "Permission denied" in err_text:
        return "permission_denied"
    if "command not found" in err_text:
        return "command_not_found"
    if "GraphQL:" in err_text:
        return "gh_graphql_error"
    if "MSYS" in err_text or "C:/Program Files/Git" in err_text:
        return "msys_path_rewrite"
    if "merge" in err_text.lower() and (
        "conflict" in err_text.lower() or "rebase" in err_text.lower()
    ):
        return "git_merge_conflict"
    if "rebase" in err_text.lower() and (
        "unstaged" in err_text.lower() or "uncommitted" in err_text.lower()
    ):
        return "dirty_working_tree"
    if "unstaged changes" in err_text or "uncommitted" in err_text:
        return "dirty_working_tree"
    if ".gitignore" in err_text:
        return "gitignored_file"
    if "hook" in err_text.lower() and "pre-commit" in err_text.lower():
        return "git_hook_failure"
    if "404" in err_text or "Not Found" in err_text:
        return "http_404"
    if "unexpected EOF" in err_text:
        return "bash_quoting_eof"
    if "SyntaxError" in err_text or "IndentationError" in err_text:
        return "python_syntax_error"
    if "Traceback" in err_text:
        return "python_exception"
    if "timeout" in err_text.lower() or "timed out" in err_text.lower():
        return "timeout"
    if "status checks" in err_text:
        return "ci_checks_not_passed"
    if "no checks reported" in err_text:
        return "ci_checks_pending"
    if "Unable to locate credentials" in err_text:
        return "aws_credentials_missing"
    if "Token has expired and refresh failed" in err_text:
        return "aws_sso_expired"
    if "You must specify a region" in err_text:
        return "aws_region_missing"
    if "GH006" in err_text or "Protected branch update failed" in err_text:
        return "protected_branch_push"
    if "you must first push the current branch" in err_text:
        return "pr_before_push"
    if "head branch" in err_text and "same as base" in err_text:
        return "pr_from_main"
    if "Request interrupted by user" in err_text:
        return "user_interrupted"
    if "Terraform" in err_text and ("Warning" in err_text or "Deprecated" in err_text):
        return "terraform_warning"
    if "WindowsApps" in err_text and "PythonSoftwareFoundation" in err_text:
        return "wrong_python_interpreter"
    if "ModuleNotFoundError" in err_text or "No module named" in err_text:
        return "python_missing_module"
    if "ImportError" in err_text:
        return "python_import_error"
    if "already exists" in err_text and (
        "branch" in err_text.lower() or "ref" in err_text.lower()
    ):
        return "git_branch_exists"
    if "Could not resolve host" in err_text or "Name or service not known" in err_text:
        return "dns_resolution_failure"
    if "Connection refused" in err_text or "Connection reset" in err_text:
        return "connection_refused"
    if "rate limit" in err_text.lower() or "API rate" in err_text:
        return "api_rate_limit"
    if "disk" in err_text.lower() and (
        "full" in err_text.lower() or "space" in err_text.lower()
    ):
        return "disk_full"
    if "json.decoder.JSONDecodeError" in err_text or "Expecting value" in err_text:
        return "json_parse_error"
    if "UnicodeDecodeError" in err_text or "codec can't decode" in err_text:
        return "encoding_error"
    # Added 2026-03-15: patterns from 4 consecutive retros of "other" at 48%
    if "jq" in err_text and (
        "parse" in err_text.lower()
        or "Cannot iterate" in err_text
        or "error" in err_text.lower()
    ):
        return "jq_parse_error"
    if "fatal: couldn't find remote ref" in err_text or "fatal: bad object" in err_text:
        return "git_remote_not_found"
    if "Device or resource busy" in err_text:
        return "file_locked"
    if "admin:org" in err_text or "missing_scope" in err_text or "403" in err_text:
        return "api_403_scope"
    if "already up to date" in err_text.lower() or "Already up to date" in err_text:
        return "git_noop"
    if "nothing to commit" in err_text or "nothing added to commit" in err_text:
        return "git_noop"
    if "lock" in err_text.lower() and "file" in err_text.lower():
        return "file_locked"
    if "FAILED" in err_text and (
        "test" in err_text.lower() or "pytest" in err_text.lower()
    ):
        return "test_failure"
    if "short test summary" in err_text:
        return "test_failure"
    if "WinError 32" in err_text or "being used by another process" in err_text:
        return "file_locked"
    if "cannot be rerun" in err_text or "cannot be retried" in err_text:
        return "workflow_rerun_blocked"
    if "Cannot approve your own pull request" in err_text:
        return "self_approval_blocked"
    if "preload" in err_text.lower() and "failed" in err_text.lower():
        return "background_preload_failure"
    # Git repo/ref failures
    if "fatal: not a git repository" in err_text:
        return "not_git_repo"
    if "fatal: ambiguous argument" in err_text:
        return "git_ambiguous_arg"
    # pip/package install failures
    if ("pip install" in err_text or "pip3 install" in err_text) and (
        "ERROR" in err_text or "Could not" in err_text
    ):
        return "pip_install_failure"
    # PowerShell errors
    if "pwsh" in err_text.lower() or "TerminatingError" in err_text:
        return "powershell_error"
    # gh CLI auth
    if "gh auth" in err_text or "not logged into" in err_text:
        return "gh_auth_failure"
    # UnicodeEncodeError (cp1252 stdout)
    if "UnicodeEncodeError" in err_text or "codec can't encode" in err_text:
        return "encoding_error"
    # taskkill / process management
    if "taskkill" in err_text.lower() or "tasklist" in err_text.lower():
        if "ERROR" in err_text or "not found" in err_text.lower():
            return "process_management_error"
    # AWS CLI errors
    if "aws" in err_text.lower() and "error" in err_text.lower() and "botocore" in err_text.lower():
        return "aws_cli_error"
    # CKLB/SCA script informational exits
    if ("cklb" in err_text.lower() or "stig" in err_text.lower()) and len(err_text) < 200:
        return "sca_script_exit"
    # Added 2026-03-27: patterns from 122 "other" errors in 7d retro
    # Dirty working tree: "local changes would be overwritten by checkout/merge"
    if "local changes" in err_text and "overwritten" in err_text:
        return "dirty_working_tree"
    # GitHub API deprecated endpoints (HTTP 410)
    if "HTTP 410" in err_text or "endpoint has been moved" in err_text:
        return "gh_api_deprecated"
    # GitHub API invalid query (HTTP 400)
    if "supplied query is invalid" in err_text:
        return "gh_api_invalid_query"
    # GitHub PR not mergeable (branch policy)
    if "is not mergeable" in err_text or "base branch policy prohibits" in err_text:
        return "gh_pr_not_mergeable"
    # GitHub PR already merged/closed
    if "can't be closed because it was already" in err_text:
        return "gh_pr_already_closed"
    # GitHub CLI unknown JSON field
    if "Unknown JSON field" in err_text:
        return "gh_cli_field_error"
    # GitHub workflow dispatch error (HTTP 422)
    if "could not create workflow dispatch event" in err_text:
        return "gh_workflow_dispatch_error"
    # GitHub workflow ambiguous name
    if "could not resolve to a unique workflow" in err_text:
        return "gh_workflow_ambiguous"
    # CI check failure output (gh pr checks / gh run view showing failures)
    if re.search(r"\b(fail|failing)\b.*https://github\.com/", err_text, re.IGNORECASE):
        return "ci_check_failure"
    # Git refspec push error
    if "src refspec" in err_text and "does not match" in err_text:
        return "git_push_refspec_error"
    # Git network errors (unable to access, Recv failure, wsasend)
    if "unable to access" in err_text and "fatal:" in err_text:
        return "git_network_error"
    if "wsasend:" in err_text or "Recv failure" in err_text:
        return "git_network_error"
    # PowerShell ANSI-wrapped errors (Get-ChildItem, etc.)
    if "Get-ChildItem" in err_text or "Get-Content" in err_text:
        return "powershell_error"
    # Silent nonzero exit (just "Exit code N" with no error message)
    if re.match(r"^Exit code \d+\s*$", err_text.strip()):
        return "silent_nonzero_exit"
    # Benign tool output with nonzero exit (self-update messages, routing tests)
    if "Self-update is not supported" in err_text:
        return "benign_tool_output"
    if "cannot iterate over: null" in err_text:
        return "jq_parse_error"
    # Git commit output with exit code 1 (committer warning, not a real error)
    if "Committer:" in err_text and "git commit" not in err_text:
        return "git_commit_warning"
    # ls: cannot access / Not a directory
    if "ls:" in err_text and ("cannot access" in err_text or "Not a directory" in err_text):
        return "file_not_found"
    # unzip errors
    if "unzip:" in err_text and "cannot find" in err_text:
        return "file_not_found"
    # Fatal git errors not caught above (generic)
    if "fatal:" in err_text and err_text.startswith("Exit code 128"):
        return "git_fatal_other"
    return "other"


def classify_error(err_msg):
    """Classify an error message into category and subcategory."""
    if "PreToolUse:" in err_msg and "hook error" in err_msg:
        if "dangerous-command-guard" in err_msg:
            return "hook_block", "dangerous_command_guard"
        if "guard-webfetch" in err_msg:
            return "hook_block", "guard_webfetch"
        if "exfiltration-guard" in err_msg:
            return "hook_block", "exfiltration_guard"
        if "security_reminder" in err_msg:
            return "hook_block", "security_reminder"
        if "credential" in err_msg.lower():
            return "hook_block", "credential_guard"
        if "graph_mutate" in err_msg or "graph_request" in err_msg:
            return "hook_block", "graph_prompt_hook"
        return "hook_block", "other_hook"

    if "<tool_use_error>" in err_msg:
        if "File has not been read yet" in err_msg:
            return "tool_error", "file_not_read"
        if "File has been modified since read" in err_msg:
            return "tool_error", "file_modified_since_read"
        if "matches of the string to replace" in err_msg:
            return "tool_error", "ambiguous_edit_match"
        if "No changes to make" in err_msg:
            return "tool_error", "no_op_edit"
        if "String to replace not found" in err_msg:
            return "tool_error", "stale_edit_context"
        if "cannot be used with Skill tool" in err_msg:
            return "tool_error", "skill_invocation_error"
        if "No such tool" in err_msg:
            return "tool_error", "tool_not_found"
        if "Path does not exist" in err_msg:
            return "tool_error", "path_not_found"
        if "No task found" in err_msg:
            return "tool_error", "task_not_found"
        if "Unknown skill" in err_msg:
            return "tool_error", "unknown_skill"
        return "tool_error", "other_tool_error"

    if "Exit code" in err_msg:
        sub = classify_bash_error(err_msg)
        return "bash_error", sub

    if "Ripgrep search timed out" in err_msg:
        return "tool_error", "ripgrep_timeout"

    if "File does not exist" in err_msg:
        return "tool_error", "file_not_found"

    if "API 400" in err_msg or "API 404" in err_msg or "API 500" in err_msg:
        return "api_error", err_msg[:60]

    if "Request failed" in err_msg:
        return "api_error", "request_failed"

    if "Client error" in err_msg:
        return "api_error", "client_error"

    if "Request interrupted by user" in err_msg:
        return "user_action", "interrupted"

    if "user doesn't want" in err_msg:
        return "user_action", "rejected"

    if "worktree" in err_msg.lower():
        return "tool_error", "worktree_error"

    if "pdftoppm" in err_msg or "browser" in err_msg.lower():
        return "tool_error", "missing_dependency"

    if "MCP error" in err_msg:
        return "api_error", "mcp_error"

    return "other_error", err_msg[:60]


def extract_session(filepath, deep=True):
    """Extract metrics from a single transcript JSONL file."""
    tool_calls = Counter()
    classified_errors = defaultdict(list)  # category -> [messages]
    skills_invoked = []
    cwds = set()
    timestamps = []
    first_human_message = None
    token_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    last_tool_name = None
    last_tool_errored = False
    retry_count = 0

    # Deep mode additional tracking
    empty_results = 0
    empty_results_friction = 0
    empty_results_validation = 0
    empty_results_by_tool = Counter()
    user_corrections = []
    approach_changes = 0
    # Track the last tool_use name for correlating with empty results
    pending_tool_name = None
    # Track recent tool names for friction intent classification (Fix 5)
    recent_tools = []
    # Track multi-step manual patterns (sequences of Bash calls without skills)
    consecutive_bash = 0
    max_consecutive_bash = 0
    # Track Bash command content for task pattern detection
    bash_commands = []
    # Track outcome signals
    has_git_commit = False
    has_file_write = False
    last_user_message = None
    # Fix 1: Parent-skill attribution — track active slash command
    active_command = None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rec_type = record.get("type")
                ts = parse_iso_timestamp(record.get("timestamp"))
                if ts:
                    timestamps.append(ts)

                cwd = record.get("cwd")
                if cwd:
                    cwds.add(cwd)

                if rec_type == "user":
                    msg = record.get("message", {})
                    content = msg.get("content", "")

                    # First human text message (skip system boilerplate)
                    if isinstance(content, str) and content.strip():
                        text = content.strip()

                        # Fix 1: Detect slash commands for parent-skill attribution
                        cmd_match = re.search(r'<command-name>/?([\w][\w-]*)</command-name>', text)
                        if cmd_match:
                            active_command = cmd_match.group(1)

                        if not (
                            "<local-command-caveat>" in text
                            or "<command-name>" in text
                            or "<command-message>" in text
                            or text.startswith("<system-reminder>")
                            or "<task-notification>" in text
                        ):
                            if first_human_message is None:
                                first_human_message = text
                            # Clear active_command on real user messages (not slash commands)
                            active_command = None

                            # Track last user message for outcome pairing
                            if deep:
                                last_user_message = text

                            # Deep: detect user corrections
                            if deep:
                                lower = text.lower()
                                # Skip boilerplate / pasted-content that trips the
                                # broad phrase list (compaction markers, Stop-hook
                                # feedback, tool-rejection text, command echoes).
                                if any(x in lower for x in USER_CORRECTION_EXCLUSIONS):
                                    pass
                                else:
                                    for phrase in USER_CORRECTION_PHRASES:
                                        if phrase in lower:
                                            user_corrections.append(text)
                                            break

                    # Check tool_result blocks
                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_result":
                                if block.get("is_error"):
                                    err_content = block.get("content", "")
                                    if isinstance(err_content, list):
                                        err_texts = [
                                            b.get("text", "")
                                            for b in err_content
                                            if isinstance(b, dict)
                                            and b.get("type") == "text"
                                        ]
                                        err_msg = "; ".join(err_texts)
                                    elif isinstance(err_content, str):
                                        err_msg = err_content
                                    else:
                                        err_msg = str(err_content)

                                    category, subcategory = classify_error(err_msg)
                                    classified_errors[category].append(
                                        {
                                            "subcategory": subcategory,
                                            "message": err_msg,
                                        }
                                    )

                                    if (
                                        category != "hook_block"
                                        and category != "user_action"
                                    ):
                                        last_tool_errored = True

                                elif deep:
                                    # Deep: check for empty/useless results
                                    result_text = ""
                                    rc = block.get("content", "")
                                    if isinstance(rc, list):
                                        result_text = " ".join(
                                            b.get("text", "")
                                            for b in rc
                                            if isinstance(b, dict)
                                        )
                                    elif isinstance(rc, str):
                                        result_text = rc
                                    stripped = result_text.strip()
                                    if stripped in (
                                        "",
                                        "No files found",
                                        "No matches found",
                                    ):
                                        # Only count empties from search/query tools
                                        is_search = (
                                            pending_tool_name in SEARCH_TOOLS
                                            or (
                                                pending_tool_name
                                                and pending_tool_name.startswith(
                                                    "mcp__"
                                                )
                                            )
                                        )
                                        if is_search:
                                            empty_results += 1
                                            if pending_tool_name:
                                                empty_results_by_tool[
                                                    pending_tool_name
                                                ] += 1
                                            # Fix 5: Classify as validation vs friction
                                            # Grep/Glob after Edit/Write/Bash = likely validation check
                                            has_recent_mutation = any(
                                                t in ("Edit", "Write", "Bash")
                                                for t in recent_tools[-4:-1]
                                            )
                                            if pending_tool_name in ("Grep", "Glob") and has_recent_mutation:
                                                empty_results_validation += 1
                                            else:
                                                empty_results_friction += 1

                elif rec_type == "assistant":
                    msg = record.get("message", {})
                    content = msg.get("content", [])
                    usage = msg.get("usage", {})

                    for key in token_usage:
                        token_usage[key] += usage.get(key, 0)

                    if not isinstance(content, list):
                        continue

                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_calls[tool_name] += 1
                            pending_tool_name = tool_name
                            # Fix 5: Track recent tools for friction intent
                            recent_tools.append(tool_name)
                            if len(recent_tools) > 5:
                                recent_tools.pop(0)

                            if tool_name == last_tool_name and last_tool_errored:
                                retry_count += 1
                            last_tool_name = tool_name
                            last_tool_errored = False

                            # Track consecutive Bash runs (manual workflow signal)
                            if deep:
                                if tool_name == "Bash":
                                    consecutive_bash += 1
                                    max_consecutive_bash = max(
                                        max_consecutive_bash, consecutive_bash
                                    )
                                    # Capture Bash command for pattern detection
                                    cmd = block.get("input", {}).get("command", "")
                                    if cmd:
                                        bash_commands.append(cmd)
                                        # Outcome: detect git commits
                                        if "git commit" in cmd:
                                            has_git_commit = True
                                else:
                                    consecutive_bash = 0

                                # Outcome: detect file writes
                                if tool_name in ("Write", "Edit"):
                                    has_file_write = True

                            if tool_name == "Skill":
                                skill_input = block.get("input", {})
                                skill_name = skill_input.get("skill", "unknown")
                                # Fix 1: Attribute child skill to parent command
                                if active_command and active_command != skill_name:
                                    skills_invoked.append(f"{active_command}>{skill_name}")
                                else:
                                    skills_invoked.append(skill_name)

                        elif deep and block.get("type") == "text":
                            text_lower = block.get("text", "").lower()
                            for phrase in APPROACH_CHANGE_PHRASES:
                                if phrase in text_lower:
                                    approach_changes += 1
                                    break

    except OSError:
        return None

    if not timestamps:
        return None

    timestamps.sort()
    duration_seconds = (timestamps[-1] - timestamps[0]).total_seconds()

    domains = set()
    for c in cwds:
        normalized = c.replace("\\", "/")
        for repo in KNOWN_REPOS:
            if normalized.startswith(repo):
                domains.add(repo.rsplit("/", 1)[-1])
                break

    total_tool_calls = sum(tool_calls.values())

    base_name = Path(filepath).stem

    # Build error summary by category
    error_summary = {}
    total_real_errors = 0
    for category, items in classified_errors.items():
        subcounts = Counter(item["subcategory"] for item in items)
        error_summary[category] = {
            "count": len(items),
            "subcategories": dict(subcounts.most_common()),
            "messages": [item["message"] for item in items],
        }
        if category not in ("hook_block", "user_action"):
            total_real_errors += len(items)

    hook_block_count = error_summary.get("hook_block", {}).get("count", 0)

    # Hook ROI: extract hook filenames from block messages.
    # Messages come in three formats (observed 2026-04-21 retro):
    #   1. [<full-python-path> <full-hook-path>]: ...   (direct pythonw invocation)
    #   2. ["$HOME/.claude/hooks/run-hook" <hook-name>.py]: ...  (run-hook wrapper)
    #   3. hooks/<hook-name>.py: ...                    (fallback, rare)
    # The old pattern `hooks[/\\](\S+\.py)` only caught #1; for #2 it matched
    # `run-hook"` because \S+ stops at whitespace. Now try run-hook format
    # first, then fall back to plain hooks/ path.
    hook_blocks_by_name = Counter()
    _RUN_HOOK_RE = re.compile(r'run-hook"?\s+([\w-]+\.py)')
    _HOOK_PATH_RE = re.compile(r"hooks[/\\]([\w-]+\.py)")
    for item in classified_errors.get("hook_block", []):
        msg = item.get("message", "")
        m = _RUN_HOOK_RE.search(msg) or _HOOK_PATH_RE.search(msg)
        if m:
            hook_blocks_by_name[m.group(1)] += 1
    user_action_count = error_summary.get("user_action", {}).get("count", 0)

    # Fix 5: Friction score uses only genuine friction empties, not validation checks
    friction_score = (
        total_real_errors + empty_results_friction + len(user_corrections) + approach_changes
    )

    # Fix 2: Session complexity tier (total_tool_calls computed above)
    if duration_seconds < 600 or total_tool_calls < 20:
        complexity_tier = "trivial"
    elif duration_seconds > 7200:
        complexity_tier = "complex"
    else:
        complexity_tier = "standard"

    result = {
        "file": Path(filepath).name,
        "session_id": base_name.split("-", 5)[-1] if "-" in base_name else base_name,
        "start": timestamps[0].isoformat(),
        "end": timestamps[-1].isoformat(),
        "duration_seconds": round(duration_seconds, 1),
        "duration_human": format_duration(duration_seconds),
        "tool_calls": dict(tool_calls.most_common()),
        "total_tool_calls": total_tool_calls,
        "errors": {
            "count": total_real_errors,
            "classified": error_summary,
        },
        "hook_blocks": hook_block_count,
        "hook_blocks_by_name": dict(hook_blocks_by_name.most_common()),
        "user_actions": user_action_count,
        "retry_count": retry_count,
        "skills_invoked": skills_invoked,
        "cwds": sorted(cwds),
        "domains": sorted(domains),
        "user_request": first_human_message,
        "token_usage": token_usage,
        "complexity_tier": complexity_tier,
        "friction": {
            "score": friction_score,
            "empty_results": empty_results,
            "empty_results_friction": empty_results_friction,
            "empty_results_validation": empty_results_validation,
            "empty_results_by_tool": dict(empty_results_by_tool.most_common()),
            "user_corrections": len(user_corrections),
            "user_correction_messages": user_corrections,
            "approach_changes": approach_changes,
            "max_consecutive_bash": max_consecutive_bash,
        },
        "outcome": {
            "has_git_commit": has_git_commit,
            "has_file_write": has_file_write,
            "ended_with_error": bool(
                total_real_errors > 0 and not has_git_commit and not has_file_write
            ),
            "last_user_message": last_user_message,
        },
        "task_patterns_detected": _detect_task_patterns(bash_commands),
    }

    return result


def _detect_task_patterns(bash_commands):
    """Detect recurring workflow patterns from Bash command sequences."""
    detected = {}
    all_cmds = " ".join(bash_commands).lower()
    for pattern_name, keywords in TASK_PATTERNS.items():
        hits = sum(1 for kw in keywords if kw in all_cmds)
        if hits >= 2:
            detected[pattern_name] = hits
    return detected


def format_duration(seconds):
    """Format seconds into a human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def matches_focus(session, focus):
    """Check if a session matches the focus keyword (case-insensitive)."""
    focus_lower = focus.lower()
    for tool_name in session.get("tool_calls", {}):
        if focus_lower in tool_name.lower():
            return True
    for cwd in session.get("cwds", []):
        if focus_lower in cwd.lower():
            return True
    req = session.get("user_request", "") or ""
    if focus_lower in req.lower():
        return True
    for skill in session.get("skills_invoked", []):
        if focus_lower in skill.lower():
            return True
    for domain in session.get("domains", []):
        if focus_lower in domain.lower():
            return True
    return False


def compute_aggregates(sessions, window_hours=48):
    """Compute aggregate metrics across all sessions."""
    if not sessions:
        return {}

    total_tool_calls = sum(s["total_tool_calls"] for s in sessions)
    total_errors = sum(s["errors"]["count"] for s in sessions)
    total_hook_blocks = sum(s["hook_blocks"] for s in sessions)
    total_retries = sum(s["retry_count"] for s in sessions)
    total_sessions = len(sessions)

    # Aggregate classified errors across all sessions
    global_error_categories = defaultdict(lambda: defaultdict(int))
    for s in sessions:
        for category, data in s["errors"]["classified"].items():
            for sub, count in data.get("subcategories", {}).items():
                global_error_categories[category][sub] += count

    # Friction aggregates
    total_friction = sum(s["friction"]["score"] for s in sessions)
    total_empty = sum(s["friction"]["empty_results"] for s in sessions)
    total_empty_friction = sum(s["friction"].get("empty_results_friction", 0) for s in sessions)
    total_empty_validation = sum(s["friction"].get("empty_results_validation", 0) for s in sessions)
    total_user_corrections = sum(s["friction"]["user_corrections"] for s in sessions)
    total_approach_changes = sum(s["friction"]["approach_changes"] for s in sessions)

    # Empty results by tool (aggregate)
    global_empty_by_tool = Counter()
    for s in sessions:
        global_empty_by_tool.update(s["friction"].get("empty_results_by_tool", {}))

    # Sessions with high consecutive bash (manual workflow candidates)
    high_bash_sessions = sum(
        1 for s in sessions if s["friction"].get("max_consecutive_bash", 0) >= 10
    )

    # Fix 2: Complexity tier breakdown
    tier_counts = Counter(s.get("complexity_tier", "standard") for s in sessions)
    nontrivial_sessions = [s for s in sessions if s.get("complexity_tier") != "trivial"]

    # Fix 2: Sessions without skills — only count standard+ sessions
    no_skill_sessions_all = sum(1 for s in sessions if not s["skills_invoked"])
    no_skill_sessions = sum(1 for s in nontrivial_sessions if not s["skills_invoked"])

    # Tool usage ranking (global)
    global_tool_counts = Counter()
    for s in sessions:
        global_tool_counts.update(s["tool_calls"])

    # Fix 1: Skill utilization — separate parent commands from child skills
    all_skills = Counter()
    parent_skill_invocations = Counter()
    child_skill_attributions = Counter()
    for s in sessions:
        for skill_entry in s["skills_invoked"]:
            all_skills[skill_entry] += 1
            if ">" in skill_entry:
                parent, child = skill_entry.split(">", 1)
                parent_skill_invocations[parent] += 1
                child_skill_attributions[skill_entry] += 1

    # Skill ROI: avg friction for sessions using each skill
    skill_friction = defaultdict(list)
    for s in sessions:
        for skill_name in s["skills_invoked"]:
            skill_friction[skill_name].append(s["friction"]["score"])
    skill_roi = {
        name: {"invocations": len(frictions), "avg_friction": round(sum(frictions) / len(frictions), 1)}
        for name, frictions in skill_friction.items()
    }

    # Hook ROI: aggregate blocks by hook name
    global_hook_blocks = Counter()
    for s in sessions:
        global_hook_blocks.update(s.get("hook_blocks_by_name", {}))

    # Domain spread
    domain_counts = Counter()
    for s in sessions:
        for d in s["domains"]:
            domain_counts[d] += 1

    # Token totals
    token_totals = defaultdict(int)
    for s in sessions:
        for key, val in s["token_usage"].items():
            token_totals[key] += val

    durations = [s["duration_seconds"] for s in sessions]
    avg_duration = sum(durations) / len(durations) if durations else 0

    error_rate = (total_errors / total_tool_calls * 100) if total_tool_calls > 0 else 0
    retry_rate = (total_retries / total_tool_calls * 100) if total_tool_calls > 0 else 0
    first_try_success = (
        (total_tool_calls - total_errors - total_retries) / total_tool_calls * 100
        if total_tool_calls > 0
        else 0
    )

    return {
        "session_count": total_sessions,
        "total_tool_calls": total_tool_calls,
        "total_errors": total_errors,
        "total_hook_blocks": total_hook_blocks,
        "total_retries": total_retries,
        "error_rate_pct": round(error_rate, 2),
        "retry_rate_pct": round(retry_rate, 2),
        "first_try_success_pct": round(max(first_try_success, 0), 2),
        "avg_errors_per_session": round(total_errors / total_sessions, 2),
        "avg_duration_seconds": round(avg_duration, 1),
        "avg_duration_human": format_duration(avg_duration),
        "error_breakdown": {
            cat: dict(subs) for cat, subs in global_error_categories.items()
        },
        "friction": {
            "total_score": total_friction,
            "avg_per_session": round(total_friction / total_sessions, 1),
            "empty_results": total_empty,
            "empty_results_friction": total_empty_friction,
            "empty_results_validation": total_empty_validation,
            "empty_results_by_tool": dict(global_empty_by_tool.most_common(10)),
            "user_corrections": total_user_corrections,
            "approach_changes": total_approach_changes,
        },
        "strategic": {
            "sessions_without_skills": no_skill_sessions,
            "sessions_without_skills_all": no_skill_sessions_all,
            "sessions_with_high_bash_runs": high_bash_sessions,
            "pct_sessions_no_skill": round(
                no_skill_sessions / len(nontrivial_sessions) * 100, 1
            ) if nontrivial_sessions else 0,
            "complexity_tiers": dict(tier_counts.most_common()),
        },
        # Fix 4: Per-day normalized rates for cross-window comparison
        "per_day": {
            "sessions": round(total_sessions / max(window_hours / 24, 1), 1),
            "errors": round(total_errors / max(window_hours / 24, 1), 1),
            "friction": round(total_friction / max(window_hours / 24, 1), 1),
            "tool_calls": round(total_tool_calls / max(window_hours / 24, 1), 1),
        },
        "tool_usage_ranking": dict(global_tool_counts.most_common(25)),
        "skill_utilization": dict(all_skills.most_common()),
        "parent_skill_invocations": dict(parent_skill_invocations.most_common()),
        "child_skill_attributions": dict(child_skill_attributions.most_common()),
        "domain_spread": dict(domain_counts.most_common()),
        "token_totals": dict(token_totals),
        "skill_roi": skill_roi,
        "hook_block_totals": dict(global_hook_blocks.most_common()),
    }


def gather_git_commits(window_hours):
    """Gather structured git commit data from known repos."""
    import subprocess

    since = f"{int(window_hours)} hours ago"
    repos = {}
    for repo_path in KNOWN_REPOS:
        repo_name = repo_path.rsplit("/", 1)[-1]
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            continue
        try:
            # Format: hash|message|files_changed|insertions|deletions|date
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "log",
                    f"--since={since}",
                    "--pretty=format:%h|%s|%aI",
                    "--shortstat",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
            )
            if result.returncode != 0:
                continue
            commits = []
            lines = result.stdout.strip().split("\n")
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue
                if "|" in line:
                    parts = line.split("|", 2)
                    if len(parts) >= 3:
                        sha, msg, date = parts[0], parts[1], parts[2]
                        stats = {"files": 0, "insertions": 0, "deletions": 0}
                        # Next line might be shortstat
                        if i + 1 < len(lines) and "changed" in lines[i + 1]:
                            stat_line = lines[i + 1].strip()
                            import re as _re

                            f_match = _re.search(r"(\d+) files? changed", stat_line)
                            i_match = _re.search(r"(\d+) insertions?", stat_line)
                            d_match = _re.search(r"(\d+) deletions?", stat_line)
                            if f_match:
                                stats["files"] = int(f_match.group(1))
                            if i_match:
                                stats["insertions"] = int(i_match.group(1))
                            if d_match:
                                stats["deletions"] = int(d_match.group(1))
                            i += 1
                        commits.append(
                            {
                                "sha": sha,
                                "message": msg,
                                "date": date,
                                **stats,
                            }
                        )
                i += 1
            if commits:
                total_ins = sum(c["insertions"] for c in commits)
                total_del = sum(c["deletions"] for c in commits)
                repos[repo_name] = {
                    "commit_count": len(commits),
                    "total_insertions": total_ins,
                    "total_deletions": total_del,
                    "commits": commits,
                }
        except (subprocess.TimeoutExpired, OSError):
            continue
    return repos


def gather_pr_data(window_hours):
    """Gather merged PR data from Example repos via gh CLI."""
    import subprocess

    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    since_str = since.strftime("%Y-%m-%d")
    repos_to_check = [
        "example-org/mcp-servers",
        "example-org/mcp-infra",
        "brandyn-s/claude-harness",
        "example-org/example-compliance-repo",
        "example-org/example-sbom-tool",
    ]
    all_prs = {}
    for repo in repos_to_check:
        repo_name = repo.split("/")[1]
        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--state",
                    "merged",
                    "--limit",
                    "100",
                    "--json",
                    "number,title,mergedAt,additions,deletions,changedFiles",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                env={**os.environ, "MSYS_NO_PATHCONV": "1"},
            )
            if result.returncode != 0:
                continue
            prs = json.loads(result.stdout)
            # Filter to window
            filtered = []
            for pr in prs:
                merged_at = pr.get("mergedAt", "")
                if merged_at and merged_at >= since_str:
                    filtered.append(
                        {
                            "number": pr["number"],
                            "title": pr["title"],
                            "merged_at": merged_at,
                            "additions": pr.get("additions", 0),
                            "deletions": pr.get("deletions", 0),
                            "changed_files": pr.get("changedFiles", 0),
                        }
                    )
            if filtered:
                all_prs[repo_name] = {
                    "count": len(filtered),
                    "total_additions": sum(p["additions"] for p in filtered),
                    "total_deletions": sum(p["deletions"] for p in filtered),
                    "prs": filtered,
                }
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            continue
    return all_prs


def gather_learning_reports(window_hours, session_ids):
    """Gather learning artifacts generated during the window.

    Two sources (unioned):
      1. LEGACY: ~/.claude/session-transcripts/<ts>-<sid>.md files matched to
         session_ids. Kept for backward compat; mostly unused since March 2026.
      2. MODERN (2026-04-21 retro fix): git log of `distill:`/`capture:` commits
         in the window across the learning repos (.claude, knowledge-base).
         This matches what /retro>distill and /retro>capture actually produce.

    Returns a dict with two sub-keys:
      {
        "session_reports": {session_id: {file, summary, entries_written}},
        "commits": {repo: [{sha, subject, date, kind}]},
      }
    """
    import subprocess

    session_reports = {}
    try:
        transcripts_entries = os.listdir(TRANSCRIPTS_DIR) if TRANSCRIPTS_DIR.exists() else []
    except OSError:
        transcripts_entries = []

    for fname in transcripts_entries:
        if not fname.endswith(".md"):
            continue
        base = fname[:-3]  # strip .md
        m = FILENAME_RE.match(base + ".jsonl")
        if not m:
            continue
        session_id = m.group(6)
        if session_id not in session_ids:
            continue
        filepath = TRANSCRIPTS_DIR / fname
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n")
            summary_lines = []
            entries_written = []
            in_entries = False
            for line in lines:
                if line.startswith("# ") or line.startswith("## "):
                    in_entries = "entries" in line.lower() or "written" in line.lower()
                    if not in_entries:
                        summary_lines.append(line)
                elif in_entries and line.strip().startswith("-"):
                    entries_written.append(line.strip())
                elif not in_entries and line.strip():
                    summary_lines.append(line)
            session_reports[session_id] = {
                "file": fname,
                "summary": "\n".join(summary_lines),
                "entries_written": entries_written,
            }
        except OSError:
            continue

    # Modern source: git log for distill/capture commits in the window.
    since = f"{int(window_hours)} hours ago"
    learning_repos = [
        (str(Path.home() / ".claude"), ["distill", "retro"]),
        (str(Path.home() / "Documents" / "knowledge-base"), ["capture"]),
    ]
    commits_by_repo = {}
    for repo_path, kinds in learning_repos:
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            continue
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "log",
                    f"--since={since}",
                    "--pretty=format:%h|%aI|%s",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
            )
            if result.returncode != 0:
                continue
        except (subprocess.TimeoutExpired, OSError):
            continue

        repo_name = repo_path.rsplit("/", 1)[-1]
        entries = []
        for line in result.stdout.strip().split("\n"):
            if not line or "|" not in line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            sha, date, subject = parts[0], parts[1], parts[2]
            subj_lower = subject.lower()
            matched_kind = None
            for kind in kinds:
                # Match "distill:", "distill(scope):", "chore(distill):", etc.
                if re.match(rf"^(\w+\()?{kind}[:(]\s*", subj_lower) or subj_lower.startswith(
                    f"{kind}: "
                ) or subj_lower.startswith(f"{kind}("):
                    matched_kind = kind
                    break
                if f"({kind})" in subj_lower:
                    matched_kind = kind
                    break
            if matched_kind:
                entries.append(
                    {"sha": sha, "date": date, "subject": subject, "kind": matched_kind}
                )
        if entries:
            commits_by_repo[repo_name] = entries

    return {
        "session_reports": session_reports,
        "commits": commits_by_repo,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract metrics from Claude Code session transcripts."
    )
    parser.add_argument(
        "--window",
        type=float,
        default=48,
        help="Time window in hours to look back (default: 48)",
    )
    parser.add_argument(
        "--focus",
        type=str,
        default=None,
        help="Optional domain/keyword filter for sessions",
    )
    parser.add_argument(
        "--depth",
        choices=["shallow", "deep"],
        default="deep",
        help="Analysis depth: shallow (errors only) or deep (friction score, classifications)",
    )
    args = parser.parse_args()

    deep = args.depth == "deep"

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.window)

    candidates = []

    # Source 1: Legacy session-transcripts/ (timestamp-named files)
    if TRANSCRIPTS_DIR.exists():
        for fname in os.listdir(TRANSCRIPTS_DIR):
            if not fname.endswith(".jsonl"):
                continue
            ts = parse_filename_timestamp(fname)
            if ts and ts >= cutoff:
                candidates.append(TRANSCRIPTS_DIR / fname)

    # Source 2: Project-level JSONL (UUID-named, same record format)
    if PROJECTS_DIR.exists():
        cutoff_local = datetime.now() - timedelta(hours=args.window)
        for fpath in PROJECTS_DIR.glob("*.jsonl"):
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
            if mtime >= cutoff_local:
                candidates.append(fpath)

    if not candidates:
        result = {"error": f"No transcripts found in the last {args.window:.0f}h"}
        print(json.dumps(result, indent=2))
        return

    candidates.sort(key=lambda p: p.stat().st_mtime)

    # Deduplicate: keep only the latest file per session ID
    by_session_id = {}
    for filepath in candidates:
        m = FILENAME_RE.match(filepath.name)
        if m:
            session_id = m.group(6)
        else:
            # Project-level files use UUID names; use stem as session ID
            session_id = filepath.stem
        by_session_id[session_id] = filepath
    candidates = sorted(by_session_id.values(), key=lambda p: p.stat().st_mtime)

    sessions = []
    for filepath in candidates:
        session_data = extract_session(filepath, deep=deep)
        if session_data is None:
            continue
        if args.focus and not matches_focus(session_data, args.focus):
            continue
        sessions.append(session_data)

    if not sessions:
        if args.focus:
            result = {
                "error": f"No sessions matching focus '{args.focus}' in the last {args.window:.0f}h"
            }
        else:
            result = {
                "error": f"No parseable sessions found in the last {args.window:.0f}h"
            }
        print(json.dumps(result, indent=2))
        return

    aggregates = compute_aggregates(sessions, window_hours=args.window)

    # Gather supplementary data (deep mode only)
    git_commits = {}
    pr_data = {}
    learning_reports = {}
    if deep:
        session_ids = {s["session_id"] for s in sessions}
        git_commits = gather_git_commits(args.window)
        pr_data = gather_pr_data(args.window)
        learning_reports = gather_learning_reports(args.window, session_ids)

    result = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": args.window,
        "depth": args.depth,
        "focus": args.focus,
        "aggregates": aggregates,
        "sessions": sessions,
        "git_commits": git_commits,
        "pr_data": pr_data,
        "learning_reports": learning_reports,
    }

    output_json = json.dumps(result, indent=2)
    print(output_json)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"extract-{today}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_json)
        f.write("\n")


if __name__ == "__main__":
    main()
