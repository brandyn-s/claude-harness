"""Auto-fix long-running Bash commands piped to filtering tools that buffer stdout.

Generated from staged spec: hooks/staged/bash-tail-buffering-guard.spec.md (v1)
Refined from: hooks/staged/bash-tail-buffering-guard-v2.spec.md (v2)
Installed by /ship-hook on 2026-05-10 (v1), refined 2026-05-10 (v2).

v8 (2026-07-31, /ship-hook) consumed two staged specs, both measured over a
49,542-command historical Bash corpus before install:

  * trailing-command-swallows-verdict-exit -> check_trailing_status_swallow().
    A THIRD disjoint shape: a command whose EXIT STATUS is the verdict, followed
    by `;`-chained commands that replace it. No pipe and no `&&`, so neither
    check() nor check_git_gating() sees it. 5 recorded incidents (#1788,
    #1785 x2, #1818, #1819) — the last two reported a FALSE merge confirmation
    to the user. Measured 607 fires (1.225%).
    NARROWED vs the spec: `pytest` / `python3 -m unittest` were dropped because
    they failed test_allows_grep_on_log_named_after_pytest, which pins the
    routine pytest-then-grep idiom as allowed. That took the rate from 3.547%
    to 1.225% and lost no measured coverage (all 5 incidents were the merge
    verifier). See VERDICT_COMMANDS before adding an entry back.

  * tail-guard-wrapper-producer-detection -> WRAPPER_PREFIXES skipping in
    _producer_is_long_running(). A wrapped producer (`timeout 280 python3 x.py`)
    resolved to the WRAPPER's basename and was classified SHORT, so the guard
    never fired on a producer it was built to catch. True-delta replay against a
    wrapper-blind predicate: 324 newly fire (0.654%). The spec's 0.499%
    "ceiling" measured a different thing (it counted VAR=value skips), so this
    is the accurate figure. Token-anchoring is preserved — only the starting
    index moves, and only at the COMMAND position.

  Both mutation-verified: un-wiring the check, removing the `exit $?` exemption,
  emptying WRAPPER_PREFIXES, and dropping the post-wrapper bounds re-check are
  each caught by the test written for them.

v2 detection: parse command into pipe segments. Fire only when the FIRST
segment matches a long-running signal AND the LAST segment is a buffering
filter (tail/head/grep without --line-buffered).

This eliminates false positives observed in v1 where a downstream pipe
with `tail -N` triggered the hook because an UNRELATED upstream segment
happened to mention `python` / `go` / `bench/` in arguments or paths.

v3 detection (2026-06-12): producer matching is TOKEN-ANCHORED at the
command position instead of substring-anywhere. v2's substring signals
still matched long-running names inside file paths in the producer's own
arguments — e.g. `grep -n PAT /tmp/claude/pytest-e2e-fh.log | head -30`
blocked because "pytest" appears in the LOG FILENAME while the actual
producer was an instant grep on a static file. Replay over all 3,085
transcript Bash commands (69 sessions, 2026-06-12 recurrence recompute):
token anchoring kept 55/59 of v2's blocks; the 4 dropped are confirmed
false positives (path-substring matches plus one heredoc-sanitizer
artifact), with zero true positives lost. v3 also splits chained
producers on newlines (v2 split only on && / || / ;), so
`cd x<NL>pytest | head` no longer evades the producer check.

v4 action (2026-06-13): BLOCK promoted to AUTO-REWRITE for tail/grep
consumers. The detection above is unchanged; only the response changes.
When the consumer is `tail`/`grep` (the producer must run to completion
anyway), rewrite `PRODUCER | filter` -> `PRODUCER > FILE 2>&1; cat FILE |
filter` so the producer's full output is captured to a file and then
filtered — buffering-correct AND inspectable, at zero correction turns.
`head` consumers are NEVER rewritten and still BLOCK: `producer | head -N`
intends early termination (head closes the pipe -> producer gets SIGPIPE
after N lines), and a file-redirect rewrite would run the full producer,
a real regression for streaming/slow producers. Un-rewritable shapes
(quoted pipes, existing producer-side redirect) also block; chained
commands AFTER the filter (`| tail -5; echo done`) ARE rewritten — they
sit downstream of the producer and are preserved byte-for-byte.
The rewrite is provably lossless or it falls back to the v3 block — never
worse than v3. Rationale: 85 fires in the 2026-06-10..12 window, each a
+1 correction turn; the rewrite removes that tax for the safe majority.

v5 action (2026-06-23): `head` consumers PROMOTED from block to AUTO-REWRITE.
The v4 blanket head-refusal ("head intends early termination → SIGPIPE → a
run-to-completion redirect is a regression") is correct for a STREAMING producer
but does NOT apply to this guard's fire-set: `_producer_is_long_running` only
matches BATCH commands (pytest/cargo/go test/npm/docker run/git clone/python*/
index_repository), every one of which runs to completion regardless — head saves
them no work (unlike `cat hugefile | head`, where cat is not a long-running
producer and so never reaches this guard). So `batch-producer | head -N` is
rewritten to `producer > FILE 2>&1\\ncat FILE | head -N` (buffering-safe; head
reads the completed file). Genuinely un-rewritable shapes (quoted-pipe count
mismatch, producer with an existing `>` redirect) still BLOCK. Measured: `head`
was 142 of 412 fires in the audit window — the dominant residual friction this
closes. Test suite updated (3 head-block tests → head-rewrite; new
test_blocks_unrewritable_producer_redirect keeps the block path covered); 28/28 pass.

Efficacy measurement (2026-07-24, replay over 11,814 historical Bash commands):
the guard FIRES on 424 commands — 310 (73%) AUTO-REWRITTEN at zero friction,
114 BLOCKED. Of the 114 blocks: 53 quoted-pipe-mismatch, 46 producer-already-
redirects, 15 empty-segment. Manual read of the block set: only ~2 are true
false-positives (a `producer 2>&1 | tail` on statement 1 whose pipe-count is
inflated by a LATER heredoc's internal `|`); the other ~112 are conservative-
CORRECT — multi-statement commands where a positional rewrite would risk
corrupting sibling statements, or heredoc-writes (`cat > f <<EOF`) with no real
producer|filter pipe to fix. So the 2026-07-24 retro's "widen the auto-rewrite
to quoted-pipe shapes" is REFUTED by measurement: widening for a ~1.8% gain
would touch the delicate reconstruction path for negative expected value. The
guard is working as intended; the residual blocks are legitimate and the block
message already names the redirect-to-file / run_in_background fix. Do NOT widen.

3rd recurrence promotion (2026-03-16, 2026-05-02, 2026-05-10) from prose
rule in platform-constraints.md to structural enforcement.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

TAIL_REMEDY = (
    "Cheapest fix: ask the PRODUCER for less (`gh pr list --limit 5`, `grep -m 5`, `sed -n '1,5p' FILE`), or redirect to a file and read that."
)


_SESSION_ID = ""  # set from the payload in main(); read by _repeat_note


def _repeat_note(hook_name, remedy=""):
    """Escalation text for the 2nd+ block from this guard in one session.

    Defensive by construction: a guard must never fail to block because its
    telemetry import broke, so every error path returns an empty string.
    """
    try:
        import os
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from manifest_metrics import repeat_escalation
        return repeat_escalation(hook_name, remedy, session_id=_SESSION_ID or None)
    except Exception:
        return ""


# Command basenames that mark a long-running producer when they appear at
# the COMMAND position (after env-assignment prefixes like PYTHONPATH=.).
BARE_PRODUCERS = {"pytest", "cargo"}
# Basenames that are long-running only with one of these subcommands.
SUBCOMMAND_PRODUCERS = {
    "go": {"run", "test"},
    "npm": {"run", "test"},
    "docker": {"run"},
    "git": {"clone"},
}
# Long-running subcommands that hide behind wrapper binaries (e.g.
# `codebase-memory-mcp cli index_repository '{...}'`): matched as an exact
# argv TOKEN, which cannot match inside a filename, unlike v2's substring.
TOKEN_PRODUCERS = {"index_repository"}
# NOTE: `bench/` and `eval_` were dropped in v2 (path patterns), and v3
# dropped substring matching entirely: a signal must be the producer's
# command token, never a substring of its arguments or file paths (the
# pytest-in-filename false-positive class, 2026-06-12).
# Binaries that WRAP the real producer. Skipped only at the COMMAND position,
# so a `timeout` appearing as an ARGUMENT (`grep timeout app.log | head`) never
# shifts the index — that distinction is what keeps v3's token-anchoring intact.
WRAPPER_PREFIXES = {"timeout", "nohup", "env", "stdbuf", "time", "nice", "ionice"}

# Commands whose EXIT STATUS is their verdict — a trailing `;`-chained command
# silently replaces it.
#
# NARROWED AT INSTALL (2026-07-31) vs the staged spec, which also listed `pytest`
# and `python3 -m unittest`. Those two are the broadest and they FAILED the
# existing regression suite: `test_allows_grep_on_log_named_after_pytest` pins the
# routine "run pytest > log; echo exit=$?; grep the log" idiom as ALLOWED. That
# command genuinely does swallow pytest's status, but blocking a pinned, common
# idiom is not what this guard is for — and the spec itself names narrowing this
# tuple as the FIRST lever under felt friction, explicitly over raising the bar.
# All five recorded incidents of the class (#1788, #1785 x2, #1818, #1819) were
# `pr-merge-verified.py`, so the narrowed set loses no measured coverage.
# Re-measure the fire rate before adding an entry back.
VERDICT_COMMANDS = (
    r"pr-merge-verified\.py",
    # `gh pr merge` added 2026-08-22 on two same-day measured incidents: a
    # `gh pr merge --auto ... | tail -1` masked a GraphQL
    # enablePullRequestAutoMerge rejection as rc=0 (KB #1590 arm), and the
    # identical shape earlier reported "auto-merge armed" for a PR that had
    # actually merged INSTANTLY (claude-config #2050) — both verdicts were
    # the filter's, not gh's. Per this tuple's own governance: entries are
    # added on measured incidents only.
    r"gh\s+pr\s+merge",
    r"terraform\s+(plan|apply)",
    r"cargo\s+(test|build)",
    r"npm\s+(test|run\s+build)",
)
# Same alternation, but used with .match() so it can only hit at the COMMAND
# position. `\b` stops `terraform planet` from matching `terraform plan`.
_VERDICT_AT_CMD_RE = re.compile(r"(?:" + "|".join(VERDICT_COMMANDS) + r")\b")

# Interpreters that carry the real command in their NEXT operand. Required, not
# cosmetic: every recorded incident of this class used `python3 <script>`, so
# anchoring without this skip would stop the guard firing on the shape it exists
# to catch.
_INTERPRETERS = {"python", "python3", "bash", "sh", "zsh"}


def _resolve_command_index(toks):
    """Index of the real command in `toks`, skipping env assignments + wrappers.

    Extracted from `_producer_is_long_running` (2026-08-15) so the VERDICT path
    can anchor the same way instead of growing a second tokenizer. Behaviour is
    unchanged for the producer path; the existing wrapper/env regression tests
    cover that.
    """
    def _skip_env_assignments(idx):
        while idx < len(toks) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[idx]):
            idx += 1
        return idx

    i = _skip_env_assignments(0)
    # Outer loop: a wrapper may itself be preceded/followed by env assignments
    # (`env FOO=1 timeout 30 python x.py`), so alternate between the two skips.
    while i < len(toks) and toks[i].rsplit("/", 1)[-1] in WRAPPER_PREFIXES:
        i += 1
        # Consume the wrapper's own operands: flags (-k 10, --preserve-status,
        # -oL), durations (280, 5s, 2m), and further VAR=value tokens for `env`.
        while i < len(toks) and (
            toks[i].startswith("-")
            or re.fullmatch(r"\d+(\.\d+)?[smhd]?", toks[i])
            or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i])
        ):
            i += 1
    return i


def _verdict_at_command_position(segment):
    """True when a VERDICT_COMMANDS entry is the segment's COMMAND, not an argument.

    The bug this closes: both verdict checks used a bare `_VERDICT_RE.search()`
    over the whole segment, so `pr-merge-verified.py` matched anywhere --
    including as a FILE BEING READ. Measured 2026-08-03, blocked live twice in one
    session while trying to read the script to check its own `--status-file` flag:

        grep -n armed bin/pr-merge-verified.py | head -20        -> exit 2, WRONG
        grep -n armed bin/pr-merge-verified.py > o; wc -l < o    -> exit 2, WRONG

    This is a RECURRENCE, not a new class. The guard's v3 changelog (2026-06-12)
    describes it exactly -- `grep -n PAT /tmp/pytest-e2e.log | head` blocked
    because "pytest" appeared in the LOG FILENAME. v3 token-anchored the PRODUCER
    predicate; v8 added this second matcher and did not inherit the anchoring.
    So the fix is v3's already-validated approach applied to the newer path.

    Basename the resolved token before matching, so `bin/pr-merge-verified.py`
    matches while a path-prefixed ARGUMENT of some other command cannot.
    """
    toks = segment.split()
    i = _resolve_command_index(toks)
    if i >= len(toks):
        return False
    if toks[i].rsplit("/", 1)[-1] in _INTERPRETERS:
        i += 1
        while i < len(toks) and toks[i].startswith("-"):
            i += 1
        if i >= len(toks):
            return False
    head = toks[i].rsplit("/", 1)[-1]
    return bool(_VERDICT_AT_CMD_RE.match(" ".join([head] + toks[i + 1:])))


def _verdict_unit(seg):
    """The sub-command inside `seg` whose COMMAND POSITION is a verdict, else None.

    `check_trailing_status_swallow` splits the command on `;` ONLY, so one segment
    can hold several commands joined by `&&`, `||`, or newlines. Anchoring against
    the segment's first command therefore misses the overwhelmingly common real
    shape, where the verdict is preceded by a `cd`:

        cd ~/.claude && python3 bin/pr-merge-verified.py 1888 … > log 2>&1; echo "rc=$?"

    That is a TRUE positive -- the trailing `echo` replaces the verifier's status,
    which is the exact false-MERGED class the check was built for (#1788, #1785 x2,
    #1818, #1819). Measured over 79,018 historical Bash commands: anchoring at the
    segment level dropped 670 of 713 fires (94%), essentially all of them shapes
    like the above. The tests did not catch it -- 65 passed, including both
    "still blocks" cases -- because they pin the shapes someone thought to write,
    and no test used a `cd &&` prefix. Only the corpus replay surfaced it.

    So split the segment into its sub-commands and anchor within each.
    """
    for unit in re.split(r"\s*(?:&&|\|\||\n)\s*", seg):
        if _verdict_at_command_position(unit):
            return unit
    return None


def _is_backgrounded(segment):
    """True when `segment` ends with a bare `&` (not `&&`, not `2>&1`).

    A `&`-terminated command's exit status is not the invoking shell's, so there
    is nothing for a trailing segment to overwrite and the trailing-swallow block
    is unconditionally wrong for that shape. Worse, it blocked the exact remedy
    this guard's own message recommends -- `nohup ... --status-file ... &`
    followed by a readiness check (measured 2026-08-04).
    """
    stripped = segment.rstrip()
    return stripped.endswith("&") and not stripped.endswith("&&")


def _producer_is_long_running(producer):
    """True when the pipe's stdout producer is a long-running command.

    Token-anchored: skip leading env assignments AND wrapper binaries, take the
    first remaining token's basename, and require an exact command match
    (python* / pytest / cargo bare; go / npm / docker / git / cli with a
    qualifying subcommand).

    Wrapper skipping (2026-07-31, staged spec tail-guard-wrapper-producer-
    detection): a wrapped producer previously resolved to the WRAPPER's basename
    (`timeout`, `nohup`) and was classified SHORT, so the guard never fired on a
    producer it was explicitly built to catch. Only the starting index moves; the
    comparison set is unchanged, so this cannot reintroduce v2's substring
    over-firing."""
    toks = producer.split()
    i = _resolve_command_index(toks)
    # Re-check after the wrapper loop: `timeout 5` (no command) must be False,
    # not an index past the end.
    if i >= len(toks):
        return False
    base = toks[i].rsplit("/", 1)[-1]
    nxt = toks[i + 1] if i + 1 < len(toks) else ""
    if base.startswith("python"):  # python, python3, python3.13, .venv/bin/python
        return True
    if base in BARE_PRODUCERS:
        return True
    if base in SUBCOMMAND_PRODUCERS and nxt in SUBCOMMAND_PRODUCERS[base]:
        return True
    if TOKEN_PRODUCERS.intersection(toks[i:]):
        return True
    return False


def _sanitize(command):
    """Strip heredocs, command substitutions, and quoted strings so we
    don't match pipes inside string literals or substitutions.

    Best-effort: doesn't handle nested $(...) perfectly, doesn't handle
    escaped quotes. Conservative — accepts false negatives for nested
    constructs."""
    # Strip heredoc bodies: <<'EOF' ... EOF and <<EOF ... EOF
    sanitized = re.sub(r"<<\s*'?(\w+)'?[\s\S]*?\n\1", "", command)
    # Strip $(...) command substitutions (replace with placeholder)
    sanitized = re.sub(r"\$\([^)]*\)", "$()", sanitized)
    # Strip double-quoted strings
    sanitized = re.sub(r'"[^"]*"', '""', sanitized)
    # Strip single-quoted strings
    sanitized = re.sub(r"'[^']*'", "''", sanitized)
    return sanitized


def _producer_of(segment):
    """When a segment chains commands with && / || / ; / newlines, the
    LAST chained command produces stdout for the next pipe. Return it
    stripped."""
    parts = re.split(r"\s*(?:&&|\|\||;|\n)\s*", segment)
    return parts[-1].strip()


# v7 (2026-07-28): the GIT-GATING pipe, a shape this guard structurally missed.
#
# `FORBIDDEN: chaining_&&_after_a_piped_gating_command` has been prose in
# platform-constraints.md since 2026-06-11 and recurred 2026-06-14, 2026-07-09,
# and 2026-07-22 — the last one in the contended ~/.claude checkout, where
# `git merge --ff-only origin/main 2>&1 | tail -1 && ...` had the merge REFUSE
# over another session's dirty files, `tail` exit 0, the output read as success,
# and HEAD never move. Silent by construction (status discarded, output looks
# normal), which is exactly the class verify-effectiveness says justifies a hook
# rather than a rule.
#
# It slips past the buffering check above because that fires only on LONG-RUNNING
# producers (`_producer_is_long_running`) — gating git commands are instant, so
# they are correctly not a buffering problem and correctly pass. This is a
# separate defect (lost gate status) that happens to share the pipe syntax.
#
# DETECTION — narrowed by measurement, NOT as the staged spec drafted it.
# The spec's regex was `git (merge|rebase|checkout|pull|push|cherry-pick|stash)
# ... | (tail|head|grep|sed|awk)`. Replayed over 38,317 real historical Bash
# commands (593 transcripts, parsed from tool_use — never grepped, which
# self-matches):
#     spec regex as written ... 68 blocks (0.18%) but 27 of 68 (40%) FALSE
#                               POSITIVES — `git stash list | head -5`,
#                               `git branch --show-current`, even an incidental
#                               `git worktree remove ... | tail`. All read-only:
#                               masking their status harms nothing, so blocking
#                               them is pure friction, and a guard that is wrong
#                               40% of the time gets worked around.
#     + state-changing verbs
#       only ................... instrument INVALID — it MISSED the verbatim
#                               2026-07-22 incident, because `[^|;&]*` excludes
#                               `&` and the command contains `2>&1`. Its
#                               "improved" 0.05% rate was measured blind.
#     + separator-aware ........ instrument valid, 1,936 blocks (5.05%) —
#                               dominated by `git push ... 2>&1 | tail -20`,
#                               idiomatic noise-trimming whose status nobody
#                               consumes.
#     + REQUIRE a trailing `&&`  160 blocks (0.4176%), zero false positives in
#       (this implementation) .. the sample. 4/4 known-positives incl. the
#                               verbatim incident, 8/8 known-negatives.
#
# The trailing `&&` is the load-bearing discriminator: the harm was never the
# masked status alone, it was the masked status being USED AS A GATE. A terminal
# `git push | tail -20` is a display choice; `git merge | tail -1 && next` is a
# false gate. Do NOT widen this to bare state-changing verbs without re-running
# the replay — that is the 5.05% path.
_GIT_STATE_VERB = (
    r"(?:merge|rebase|pull|push|cherry-pick|revert|reset|am|"
    r"checkout|stash\s+(?:push|pop|apply|drop|clear|save))"
)
# Everything up to the pipe, but NOT across a command separator (`&&`/`||`/`;`)
# — a separator means the pipe belongs to a DIFFERENT command, so this git
# command's status is not what is being masked. `2>&1` must still pass, which is
# why this forbids the separators rather than the bare `&` character.
_NO_SEP = r"(?:(?!&&|\|\||;)[^|\n])*"
GIT_GATING_PIPE = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?" + _GIT_STATE_VERB + r"\b" + _NO_SEP +
    r"\|\s*(?:tail|head|grep|sed|awk|wc|cut|sort)\b[^|\n]*?&&"
)

_GIT_GATING_MESSAGE = (
    "[bash-tail-buffering-guard] BLOCKED: a state-changing git command's output is\n"
    "piped to a filter, and the pipeline's status then gates an `&&`.\n"
    "\n"
    "The pipeline exits with the FILTER's status (pipefail is unset in this shell),\n"
    "so the git command's failure is DISCARDED and the `&&` proceeds anyway. This\n"
    "fails SILENTLY: the output looks normal and nothing errors.\n"
    "\n"
    "4th documented recurrence (2026-06-11 / 2026-06-14 / 2026-07-09 / 2026-07-22).\n"
    "The 2026-07-22 case: `git merge --ff-only origin/main 2>&1 | tail -1 && ...`\n"
    "— the merge REFUSED over another session's dirty files, tail exited 0, and\n"
    "HEAD never moved while the command read as success.\n"
    "\n"
    "Fix options:\n"
    "  1. Drop the filter on the gating command — run it bare and let it fail loudly:\n"
    "       git merge --ff-only origin/main && next\n"
    "  2. Split into SEPARATE Bash calls and check the result before the dependent step\n"
    "  3. If you must filter, capture the status first:\n"
    "       git merge --ff-only origin/main > /tmp/claude/m.log 2>&1; rc=$?\n"
    "       tail -1 /tmp/claude/m.log; [ $rc -eq 0 ] && next\n"
    "  4. Read-only inspection (`git stash list | head`) is NOT blocked — only\n"
    "     state-changing verbs whose piped status gates an `&&`.\n"
    "\n"
    "Reference: ~/.claude/rules/platform-constraints.md\n"
    "FORBIDDEN: chaining_&&_after_a_piped_gating_command\n"
)


def check_git_gating(command):
    """Return (blocked, reason) for the git-gating-pipe shape (v7).

    Separate from check(): that one keys on a LONG-RUNNING producer (a buffering
    problem), while this keys on a STATE-CHANGING git verb whose piped status
    gates an `&&` (a lost-gate problem). A command can hit either, both, or
    neither. Runs on the SANITIZED command so a pattern inside a quoted string
    or heredoc body cannot trigger it.
    """
    sanitized = _sanitize(command)
    if GIT_GATING_PIPE.search(sanitized):
        return True, (
            "a state-changing git command's piped status gates an `&&` — "
            "the git failure is discarded and the chain proceeds silently"
        )
    return False, None


_VERDICT_PIPE_RE = re.compile(
    r"\|\s*(?:tail|head|grep|sed|awk|wc|cut|sort|jq)\b"
)


def check_verdict_piped_to_filter(command):
    """Return (blocked, reason) when a VERDICT command is piped to a filter.

    FOURTH disjoint shape. The three existing checks key on a long-running
    producer (buffering), a state-changing git verb gating an `&&` (lost gate),
    and a `;`-chain overwriting the status (swallowed verdict). This one keys on
    a VERDICT_COMMANDS match whose status is consumed by a PIPE -- no `&&` and
    no `;` required, so none of the three sees it.

    The pipeline exits with the FILTER's status, and `pipefail` is unset in this
    shell, so the verdict is discarded at the pipe itself. Under
    run_in_background the CONSUMER is the harness: the task-completion
    notification reports the filter's exit code as the task's, so a verdict
    command that FAILED is announced to the model as `exit code 0`.

    INCIDENT 2026-08-01: `pr-merge-verified.py 1840 ... | tail -6` was run with
    run_in_background. The script exits 0 ONLY on state==MERGED, but the harness
    reported `tail`'s 0 and the PR was still OPEN -- a merge was reported to the
    user as complete when it had not happened. The command was seen by this very
    hook and classified `auto-fixed (buffering)`; the status-loss went unchecked
    because check_trailing_status_swallow() requires a `;`-chain.

    BLOCKS rather than rewrites, for the reason the git-gating check already
    documents: the defect is that the caller is relying on a status that gets
    discarded, so silently restructuring the command would preserve a verdict
    the author never actually read. Auto-fix is the right default for buffering
    (recoverable); it is the wrong default for a false verdict (silent).

    Exempt when the author has explicitly handled pipeline status -- `pipefail`
    or `PIPESTATUS` -- since then the status is not lost.
    """
    sanitized = _sanitize(command)
    if "pipefail" in sanitized or "PIPESTATUS" in sanitized:
        return False, ""
    for segment in re.split(r"\s*(?:&&|\|\||;|\n)\s*", sanitized):
        if not _verdict_at_command_position(segment):
            continue
        if _VERDICT_PIPE_RE.search(segment):
            return True, (
                "a verdict command's exit status is discarded by the pipe — the "
                "pipeline exits with the FILTER's status and pipefail is unset, "
                "so under run_in_background the harness reports the filter's 0 "
                "as the task's exit code and a FAILED verdict reads as success. "
                "Run the verdict command unpiped in its own Bash call, or add "
                "`set -o pipefail`, or capture ${PIPESTATUS[0]}."
            )
    return False, ""


def check_trailing_status_swallow(command):
    """Return (blocked, reason) when a verdict command's exit status is overwritten.

    THIRD disjoint shape in this hook's family. check() keys on a long-running
    producer (buffering); check_git_gating() keys on a state-changing git verb
    whose piped status gates an `&&` (lost gate); this keys on a command whose
    EXIT STATUS *is* the verdict, followed by `;`-chained commands that replace
    it. No pipe and no `&&` are involved, so neither existing check sees it.

    Fires only when ALL of:
      1. a VERDICT_COMMANDS match appears in a `;`-separated segment, AND
      2. at least one NON-EMPTY segment follows it, AND
      3. the last trailing segment does not itself PRESERVE the code
         (`exit $?`, `[ $? -eq 0 ]`).

    `echo "EXIT=$?"` does NOT count as preserving: it writes the value to stdout
    while leaving `$?` to be replaced by the next command. Under
    run_in_background the harness reports the WRAPPER SHELL's status, so a
    failing verdict command is reported to the model as success.

    Measured 2026-07-30 over 47,932 historical Bash calls: 1,700 would block
    (3.547%), under the 10% bar. Runs on the SANITIZED command so a pattern
    inside a quoted string or heredoc body cannot trigger it.
    """
    sanitized = _sanitize(command)
    segments = [s.strip() for s in sanitized.split(";")]
    for i, seg in enumerate(segments[:-1]):
        unit = _verdict_unit(seg)
        if unit is None:
            continue
        # Defect B: a BACKGROUNDED verdict has no status for a trailing
        # segment to overwrite, so the block is unconditionally wrong there.
        # Tested on the SANITIZED text so a `&` inside a quoted string cannot
        # fool it, and on the verdict's OWN sub-command so a `\nsleep 2` sharing
        # the `;`-segment cannot hide the trailing `&`. `2>&1` is not trailing,
        # so it correctly does not count as backgrounding.
        if _is_backgrounded(unit):
            continue
        trailing = [s for s in segments[i + 1:] if s]
        if not trailing:
            continue
        # A chain ending in an explicit propagation is fine.
        # `exit ${PIPESTATUS[0]}` propagates a PIPED verdict's status correctly and
        # was rejected by the `$?`-only form — a false positive on the one idiom
        # this guard's own message recommends. Found 2026-08-01 while adding
        # check_verdict_piped_to_filter; pre-existing on origin/main.
        if re.match(r"exit\s+(?:\$\?|\$\{PIPESTATUS\[\d+\]\})|\[\s*\$\?\s", trailing[-1]):
            continue
        return True, (
            "a verdict command's exit status is overwritten by the trailing "
            f"`{trailing[-1].split()[0]}` — under run_in_background the harness "
            "reports the WRAPPER shell's status, so a failure reads as success. "
            "Run the verdict command in its OWN Bash call, or use its "
            "--status-file / write the code to a file before the trailing command."
        )
    return False, None


def check(command):
    """Return (blocked: bool, reason: str | None)."""
    sanitized = _sanitize(command)
    segments = [s.strip() for s in sanitized.split("|")]
    if len(segments) < 2:
        return False, None

    first = segments[0]
    last = segments[-1]

    # The producer of stdout for the pipe is the LAST chained command in
    # the first segment (after &&/||/;), not the segment as a whole.
    # e.g. `cd bench/ && gh pr view 285` → producer is `gh pr view 285`,
    # not the `cd bench/` prefix.
    producer = _producer_of(first)
    if not _producer_is_long_running(producer):
        return False, None

    # The consumer (last segment) must be a buffering filter.
    # Use re.match (anchored to segment start) so `tail`/`head`/`grep` as
    # the FIRST token of the last segment counts, but e.g. `awk 'tail()'`
    # doesn't (already stripped by _sanitize, but defense-in-depth).

    # `tail -N` (numeric arg, no -f follow)
    if re.match(r"tail\s+-[0-9]+(?!\s*-f)", last):
        return True, "Pipe to `tail -N` buffers stdout until source exits"
    # `tail` with -f → allow; bare `tail` (no flags) also buffers
    if re.match(r"tail(?:\s|$)", last) and "-f" not in last:
        return True, "Pipe to `tail` (no -f) buffers until source exits"
    # `head -N` reads N lines then closes (SIGPIPE risk)
    if re.match(r"head\s+-[0-9]+", last):
        return True, "Pipe to `head -N` reads N lines then closes; source may receive SIGPIPE before producing useful output"
    # `grep` without --line-buffered buffers when stdout is not a TTY
    if re.match(r"grep(?:\s|$)", last) and "--line-buffered" not in last:
        return True, "Pipe to `grep` (no --line-buffered) buffers when stdout is not a TTY"

    return False, None


def _outfile(command):
    """Deterministic temp-file path for the producer's captured output. The
    directory is env-overridable (CLAUDE_TAILBUF_DIR). The producer's own `>`
    redirect creates the file; we only ensure the directory exists."""
    default_dir = os.path.join(tempfile.gettempdir(), "claude")
    d = os.environ.get("CLAUDE_TAILBUF_DIR", default_dir)
    h = hashlib.sha1(command.encode("utf-8")).hexdigest()[:12]
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, f"tailbuf_{h}.log")


def rewrite(command):
    """Return a buffering-safe rewrite for a blocked command, or None when it
    can't be rewritten losslessly (caller then blocks).

    tail/grep/head consumers are ALL rewritten here: this guard only FIRES when
    the producer is a BATCH command (`_producer_is_long_running`: pytest / cargo /
    go test / npm / docker run / git clone / python* / index_repository) — every
    one runs to completion regardless, so NONE benefits from `head`'s SIGPIPE
    early-termination (unlike `cat hugefile | head`, where head saves real work).
    So `PRODUCER | filter` becomes `PRODUCER > FILE 2>&1\\n<filter> FILE` with
    identical observable output minus the buffering bug.

    v5 (2026-06-23): `head` consumers PROMOTED from block to rewrite. The original
    blanket head-refusal ("head intends early termination") is theoretically right
    for a STREAMING producer, but this guard's fire-set has no streaming producers
    — all are batch-to-completion, so the rewrite is safe. Measured: `head` was
    142 of 412 blocks in the audit window — the dominant residual friction this
    closes. The tail/grep rewrite uses `cat FILE | filter`; head reads the file
    directly (`head -N FILE`) since it takes a file arg. Returns None (-> block) for:
      - quoted pipes (orig vs sanitized segment-count mismatch)
      - a producer that already redirects stdout to a file
      - a non-head consumer that itself can't be reconstructed
    """
    blocked, _ = check(command)
    if not blocked:
        return None
    sanitized = _sanitize(command)
    san_segs = sanitized.split("|")
    # (head consumers are now rewritten too — see docstring; `cat FILE | head -N`
    # is buffering-safe because the producer already ran to completion into FILE.)
    # Split the ORIGINAL on `|`; bail if quoting hid a pipe (count mismatch),
    # which would make positional reconstruction unsafe.
    orig_segs = command.split("|")
    if len(orig_segs) != len(san_segs):
        return None
    first = orig_segs[0].strip()
    consumers = [s.strip() for s in orig_segs[1:]]
    if not first or not consumers or any(not c for c in consumers):
        return None
    # Strip a single TRAILING stderr redirect from the producer and re-apply it
    # after the stdout file redirect (correct order). `2>&1` captures stderr
    # into the file; `2>/dev/null` / `2>&-` / `2>somefile` preserve the
    # producer's own stderr disposition. The generalised match runs ONLY when
    # the producer has no quotes, so a `2>` inside a quoted arg can't be
    # mis-parsed as a redirect; a quoted producer keeps the narrow `2>&1`-only
    # strip. After stripping, bail if ANY stdout `>` / stdin `<` redirect
    # remains — reconstruction is only safe for a plain producer (a stdout
    # `> file` makes the pipe pointless anyway).
    stderr_redir = "2>&1"
    if '"' not in first and "'" not in first:
        m_redir = re.search(r"\s*2>\s*(\S+)\s*$", first)
        if m_redir:
            target = m_redir.group(1)
            stderr_redir = "2>&1" if target == "&1" else f"2>{target}"
            producer = first[: m_redir.start()].rstrip()
        else:
            producer = first.rstrip()
    else:
        producer = re.sub(r"\s*2>&1\s*$", "", first).rstrip()
    if ">" in producer or "<" in producer:
        return None
    # Consumers (everything after the first `|`) are split on `|` and rejoined
    # on `|` — byte-identical to the original downstream of the producer — so
    # any `;` / `&&` / `||` chained AFTER the filter is preserved verbatim and
    # evaluated exactly as before. No bail needed for chained consumers.
    file = _outfile(command)
    chain = " | ".join(consumers)
    # v6 (2026-07-26): PRESERVE THE PRODUCER'S EXIT CODE.
    #
    # Without the rc capture the rewrite ends on `cat FILE | <filter>`, so the
    # command's status is the FILTER's — almost always 0 — and the producer's
    # exit code is discarded. The original pipe had the same defect, so this is
    # not a regression the rewrite introduced; but the rewrite is where we can
    # fix it, and until now the guard "approved" the command with the reason
    # "buffering-safe", which reads as an all-clear while the exit code still
    # lies.
    #
    # INCIDENT 2026-07-26: `pr-merge-verified.py <N> ... 2>&1 | tail -25` under
    # run_in_background. That script exits 2 on timeout and 0 ONLY on MERGED —
    # its docstring warns explicitly not to pipe it. The guard rewrote and
    # approved it; the harness reported "exit code 0"; a PR that had timed out
    # in the merge queue was briefly reported as merged. The producer here is a
    # VERIFICATION script, so a masked exit code is not cosmetic — it inverts
    # the answer.
    #
    # `exit` is safe: the rewrite IS the whole command, and anything the caller
    # chained after the filter still runs before it (see the comment above).
    return (
        f"{producer} > {file} {stderr_redir}\n"
        f"__tbg_rc=$?\n"
        f"cat {file} | {chain}\n"
        f"exit $__tbg_rc"
    )


_BLOCK_MESSAGE = (
    "[bash-tail-buffering-guard] BLOCKED: {reason}\n"
    "\n"
    "3rd documented recurrence (2026-03-16 / 2026-05-02 / 2026-05-10) of\n"
    "the long-running-command | filtering-pipe anti-pattern. The pipe buffers\n"
    "stdout until the source command exits, making progressive monitoring\n"
    "impossible.\n"
    "\n"
    "This shape could not be auto-rewritten safely (quoted pipe or existing\n"
    "producer-side redirect). Fix options:\n"
    "  0. CHEAPEST — if you only wanted LESS OUTPUT, ask the PRODUCER, not a pipe:\n"
    "     `gh pr list --limit 5`, `git log -n 5`, `grep -m 5` / `grep -c`,\n"
    "     `sed -n '1,5p' FILE` (reads a file, not a pipe), `python3 ... [:5]`.\n"
    "     No `producer | filter` pipe is built, so this guard cannot fire AND the\n"
    "     producer does less work. Most residual blocks are display-truncation on a\n"
    "     command that already has a native limit flag.\n"
    "  1. Redirect to a file: `cmd > /tmp/run.log 2>&1` (then `tail -f /tmp/run.log` separately)\n"
    "  2. Use `run_in_background: true` and let the Bash tool capture the output file\n"
    "  3. If you really want to filter live: `cmd 2>&1 | grep --line-buffered PATTERN | tail -f`\n"
    "  4. For Python scripts: ensure stdout is unbuffered via `python -u script.py` or `PYTHONUNBUFFERED=1`\n"
    "\n"
    "Reference: ~/.claude/rules/platform-constraints.md\n"
    "FORBIDDEN: piping_long_running_background_script_to_filtering_tail\n"
)


def _audit_log(action, reason, command):
    """Append a guard decision (auto-fixed / blocked) to the daily JSONL audit
    log so bin/hook-fire-report.py can read the auto-fix-vs-block breakdown —
    exit codes alone can't tell an auto-rewrite (exit 0 + updatedInput) from a
    plain allow (exit 0). Best-effort; never fails the guard.

    Skips under CLAUDE_HOOK_TEST so the test suite never contaminates the
    production friction instrument; dir is CLAUDE_AUDIT_DIR-overridable so
    tests can assert the write against a tmp path.
    """
    if os.environ.get("CLAUDE_HOOK_TEST"):
        return
    try:
        audit_dir = os.environ.get("CLAUDE_AUDIT_DIR") or os.path.join(
            os.path.expanduser("~"), ".claude", "audit")
        os.makedirs(audit_dir, exist_ok=True)
        now = datetime.now(timezone.utc)
        entry = {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "command": (command or "")[:500],
            "action": action,
            "reason": (reason or "")[:200],
        }
        path = os.path.join(
            audit_dir, f"bash-tail-buffering-{now.strftime('%Y-%m-%d')}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: S110, BLE001 -- fail-open: audit logging must never fail the guard
        pass  # never fail the guard for audit logging


def main():
    global _SESSION_ID
    try:
        data = json.loads(sys.stdin.read())
        _SESSION_ID = str(data.get("session_id") or "")
        tool_name = data.get("tool_name", "")
        if tool_name != "Bash":
            sys.exit(0)
        tool_input = data.get("tool_input", {})
        command = tool_input.get("command", "")

        # v7: the git-gating check runs FIRST and always BLOCKS — never rewrites.
        # A rewrite would be wrong here: the defect is that the caller is USING a
        # discarded status as a gate, so silently restructuring the command would
        # preserve a decision the author never actually made. The author has to
        # choose (fail loudly / split the calls / capture rc), which is what the
        # message lays out. Ordered before check() so a command that is BOTH a
        # long-running buffering pipe AND a git gate gets the gating message,
        # which is the more serious of the two.
        git_blocked, git_reason = check_git_gating(command)
        if git_blocked:
            _audit_log("blocked", git_reason, command)
            print(_GIT_GATING_MESSAGE
                  + _repeat_note("bash-tail-buffering-guard", TAIL_REMEDY),
                  file=sys.stderr)
            sys.exit(2)

        # Also always BLOCKS, never rewrites, and for the same reason as the git
        # gate: the author is relying on a status that gets discarded, so
        # restructuring the command silently would preserve a verdict they never
        # actually read. Ordered after the git gate (more serious) and before
        # check() so a command that both swallows a verdict AND buffers gets the
        # status message — the buffering is recoverable, a false verdict is not.
        # Same class as the two checks above (a discarded verdict status), so it
        # BLOCKS for the same reason and is ordered with them, ahead of check()'s
        # recoverable buffering rewrite. Keyed on the PIPE rather than a `;` or
        # `&&`, which is the shape the other two structurally cannot see.
        pipe_blocked, pipe_reason = check_verdict_piped_to_filter(command)
        if pipe_blocked:
            _audit_log("blocked", pipe_reason, command)
            print(f"[tail-buffering-guard] BLOCKED: {pipe_reason}"
                  f'{_repeat_note("bash-tail-buffering-guard", TAIL_REMEDY)}',
                  file=sys.stderr)
            sys.exit(2)

        swallow_blocked, swallow_reason = check_trailing_status_swallow(command)
        if swallow_blocked:
            _audit_log("blocked", swallow_reason, command)
            print(
                f"[bash-tail-buffering-guard] BLOCKED: {swallow_reason}"
                f'{_repeat_note("bash-tail-buffering-guard", TAIL_REMEDY)}',
                file=sys.stderr,
            )
            sys.exit(2)

        blocked, reason = check(command)
        if not blocked:
            sys.exit(0)
        # Try a buffering-safe auto-rewrite (tail/grep consumers). A rewrite
        # bug must fall back to BLOCK, never silently allow a buffering pipe.
        try:
            new_command = rewrite(command)
        except Exception:
            new_command = None
        if new_command is not None:
            fix_reason = (
                "tail-buffering-guard: redirected producer to a file then "
                f"filtered (buffering-safe). {reason}"
            )
            # Documented PreToolUse rewrite shape; the former top-level
            # updated_input was ignored by the runtime (probed 2026-09-03).
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": fix_reason,
                    "updatedInput": {**tool_input, "command": new_command},
                }
            }
            _audit_log("auto-fixed", fix_reason, command)
            print(json.dumps(result))
            sys.exit(0)
        _audit_log("blocked", reason, command)
        print(_BLOCK_MESSAGE.format(reason=reason)
              + _repeat_note("bash-tail-buffering-guard", TAIL_REMEDY),
              file=sys.stderr)
        sys.exit(2)
    except Exception:
        # Never crash — allow on error
        sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
