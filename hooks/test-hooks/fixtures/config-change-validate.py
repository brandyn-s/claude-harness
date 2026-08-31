#!/usr/bin/env python3
"""Branch-local ConfigChange fixture for release-qualification integration tests.

The config-integrity branch owns the production hook. This fixture supplies
only the minimal public contract needed to qualify the runtime branch before
those independently reviewed changes are integrated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


MUTABLE_SOURCES = {"user_settings", "project_settings", "local_settings"}


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}
    if not isinstance(event, dict) or event.get("source") not in MUTABLE_SOURCES:
        return 0
    try:
        candidate = Path(str(event.get("file_path", "")))
        value = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("settings root must be an object")
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"decision": "block", "reason": f"invalid settings: {exc}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
