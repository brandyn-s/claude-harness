"""
Scan session transcripts for rule violations.
Calibrated detector — assistant messages only for code violations.

The scanner runs EIGHT opinionated detectors (V1-V8 below). It does NOT
read rules/*.md and derive checks dynamically — adding a new rule does
not add a new detector. Treat the violation table as an opinionated
sample, not a census of all rules.

Usage:
  scan_violations.py                       # last 14 days
  scan_violations.py --days 30             # last 30 days
  scan_violations.py --since 2026-04-03    # absolute lower bound
  scan_violations.py --before 2026-04-17   # absolute upper bound (exclusive)
  scan_violations.py --since 2026-04-03 --before 2026-04-17   # window
  scan_violations.py --rule encoding-missing-open             # filter to one rule
  scan_violations.py --json                # JSON output

Post-promotion lifecycle example:
  scan_violations.py --since 2026-04-03 --before 2026-04-17  # pre-promotion
  scan_violations.py --since 2026-04-17                      # post-promotion
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')


# Block-signature map: for hook-ENFORCED rules, the distinctive substring(s)
# a guard prints when it BLOCKS the violating command. Used to split a rule's
# session_rate_pct into block-then-fix (the guard fired; the scanner counted
# the pre-block attempt) vs net-silent (the violation actually executed). This
# is ADDITIVE — session_rate_pct is unchanged; the breakdown is reported
# alongside it. Only rules listed here get the breakdown; rules absent from
# this map report the raw attempted rate exactly as before. Signatures verified
# present in transcripts via /audit-rules 2026-06-16 forensics (48 of 55
# flagged encoding-missing-open sessions carried one of these — i.e. the
# headline 11.4% attempted-rate was ~87% block-then-fix, not silent failure).
RULE_BLOCK_SIGNATURES = {
    "encoding-missing-open": [
        "[inline-encoding-guard]",
        "[heredoc-encoding-guard]",
        "without encoding='utf-8' at",
    ],
    "inline-python-c": [
        "[inline-python-guard] BLOCKED",
    ],
}

# Every detector the scanner runs (V1-V8, in ledger order — see the
# SKILL.md detector table). Output always includes each of these, with a
# zero-count entry when a rule recorded no violations in the window, so
# "measured clean" is distinguishable from "detector removed". Silent
# omission of zero-hit rules was the exact gap the 2026-08-22 audit run
# hit: V6/V7/V8 vanished from the JSON and the reader could not tell
# clean from unmeasured.
ALL_RULES = (
    "encoding-missing-open",         # V1
    "missing-stdout-reconfigure",    # V2
    "inline-python-c",               # V3
    "str-replace-crlf-risk",         # V4
    "git-commit-no-branch-check",    # V5
    "websearch-webfetch-used",       # V6
    "curl-verbose-with-auth",        # V7
    "pip-install-upgrade-all",       # V8
)

# V1 path-category split: an open() of an ephemeral scratch path on a
# UTF-8-default host is exactly the shape the 2026-06-27 demotion
# accepted (see AUDIT-TRACKERS/demotions.yaml); an open() of a durable
# path is the portability risk the warn still targets. Splitting the
# count makes the warn-band number interpretable.
_SCRATCH_PATH_PREFIXES = ("/tmp/", "/private/tmp/", "/dev/", "/var/folders/")
_OPEN_ARG_PATTERN = re.compile(r"""open\s*\(\s*[rbf]{0,2}(['"])([^'"]*)""")


def _classify_open_path(call):
    """Bucket a V1 excerpt by its open() argument: 'scratch' (tmp/dev
    paths), 'durable_or_unknown' (any other literal), or 'non_literal'
    (variable/expression argument — path unknowable from the excerpt)."""
    m = _OPEN_ARG_PATTERN.search(call)
    if not m:
        return "non_literal"
    path = m.group(2)
    if path.startswith(_SCRATCH_PATH_PREFIXES) or "$TMPDIR" in path:
        return "scratch"
    return "durable_or_unknown"


class ViolationTracker:
    # Keep up to this many distinct sessions' examples per rule.
    # Bumped from 3→5 on 2026-04-21 — 3 slots filled by repeat hits from one
    # session left no room for cross-session diversity.
    MAX_EXAMPLES_PER_RULE = 5
    # Excerpt window. 200 chars was too short to tell str.replace('\n')
    # false positives from real CRLF bugs; 500 shows enough surrounding code.
    EXCERPT_CHARS = 500

    def __init__(self, suppressions=None):
        self.counts = Counter()
        self.examples = defaultdict(list)
        self.sessions_scanned = 0
        self.lines_scanned = 0
        self.sessions_with_violations = defaultdict(set)
        self.session_mtimes = {}  # session_id -> datetime
        self.scan_window = None   # (since_dt, before_dt) for reporting
        # Durable FP suppressions. List of dicts per rule-suppressions.yaml
        # schema; each entry has rule + (pattern | session_id) + reason.
        # The tracker filters matching violations BEFORE record(), so
        # they don't count toward session_rate_pct.
        self.suppressions = suppressions or []
        # Count suppressed violations for reporting/audit trail; the
        # operator can see "encoding-missing-open: 12 suppressed via
        # rule-suppressions.yaml" in the JSON output.
        self.suppressed_counts = Counter()
        # Per-rule set of sessions where a hook BLOCK signature appeared
        # (see RULE_BLOCK_SIGNATURES). Intersected with sessions_with_
        # violations in to_dict() to split block-then-fix from net-silent.
        self.sessions_with_block_sig = defaultdict(set)
        # Per-rule Counter of path categories (V1 passes one per hit via
        # record(category=...)). Rules that never pass a category have no
        # path_split in their output entry.
        self.path_categories = defaultdict(Counter)

    def note_block_signatures(self, session_id, raw_line):
        """Record which rules' hook BLOCK signatures appear in this raw
        transcript line. Block feedback lands in tool_result content, not
        assistant messages, so this runs on every raw line BEFORE the
        assistant-only filter in scan_transcript(). Faithful to the manual
        forensic grep (whole-file substring match) the /audit-rules gate
        prescribes."""
        for rule, sigs in RULE_BLOCK_SIGNATURES.items():
            if session_id in self.sessions_with_block_sig[rule]:
                continue
            if any(sig in raw_line for sig in sigs):
                self.sessions_with_block_sig[rule].add(session_id)

    def _is_suppressed(self, rule, session_id, excerpt) -> bool:
        """Check if this violation matches a durable suppression entry.
        Returns True iff a suppression for `rule` matches by pattern
        (substring, case-insensitive) OR by session_id prefix."""
        short_id = session_id[:12]
        excerpt_lower = excerpt.lower()
        for entry in self.suppressions:
            if entry.get("rule") != rule:
                continue
            # Honor expires if set; expired entries don't suppress.
            expires = entry.get("expires")
            if expires:
                try:
                    exp_dt = datetime.fromisoformat(expires)
                    if datetime.now() > exp_dt:
                        continue
                except (TypeError, ValueError):
                    pass
            pattern = entry.get("pattern", "")
            if pattern and pattern.lower() in excerpt_lower:
                return True
            sess = entry.get("session_id", "")
            if sess and short_id.startswith(sess[:12]):
                return True
        return False

    def record(self, rule, session_id, excerpt, category=None):
        # Durable FP suppression: skip violations matching a rule-
        # suppressions.yaml entry. Count them separately so the
        # operator can see how many were suppressed (and re-enable
        # if the suppression looks too broad).
        if self._is_suppressed(rule, session_id, excerpt):
            self.suppressed_counts[rule] += 1
            return
        if category:
            self.path_categories[rule][category] += 1
        self.counts[rule] += 1
        self.sessions_with_violations[rule].add(session_id)
        # Dedup: keep one example per distinct session so readers see breadth,
        # not three near-identical excerpts from the same chat.
        short_id = session_id[:12]
        if any(e[0] == short_id for e in self.examples[rule]):
            return
        if len(self.examples[rule]) < self.MAX_EXAMPLES_PER_RULE:
            self.examples[rule].append((short_id, excerpt[:self.EXCERPT_CHARS]))

    def _violation_entry(self, rule, count):
        flagged = self.sessions_with_violations[rule]
        n_flagged = len(flagged)
        entry = {
            "count": count,
            "unique_sessions": n_flagged,
            "session_rate_pct": round(
                n_flagged / self.sessions_scanned * 100, 1
            ) if self.sessions_scanned else 0,
            "examples": self.examples[rule],
            "suppressed_count": int(self.suppressed_counts.get(rule, 0)),
        }
        # Block-then-fix breakdown (ADDITIVE; only for rules with a known
        # guard signature in RULE_BLOCK_SIGNATURES). session_rate_pct above
        # counts every ATTEMPT; this splits it into attempts the hook caught
        # (block-then-fix) vs ones that actually executed unblocked
        # (net-silent). For a hook-enforced rule, net-silent is the real
        # compliance gap; the raw attempted-rate over-counts block-then-fix.
        if rule in RULE_BLOCK_SIGNATURES:
            blocked = len(flagged & self.sessions_with_block_sig[rule])
            net_silent = n_flagged - blocked
            entry["blocked_then_fixed_sessions"] = blocked
            entry["net_silent_sessions"] = net_silent
            entry["net_silent_rate_pct"] = round(
                net_silent / self.sessions_scanned * 100, 1
            ) if self.sessions_scanned else 0
        if self.path_categories.get(rule):
            entry["path_split"] = dict(self.path_categories[rule])
        return entry

    def to_dict(self, include_all_rules=False):
        """Serialize scan results.

        include_all_rules=True adds a zero-count entry for every ALL_RULES
        detector that recorded nothing, so the output distinguishes
        "measured clean" from "detector absent". Default False preserves
        the tracker-level contract that only recorded rules appear (a
        block signature alone must not fabricate an entry).
        """
        violations = {
            rule: self._violation_entry(rule, count)
            for rule, count in self.counts.most_common()
        }
        if include_all_rules:
            for rule in ALL_RULES:
                if rule not in violations:
                    violations[rule] = self._violation_entry(rule, 0)
        return {
            "sessions_scanned": self.sessions_scanned,
            "lines_scanned": self.lines_scanned,
            "scan_window": (
                [self.scan_window[0].isoformat(), self.scan_window[1].isoformat()]
                if self.scan_window else None
            ),
            "suppressed": {
                rule: int(n) for rule, n in self.suppressed_counts.items()
            },
            "violations": violations,
        }


def _load_suppressions(repo_root):
    """Load AUDIT-TRACKERS/rule-suppressions.yaml if present.

    Tiny home-grown loader (no PyYAML dep, matching the parser style
    in oracle/finding.py). Returns a list of entry dicts; missing file
    or empty list returns []."""
    import re as _re
    path = repo_root / "AUDIT-TRACKERS" / "rule-suppressions.yaml"
    if not path.is_file():
        return []
    entries = []
    current = None
    in_list = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "suppressions:" or stripped == "suppressions: []":
            in_list = True
            continue
        if not in_list:
            continue
        if stripped.startswith("- "):
            if current is not None:
                entries.append(current)
            current = {}
            stripped = stripped[2:]
        m = _re.match(r'^([a-zA-Z_]+):\s*(.*)$', stripped)
        if m and current is not None:
            k, v = m.group(1), m.group(2).strip().strip('"').strip("'")
            if k in ("rule", "pattern", "session_id", "reason", "added", "expires"):
                current[k] = v
    if current is not None:
        entries.append(current)
    # Drop malformed entries (require rule + reason + at least one matcher)
    return [
        e for e in entries
        if e.get("rule") and e.get("reason") and (e.get("pattern") or e.get("session_id"))
    ]


_BINARY_MODES = ("'rb'", '"rb"', "'wb'", '"wb"', "'ab'", '"ab"')

# V4 gating pattern: file-read markers that must co-occur with .replace('\n', X)
# to flag a session. Mirrors check_str_replace_crlf in post-write-edit.py so the
# scanner's metric matches what the hook actually enforces.
_FILE_READ_PATTERN = re.compile(
    r"\b(?:open\s*\([^)]*['\"][wra][+b]?['\"]|\.read_text\s*\(|\.read\s*\()"
)

# V4 match pattern: .replace('\n', X) or .replace("\n", X)
_CRLF_REPLACE_PATTERN = re.compile(r'\.replace\(["\'][^"\']*\\n[^"\']*["\']')

# V5 worktree-path detector: `cd "...worktrees/<repo>-<topic>"` is functionally
# a branch check — the worktree path is the branch disambiguator. Modern
# /work + git-hygiene workflow puts each branch in its own worktree, so a
# commit inside a worktree-path cwd already satisfies the "know your branch"
# intent of the rule. Without this gate V5 over-fires ~70% on worktree-based
# sessions (2026-05-26 audit-rules probe, session 100cf57e: 11 of 16 hits had
# `git branch` earlier in the session OR a `cd "...worktrees/..."` in the
# same Bash invocation).
_V5_WORKTREE_PATH_PATTERN = re.compile(r'[/\\]worktrees[/\\][^"\'\s]+')

# Branch-awareness idioms for V5. `git branch` (explicit check),
# `checkout -b` / `switch -c` (branch CREATION — the commit lands on the
# branch the same command just created, which is maximally branch-aware).
_V5_BRANCH_SIGNALS = ('git branch', 'checkout -b', 'switch -c')


def _has_branch_awareness(text):
    return any(sig in text for sig in _V5_BRANCH_SIGNALS)

# V7: forbidden curl verbose-with-auth pattern from platform-constraints.
# Detects the auth-header-leak combination on a single line, within 500
# non-newline chars. The same-line constraint prevents matching prose
# (since explanatory text would put curl and the header on different
# lines). See rules/platform-constraints.md FORBIDDEN block for the rule.
_CURL_VERBOSE_AUTH_PATTERN = re.compile(
    r'curl\s+(?:-v\b|--verbose\b|--trace[a-z-]*\b)[^\n]{0,500}?'
    r'-H\s+["\'](?:Authorization|X-API-Key|X-Api-Key|Cookie):',
    re.IGNORECASE,
)

# V8: forbidden bulk pip-upgrade pattern from platform-constraints.
# Two shapes both forbidden (see rules/platform-constraints.md
# FORBIDDEN block):
#   shape 1: command-substitution over a pip-outdated list
#   shape 2: --upgrade followed by 5+ package names
# Same-line constraint (no \n) prevents matching prose.
_PIP_UPGRADE_ALL_PATTERN = re.compile(
    r'pip3?\s+install\s+[^\n]*?(?:'
    r'(?:--upgrade|-U)\s+\$\([^)]*outdated[^)]*\)'
    r'|'
    r'(?:--upgrade|-U)(?:\s+[a-z0-9_.-]+){5,}'
    r')'
)

# V9 was prototyped but disabled — too many false positives on legitimate
# internal subprocess.run usage (the rule's "for external APIs" qualifier
# is semantic and can't be inferred from regex alone). Re-enable when a
# stronger gating signal is available (e.g., subprocess argv references
# a known-external CLI). For now: documented as a gap; operators can
# add a manual detector if patterns warrant it.


def detect_assistant_violations(
    text, session_id, tracker, executed_text=None, display_raw=None, tool_names=None,
    session_branch_seen=False,
):
    """Detect violations ONLY in assistant-generated content.

    Three input streams:
      - `executed_text`: concatenated tool_use input string values. This is
        the code Claude actually ran (Bash, Write, Edit). V1 uses this so
        the metric aligns with hooks that intercept tool_use.
      - `display_raw`: original assistant text blocks joined verbatim,
        fences intact. V3 needs this — searching for ```python``` patterns
        only works against the un-stripped text.
      - `text`: merged buffer (executed_text + fence-stripped code). Retained
        for detectors that intentionally pool both streams (V2, V6).
      - `tool_names`: set of tool names invoked in the message. V4/V5 use
        this instead of grepping for `"Bash"` / `"WebSearch"` literals —
        tool NAMES aren't included in the merged text, only inputs.
    """
    if executed_text is None:
        executed_text = text
    if display_raw is None:
        display_raw = ""
    if tool_names is None:
        tool_names = set()

    # V1: open() without encoding — executed code only. The (?<![\w.])
    # lookbehind excludes urlopen()/fdopen() (network/fd wrappers) AND
    # os.open()/Path.open() (fd-returning, no encoding kwarg) — matching
    # post-write-edit.py's check_python_encoding anchor exactly.
    # 2026-06-12 audit-rules probe: the prior `open\s*\([^)]+\)` findall
    # truncated nested-paren calls at the FIRST `)`, so
    # `open(Path.home() / "x.json", encoding="utf-8")` was cut to
    # `open(Path.home()` and counted as missing-encoding — ~20% of that
    # wave's hits were this FP shape. Anchor on the call site and scan to
    # end of line instead (same fix as the bash-security-guard heredoc/
    # inline encoding guards in the paired hook PR).
    for m in re.finditer(r'(?<![\w.])open\s*\(', executed_text):
        line_end = executed_text.find('\n', m.start())
        if line_end == -1:
            line_end = len(executed_text)
        call = executed_text[m.start():line_end]
        if any(b in call for b in _BINARY_MODES):
            continue
        if 'encoding' not in call:
            ctx_start = max(0, m.start() - 100)
            ctx = executed_text[ctx_start:m.start()]
            # Match if any code-context keyword is in the lookback OR
            # if the executed_text itself is short (a single-line
            # Bash("python -c \"open(...)\"") payload has empty pre-context).
            # Without this, short inputs systematically false-negative.
            if (any(kw in ctx for kw in ('def ', 'import ', 'with ', 'data =', 'f =', '.py', '.read(', '.write(', 'json.'))
                    or len(executed_text) < 200):
                tracker.record("encoding-missing-open", session_id, call[:120],
                               category=_classify_open_path(call))

    # V3: inline python -c (complex)
    # Threshold 300 chars: aligned with bash-security-guard's 800-char block.
    # P50 of inline python -c is ~340 chars; below 300 is almost always fine
    # (visible SyntaxError is self-correcting per verify-effectiveness.md).
    for match in re.finditer(r'python3?\s+-c\s+["\'](.{300,})', text):
        tracker.record("inline-python-c", session_id, match.group(0)[:120])

    # V2: Python code blocks (display-only) with print() but no reconfigure.
    # MUST scan display_raw — fences are stripped from the merged `text`.
    # Allow optional trailing chars on the fence line (e.g., `python `,
    # `python {hl_lines=1-2}`) — prior pattern required exact \n after
    # the language tag, silently skipping any fence with trailing space
    # or attributes. Also matches tilde fences (`~~~python`) per
    # CommonMark — both backtick and tilde fences are valid markdown.
    v2_pat = re.compile(r'(?:```|~~~)python[^\n]*\n(.*?)(?:```|~~~)', re.DOTALL)
    for block in v2_pat.findall(display_raw):
        if 'print(' in block and 'reconfigure' not in block and len(block) > 100:
            tracker.record("missing-stdout-reconfigure", session_id,
                           f"Code block ({len(block)} chars)")

    # V6: WebSearch/WebFetch — check tool_names (the literal text-grep was
    # vestigial; tool names aren't in the merged buffer).
    if "WebSearch" in tool_names or "WebFetch" in tool_names:
        tracker.record("websearch-webfetch-used", session_id, "WebSearch/WebFetch")

    # V5: git commit without branch check — fire when executed_text contains
    # `git commit` and lacks any branch-awareness signal.
    # Branch-awareness signals (any one satisfies the rule's intent):
    #   1. `git branch` / `git checkout -b` / `git switch -c` in the same
    #      assistant message. checkout -b CREATES the branch being committed
    #      to — it is the canonical git-hygiene idiom and the exact remedy
    #      bash-security-guard's commit-guard block message prescribes.
    #      2026-06-12 audit-rules wave: 4 of 5 sampled V5 sessions used
    #      `git checkout -b <branch> && git commit` chains and were counted
    #      as violations because only the `git branch` literal matched.
    #   2. Any of those was already observed earlier in the session
    #      (caller passes `session_branch_seen`)
    #   3. A `cd .../worktrees/<branch-named-path>` in the same message —
    #      modern /work workflow: the worktree path IS the branch.
    # Tuned 2026-05-26 after the audit-rules probe showed ~70% of V5 hits
    # in worktree-heavy sessions were false positives.
    if 'git commit' in executed_text:
        has_local_branch_check = _has_branch_awareness(executed_text)
        has_worktree_cd = bool(_V5_WORKTREE_PATH_PATTERN.search(executed_text))
        if not (has_local_branch_check or session_branch_seen or has_worktree_cd):
            tracker.record("git-commit-no-branch-check", session_id,
                           "git commit without branch check")

    # V4: str.replace with \n — only flag when a file-read marker co-occurs
    # within ±500 chars of the match. Matches the gating heuristic used by
    # check_str_replace_crlf in post-write-edit.py, so the scanner metric
    # reflects what the hook actually enforces. Without this gate the
    # detector over-reports ~3x on in-memory string work (e.g. normalizing
    # text read from API responses, not a file).
    # Tightened 2026-04-21 after audit-rules --since 2026-04-20 showed both
    # sampled excerpts were false positives (api response + xlsx cell value).
    for m in _CRLF_REPLACE_PATTERN.finditer(text):
        gate_start = max(0, m.start() - 500)
        gate_end = min(len(text), m.end() + 500)
        if not _FILE_READ_PATTERN.search(text[gate_start:gate_end]):
            continue
        ctx_start = max(0, m.start() - 150)
        ctx_end = min(len(text), m.end() + 150)
        tracker.record("str-replace-crlf-risk", session_id, text[ctx_start:ctx_end])

    # V7: curl_verbose_with_auth_or_secret_header
    # FORBIDDEN in rules/platform-constraints.md: `curl -v` echoes
    # request headers to stdout; combined with -H "Authorization:" etc.
    # this leaks credentials to the session transcript. The hook
    # CURL_VERBOSE_WITH_AUTH guards PreToolUse Bash; this detector
    # measures historical bypass / occurrences across transcripts.
    # The combined pattern requires curl -v AND an auth-bearing -H
    # header within 500 chars on the SAME LINE (no \n between them),
    # which avoids matching doc comments where the two appear on
    # separate lines.
    for m in _CURL_VERBOSE_AUTH_PATTERN.finditer(executed_text):
        ctx_start = max(0, m.start() - 80)
        ctx_end = min(len(executed_text), m.end() + 80)
        tracker.record("curl-verbose-with-auth", session_id,
                       executed_text[ctx_start:ctx_end])
        break  # one match per session is enough

    # V8: pip_install_upgrade_all_outdated
    # FORBIDDEN in rules/platform-constraints.md: `pip install --upgrade`
    # over all-outdated breaks MCP server deps via cascading conflicts.
    # Common shapes:
    #   pip install --upgrade $(pip list --outdated --format=freeze | ...)
    #   pip install --upgrade <pkg1> <pkg2> ... <pkgN>   (5+ at once)
    # Same-line constraint (no \n in the pattern) prevents matching
    # prose / doc comments.
    for m in _PIP_UPGRADE_ALL_PATTERN.finditer(executed_text):
        ctx_start = max(0, m.start() - 50)
        ctx_end = min(len(executed_text), m.end() + 150)
        tracker.record("pip-install-upgrade-all", session_id,
                       executed_text[ctx_start:ctx_end])
        break  # one match per session is enough

    # V9 (subprocess_run_text_true_for_external_apis) intentionally
    # NOT implemented. Prototype showed 73.3% FP rate — the rule's
    # "for external APIs" qualifier is semantic and can't be inferred
    # from regex alone (subprocess.run + text=True is correct for
    # internal CLI shelling). Disabled until a stronger gating signal
    # is available; coverage gap surfaces as a GAP finding via
    # scan_to_findings.py --include-uncovered.


def _extract_code_from_text(text):
    """Extract only code fences from a text block — skip prose discussion."""
    fenced = re.findall(r'```(?:python|bash|sh)?\n(.*?)```', text, re.DOTALL)
    return "\n".join(fenced)


def scan_transcript(filepath, tracker):
    session_id = os.path.basename(filepath).replace('.jsonl', '')
    try:
        f = open(filepath, 'r', encoding='utf-8', errors='replace')
    except OSError as e:
        print(f"  skip {os.path.basename(filepath)}: {e}", file=sys.stderr)
        return
    # Session-level branch-awareness state for V5. Once we've seen
    # `git branch` in any prior assistant message of this session, a later
    # `git commit` is considered branch-aware. Set is monotonic per session.
    session_branch_seen = False
    with f:
        for line in f:
            tracker.lines_scanned += 1
            line = line.strip()
            if not line:
                continue
            # Block signatures land in tool_result content (not assistant
            # messages); check the raw line before the assistant-only filter.
            tracker.note_block_signatures(session_id, line)
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue

            message = entry.get("message", {})
            if not isinstance(message, dict):
                continue
            role = message.get("role", "")
            content = message.get("content", "")

            if role != "assistant" or not isinstance(content, list):
                continue

            display_parts = []        # fences stripped (for merged buffer)
            display_raw_parts = []    # original text with fences (for V3)
            executed_parts = []
            tool_names = set()
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        raw = block.get("text", "")
                        if raw:
                            display_raw_parts.append(raw)
                            code = _extract_code_from_text(raw)
                            if code:
                                display_parts.append(code)
                    elif block.get("type") == "tool_use":
                        name = block.get("name")
                        if name:
                            tool_names.add(name)
                        inp = block.get("input", {})
                        if isinstance(inp, dict):
                            for v in inp.values():
                                if isinstance(v, str):
                                    executed_parts.append(v)
            executed_text = "\n".join(executed_parts)
            display_raw = "\n".join(display_raw_parts)
            text = executed_text + ("\n" + "\n".join(display_parts) if display_parts else "")
            if text or display_raw or tool_names:
                detect_assistant_violations(
                    text, session_id, tracker,
                    executed_text=executed_text,
                    display_raw=display_raw,
                    tool_names=tool_names,
                    session_branch_seen=session_branch_seen,
                )
            # Monotonic latch: once we see any branch-awareness idiom
            # (git branch / checkout -b / switch -c) anywhere in the
            # session, subsequent `git commit`s are branch-aware.
            if not session_branch_seen and _has_branch_awareness(executed_text):
                session_branch_seen = True


def _parse_date(s, arg_name):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: {arg_name} must be YYYY-MM-DD, got {s!r}", file=sys.stderr)
        sys.exit(2)


def discover_transcript_dirs():
    """Return the set of directories that hold .jsonl session transcripts.

    Transcripts are a runtime artifact under ~/.claude/, independent of where
    this script lives. `~/.claude/projects/` holds one subdirectory per cwd,
    name-encoded (e.g. `-home-user-claude-config`). `~/.claude/session-transcripts/`
    is the canonical centralized location when configured. We return every
    subdir of `projects/` that exists plus `session-transcripts/` if present.
    """
    dirs = []
    projects_root = os.path.expanduser("~/.claude/projects")
    if os.path.isdir(projects_root):
        for entry in os.listdir(projects_root):
            full = os.path.join(projects_root, entry)
            if os.path.isdir(full):
                dirs.append(full)
    transcripts_root = os.path.expanduser("~/.claude/session-transcripts")
    if os.path.isdir(transcripts_root):
        dirs.append(transcripts_root)
    return dirs


def main():
    parser = argparse.ArgumentParser(
        description="Scan transcripts for rule violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Post-promotion lifecycle comparison:\n"
            "  --since 2026-04-03 --before 2026-04-17  # pre-promotion window\n"
            "  --since 2026-04-17                      # post-promotion window"
        ),
    )
    parser.add_argument("--days", type=int, default=14, help="Days back to scan (default 14)")
    parser.add_argument("--since", help="Absolute lower bound YYYY-MM-DD (overrides --days)")
    parser.add_argument("--before", help="Absolute upper bound YYYY-MM-DD (exclusive)")
    parser.add_argument("--rule", help="Filter output to a single rule name")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    args = parser.parse_args()

    if args.since:
        since_dt = _parse_date(args.since, "--since")
    else:
        since_dt = datetime.now() - timedelta(days=args.days)
    before_dt = _parse_date(args.before, "--before") if args.before else None

    transcript_dirs = discover_transcript_dirs()
    if not transcript_dirs:
        print(
            "ERROR: no transcript directories found. Looked for "
            "~/.claude/projects/*/ and ~/.claude/session-transcripts/. "
            "Either there are no sessions yet, or Claude is configured to "
            "store transcripts elsewhere.",
            file=sys.stderr,
        )
        sys.exit(1)

    files = []
    for d in transcript_dirs:
        for f in glob.glob(os.path.join(d, "*.jsonl")):
            mtime = datetime.fromtimestamp(os.path.getmtime(f))
            if mtime < since_dt:
                continue
            if before_dt is not None and mtime >= before_dt:
                continue
            files.append(f)

    seen = set()
    unique = []
    for f in files:
        base = os.path.basename(f)
        if base not in seen:
            seen.add(base)
            unique.append(f)

    if not unique:
        print(
            f"WARN: 0 transcripts in window "
            f"{since_dt.date()} → {before_dt.date() if before_dt else 'now'} "
            f"(searched {len(transcript_dirs)} dir(s)).",
            file=sys.stderr,
        )

    # Resolve repo root: scripts at skills/audit-rules/references/X.py
    # → parents[3] is the repo root. Tolerate execution from either
    # the source repo or the deployed ~/.claude/ symlink.
    from pathlib import Path as _Path
    repo_root = _Path(__file__).resolve().parents[3]
    suppressions = _load_suppressions(repo_root)
    tracker = ViolationTracker(suppressions=suppressions)
    tracker.scan_window = (since_dt, before_dt or datetime.now())
    for i, fp in enumerate(unique):
        tracker.sessions_scanned += 1
        tracker.session_mtimes[os.path.basename(fp).replace(".jsonl", "")] = (
            datetime.fromtimestamp(os.path.getmtime(fp))
        )
        scan_transcript(fp, tracker)
        if (i + 1) % 100 == 0:
            print(f"  ...{i+1}/{len(unique)}", file=sys.stderr)

    window_label = (
        f"{since_dt.date()} → {before_dt.date() if before_dt else 'now'}"
    )

    # Zero-hit ALL_RULES detectors are included (count 0) so the report
    # distinguishes "measured clean" from "detector absent".
    rule_items = list(tracker.counts.most_common())
    rule_items += [(r, 0) for r in ALL_RULES if r not in tracker.counts]
    if args.rule:
        rule_items = [(r, c) for r, c in rule_items if r == args.rule]

    if args.json:
        data = tracker.to_dict(include_all_rules=True)
        if args.rule:
            data["violations"] = {
                r: v for r, v in data["violations"].items() if r == args.rule
            }
        print(json.dumps(data, indent=2, default=str))
    else:
        print(f"Window: {window_label}")
        print(f"Sessions: {tracker.sessions_scanned} | Lines: {tracker.lines_scanned:,}")
        if args.rule and not rule_items:
            print(f"\n(rule {args.rule!r} is not a known detector and recorded no violations)")
            return
        print(f"\n{'Rule':<40s} {'Count':>6s} {'Sessions':>10s} {'Rate':>8s}  Net-silent / block-then-fix")
        print("-" * 100)
        for rule, count in rule_items:
            sessions = len(tracker.sessions_with_violations[rule])
            rate = sessions / tracker.sessions_scanned * 100 if tracker.sessions_scanned else 0
            if rule in RULE_BLOCK_SIGNATURES:
                blocked = len(tracker.sessions_with_violations[rule]
                              & tracker.sessions_with_block_sig[rule])
                net = sessions - blocked
                net_rate = net / tracker.sessions_scanned * 100 if tracker.sessions_scanned else 0
                extra = f"net-silent {net} ({net_rate:.1f}%); {blocked} blocked-then-fixed"
            else:
                extra = "—  (no guard signature mapped)"
            print(f"  {rule:<38s} {count:6d} {sessions:10d} {rate:7.1f}%  {extra}")


if __name__ == "__main__":
    main()
