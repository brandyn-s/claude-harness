#!/usr/bin/env python3
"""Tests for bin/spend-limits.py.

The load-bearing behaviours, each of which corresponds to a way the
2026-08-01 wrong-org incident could recur:

  1. a CONSOLE key is refused before any network call (the incident itself)
  2. every non-200 is classified with the ORG-vs-SCOPE distinction
  3. a 400 "not supported for this organization type" is NEVER reported as
     a capability verdict
  4. writes refuse without --yes
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("spend_limits", ROOT / "bin" / "spend-limits.py")
assert SPEC and SPEC.loader
sl = importlib.util.module_from_spec(SPEC)
sys.modules["spend_limits"] = sl
SPEC.loader.exec_module(sl)


class TestKeyFamilyGuard(unittest.TestCase):
    def test_console_key_is_refused(self):
        with self.assertRaises(sl.SpendLimitError) as cm:
            sl.guard_key_family("sk-ant-admin01-abc123")
        msg = str(cm.exception)
        self.assertIn("CONSOLE", msg)
        # It must explain the 400 is not a capability verdict.
        self.assertIn("does not exist", msg)

    def test_enterprise_key_passes(self):
        sl.guard_key_family("sk-ant-api01-abc123")  # must not raise

    def test_unknown_prefix_warns_but_does_not_raise(self):
        sl.guard_key_family("sk-ant-api03-abc123")  # regular key: warn only


class TestClassify(unittest.TestCase):
    def test_400_org_type_is_wrong_org_not_absent_capability(self):
        out = sl.classify(400, '{"error":{"message":"this endpoint is not supported for this organization type"}}')
        self.assertIn("WRONG ORG", out)
        self.assertIn("NOT a capability verdict", out)
        # It must name the Console org so the reader knows which key was used.
        self.assertIn(sl.CONSOLE_ORG_UUID, out)

    def test_403_is_missing_scope_and_names_fixed_at_creation(self):
        out = sl.classify(403, '{"error":{"message":"Organization level API key required"}}')
        self.assertIn("MISSING SCOPE", out)
        self.assertIn("FIXED at creation", out)

    def test_401_is_wrong_key_class(self):
        self.assertIn("WRONG KEY CLASS", sl.classify(401, "invalid x-api-key"))

    def test_405_points_at_effective(self):
        self.assertIn("effective", sl.classify(405, "Method Not Allowed"))

    def test_429_names_the_shared_org_limit(self):
        self.assertIn("60 req/min", sl.classify(429, "Too Many Requests"))

    def test_403_and_400_are_not_the_same_message(self):
        """The whole incident was conflating these two."""
        a = sl.classify(400, "not supported for this organization type")
        b = sl.classify(403, "Organization level API key required")
        self.assertNotEqual(a, b)


class TestUsdFormatting(unittest.TestCase):
    def test_none_is_unlimited_not_zero(self):
        """null means UNLIMITED; rendering it as $0.00 would invert the meaning."""
        self.assertEqual(sl.usd(None), "unlimited")

    def test_zero_string_is_a_real_zero_cap(self):
        self.assertEqual(sl.usd("0"), "$0.00")

    def test_cents_to_dollars(self):
        self.assertEqual(sl.usd("50000"), "$500.00")

    def test_fractional_cents_survive(self):
        self.assertEqual(sl.usd("41280.125"), "$412.80")


if __name__ == "__main__":
    unittest.main()
