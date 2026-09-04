#!/usr/bin/env python3
"""Offline mock runner — exercises the runner harness without API calls.

Generates pseudo-random activation outcomes from a plausible distribution
so the analysis pipeline can be validated end-to-end before paying for
real LLM trials.

Usage:
    python3 mock_runner.py
    python3 mock_runner.py --output results/dry-run.jsonl --seed 42
"""
import argparse
import json
import random
import yaml
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
DESIGN = yaml.safe_load((ROOT / "design.yaml").read_text())


# Plausible activation rates per (style, trigger_type) — extrapolated from
# Seleznov (Sonnet 4.5 baseline) + the 4.7-amplification hypothesis.
# These are the values the live runner should approximately reproduce IF
# the H1/H2/H3 hypotheses hold.
ACTIVATION_RATES = {
    ("passive",          "exact"):     0.85,
    ("passive",          "near"):      0.65,
    ("passive",          "semantic"):  0.40,
    ("passive",          "unrelated"): 0.05,
    ("directive",        "exact"):     0.95,
    ("directive",        "near"):      0.85,
    ("directive",        "semantic"):  0.60,
    ("directive",        "unrelated"): 0.05,
    ("directive_do_not", "exact"):     1.00,
    ("directive_do_not", "near"):      0.95,
    ("directive_do_not", "semantic"):  0.70,
    ("directive_do_not", "unrelated"): 0.03,
}

# Prefix-condition modifiers: how much each prefix shifts the base rate.
# hook_inject converges everything toward 100% on positive triggers.
PREFIX_MODIFIERS = {
    "none":            lambda base, trigger_type: base,
    "use_skills_hint": lambda base, trigger_type: min(1.0, base * 1.05) if trigger_type != "unrelated" else base,
    "hook_inject":     lambda base, trigger_type: 0.97 if trigger_type != "unrelated" else 0.02,
}


def build_cells(design):
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


def mock_trial(cell, trial_idx, rng):
    base_rate = ACTIVATION_RATES[(cell["style"], cell["trigger_type"])]
    final_rate = PREFIX_MODIFIERS[cell["prefix"]](base_rate, cell["trigger_type"])
    activated = rng.random() < final_rate
    return {
        "cell_id": cell["cell_id"],
        "trial_idx": trial_idx,
        "skill": cell["skill"],
        "style": cell["style"],
        "trigger_type": cell["trigger_type"],
        "prefix": cell["prefix"],
        "activated": activated,
        "skill_invocations": 1 if activated else 0,
        "latency_ms": rng.randint(800, 4500),
        "exit_code": 0,
        "input_tokens": rng.randint(200, 600),
        "output_tokens": rng.randint(50, 800),
        "mock": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=f"results/{date.today().isoformat()}-mock-results.jsonl")
    ap.add_argument("--trials-per-cell", type=int, default=DESIGN.get("trials_per_cell", 4))
    ap.add_argument("--seed", type=int, default=20260527)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    cells = build_cells(DESIGN)
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_done = 0
    n_activated = 0
    with open(out_path, "w") as out:
        for cell in cells:
            for trial_idx in range(args.trials_per_cell):
                rec = mock_trial(cell, trial_idx, rng)
                out.write(json.dumps(rec) + "\n")
                n_done += 1
                if rec["activated"]:
                    n_activated += 1

    print(f"Mock run: {n_done} trials, {n_activated} activated ({n_activated/n_done:.1%}).")
    print(f"Results: {out_path}")
    print(f"\nNext: python3 {ROOT.relative_to(Path.cwd())}/analysis.py --input {out_path}")


if __name__ == "__main__":
    main()
