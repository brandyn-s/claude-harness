"""Generic synthetic-probe harness for the audit-rules hook-coverage gate.

Drives each fixture in `probes/<rule>/fixtures.json` through the relevant hook
via subprocess and records BLOCK/ALLOW verdicts. This is the reusable harness
the SKILL.md Step 3 gate (hook-enforced + high-rate rule) prescribes — run it
instead of hand-building a probe per audit.

Usage:
  python3 skills/audit-rules/probes/probe.py --rule encoding-missing-open
  python3 skills/audit-rules/probes/probe.py            # defaults to encoding-missing-open
  python3 skills/audit-rules/probes/probe.py --list     # list rules with fixtures

To probe a NEW rule, create `probes/<rule>/fixtures.json` with the same schema
(see probes/encoding-missing-open/fixtures.json). Fixtures live in a sibling
JSON so a patched hook does not fire on literal `open('foo.json')` payload
strings inside this .py script (2026-05-22 incident lessons, PR #948).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent          # skills/audit-rules/probes
REPO_ROOT = HERE.parents[2]                       # repo root
HOOKS_DIR = REPO_ROOT / "hooks"


def _available_rules() -> list[str]:
    return sorted(
        p.parent.name for p in HERE.glob("*/fixtures.json")
    )


def _build_payload(fixture: dict, tmpdir: Path) -> dict:
    """Build the hook input payload for one fixture."""
    tool = fixture["tool"]
    if tool == "Write":
        content = "\n".join(fixture["content_lines"]) + "\n"
        target = tmpdir / fixture["file_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": content},
            "tool_response": {"filePath": str(target)},
        }
    if tool == "Edit":
        target = tmpdir / fixture["file_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(fixture["new_string"] + "\n", encoding="utf-8")
        return {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": fixture["old_string"],
                "new_string": fixture["new_string"],
            },
            "tool_response": {"filePath": str(target)},
        }
    if tool == "Bash":
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": fixture["command"]},
        }
    raise ValueError(f"unknown tool {tool!r}")


def _run_hook(hook_name: str, payload: dict) -> tuple[int, str, str]:
    hook_path = HOOKS_DIR / hook_name
    if not hook_path.is_file():
        return -1, "", f"hook script not found: {hook_path}"
    proc = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=15,
    )
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


def _verdict(returncode: int, stdout: str, stderr: str) -> str:
    """Decode a hook's exit + output into BLOCK / ALLOW / ERROR.

    Hooks emit either `{"decision": "block", ...}` on stdout (PostToolUse-
    style) or `sys.exit(2)` with a stderr message (PreToolUse-style). ALLOW is
    exit 0 with no block JSON.
    """
    if returncode == 2:
        return "BLOCK"
    if returncode != 0:
        return "ERROR"
    try:
        out_json = json.loads(stdout)
        if isinstance(out_json, dict) and out_json.get("decision") == "block":
            return "BLOCK"
    except (json.JSONDecodeError, ValueError):
        pass
    return "ALLOW"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rule", default="encoding-missing-open",
        help="rule name; fixtures resolved from probes/<rule>/fixtures.json",
    )
    parser.add_argument(
        "--list", action="store_true", help="list rules that have fixtures",
    )
    args = parser.parse_args()

    if args.list:
        rules = _available_rules()
        print("Rules with probe fixtures:")
        for r in rules:
            print(f"  {r}")
        return 0

    fixtures_file = HERE / args.rule / "fixtures.json"
    if not fixtures_file.is_file():
        print(
            f"No fixtures for rule {args.rule!r} at {fixtures_file}.\n"
            f"Available: {', '.join(_available_rules()) or '(none)'}\n"
            f"Create probes/{args.rule}/fixtures.json to probe a new rule.",
            file=sys.stderr,
        )
        return 2

    fixtures = json.loads(fixtures_file.read_text(encoding="utf-8"))["fixtures"]
    results = []
    matrix_failures = []
    with tempfile.TemporaryDirectory(prefix="audit-rules-probe-") as td:
        tmpdir = Path(td)
        for fx in fixtures:
            payload = _build_payload(fx, tmpdir)
            rc, out, err = _run_hook(fx["hook"], payload)
            got = _verdict(rc, out, err)
            expected = fx["expected"]
            match = "OK" if got == expected else "MISMATCH"
            if match == "MISMATCH":
                matrix_failures.append((fx["id"], expected, got))
            results.append({
                "id": fx["id"], "expected": expected, "got": got, "match": match,
            })

    width_id = max(len(r["id"]) for r in results)
    print(f"rule: {args.rule}  ({len(results)} fixtures)")
    print(f"{'id':<{width_id}}  expected  got     match")
    print("-" * (width_id + 28))
    for r in results:
        print(f"{r['id']:<{width_id}}  {r['expected']:<8}  {r['got']:<6}  {r['match']}")

    if matrix_failures:
        print("\nMISMATCHES:")
        for fx_id, expected, got in matrix_failures:
            print(f"  {fx_id}: expected {expected}, got {got}")
        return 1
    print(f"\nAll {len(results)} probes match expected verdicts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
