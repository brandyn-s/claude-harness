"""Validate an installed Claude Code version against the architecture floor."""

from __future__ import annotations

import re
import sys

MINIMUM_VERSION = (2, 1, 223)


def parse_version(output: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", output)
    if not match:
        raise ValueError(f"could not parse Claude Code version from {output!r}")
    return tuple(int(part) for part in match.groups())


def validate_version(output: str) -> tuple[int, int, int]:
    version = parse_version(output)
    if version < MINIMUM_VERSION:
        minimum = ".".join(str(part) for part in MINIMUM_VERSION)
        actual = ".".join(str(part) for part in version)
        raise ValueError(
            f"Claude Code {actual} is below the required architecture floor {minimum}"
        )
    return version


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_claude_version.py '<claude --version output>'", file=sys.stderr)
        return 2
    try:
        version = validate_version(args[0])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Claude Code version accepted: " + ".".join(str(part) for part in version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
