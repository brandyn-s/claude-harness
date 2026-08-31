"""Tests for bin/hook-fire-report.py — auto-fix awareness + prune logic.

The 2026-06-13 block->auto-rewrite conversion means a guard can earn its keep
by REWRITING (exit 0 + updated_input) rather than blocking (exit 2). The
hook-fires telemetry records exit code only, so an auto-fix looks like a plain
allow; the auto-fix signal is read from the per-guard audit logs instead.
These tests pin the invariants that conversion created:
  (1) auto-fixes are counted (from the per-guard log, not hook-fires),
  (2) a guard that auto-fixes is NOT prune-flagged even with zero blocks,
  (3) a genuinely-idle blocking guard (0 blocks AND 0 auto-fixes) IS flagged.
Without (2) the conversion would make bash-tail-buffering-guard look like a
guard that "stopped blocking" and get falsely recommended for pruning.
"""
import json
import subprocess
import sys

from conftest import HOOKS_DIR

REPORT = HOOKS_DIR.parent / "bin" / "hook-fire-report.py"


def _seed(audit_dir, hook_fires, autofix_logs):
    (audit_dir / "hook-fires-20260613.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in hook_fires), encoding="utf-8")
    for prefix, entries in autofix_logs.items():
        (audit_dir / f"{prefix}-2026-06-13.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def _run(audit_dir, *args):
    r = subprocess.run([sys.executable, str(REPORT), "--dir", str(audit_dir), *args],
                       capture_output=True, text=True, timeout=30)
    return r.stdout


def test_autofixes_counted_from_per_guard_log(tmp_path):
    _seed(tmp_path,
          [{"ts": 1, "hook": "bash-tail-buffering-guard.py", "exit": 0, "ms": 5}] * 20,
          {"bash-tail-buffering": [{"action": "auto-fixed"}] * 20})
    data = json.loads(_run(tmp_path, "--json"))
    tail = next(h for h in data["hooks"] if h["hook"] == "bash-tail-buffering-guard.py")
    assert tail["auto_fixes"] == 20
    assert tail["blocks"] == 0


def test_autofixing_guard_not_prune_flagged(tmp_path):
    # blocks==0 but auto_fixes>0 → earning its keep → NOT a prune candidate.
    _seed(tmp_path,
          [{"ts": 1, "hook": "bash-tail-buffering-guard.py", "exit": 0, "ms": 5}] * 20,
          {"bash-tail-buffering": [{"action": "auto-fixed"}] * 20})
    out = _run(tmp_path)
    prune = out.split("PRUNE/TEST CANDIDATES", 1)
    flagged = len(prune) > 1 and "bash-tail-buffering-guard.py" in prune[1]
    assert not flagged, "auto-fixing guard wrongly flagged as prune candidate"


def test_idle_blocking_guard_still_prune_flagged(tmp_path):
    # A blocking guard with 0 blocks AND 0 auto-fixes IS a prune/test candidate.
    _seed(tmp_path,
          [{"ts": 1, "hook": "promise-checker.py", "exit": 0, "ms": 5}] * 15,
          {})
    out = _run(tmp_path)
    prune = out.split("PRUNE/TEST CANDIDATES", 1)
    assert len(prune) > 1 and "promise-checker.py" in prune[1]


def test_friction_summary_present(tmp_path):
    _seed(tmp_path,
          [{"ts": 1, "hook": "bash-tail-buffering-guard.py", "exit": 2, "ms": 5}] * 3,
          {"bash-tail-buffering": [{"action": "auto-fixed"}] * 7})
    out = _run(tmp_path)
    assert "FRICTION:" in out and "7 auto-fixes" in out
