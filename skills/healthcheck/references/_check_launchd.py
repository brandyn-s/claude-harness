#!/usr/bin/env python3
"""Check 13: launchd agents — templates that were never installed, and agents that fail.

WHY THIS EXISTS (measured 2026-08-12, two distinct real findings in one run):

1. `templates/launchd/com.example.claude.transcript-backup.plist` sat in the repo
   for TEN DAYS without being installed. Its script's bytes were deployed to
   ~/.claude/bin and the PR was merged, so every "is it built?" check said yes —
   while `launchctl list` had no such label and the backup had not run since the
   day it shipped. `source` and `deployed` were true; `configured` and `live` were
   false, and nothing looked at the last two.
2. Once installed, the agent FAILED on its next two scheduled runs (bash 3.2
   empty-array expansion under `set -u`). It logged START and never OK. The ONLY
   place that surfaced was the last-exit-status column of `launchctl list`.

So this check asserts three things per template, not one: the label is INSTALLED
in ~/Library/LaunchAgents, it is LOADED in `launchctl list`, and its LAST EXIT was
0. A check that stopped at "the plist file exists" would have missed finding 2
entirely, which is the one that had a live protection gap behind it.

It also reports the REVERSE drift — a loaded `com.example.*` agent with no
template in the repo — because that is an agent nobody can reconstruct from source.

macOS only: `launchctl` does not exist elsewhere, so on any other platform this
exits 0 with a SKIP line rather than failing the ubuntu/windows CI legs.

Exit 0 = PASS/SKIP, 1 = WARN (uninstalled, unloaded, failing, or undeclared).
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

TEMPLATE_DIR = Path(os.path.expanduser("~/.claude/templates/launchd"))
AGENT_DIR = Path(os.path.expanduser("~/Library/LaunchAgents"))

#: Templates deliberately NOT installed on this host. A recorded reason is
#: required — the whole point of the check is that "not installed" must be a
#: decision, not an accident (same contract as the channel registry's
#: DELIBERATE_EXCLUSIONS).
NOT_INSTALLED_ON_PURPOSE: dict[str, str] = {}

#: Loaded agents that legitimately have no template in this repo.
UNDECLARED_ON_PURPOSE: dict[str, str] = {
    "com.example.jed-daily": "JED competition harness, lives outside claude-config",
    "com.example.jed-generate": "JED competition harness, lives outside claude-config",
    "com.example.jed-search": "JED competition harness, lives outside claude-config",
}


def read_label(path: Path) -> str | None:
    """Return a template's Label using the parser launchd ITSELF uses.

    `plutil` wraps CFPropertyList — the same implementation launchd reads plists
    with — so it is the semantics that decide whether an agent actually loads.
    Python's `plistlib` is strict expat and REJECTS files CFPropertyList accepts.

    MEASURED 2026-08-12: `com.example.claude.transcript-backup.plist` fails
    plistlib with `ExpatError: not well-formed, line 18` because a comment reads
    `rsync --link-dest ...` and XML forbids `--` inside a comment. `plutil -lint`
    says OK and the agent loads and runs fine. A plistlib-only reader therefore
    extracted no Label, and the loaded agent then appeared in the REVERSE-drift
    list as "loaded, no template" — a confident wrong answer about a working
    agent, produced by choosing the stricter parser over the real one.

    plistlib remains the fallback so the function still works off-macOS (where
    the tests run).
    """
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["plutil", "-extract", "Label", "raw", "-o", "-",
                                str(path)], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        with path.open("rb") as fh:
            label = plistlib.load(fh).get("Label")
        return str(label) if label else None
    except Exception:  # noqa: BLE001 — caller reports the unreadable template
        return None


def template_labels() -> tuple[dict[str, Path], list[str]]:
    """Map Label -> template path, plus the names of templates with no readable Label.

    A filename is not the Label: a renamed template with an unchanged Label would
    otherwise read as a missing agent, and vice versa.
    """
    out: dict[str, Path] = {}
    unreadable: list[str] = []
    if not TEMPLATE_DIR.is_dir():
        return out, unreadable
    for p in sorted(TEMPLATE_DIR.glob("*.plist")):
        label = read_label(p)
        if label:
            out[label] = p
        else:
            unreadable.append(p.name)
    return out, unreadable


def loaded_agents() -> dict[str, str] | None:
    """Map label -> last exit status string from `launchctl list`.

    Returns None when launchctl is unavailable (non-macOS), which the caller must
    treat as UNKNOWN rather than as "nothing is loaded" — an absent instrument is
    not an empty result.
    """
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out: dict[str, str] = {}
    for line in r.stdout.splitlines()[1:]:
        parts = re.split(r"\s+", line.strip())
        if len(parts) >= 3:
            out[parts[2]] = parts[1]
    return out


def main() -> int:
    if sys.platform != "darwin":
        print("launchd: SKIP — launchctl is macOS-only")
        return 0

    templates, unreadable = template_labels()
    if not templates and not unreadable:
        print(f"launchd: SKIP — no templates at {TEMPLATE_DIR}")
        return 0

    loaded = loaded_agents()
    if loaded is None:
        print("launchd: WARN — `launchctl list` unavailable; state UNKNOWN, not clean")
        return 1

    not_installed, not_loaded, failing, undeclared, excluded = [], [], [], [], []

    for label, path in templates.items():
        if label in NOT_INSTALLED_ON_PURPOSE:
            excluded.append(label)
            continue
        if not (AGENT_DIR / f"{label}.plist").exists():
            not_installed.append((label, path.name))
            continue
        if label not in loaded:
            not_loaded.append(label)
            continue
        status = loaded[label]
        # "-" means never run in this session; a nonzero integer is a real failure.
        if status not in ("-", "0"):
            failing.append((label, status))

    for label in sorted(loaded):
        if not label.startswith("com.example."):
            continue
        if label in templates or label in UNDECLARED_ON_PURPOSE:
            continue
        undeclared.append(label)

    issues = (len(not_installed) + len(not_loaded) + len(failing)
              + len(undeclared) + len(unreadable))
    if not issues:
        print(f"launchd: PASS — {len(templates)} template(s), all installed, loaded, "
              f"last exit 0"
              + (f"; {len(excluded)} excluded by record" if excluded else ""))
        return 0

    print(f"launchd: WARN — {issues} issue(s) across {len(templates)} template(s)")
    for label, fname in not_installed:
        print(f"  NOT INSTALLED   {label}  (templates/launchd/{fname})")
        print("                  -> cp the template to ~/Library/LaunchAgents and "
              "`launchctl bootstrap gui/$(id -u) <path>`, or record it in "
              "NOT_INSTALLED_ON_PURPOSE with a reason")
    for label in not_loaded:
        print(f"  NOT LOADED      {label}  (plist installed but absent from launchctl)")
    for label, status in failing:
        print(f"  LAST EXIT {status:>4}  {label}  <- ran and FAILED; check its stderr log")
    for label in undeclared:
        print(f"  UNDECLARED      {label}  (loaded, no template in this repo)")
    for name in unreadable:
        print(f"  NO LABEL        templates/launchd/{name}  (neither plutil nor "
              f"plistlib could read a Label — the agent cannot be reconciled)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
