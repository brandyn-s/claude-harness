"""Tests for msgraph_helper._open_with_429_retry — the bounded 429 backoff added
2026-08-29 after the dept-rename incident's directoryAudits throttling propagated
a failed stream as 'removals=0' into a joined report."""
from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))

import msgraph_helper  # noqa: E402


def _http_429(retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://x", 429, "Too Many Requests", headers,
                                  io.BytesIO(b'{"error":"throttled"}'))


def _http_403():
    return urllib.error.HTTPError("https://x", 403, "Forbidden", Message(),
                                  io.BytesIO(b'{"error":"denied"}'))


class TestOpenWith429Retry(unittest.TestCase):
    def test_retries_429_honoring_retry_after_then_succeeds(self):
        ok = mock.MagicMock(name="response")
        sleeps = []
        with mock.patch.object(msgraph_helper.urllib.request, "urlopen",
                               side_effect=[_http_429(retry_after=7), ok]) as opener, \
             mock.patch.object(msgraph_helper.time, "sleep", side_effect=sleeps.append):
            result = msgraph_helper._open_with_429_retry("req")
        self.assertIs(result, ok)
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(sleeps, [7])

    def test_missing_retry_after_uses_escalating_default(self):
        ok = mock.MagicMock(name="response")
        sleeps = []
        with mock.patch.object(msgraph_helper.urllib.request, "urlopen",
                               side_effect=[_http_429(), _http_429(), ok]), \
             mock.patch.object(msgraph_helper.time, "sleep", side_effect=sleeps.append):
            result = msgraph_helper._open_with_429_retry("req")
        self.assertIs(result, ok)
        self.assertEqual(sleeps, [30, 60])

    def test_exhausted_attempts_raises_the_429(self):
        sleeps = []
        with mock.patch.object(msgraph_helper.urllib.request, "urlopen",
                               side_effect=[_http_429(), _http_429(), _http_429()]) as opener, \
             mock.patch.object(msgraph_helper.time, "sleep", side_effect=sleeps.append):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                msgraph_helper._open_with_429_retry("req", max_attempts=3)
        self.assertEqual(ctx.exception.code, 429)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(len(sleeps), 2)  # no sleep after the final failure

    def test_non_429_raises_immediately_without_sleep(self):
        with mock.patch.object(msgraph_helper.urllib.request, "urlopen",
                               side_effect=[_http_403()]) as opener, \
             mock.patch.object(msgraph_helper.time, "sleep") as slept:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                msgraph_helper._open_with_429_retry("req")
        self.assertEqual(ctx.exception.code, 403)
        self.assertEqual(opener.call_count, 1)
        slept.assert_not_called()

    def test_retry_after_wait_is_capped_at_120s(self):
        ok = mock.MagicMock(name="response")
        sleeps = []
        with mock.patch.object(msgraph_helper.urllib.request, "urlopen",
                               side_effect=[_http_429(retry_after=999), ok]), \
             mock.patch.object(msgraph_helper.time, "sleep", side_effect=sleeps.append):
            msgraph_helper._open_with_429_retry("req")
        self.assertEqual(sleeps, [120])


if __name__ == "__main__":
    unittest.main()
