"""Tests for read-deny-guard.py (compensating control for claude-code #88795)."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(__file__), "..", "read-deny-guard.py")


def run_hook(payload, settings_path=None):
    env = dict(os.environ)
    if settings_path is not None:
        env["CLAUDE_READ_DENY_SETTINGS"] = settings_path
    proc = subprocess.run(
        [sys.executable, HOOK],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc


def load_module():
    spec = importlib.util.spec_from_file_location("read_deny_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPatternMatching(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_env_at_depth(self):
        self.assertTrue(self.mod.path_matches("/tmp/x/y/.env", "**/.env"))

    def test_env_suffix(self):
        self.assertTrue(self.mod.path_matches("/tmp/x/.env.production", "**/.env.*"))

    def test_home_anchored(self):
        home = os.path.expanduser("~")
        self.assertTrue(self.mod.path_matches(home + "/.ssh/id_rsa", "~/.ssh/**"))

    def test_secrets_glob(self):
        self.assertTrue(self.mod.path_matches("/tmp/x/secrets.yaml", "**/secrets.*"))

    def test_non_match(self):
        self.assertFalse(self.mod.path_matches("/tmp/x/notes.md", "**/.env"))
        self.assertFalse(self.mod.path_matches("/tmp/x/.environment", "**/.env"))

    def test_symlink_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, ".env")
            with open(target, "w", encoding="utf-8") as f:
                f.write("x=1\n")
            link = os.path.join(d, "innocent.txt")
            os.symlink(target, link)
            self.assertTrue(self.mod.path_matches(link, "**/.env"))


class TestEndToEnd(unittest.TestCase):
    """Hermetic: writes its own settings file and points the hook at it via
    CLAUDE_READ_DENY_SETTINGS. The 2026-08-22 version read the LIVE
    ~/.claude/settings.json, which does not exist on a CI runner — the hook
    loaded zero deny patterns, exited 0, and both deny tests failed on every
    runner while passing locally (main red for 5 consecutive runs)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = os.path.join(self._tmp.name, "settings.json")
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump(
                {"permissions": {"deny": ["Read(**/.env)", "Read(~/.ssh/**)"]}}, f
            )

    def test_denied_env_blocks(self):
        proc = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/claude/anything/.env"}},
            settings_path=self.settings,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("read-deny-guard", proc.stderr)

    def test_denied_ssh_blocks(self):
        proc = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": os.path.expanduser("~/.ssh/id_ed25519")}},
            settings_path=self.settings,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_allowed_path_passes(self):
        proc = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/claude/notes.md"}},
            settings_path=self.settings,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_no_deny_rules_is_fail_open(self):
        # Negative control: a settings file with no deny list must allow.
        empty = os.path.join(self._tmp.name, "empty.json")
        with open(empty, "w", encoding="utf-8") as f:
            json.dump({"permissions": {"deny": []}}, f)
        proc = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/claude/anything/.env"}},
            settings_path=empty,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_settings_file_is_fail_open(self):
        # Fail-open control: unreadable settings path -> allow (documented behavior).
        proc = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/claude/anything/.env"}},
            settings_path=os.path.join(self._tmp.name, "nonexistent.json"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_empty_stdin_passes(self):
        proc = run_hook("")
        self.assertEqual(proc.returncode, 0)

    def test_malformed_json_passes(self):
        proc = run_hook("{not json")
        self.assertEqual(proc.returncode, 0)

    def test_other_tool_passes(self):
        proc = run_hook({"tool_name": "Grep", "tool_input": {"file_path": "/tmp/x/.env"}})
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
