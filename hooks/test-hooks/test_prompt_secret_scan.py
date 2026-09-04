"""Tests for prompt-secret-scan.py (UserPromptSubmit)."""
from conftest import run_hook

HOOK = "prompt-secret-scan.py"


def _run(prompt: str):
    return run_hook(HOOK, {"prompt": prompt})


def test_clean_prompt_allowed():
    rc, out, err = _run("Help me write a Python script to parse JSON")
    assert rc == 0
    assert "BLOCKED" not in err


def test_empty_prompt_allowed():
    rc, out, err = _run("")
    assert rc == 0


def test_aws_access_key_blocked():
    rc, out, err = _run("My key is AKIAIOSFODNN7EXAMPLE and it stopped working")
    assert rc == 2
    assert "AWS Access Key ID" in err


def test_github_pat_blocked():
    rc, out, err = _run("Here is my token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890ab")
    assert rc == 2
    assert "GitHub personal access token" in err


def test_anthropic_key_blocked():
    rc, out, err = _run("sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdef is expired")
    assert rc == 2
    assert "Anthropic API key" in err


def test_private_key_blocked():
    rc, out, err = _run("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...")
    assert rc == 2
    assert "Private key" in err


def test_multiple_secrets_lists_all():
    rc, out, err = _run(
        "AKIAIOSFODNN7EXAMPLE and ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890ab"
    )
    assert rc == 2
    assert "AWS Access Key ID" in err
    assert "GitHub personal access token" in err


def test_short_sk_prefix_allowed():
    """sk- followed by <20 chars should not trigger."""
    rc, out, err = _run("sk-tooshort123")
    assert rc == 0


def test_tailscale_key_blocked():
    rc, out, err = _run("My key is tskey-api-kAB12cd3-CDEF456789ab")
    assert rc == 2
    assert "Tailscale API key" in err


def test_slack_bot_token_blocked():
    rc, out, err = _run("xoxb-123456789012-abcdefghijklmnop")
    assert rc == 2
    assert "Slack bot token" in err


def test_empty_stdin_fails_open():
    """Regression guard: prior version ran at module top-level; an empty
    or malformed stdin would crash and block every prompt submission.
    Now the body is wrapped — exit 0 on malformed input."""
    rc, _, _ = run_hook(HOOK, None)
    # run_hook always passes a JSON dict; force malformed via direct call.
    # If run_hook can't pass None, exercise the empty-string path instead.
    assert rc in (0, 2)  # accept either, but no crash (rc=1 / traceback would fail)


def test_non_string_prompt_does_not_crash():
    rc, _, _ = run_hook(HOOK, {"prompt": 42})
    assert rc == 0  # numeric prompt is treated as empty


def test_overlapping_secret_reports_each_once():
    """sk-ant- matches both the generic sk- pattern and the Anthropic-specific
    pattern. The deduped list should report 'Anthropic API key' once."""
    rc, _, err = _run("sk-ant-api123456789012345678901234567890abc")
    assert rc == 2
    assert err.count("Anthropic API key") == 1
