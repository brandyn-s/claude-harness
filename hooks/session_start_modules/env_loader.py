"""Environment variable loader for SessionStart.

CUSTOMIZE: Update paths and service URLs below to match your environment.
"""
import os
import subprocess
import sys
from pathlib import Path

_HOME = str(Path.home())

# CUSTOMIZE: Update these environment variables for your org
ENV_VARS = [
    f"PYTHON_EXE={Path(_HOME, 'AppData/Local/Programs/Python/Python312/python.exe') if os.name == 'nt' else 'python3'}",
    "AIRLOCK_SERVER=airlock.example.internal:3129",
    "AIRLOCK_BLOCKLIST_GLOBAL=0000000000",
    "CS_BASE_URL=api.laggar.gcw.crowdstrike.com",
    f"CS_HYGIENE={Path(_HOME, 'Documents/CrowdStrike/cs_hygiene.py')}",
    "TENABLE_URL=https://fedcloud.tenable.com",
    "GRAPH_TENANT=11111111-1111-1111-1111-111111111111",
    "GRAPH_CLOUD=gcchigh",
    f"CMMC_DIR={Path(_HOME, 'Documents/CMMC/assessment')}",
    f"STIG_LIB={Path(_HOME, 'Downloads/U_SRG-STIG_Library_October_2025')}",
    "RAMP_SQL_LIMIT=100",
    "CONFLUENCE_SPACES=EXAMPLE,DOCS",
    "CONFLUENCE_EMAIL=security@example.com",
]

# Secrets are never hardcoded here. Resolution order per name:
#   1. an already-set env var (Windows user env vars; any platform), then
#   2. the macOS Keychain — generic password, service "claude/<NAME>",
#      seeded once via bin/keychain-seed.
# Keychain reads keep secrets out of dotfiles and process argv (see
# rules/platform-constraints.md ON macos_secret_storage). First read per
# python binary triggers a Keychain ACL prompt; "Always Allow" persists it.
_SECRET_ENV_VARS = ["CONFLUENCE_API_TOKEN"]


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


for _var in _SECRET_ENV_VARS:
    _val = _resolve_secret(_var)
    if _val:
        ENV_VARS.append(f"{_var}={_val}")


def run_env_loader():
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        # mode="w" (truncate) not "a" (append). SessionStart fires multiple
        # times per session UUID (compact, resume, etc.); appending each time
        # stacks duplicate KEY=value lines and a partial-write race can leave
        # the file in a state bash refuses to source ("GRAPH_: command not
        # found" on line 134 = 10th appended block). Truncating each fire
        # keeps the file at exactly len(ENV_VARS) lines, always fresh.
        with open(env_file, "w", encoding="utf-8") as f:
            for var in ENV_VARS:
                f.write(var + "\n")
