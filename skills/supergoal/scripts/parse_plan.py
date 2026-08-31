#!/usr/bin/env python3
"""Parse a superplan-produced plan markdown into a state.json + events.jsonl
that the type:agent Stop hook reads each turn.

Usage:
    parse_plan.py <plan-path> [--state-dir ~/.claude/supergoal/]
                  [--force-rerun] [--headless] [--per-turn-commit]
                  [--budget-turns=N] [--budget-wallclock=Ss] [--budget-tokens=M]

State file lives at <state-dir>/<plan-slug>/state.json (NOT /tmp — claude-code#28923
documents single-file state-corruption from concurrent writes; per-plan
directory + atomic+locked writes prevent cascade).

Required plan fields (errors loudly if missing):
    - Demo: <one-line success criterion>
    - ## Falsifiers section with list items
    - At least one ### Metric Commands code block (or legacy `Verification:` block)

Recommended plan fields (warns if missing):
    - ### Guard Commands — separate from falsifiers, must keep passing
    - ### Artifact Probe — observes the artifact, not the metric (Goodhart probe)
    - ### Forbidden Actions — tool-call patterns agent must not take (Devin convention)

Parsed if present (no warning if absent):
    - ### Phase 3.5 Baseline (currently <N>, expected <M>)
    - Effort: XS|S|M|L|XL

Setup-time exit codes (matched against references/headless.md table):
    20 = parse-failed       (plan missing required fields, plan-not-found, bad args)
    22 = attestation-failed (couldn't write SHA-256 attestation file)
     1 = other / unexpected error (active-state conflict, etc.)

--headless is auto-set when stdin is not a TTY (detected via os.isatty) so
`claude -p` invocations behave correctly without the caller specifying it.
The explicit flag still wins over auto-detection.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BUDGET_DEFAULTS = {
    "XS": {"turns": 5, "wallclock_seconds": 300, "tokens_advisory": 50_000},
    "S":  {"turns": 15, "wallclock_seconds": 1800, "tokens_advisory": 200_000},
    "M":  {"turns": 20, "wallclock_seconds": 3600, "tokens_advisory": 400_000},
    "L":  {"turns": 40, "wallclock_seconds": 7200, "tokens_advisory": 800_000},
    "XL": {"turns": 80, "wallclock_seconds": 14400, "tokens_advisory": 2_000_000},
}

# Setup-time exit codes — must match references/headless.md "Exit codes" table.
# Runtime exits (0/10/11/12/13/14) are owned by write_terminal.py.
EXIT_PARSE_FAILED = 20
EXIT_ATTESTATION_FAILED = 22


def _auto_headless():
    """True if stdin is not a TTY — `claude -p` invocations land here.
    The explicit `--headless` flag still wins; this just sets the default."""
    try:
        return not sys.stdin.isatty()
    except (AttributeError, OSError, ValueError):
        # No stdin attached (subprocess capture, daemonized) — treat as headless.
        return True


USAGE = (
    "usage: parse_plan.py <plan-path> [--state-dir DIR] [flags]\n"
    "\n"
    "Parses a supergoal plan file and bootstraps the state directory.\n"
    "\n"
    "Positional:\n"
    "  <plan-path>            path to the plan markdown file\n"
    "\n"
    "Flags:\n"
    "  --state-dir DIR        state directory (default ~/.claude/supergoal)\n"
    "  --force-rerun          ignore existing state; start a new arc\n"
    "  --headless             force headless mode (default: auto-detect via TTY)\n"
    "  --per-turn-commit      commit after every loop turn\n"
    "  --reset                clear state before bootstrapping\n"
    "  --budget-turns N       per-arc turn budget\n"
    "  --budget-wallclock S   per-arc wallclock budget (seconds or 1h/30m)\n"
    "  --budget-tokens N      per-arc token budget (advisory)\n"
    "  -h, --help             show this help message and exit\n"
)


def _next_value(argv, i):
    """Value token for a space-separated flag; clean usage error (exit 20)
    instead of an IndexError traceback when the flag is the last token."""
    if i + 1 >= len(argv):
        print(f"error: {argv[i]} requires a value", file=sys.stderr)
        print("hint: run with --help for flag usage", file=sys.stderr)
        sys.exit(EXIT_PARSE_FAILED)
    return argv[i + 1]


def _parse_flag_value(flag, raw, parser):
    """Apply a flag's value parser; bad values exit 20 with a clean usage
    error (documented bad-args code) instead of a ValueError traceback.
    Space and `=` forms route through the same parser per flag."""
    try:
        return parser(raw)
    except ValueError:
        print(f"error: invalid value for {flag}: {raw!r}", file=sys.stderr)
        print("hint: run with --help for flag usage (e.g. --budget-wallclock 30m, --budget-tokens 2M)",
              file=sys.stderr)
        sys.exit(EXIT_PARSE_FAILED)


def parse_args(argv):
    # Short-circuit --help/-h before any positional resolution; otherwise
    # "--help" gets treated as a plan-path and resolves under cwd.
    if any(a in ("-h", "--help") for a in argv[1:]):
        print(USAGE)
        sys.exit(0)
    if len(argv) < 2:
        # Argument parse errors are a setup-time failure, not a runtime failure.
        print(USAGE, file=sys.stderr)
        sys.exit(EXIT_PARSE_FAILED)
    plan_path = Path(argv[1]).expanduser().resolve()
    # Headless defaults to auto-detection (no TTY → headless). Explicit --headless
    # still wins; the auto flag just removes the need to thread --headless through
    # `claude -p` invocations.
    flags = {
        "state_dir": Path.home() / ".claude" / "supergoal",
        "force_rerun": False,
        "headless": _auto_headless(),
        "headless_auto_detected": True,
        "per_turn_commit": False,
        "reset": False,
        "budget_turns": None,
        "budget_wallclock_seconds": None,
        "budget_tokens": None,
    }
    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg == "--state-dir":
            flags["state_dir"] = Path(_next_value(argv, i)).expanduser().resolve()
            i += 2
        elif arg == "--force-rerun":
            flags["force_rerun"] = True
            i += 1
        elif arg == "--headless":
            flags["headless"] = True
            flags["headless_auto_detected"] = False
            i += 1
        elif arg == "--per-turn-commit":
            flags["per_turn_commit"] = True
            i += 1
        elif arg == "--reset":
            flags["reset"] = True
            i += 1
        elif arg == "--budget-turns":
            flags["budget_turns"] = _parse_flag_value(arg, _next_value(argv, i), int)
            i += 2
        elif arg == "--budget-wallclock":
            flags["budget_wallclock_seconds"] = _parse_flag_value(arg, _next_value(argv, i), _parse_duration)
            i += 2
        elif arg == "--budget-tokens":
            flags["budget_tokens"] = _parse_flag_value(arg, _next_value(argv, i), _parse_token_count)
            i += 2
        elif arg.startswith("--budget-turns="):
            flags["budget_turns"] = _parse_flag_value("--budget-turns", arg.split("=", 1)[1], int)
            i += 1
        elif arg.startswith("--budget-wallclock="):
            flags["budget_wallclock_seconds"] = _parse_flag_value("--budget-wallclock", arg.split("=", 1)[1], _parse_duration)
            i += 1
        elif arg.startswith("--budget-tokens="):
            flags["budget_tokens"] = _parse_flag_value("--budget-tokens", arg.split("=", 1)[1], _parse_token_count)
            i += 1
        else:
            print(f"unknown arg: {arg}", file=sys.stderr)
            sys.exit(EXIT_PARSE_FAILED)
    return plan_path, flags


def _parse_token_count(s):
    s = s.strip().upper()
    mult = 1
    if s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    return int(float(s) * mult)


def _parse_duration(s):
    s = s.strip().lower()
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    return int(s)


def extract_demo(text):
    # Tolerate a leading markdown bold/italic marker on the label — `**Demo:**`,
    # `*Demo:*`, `__Demo:__` — and an optional bold-close after the colon. Plans
    # written for human readability bold the label; a bare `^\s*Demo:` anchor
    # silently failed on `**Demo:**` and reported the plan not-supergoal-ready.
    # (2026-06-21: mega-capture plan's bolded Demo line was invisible to the parser.)
    m = re.findall(r"(?m)^\s*[*_]{0,2}Demo:[*_]{0,2}\s*(.+)$", text)
    if not m:
        return None
    # Strip a trailing bold/italic close that the greedy `.+` may have captured.
    return m[0].strip().rstrip("*_ ").strip() or None


def extract_section_items(text, pattern):
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    section = m.group(1) if m.lastindex else m.group(0)
    items = []
    for line in section.splitlines():
        line = line.strip()
        if line.startswith(("-", "*")):
            items.append(line.lstrip("-* ").strip())
    return items


def extract_falsifiers(text):
    return extract_section_items(text, r"(?ms)^##+\s*Falsifiers\s*\n(.+?)(?=^#{2,}\s|\Z)")


def extract_forbidden_actions(text):
    return extract_section_items(text, r"(?ms)^###?\s*Forbidden Actions\s*\n(.+?)(?=^###?\s|\Z)")


def extract_code_block_lines(text, section_pattern):
    m = re.search(section_pattern, text, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    section = m.group(1) if m.lastindex else m.group(0)
    blocks = re.findall(r"```(?:bash|sh)?\n(.*?)\n```", section, re.DOTALL)
    out = []
    for b in blocks:
        for line in b.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def extract_metric_commands(text):
    new_form = extract_code_block_lines(text, r"###+\s*Metric Commands\s*\n(.+?)(?=^###?\s|\Z)")
    if new_form:
        return new_form
    # Legacy fallback: accept both `Verification:` label-form AND `## Verification` H2-heading
    # form. superplan's documented Plan Structure Template uses the H2-heading form, so
    # plans following the template literally must parse without ceremony.
    label_form = extract_code_block_lines(text, r"(?:^|\n)Verification:\s*\n(.+?)(?=^#{2,}\s|\Z)")
    if label_form:
        return label_form
    return extract_code_block_lines(text, r"(?m)^##+\s*Verification\s*\n(.+?)(?=^#{2,}\s|\Z)")


def extract_guard_commands(text):
    return extract_code_block_lines(text, r"###+\s*Guard Commands\s*\n(.+?)(?=^###?\s|\Z)")


def extract_artifact_probe(text):
    return extract_code_block_lines(text, r"###+\s*Artifact Probe\s*\n(.+?)(?=^###?\s|\Z)")


def extract_baseline(text):
    # Anchor the number so a trailing sentence period isn't captured: a bare
    # `[0-9.]+` greedily eats the `.` in "expected 1.0." → float("1.0.") raises
    # ValueError and crashes the whole parse. `[0-9]+(?:\.[0-9]+)?` matches an
    # int or a proper decimal and stops before punctuation.
    # (2026-06-21: "expected 1.0." sentence-final period crashed mega-capture parse.)
    num = r"([0-9]+(?:\.[0-9]+)?)"
    m_curr = re.search(rf"currently[:\s]+{num}", text, re.IGNORECASE)
    m_exp = re.search(rf"expected[:\s]+{num}", text, re.IGNORECASE)
    if not (m_curr and m_exp):
        return None
    return {"currently_N": float(m_curr.group(1)), "expected_M": float(m_exp.group(1))}


def extract_effort(text):
    m = re.search(r"(?im)^\s*Effort:\s*(XS|S|M|L|XL)\b", text)
    return m.group(1).upper() if m else "M"


def extract_metric_names(text):
    # PREFER explicit `METRIC <name>=...` declarations (any case). When a plan
    # declares its metrics this way — the documented contract form — they are
    # the ONLY real metric names, and the greedy ALLCAPS scan below is pure
    # noise: it grabs prose words ("NOT", "ALL", "EVERY", "THEN") that collide
    # with unrelated terminal docs and produce a spurious prior-arc REFUSE.
    # (2026-06-21: mega-capture, a brand-NEW skill with zero real prior arcs,
    # was REFUSED with "27 prior arcs" because ALLCAPS prose tokens matched
    # NOT/F1/ALL in 27 unrelated terminal docs. Declared metric `megacapture_ready`
    # matched zero — the correct answer.)
    # Match METRIC at a line-start OR after a quote/paren/whitespace — the
    # canonical emission form is `print("METRIC name=value")` / `echo 'METRIC
    # name=...'`, where METRIC is mid-line inside a string, so a strict
    # `^\s*METRIC` anchor (the original) never matched the real form and the
    # noisy ALLCAPS fallback always ran. (2026-06-21.)
    declared = re.findall(r"""(?im)(?:^|[\s'"(])METRIC\s+([A-Za-z_][A-Za-z0-9_]*)\s*=""", text)
    if declared:
        return sorted(set(declared))

    # Fallback ONLY when no METRIC declarations exist: the legacy ALLCAPS +
    # known-acronym scan, with an expanded blacklist of common English ALLCAPS
    # words that are never metric names. This path is inherently noisy; the
    # METRIC-declaration form above is the reliable one and plans should use it.
    names = set(re.findall(r"\b[A-Z][A-Z_0-9]{2,}\b", text))
    names.update(re.findall(r"\b(Acc@\d+|MRR|F1|precision|recall)\b", text))
    blacklist = {
        "METRIC", "TODO", "FIXME", "XXX", "HACK", "NOTE", "WARN", "ERROR", "DEBUG", "INFO",
        # Common ALLCAPS English / markdown-emphasis words that are NOT metrics
        # (the prose-collision set that caused the 2026-06-21 false REFUSE).
        "NOT", "ALL", "ANY", "AND", "THE", "FOR", "WITH", "WITHIN", "ACROSS", "EVERY",
        "SOME", "NONE", "THEN", "WHAT", "WHEN", "HOW", "WHY", "WHO", "OUT", "END", "OTHER",
        "DIFFERENT", "COMPLETE", "MISSING", "MERGED", "NEVER", "ONLY", "EACH", "PER",
        "SKILL", "README", "ARCHITECTURE", "GUARD", "ARTIFACT", "FORBIDDEN", "DEMO",
        "FAIL", "PASS", "PASSES", "OK", "DONE", "STOP", "HOME", "CLAUDE", "GPT", "SPLIT",
        "FRONT", "LOSSY", "UNION", "THEME", "AGNOSTIC", "DON", "OUT", "OFF", "NEW",
    }
    return sorted(n for n in names if n not in blacklist)


def _slug(plan_path):
    raw = plan_path.stem
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-.")
    return sanitized or "plan"


def main():
    plan_path, flags = parse_args(sys.argv)
    if not plan_path.exists():
        print(f"plan file not found: {plan_path}", file=sys.stderr)
        sys.exit(EXIT_PARSE_FAILED)
    text = plan_path.read_text(encoding="utf-8")

    demo = extract_demo(text)
    falsifiers = extract_falsifiers(text)
    metric_commands = extract_metric_commands(text)
    guard_commands = extract_guard_commands(text)
    artifact_probe = extract_artifact_probe(text)
    forbidden_actions = extract_forbidden_actions(text)
    baseline = extract_baseline(text)
    effort = extract_effort(text)
    metric_names = extract_metric_names(text)

    missing = []
    if not demo: missing.append("Demo: line")
    if not falsifiers: missing.append("## Falsifiers section with list items")
    if not metric_commands: missing.append("### Metric Commands or Verification: code block")
    if missing:
        print(
            "plan is not supergoal-ready. Missing:\n  - "
            + "\n  - ".join(missing)
            + "\n\nRe-run superplan with these sections added, then retry.",
            file=sys.stderr,
        )
        sys.exit(EXIT_PARSE_FAILED)

    warns = []
    if not guard_commands:
        warns.append("no ### Guard Commands block — only metric_commands will be enforced")
    if not artifact_probe:
        warns.append("no ### Artifact Probe block — Goodhart probe disabled; metric-gaming undetectable")
    if not forbidden_actions:
        warns.append("no ### Forbidden Actions block — policy axis disabled (no forbidden-tool-call check)")
    for w in warns:
        print(f"WARN: {w}", file=sys.stderr)

    if effort == "XL" and (
        flags["budget_turns"] is None
        or flags["budget_wallclock_seconds"] is None
    ):
        print(
            "XL requires explicit user opt-in: pass both --budget-turns and "
            "--budget-wallclock",
            file=sys.stderr,
        )
        sys.exit(EXIT_PARSE_FAILED)

    budgets = BUDGET_DEFAULTS[effort]
    turn_budget = flags["budget_turns"] or budgets["turns"]
    wallclock_budget = flags["budget_wallclock_seconds"] or budgets["wallclock_seconds"]
    token_budget = flags["budget_tokens"] or budgets["tokens_advisory"]

    state_dir = flags["state_dir"] / _slug(plan_path)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "state.json"
    events_path = state_dir / "events.jsonl"
    sha_path = state_dir / "plan.sha256"

    if state_path.exists() and not flags["reset"]:
        try:
            existing = json.loads(state_path.read_text(encoding="utf-8"))
            turns_used = existing.get("turn_budget_total", 0) - existing.get("turn_budget_remaining", 0)
            exit_reason = existing.get("exit_reason")
            paused = existing.get("paused_at")
        except Exception:
            existing = None
            turns_used = 0
            exit_reason = None
            paused = None
        if existing and not exit_reason:
            sys.exit(
                f"ERROR: active supergoal state exists at {state_path} "
                f"(turns_used={turns_used}, paused={bool(paused)}).\n"
                f"  - To resume the existing loop: /supergoal-resume\n"
                f"  - To inspect: /superplan-status {_slug(plan_path)}\n"
                f"  - To wipe and start over: re-run with --reset (loses prior-arc lineage state)"
            )

    sha = hashlib.sha256(text.encode()).hexdigest()
    mtime = plan_path.stat().st_mtime
    sibling_attest = plan_path.with_suffix(plan_path.suffix + ".attestation")
    try:
        sha_path.write_text(f"{sha}  {plan_path.name}\n", encoding="utf-8")
        sibling_attest.write_text(f"{sha}  {plan_path.name}\n", encoding="utf-8")
    except OSError as e:
        # headless.md exit code 22 — attestation file unwritable (read-only FS,
        # permissions, no space). Surface separately from generic parse failure
        # so CI can distinguish "plan bad" from "filesystem bad".
        print(
            f"ERROR: could not write SHA-256 attestation: {e}\n"
            f"  sha_path: {sha_path}\n"
            f"  sibling_attest: {sibling_attest}",
            file=sys.stderr,
        )
        sys.exit(EXIT_ATTESTATION_FAILED)

    state = {
        "plan_path": str(plan_path),
        "plan_slug": _slug(plan_path),
        "plan_sha256": sha,
        "plan_mtime": mtime,
        "sha_path": str(sha_path),
        "events_path": str(events_path),
        "demo": demo,
        "falsifiers": falsifiers,
        "metric_commands": metric_commands,
        "guard_commands": guard_commands,
        "artifact_probe": artifact_probe,
        "forbidden_actions": forbidden_actions,
        "baseline": baseline,
        "effort": effort,
        "metric_names": metric_names,
        "consecutive_blocks": 0,
        "consecutive_no_progress": 0,
        "max_stuck": 3,
        "scorer_broken_codes": [2, 126, 127, 137],
        "turn_budget_remaining": turn_budget,
        "turn_budget_total": turn_budget,
        "wallclock_used_seconds": 0,
        "time_budget_seconds": wallclock_budget,
        "tokens_used_advisory": 0,
        "token_budget_advisory": token_budget,
        "last_verified_at": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "force_rerun": flags["force_rerun"],
        "headless": flags["headless"],
        "git_commits_enabled": flags["per_turn_commit"],
        "active_started_at": datetime.now(timezone.utc).isoformat(),
        "paused_at": None,
        "lineage": [],
        "prior_arc_ledger": "",
        "prior_arc_count": 0,
    }

    _atomic_write_json(state_path, state)
    sibling_status = plan_path.with_suffix(".status.json")
    _atomic_write_json(sibling_status, state)

    active_ptr = flags["state_dir"] / ".active"
    tmp_ptr = active_ptr.with_suffix(".tmp")
    tmp_ptr.write_text(str(state_path) + "\n", encoding="utf-8")
    os.rename(tmp_ptr, active_ptr)

    _append_event(events_path, {
        "turn": 0,
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "started",
        "plan_sha256": sha,
        "baseline": baseline,
        "budgets": {"turns": turn_budget, "wallclock_seconds": wallclock_budget, "tokens_advisory": token_budget},
    })

    print(f"parsed: {plan_path}")
    print(f"  demo: {demo}")
    print(f"  falsifiers: {len(falsifiers)}")
    print(f"  metric_commands: {len(metric_commands)}")
    print(f"  guard_commands: {len(guard_commands)}")
    print(f"  artifact_probe: {len(artifact_probe)}")
    print(f"  forbidden_actions: {len(forbidden_actions)}")
    print(f"  baseline: {baseline}")
    print(f"  effort: {effort}")
    print(f"  budget: {turn_budget} turns / {wallclock_budget}s wallclock / {token_budget} tokens (advisory)")
    print(f"  metric_names: {metric_names}")
    print(f"  per_turn_commit: {flags['per_turn_commit']}")
    print(f"state dir: {state_dir}")
    print(f"events log: {events_path}")


def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.rename(tmp, path)


def _append_event(path, ev):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev) + "\n")


if __name__ == "__main__":
    main()
