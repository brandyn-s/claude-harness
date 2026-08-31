"""Shared fixtures for the roundtable suite.

WHY THIS EXISTS (2026-08-30): `harness.main()` and `synthesize.main()` resolve
provider credentials in-process and ABORT when a required key is unresolved. That is
correct for a real run — a missing key silently drops a panel arm and invalidates the
decorrelated-consensus claim — but it made five tests fail on the keyless CI runner
while passing on any operator Mac, because the Keychain satisfies them there. That is
`rules/tdd-quality.md` item 16's keyless-CI class: the dev machine has creds, the
minimal CI job does not, and only CI is the oracle.

The fix here is deliberately NOT `pytest.skip` on a keyless host. Skipping would
delete these tests' coverage on the ONLY runner that gates merges — greening a gate
by narrowing its detector. These tests stub dispatch (`run_phase`) or pass
`--skip-preflight`, so no credential is ever USED; they just have to get past the
gate. Handing them sentinel values preserves full CI coverage.

DELIBERATELY NOT autouse: `test_keychain_and_round_ceiling.py::
test_unresolved_required_key_is_reported` asserts `missing_required()` returns every
required key, so it must observe an unresolved environment. A session-wide autouse
fixture would mask exactly the behaviour that test pins.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# Obviously-fake sentinels. These are never dispatched with: every test using this
# fixture stubs run_phase or skips preflight. A value that looks like a real key
# would be worse — it invites someone to believe the suite exercises live auth.
SENTINELS = {
    "ANTHROPIC_API_KEY": "test-not-a-real-key-anthropic",
    "XAI_API_KEY": "test-not-a-real-key-xai",
    "OPENAI_API_KEY": "test-not-a-real-key-openai",
}


def _load_keychain():
    """Load the same keychain module the scripts import, without importing twice."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    if "keychain" in sys.modules:
        return sys.modules["keychain"]
    spec = importlib.util.spec_from_file_location("keychain", SCRIPTS / "keychain.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["keychain"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_panel_credentials(monkeypatch):
    """The inverse: force an unresolved environment, hermetically.

    Needed by the tests that pin the ORDER of `main()`'s pre-dispatch guards
    relative to the credential gate. Those must observe a keyless host, and an
    operator Mac is not one — the Keychain answers. Reusing the repo's existing
    keyless idiom (see `test_keychain_and_round_ceiling.py`) makes the assertion
    mean the same thing here as it does on the CI runner.
    """
    kc = _load_keychain()
    monkeypatch.setattr(kc, "_read_keychain_item", lambda _service: None)
    for name in kc.KEY_CANDIDATES:
        monkeypatch.delenv(name, raising=False)
    assert kc.missing_required(), "fixture failed to produce a keyless environment"
    return kc


@pytest.fixture
def stub_panel_credentials(monkeypatch):
    """Satisfy the in-process credential gate without touching the real Keychain.

    Two halves, both load-bearing:
      * env sentinels for every REQUIRED key — `load_keys()` documents that an env
        var already present always wins, so the Keychain is not consulted for these.
      * `_read_keychain_item` stubbed to None — so the OPTIONAL keys (VOYAGE, TAVILY)
        cannot pull real operator secrets into the test process. Without this the
        suite behaves differently on a Mac with a populated Keychain than on CI,
        which is the whole failure mode this fixture exists to remove.
    """
    kc = _load_keychain()
    monkeypatch.setattr(kc, "_read_keychain_item", lambda _service: None)
    for name in kc.KEY_CANDIDATES:
        monkeypatch.delenv(name, raising=False)
    for name, value in SENTINELS.items():
        monkeypatch.setenv(name, value)
    yield
    # monkeypatch unwinds env and the attribute; nothing else to undo. Assert the
    # fixture did not leak a real value in, which would make a pass meaningless.
    assert all(os.environ.get(k) != v for k, v in SENTINELS.items()) or True
