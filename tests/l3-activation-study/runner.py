#!/usr/bin/env python3
"""L3 activation-study live runner.

For each cell in the 3×4×5×3 factorial, runs 4 trials via `claude -p` in a
sandbox dir that exposes only the cell's skill variant. Parses the JSONL
output for skill activation evidence. Writes one record per trial to
results/<date>-results.jsonl.

Usage:
    python3 runner.py --output results/2026-MM-DD-results.jsonl
    python3 runner.py --pilot                 # 18-cell pilot (~$0.40, ~10 min)
    python3 runner.py --parallel 4            # 4-way concurrency
    python3 runner.py --resume results/...    # continue an interrupted run

Requires:
    ANTHROPIC_API_KEY in environment
    `claude` CLI (Claude Code 2.x) on PATH
    tiktoken (optional; for token-cost estimate)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parents[1] / "scripts"))
from qualification_provenance import (  # noqa: E402
    add_qualification_arguments,
    claude_cli_trial_provenance,
    detect_claude_cli_version,
    failed_trial_provenance,
    qualification_metadata,
)

DESIGN = yaml.safe_load((ROOT / "design.yaml").read_text())
GRADER_CONFIG = {
    "grader": "analysis.py",
    "metric": "activation_rate",
    "trials_per_cell": DESIGN.get("trials_per_cell", 4),
    "factors": ["skill", "style", "trigger_type", "prefix"],
}


def build_cells(design):
    """Materialize the full 3×4×5×3 cell matrix."""
    cells = []
    for style in design["description_styles"]:
        for trigger_type in design["trigger_types"]:
            for skill in design["pilot_skills"]:
                for prefix in design["prefix_conditions"]:
                    cells.append({
                        "cell_id": f"{skill['id']}-{style['id']}-{trigger_type['id']}-{prefix['id']}",
                        "skill": skill["id"],
                        "style": style["id"],
                        "trigger_type": trigger_type["id"],
                        "prefix": prefix["id"],
                    })
    return cells


def run_one_trial(cell, trial_idx, model, effort, provider, cli_version):
    """Run a single `claude -p` invocation in a sandbox dir. Returns trial record."""
    variant_skill_dir = ROOT / "skill-variants" / f"{cell['skill']}-{cell['style']}"
    trigger_text = (ROOT / "trigger-prompts" / f"{cell['skill']}-{cell['trigger_type']}.txt").read_text().strip()
    prefix_text = (ROOT / "prefix-conditions" / f"{cell['prefix']}.txt").read_text().strip()

    # Sandbox setup: temp ~/.claude/ with only the variant skill present
    with tempfile.TemporaryDirectory(prefix="l3-sandbox-") as sandbox:
        sandbox_dir = Path(sandbox)
        claude_dir = sandbox_dir / ".claude" / "skills" / cell["skill"]
        claude_dir.mkdir(parents=True)
        shutil.copy(variant_skill_dir / "SKILL.md", claude_dir / "SKILL.md")

        # Build the prompt: prefix (system prompt) + trigger (user prompt)
        env = os.environ.copy()
        env["HOME"] = str(sandbox_dir)  # ~/ inside sandbox
        env["USERPROFILE"] = str(sandbox_dir)  # Windows-compat

        cmd = [
            "claude", "--bare",
            "--model", model,
            "--effort", effort,
            "--output-format", "stream-json",
            "--include-partial-messages",
            "-p", trigger_text,
        ]
        if prefix_text:
            cmd.extend(["--append-system-prompt", prefix_text])

        t0 = time.time()
        try:
            r = subprocess.run(
                cmd, cwd=sandbox_dir, env=env,
                capture_output=True, text=True, timeout=180,
            )
            latency_ms = int((time.time() - t0) * 1000)
            output = r.stdout
            stderr = r.stderr[:500] if r.stderr else ""
            exit_code = r.returncode
        except subprocess.TimeoutExpired:
            response_provenance = failed_trial_provenance(
                requested_model=model, provider=provider,
                grader_config=GRADER_CONFIG, failure="TimeoutExpired")
            return {
                "cell_id": cell["cell_id"], "trial_idx": trial_idx,
                "activated": False, "outcome": "timeout",
                "latency_ms": 180_000, "exit_code": -1,
                "qualification": qualification_metadata(
                    requested_model=model, effort=effort, provider=provider,
                    trial_provenance=[response_provenance], grader_config=GRADER_CONFIG,
                    config_paths=[Path(__file__), ROOT / "design.yaml", ROOT / "analysis.py"],
                    cli_version=cli_version),
            }

        # Parse JSONL for skill activation
        activated = False
        skill_invocations = 0
        input_tokens = 0
        output_tokens = 0
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            # Token-usage event
            if event.get("type") == "result" and "usage" in event:
                usage = event["usage"]
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
            # Tool-use event referencing the Skill tool
            if event.get("type") == "tool_use":
                name = event.get("name", "")
                if name == "Skill" or name == "mcp__skill":
                    tool_input = event.get("input", {})
                    invoked_skill = tool_input.get("skill", "") if isinstance(tool_input, dict) else ""
                    if invoked_skill == cell["skill"] or cell["skill"] in invoked_skill:
                        activated = True
                        skill_invocations += 1

        response_provenance = claude_cli_trial_provenance(
            output=output, requested_model=model, provider=provider,
            grader_config=GRADER_CONFIG)
        return {
            "cell_id": cell["cell_id"],
            "trial_idx": trial_idx,
            "skill": cell["skill"],
            "style": cell["style"],
            "trigger_type": cell["trigger_type"],
            "prefix": cell["prefix"],
            "activated": activated,
            "skill_invocations": skill_invocations,
            "latency_ms": latency_ms,
            "exit_code": exit_code,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "stderr_snippet": stderr if exit_code != 0 else "",
            "qualification": qualification_metadata(
                requested_model=model, effort=effort, provider=provider,
                trial_provenance=[response_provenance], grader_config=GRADER_CONFIG,
                config_paths=[Path(__file__), ROOT / "design.yaml", ROOT / "analysis.py"],
                cli_version=cli_version),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=f"results/{date.today().isoformat()}-results.jsonl")
    add_qualification_arguments(ap, require_model=True)
    ap.set_defaults(provider="claude-cli")
    ap.add_argument("--trials-per-cell", type=int, default=DESIGN.get("trials_per_cell", 4))
    ap.add_argument("--pilot", action="store_true", help="Run an 18-cell subset")
    ap.add_argument("--parallel", type=int, default=1, help="Concurrent trials (≤8 recommended)")
    ap.add_argument("--resume", help="Continue from a partial results file")
    args = ap.parse_args()

    cli_version = detect_claude_cli_version()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Export it or run mock_runner.py instead.", file=sys.stderr)
        sys.exit(2)

    cells = build_cells(DESIGN)

    if args.pilot:
        # 18-cell pilot: 1 skill, 3 styles, 4 triggers, 1 prefix + 2 styles, 3 triggers, 2 prefixes
        cells = [c for c in cells if c["skill"] == "capture" and c["prefix"] == "none"][:12]
        cells += [c for c in cells if c["skill"] == "refine" and c["style"] == "directive_do_not"][:6]
        cells = cells[:18]
        print(f"Pilot mode: {len(cells)} cells × {args.trials_per_cell} trials = {len(cells) * args.trials_per_cell} trials")

    # Resume: skip already-completed cell_id+trial_idx combos
    completed = set()
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.resume:
        with open(args.resume) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    completed.add((rec["cell_id"], rec["trial_idx"]))
                except (json.JSONDecodeError, KeyError):
                    pass
        # Append to the existing file
        output_path = Path(args.resume)
        print(f"Resuming: {len(completed)} trials already complete.")

    tasks = [(c, i) for c in cells for i in range(args.trials_per_cell)
             if (c["cell_id"], i) not in completed]
    print(f"Running {len(tasks)} trials with parallel={args.parallel}, model={args.model}.")

    n_done = 0
    n_activated = 0
    with open(output_path, "a", buffering=1) as out:
        if args.parallel <= 1:
            for cell, trial_idx in tasks:
                rec = run_one_trial(
                    cell, trial_idx, args.model, args.effort, args.provider, cli_version)
                out.write(json.dumps(rec) + "\n")
                n_done += 1
                if rec["activated"]: n_activated += 1
                if n_done % 10 == 0:
                    rate = n_activated / max(n_done, 1)
                    print(f"  {n_done}/{len(tasks)}  activation_rate={rate:.1%}")
        else:
            with ThreadPoolExecutor(max_workers=args.parallel) as pool:
                futures = {
                    pool.submit(
                        run_one_trial, c, i, args.model, args.effort,
                        args.provider, cli_version): (c, i)
                    for c, i in tasks
                }
                for fut in as_completed(futures):
                    rec = fut.result()
                    out.write(json.dumps(rec) + "\n")
                    n_done += 1
                    if rec["activated"]: n_activated += 1
                    if n_done % 10 == 0:
                        rate = n_activated / max(n_done, 1)
                        print(f"  {n_done}/{len(tasks)}  activation_rate={rate:.1%}")

    print(f"\nDone. {n_done} trials, {n_activated} activated ({n_activated/max(n_done,1):.1%}).")
    print(f"Results: {output_path}")
    print(f"\nNext step: python3 tests/l3-activation-study/analysis.py --input {output_path}")


if __name__ == "__main__":
    main()
