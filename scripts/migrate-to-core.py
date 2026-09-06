#!/usr/bin/env python3
"""Move a kitchen-sink settings.json to the core posture, one named change at a time.

WHAT THE CORE POSTURE IS (profiles/fresh-laptop/settings.json, docs/sandbox-evaluation.md,
docs/fresh-laptop-control-audit.md)
    the native sandbox ON with autoAllowBashIfSandboxed -- a sandboxed command runs
    without a prompt, an escape returns to permission review; the credential paths
    in filesystem.denyRead; the deny list; no blanket tool allows; no
    skipDangerousModePermissionPrompt; no Stop hook that blocks on phrases.
    Permission mode is acceptEdits (fresh-laptop) or auto with the operator
    profile's autoMode block (operator) -- both were evaluated
    (docs/auto-mode-evaluation.md); `auto` with no autoMode block was not.

WHAT THIS TOOL DOES
    Reads a settings.json, computes the changes that take it to the core posture,
    and prints each one as before -> after with the reason. Nothing is written
    without --apply; --apply writes atomically after a timestamped backup beside
    the file (the same helpers scripts/install-profile.py uses). Everything the
    core has no opinion about -- your MCP servers, your other hooks, your env, your
    non-blanket allow rules -- is left exactly as it was.

THE CHANGES
    1 sandbox.enabled=true, autoAllowBashIfSandboxed=true, allowUnsandboxedCommands=true;
      filesystem.denyRead gains the core's credential paths (union)
    2 skipDangerousModePermissionPrompt removed (it only has an effect set to true)
    3 permissions.allow: BLANKET entries removed -- a bare tool name or Tool(*) / Tool(**)
      for Bash, Edit, Write, Read, MultiEdit, NotebookEdit, WebFetch, Agent. Every
      qualified rule (Bash(git *), Read(~/x/**)) stays.
    4 permissions.deny gains the core deny list (union)
    5 permissions.defaultMode: bypassPermissions / dontAsk -> the target mode; auto stays
      auto only when the target is operator, which brings the autoMode block; with
      --to fresh-laptop, auto -> acceptEdits
    6 Stop hooks that block on phrases (promise-checker, stop-phrase*, or whatever
      --stop-blocker names) are unregistered; other Stop hooks are kept and listed
      for review, because the harness core registers none

USAGE
    python3 scripts/migrate-to-core.py                      # preview ~/.claude/settings.json -> operator
    python3 scripts/migrate-to-core.py --to fresh-laptop
    python3 scripts/migrate-to-core.py --settings PATH --apply
    python3 scripts/migrate-to-core.py --json               # machine-readable plan

After --apply: `python3 scripts/install-profile.py` previews what the profile
would still change (it should say nothing for the keys above), and
harness/fresh-laptop-canary/run.py --plan shows the canary's arms if you want the
before/after safety regression check the plan documents.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("install_profile", ROOT / "scripts" / "install-profile.py")
_ip = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _ip
_spec.loader.exec_module(_ip)

CORE_PROFILE = ROOT / "profiles" / "fresh-laptop" / "settings.json"
OPERATOR_PROFILE = ROOT / "profiles" / "brandyn-operator" / "settings.json"
BLANKET_TOOLS = ("Bash", "Edit", "Write", "Read", "MultiEdit", "NotebookEdit", "WebFetch", "Agent", "Task")
BLANKET_RE = re.compile(r"^(?P<tool>[A-Za-z]+)(?:\((?:\*|\*\*|\*:\*|)\))?$")
STOP_BLOCKERS = ("promise-checker", "stop-phrase", "phrase-blocker")
TARGET_MODE = {"fresh-laptop": "acceptEdits", "operator": "auto"}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_blanket(rule: str) -> bool:
    m = BLANKET_RE.match(str(rule).strip())
    return bool(m) and m.group("tool") in BLANKET_TOOLS


def _hook_names(entry: dict) -> str:
    parts = [str(entry.get("command") or "")] + [str(a) for a in (entry.get("args") or [])]
    return " ".join(parts)


def plan(settings: dict[str, Any], target: str, stop_blockers: tuple[str, ...] = STOP_BLOCKERS) -> tuple[dict, list[dict]]:
    """Return (new settings, changes). Each change: {step, key, before, after, why}."""
    core = _load(CORE_PROFILE)
    new = copy.deepcopy(settings)
    changes: list[dict] = []

    def change(step, key, before, after, why):
        if before != after:
            changes.append({"step": step, "key": key, "before": before, "after": after, "why": why})

    # 1 sandbox
    sb_before = copy.deepcopy(settings.get("sandbox") or {})
    sb = new.setdefault("sandbox", {})
    for k in ("enabled", "autoAllowBashIfSandboxed", "allowUnsandboxedCommands"):
        sb[k] = True
    fs = sb.setdefault("filesystem", {})
    deny_read = list(fs.get("denyRead") or [])
    for p in core["sandbox"]["filesystem"]["denyRead"]:
        if p not in deny_read:
            deny_read.append(p)
    fs["denyRead"] = deny_read
    change(1, "sandbox", sb_before, sb,
           "the native sandbox is the enforcement layer: a sandboxed command runs without a prompt, an escape returns "
           "to permission review (docs/sandbox-evaluation.md); the denyRead paths are the credential files every guard "
           "also protects")

    # 2 skipDangerousModePermissionPrompt
    if "skipDangerousModePermissionPrompt" in new:
        change(2, "skipDangerousModePermissionPrompt", new["skipDangerousModePermissionPrompt"], None,
               "the prompt is the one native control left on a dangerous-mode session; the control audit's "
               "'low friction requires blanket authority' was refuted, not confirmed")
        del new["skipDangerousModePermissionPrompt"]

    # 3 blanket allows
    perms = new.setdefault("permissions", {})
    allow = list(perms.get("allow") or [])
    blanket = [r for r in allow if _is_blanket(r)]
    if blanket:
        perms["allow"] = [r for r in allow if not _is_blanket(r)]
        change(3, "permissions.allow", allow, perms["allow"],
               f"a blanket allow ({', '.join(blanket)}) removes every permission decision for that tool; the sandbox "
               f"and the guards are what make un-prompted Bash safe, not a rule that pre-approves it. Qualified rules stay.")
        if not perms["allow"]:
            del perms["allow"]

    # 4 deny union
    deny_before = list(perms.get("deny") or [])
    deny = list(deny_before)
    for r in core["permissions"]["deny"]:
        if r not in deny:
            deny.append(r)
    perms["deny"] = deny
    change(4, "permissions.deny", deny_before, deny, "the core deny list (union; nothing of yours is removed)")

    # 5 mode
    mode_before = perms.get("defaultMode")
    if mode_before in ("bypassPermissions", "dontAsk") or (mode_before == "auto" and target == "fresh-laptop") \
            or mode_before is None:
        perms["defaultMode"] = TARGET_MODE[target]
        change(5, "permissions.defaultMode", mode_before, perms["defaultMode"],
               "bypassPermissions/dontAsk skip every native decision; acceptEdits (fresh-laptop) keeps them for anything "
               "the sandbox cannot contain; auto is evaluated only with the operator profile's autoMode block "
               "(docs/auto-mode-evaluation.md)" if mode_before else "no mode set: the target profile's mode")
    if target == "operator":
        op = _load(OPERATOR_PROFILE)
        if perms.get("defaultMode") == "auto":
            am_before = copy.deepcopy(new.get("autoMode"))
            merged = _ip.merge({"autoMode": new.get("autoMode") or {}}, {"autoMode": op["autoMode"]})["autoMode"]
            new["autoMode"] = merged
            change(5, "autoMode", am_before, merged,
                   "auto without soft_deny is the posture the control audit was written against; the operator profile's "
                   "block names the irreversible classes the classifier must treat as intent-judged blocks (union)")

    # 6 Stop phrase blockers
    hooks = new.get("hooks") or {}
    stop = hooks.get("Stop")
    if isinstance(stop, list):
        kept, removed = [], []
        for group in stop:
            entries = list((group or {}).get("hooks") or [])
            keep_entries = [e for e in entries if not any(b in _hook_names(e) for b in stop_blockers)]
            removed += [_hook_names(e) for e in entries if e not in keep_entries]
            if keep_entries:
                g = dict(group)
                g["hooks"] = keep_entries
                kept.append(g)
        if removed:
            if kept:
                hooks["Stop"] = kept
            else:
                del hooks["Stop"]
            change(6, "hooks.Stop", stop, kept or None,
                   f"unregistered {len(removed)} phrase blocker(s): a Stop hook that blocks on 'let's wrap up' fights "
                   f"outcome-over-verification, which owns the stopping decision (docs/fresh-laptop-control-audit.md)")
        if kept:
            changes.append({"step": 6, "key": "hooks.Stop (kept)", "before": None, "after": [_hook_names(e) for g in kept for e in g["hooks"]],
                            "why": "review: the harness core registers no Stop hook; these are yours and were left alone"})
    return new, changes


def render(changes: list[dict], settings_path: Path, target: str, applied: bool, backup: Path | None) -> str:
    lines = [f"migrate-to-core: {settings_path} -> {target} posture ({'APPLIED' if applied else 'preview; nothing written'})", ""]
    if not changes:
        lines.append("already at the core posture: no changes")
    for c in changes:
        lines.append(f"[{c['step']}] {c['key']}")
        lines.append(f"      before: {json.dumps(c['before'], sort_keys=True)[:300]}")
        lines.append(f"      after:  {json.dumps(c['after'], sort_keys=True)[:300]}")
        lines.append(f"      why:    {c['why']}")
    lines.append("")
    if applied:
        lines.append(f"backup: {backup}")
        lines.append("next: python3 scripts/install-profile.py   (preview; the keys above should now match the profile)")
    else:
        lines.append("re-run with --apply to write (a timestamped backup is made first)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", default=str(Path.home() / ".claude" / "settings.json"))
    ap.add_argument("--to", choices=sorted(TARGET_MODE), default="operator", help="target posture (default operator)")
    ap.add_argument("--apply", action="store_true", help="write the result (backup first)")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    ap.add_argument("--stop-blocker", action="append", default=[], help="extra Stop hook name fragment to unregister")
    args = ap.parse_args()
    path = Path(args.settings).expanduser()
    if not path.is_file():
        print(f"migrate-to-core: {path} does not exist", file=sys.stderr)
        return 2
    try:
        settings = _load(path)
    except ValueError as exc:
        print(f"migrate-to-core: {path} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    new, changes = plan(settings, args.to, tuple(STOP_BLOCKERS) + tuple(args.stop_blocker))
    backup = None
    if args.apply and any(c["key"] != "hooks.Stop (kept)" for c in changes):
        backup = _ip._backup_path(path)
        backup.write_bytes(path.read_bytes())
        _ip._atomic_write(path, new)
    if args.json:
        print(json.dumps({"settings": str(path), "target": args.to, "applied": bool(backup), "backup": str(backup) if backup else None,
                          "changes": changes, "result": new}, indent=2, sort_keys=True))
    else:
        print(render(changes, path, args.to, bool(backup), backup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
