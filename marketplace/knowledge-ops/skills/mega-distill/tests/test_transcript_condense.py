from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "transcript_condense.py"


def _jwt_fixture() -> str:
    # Assemble at runtime so the test source is not itself a credential-shaped file.
    return ".".join(
        (
            "eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "eyJ" + "zdWIiOiJ0ZXN0LXVzZXIiLCJleHAiOjk5OTk5OTk5OTl9",
            "dGVzdC1zaWduYXR1cmUtdGhhdC1pcy1ub3QtcmVhbA",
        )
    )


def _api_key_fixture() -> str:
    # Assemble at runtime so the test source is not itself a credential-shaped file.
    return "sk-" + "notarealcredentialvalue123456789"


def test_condensed_slice_redacts_credentials_and_preserves_diagnostics(
    tmp_path: Path,
) -> None:
    token = _jwt_fixture()
    api_key = _api_key_fixture()
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Deploy source "
                                "f818e2c3918159937c1ba402f4bbe05fbb176066 "
                                f"with bearer {token} and api key {api_key}"
                            ),
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "slices"

    subprocess.run(
        [sys.executable, str(SCRIPT), str(transcript), "--out-dir", str(out_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    slice_text = (out_dir / "slice_000.txt").read_text(encoding="utf-8")
    assert token not in slice_text
    assert api_key not in slice_text
    assert "[REDACTED:JWT]" in slice_text
    assert "[REDACTED:API_KEY]" in slice_text
    assert "f818e2c3918159937c1ba402f4bbe05fbb176066" in slice_text
