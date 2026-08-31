#!/usr/bin/env python3
"""UserPromptSubmit hook: scan user prompts for accidentally pasted secrets.

Catches API keys, tokens, and credentials before they reach the Anthropic API.
Blocks the prompt and warns the user to remove the secret.

Crash safety: the entire body is wrapped in try/except. Per skill-standards,
a security-critical PreToolUse/UserPromptSubmit hook that crashes would
block every user prompt. On any unexpected error this hook fails OPEN
(exit 0, allow the prompt) rather than fail CLOSED — silent allow-through
on a malformed input is preferable to bricking the session, and the
secondary defense (server-side logging review) catches anything missed.
"""
import json
import re
import sys

SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI/Anthropic API key"),
    (r"sk-proj-[A-Za-z0-9_-]{20,}", "OpenAI project key"),
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic API key"),
    (r"ghp_[A-Za-z0-9]{36,}", "GitHub personal access token"),
    (r"ghs_[A-Za-z0-9]{36,}", "GitHub server token"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained PAT"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"ATATT[A-Za-z0-9_=\-]{20,}", "Atlassian API token"),
    (r"tskey-api-[A-Za-z0-9]+-[A-Za-z0-9]+", "Tailscale API key"),
    (r"pa-[A-Za-z0-9_-]{30,}", "Voyage AI API key"),
    (r"xoxb-[0-9]+-[A-Za-z0-9]+", "Slack bot token"),
    (r"xoxp-[0-9]+-[A-Za-z0-9]+", "Slack user token"),
    (r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private key"),
]


def main():
    try:
        compiled = [(re.compile(p), desc) for p, desc in SECRET_PATTERNS]
    except re.error:
        # If any pattern is malformed, fail open. Better to allow the prompt
        # than to permanently block all submissions.
        sys.exit(0)

    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError, OSError):
        sys.exit(0)

    prompt = data.get("prompt", "")
    if not isinstance(prompt, str) or not prompt:
        sys.exit(0)

    findings = []
    # Track which findings have already fired so a single key matching
    # multiple overlapping patterns (e.g., sk-ant-... matches both
    # `sk-[A-Za-z0-9]{20,}` and `sk-ant-...`) reports once per kind.
    seen = set()
    for pattern, desc in compiled:
        try:
            if pattern.search(prompt) and desc not in seen:
                findings.append(desc)
                seen.add(desc)
        except re.error:
            # A pathological prompt that hits a regex engine bug shouldn't
            # block the user; skip the offending pattern and continue.
            continue

    if findings:
        types = ", ".join(findings)
        try:
            print(
                f"[prompt-secret-scan] BLOCKED: Your prompt contains what appears to be: {types}. "
                "Remove the secret before submitting. Secrets in prompts are sent to the API "
                "and may be logged.",
                file=sys.stderr,
            )
        except OSError:
            pass
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Last-resort fail-open. Crash-safety per skill-standards.
        sys.exit(0)
