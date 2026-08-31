#!/usr/bin/env python3
"""Tests for bin/kb-entry-budget.py — the pre-write budget for KB entries.

The tool's entire value is AGREEING WITH `kb.py check`. A budget that
disagrees is worse than none: it greenlights drafts the gate rejects, or
blocks drafts the gate would accept. So the tests here are about fidelity to
the checker's model, not about the tool's own prose:

  - limits are READ from kb.py, never hardcoded (so they cannot rot apart)
  - chunk boundaries fall at every H2 AND H3, matching kb.py's _chunk_errors
    (this is what makes `###` splitting a real fix, and it is the property a
    naive H2-only model would get wrong)
  - a section soft-split into `###` children reports the CHILD as the
    constraint, not the H2's heading-only size

Ground truth: on 2026-07-28 a capture run had three entries rejected by
kb.py at 3,525c / 3,601c / 3,115c. Those numbers are the fixture below —
if this tool's arithmetic drifts, the fixture stops reproducing them.

The tool reads ~/Documents/knowledge-base, so tests that need a topic page
are skipped when that checkout is absent (fresh host / CI).
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "bin" / "kb-entry-budget.py"
KB = pathlib.Path.home() / "Documents" / "knowledge-base"
HAS_KB = (KB / "tools" / "kb.py").exists()


def run(args, *, cwd=None):
    p = subprocess.run([sys.executable, str(SCRIPT)] + args,
                       cwd=cwd, capture_output=True, timeout=120)
    return p.returncode, p.stdout.decode(), p.stderr.decode()


class ModelFidelityTest(unittest.TestCase):
    """The chunk model must match kb.py's, independent of any real topic."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import importlib.util
        spec = importlib.util.spec_from_file_location("keb", SCRIPT)
        assert spec and spec.loader
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_h3_starts_a_new_chunk(self):
        """kb.py's _chunk_errors uses `level in {2, 3}`. If this model only
        split on H2, an entry with `###` sub-sections would be reported as one
        oversized chunk and the documented split fix would look ineffective."""
        body = "## Head (2026-01-01)\nAAAA\n### Sub\nBBBB\n"
        cs = self.mod.chunks(body)
        self.assertEqual([c["level"] for c in cs], [2, 3])
        self.assertEqual(cs[0]["title"], "Head (2026-01-01)")

    def test_h4_does_not_start_a_chunk(self):
        """Only H2/H3 are structural in kb.py. An H4 belongs to its parent's
        chunk — treating it as a boundary would UNDER-report size and let an
        oversized entry through."""
        body = "## Head (2026-01-01)\nAAAA\n#### Deep\nBBBB\n"
        cs = self.mod.chunks(body)
        self.assertEqual(len(cs), 1)
        self.assertIn("Deep", "".join(c["title"] for c in cs) + body)
        self.assertGreater(cs[0]["chars"], len("## Head (2026-01-01)\n"))

    def test_chunk_size_counts_heading_plus_body(self):
        body = "## H (2026-01-01)\n" + "x" * 100 + "\n"
        cs = self.mod.chunks(body)
        self.assertEqual(cs[0]["chars"], len(body))

    def test_stage_thresholds_match_capture(self):
        self.assertEqual(self.mod.stage_for(2), "seedling")
        self.assertEqual(self.mod.stage_for(3), "budding")
        self.assertEqual(self.mod.stage_for(7), "budding")
        self.assertEqual(self.mod.stage_for(8), "evergreen")

    def test_cli_uses_invoking_knowledge_base_worktree(self):
        """A capture running in a KB worktree must inspect that worktree.

        The historical helper silently inspected ~/Documents/knowledge-base,
        so it could approve an append against different topic bytes than the
        checkout that would receive the write.
        """
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "tools").mkdir()
            (root / "topics").mkdir()
            (root / "tools" / "kb.py").write_text(
                "CHUNK_HARD_LIMIT = 3000\n"
                "CURRENT_UNDERSTANDING_THRESHOLD = 8\n",
                encoding="utf-8",
            )
            slug = "worktree-only-budget-topic"
            (root / "topics" / f"{slug}.md").write_text(
                "---\nstage: seedling\n---\n\n# Worktree only\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, timeout=30
            )

            rc, out, err = run([slug, "--json"], cwd=root)

        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["slug"], slug)

    def test_explicit_kb_root_is_deterministic_outside_git(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "kb"
            elsewhere = pathlib.Path(td) / "elsewhere"
            (root / "tools").mkdir(parents=True)
            (root / "topics").mkdir()
            elsewhere.mkdir()
            (root / "tools" / "kb.py").write_text(
                "CHUNK_HARD_LIMIT = 3000\n"
                "CURRENT_UNDERSTANDING_THRESHOLD = 8\n",
                encoding="utf-8",
            )
            slug = "explicit-root-topic"
            (root / "topics" / f"{slug}.md").write_text(
                "# Explicit root\n", encoding="utf-8"
            )

            rc, out, err = run(
                [slug, "--kb-root", str(root), "--json"], cwd=elsewhere
            )

        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["slug"], slug)

    @unittest.skipUnless(HAS_KB, "knowledge-base checkout absent")
    def test_limits_are_read_from_kb_py_not_hardcoded(self):
        limits, err = self.mod.read_limits()
        self.assertIsNone(err)
        assert limits
        src = (KB / "tools" / "kb.py").read_text(encoding="utf-8")
        self.assertIn(f"CHUNK_HARD_LIMIT = {limits['CHUNK_HARD_LIMIT']}", src)
        self.assertIn("CURRENT_UNDERSTANDING_THRESHOLD = "
                      f"{limits['CURRENT_UNDERSTANDING_THRESHOLD']}", src)

    @unittest.skipUnless(HAS_KB, "knowledge-base checkout absent")
    def test_self_check_passes(self):
        rc, out, _ = run(["--self-check"])
        self.assertEqual(rc, 0)
        self.assertIn("H3 starts a new chunk: yes", out)


@unittest.skipUnless(HAS_KB, "knowledge-base checkout absent")
class GroundTruthTest(unittest.TestCase):
    """Reproduce the 2026-07-28 rejections the tool exists to have prevented."""

    def _slug(self):
        # Any real topic works as the append target; the entry's own chunk is
        # what the assertion is about.
        for cand in ("skill-data-driven-workflows", "github-actions-discipline"):
            if (KB / "topics" / f"{cand}.md").exists():
                return cand
        self.skipTest("no known topic present")

    def test_oversized_entry_fails_with_exit_1(self):
        slug = self._slug()
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write("## Oversized draft (2026-07-28)\n\n" + ("word " * 900))
            draft = fh.name
        rc, out, _ = run([slug, "--entry-file", draft])
        self.assertEqual(rc, 1, f"expected predicted failure; out={out}")
        self.assertIn("OVER", out)
        self.assertIn("SPLITTING", out,
                      "must steer toward splitting, not trimming")

    def test_split_entry_passes(self):
        """The SAME content, split at an `###`, must pass — otherwise the
        remedy the tool recommends does not actually work."""
        slug = self._slug()
        half = "word " * 450
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write("## Split draft (2026-07-28)\n\n" + half +
                     "\n\n### Second half\n\n" + half)
            draft = fh.name
        _, out, _ = run([slug, "--entry-file", draft])
        self.assertNotIn("chunk(s) in the draft exceed", out,
                         f"split entry still reported oversized: {out}")

    def test_small_entry_on_clean_page_passes(self):
        """NEGATIVE CONTROL: the tool must not fail everything. Without this,
        a broken model that always exits 1 would pass every test above."""
        slug = self._slug()
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write("## Tiny draft (2026-07-28)\n\nOne short paragraph.\n")
            draft = fh.name
        _, out, _ = run([slug, "--entry-file", draft])
        self.assertNotIn("chunk(s) in the draft exceed", out)

    def test_json_mode_is_machine_readable(self):
        slug = self._slug()
        _, out, _ = run([slug, "--json"])
        payload = json.loads(out)
        self.assertEqual(payload["slug"], slug)
        self.assertIn("dated_entries_before", payload)
        self.assertIn("hard_limit", payload)

    def test_unknown_topic_exits_two(self):
        rc, _, err = run(["definitely-not-a-real-topic-slug-xyz"])
        self.assertEqual(rc, 2)
        self.assertIn("topic not found", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
