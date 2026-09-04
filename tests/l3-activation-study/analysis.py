#!/usr/bin/env python3
"""L3 activation-study analysis.

Reads a results.jsonl from runner.py or mock_runner.py and produces:
  - Per-cell activation rates with 95% Wilson-score CIs
  - Cochran-Mantel-Haenszel odds ratios stratified by skill + prefix
    (replicating Seleznov's analysis methodology)
  - Effect-size comparison against Seleznov's 20.6× baseline (1-tailed)
  - Hook-condition convergence test (H3)
  - Markdown report with all three pre-registered hypotheses evaluated

Usage:
    python3 analysis.py --input results/2026-MM-DD-results.jsonl
    python3 analysis.py --input results/dry-run.jsonl --output analysis/dry-run.md

The script uses only stdlib + math.log for CIs and CMH math — no scipy
dependency. Trades off some statistical convenience for portability.
"""
import argparse
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent

SELEZNOV_SONNET_45_OR = 20.6  # Sonnet 4.5 baseline OR for directive vs passive (Seleznov 2026)


def wilson_ci(n_success, n_total, z=1.96):
    """Wilson-score 95% confidence interval for a binomial proportion."""
    if n_total == 0:
        return (0.0, 0.0)
    p = n_success / n_total
    denom = 1 + z*z / n_total
    center = (p + z*z / (2*n_total)) / denom
    spread = z * math.sqrt(p * (1 - p) / n_total + z*z / (4*n_total*n_total)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def cmh_odds_ratio(strata):
    """Cochran-Mantel-Haenszel common-odds-ratio across strata.

    Each stratum is a 2x2 table:
        [[a, b],    a = directive activated,  b = directive not
         [c, d]]    c = passive activated,    d = passive not

    Returns (OR_MH, log_OR, var_log_OR) using the standard CMH estimator
    with Mantel-Haenszel weights (no continuity correction by default).
    """
    num = 0.0
    den = 0.0
    for (a, b, c, d) in strata:
        n = a + b + c + d
        if n == 0:
            continue
        num += a * d / n
        den += b * c / n
    if den == 0:
        return (float("inf"), float("inf"), 0.0)
    or_mh = num / den

    # Robins-Breslow-Greenland variance estimator for log(OR_MH)
    # See: Robins, Breslow, Greenland (1986)
    rbg_num = 0.0
    pq_sum = 0.0  # P*R + P*S + Q*R + Q*S terms; built in two halves
    rs_sum = 0.0
    for (a, b, c, d) in strata:
        n = a + b + c + d
        if n == 0:
            continue
        P = (a + d) / n
        Q = (b + c) / n
        R = a * d / n
        S = b * c / n
        rbg_num += P * R
        pq_sum += (P * S + Q * R)
        rs_sum += Q * S
    R_sum = sum(a * d / max(a + b + c + d, 1) for (a, b, c, d) in strata)
    S_sum = sum(b * c / max(a + b + c + d, 1) for (a, b, c, d) in strata)
    if R_sum == 0 or S_sum == 0:
        return (or_mh, math.log(or_mh) if or_mh > 0 else float("-inf"), 0.0)
    var_log = (rbg_num / (2 * R_sum**2)
               + pq_sum / (2 * R_sum * S_sum)
               + rs_sum / (2 * S_sum**2))
    log_or = math.log(or_mh)
    return (or_mh, log_or, var_log)


def load_results(path):
    records = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def summarize(records):
    """Per-cell summary."""
    by_cell = defaultdict(lambda: {"trials": 0, "activated": 0})
    for r in records:
        key = (r["skill"], r["style"], r["trigger_type"], r["prefix"])
        by_cell[key]["trials"] += 1
        if r["activated"]:
            by_cell[key]["activated"] += 1
    return by_cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default=None, help="Markdown report path (default: stdout)")
    args = ap.parse_args()

    records = load_results(args.input)
    by_cell = summarize(records)
    n_trials = len(records)
    n_activated = sum(1 for r in records if r["activated"])
    is_mock = any(r.get("mock") for r in records)

    out = []
    out.append("# L3 activation-study analysis")
    out.append("")
    out.append(f"- **Input**: `{args.input}`")
    out.append(f"- **Mode**: {'MOCK (pseudo-random)' if is_mock else 'LIVE'}")
    out.append(f"- **Date**: {date.today().isoformat()}")
    out.append(f"- **Trials**: {n_trials}")
    out.append(f"- **Activated**: {n_activated} ({n_activated/max(n_trials,1):.1%})")
    out.append("")

    # --- Per-(style, trigger_type) marginal rates ---
    out.append("## Marginal activation rates by (style × trigger_type)")
    out.append("")
    out.append("| Style | Exact | Near | Semantic | Unrelated |")
    out.append("|---|---:|---:|---:|---:|")
    for style in ["passive", "directive", "directive_do_not"]:
        row = [style]
        for tt in ["exact", "near", "semantic", "unrelated"]:
            trials = sum(c["trials"] for k, c in by_cell.items() if k[1] == style and k[2] == tt)
            acts = sum(c["activated"] for k, c in by_cell.items() if k[1] == style and k[2] == tt)
            rate = acts / trials if trials else 0
            lo, hi = wilson_ci(acts, trials)
            row.append(f"{rate:.0%} [{lo:.0%}, {hi:.0%}]")
        out.append("| " + " | ".join(row) + " |")
    out.append("")

    # --- H1: directive_do_not vs passive on positive triggers ---
    # CMH stratified by (skill, prefix), pooling exact + near + semantic triggers
    strata = []
    for skill_id in {k[0] for k in by_cell}:
        for prefix_id in {k[3] for k in by_cell}:
            # directive_do_not row
            a = sum(c["activated"] for k, c in by_cell.items()
                    if k[0] == skill_id and k[1] == "directive_do_not" and k[3] == prefix_id and k[2] != "unrelated")
            b = sum(c["trials"] - c["activated"] for k, c in by_cell.items()
                    if k[0] == skill_id and k[1] == "directive_do_not" and k[3] == prefix_id and k[2] != "unrelated")
            # passive row
            c_ = sum(c["activated"] for k, c in by_cell.items()
                     if k[0] == skill_id and k[1] == "passive" and k[3] == prefix_id and k[2] != "unrelated")
            d = sum(c["trials"] - c["activated"] for k, c in by_cell.items()
                    if k[0] == skill_id and k[1] == "passive" and k[3] == prefix_id and k[2] != "unrelated")
            strata.append((a, b, c_, d))

    or_mh, log_or, var_log = cmh_odds_ratio(strata)
    if var_log > 0:
        ci_lo = math.exp(log_or - 1.96 * math.sqrt(var_log))
        ci_hi = math.exp(log_or + 1.96 * math.sqrt(var_log))
    else:
        ci_lo = ci_hi = or_mh

    out.append("## H1 — directive_do_not vs passive (CMH stratified by skill + prefix)")
    out.append("")
    out.append(f"**Common odds ratio (CMH)**: {or_mh:.2f}")
    out.append(f"**95% CI**: [{ci_lo:.2f}, {ci_hi:.2f}]")
    out.append("")
    if ci_lo > 5.0:
        out.append("✓ **H1 SUPPORTED**: 95% CI lower bound > 5×")
    else:
        out.append(f"✗ **H1 NOT SUPPORTED**: 95% CI lower bound = {ci_lo:.2f} ≤ 5×")
    out.append("")

    # --- H2: 4.7 effect > Sonnet 4.5 baseline (Seleznov 20.6×) ---
    out.append(f"## H2 — Opus 4.7 effect > Sonnet 4.5 baseline ({SELEZNOV_SONNET_45_OR}×)")
    out.append("")
    out.append(f"**Opus 4.7 OR_MH**: {or_mh:.2f}")
    out.append(f"**Seleznov Sonnet 4.5 baseline**: {SELEZNOV_SONNET_45_OR}")
    if ci_lo > SELEZNOV_SONNET_45_OR:
        out.append(f"✓ **H2 SUPPORTED**: 95% CI lower bound ({ci_lo:.2f}) > {SELEZNOV_SONNET_45_OR}")
    elif or_mh > SELEZNOV_SONNET_45_OR:
        out.append("~ **H2 DIRECTIONAL**: point estimate higher but CI does not exclude baseline")
    else:
        out.append("✗ **H2 NOT SUPPORTED**: 4.7 effect ≤ Sonnet 4.5 baseline")
    out.append("")

    # --- H3: hook_inject → ≥95% activation on positive triggers ---
    hook_acts = sum(c["activated"] for k, c in by_cell.items()
                    if k[3] == "hook_inject" and k[2] != "unrelated")
    hook_trials = sum(c["trials"] for k, c in by_cell.items()
                      if k[3] == "hook_inject" and k[2] != "unrelated")
    hook_rate = hook_acts / hook_trials if hook_trials else 0
    lo, hi = wilson_ci(hook_acts, hook_trials)

    out.append("## H3 — hook_inject convergence on positive triggers")
    out.append("")
    out.append(f"**Activation rate**: {hook_rate:.1%} ({hook_acts}/{hook_trials})")
    out.append(f"**95% CI**: [{lo:.1%}, {hi:.1%}]")
    if lo >= 0.95:
        out.append("✓ **H3 SUPPORTED**: 95% CI lower bound ≥ 95%")
    else:
        out.append(f"✗ **H3 NOT SUPPORTED**: 95% CI lower bound = {lo:.1%} < 95%")
    out.append("")

    # --- Negative-control sanity check ---
    unrel_acts = sum(c["activated"] for k, c in by_cell.items() if k[2] == "unrelated")
    unrel_trials = sum(c["trials"] for k, c in by_cell.items() if k[2] == "unrelated")
    unrel_rate = unrel_acts / unrel_trials if unrel_trials else 0
    out.append("## Negative-control (unrelated triggers)")
    out.append("")
    out.append(f"**False-positive activation rate**: {unrel_rate:.1%} ({unrel_acts}/{unrel_trials})")
    if unrel_rate <= 0.10:
        out.append("✓ False-positive rate ≤ 10%; negative control passes.")
    else:
        out.append(f"✗ False-positive rate {unrel_rate:.1%} > 10% — descriptions may be over-activating.")
    out.append("")

    # --- Caveats ---
    out.append("## Caveats")
    out.append("")
    out.append("- Single-author, single-environment (same as Seleznov's original).")
    out.append("- Model: see input file metadata. Pin model in publication.")
    out.append("- Variance estimator: Robins-Breslow-Greenland (no continuity correction).")
    out.append("- Pre-registration: hypotheses H1/H2/H3 fixed in README.md before data collection.")
    if is_mock:
        out.append("- **THIS IS MOCK DATA** — pseudo-random outcomes from a plausible distribution.")
        out.append("  Numbers above are validating the analysis pipeline, not measuring real model behavior.")

    report = "\n".join(out)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
        print(f"Report: {out_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
