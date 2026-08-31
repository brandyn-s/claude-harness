"""UserPromptSubmit hook: detect assessment-class user prompts and inject
guidance to apply symmetric-evidentiary-burden + run /interview before
publishing refutations of 2+ proposal points.

Created 2026-04-29 in response to the chat-audit incident where 4 of 7
refutations were reversed and 2 weakened on second-pass research because
the original audit applied asymmetric evidentiary standards (single-source
or pre-LLM citations as primary refutation evidence).

Trigger phrases match: "objective thoughts", "honest assessment", "audit
this", "red team", "what's wrong with", "critique this", "challenge this",
"poke holes", "what am I missing", "refute", and similar audit-class
language.

The hook is non-blocking and fail-silent. It emits an additionalContext
systemMessage reminding the model to:
  1. Apply ~/.claude/rules/symmetric-evidentiary-burden.md
  2. Apply ~/.claude/rules/uncharted-vs-refuted.md
  3. Run /interview against own draft if refuting 2+ points
  4. Apply citation-domain freshness check (skills/gather-research/references/citation-domain-freshness.md)
     for LLM-era behavioral claims (≤18 months, model-class match for PRIMARY)

Exit codes:
  0 = continue (with optional additionalContext)
  Non-zero = block (not used here; this hook never blocks)
"""

import json
import re
import sys


# Compile patterns once at module load
_ASSESSMENT_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bobjective\s+(thoughts|assessment|view|opinion|take)\b",
        r"\bhonest\s+(assessment|review|opinion|thoughts|take)\b",
        r"\baudit\s+(this|that|the|my|these|those)\b",
        r"\b(red[- ]?team|stress[- ]?test)\s+(this|that|the|my|these|those)\b",
        r"\bwhat'?s?\s+wrong\s+with\s+(this|that|these|the|my)\s+(approach|design|plan|proposal|argument|reasoning|claim|assessment|recommendation|theory|hypothesis|methodology|framework|strategy)\b",
        r"\bcritique\s+(this|that|the|my|these|those)\b",
        r"\bchallenge\s+(this|that|these|those|my|the)\b",
        r"\bpoke\s+holes\b",
        r"\bwhat\s+am\s+I\s+missing\b",
        r"\b(refute|debunk|disprove)\b",
        r"\bsecond[- ]opinion\b",
        r"\b(your|claude'?s?)\s+(objective\s+)?(thoughts|view|take|opinion)\s+on\b",
        r"\b(is|are)\s+(this|that|these)\s+(right|correct|sound|valid|accurate)\b",
        r"\b(verify|validate|fact[- ]?check)\s+(this|that|the|my)\s+(claim|argument|reasoning|assessment)\b",
        r"\b(steel[- ]?man|devil'?s?\s+advocate)\b",
        # 2026-06-12 (Fable 5 recompute): the week's genuine assessment
        # request ("I want you to assess my claude code architecture")
        # matched none of the patterns above — direct assess/evaluate
        # verb-plus-object forms were missing entirely.
        r"\bassess\s+(my|our|this|that|these|those|the|its|whether)\b",
        r"\b(re-?assess|evaluate)\s+(my|our|this|that|these|those|the|whether)\b",
    ]
]

# Skip if user has explicitly framed as casual/conversational
_SKIP_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^(quick|short|brief)\s+(question|q):",
        r"\bgut\s+(check|reaction|take)\b",
        r"\bjust\s+curious\b",
    ]
]

# Skip if prompt is too short to be an assessment request
_MIN_LENGTH = 25

GUIDANCE_TEXT = (
    "[ASSESSMENT-CLASS REQUEST DETECTED]\n\n"
    "This prompt asks for an audit, refutation, critique, or load-bearing "
    "assessment. Before publishing the response, apply:\n\n"
    "1. **Symmetric evidentiary burden** "
    "(`~/.claude/rules/symmetric-evidentiary-burden.md`): refutations need "
    "the same multi-source 2024+ bar as the claims they assess. Single-source "
    "counter-evidence is preliminary signal, NOT refutation.\n\n"
    "2. **Citation-domain freshness** "
    "(`skills/gather-research/references/citation-domain-freshness.md`): for "
    "LLM-era behavioral claims about specific model classes (Opus 4.5+, "
    "GPT-5+, Gemini 3+), only sources tested on that model class within "
    "the last 18 months count as PRIMARY evidence. Pre-LLM citations cannot "
    "refute LLM-era claims.\n\n"
    "3. **Uncharted vs refuted** "
    "(`~/.claude/rules/uncharted-vs-refuted.md`): absence of supporting "
    "evidence in your search is UNCHARTED, not REFUTED. Document what you "
    "searched. Don't fill in absence with assertion.\n\n"
    "4. **Self-interview gate**: if your draft refutes 2+ proposal points, "
    "run `/interview` against your OWN draft (not just the proposal's claims) "
    "before presenting. Asymmetric stress-testing is the failure mode this "
    "guidance exists to prevent (2026-04-29 chat-audit incident: 4 of 7 "
    "refutations reversed on second-pass multi-source research).\n\n"
    "5. **Verdict labels**: distinguish REFUTED (≥3 PRIMARY sources contradict) "
    "/ CONTESTED (mixed PRIMARY) / SUPPORTED (≥2 PRIMARY confirm) / UNCHARTED "
    "(0 PRIMARY) — single-source items go in CONTESTED with the source noted "
    "as preliminary, not REFUTED."
)


def _is_assessment_prompt(prompt: str) -> bool:
    """Return True if the prompt looks like an assessment-class request."""
    if not prompt or len(prompt) < _MIN_LENGTH:
        return False

    # Skill-invocation payloads arrive through UserPromptSubmit but are not
    # user-authored prose. On this host they were 23/23 of this hook's
    # matches (the /retro skill body contains assessment language) while
    # real user prompts matched 0/284 (2026-06-12 Fable 5 recompute).
    if "Base directory for this skill" in prompt[:300]:
        return False

    # Skip if user explicitly framed as casual
    for pat in _SKIP_PATTERNS:
        if pat.search(prompt):
            return False

    # Match assessment patterns
    for pat in _ASSESSMENT_PATTERNS:
        if pat.search(prompt):
            return True

    return False


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        # Fail silent — don't block on hook input errors
        sys.exit(0)

    # Try multiple known field names for the user prompt
    prompt = (
        data.get("prompt")
        or data.get("user_message")
        or data.get("userMessage")
        or data.get("message")
        or ""
    )

    if not isinstance(prompt, str):
        sys.exit(0)

    if not _is_assessment_prompt(prompt):
        sys.exit(0)

    # Emit guidance via hookSpecificOutput.additionalContext
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": GUIDANCE_TEXT,
        }
    }

    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)