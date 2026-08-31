"""PostToolUse hook: redact high-confidence secrets from tool OUTPUT before the
model reads them — covering Bash output, Read tool content, and MCP tool output.

Defense-in-depth BELOW credential-guard (which blocks reading secret FILES) and
the sandbox denyRead globs: a tool's OUTPUT can still surface a secret that never
touched a denied file path — `env`/`printenv` dumps, cloud-CLI output
(`aws configure list`, `gh auth token`), a `git remote -v` with an embedded
token, a Read of a source file with a hardcoded key, or an MCP tool returning a
Slack message / API response that contains a token. Those land in the model's
context AND the logged telemetry. This hook replaces ONLY the secret substring
with a `[REDACTED:<type>]` marker, preserving all surrounding output.

Surface coverage rationale (fleet replay, 2026-07-13..19, real redactor patterns
over claude_code_tool_io traces): of 55 real secret-bearing tool outputs in one
week, Bash carried 25 (45%) and Read carried 23 (42%) — so a Bash-only redactor
left the majority of secret-bearing output unredacted. Extending to Read lifts
coverage to ~87%. MCP measured 0 in-window (MCP I/O may not land in that traces
view — treated as UNCHARTED, covered here defensively since the shape is known).
Write output (7/wk) is intentionally NOT redacted: its content originated from
the model, so redacting the tool_response protects nothing the model doesn't
already hold.

Mechanism (verified against code.claude.com/docs/en/hooks):
  - Bash tool_response = {stdout, stderr, interrupted, isImage} — precise path.
  - Read tool_response is a structured Output object whose EXACT field names are
    NOT documented, and `updatedToolOutput` SILENTLY falls back to the original
    output if the returned value doesn't match the tool's schema (no error). So
    for Read we do NOT hand-construct a guessed object — we recurse the received
    object and redact only its STRING LEAVES, returning the SAME structure with
    secret substrings masked. A wrong assumption degrades to "no redaction"
    (fail-open), never a crash — and the systemMessage makes a real redaction
    visible, so a silent shape-mismatch is detectable (a known-secret Read that
    produces no systemMessage = the shape isn't what we think; needs a live
    smoke test before this is trusted to enforce).
  - MCP tools use the documented `updatedMCPToolOutput` replacement field.
  - "updatedToolOutput only changes what Claude sees. The tool has already run"
    — this sanitizes the CONTEXT + logged transcript, not execution.

Patterns are HIGH-CONFIDENCE only (structured prefixes / PEM headers) so the
false-positive rate is ~0. KEEP SECRET_PATTERNS in sync with
hooks/prompt-secret-scan.py (duplicated deliberately — hooks must be
import-self-contained for marketplace bundling).

Fail-open: any error exits 0 (unredacted output reaches the model). The secret
already executed; redaction is defense-in-depth and must never brick a tool call.
"""
import json
import re
import sys

# High-confidence secret patterns (structured -> near-zero false positives).
# KEEP IN SYNC with hooks/prompt-secret-scan.py SECRET_PATTERNS. More-specific
# prefixes (sk-ant-, sk-proj-) are ordered before the generic sk- so the
# specific type label wins; once redacted, the generic pattern can't re-match.
SECRET_PATTERNS = [
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic API key"),
    (r"sk-proj-[A-Za-z0-9_-]{20,}", "OpenAI project key"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI/Anthropic API key"),
    (r"ghp_[A-Za-z0-9]{36,}", "GitHub PAT"),
    (r"ghs_[A-Za-z0-9]{36,}", "GitHub server token"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained PAT"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"ATATT[A-Za-z0-9_=\-]{20,}", "Atlassian API token"),
    (r"tskey-api-[A-Za-z0-9]+-[A-Za-z0-9]+", "Tailscale API key"),
    (r"pa-[A-Za-z0-9_-]{30,}", "Voyage AI API key"),
    (r"xoxb-[0-9]+-[A-Za-z0-9]+", "Slack bot token"),
    (r"xoxp-[0-9]+-[A-Za-z0-9]+", "Slack user token"),
    (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
     r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private key"),
]
_COMPILED = [(re.compile(p), d) for p, d in SECRET_PATTERNS]

# Bound regex cost per string: only act on the first _SCAN_CAP chars.
_SCAN_CAP = 200_000


def redact(text):
    """Return (redacted_text, [types_found]). Replaces only the matched secret
    substrings with `[REDACTED:<type>]`; all surrounding text is preserved."""
    if not isinstance(text, str) or not text:
        return text, []
    found = []
    out = text
    for rx, desc in _COMPILED:
        if not rx.search(out[:_SCAN_CAP]):
            continue
        new = rx.sub(f"[REDACTED:{desc}]", out)
        if new != out:
            found.append(desc)
            out = new
    return out, found


def redact_obj(obj, _depth=0):
    """Recursively redact secret substrings in the STRING LEAVES of a structured
    tool response, preserving the object's shape. Returns (new_obj, [types]).
    Depth-bounded so a pathological nested response can't blow the stack."""
    if _depth > 12:
        return obj, []
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        found, out = [], []
        for item in obj:
            new, f = redact_obj(item, _depth + 1)
            out.append(new)
            found += f
        return out, found
    if isinstance(obj, dict):
        found, out = [], {}
        for k, v in obj.items():
            new, f = redact_obj(v, _depth + 1)
            out[k] = new
            found += f
        return out, found
    return obj, []  # int / bool / None — nothing to redact


def _emit(updated_field, updated_value, found, surface):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            updated_field: updated_value,
        },
        "systemMessage": (
            f"output-secret-redact: redacted {', '.join(sorted(set(found)))} "
            f"from {surface} output before it entered context."
        ),
    }))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "") or ""
    resp = (data.get("tool_response") or data.get("tool_result")
            or data.get("response"))
    if resp is None:
        sys.exit(0)

    # ---- Bash: precise stdout/stderr path (unchanged contract) ----
    if tool_name == "Bash":
        if not isinstance(resp, dict):
            sys.exit(0)
        new_out, f1 = redact(resp.get("stdout", ""))
        new_err, f2 = redact(resp.get("stderr", ""))
        found = f1 + f2
        if not found:
            sys.exit(0)
        updated = dict(resp)
        updated["stdout"], updated["stderr"] = new_out, new_err
        _emit("updatedToolOutput", updated, found, "Bash")
        sys.exit(0)

    # ---- MCP tools: recurse the response, return via updatedMCPToolOutput ----
    if tool_name.startswith("mcp__"):
        new_resp, found = redact_obj(resp)
        if not found:
            sys.exit(0)
        _emit("updatedMCPToolOutput", new_resp, found, "MCP")
        sys.exit(0)

    # ---- Read (built-in): shape is undocumented, so recurse string leaves and
    #      return the SAME structure via updatedToolOutput (schema-preserving).
    #      A wrong shape assumption degrades to no-redaction (fail-open). ----
    if tool_name == "Read":
        new_resp, found = redact_obj(resp)
        if not found:
            sys.exit(0)
        _emit("updatedToolOutput", new_resp, found, "Read")
        sys.exit(0)

    sys.exit(0)  # every other tool: untouched


if __name__ == "__main__":
    # crash-safety: any unhandled error fails OPEN (exit 0).
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
