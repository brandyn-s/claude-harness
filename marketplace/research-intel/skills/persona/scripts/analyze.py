"""Aggregate per-cell metrics + Cohen's kappa per RC.

Reads a run dir's persona JSONs (after both keyword + LLM-judge scoring
have run), computes:
  - per-RC endorsement rate (keyword and LLM-judge separately)
  - Cohen's kappa per RC between keyword and LLM-judge
  - off-rubric actionable summary

Writes analysis.md to the run dir.

Per F6 finding: REPORT BOTH SCORERS SEPARATELY. Never average.
Kappa < 0.6 = rubric ambiguity flag.

Usage:
    python3 analyze.py <run-dir>
    python3 analyze.py --aggregate <run-dir> [<run-dir> ...]  # meta-mode rollup
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cohens_kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if n == 0 or n != len(b):
        return float("nan")
    agreed = sum(1 for x, y in zip(a, b) if x == y)
    p_o = agreed / n
    p_a = sum(a) / n
    p_b = sum(b) / n
    p_e = p_a * p_b + (1 - p_a) * (1 - p_b)
    if p_e == 1:
        return float("nan")
    return round((p_o - p_e) / (1 - p_e), 3)


def _analyze_one(run_dir: Path) -> dict | None:
    """Return per-RC summary for a single run dir, or None if no successful
    persona outputs. Mirrors the single-run path but returns the aggregate
    instead of writing analysis.md, so the meta-mode rollup can compose
    multiple runs."""
    persona_dir = run_dir / "results-by-persona"
    if not persona_dir.exists():
        return None
    records: list[dict] = []
    for p in sorted(persona_dir.glob("persona_*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: malformed persona JSON in {p}: {e}", file=sys.stderr)
            print("  hint: delete or regenerate the corrupt file (re-run "
                  "dispatch.py) before re-running analyze.py.", file=sys.stderr)
            sys.exit(2)
        dispatch = rec.get("dispatch") or rec
        if dispatch.get("ok"):
            records.append(rec)
    if not records:
        return None
    rc_ids: set[str] = set()
    for r in records:
        kw = r.get("scoring", {}).get("keyword", {})
        for rc_id in kw.get("rcs", {}).keys():
            rc_ids.add(rc_id)
    rc_ids_sorted = sorted(rc_ids)
    keyword_endorse: dict[str, int] = {rc: 0 for rc in rc_ids_sorted}
    judge_endorse: dict[str, int] = {rc: 0 for rc in rc_ids_sorted}
    for r in records:
        kw = r.get("scoring", {}).get("keyword", {}).get("rcs", {})
        jd = r.get("scoring", {}).get("llm_judge", {}).get("judgment", {})
        for rc in rc_ids_sorted:
            if kw.get(rc) == "endorse":
                keyword_endorse[rc] += 1
            if jd.get(rc.lower()) == "endorse":
                judge_endorse[rc] += 1
    return {
        "run_dir": str(run_dir),
        "n": len(records),
        "rc_ids": rc_ids_sorted,
        "keyword_endorse": keyword_endorse,
        "judge_endorse": judge_endorse,
    }


def _run_aggregate(run_dirs: list[Path]) -> int:
    """Write meta_analysis.md beside the first run dir with a side-by-side
    rollup across all supplied run dirs. Used by meta mode after running
    rubric N times with different slugs."""
    summaries: list[dict] = []
    for rd in run_dirs:
        s = _analyze_one(rd)
        if s is None:
            print(f"  skipped (no successful outputs): {rd}", file=sys.stderr)
            continue
        summaries.append(s)
    if not summaries:
        sys.exit("No run dirs with successful outputs to aggregate")
    rc_ids: set[str] = set()
    for s in summaries:
        rc_ids.update(s["rc_ids"])
    rc_ids_sorted = sorted(rc_ids)
    out: list[str] = []
    out.append("# Meta-mode aggregate analysis")
    out.append("")
    out.append(f"**Run dirs aggregated**: {len(summaries)}")
    out.append("")
    out.append("## Per-run endorsement (keyword | LLM-judge), per RC")
    out.append("")
    header_cols = ["Run", "N"] + [f"{rc} (kw)" for rc in rc_ids_sorted] + \
                  [f"{rc} (jd)" for rc in rc_ids_sorted]
    out.append("| " + " | ".join(header_cols) + " |")
    out.append("|" + "|".join(["---"] * len(header_cols)) + "|")
    for s in summaries:
        row = [Path(s["run_dir"]).name, str(s["n"])]
        for rc in rc_ids_sorted:
            kw = s["keyword_endorse"].get(rc, 0)
            row.append(f"{kw}/{s['n']}")
        for rc in rc_ids_sorted:
            jd = s["judge_endorse"].get(rc, 0)
            row.append(f"{jd}/{s['n']}")
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    out.append("Per F6: never average across runs that varied cohort sampling, ")
    out.append("model, or seed. Compare cells side-by-side; treat divergence as ")
    out.append("a signal about the methodology, not the personas.")
    out.append("")
    dest = run_dirs[0].parent / "meta_analysis.md"
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {dest}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", nargs="+",
                     help="One run dir (single-run analysis) or multiple "
                          "run dirs together with --aggregate (meta rollup).")
    ap.add_argument("--aggregate", action="store_true",
                     help="Aggregate multiple run dirs into a single "
                          "meta_analysis.md (meta mode).")
    ap.add_argument("--strict", action="store_true",
                     help="exit 1 if any RC has in-band Cohen's kappa below "
                          "--kappa-floor (the rubric-ambiguity gate — promotes "
                          "the advisory kappa flag to an enforced floor).")
    ap.add_argument("--kappa-floor", type=float, default=0.6,
                     help="kappa gate floor for --strict (default 0.6 = persona's "
                          "in-band ambiguity threshold). The kappa-paradox guard "
                          "still applies: out-of-band low kappa never gates.")
    args = ap.parse_args()
    if args.aggregate:
        return _run_aggregate([Path(rd) for rd in args.run_dir])
    if len(args.run_dir) != 1:
        sys.exit("Single-run analysis takes exactly one run dir; pass "
                  "--aggregate for multi-dir rollup.")
    run_dir = Path(args.run_dir[0])
    persona_dir = run_dir / "results-by-persona"
    if not persona_dir.exists():
        sys.exit(f"No results-by-persona/ in {run_dir}")

    records: list[dict] = []
    for p in sorted(persona_dir.glob("persona_*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: malformed persona JSON in {p}: {e}", file=sys.stderr)
            print("  hint: delete or regenerate the corrupt file (re-run "
                  "dispatch.py) before re-running analyze.py.", file=sys.stderr)
            return 2
        dispatch = rec.get("dispatch") or rec
        if dispatch.get("ok"):
            records.append(rec)

    n = len(records)
    if n == 0:
        sys.exit("No successful persona outputs to analyze")

    # Collect per-RC results from each scorer
    rc_ids: set[str] = set()
    for r in records:
        kw = r.get("scoring", {}).get("keyword", {})
        for rc_id in kw.get("rcs", {}).keys():
            rc_ids.add(rc_id)
    rc_ids_sorted = sorted(rc_ids)

    # Per-RC keyword endorsement
    keyword_endorse: dict[str, int] = {rc: 0 for rc in rc_ids_sorted}
    judge_endorse: dict[str, int] = {rc: 0 for rc in rc_ids_sorted}
    judge_records: list[dict] = []

    for r in records:
        kw = r.get("scoring", {}).get("keyword", {}).get("rcs", {})
        jd = r.get("scoring", {}).get("llm_judge", {}).get("judgment", {})
        for rc in rc_ids_sorted:
            if kw.get(rc) == "endorse":
                keyword_endorse[rc] += 1
            if jd.get(rc.lower()) == "endorse":
                judge_endorse[rc] += 1
        judge_records.append(jd)

    # Cohen's kappa per RC (keyword endorse vs LLM-judge endorse)
    kappas: dict[str, float] = {}
    for rc in rc_ids_sorted:
        kw_bool = [r.get("scoring", {}).get("keyword", {}).get("rcs", {}).get(rc) == "endorse"
                    for r in records]
        jd_bool = [r.get("scoring", {}).get("llm_judge", {}).get("judgment", {}).get(rc.lower()) == "endorse"
                    for r in records]
        kappas[rc] = cohens_kappa(kw_bool, jd_bool)

    # Off-rubric actionable summary (LLM-judge)
    off_rubric_total = 0
    off_rubric_examples: list[str] = []
    for jd in judge_records:
        off_rubric_total += jd.get("off_rubric_actionable_count", 0)
        off_rubric_examples.extend(jd.get("off_rubric_examples", []))

    # False-lead (FL) endorsement and aggregate RC/FL fields (per D2 finding):
    # score_keyword.py writes "fls", "n_rc_endorsed", "n_fl_endorsed", and
    # "all_rc_endorsed"; score_llm_judge.py's schema requires "fl_endorsed"
    # and "kappa_check_notes". None of these reached analysis.md before.
    fl_ids: set[str] = set()
    for r in records:
        fl_ids.update(r.get("scoring", {}).get("keyword", {}).get("fls", {}).keys())
    fl_ids_sorted = sorted(fl_ids)
    fl_keyword_endorse: dict[str, int] = {fl: 0 for fl in fl_ids_sorted}
    fl_judge_endorse: dict[str, int] = {fl: 0 for fl in fl_ids_sorted}
    for r in records:
        kw_fls = r.get("scoring", {}).get("keyword", {}).get("fls", {})
        jd_fl_endorsed = {
            str(fl).lower()
            for fl in (r.get("scoring", {}).get("llm_judge", {})
                        .get("judgment", {}).get("fl_endorsed", []) or [])
        }
        for fl in fl_ids_sorted:
            if kw_fls.get(fl) == "endorse":
                fl_keyword_endorse[fl] += 1
            if fl.lower() in jd_fl_endorsed:
                fl_judge_endorse[fl] += 1
    all_rc_endorsed_count = sum(
        1 for r in records
        if r.get("scoring", {}).get("keyword", {}).get("all_rc_endorsed")
    )
    mean_n_rc_endorsed = sum(
        r.get("scoring", {}).get("keyword", {}).get("n_rc_endorsed", 0)
        for r in records
    ) / max(1, n)
    mean_n_fl_endorsed = sum(
        r.get("scoring", {}).get("keyword", {}).get("n_fl_endorsed", 0)
        for r in records
    ) / max(1, n)
    kappa_check_notes = [
        note.strip()
        for note in (
            jd.get("kappa_check_notes", "") for jd in judge_records
        )
        if note and note.strip()
    ]

    # Write analysis.md
    out: list[str] = []
    out.append(f"# Rubric mode analysis — {run_dir.name}")
    out.append("")
    out.append(f"**N successful**: {n}")
    out.append("")
    out.append("## Per-RC endorsement rates")
    out.append("")
    out.append("Cohen's kappa is base-rate-sensitive (Feinstein & Cicchetti 1990 — ")
    out.append("\"kappa paradox\"): at extreme base rates (most personas all endorse OR ")
    out.append("all reject), kappa can be low even at 90%+ raw agreement. The skill ")
    out.append("flags `kappa < 0.6` as rubric ambiguity ONLY when both scorers' base ")
    out.append("rates are in [0.2, 0.8]. Outside that band, kappa is unreliable and ")
    out.append("low values do not indicate ambiguity.")
    out.append("")
    out.append("| RC | Keyword endorse | LLM-judge endorse | Cohen's kappa | Flag |")
    out.append("|---|---:|---:|---:|---|")
    # RCs that trip the in-band ambiguity gate (kappa-paradox-safe: only
    # when both base rates are in [0.2, 0.8]). Drives --strict's exit code.
    floor = args.kappa_floor
    ambiguous: list[str] = []
    for rc in rc_ids_sorted:
        kw_pct = 100 * keyword_endorse[rc] / n
        jd_pct = 100 * judge_endorse[rc] / n
        kw_rate = keyword_endorse[rc] / n
        jd_rate = judge_endorse[rc] / n
        kappa = kappas[rc]
        kappa_str = f"{kappa:.3f}" if kappa == kappa else "NaN"  # NaN check
        in_band = 0.2 <= kw_rate <= 0.8 and 0.2 <= jd_rate <= 0.8
        if kappa == kappa and in_band and kappa < floor:
            ambiguous.append(rc)
        flag = ""
        if kappa == kappa and kappa < floor:
            if in_band:
                flag = f"⚠ kappa<{floor} — rubric ambiguity"
            else:
                flag = "low kappa, extreme base rate — kappa unreliable"
        elif kappa == kappa and kappa >= 0.8:
            flag = "high agreement"
        out.append(f"| {rc} | {keyword_endorse[rc]}/{n} ({kw_pct:.0f}%) | "
                   f"{judge_endorse[rc]}/{n} ({jd_pct:.0f}%) | "
                   f"{kappa_str} | {flag} |")
    out.append("")
    out.append("## Off-rubric actionable")
    out.append("")
    out.append(f"- Total off-rubric actionable count (LLM-judge): {off_rubric_total}")
    out.append(f"- Mean per persona: {off_rubric_total / max(1, n):.2f}")
    out.append("")
    if off_rubric_examples:
        out.append("Examples (sample of up to 10):")
        for ex in off_rubric_examples[:10]:
            out.append(f"- {ex[:200]}")
        out.append("")
    out.append("## False-lead (FL) endorsement and RC/FL aggregates")
    out.append("")
    if fl_ids_sorted:
        out.append("| FL | Keyword endorse | LLM-judge endorse |")
        out.append("|---|---:|---:|")
        for fl in fl_ids_sorted:
            out.append(f"| {fl} | {fl_keyword_endorse[fl]}/{n} | "
                       f"{fl_judge_endorse[fl]}/{n} |")
        out.append("")
    else:
        out.append("No false leads defined in this fixture.")
        out.append("")
    out.append(f"- All-RC rate (keyword, every RC endorsed): "
               f"{all_rc_endorsed_count}/{n}")
    out.append(f"- Mean RC endorsed per persona (keyword): "
               f"{mean_n_rc_endorsed:.2f}")
    out.append(f"- Mean FL endorsed per persona (keyword): "
               f"{mean_n_fl_endorsed:.2f}")
    out.append("")
    if kappa_check_notes:
        out.append("LLM-judge rubric-ambiguity notes (sample of up to 10):")
        for note in kappa_check_notes[:10]:
            out.append(f"- {note[:200]}")
        out.append("")
    out.append("## Methodology notes")
    out.append("")
    out.append("Per F6 finding: keyword scorer and LLM-judge measure")
    out.append("orthogonal-but-overlapping constructs. Reported separately.")
    out.append("Never average. Kappa < 0.6 IN-BAND (both base rates in")
    out.append("[0.2, 0.8]) indicates rubric ambiguity that should be")
    out.append("addressed in the next iteration of the rubric. Kappa < 0.6")
    out.append("OUT-OF-BAND is uninformative — use raw-agreement instead.")
    out.append("")
    out.append("Per F6 finding: ignore casual scoring (B1) entirely. The")
    out.append("rubric mode workflow does not include casual scoring.")
    out.append("")
    (run_dir / "analysis.md").write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {run_dir / 'analysis.md'}")

    # Enforced gate (opt-in): promote the advisory in-band kappa flag to an
    # exit code so a rubric with ambiguous RCs can block a run instead of
    # only annotating analysis.md. Default (no --strict) is unchanged.
    if args.strict and ambiguous:
        print(
            f"GATE FAIL: {len(ambiguous)} RC(s) with in-band Cohen's kappa "
            f"< {floor} (keyword vs LLM-judge disagree beyond chance while "
            f"both base rates are in [0.2, 0.8]): {', '.join(ambiguous)}. "
            f"Refine the rubric or re-label before trusting these "
            f"endorsement rates.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
