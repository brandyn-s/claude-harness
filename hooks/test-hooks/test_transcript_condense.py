#!/usr/bin/env python3
"""Tests for bin/transcript_condense.py — the compaction-recovery condense front-end for /distill.

The condense filter is the keeper of the 2026-06-21 reframe (red-team retired the per-chunk
findings census): KEEP the diagnostic signal (user/assistant text, tool calls, ERROR results,
compaction markers, chronological order); DROP the noise (thinking, images, success tool_result
bodies, file-history-snapshot, attachments, bookkeeping). Deterministic, no LLM."""
import importlib.util
import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_condense.py"))
spec = importlib.util.spec_from_file_location("transcript_condense", BIN)
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)


def _rec(obj):
    return json.dumps(obj)


def _write_transcript(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(_rec(r) + "\n" for r in records)


def test_condense_keeps_signal_drops_noise():
    """KEEP user/assistant text, tool_use, ERROR tool_result, compaction markers.
    DROP thinking, images, SUCCESS tool_result, file-history-snapshot, attachment, bookkeeping."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.jsonl")
        _write_transcript(src, [
            {"type": "user", "message": {"content": "fix the thing"}},
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "SECRET REASONING that must be dropped"},
                {"type": "text", "text": "I will fix it"},
                {"type": "tool_use", "name": "Bash", "input": {"command": "make build"}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "is_error": True, "content": "BUILD FAILED: missing dep"},
            ]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_result", "content": "SUCCESS noise that must be dropped"},
                {"type": "image", "source": {"data": "BASE64NOISE"}},
            ]}},
            {"type": "file-history-snapshot", "snapshot": {"big": "NOISE"}},
            {"type": "pr-link", "prNumber": 999},
            {"type": "system", "isCompactSummary": True, "i": 1},
            {"type": "user", "message": {"content": "after compaction"}},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(t for t, _ in lines)
        # signal kept
        assert "USER: fix the thing" in blob
        assert "ASST: I will fix it" in blob
        assert "TOOL Bash(command=make build)" in blob
        assert "ERROR: BUILD FAILED: missing dep" in blob
        assert "COMPACTION BOUNDARY" in blob
        assert "USER: after compaction" in blob
        # noise dropped
        assert "SECRET REASONING" not in blob, "thinking must be dropped"
        assert "SUCCESS noise" not in blob, "success tool_result body must be dropped"
        assert "BASE64NOISE" not in blob, "image must be dropped"
        assert "file-history" not in blob.lower() and "999" not in blob, "bookkeeping must be dropped"
        assert counts == {"user": 2, "asst": 1, "tool": 1, "error": 1, "compaction": 1, "malformed_lines": 0}, counts
        print("[condense] keeps signal (user/asst/tool/error/compaction), drops noise OK")


def test_condense_keeps_codex_rollout_signal():
    """Codex response_item records retain signal without successful tool-result noise."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "codex.jsonl")
        _write_transcript(src, [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "review the repo"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "I will inspect it"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "make test"}),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": (
                        "Chunk ID: failed\n"
                        "Process exited with code 1\n"
                        "Output:\n"
                        "FAILED: missing dependency"
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": (
                        "Chunk ID: successful\n"
                        "Process exited with code 0\n"
                        "Output:\n"
                        "SUCCESS body must be dropped"
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_search_call",
                    "arguments": {"query": "GitHub repository tools"},
                },
            },
            {"type": "compacted", "payload": {"message": "summary noise"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "private reasoning"}],
                },
            },
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(text for text, _ in lines)
        assert "USER: review the repo" in blob
        assert "ASST: I will inspect it" in blob
        assert "TOOL exec_command(cmd=make test)" in blob
        assert "ERROR:" in blob and "FAILED: missing dependency" in blob
        assert "TOOL tool_search(query=GitHub repository tools)" in blob
        assert "COMPACTION BOUNDARY" in blob
        assert "SUCCESS body must be dropped" not in blob
        assert "private reasoning" not in blob
        assert "summary noise" not in blob
        assert counts == {
            "user": 1,
            "asst": 1,
            "tool": 2,
            "error": 1,
            "compaction": 1,
            "malformed_lines": 0,
        }, counts


def test_condense_keeps_codex_auxiliary_diagnostics():
    """Clear subagent findings and explicit MCP failures survive without encrypted noise."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "codex-auxiliary.jsonl")
        _write_transcript(src, [
            {
                "type": "response_item",
                "payload": {
                    "type": "agent_message",
                    "content": [{"type": "input_text", "text": "subagent found a race"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "agent_message",
                    "content": [
                        {"type": "input_text", "text": "empty encrypted header"},
                        {"type": "encrypted_content", "encrypted_content": "ciphertext"},
                    ],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "invocation": {"server": "codex_apps", "tool": "github.fetch_commit"},
                    "result": {
                        "Ok": {
                            "content": [{"type": "text", "text": "GitHub API error 422"}],
                            "structuredContent": {"error": "GitHub API error 422"},
                            "isError": True,
                        },
                    },
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "invocation": {"server": "node_repl", "tool": "js_add_node_module_dir"},
                    "result": {
                        "Err": "tool call failed: path must name a node_modules directory",
                    },
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "invocation": {"server": "codex_apps", "tool": "github.search_branches"},
                    "result": {
                        "Ok": {
                            "content": [{"type": "text", "text": "SUCCESS MCP body must be dropped"}],
                            "isError": False,
                        },
                    },
                },
            },
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(text for text, _ in lines)
        assert "ASST: subagent found a race" in blob
        assert "ERROR: codex_apps.github.fetch_commit: GitHub API error 422" in blob
        assert (
            "ERROR: node_repl.js_add_node_module_dir: "
            "tool call failed: path must name a node_modules directory"
        ) in blob
        assert "ASST: empty encrypted header" in blob
        assert "ciphertext" not in blob
        assert "SUCCESS MCP body must be dropped" not in blob
        assert counts == {
            "user": 0,
            "asst": 2,
            "tool": 0,
            "error": 2,
            "compaction": 0,
            "malformed_lines": 0,
        }, counts


def test_condense_classifies_codex_status_variants():
    """Nonzero direct status and validation failures survive; code zero remains noise."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "codex-status.jsonl")
        _write_transcript(src, [
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": "Exit code: 1\nOutput:\npatch rejected",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": "Exit code: 0\nOutput:\nSUCCESS patch body must be dropped",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "timeout_ms must be at least 10000",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": (
                        "Process exited with code 0\n"
                        "Output:\n"
                        "quoted example: Process exited with code 1\n"
                        "collab tool failed: quoted analytical evidence"
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": "### lint\nexit=1\nEXE001 script is not executable",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "apply_patch verification failed: context drift",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": {"success": False, "error": "transport unavailable"},
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": json.dumps({"is_error": True, "error": "MCP refused request"}),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": {
                        "exit_code": 0,
                        "success": False,
                        "error": "quoted failure under successful outer status",
                    },
                },
            },
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(text for text, _ in lines)
        assert "ERROR: Exit code: 1" in blob
        assert "ERROR: timeout_ms must be at least 10000" in blob
        assert "ERROR: ### lint" in blob and "exit=1" in blob
        assert "ERROR: apply_patch verification failed: context drift" in blob
        assert "ERROR: transport unavailable" in blob
        assert "ERROR: MCP refused request" in blob
        assert "SUCCESS patch body must be dropped" not in blob
        assert "quoted analytical evidence" not in blob
        assert "quoted failure under successful outer status" not in blob
        assert counts["error"] == 6, counts


def test_condense_keeps_functions_exec_nested_exit_code_failures():
    """functions.exec text envelopes retain failed nested command output."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "codex-functions-exec.jsonl")
        _write_transcript(src, [
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": [
                        {"type": "input_text", "text": "Script completed\nOutput:\n"},
                        {
                            "type": "input_text",
                            "text": "fatal: unable to create shared worktree index.lock",
                        },
                        {"type": "input_text", "text": "exit_code=128"},
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": [
                        {"type": "input_text", "text": "Script completed\nOutput:\n"},
                        {"type": "input_text", "text": "SUCCESS body must be dropped"},
                        {"type": "input_text", "text": "exit_code=0"},
                    ],
                },
            },
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(text for text, _ in lines)
        assert "ERROR:" in blob
        assert "fatal: unable to create shared worktree index.lock" in blob
        assert "exit_code=128" in blob
        assert "SUCCESS body must be dropped" not in blob
        assert counts["error"] == 1, counts


def test_condense_prefers_legacy_search_pattern_over_scope_path():
    """Adding Codex path inputs must not replace Claude Grep's diagnostic pattern."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "legacy-grep.jsonl")
        _write_transcript(src, [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Grep",
                            "input": {"pattern": "needle", "path": "src"},
                        },
                    ],
                },
            },
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(text for text, _ in lines)
        assert "TOOL Grep(pattern=needle)" in blob
        assert "TOOL Grep(path=src)" not in blob
        assert counts["tool"] == 1
def test_condense_keeps_codex_rollout_signal_drops_noise():
    """Codex Desktop rollout JSONL preserves the same signal contract as Claude JSONL."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "codex-rollout.jsonl")
        _write_transcript(src, [
            {"type": "session_meta", "payload": {"id": "session-noise"}},
            {"type": "response_item", "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "<environment_context>INJECTED</environment_context>"}],
            }},
            {"type": "response_item", "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "DUPLICATE ASSISTANT TEXT"}],
            }},
            {"type": "event_msg", "payload": {
                "type": "user_message",
                "message": "review the repository",
            }},
            {"type": "event_msg", "payload": {
                "type": "agent_message",
                "message": "I will inspect it",
            }},
            {"type": "response_item", "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "pytest -q"}),
            }},
            {"type": "response_item", "payload": {
                "type": "function_call_output",
                "output": (
                    "Chunk ID: abc123\n"
                    "Wall time: 0.1 seconds\n"
                    "Process exited with code 2\n"
                    "Output:\nFAILED: regression"
                ),
            }},
            {"type": "response_item", "payload": {
                "type": "function_call_output",
                "output": (
                    "Chunk ID: success\n"
                    "Wall time: 0.1 seconds\n"
                    "Process exited with code 0\n"
                    "Output:\n"
                    "Example only: Process exited with code 2"
                ),
            }},
            {"type": "event_msg", "payload": {
                "type": "token_count",
                "info": {"total_tokens": 999999},
            }},
            {"type": "compacted", "payload": {
                "replacement_history": [{"type": "reasoning", "encrypted_content": "HUGE NOISE"}],
            }},
            {"type": "event_msg", "payload": {
                "type": "context_compacted",
            }},
            {"type": "event_msg", "payload": {
                "type": "agent_message",
                "message": "after compaction",
            }},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(t for t, _ in lines)

        assert "USER: review the repository" in blob
        assert "ASST: I will inspect it" in blob
        assert "TOOL exec_command(cmd=pytest -q)" in blob
        assert "ERROR:" in blob and "Process exited with code 2" in blob
        assert "COMPACTION BOUNDARY" in blob
        assert "ASST: after compaction" in blob

        assert "SECRET REASONING" not in blob
        assert "HUGE NOISE" not in blob
        assert "999999" not in blob
        assert "INJECTED" not in blob
        assert "DUPLICATE ASSISTANT TEXT" not in blob
        assert "Example only" not in blob
        assert counts == {"user": 1, "asst": 2, "tool": 1, "error": 1, "compaction": 1, "malformed_lines": 0}
        print("[condense] Codex rollout signal kept and noise dropped OK")


def test_condense_keeps_response_item_dialogue_when_events_are_absent():
    """Older response-item-only Codex rollouts retain visible dialogue as a fallback."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "response-only-codex-rollout.jsonl")
        _write_transcript(src, [
            {"type": "response_item", "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "inspect this repository"}],
            }},
            {"type": "response_item", "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I found the issue"}],
            }},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(t for t, _ in lines)

        assert "USER: inspect this repository" in blob
        assert "ASST: I found the issue" in blob
        assert counts == {"user": 1, "asst": 1, "tool": 0, "error": 0, "compaction": 0, "malformed_lines": 0}
        print("[condense] response-item-only Codex dialogue fallback kept OK")


def test_condense_uses_response_fallback_per_missing_dialogue_role():
    """A mirrored user event must not erase a response-only assistant message."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "mixed-codex-rollout.jsonl")
        _write_transcript(src, [
            {"type": "response_item", "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "inspect this repository"}],
            }},
            {"type": "event_msg", "payload": {
                "type": "user_message",
                "message": "inspect this repository",
            }},
            {"type": "response_item", "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I found the issue"}],
            }},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(t for t, _ in lines)

        assert blob.count("USER: inspect this repository") == 1
        assert "ASST: I found the issue" in blob
        assert counts == {"user": 1, "asst": 1, "tool": 0, "error": 0, "compaction": 0, "malformed_lines": 0}


def test_condense_keeps_legacy_codex_compaction_event():
    """Older event-only Codex compaction envelopes still produce one boundary."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "legacy-codex-rollout.jsonl")
        _write_transcript(src, [
            {"type": "event_msg", "payload": {"type": "context_compacted"}},
            {"type": "event_msg", "payload": {
                "type": "agent_message",
                "message": "after legacy compaction",
            }},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(t for t, _ in lines)

        assert blob.count("COMPACTION BOUNDARY") == 1
        assert "ASST: after legacy compaction" in blob
        assert counts == {"user": 0, "asst": 1, "tool": 0, "error": 0, "compaction": 1, "malformed_lines": 0}
        print("[condense] legacy Codex context_compacted envelope kept once OK")


def test_condense_keeps_codex_agent_and_custom_tool_signal():
    """Codex subagent reports, searched tools, and custom-tool failures stay visible."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "codex-custom.jsonl")
        _write_transcript(src, [
            {"type": "response_item", "payload": {
                "type": "agent_message",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Message Type: FINAL_ANSWER\nPayload:\nFound the root cause.",
                    },
                    {"type": "encrypted_content", "encrypted_content": "SECRET AGENT REASONING"},
                ],
            }},
            {"type": "response_item", "payload": {
                "type": "tool_search_call",
                "arguments": json.dumps({"query": "GitHub repository tools"}),
            }},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "input": "*** Begin Patch\n*** Update File: example.py",
            }},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call_output",
                "output": "apply_patch verification failed: expected context was not found",
            }},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call_output",
                "output": [{"type": "input_text", "text": "Script completed\nSUCCESS BODY NOISE"}],
            }},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(t for t, _ in lines)

        assert "ASST: Message Type: FINAL_ANSWER" in blob
        assert "TOOL tool_search(query=GitHub repository tools)" in blob
        assert "TOOL apply_patch(input=*** Begin Patch" in blob
        assert "ERROR: apply_patch verification failed" in blob

        assert "SECRET AGENT REASONING" not in blob
        assert "SUCCESS BODY NOISE" not in blob
        assert counts == {"user": 0, "asst": 1, "tool": 2, "error": 1, "compaction": 0, "malformed_lines": 0}
        print("[condense] Codex agent/custom-tool signal kept and success noise dropped OK")


def test_condense_prefers_search_pattern_over_scope_path():
    """A search tool summary keeps the query predicate instead of only its scope."""
    summary = tc._summarize_tool_input(
        {"pattern": "needle", "path": "src"},
        tool_input_cap=160,
    )
    assert summary == "pattern=needle"


def test_condense_keeps_structured_codex_and_mcp_failures():
    """Explicit structured and MCP failures survive without retaining successful output."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "codex-errors.jsonl")
        _write_transcript(src, [
            {"type": "response_item", "payload": {
                "type": "function_call_output",
                "output": {"success": False, "error": "transport unavailable"},
            }},
            {"type": "response_item", "payload": {
                "type": "function_call_output",
                "output": json.dumps({"is_error": True, "error": "MCP refused request"}),
            }},
            {"type": "response_item", "payload": {
                "type": "function_call_output",
                "output": {
                    "exit_code": 0,
                    "success": False,
                    "error": "quoted failure under successful outer status",
                },
            }},
            {"type": "event_msg", "payload": {
                "type": "mcp_tool_call_end",
                "invocation": {"server": "node_repl", "tool": "js_add_node_module_dir"},
                "result": {"Err": "path must name a node_modules directory"},
            }},
            {"type": "event_msg", "payload": {
                "type": "mcp_tool_call_end",
                "invocation": {"server": "github", "tool": "fetch_commit"},
                "result": {"Ok": {
                    "isError": True,
                    "structuredContent": {"error": "GitHub API error 422"},
                }},
            }},
            {"type": "event_msg", "payload": {
                "type": "mcp_tool_call_end",
                "invocation": {"server": "github", "tool": "search_branches"},
                "result": {"Ok": {
                    "isError": False,
                    "content": [{"type": "text", "text": "SUCCESS MCP BODY NOISE"}],
                }},
            }},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(t for t, _ in lines)

        assert "ERROR: transport unavailable" in blob
        assert "ERROR: MCP refused request" in blob
        assert "ERROR: node_repl.js_add_node_module_dir: path must name" in blob
        assert "ERROR: github.fetch_commit: GitHub API error 422" in blob
        assert "quoted failure under successful outer status" not in blob
        assert "SUCCESS MCP BODY NOISE" not in blob
        assert counts == {"user": 0, "asst": 0, "tool": 0, "error": 4, "compaction": 0, "malformed_lines": 0}
        print("[condense] structured Codex and MCP failures kept; successes dropped OK")


def test_condense_error_cap():
    """ERROR bodies are capped so one giant error dump can't bloat the slice."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.jsonl")
        _write_transcript(src, [
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "is_error": True, "content": "X" * 5000},
            ]}},
        ])
        lines, _ = tc.condense(src, err_cap=1500, tool_input_cap=160)
        err_line = [t for t, _ in lines if t.startswith("  ERROR:")][0]
        assert len(err_line) < 1600, "error body must be capped near err_cap"
        print("[condense] error body capped OK")


def test_condense_splits_only_at_boundaries():
    """When each segment fits, compaction boundaries remain the preferred split."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.jsonl")
        recs = []
        # 3 segments of big user text separated by 2 compaction boundaries
        for seg in range(3):
            if seg > 0:
                recs.append({"type": "system", "isCompactSummary": True, "i": seg})
            for _ in range(5):
                recs.append({"type": "user", "message": {"content": "Z" * 2000}})
        _write_transcript(src, recs)
        lines, _ = tc.condense(src, 1500, 160)
        # Each ~10K-char segment fits, but adjacent segments do not.
        parts = tc.split_to_parts(lines, max_tokens=int(12000 / tc.BYTES_PER_TOKEN))
        assert len(parts) >= 2, "over-budget multi-boundary slice must split"
        # every part after the first must begin at a compaction boundary marker
        for p in parts[1:]:
            assert p[0].startswith("\n====="), f"part must start at a boundary, got {p[0][:40]!r}"
        # nothing lost: concatenated parts == all lines in order
        flat = [t for part in parts for t in part]
        assert flat == [t for t, _ in lines], "split must preserve all lines in order"
        print(f"[condense] over-budget split at boundaries only, {len(parts)} parts, order preserved OK")


def test_condense_splits_oversized_boundary_free_segment_by_record():
    """The default is a real ceiling even when a transcript has no compaction boundary."""
    lines = [
        ("USER: " + ("A" * 100_000), False),
        ("ASST: " + ("B" * 100_000), False),
        ("USER: " + ("C" * 100_000), False),
        ("ASST: " + ("D" * 100_000), False),
        ("USER: " + ("E" * 100_000), False),
    ]

    parts = tc.split_to_parts(lines, max_tokens=tc.DEFAULT_MAX_TOKENS)

    assert len(parts) == 2
    assert [text for part in parts for text in part] == [text for text, _ in lines]
    assert all(
        sum(len(text.encode("utf-8")) + 1 for text in part)
        <= tc.DEFAULT_MAX_TOKENS * tc.BYTES_PER_TOKEN
        for part in parts
    )


def test_condense_budget_counts_utf8_bytes():
    """Multibyte records cannot pass a byte-based estimate that the manifest then exceeds."""
    try:
        tc.split_to_parts([("USER: " + ("🚢" * 100), False)], max_tokens=100)
    except ValueError as error:
        assert "single diagnostic record" in str(error)
    else:
        raise AssertionError("multibyte record over the estimated token budget must fail")


def test_condense_rejects_one_record_larger_than_budget():
    """An indivisible record cannot silently create an unreadable part."""
    try:
        tc.split_to_parts([("USER: " + ("X" * 300), False)], max_tokens=100)
    except ValueError as error:
        assert "single diagnostic record" in str(error)
    else:
        raise AssertionError("oversized single record must fail explicitly")


def test_condense_cli_emits_slices_and_manifest():
    """End-to-end CLI: writes slice_NNN.txt + condense-manifest.json with honest counts."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.jsonl")
        _write_transcript(src, [
            {"type": "user", "message": {"content": "hello"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi there friend"}]}},
        ])
        out = os.path.join(d, "slices")
        r = subprocess.run(["python3", BIN, src, "--out-dir", out, "--max-tokens", "600000"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        man = json.load(open(os.path.join(out, "condense-manifest.json"), encoding="utf-8"))
        assert man["n_parts"] == 1
        assert man["signal_counts"]["user"] == 1 and man["signal_counts"]["asst"] == 1
        assert os.path.exists(os.path.join(out, "slice_000.txt"))
        print("[condense] CLI emits slices + manifest OK")


def test_condense_codex_rollout_schema():
    """Codex rollouts keep real turns/tools/errors/boundaries while dropping injected context."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "rollout.jsonl")
        _write_transcript(src, [
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "<environment_context>noise</environment_context>"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "review production"}]}},
            {"type": "event_msg", "payload": {"type": "user_message",
                "message": "review production"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "Starting review"}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                "arguments": json.dumps({"cmd": "make test"})}},
            {"type": "response_item", "payload": {"type": "function_call_output",
                "output": json.dumps({"exit_code": 2, "output": "tests failed"})}},
            {"type": "response_item", "payload": {"type": "function_call_output",
                "output": json.dumps({"exit_code": 0, "output": "success noise"})}},
            {"type": "compacted", "payload": {"message": "summary noise"}},
            {"type": "event_msg", "payload": {"type": "context_compacted"}},
        ])
        lines, counts = tc.condense(src, err_cap=1500, tool_input_cap=160)
        blob = "\n".join(text for text, _ in lines)
        assert blob.count("USER: review production") == 1, "UI event duplicate must be dropped"
        assert "environment_context" not in blob
        assert "ASST: Starting review" in blob
        assert "TOOL exec_command(cmd=make test)" in blob
        assert "ERROR:" in blob and "tests failed" in blob
        assert "success noise" not in blob
        assert blob.count("COMPACTION BOUNDARY") == 1, "event mirror must not double-count"
        assert counts == {"user": 1, "asst": 1, "tool": 1, "error": 1, "compaction": 1, "malformed_lines": 0}, counts
        print("[condense] Codex rollout schema keeps signal and drops duplicated/injected noise OK")


def test_condense_cli_fails_closed_on_supported_but_empty_transcript():
    """A recognized transcript must not silently emit a zero-part success."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "empty-signal.jsonl")
        _write_transcript(src, [
            {"type": "response_item", "payload": {"type": "reasoning", "summary": []}},
        ])
        out = os.path.join(d, "slices")
        r = subprocess.run(["python3", BIN, src, "--out-dir", out],
                           capture_output=True, text=True)
        assert r.returncode != 0
        assert "no diagnostic signal" in (r.stdout + r.stderr)
        print("[condense] CLI fails closed on supported schema with zero extracted signal OK")
def test_condense_cli_removes_stale_tail_slices_on_rerun():
    """Reusing the documented session output directory cannot expose old tail parts."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.jsonl")
        out = os.path.join(d, "slices")
        _write_transcript(src, [
            {"type": "user", "message": {"content": str(i) + ("X" * 180)}}
            for i in range(5)
        ])
        first = subprocess.run(
            ["python3", BIN, src, "--out-dir", out, "--max-tokens", "100"],
            capture_output=True,
            text=True,
        )
        assert first.returncode == 0, first.stderr
        assert len([name for name in os.listdir(out) if name.startswith("slice_")]) > 1

        _write_transcript(src, [
            {"type": "user", "message": {"content": "small rerun"}},
        ])
        second = subprocess.run(
            ["python3", BIN, src, "--out-dir", out, "--max-tokens", "100"],
            capture_output=True,
            text=True,
        )
        assert second.returncode == 0, second.stderr
        assert sorted(name for name in os.listdir(out) if name.startswith("slice_")) == [
            "slice_000.txt"
        ]
        manifest = json.load(
            open(os.path.join(out, "condense-manifest.json"), encoding="utf-8")
        )
        assert manifest["n_parts"] == 1


def test_condense_cli_rejects_nonempty_zero_signal_transcript():
    """An unknown nonempty envelope must not silently produce a zero-part success."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "unknown.jsonl")
        _write_transcript(src, [
            {"type": "future_rollout_envelope", "payload": {"opaque": True}},
        ])
        out = os.path.join(d, "slices")
        r = subprocess.run(
            ["python3", BIN, src, "--out-dir", out],
            capture_output=True,
            text=True,
        )
        assert r.returncode != 0
        assert "no diagnostic signal" in r.stderr.lower()
        assert not os.path.exists(os.path.join(out, "condense-manifest.json"))
        print("[condense] unknown nonempty envelope fails closed OK")


def test_condense_counts_malformed_lines_upstream_81843():
    """A spliced JSONL record must be COUNTED, not silently skipped.

    Upstream #81843: four writer domains append to one session .jsonl with no
    shared lock, so records get spliced mid-write (still present on 2.1.220).
    Skipping such a line is correct; skipping it SILENTLY is not, because a
    partial mine then looks identical to a complete one — the exact
    completeness claim rules/transcript-over-summary.md rests on.

    Known-negative (clean) and known-positive (both #81843 signatures).
    """
    with tempfile.TemporaryDirectory() as d:
        good = [
            {"type": "user", "message": {"content": "first question"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "first answer"}]}},
            {"type": "user", "message": {"content": "second question"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "second answer"}]}},
        ]

        # known-negative: every line valid -> 0 malformed, all signal present
        clean = os.path.join(d, "clean.jsonl")
        _write_transcript(clean, good)
        _, counts = tc.condense(clean, err_cap=1500, tool_input_cap=160)
        assert counts["malformed_lines"] == 0, counts
        assert counts["user"] == 2 and counts["asst"] == 2, counts

        # known-positive: reproduce both signatures from the upstream report
        a, b = _rec(good[1]), _rec(good[2])
        corrupt = os.path.join(d, "corrupt.jsonl")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write(_rec(good[0]) + "\n")
            fh.write(a[:len(a) // 2] + b + "\n")   # truncated splice (21x upstream)
            fh.write(a + b + "\n")                 # missing newline, "}{" junction (3x upstream)
            fh.write(_rec(good[3]) + "\n")
        _, counts = tc.condense(corrupt, err_cap=1500, tool_input_cap=160)
        assert counts["malformed_lines"] == 2, counts
        # surviving signal is genuinely reduced — this is precisely what a silent
        # skip would have reported with no indication anything was lost
        assert counts["user"] == 1 and counts["asst"] == 1, counts
        print("[condense] counts malformed JSONL lines instead of silently skipping (#81843) OK")


def test_condense_default_budget_fits_codex_context():
    """The default must leave prompt/rules headroom under the active Codex window."""
    assert tc.DEFAULT_MAX_TOKENS == 180_000


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
