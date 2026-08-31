#!/usr/bin/env python3
"""Compatibility entry point for mega-distill's bundled transcript condenser."""
from __future__ import annotations

import importlib.util
from pathlib import Path


_IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "mega-distill"
    / "scripts"
    / "transcript_condense.py"
)
_SPEC = importlib.util.spec_from_file_location("_mega_distill_transcript_condense", _IMPLEMENTATION)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load transcript condenser from {_IMPLEMENTATION}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

for _NAME in dir(_MODULE):
    if not _NAME.startswith("__"):
        globals()[_NAME] = getattr(_MODULE, _NAME)


if __name__ == "__main__":
    _MODULE.main()
