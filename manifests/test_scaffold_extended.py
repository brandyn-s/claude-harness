"""Self-tests for the scaffold_extended CLI contract.

Runnable from CI (cross-platform — tempfile + pathlib, explicit utf-8):
    python -m manifests.test_scaffold_extended

The former KB-topic tests (create-only vs --force refresh) were removed with the
`--kb` domain: claude-knowledge-base #1239 deleted all 310
`topics/manifests/*.yaml`, made `topics/*.md` the sole authored source compiled
by `tools/kb.py`, and made that repo's `tools/kb.py check` FAIL if any per-topic
manifest reappears. Regenerating sidecars would break every knowledge-base PR,
so these tests now guard that the domain stays unreachable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import manifests.scaffold_extended as se

SCRIPT = Path(str(se.__file__)).resolve()
REPO_ROOT = SCRIPT.parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "manifests.scaffold_extended", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_kb_flag_is_rejected() -> None:
    """--kb must fail loudly, not silently write retired sidecars."""
    result = _run("--kb")
    assert result.returncode != 0, "--kb must not succeed"
    assert "unrecognized arguments: --kb" in result.stderr, result.stderr


def test_all_does_not_scaffold_kb_topics() -> None:
    """--all must not reach the retired KB domain."""
    result = _run("--all", "--dry-run")
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Knowledge Base Topics" not in combined, combined


def test_no_domain_selected_fails_without_listing_kb() -> None:
    """The usage error must not advertise the retired domain."""
    result = _run()
    assert result.returncode == 2, result.returncode
    assert "no domain selected" in result.stderr, result.stderr
    assert "--kb" not in result.stderr, "usage text still offers the retired --kb"


def test_remaining_domains_are_still_wired() -> None:
    """sessions / mcp / terraform must still dispatch."""
    for domain in ("--sessions", "--mcp", "--terraform"):
        result = _run(domain, "--dry-run")
        assert result.returncode == 0, f"{domain}: rc={result.returncode}\n{result.stderr}"


def test_retired_kb_scaffold_is_fully_removed() -> None:
    """No KB-manifest writer may survive anywhere in the module.

    The retired code wrote to ~/Documents/knowledge-base/topics/manifests/,
    which that repo's tools/kb.py check now rejects — so a dormant copy is a
    loaded gun, not harmless dead code.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    for name in ("scaffold_kb_topics", "KB_MANIFEST_DIR", "KB_DIR", "_guess_kb_category"):
        assert name not in source, f"retired KB scaffold symbol still present: {name}"
    assert not hasattr(se, "scaffold_kb_topics"), "module still exports scaffold_kb_topics"


def main() -> None:
    tests = [
        test_kb_flag_is_rejected,
        test_all_does_not_scaffold_kb_topics,
        test_no_domain_selected_fails_without_listing_kb,
        test_remaining_domains_are_still_wired,
        test_retired_kb_scaffold_is_fully_removed,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"All {len(tests)} scaffold_extended CLI tests passed")


if __name__ == "__main__":
    main()
    sys.exit(0)
