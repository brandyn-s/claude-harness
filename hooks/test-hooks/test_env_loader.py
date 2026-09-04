"""Unit tests for env_loader's secret resolution (Keychain + env var)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import env_loader as mod  # noqa: E402


class _FakeResult:
    def __init__(self, returncode=0, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def test_keychain_get_is_darwin_only(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call security off-darwin")),
    )
    assert mod._keychain_get("ANY") is None


def test_keychain_get_respects_opt_out(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setenv("CLAUDE_KEYCHAIN_SECRETS", "0")
    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("opt-out must not call security")),
    )
    assert mod._keychain_get("ANY") is None


def test_keychain_get_success(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_KEYCHAIN_SECRETS", raising=False)
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return _FakeResult(returncode=0, stdout=b"s3cret\n")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._keychain_get("MY_TOKEN") == "s3cret"
    # Service name carries the claude/ prefix; -w keeps output to the value.
    assert calls["cmd"][:2] == ["security", "find-generic-password"]
    assert "claude/MY_TOKEN" in calls["cmd"]


def test_keychain_get_missing_item_returns_none(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_KEYCHAIN_SECRETS", raising=False)
    monkeypatch.setattr(
        mod.subprocess, "run", lambda *a, **k: _FakeResult(returncode=44, stdout=b"")
    )
    assert mod._keychain_get("MISSING") is None


def test_keychain_get_swallows_security_absence(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_KEYCHAIN_SECRETS", raising=False)

    def boom(*a, **k):
        raise FileNotFoundError("security not found")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    assert mod._keychain_get("ANY") is None


def test_resolve_secret_prefers_env_var(monkeypatch):
    monkeypatch.setenv("SOME_TOKEN", "from-env")
    monkeypatch.setattr(
        mod, "_keychain_get",
        lambda name: (_ for _ in ()).throw(AssertionError("env var must win")),
    )
    assert mod._resolve_secret("SOME_TOKEN") == "from-env"


def test_resolve_secret_falls_back_to_keychain(monkeypatch):
    monkeypatch.delenv("OTHER_TOKEN", raising=False)
    monkeypatch.setattr(mod, "_keychain_get", lambda name: "from-keychain")
    assert mod._resolve_secret("OTHER_TOKEN") == "from-keychain"


def test_keychain_get_empty_value_is_none(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_KEYCHAIN_SECRETS", raising=False)
    monkeypatch.setattr(
        mod.subprocess, "run", lambda *a, **k: _FakeResult(returncode=0, stdout=b"\n")
    )
    assert mod._keychain_get("EMPTY") is None


# ── Review 2026-09-03: bare-name Keychain items ──────────────────────────
#
# The operator's secrets live in a custom keychain with service == account ==
# the bare variable name (TAVILY_API_KEY), while this loader looked only for
# the `claude/<NAME>` service that bin/keychain-seed writes. Both spellings
# must resolve; the prefixed one still wins when both exist.

def test_keychain_get_falls_back_to_bare_service_name(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_KEYCHAIN_SECRETS", raising=False)
    services = []

    def fake_run(cmd, **kwargs):
        service = cmd[cmd.index("-s") + 1]
        services.append(service)
        if service == "MY_TOKEN":
            return _FakeResult(returncode=0, stdout=b"bare-value\n")
        return _FakeResult(returncode=44, stdout=b"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._keychain_get("MY_TOKEN") == "bare-value"
    assert services == ["claude/MY_TOKEN", "MY_TOKEN"], services


def test_keychain_get_prefers_prefixed_item_when_both_exist(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_KEYCHAIN_SECRETS", raising=False)
    services = []

    def fake_run(cmd, **kwargs):
        service = cmd[cmd.index("-s") + 1]
        services.append(service)
        return _FakeResult(returncode=0, stdout=b"prefixed-value\n")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._keychain_get("MY_TOKEN") == "prefixed-value"
    assert services == ["claude/MY_TOKEN"], "must not query the bare name once the prefixed item resolved"


# ── env_exports: the catalog is the only source of exported variables ─────
#
# Before 2026-09-04 the module hard-coded the author's vendor hosts, tenant id
# and local paths in an ENV_VARS list. They now come from the `env_exports`
# section of the environment catalog; conftest points the suite at the fixture
# that carries those historical values.

def _run_loader(monkeypatch, tmp_path, section, secrets=None):
    monkeypatch.setattr(mod, "load_section", lambda name: section if name == mod.SECTION else {})
    monkeypatch.setattr(mod, "_resolve_secret", lambda name: (secrets or {}).get(name))
    env_file = tmp_path / "claude-env"
    monkeypatch.setenv("CLAUDE_ENV_FILE", str(env_file))
    mod.run_env_loader()
    return env_file.read_text(encoding="utf-8")


def test_fixture_values_come_from_the_catalog_and_expand_home():
    """Known-positive: the suite's fixture is in effect and its values are read."""
    values = dict(mod.exported_values())
    assert values["RAMP_SQL_LIMIT"] == "100"
    assert values["CMMC_DIR"] == str(Path.home() / "Documents" / "CMMC" / "assessment")
    assert mod.secret_names() == ["CONFLUENCE_API_TOKEN"]


def test_run_env_loader_writes_values_then_resolved_secrets(monkeypatch, tmp_path):
    text = _run_loader(
        monkeypatch, tmp_path,
        {"values": {"ALPHA": "1", "ROOT": "~/data"}, "secrets": ["TOKEN", "UNSET_TOKEN"]},
        secrets={"TOKEN": "s3cret"},
    )
    assert text == f"ALPHA=1\nROOT={Path.home() / 'data'}\nTOKEN=s3cret\n"


def test_run_env_loader_truncates_instead_of_appending(monkeypatch, tmp_path):
    _run_loader(monkeypatch, tmp_path, {"values": {"ALPHA": "1"}, "secrets": []})
    assert _run_loader(monkeypatch, tmp_path, {"values": {}, "secrets": []}) == ""


def test_run_env_loader_without_env_file_is_a_noop(monkeypatch):
    monkeypatch.delenv("CLAUDE_ENV_FILE", raising=False)
    monkeypatch.setattr(
        mod, "load_section",
        lambda name: (_ for _ in ()).throw(AssertionError("no env file -> the catalog is not read")),
    )
    assert mod.run_env_loader() is None


def test_values_expand_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_LOADER_TEST_ROOT", "/srv/shared")
    text = _run_loader(monkeypatch, tmp_path, {"values": {"DATA": "$ENV_LOADER_TEST_ROOT/data"}, "secrets": []})
    assert text == "DATA=/srv/shared/data\n"


def test_unsourceable_entries_are_skipped_with_a_note_each(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_section", lambda name: {
        "values": {"OK": "v", "9BAD": "x", "MULTI": "a\nb", "NUM": 5},
        "secrets": ["OK_SECRET", 7, "bad name"],
    })
    assert mod.exported_values() == [("OK", "v")]
    assert mod.secret_names() == ["OK_SECRET"]
    err = capsys.readouterr().err
    assert err.count("\n") == 5, err
    for bad in ("'9BAD'", "'MULTI'", "'NUM'", "7", "'bad name'"):
        assert bad in err


def test_wrong_container_types_export_nothing(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_section", lambda name: {"values": ["A=1"], "secrets": "TOKEN"})
    assert mod.exported_values() == []
    assert mod.secret_names() == []
    assert capsys.readouterr().err.count("\n") == 2


def test_module_carries_no_exported_variable_data():
    """The list of names and values left the source; only the mechanism stays."""
    source = (HOOKS_DIR / "session_start_modules" / "env_loader.py").read_text(encoding="utf-8")
    assert "ENV_VARS" not in source
    assert "_SECRET_ENV_VARS" not in source
    assert "=https://" not in source
