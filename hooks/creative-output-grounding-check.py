#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Creative-output grounding check.

PostToolUse advisory payload diagnostic scoped to Skill invocations of
creative-discovery skills. When Claude Code provides a substantive Skill tool
response, scans that payload for three trust-calibration signals:
  1. Confidence labels (HIGH/MEDIUM/LOW or hedging language)
  2. Provenance (URL / [INFERRED] tag / [DISPUTED] tag / DOI)
  3. Counterfactual (inverted hypothesis offered for at least one recommendation)

Non-blocking (always exit 0). Emits a systemMessage warning when an available
substantive payload is missing signals. Normal Skill results are launcher
metadata, not the later user-facing answer, so this hook cannot grade the final
answer and silence is not evidence of compliance. The prompt/evaluation
contract in skills/_shared/output-grounding.md remains the enforcement surface.
"""

import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Skills this hook applies to (creative-discovery / knowledge-asymmetric)
TARGET_SKILLS = {
    "scout-frontier",
    "brainstorm",
    "deep-dive",
    "refine",
}

# Confidence indicators (any one match satisfies Layer 1).
# These patterns must look like an EXPLICIT calibration signal, not a
# vague hedge word in passing prose. The earlier
# r"\b(?:likely|probable|uncertain|confident|approximately|roughly|estimated)\b"
# matched any English sentence containing "likely" (e.g., "this is likely
# what you want" — no calibration content), defeating the layer's purpose.
# Real calibration signals always co-occur with a noun like
# "confidence/grade/certainty" OR a percentage OR an explicit
# tier label.
CONFIDENCE_PATTERNS = [
    r"\b(?:HIGH|MEDIUM|LOW)\s+(?:confidence|grade|tier|certainty)\b",
    r"\b\d{1,3}\s*%\s*(?:confidence|certain|likely|sure|probability)\b",
    r"\bconfidence\s*[:=]\s*(?:high|medium|low)\b",
    # Hedge words paired with an explicit calibration anchor — both
    # required, not either-or.
    r"\b(?:likely|probable|uncertain|approximately|roughly|estimated)\b[^.\n]{0,80}\b(?:confidence|certainty|probability|estimate|grade)\b",
    r"\b(?:confidence|certainty|probability|estimate|grade)\b[^.\n]{0,80}\b(?:likely|probable|uncertain|approximately|roughly|estimated)\b",
]

# Provenance indicators (any one match satisfies Layer 2)
PROVENANCE_PATTERNS = [
    r"https?://[^\s\)\]>]+",
    r"\barXiv:\s*\d{4}\.\d{4,5}\b",
    r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b",
    r"\[INFERRED\]",
    r"\[DISPUTED\]",
    r"\bDOI\s*:\s*\S+",
]

# Counterfactual indicators (any one match satisfies Layer 3)
COUNTERFACTUAL_PATTERNS = [
    r"\bif\s+\w+\s+(?:were|was|did)\s+not\b",
    r"\bcounterfactual\b",
    r"\binverted\s+(?:hypothesis|relationship|analogy)\b",
    r"\bwhat\s+if\b",
    r"\balternative\s+(?:hypothesis|interpretation|framing)\b",
    r"\bsurvives?\s+counterfactual\b",
    r"\bcollapses?\s+under\s+counterfactual\b",
]

# Skip patterns: when the skill result is a meta-message (forked execution,
# launching, error) the actual skill output lives elsewhere (saved to file,
# in the forked subagent's context). The hook cannot audit content that
# doesn't pass through PostToolUse, so it stays silent on these.
SKIP_META_PATTERNS = [
    r"^Launching skill:\s",
    r"completed\s*\(forked execution\)",
    r"<tool_use_error>",
    r"\bReport saved\b",
    # Anchor "saved to <path>.md" to the START of a line and require the
    # path to be short and self-contained — meta-messages look like
    # "Report saved to docs/foo.md" on their own line. The prior pattern
    # matched ANY substantive output that ALSO contained "saved to ...
    # .md" anywhere (skill outputs reference output paths inline), and
    # silenced the entire grounding check.
    r"(?im)^\s*(?:report\s+)?saved\s+to\s+[^\s]+\.md\s*\.?\s*$",
    r"\bsaved successfully\b",
]

# Minimum content length: shorter than this is almost certainly a meta-message,
# not substantive skill output. Empirically calibrated against historical replay.
MIN_CONTENT_LEN = 500


def has_pattern(text: str, patterns: list[str]) -> bool:
    """Return True if any of the patterns matches."""
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False


def extract_skill_name(hook_input: dict) -> str | None:
    """Pull skill name from hook input. Returns None if non-Skill tool call."""
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Skill":
        return None
    tool_input = hook_input.get("tool_input", {}) or {}
    skill = tool_input.get("skill") or tool_input.get("name")
    if not isinstance(skill, str):
        return None
    return skill.strip().lstrip("/")


def main() -> None:
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Malformed input: do not block, do not warn (could not parse).
        sys.exit(0)

    skill_name = extract_skill_name(hook_input)
    if skill_name is None or skill_name not in TARGET_SKILLS:
        # Not a creative-discovery skill — out of scope for this hook.
        sys.exit(0)

    # PostToolUse field name varies across Claude Code versions; read all.
    tool_result = (
        hook_input.get("tool_response")
        or hook_input.get("tool_result")
        or hook_input.get("response")
        or ""
    )
    if not isinstance(tool_result, str) or not tool_result.strip():
        sys.exit(0)

    # Skip when result is a meta-message (forked execution, launch, error)
    # rather than substantive skill output. The actual content lives in the
    # saved file or the subagent's context — we cannot audit through this hook.
    for pat in SKIP_META_PATTERNS:
        if re.search(pat, tool_result, flags=re.IGNORECASE):
            sys.exit(0)

    # Short results are almost always meta-messages. Skip rather than warn.
    if len(tool_result) < MIN_CONTENT_LEN:
        sys.exit(0)

    has_confidence = has_pattern(tool_result, CONFIDENCE_PATTERNS)
    has_provenance = has_pattern(tool_result, PROVENANCE_PATTERNS)
    has_counterfactual = has_pattern(tool_result, COUNTERFACTUAL_PATTERNS)

    missing = []
    if not has_confidence:
        missing.append("confidence labels (HIGH/MEDIUM/LOW or hedging)")
    if not has_provenance:
        missing.append("provenance (URL / [INFERRED] / DOI)")
    if not has_counterfactual:
        missing.append("counterfactual (inverted hypothesis)")

    if not missing:
        # All three layers present — silent.
        sys.exit(0)

    if len(missing) == 1:
        warning = (
            f"OUTPUT GROUNDING: /{skill_name} output is missing "
            f"{missing[0]}. The three-layer defense (skills/_shared/output-grounding.md) "
            f"requires all three signals for knowledge-asymmetric outputs. "
            f"Add the missing signal before treating output as actionable."
        )
    else:
        joined = "; ".join(missing)
        warning = (
            f"OUTPUT GROUNDING: /{skill_name} output is missing 2+ signals: "
            f"{joined}. Per skills/_shared/output-grounding.md three-layer defense, "
            f"add confidence + provenance + counterfactual before the user "
            f"acts on these recommendations. Without these, plausible-but-wrong "
            f"output reads as authoritative (AI Scientist v2 57% false-data "
            f"failure mode)."
        )

    print(json.dumps({"systemMessage": warning}))
    sys.exit(0)


if __name__ == "__main__":
    main()
