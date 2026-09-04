#!/usr/bin/env python3
"""Record configured request precedence and available runtime evidence. READ-ONLY.

WHY THIS EXISTS
---------------
The audit's recurring theme is that documented/configured values and the values
that actually take effect drift apart, and nothing measured the gap:

  * `MAX_THINKING_TOKENS=65536` is CONFIGURED but INERT on the active models.
    First-party docs (code.claude.com/docs/en/model-config, verified 2026-07-26):
    "Fable 5, Sonnet 5, and Opus 4.7 and later always use adaptive reasoning. The
    fixed thinking budget mode and CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING do not
    apply to them." and "Other values apply only with a fixed thinking budget."
  * OTel was reported as disabled from `DISABLE_TELEMETRY=1`, but Anthropic's
    OTel contract uses `CLAUDE_CODE_ENABLE_TELEMETRY`; the former is not an
    OTel kill switch. Configured != effective startup != backend-observed.
  * A skill's `model:`/`effort:` frontmatter may be silently ignored at runtime.
  * A hook can be REGISTERED for Write|Edit while the guard it contains also
    claims to cover Bash -- the registration, not the script, is what enforces.

So this probe reports, for each dimension: the CONFIGURED value, the REQUESTED
value after observable settings/environment precedence, the EFFECTIVE value where
it can be observed, and an explicit `unverified` marker where it cannot. It never
infers "effective" from "configured" or "requested".

It writes a machine-readable snapshot suitable for before/after comparison across
a change, and it is safe to run at any time: it only reads.

Privacy: values for keys whose name matches a secret-ish pattern are replaced with
a presence marker plus a length, never the value. Paths are reported relative to
$HOME where possible.

Usage:
    python3 bin/acceptance_probe.py                       # human-readable
    python3 bin/acceptance_probe.py --json snap.json      # machine-readable
    python3 bin/acceptance_probe.py --compare a.json b.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hook_exec_form import configured_hook_script  # noqa: E402 -- resolves via the sys.path insert above

HOME = os.path.expanduser("~")
SNAPSHOT_SCHEMA = "acceptance-probe/4"

#: Env/settings keys whose VALUE must never be recorded.
SECRETISH = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|APIKEY|API_KEY|_KEY|CREDENTIAL|AUTH|BEARER|SESSION_ID)",
    re.IGNORECASE,
)

#: Keys that MATCH the secret-ish pattern above but are numeric limits, not
#: secrets. Without this allowlist the probe redacts `MAX_THINKING_TOKENS` (it
#: contains "TOKEN") to a presence marker, and then reports the configured value
#: as absent -- silently blinding the probe to the exact drift it exists to catch.
#: Caught 2026-07-26: probe printed `configured=None` while the live settings
#: plainly contained "65536".
SECRETISH_ALLOWLIST = frozenset(
    {
        "MAX_THINKING_TOKENS",
        "MAX_MCP_OUTPUT_TOKENS",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
        "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS",
    }
)

#: Env vars whose effective value materially changes agent behaviour.
BEHAVIOURAL_ENV = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
    "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION",
    "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
    "CLAUDE_CODE_ENABLE_AUTO_MODE",
    "CLAUDE_CODE_ENABLE_TELEMETRY",
    "DISABLE_TELEMETRY",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "MAX_THINKING_TOKENS",
    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING",
    "MAX_MCP_OUTPUT_TOKENS",
    "ENABLE_TOOL_SEARCH",
    "ENABLE_PROMPT_CACHING_1H",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
    "CLAUDE_CODE_MCP_ALLOWLIST_ENV",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_METRICS_EXPORTER",
    "OTEL_LOGS_EXPORTER",
]

#: Models on which a nonzero fixed thinking budget is INERT, per first-party docs
#: (code.claude.com/docs/en/model-config, verified verbatim 2026-07-26).
ADAPTIVE_ONLY_MODELS = ("fable-5", "sonnet-5", "opus-5", "opus-4-7", "opus-4-8")

OTEL_CONTENT_ENV = (
    "OTEL_LOG_ASSISTANT_RESPONSES",
    "OTEL_LOG_RAW_API_BODIES",
    "OTEL_LOG_TOOL_CONTENT",
    "OTEL_LOG_TOOL_DETAILS",
    "OTEL_LOG_USER_PROMPTS",
)
OTEL_EFFECTIVE_ENV = (
    "CLAUDE_CODE_ENABLE_TELEMETRY",
    "OTEL_METRICS_EXPORTER",
    "OTEL_LOGS_EXPORTER",
    "OTEL_TRACES_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    *OTEL_CONTENT_ENV,
)


def redact(key: str, value):
    """Never record a secret-ish value; record presence + length instead."""
    if value is None:
        return None
    if (key or "") in SECRETISH_ALLOWLIST:
        return value
    if SECRETISH.search(key or ""):
        return {"present": True, "length": len(str(value)), "value": "<redacted>"}
    return value


def rel_home(path: str) -> str:
    if isinstance(path, str) and path.startswith(HOME):
        return "~" + path[len(HOME):]
    return path


def read_json(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as exc:
        return {"_parse_error": f"{type(exc).__name__}"}


def _run_with_outcome(cmd: list[str], timeout: int = 30):
    """Run read-only command and preserve sanitized execution failure class."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, check=False
        )
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", "replace").strip(),
            None,
        )
    except subprocess.TimeoutExpired:
        return None, None, "timeout"
    except OSError:
        return None, None, "spawn_error"
    except subprocess.SubprocessError:
        return None, None, "subprocess_error"


def run(cmd: list[str], timeout: int = 30):
    """Run a read-only command; return (rc, stdout) or (None, None) on failure."""
    rc, out, _outcome = _run_with_outcome(cmd, timeout)
    return rc, out


# ---------------------------------------------------------------------------
# dimensions
# ---------------------------------------------------------------------------
def probe_version() -> dict:
    _rc, out = run(["claude", "--version"])
    version = None
    if out:
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        version = m.group(1) if m else None
    return {
        "configured": None,
        "effective": version,
        "unverified": version is None,
        "note": "effective CLI version from `claude --version`",
    }


def probe_env() -> dict:
    """Effective process environment for behaviour-changing variables.

    IMPORTANT: this is the environment of THIS probe process. A launcher that
    wraps `claude` (an alias/function that exports or unsets variables) can make
    the agent's environment differ from this one, so a mismatch here is a real
    signal, not noise.
    """
    out = {}
    for key in BEHAVIOURAL_ENV:
        raw = os.environ.get(key)
        out[key] = {
            "effective": redact(key, raw),
            "set": raw is not None,
        }
    return out


def probe_settings(path: str) -> dict:
    data = read_json(path)
    if data is None:
        return {"path": rel_home(path), "present": False}
    env = data.get("env", {}) if isinstance(data, dict) else {}
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    perms = data.get("permissions", {}) if isinstance(data, dict) else {}
    sandbox = data.get("sandbox", {}) if isinstance(data, dict) else {}

    # Which hook EVENTS are registered, and for each, the matchers + timeouts.
    # The registration is the enforcement surface -- not what a script contains.
    registered = {}
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            rows = []
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    inner = entry.get("hooks", [])
                    for h in inner if isinstance(inner, list) else []:
                        if not isinstance(h, dict):
                            continue
                        # Exec-form registrations put the real hook script in
                        # argv; the command is only the shared dispatcher (or
                        # bash.exe on native Windows). Keep legacy shell-form
                        # compatibility for older evidence snapshots.
                        script = configured_hook_script(h)
                        rows.append(
                            {
                                "matcher": entry.get("matcher"),
                                "if": h.get("if"),
                                "script": script,
                                "timeout": h.get("timeout"),
                                "type": h.get("type", "command"),
                            }
                        )
            registered[event] = rows

    return {
        "path": rel_home(path),
        "present": True,
        "env": {k: redact(k, v) for k, v in env.items()} if isinstance(env, dict) else {},
        "hook_events": sorted(registered.keys()),
        "hook_registrations": registered,
        "permission_allow_count": len(perms.get("allow", []) or [])
        if isinstance(perms, dict)
        else None,
        "permission_deny_count": len(perms.get("deny", []) or [])
        if isinstance(perms, dict)
        else None,
        "permission_ask_count": len(perms.get("ask", []) or [])
        if isinstance(perms, dict)
        else None,
        "default_mode": perms.get("defaultMode") if isinstance(perms, dict) else None,
        "model": data.get("model"),
        "fallback_model": data.get("fallbackModel"),
        "effort_level": data.get("effortLevel"),
        "switch_models_on_flag": data.get("switchModelsOnFlag"),
        "always_thinking_enabled": data.get("alwaysThinkingEnabled"),
        "enableAllProjectMcpServers": data.get("enableAllProjectMcpServers"),
        "sandbox_enabled": sandbox.get("enabled") if isinstance(sandbox, dict) else None,
    }


def probe_model_runtime(settings_probe: dict) -> dict:
    """Resolve request precedence while leaving effective runtime facts unknown."""
    configured_model = settings_probe.get("model")
    configured_effort = settings_probe.get("effort_level")
    env_model = os.environ.get("ANTHROPIC_MODEL")
    env_effort = os.environ.get("CLAUDE_CODE_EFFORT_LEVEL")

    requested_model = env_model if env_model is not None else configured_model
    requested_effort = env_effort if env_effort is not None else configured_effort
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1":
        provider = "aws-bedrock-requested"
    elif os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1":
        provider = "google-vertex-requested"
    elif os.environ.get("ANTHROPIC_BASE_URL"):
        provider = "custom-base-url-requested"
    else:
        provider = "anthropic-first-party-requested"

    return {
        "configured_model": configured_model,
        "configured_fallback_models": settings_probe.get("fallback_model"),
        "configured_effort": configured_effort,
        "configured_switch_models_on_flag": settings_probe.get(
            "switch_models_on_flag"
        ),
        "requested_model": requested_model,
        "requested_model_source": (
            "environment:ANTHROPIC_MODEL"
            if env_model is not None
            else "settings.json:model"
        ),
        "requested_effort": requested_effort,
        "requested_effort_source": (
            "environment:CLAUDE_CODE_EFFORT_LEVEL"
            if env_effort is not None
            else "settings.json:effortLevel"
        ),
        "provider_request": provider,
        "entrypoint": "probe-process; launcher wrappers may differ",
        "context_class": "runtime-unknown",
        "retention_class": "provider-and-account-contract-required",
        "effective_model": "runtime-unknown",
        "effective_effort": "runtime-unknown",
        "unverified": True,
        "note": (
            "settings and environment establish request precedence only; a fresh "
            "runtime init/model-usage event is required for effective model, "
            "effort, context, provider, fallback, and retention evidence"
        ),
    }


def probe_thinking_budget(settings_env: dict) -> dict:
    """Is a configured MAX_THINKING_TOKENS actually in effect?

    Verbatim first-party contract (model-config, 2026-07-26):
      "Fable 5, Sonnet 5, and Opus 4.7 and later always use adaptive reasoning.
       The fixed thinking budget mode and CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING
       do not apply to them."
      "Other values apply only with a fixed thinking budget."
    """
    configured = settings_env.get("MAX_THINKING_TOKENS")
    if isinstance(configured, dict):
        configured = None
    model = os.environ.get("ANTHROPIC_MODEL") or "(settings/default)"
    disable_adaptive = os.environ.get("CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING")

    model_l = str(model).lower().replace(".", "-")
    adaptive_only = any(tag in model_l for tag in ADAPTIVE_ONLY_MODELS) or model_l in (
        "opus",
        "sonnet",
        "fable",
    )

    if configured in (None, "", "0"):
        effect = "not set or explicitly 0"
    elif adaptive_only:
        effect = "INERT: model uses adaptive reasoning; fixed budget does not apply"
    elif disable_adaptive == "1":
        effect = "ACTIVE: legacy 4.6-class path with adaptive thinking disabled"
    else:
        effect = "UNVERIFIED: model family could not be resolved from env"

    return {
        "configured": configured,
        "model_hint": model,
        "disable_adaptive_thinking": disable_adaptive,
        "effective": effect,
        "unverified": effect.startswith("UNVERIFIED"),
        "doc": "https://code.claude.com/docs/en/model-config",
    }


def probe_otel(
    settings_env: dict,
    effective_startup_env: dict | None = None,
) -> dict:
    """Keep source intent, effective startup config, and delivery evidence separate.

    Claude Code does not pass its managed ``OTEL_*`` configuration to spawned
    subprocesses. Consequently this Python process's environment cannot attest
    the winning Claude startup environment. Callers may supply separately
    acquired, sanitized startup evidence; the normal read-only probe does not.
    """
    disable = settings_env.get("DISABLE_TELEMETRY")
    if disable is None:
        disable = os.environ.get("DISABLE_TELEMETRY")
    if isinstance(disable, dict):
        disable = "<redacted>"

    if effective_startup_env is None:
        startup = {
            "status": "unverified",
            "content_classification": "unverified",
            "unsafe_content_flags": [],
            "evidence": "winning managed/effective Claude startup environment not collected",
        }
        state = "UNVERIFIED: effective Claude OTel startup environment not observed"
    else:
        enable = str(effective_startup_env.get("CLAUDE_CODE_ENABLE_TELEMETRY")) == "1"
        unsafe_content = sorted(
            key
            for key in OTEL_CONTENT_ENV
            if str(effective_startup_env.get(key) or "0") != "0"
        )
        explicit_content_controls = all(
            str(effective_startup_env.get(key)) == "0" for key in OTEL_CONTENT_ENV
        )
        if unsafe_content:
            startup_status = (
                "unsafe-content-enabled" if enable else "unsafe-content-configured"
            )
            content_classification = "unsafe"
            state = (
                "UNSAFE: effective Claude startup enables content-bearing OTel"
                if enable
                else "UNSAFE: content-bearing OTel flags are configured"
            )
        elif enable and explicit_content_controls:
            startup_status = "metadata-only"
            content_classification = "metadata-only"
            state = "ENABLED: effective Claude startup is explicitly metadata-only"
        elif enable:
            startup_status = "content-controls-unverified"
            content_classification = "unverified"
            state = "UNVERIFIED: OTel enabled without every content control explicit"
        else:
            startup_status = "otel-disabled"
            content_classification = "inactive"
            state = "DISABLED: effective CLAUDE_CODE_ENABLE_TELEMETRY is not 1"
        startup = {
            "status": startup_status,
            "content_classification": content_classification,
            "unsafe_content_flags": unsafe_content,
            "enable_telemetry": effective_startup_env.get(
                "CLAUDE_CODE_ENABLE_TELEMETRY"
            ),
            "exporter_configured": any(
                str(effective_startup_env.get(key) or "").lower()
                not in {"", "none"}
                for key in (
                    "OTEL_METRICS_EXPORTER",
                    "OTEL_LOGS_EXPORTER",
                    "OTEL_TRACES_EXPORTER",
                )
            ),
            "evidence": "caller-supplied sanitized startup environment",
        }

    return {
        "source_intent": {
            "enable_telemetry": settings_env.get("CLAUDE_CODE_ENABLE_TELEMETRY"),
            "content_env": {key: settings_env.get(key) for key in OTEL_CONTENT_ENV},
            "attests_live_state": False,
        },
        "probe_process_environment": {
            "enable_telemetry": os.environ.get("CLAUDE_CODE_ENABLE_TELEMETRY"),
            "content_env": {key: os.environ.get(key) for key in OTEL_CONTENT_ENV},
            "attests_claude_startup": False,
        },
        "disable_telemetry": {
            "configured": disable,
            "is_otel_control": False,
            "note": "not documented by Anthropic as a Claude Code OTel enable/disable control",
        },
        "effective_startup": startup,
        "backend_receipt": {
            "status": "not-probed",
            "observed": False,
            "evidence": "requires a separate authenticated backend query",
        },
        "effective": state,
        "unverified": True,
        "note": "source intent != effective startup configuration != backend delivery receipt",
        "doc": "https://code.claude.com/docs/en/monitoring-usage",
    }


_MCP_SECOND_STATUS = re.compile(
    r"(?:\s+-\s+|\s+—\s+|[,;|/]\s*)"
    r"(?:[✓✔✗×!⚠○◯]\s*)?"
    r"(?:(?:tools/)?list\s+)?"
    r"(?:connected\b|failed\b|needs?\s+authentication\b|disabled\b)",
    re.IGNORECASE,
)
_MCP_ROW = re.compile(
    r"^\s*(?:\x1b\[[0-9;]*m)*(?:[-*•●▪◦]\s+)?"
    r"(?:\x1b\[[0-9;]*m)*(?P<name>[A-Za-z0-9_.-]+)"
    r"(?:\x1b\[[0-9;]*m)*\s*:"
)
_MCP_ROW_SHAPE = _MCP_ROW
_MCP_PRIMARY_STATUS = re.compile(
    r"^(?:(?P<marker>[✓✔✗×!⚠○◯])\s*)?"
    r"(?P<status>connected\b|failed(?:\s+to\s+connect)?\b|"
    r"needs?\s+authentication\b|disabled\b)",
    re.IGNORECASE,
)
_MCP_STATUS_MARKERS = {
    "connected": frozenset({"✓", "✔"}),
    "failed": frozenset({"✗", "×"}),
    "needs_auth": frozenset({"!", "⚠"}),
    "disabled": frozenset({"○", "◯"}),
}


def _classify_mcp_status(status_text: str) -> tuple[str, bool]:
    """Return a leading status class and whether another status conflicts."""
    text = status_text.strip()
    match = _MCP_PRIMARY_STATUS.match(text)
    if match is None:
        return "unknown", False

    status_word = match.group("status").lower()
    if status_word.startswith("connected"):
        status = "connected"
    elif status_word.startswith("failed"):
        status = "failed"
    elif status_word.startswith(("need authentication", "needs authentication")):
        status = "needs_auth"
    else:
        status = "disabled"

    marker = match.group("marker")
    marker_conflict = marker is not None and marker not in _MCP_STATUS_MARKERS[status]
    ambiguous = marker_conflict or _MCP_SECOND_STATUS.search(text) is not None
    return ("unknown" if ambiguous else status), ambiguous


def parse_mcp_list(
    output: str | None,
    probe_rc: int | None,
    execution_error: str | None = None,
) -> dict:
    """Parse sanitized connection evidence from ``claude mcp list`` output."""

    status_counts = {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 0,
    }
    if execution_error is not None:
        return {
            "probe_rc": probe_rc,
            "probe_state": "timeout" if execution_error == "timeout" else "probe_error",
            "server_count": None,
            "servers": None,
            "status_counts": status_counts,
            "unverified": True,
            "unverified_reason": execution_error,
            "note": (
                "sanitized names and connection classes only; tool inventories and "
                "headless mcp_server_errors require separate live authenticated probes"
            ),
        }
    if probe_rc is None:
        return {
            "probe_rc": probe_rc,
            "probe_state": "probe_error",
            "server_count": None,
            "servers": None,
            "status_counts": status_counts,
            "unverified": True,
            "unverified_reason": "probe_not_completed",
            "note": (
                "sanitized names and connection classes only; tool inventories and "
                "headless mcp_server_errors require separate live authenticated probes"
            ),
        }
    if probe_rc != 0 and not (output or "").strip():
        return {
            "probe_rc": probe_rc,
            "probe_state": "command_failed",
            "server_count": None,
            "servers": None,
            "status_counts": status_counts,
            "unverified": True,
            "unverified_reason": "nonzero_exit",
            "note": (
                "sanitized names and connection classes only; tool inventories and "
                "headless mcp_server_errors require separate live authenticated probes"
            ),
        }
    if probe_rc == 0 and not (output or "").strip():
        return {
            "probe_rc": probe_rc,
            "probe_state": "no_output",
            "server_count": None,
            "servers": None,
            "status_counts": status_counts,
            "unverified": True,
            "unverified_reason": "no_output",
            "note": (
                "sanitized names and connection classes only; tool inventories and "
                "headless mcp_server_errors require separate live authenticated probes"
            ),
        }
    servers = []
    ambiguous_status = False
    unparsed_server_row = False
    for line in (output or "").splitlines():
        match = _MCP_ROW.match(line)
        if not match or " - " not in line:
            unparsed_server_row = (
                unparsed_server_row or _MCP_ROW_SHAPE.match(line) is not None
            )
            continue
        status_text = line.split(" - ", 1)[1]
        status, row_ambiguous = _classify_mcp_status(status_text)
        ambiguous_status = ambiguous_status or row_ambiguous
        servers.append({"name": match.group("name"), "status": status})
        status_counts[status] += 1

    statuses_by_server: dict[str, set[str]] = {}
    for row in servers:
        statuses_by_server.setdefault(row["name"], set()).add(row["status"])
    conflicting_server_status = any(
        len(statuses) > 1 for statuses in statuses_by_server.values()
    )
    servers = [
        {
            "name": name,
            "status": next(iter(statuses)) if len(statuses) == 1 else "unknown",
        }
        for name, statuses in sorted(statuses_by_server.items())
    ]
    status_counts = {status: 0 for status in status_counts}
    for server in servers:
        status_counts[server["status"]] += 1

    unknown_status = status_counts["unknown"] > 0
    zero_server_line = re.compile(
        r"^\s*No\s+MCP\s+servers\s+(?:configured|found)"
        r"(?:\.\s*(?:Use `claude mcp add` to add (?:one|a server)\.)?)?\s*$",
        re.IGNORECASE,
    )
    zero_servers_reported = any(
        zero_server_line.fullmatch(line) for line in (output or "").splitlines()
    )
    if probe_rc == 0 and not servers and not zero_servers_reported:
        return {
            "probe_rc": probe_rc,
            "probe_state": "unparseable_output",
            "server_count": None,
            "servers": None,
            "status_counts": status_counts,
            "unverified": True,
            "unverified_reason": (
                "unparsed_server_row"
                if unparsed_server_row
                else "no_server_rows_or_zero_server_marker"
            ),
            "note": (
                "sanitized names and connection classes only; tool inventories and "
                "headless mcp_server_errors require separate live authenticated probes"
            ),
        }
    command_failed = probe_rc != 0
    zero_server_contradiction = zero_servers_reported and bool(servers)
    contradictory_output = (
        zero_server_contradiction or conflicting_server_status or ambiguous_status
    )
    return {
        "probe_rc": probe_rc,
        "probe_state": (
            "command_failed"
            if command_failed
            else "contradictory_output"
            if contradictory_output
            else "partial_unparseable_output"
            if unparsed_server_row
            else "completed_zero_servers"
            if zero_servers_reported
            else "completed"
        ),
        "server_count": len(servers),
        "servers": servers,
        "status_counts": status_counts,
        "unverified": (
            command_failed
            or contradictory_output
            or unparsed_server_row
            or ambiguous_status
            or unknown_status
        ),
        "unverified_reason": (
            "nonzero_exit"
            if command_failed
            else "zero_server_marker_with_rows"
            if zero_server_contradiction
            else "conflicting_statuses_for_server"
            if conflicting_server_status
            else "unparsed_server_row"
            if unparsed_server_row
            else "ambiguous_server_status"
            if ambiguous_status
            else "unknown_server_status"
            if unknown_status
            else None
        ),
        "note": (
            "sanitized names and connection classes only; tool inventories and "
            "headless mcp_server_errors require separate live authenticated probes"
        ),
    }


def probe_mcp() -> dict:
    """MCP connection evidence as the CLI reports it, sanitized by the parser."""
    rc, out, execution_error = _run_with_outcome(
        ["claude", "mcp", "list"], timeout=60
    )
    return parse_mcp_list(out, rc, execution_error)


def probe_subagent_limits() -> dict:
    """Record every configured native child ceiling without assuming efficacy."""

    concurrent = os.environ.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS")
    per_session = os.environ.get("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION")
    depth = os.environ.get("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH")
    return {
        "configured_concurrent": concurrent,
        "configured_per_session": per_session,
        "configured_depth": depth,
        "pinned": all(value is not None for value in (concurrent, per_session, depth)),
        "effective": "UNVERIFIED: requires runtime ceiling probes",
        "unverified": True,
        "note": (
            "record explicit local intent; environment presence alone does not "
            "prove the runtime enforced each ceiling"
        ),
    }


def probe_git(repo: str) -> dict:
    def g(*args):
        rc, out = run(["git", "-C", repo, *args])
        return out if rc == 0 else None

    return {
        "repo": rel_home(repo),
        "head": g("rev-parse", "HEAD"),
        "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_files": len([x for x in (g("status", "--porcelain") or "").splitlines() if x]),
        "describe": g("describe", "--always", "--dirty"),
    }


def build_snapshot(repo: str) -> dict:
    user_settings = probe_settings(os.path.join(HOME, ".claude", "settings.json"))
    settings_env = user_settings.get("env", {}) if user_settings.get("present") else {}
    return {
        "schema": SNAPSHOT_SCHEMA,
        "generated_by": "bin/acceptance_probe.py",
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "claude_on_path": shutil.which("claude") is not None,
        },
        "claude_version": probe_version(),
        "effective_env": probe_env(),
        "user_settings": user_settings,
        "model_runtime": probe_model_runtime(user_settings),
        "thinking_budget": probe_thinking_budget(settings_env),
        "otel": probe_otel(settings_env),
        "mcp": probe_mcp(),
        "subagent_limits": probe_subagent_limits(),
        "git": probe_git(repo),
    }


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------
def flatten(obj, prefix="") -> dict:
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, sort_keys=True)
    else:
        out[prefix] = obj
    return out


def compare(a: dict, b: dict) -> int:
    """Diff two snapshots. Returns 1 if anything differs, else 0."""
    # Volatile keys that legitimately differ run-to-run.
    ignore = ("git.dirty_files", "git.head", "git.describe", "git.branch")
    fa, fb = flatten(a), flatten(b)
    keys = sorted(set(fa) | set(fb))
    diffs = []
    for k in keys:
        if any(k.startswith(i) for i in ignore):
            continue
        if fa.get(k) != fb.get(k):
            diffs.append((k, fa.get(k), fb.get(k)))
    if not diffs:
        print("snapshots match on all non-volatile dimensions")
        return 0
    print(f"{len(diffs)} difference(s):")
    for k, av, bv in diffs:
        print(f"  {k}\n      A: {av!r}\n      B: {bv!r}")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", dest="json_out", help="write snapshot JSON here")
    ap.add_argument(
        "--repo",
        default=os.getcwd(),
        help="git repo whose HEAD/branch to record (default: cwd)",
    )
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="diff two snapshots")
    args = ap.parse_args(argv)

    if args.compare:
        a = read_json(args.compare[0])
        b = read_json(args.compare[1])
        if a is None or b is None:
            print("could not read one or both snapshots", file=sys.stderr)
            return 2
        return compare(a, b)

    snap = build_snapshot(args.repo)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=2, sort_keys=True)
        print(f"wrote {args.json_out}")

    print("=== configured request and runtime evidence snapshot ===")
    print(f"claude version   : {snap['claude_version']['effective']}")
    print(f"settings present : {snap['user_settings']['present']}")
    print(f"hook events      : {len(snap['user_settings'].get('hook_events') or [])}")
    print(f"  {', '.join(snap['user_settings'].get('hook_events') or [])}")
    print(f"default mode     : {snap['user_settings'].get('default_mode')}")
    print(f"allow/deny/ask   : {snap['user_settings'].get('permission_allow_count')}/"
          f"{snap['user_settings'].get('permission_deny_count')}/"
          f"{snap['user_settings'].get('permission_ask_count')}")
    print(f"project MCP auto : {snap['user_settings'].get('enableAllProjectMcpServers')}")
    print(f"sandbox enabled  : {snap['user_settings'].get('sandbox_enabled')}")
    mr = snap.get("model_runtime")
    if mr:
        print(
            "model request     : "
            f"{mr['requested_model']!r} ({mr['requested_model_source']})"
        )
        print(
            "effort request    : "
            f"{mr['requested_effort']!r} ({mr['requested_effort_source']})"
        )
        print(
            "runtime effective : "
            f"model={mr['effective_model']} effort={mr['effective_effort']}"
        )
    print()
    tb = snap["thinking_budget"]
    print(f"MAX_THINKING_TOKENS configured={tb['configured']!r} model={tb['model_hint']!r}")
    print(f"  -> effective: {tb['effective']}")
    print()
    ot = snap["otel"]
    print(f"OTel: {ot['effective']}")
    print()
    sa = snap["subagent_limits"]
    print(
        "subagent limits "
        f"concurrent={sa['configured_concurrent']!r} "
        f"per_session={sa['configured_per_session']!r} "
        f"depth={sa['configured_depth']!r} -> {sa['effective']}"
    )
    print()
    mcp = snap["mcp"]
    print(f"MCP servers: {mcp['server_count']} (unverified={mcp['unverified']})")
    print(f"MCP probe state: {mcp['probe_state']}")
    nonzero_statuses = [
        f"{status}={count}"
        for status, count in mcp["status_counts"].items()
        if count
    ]
    print(f"MCP status counts: {', '.join(nonzero_statuses) or 'none'}")
    print(f"MCP unverified reason: {mcp['unverified_reason'] or 'none'}")

    unverified = [
        name
        for name, val in snap.items()
        if isinstance(val, dict) and val.get("unverified")
    ]
    if unverified:
        print(f"\nUNVERIFIED dimensions (configured != proven effective): "
              f"{', '.join(unverified)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
