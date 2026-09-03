"""LLM-driven sandboxed skill-eval harness (Tier 2 — M2 from the eval roadmap).

For each test YAML containing an `llm_eval:` block, this runner:

1. Spawns a sandboxed Claude Code instance via `claude -p` with controlled
   env (HOME=sandbox, only the target skill present in ~/.claude/skills/).
2. Sends the configured user prompt.
3. Parses the JSONL output stream for:
   - whether the target skill activated (Skill tool use referencing it)
   - whether expected substrings appear in the response
   - whether forbidden substrings appear
   - whether expected file side effects occurred in the sandbox
4. Writes one record per trial to tests/<skill>/<eval>-llm-results.jsonl.

Cost: ~$0.02/trial (per Spence's published Daytona benchmark). Run nightly
not per-PR; use --pilot for cheap subset.

Usage:
    python3 scripts/run-skill-llm-evals.py                     # all skills with llm_eval blocks
    python3 scripts/run-skill-llm-evals.py --skill capture     # one skill
    python3 scripts/run-skill-llm-evals.py --mock              # offline validation, no API
    python3 scripts/run-skill-llm-evals.py --trials 3          # repeat each eval N times for stability
    python3 scripts/run-skill-llm-evals.py --strict            # exit non-zero on any failure

Requires (live mode):
    ANTHROPIC_API_KEY
    `claude` CLI 2.x
"""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_requested_model(cli_model=None, env=None):
    """Resolve an explicit requested model without inventing an effective one."""
    environment = os.environ if env is None else env
    if cli_model:
        return cli_model
    if environment.get("CLAUDE_MODEL"):
        return environment["CLAUDE_MODEL"]
    # settings.json no longer pins a model (the runtime chooses); an eval must
    # name the model it is measuring rather than inherit an implicit one.
    raise ValueError("no model requested: name it with --model or CLAUDE_MODEL")


def claude_code_version():
    result = subprocess.run(
        ["claude", "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return "<unavailable>"
    match = re.match(r"^(\d+\.\d+\.\d+)\b", result.stdout.strip())
    return match.group(1) if match else "<unavailable>"


def runtime_receipt(events, requested_model, version):
    effective_model = "<unavailable>"
    effort = "<unavailable>"
    provider = "<unavailable>"
    context_class = "<unavailable>"
    refusal = False
    for event in events:
        message = event.get("message") if isinstance(event, dict) else None
        message = message if isinstance(message, dict) else {}
        if effective_model == "<unavailable>":
            candidate = message.get("model")
            if not candidate and event.get("type") == "system":
                candidate = event.get("model")
            if isinstance(candidate, str) and candidate:
                effective_model = candidate
        if effort == "<unavailable>":
            candidate = event.get("effort") or message.get("effort")
            if isinstance(candidate, str) and candidate:
                effort = candidate
        if provider == "<unavailable>":
            candidate = event.get("provider") or event.get("api_provider")
            if isinstance(candidate, str) and candidate:
                provider = candidate
        if context_class == "<unavailable>":
            candidate = event.get("context_class") or event.get("context_window")
            if isinstance(candidate, (str, int)) and candidate:
                context_class = str(candidate)
        if (
            event.get("stop_reason") == "refusal"
            or message.get("stop_reason") == "refusal"
        ):
            refusal = True
    fallback = (
        effective_model != requested_model
        if effective_model != "<unavailable>"
        else "<unavailable>"
    )
    return {
        "requested_model": requested_model,
        "effective_model": effective_model,
        "provider": provider,
        "effort": effort,
        "context_class": context_class,
        "claude_code_version": version,
        "fallback": fallback,
        "switch_reason": "<unavailable>",
        "refusal": refusal,
    }


def qualification_failures(exit_code, receipt):
    """Return typed runtime outcomes that cannot qualify a trial as successful."""
    failures = []
    if exit_code != 0:
        failures.append(f"claude CLI exited with code {exit_code}")
    if receipt.get("refusal") is True:
        failures.append("provider refusal")
    if receipt.get("fallback") is True:
        failures.append("effective model differed from requested model")
    return failures


def parse_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None, text
    try:
        return yaml.safe_load(m.group(1)), text[m.end() :]
    except yaml.YAMLError:
        return None, text


def discover_llm_evals(skill_filter=None):
    """Returns list of (eval_file, llm_eval_dict) tuples."""
    discovered = []
    for yaml_file in sorted((REPO_ROOT / "tests").rglob("*.yaml")):
        if "l3-activation-study" in str(yaml_file):
            continue  # L3 is a separate harness
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        if "llm_eval" not in data:
            continue
        skill = data.get("skill") or yaml_file.parent.name
        if skill_filter and skill != skill_filter:
            continue
        discovered.append((yaml_file, data))
    return discovered


def setup_sandbox(skill_name):
    """Create a tempdir layout that mimics ~/.claude/skills/<skill>/."""
    sandbox = tempfile.mkdtemp(prefix=f"llm-eval-{skill_name}-")
    src_dir = REPO_ROOT / "skills" / skill_name
    dst_dir = Path(sandbox) / ".claude" / "skills" / skill_name
    dst_dir.parent.mkdir(parents=True)
    shutil.copytree(src_dir, dst_dir)
    return Path(sandbox)


def run_live_trial(eval_data, llm_eval, trial_idx, model, version):
    """Live `claude -p` invocation. Returns trial record."""
    skill = eval_data.get("skill")
    inv = llm_eval.get("invocation", {})
    user_prompt = inv.get("prompt", "")
    system_prompt = inv.get("system_prompt", "")
    timeout_s = inv.get("timeout_s", 120)
    explicit_model = inv.get("model", model)

    sandbox = setup_sandbox(skill)
    env = os.environ.copy()
    env["HOME"] = str(sandbox)
    env["USERPROFILE"] = str(sandbox)

    cmd = [
        "claude",
        "--bare",
        "--model",
        explicit_model,
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "-p",
        user_prompt,
    ]
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])

    t0 = time.time()
    try:
        r = subprocess.run(
            cmd,
            cwd=sandbox,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        latency_ms = int((time.time() - t0) * 1000)
        output = r.stdout
        exit_code = r.returncode
    except subprocess.TimeoutExpired:
        shutil.rmtree(sandbox, ignore_errors=True)
        return {
            "trial_idx": trial_idx,
            "outcome": "timeout",
            "latency_ms": timeout_s * 1000,
            "activated": False,
            "passed": False,
            "failures": ["timeout"],
            "runtime_receipt": runtime_receipt([], explicit_model, version),
        }

    # Parse JSONL
    activated = False
    response_text = []
    events = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        events.append(event)
        if event.get("type") == "tool_use":
            tool_name = event.get("name", "")
            if tool_name in ("Skill", "mcp__skill"):
                tool_input = event.get("input", {})
                target = (
                    tool_input.get("skill", "") if isinstance(tool_input, dict) else ""
                )
                if target == skill or skill in target:
                    activated = True
        if event.get("type") == "assistant_message" and "text" in event:
            response_text.append(event["text"])
    response = "\n".join(response_text)

    # Run assertions
    failures = []
    expected_to_fire = inv.get("expected_skill_fires", True)
    if expected_to_fire and not activated:
        failures.append("skill did not fire when expected")
    if not expected_to_fire and activated:
        failures.append("skill fired when not expected")

    for substr in llm_eval.get("expected_output_contains", []):
        if substr.lower() not in response.lower():
            failures.append(f"missing expected substring: {substr!r}")
    for substr in llm_eval.get("forbidden_output", []):
        if substr.lower() in response.lower():
            failures.append(f"contains forbidden substring: {substr!r}")

    # Side-effect assertions
    for assertion in llm_eval.get("side_effect_assertions", []):
        for atype, aval in (
            assertion.items() if isinstance(assertion, dict) else [(None, None)]
        ):
            if atype == "file_exists":
                path = Path(str(aval).replace("~", str(sandbox)))
                if not path.exists():
                    failures.append(f"file_exists: {aval} not created")

    receipt = runtime_receipt(events, explicit_model, version)
    failures.extend(qualification_failures(exit_code, receipt))

    shutil.rmtree(sandbox, ignore_errors=True)
    return {
        "trial_idx": trial_idx,
        "activated": activated,
        "passed": len(failures) == 0,
        "failures": failures,
        "latency_ms": latency_ms,
        "exit_code": exit_code,
        "response_snippet": response[:300],
        "runtime_receipt": receipt,
    }


def run_mock_trial(eval_data, llm_eval, trial_idx, rng, model):
    """Offline mock — pretend the skill fired ~85% of the time on positive cases."""
    inv = llm_eval.get("invocation", {})
    expected = inv.get("expected_skill_fires", True)
    base_rate = 0.85 if expected else 0.05
    activated = rng.random() < base_rate
    failures = []
    if expected and not activated:
        failures.append("[mock] skill did not fire when expected")
    if not expected and activated:
        failures.append("[mock] skill fired when not expected")
    return {
        "trial_idx": trial_idx,
        "activated": activated,
        "passed": len(failures) == 0,
        "failures": failures,
        "latency_ms": rng.randint(500, 3000),
        "exit_code": 0,
        "mock": True,
        "runtime_receipt": {
            "requested_model": llm_eval.get("invocation", {}).get("model", model),
            "effective_model": "<synthetic>",
            "provider": "offline_mock",
            "effort": "<unavailable>",
            "context_class": "<unavailable>",
            "claude_code_version": "<unavailable>",
            "fallback": "<unavailable>",
            "switch_reason": "<unavailable>",
            "refusal": False,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", help="One skill only")
    ap.add_argument("--mock", action="store_true", help="Offline mock; no API calls")
    ap.add_argument("--trials", type=int, default=3, help="Repeat each eval N times")
    ap.add_argument(
        "--strict", action="store_true", help="Exit non-zero on any failure"
    )
    ap.add_argument(
        "--model",
        help="requested model; defaults to CLAUDE_MODEL, then settings.json",
    )
    ap.add_argument(
        "--pilot", action="store_true", help="3 skills only (capture/recall/refine)"
    )
    ap.add_argument("--seed", type=int, default=20260527)
    args = ap.parse_args()
    args.model = resolve_requested_model(args.model)

    if not args.mock and not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY not set. Use --mock for offline validation.",
            file=sys.stderr,
        )
        sys.exit(2)

    evals = discover_llm_evals(args.skill)
    if args.pilot:
        evals = [
            (p, d)
            for p, d in evals
            if d.get("skill") in ("capture", "recall", "refine")
        ]

    if not evals:
        print("No llm_eval blocks found.")
        sys.exit(0)

    print(
        f"Discovered {len(evals)} llm_eval blocks. Mode: {'MOCK' if args.mock else 'LIVE'}."
    )
    print(f"Trials per eval: {args.trials}. Model: {args.model}.")
    print()

    rng = random.Random(args.seed)
    version = "<unavailable>" if args.mock else claude_code_version()
    all_results = []
    for eval_file, eval_data in evals:
        skill = eval_data.get("skill", eval_file.parent.name)
        llm_eval = eval_data["llm_eval"]
        eval_name = eval_data.get("name", eval_file.stem)
        print(f"  [{skill:<30}] {eval_name}")
        trials = []
        for i in range(args.trials):
            if args.mock:
                rec = run_mock_trial(eval_data, llm_eval, i, rng, args.model)
            else:
                rec = run_live_trial(eval_data, llm_eval, i, args.model, version)
            trials.append(rec)
        # Aggregate: pass if ≥80% of trials passed (non-determinism tolerance)
        pass_rate = sum(1 for t in trials if t["passed"]) / len(trials)
        agg_passed = pass_rate >= 0.80
        mark = "✓" if agg_passed else "✗"
        print(
            f"    {mark} pass_rate={pass_rate:.0%}  ({sum(1 for t in trials if t['passed'])}/{len(trials)})"
        )
        if not agg_passed:
            for t in trials:
                if t["failures"]:
                    print(f"      trial {t['trial_idx']}: {t['failures'][:2]}")
        all_results.append(
            {
                "skill": skill,
                "eval": eval_name,
                "file": str(eval_file.relative_to(REPO_ROOT)),
                "trials": trials,
                "pass_rate": pass_rate,
                "passed": agg_passed,
            }
        )

    n_passed = sum(1 for r in all_results if r["passed"])
    print()
    print("=== LLM-eval summary ===")
    print(f"  Evals run: {len(all_results)}")
    print(f"  Passing (≥80% trial pass rate): {n_passed}")
    print(f"  Failing: {len(all_results) - n_passed}")

    # Write results
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    out_path = REPO_ROOT / "tests" / "llm-eval-results" / f"{timestamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(result) + "\n" for result in all_results)
    print(f"  Results: {out_path}")

    if args.strict and n_passed < len(all_results):
        sys.exit(1)


if __name__ == "__main__":
    main()
