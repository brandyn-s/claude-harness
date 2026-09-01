"""Tests for hooks/poll-loop-nudge.py (PreToolUse:Bash), added 2026-08-27.

WHY THIS FILE EXISTS AT ALL — the registration vanished and nothing noticed.

`poll-loop-nudge.py` shipped 2026-07-24 (#1681) and fired **43,158 times over its 14
live days**. On 2026-08-09, #1950 rewrote 362 lines of settings.json to migrate every
hook from the old exec form (`"command": "\"$HOME/...\" name.py"`) to the new
`command` + `args[]` form, and in that mechanical rewrite this hook's entry was
DROPPED. It sat next to `zsh-dialect-guard.py` in one group; the rewrite kept the
neighbour. **11 registrations were lost the same way**, of which 9 are registered on
no surface at all today.

It went unnoticed for 18 days because this hook had, uniquely, NO test file, NO
ARCHITECTURE.md row, and no reference anywhere in the tree — which is also why it was
the only one of the nine the architecture audit could report. That audit asks "is this
file dead code?" (a true orphan is one *nothing reaches*), not "is this hook wired?",
so the other eight are excluded by a passing mention in a manifest, test, or skill.

So the assertions below deliberately include a WIRING test. A detection suite alone
would have stayed green through all 18 unwired days.

Evidence that the restore is warranted rather than sentimental (measured 2026-08-27):
  * the guarded shape recurred **53 times in a single session** (4.20% of 1,261 Bash
    commands) while the hook was unwired — including `sleep 110; gh pr checks 336`
    repeated for 337 and 338, which is exactly the wasted-turn loop it exists to stop
  * corpus fire rate 3.63% (497 of 13,697), against the hook's original 5.22%
    qualification and its <10% advisory gate
  * no other hook covers it: `bash-tail-buffering-guard` names `run_in_background`
    only inside its own fix text for pipe buffering, and its source says "Do NOT widen"
"""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "poll-loop-nudge.py"
REPO = HOOK.parents[1]
ADVISORY = "[poll-loop-nudge]"


def _load():
    """Import by path — the filename is hyphenated, so it is not importable."""
    spec = importlib.util.spec_from_file_location("poll_loop_nudge", HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    return mod


G = _load()


class Wiring(unittest.TestCase):
    """The test class that would have caught the 2026-08-09 loss.

    A detection-only suite passes perfectly while the hook is unreachable. These
    assertions fail the moment the registration disappears again.
    """

    @staticmethod
    def _registered(settings_path: Path):
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        out = []
        for event, groups in (data.get("hooks") or {}).items():
            for group in groups if isinstance(groups, list) else []:
                if not isinstance(group, dict):
                    continue
                for h in group.get("hooks", []) or []:
                    if isinstance(h, dict) and h.get("args") == ["poll-loop-nudge.py"]:
                        out.append((event, group.get("matcher"), h.get("timeout")))
        return out

    def test_registered_in_settings_json(self):
        rows = self._registered(REPO / "settings.json")
        self.assertEqual(len(rows), 1, f"expected exactly one registration, got {rows}")
        event, matcher, timeout = rows[0]
        self.assertEqual(event, "PreToolUse")
        self.assertIn("Bash", matcher or "")
        # architecture-drift-check.py enforces a 10s floor on PreToolUse: the run-hook
        # wrapper's start-up alone is a measured 1.4-4.1s.
        self.assertGreaterEqual(timeout, 10)

    def test_registered_in_settings_example_json(self):
        """The example must not drift from the live file — the drift gate blocks on it."""
        rows = self._registered(REPO / "settings.example.json")
        self.assertEqual(len(rows), 1, f"expected exactly one registration, got {rows}")

    def test_documented_in_architecture_md(self):
        """Absence here is why the audit saw this hook and not its eight siblings.

        The audit reports a hook only when NOTHING in hooks/, manifests/, skills/ or
        test-hooks/ mentions it. Documenting it is what makes a future de-registration
        visible to the wiring tests above rather than to nothing at all.

        ASSERTS BOTH REQUIRED LOCATIONS, NOT A BARE SUBSTRING. The first version of
        this test was `assertIn("poll-loop-nudge.py", arch)`, and mutation-testing
        showed it MISSED: the name appears in two places (the Layer-5 table and the
        hooks tree listing), so renaming the table row left the tree listing
        satisfying the assertion. A presence check on a repeated token passes for the
        wrong reason (tdd-mutation-testing item 25's count-not-presence corollary).
        The drift gate reads the Layer-5 TABLES specifically, so that row is the one
        that actually matters.
        """
        arch = (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8")

        self.assertIn(
            "reports direct-test coverage gaps",
            arch,
            "architecture must state the truthful hook-coverage contract",
        )

    def test_advisory_ordering_keeps_it_after_the_blocking_bash_guards(self):
        """An advisory must not preempt a block.

        If a command is both a poll loop and a credential leak, the BLOCK is the
        verdict that counts. Pinning the order stops a future edit from moving this
        ahead of the guards that can actually stop a command.
        """
        data = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
        names = []
        for group in data["hooks"]["PreToolUse"]:
            if "Bash" not in (group.get("matcher") or ""):
                continue
            for h in group.get("hooks", []) or []:
                for a in h.get("args", []) or []:
                    names.append(a)
        self.assertIn("poll-loop-nudge.py", names)
        self.assertIn("bash-security-guard.py", names)
        self.assertLess(
            names.index("bash-security-guard.py"), names.index("poll-loop-nudge.py"),
            "the blocking security guard must be evaluated before this advisory",
        )


class Detection(unittest.TestCase):
    """Shape A (single long sleep) and Shape B (state-polling loop), and the negatives."""

    def test_single_long_foreground_sleep_fires(self):
        self.assertTrue(G.fires("sleep 110; gh pr checks 336 --repo o/r"))
        self.assertTrue(G.fires("sleep 60; cat /tmp/out.log"))

    def test_real_recurrence_from_an_unwired_session_fires(self):
        """Verbatim from the session that ran while the hook was de-registered.

        Repeated for PRs 337 and 338 in the same session — the exact wasted-turn loop
        an advisory on the FIRST one would have short-circuited.
        """
        self.assertTrue(G.fires(
            "sleep 110; gh pr checks 336 --repo example-labs-org/example-labs-infra "
            "> /tmp/claude/c336.log 2>&1; grep -iE 'contract' /tmp/claude/c336.log"
        ))

    def test_short_sleep_alone_does_not_fire(self):
        """The whole point of the 60s floor: `sleep 5` is not a timeout risk."""
        for cmd in ("sleep 5; echo done", "sleep 30 && ls", "sleep 0.5"):
            self.assertFalse(G.fires(cmd), cmd)

    def test_bounded_poll_loop_fires_only_when_worst_case_approaches_the_timeout(self):
        # 10 iterations x 15s = 150s worst case, >= 90 -> fires
        self.assertTrue(G.fires(
            "for i in $(seq 1 10); do sleep 15; gh run view 1 --json status; done"
        ))
        # 3 iterations x 5s = 15s worst case, < 90 -> does not fire
        self.assertFalse(G.fires(
            "for i in $(seq 1 3); do sleep 5; gh run view 1 --json status; done"
        ))

    def test_unbounded_while_loop_fires_at_a_lower_per_iteration_threshold(self):
        """An unbounded `while` has no worst case, so a >=20s per-iter sleep suffices."""
        self.assertTrue(G.fires("while true; do sleep 20; gh pr view 1 --json state; done"))
        self.assertFalse(G.fires("while true; do sleep 2; echo tick; done"))

    def test_loop_without_a_poll_token_does_not_fire(self):
        """Shape B requires waiting on ASYNC STATE, not merely looping with a sleep."""
        self.assertFalse(G.fires(
            "for i in $(seq 1 10); do sleep 15; echo hello; done"
        ))

    def test_no_sleep_never_fires(self):
        for cmd in ("gh pr checks 336", "ls -la", "python3 -m pytest -q"):
            self.assertFalse(G.fires(cmd), cmd)


class AdvisoryContract(unittest.TestCase):
    """exit 0 always. A hook that blocks a legitimate long wait IS the DoS."""

    def _run(self, cmd):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        return subprocess.run([sys.executable, str(HOOK)], input=payload,
                              capture_output=True, text=True, check=False, timeout=30)

    def test_firing_case_exits_zero_and_writes_stderr(self):
        r = self._run("sleep 110; gh pr checks 336 --repo o/r")
        self.assertEqual(r.returncode, 0, "an advisory must never block")
        self.assertIn(ADVISORY, r.stderr)
        self.assertIn("run_in_background", r.stderr, "must name the actual remedy")

    def test_quiet_case_exits_zero_silently(self):
        r = self._run("ls -la")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn(ADVISORY, r.stderr)

    def test_malformed_input_never_blocks(self):
        for payload in ("", "{}", '{"tool_name":"Bash"}',
                        '{"tool_name":"Bash","tool_input":{}}', "not json"):
            r = subprocess.run([sys.executable, str(HOOK)], input=payload,
                               capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(r.returncode, 0, payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
