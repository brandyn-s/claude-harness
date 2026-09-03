"""TaskCompleted hook - verify task results before marking complete.

Fires when an Agent Team task is being marked as completed. Historically
this was an exit-0 observer that only reported whether file changes existed
on disk. Phase D turns it into an *enforcing* gate while staying strictly
fail-open for uncontracted tasks. Once a task explicitly declares a completion
contract, malformed or unverifiable contract state fails closed: silently
downgrading an invalid contract to "no contract" would defeat the gate.

WHAT TRIGGERS A BLOCK
---------------------
The gate blocks (exit 2) on an explicit machine-readable failure signal. It
also supports an opt-in evidence contract in Claude Code's documented
``task_description`` field::

  Completion-Contract: {"required_paths":["docs/report.md"]}

Contracted paths must remain inside ``cwd`` and be non-empty. A contracted task
also cannot close with a partial, truncated, prompt-too-long, or
completed-with-errors status when an integration supplies such a status.
Explicit failures include:

  - a top-level / result-level status field equals an explicit failure value
    ("failed", "failure", "error", "errored", "incomplete", "aborted",
    "timed_out", "timeout", "cancelled", "canceled"); or
  - a boolean success/ok/passed field is explicitly False (not merely absent); or
  - a result/tool_response carries `is_error: true` / `isError: true`.

It does NOT block uncontracted soft / ambiguous signals:
  - "no file changes on disk" -> informational only (the original observer
    behavior is preserved as a pass message). Many legitimate tasks (research,
    review, analysis) produce no diff.
  - missing status field -> allow; the official TaskCompleted event does not
    currently publish a result status.
  - free-text that merely mentions the word "error" -> NOT a block; we only
    trust structured status/boolean fields, never substring-sniffing prose
    (avoids spurious blocks on tasks that discuss errors).

When a block fires, an actionable reason is written to stderr and the hook
exits 2 (the repo's standard Stop-family block convention; see
subagent-stop.py:362-364 and promise-checker.py:194-199).

FAILURE BOUNDARY
----------------
Malformed whole-hook input and failures on tasks with no declared contract
remain fail-open. A declared completion contract is different: invalid JSON,
wrong types, missing cwd, unsafe paths, or verification errors block with an
actionable reason. This preserves availability without converting a broken
evidence contract into an uncontracted pass.

FALSIFIER NOTE
--------------
Agent Teams are experimental and official TaskCompleted input is intentionally
small. Evidence enforcement therefore depends on declaring the contract at
TaskCreate time; uncontracted research and review tasks remain valid.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    import ctypes

    _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if _hwnd:
        ctypes.windll.user32.ShowWindow(_hwnd, 0)

# Desktop notification (macOS only; no-op elsewhere). Guarded import keeps
# this hook self-contained: a missing/broken helper must never affect the
# enforcement gate (fail-open guarantee below).
try:
    from macos_notify import notify as _notify
except Exception:  # pragma: no cover - defensive
    def _notify(title, message):
        return False

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Explicit failure tokens for string-valued status fields. Compared
# case-insensitively against the field's exact value (not substring).
_FAILURE_STATUS_VALUES = frozenset(
    {
        "failed",
        "failure",
        "fail",
        "error",
        "errored",
        "incomplete",
        "aborted",
        "abort",
        "timed_out",
        "timeout",
        "cancelled",
        "canceled",
        "rejected",
    }
)

# These outcomes can be useful for uncontracted research, but are not a valid
# completion when the task explicitly requires evidence on disk.
_CONTRACT_NON_SUCCESS_VALUES = frozenset(
    {
        "completed_with_errors",
        "partial",
        "truncated",
        "prompt_too_long",
        "prompt-too-long",
    }
)

# String-valued fields that may carry a task status.
_STATUS_KEYS = ("status", "result_status", "task_status", "state", "outcome")

# Boolean-valued fields where an *explicit* False means failure. Absent or
# non-bool values are ignored (uncertain => allow).
_BOOL_SUCCESS_KEYS = ("success", "ok", "passed", "succeeded")

# Boolean-valued error flags where an *explicit* True means failure.
_BOOL_ERROR_KEYS = ("is_error", "isError", "errored", "has_error")

_DESCRIPTION_CONTRACT_RE = re.compile(
    r"(?im)^\s*Completion-Contract:\s*(\{[^\r\n]*\})\s*$"
)
_DESCRIPTION_CONTRACT_DECLARED_RE = re.compile(
    r"(?im)^\s*Completion-Contract:"
)


class CompletionContractError(ValueError):
    """A task declared a completion contract that cannot be enforced safely."""


def _contract_declared(obj: dict) -> bool:
    if "completion_contract" in obj:
        return True
    description = obj.get("task_description")
    return isinstance(description, str) and bool(
        _DESCRIPTION_CONTRACT_DECLARED_RE.search(description)
    )


def _explicit_failure_reason(obj) -> str:
    """Return an actionable block reason if ``obj`` carries an EXPLICIT
    failure signal, else "". Conservative by construction: only structured
    status/boolean fields are trusted; free-text is never sniffed.

    ``obj`` may be a dict (the payload, or a nested result/tool_response) or
    a non-dict (in which case there is no structured signal -> "").
    """
    if not isinstance(obj, dict):
        return ""

    # 1) Explicit string status fields.
    for key in _STATUS_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.strip().lower() in _FAILURE_STATUS_VALUES:
            return (
                f"task reported {key}={val!r} (an explicit failure status). "
                f"Do not mark this task complete. Fix the underlying failure "
                f"and re-run the task, or report the failure explicitly rather "
                f"than claiming success."
            )

    # 2) Explicit boolean success == False.
    for key in _BOOL_SUCCESS_KEYS:
        if key in obj and obj.get(key) is False:
            return (
                f"task reported {key}=false (explicit failure). Do not mark "
                f"this task complete. Address what failed and re-run, or report "
                f"the failure instead of claiming success."
            )

    # 3) Explicit boolean error flag == True.
    for key in _BOOL_ERROR_KEYS:
        if key in obj and obj.get(key) is True:
            return (
                f"task reported {key}=true (the task errored). Do not mark this "
                f"task complete. Investigate and resolve the error, then re-run "
                f"the task."
            )

    return ""


def _completion_contract(obj: dict) -> dict | None:
    """Read a contract from an extension field or documented task_description."""

    if "completion_contract" in obj:
        contract = obj.get("completion_contract")
        if not isinstance(contract, dict):
            raise CompletionContractError("completion_contract must be an object")
    else:
        description = obj.get("task_description")
        if not isinstance(description, str):
            return None
        declared = _DESCRIPTION_CONTRACT_DECLARED_RE.search(description)
        if not declared:
            return None
        match = _DESCRIPTION_CONTRACT_RE.search(description)
        if not match:
            raise CompletionContractError(
                "invalid Completion-Contract declaration; expected one JSON object"
            )
        try:
            contract = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError) as exc:
            raise CompletionContractError(
                f"invalid Completion-Contract JSON: {exc.msg if hasattr(exc, 'msg') else exc}"
            ) from exc
        if not isinstance(contract, dict):
            raise CompletionContractError("Completion-Contract JSON must be an object")

    if "required_paths" not in contract:
        raise CompletionContractError("completion contract requires required_paths")
    required_paths = contract.get("required_paths")
    if not isinstance(required_paths, list):
        raise CompletionContractError("required_paths must be a list")
    if not required_paths:
        raise CompletionContractError("required_paths must be a nonempty list")
    if any(not isinstance(value, str) or not value.strip() for value in required_paths):
        raise CompletionContractError(
            "required_paths entries must be nonempty strings"
        )

    cwd = obj.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        raise CompletionContractError("completion contract requires a nonempty cwd")
    base = Path(cwd).resolve()
    for value in required_paths:
        relative = Path(value)
        if relative.is_absolute() or re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", value):
            raise CompletionContractError(
                f"required path {value!r} must be relative to cwd"
            )
        candidate = (base / relative).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise CompletionContractError(
                f"required path {value!r} escapes cwd"
            ) from exc
    return contract


def _has_evidence_contract(obj: dict) -> bool:
    contract = _completion_contract(obj)
    if not isinstance(contract, dict):
        return False
    return True


def _contract_status_reason(obj: dict) -> str:
    """Reject partial outcomes only when the task declares required evidence."""

    if not _has_evidence_contract(obj):
        return ""
    for key in _STATUS_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.strip().lower() in _CONTRACT_NON_SUCCESS_VALUES:
            return (
                f"task reported {key}={val!r}, which is not successful enough "
                "for its completion_contract. Produce the required evidence "
                "before marking the task complete."
            )
    return ""


def _missing_required_path_reason(obj: dict) -> str:
    """Return a block reason when a contracted output is absent from cwd."""

    contract = _completion_contract(obj)
    if not isinstance(contract, dict):
        return ""
    required_paths = contract.get("required_paths")
    if not isinstance(required_paths, list):
        raise CompletionContractError("required_paths must be a list")

    cwd = obj.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise CompletionContractError("completion contract requires a nonempty cwd")
    base = Path(cwd).resolve()
    for value in required_paths:
        if not isinstance(value, str) or not value.strip():
            raise CompletionContractError(
                "required_paths entries must be nonempty strings"
            )
        relative = Path(value)
        candidate = (base / relative).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            return f"required output {value!r} escapes the task working directory"
        if relative.is_absolute() or not candidate.is_file():
            return f"required output {value!r} is missing"
        if candidate.stat().st_size == 0:
            return f"required output {value!r} is empty"
    return ""


def _verify(hook_input: dict) -> str:
    """Best-effort verification. Returns a non-empty actionable block reason
    only on a CLEAR, structured failure signal; "" to allow."""
    if not isinstance(hook_input, dict):
        return ""

    # Inspect the top-level payload first.
    reason = _explicit_failure_reason(hook_input)
    if reason:
        return reason
    reason = _contract_status_reason(hook_input)
    if reason:
        return reason
    reason = _missing_required_path_reason(hook_input)
    if reason:
        return reason

    # Then inspect the nested result/tool_response body, whichever key the
    # current Claude Code version uses. We do NOT import hook_input.py for
    # this (keeps the hook self-contained / import-safe); we just probe the
    # known key aliases directly.
    for key in ("result", "tool_response", "tool_result", "response", "task_result"):
        nested = hook_input.get(key)
        reason = _explicit_failure_reason(nested)
        if reason:
            return reason

    return ""


def main():
    try:
        if sys.stdin and not sys.stdin.closed:
            raw = sys.stdin.read()
            hook_input = json.loads(raw) if raw and raw.strip() else {}
        else:
            hook_input = {}
    except Exception:
        # Unparseable input -> allow (fail-open).
        hook_input = {}

    if not isinstance(hook_input, dict):
        hook_input = {}

    # ── Enforcement gate ────────────────────────────────────────────────
    # Block ONLY on a clear, structured failure signal in the payload.
    # Any error in verification itself falls through to allow.
    try:
        block_reason = _verify(hook_input)
    except CompletionContractError as exc:
        block_reason = f"completion contract invalid: {exc}"
    except Exception as exc:
        block_reason = (
            f"completion contract verification failed: {type(exc).__name__}"
            if _contract_declared(hook_input)
            else ""
        )

    if block_reason:
        # Blocks are rare and need eyes — always notify (macOS only).
        _notify("Claude task blocked", block_reason)
        # Repo Stop-family block convention: stderr message + exit 2.
        # (cf. subagent-stop.py:362-364, promise-checker.py:194-199)
        print(f"[TaskCompleted] BLOCK: {block_reason}", file=sys.stderr)
        sys.exit(2)

    # ── Informational observer (unchanged behavior) ─────────────────────
    cwd = hook_input.get("cwd", ".")
    if not isinstance(cwd, str) or not cwd:
        cwd = "."

    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        diff_stat = result.stdout.strip()
    except Exception:
        diff_stat = ""

    try:
        result2 = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        status = result2.stdout.strip()
    except Exception:
        status = ""

    has_changes = bool(diff_stat or status)

    msg = (
        f"[TaskCompleted] Task done"
        f"{' (changes detected)' if has_changes else ' (no file changes)'}."
    )

    # Pass-path notifications are opt-in: an agent-team run completes many
    # tasks, and a banner per task is noise (see macos_notify.py policy).
    if os.environ.get("CLAUDE_NOTIFY_TASKS") == "1":
        _notify("Claude task completed", msg)

    # A pass emits nothing: the former {"result": "pass", "message": ...} was
    # not a documented shape and never reached the model (probed 2026-09-03).


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0 (fail-open).
    # A hook bug must never block all task completions.
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[TaskCompleted] WARNING: hook error, allowing completion: {exc}",
              file=sys.stderr)
        sys.exit(0)
