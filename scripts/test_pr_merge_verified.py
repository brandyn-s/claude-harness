#!/usr/bin/env python3
"""Tests for bin/pr-merge-verified.py — the merge-queue drive-to-terminal loop.

WHY THESE TESTS EXIST: the script has now burned a full 20-minute timeout
twice on states that never self-resolve, each time reporting only a generic
"timeout" that hid a one-command fix:

  - DRAFT   (2026-07-27 mcp-servers #884) — a draft cannot arm auto-merge.
  - BEHIND  (2026-07-28 KB #1273)         — legacy auto-merge never updates
                                            the branch, so BEHIND + armed +
                                            unqueued is stable forever.

Both are now handled, and both are pinned here. The distinction the loop
must preserve: BEHIND is terminal-until-acted-on, while BLOCKED / UNSTABLE /
UNKNOWN genuinely are transient CI states that must keep waiting. A test
that only asserted "BEHIND does something" would pass on a loop that also
mangled the transient states, so the transient case is asserted too.

Mechanism: the script shells out to `gh` exclusively, so a fake `gh` earlier
on PATH is a complete seam. Each fake reads a scripted state sequence and
records every invocation, letting the test assert on the *commands issued*
(did it call `pr update-branch`?) rather than on log prose.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "pr-merge-verified.py"

# A fake `gh`. States are consumed one per `pr view`; the last one repeats so
# a loop that never converges still terminates on the script's own timeout
# rather than hanging the test suite.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ["FAKE_GH_LOG"]
states = json.loads(os.environ["FAKE_GH_STATES"])
argv = sys.argv[1:]
with open(log, "a") as fh:
    fh.write(" ".join(argv) + "\n")

def out(s):
    sys.stdout.write(s)
    raise SystemExit(0)

# `gh api graphql ...` -> merge-queue entry lookup
if argv[:2] == ["api", "graphql"]:
    calls = sum(1 for line in open(log) if line.startswith("pr view"))
    idx = min(max(calls - 1, 0), len(states) - 1)
    queued = states[idx].get("queued", False)
    entry = {"state": "QUEUED"} if queued else None
    out(json.dumps({"data": {"repository": {"pullRequest":
        {"mergeQueueEntry": entry}}}}))

if argv[:2] == ["pr", "view"]:
    calls = sum(1 for line in open(log) if line.startswith("pr view"))
    idx = min(calls - 1, len(states) - 1)
    s = states[idx]
    out(json.dumps({
        "state": s.get("state", "OPEN"),
        "mergeStateStatus": s.get("mss", "CLEAN"),
        "autoMergeRequest": {"enabledAt": "x"} if s.get("armed") else None,
        "isDraft": s.get("draft", False),
    }))

if argv[:2] == ["pr", "update-branch"]:
    if os.environ.get("FAKE_GH_UPDATE_FAILS") == "1":
        sys.stderr.write("failed to update branch: permission denied\n")
        raise SystemExit(1)
    out("PR branch updated\n")

if argv[:2] == ["pr", "merge"]:
    if os.environ.get("FAKE_GH_MERGE_REJECTS") == "protected":
        sys.stderr.write(
            "GraphQL: Pull request Branch does not have required protected "
            "branch rules (enablePullRequestAutoMerge)\n")
        raise SystemExit(1)
    out("")

out("")
'''


def _install_fake_gh(bindir: Path) -> None:
    """Put an executable `gh` on PATH that works on POSIX **and** Windows.

    The first version of this wrote the Python source to a file named `gh` with a
    shebang and chmod 0o755. That is Unix-only: Windows honours neither shebangs
    nor the POSIX exec bit, so `gh` was simply not runnable there. Every test
    then saw `gh calls were: []` and fell through to TIMEOUT — five failures on
    the windows-2022 leg while macOS and ubuntu passed. The tests looked like
    they asserted merge-loop behaviour; on Windows they asserted nothing.

    Fix, part one: write the logic to a `.py` file, then add the platform's own
    dispatch — a `gh.cmd` batch shim on Windows, a shebang + exec bit on POSIX.
    Same seam on both platforms, and deliberately NOT a skip: a test skipped on
    the only leg that can catch a platform bug is not coverage (tdd-quality
    item 11).

    Fix, part two — and this is what part one MISSED for a full CI cycle. Part
    one shipped on the reasoning "cmd.exe resolves a bare `gh` to `gh.cmd` via
    PATHEXT". True of cmd.exe, and irrelevant here: the code under test calls
    `subprocess.run([...], shell=False)`, which reaches Win32 CreateProcess
    directly, and CreateProcess appends only `.exe` — PATHEXT is a shell
    feature, not a kernel one. So the `gh.cmd` shim was still invisible and
    windows-2022 still reported `gh calls were: []`. The shim only became
    reachable once bin/pr-merge-verified.py started resolving through
    `shutil.which` (see `_gh_exe` there, and GhResolutionTest below).

    The lesson worth keeping: naming the right PLATFORM is not naming the right
    MECHANISM, and a test whose seam is unreachable fails as a TIMEOUT rather
    than as a missing shim — which is why the wrong mechanism survived a cycle.
    """
    script = bindir / "fake_gh.py"
    script.write_text(FAKE_GH, encoding="utf-8")
    if sys.platform == "win32":
        shim = bindir / "gh.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
    else:
        shim = bindir / "gh"
        shim.write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
        shim.chmod(0o755)


class MergeLoopTest(unittest.TestCase):
    def _run(self, states, update_fails=False, timeout_mins=0.05, extra_args=(),
             merge_rejects=False):
        """Run the script against a scripted state sequence.

        `states` describes what the POLL LOOP sees, in order. The script also
        makes one `pr view` BEFORE the loop (the draft pre-flight check), so
        states[0] is duplicated here to feed it — otherwise every test would
        silently be asserting against the second state and a loop that
        ignored the first would pass.

        Returns (returncode, stdout, stderr, gh_invocations).
        """
        states = [states[0]] + list(states)
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            _install_fake_gh(bindir)
            log = Path(td) / "gh.log"
            log.write_text("", encoding="utf-8")

            env = dict(os.environ)
            env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
            env["FAKE_GH_LOG"] = str(log)
            env["FAKE_GH_STATES"] = json.dumps(states)
            if update_fails:
                env["FAKE_GH_UPDATE_FAILS"] = "1"
            if merge_rejects:
                env["FAKE_GH_MERGE_REJECTS"] = "protected"

            command = [
                sys.executable, str(SCRIPT), "42", "--repo", "o/r",
                "--timeout-mins", str(timeout_mins), "--poll-secs", "0.01",
                *extra_args,
            ]
            p = subprocess.run(
                command,
                capture_output=True, env=env, timeout=120,
            )
            calls = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]
            return (p.returncode, p.stdout.decode(), p.stderr.decode(), calls)

    def test_behind_triggers_update_branch_then_merges(self):
        """BEHIND + armed + unqueued must be ACTED on, not waited out.

        This is the KB #1273 shape. Before the fix, BEHIND fell into the
        'keep waiting for CI' bucket and the loop polled to timeout.
        """
        rc, out, err, calls = self._run([
            {"state": "OPEN", "mss": "BEHIND", "armed": True, "queued": False},
            {"state": "MERGED"},
        ], timeout_mins=0.5)
        self.assertIn("pr update-branch 42 --repo o/r", calls,
                      f"never called update-branch; gh calls were: {calls}")
        self.assertEqual(rc, 0, f"expected MERGED exit 0; stderr={err}")
        self.assertIn("MERGED", out)

    def test_behind_rearms_after_updating(self):
        """The update creates a new head, which can drop the arm — so the
        loop must re-arm after updating, not merely update."""
        _, _, _, calls = self._run([
            {"state": "OPEN", "mss": "BEHIND", "armed": True, "queued": False},
            {"state": "MERGED"},
        ], timeout_mins=0.5)
        upd = calls.index("pr update-branch 42 --repo o/r")
        merges_after = [c for c in calls[upd:] if c.startswith("pr merge")]
        self.assertTrue(merges_after,
                        f"no re-arm after update-branch; calls={calls}")

    def test_behind_with_failing_update_exits_nonzero_not_timeout(self):
        """If the branch cannot be updated the loop must report that, not
        spend the timeout. Exit 6 is distinguishable from 2 (timeout)."""
        rc, _, err, _ = self._run([
            {"state": "OPEN", "mss": "BEHIND", "armed": True, "queued": False},
        ], update_fails=True, timeout_mins=0.5)
        self.assertEqual(rc, 6, f"expected BEHIND_STUCK exit 6, got {rc}")
        self.assertIn("BEHIND", err)

    def test_behind_while_queued_is_left_alone(self):
        """A queued PR is mid-merge_group; the queue owns the branch. Do NOT
        update it out from under the queue."""
        _, _, _, calls = self._run([
            {"state": "OPEN", "mss": "BEHIND", "armed": True, "queued": True},
            {"state": "MERGED"},
        ], timeout_mins=0.5)
        self.assertNotIn("pr update-branch 42 --repo o/r", calls,
                         f"updated a QUEUED pr; calls={calls}")

    def test_transient_states_still_wait(self):
        """NEGATIVE CONTROL for the fix's scope. BLOCKED/UNSTABLE/UNKNOWN are
        real CI-in-flight states: they must NOT be update-branched. Without
        this, a fix that treated every non-CLEAN state as actionable would
        pass the BEHIND tests above."""
        for mss in ("BLOCKED", "UNSTABLE", "UNKNOWN"):
            with self.subTest(mss=mss):
                _, _, _, calls = self._run([
                    {"state": "OPEN", "mss": mss, "armed": True,
                     "queued": False},
                    {"state": "MERGED"},
                ], timeout_mins=0.5)
                self.assertNotIn("pr update-branch 42 --repo o/r", calls,
                                 f"{mss} was treated as actionable; {calls}")

    def test_draft_fails_fast(self):
        """The 2026-07-27 shape: a draft can never arm, so fail before the
        poll loop with the actual reason."""
        rc, _, err, calls = self._run([
            {"state": "OPEN", "mss": "CLEAN", "draft": True},
        ])
        self.assertEqual(rc, 5, f"expected DRAFT exit 5, got {rc}")
        self.assertIn("gh pr ready", err)
        self.assertNotIn("pr merge 42 --repo o/r --auto", calls,
                         "tried to arm a draft")

    def test_dirty_exits_three(self):
        rc, _, err, _ = self._run([
            {"state": "OPEN", "mss": "DIRTY", "armed": False},
        ])
        self.assertEqual(rc, 3)
        self.assertIn("DIRTY", err)

    def test_status_file_records_terminal_outcome(self):
        """--status-file exists because a piped exit code lies. Assert the
        file, since that is the contract callers now depend on."""
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            _install_fake_gh(bindir)
            log = Path(td) / "gh.log"
            log.write_text("", encoding="utf-8")
            status = Path(td) / "status.json"
            env = dict(os.environ)
            env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
            env["FAKE_GH_LOG"] = str(log)
            env["FAKE_GH_STATES"] = json.dumps([{"state": "MERGED"}])
            subprocess.run(
                [sys.executable, str(SCRIPT), "42", "--repo", "o/r",
                 "--poll-secs", "0.01", "--timeout-mins", "0.5",
                 "--status-file", str(status)],
                capture_output=True, env=env, timeout=120,
            )
            payload = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(payload["terminal"], "MERGED")
            self.assertEqual(payload["exit"], 0)

    def test_queue_only_returns_after_auto_merge_is_durably_armed(self):
        rc, out, err, calls = self._run(
            [
                {"state": "OPEN", "mss": "CLEAN", "armed": False},
                {"state": "OPEN", "mss": "BLOCKED", "armed": True},
            ],
            timeout_mins=0.5,
            extra_args=("--queue-only",),
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("QUEUED", out)
        self.assertTrue(any(call.startswith("pr merge") for call in calls))

    def test_queue_only_unqueueable_fails_fast(self):
        """A repo that cannot HOLD an auto-merge request (no protected-branch
        rules) makes QUEUED structurally unreachable — --queue-only must fail
        fast with the direct-merge recipe, not poll to timeout or DIRTY.
        Measured 2026-08-22 (claude-config #2062, KB #1590)."""
        rc, out, err, calls = self._run(
            [{"state": "OPEN", "mss": "UNSTABLE", "armed": False}],
            timeout_mins=0.5,
            extra_args=("--queue-only",),
            merge_rejects=True,
        )
        self.assertEqual(rc, 7, err)
        self.assertIn("UNQUEUEABLE", err)
        self.assertIn("merge directly", err.lower())
        # Fail-fast: the draft pre-flight view plus at most one loop poll —
        # not a poll-to-timeout tail.
        views = [c for c in calls if c.startswith("pr view")]
        self.assertLessEqual(len(views), 2, calls)

    def test_unqueueable_without_queue_only_still_polls_to_merged(self):
        """Without --queue-only the unqueueable arm failure must NOT
        short-circuit: the loop's clean-status path is still a route to
        MERGED (e.g. another actor or the direct merge lands)."""
        rc, out, err, calls = self._run(
            [
                {"state": "OPEN", "mss": "UNSTABLE", "armed": False},
                {"state": "MERGED"},
            ],
            timeout_mins=0.5,
            merge_rejects=True,
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("MERGED", out)


class FakeGhPortabilityTest(unittest.TestCase):
    """The test harness itself must work on every CI leg.

    This class exists because the harness was Unix-only and that made five
    windows-2022 assertions vacuous rather than failing loudly: with no runnable
    `gh`, every call returned nothing and the loop timed out, so the tests were
    asserting on an empty command log. A harness bug is worse than a code bug —
    it removes coverage silently on exactly the platform that would have caught
    it (tdd-quality item 11).

    The Windows branch is exercised by faking sys.platform, so this runs on any
    host. The negative control below is what makes that emulation meaningful.
    """

    def test_windows_branch_writes_a_cmd_shim(self):
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            with mock.patch.object(sys, "platform", "win32"):
                _install_fake_gh(bindir)
            names = {p.name for p in bindir.iterdir()}
            self.assertIn("gh.cmd", names,
                          "cmd.exe resolves a bare `gh` via PATHEXT to gh.cmd; "
                          "without it nothing is executable")
            self.assertIn("fake_gh.py", names)
            body = (bindir / "gh.cmd").read_text(encoding="utf-8")
            self.assertTrue(body.startswith("@echo off"))
            self.assertIn(sys.executable, body)
            self.assertIn("%*", body, "must forward every argument")

    def test_posix_branch_writes_an_executable_shebang(self):
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            with mock.patch.object(sys, "platform", "darwin"):
                _install_fake_gh(bindir)
            gh = bindir / "gh"
            self.assertTrue(gh.read_text(encoding="utf-8").startswith("#!"))
            if sys.platform != "win32":
                # chmod's POSIX bits are a no-op on Windows (item 11), so this
                # half of the assertion is guarded rather than skipped whole.
                self.assertTrue(gh.stat().st_mode & 0o111)

    def test_the_old_unix_only_approach_produces_nothing_windows_can_run(self):
        """NEGATIVE CONTROL. Proves the fix addresses a real difference: the
        shipped approach (one shebang file, chmod) leaves no .cmd shim, which is
        precisely why `gh calls were: []` on windows-2022."""
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            old = bindir / "gh"
            old.write_text(FAKE_GH, encoding="utf-8")
            old.chmod(0o755)
            self.assertNotIn("gh.cmd", {p.name for p in bindir.iterdir()})


class GhResolutionTest(unittest.TestCase):
    """`gh` must be RESOLVED against PATH, not handed to subprocess bare.

    This is the property whose absence made the windows-2022 leg vacuous for a
    whole CI cycle even after the `gh.cmd` shim landed. `subprocess.run` is
    shell=False, so a bare "gh" reaches CreateProcess, which appends only
    `.exe` — PATHEXT never enters the picture, so the shim was unreachable.
    Asserting the MECHANISM (a resolved path) rather than the PLATFORM lets
    this run everywhere, including on the legs that cannot reproduce the bug.
    """

    def _load_script(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_prmv", SCRIPT)
        assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_gh_is_resolved_to_a_real_path_not_passed_as_a_bare_name(self):
        mod = self._load_script()
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            _install_fake_gh(bindir)
            with mock.patch.dict(
                os.environ, {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
            ):
                resolved = mod._gh_exe()
            self.assertNotEqual(
                resolved, "gh",
                "returned the bare name — CreateProcess would never find a "
                "non-.exe shim, which is the windows-2022 `gh calls were: []`",
            )
            self.assertEqual(
                Path(resolved).parent.resolve(), bindir.resolve(),
                f"resolved outside the seeded bindir: {resolved}",
            )

    def test_resolution_is_per_call_so_a_later_PATH_change_is_honoured(self):
        """Caching at import would silently ignore the test harness's PATH,
        reintroducing the empty-command-log failure by a different route."""
        mod = self._load_script()
        with tempfile.TemporaryDirectory() as td:
            first, second = Path(td) / "a", Path(td) / "b"
            for d in (first, second):
                d.mkdir()
                _install_fake_gh(d)
            base = os.environ["PATH"]
            with mock.patch.dict(os.environ, {"PATH": f"{first}{os.pathsep}{base}"}):
                a = mod._gh_exe()
            with mock.patch.dict(os.environ, {"PATH": f"{second}{os.pathsep}{base}"}):
                b = mod._gh_exe()
            self.assertNotEqual(a, b, "resolution appears cached across calls")

    def test_a_cmd_only_bindir_is_invisible_to_bare_name_lookup(self):
        """NEGATIVE CONTROL for the above, and the closest this host can get to
        emulating the Windows failure: a bindir holding ONLY `gh.cmd` offers
        nothing a bare-name lookup can execute. That is exactly the state
        windows-2022 was in — the shim existed, and nothing could reach it.
        Without this assertion the two tests above would also pass on a
        `_gh_exe` that merely returned "gh" on some platforms.
        """
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            (bindir / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
            (bindir / "gh.cmd").write_text("@echo off\r\n", encoding="utf-8")
            self.assertFalse(
                (bindir / "gh").exists(),
                "no extensionless `gh`, so CreateProcess's `.exe`-only search "
                "finds nothing — the shim is present but unreachable",
            )


class DocumentedBehaviourTest(unittest.TestCase):
    def test_gh_resolution_rationale_is_recorded_in_the_script(self):
        """The wrong mechanism (PATHEXT) was plausible enough to ship once.
        Pin the corrected reasoning where the next reader of `gh()` will see
        it, so a future 'simplify this back to ["gh"]' has to argue with it.
        """
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("shutil.which", text)
        self.assertIn("CreateProcess", text,
                      "the reason bare-name lookup fails is not recorded")

    def test_docstring_does_not_list_behind_as_a_wait_state(self):
        """The docstring is the operator-facing contract. It listed BEHIND
        among 'keep waiting' states, which is what made the wrong behaviour
        look intentional for two months."""
        text = SCRIPT.read_text(encoding="utf-8")
        head = text.split('"""')[1]
        self.assertNotIn("(BEHIND/BLOCKED", head,
                         "docstring still groups BEHIND with wait states")
        self.assertIn("BEHIND IS NOT A WAIT STATE", head)


if __name__ == "__main__":
    unittest.main(verbosity=2)
