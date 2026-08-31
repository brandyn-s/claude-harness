"""Core types for the audit-skill oracle.

A Finding is a structured representation of an audit observation. A
Reproducer encapsulates the verifiable evidence that a finding is real:
a small, deterministic check that returns True iff the bug still
manifests. The four oracle layers all consume these types:

- Layer A (reverify): runs Reproducer.fires() against the live tree to
  drop stale findings before they become fix tasks.
- Layer B (consensus): aggregates N independent Findings, retains only
  the intersection.
- Layer C (golden corpus): compares observed findings against curated
  expected-findings.yaml entries to measure precision/recall.
- Layer D (fix-loop): runs Reproducer.fires() before AND after a
  proposed fix; a real fix flips fires() from True to False.

The Reproducer ABC has several concrete subclasses that cover the
patterns we observed in the May 2026 Phase 2 audit: grep (file
contains/lacks pattern), bash (command exits non-zero), python (snippet
raises), file_exists, file_missing. Reproducers that can't be expressed
in those terms are tagged ``manual`` and excluded from automated
verification — they must remain ``[unverified]`` until someone provides
a deterministic check.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _resolve_bash() -> str:
    """Return a path to a bash that understands POSIX shell + Windows paths.

    On Windows, ``shutil.which('bash')`` and Python's subprocess PATH search
    both prefer ``C:\\Windows\\System32\\bash.exe`` (the WSL launcher) over
    Git Bash. WSL bash hangs or fails on Windows-style paths like
    ``C:/Users/...`` because its filesystem root is the WSL distro, not
    the Windows drive. Reproducers that embed Windows paths therefore
    silently return rc=1 (or time out), and the oracle misclassifies
    every such finding as STALE.

    Fix: on Windows, search PATH with System32 entries filtered out so
    Git Bash wins. On POSIX, ``shutil.which('bash')`` is correct.
    """
    if sys.platform == "win32":
        filtered = os.pathsep.join(
            p for p in os.environ.get("PATH", "").split(os.pathsep)
            if "system32" not in p.lower() and "windowsapps" not in p.lower()
        )
        candidate = shutil.which("bash", path=filtered)
        if candidate:
            return candidate
        # Fall back to a known Git-for-Windows install location.
        for default in (
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files\Git\bin\bash.exe",
        ):
            if os.path.exists(default):
                return default
    return shutil.which("bash") or "bash"


_BASH = _resolve_bash()


def _reproducer_timeout() -> float:
    """Per-Reproducer subprocess timeout, in seconds.

    Default 30s preserves prior behavior. Override via the
    `AUDIT_SKILL_ORACLE_TIMEOUT` env var when a reproducer needs
    more (e.g. `wc -w` on a multi-thousand-line SKILL.md hit 30s
    on Windows during the 2026-05-25 reverify). Resolved per-call
    (not at import) so tests + ad-hoc runs can set the env var
    after the module loads.
    """
    raw = os.environ.get("AUDIT_SKILL_ORACLE_TIMEOUT", "")
    if not raw:
        return 30.0
    try:
        return float(raw)
    except ValueError:
        return 30.0


REPRODUCER_TYPES = (
    "grep",         # run a grep command; finding fires iff grep matches
    "grep_absent",  # finding fires iff grep does NOT match
    "bash",         # run a bash command; finding fires iff exit == expected_exit
                    # (expected_exit = the code that means "bug present"; default 0)
    "python",       # run a Python snippet; finding fires iff raises (or returns truthy)
    "file_exists",  # finding fires iff path exists (used for "phantom file" type bugs inverted)
    "file_missing", # finding fires iff path does NOT exist
    "transcript_pattern",  # run a measurement command emitting JSON; finding fires iff
                           # the measured rate meets a threshold (used by audit-rules)
    "manual",       # human-described; no automated check
)


# Predicates that "fire" regardless of repository content — the
# reward-hacking surface where a proposer pairs a real-sounding finding
# with a reproducer that always returns True (e.g. `grep -q .`). The
# specificity guard (oracle/specificity.py) and Layer A's breadth signal
# both consult this list. Matched against the reproducer's command after
# light normalization. See oracle/SPEC.md "Specificity guard".
VACUOUS_COMMAND_PATTERNS = (
    r"grep\s+-[A-Za-z]*q[A-Za-z]*\s+['\"]?\.['\"]?(\s|$)",       # grep -q .
    r"grep\s+-[A-Za-z]*q[A-Za-z]*\s+['\"]{2}",                   # grep -q ''  / -q ""
    r"grep\s+-[A-Za-z]*q[A-Za-z]*\s+['\"]?\.[*+]['\"]?(\s|$)",   # grep -qE .* / .+
    r"\btest\s+-[ef]\s+\.(\s|$)",                               # test -e .  / test -f .
    r"^\s*true\s*$",                                            # bash: true
    r"^\s*:\s*$",                                               # bash: :
)


@dataclasses.dataclass
class Reproducer:
    """Machine-checkable evidence for a finding.

    Fields:
      type: one of REPRODUCER_TYPES.
      command: bash command (type=grep/grep_absent/bash) or Python code
        (type=python).
      path: file path for file_exists / file_missing.
      expected_exit: for bash, the exit code that means "bug is present" —
        the finding fires iff the command's exit EQUALS this value
        (default 0: command succeeding indicates the bug). For grep,
        ignored (firing is controlled by the type alone).
      description: human-readable for manual type.
    """
    type: str
    command: str = ""
    path: str = ""
    expected_exit: int = 0
    description: str = ""
    # For file_exists / file_missing only: optionally constrain to a
    # specific path-type. Default `either` accepts both files and
    # directories (back-compat with pre-2026-05-26 reproducers).
    # Use `file` or `dir` to assert the path-type matches; the
    # reproducer fires only when the type is correct AND the
    # exists/missing condition holds.
    expect_type: str = "either"
    # For transcript_pattern only: the predicate is "command emits JSON;
    # extract a numeric metric via metric_path; fires iff metric meets
    # threshold per threshold_op."
    #   metric_path:    JSONPath-like dot path into the JSON output
    #                   (e.g., "session_rate" or "rules.encoding.session_rate")
    #   threshold:      numeric threshold to compare against
    #   threshold_op:   one of "gte" (>=), "gt" (>), "lte" (<=), "lt" (<)
    #                   default gte (rate >= threshold means "still failing")
    metric_path: str = ""
    threshold: float = 0.0
    threshold_op: str = "gte"

    # Resolved at import time (see _RESOLVE_TIMEOUT below) so tests
    # can monkeypatch AUDIT_SKILL_ORACLE_TIMEOUT before invoking
    # fires(). Default 30s preserves prior behavior; override via
    # env var when a reproducer needs more (e.g. wc on a large file).

    def __post_init__(self):
        if self.type not in REPRODUCER_TYPES:
            raise ValueError(
                f"reproducer.type must be one of {REPRODUCER_TYPES}; got {self.type!r}"
            )
        if self.expect_type not in ("either", "file", "dir"):
            raise ValueError(
                f"reproducer.expect_type must be one of "
                f"('either', 'file', 'dir'); got {self.expect_type!r}"
            )
        if self.threshold_op not in ("gte", "gt", "lte", "lt"):
            raise ValueError(
                f"reproducer.threshold_op must be one of "
                f"('gte', 'gt', 'lte', 'lt'); got {self.threshold_op!r}"
            )

    def fires(self, repo_root: Path) -> tuple[bool, str]:
        """Return (fires, evidence_str). 'fires' is True iff the bug
        described by this reproducer is still present in the live tree
        at repo_root.

        For 'manual' reproducers, returns (False, '<manual>') with
        evidence noting no automated check ran — callers must escalate
        to human review."""
        if self.type == "manual":
            return False, f"<manual: {self.description}>"

        if self.type == "transcript_pattern":
            return self._fires_transcript_pattern(repo_root)

        if self.type in ("file_exists", "file_missing"):
            full = repo_root / self.path if not Path(self.path).is_absolute() else Path(self.path)
            exists = full.exists()
            # expect_type guard: a reproducer like
            # `type: file_missing, path: tests, expect_type: dir`
            # asserts the bug is "tests directory absent." If the
            # path exists but is a FILE (renamed/symlinked), the
            # legacy `either` mode would falsely conclude "bug
            # absent" even though the dir is gone. expect_type=dir
            # makes the predicate path-type-aware.
            if exists and self.expect_type != "either":
                is_dir = full.is_dir()
                type_matches = (
                    (self.expect_type == "dir" and is_dir) or
                    (self.expect_type == "file" and not is_dir)
                )
                if not type_matches:
                    # Path exists but wrong type → treat as if missing.
                    exists = False
            ev = (
                f"path {self.path!r} exists={exists}"
                + (f" expect_type={self.expect_type}" if self.expect_type != "either" else "")
            )
            if self.type == "file_exists":
                return exists, ev
            return (not exists), ev

        if self.type == "python":
            # Run the snippet in a subprocess so it can't pollute our
            # interpreter state; cwd=repo_root so relative paths resolve.
            r = subprocess.run(
                [sys.executable, "-c", self.command],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=_reproducer_timeout(),
            )
            # Contract:
            #   rc=0  → bug absent (snippet ran to completion w/o raising) → STALE
            #   rc!=0 with INSTRUMENT_FAILURE pattern in stderr → ERROR (raised)
            #   rc!=0 otherwise → bug present (snippet raised intentionally) → STILL-FIRES
            #
            # The instrument-failure routing is the python equivalent of
            # the grep rc>=2 -> ERROR fix. Without it, a typo (SyntaxError,
            # NameError) or a missing import produces the same STILL-FIRES
            # verdict as a real bug, and Layer D fix-loop then reports
            # "fix didn't work" because the broken snippet still fires
            # across any fix attempt. The conflation class is identical
            # to the original grep rc>=2 bug — see oracle/SPEC.md
            # "Exit-code contract".
            INSTRUMENT_FAILURE_PATTERNS = (
                "SyntaxError",
                "IndentationError",
                "ModuleNotFoundError",
                "ImportError",
                "NameError",        # almost always a typo
                "AttributeError",   # usually missing import or wrong API
            )
            if r.returncode != 0 and any(p in r.stderr for p in INSTRUMENT_FAILURE_PATTERNS):
                raise RuntimeError(
                    f"python reproducer instrument failure rc={r.returncode}; "
                    f"stderr={r.stderr[:200]!r}"
                )
            fires = r.returncode != 0
            evidence = f"python rc={r.returncode}; stderr={r.stderr[:200]!r}"
            return fires, evidence

        # bash / grep / grep_absent — all run via shell.
        # _BASH is resolved at import time to skip System32's WSL bash on
        # Windows; see _resolve_bash() above.
        cmd = self.command
        r = subprocess.run(
            [_BASH, "-c", cmd],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_reproducer_timeout(),
        )
        if self.type == "grep":
            # grep contract:
            #   rc=0  → at least one line matched           → bug present
            #   rc=1  → no lines matched                    → bug absent (STALE)
            #   rc≥2  → grep error (bad regex, file not
            #           found, IO failure) OR bash error
            #           (rc=127 command-not-found, rc=126
            #           not-executable). Either way the
            #           reproducer didn't actually answer the
            #           question — raise so reverify routes
            #           this to ERROR, not STALE. Without this
            #           a typo'd file path looks identical to
            #           "bug fixed."
            if r.returncode >= 2:
                raise RuntimeError(
                    f"grep reproducer error rc={r.returncode}; "
                    f"stderr={r.stderr[:200]!r}"
                )
            fires = (r.returncode == 0)
            ev = f"grep rc={r.returncode}; match={'yes' if fires else 'no'}"
            return fires, ev
        if self.type == "grep_absent":
            # grep_absent: bug present iff grep finds NO match.
            # Same contract as `grep` but inverted; same ERROR
            # discipline on rc≥2.
            if r.returncode >= 2:
                raise RuntimeError(
                    f"grep_absent reproducer error rc={r.returncode}; "
                    f"stderr={r.stderr[:200]!r}"
                )
            fires = (r.returncode == 1)
            ev = f"grep_absent rc={r.returncode}; match={'yes' if r.returncode == 0 else 'no'}"
            return fires, ev
        # bash: 'expected_exit' is the exit code that means "bug is present"
        # (per the dataclass docstring). So the finding fires when the
        # command's exit matches expected_exit.
        #
        # Exit-code contract for bash (closes the third conflation
        # surface after grep #979 and python #981):
        #
        #   rc == expected_exit          → predicate fires (STILL-FIRES)
        #   rc != expected_exit AND rc in {126, 127} OR rc >= 128
        #                                → ERROR (instrument failure)
        #   rc != expected_exit otherwise → predicate doesn't fire (STALE)
        #
        # The instrument-failure rc set is documented shell exit
        # semantics:
        #   126 — command found but not executable
        #   127 — command not found (typo / missing binary)
        #   128 + N — process killed by signal N (Git Bash on Windows
        #            reports this form: e.g. 137=SIGKILL, 139=SIGSEGV)
        #   negative — signal kill in Python's subprocess convention
        #            on POSIX (Linux/macOS): rc = -N for signal N
        #
        # If the author explicitly sets `expected_exit` to one of these
        # (e.g. testing whether a command IS missing,
        # `expected_exit=127`), the equality branch wins first and
        # STILL-FIRES is returned. Without this routing, a typo'd
        # command (`grpe -q ...`) returns rc=127, fails the equality
        # check, and the oracle reports STALE — indistinguishable from
        # "bug fixed." Same conflation class the grep `rc≥2` and
        # python instrument-failure fixes closed; this is the third
        # and last executable-reproducer surface.
        if r.returncode == self.expected_exit:
            fires = True
        elif r.returncode in (126, 127) or r.returncode >= 128 or r.returncode < 0:
            raise RuntimeError(
                f"bash reproducer instrument failure rc={r.returncode} "
                f"(expected_exit={self.expected_exit}); "
                f"stderr={r.stderr[:200]!r}"
            )
        else:
            fires = False
        ev = f"bash rc={r.returncode}; expected_exit={self.expected_exit}; fires={fires}"
        return fires, ev

    def fires_with_breadth(self, repo_root: Path) -> tuple[bool, str, dict]:
        """Like fires(), but also returns a breadth signal for drift
        detection (oracle/SPEC.md "Trace contract"). The breadth dict
        records the predicate's static specificity verdict and the
        observed return code parsed from the evidence string. A
        reproducer whose specificity drifts toward 'vacuous' over many
        runs is a reward-hacking signal. ``match_count`` is reserved
        (stays None unless a future non-`-q` grep path populates it).

        Delegates to fires() — the exit-code contract is unchanged — so
        every existing caller keeps the (bool, str) contract."""
        fires, evidence = self.fires(repo_root)
        breadth: dict[str, Any] = {
            "type": self.type,
            "specificity": static_vacuity(self),
            "rc": None,
            "match_count": None,
        }
        m = re.search(r"rc=(-?\d+)", evidence)
        if m:
            breadth["rc"] = int(m.group(1))
        return fires, evidence, breadth

    def _fires_transcript_pattern(self, repo_root: Path) -> tuple[bool, str]:
        """Run the measurement command, parse its JSON output, extract
        the metric at metric_path, compare to threshold.

        Designed for audit-rules: the command is typically
        ``python scan_violations.py --rule <name> --json``, the JSON
        contains a per-rule session_rate, and the threshold is a
        promotion-trigger threshold (e.g., 10% session rate).

        Returns (fires, evidence) where fires=True means the bug (rule
        is being violated above threshold) is still present.
        """
        r = subprocess.run(
            [_BASH, "-c", self.command],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_reproducer_timeout(),
        )
        if r.returncode != 0:
            # Instrument failure — the command itself broke. Surface
            # as ERROR via RuntimeError per the oracle's contract.
            raise RuntimeError(
                f"transcript_pattern command failed rc={r.returncode}; "
                f"stderr={r.stderr[:200]!r}"
            )
        # Parse JSON output and extract metric_path.
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"transcript_pattern command did not emit valid JSON: {e}; "
                f"stdout[:200]={r.stdout[:200]!r}"
            )
        metric_value = _extract_metric(data, self.metric_path)
        if metric_value is None:
            raise RuntimeError(
                f"transcript_pattern metric_path {self.metric_path!r} "
                f"not found in JSON output; available keys: "
                f"{list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
            )
        try:
            metric_value = float(metric_value)
        except (TypeError, ValueError):
            raise RuntimeError(
                f"transcript_pattern metric at {self.metric_path!r} "
                f"is not numeric: {metric_value!r}"
            )
        fires = _compare(metric_value, self.threshold_op, self.threshold)
        ev = (
            f"transcript_pattern: {self.metric_path}={metric_value} "
            f"{self.threshold_op} {self.threshold} → fires={fires}"
        )
        return fires, ev


def _extract_metric(data, metric_path: str):
    """Navigate dot-path into nested dict/list. Returns None if the
    path is invalid. Supports simple keys and numeric indices
    (e.g., 'rules.encoding.session_rate' or 'items.0.value')."""
    if not metric_path:
        return None
    cur = data
    for part in metric_path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def _compare(value: float, op: str, threshold: float) -> bool:
    """Compare value to threshold per op. Used by transcript_pattern.fires()."""
    if op == "gte":
        return value >= threshold
    if op == "gt":
        return value > threshold
    if op == "lte":
        return value <= threshold
    if op == "lt":
        return value < threshold
    raise ValueError(f"unknown threshold_op: {op!r}")


def _python_vacuous(command: str) -> str | None:
    """Static check for ``python`` reproducers that fire unconditionally —
    the proposer-grades-its-own-homework class for type=python.

    The grep/bash empirical control-run (oracle/specificity.py) cannot cover
    python: running a content-specific snippet against a benign control tree
    raises FileNotFoundError, which the exit-code contract reads as a *fire*,
    so a control-run would false-flag legitimate python reproducers. Instead
    we flag ONLY a snippet whose sole executable statement (imports stripped)
    is a bare ``raise``, ``assert False`` / ``assert 0``, or an unconditional
    nonzero ``exit(...)`` / ``sys.exit(...)``. A genuine reproducer reads repo
    content first (≥2 statements, or a call/compare over file contents), so
    this has near-zero false-positive risk. Unparseable snippets return None —
    the exit-code contract already routes SyntaxError to ERROR."""
    try:
        tree = ast.parse(command or "")
    except SyntaxError:
        return None
    stmts = [s for s in tree.body if not isinstance(s, (ast.Import, ast.ImportFrom))]
    if len(stmts) != 1:
        return None
    s = stmts[0]
    if isinstance(s, ast.Raise):
        return "python predicate is a bare unconditional `raise` (fires regardless of repo content)"
    if isinstance(s, ast.Assert) and isinstance(s.test, ast.Constant) and not s.test.value:
        return "python predicate is `assert False`/`assert 0` (fires regardless of repo content)"
    if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
        fn = s.value.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if fname in ("exit", "_exit") and s.value.args \
                and isinstance(s.value.args[0], ast.Constant) \
                and s.value.args[0].value not in (0, None):
            return "python predicate is an unconditional nonzero exit (fires regardless of repo content)"
    return None


def static_vacuity(reproducer) -> str | None:
    """Return a reason string if the reproducer's predicate is vacuous
    (fires regardless of repository content), else None. Static, no I/O.

    The cheap first layer of the specificity guard: catches the
    `grep -q .` reward-hacking class without running anything. The
    empirical control-run in oracle/specificity.py is the backstop for
    vacuous grep/bash predicates that aren't literal pattern matches;
    ``python`` is covered here statically by ``_python_vacuous`` (a
    control-run can't, see that helper). file_exists, file_missing,
    transcript_pattern, and manual remain out of scope for static
    detection."""
    if reproducer.type == "python":
        return _python_vacuous(reproducer.command or "")
    if reproducer.type not in ("grep", "grep_absent", "bash"):
        return None
    cmd = (reproducer.command or "").strip()
    if not cmd:
        return None
    for pat in VACUOUS_COMMAND_PATTERNS:
        if re.search(pat, cmd, re.MULTILINE):
            return f"command matches vacuous pattern {pat!r}"
    return None


# Valid triage_status values. See SPEC.md §"Triage status" for full
# semantics. The workflow for filtering is:
#
#   open / "" / None  → actionable. act_on includes in worklist.
#   STALE             → re-audit confirmed not reproducible. SKIP.
#   FIXED             → resolved by a prior commit. SKIP.
#   FALSE_POSITIVE    → original finding was wrong. SKIP.
#   DEFER             → real but out of scope for current wave. SKIP
#                       unless wave explicitly named to address.
#
# Added 2026-05-25 as a structural fix for the
# "stale-finding-survives-into-next-campaign" pattern observed when
# triaging Phase 2 unverified items: 21/25 turned out to be stale
# but the YAML lacked a status field, so the next campaign would
# re-surface all 25.
TRIAGE_STATUSES = ("", "open", "STALE", "FIXED", "FALSE_POSITIVE", "DEFER")


@dataclasses.dataclass
class Finding:
    """An audit-skill finding with machine-checkable reproducer.

    label is one of ``behavior-fix``, ``doc-fix``, ``unverified``.
    code is the audit category (D1, D2, A1, M2, etc.) — free-form so
    new Phase 2 categories don't need a schema migration.
    triage_status is one of TRIAGE_STATUSES (default "" = untriaged /
    actionable).
    """
    skill: str
    code: str
    severity: str  # drift | info | error
    label: str     # behavior-fix | doc-fix | unverified
    description: str
    reproducer: Reproducer
    source: str = ""  # path-line locator for the finding
    triage_status: str = ""  # see TRIAGE_STATUSES
    triage_note: str = ""    # free-text rationale for the status
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        if self.triage_status and self.triage_status not in TRIAGE_STATUSES:
            raise ValueError(
                f"triage_status must be one of {TRIAGE_STATUSES}; "
                f"got {self.triage_status!r}"
            )

    def is_actionable(self) -> bool:
        """True if act_on / orchestrator should include this finding
        in dispatch. Findings with closed triage statuses are skipped."""
        return self.triage_status in ("", "open")

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        rep = d.pop("reproducer", {})
        if isinstance(rep, dict):
            rep = Reproducer(**rep)
        # Lenient triage_status on the FILE-LOADING path: an out-of-enum
        # value (e.g. a prior run's ad-hoc "BLOCKED"/"DIAGNOSED") must NOT
        # abort the whole findings file via __post_init__. Coerce to ""
        # (untriaged -> actionable: surfaces rather than hides) and warn.
        # __post_init__ stays strict for direct programmatic construction
        # (tests rely on it). 2026-06-16: a prior audit-architecture
        # findings.yaml with triage_status: BLOCKED made `reverify` exit 2
        # at load, blackholing all gating until the file was hand-rewritten.
        ts = d.get("triage_status")
        if ts and ts not in TRIAGE_STATUSES:
            print(
                f"warning: triage_status {ts!r} not in {TRIAGE_STATUSES} "
                f"(skill={d.get('skill')!r}, code={d.get('code')!r}); "
                f"coercing to '' (actionable)",
                file=sys.stderr,
            )
            d["triage_status"] = ""
        # Route unknown keys into .extra so calibration metadata
        # (expected_fires, ground_truth, label_source, etc.) is
        # preserved without expanding the canonical schema.
        known_fields = {f.name for f in dataclasses.fields(cls)}
        extras = {k: v for k, v in d.items() if k not in known_fields}
        kwargs = {k: v for k, v in d.items() if k in known_fields}
        existing_extra = kwargs.pop("extra", None) or {}
        kwargs["extra"] = {**existing_extra, **extras}
        return cls(reproducer=rep, **kwargs)


class FindingsParseError(ValueError):
    """Raised when a findings file is malformed or has missing required
    fields. CLI callers should catch this and exit with a clean message
    rather than letting the underlying TypeError/KeyError surface as a
    Python traceback. See cmd_reverify, cmd_act_on, etc."""


def load_findings(path: Path) -> list[Finding]:
    """Load findings from a YAML or JSON file. Format:
        findings:
          - skill: foo
            code: D2
            severity: drift
            label: behavior-fix
            description: ...
            reproducer:
              type: grep
              command: |
                grep -q 'workspace_name' skills/foo/manifest.yaml

    Raises FindingsParseError with a clear message on any parse or
    schema problem (bad YAML, missing required fields on a finding,
    missing reproducer.type, etc.). Callers should translate this
    into a user-facing CLI error, not propagate as a traceback.
    """
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix in (".json", ".jsonl"):
            data = json.loads(text)
        else:
            data = _parse_findings_yaml(text)
    except (json.JSONDecodeError, ValueError) as e:
        raise FindingsParseError(
            f"could not parse findings file {path}: {e}"
        ) from e
    if not isinstance(data, dict):
        raise FindingsParseError(
            f"findings file {path} must be a YAML/JSON mapping at top "
            f"level (got {type(data).__name__})"
        )
    findings_list = data.get("findings", [])
    if not isinstance(findings_list, list):
        raise FindingsParseError(
            f"findings file {path}: 'findings:' must be a list "
            f"(got {type(findings_list).__name__})"
        )
    out = []
    for idx, entry in enumerate(findings_list):
        if not isinstance(entry, dict):
            raise FindingsParseError(
                f"findings file {path}: entry #{idx} must be a mapping "
                f"(got {type(entry).__name__})"
            )
        try:
            out.append(Finding.from_dict(dict(entry)))
        except TypeError as e:
            # Reproducer/Finding kwargs mismatch — missing required
            # field, typically reproducer.type or finding.description.
            raise FindingsParseError(
                f"findings file {path}: entry #{idx} "
                f"(skill={entry.get('skill', '?')!r}, "
                f"code={entry.get('code', '?')!r}) is missing or has "
                f"a malformed field: {e}"
            ) from e
        except ValueError as e:
            # E.g. triage_status not in TRIAGE_STATUSES, or
            # Reproducer.type not in REPRODUCER_TYPES.
            raise FindingsParseError(
                f"findings file {path}: entry #{idx} "
                f"(skill={entry.get('skill', '?')!r}, "
                f"code={entry.get('code', '?')!r}) failed validation: {e}"
            ) from e
    return out


def _parse_findings_yaml(text: str) -> dict:
    """Parse findings YAML — PyYAML when importable, minimal parser as
    the dependency-free fallback.

    PyYAML is primary because it implements FULL YAML semantics: the
    minimal parser silently TRUNCATED width-folded flow scalars at the
    fold point (2026-06-12 incident: 68 reproducer commands loaded cut
    short → ~90 live findings false-STALE'd in one campaign reverify).
    The rest of this toolchain (backfill, tests, emit paths) already
    hard-depends on pyyaml, so the "avoid a pyyaml dep" rationale only
    holds for stripped-down environments — which keep the fallback.

    Raises ValueError on malformed input (the caller converts to
    FindingsParseError) so garbage can never read as an empty worklist.
    """
    try:
        import yaml as _yaml  # type: ignore
    except ImportError:
        data = _parse_minimal_yaml(text)
        # Without pyyaml there is no arbiter for "garbage vs genuinely
        # findings-less" — stay lenient, matching the historical
        # fallback behavior.
        return data
    try:
        loaded = _yaml.safe_load(text)
    except _yaml.YAMLError as e:
        raise ValueError(f"not valid YAML: {e}") from e
    if loaded is None:
        # Empty / comments-only document — a legitimate zero-finding file
        # (the calibration corpus depends on this being accepted).
        return {"findings": []}
    if not isinstance(loaded, dict):
        raise ValueError(
            f"top-level value must be a mapping (got {type(loaded).__name__})"
        )
    return loaded


def _parse_minimal_yaml(text: str) -> dict:
    """Parse the small subset of YAML used in our oracle files:
    top-level ``findings:`` list of mappings whose values are scalars,
    multi-line block scalars (``|``), or short inline strings. Fallback
    for environments without pyyaml — see _parse_findings_yaml."""
    result: dict = {"findings": []}
    lines = text.splitlines()
    i = 0
    in_findings = False
    current: dict | None = None
    current_rep: dict | None = None
    pending_block_key: tuple[str, dict] | None = None
    pending_block_indent: int = -1
    pending_block_lines: list[str] = []

    # Indent of the first content line in the current block scalar.
    # Set on first non-blank line; used to dedent every subsequent line.
    # Without this we'd strip a fixed key-indent+1 prefix, leaving a
    # leading space in block content — invisible for bash (shell trims),
    # but breaks Python (IndentationError: unexpected indent) and any
    # other interpretive context. See incident 2026-05-26 in the
    # calibration ERROR-pathway PR.
    block_content_indent: int = -1

    def flush_block():
        nonlocal pending_block_key, pending_block_lines, block_content_indent
        if pending_block_key is None:
            return
        key, target = pending_block_key
        target[key] = "\n".join(pending_block_lines).rstrip()
        pending_block_key = None
        pending_block_lines = []
        block_content_indent = -1

    # Flow scalars are finalized lazily so width-folded continuations
    # (closing quote on a later line) can be re-attached first. The old
    # eager strip-and-assign dropped every folded continuation line —
    # 2026-06-12 incident: 68 reproducer commands in one campaign tracker
    # loaded truncated at the fold point, turning live findings into
    # false STALEs (and risking false fires).
    # pending_scalar = [key, target_dict, raw_value, key_line_indent]
    pending_scalar: list | None = None

    def flush_scalar():
        nonlocal pending_scalar
        if pending_scalar is None:
            return
        key, target, raw, _ = pending_scalar
        pending_scalar = None
        val = raw.strip()
        # Strip surrounding quotes and decode escape sequences.
        # The encoder (tracker._yaml_escape) encodes `\` → `\\` then
        # `"` → `\"`. The decoder must reverse this; otherwise each
        # round-trip doubles the backslash count and descriptions
        # accumulate corruption (root cause of the 46-finding
        # corruption observed 2026-05-26 across PRs #976 → Option 4).
        if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
            val = _decode_double_quoted(val[1:-1])
        elif len(val) >= 2 and val.startswith("'") and val.endswith("'"):
            # Single-quoted YAML uses `''` for embedded quote;
            # no backslash decoding. We just strip the wrapping.
            val = val[1:-1].replace("''", "'")
        if key == "expected_exit":
            try:
                val = int(val)
            except ValueError:
                pass
        if key == "threshold":
            try:
                val = float(val)
            except ValueError:
                pass
        target[key] = val

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Comment or blank — flush block lines that are clearly outside
        # (we use indentation, but be conservative).
        if pending_block_key is not None:
            # Continue collecting block lines until a less-indented non-
            # blank line is seen.
            if not stripped:
                pending_block_lines.append("")
                i += 1
                continue
            indent = len(line) - len(line.lstrip())
            if indent > pending_block_indent:
                # First content line: lock in the block's content indent.
                # Subsequent lines must be at least this indent to remain
                # inside the block; we strip exactly this many leading
                # chars so the block content starts at column 0.
                if block_content_indent < 0:
                    block_content_indent = indent
                pending_block_lines.append(line[block_content_indent:])
                i += 1
                continue
            flush_block()

        if not stripped or stripped.startswith("#"):
            flush_scalar()
            i += 1
            continue

        if stripped == "findings:" or re.match(r"^findings:\s*\[\s*\]\s*$", stripped):
            # Accept both the block form ("findings:" + items) and the
            # flow-style empty list ("findings: []") an emitter produces
            # for a zero-finding file — without the second form, the
            # no-findings-key guard below would reject a legitimately
            # empty worklist as malformed.
            flush_scalar()
            in_findings = True
            i += 1
            continue

        if not in_findings:
            i += 1
            continue

        if stripped.startswith("- "):
            # Start a new finding
            flush_scalar()
            if current is not None:
                result["findings"].append(current)
            current = {}
            current_rep = None
            stripped = stripped[2:]
            # Fall through to key parsing on the rest of the line

        # key: value
        m = re.match(r"^([a-zA-Z_]+):\s*(.*)$", stripped)
        if m and current is not None:
            flush_scalar()
            key, val = m.group(1), m.group(2)
            indent = len(line) - len(line.lstrip())
            if val in ("|", ">", "|-", ">-", "|+", ">+"):
                # Block scalar follows on subsequent more-indented lines.
                # Chomping indicators (|- |+ >- >+) are accepted: flush_block
                # rstrips, which matches strip-chomping and is harmless for
                # keep/clip given these values feed shell/python runners.
                target_dict = current_rep if current_rep is not None and key in ("command", "description") else current
                # If we're inside a reproducer (already saw 'reproducer:'),
                # block keys belong there.
                if current_rep is not None and key in ("type", "command", "path", "expected_exit", "description", "expect_type", "metric_path", "threshold", "threshold_op"):
                    target_dict = current_rep
                pending_block_key = (key, target_dict)
                pending_block_indent = indent
                pending_block_lines = []
                i += 1
                continue
            if key == "reproducer":
                current_rep = {}
                current["reproducer"] = current_rep
                i += 1
                continue
            # Scalar value — finalized lazily by flush_scalar() so a
            # width-folded continuation line (including one carrying the
            # closing quote) can be re-attached before quote-stripping.
            target = current
            if current_rep is not None and key in ("type", "command", "path", "expected_exit", "description", "expect_type", "metric_path", "threshold", "threshold_op"):
                target = current_rep
            pending_scalar = [key, target, val.strip(), indent]
        elif (current is not None and pending_scalar is not None
                and (len(line) - len(line.lstrip())) > pending_scalar[3]):
            # Folded flow-scalar continuation: YAML unfolds the line break
            # + indent to a single space. Without this branch these lines
            # fell through silently and the scalar loaded truncated.
            pending_scalar[2] = pending_scalar[2] + " " + stripped
        i += 1

    flush_scalar()
    flush_block()
    if current is not None:
        result["findings"].append(current)
    return result


def _decode_double_quoted(s: str) -> str:
    """Decode YAML double-quoted-string escape sequences.

    The encoder (tracker._yaml_escape) produces only \\\\ and \\".
    This decoder reverses those, plus \\n and \\t for completeness.
    Unknown escapes are preserved as-is (don't lose data on novel
    inputs).
    """
    result: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            c = s[i + 1]
            if c == "\\":
                result.append("\\")
            elif c == '"':
                result.append('"')
            elif c == "n":
                result.append("\n")
            elif c == "t":
                result.append("\t")
            elif c == "r":
                result.append("\r")
            else:
                # Unknown escape — preserve verbatim
                result.append(s[i : i + 2])
            i += 2
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def dump_findings(findings: list[Finding], path: Path) -> None:
    """Write findings to a JSON file for downstream tools."""
    data = {"findings": [f.to_dict() for f in findings]}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
