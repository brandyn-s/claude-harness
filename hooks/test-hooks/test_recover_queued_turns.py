"""Behavior tests for mega-distill's queued-turn recovery helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = (
    REPO_ROOT
    / "skills"
    / "mega-distill"
    / "scripts"
    / "recover_queued_turns.py"
)
UNVERIFIED_MESSAGE = "UNVERIFIED: queued-turn evidence could not be verified\n"


def _run_helper_text(
    tmp_path: Path,
    transcript_text: str,
    *,
    slice_text: str = "USER: already preserved pivot\n",
    manifest_mutator: Callable[[dict[str, object]], None] | None = None,
    fixture_mutator: Callable[[dict[str, Path]], None] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    transcript = tmp_path / "session.jsonl"
    slice_path = tmp_path / "slice_000.txt"
    manifest = tmp_path / "condense-manifest.json"
    output = tmp_path / "recovered_user_turns.txt"
    transcript.write_text(transcript_text, encoding="utf-8")
    slice_path.write_text(slice_text, encoding="utf-8")
    slice_bytes = len(slice_text.encode("utf-8"))
    manifest_document: dict[str, object] = {
        "transcript": str(transcript),
        "signal_counts": {
            "user": 1,
            "asst": 0,
            "tool": 0,
            "error": 0,
            "compaction": 1,
            "malformed_lines": 0,
        },
        "n_parts": 1,
        "total_slice_bytes": slice_bytes,
        "total_est_tokens": int(slice_bytes / 2.5),
        "parts": [
            {
                "part": 0,
                "bytes": slice_bytes,
                "est_tokens": int(slice_bytes / 2.5),
                "path": str(slice_path),
            }
        ],
    }
    if manifest_mutator is not None:
        manifest_mutator(manifest_document)
    manifest.write_text(json.dumps(manifest_document), encoding="utf-8")
    if fixture_mutator is not None:
        fixture_mutator(
            {
                "transcript": transcript,
                "manifest": manifest,
                "slice": slice_path,
                "output": output,
            }
        )

    completed = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            str(transcript),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return completed, output


def _run_helper(
    tmp_path: Path, transcript_records: list[object]
) -> tuple[subprocess.CompletedProcess[str], Path]:
    transcript_text = "".join(
        json.dumps(record) + "\n" for record in transcript_records
    )
    return _run_helper_text(tmp_path, transcript_text)


def test_cli_recovers_distinct_dropped_delivery_records_deterministically(tmp_path: Path) -> None:
    records = [
        {
            "type": "queue-operation",
            "operation": "enqueue",
            "content": "  already   preserved pivot  ",
        },
        {
            "type": "attachment",
            "attachment": {
                "type": "queued_command",
                "prompt": [{"type": "text", "text": "already preserved pivot"}],
            },
        },
        {
            "type": "attachment",
            "attachment": {
                "type": "queued_command",
                "prompt": ["list", {"type": "text", "text": "payload"}],
            },
        },
        {
            "type": "queue-operation",
            "operation": "remove",
            "content": {"type": "text", "text": "queue only"},
        },
        {
            "type": "queue-operation",
            "operation": "popAll",
            "content": ["list", {"text": "payload"}],
        },
        {"type": "queue-operation", "operation": "dequeue"},
        {
            "type": "attachment",
            "attachment": {
                "type": "queued_command",
                "prompt": "<task-notification>machine noise</task-notification>",
            },
        },
    ]

    completed, output = _run_helper(tmp_path, records)

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == (
        "[raw line 3] list payload\n\n[raw line 4] queue only\n"
    )
    assert json.loads(completed.stdout) == {
        "delivery_records": 6,
        "dropped_prompts": 2,
        "probe_state": "verified",
        "unique_prompts": 3,
    }


def test_cli_recovers_text_from_real_mixed_text_and_image_prompt(
    tmp_path: Path,
) -> None:
    completed, output = _run_helper(
        tmp_path,
        [
            {
                "type": "attachment",
                "attachment": {
                    "type": "queued_command",
                    "prompt": [
                        {"type": "text", "text": "inspect this image"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "not-user-text",
                            },
                        },
                    ],
                },
            }
        ],
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == (
        "[raw line 1] inspect this image\n"
    )


def test_cli_marks_malformed_transcript_unverified_and_removes_stale_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "recovered_user_turns.txt"
    output.write_text("stale evidence\n", encoding="utf-8")

    completed, output = _run_helper_text(
        tmp_path,
        '{"type":"queue-operation","operation":"enqueue","content":"pivot"\n',
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_marks_unknown_delivery_shape_unverified(tmp_path: Path) -> None:
    completed, output = _run_helper(
        tmp_path,
        [
            {
                "type": "queue-operation",
                "operation": "futureDeliveryOperation",
                "content": "pivot",
            }
        ],
    )

    assert completed.returncode == 2
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_does_not_suppress_prompt_that_is_only_a_slice_substring(
    tmp_path: Path,
) -> None:
    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        slice_text="USER: prefix materials\n",
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == "[raw line 1] fix\n"
    assert json.loads(completed.stdout)["dropped_prompts"] == 1


def test_cli_matches_queued_prompt_to_exact_native_command_envelope(
    tmp_path: Path,
) -> None:
    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "/software-security-review all",
            }
        )
        + "\n",
        slice_text=(
            "USER: <command-message>software-security-review</command-message>\n"
            "<command-name>/software-security-review</command-name>\n"
            "<command-args>all</command-args>\n"
        ),
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == ""
    assert json.loads(completed.stdout)["dropped_prompts"] == 0


def test_cli_marks_inconsistent_native_command_envelope_unverified(
    tmp_path: Path,
) -> None:
    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "/software-security-review all",
            }
        )
        + "\n",
        slice_text=(
            "USER: <command-message>different-command</command-message>\n"
            "<command-name>/software-security-review</command-name>\n"
            "<command-args>all</command-args>\n"
        ),
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_marks_unbounded_slice_text_unverified(tmp_path: Path) -> None:
    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        slice_text="prefix materials\n",
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_manifest_bound_to_a_different_transcript(
    tmp_path: Path,
) -> None:
    other_transcript = tmp_path / "other-session.jsonl"
    other_transcript.write_text("{}\n", encoding="utf-8")

    def bind_wrong_transcript(manifest: dict[str, object]) -> None:
        manifest["transcript"] = str(other_transcript)

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=bind_wrong_transcript,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_incomplete_manifest_part_set(tmp_path: Path) -> None:
    def claim_missing_part(manifest: dict[str, object]) -> None:
        manifest["n_parts"] = 2

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=claim_missing_part,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_duplicate_manifest_part(tmp_path: Path) -> None:
    def duplicate_part(manifest: dict[str, object]) -> None:
        parts = manifest["parts"]
        assert isinstance(parts, list)
        assert isinstance(parts[0], dict)
        parts.append(dict(parts[0]))
        manifest["n_parts"] = 2

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=duplicate_part,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_part_path_outside_manifest_directory(tmp_path: Path) -> None:
    nested = tmp_path / "outside"
    nested.mkdir()
    outside_part = nested / "slice_000.txt"
    outside_part.write_text("USER: already preserved pivot\n", encoding="utf-8")

    def point_outside(manifest: dict[str, object]) -> None:
        parts = manifest["parts"]
        assert isinstance(parts, list)
        assert isinstance(parts[0], dict)
        parts[0]["path"] = str(outside_part)

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=point_outside,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_unlisted_slice_file(tmp_path: Path) -> None:
    def create_unlisted_part(_manifest: dict[str, object]) -> None:
        (tmp_path / "slice_001.txt").write_text(
            "USER: unlisted evidence\n",
            encoding="utf-8",
        )

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=create_unlisted_part,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_manifest_part_byte_count_mismatch(tmp_path: Path) -> None:
    def corrupt_byte_count(manifest: dict[str, object]) -> None:
        parts = manifest["parts"]
        assert isinstance(parts, list)
        assert isinstance(parts[0], dict)
        part_bytes = parts[0]["bytes"]
        assert isinstance(part_bytes, int)
        parts[0]["bytes"] = part_bytes + 1

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=corrupt_byte_count,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_inconsistent_manifest_aggregate_counts(tmp_path: Path) -> None:
    def corrupt_aggregates(manifest: dict[str, object]) -> None:
        manifest["total_slice_bytes"] = -1
        manifest["total_est_tokens"] = -1

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=corrupt_aggregates,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


def test_cli_rejects_inconsistent_manifest_part_token_estimate(
    tmp_path: Path,
) -> None:
    def corrupt_estimate(manifest: dict[str, object]) -> None:
        parts = manifest["parts"]
        assert isinstance(parts, list)
        assert isinstance(parts[0], dict)
        parts[0]["est_tokens"] = -1

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        manifest_mutator=corrupt_estimate,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()


@pytest.mark.parametrize("target", ["transcript", "manifest", "slice"])
def test_cli_rejects_non_utf8_evidence_with_constant_output(
    tmp_path: Path,
    target: str,
) -> None:
    def corrupt_fixture(paths: dict[str, Path]) -> None:
        path = paths[target]
        raw = bytearray(path.read_bytes())
        needles = {
            "transcript": b"fix",
            "manifest": b"signal_counts",
            "slice": b"already",
        }
        offset = raw.index(needles[target]) + 1
        raw[offset] = 0xFF
        path.write_bytes(raw)
        paths["output"].write_text("stale evidence\n", encoding="utf-8")

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        fixture_mutator=corrupt_fixture,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert "Traceback" not in completed.stderr
    assert not output.exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO fixture unavailable")
def test_cli_rejects_non_regular_manifest_part_without_opening_it(
    tmp_path: Path,
) -> None:
    def replace_slice_with_fifo(paths: dict[str, Path]) -> None:
        paths["slice"].unlink()
        os.mkfifo(paths["slice"])

    completed, output = _run_helper_text(
        tmp_path,
        json.dumps(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "content": "fix",
            }
        )
        + "\n",
        fixture_mutator=replace_slice_with_fifo,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == UNVERIFIED_MESSAGE
    assert not output.exists()
