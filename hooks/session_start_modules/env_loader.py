"""Environment variable loader for SessionStart.

Writes the operator's exported variables to CLAUDE_ENV_FILE so every Bash tool
call in the session sees them. WHICH variables, and their values, are
environment data and live in the `env_exports` section of the environment
catalog (hooks/_environment_catalog.py; shape in
contracts/environment-catalog.example.json), never in this module:

  values   NAME -> value. `~` and `$VAR` / `${VAR}` (also `%VAR%` on Windows)
           expand at write time, so a catalog can carry portable paths.
  secrets  variable NAMES only. Each is resolved at write time from an
           already-set variable, then the macOS Keychain (bin/keychain-seed);
           a name that resolves to nothing is left out. No secret value ever
           belongs in a catalog.

contracts/environment-catalog.json ships both parts empty, so the loader writes
an empty file until the operator fills the section in.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _environment_catalog import load_section

SECTION = "env_exports"
# A shell `source`s the env file, so only names it can parse are written: a
# broken line once left the file in a state bash refused to load.
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _note(message: str) -> None:
    try:
        sys.stderr.write(f"[env-loader] {message}\n")
    except Exception:  # noqa: S110, BLE001 -- fail-open: the note must never break session start
        pass


def _expand(value: str) -> str:
    """`$VAR` / `${VAR}` (and `%VAR%` on Windows) first, then a leading `~`."""
    return os.path.expanduser(os.path.expandvars(value))


def exported_values() -> list[tuple[str, str]]:
    """(NAME, expanded value) pairs from `env_exports.values`, in catalog order.

    An entry a shell could not source (bad name, non-string or multi-line
    value) is skipped with one stderr note; the rest still ship.
    """
    values = load_section(SECTION).get("values", {})
    if not isinstance(values, dict):
        _note("env_exports.values must be a JSON object; exporting nothing")
        return []
    out: list[tuple[str, str]] = []
    for name, value in values.items():
        if not isinstance(name, str) or not _NAME_RE.match(name):
            _note(f"skipping env_exports.values entry {name!r}: not a valid variable name")
            continue
        if not isinstance(value, str) or "\n" in value or "\r" in value:
            _note(f"skipping env_exports.values entry {name!r}: value must be a single-line string")
            continue
        out.append((name, _expand(value)))
    return out


def secret_names() -> list[str]:
    """Variable names from `env_exports.secrets` (names only, never values)."""
    names = load_section(SECTION).get("secrets", [])
    if not isinstance(names, list):
        _note("env_exports.secrets must be a JSON array of names; resolving none")
        return []
    out: list[str] = []
    for name in names:
        if not isinstance(name, str) or not _NAME_RE.match(name):
            _note(f"skipping env_exports.secrets entry {name!r}: not a valid variable name")
            continue
        out.append(name)
    return out


# Secrets are never in the catalog or here. Resolution order per name:
#   1. an already-set env var (Windows user env vars; any platform), then
#   2. the macOS Keychain — generic password, service "claude/<NAME>",
#      seeded once via bin/keychain-seed.
# Keychain reads keep secrets out of dotfiles and process argv (see
# rules/platform-constraints.md ON macos_secret_storage). First read per
# python binary triggers a Keychain ACL prompt; "Always Allow" persists it.


def _keychain_get(name: str) -> str | None:
    """macOS Keychain lookup: service ``claude/<name>`` first, then bare ``<name>``.

    bin/keychain-seed writes the prefixed form; operators who keep secrets in a
    custom keychain (service == account == variable name) use the bare form.
    Both resolve, the prefixed item wins when both exist, and `security` searches
    every keychain in the user's search list (review 2026-09-03).

    Returns None off-darwin, when CLAUDE_KEYCHAIN_SECRETS=0, or on any
    `security` failure — callers fall through to other sources.
    """
    if sys.platform != "darwin":
        return None
    if os.environ.get("CLAUDE_KEYCHAIN_SECRETS") == "0":
        return None
    for service in (f"claude/{name}", name):
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        if r.returncode != 0:
            continue
        val = r.stdout.decode("utf-8", errors="replace").strip()
        if val:
            return val
    return None


def _resolve_secret(name: str) -> str | None:
    """Env var first (works everywhere), then macOS Keychain."""
    return os.environ.get(name) or _keychain_get(name)


def run_env_loader():
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return
    lines = [f"{name}={value}" for name, value in exported_values()]
    for name in secret_names():
        value = _resolve_secret(name)
        if value:
            lines.append(f"{name}={value}")
    # mode="w" (truncate) not "a" (append). SessionStart fires multiple
    # times per session UUID (compact, resume, etc.); appending each time
    # stacks duplicate KEY=value lines and a partial-write race can leave
    # the file in a state bash refuses to source ("GRAPH_: command not
    # found" on line 134 = 10th appended block). Truncating each fire
    # keeps the file at exactly one line per exported variable, always fresh.
    try:
        with open(env_file, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
    except OSError as exc:
        _note(f"cannot write {env_file} ({exc}); session environment not exported")
