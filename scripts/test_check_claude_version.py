"""Tests for the installer Claude Code version preflight."""

from __future__ import annotations

import pytest
from check_claude_version import parse_version, validate_version


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("2.1.223 (Claude Code)", (2, 1, 223)),
        ("claude version 2.2.0", (2, 2, 0)),
        ("@anthropic-ai/claude-code v10.0.1", (10, 0, 1)),
    ],
)
def test_parse_version_accepts_supported_cli_shapes(output, expected):
    assert parse_version(output) == expected


def test_validate_version_accepts_floor_and_newer():
    assert validate_version("2.1.223") == (2, 1, 223)
    assert validate_version("2.1.224") == (2, 1, 224)


@pytest.mark.parametrize("output", ["2.1.222", "1.99.999", "2.0.999"])
def test_validate_version_rejects_versions_below_floor(output):
    with pytest.raises(ValueError, match="below the required architecture floor"):
        validate_version(output)


@pytest.mark.parametrize("output", ["", "Claude Code", "2.1", "version unknown"])
def test_parse_version_fails_loudly_on_unrecognized_output(output):
    with pytest.raises(ValueError, match="could not parse"):
        parse_version(output)
