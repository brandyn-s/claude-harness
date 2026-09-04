"""SubagentStop hook - surfaces agent work and captures learnings.

Fires when any Task tool subprocess finishes. Prints a visibility notice
and scans output for learning markers to auto-route to topic files.
"""
import hashlib
import os
import subprocess
import sys

if sys.platform == "win32":
    import ctypes
    _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if _hwnd:
        ctypes.windll.user32.ShowWindow(_hwnd, 0)
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Atomic write helper
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from atomic_write import atomic_write

# Windows defaults stderr to cp1252; reconfigure to utf-8 so any non-ASCII in
# stderr/stdout (e.g. an em-dash in a block message) won't corrupt callers that
# decode as UTF-8 (pytest conftest.run_hook, Claude Code).
try:
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

# TOPICS_DIR is env-overridable so the test suite can point captures at a
# tmp dir instead of polluting the real topic files. Running these tests
# locally on Windows previously appended [auto-captured] entries to real
# topics, because run_hook does not override HOME.
TOPICS_DIR = Path(
    os.environ.get("CLAUDE_TOPICS_DIR")
    or (Path.home() / ".claude" / "agent-memory" / "topics")
)

# Patterns that indicate the agent learned something worth capturing
LEARNING_MARKERS = re.compile(
    r"\[observed\]|\[confirmed\]|I learned that|Adding to (?:topic |persistent )?memory",
    re.IGNORECASE,
)

# Reject snippets that are distill/capture/retro skill META-output, not genuine
# domain learnings. [observed]/[confirmed] ARE the distill/capture vocabulary,
# so agent prose ABOUT those skills - lessons tables, routing arrows, retro
# narration, prior auto-captures it re-quotes - trips LEARNING_MARKERS. These
# shapes are unambiguously skill output. Pollution incidents this guards
# against: msgraph.md (2026-05-28), airlock.md / infrastructure.md (60+
# duplicated distill-table rows, 2026-06-07), and a SECOND wave (2026-06-12/13
# slack.md / architecture.md / infrastructure.md) where the agent emitted
# distill/retro analysis in shapes the colon-only tier cell + arrow-to-
# [confirmed] patterns missed: pipe-delimited tier cells (`| T5 |`), routing
# arrows to a tier/skip/SKILL-ROUTED, [observed]/[confirmed] inside a table
# cell (review-learnings checklist rows), and /retro narration.
SKILL_META_OUTPUT = re.compile(
    # distill promote notation: [observed] -> [confirmed] (ASCII + unicode arrow)
    r"(?:->|→)\s*\[confirmed\]"
    # distill routing arrows: → **T5 skip**, -> SKIP, → SKILL-ROUTED (2026-06-12 slack.md)
    r"|(?:->|→)\s*\*{0,2}(?:T[0-5]\b|SKIP\b|SKILL-ROUTED)"
    # distill tier cell, pipe- OR colon-delimited: | T4: , | T5 | (2026-06-12 slack.md)
    r"|\|\s*T[0-5]\s*[|:]"
    # [observed]/[confirmed] INSIDE a table cell = skill analysis table, not
    # prose (2026-06-12 architecture.md review-learnings checklist row)
    r"|\|[^|\n]*\[(?:observed|confirmed)\][^|\n]*\|"
    r"|\*\*Example\s+\d"           # SKILL.md example headers
    # /retro narration: **Postmortem**, Skipped (T5): (2026-06-12 slack.md)
    r"|\*\*Postmortem\*\*|Skipped\s*\(T[0-5]\)"
    r"|###\s*\[auto-captured\]",   # a prior auto-capture (re-capture guard)
    re.IGNORECASE,
)

# Map keywords in learnings to topic files. ORDER MATTERS: specific
# compound keywords precede the generic ones they contain ("code-graph"
# and "msgraph" before "graph") — first match wins in detect_topic.
KEYWORD_TO_TOPIC = {
    "code-graph": "code-graph-dev.md",
    "msgraph": "msgraph.md",
    "crowdstrike": "crowdstrike.md",
    "falcon": "crowdstrike.md",
    "tenable": "tenable.md",
    "airlock": "airlock.md",
    "graph": "msgraph.md",
    "entra": "msgraph.md",
    "ramp": "ramp.md",
    "linear": "linear.md",
    "confluence": "confluence.md",
    "tailscale": "tailscale.md",
    "slack": "slack.md",
    "terraform": "infrastructure.md",
    "ecs": "infrastructure.md",
    "docker": "infrastructure.md",
    "github": "infrastructure.md",
    "powershell": "runbook.md",
    "azure": "runbook.md",
    "skill": "architecture.md",
    "hook": "architecture.md",
    "plugin": "architecture.md",
}


def detect_topic(text):
    """Map learning text to a topic file based on keywords.

    Keywords match on a LEFT word boundary only (not preceded by a word
    char or hyphen): bare-substring matching routed every "code-graph"
    learning to msgraph.md because "graph" is a substring (2026-06-12
    pollution). The right side stays unguarded so plurals still match
    ("skills", "hooks", "graphs"). Compound keys like "code-graph" are
    listed before the generic keys they contain; dict order is the
    priority order.
    """
    lower = text.lower()
    for keyword, topic in KEYWORD_TO_TOPIC.items():
        if re.search(r"(?<![\w-])" + re.escape(keyword), lower):
            return topic
    return None


# Maximum bytes of captured learning text to write to a topic file. Bounds
# the worst case if a learning marker accidentally appears inside a large
# string (e.g., a quoted error message). Prevents the 2026-05-28
# msgraph.md pollution recurrence where a 26 KB hook-event payload was
# appended verbatim.
LEARNING_SNIPPET_MAX_CHARS = 800

# Every entry header used to be the hardcoded literal "Worker learning" -
# indistinguishable across files/dates and useless for later dedup/skim
# (review-learnings 2026-07-03: 7 identically-titled entries across 6
# topic files). Derive a short title from the snippet's own first line
# instead; only fall back to the generic label when that line is too
# short to be informative.
_TITLE_LEADING_NOISE = re.compile(r"^[-*#>\s]+")
_TITLE_TAG_PREFIX = re.compile(r"^\[(?:observed|confirmed)\]\s*", re.IGNORECASE)
_TITLE_MAX_CHARS = 80


def _derive_title(learning):
    """Extract a short descriptive title from a captured learning snippet.

    Falls back to "Worker learning" when the first line yields nothing
    substantive (empty, or too short to be worth distinguishing entries by).
    """
    first_line = learning.strip().split("\n", 1)[0].strip()
    first_line = _TITLE_LEADING_NOISE.sub("", first_line)
    first_line = _TITLE_TAG_PREFIX.sub("", first_line)
    first_line = first_line.replace("**", "").strip()
    if len(first_line) > _TITLE_MAX_CHARS:
        cut = first_line.rfind(" ", 0, _TITLE_MAX_CHARS)
        first_line = first_line[: cut if cut > _TITLE_MAX_CHARS // 2 else _TITLE_MAX_CHARS].rstrip() + "…"
    return first_line if len(first_line) >= 8 else "Worker learning"


def _extract_message_text(entry):
    """Return concatenated assistant-prose text from a transcript JSONL entry,
    or "" for entries that aren't user/assistant text messages.

    Claude Code transcript JSONL has one JSON object per line. Many event
    types - tool_result, hook attachment events, system reminders - embed
    quoted strings that may contain literal "[observed]" / "[confirmed]"
    tokens (from topic-file content loaded by auto-topic-loader.py, for
    example). Those tokens are NOT learnings the agent emitted; they are
    substrings inside another tool's payload.

    Only return text from message.content blocks of type "text" on
    ASSISTANT messages. Excludes tool_use/tool_result blocks, attachment
    events, and USER messages entirely: in a subagent transcript the first
    user message IS the dispatch prompt (skill body + ARGUMENTS), which
    routinely quotes [observed]/[confirmed] vocabulary. Capturing it echoes
    the orchestrator's instructions into topic files as fake "learnings"
    (2026-06-12 msgraph.md pollution: a /ship agent's ARGUMENTS string was
    appended verbatim). Learnings are what the agent SAID, not what it was
    told.
    """
    if not isinstance(entry, dict):
        return ""
    if entry.get("type") != "assistant":
        return ""
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return ""


def _iter_message_texts(transcript):
    """Yield textual message contents from a transcript that may be JSONL
    (one JSON object per line) or plain text.

    JSONL: parse each line; yield only assistant/user text content.
    Plain text: yield the whole transcript once (preserves the existing
    test fixtures that pass `transcript: "[observed] ..."` inline).
    """
    if not transcript:
        return
    looks_like_jsonl = False
    for line in transcript.split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        looks_like_jsonl = True
        text = _extract_message_text(entry)
        if text:
            yield text
    if not looks_like_jsonl:
        yield transcript



# Learning categorization patterns (added 2026-03-20)
STRATEGY_PATTERNS = re.compile(
    r"works? well|succeeded|correct approach|the right way|should use|best practice|"
    r"pattern for|recommended|effective",
    re.IGNORECASE,
)
RECOVERY_PATTERNS = re.compile(
    r"fail|error|broke|wrong|bug|fix|workaround|instead of|not work|"
    r"recover|retry|fallback|corrected|resolved",
    re.IGNORECASE,
)
OPTIMIZATION_PATTERNS = re.compile(
    r"slow|fast|efficien|token|cost|reduc|optimi|improv|better approach|"
    r"instead.*faster|fewer.*calls|batch|parallel",
    re.IGNORECASE,
)

def categorize_learning(text):
    """Classify learning by trajectory type."""
    recovery_score = len(RECOVERY_PATTERNS.findall(text))
    optimization_score = len(OPTIMIZATION_PATTERNS.findall(text))
    strategy_score = len(STRATEGY_PATTERNS.findall(text))

    if recovery_score > strategy_score and recovery_score > optimization_score:
        return "recovery"
    if optimization_score > strategy_score and optimization_score > recovery_score:
        return "optimization"
    return "strategy"

# ──────────────────────────────────────────────────────────────────
# Enforced Layer-D gate (oracle/SPEC.md §"Layer D").
#
# Promotes this hook from advisory to enforcing: if a dispatched fix for
# THIS session is FIX-INEFFECTIVE or INTRODUCED a regression (Layer-D
# trace verdict), block the subagent from finishing (exit 2) instead of
# silently passing. Reads ~/.claude/oracle-trace.jsonl directly (no
# oracle import - the hook can't assume the repo path).
#
# Fail-safe by construction: returns None (no block) on empty session_id,
# missing/unreadable trace, parse errors, or records outside the recent
# window. Attribution is by session_id (the orchestrator exports
# AUDIT_SKILL_ORACLE_SESSION = Claude session id around fix-loop calls);
# without it the gate is inert. "Latest verdict per finding wins" so a
# fix that was re-verified VERIFIED on retry does NOT block.
# ──────────────────────────────────────────────────────────────────
GATE_VERDICTS = ("FIX-INEFFECTIVE", "INTRODUCED")


def _read_trace_tail(path, max_bytes=512_000):
    """Read up to the last max_bytes of the trace, dropping a leading
    partial line. Keeps the gate within the hook's 5s timeout on large
    append-only traces."""
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # discard partial first line
            return f.read()
    except OSError:
        return ""


def check_fix_loop_gate(session_id, now=None):
    """Return a block-reason string if the oracle trace has a Layer-D
    FIX-INEFFECTIVE/INTRODUCED verdict attributed to this session within
    the recent window and not superseded by a later VERIFIED for the same
    finding; else None. Never raises."""
    if not session_id:
        return None
    trace_file = Path(
        os.environ.get("AUDIT_SKILL_ORACLE_TRACE")
        or (Path.home() / ".claude" / "oracle-trace.jsonl")
    )
    if not trace_file.exists():
        return None
    try:
        window = int(os.environ.get("AUDIT_SKILL_ORACLE_GATE_WINDOW", "1800") or "1800")
    except ValueError:
        window = 1800
    now = now or datetime.now(timezone.utc)
    latest: dict = {}  # finding_id -> (ts, verdict, skill)
    try:
        for line in _read_trace_tail(trace_file).splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if rec.get("layer") != "D":
                continue
            inp = rec.get("input") or {}
            if inp.get("session_id") != session_id:
                continue
            try:
                ts = datetime.fromisoformat(rec.get("ts", ""))
            except (ValueError, TypeError):
                continue
            if (now - ts).total_seconds() > window:
                continue
            fid = rec.get("finding_id", "")
            prev = latest.get(fid)
            if prev is None or ts >= prev[0]:
                latest[fid] = (ts, rec.get("verdict", ""), rec.get("skill", "?"))
    except Exception:
        return None  # fail-safe: never block on an internal error

    offending = [(skill, verdict) for (_ts, verdict, skill) in latest.values()
                 if verdict in GATE_VERDICTS]
    if not offending:
        return None
    skills = sorted({s for s, _ in offending})
    verdicts = sorted({v for _, v in offending})
    return (
        f"oracle Layer-D gate: {len(offending)} unresolved fix verdict(s) "
        f"{verdicts} attributed to this session (skills: {', '.join(skills)}). "
        f"A dispatched fix is FIX-INEFFECTIVE or INTRODUCED a regression - "
        f"re-diagnose and re-verify before finishing."
    )


# ──────────────────────────────────────────────────────────────────
# PHASE F: per-subagent git-worktree cleanup (OPT-IN, fail-open).
#
# Complement to pre-agent-dispatch.py's provision_subagent_worktree().
# When SUBAGENT_WORKTREE_ISOLATION=1 was set at dispatch, that hook wrote a
# claim file under ~/.claude/state/subagent-worktree-claims/. On subagent
# stop we look up the claim(s) for this session and:
#   * if the worktree has NO changes vs. its base ref -> GC it (worktree
#     remove + delete the throwaway branch), so unused isolation leaves no
#     residue.
#   * if it HAS commits/changes -> leave it in place and FLAG it (stderr
#     notice) so the orchestrator can merge/ship the branch deliberately.
#
# CRITICAL CONTRACT: gated behind the same env var; when unset, every path
# here is skipped (no claim lookup, no git calls) and stop behavior is
# byte-for-byte identical to before this block. Every failure is swallowed
# (fail-open) — cleanup never blocks or errors a subagent stop.
# ──────────────────────────────────────────────────────────────────
SUBAGENT_WORKTREE_ISOLATION_ENV = "SUBAGENT_WORKTREE_ISOLATION"
_SUBAGENT_CLAIM_DIR = Path.home() / ".claude" / "state" / "subagent-worktree-claims"
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _wt_isolation_enabled():
    val = os.environ.get(SUBAGENT_WORKTREE_ISOLATION_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _git(args, cwd=None, timeout=10):
    try:
        return subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, cwd=cwd, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _worktree_is_unchanged(claim):
    """True only when the worktree has no uncommitted changes AND no commits
    ahead of its base ref. Conservative: any uncertainty -> False (keep it)."""
    wt = claim.get("worktree_path")
    if not wt or not os.path.isdir(wt):
        return False
    status = _git(["status", "--porcelain"], cwd=wt)
    if not status or status.returncode != 0 or status.stdout.strip():
        return False  # dirty or git error -> keep
    base = claim.get("base_ref") or "HEAD"
    # Count commits on the worktree branch not in the base ref.
    rev = _git(["rev-list", "--count", f"{base}..HEAD"], cwd=wt)
    if not rev or rev.returncode != 0:
        return False
    try:
        ahead = int(rev.stdout.strip() or "0")
    except ValueError:
        return False
    return ahead == 0


def cleanup_subagent_worktrees(session_id):
    """Find this session's per-subagent worktree claims and GC unchanged ones,
    flagging changed ones for deliberate merge. No-op unless opt-in env set.
    Never raises."""
    if not _wt_isolation_enabled():
        return
    if not session_id:
        return
    suffix = session_id[:8]
    try:
        if not _SUBAGENT_CLAIM_DIR.exists():
            return
        claim_files = [
            p for p in _SUBAGENT_CLAIM_DIR.iterdir()
            if p.is_file() and p.name.startswith(f"{suffix}-agent-")
            and p.suffix == ".json"
        ]
    except OSError:
        return

    for cf in claim_files:
        try:
            claim = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        wt = claim.get("worktree_path")
        branch = claim.get("branch", "?")
        repo_root = claim.get("repo_root")
        try:
            if _worktree_is_unchanged(claim):
                # GC: remove the worktree and delete the throwaway branch.
                _git(["worktree", "remove", "--force", wt], cwd=repo_root)
                _git(["branch", "-D", branch], cwd=repo_root)
                try:
                    cf.unlink()
                except OSError:
                    pass
                print(
                    f"[SubagentStop] worktree-isolation: GC'd unchanged "
                    f"worktree {wt} (branch {branch}).",
                    file=sys.stderr,
                )
            else:
                # Has changes — leave it and flag for deliberate merge/ship.
                print(
                    f"[SubagentStop] worktree-isolation: worktree {wt} "
                    f"(branch {branch}) has changes — left in place. Review "
                    f"and merge/ship the branch, then `git worktree remove "
                    f"{wt}` to clean up.",
                    file=sys.stderr,
                )
        except Exception:  # noqa: S112, BLE001 -- fail-open per-claim: one bad worktree never aborts the rest
            # fail-open per-claim: one bad worktree never aborts the rest.
            continue


def main():
    try:
        if sys.stdin and not sys.stdin.closed:
            hook_input = json.load(sys.stdin)
        else:
            hook_input = {}
    except Exception:
        hook_input = {}

    agent_type = hook_input.get("agent_type", "unknown-agent")
    session_id = hook_input.get("session_id", "")
    short_id = session_id[:8] if session_id else "?"
    # Claude Code's SubagentStop hook sends `transcript_path` (a file path),
    # not the transcript content directly. Read the file and fall back to
    # the inline `transcript` key for callers (incl. tests) that pass it
    # inline. Defensive: a missing or unreadable file silently yields "".
    transcript = ""
    transcript_path = hook_input.get("transcript_path")
    if transcript_path:
        try:
            transcript = Path(transcript_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            transcript = ""
    if not transcript:
        transcript = hook_input.get("transcript", "") or ""

    # Print visibility notice
    print(
        f"\n[SubagentStop] Agent '{agent_type}' finished (session {short_id}). "
        f"Review any memory writes or file changes above.",
        file=sys.stderr,
    )

    # Scan for learnings in extracted prose only. The transcript may be plain
    # text (existing test harness) or JSONL (Claude Code production format).
    # _iter_message_texts handles both: for JSONL it yields only user/assistant
    # text content, skipping tool_use/tool_result/attachment events whose
    # embedded strings may contain "[observed]"/"[confirmed]" substrings that
    # are NOT agent learnings (e.g., the auto-topic-loader hook injects
    # topic-file content as additionalContext, and topic files literally
    # contain those tokens). Bounded snippet length defends against the
    # residual case where a marker token does appear in legitimate text near
    # other multi-KB content.
    learnings = []
    if transcript:
        for prose in _iter_message_texts(transcript):
            if not LEARNING_MARKERS.search(prose):
                continue
            prose_lines = prose.split("\n")
            for i, line in enumerate(prose_lines):
                if LEARNING_MARKERS.search(line):
                    snippet = "\n".join(prose_lines[i : i + 3]).strip()
                    # Skip distill/capture skill meta-output (tables, examples,
                    # promote-notation, prior auto-captures) - not real learnings.
                    if snippet and not SKILL_META_OUTPUT.search(snippet):
                        learnings.append(snippet[:LEARNING_SNIPPET_MAX_CHARS])
            if len(learnings) >= 3:
                break

    if learnings:
        # Route each learning to appropriate topic file
        for learning in learnings[:3]:  # cap at 3 per agent run
            topic = detect_topic(learning)
            if topic:
                topic_path = TOPICS_DIR / topic
                if topic_path.exists():
                    try:
                        today = datetime.now().strftime("%Y-%m-%d")
                        title = _derive_title(learning)
                        entry = (
                            f"\n### [auto-captured] {title} ({today})\n"
                            f"{learning}\n"
                            f"- Source: {agent_type} agent (session {short_id})\n"
                        )
                        # Read existing content, append, write atomically
                        existing = topic_path.read_text(encoding="utf-8")
                        # Dedup: every SubagentStop re-reads the full (growing)
                        # transcript, so without this the same snippet is
                        # re-appended on each stop - the 60+ duplicate blocks in
                        # the 2026-06-07 airlock.md pollution. Skip if present.
                        if learning.strip() and learning.strip() in existing:
                            continue
                        atomic_write(topic_path, existing + entry)
                        # RT-008: Update integrity checksum after legitimate write
                        checksum_path = Path.home() / ".claude" / "hooks" / "topic-checksums.json"
                        if checksum_path.exists():
                            try:
                                with open(checksum_path, "r", encoding="utf-8") as cf:
                                    checksums = json.load(cf)
                                with open(topic_path, "rb") as tf:
                                    checksums[topic] = hashlib.sha256(tf.read()).hexdigest()
                                atomic_write(checksum_path, json.dumps(checksums, indent=2))
                            except Exception:  # noqa: S110, BLE001 -- fail-open: checksum bookkeeping must never fail the capture
                                pass  # fail-open: checksum bookkeeping only
                        print(
                            f"[SubagentStop] Captured learning -> {topic}",
                            file=sys.stderr,
                        )
                    except Exception:  # noqa: S110, BLE001 -- fail-open: learning capture is best-effort and never affects the stop outcome
                        pass  # fail-open: best-effort capture

    # PHASE F (OPT-IN, fail-open): GC/flag per-subagent worktrees provisioned
    # by pre-agent-dispatch.py for this session. Runs before the Layer-D gate
    # so unchanged-worktree GC happens even if the gate later blocks. No-op
    # when SUBAGENT_WORKTREE_ISOLATION is unset — default behavior unchanged.
    try:
        cleanup_subagent_worktrees(session_id)
    except Exception:  # noqa: S110, BLE001 -- fail-open: cleanup never affects the stop outcome
        pass  # fail-open: cleanup never affects stop outcome

    # Enforced Layer-D gate: block completion if a dispatched fix for this
    # session is unresolved-ineffective or introduced a regression.
    # Fail-safe - no session attribution (orchestrator didn't export
    # AUDIT_SKILL_ORACLE_SESSION) means no block.
    try:
        block_reason = check_fix_loop_gate(session_id)
    except Exception:
        block_reason = None
    if block_reason:
        print(f"[SubagentStop] BLOCK: {block_reason}", file=sys.stderr)
        sys.exit(2)
    # A pass emits nothing: {"result": "pass"} is not a documented shape and
    # never reached the model (live-probed 2026-09-03).


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
