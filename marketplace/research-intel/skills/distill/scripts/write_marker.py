#!/usr/bin/env python3
"""Write distill's session-scoped coordination marker atomically."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TIER_PATTERN = re.compile(r"^(T[0-5](-hook|-startup|-ci)?|SKILL-ROUTED)$")
FRICTION_CATEGORIES = {
    "tool-failure",
    "skill-misfire",
    "rule-gap",
    "rule-overload",
    "context-waste",
    "permission-gap",
    "missing-capability",
}
PAYLOAD_KEYS = {"metrics", "lessons"}


class PayloadError(ValueError):
    """The caller supplied a payload that cannot form a valid marker."""


def _load_payload(source: str | None, clean: bool) -> dict[str, Any]:
    if clean:
        return {"lessons": []}
    if source is None:
        raise PayloadError("one of --input or --clean is required")
    try:
        if source == "-":
            value = json.load(sys.stdin)
        else:
            value = json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PayloadError(f"cannot read payload: {exc}") from exc
    if not isinstance(value, dict):
        raise PayloadError("payload must be a JSON object")
    extras = sorted(set(value) - PAYLOAD_KEYS)
    if extras:
        raise PayloadError(f"unsupported payload keys: {', '.join(extras)}")
    return value


def _validated_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metrics = payload.get("metrics")
    if metrics is not None:
        if not isinstance(metrics, dict):
            raise PayloadError("metrics must be a JSON object")
        for key, value in metrics.items():
            if not isinstance(key, str) or not key:
                raise PayloadError("metric names must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise PayloadError(f"metric {key!r} must be a number or string")

    lessons = payload.get("lessons", [])
    if not isinstance(lessons, list):
        raise PayloadError("lessons must be a JSON array")
    for index, lesson in enumerate(lessons):
        if not isinstance(lesson, dict):
            raise PayloadError(f"lessons[{index}] must be a JSON object")
        for field in ("title", "tier", "target"):
            value = lesson.get(field)
            if not isinstance(value, str) or not value.strip():
                raise PayloadError(f"lessons[{index}].{field} must be a non-empty string")
        if not TIER_PATTERN.fullmatch(lesson["tier"]):
            raise PayloadError(f"lessons[{index}].tier is invalid: {lesson['tier']!r}")
        friction = lesson.get("friction")
        if friction is not None and friction not in FRICTION_CATEGORIES:
            raise PayloadError(f"lessons[{index}].friction is invalid: {friction!r}")
    return metrics, lessons


def _session_id() -> str:
    return (
        os.environ.get("CODEX_THREAD_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or "unknown"
    )


def _default_state_root() -> Path:
    state_dir = ".codex" if os.environ.get("CODEX_THREAD_ID") else ".claude"
    return Path.home() / state_dir


def _atomic_write(path: Path, marker: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".last-distill-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(marker, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="payload JSON path, or - for stdin")
    source.add_argument("--clean", action="store_true", help="write a zero-lesson marker")
    parser.add_argument(
        "--state-root",
        type=Path,
        help="override the runtime state directory (defaults to ~/.codex or ~/.claude)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = _load_payload(args.input, args.clean)
        metrics, lessons = _validated_payload(payload)
    except PayloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    marker: dict[str, Any] = {
        "session_id": _session_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lesson_count": len(lessons),
        "lessons": lessons,
    }
    if metrics is not None:
        marker["metrics"] = metrics

    state_root = (args.state_root or _default_state_root()).expanduser()
    output = state_root / "last-distill.json"
    try:
        _atomic_write(output, marker)
    except OSError as exc:
        print(f"error: cannot write {output}: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {output} ({len(lessons)} lesson(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
