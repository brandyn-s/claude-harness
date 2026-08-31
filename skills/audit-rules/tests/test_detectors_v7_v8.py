"""Tests for V7 (curl-verbose-with-auth) and V8 (pip-install-upgrade-all)
detectors in scan_violations.py.

These detectors close the coverage gap on two rules.platform-constraints
FORBIDDEN entries that had no scanner before Phase 7:

  - V7: curl -v + auth header → secret leak in transcript
  - V8: pip install --upgrade over many packages → MCP server breakage

V9 (subprocess.run text=True for external APIs) was prototyped but
disabled — 73.3% FP rate from internal-CLI shelling. These tests
also pin that V9 is intentionally absent.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCANNER = REPO / "skills" / "audit-rules" / "references" / "scan_violations.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("scan_violations", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── V7: curl_verbose_with_auth ───────────────────────────────────

def test_v7_fires_on_curl_v_with_authorization_same_line():
    """The canonical failure case from the 2026-05-01 OPENAI_API_KEY
    incident: curl -v with Authorization header on a single line."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = (
        'curl -v -H "Authorization: Bearer $OPENAI_API_KEY" '
        'https://api.openai.com/v1/models'
    )
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 1


def test_v7_fires_on_verbose_long_form():
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = 'curl --verbose -H "X-API-Key: $KEY" https://api.example.com'
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 1


def test_v7_fires_on_cookie_header():
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = 'curl -v -H "Cookie: session=$SESSION_TOKEN" https://example.com'
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 1


def test_v7_does_not_fire_on_curl_without_auth():
    """Plain curl -v on a public endpoint is documented-safe per the rule."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = 'curl -v https://httpbin.org/get'
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 0


def test_v7_does_not_fire_on_auth_without_verbose():
    """curl with Authorization but NO -v is fine — headers don't print."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = 'curl -H "Authorization: Bearer $KEY" https://api.example.com'
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 0


def test_v7_does_not_fire_when_curl_and_auth_on_different_lines():
    """The same-line constraint avoids prose/comment false-positives.
    Two separate commands on separate lines should NOT match."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = (
        'curl -v https://httpbin.org/get\n'
        '# elsewhere: -H "Authorization: token"'
    )
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 0


def test_v7_fires_on_trace_flags():
    """--trace, --trace-ascii, --trace-time all log requests with headers."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = 'curl --trace-ascii /tmp/log -H "Authorization: Bearer x" https://api'
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 1


# ─── V8: pip_install_upgrade_all ───────────────────────────────────

def test_v8_fires_on_pip_upgrade_outdated_substitution():
    """Shape 1: --upgrade $(pip list --outdated ...) — the original
    forbidden anti-pattern from platform-constraints.md."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = "pip install --upgrade $(pip list --outdated --format=freeze | cut -d= -f1)"
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("pip-install-upgrade-all", 0) == 1


def test_v8_fires_on_pip_upgrade_many_packages():
    """Shape 2: --upgrade pkg1 pkg2 ... pkgN with 5+ packages."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = "pip install --upgrade httpx pydantic requests urllib3 anyio fastmcp"
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("pip-install-upgrade-all", 0) == 1


def test_v8_fires_with_short_flag():
    """-U is shorthand for --upgrade and should still match."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = "pip install -U httpx pydantic requests urllib3 anyio fastmcp"
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("pip-install-upgrade-all", 0) == 1


def test_v8_does_not_fire_on_single_package_upgrade():
    """Single-package upgrades are allowed per the rule."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = "pip install --upgrade fastmcp"
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("pip-install-upgrade-all", 0) == 0


def test_v8_does_not_fire_on_normal_install():
    """pip install without --upgrade is fine."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = "pip install httpx pydantic requests urllib3 anyio fastmcp"
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("pip-install-upgrade-all", 0) == 0


def test_v8_does_not_fire_when_upgrade_and_install_on_different_lines():
    """Same-line constraint avoids prose matching."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = (
        "Background:\n"
        "We avoid pip install for security reasons.\n"
        "Don't use --upgrade a b c d e f without thinking.\n"
    )
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("pip-install-upgrade-all", 0) == 0


def test_v8_pip3_also_matches():
    """pip3 is functionally equivalent to pip on this system."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = "pip3 install --upgrade $(pip3 list --outdated | awk 'NR>2 {print $1}')"
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("pip-install-upgrade-all", 0) == 1


# ─── V9: explicitly disabled ───────────────────────────────────

def test_v9_is_not_present_in_detector():
    """V9 (subprocess.run text=True) was prototyped and disabled at
    73.3% FP rate. The detector intentionally omits it. If a future
    edit re-enables V9, this test ensures the omission was deliberate."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    # subprocess.run + text=True — the rule's surface, but cannot be
    # distinguished from internal CLI shelling without semantic analysis.
    payload = 'subprocess.run([cmd], capture_output=True, text=True)'
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("subprocess-run-text-true", 0) == 0


def test_v9_pattern_constant_not_defined():
    """The pattern constant was removed; if it comes back, this test
    fails so the operator must re-evaluate the FP rate."""
    sv = _load_scanner()
    assert not hasattr(sv, "_SUBPROCESS_TEXT_TRUE_PATTERN"), (
        "V9 _SUBPROCESS_TEXT_TRUE_PATTERN was disabled at 73% FP rate; "
        "if it's back, validate with a fresh known-positive sample first."
    )


# ─── Cross-detector smoke ──────────────────────────────────────────

def test_v7_and_v8_can_both_fire_in_one_message():
    """Independent detectors should both fire when both patterns
    occur in the same executed text."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    payload = (
        'curl -v -H "Authorization: Bearer X" https://api\n'
        'pip install --upgrade httpx pydantic requests urllib3 anyio'
    )
    sv.detect_assistant_violations(payload, "s1", t, executed_text=payload)
    assert t.counts.get("curl-verbose-with-auth", 0) == 1
    assert t.counts.get("pip-install-upgrade-all", 0) == 1
