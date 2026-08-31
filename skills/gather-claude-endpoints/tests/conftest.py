"""Shared fixtures for the endpoint-drift tests.

The engine's freshness cache (diff_engine.FRESHNESS_CACHE) is real cross-run
state in /tmp. Left unisolated, the first test that computes FRESH poisons
every later test that mocks a STALE/UNKNOWN git (measured 2026-08-22: three
code-freshness tests read a cached FRESH from an earlier test's mock), and
tests write throwaway tmp-path keys into the real cache file. Point it at a
per-test path instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diff_channels as dc  # noqa: E402  (module-swapped to the shared engine)


@pytest.fixture(autouse=True)
def _isolated_freshness_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "FRESHNESS_CACHE", tmp_path / "freshness-cache.json")
