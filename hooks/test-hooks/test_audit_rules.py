"""Regression tests for skills/audit-rules/ scripts.

These backstop the failure modes that drove the recent repair:
  - V3/V4/V5 detectors silently broke in PR #947 when the
    executed-vs-display split was added but only V1 was updated.
  - PostToolUse hooks were mis-classified as warn-only despite
    emitting `decision: "block"`.
  - Rule-name extraction grabbed the conventional-commit scope
    (e.g. `bulk-api-script`) instead of the actual rule.

If a future refactor reintroduces any of these, CI fails here.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REFS = REPO_ROOT / "skills" / "audit-rules" / "references"


def _load(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, REFS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scanner():
    return _load("audit_scanner", "scan_violations.py")


@pytest.fixture(scope="module")
def lifecycle():
    return _load("audit_lifecycle", "lifecycle_check.py")


@pytest.fixture
def tracker(scanner):
    return scanner.ViolationTracker()


def _detect(scanner, tracker, *, executed="", display="", tools=None, session="s"):
    """Invoke the detector with explicit streams. Mirrors the production
    scanner's merge: `text` contains executed_text + fence-stripped code,
    while `display_raw` carries the original (fenced) display text. Tests
    that pass `display` here are checking the display path correctly —
    if V3 ever reverts to reading `text`, the fences won't be there to
    match, and tests fail."""
    stripped = scanner._extract_code_from_text(display) if display else ""
    text = executed + (("\n" + stripped) if stripped else "")
    scanner.detect_assistant_violations(
        text, session, tracker,
        executed_text=executed,
        display_raw=display,
        tool_names=tools or set(),
    )


# ── V1: encoding-missing-open (executed code only) ──


def test_v1_open_without_encoding_flags(scanner, tracker):
    _detect(scanner, tracker, executed=(
        "import json\n"
        "def load():\n"
        "    f = open('/tmp/data.json')\n"
        "    return json.load(f)\n"
    ))
    assert tracker.counts["encoding-missing-open"] >= 1


def test_v1_binary_mode_skipped(scanner, tracker):
    _detect(scanner, tracker, executed="data = open('/tmp/x.bin', 'rb').read()")
    assert tracker.counts["encoding-missing-open"] == 0


def test_v1_encoding_present_skipped(scanner, tracker):
    _detect(scanner, tracker, executed="f = open('/tmp/x.txt', encoding='utf-8')")
    assert tracker.counts["encoding-missing-open"] == 0


def test_v1_display_only_must_not_fire(scanner, tracker):
    """Calibration intent of PR #947: display fences are not executed code."""
    _detect(scanner, tracker,
            display="```python\nf = open('/tmp/data.json')\n```")
    assert tracker.counts["encoding-missing-open"] == 0


def test_v1_urlopen_not_flagged(scanner, tracker):
    """urlopen()/fdopen() are not file opens and can't take encoding=. The
    (?<!\\w)open\\s*\\( regex must skip them, matching post-write-edit.py's
    hook. Prior bare open\\( regex counted `urlopen(req, ...)` as a FP and
    inflated the encoding-missing-open rate (audit-rules 2026-05-29)."""
    _detect(scanner, tracker, executed=(
        "import urllib.request\n"
        "resp = urllib.request.urlopen(req, timeout=10)\n"
    ))
    assert tracker.counts["encoding-missing-open"] == 0


# ── V2: inline python -c (>300 chars) ──


def test_v2_long_inline_python_c_flags(scanner, tracker):
    body = "import json; " * 30 + "print('hi')"
    _detect(scanner, tracker, executed=f'python3 -c "{body}"')
    assert tracker.counts["inline-python-c"] >= 1


def test_v2_short_inline_python_c_skipped(scanner, tracker):
    _detect(scanner, tracker, executed='python3 -c "print(1)"')
    assert tracker.counts["inline-python-c"] == 0


# ── V3: missing-stdout-reconfigure (display fences) ──
# REGRESSION GUARD: V3 must read display_raw, not the fence-stripped buffer.


def test_v3_display_python_print_no_reconfigure_flags(scanner, tracker):
    block = (
        "Here is a script:\n"
        "```python\n"
        "import sys\n"
        "def compute(x):\n"
        "    result = x * 2 + 1\n"
        "    print(f'value: {result}')\n"
        "    return result\n"
        "for i in range(10):\n"
        "    compute(i)\n"
        "```\n"
    )
    _detect(scanner, tracker, display=block)
    assert tracker.counts["missing-stdout-reconfigure"] >= 1, (
        "V3 didn't fire on a display-only Python block with print() and no "
        "reconfigure. PR #947 stripped fences from the merged buffer; V3 "
        "must read display_raw separately."
    )


def test_v3_with_reconfigure_skipped(scanner, tracker):
    block = (
        "```python\nimport sys\nsys.stdout.reconfigure(encoding='utf-8')\n"
        + "print('x') " * 30 + "\n```"
    )
    _detect(scanner, tracker, display=block)
    assert tracker.counts["missing-stdout-reconfigure"] == 0


def test_v3_short_block_skipped(scanner, tracker):
    _detect(scanner, tracker, display="```python\nprint('hi')\n```")
    assert tracker.counts["missing-stdout-reconfigure"] == 0


# ── V4: websearch-webfetch-used (tool names, not text grep) ──
# REGRESSION GUARD: the vestigial `"WebSearch" in text` check was replaced.


def test_v4_websearch_via_tool_names_flags(scanner, tracker):
    _detect(scanner, tracker, executed="anything", tools={"WebSearch"})
    assert tracker.counts["websearch-webfetch-used"] >= 1


def test_v4_webfetch_via_tool_names_flags(scanner, tracker):
    _detect(scanner, tracker, executed="anything", tools={"WebFetch"})
    assert tracker.counts["websearch-webfetch-used"] >= 1


def test_v4_other_tools_skipped(scanner, tracker):
    _detect(scanner, tracker, executed="foo", tools={"Bash", "Write"})
    assert tracker.counts["websearch-webfetch-used"] == 0


# ── V5: git-commit-no-branch-check ──
# REGRESSION GUARD: the vestigial `"Bash"` literal gate was removed.


def test_v5_git_commit_alone_flags(scanner, tracker):
    _detect(scanner, tracker, executed="git commit -m 'fix'", tools={"Bash"})
    assert tracker.counts["git-commit-no-branch-check"] >= 1


def test_v5_branch_check_present_skipped(scanner, tracker):
    _detect(scanner, tracker,
            executed="git branch --show-current\ngit commit -m 'fix'",
            tools={"Bash"})
    assert tracker.counts["git-commit-no-branch-check"] == 0


def test_v5_worktree_path_cwd_satisfies_branch_check(scanner, tracker):
    """A cd into a /worktrees/<name>/ directory IS branch awareness — the
    worktree path is the branch disambiguator under /work workflow.
    (2026-05-26 audit-rules probe: ~70% of session 100cf57e V5 hits were
    worktree-path commits.)"""
    _detect(scanner, tracker, executed=(
        "cd \"C:/Users/you/worktrees/claude-config-fix-v5\" && "
        "git commit -m 'fix'"
    ), tools={"Bash"})
    assert tracker.counts["git-commit-no-branch-check"] == 0


def test_v5_session_branch_seen_latches_skips_later_commit(scanner, tracker):
    """Once `git branch` is seen in any prior assistant message of the
    session, later `git commit`s are branch-aware. Prior V5 logic missed
    this and over-fired ~69% on multi-message ship flows."""
    scanner.detect_assistant_violations(
        "git branch --show-current", "s",
        tracker, executed_text="git branch --show-current",
        display_raw="", tool_names={"Bash"},
        session_branch_seen=False,
    )
    # Second message: bare commit, but session-level branch awareness latched.
    scanner.detect_assistant_violations(
        "git commit -m 'fix'", "s",
        tracker, executed_text="git commit -m 'fix'",
        display_raw="", tool_names={"Bash"},
        session_branch_seen=True,
    )
    assert tracker.counts["git-commit-no-branch-check"] == 0


# ── V6: str-replace-crlf-risk (gated by file read) ──


def test_v6_replace_with_file_read_flags(scanner, tracker):
    code = (
        "with open('/tmp/data.txt', 'r', encoding='utf-8') as f:\n"
        "    text = f.read()\n"
        "cleaned = text.replace('\\n', ' ')\n"
    )
    _detect(scanner, tracker, executed=code, tools={"Write"})
    assert tracker.counts["str-replace-crlf-risk"] >= 1


def test_v6_replace_without_file_read_skipped(scanner, tracker):
    """In-memory string work should not flag (2026-04-21 false-positive case)."""
    code = "response = api_call()\ntext = response.text.replace('\\n', ' ')\n"
    _detect(scanner, tracker, executed=code)
    assert tracker.counts["str-replace-crlf-risk"] == 0


# ── Lifecycle / promotion-commit parsing ──


def test_lifecycle_assess_boundaries(lifecycle):
    assert lifecycle.assess(40.0, 25.0) == "OK"
    assert lifecycle.assess(40.0, 28.0) == "OK"
    assert lifecycle.assess(40.0, 29.0) == "INEFFECTIVE"
    assert lifecycle.assess(None, 20.0) == "INCONCLUSIVE"
    assert lifecycle.assess(20.0, None) == "INCONCLUSIVE"
    assert lifecycle.assess(0.0, 0.0) == "INCONCLUSIVE"


@pytest.mark.parametrize("subject", [
    "feat(bulk-api-script): embed str-replace-crlf-risk rule",
    "feat(ship): promote git-branch-check from prompt-only",
    "chore(audit-rules): skill-enforced verify-effectiveness step",
    "fix(post-write-edit): hook-enforce encoding-missing-open",
    "distill(superplan): embed topic loading step",
])
def test_promotion_subject_positive(lifecycle, subject):
    matched, _ = lifecycle._is_promotion(subject)
    assert matched, f"should match {subject!r}"


@pytest.mark.parametrize("subject", [
    "fix(scout-skills): resolve $HOME literal-path bug",
    "chore: routine refactor",
    "feat(healthcheck): orphan helper",
])
def test_promotion_subject_negative(lifecycle, subject):
    matched, _ = lifecycle._is_promotion(subject)
    assert not matched, f"should NOT match {subject!r}"


def test_rule_name_extraction_skips_scope(lifecycle):
    """REGRESSION: scope `bulk-api-script` must not be extracted as the rule."""
    subject = "feat(bulk-api-script): embed str-replace-crlf-risk rule as Step 5"
    _, body = lifecycle._is_promotion(subject)
    candidates = [
        n for n in lifecycle.RULE_NAME.findall(body)
        if n not in lifecycle.COMMON_WORDS
        and "-" in n
        and n in lifecycle.REAL_RULE_NAMES
    ]
    assert candidates and candidates[0] == "str-replace-crlf-risk"


def test_rule_name_extraction_rejects_noise_tokens(lifecycle):
    """REGRESSION 2026-05-26: noise tokens like `snapshot-aware` and
    `high-rate` were leaking through the kebab-case filter and being
    treated as rule names — silently making every promotion verdict
    INCONCLUSIVE. The allowlist against REAL_RULE_NAMES rejects them."""
    subject = "feat(chunk-drop-guard): snapshot-aware logic + promote to BLOCK"
    _, body = lifecycle._is_promotion(subject)
    candidates = [
        n for n in lifecycle.RULE_NAME.findall(body)
        if n not in lifecycle.COMMON_WORDS
        and "-" in n
        and n in lifecycle.REAL_RULE_NAMES
    ]
    # Should produce no inferred rule name — neither "snapshot-aware" nor
    # "chunk-drop-guard" is a real rule.
    assert candidates == [], f"noise leaked through: {candidates}"


def test_rule_name_extraction_accepts_real_rule(lifecycle):
    """A subject naming a real rule from rules/*.md is accepted."""
    subject = "feat(ship): promote diagnose-before-fix from prompt-only"
    _, body = lifecycle._is_promotion(subject)
    candidates = [
        n for n in lifecycle.RULE_NAME.findall(body)
        if "-" in n
        and n in lifecycle.REAL_RULE_NAMES
    ]
    assert candidates == ["diagnose-before-fix"], candidates


def test_real_rule_names_includes_scanner_detectors(lifecycle):
    """The allowlist must include scanner detector names so promotions
    referencing detectors (str-replace-crlf-risk, encoding-missing-open)
    can still be measured even if no rules/*.md file shares the name."""
    expected = {
        "str-replace-crlf-risk", "encoding-missing-open",
        "inline-python-c", "websearch-webfetch-used",
    }
    assert expected.issubset(lifecycle.REAL_RULE_NAMES)


# ── classify_rules: source-based hook strength ──


def test_classify_rules_post_write_edit_is_enforced():
    """REGRESSION: PostToolUse hooks that emit `decision: "block"` are
    hook-enforced, not warn-only (the old PreToolUse/PostToolUse heuristic
    mis-labeled them).

    2026-08-22 update: the encoding rule is EXEMPT off-Windows — it was
    deliberately demoted 2026-06-27 (AUDIT-TRACKERS/demotions.yaml, scope
    non-win32), so the classifier now reports it hook-warned (demoted …)
    there by design. The block-signal-detection regression this test
    exists for stays pinned by post-write-edit's other three rules, which
    must remain hook-enforced everywhere."""
    out = subprocess.check_output(
        [sys.executable, str(REFS / "classify_rules.py"), "--json"],
        cwd=str(REPO_ROOT), encoding="utf-8",
    )
    data = json.loads(out)
    pwe = [r for r in data["rules"] if r["hook_or_skill"] == "post-write-edit.py"]
    assert pwe, "post-write-edit.py should appear in HOOK_RULE_MAP"
    encoding_rule = "Block Python scripts missing encoding='utf-8' in open()"
    for r in pwe:
        if r["rule"] == encoding_rule and sys.platform != "win32":
            assert r["layer"].startswith("hook-warned (demoted"), (
                f"encoding rule should report its ledgered demotion "
                f"off-Windows, got {r['layer']!r}"
            )
            continue
        assert r["layer"].startswith("hook-enforced"), (
            f"post-write-edit.py mis-classified as {r['layer']!r}. "
            f"Check whether it still emits `decision: \"block\"` and that "
            f"hook_strength() still detects the signal."
        )


def test_classify_rules_summary_has_expected_floors():
    out = subprocess.check_output(
        [sys.executable, str(REFS / "classify_rules.py"), "--json"],
        cwd=str(REPO_ROOT), encoding="utf-8",
    )
    summary = json.loads(out)["summary"]
    assert summary["hook_enforced"] >= 2, summary
    assert summary["skill_enforced"] >= 5, summary
    assert summary["total_rule_lines"] >= 20, (
        f"Expected ≥20 rule lines; got {summary['total_rule_lines']}. "
        f"Either rules/ shrank dramatically or RULES_DIR didn't resolve."
    )


# ── Full pipeline: synthetic transcript → scanner CLI → all 6 detectors ──


def test_scanner_full_pipeline_detects_all_six(tmp_path):
    """End-to-end: write a fixture with all six patterns, scan it via the
    real CLI, assert every detector fires. This is the headline backstop
    for PR #947-style silent regressions."""
    home = tmp_path / "home"
    transcripts = home / ".claude" / "session-transcripts"
    transcripts.mkdir(parents=True)

    long_body = "import json; " * 30 + "print('x')"
    print_block = "print('x') " * 25
    events = [
        # V1
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write", "input": {
                "file_path": "/tmp/x.py",
                "content": (
                    "import json\n"
                    "def load():\n"
                    "    f = open('/tmp/data.json')\n"
                    "    return json.load(f)\n"
                ),
            }}
        ]}},
        # V2
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": f'python3 -c "{long_body}"'}}
        ]}},
        # V3 (display-only)
        {"message": {"role": "assistant", "content": [
            {"type": "text", "text": (
                "Here is a script:\n```python\n"
                "import sys\n"
                "def compute(x):\n"
                f"    {print_block}\n"
                "    return x\n"
                "for i in range(10):\n    compute(i)\n```\n"
            )}
        ]}},
        # V4
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "x"}}
        ]}},
        # V5
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "git commit -m 'x'"}}
        ]}},
        # V6
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write", "input": {
                "file_path": "/tmp/y.py",
                "content": (
                    "with open('/tmp/data.txt', encoding='utf-8') as f:\n"
                    "    text = f.read()\n"
                    "cleaned = text.replace('\\n', ' ')\n"
                ),
            }}
        ]}},
    ]
    fixture = transcripts / "fixture-test.jsonl"
    with fixture.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    # USERPROFILE alongside HOME — CPython's `ntpath.expanduser` (Windows)
    # ignores HOME and reads USERPROFILE; `posixpath.expanduser` (Linux,
    # macOS) reads HOME. Setting both makes `pathlib.Path.home()` resolve
    # to `home` on every platform. Same fix shape as PR #982 marker
    # round-trip (see rules/incidents/eval-shipping-discipline.md and
    # rules/platform-constraints.md).
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    out = subprocess.check_output(
        [sys.executable, str(REFS / "scan_violations.py"), "--days", "365", "--json"],
        encoding="utf-8", env=env,
    )
    data = json.loads(out)
    detected = set(data["violations"].keys())
    expected = {
        "encoding-missing-open",
        "inline-python-c",
        "missing-stdout-reconfigure",
        "websearch-webfetch-used",
        "git-commit-no-branch-check",
        "str-replace-crlf-risk",
    }
    missing = expected - detected
    assert not missing, (
        f"Detectors silently broke: {sorted(missing)}. This is the exact "
        f"PR #947 failure mode. Check scan_violations.detect_assistant_violations."
    )
