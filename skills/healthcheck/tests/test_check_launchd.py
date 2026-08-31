"""Unit tests for healthcheck/references/_check_launchd.py.

The check exists because of two MEASURED failures on 2026-08-12 that every
existing signal called healthy:

1. A template sat uninstalled for TEN DAYS. Its script's bytes were deployed and
   its PR merged, so "is it built?" said yes while `launchctl list` had no such
   label.
2. Once installed the agent FAILED its next two runs, visible ONLY in the
   last-exit-status column of `launchctl list`.

So the tests below are mostly about the states that LOOK fine: installed-but-
unloaded, loaded-but-failing, and an absent instrument. A test suite that only
covered the happy path plus a missing file would have missed defect 2, which is
the one with a live protection gap behind it.

Runs on every platform: the darwin-only paths are stubbed, and the one genuinely
macOS-dependent assertion is skipped elsewhere.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_launchd",
    Path(__file__).resolve().parent.parent / "references" / "_check_launchd.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>/bin/true</string></array>
</dict></plist>
"""


def _env(monkeypatch, tmp_path, templates, installed, loaded):
    """Wire the module at its seams: template dir, agent dir, launchctl output."""
    tdir = tmp_path / "templates"
    adir = tmp_path / "agents"
    tdir.mkdir()
    adir.mkdir()
    for label in templates:
        (tdir / f"{label}.plist").write_text(PLIST.format(label=label), encoding="utf-8")
    for label in installed:
        (adir / f"{label}.plist").write_text(PLIST.format(label=label), encoding="utf-8")
    monkeypatch.setattr(hc, "TEMPLATE_DIR", tdir)
    monkeypatch.setattr(hc, "AGENT_DIR", adir)
    monkeypatch.setattr(hc.sys, "platform", "darwin")
    # read_label prefers plutil on darwin; force the portable path so the test
    # runs identically on ubuntu/windows CI.
    monkeypatch.setattr(hc, "read_label",
                        lambda p: __import__("plistlib").loads(p.read_bytes()).get("Label"))
    monkeypatch.setattr(hc, "loaded_agents", lambda: loaded)
    return tdir, adir


def test_non_darwin_skips_cleanly(monkeypatch, capsys):
    """launchctl is macOS-only; the ubuntu/windows CI legs must not fail."""
    monkeypatch.setattr(hc.sys, "platform", "linux")
    assert hc.main() == 0
    assert "SKIP" in capsys.readouterr().out


def test_all_healthy_is_pass(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"],
         {"com.example.a": "0"})
    assert hc.main() == 0
    assert "PASS" in capsys.readouterr().out


def test_never_run_dash_is_not_a_failure(monkeypatch, tmp_path, capsys):
    """`-` means "not run in this session", which is the normal state for a
    daily agent that has not fired yet. Treating it as failure would make the
    check fire on every healthy morning."""
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"],
         {"com.example.a": "-"})
    assert hc.main() == 0


def test_uninstalled_template_is_reported(monkeypatch, tmp_path, capsys):
    """Defect 1: the ten-day gap."""
    _env(monkeypatch, tmp_path, ["com.example.a"], [], {})
    assert hc.main() == 1
    out = capsys.readouterr().out
    assert "NOT INSTALLED" in out
    assert "com.example.a" in out


def test_installed_but_not_loaded_is_reported(monkeypatch, tmp_path, capsys):
    """The state that looks most healthy: the plist file exists. A check that
    stopped at file existence would pass here."""
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"], {})
    assert hc.main() == 1
    assert "NOT LOADED" in capsys.readouterr().out


def test_nonzero_last_exit_is_reported(monkeypatch, tmp_path, capsys):
    """Defect 2, the one with a live protection gap behind it: installed, loaded,
    and failing every run."""
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"],
         {"com.example.a": "1"})
    assert hc.main() == 1
    out = capsys.readouterr().out
    assert "LAST EXIT" in out
    assert "com.example.a" in out


def test_absent_instrument_is_WARN_not_clean(monkeypatch, tmp_path, capsys):
    """`launchctl list` unavailable must NOT read as "nothing is wrong". An
    absent instrument is unknown state, and reporting PASS there is how a
    broken agent stays invisible."""
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"], None)
    assert hc.main() == 1
    assert "UNKNOWN" in capsys.readouterr().out


def test_undeclared_example_agent_is_reported(monkeypatch, tmp_path, capsys):
    """Reverse drift: a loaded agent nobody can reconstruct from the repo."""
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"],
         {"com.example.a": "0", "com.example.ghost": "0"})
    assert hc.main() == 1
    assert "UNDECLARED" in capsys.readouterr().out


def test_recorded_undeclared_agent_is_not_reported(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(hc.UNDECLARED_ON_PURPOSE, "com.example.ghost", "reason")
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"],
         {"com.example.a": "0", "com.example.ghost": "0"})
    assert hc.main() == 0


def test_non_example_loaded_agents_are_ignored(monkeypatch, tmp_path):
    """The machine is full of Apple and third-party agents; only ours are in scope."""
    _env(monkeypatch, tmp_path, ["com.example.a"], ["com.example.a"],
         {"com.example.a": "0", "com.apple.something": "0", "com.docker.helper": "1"})
    assert hc.main() == 0


def test_recorded_exclusion_suppresses_not_installed(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(hc.NOT_INSTALLED_ON_PURPOSE, "com.example.a", "reason")
    _env(monkeypatch, tmp_path, ["com.example.a"], [], {})
    assert hc.main() == 0
    assert "excluded by record" in capsys.readouterr().out


def test_label_is_read_from_the_plist_not_the_filename(monkeypatch, tmp_path, capsys):
    """A renamed template with an unchanged Label must not read as a missing agent."""
    tdir = tmp_path / "templates"
    adir = tmp_path / "agents"
    tdir.mkdir()
    adir.mkdir()
    (tdir / "renamed-file.plist").write_text(
        PLIST.format(label="com.example.real"), encoding="utf-8")
    (adir / "com.example.real.plist").write_text(
        PLIST.format(label="com.example.real"), encoding="utf-8")
    monkeypatch.setattr(hc, "TEMPLATE_DIR", tdir)
    monkeypatch.setattr(hc, "AGENT_DIR", adir)
    monkeypatch.setattr(hc.sys, "platform", "darwin")
    monkeypatch.setattr(hc, "loaded_agents", lambda: {"com.example.real": "0"})
    assert hc.main() == 0


def test_unreadable_template_is_a_finding_not_a_silent_skip(monkeypatch, tmp_path, capsys):
    tdir = tmp_path / "templates"
    adir = tmp_path / "agents"
    tdir.mkdir()
    adir.mkdir()
    (tdir / "broken.plist").write_text("not a plist at all", encoding="utf-8")
    monkeypatch.setattr(hc, "TEMPLATE_DIR", tdir)
    monkeypatch.setattr(hc, "AGENT_DIR", adir)
    monkeypatch.setattr(hc.sys, "platform", "darwin")
    monkeypatch.setattr(hc, "loaded_agents", dict)
    assert hc.main() == 1
    assert "NO LABEL" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "darwin", reason="plutil is macOS-only")
def test_double_hyphen_comment_parses_via_plutil_not_plistlib(tmp_path):
    """The real 2026-08-12 case. XML forbids `--` inside a comment, so plistlib
    raises ExpatError — but CFPropertyList (plutil, and launchd itself) accepts
    it and the agent loads. Reading with the strict parser produced a confident
    wrong answer about a WORKING agent, so read_label must prefer plutil."""
    p = tmp_path / "dh.plist"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        '<!-- rsync --link-dest hardlinks unchanged files -->\n'
        '<key>Label</key><string>com.example.dh</string>\n'
        '</dict></plist>\n', encoding="utf-8")

    import plistlib
    with pytest.raises(Exception):
        plistlib.loads(p.read_bytes())          # the strict parser refuses
    assert subprocess.run(["plutil", "-lint", str(p)],
                          capture_output=True).returncode == 0
    assert hc.read_label(p) == "com.example.dh"  # the check reads it anyway


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
