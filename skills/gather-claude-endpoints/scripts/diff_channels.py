#!/usr/bin/env python3
"""Compatibility shim — the engine moved to skills/_shared/endpoint-drift/diff_engine.py.

Every documented command (`python3 .../scripts/diff_channels.py ...`) and every
import (`import diff_channels as dc`) keeps working: the sys.modules swap below
makes `diff_channels` BE the engine module, so attribute access, monkeypatching,
and global rebinding all hit the real engine — a re-export copy would silently
fork state (the two-source drift class). Without --specs the engine defaults to
this skill's channel_specs.py, so behavior here is unchanged.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared" / "endpoint-drift"
for _p in (str(_SHARED), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import diff_engine  # noqa: E402

sys.modules[__name__] = diff_engine

if __name__ == "__main__":
    sys.exit(diff_engine.main())
