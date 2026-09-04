"""Tests for mcp-truncation-signal-guard.py (spec: hooks/staged/…spec.md).

Known-positive per signal family, negative controls, the raw_decode fallback,
shape tolerance, and the non-MCP gate (exercised via main()).
"""
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / 'mcp-truncation-signal-guard.py'
spec = importlib.util.spec_from_file_location('guard', HOOK)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def blocks(text):
    return [{'type': 'text', 'text': text}]


class DetectTests(unittest.TestCase):
    def test_gateway_marker_fires(self):
        out = guard.detect('mcp__x__y', blocks('payload…\n[_mcp_truncated=true effective_cap=100000]'))
        self.assertEqual(len(out), 1)
        self.assertIn('effective_cap=100000', out[0])

    def test_page_exhaustion_fires_with_counts_in_message(self):
        out = guard.detect('mcp__jamf__find_computers_by_user', blocks(
            json.dumps({'scannedCount': 500, 'totalCount': 857,
                        'scannedPages': 6, 'maxPages': 5, 'matchCount': 0})))
        self.assertEqual(len(out), 1)
        self.assertIn('scannedCount=500 of totalCount=857', out[0])
        self.assertIn('scannedPages 6 / maxPages 5', out[0])

    def test_equal_counts_silent(self):
        out = guard.detect('mcp__jamf__t', blocks(
            json.dumps({'scannedCount': 857, 'totalCount': 857})))
        self.assertEqual(out, [])

    def test_integer_compare_not_string(self):
        out = guard.detect('mcp__x__y', blocks(
            json.dumps({'scannedCount': 1000, 'totalCount': 857})))
        self.assertEqual(out, [])  # "1000" < "857" as strings would wrongly fire

    def test_capped_true_fires_capped_false_silent(self):
        fires = guard.detect('mcp__a__b', blocks(json.dumps({'capped': True, 'capped_hint': 'raise limit'})))
        self.assertEqual(len(fires), 1)
        self.assertIn('raise limit', fires[0])
        self.assertEqual(guard.detect('mcp__a__b', blocks(json.dumps({'capped': False}))), [])

    def test_valid_json_with_trailing_marker_fires_both(self):
        text = json.dumps({'scannedCount': 5, 'totalCount': 9}) + '\n[_mcp_truncated=true effective_cap=1]'
        out = guard.detect('mcp__x__y', blocks(text))
        self.assertEqual(len(out), 2)  # marker + counter, proves raw_decode fallback

    def test_nested_counters_fire(self):
        out = guard.detect('mcp__x__y', blocks(
            json.dumps({'meta': {'page': {'scannedCount': 1, 'totalCount': 2}}})))
        self.assertEqual(len(out), 1)

    def test_malformed_silent_no_exception(self):
        self.assertEqual(guard.detect('mcp__x__y', blocks('not json {{{')), [])
        self.assertEqual(guard.detect('mcp__x__y', None), [])
        self.assertEqual(guard.detect('mcp__x__y', {'weird': ['shapes', 1]}), [])


class MainTests(unittest.TestCase):
    def run_main(self, payload):
        stdin, stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = io.StringIO()
        try:
            with self.assertRaises(SystemExit) as cm:
                guard.main()
            return cm.exception.code, sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = stdin, stdout

    def test_non_mcp_tool_silent(self):
        code, out = self.run_main({'tool_name': 'Bash', 'tool_response': '[_mcp_truncated=true]'})
        self.assertEqual((code, out), (0, ''))

    def test_mcp_fire_emits_system_message_exit_zero(self):
        code, out = self.run_main({'tool_name': 'mcp__jamf__t',
                                   'tool_response': blocks(json.dumps({'scannedCount': 1, 'totalCount': 3}))})
        self.assertEqual(code, 0)
        self.assertIn('additionalContext', json.loads(out)['hookSpecificOutput'])

    def test_garbage_stdin_exit_zero(self):
        stdin = sys.stdin
        sys.stdin = io.StringIO('not json')
        try:
            with self.assertRaises(SystemExit) as cm:
                guard.main()
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.stdin = stdin


if __name__ == '__main__':
    unittest.main()
