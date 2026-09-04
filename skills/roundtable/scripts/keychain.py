#!/usr/bin/env python3
"""Resolve provider API keys from the macOS Keychain into the process env.

WHY THIS EXISTS (two defects it closes):

1. `harness.py` had no Keychain resolution at all — the adapters read
   `os.environ` directly, so every run required the operator to inline keys at
   the invocation site. That is not merely inconvenient: a launcher carrying
   secrets makes any later process inspection leak them, and this repo's own
   `bash-security-guard` blocks full-command-line process listings for exactly
   that reason. Resolving in-process removes the need to inline anything.

2. The Keychain item name is NOT the env-var name. OpenAI's items were renamed
   2026-08-04: `OPENAI_API_KEY` no longer exists and the inference key lives at
   `OPENAI_PLATFORM_API`. `jrh_harness.py` looked keys up BY ENV-VAR NAME, so
   its OpenAI lookup had been failing since that rename — and a failed key
   silently reduces a three-vendor panel to two, which is precisely the
   decorrelation loss `rules/eval-shipping-discipline.md` exists to
   prevent. Consumers therefore carry an explicit candidate list.

ADMIN items are deliberately absent from the candidate lists.
`OPENAI_PLATFORM_ADMIN_API` and `OPENAI_CHATGPT_ADMIN_API` authenticate the
Admin/Compliance surfaces, not inference; a panel arm must never silently fall
back to one. Adding them "for robustness" would let a run authenticate with a
credential whose scope the protocol never intended to use.

Values are never printed, returned, or logged — only the resolved SOURCE is.
"""
import os
import shutil
import subprocess

# env var the adapters read -> ordered Keychain service-name candidates.
# Current name first, legacy name second, so a host that still has the old item
# keeps working while a renamed host resolves correctly.
KEY_CANDIDATES = {
    "ANTHROPIC_API_KEY": ("ANTHROPIC_API_KEY",),
    "XAI_API_KEY": ("XAI_API_KEY",),
    "OPENAI_API_KEY": ("OPENAI_PLATFORM_API", "OPENAI_API_KEY"),
    "VOYAGE_API_KEY": ("VOYAGE_API_KEY",),
    "TAVILY_API_KEY": ("TAVILY_API_KEY",),
}

# Arms whose absence collapses the panel. VOYAGE_API_KEY (--auto-stop
# convergence embedding) and TAVILY_API_KEY (validate_claims.py factuality
# check) are optional post-processing keys, not panel arms.
REQUIRED_KEYS = ("ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY")

# The Anthropic key alone is enough for synthesis, which dispatches only that arm.
SYNTHESIS_KEYS = ("ANTHROPIC_API_KEY",)


def _read_keychain_item(service: str) -> str | None:
    """Return the generic-password value for `service`, or None.

    Never raises and never echoes the value. A non-zero exit means the item is
    absent or access was denied; both are 'not resolved' for our purposes.
    """
    security = shutil.which("security")
    if not security:  # non-macOS host, or Keychain CLI unavailable
        return None
    try:
        proc = subprocess.run(
            [security, "find-generic-password", "-w", "-s", service],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def load_keys(names=None) -> list[str]:
    """Populate os.environ for each key that is not already set.

    Returns human-readable status lines that are safe to print: they name the
    env var and the Keychain item that satisfied it, never the value.
    An env var already present always wins — an operator-supplied override must
    not be silently replaced by a Keychain item.
    """
    statuses = []
    for env_name in (names or KEY_CANDIDATES.keys()):
        candidates = KEY_CANDIDATES.get(env_name, (env_name,))
        if os.environ.get(env_name):
            statuses.append(f"{env_name}: already set in env")
            continue
        for service in candidates:
            value = _read_keychain_item(service)
            if value:
                os.environ[env_name] = value
                suffix = "" if service == env_name else "  (item name differs from env var)"
                statuses.append(f"{env_name}: resolved from Keychain item '{service}'{suffix}")
                break
        else:
            statuses.append(
                f"{env_name}: NOT FOUND (checked Keychain items: {', '.join(candidates)})"
            )
    return statuses


def missing_required() -> list[str]:
    """Required env vars still unset after load_keys()."""
    return [k for k in REQUIRED_KEYS if not os.environ.get(k)]
