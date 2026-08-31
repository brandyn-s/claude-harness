"""Release contract for HOME-independent, shell-free hook registration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from hook_exec_form import (
    _is_absolute_exec_path,
    configured_hook_embeds_dispatcher,
    configured_hook_invocation,
    configured_hook_is_malformed,
    configured_hook_script,
    configured_hook_uses_dispatcher,
)

REPO = Path(__file__).resolve().parent.parent


def test_absolute_exec_classifier_is_host_independent():
    assert _is_absolute_exec_path("/Users/example/.claude/hooks/run-hook")
    assert _is_absolute_exec_path("C:/Users/example/.claude/hooks/run-hook")
    assert not _is_absolute_exec_path("relative/hooks/run-hook")


def _command_hooks(settings_path: Path):
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    for event, groups in settings.get("hooks", {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("type") == "command":
                    yield event, hook


def test_all_registered_hooks_use_absolute_exec_form_without_shell_expansion():
    for filename in ("settings.json", "settings.example.json"):
        hooks = list(_command_hooks(REPO / filename))
        assert hooks, f"{filename} has no command hooks"
        for event, hook in hooks:
            command = hook.get("command", "")
            args = hook.get("args")
            assert _is_absolute_exec_path(command), (
                f"{filename} {event}: command is not absolute: {command!r}"
            )
            assert "$" not in command and "~" not in command, (
                f"{filename} {event}: command depends on shell expansion: {command!r}"
            )
            assert isinstance(args, list), (
                f"{filename} {event}: exec-form args list is missing for {command!r}"
            )
            assert all(isinstance(arg, str) for arg in args)
            assert not any(token in command for token in ("$", "~", "`", "\n", "\r"))
            assert not any(
                token in arg for arg in args for token in ("\x00", "\n", "\r")
            )


def test_run_hook_registrations_pass_exactly_one_python_script_argument():
    for filename in ("settings.json", "settings.example.json"):
        for event, hook in _command_hooks(REPO / filename):
            if Path(hook["command"]).name != "run-hook":
                continue
            args = hook["args"]
            assert len(args) == 1 and args[0].endswith(".py"), (
                f"{filename} {event}: malformed run-hook argv {args!r}"
            )


def test_status_line_registration_does_not_depend_on_home_expansion():
    for filename in ("settings.json", "settings.example.json"):
        settings = json.loads((REPO / filename).read_text(encoding="utf-8"))
        command = settings.get("statusLine", {}).get("command", "")
        assert _is_absolute_exec_path(command), f"{filename}: {command!r}"
        assert "$" not in command and "~" not in command


def test_status_line_launcher_runs_without_home(tmp_path):
    config = tmp_path / ".claude"
    bin_dir = config / "bin"
    bin_dir.mkdir(parents=True)
    launcher = bin_dir / "statusline-launcher"
    shutil.copy2(REPO / "bin" / "statusline-launcher", launcher)
    launcher.chmod(0o755)
    (config / "statusline.py").write_text(
        "import sys\nprint('HOMELESS:' + sys.stdin.read())\n", encoding="utf-8"
    )
    env = dict(os.environ)
    for key in ("HOME", "USERPROFILE", "CLAUDE_HUD"):
        env.pop(key, None)

    result = subprocess.run(
        [str(launcher)],
        input="payload",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "HOMELESS:payload"


def test_ship_hook_generator_uses_the_same_exec_form_contract():
    body = (REPO / "skills" / "ship-hook" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert 'scripts/wire_hooks.py' in body
    assert '"$PYTHON_BIN" "$REGISTRAR"' in body
    assert '"{EVENT}|{MATCHER}|{name}.py|{TIMEOUT}"' in body
    assert "Do not fall back to direct" in body
    assert "CLAUDE_PLUGIN_ROOT" in body
    assert "read_text(encoding='utf-8')" not in body
    assert '"$HOME/.claude/hooks/run-hook"' not in body


def test_legacy_hook_identity_survives_trailing_arguments():
    assert configured_hook_script(
        {
            "type": "command",
            "command": 'python "/absolute/hooks/guard.py" --mode strict',
        }
    ) == "guard.py"


def test_dispatcher_identity_is_the_first_script_and_keeps_trailing_python_args():
    script, trailing = configured_hook_invocation(
        {
            "type": "command",
            "command": "/absolute/hooks/run-hook",
            "args": ["guard.py", "--mode", "strict", "payload.py"],
        }
    )

    assert script == "guard.py"
    assert trailing == ["--mode", "strict", "payload.py"]


def test_native_windows_dispatcher_identity_precedes_trailing_python_argument(tmp_path):
    bash = tmp_path / "Program Files" / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\n", encoding="utf-8")
    hook = {
        "type": "command",
        "command": str(bash),
        "args": [
            "C:/Users/example/.claude/hooks/run-hook",
            "guard.py",
            "payload.py",
        ],
    }
    script, trailing = configured_hook_invocation(hook)

    assert configured_hook_uses_dispatcher(hook) is True
    assert script == "guard.py"
    assert trailing == ["payload.py"]


def test_legacy_identity_is_first_script_not_later_python_argument():
    script, trailing = configured_hook_invocation(
        {
            "type": "command",
            "command": 'python "/absolute/hooks/guard.py" --mode strict payload.py',
        }
    )

    assert script == "guard.py"
    assert trailing == ["--mode", "strict", "payload.py"]


def test_trailing_run_hook_basename_is_not_mistaken_for_dispatcher():
    script, trailing = configured_hook_invocation(
        {
            "type": "command",
            "command": (
                "python /old/hooks/guard.py --helper /data/run-hook payload.py"
            ),
        }
    )

    assert script == "guard.py"
    assert trailing == ["--helper", "/data/run-hook", "payload.py"]


def test_direct_shell_hook_keeps_first_payload_argument_named_run_hook():
    script, trailing = configured_hook_invocation(
        {
            "type": "command",
            "command": "/old/hooks/guard.sh",
            "args": ["/data/run-hook", "payload.py"],
        }
    )

    assert script == "guard.sh"
    assert trailing == ["/data/run-hook", "payload.py"]


def test_dispatcher_requires_immediate_unquoted_basename_target():
    for args in (["--mode", "guard.py"], ["../guard.py"], ["'guard.py'"]):
        script, trailing = configured_hook_invocation(
            {
                "type": "command",
                "command": "/old/hooks/run-hook",
                "args": args,
            }
        )

        assert script is None
        assert trailing == []


def test_program_files_bash_dispatcher_rejects_pre_target_tokens(tmp_path):
    bash = tmp_path / "Program Files" / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\n", encoding="utf-8")
    hook = {
        "type": "command",
        "command": str(bash),
        "args": [
            "C:/Users/example/.claude/hooks/run-hook",
            "--mode",
            "guard.py",
        ],
    }

    assert configured_hook_uses_dispatcher(hook) is True
    assert configured_hook_invocation(hook) == (None, [])


def test_structured_exec_form_does_not_repair_embedded_dispatcher_argv():
    for command in (
        "/bin/bash /old/hooks/run-hook",
        "/bin/bash --noprofile /old/hooks/run-hook",
        "/usr/bin/env bash /old/hooks/run-hook",
        "/usr/bin/nohup /bin/bash /old/hooks/run-hook",
        "/usr/bin/sudo /bin/bash /old/hooks/run-hook",
        "/usr/bin/env -S 'bash /old/hooks/run-hook'",
        '"C:/Program Files/Git/bin/bash.exe" C:/Users/example/.claude/hooks/run-hook',
    ):
        hook = {
            "type": "command",
            "command": command,
            "args": ["guard.py"],
        }

        assert configured_hook_embeds_dispatcher(hook) is True
        assert configured_hook_uses_dispatcher(hook) is False
        assert configured_hook_invocation(hook) == (None, [])


def test_structured_exec_form_rejects_wrapped_direct_hook_commands():
    for command in (
        "/usr/bin/python /old/hooks/guard.py",
        "/usr/bin/env python /old/hooks/guard.py",
        "/bin/bash /old/hooks/guard.sh",
        "/usr/bin/nohup /other/bash",
        "/bin/echo C:/Program Files/Git/bin/bash.exe",
        "C:/Windows/System32/cmd.exe C:/Program Files/Git/bin/bash.exe",
        "C:/Windows/System32/cmd.exe Program Files/Git/bin/bash.exe",
        "C:/Tools/wrapper.ps1 Program Files/Git/bin/bash.exe",
        "/bin/true&/old/hooks/run-hook",
        "'/old/hooks/guard.py'",
    ):
        hook = {"type": "command", "command": command, "args": []}

        assert configured_hook_is_malformed(hook) is True
        assert configured_hook_invocation(hook) == (None, [])


def test_structured_payload_script_names_are_not_hook_identity():
    for command, args in (
        ("/usr/bin/logger", ["guard.py"]),
        ("/usr/bin/printf", ["payload.py", "guard.py"]),
        ("/usr/bin/env", ["guard.py"]),
    ):
        hook = {"type": "command", "command": command, "args": args}

        assert configured_hook_is_malformed(hook) is False
        assert configured_hook_invocation(hook) == (None, [])


def test_legacy_migration_rejects_unparseable_or_semantic_wrappers():
    for command in (
        'python "/old/hooks/guard.py --mode',
        'python /old/hooks/guard.py "unterminated',
        "false && python /old/hooks/guard.py --mode strict",
        "python /old/hooks/guard.py || true",
        "FOO=bar python /old/hooks/guard.py",
        "/usr/bin/env FOO=bar python /old/hooks/guard.py",
        "timeout 5 python /old/hooks/guard.py",
        "nice -n 10 python /old/hooks/guard.py",
        "python -B /old/hooks/guard.py --mode",
        "python /old/hooks/guard.py 2>/tmp/log",
        "/old/hooks/run-hook guard.py 2>/tmp/log",
        "python /old/hooks/guard.py $PAYLOAD",
        'python /old/hooks/guard.py --label "$PAYLOAD"',
        'python /old/hooks/guard.py --label "$(echo unsafe)"',
        'python /old/hooks/guard.py --label "`echo unsafe`"',
        "python /old/hooks/guard.py ~/payload",
        "/old/hooks/run-hook guard.py ~/payload",
        "python /old/hooks/guard.py |tee",
        "python /old/hooks/guard.py ;echo",
        "python /old/hooks/guard.py &&echo",
        "python /old/hooks/guard.py arg&",
        "python /old/hooks/guard.py # ignored",
        "python /old/hooks/guard.py\necho changed",
        "python /old/hooks/guard.py (echo changed)",
        "/old/hooks/run-hook guard.py (echo changed)",
        "python /old/hooks/guard.py foo(bar)",
        "/old/hooks/run-hook guard.sh",
        '"$HOME/.claude/hooks/run-hook" guard.sh',
        '"$PAYLOAD/run-hook" guard.py',
        '"${PAYLOAD}/run-hook" guard.py',
        "'$PAYLOAD/run-hook' guard.py",
        'python "${PAYLOAD}/guard.py"',
        "python '$PAYLOAD/guard.py'",
        "bash '$PAYLOAD/run-hook' guard.py",
        '"~/other/run-hook" guard.py',
        "'~/other/run-hook' guard.py",
        '"%PAYLOAD%\\run-hook" guard.py',
        '"%ProgramFiles(x86)%\\Git\\hooks\\run-hook" guard.py',
        '"%PROGRAM-FILES%\\Git\\hooks\\run-hook" guard.py',
        '"%Program Files%\\Git\\hooks\\run-hook" guard.py',
        '"%USERPROFILE%%HOME%\\.claude\\hooks\\run-hook" guard.py',
        '"%USERPROFILE%X\\.claude\\hooks\\run-hook" guard.py',
        (
            '"C:\\Program Files\\Git\\bin\\bash.exe" '
            '"C:\\old\\hooks\\run-hook" guard.py --label "%PAYLOAD%"'
        ),
        (
            '"C:\\old\\hooks\\run-hook" guard.py '
            '--label "%ProgramFiles(x86)%"'
        ),
        '"C:\\old\\hooks\\run-hook" guard.py \'x& calc\'',
        '"C:\\Python\\python.exe" "C:\\old\\hooks\\guard.py" \'x| calc\'',
        '"C:/Program Files/Git/bin/bash.exe" C:/old/hooks/run-hook guard.sh',
    ):
        hook = {"type": "command", "command": command}

        assert configured_hook_invocation(hook) == (None, [])


def test_legacy_direct_shell_hook_remains_migratable():
    hook = {
        "type": "command",
        "command": "/old/hooks/guard.sh --mode strict",
    }

    assert configured_hook_invocation(hook) == ("guard.sh", ["--mode", "strict"])


def test_legacy_quoted_literal_arguments_remain_migratable():
    hook = {
        "type": "command",
        "command": (
            "python /old/hooks/guard.py --label 'alpha#beta' "
            "'$PAYLOAD' 'foo(bar)'"
        ),
    }

    assert configured_hook_invocation(hook) == (
        "guard.py",
        ["--label", "alpha#beta", "$PAYLOAD", "foo(bar)"],
    )


def test_legacy_escaped_and_posix_percent_literals_remain_migratable():
    hook = {
        "type": "command",
        "command": (
            'python /old/hooks/guard.py --label "\\$PAYLOAD" '
            '"\\`echo literal\\`" \'%PAYLOAD%\''
        ),
    }

    assert configured_hook_invocation(hook) == (
        "guard.py",
        ["--label", "$PAYLOAD", "`echo literal`", "%PAYLOAD%"],
    )


def test_legacy_home_dispatcher_path_remains_migratable():
    hook = {
        "type": "command",
        "command": '"$HOME/.claude/hooks/run-hook" guard.py --mode strict',
    }

    assert configured_hook_invocation(hook) == ("guard.py", ["--mode", "strict"])


def test_legacy_tilde_dispatcher_path_remains_migratable():
    hook = {
        "type": "command",
        "command": "~/.claude/hooks/run-hook guard.py --mode strict",
    }

    assert configured_hook_invocation(hook) == ("guard.py", ["--mode", "strict"])


def test_legacy_posix_escaped_space_paths_remain_migratable():
    cases = [
        (
            "/Users/First\\ Last/.claude/hooks/run-hook guard.py --mode strict",
            ("guard.py", ["--mode", "strict"]),
        ),
        (
            "python /Users/First\\ Last/.claude/hooks/guard.py --mode strict",
            ("guard.py", ["--mode", "strict"]),
        ),
    ]

    for command, expected in cases:
        assert configured_hook_invocation(
            {"type": "command", "command": command}
        ) == expected


def test_legacy_quoted_windows_paths_remain_migratable():
    cases = [
        (
        (
            '"C:\\Program Files\\Git\\bin\\bash.exe" '
                '"C:\\Users\\First Last\\.claude\\hooks\\run-hook" '
                "guard.py --mode strict"
            ),
            ("guard.py", ["--mode", "strict"]),
        ),
        (
            (
                '"C:\\Program Files (x86)\\Git\\bin\\bash.exe" '
                '"C:\\Users\\First Last\\.claude\\hooks\\run-hook" '
                "guard.py --mode strict"
            ),
            ("guard.py", ["--mode", "strict"]),
        ),
        (
            '"%USERPROFILE%\\.claude\\hooks\\run-hook" guard.py --mode strict',
            ("guard.py", ["--mode", "strict"]),
        ),
        (
            '"%userprofile%\\.claude\\hooks\\run-hook" guard.py --mode strict',
            ("guard.py", ["--mode", "strict"]),
        ),
        (
            '"C:\\Users\\First Last\\.claude\\hooks\\guard.sh" --mode strict',
            ("guard.sh", ["--mode", "strict"]),
        ),
        (
            (
                '"C:\\Python\\python.exe" '
                '"C:\\Users\\First Last\\.claude\\hooks\\guard.py" '
                "--mode strict"
            ),
            ("guard.py", ["--mode", "strict"]),
        ),
    ]

    for command, expected in cases:
        hook = {"type": "command", "command": command}
        assert configured_hook_invocation(hook) == expected


def test_legacy_windows_double_quoted_control_text_remains_migratable():
    hook = {
        "type": "command",
        "command": (
            '"C:\\old\\hooks\\run-hook" guard.py '
            '--label "x& y|z (literal)"'
        ),
    }

    assert configured_hook_invocation(hook) == (
        "guard.py",
        ["--label", "x& y|z (literal)"],
    )


def test_structured_exec_form_rejects_invalid_argument_shapes():
    for args in (
        "payload.py",
        ["guard.py", {"bad": 1}, "payload.py"],
        ["guard.py", 7],
        ["guard.py", None],
    ):
        hook = {
            "type": "command",
            "command": "/old/hooks/run-hook",
            "args": args,
        }

        assert configured_hook_is_malformed(hook) is True
        assert configured_hook_invocation(hook) == (None, [])


def test_existing_direct_hook_path_with_spaces_is_not_shell_split(tmp_path):
    hook_path = tmp_path / "bash User" / ".claude" / "hooks" / "run-hook"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_text("#!/bin/sh\n", encoding="utf-8")
    hook = {
        "type": "command",
        "command": str(hook_path),
        "args": ["guard.py"],
    }

    assert configured_hook_is_malformed(hook) is False
    assert configured_hook_uses_dispatcher(hook) is True
    assert configured_hook_invocation(hook) == ("guard.py", [])
