"""PreToolUse:Skill hook - map common skill name misspellings to correct names."""
import json
import sys

ALIASES = {
    "brainstorming": "superpowers:brainstorm",
    "superpowers:brainstorming": "superpowers:brainstorm",
    "deep-research": "deep-dive",
    "security-triage": "triage",
    "productionize-mcp": "mcp-create",
    "mcp-forge": None,  # Ambiguous - needs user clarification
    "runbook-dev": None,  # Doesn't exist
    "claude-code-guide": None,  # Doesn't exist as skill
    "fast": None,  # Built-in CLI command, not a skill
}

# Built-in CLI commands that must not be routed through the Skill tool
BUILTINS = {"fast", "help", "clear", "compact", "model", "config", "cost",
            "stats", "debug", "copy", "env", "hooks", "skills", "resume",
            "rewind", "release-notes", "feedback", "powerup", "effort",
            "remote-control", "batch", "simplify", "loop"}

def _block(reason):
    """Block the Skill call. PreToolUse blocks via exit 2 + a stderr reason
    (the repo convention — see block-partial-read.py / destructive-ops-guard.py).
    The old `{"result": "block"}` on stdout with exit 0 was an unrecognized
    shape the harness ignored, so aliased/misspelled skills ran anyway."""
    sys.stderr.write("[skill-alias] BLOCKED: " + reason + "\n")
    sys.exit(2)


try:
    hook_input = json.loads(sys.stdin.read())
    tool_input = hook_input.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    if skill_name in BUILTINS:
        _block(
            f'"{skill_name}" is a built-in CLI command, not a skill. Type '
            f"/{skill_name} directly in the prompt instead of using the Skill tool."
        )

    if skill_name in ALIASES:
        correct = ALIASES[skill_name]
        if correct:
            _block(f'Skill "{skill_name}" does not exist. Use "{correct}" instead.')
        elif skill_name == "mcp-forge":
            _block(
                'Ambiguous: did you mean "mcp-forge-build" (create new server) '
                'or "mcp-forge-audit" (audit existing server)?'
            )
        else:
            _block(f'Skill "{skill_name}" does not exist. Check available skills.')

    # Not an alias / builtin — allow the Skill call through.
    sys.exit(0)
except SystemExit:
    raise
except Exception:
    sys.exit(0)
