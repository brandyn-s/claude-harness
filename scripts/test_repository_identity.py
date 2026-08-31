"""Regression tests for the repository's canonical GitHub identity."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_codeowners_does_not_reference_old_organization() -> None:
    codeowners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")

    assert "@example-org/" not in codeowners


def test_active_install_and_reporting_surfaces_use_canonical_repository() -> None:
    deprecated = (
        "you-s/claude-config",
        "example-org/claude-config",
    )
    active_surfaces = (
        "README.md",
        "ARCHITECTURE.md",
        "install.sh",
        "scripts/build-marketplace.py",
        "scripts/retro-extract.py",
        ".claude-plugin/marketplace.json",
    )

    for relative_path in active_surfaces:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for old_identity in deprecated:
            assert old_identity not in text, (
                f"{relative_path} still references {old_identity}"
            )
