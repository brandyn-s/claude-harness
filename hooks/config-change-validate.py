"""Validate settings after a Claude Code ConfigChange event."""

import json
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass

MAX_SETTINGS_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 1024 * 1024
PROTECTED_HOOK_REMOVAL_ENV = "CLAUDE_CONFIG_ALLOW_PROTECTED_HOOK_REMOVAL"
SETTINGS_SOURCE_LABELS = {
    "user_settings": "user settings",
    "project_settings": "project settings",
    "local_settings": "local settings",
}

# Region-qualified Bedrock inference-profile prefixes and ARNs. Kept identical to
# bin/architecture-drift-check.py::PROVIDER_MODEL_PREFIXES; the two gates cover the
# same invariant on different surfaces (that one the committed file, this one the
# live file), so they must agree on what "provider-specific" means.
PROVIDER_MODEL_PREFIXES = (
    "us.anthropic.",
    "us-gov.anthropic.",
    "eu.anthropic.",
    "apac.anthropic.",
    "arn:aws",
)

@dataclass(frozen=True)
class ProtectedHook:
    event: str
    matcher: str | None
    script: str
    timeout: int
    # Registrations that satisfy this protection in place of the direct one: a
    # dispatcher that runs the script in-process is the same boundary behind one
    # launcher. Each alternative is matched as exactly as the direct registration.
    carried_by: tuple["ProtectedHook", ...] = ()


# Runs bash-security-guard and destructive-ops-guard (plus four advisories) in one
# process; the repository's settings.json registers this instead of the two guards.
_BASH_DISPATCHER = ProtectedHook(
    "PreToolUse", "Bash|PowerShell", "bash-pretooluse-dispatcher.py", 30
)

# These are the exact registrations whose removal or weakening would disable
# the architecture's settings-integrity and command-safety boundary.
PROTECTED_USER_HOOKS = (
    ProtectedHook(
        "ConfigChange",
        "user_settings|project_settings|local_settings",
        "config-change-validate.py",
        30,
    ),
    # Installer profiles register the two Bash guards directly; the repository's
    # settings.json carries both inside the dispatcher. Either keeps the boundary.
    ProtectedHook(
        "PreToolUse", "Bash", "bash-security-guard.py", 30, carried_by=(_BASH_DISPATCHER,)
    ),
    ProtectedHook(
        "PreToolUse",
        "Bash|PowerShell",
        "destructive-ops-guard.py",
        30,
        carried_by=(_BASH_DISPATCHER,),
    ),
    ProtectedHook(
        "PreToolUse",
        "Write|Edit",
        "write-edit-dispatcher.py",
        30,
    ),
    ProtectedHook("PostToolUse", "Write|Edit", "post-write-edit.py", 30),
    ProtectedHook("SessionStart", None, "session-start.py", 30),
    ProtectedHook("SessionEnd", ".*", "session-end.py", 5),
)


def block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}, sort_keys=True))
    return 0


def _normalize_absolute_path(value: str, *, config_home: str) -> str | None:
    expanded = value.replace("${HOME}", config_home).replace("$HOME", config_home)
    expanded = os.path.expanduser(expanded)
    if not os.path.isabs(expanded):
        return None
    return os.path.normcase(os.path.normpath(os.path.abspath(expanded)))


def _trusted_windows_bash(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return re.fullmatch(
        r"[A-Za-z]:/Program Files(?: \(x86\))?/Git/(?:bin|usr/bin)/bash\.exe",
        normalized,
        flags=re.IGNORECASE,
    ) is not None


def _invokes_expected_hook(
    entry: dict,
    *,
    expected_runner: str,
    expected_script: str,
    expected_timeout: int,
    config_home: str,
) -> bool:
    """Validate the effective absolute runner/script pair and control fields."""

    if entry.get("type") != "command" or not isinstance(entry.get("command"), str):
        return False
    if any(field in entry for field in ("if", "async", "once", "shell")):
        return False
    timeout = entry.get("timeout")
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or timeout != expected_timeout
    ):
        return False
    command = entry["command"]
    args = entry.get("args")
    if isinstance(args, list) and all(isinstance(arg, str) for arg in args):
        tokens = [command, *args]
    elif args is None:
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return False
    else:
        return False
    if not tokens:
        return False

    launcher = _normalize_absolute_path(tokens[0], config_home=config_home)
    hook_args = tokens[1:]
    if launcher == expected_runner:
        pass
    elif _trusted_windows_bash(tokens[0]) and hook_args:
        launcher = _normalize_absolute_path(hook_args[0], config_home=config_home)
        if launcher != expected_runner:
            return False
        hook_args = hook_args[1:]
    else:
        return False

    if len(hook_args) != 1:
        return False
    script_arg = hook_args[0]
    candidate_script = _normalize_absolute_path(script_arg, config_home=config_home)
    if candidate_script is None:
        candidate_script = os.path.normcase(
            os.path.normpath(os.path.join(os.path.dirname(expected_runner), script_arg))
        )
    return candidate_script == expected_script


def _group_has_exact_matcher(group: dict, expected: str | None) -> bool:
    if expected is None:
        return "matcher" not in group
    return group.get("matcher") == expected


def _has_protected_user_hooks(settings: dict, settings_path: str) -> bool:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    settings_dir = os.path.abspath(os.path.dirname(settings_path))
    config_home = (
        os.path.dirname(settings_dir)
        if os.path.basename(settings_dir) == ".claude"
        else os.path.expanduser("~")
    )
    hooks_dir = os.path.normcase(os.path.normpath(os.path.join(settings_dir, "hooks")))
    expected_runner = os.path.join(hooks_dir, "run-hook")
    return all(
        any(
            _registration_present(
                hooks,
                candidate,
                hooks_dir=hooks_dir,
                expected_runner=expected_runner,
                config_home=config_home,
            )
            for candidate in (protected, *protected.carried_by)
        )
        for protected in PROTECTED_USER_HOOKS
    )


def _registration_present(
    hooks: dict,
    protected: ProtectedHook,
    *,
    hooks_dir: str,
    expected_runner: str,
    config_home: str,
) -> bool:
    groups = hooks.get(protected.event)
    if not isinstance(groups, list):
        return False
    expected_script = os.path.join(hooks_dir, protected.script)
    return any(
        isinstance(group, dict)
        and "if" not in group
        and _group_has_exact_matcher(group, protected.matcher)
        and isinstance(group.get("hooks"), list)
        and any(
            isinstance(entry, dict)
            and _invokes_expected_hook(
                entry,
                expected_runner=expected_runner,
                expected_script=expected_script,
                expected_timeout=protected.timeout,
                config_home=config_home,
            )
            for entry in group["hooks"]
        )
        for group in groups
    )


def _provider_prefixed_model_surface(settings: dict) -> str | None:
    """Name the first settings surface carrying a provider-specific model ID.

    A settings file is provider-agnostic: it is read by every launcher, including
    the first-party ones. A region-qualified Bedrock ID there is resolvable only by
    a Bedrock backend, so a 1P session cannot resolve it and silently falls back to
    ``fallbackModel`` -- and every model-id consumer (the statusline's backend
    label, the auto-mode Bash safety classifier) reads the poisoned string as
    though the session really were on Bedrock.

    ``bin/architecture-drift-check.py::check_global_model`` gates these same three
    surfaces, but only ever sees the COMMITTED file. ``/model`` writes the LIVE one,
    which never crosses that gate -- which is how the same misroute reached a
    running session on 2026-06-18, 06-21, 06-26, 08-18 and 08-28. Blocking at the
    write seam is what those five recurrences have in common.

    Returns the surface name for the block reason, or None when clean. The value
    itself is deliberately NOT returned: block reasons in this hook never echo
    settings contents.
    """

    model = settings.get("model")
    if isinstance(model, str) and model.startswith(PROVIDER_MODEL_PREFIXES):
        return "`model`"

    fallback = settings.get("fallbackModel")
    candidates = fallback if isinstance(fallback, list) else [fallback]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith(PROVIDER_MODEL_PREFIXES):
            return "`fallbackModel`"

    env = settings.get("env")
    if isinstance(env, dict):
        # Sorted so a file with several offending entries always names the same
        # surface; an unordered scan makes the block reason nondeterministic and
        # therefore untestable.
        for key in sorted(env):
            value = env[key]
            if isinstance(value, str) and value.startswith(PROVIDER_MODEL_PREFIXES):
                return f"`env.{key}`"

    return None


def main() -> int:
    try:
        raw_event = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if len(raw_event) > MAX_EVENT_BYTES:
            return block(
                "ConfigChange event cannot be validated; existing policy remains active."
            )
        event = json.loads(raw_event.decode("utf-8"))
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return block(
            "ConfigChange event cannot be validated; existing policy remains active."
        )

    if not isinstance(event, dict):
        return block(
            "ConfigChange event cannot be validated; existing policy remains active."
        )
    source = event.get("source")
    if not isinstance(source, str):
        return 0
    source_label = SETTINGS_SOURCE_LABELS.get(source)
    if source_label is None:
        return 0

    file_path = event.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return block(
            f"Changed {source_label} cannot be read; existing policy remains active."
        )
    if os.path.islink(file_path):
        return block(
            f"Changed {source_label} cannot be read; existing policy remains active."
        )
    try:
        path_stat = os.lstat(file_path)
        if not stat.S_ISREG(path_stat.st_mode):
            return block(
                f"Changed {source_label} cannot be read; existing policy remains active."
            )
    except (OSError, ValueError):
        return block(
            f"Changed {source_label} cannot be read; existing policy remains active."
        )
    open_flags = os.O_RDONLY
    for optional_flag in ("O_BINARY", "O_NOFOLLOW", "O_NONBLOCK"):
        open_flags |= getattr(os, optional_flag, 0)
    try:
        descriptor = os.open(file_path, open_flags)
        with os.fdopen(descriptor, "rb") as settings_file:
            opened_stat = os.fstat(settings_file.fileno())
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or (opened_stat.st_dev, opened_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                return block(
                    f"Changed {source_label} cannot be read; existing policy remains active."
                )
            if opened_stat.st_size > MAX_SETTINGS_BYTES:
                return block(
                    f"Changed {source_label} exceed the 4 MiB validation limit; existing policy remains active."
                )
            raw_settings = settings_file.read(MAX_SETTINGS_BYTES + 1)
    except (OSError, ValueError):
        return block(
            f"Changed {source_label} cannot be read; existing policy remains active."
        )
    if len(raw_settings) > MAX_SETTINGS_BYTES:
        return block(
            f"Changed {source_label} exceed the 4 MiB validation limit; existing policy remains active."
        )
    try:
        settings = json.loads(raw_settings.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return block(
            f"Changed {source_label} are not valid JSON; existing policy remains active."
        )
    if not isinstance(settings, dict):
        return block(
            f"Changed {source_label} must be a JSON object; existing policy remains active."
        )
    # A tool call cannot mutate the environment of its already-running Claude
    # parent.  The operator must therefore set this before starting the session;
    # settings content alone can never activate this narrowly scoped registry-
    # removal authorization.  Independent validity and disableAllHooks
    # protections still apply.
    allow_protected_hook_removal = (
        source == "user_settings"
        and os.environ.get(PROTECTED_HOOK_REMOVAL_ENV) == "1"
    )
    if settings.get("disableAllHooks") is True:
        return block(
            f"Changed {source_label} set disableAllHooks=true; existing hooks remain active."
        )
    if (
        source == "user_settings"
        and not allow_protected_hook_removal
        and "hooks" in settings
        and isinstance(settings["hooks"], dict)
        and not settings["hooks"]
    ):
        return block(
            "Changed user settings explicitly empty the hooks object; existing hooks remain active."
        )
    if (
        source == "user_settings"
        and not allow_protected_hook_removal
        and not _has_protected_user_hooks(settings, file_path)
    ):
        return block(
            "Changed user settings remove required protected hooks; existing hooks remain active."
        )
    # Checked last so the hook-integrity boundary above always owns the block
    # reason when a change violates both.
    model_surface = _provider_prefixed_model_surface(settings)
    if model_surface is not None:
        return block(
            f"Changed {source_label} set {model_surface} to a provider-specific "
            "(Bedrock/GovCloud) model ID; existing model configuration remains "
            "active. Settings are shared by every launcher and must use "
            "1P-format `claude-*` IDs; provider-specific IDs belong only in a "
            "launcher's own ANTHROPIC_MODEL export. If you picked this model "
            "from a Bedrock or GovCloud session, re-run /model from a plain "
            "`claude` session."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
