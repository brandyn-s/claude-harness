"""PostToolUse hook: trim large MCP tool responses using updatedMCPToolOutput.

Reduces context consumption from verbose MCP responses (CrowdStrike detections,
Tenable vulnerabilities, etc.) by extracting essential fields and discarding bulk data.

Uses the updatedMCPToolOutput JSON return field (hooks.ts:646-649) to inject
trimmed output that the model sees instead of the full response.

Exit codes:
  0 = continue (with optional updatedMCPToolOutput)
"""

import json
import sys

# Threshold: only trim responses larger than this (characters)
TRIM_THRESHOLD = 40_000

# Maximum output size after trimming
MAX_OUTPUT_CHARS = 25_000


def _cap_lists(value, cap):
    """Return a copy of `value` with every list capped to `cap` elements,
    recording how many were dropped. Keeps the structure valid JSON."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, list) and len(v) > cap:
                out[k] = v[:cap]
                out[f"_{k}_truncated"] = len(v) - cap
            else:
                out[k] = v
        return out
    if isinstance(value, list) and len(value) > cap:
        return value[:cap]
    return value


def _enforce_json_cap(value):
    """Serialize `value` to JSON that is <= MAX_OUTPUT_CHARS AND always valid.

    Caps top-level lists progressively; if even a 1-element view is still too
    large, falls back to a valid JSON wrapper around a truncated string. This
    is the critical contract: updatedMCPToolOutput is handed back to the model
    as the tool output, so it must never be a JSON value sliced mid-structure.
    """
    full = json.dumps(value, indent=2, default=str)
    if len(full) <= MAX_OUTPUT_CHARS:
        return full
    for cap in (50, 25, 10, 5, 2, 1):
        s = json.dumps(_cap_lists(value, cap), indent=2, default=str)
        if len(s) <= MAX_OUTPUT_CHARS:
            return s
    # Last resort: wrap a truncated serialization as a string value so the
    # payload stays parseable JSON.
    return json.dumps({
        "_truncated": True,
        "_note": "Response too large to trim structurally; truncated. "
                 "Full response available in transcript.",
        "partial_response": full[:MAX_OUTPUT_CHARS],
    }, default=str)


def trim_crowdstrike(data):
    """Extract essential fields from CrowdStrike detection/alert responses."""
    if isinstance(data, dict) and "resources" in data:
        resources = data["resources"]
        if isinstance(resources, list):
            trimmed = []
            for r in resources[:50]:  # Cap at 50 items
                trimmed.append({
                    k: r.get(k)
                    for k in [
                        "detection_id", "composite_id", "severity",
                        "severity_name", "tactic", "technique",
                        "hostname", "local_ip", "timestamp",
                        "status", "assigned_to_name", "description",
                        "behaviors",  # Keep behaviors for context
                    ]
                    if r.get(k) is not None
                })
            result = {"resources": trimmed, "meta": data.get("meta", {})}
            # Item-cap alone doesn't bound size (large per-item fields can blow
            # past MAX_OUTPUT_CHARS), so enforce the char cap on a valid object.
            return _enforce_json_cap(result)
    return None


def trim_tenable(data):
    """Extract essential fields from Tenable vulnerability responses."""
    if isinstance(data, dict) and "vulnerabilities" in data:
        vulns = data["vulnerabilities"]
        if isinstance(vulns, list):
            trimmed = []
            for v in vulns[:50]:
                trimmed.append({
                    k: v.get(k)
                    for k in [
                        "plugin_id", "plugin_name", "severity",
                        "count", "host_count", "vpr_score",
                        "cvss_base_score", "accepted_count",
                    ]
                    if v.get(k) is not None
                })
            result = {"vulnerabilities": trimmed, "total_count": data.get("total_count")}
            return _enforce_json_cap(result)
    return None


def trim_generic(text, response_data=None):
    """Generic trimming.

    If the response was valid JSON (`response_data` provided), reduce it while
    keeping the output valid JSON — byte-slicing a serialized JSON string mid
    -structure produces unparseable output that breaks the model's downstream
    parse. Only plain (non-JSON) text is truncated by character offset.
    """
    if response_data is not None:
        return _enforce_json_cap(response_data)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    truncated = text[:MAX_OUTPUT_CHARS]
    remaining = len(text) - MAX_OUTPUT_CHARS
    return truncated + f"\n\n[...truncated {remaining:,} chars. Full response available in transcript.]"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    # PostToolUse field name varies across Claude Code versions; read all.
    response = (
        data.get("tool_response")
        or data.get("tool_result")
        or data.get("response")
        or ""
    )

    # Only process MCP tools
    if not tool_name.startswith("mcp__"):
        sys.exit(0)

    # Convert response to string for size check
    response_str = response if isinstance(response, str) else json.dumps(response, default=str)

    # Skip small responses
    if len(response_str) < TRIM_THRESHOLD:
        sys.exit(0)

    # Try tool-specific trimming
    trimmed = None

    # Parse response as JSON for structured trimming
    response_data = None
    if isinstance(response, str):
        try:
            response_data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(response, dict):
        response_data = response

    if response_data:
        if "crowdstrike" in tool_name or "remote-crowdstrike" in tool_name:
            trimmed = trim_crowdstrike(response_data)
        elif "tenable" in tool_name or "remote-tenable" in tool_name:
            trimmed = trim_tenable(response_data)

    # Fall back to generic truncation. Pass response_data so a valid-JSON
    # response is reduced as JSON (never sliced mid-structure).
    if trimmed is None:
        trimmed = trim_generic(response_str, response_data=response_data)

    # Only output if we actually trimmed
    if len(trimmed) < len(response_str):
        original_size = len(response_str)
        trimmed_size = len(trimmed)
        savings = original_size - trimmed_size

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedMCPToolOutput": trimmed
            },
            "systemMessage": f"MCP response trimmed: {original_size:,} -> {trimmed_size:,} chars ({savings:,} saved)"
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)