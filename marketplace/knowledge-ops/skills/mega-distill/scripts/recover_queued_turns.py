#!/usr/bin/env python3
"""Recover user prompts carried outside supported transcript dialogue records."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

_DELIVERY_OPERATIONS = {"enqueue", "popAll", "remove"}
_CONTROL_OPERATIONS = {"dequeue"}
_TEXT_KEYS = ("text", "content", "message", "prompt")
_SLICE_NAME_RE = re.compile(r"slice_[0-9]{3,}\.txt\Z")
_COMMAND_TAG_RE = re.compile(
    r"<(?P<tag>command-name|command-message|command-args)>"
    r"(?P<value>.*?)</(?P=tag)>",
    re.DOTALL,
)
_COMMAND_TAG_TOKEN_RE = re.compile(r"</?command-(?:name|message|args)(?:>|\s)")
_BYTES_PER_TOKEN = 2.5
UNVERIFIED_MESSAGE = "UNVERIFIED: queued-turn evidence could not be verified"


class RecoveryError(ValueError):
    """The queued-delivery evidence could not be verified."""


def _fail(message: str) -> NoReturn:
    raise RecoveryError(message)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _user_record_prompts(text: str) -> set[str]:
    """Return exact prompt identities carried by one complete USER record."""
    normalized = _normalize(text)
    prompts = {normalized} if normalized else set()
    matches = list(_COMMAND_TAG_RE.finditer(text))
    if not matches:
        if _COMMAND_TAG_TOKEN_RE.search(text):
            _fail("slice contains an incomplete native command envelope")
        return prompts

    residue = _COMMAND_TAG_RE.sub("", text)
    if residue.strip():
        _fail("slice mixes a native command envelope with ambiguous text")
    fields: dict[str, str] = {}
    for match in matches:
        tag = match.group("tag")
        if tag in fields:
            _fail("slice contains duplicate native command envelope fields")
        fields[tag] = _normalize(match.group("value"))
    command_name = fields.get("command-name", "")
    if (
        not command_name.startswith("/")
        or any(character.isspace() for character in command_name)
    ):
        _fail("slice native command envelope has an invalid command name")
    command_message = fields.get("command-message")
    if command_message is not None and command_message != command_name[1:]:
        _fail("slice native command envelope fields disagree")
    command_args = fields.get("command-args", "")
    prompts.add(_normalize(f"{command_name} {command_args}"))
    return prompts


def flatten_payload(value: object, *, location: str) -> str:
    """Flatten supported text payload shapes or fail on an unknown shape."""
    if isinstance(value, str):
        return _normalize(value)
    if isinstance(value, list):
        flattened = [
            flatten_payload(item, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
        return _normalize(" ".join(part for part in flattened if part))
    if isinstance(value, dict):
        present = [key for key in _TEXT_KEYS if key in value]
        if not present:
            if value.get("type") == "image" and "source" in value:
                return ""
            _fail(f"{location}: unsupported object keys")
        flattened = [
            flatten_payload(value[key], location=f"{location}.{key}")
            for key in present
        ]
        return _normalize(" ".join(part for part in flattened if part))
    _fail(f"{location}: unsupported payload type {type(value).__name__}")


def _delivery_payload(record: dict[str, object], line_number: int) -> object | None:
    record_type = record.get("type")
    if record_type == "attachment":
        attachment = record.get("attachment")
        if not isinstance(attachment, dict):
            _fail(f"line {line_number}: attachment envelope is not an object")
        if attachment.get("type") != "queued_command":
            return None
        if "prompt" not in attachment:
            _fail(f"line {line_number}: queued_command has no prompt")
        return attachment["prompt"]

    if record_type != "queue-operation":
        return None

    operation = record.get("operation")
    if not isinstance(operation, str):
        _fail(f"line {line_number}: queue-operation has no string operation")
    if operation in _CONTROL_OPERATIONS:
        if record.get("content") is not None:
            _fail(f"line {line_number}: {operation} unexpectedly carries content")
        return None
    if operation not in _DELIVERY_OPERATIONS:
        _fail(f"line {line_number}: unsupported queue operation {operation!r}")
    if "content" not in record or record.get("content") is None:
        _fail(f"line {line_number}: {operation} has no content")
    return record["content"]


def _slice_user_prompts(text: str) -> set[str]:
    """Return exact normalized USER records from one condenser slice."""
    prompts: set[str] = set()
    current_user: list[str] | None = None
    current_record: str | None = None
    saw_record = False

    def finish_user() -> None:
        nonlocal current_user
        if current_user is not None:
            prompts.update(_user_record_prompts("\n".join(current_user)))
        current_user = None

    for line in text.splitlines():
        if line.startswith("USER: "):
            finish_user()
            current_user = [line.removeprefix("USER: ")]
            current_record = "user"
            saw_record = True
        elif line.startswith(("ASST: ", "  TOOL ", "  ERROR:")) or line.strip() == (
            "===== [COMPACTION BOUNDARY] ====="
        ):
            finish_user()
            current_record = "other"
            saw_record = True
        elif current_record == "user" and current_user is not None:
            current_user.append(line)
        elif current_record == "other" or not line.strip():
            continue
        else:
            _fail("slice contains text outside a supported record boundary")
    finish_user()
    if text.strip() and not saw_record:
        _fail("slice contains no supported record boundary")
    return prompts


def _read_slice_prompts(manifest_path: Path, transcript: Path) -> set[str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _fail(f"cannot read condense manifest: {error}")
    manifest_transcript = manifest.get("transcript") if isinstance(manifest, dict) else None
    if not isinstance(manifest_transcript, str) or not manifest_transcript:
        _fail("condense manifest has no transcript provenance")
    try:
        same_transcript = Path(manifest_transcript).samefile(transcript)
    except OSError as error:
        _fail(f"cannot validate manifest transcript provenance: {error}")
    if not same_transcript:
        _fail("condense manifest belongs to a different transcript")
    parts = manifest.get("parts") if isinstance(manifest, dict) else None
    if not isinstance(parts, list) or not parts:
        _fail("condense manifest has no parts")
    n_parts = manifest.get("n_parts")
    if type(n_parts) is not int or n_parts <= 0:
        _fail("condense manifest has an invalid n_parts")
    if len(parts) != n_parts:
        _fail("condense manifest part count is incomplete")

    part_numbers: list[int] = []
    raw_paths: list[str] = []
    byte_counts: list[int] = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            _fail(f"condense manifest part {index} is not an object")
        part_number = part.get("part")
        raw_path = part.get("path")
        byte_count = part.get("bytes")
        token_estimate = part.get("est_tokens")
        if type(part_number) is not int:
            _fail(f"condense manifest part {index} has no integer part number")
        if not isinstance(raw_path, str) or not raw_path:
            _fail(f"condense manifest part {index} has no path")
        if type(byte_count) is not int or byte_count < 0:
            _fail(f"condense manifest part {index} has an invalid byte count")
        if (
            type(token_estimate) is not int
            or token_estimate != int(byte_count / _BYTES_PER_TOKEN)
        ):
            _fail(f"condense manifest part {index} has an invalid token estimate")
        part_numbers.append(part_number)
        raw_paths.append(raw_path)
        byte_counts.append(byte_count)
    if part_numbers != list(range(n_parts)):
        _fail("condense manifest part numbers are missing, duplicate, or unordered")
    if len(set(raw_paths)) != len(raw_paths):
        _fail("condense manifest contains duplicate part paths")
    total_slice_bytes = manifest.get("total_slice_bytes")
    total_est_tokens = manifest.get("total_est_tokens")
    expected_total_bytes = sum(byte_counts)
    if type(total_slice_bytes) is not int or total_slice_bytes != expected_total_bytes:
        _fail("condense manifest has an inconsistent total byte count")
    if (
        type(total_est_tokens) is not int
        or total_est_tokens != int(expected_total_bytes / _BYTES_PER_TOKEN)
    ):
        _fail("condense manifest has an inconsistent total token estimate")

    manifest_directory = manifest_path.resolve(strict=True).parent
    slice_prompts: set[str] = set()
    resolved_paths: set[Path] = set()
    for index, part in enumerate(parts):
        raw_path = raw_paths[index]
        source_path = Path(raw_path)
        try:
            source_mode = source_path.lstat().st_mode
            path = source_path.resolve(strict=True)
        except OSError as error:
            _fail(f"cannot resolve slice {index}: {error}")
        if stat.S_ISLNK(source_mode) or not stat.S_ISREG(source_mode):
            _fail(f"slice {index} is not a regular file")
        if path.parent != manifest_directory:
            _fail(f"slice {index} is outside the manifest directory")
        if path.name != f"slice_{index:03d}.txt":
            _fail(f"slice {index} does not have its canonical filename")
        if path in resolved_paths:
            _fail("condense manifest resolves multiple parts to one file")
        resolved_paths.add(path)
        try:
            raw_slice = path.read_bytes()
        except OSError as error:
            _fail(f"cannot read slice {index}: {error}")
        if len(raw_slice) != byte_counts[index]:
            _fail(f"slice {index} does not match its manifest byte count")
        text = raw_slice.decode("utf-8", errors="strict")
        slice_prompts.update(_slice_user_prompts(text))
    actual_paths: set[Path] = set()
    for candidate in manifest_directory.iterdir():
        if _SLICE_NAME_RE.fullmatch(candidate.name) is None:
            continue
        if candidate.is_symlink() or not candidate.is_file():
            _fail("manifest directory contains a non-regular slice path")
        actual_paths.add(candidate.resolve(strict=True))
    if actual_paths != resolved_paths:
        _fail("manifest parts do not match the complete on-disk slice set")
    return slice_prompts


def recover(transcript: Path, manifest: Path) -> tuple[list[tuple[int, str]], dict[str, object]]:
    """Return dropped prompts and a verified evidence summary."""
    slice_prompts = _read_slice_prompts(manifest, transcript)
    prompts: list[tuple[int, str]] = []
    seen: set[str] = set()
    delivery_records = 0

    try:
        lines = transcript.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as error:
        _fail(f"cannot read transcript: {error}")

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            _fail(f"line {line_number}: malformed JSON: {error.msg}")
        if not isinstance(record, dict):
            _fail(f"line {line_number}: transcript record is not an object")
        payload = _delivery_payload(record, line_number)
        if payload is None:
            continue
        delivery_records += 1
        prompt = flatten_payload(payload, location=f"line {line_number}")
        if not prompt:
            _fail(f"line {line_number}: delivery payload has no text")
        if prompt.startswith("<task-notification>") or prompt in seen:
            continue
        seen.add(prompt)
        if prompt not in slice_prompts:
            prompts.append((line_number, prompt))

    summary: dict[str, object] = {
        "delivery_records": delivery_records,
        "dropped_prompts": len(prompts),
        "probe_state": "verified",
        "unique_prompts": len(seen),
    }
    return prompts, summary


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        args.output.unlink(missing_ok=True)
        prompts, summary = recover(args.transcript, args.manifest)
        rendered = "\n\n".join(
            f"[raw line {line_number}] {prompt}"
            for line_number, prompt in prompts
        )
        _write_atomic(args.output, f"{rendered}\n" if rendered else "")
    except (OSError, UnicodeError, RecoveryError):
        print(UNVERIFIED_MESSAGE, file=sys.stderr)
        return 2

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
