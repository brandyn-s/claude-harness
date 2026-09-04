#!/usr/bin/env python3
r"""Tests for hooks/zsh-dialect-guard.py.

BRANCH COVERAGE IS THE POINT (spec item 4, verify-effectiveness's N-branch GUARD).
The guard sorts input into three states — option-value / find-predicate / none —
and every test below asserts WHICH branch fired, not merely that the hook exited
0. A control that always takes the same path still exits 0, so the branch nobody
exercises is the one that rots, silently, while the others keep the suite green.

Also exercises the ADVISORY contract end-to-end through main() over a real pipe,
because the emit path (json on stdout, exit 0) is what the harness consumes and it
is not reachable from check_unquoted_glob() alone.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOOK = Path(__file__).resolve().parent.parent / "zsh-dialect-guard.py"
MANIFEST = HOOK.parent / "manifests" / "zsh-dialect-guard.yaml"
WORD_SPLIT_SPEC = HOOK.parent / "staged" / "zsh-word-splitting-guard.spec.md"
GLOB_SPEC = HOOK.parent / "staged" / "bash-glob-metachar-guard.spec.md"
# Both specs above were DELETED 2026-08-27 once `bin/staged-spec-staleness.py`
# confirmed their fixes had shipped into this hook. Their install provenance moved
# into that tool's MARKERS map, which is a better home: it is machine-checked and
# rerunnable, where a spec file recording its own installation is inert prose that
# reads as pending work. The paths stay defined so the test below can assert they
# are ABSENT.
STALENESS = HOOK.parent.parent / "bin" / "staged-spec-staleness.py"
REPLAY = HOOK.parent / "test-hooks" / "replay_bash_glob_metachar.py"


def _load():
    """Import a hyphenated module file by path (no package, hyphen in name)."""
    spec = importlib.util.spec_from_file_location("zsh_dialect_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load()


class BranchCoverage(unittest.TestCase):
    """Every branch, asserted BY NAME."""

    def test_option_value_branch(self):
        fired, tok, branch = G.check_unquoted_glob(
            'grep -rn "x" hooks/ --include=*.py'
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "option-value")
        self.assertEqual(tok, "--include=*.py")

    def test_find_predicate_branch(self):
        fired, tok, branch = G.check_unquoted_glob("find . -name *.md")
        self.assertTrue(fired)
        self.assertEqual(branch, "find-predicate")
        self.assertEqual(tok, "-name *.md")

    def test_set_dashdash_word_split_branch(self):
        fired, tok, branch = G.check_unquoted_glob("set -- $spec")
        self.assertTrue(fired)
        self.assertEqual(branch, "set-dashdash")
        self.assertEqual(tok, "$spec")

    def test_flag_packing_word_split_branch(self):
        fired, tok, branch = G.check_unquoted_glob(
            'R="--region us-gov-west-1"; aws logs describe-log-groups $R'
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "flag-packing")
        self.assertEqual(tok, "$R")

    def test_none_branch(self):
        fired, tok, branch = G.check_unquoted_glob("ls -la")
        self.assertFalse(fired)
        self.assertEqual(branch, "none")
        self.assertEqual(tok, "")

    def test_option_value_wins_when_both_present(self):
        """Ordering is deliberate — assert it so a reorder is a test failure."""
        fired, _, branch = G.check_unquoted_glob(
            "find . -name *.md ; grep -rn x . --include=*.py"
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "option-value")


class KnownNegatives(unittest.TestCase):
    """Shapes that MUST NOT fire. Each one measured against the real corpus."""

    def test_quoted_option_value(self):
        self.assertFalse(
            G.check_unquoted_glob("grep -rn 'x' hooks/ --include='*.py'")[0]
        )

    def test_quoted_find_predicate(self):
        self.assertFalse(G.check_unquoted_glob("find . -name '*.md'")[0])

    def test_intended_shell_expansion(self):
        """`ls *.py` is the CORRECT idiom when a match is expected."""
        self.assertFalse(G.check_unquoted_glob("ls *.py")[0])

    def test_trailing_path_glob(self):
        self.assertFalse(G.check_unquoted_glob("cat logs/*.txt")[0])

    def test_prose_in_echo_is_not_a_find_predicate(self):
        """The REAL false positive the historical replay found.

        Without the `(?<![\\w-])` left boundary, `class-name substitution?`
        matches as a find predicate. This corpus writes echo banners constantly,
        so the true fire rate would be far above the measured 0.13%.
        """
        self.assertFalse(
            G.check_unquoted_glob(
                'echo "=== is the token migration purely class-name substitution? ==="'
            )[0]
        )

    def test_heredoc_body_is_data_not_a_command(self):
        """The heredoc body is a FILE BEING WRITTEN, not a command being run.

        The globs below are deliberately UNQUOTED inside the body. An earlier
        version used `x = '--include=*.py'`, where the single-quote strip covered
        it independently — so mutation-testing found that removing the heredoc
        strip was MISSED. Same overlapping-defence problem as the left-boundary
        test above: a fixture that two mechanisms both cover cannot tell you
        whether either one works.
        """
        for cmd in (
            "cat > f.sh <<'SH'\ngrep -rn x . --include=*.py\nSH",
            "cat > f.sh <<'SH'\nfind . -name *.md\nSH",
            "python3 - <<'PY'\nx = '--include=*.py'\nPY",
        ):
            with self.subTest(cmd=cmd.splitlines()[0]):
                fired, tok, branch = G.check_unquoted_glob(cmd)
                self.assertFalse(
                    fired,
                    f"a glob in a heredoc body is data being written, not an "
                    f"argument being expanded (matched {tok!r} via {branch})",
                )

    def test_a_flag_outside_a_heredoc_still_fires(self):
        """Negative control: the heredoc strip must not swallow the real command."""
        fired, tok, branch = G.check_unquoted_glob(
            "grep -rn x . --include=*.py <<'EOF'\nsome data\nEOF"
        )
        self.assertTrue(fired, "the flag is OUTSIDE the body and must be caught")
        self.assertEqual(branch, "option-value")
        self.assertEqual(tok, "--include=*.py")

    def test_the_pattern_inside_a_quoted_string_never_fires(self):
        """The property that actually protects real commands.

        SCOPE, stated honestly: an earlier version of this test scanned the
        guard's OWN SOURCE and failed, because the `--include=*.py` example lives
        in the module DOCSTRING and the filter only stripped `#` lines. That was
        a test-fixture artifact, not a live defect — the guard scans COMMANDS, and
        never its own file. Testing the self-scan would pin a behaviour nothing
        depends on (and tempt a "fix" that strips triple-quoted blocks out of
        commands, which would be wrong: a heredoc-adjacent quoted glob in a real
        command IS worth stripping, a Python docstring is not a thing commands
        have).

        What DOES matter is that a glob appearing inside a quoted string in a real
        command is treated as prose. That is the echo-banner case the historical
        replay caught, and it is asserted directly here.
        """
        for cmd in (
            'echo "use --include=*.py to scope it"',
            "echo 'find . -name *.md is the wrong way'",
            'printf "%s\\n" "--exclude-dir=*.git"',
        ):
            with self.subTest(cmd=cmd):
                fired, tok, branch = G.check_unquoted_glob(cmd)
                self.assertFalse(
                    fired,
                    f"a glob inside a quoted string is prose, not an argument "
                    f"(matched {tok!r} via {branch})",
                )

    def test_flag_packing_example_inside_quoted_prose_does_not_fire(self):
        fired, tok, branch = G.check_unquoted_glob(
            'echo "try R=\'-v --color\'; cmd $R instead"'
        )
        self.assertFalse(
            fired,
            f"a packed-flag example inside quoted prose is not executed "
            f"(matched {tok!r} via {branch})",
        )

    def test_hyphenated_word_is_not_a_find_predicate(self):
        """Isolates the LEFT BOUNDARY `(?<![\\w-])`, which nothing else covers.

        Added because mutation-testing found removing the boundary was MISSED by
        every other test here: the quoted-string strip independently covers the
        echo-banner case, so the boundary LOOKED redundant while actually being
        the only defence for an UNQUOTED hyphenated word. Two overlapping
        defences, and a test suite that exercised only one of them.

        The cases below are deliberately UNQUOTED so the strip cannot mask the
        boundary — `class-name`, `file-path`, `by-name` all end in a token the
        predicate pattern would otherwise match.
        """
        for cmd in (
            "cmd --flag class-name substitution?",
            "run task by-name *.md",
            "tool --mode file-path glob?",
        ):
            with self.subTest(cmd=cmd):
                fired, tok, branch = G.check_unquoted_glob(cmd)
                self.assertFalse(
                    fired,
                    f"a hyphenated word ending in name/path is not a find "
                    f"predicate (matched {tok!r} via {branch})",
                )

    def test_a_genuine_find_predicate_after_a_hyphenated_word_still_fires(self):
        """Negative control: the boundary must not blind the real predicate."""
        fired, tok, branch = G.check_unquoted_glob(
            "echo class-name; find . -name *.md"
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "find-predicate")
        self.assertEqual(tok, "-name *.md")

    def test_a_real_flag_still_fires_when_a_quoted_decoy_is_present(self):
        """Negative control for the strip: stripping must not blind the check.

        Without this, `_strip_noise` could be over-broad (e.g. dropping the whole
        line) and every test above would still pass — the strip would silently
        disable the guard rather than scope it.
        """
        fired, tok, branch = G.check_unquoted_glob(
            'echo "safe --include=*.md" && grep -rn x . --include=*.py'
        )
        self.assertTrue(fired, "the UNQUOTED flag must still be caught")
        self.assertEqual(branch, "option-value")
        self.assertEqual(tok, "--include=*.py", "must match the unquoted one, not the decoy")


class AdvisoryContract(unittest.TestCase):
    """main() must WARN and exit 0 — never block. Exercised over a real pipe."""

    def _run(self, payload):
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            check=False,  # the EXIT CODE is the assertion — never raise on it
        )

    def test_fires_advisory_and_exits_zero(self):
        r = self._run(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'grep -rn "x" . --include=*.py'},
            }
        )
        self.assertEqual(r.returncode, 0, "an advisory guard must never block")
        out = json.loads(r.stdout.decode())
        self.assertIn("hookSpecificOutput", out)
        self.assertNotIn(
            "permissionDecision",
            out,
            "a permissionDecision would make this a GATE, not an advisory",
        )
        msg = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("--include=*.py", msg)
        self.assertIn("--include='*.py'", msg, "must show the QUOTED fix")
        self.assertIn("PHANTOM 0-HIT", msg)

    def test_silent_on_a_clean_command(self):
        r = self._run({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.decode().strip(), "", "must be silent when clean")

    def test_ignores_non_bash_tools(self):
        r = self._run({"tool_name": "Read", "tool_input": {"file_path": "*.py"}})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.decode().strip(), "")

    def test_fails_open_on_malformed_input(self):
        r = subprocess.run(
            [sys.executable, str(HOOK)],
            input=b"not json",
            capture_output=True,
            check=False,  # asserting it exits 0; check=True would mask that
        )
        self.assertEqual(
            r.returncode, 0, "must fail OPEN — a crash would block every Bash call"
        )

    def test_find_predicate_advisory_shows_quoted_fix(self):
        r = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "find . -name *.md"}}
        )
        self.assertEqual(r.returncode, 0)
        msg = json.loads(r.stdout.decode())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("-name '*.md'", msg)

    def test_word_splitting_advisory_explains_wrong_argv_and_stays_nonblocking(self):
        r = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "set -- $spec"}}
        )
        self.assertEqual(r.returncode, 0, "the word-splitting check is advisory")
        out = json.loads(r.stdout.decode())
        self.assertNotIn("permissionDecision", out)
        msg = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("zsh does not word-split $spec", msg)
        self.assertIn("whole string", msg)
        self.assertIn("array", msg)

    def test_for_in_advisory_uses_the_word_split_message_not_the_glob_one(self):
        """Pins the ADVISORY ROUTING for the new branch.

        Without this, dropping "for-in-split" from advise()'s word-split set is
        invisible: the branch still fires, so every detection test stays green
        while the user is told the command will ABORT (it will not -- it runs
        once with the wrong argv). Mutation M5 reported MISSED until this
        existed.
        """
        fired, token, branch = G.check_unquoted_glob("for r in $repos; do :; done")
        self.assertTrue(fired)
        self.assertEqual(branch, "for-in-split")
        msg = G.advise(token, branch)["advice"]
        self.assertIn("does not word-split $repos", msg)
        self.assertIn("${=repos}", msg)
        self.assertNotIn("will ABORT", msg)
        self.assertNotIn("PHANTOM 0-HIT", msg)

    def test_flag_packing_advisory_does_not_echo_assigned_value(self):
        r = self._run(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        'FLAGS="--token sensitive-example-value"; command $FLAGS'
                    )
                },
            }
        )
        self.assertEqual(r.returncode, 0)
        msg = json.loads(r.stdout.decode())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("$FLAGS", msg)
        self.assertNotIn("sensitive-example-value", msg)


class WordSplittingCoverage(unittest.TestCase):
    """Narrow positives, deliberate exclusions, and branch mutation controls."""

    def test_known_positive_forms(self):
        cases = (
            ("set -- ${spec}", "set-dashdash", "${spec}"),
            ("FLAGS='-v --color'; command $FLAGS", "flag-packing", "$FLAGS"),
            ("for r in $repos; do echo $r; done", "for-in-split", "$repos"),
            ("for f in ${files}; do :; done", "for-in-split", "${files}"),
        )
        for command, expected_branch, expected_token in cases:
            with self.subTest(command=command):
                fired, token, branch = G.check_unquoted_glob(command)
                self.assertTrue(fired)
                self.assertEqual(branch, expected_branch)
                self.assertEqual(token, expected_token)

    def test_known_negative_forms(self):
        commands = (
            "echo $HOME",
            "cd $DIR",
            'cat "$FILE"',
            'args=(x y); set -- "${args[@]}"',
            "set -- ${=spec}",
            "set -- \"$spec\"",
            # `for item in $ITEMS` moved from here to test_known_positive_forms
            # on 2026-08-16 -- v1 scoped it out, the staged spec required it, and
            # 9/9 corpus fires proved genuine at 0.132%. These four remain
            # negative, each isolating ONE mechanism of the new branch:
            "for f in $arr[@]; do :; done",      # right boundary
            "for x in ${=list}; do :; done",     # brace-content class
            # `endfor r in $repos`, NOT `endfor in $x`: the latter cannot reach
            # the boundary at all (after `for ` the name group consumes `in`, then
            # a second literal `in` is required and absent), so it stayed quiet
            # with the boundary REMOVED and reported the mutation MISSED --
            # tdd-mutation-testing item 18, an unreachable fixture.
            "endfor r in $repos",                # left boundary
            "for i in $(seq 3); do :; done",     # command substitution
            "for f in *.py; do :; done",         # glob, not this class
            "command -- $FILES",
            'R="--region us-gov-west-1"; command "$R"',
            'R="--verbose"; command $R',
            'R="region us-gov-west-1"; command $R',
        )
        for command in commands:
            with self.subTest(command=command):
                fired, token, branch = G.check_unquoted_glob(command)
                self.assertFalse(
                    fired,
                    f"out-of-scope or correct zsh form matched {token!r} via {branch}",
                )

    def test_disabling_set_branch_does_not_hide_flag_packing_branch(self):
        with mock.patch.object(G, "_SET_DASHDASH", re.compile(r"(?!)")):
            self.assertFalse(G.check_unquoted_glob("set -- $spec")[0])
            fired, _, branch = G.check_unquoted_glob(
                'R="--region us-gov-west-1"; command $R'
            )
            self.assertTrue(fired)
            self.assertEqual(branch, "flag-packing")

    def test_disabling_for_in_branch_does_not_hide_set_branch(self):
        with mock.patch.object(G, "_FOR_IN_SPLIT", re.compile(r"(?!)")):
            self.assertFalse(
                G.check_unquoted_glob("for r in $repos; do :; done")[0]
            )
            fired, _, branch = G.check_unquoted_glob("set -- $spec")
            self.assertTrue(fired)
            self.assertEqual(branch, "set-dashdash")

    def test_disabling_set_branch_does_not_hide_for_in_branch(self):
        with mock.patch.object(G, "_SET_DASHDASH", re.compile(r"(?!)")):
            self.assertFalse(G.check_unquoted_glob("set -- $spec")[0])
            fired, _, branch = G.check_unquoted_glob(
                "for r in $repos; do :; done"
            )
            self.assertTrue(fired)
            self.assertEqual(branch, "for-in-split")

    def test_disabling_flag_packing_branch_does_not_hide_set_branch(self):
        with mock.patch.object(G, "_FLAG_PACKING_ASSIGN", re.compile(r"(?!)")):
            self.assertFalse(
                G.check_unquoted_glob(
                    'R="--region us-gov-west-1"; command $R'
                )[0]
            )
            fired, _, branch = G.check_unquoted_glob("set -- $spec")
            self.assertTrue(fired)
            self.assertEqual(branch, "set-dashdash")


class ManifestContract(unittest.TestCase):
    def test_manifest_declares_every_advisory_word_splitting_branch(self):
        text = MANIFEST.read_text(encoding="utf-8")
        self.assertIn("action_type: advisory", text)
        self.assertIn("set-dashdash branch", text)
        self.assertIn("flag-packing branch", text)
        self.assertIn("for-in-split branch", text)
        self.assertIn("combined fire rate", text)

    def test_hook_source_describes_current_advisory_scope_without_timer(self):
        text = HOOK.read_text(encoding="utf-8")
        self.assertIn("word-splitting", text)
        self.assertNotIn("~30 days", text)

    def test_shipped_spec_provenance_moved_to_the_staleness_registry(self):
        """Replaces test_staged_specs_record_install_and_supersession_without_timer.

        That test read the two staged specs and asserted they recorded their own
        install. Both were DELETED 2026-08-27 after `bin/staged-spec-staleness.py`
        confirmed against this hook's SOURCE that their fixes had shipped — a spec
        that records its own installation is inert prose sitting in a work queue,
        indistinguishable from pending work to the next session that reads it.

        The assertion is stronger now, not weaker: it pins that the provenance is
        recorded in the machine-checked registry AND that the specs are really gone,
        so neither can be silently re-derived.
        """
        registry = STALENESS.read_text(encoding="utf-8")
        for spec_name, marker, when in (
            ("bash-glob-metachar-guard.spec.md", "_OPT_EQ", "2026-08-02"),
            ("zsh-word-splitting-guard.spec.md", "_FOR_IN_SPLIT", "2026-08-08"),
        ):
            self.assertIn(spec_name, registry, "provenance row missing")
            self.assertIn(marker, registry, "shipped-marker missing")
            self.assertIn(when, registry, "install date missing")
            # The marker must actually be present in the hook, or the registry would
            # report the spec as still-live and the row would be a lie.
            self.assertIn(marker, HOOK.read_text(encoding="utf-8"))

        self.assertFalse(WORD_SPLIT_SPEC.exists(), "shipped spec should be deleted")
        self.assertFalse(GLOB_SPEC.exists(), "shipped spec should be deleted")
        # The no-escalation-timer property the original test protected.
        self.assertNotIn("30 days", registry)


class UrlQueryBranch(unittest.TestCase):
    """The `?key=` branch (added 2026-08-02).

    A URL query string is the highest-frequency NON-search instance of the
    metachar abort, and the two original branches (option-value, find-predicate)
    are an allowlist that cannot match it. Measured before the fix: the real
    failing command produced NO advisory while `--include=*.py` warned.
    """

    def test_unquoted_query_string_fires(self):
        fired, tok, branch = G.check_unquoted_glob(
            "gh api repos/o/r/contents/pyproject.toml?ref=v0.11.0 --jq '.content'"
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "url-query")
        self.assertEqual(tok, "repos/o/r/contents/pyproject.toml?ref=v0.11.0")

    def test_quoted_query_string_does_not_fire(self):
        self.assertFalse(
            G.check_unquoted_glob('gh api "repos/o/r/x.toml?ref=v0.11.0"')[0]
        )

    def test_full_url_with_query_fires(self):
        fired, _, branch = G.check_unquoted_glob(
            "curl -s https://api.example.com/v1/items?pageSize=10"
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "url-query")

    def test_no_query_string_does_not_fire(self):
        # A path with slashes but no `?key=` carries no metachar at all.
        self.assertFalse(G.check_unquoted_glob("aws s3 ls s3://bucket/prefix/")[0])

    def test_env_assignment_does_not_fire(self):
        # `KEY=value` has an `=` but no `?` — the branch requires the metachar.
        self.assertFalse(
            G.check_unquoted_glob("AWS_PROFILE=x aws sts get-caller-identity")[0]
        )

    def test_fix_suggestion_quotes_the_WHOLE_token(self):
        """The load-bearing assertion: partial quoting does not fix a query string.

        `advise()`'s default splits on the first `=` and quotes only the value —
        correct for `--include=*.py`, WRONG here, because `?` would remain in the
        unquoted prefix and zsh globs the word anyway. A suggestion that does not
        fix the problem is worse than none: it is followed.
        """
        tok = "repos/o/r/x.toml?ref=v0.11.0"
        msg = G.advise(tok, "url-query")["advice"]
        self.assertIn(f'"{tok}"', msg)
        self.assertNotIn("?ref='v0.11.0'", msg)

    def test_unterminated_quote_is_suppressed_by_the_token_boundary(self):
        """Isolates `(?:^|\\s)` — the ONLY fixture where the boundary changes the verdict.

        An unterminated quote survives `_strip_noise` (which needs a closing
        quote), so without the token-boundary anchor the engine slides PAST the
        opening quote and matches mid-token, defeating the `(?!['\"])` lookahead.
        Suppressing is correct: an unterminated quote is a zsh PARSE/continuation
        condition, not a glob abort, so a globbing advisory would be a confidently
        wrong diagnosis of a real but different problem.

        Added 2026-08-02 after this exact mutation came back MISSED — a missing
        fixture, not dead code (tdd-mutation-testing item 18).
        """
        self.assertFalse(G.check_unquoted_glob('curl "https://x/y?a=b')[0])
        self.assertFalse(G.check_unquoted_glob("curl 'https://x/y?a=b")[0])

    def test_other_branches_keep_their_own_fix_shape(self):
        # Regression guard: the branch param must not change existing advice.
        msg = G.advise("--include=*.py", "option-value")["advice"]
        self.assertIn("--include='*.py'", msg)

    def test_replay_runs_fixtures_without_private_transcripts(self):
        """The committed replay remains reproducible in a clean CI-like home."""
        with tempfile.TemporaryDirectory() as empty_home:
            env = os.environ.copy()
            env["HOME"] = empty_home
            result = subprocess.run(
                [sys.executable, str(REPLAY)],
                cwd=HOOK.parents[1],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Bash commands  : 0", result.stdout)
        self.assertIn("fixtures: ALL PASS", result.stdout)
        self.assertIn("GATE PASSED (rate=0.00%", result.stdout)


class ColonModifierBranch(unittest.TestCase):
    r"""The `colon-modifier` branch (added 2026-08-27).

    Merges TWO staged specs written 15 days apart for the same hazard:
    `zsh-unbraced-colon-modifier.spec.md` (2026-08-12) and
    `zsh-colon-modifier-guard.spec.md` (2026-08-27, via #2158). Neither session knew
    the other had staged it.

    EVERY expectation below was MEASURED in real zsh 5.9 under `emulate -L zsh`,
    not taken from either spec — both spec letter sets were WRONG. Each listed
    characters that measure INERT (`p x g`, and `f F w W` in the older one), so
    either implemented verbatim would fire on `"$IMG:prod"`, a safe and extremely
    common docker tag. The older list also missed `Q`.

    Measured character classes (every ASCII letter plus `& # % ? - / . _`):
        corrupt silently : a c e h l q r t u A P Q &
        abort loudly     : s   ("bad substitution")
        inert            : the other 46
    """

    # ---- positives: each confirmed to corrupt or abort in real zsh ----------

    def test_docker_tag_shape_fires(self):
        """The motivating incident. Measured: yields `registry/mcp/connectatest`.

        `:l` lowercases the value AND is consumed, so the `l` of `latest` is eaten
        and the tag is destroyed outright — the image reference ends up with no tag.
        """
        fired, tok, branch = G.check_unquoted_glob('docker build -t "$ECR:latest" .')
        self.assertTrue(fired)
        self.assertEqual(branch, "colon-modifier")
        self.assertEqual(tok, "$ECR:l")

    def test_aborting_modifier_fires(self):
        """`:s` with no /pattern/ aborts: measured `zsh: bad substitution`."""
        fired, tok, branch = G.check_unquoted_glob('git log "$br:squashed"')
        self.assertTrue(fired)
        self.assertEqual(branch, "colon-modifier")
        self.assertEqual(tok, "$br:s")

    def test_git_rev_path_syntax_fires(self):
        """git's own `<rev>:<path>` collides with the modifier syntax.

        3 of the 4 real corpus fires were this shape, not docker tags. Measured:
        `$sha:rules/x.md` becomes `<sha>ules/x.md` — and the original commands
        silenced it with `2>/dev/null`.
        """
        fired, tok, branch = G.check_unquoted_glob(
            "git cat-file -s $(git rev-parse $sha:rules/git-hygiene.md) 2>/dev/null"
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "colon-modifier")
        self.assertEqual(tok, "$sha:r")

    def test_git_refspec_syntax_fires(self):
        """`<src>:<dst>` too. Measured: collapses into ONE mangled ref."""
        fired, tok, branch = G.check_unquoted_glob(
            'git fetch origin "refs/heads/$HEAD_REF:refs/remotes/origin/$HEAD_REF"'
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "colon-modifier")
        self.assertEqual(tok, "$HEAD_REF:r")

    def test_subscripted_expansion_fires(self):
        fired, _tok, branch = G.check_unquoted_glob('echo "$arr[1]:t"')
        self.assertTrue(fired)
        self.assertEqual(branch, "colon-modifier")

    def test_unquoted_form_also_fires(self):
        """Not only inside double quotes — an unquoted expansion expands too."""
        fired, _tok, branch = G.check_unquoted_glob("echo $BR:test")
        self.assertTrue(fired)
        self.assertEqual(branch, "colon-modifier")

    # ---- negatives: each confirmed INERT in real zsh ------------------------

    def test_braced_form_never_fires(self):
        """`${ECR}:latest` is the CORRECT form and the advisory's own suggested fix.

        If this ever fires, the guard is telling people to write something it then
        complains about.
        """
        for cmd in ('docker build -t "${ECR}:latest" .', 'echo "${f}:h"',
                    'echo "${br:h}"'):
            self.assertFalse(G.check_unquoted_glob(cmd)[0], cmd)

    def test_inert_characters_do_not_fire(self):
        """The measured-inert set. `prod` is the load-bearing case.

        BOTH staged specs included `p`, so both would have fired here — on a docker
        tag that is completely safe and very widely used.
        """
        for cmd, why in (
            ('docker tag x "$IMG:prod"', "p is inert — both specs got this wrong"),
            ('docker tag x "$IMG:dev"', "d inert"),
            ('docker tag x "$IMG:main"', "m inert"),
            ('docker tag x "$IMG:v2"', "v inert"),
            ('curl "$host:8080/x"', "digits are never modifiers"),
            ('echo "$dir:/opt"', "/ inert"),
            ('echo "$x:-default"', ":- is a default value, not a modifier"),
        ):
            self.assertFalse(G.check_unquoted_glob(cmd)[0], f"{cmd} ({why})")

    def test_single_quoted_and_heredoc_bodies_do_not_fire(self):
        for cmd in ("echo '$ECR:latest'",
                    "python3 - <<'PY'\nx = \"$ECR:latest\"\nPY"):
            self.assertFalse(G.check_unquoted_glob(cmd)[0], cmd)

    def test_escaped_dollar_does_not_fire(self):
        r"""A BACKSLASH-ESCAPED `\$` is never expanded by zsh.

        This was a real FALSE POSITIVE found by the corpus replay, not by reasoning:
        1 of the first 5 fires was
        `echo "=== tag it :latest (BRACED -- \$ECR:latest would trigger the zsh :l
        modifier) ==="` — prose warning about this very hazard, written by an earlier
        session that had just been bitten by it. A guard that fires on correct
        writing ABOUT itself is `tdd-quality` item 19's self-reference class, and the
        fire rate alone (0.044%, far under any gate) would not have revealed it.
        """
        cmd = 'echo "BRACED - \\$ECR:latest would trigger the zsh :l modifier"'
        self.assertFalse(G.check_unquoted_glob(cmd)[0], cmd)

    def test_pid_expansion_does_not_fire(self):
        """`$$foo` is the PID followed by a literal word, not an expansion of foo."""
        self.assertFalse(G.check_unquoted_glob('echo "$$foo:t"')[0])

    # ---- the strip asymmetry, which is the branch's whole design -------------

    def test_branch_uses_a_strip_that_keeps_double_quoted_spans(self):
        """DOUBLE-quoted spans must survive for this branch, unlike the glob ones.

        `_strip_noise` blanks `"..."`, which is right for a glob (inert inside
        quotes) and exactly wrong here (a parameter expansion inside double quotes
        DOES expand). Every measured instance of this hazard lives inside double
        quotes, so sharing `_strip_noise` would make the branch structurally blind
        to the defect it exists to catch — while an unquoted fixture kept passing.

        Asserted at the two helpers directly, because the end-to-end behaviour of a
        correct implementation and a `_strip_noise`-sharing one differs ONLY on
        double-quoted input, which is easy to omit from a fixture set.
        """
        cmd = 'docker build -t "$ECR:latest" .'
        self.assertNotIn("$ECR:l", G._strip_noise(cmd))
        self.assertIn("$ECR:l", G._strip_unexpanded(cmd))
        # ...and single quotes / heredocs are still dropped by the new strip.
        self.assertNotIn("$ECR:l", G._strip_unexpanded("echo '$ECR:latest'"))

    def test_hazard_character_set_is_exactly_the_measured_one(self):
        """Pin the measured set so a future edit toward either spec's list fails.

        Not a style assertion: adding an inert character creates a false-positive
        class (`p` -> `"$IMG:prod"`), and dropping a live one creates a blind spot.
        """
        self.assertEqual(set(G._COLON_HAZARD_CHARS), set("acehlqrtuAPQ&s"))
        for inert in "bdfgijkmnopvwxyz":
            self.assertNotIn(inert, G._COLON_HAZARD_CHARS,
                             f"{inert!r} measured INERT in zsh; including it fires "
                             f"on safe input")

    # ---- the advisory contract ---------------------------------------------

    def test_advisory_names_the_variable_the_letter_and_the_braced_fix(self):
        fired, tok, branch = G.check_unquoted_glob('docker build -t "$ECR:latest" .')
        self.assertTrue(fired)
        msg = G.advise(tok, branch)["advice"]
        self.assertIn("$ECR", msg)
        self.assertIn("lowercased", msg)
        self.assertIn("${ECR}", msg, "must show the braced fix")
        self.assertIn("${ECR:l}", msg, "must show the explicit-intent form")

    def test_aborting_modifier_message_does_not_claim_silence(self):
        """`:s` fails LOUDLY; saying "no error is raised" would be simply false.

        A guard whose own message misdescribes the failure mode teaches the wrong
        lesson about what to look for.
        """
        fired, tok, branch = G.check_unquoted_glob('git log "$br:squashed"')
        self.assertTrue(fired)
        msg = G.advise(tok, branch)["advice"]
        self.assertIn("bad substitution", msg)
        self.assertNotIn("No error is raised", msg)

    def test_silent_modifier_message_does_claim_silence(self):
        """The known-negative for the test above: the branches must differ.

        Without this, a mutation collapsing both variants into the abort text would
        pass — the assertion above only checks one direction.
        """
        fired, tok, branch = G.check_unquoted_glob('docker build -t "$ECR:latest" .')
        self.assertTrue(fired)
        msg = G.advise(tok, branch)["advice"]
        self.assertIn("No error is raised", msg)
        self.assertNotIn("bad substitution", msg)

    def test_git_note_appears_only_for_rev_and_refspec_modifiers(self):
        """Scoped so the note lands where it helps instead of padding every message."""
        _f, tok, br = G.check_unquoted_glob("git rev-parse $sha:rules/x.md")
        self.assertIn("refspec", G.advise(tok, br)["advice"])
        _f2, tok2, br2 = G.check_unquoted_glob('docker build -t "$ECR:latest" .')
        self.assertNotIn("refspec", G.advise(tok2, br2)["advice"])

    def test_advisory_exits_zero_end_to_end(self):
        """The branch must never block — the guard's whole contract."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": 'docker build -t "$ECR:latest" .'},
        })
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=payload,
            capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = json.loads(result.stdout)
        self.assertIn("hookSpecificOutput", emitted)
        self.assertIn("$ECR", emitted["hookSpecificOutput"]["additionalContext"])

    def test_existing_branches_keep_precedence(self):
        """The colon branch is evaluated LAST, deliberately.

        A command carrying two hazards must still report the pre-existing branch, or
        this addition silently re-verdicts fixtures pinned by earlier work.
        """
        fired, _tok, branch = G.check_unquoted_glob(
            'grep -rn x hooks/ --include=*.py && echo "$ECR:latest"'
        )
        self.assertTrue(fired)
        self.assertEqual(branch, "option-value")

if __name__ == "__main__":
    unittest.main(verbosity=2)
