"""Drift guard for scan_violations.py RULE_BLOCK_SIGNATURES (2026-06-16, #1 follow-up).

The scanner's net-silent / block-then-fix split is only correct while the
substrings in RULE_BLOCK_SIGNATURES verbatim match what the guards print when
they block. Those strings live in a DIFFERENT file (hooks/*.py) than the map,
so a rename silently reverts the scanner to over-counting with no test failing.

These tests run a known-positive payload through each signature's guard and
assert the signature appears in the emitted block REASON — a RUNTIME check, not
a source grep (post-write-edit splits "open() without " + "encoding='utf-8' at"
across two f-string lines, so the substring only exists once concatenated at
runtime; a source grep would false-alarm). A self-coverage test fails if a
signature is added to the map without a matching probe.

Payloads are loaded from signature_drift_probes.json so this .py carries no
open()/inline-python literals for the running guards to trip on.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCANNER = REPO / "skills" / "audit-rules" / "references" / "scan_violations.py"
HOOKS = REPO / "hooks"
PROBES = json.loads(
    (Path(__file__).parent / "signature_drift_probes.json").read_text(encoding="utf-8")
)["probes"]


def _load_scanner():
    spec = importlib.util.spec_from_file_location("scan_violations", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hook_block_reason(probe, tmpdir):
    """Drive one probe through its hook; return the combined block reason text
    (PreToolUse writes the reason to stderr + exit 2; PostToolUse emits a
    {"decision":"block","reason":...} JSON on stdout)."""
    hook_path = HOOKS / probe["hook"]
    if probe["tool"] == "Bash":
        command = probe["command"].replace("__PAD300__", "x" * 320)
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    else:  # Write / Edit — seed a real .py file on disk for the PostToolUse hook
        target = tmpdir / "drift_seed.py"
        target.write_text(probe["content"], encoding="utf-8")
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
    # The inline/heredoc encoding guards are scoped to Windows (2026-06-27:
    # cp1252 is Windows-only; macOS/Linux open() defaults to UTF-8), so on a
    # non-Windows CI host they no-op and emit no signature. This drift guard
    # verifies the SIGNATURE STRING (a rewording check) which is platform-
    # independent, so force the guards active to exercise their emit path.
    # Signature coverage spans the full author-workstation policy surface,
    # including optional portability/workflow checks. Select that profile
    # explicitly; the fresh-laptop default intentionally omits these checks.
    env = {
        **os.environ,
        "CLAUDE_BASH_POLICY_PACKS": "all",
        "CLAUDE_ENCODING_GUARD_FORCE": "1",
    }
    proc = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=15,
        env=env,
    )
    reason = proc.stderr.decode("utf-8", "replace")
    out = proc.stdout.decode("utf-8", "replace")
    if out.strip():
        try:
            reason += " " + str(json.loads(out).get("reason", ""))
        except (json.JSONDecodeError, ValueError):
            reason += " " + out
    return reason


@pytest.mark.parametrize("probe", PROBES, ids=[p["signature"] for p in PROBES])
def test_signature_is_emitted_by_its_guard(probe):
    """The mapped signature must appear in the guard's actual block reason.
    Fails loudly if a hook reworded its output (the silent-rot this guards)."""
    with tempfile.TemporaryDirectory(prefix="sig-drift-") as td:
        reason = _hook_block_reason(probe, Path(td))
    assert probe["signature"] in reason, (
        f"signature {probe['signature']!r} (rule {probe['rule']}) NOT found in "
        f"{probe['hook']} block reason — the hook likely reworded its output, "
        f"which silently breaks the scanner's net-silent split. "
        f"Got: {reason[:240]!r}"
    )


def test_every_mapped_signature_has_a_drift_probe():
    """Self-coverage: adding a rule to RULE_BLOCK_SIGNATURES without a probe
    fails here, so the map and its drift guard cannot diverge."""
    sv = _load_scanner()
    probed = {p["signature"] for p in PROBES}
    missing = [
        (rule, sig)
        for rule, sigs in sv.RULE_BLOCK_SIGNATURES.items()
        for sig in sigs
        if sig not in probed
    ]
    assert not missing, (
        "RULE_BLOCK_SIGNATURES entries with no drift probe in "
        f"signature_drift_probes.json: {missing}. Add a known-positive probe "
        "for each so a hook rename can't silently break the net-silent split."
    )


def test_probes_only_reference_mapped_signatures():
    """Reverse guard: every probe's signature must still be in the map (catches
    a probe left behind after a signature is removed from the map)."""
    sv = _load_scanner()
    mapped = {s for sigs in sv.RULE_BLOCK_SIGNATURES.values() for s in sigs}
    stray = [p["signature"] for p in PROBES if p["signature"] not in mapped]
    assert not stray, f"probes reference signatures absent from the map: {stray}"
