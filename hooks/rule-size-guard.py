"""PreToolUse:Write|Edit hook: enforce per-file and aggregate rule budgets.

WHY: ambient rules under ~/.claude/rules/ are loaded into every session.
Files >40K chars trigger a Claude Code performance warning. Periodic
manual descopes recurred (2026-05-18, 2026-05-19, 2026-05-21) because
/distill appends incidents without checking the file's current size
against a budget. This hook moves the check from "discovered hours
later by the warning banner" to "refused at write-time" so the
editorial choice (extract older content, shrink the addition, or move
to a topic file) happens in the moment instead of in a periodic
descope.

Per-file thresholds:
  WARN  35,000 UTF-8 bytes  advisory stderr message, write allowed
  BLOCK 38,000 UTF-8 bytes  exit 2 with extraction guidance
  HARD  40,000 UTF-8 bytes  the Claude Code performance-warning floor

Aggregate always-loaded corpus thresholds:
  WARN 225,000 UTF-8 bytes  advisory stderr message, write allowed
  BLOCK 250,000 UTF-8 bytes exit 2 when a write makes the corpus larger

The aggregate count includes only top-level ``rules/*.md`` files without
``paths:`` frontmatter. Path-scoped rules and ``rules/incidents/`` do not
consume every session.

BLOCK gates on "over budget AND non-decreasing", not on projected size alone.
A NON-INCREASING edit to an already-over file is the prescribed remedy
(extract narratives to rules/incidents/, leave a pointer), so refusing it would
make the fix reachable only through the override. Such an edit is ALLOWED with
an advisory naming how far is left. See `check()` for the measured incident.

Bypass: CLAUDE_RULE_SIZE_OVERRIDE=1 (intended for an explicit "I know
this addition is load-bearing and I'll descope later" decision).

Scope: only fires on Write|Edit when file_path resolves under
~/.claude/rules/*.md. Does not gate topic files, skills, or hooks.
"""

import json
import os
import sys
from pathlib import Path

from rule_context_budget import (
    BLOCK_BYTES as CORPUS_BLOCK_THRESHOLD,
)
from rule_context_budget import (
    BUDGET_LEDGER_RELPATH,
    RuleContextBudgetError,
    load_ambient_budget,
    unconditional_rule_bytes,
)
from rule_context_budget import (
    WARN_BYTES as CORPUS_WARN_THRESHOLD,
)

# On Windows, sys.stderr/stdout default to cp1252 encoding. The BLOCK
# message at ~line 130 contains an em-dash (—), which cp1252 encodes
# to byte 0x97 — a byte that fails utf-8 decode in the test harness
# (`subprocess.run(..., text=True, encoding='utf-8')`). Force utf-8 so
# the em-dash and any future non-ASCII typography survives the cross-
# encoding round-trip. Same pattern as _check_orphans.py:29.
sys.stderr.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

WARN_THRESHOLD = 35000
BLOCK_THRESHOLD = 38000
HARD_LIMIT = 40000


def _is_claude_config_root(root: Path) -> bool:
    """True when `root` looks like a claude-config checkout (or the deployed dir).

    Discriminator must match the deployed path, the main checkout, AND every
    worktree, without matching an unrelated repo that happens to ship a
    `rules/` directory.
    """
    return (root / ".claude-plugin").is_dir() or (root / "settings.json").is_file()


def rules_dir_for_path(path_str: str) -> Path | None:
    """Return the owning claude-config rules directory for a guarded path."""

    if not path_str:
        return None
    try:
        p = Path(path_str).expanduser().resolve()
    except (OSError, ValueError):
        return None
    if p.suffix != ".md":
        return None

    # Fast path: the deployed directory. Behaviour here is unchanged.
    rules_dir = Path("~/.claude/rules").expanduser().resolve()
    try:
        p.relative_to(rules_dir)
    except ValueError:
        # Not the deployed path. Recognise a rules file by its repo-relative
        # SHAPE instead of an absolute prefix: `<root>/rules/<name>.md` where
        # `<root>` is a claude-config checkout. Without this, the guard is a
        # no-op for rule authoring — worktree-by-default MANDATES that rule
        # edits happen in a worktree, and worktree-enforcement.py BLOCKS them
        # in the ~/.claude main checkout on a non-main branch. The guard gated
        # the one path we forbid and ignored the paths we require, which is how
        # several rules drifted past 38,000 B unchecked (measured 2026-07-30:
        # verify-effectiveness 37,953 -> 38,405 and platform-constraints
        # 37,837 -> 38,029, both crossing BLOCK with no guard output).
        rules_dir = None
        for ancestor in p.parents:
            if ancestor.name == "rules" and _is_claude_config_root(ancestor.parent):
                rules_dir = ancestor
                break
        if rules_dir is None:
            return None

    # Skip incidents/ subdirectory — that's the extraction target, not
    # an ambient rule file. The size budget there is independent.
    try:
        p.relative_to(rules_dir / "incidents")
        return None
    except ValueError:
        return rules_dir


def is_rules_file(path_str: str) -> bool:
    return rules_dir_for_path(path_str) is not None


def current_byte_size(file_path: str) -> int:
    try:
        return Path(file_path).expanduser().stat().st_size
    except (OSError, FileNotFoundError):
        return 0


def project_edit_text(file_path: str, old: str, new: str, replace_all: bool) -> str:
    """Return complete projected text or fail closed when it is unreadable."""

    try:
        # Path.read_text() uses universal-newline translation and silently turns
        # CRLF into LF. That can make a growing Edit look smaller than the raw
        # file measured by stat(), incorrectly activating the reducing-edit
        # exemption. Decode the raw bytes so projected and current sizes share
        # the same representation.
        content = Path(file_path).expanduser().read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuleContextBudgetError(f"cannot read rule for Edit: {file_path}") from exc
    if not old:
        return content + new
    if replace_all:
        return content.replace(old, new)
    return content.replace(old, new, 1)


def project_edit_size(file_path: str, old: str, new: str, replace_all: bool) -> int:
    return len(project_edit_text(file_path, old, new, replace_all).encode("utf-8"))


def check(hook_input):
    """Returns (exit_code, stderr_payload, stdout_payload)."""
    if os.environ.get("CLAUDE_RULE_SIZE_OVERRIDE") == "1":
        return (0, None, None)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    file_path = tool_input.get("file_path", "")
    rules_dir = rules_dir_for_path(file_path)
    if rules_dir is None:
        return (0, None, None)

    if tool_name == "Write":
        projected_content = tool_input.get("content", "")
        projected = len(projected_content.encode("utf-8"))
    elif tool_name == "Edit":
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        replace_all = tool_input.get("replace_all", False)
        try:
            projected_content = project_edit_text(file_path, old, new, replace_all)
        except RuleContextBudgetError as exc:
            return (2, f"[rule-size-guard] BLOCKED: {exc}", None)
        projected = len(projected_content.encode("utf-8"))
    else:
        return (0, None, None)

    name = Path(file_path).name
    current = current_byte_size(file_path)

    # A NON-INCREASING edit to an already-over-budget file is the REMEDY, not a
    # violation — blocking it makes the prescribed fix (extract narratives to
    # rules/incidents/, leave a pointer) unappliable except via the override,
    # which turns a remedy into a bypass. Gate on "exceeds budget AND makes it
    # worse", never on projected size alone.
    #
    # Measured 2026-07-30: a -2,508 B extraction edit on verify-before-assuming.md
    # (42,670 -> 40,162) was refused with "would push ... to 40,162 chars" while
    # it was LOWERING the file. Both remaining over-BLOCK rules were frozen to
    # hand-edits, which is exactly the pair /distill appends GUARDs to most.
    # Before the #1799 worktree scoping this was masked (the guard only matched
    # the deployed ~/.claude/rules path, which worktree-by-default forbids
    # editing), so correcting the scope surfaced the latent bug.
    #
    # Only the DEPLOYED file's size is a real budget fact, so a file that does
    # not exist yet (current == 0) can never be "reducing".
    reducing = current > 0 and projected <= current

    messages: list[str] = []

    if projected > BLOCK_THRESHOLD and not reducing:
        msg = (
            f"[rule-size-guard] BLOCKED: write would push {name} to "
            f"{projected:,} bytes "
            f"(block at {BLOCK_THRESHOLD:,}, hard limit {HARD_LIMIT:,}).\n\n"
            f"Options:\n"
            f"  1. Extract older INCIDENT narratives to "
            f"~/.claude/rules/incidents/{name} and leave a one-line "
            f"pointer in the rule.\n"
            f"  2. Move advisory reference material to a topic file in "
            f"~/Documents/knowledge-base/topics/.\n"
            f"  3. Shrink the proposed addition.\n"
            f"  4. If load-bearing and must land now: set "
            f"CLAUDE_RULE_SIZE_OVERRIDE=1 — but plan a descope before "
            f"the next /distill."
        )
        return (2, msg, None)

    if projected > BLOCK_THRESHOLD:
        # Reducing, but still over budget: allow it and say how far is left, so
        # a multi-step extraction gets feedback instead of a refusal.
        messages.append(
            f"[rule-size-guard] ALLOWED (reducing): {name} "
            f"{current:,} -> {projected:,} bytes "
            f"({projected - current:+,}). Still over block "
            f"{BLOCK_THRESHOLD:,} by {projected - BLOCK_THRESHOLD:,} — keep "
            f"extracting to rules/incidents/{name}."
        )
    elif projected > WARN_THRESHOLD:
        verb = "leaves" if reducing else "pushes"
        messages.append(
            f"[rule-size-guard] WARN: write {verb} {name} at "
            f"{projected:,} bytes (warn {WARN_THRESHOLD:,}, block "
            f"{BLOCK_THRESHOLD:,}). Consider extracting older incidents "
            f"to rules/incidents/{name} before the next /distill."
        )
    target = Path(file_path).expanduser().resolve()
    if target.parent == rules_dir.resolve():
        try:
            current_corpus = unconditional_rule_bytes(rules_dir)
            projected_corpus = unconditional_rule_bytes(
                rules_dir, {target: projected_content}
            )
        except RuleContextBudgetError as exc:
            return (
                2,
                f"[rule-size-guard] BLOCKED: could not measure the always-loaded "
                f"rule corpus without undercounting: {exc}",
                None,
            )
        delta = projected_corpus - current_corpus

        # ---- delta gate ------------------------------------------------------
        # The absolute ceilings below bound the corpus; they do not bound its
        # GROWTH. Growth is what produced 13 cap-repair PRs, because a ceiling is a
        # cliff: repairs converge to just under it and the next append breaches it.
        # The ledger's DERIVED ceiling (baseline + sum of justified entries) is the
        # operative bound, and it is checked before the absolute ones so the author
        # sees the real constraint rather than a distant one.
        # rules_dir.parent IS the claude-config root: the ancestor walk above only
        # accepts a `rules` dir whose parent passes _is_claude_config_root, so this
        # resolves correctly for the deployed dir, the main checkout, and every
        # worktree without a second discriminator.
        # ADVISORY here, HARD in CI -- a deliberate asymmetry. The deployed ~/.claude
        # is shared by every concurrent session and can sit behind origin/main for
        # days, so it may legitimately lack a ledger this change only just introduced.
        # Blocking there would refuse EVERY rule edit on a stale checkout: the >10%
        # block-rate DoS verify-effectiveness forbids. Enforcement lives in
        # scripts/test_context_policy_contracts.py, which runs where the ledger
        # provably exists and RAISES without it -- so the gate cannot be disabled by
        # deleting the file; doing so reds CI.
        #
        # ABSENT is silent, MALFORMED warns. Warning on every rule write in a
        # not-yet-synced checkout is pure alarm fatigue; a ledger that EXISTS but is
        # broken is a real defect and is said out loud.
        ledger_path = rules_dir.resolve().parent / BUDGET_LEDGER_RELPATH
        budget = None
        if ledger_path.is_file():
            try:
                budget = load_ambient_budget(ledger_path)
            except RuleContextBudgetError as exc:
                messages.append(
                    "[rule-size-guard] WARN: ambient budget ledger is present but "
                    f"unusable, so the growth gate is not evaluated here ({exc}). "
                    "CI still enforces it."
                )

        if budget is not None and projected_corpus > budget.allowed_bytes and delta > 0:
            over = projected_corpus - budget.allowed_bytes
            messages.append(
                "[rule-size-guard] BLOCKED: this write grows the always-loaded rule "
                f"corpus {current_corpus:,} -> {projected_corpus:,} ({delta:+,}), "
                f"which is {over:,} over the ledger ceiling of "
                f"{budget.allowed_bytes:,}.\n"
                "The ambient tier is net-zero-growth by default. Cheapest resolutions "
                "first:\n"
                "  1. relocate >= this many bytes out of ambient in the SAME change "
                "(rules/incidents/<name>.md or docs/rule-reference/<name>.md cost "
                "nothing until read)\n"
                "  2. route the lesson to agent-memory/topics/ or a skill step instead\n"
                "  3. add paths: frontmatter if the rule is genuinely path-scoped\n"
                f"  4. only if none fit, append a justified entry to "
                f"{BUDGET_LEDGER_RELPATH} naming the bytes and why they must be ambient"
            )
            return (2, "\n\n".join(messages), None)

        if projected_corpus > CORPUS_BLOCK_THRESHOLD and delta > 0:
            messages.append(
                "[rule-size-guard] BLOCKED: write would grow the always-loaded "
                f"rule corpus from {current_corpus:,} to {projected_corpus:,} "
                f"bytes ({delta:+,}); aggregate block is "
                f"{CORPUS_BLOCK_THRESHOLD:,}. Compact, path-scope, or move "
                "detail into a skill/reference before adding ambient context."
            )
            return (2, "\n\n".join(messages), None)

        if projected_corpus > CORPUS_BLOCK_THRESHOLD and delta < 0:
            messages.append(
                "[rule-size-guard] ALLOWED (aggregate reducing): always-loaded "
                f"rule corpus {current_corpus:,} -> {projected_corpus:,} bytes "
                f"({delta:+,}). It remains "
                f"{projected_corpus - CORPUS_BLOCK_THRESHOLD:,} bytes over the "
                "aggregate block; keep compacting or path-scoping."
            )
        elif projected_corpus > CORPUS_WARN_THRESHOLD and delta != 0:
            direction = "reduces" if delta < 0 else "grows"
            messages.append(
                f"[rule-size-guard] WARN: write {direction} the always-loaded "
                f"rule corpus to {projected_corpus:,} bytes ({delta:+,}; warn "
                f"{CORPUS_WARN_THRESHOLD:,}, block {CORPUS_BLOCK_THRESHOLD:,})."
            )

    return (0, "\n\n".join(messages) if messages else None, None)


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)
    code, stderr_msg, stdout_msg = check(hook_input)
    if stderr_msg:
        sys.stderr.write(stderr_msg + "\n")
    if stdout_msg:
        print(stdout_msg)
    sys.exit(code)


if __name__ == "__main__":
    main()
