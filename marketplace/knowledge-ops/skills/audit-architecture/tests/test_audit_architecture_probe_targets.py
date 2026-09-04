"""Generator contract for references/gen_probe_targets.py.

The server list in probe-targets.md comes only from the live machine config;
the repo ships no inventory of its own. Pinned here:

  1. zero registered servers renders a clean one-line block (a fresh machine
     is a normal state, not a crash or a wall of empty tables)
  2. only registered servers are rendered; catalog entries for servers that
     are not registered stay silent instead of warning about "stale" pings
  3. the --check / --write contract round-trips: a drifted block fails
     --check (exit 1), --write rewrites only the block, --check then passes

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_probe_targets.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "skills" / "audit-architecture" / "references" / "gen_probe_targets.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "audit_architecture_gen_probe_targets", GENERATOR
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_zero_servers_renders_a_clean_block():
    mod = _load_generator()

    block = mod.render([])

    assert block.startswith(mod.BEGIN) and block.endswith(mod.END)
    assert "0 registered" in block
    assert "No MCP servers are registered" in block
    assert "| Server |" not in block, "empty tables must not be rendered"
    assert "WARNING" not in block


def test_only_registered_servers_are_rendered():
    mod = _load_generator()
    known = next(iter(mod.PING_TOOLS))

    block = mod.render(["example-server", known])

    assert f"| {known} | {mod.PING_TOOLS[known]} |" in block
    assert "example-server" in block
    for other in mod.PING_TOOLS:
        if other != known:
            assert f"| {other} |" not in block
    assert "WARNING" not in block, "an unregistered catalog entry is not a defect"


def test_write_then_check_round_trip_with_zero_servers(tmp_path, monkeypatch):
    mod = _load_generator()
    doc = tmp_path / "probe-targets.md"
    doc.write_text(
        f"# head\n\n{mod.BEGIN}\nstale hand-written inventory\n{mod.END}\n\ntail\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "DOC", str(doc))
    monkeypatch.setattr(mod, "live_servers", list)

    monkeypatch.setattr(sys, "argv", ["gen_probe_targets.py", "--check"])
    assert mod.main() == 1, "a drifted block must fail --check"
    monkeypatch.setattr(sys, "argv", ["gen_probe_targets.py", "--write"])
    assert mod.main() == 0
    monkeypatch.setattr(sys, "argv", ["gen_probe_targets.py", "--check"])
    assert mod.main() == 0, "--check must pass against the block --write produced"

    text = doc.read_text(encoding="utf-8")
    assert text.startswith("# head\n\n") and text.endswith("\n\ntail\n")
    assert "stale hand-written inventory" not in text
    assert "No MCP servers are registered" in text


def test_committed_block_is_the_neutral_zero_server_rendering():
    """The repo ships the zero-server rendering, never a host's inventory.

    `--write` is a per-host action; its output on a machine with servers is
    that machine's catalog and must not be committed. Pinning the committed
    block to `render([])` turns such a commit into a failing test instead of
    a silent re-introduction of the inventory this test file exists to keep out.
    """
    mod = _load_generator()
    doc = (REPO / "skills" / "audit-architecture" / "references" / "probe-targets.md").read_text(encoding="utf-8")
    start = doc.index(mod.BEGIN)
    end = doc.index(mod.END) + len(mod.END)

    committed = "\n".join(line.rstrip() for line in doc[start:end].splitlines())
    neutral = "\n".join(line.rstrip() for line in mod.render([]).splitlines())

    assert committed == neutral, "probe-targets.md carries a host inventory; run the generator only locally"
