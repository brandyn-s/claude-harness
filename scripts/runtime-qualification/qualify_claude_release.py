#!/usr/bin/env python3
"""Qualify a native Claude Code release against deterministic loopback probes."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = re.compile(r"^(\d+\.\d+\.\d+)\b")
REPO = Path(__file__).resolve().parents[2]
FORK_ARGUMENT_PLUGIN = "runtime-argument-qualification"
FORK_ARGUMENT_VALUE = "alpha beta gamma"
FORK_EXPLICIT_PREFIX = "RUNTIME_FORK_ARGUMENT_EXPLICIT_BEGIN["
FORK_EXPLICIT_SUFFIX = "]RUNTIME_FORK_ARGUMENT_EXPLICIT_END"
FORK_IMPLICIT_MARKER = "RUNTIME_FORK_ARGUMENT_IMPLICIT_BODY"


class QualificationError(RuntimeError):
    """A release probe failed its deterministic oracle."""


@dataclass(frozen=True)
class Scenario:
    name: str
    tool_name: str | None = None
    tool_input: dict | None = None


@dataclass(frozen=True)
class ClaudeRun:
    events: list[dict]
    stdout: str
    stderr: str
    requests: list[dict]


@dataclass(frozen=True)
class LoopbackCapture:
    base_url: str
    requests: list[dict]


def _sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
        for name, data in events
    ).encode()


def _text_response(model: str) -> bytes:
    return _sse(
        [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_runtime_qualification_text",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 0},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "mock complete"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


def _tool_response(model: str, name: str, tool_input: dict) -> bytes:
    return _sse(
        [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_runtime_qualification_tool",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 0},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_runtime_qualification",
                        "name": name,
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(
                            tool_input, separators=(",", ":")
                        ),
                    },
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


class _LoopbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def do_POST(self) -> None:
        size = int(self.headers.get("content-length", "0"))
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except (TypeError, ValueError):
            body = {}
        self.server.requests.append(body)

        request_path = self.path.split("?", 1)[0]
        if request_path.endswith("/count_tokens"):
            payload = json.dumps({"input_tokens": 1}).encode()
            content_type = "application/json"
        else:
            model = body.get("model") or "claude-test"
            scenario = self.server.scenario
            declared = {
                tool.get("name")
                for tool in body.get("tools", [])
                if isinstance(tool, dict)
            }
            has_tool_result = any(
                isinstance(message, dict)
                and isinstance(message.get("content"), list)
                and any(
                    isinstance(block, dict) and block.get("type") == "tool_result"
                    for block in message["content"]
                )
                for message in body.get("messages", [])
            )
            if (
                body.get("stream")
                and scenario.tool_name in declared
                and not has_tool_result
                and not self.server.tool_sent
            ):
                self.server.tool_sent = True
                payload = _tool_response(
                    model, scenario.tool_name, scenario.tool_input or {}
                )
            else:
                payload = _text_response(model)
            content_type = "text/event-stream"

        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(payload)))
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)


@contextlib.contextmanager
def loopback_server(scenario: Scenario) -> Iterator[LoopbackCapture]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackHandler)
    server.scenario = scenario
    server.requests = []
    server.tool_sent = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield LoopbackCapture(f"http://{host}:{port}", server.requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def native_version(executable: str) -> str:
    result = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise QualificationError(
            f"{executable} --version failed with exit {result.returncode}"
        )
    match = VERSION.match(result.stdout.strip())
    if not match:
        raise QualificationError(
            f"could not parse Claude Code version from {result.stdout.strip()!r}"
        )
    return match.group(1)


def require_blocked_hook(events: list[dict], marker: str) -> None:
    responses = [
        event
        for event in events
        if event.get("type") == "system"
        and event.get("subtype") == "hook_response"
        and event.get("hook_name") == "PreToolUse:Bash"
    ]
    if not any(
        event.get("exit_code") == 2 and marker in event.get("stderr", "")
        for event in responses
    ):
        raise QualificationError(f"blocking hook did not return exit 2 with {marker}")

    non_execution = any(
        meta.get("non_execution_kind") == "permission-rule"
        for event in events
        for meta in event.get("tool_result_meta", [])
        if isinstance(meta, dict)
    )
    if not non_execution:
        raise QualificationError("blocked hook lacks the permission-rule non-execution proof")


def require_unfiltered_bash(events: list[dict], output_marker: str) -> None:
    if any(event.get("subtype") == "hook_started" for event in events):
        raise QualificationError("nonmatching if-scoped hook unexpectedly started")
    if output_marker not in json.dumps(events, separators=(",", ":")):
        raise QualificationError("nonmatching Bash command did not execute")


def require_worker_local(events: list[dict]) -> None:
    init = next(
        (
            event
            for event in events
            if event.get("type") == "system" and event.get("subtype") == "init"
        ),
        None,
    )
    if not init or "Bash" not in init.get("tools", []):
        raise QualificationError("worker session did not expose Bash")
    cwd = init.get("cwd", "")
    if "/.claude/worktrees/" not in cwd:
        raise QualificationError("worker session cwd is not a linked worktree")
    successful_pwd = any(
        isinstance(block, dict)
        and block.get("type") == "tool_result"
        and block.get("content") == cwd
        and block.get("is_error") is False
        for event in events
        for block in (event.get("message") or {}).get("content", [])
    )
    if not successful_pwd:
        raise QualificationError("worker Bash did not execute pwd inside its worktree")


def require_worker_fence(events: list[dict]) -> None:
    refused = any(
        isinstance(block, dict)
        and block.get("type") == "tool_result"
        and block.get("is_error") is True
        and "redirects git to the shared checkout" in block.get("content", "")
        and "Refusing to run it" in block.get("content", "")
        for event in events
        for block in (event.get("message") or {}).get("content", [])
    )
    if not refused:
        raise QualificationError("worker isolation refusal was not observed")


def _request_text_blocks(requests: list[dict]) -> Iterator[str]:
    for request in requests:
        for message in request.get("messages", []):
            if not isinstance(message, dict):
                continue
            content = message.get("content", [])
            if isinstance(content, str):
                yield content
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    yield block["text"]


def require_rendered_fork_arguments(requests: list[dict], argument: str) -> None:
    expected = f"{FORK_EXPLICIT_PREFIX}{argument}{FORK_EXPLICIT_SUFFIX}"
    if not any(expected in block for block in _request_text_blocks(requests)):
        raise QualificationError(
            "context: fork skill did not render the invocation into $ARGUMENTS"
        )


def require_appended_fork_arguments(requests: list[dict], argument: str) -> None:
    expected = f"ARGUMENTS: {argument}"
    same_block = any(
        FORK_IMPLICIT_MARKER in block
        and expected in block
        and block.index(FORK_IMPLICIT_MARKER) < block.index(expected)
        for block in _request_text_blocks(requests)
    )
    if not same_block:
        raise QualificationError(
            "context: fork skill without $ARGUMENTS did not receive an appended "
            "ARGUMENTS field in the same skill block"
        )


def require_success(events: list[dict], expected_version: str) -> None:
    init = next(
        (
            event
            for event in events
            if event.get("type") == "system" and event.get("subtype") == "init"
        ),
        None,
    )
    found = init.get("claude_code_version") if init else None
    if found != expected_version:
        raise QualificationError(
            f"session init reported {found!r}; expected {expected_version!r}"
        )
    if not any(
        event.get("type") == "result"
        and event.get("subtype") == "success"
        and event.get("is_error") is False
        for event in events
    ):
        raise QualificationError("session did not emit a successful terminal result")


def _parse_stream(stdout: str) -> list[dict]:
    events: list[dict] = []
    for number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QualificationError(
                f"Claude stream line {number} is not JSON: {exc.msg}"
            ) from exc
        if not isinstance(event, dict):
            raise QualificationError(f"Claude stream line {number} is not an object")
        events.append(event)
    if not events:
        raise QualificationError("Claude emitted no stream events")
    return events


def _probe_environment(config_dir: Path, base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_ANTHROPIC_AWS",
        "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
        "CLAUDE_CODE_USE_MANTLE",
        "CLAUDE_CODE_USE_GATEWAY",
    ):
        env.pop(key, None)
    env.update(
        {
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "ANTHROPIC_API_KEY": "loopback-runtime-qualification",
            "ANTHROPIC_BASE_URL": base_url,
            "CLAUDE_CODE_DISABLE_TELEMETRY": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "NO_PROXY": "127.0.0.1,localhost",
        }
    )
    return env


def _run_scenario(
    executable: str,
    expected_version: str,
    scratch: Path,
    cwd: Path,
    scenario: Scenario,
    settings: dict,
    tools: tuple[str, ...],
    extra_args: tuple[str, ...] = (),
    include_hook_events: bool = False,
    enable_skills: bool = False,
    prompt: str | None = None,
) -> ClaudeRun:
    config_dir = scratch / f"config-{scenario.name}"
    config_dir.mkdir()
    with loopback_server(scenario) as loopback:
        command = [
            executable,
            "--setting-sources",
            "",
            "--settings",
            json.dumps(settings, separators=(",", ":")),
            "--no-session-persistence",
            "--tools",
            ",".join(tools),
        ]
        if tools:
            command.extend(["--allowedTools", ",".join(tools)])
        command.extend(
            [
                "--mcp-config",
                '{"mcpServers":{}}',
                "--strict-mcp-config",
                "--max-turns",
                "3",
                "--output-format",
                "stream-json",
                "--verbose",
            ]
        )
        if include_hook_events:
            command.append("--include-hook-events")
        if not enable_skills:
            command.append("--disable-slash-commands")
        command.extend(extra_args)
        command.extend(
            ["-p", prompt or f"deterministic runtime qualification: {scenario.name}"]
        )
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_probe_environment(config_dir, loopback.base_url),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    if result.returncode != 0:
        raise QualificationError(
            f"{scenario.name} exited {result.returncode}: {result.stderr.strip()}"
        )
    events = _parse_stream(result.stdout)
    require_success(events, expected_version)
    return ClaudeRun(events, result.stdout, result.stderr, list(loopback.requests))


def _hook_settings(if_condition: str, marker: str) -> dict:
    return {
        "permissions": {"allow": ["Bash"], "defaultMode": "default"},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/bin/sh",
                            "args": [
                                "-c",
                                f"printf {marker} >&2; exit 2",
                            ],
                            "if": if_condition,
                            "timeout": 30,
                        }
                    ],
                }
            ]
        },
    }


def _cross_session_settings() -> dict:
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    contract = {
        "crossSessionInbound": settings.get("crossSessionInbound"),
        "dialogExpiry": settings.get("dialogExpiry"),
        "isolatePeerMachines": settings.get("isolatePeerMachines"),
    }
    required = {
        "crossSessionInbound": "refuse",
        "dialogExpiry": "5m",
        "isolatePeerMachines": True,
    }
    if contract != required:
        raise QualificationError(
            f"repository cross-session contract differs from {required!r}"
        )
    return contract


def _worker_args(name: str) -> tuple[str, ...]:
    agents = {
        "worker-probe": {
            "description": "local worker exposure probe",
            "prompt": "run the requested read-only probe",
            "tools": ["Bash"],
            "disallowedTools": ["Agent"],
            "isolation": "worktree",
        }
    }
    return (
        "--agents",
        json.dumps(agents, separators=(",", ":")),
        "--agent",
        "worker-probe",
        "--worktree",
        name,
    )


def _init_git_fixture(path: Path) -> None:
    path.mkdir()
    commands = (
        ("git", "init", "-q", "-b", "main"),
        (
            "git",
            "-c",
            "user.name=Runtime Qualification",
            "-c",
            "user.email=runtime-qualification@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ),
    )
    for command in commands:
        result = subprocess.run(
            command,
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise QualificationError(
                f"temporary git fixture failed: {result.stderr.strip()}"
            )


def write_fork_argument_plugin(root: Path) -> Path:
    plugin = root / "fork-argument-plugin"
    metadata = plugin / ".claude-plugin"
    metadata.mkdir(parents=True)
    (metadata / "plugin.json").write_text(
        json.dumps(
            {
                "name": FORK_ARGUMENT_PLUGIN,
                "description": "temporary context-fork argument qualification",
                "version": "0.0.0",
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    explicit = plugin / "skills" / "explicit"
    explicit.mkdir(parents=True)
    (explicit / "SKILL.md").write_text(
        "---\n"
        "name: explicit\n"
        "description: Qualify explicit context-fork argument rendering.\n"
        'argument-hint: "<value>"\n'
        "context: fork\n"
        "---\n\n"
        f"{FORK_EXPLICIT_PREFIX}$ARGUMENTS{FORK_EXPLICIT_SUFFIX}\n",
        encoding="utf-8",
    )

    implicit = plugin / "skills" / "implicit"
    implicit.mkdir(parents=True)
    (implicit / "SKILL.md").write_text(
        "---\n"
        "name: implicit\n"
        "description: Qualify implicit context-fork argument appending.\n"
        'argument-hint: "<value>"\n'
        "context: fork\n"
        "---\n\n"
        f"{FORK_IMPLICIT_MARKER}\n",
        encoding="utf-8",
    )
    return plugin


def run_native_qualification(executable: str, expected_version: str) -> list[str]:
    passed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="claude-runtime-qualification-") as tmp:
        scratch = Path(tmp)
        git_fixture = scratch / "fixture"
        _init_git_fixture(git_fixture)

        schema = _run_scenario(
            executable,
            expected_version,
            scratch,
            git_fixture,
            Scenario("schema-settings"),
            _cross_session_settings(),
            (),
        )
        require_success(schema.events, expected_version)
        passed.append("schema-settings")

        fork_plugin = write_fork_argument_plugin(scratch)
        for name, skill, oracle in (
            (
                "fork-skill-rendered-arguments",
                "explicit",
                require_rendered_fork_arguments,
            ),
            (
                "fork-skill-appended-arguments",
                "implicit",
                require_appended_fork_arguments,
            ),
        ):
            forked = _run_scenario(
                executable,
                expected_version,
                scratch,
                git_fixture,
                Scenario(
                    name,
                    "Skill",
                    {
                        "skill": f"{FORK_ARGUMENT_PLUGIN}:{skill}",
                        "args": FORK_ARGUMENT_VALUE,
                    },
                ),
                {},
                ("default",),
                ("--plugin-dir", str(fork_plugin)),
                enable_skills=True,
                prompt="invoke the supplied deterministic skill",
            )
            oracle(forked.requests, FORK_ARGUMENT_VALUE)
            passed.append(name)

        nonmatch = _run_scenario(
            executable,
            expected_version,
            scratch,
            git_fixture,
            Scenario(
                "if-push-nonmatch",
                "Bash",
                {"command": "printf local-if-probe-executed"},
            ),
            _hook_settings("Bash(git push*)", "NONMATCH_HOOK_FIRED"),
            ("Bash",),
            include_hook_events=True,
        )
        require_unfiltered_bash(nonmatch.events, "local-if-probe-executed")
        passed.append("if-push-nonmatch")

        for name, condition, command, marker in (
            (
                "if-push-block",
                "Bash(git push*)",
                "git push --dry-run",
                "MATCHED_PUSH_BLOCKING_HOOK",
            ),
            (
                "if-commit-block",
                "Bash(git commit*)",
                "git commit --dry-run",
                "MATCHED_COMMIT_BLOCKING_HOOK",
            ),
        ):
            blocked = _run_scenario(
                executable,
                expected_version,
                scratch,
                git_fixture,
                Scenario(name, "Bash", {"command": command}),
                _hook_settings(condition, marker),
                ("Bash",),
                include_hook_events=True,
            )
            require_blocked_hook(blocked.events, marker)
            passed.append(name)

        worker_settings = {
            "permissions": {"allow": ["Bash"], "defaultMode": "default"}
        }
        local = _run_scenario(
            executable,
            expected_version,
            scratch,
            git_fixture,
            Scenario("worker-local-bash", "Bash", {"command": "pwd"}),
            worker_settings,
            ("Bash",),
            _worker_args("worker-local-runtime-qualification"),
        )
        require_worker_local(local.events)
        passed.append("worker-local-bash")

        fence = _run_scenario(
            executable,
            expected_version,
            scratch,
            git_fixture,
            Scenario(
                "worker-cross-checkout-fence",
                "Bash",
                {"command": f"git -C {git_fixture} status --short"},
            ),
            worker_settings,
            ("Bash",),
            _worker_args("worker-fence-runtime-qualification"),
        )
        require_worker_fence(fence.events)
        passed.append("worker-cross-checkout-fence")
    return passed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-native",
        action="store_true",
        help="explicitly run the local native binary against loopback-only fixtures",
    )
    parser.add_argument(
        "--claude",
        default=shutil.which("claude") or "claude",
        help="native Claude Code executable",
    )
    parser.add_argument(
        "--expected-version",
        default="2.1.226",
        help="exact Claude Code version required for the qualification",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.run_native:
        print("native qualification is opt-in; pass --run-native to execute it")
        return 0
    try:
        found = native_version(args.claude)
        if found != args.expected_version:
            raise QualificationError(
                f"expected {args.expected_version}, found {found}"
            )
        passed = run_native_qualification(args.claude, args.expected_version)
        for name in passed:
            print(f"PASS {name}")
        print(f"qualified Claude Code {found}: {len(passed)} deterministic probes")
        return 0
    except (OSError, subprocess.SubprocessError, QualificationError) as exc:
        print(f"native qualification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
