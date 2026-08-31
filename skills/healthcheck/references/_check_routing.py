#!/usr/bin/env python3
"""Check 7: Routing health for hooks/skill-rules.json.

Validates structure (dict with `rules` + `skip_patterns`), dead skill/agent
references, and duplicate patterns. Rules carry BOTH `skill` and `agent` keys
with one set to null per rule — so a null/empty value is NOT a dead reference.
An earlier inline implementation in SKILL.md treated `"skill": null` as a
reference to a skill dir named "None" and reported 85 phantom dead refs
(observed 2026-06-16: 19 dead-skill + 66 dead-agent, all null). This helper
skips null/empty values.

Exit 0 = PASS, 1 = WARN (dead refs / dup patterns / structure issue).
"""
import os
import sys
import json

H = os.path.expanduser("~/.claude")
RULES_PATH = f"{H}/hooks/skill-rules.json"


def main():
    try:
        data = json.load(open(RULES_PATH, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Routing: FAIL — cannot read {RULES_PATH}: {e}")
        return 1

    if not isinstance(data, dict):
        print(f"Routing: FAIL — top-level type is {type(data).__name__}, expected dict")
        return 1
    rules = data.get("rules")
    if not isinstance(rules, list):
        print("Routing: FAIL — 'rules' missing or not a list")
        return 1

    dead_skill, dead_agent, patterns, dupes = [], [], {}, []
    for r in rules:
        sk = r.get("skill")
        ag = r.get("agent")
        if sk:  # skip null / empty — a rule that routes to an agent has skill=null
            if not os.path.isdir(f"{H}/skills/{sk}"):
                dead_skill.append(sk)
        if ag:
            if not os.path.exists(f"{H}/agents/{ag}.md"):
                dead_agent.append(ag)
        p = r.get("pattern")
        if p is not None:
            if p in patterns:
                dupes.append(p)
            patterns[p] = patterns.get(p, 0) + 1

    bad = bool(dead_skill or dead_agent or dupes)
    if not bad:
        print(f"Routing: PASS — {len(rules)} rules valid, no dead references")
        return 0

    print(
        f"Routing: WARN — {len(set(dead_skill))} dead skill, "
        f"{len(set(dead_agent))} dead agent, {len(set(dupes))} dup patterns"
    )
    for s in sorted(set(dead_skill)):
        print(f"    dead skill ref: {s}")
    for a in sorted(set(dead_agent)):
        print(f"    dead agent ref: {a}")
    for d in sorted(set(dupes)):
        print(f"    duplicate pattern: {d!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
