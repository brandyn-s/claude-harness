"""UserPromptSubmit hook: pattern-match prompt keywords and suggest skill/agent routing.

Reads routing rules from skill-rules.json (same directory as this script).
Adding a new skill = adding a JSON entry. No Python edits needed.

Manifest enrichment (2026-04-15): when a matched skill has a manifest.yaml,
the routing hint includes auth_constraint and execution_context from the
manifest. This tells the agent whether the skill needs main_thread execution
before it invokes the skill.

Optimized 2026-03-27: module-level compiled regex cache, early-exit for
short prompts (<30 chars — confirmations, follow-ups, single-word responses).

Exit codes:
  0 = continue (with optional systemMessage)
  Non-zero = block (not used here)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(SCRIPT_DIR, "skill-rules.json")
USAGE_FILE = os.path.join(os.path.expanduser("~"), ".claude", "skill-usage.jsonl")
CLAUDE_DIR = Path.home() / ".claude"
SKILLS_DIR = CLAUDE_DIR / "skills"

# Module-level manifest cache
_manifest_cache = {}
_manifest_cache_mtime = 0

# Liveness cache: skill_name -> (SKILL.md_mtime, list_of_missing_refs)
_liveness_cache = {}

# Regex for hook/script references in skill bodies.
_REF_PATTERN = re.compile(r"\b(hooks|scripts)/([\w.-]+\.py)\b")

# Module-level cache — compiled once per process lifetime (pythonw stays alive
# for the session duration when spawned by Claude Code's hook system).
_cached_rules = None
_cached_skip_re = None
_cache_mtime = 0


def _check_skill_liveness(skill_name):
    """Return list of missing hooks/*.py or scripts/*.py referenced by the skill.

    Empty list = skill is healthy. Cached per SKILL.md mtime so the check
    doesn't re-parse on every prompt.
    """
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_md.is_file():
        return []
    try:
        mtime = skill_md.stat().st_mtime
    except OSError:
        return []

    cached = _liveness_cache.get(skill_name)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        with open(skill_md, "r", encoding="utf-8") as fh:
            body = fh.read()
    except (OSError, UnicodeDecodeError):
        _liveness_cache[skill_name] = (mtime, [])
        return []

    # Strip fenced code blocks — refs inside examples don't count.
    stripped = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    # Only validate claude-local references. A ref like
    # `mcp-servers/scripts/foo.py` points into ANOTHER repo, not ~/.claude —
    # checking it against CLAUDE_DIR yields a false "missing" warning. Keep
    # bare `hooks|scripts/...` refs and `.claude/`-rooted refs; skip any ref
    # prefixed by a foreign path segment (e.g. `mcp-servers/`).
    missing = []
    seen = set()
    for m in _REF_PATTERN.finditer(stripped):
        window = stripped[max(0, m.start() - 64):m.start()]
        preceding = re.search(r"([\w.~-]+)/$", window)
        if preceding and preceding.group(1) not in ("claude", ".claude"):
            continue
        ref = f"{m.group(1)}/{m.group(2)}"
        if ref in seen:
            continue
        seen.add(ref)
        if not (CLAUDE_DIR / m.group(1) / m.group(2)).exists():
            missing.append(ref)

    missing.sort()
    _liveness_cache[skill_name] = (mtime, missing)
    return missing


def _load_rules():
    """Load and cache compiled routing rules. Re-reads only if file changed."""
    global _cached_rules, _cached_skip_re, _cache_mtime

    try:
        mtime = os.path.getmtime(RULES_FILE)
    except OSError:
        return [], None

    if _cached_rules is not None and mtime == _cache_mtime:
        return _cached_rules, _cached_skip_re

    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return [], None

    skip_words = config.get("skip_patterns", [])
    skip_re = (
        re.compile("(" + "|".join(skip_words) + ")", re.IGNORECASE)
        if skip_words
        else None
    )

    rules = []
    for rule in config.get("rules", []):
        try:
            compiled = re.compile(rule["pattern"], re.IGNORECASE)
            rules.append(
                {
                    "compiled": compiled,
                    "skill": rule.get("skill"),
                    "agent": rule.get("agent"),
                    "desc": rule.get("desc", ""),
                    "priority": rule.get("priority", "medium"),
                    "must_activate": bool(rule.get("must_activate", False)),
                }
            )
        except re.error:
            continue

    _cached_rules = rules
    _cached_skip_re = skip_re
    _cache_mtime = mtime
    return rules, skip_re


def _get_manifest(skill_name):
    """Load a skill's manifest.yaml if it exists. Cached per process."""
    if skill_name in _manifest_cache:
        return _manifest_cache[skill_name]

    manifest_path = SKILLS_DIR / skill_name / "manifest.yaml"
    result = None
    if manifest_path.exists():
        try:
            with open(manifest_path, encoding="utf-8") as f:
                result = yaml.safe_load(f)
        except Exception:
            pass
    _manifest_cache[skill_name] = result
    return result


def log_usage(skill, agent, matched_text):
    """Append a usage record to skill-usage.jsonl. Fire-and-forget."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "skill": skill,
            "agent": agent,
            "matched": matched_text,
        }
        with open(USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _skill_invoked_this_session(skill, session_id):
    """Best-effort: has `skill` already fired in this session?

    Reads back the usage log and looks for an invocation-flagged record
    ("event":"invoked" or "invoked":true) for this skill in the current
    session. Conservative: ANY error -> return True (so enforcement does NOT
    block; fail-open). The log is hint-only today, so a future writer must add
    the invocation signal for this to ever suppress a block.
    """
    try:
        if not os.path.exists(USAGE_FILE):
            return False
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("skill") != skill:
                    continue
                invoked = rec.get("event") == "invoked" or bool(rec.get("invoked"))
                if not invoked:
                    continue
                # If session scoping is available, require a match; otherwise
                # any invocation record counts.
                rec_session = rec.get("session_id")
                if session_id and rec_session and rec_session != session_id:
                    continue
                return True
        return False
    except Exception:
        # Fail-open: never let a read error cause a spurious block.
        return True


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = data.get("prompt", "")

    # Early-exit: short prompts are confirmations/follow-ups, never need routing
    if not prompt or len(prompt) < 30:
        sys.exit(0)

    rules, skip_re = _load_rules()
    if not rules:
        sys.exit(0)

    if skip_re and skip_re.search(prompt):
        sys.exit(0)

    PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    PRIORITY_LABELS = {
        "critical": "REQUIRED",
        "high": "RECOMMENDED",
        "medium": "SUGGESTED",
        "low": "OPTIONAL",
    }
    matches = []
    for rule in rules:
        match = rule["compiled"].search(prompt)
        if match:
            matches.append((rule, match))

    if matches:
        matches.sort(
            key=lambda x: (PRIORITY_ORDER.get(x[0]["priority"], 2), x[1].start())
        )
        best_rule, best_match = matches[0]

        parts = []
        if best_rule["skill"]:
            skill_hint = f"Skill: /{best_rule['skill']} ({best_rule['desc']})"
            # Liveness check: if the skill references missing script files,
            # warn so the user doesn't invoke a broken skill. See PR #636
            # (sync-repo) — routing kept suggesting it for 6 days while the
            # underlying hooks/sync-repo.py had been deleted.
            missing_refs = _check_skill_liveness(best_rule["skill"])
            if missing_refs:
                preview = ", ".join(missing_refs[:3])
                if len(missing_refs) > 3:
                    preview += f" (+{len(missing_refs) - 3} more)"
                skill_hint += (
                    f" [LIVENESS WARNING: skill references missing files: "
                    f"{preview}]"
                )
            # Enrich with manifest metadata
            manifest = _get_manifest(best_rule["skill"])
            if manifest:
                from manifest_metrics import log_manifest_query
                auth = manifest.get("auth_constraint", "any")
                ctx = manifest.get("execution_context", "main_thread")
                has_enrichment = auth == "main_thread_only" or ctx != "main_thread"
                log_manifest_query(
                    "skill-routing-hint", "auth_enrichment",
                    f"skill={best_rule['skill']} auth={auth} ctx={ctx} enriched={has_enrichment}",
                )
                extras = []
                if auth == "main_thread_only":
                    providers = manifest.get("requires_auth", [])
                    provider_names = [p["provider"] if isinstance(p, dict) else p for p in providers]
                    extras.append(f"auth: main_thread_only ({', '.join(provider_names)})")
                if ctx != "main_thread":
                    extras.append(f"execution: {ctx}")
                if extras:
                    skill_hint += f" [{'; '.join(extras)}]"
            parts.append(skill_hint)
        if best_rule["agent"]:
            parts.append(f"Agent: {best_rule['agent']}")

        priority = best_rule["priority"]
        label = PRIORITY_LABELS.get(priority, "SUGGESTED")
        hint = f"Routing hint [{label}]: " + " -> ".join(parts)
        hint += f" [matched: '{best_match.group()}']"

        log_usage(best_rule["skill"], best_rule["agent"], best_match.group())

        # OPTIONAL enforce path — OFF by default. Only active when
        # SKILL_ACTIVATION_ENFORCE is set AND the matched rule is must_activate
        # AND (best-effort) the skill has not yet fired this session. Any error
        # here falls through to the default hint-only behavior (fail-open).
        try:
            if (
                os.environ.get("SKILL_ACTIVATION_ENFORCE") == "1"
                and best_rule.get("must_activate")
                and best_rule.get("skill")
            ):
                session_id = data.get("session_id") or data.get("sessionId")
                if not _skill_invoked_this_session(best_rule["skill"], session_id):
                    block = (
                        f"This request requires the /{best_rule['skill']} skill "
                        f"({best_rule['desc']}) — it is marked must_activate and "
                        "has not been invoked this session. Invoke it before "
                        f"proceeding. [matched: '{best_match.group()}']"
                    )
                    print(
                        json.dumps(
                            {
                                "decision": "block",
                                "reason": block,
                                "systemMessage": block,
                            }
                        )
                    )
                    sys.exit(0)
        except Exception:
            # Fail-open: fall through to the standard hint below.
            pass

        print(json.dumps({"systemMessage": hint}))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)