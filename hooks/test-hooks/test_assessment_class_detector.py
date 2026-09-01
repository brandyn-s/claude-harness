import json

from conftest import run_hook

HOOK = "assessment-class-detector.py"


def test_assessment_prompt_injects_symmetric_evidence_guidance() -> None:
    rc, stdout, stderr = run_hook(
        HOOK,
        {"prompt": "Please audit this architecture and challenge the assumptions."},
    )
    assert rc == 0 and not stderr
    payload = json.loads(stdout)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    assert "Symmetric evidentiary burden" in output["additionalContext"]


def test_casual_or_skill_payload_does_not_inject() -> None:
    for prompt in (
        "Quick question: is this okay?",
        "Base directory for this skill: /tmp/example\nPlease audit this design.",
    ):
        rc, stdout, _ = run_hook(HOOK, {"prompt": prompt})
        assert rc == 0
        assert stdout == ""


def test_non_string_prompt_fails_open() -> None:
    rc, stdout, _ = run_hook(HOOK, {"prompt": ["audit this"]})
    assert rc == 0
    assert stdout == ""
