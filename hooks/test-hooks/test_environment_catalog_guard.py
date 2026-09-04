"""Guard: converted hook sources carry no environment names.

The hooks listed in CONVERTED used to hard-code the author's former workplace:
the MCP servers that existed there, the vendor tools whose writes warranted a
confirmation, the topic files loaded per tool prefix, the failure-pattern files
per server, and the author's local repo paths. That data now lives in the
environment catalog (contracts/environment-catalog.json, the operator's
~/.claude/environment-catalog.json, or the file named by
CLAUDE_ENVIRONMENT_CATALOG) and in the test fixture under fixtures/. The hook
LOGIC must stay generic, so no converted source may mention any of the names
below, in code, comments or docstrings.

Written 2026-09-04 BEFORE the conversion and watched failing on the untouched
sources (96 sweep hits across hooks/ at the time), so a green run here is
evidence the names left the code, not evidence the guard never looked.

hooks/protected-repos.json and the dispatcher hooks that read it are exempt: it
is already a data file (the canonical protected-repository list) and is the
precedent for the catalog's shape.
"""
import re
from pathlib import Path

# validate-hook-paths-target: hooks/_environment_catalog.py
import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent

# Every hook whose environment data moved into the catalog, plus the loader.
# session_start_modules/mcp_binary_staleness.py was judged author-only in the
# 2026-09-04 report (it watched two specific local clones and their build
# artifacts) and was deleted rather than converted.
CONVERTED = [
    "_environment_catalog.py",
    "security-write-confirm.py",
    "auto-topic-loader.py",
    "subagent-stop.py",
    "post-failure-guide.py",
    "pre-agent-dispatch.py",
    "session-start.py",
    "session_start_modules/consistency.py",
    "session_start_modules/repo_sync.py",
    "session_start_modules/index_staleness.py",
    "session_start_modules/code_search_stale_project_guard.py",
    "session_start_modules/env_loader.py",
]

# Vendor / gateway server names, topic files and author repo paths. Matched
# case-insensitively anywhere in the file; the two short words that are also
# ordinary English (ramp, lever) are anchored so "cramp" or "leverage" cannot
# trip them, while "ramp_", "ramp-patterns" and "lever sunset" still do.
FORBIDDEN = [
    r"crowdstrike", r"falcon", r"tenable", r"airlock", r"msgraph",
    r"security-remix", r"netcloud", r"\bramp(?:\b|[_-])", r"\blever(?:\b|[_-])",
    r"hologram", r"lucid", r"ashby", r"knowbe4", r"palantir", r"jamf", r"intune",
    r"documents/github", r"claude-config", r"mcp-servers", r"mcp-infra",
    r"code-search",
]
_FORBIDDEN_RE = re.compile("|".join(f"({p})" for p in FORBIDDEN), re.IGNORECASE)


def _hits(path: Path) -> list[str]:
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in _FORBIDDEN_RE.finditer(line):
            out.append(f"{path.relative_to(HOOKS_DIR)}:{lineno}: {m.group(0)!r}: {line.strip()[:90]}")
    return out


@pytest.mark.parametrize("rel", CONVERTED)
def test_converted_hook_source_names_no_environment(rel):
    path = HOOKS_DIR / rel
    assert path.is_file(), f"{rel} is listed as converted but does not exist"
    hits = _hits(path)
    assert not hits, (
        f"{len(hits)} environment name(s) in {rel}; move them into the catalog:\n"
        + "\n".join(hits)
    )


@pytest.mark.parametrize("sample", [
    "mcp__remote-crowdstrike__contain_host",
    "RAMP_OP_PREFIX = 'ramp_'",
    "Lever sunset 2026-07-24",
    "~/Documents/GitHub/mcp-servers",
    '"code-search": Path.home()',
    "ACTION REQUIRED: claude-config is on branch",
])
def test_guard_pattern_catches_known_positives(sample):
    """A scanner reporting nothing and a broken scanner look the same without this."""
    assert _FORBIDDEN_RE.search(sample), sample


@pytest.mark.parametrize("sample", [
    "leverage the existing budget",   # 'lever' followed by letters is another word
    "tramp_stamp_case",               # 'ramp_' only counts at a word start
    "the cramped table",
    "mcp__slack-user__send_message",  # not an environment name the guard covers
])
def test_guard_pattern_ignores_ordinary_words(sample):
    assert not _FORBIDDEN_RE.search(sample), sample
