#!/usr/bin/env python3
"""No organisation identifier may remain in this export -- or enter it.

The README claims internal identifiers were replaced with neutral placeholders.
Measured 2026-09-03 that was incomplete: an endpoint-security tenant hostname and
object id, an identity-tenant app-id prefix, two employee first names inside an
incident narrative, one programme codename beside a scrubbed one, seven launchd
template filenames, and three claude.ai connector UUIDs survived.

The scanner lives in scripts/deidentification_residue.py (denylist as SHA-256
digests of lower-cased tokens, so this test does not itself republish the
identifiers it forbids; structural rules for the shapes that cannot be hashed).
This file is the gate over every tracked file, plus the known-positive controls
for each surface the scanner guards: files, staged files, a commit message, a
commit range.

Run: pytest scripts/test_deidentification_residue.py -q
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCANNER = REPO / "scripts" / "deidentification_residue.py"
_spec = importlib.util.spec_from_file_location("deidentification_residue", SCANNER)
dr = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dr
_spec.loader.exec_module(dr)

scan_text = dr.scan_text
CONTROL_TOKEN = dr.CONTROL_TOKEN
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL="/dev/null")


def test_no_organisation_identifiers_in_tracked_files():
    files = dr.tracked_files(REPO)
    assert len(files) > 1000, "git ls-files returned too few files; fixture is wrong"
    offenders = dr.scan_files(files, REPO)
    assert offenders == {}, (
        f"{len(offenders)} tracked file(s) still carry organisation identifiers:\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(offenders.items()))
    )


def test_scanner_detects_a_planted_control_token(tmp_path):
    """Known-positive: a zero from a scanner that cannot fire proves nothing."""
    planted = tmp_path / "planted.md"
    planted.write_text(f"harmless words {CONTROL_TOKEN} more words\n", encoding="utf-8")
    assert scan_text(planted.read_text(encoding="utf-8")) == [CONTROL_TOKEN]
    assert scan_text("mcp__12345678-1234-1234-1234-123456789abc__tool") != []
    assert scan_text("nothing to see here") == []


def _run(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCANNER), *args], input=stdin, capture_output=True,
                          text=True, timeout=120, env=GIT_ENV)


def test_commit_message_surface_fires_on_the_control_and_masks_by_default(tmp_path):
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(f"fix: tidy the {CONTROL_TOKEN} path\n\n# Please enter the commit message\n", encoding="utf-8")
    res = _run("--message-file", str(msg))
    assert res.returncode == 1
    assert CONTROL_TOKEN not in res.stderr and "r*****" in res.stderr, "masked by default"
    assert CONTROL_TOKEN in _run("--message-file", str(msg), "--reveal").stderr
    msg.write_text(f"# the comment line is stripped by git: {CONTROL_TOKEN}\nfix: clean\n", encoding="utf-8")
    assert _run("--message-file", str(msg)).returncode == 0


def test_stdin_surface():
    assert _run("--stdin", stdin="plain words").returncode == 0
    assert _run("--stdin", stdin=f"words {CONTROL_TOKEN}").returncode == 1


def test_commit_range_and_staged_surfaces_over_a_throwaway_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True, env=GIT_ENV)  # noqa: E731
    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("clean\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "clean start")
    (repo / "b.txt").write_text("also clean\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", f"mention the {CONTROL_TOKEN} in a message")
    res = _run("--repo", str(repo), "--commits", "HEAD~1..HEAD")
    assert res.returncode == 1 and "commit " in res.stderr
    assert _run("--repo", str(repo), "--commits", "HEAD~1^!").returncode == 0     # the clean root commit alone
    (repo / "c.txt").write_text(f"planted {CONTROL_TOKEN}\n", encoding="utf-8")
    git("add", "c.txt")
    res = _run("--repo", str(repo), "--staged")
    assert res.returncode == 1 and "c.txt" in res.stderr
    git("reset", "-q", "c.txt")
    assert _run("--repo", str(repo), "--staged").returncode == 0


def test_git_hooks_call_the_scanner():
    commit_msg = (REPO / ".githooks" / "commit-msg").read_text(encoding="utf-8")
    pre_commit = (REPO / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "deidentification_residue.py" in commit_msg and "--message-file" in commit_msg
    assert "deidentification_residue.py" in pre_commit and "--staged" in pre_commit
    for hook in (REPO / ".githooks" / "commit-msg", REPO / ".githooks" / "pre-commit"):
        assert os.access(hook, os.X_OK), f"{hook.name} must be executable"
    workflow = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "deidentification_residue.py --commits" in workflow, "CI scans a pull request's commit messages"
    assert "fetch-depth: 0" in workflow, "the commit-range scan needs history"


def test_structural_rules_catch_tenant_subdomains_and_emails_but_not_placeholders():
    """Known-positive controls for the shapes the digests cannot hold."""
    tenant = "<vendor tenant subdomain (an organisation's own instance of a vendor product)>"
    email = "<email address at a non-placeholder domain>"
    for text in ("https://northwind.atlassian.net/wiki", "contoso.onmicrosoft.com", "https://mycorp.jamfcloud.com/api",
                 "ws-northwind.slack.com", "https://northwind.us.auth0.com/authorize", "dev12345.service-now.com",
                 "northwind.my.salesforce.com", "https://northwind.okta.com/oauth2"):
        assert tenant in scan_text(text), text
    for text in ("https://api.slack.com/methods", "example.atlassian.net", "docs.atlassian.net", "hooks.slack.com/services/x",
                 "login.microsoftonline.com", "tenant.onmicrosoft.com", "your.jamfcloud.com"):
        assert tenant not in scan_text(text), text
    for text in ("reach me at jane.doe@somecompany.com", "cc: ops-team@northwind.io"):
        assert email in scan_text(text), text
    for text in ("t@example.com", "a.b@example.internal", "git@github.com:example-org/x.git", "noreply@users.noreply.github.com",
                 "GIT_AUTHOR_EMAIL=t@e.com", "x@anthropic.com", "svc@mail.example.org", "q@thing.invalid"):
        assert email not in scan_text(text), text
