"""
Phase 1 instrumentation for selective-triggering classifier (runbook #6).

After a /roundtable run completes, run this to tag whether multi-agent
surfaced anything beyond Round 1's single-agent independent assessment.
Accumulates in runs.csv at the skill root. After ~10-20 tagged runs,
analyze for selectivity heuristics (e.g., target word count, complexity)
that predict when multi-agent is worth its $32 cost.

Usage:
    python3 tag_run.py --run-dir <path> --useful yes
    python3 tag_run.py --run-dir <path> --useful no --notes "single-agent R1 already had everything"
    python3 tag_run.py --run-dir <path> --useful unclear --notes "ambiguous; revisit later"

If --run-dir is given, auto-fills target_word_count from context.md and
counts # of bullet items in META_SYNTHESIS.md as a rough finding count.
Manual override of any field via explicit flag.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "runs.csv"
HEADERS = [
    "run_id",
    "timestamp",
    "target_word_count",
    "num_findings",
    "num_unique_to_multi_agent",
    "multi_agent_useful",
    "notes",
]


def count_words(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return len(f.read().split())


def count_findings(meta_synthesis: Path) -> int:
    if not meta_synthesis.exists():
        return 0
    with open(meta_synthesis, encoding="utf-8") as f:
        text = f.read()
    # Heuristic: bullet items at the start of a line. Misses some
    # findings that are full paragraphs; that's fine for a Phase 1
    # sketch (the user can override with --num-findings).
    return len(re.findall(r"^\s*[-*]\s+", text, re.MULTILINE))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=None,
                        help="Path to /roundtable run directory (auto-fills counts)")
    parser.add_argument("--run-id", default=None,
                        help="Override run_id (default: run-dir basename)")
    parser.add_argument("--useful", choices=["yes", "no", "unclear"], required=True,
                        help="Did multi-agent surface anything beyond R1 single-agent?")
    parser.add_argument("--target-word-count", type=int, default=None)
    parser.add_argument("--num-findings", type=int, default=None)
    parser.add_argument("--num-unique-to-multi-agent", type=int, default=None,
                        help="How many findings only emerged from cross-talk")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    run_id = args.run_id
    target_wc = args.target_word_count
    num_findings = args.num_findings

    if args.run_dir:
        run_dir = args.run_dir.resolve()
        if not run_dir.exists():
            print(f"run-dir not found: {run_dir}", file=sys.stderr)
            return 2
        if run_id is None:
            run_id = run_dir.name
        if target_wc is None:
            ctx_candidates = [run_dir / "context.md", run_dir.parent / "context.md"]
            ctx = next((c for c in ctx_candidates if c.exists()), None)
            if not ctx:
                # Fallback: extract context_file from run_start record in transcript.jsonl
                transcript_path = run_dir / "transcript.jsonl"
                if transcript_path.exists():
                    try:
                        with open(transcript_path, encoding="utf-8") as f:
                            for line in f:
                                rec = json.loads(line)
                                if rec.get("event") == "run_start" and "context_file" in rec:
                                    ctx = Path(rec["context_file"])
                                    if ctx.exists():
                                        break
                    except (json.JSONDecodeError, OSError):
                        pass
            if ctx:
                target_wc = count_words(ctx)
            else:
                print(
                    "warning: no context.md in run-dir and no resolvable "
                    "context_file in transcript.jsonl; leaving "
                    "target_word_count blank (pass --target-word-count to set it)",
                    file=sys.stderr,
                )
                target_wc = None
        if num_findings is None:
            meta_candidates = [
                run_dir / "META_SYNTHESIS.md",
                run_dir / "results" / "META_SYNTHESIS.md",
            ]
            meta = next((m for m in meta_candidates if m.exists()), None)
            num_findings = count_findings(meta) if meta else 0
    elif run_id is None:
        print("Either --run-dir or --run-id must be provided", file=sys.stderr)
        return 2

    row = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_word_count": target_wc if target_wc is not None else "",
        "num_findings": num_findings if num_findings is not None else "",
        "num_unique_to_multi_agent": (
            args.num_unique_to_multi_agent if args.num_unique_to_multi_agent is not None else ""
        ),
        "multi_agent_useful": args.useful,
        "notes": args.notes,
    }

    new_file = not CSV_PATH.exists()
    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)

    print(f"Tagged: {run_id} -> useful={args.useful}", file=sys.stderr)
    print(f"CSV: {CSV_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
