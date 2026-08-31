"""Unit tests for probe_models.py decision logic (network + keychain mocked).

Covers the P0 red-team fixes (2026-07-05):
  - silent slug-redirect (xAI May-15 rebill shape) -> ok=False
  - 401/403 -> AUTH FAILURE, NOT retirement
  - missing 'id' (schema drift) -> not a vacuous PRESENT
  - version/fingerprint surfaced for same-slug weight-swap detection
  - Gemini full pagination (follows nextPageToken; no page-1-only truncation)
"""
import importlib.util
import io
import json
import pathlib
import sys

_SPEC = importlib.util.spec_from_file_location(
    "probe_models",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "probe_models.py",
)
assert _SPEC is not None and _SPEC.loader is not None
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def run(argv, get_impl):
    # Patch resolve_key (the actual key resolver) — NOT the old `keychain` name.
    # Without this, a CI runner with no GEMINI_API_KEY/Keychain hits the
    # real resolver -> None -> sys.exit(2) to stderr -> empty stdout, and the
    # tests pass only on a machine that happens to have the keys.
    setattr(probe, "resolve_key", lambda _s: "test-key")
    setattr(probe, "get", get_impl)
    sys.argv = ["probe_models.py"] + argv
    out, code = io.StringIO(), 0
    old = sys.stdout
    sys.stdout = out
    try:
        probe.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdout = old
    return out.getvalue(), code


def test_canonical_present_exit0():
    txt, code = run(["xai", "grok-4.3"],
                    lambda u, h: (200, json.dumps({"id": "grok-4.3", "version": "1.0", "fingerprint": "fp_x"}).encode()))
    assert "grok-4.3: PRESENT (canonical)" in txt
    assert "version=1.0" in txt and "fingerprint=fp_x" in txt  # weight-swap surface
    assert code == 0


def test_silent_redirect_exit1():
    txt, code = run(["xai", "grok-3"],
                    lambda u, h: (200, json.dumps({"id": "grok-4.3"}).encode()))
    assert "SILENT REDIRECT" in txt and "grok-4.3" in txt
    assert code == 1


def test_auth_failure_is_transient_exit2_not_retirement():
    # 401/403 must NOT abort a preflight (it's a key problem) -> exit 2, not 1.
    txt, code = run(["openai", "gpt-5.5-pro"], lambda u, h: (401, b"{}"))
    assert "AUTH FAILURE" in txt and "NOT retirement" in txt
    assert "RETIREMENT candidate" not in txt
    assert code == 2


def test_429_is_transient_exit2():
    txt, code = run(["openai", "gpt-5.5-pro"], lambda u, h: (429, b"{}"))
    assert "RATE LIMITED" in txt and code == 2


def test_5xx_is_transient_exit2():
    txt, code = run(["xai", "grok-4.3"], lambda u, h: (503, b"{}"))
    assert "5xx" in txt and code == 2


def test_404_is_retirement_exit1():
    txt, code = run(["openai", "gpt-old"], lambda u, h: (404, b"{}"))
    assert "RETIREMENT candidate" in txt
    assert code == 1


def test_grok_alias_maps_to_xai():
    # The skill's Step 2 passes the token 'grok'; the probe must accept it.
    txt, code = run(["grok", "grok-4.3"], lambda u, h: (200, json.dumps({"id": "grok-4.3"}).encode()))
    assert "grok-4.3: PRESENT (canonical)" in txt
    assert code == 0


def test_unknown_vendor_is_infra_exit2():
    txt, code = run(["bogus"], lambda u, h: (200, b"{}"))
    assert code == 2  # usage error is infra, not a retirement finding


def test_missing_id_is_schema_drift_not_vacuous_present():
    txt, code = run(["xai", "grok-4.3"], lambda u, h: (200, json.dumps({"object": "model"}).encode()))
    assert "SCHEMA DRIFT" in txt
    assert "PRESENT (canonical)" not in txt
    assert code == 1


def test_gemini_follows_pagination():
    pages = {
        None: {"models": [{"name": f"models/m{i}"} for i in range(200)], "nextPageToken": "T2"},
        "T2": {"models": [{"name": "models/gemini-9-pro-preview"}]},
    }
    def get_impl(url, headers):
        tok = "T2" if "pageToken=T2" in url else None
        return 200, json.dumps(pages[tok]).encode()
    txt, code = run(["gemini", "gemini-9-pro-preview"], get_impl)
    assert "201 models across 2 page(s)" in txt   # page-1-only would have missed it
    assert "gemini-9-pro-preview: PRESENT" in txt
    assert code == 0


def test_gemini_missing_pin_exit1():
    body = json.dumps({"models": [{"name": "models/gemini-3.1-pro-preview"}]}).encode()
    txt, code = run(["gemini", "gemini-gone"], lambda u, h: (200, body))
    assert "gemini-gone: MISSING" in txt
    assert code == 1


def test_gemini_no_pin_is_not_a_pass():
    # A currency check that verified nothing must not exit 0 (the flagship no-op bug).
    body = json.dumps({"models": [{"name": "models/gemini-3.1-pro-preview"}]}).encode()
    txt, code = run(["gemini"], lambda u, h: (200, body))
    assert "NO flagship pin passed" in txt
    assert code == 1


def test_gemini_page_cap_tripwire():
    # A never-terminating pageToken loop must trip the cap -> transient(2), not hang/false-OK.
    def get_impl(url, headers):
        return 200, json.dumps({"models": [{"name": "models/x"}], "nextPageToken": "always"}).encode()
    txt, code = run(["gemini", "gemini-3.1-pro-preview"], get_impl)
    assert "TRIPWIRE" in txt and code == 2
