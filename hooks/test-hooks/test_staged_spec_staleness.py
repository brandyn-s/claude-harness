"""Tests for bin/staged-spec-staleness.py.

Guards the class from INCIDENT 2026-07-28: an obsolete staged spec was read and
re-implemented two days after its fix shipped. The checker must (a) flag a spec
whose marker is present in the target, (b) NOT flag one whose marker is absent,
and (c) never flag a spec it cannot verify.

Run standalone:  python3 hooks/test-hooks/test_staged_spec_staleness.py
Under pytest:    collected normally (no module-level sys.exit — tdd-quality #14)
"""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "bin" / "staged-spec-staleness.py"
if not SCRIPT.exists():  # bin/ is a sibling of hooks/, not a child
    SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "bin" / "staged-spec-staleness.py"


def _load():
    spec = importlib.util.spec_from_file_location("staleness_under_test", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_repo(spec_names, target_rel, target_text):
    """Build a throwaway repo root with hooks/staged/<specs> + a target file."""
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "hooks" / "staged").mkdir(parents=True)
    (root / "skills").mkdir()          # find_repo_root sentinel
    for n in spec_names:
        (root / "hooks" / "staged" / n).write_text(
            "**Type**: PreToolUse:Bash — modify something\n", encoding="utf-8"
        )
    t = root / target_rel
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(target_text, encoding="utf-8")
    return root


class TestStalenessDetection(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_flags_spec_whose_marker_is_present(self):
        """The 2026-07-28 case: target already carries __tbg_rc -> spec is stale."""
        root = _fake_repo(
            ["tail-guard-preserve-exit-status.spec.md"],
            "hooks/bash-tail-buffering-guard.py",
            "def rewrite():\n    return '__tbg_rc=$?'\n",
        )
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(len(stale), 1, f"expected 1 stale, got {stale}")
        self.assertEqual(stale[0][0], "tail-guard-preserve-exit-status.spec.md")
        self.assertEqual(live, [])

    def test_does_not_flag_spec_whose_marker_is_absent(self):
        """NEGATIVE CONTROL. Without this, a checker that always reports stale
        would pass the test above — and would delete live work."""
        root = _fake_repo(
            ["tail-guard-preserve-exit-status.spec.md"],
            "hooks/bash-tail-buffering-guard.py",
            "def rewrite():\n    return 'no rc capture here'\n",
        )
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(stale, [], "must NOT flag a spec whose fix has not shipped")
        self.assertEqual(len(live), 1)

    def test_git_gating_spec_is_live_on_current_main(self):
        """Its GIT_GATING marker was verified absent from both guards on
        origin/main 2026-07-28 — so it must read as live, not stale."""
        root = _fake_repo(
            ["git-gating-pipe-guard.spec.md"],
            "hooks/bash-tail-buffering-guard.py",
            "def rewrite():\n    return '__tbg_rc=$?'\n",   # v6 present, but no GIT_GATING
        )
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(stale, [], "git-gating spec is NOT superseded by v6")
        self.assertEqual(len(live), 1)

    def test_undeclared_spec_is_unverifiable_never_stale(self):
        """A spec with no declared marker must be reported, never auto-flagged."""
        root = _fake_repo(
            ["some-brand-new.spec.md"],
            "hooks/bash-tail-buffering-guard.py",
            "anything",
        )
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(stale, [])
        self.assertEqual(len(unver), 1)

    def test_missing_target_is_unverifiable_never_stale(self):
        root = _fake_repo(["tail-guard-preserve-exit-status.spec.md"], "hooks/other.py", "x")
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(stale, [])
        self.assertEqual(len(unver), 1)

    def test_no_staged_dir_is_clean(self):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "hooks").mkdir()
        (root / "skills").mkdir()
        self.assertEqual(self.mod.audit(root), ([], [], []))


class TestExitCodeContract(unittest.TestCase):
    """healthcheck consumes the EXIT CODE, not audit()'s return value.

    tdd-quality #20: the audit()-level tests above all passed while main()
    returned 0 unconditionally — so a stale spec would never surface as a
    healthcheck WARN. Kills mutation: exit_zero_on_stale.
    """

    def _run(self, root):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root)],
            capture_output=True,
        )

    def test_exit_1_when_a_spec_is_stale(self):
        root = _fake_repo(
            ["tail-guard-preserve-exit-status.spec.md"],
            "hooks/bash-tail-buffering-guard.py",
            "return '__tbg_rc=$?'\n",
        )
        p = self._run(root)
        self.assertEqual(p.returncode, 1, f"stdout={p.stdout.decode()}")
        self.assertIn("STALE", p.stdout.decode())

    def test_exit_0_when_nothing_is_stale(self):
        root = _fake_repo(
            ["tail-guard-preserve-exit-status.spec.md"],
            "hooks/bash-tail-buffering-guard.py",
            "no rc capture\n",
        )
        p = self._run(root)
        self.assertEqual(p.returncode, 0, f"stdout={p.stdout.decode()}")
        self.assertNotIn("STALE", p.stdout.decode())

    def test_exit_0_on_the_real_repo(self):
        p = self._run(self.__class__._root)
        self.assertEqual(p.returncode, 0, f"stdout={p.stdout.decode()}")

    @classmethod
    def setUpClass(cls):
        cls._root = _load().find_repo_root(SCRIPT)


class TestAgainstRealRepo(unittest.TestCase):
    """Runs against the ACTUAL repo — the state this PR ships must be clean."""

    def setUp(self):
        self.mod = _load()
        self.root = self.mod.find_repo_root(SCRIPT)

    def test_repo_has_no_stale_staged_specs(self):
        stale, _unver, _live = self.mod.audit(self.root)
        self.assertEqual(
            [s[0] for s in stale], [],
            "a staged spec's fix has already shipped — git rm it",
        )

    def test_superseded_spec_is_gone_from_the_repo(self):
        self.assertFalse(
            (self.root / "hooks" / "staged" / "tail-guard-preserve-exit-status.spec.md").exists(),
            "the superseded spec must be deleted (shipped by #1713)",
        )



class TestNewFileSpecs(unittest.TestCase):
    """A spec whose target IS the new file it proposes is verifiable after all.

    Before this, every new-hook spec reported `unverifiable` forever: the target
    cannot exist until the fix ships, and a missing target was unconditionally
    unknown. "Unverifiable" is how the queue grew to 11 specs of which 4 had already
    shipped, so a permanently-unknown category is not a safe default — it is the
    failure mode.

    `new_file` must be declared EXPLICITLY. A typo'd target on an existing-file spec
    must still read unverifiable rather than silently reading as live.
    """

    def setUp(self):
        self.mod = _load()

    def _repo_with(self, spec_name, target_rel, marker, new_file, create_target):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "hooks" / "staged").mkdir(parents=True)
        (root / "skills").mkdir()
        (root / "hooks" / "staged" / spec_name).write_text("**Type**: x\n", encoding="utf-8")
        if create_target:
            t = root / target_rel
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(f"def f():\n    return {marker!r}\n", encoding="utf-8")
        decl = {"target": target_rel, "marker": marker, "shipped_by": None}
        if new_file:
            decl["new_file"] = True
        self.mod.MARKERS[spec_name] = decl
        self.addCleanup(self.mod.MARKERS.pop, spec_name, None)
        return root

    def test_new_file_spec_with_absent_target_is_LIVE_not_unverifiable(self):
        root = self._repo_with("brand-new-hook.spec.md", "hooks/brand-new-hook.py",
                               "NEW_MARKER", new_file=True, create_target=False)
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(stale, [])
        self.assertEqual(unver, [], "an absent new-file target is EVIDENCE, not unknown")
        self.assertEqual(len(live), 1)

    def test_new_file_spec_flips_to_STALE_once_the_file_carries_the_marker(self):
        """The known-positive for the branch above — without it, a checker that always
        said `live` for new-file specs would pass the previous test."""
        root = self._repo_with("brand-new-hook.spec.md", "hooks/brand-new-hook.py",
                               "NEW_MARKER", new_file=True, create_target=True)
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(len(stale), 1, f"marker present -> stale, got {stale}")
        self.assertEqual(live, [])

    def test_absent_target_WITHOUT_the_flag_stays_unverifiable(self):
        """The safety property: a typo'd existing-file target must not read as live."""
        root = self._repo_with("typo-target.spec.md", "hooks/does-not-exist.py",
                               "SOME_MARKER", new_file=False, create_target=False)
        stale, unver, live = self.mod.audit(root)
        self.assertEqual(stale, [])
        self.assertEqual(len(unver), 1)
        self.assertEqual(live, [])


class TestEverySpecIsVerifiable(unittest.TestCase):
    """THE INVARIANT THAT KEEPS THE QUEUE HONEST — every spec needs a marker.

    Measured 2026-08-27: hooks/staged/ held 11 specs. FOUR had already shipped (two
    said so in their own bodies; two were the same hazard staged 15 days apart by
    sessions that could not see each other) and SEVEN had no marker, so the tool
    printed `OK - 0 live, 11 unverifiable`. The tool was honest; the headline was not.

    Without this test the queue silently re-accumulates unknowns. With it, staging a
    spec requires declaring how its completion will be detected — which the author
    knows at staging time and nobody knows later.
    """

    def setUp(self):
        self.mod = _load()
        self.root = self.mod.find_repo_root(SCRIPT)

    def test_no_staged_spec_is_unverifiable(self):
        _stale, unver, _live = self.mod.audit(self.root)
        self.assertEqual(
            [u[0] for u in unver], [],
            "every staged spec must declare a marker in MARKERS so its completion is "
            "DETECTABLE. Add an entry naming the target file and the symbol the fix "
            "introduces (a constant or env-var name, not prose), and verify the marker "
            "is ABSENT before registering it — a marker that is already present yields "
            "a false STALE and prints a `git rm` for live work.",
        )

    def test_every_declared_marker_names_a_real_target_or_is_flagged_new_file(self):
        """A marker pointing at a path that does not exist and is not flagged new_file
        is a typo, and it silently disables verification for that spec."""
        broken = []
        for name, decl in self.mod.MARKERS.items():
            if not (self.root / "hooks" / "staged" / name).exists():
                continue          # entry for an already-deleted spec; harmless
            if not (self.root / decl["target"]).exists() and not decl.get("new_file"):
                broken.append((name, decl["target"]))
        self.assertEqual(broken, [], f"target missing and not flagged new_file: {broken}")


class TestSummaryWording(unittest.TestCase):
    """The SUMMARY LINE is what a human reads; the exit code is what healthcheck reads.

    Exit 0 with unverifiable specs is DELIBERATE (silence beats a false delete, per the
    module docstring). That makes the wording the only signal a person gets — and
    `OK - 0 live, 11 unverifiable` is exactly how this queue reached 11 specs with four
    already shipped. Mutation-driven: reverting the wording to "OK" passed all 16 tests,
    so the property was shipped untested and a future edit could silently undo it.
    """

    def _run(self, root):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root)],
            capture_output=True, text=True,
        )

    def test_says_UNKNOWN_when_a_spec_has_no_marker(self):
        root = _fake_repo(["undeclared-thing.spec.md"],
                          "hooks/bash-tail-buffering-guard.py", "anything")
        p = self._run(root)
        self.assertEqual(p.returncode, 0, "exit stays 0 — no false delete")
        self.assertIn("UNKNOWN", p.stdout)
        self.assertIn("UNVERIFIABLE", p.stdout)
        self.assertNotIn("staleness: OK", p.stdout,
                         "an unverifiable spec must not be summarized as OK")

    def test_says_OK_only_when_nothing_is_unverifiable(self):
        """Known-negative for the above: the OK branch must still exist and be reachable."""
        root = _fake_repo(["tail-guard-preserve-exit-status.spec.md"],
                          "hooks/bash-tail-buffering-guard.py", "no rc capture here\n")
        p = self._run(root)
        self.assertEqual(p.returncode, 0)
        self.assertIn("staleness: OK", p.stdout)
        self.assertNotIn("UNVERIFIABLE", p.stdout)


class TestArcOnlySpecs(unittest.TestCase):
    """The two specs that existed ONLY in the ~/.claude local arc (2026-08-27).

    Neither ever reached origin/main, because that checkout is 278 commits ahead and
    drains only via separate PRs. For 24 and 29 days they were invisible to CI, to
    every other checkout, and to this tool. TestEverySpecIsVerifiable is what
    surfaced them.
    """

    def setUp(self):
        self.mod = _load()
        self.root = self.mod.find_repo_root(SCRIPT)

    def test_org_guard_marker_names_the_UNSHIPPED_half(self):
        """Half of that spec shipped; the marker must point at the half that did NOT.

        Measured 2026-08-27 against the deployed guard: the read/write discriminator
        is live (6/6 read forms allowed, 3/3 writes blocked). If the marker named the
        SHIPPED half, this tool would report the spec STALE and print a `git rm` for
        the approval mechanism, which is still real work. That is the exact
        false-positive the module docstring warns about.
        """
        decl = self.mod.MARKERS["org-guard-read-write-discrimination.spec.md"]
        self.assertEqual(decl["target"], "hooks/bash-security-guard.py")
        guard = (self.root / decl["target"]).read_text(encoding="utf-8")
        self.assertNotIn(decl["marker"], guard,
                         "marker must be ABSENT — the approval mechanism has not shipped")
        # The SHIPPED half must really be present, or the shipped/unshipped split this
        # entry encodes is wrong. `_GH_API_GET_RE` is the read/write discriminator the
        # spec asked to be reused for the `--repo` form; `check_forbidden_org` is the
        # function that consumes it.
        self.assertIn("_GH_API_GET_RE", guard,
                      "the read/write discriminator must exist — it is the shipped half")
        self.assertIn("check_forbidden_org", guard)

    def test_org_guard_spec_records_its_half_shipped_status(self):
        """Preserved WITH a status header, not verbatim.

        A verbatim copy would let the next reader re-derive the read/write
        discriminator that already shipped — the incident this tool exists to prevent.
        """
        spec = (self.root / "hooks" / "staged"
                / "org-guard-read-write-discrimination.spec.md")
        body = spec.read_text(encoding="utf-8")
        self.assertIn("HALF SHIPPED", body)
        self.assertIn("NOT SHIPPED", body)
        self.assertIn("ORG_WRITE_APPROVAL", body,
                      "the header must name the completion marker")

    def test_tombstone_fires_if_the_obsolete_spec_is_ever_re_staged(self):
        """verdict-command-position-anchoring was arc-only and FULLY obsolete.

        Both defects shipped as _verdict_at_command_position (Defect A) and
        _is_backgrounded (Defect B), so it was deleted rather than preserved. The
        registry entry remains as a tombstone: if some old checkout re-stages it, this
        tool must say STALE on the first run instead of a session re-deriving shipped
        work. Known-positive for that, since the real repo no longer has the file.
        """
        name = "verdict-command-position-anchoring.spec.md"
        self.assertIn(name, self.mod.MARKERS, "tombstone entry must be retained")
        decl = self.mod.MARKERS[name]

        # NON-TAUTOLOGICAL CHECK, and the reason this test is not self-fulfilling.
        # The fake repo below writes the marker INTO its own target, so ANY marker
        # string matches there — mutation-testing showed that repointing the tombstone
        # at a symbol which never shipped passed all 23 tests. The marker must name
        # something that ACTUALLY SHIPPED, so assert it against the real guard.
        real_target = (self.root / decl["target"]).read_text(encoding="utf-8")
        self.assertIn(decl["marker"], real_target,
                      f"tombstone marker {decl['marker']!r} must name a symbol that "
                      f"really shipped into {decl['target']}; otherwise the tombstone "
                      f"never fires and a re-staged obsolete spec reads as live")

        root = _fake_repo([name], decl["target"],
                          f"def {decl['marker']}(segment):\n    return True\n")
        stale, unver, live = self.mod.audit(root)
        self.assertEqual([s[0] for s in stale], [name],
                         "a re-staged obsolete spec must report STALE immediately")
        self.assertEqual(live, [])
        self.assertEqual(unver, [])

    def test_tombstone_does_not_fire_when_the_fix_is_absent(self):
        """Known-negative: the tombstone must key on the SHIPPED SYMBOL, not the name.

        Without this, an entry that always reported STALE would pass the test above and
        would delete a genuinely live spec.
        """
        name = "verdict-command-position-anchoring.spec.md"
        decl = self.mod.MARKERS[name]
        root = _fake_repo([name], decl["target"], "def something_else():\n    pass\n")
        stale, _unver, live = self.mod.audit(root)
        self.assertEqual(stale, [])
        self.assertEqual(len(live), 1)

    def test_the_obsolete_spec_is_absent_from_the_repo(self):
        self.assertFalse(
            (self.root / "hooks" / "staged"
             / "verdict-command-position-anchoring.spec.md").exists(),
            "fully-obsolete spec must not be preserved — both defects shipped",
        )


class TestReAddDetection(unittest.TestCase):
    """A spec that was DELETED upstream and is now back must be reported.

    Measured 2026-08-27, self-inflicted: `org-guard-read-write-discrimination.spec.md`
    was deleted from origin/main on 2026-08-15 by 0c9f5e56 as already-shipped, whose own
    message warned that keeping a shipped spec "invites a second implementation". Twelve
    days later a pre-deletion remnant was found in a 278-commit-diverged local checkout,
    its presence there was read as "never shipped", and it was re-added to origin/main.

    The tool could report stale / live / unverifiable but had no notion of a spec coming
    BACK, so nothing surfaced the reversal. A file's presence in one checkout is not
    evidence about its history in another.
    """

    def setUp(self):
        self.mod = _load()
        self.root = self.mod.find_repo_root(SCRIPT)

    def test_the_readded_spec_is_detected_with_its_deleting_commit(self):
        """KNOWN-POSITIVE against real history — this repo genuinely has one."""
        dels = self.mod.prior_deletions(
            self.root, "org-guard-read-write-discrimination.spec.md")
        if not dels:
            self.skipTest("curated repository history does not include the deletion fixture")
        self.assertTrue(dels, "a prior deletion of this spec exists in git history")
        shas = [d[0] for d in dels]
        subjects = " ".join(d[2] for d in dels)
        self.assertIn("already shipped", subjects,
                      "the rationale must be surfaced, not just the sha")
        self.assertTrue(all(len(s) >= 7 for s in shas))

    def test_a_never_deleted_spec_reports_no_prior_deletion(self):
        """KNOWN-NEGATIVE. Without this, a function returning every commit would pass."""
        dels = self.mod.prior_deletions(self.root, "tool-receipt-log.spec.md")
        self.assertEqual(dels, [],
                         "tool-receipt-log has never been deleted; must report none")

    def test_a_nonexistent_path_reports_no_prior_deletion(self):
        self.assertEqual(
            self.mod.prior_deletions(self.root, "no-such-spec-abc123.spec.md"), [])

    def test_the_readded_report_reaches_stdout(self):
        """The exit contract is unchanged (0 when nothing is stale), so the SUMMARY is
        the only channel — assert it actually prints, like TestSummaryWording does."""
        if not self.mod.prior_deletions(
                self.root, "org-guard-read-write-discrimination.spec.md"):
            self.skipTest("curated repository history does not include the deletion fixture")
        p = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                           capture_output=True, text=True)
        # Assert the HEADER specifically, not the bare token "RE-ADDED" — that token
        # also appears on the per-spec line, so suppressing the header alone left the
        # substring satisfied. Third instance this session of an assertion passing on a
        # different occurrence of the same token (see tdd-mutation-testing item 40).
        self.assertIn("STAGED-SPEC RE-ADDED", p.stdout, "the header must print")
        self.assertIn("0c9f5e56", p.stdout, "must name the deleting commit")
        # And the RATIONALE must reach stdout, not merely the return value: a sha alone
        # makes the reader go look it up, which is the step that did not happen.
        self.assertIn("already shipped", p.stdout,
                      "the deleting commit's SUBJECT must be printed, not just its sha")
        self.assertIn("SECOND implementation", p.stdout,
                      "the ACTION line explaining why this matters must print")

if __name__ == "__main__":
    unittest.main(verbosity=2)
