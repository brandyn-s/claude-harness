"""Materialize portable Claude Code command-hook exec form."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

SAFE_MISSING_EXECUTABLE_RE = re.compile(r"^[A-Za-z0-9_@+,.=:/\\-]+$")
LEGACY_WINDOWS_PATH_RE = re.compile(
    r"(?:^|[\s\"'])(?:[A-Za-z]:[/\\]|%[^%\r\n]+%[/\\]|\\\\[^\\])",
    re.IGNORECASE,
)
LEGACY_PROFILE_EXPANSION_RE = re.compile(
    r"%[^%\r\n]+%",
    re.IGNORECASE,
)
LEGACY_SHELL_SYNTAX_CHARS = frozenset(";&|<>`*?[]{}#()")


def normalize_exec_path(value: str | os.PathLike[str]) -> str:
    """Return an absolute-path spelling accepted by Windows and POSIX hooks."""

    return os.fspath(value).replace("\\", "/")


def _git_bash_identity(candidate: Path) -> str:
    try:
        result = subprocess.run(
            [str(candidate), "-lc", "uname -s"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not execute Git Bash candidate {candidate}: {exc}") from exc
    identity = result.stdout.strip().upper()
    if result.returncode != 0 or not identity.startswith(("MINGW", "MSYS", "CYGWIN")):
        raise RuntimeError(
            f"bash.exe is not Git Bash (identity={identity or 'unavailable'}): {candidate}"
        )
    return identity


def resolve_git_bash(explicit: str | None = None) -> str:
    """Resolve and behavior-check Git for Windows' bash.exe."""

    configured = explicit or os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    candidates: list[Path] = []
    if configured:
        path = Path(configured)
        if not path.is_absolute() or not path.is_file():
            raise RuntimeError(
                "CLAUDE_CODE_GIT_BASH_PATH/bash_executable must name an existing absolute bash.exe"
            )
        candidates.append(path)
    else:
        if os.name == "nt":
            for variable in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
                base = os.environ.get(variable)
                if base:
                    candidates.extend(
                        [
                            Path(base) / "Git" / "bin" / "bash.exe",
                            Path(base) / "Programs" / "Git" / "bin" / "bash.exe",
                        ]
                    )
            git = shutil.which("git.exe")
            if git:
                candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
        discovered = shutil.which("bash.exe")
        if discovered:
            candidates.append(Path(discovered))

    failures = []
    seen = set()
    for candidate in candidates:
        normalized = normalize_exec_path(candidate)
        if normalized in seen or not candidate.is_file():
            continue
        seen.add(normalized)
        try:
            _git_bash_identity(candidate)
            return normalized
        except RuntimeError as exc:
            failures.append(str(exc))
    detail = "; ".join(failures) if failures else "no candidate was found"
    raise RuntimeError(
        "Git Bash bash.exe was not found or validated; set "
        f"CLAUDE_CODE_GIT_BASH_PATH ({detail})"
    )


def hook_exec_argv(
    config_dir: PurePath,
    hook_file: str,
    *,
    native_windows: bool | None = None,
    bash_executable: str | None = None,
    bash_is_validated: bool = False,
) -> tuple[str, list[str]]:
    """Build ``command`` and ``args`` for POSIX or native Windows."""

    if native_windows is None:
        native_windows = os.name == "nt"
    run_hook = normalize_exec_path(config_dir / "hooks" / "run-hook")
    if not native_windows:
        return run_hook, [hook_file]

    if bash_is_validated:
        if not bash_executable:
            raise RuntimeError("validated Git Bash path is missing")
        bash = normalize_exec_path(bash_executable)
    else:
        bash = resolve_git_bash(bash_executable)
    return bash, [run_hook, hook_file]


def is_bash_launcher(value: str) -> bool:
    """Return whether *value* is the supported Bash dispatcher launcher."""

    name = Path(value.strip("\"'").replace("\\", "/")).name.lower()
    return name in {"bash", "bash.exe"}


def _is_absolute_exec_path(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _legacy_uses_windows_quoting(value: str) -> bool:
    return bool(LEGACY_WINDOWS_PATH_RE.search(value))


def _unquoted_projection(value: str, *, windows: bool = False) -> str:
    """Return only shell-active text, replacing quoted/escaped data with spaces."""

    quote = None
    escaped = False
    projected = []
    for character in value:
        if windows:
            if quote == '"':
                if character == '"':
                    quote = None
                projected.append(" ")
                continue
            if character == '"':
                quote = '"'
                projected.append(" ")
            else:
                projected.append(character)
            continue
        if escaped:
            escaped = False
            projected.append(" ")
            continue
        if character == "\\" and quote != "'":
            escaped = True
            projected.append(" ")
            continue
        if quote is not None:
            if character == quote:
                quote = None
            projected.append(" ")
            continue
        if character in {'"', "'"}:
            quote = character
            projected.append(" ")
        else:
            projected.append(character)
    return "".join(projected)


def _normalize_posix_double_quote_escapes(value: str) -> str:
    """Remove expansion escapes that ``shlex`` retains inside double quotes."""

    quote = None
    index = 0
    normalized = []
    while index < len(value):
        character = value[index]
        if character in {'"', "'"}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            normalized.append(character)
            index += 1
            continue
        if (
            quote == '"'
            and character == "\\"
            and index + 1 < len(value)
            and value[index + 1] in {"$", "`"}
        ):
            normalized.append(value[index + 1])
            index += 2
            continue
        normalized.append(character)
        index += 1
    return "".join(normalized)


def _expansion_active_projection(value: str) -> str:
    """Keep POSIX expansion text outside single quotes.

    Double quotes suppress shell operators but still permit parameter and
    command substitution. Backslash only suppresses the characters for which
    it is meaningful inside double quotes.
    """

    quote = None
    index = 0
    projected = []
    while index < len(value):
        character = value[index]
        if quote == "'":
            if character == "'":
                quote = None
            projected.append(" ")
            index += 1
            continue
        if quote == '"':
            if character == '"':
                quote = None
                projected.append(" ")
                index += 1
                continue
            if character == "\\" and index + 1 < len(value):
                escaped = value[index + 1]
                if escaped in {'$', '`', '"', "\\", "\n"}:
                    projected.extend((" ", " "))
                    index += 2
                    continue
            projected.append(character)
            index += 1
            continue
        if character == "'":
            quote = "'"
            projected.append(" ")
            index += 1
            continue
        if character == '"':
            quote = '"'
            projected.append(" ")
            index += 1
            continue
        if character == "\\" and index + 1 < len(value):
            projected.extend((" ", " "))
            index += 2
            continue
        projected.append(character)
        index += 1
    return "".join(projected)


def _contains_unquoted(value: str, characters: frozenset[str]) -> bool:
    return any(character in characters for character in _unquoted_projection(value))


def _command_starts_active_home(command: str) -> bool:
    start = command.lstrip()
    return start.startswith(("$HOME/", '"$HOME/'))


def _command_starts_active_tilde(command: str) -> bool:
    return command.lstrip().startswith("~/")


def _command_starts_active_profile(command: str) -> bool:
    start = command.lstrip().upper()
    return start.startswith(
        (
            "%HOME%/",
            "%HOME%\\",
            "%USERPROFILE%/",
            "%USERPROFILE%\\",
            '"%HOME%/',
            '"%HOME%\\',
            '"%USERPROFILE%/',
            '"%USERPROFILE%\\',
        )
    )


def _path_token_has_expansion_syntax(value: str) -> bool:
    return (
        "$" in value
        or "`" in value
        or "~" in value
        or LEGACY_PROFILE_EXPANSION_RE.search(value) is not None
    )


def _exact_executable_exists(value: str) -> bool:
    try:
        return Path(value).is_file()
    except OSError:
        return False


def configured_hook_is_malformed(hook: dict) -> bool:
    """Return whether a structured command hook violates exec-form grammar.

    An ``args`` key selects Claude's structured exec form. Its command is one
    executable path, never a shell string. Space-bearing paths are ambiguous
    without shell interpretation, so accept them only when the exact path
    exists on this host. Cross-host paths with spaces must be re-materialized
    on their native host rather than guessed. Legacy registrations omit
    ``args`` and remain eligible for migration.
    """

    if "args" not in hook:
        return False
    command = hook.get("command")
    args = hook.get("args")
    if (
        not isinstance(command, str)
        or not command
        or not isinstance(args, list)
        or not all(isinstance(value, str) for value in args)
        or not _is_absolute_exec_path(command)
    ):
        return True
    if _exact_executable_exists(command):
        return False
    return SAFE_MISSING_EXECUTABLE_RE.fullmatch(command) is None


def configured_hook_embeds_dispatcher(hook: dict) -> bool:
    """Return whether structured exec form embeds dispatcher argv in command."""

    command = hook.get("command", "")
    args = hook.get("args")
    if (
        not configured_hook_is_malformed(hook)
        or not isinstance(command, str)
        or not isinstance(args, list)
    ):
        return False
    try:
        tokens = shlex.split(command, posix=not _legacy_uses_windows_quoting(command))
    except ValueError:
        return False
    if len(tokens) < 2:
        return False

    def is_dispatcher(value: str) -> bool:
        return Path(value.strip("\"'").replace("\\", "/")).name == "run-hook"

    return any(is_dispatcher(token) for token in tokens)


def _configured_tokens(hook: dict) -> tuple[list[str], list[str]]:
    """Return command and argument tokens without shell-splitting exec form.

    Claude's structured command-hook form treats ``command`` as one executable
    whenever a list-valued ``args`` field is present.  Legacy shell-form hook
    registrations omit ``args`` and still need tokenization for migration.
    """

    command = hook.get("command", "")
    args = hook.get("args")
    if "args" in hook:
        if configured_hook_is_malformed(hook):
            return [], []
        if not isinstance(command, str) or not isinstance(args, list):
            return [], []
        return [command], list(args)
    if not isinstance(command, str) or not command:
        return [], []
    windows_quoting = _legacy_uses_windows_quoting(command)
    parse_command = (
        command if windows_quoting else _normalize_posix_double_quote_escapes(command)
    )
    try:
        command_tokens = shlex.split(
            parse_command,
            posix=not windows_quoting,
        )
    except ValueError:
        return [], []
    command_tokens = [
        token[1:-1]
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
        else token
        for token in command_tokens
    ]
    if any(character in command for character in ("\x00", "\n", "\r")):
        return [], []
    unquoted = _unquoted_projection(command, windows=windows_quoting)
    expansion_active = _expansion_active_projection(command)
    if windows_quoting and "'" in unquoted:
        return [], []
    if any(character in unquoted for character in LEGACY_SHELL_SYNTAX_CHARS):
        return [], []
    if not command_tokens:
        return [], []
    executable = command_tokens[0].replace("\\", "/")
    active_home = (
        expansion_active.count("$") == 1
        and executable.count("$") == 1
        and executable.startswith("$HOME/")
        and _command_starts_active_home(command)
    )
    if "$" in expansion_active and not active_home:
        return [], []
    if "$" in executable and not active_home:
        return [], []
    if "`" in expansion_active or "`" in executable:
        return [], []
    active_tilde = (
        unquoted.count("~") == 1
        and executable.count("~") == 1
        and executable.startswith("~/")
        and _command_starts_active_tilde(command)
    )
    if "~" in unquoted and not active_tilde:
        return [], []
    if "~" in executable and not active_tilde:
        return [], []
    profile_expansions = (
        LEGACY_PROFILE_EXPANSION_RE.findall(command) if windows_quoting else []
    )
    active_profile = (
        len(profile_expansions) == 1
        and len(LEGACY_PROFILE_EXPANSION_RE.findall(executable)) == 1
        and executable.upper().startswith(("%HOME%/", "%USERPROFILE%/"))
        and _command_starts_active_profile(command)
    )
    if profile_expansions and not active_profile:
        return [], []
    if LEGACY_PROFILE_EXPANSION_RE.search(executable) and not active_profile:
        return [], []
    return command_tokens, []


def _is_python_launcher(value: str) -> bool:
    name = Path(value.replace("\\", "/")).name.lower()
    return bool(re.fullmatch(r"pythonw?(?:\d+(?:\.\d+)*)?(?:\.exe)?", name))


def _is_shell_launcher(value: str) -> bool:
    name = Path(value.replace("\\", "/")).name.lower()
    return name in {"bash", "bash.exe", "dash", "ksh", "sh", "zsh"}


def _is_dispatcher(value: str) -> bool:
    return Path(value.replace("\\", "/")).name == "run-hook"


def _dispatcher_invocation(
    tokens: list[str], dispatcher_index: int
) -> tuple[str | None, list[str]]:
    target_index = dispatcher_index + 1
    if target_index >= len(tokens):
        return None, []
    raw_target = tokens[target_index]
    target = Path(raw_target.replace("\\", "/")).name
    if raw_target != target or not target.endswith(".py"):
        return None, []
    return target, tokens[target_index + 1 :]


def _legacy_invocation(tokens: list[str]) -> tuple[str | None, list[str]]:
    if not tokens:
        return None, []
    if _is_dispatcher(tokens[0]):
        return _dispatcher_invocation(tokens, 0)
    if (
        _is_shell_launcher(tokens[0])
        and len(tokens) > 1
        and _is_dispatcher(tokens[1])
    ):
        if _path_token_has_expansion_syntax(tokens[1]):
            return None, []
        return _dispatcher_invocation(tokens, 1)

    first = tokens[0]
    first_name = Path(first.replace("\\", "/")).name
    if first_name.endswith((".py", ".sh")):
        return first_name, tokens[1:]
    if len(tokens) < 2:
        return None, []
    candidate = tokens[1]
    if _path_token_has_expansion_syntax(candidate):
        return None, []
    script = Path(candidate.replace("\\", "/")).name
    if _is_python_launcher(first) and candidate.endswith(".py"):
        return script, tokens[2:]
    if _is_shell_launcher(first) and candidate.endswith(".sh"):
        return script, tokens[2:]
    return None, []


def configured_hook_uses_dispatcher(hook: dict) -> bool:
    """Return whether the configured invocation uses the run-hook dispatcher."""

    if configured_hook_is_malformed(hook):
        return False
    command_tokens, arg_tokens = _configured_tokens(hook)
    if not command_tokens:
        return False
    if "args" not in hook:
        return _is_dispatcher(command_tokens[0]) or bool(
            _is_shell_launcher(command_tokens[0])
            and len(command_tokens) > 1
            and _is_dispatcher(command_tokens[1])
        )
    return _is_dispatcher(command_tokens[0]) or bool(
        is_bash_launcher(command_tokens[0])
        and arg_tokens
        and _is_dispatcher(arg_tokens[0])
    )


def configured_hook_invocation(hook: dict) -> tuple[str | None, list[str]]:
    """Return a hook's script identity and every argument that follows it.

    Claude command hooks may use a POSIX dispatcher, Git Bash on native
    Windows, or a legacy interpreter command.  The dispatcher target (or the
    first script in a legacy command) is the hook identity; later ``.py``
    values are ordinary hook arguments and must not replace that identity.
    """

    if configured_hook_is_malformed(hook):
        return None, []
    command_tokens, arg_tokens = _configured_tokens(hook)
    if "args" not in hook:
        return _legacy_invocation(command_tokens)
    tokens = [*command_tokens, *arg_tokens]

    dispatcher_index = None
    if command_tokens and _is_dispatcher(command_tokens[0]):
        dispatcher_index = 0
    elif (
        command_tokens
        and is_bash_launcher(command_tokens[0])
        and arg_tokens
        and _is_dispatcher(arg_tokens[0])
    ):
        # Native Windows invokes behavior-validated bash.exe with run-hook as
        # argv[0]. A later basename of run-hook is ordinary hook data.
        dispatcher_index = len(command_tokens)
    if dispatcher_index is not None:
        return _dispatcher_invocation(tokens, dispatcher_index)

    command = command_tokens[0] if command_tokens else ""
    script = Path(command.replace("\\", "/")).name
    if script.endswith((".py", ".sh")):
        return script, arg_tokens
    return None, []


def configured_hook_script(hook: dict) -> str | None:
    """Return the hook script from POSIX, Windows, or legacy registration."""

    return configured_hook_invocation(hook)[0]
