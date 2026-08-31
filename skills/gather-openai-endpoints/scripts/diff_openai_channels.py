#!/usr/bin/env python3
"""Launcher — the shared drift engine with the OpenAI registry pre-bound.

Symmetric to gather-claude-endpoints/scripts/diff_channels.py (whose engine
default is the Anthropic registry). All flags pass through; an explicit
--specs wins over the injected default.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared" / "endpoint-drift"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import diff_engine  # noqa: E402


def main() -> int:
    argv = sys.argv[1:]
    if "--specs" not in argv:
        argv = ["--specs", str(_HERE / "openai_channel_specs.py"), *argv]
    return diff_engine.main(argv)


if __name__ == "__main__":
    sys.exit(main())
