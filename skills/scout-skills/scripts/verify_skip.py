"""Multi-model SKIP verification for scout-skills Step 3.5.

Single-shot dispatch to Grok-reasoning + GPT-5.5-pro in parallel. Asks each
model to read the technique card and the architecture-wide destination
context (skill + relevant rules + topics + memory snippets), then vote on
whether the technique is present at ANY destination, missing everywhere,
or partially present.

v2 update (2026-05-17, F-S1 fix from roundtable): prior prompt anchored
on "OUR SKILL" only, which reproduced the editorial-polish bias across
models. Quorum now compares against an architecture-wide context set so
techniques don't get SKIP-confirmed just because they're absent from
one skill while a rule or topic file would house them.

Used after Step 3 returns a SKIP-candidate verdict to ensure the
asymmetric-evidentiary-burden trap doesn't slip past with a confidently
wrong "covered by our skill" verdict.

Exit codes:
  0   At least one external model agrees with SKIP (no flip warranted)
  10  Both external models say GAP-EXISTS or AMBIGUOUS (re-review needed)
  20  No model confirmed coverage (both errored, or mixed verdict with no CONFIRMED)
  30  Invalid input

Output: JSON to stdout with per-model verdict, rationale, latency.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "roundtable" / "scripts"
sys.path.insert(0, str(ROOT))
from adapters import openai_adapter, xai_adapter  # noqa: E402


PROMPT_TEMPLATE = """You are reviewing whether a substantive TECHNIQUE encoded in a community Claude Code skill is genuinely present somewhere in our architecture, or whether it represents a gap we should fill.

This is NOT a "are the SKILL.md files similar?" question. Techniques live in many places: ambient rules, knowledge-base topic files, worker-agent memory entries, skill reference files, AND skill bodies. A technique can be "covered" if any one destination encodes it.

TECHNIQUE CARD (from Step 2.7 — the underlying technique, not the artifact)
{technique_card}

COMMUNITY SKILL (the source — read for context, not as the comparison surface)
```
{community}
```

OUR ARCHITECTURE-WIDE CONTEXT (the destinations to check)
The following snippets are concatenated from candidate destinations where this technique could live. Each section is preceded by its destination label.

```
{our_context}
```

Answer with ONE of these verdicts on the first line:

  VERDICT: CONFIRMED-COVERED
  VERDICT: GAP-EXISTS
  VERDICT: AMBIGUOUS

Then ONE sentence of rationale that NAMES THE SPECIFIC DESTINATION (file path or section header) where the technique lives or fails to live. No preamble. No discussion.

Verdict definitions:
- CONFIRMED-COVERED: the operationalizable atom from the technique card is present somewhere in our architecture context with comparable rigor. Cite the destination file and section.
- GAP-EXISTS: the technique is not present at any destination, OR is mentioned only in passing (concept name without algorithm/heuristic/rubric/threshold). Cite what's missing.
- AMBIGUOUS: technique appears partially at one destination but not with the rigor of the community version. Cite both.

Bias your verdict toward GAP-EXISTS when:
- We mention the concept (the topic, the visual artifact) but not the operationalizable atom (the algorithm with inputs/outputs, the heuristic with stopping rule, the rubric with thresholds).
- The technique would clearly belong in a rule or topic file we don't have, even if a related skill discusses the topic adjacently.
- The community version names a specific source (industry/research/incident) that we have no architectural record of.

Bias toward CONFIRMED-COVERED only when the operationalizable atom is genuinely present with comparable rigor, even if formatted differently."""


def parse_verdict(text: str) -> tuple[str, str]:
    """Return (verdict, rationale). Verdict is one of the 3 expected, or 'PARSE-ERROR'."""
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("VERDICT:"):
            v = s.split(":", 1)[1].strip().upper()
            for canonical in ("CONFIRMED-COVERED", "GAP-EXISTS", "AMBIGUOUS"):
                if canonical in v:
                    rationale_lines = []
                    found_verdict = False
                    for ln in text.splitlines():
                        if found_verdict and ln.strip():
                            rationale_lines.append(ln.strip())
                        if ln.strip().upper().startswith("VERDICT:"):
                            found_verdict = True
                    return canonical, " ".join(rationale_lines)[:500]
    return "PARSE-ERROR", text.strip()[:500]


def call_model(name: str, adapter_module, prompt: str) -> dict:
    start = time.time()
    result = adapter_module.call(prompt, max_tokens=800)
    elapsed = time.time() - start
    if not result.get("ok"):
        return {
            "model": name,
            "ok": False,
            "verdict": "ERROR",
            "rationale": result.get("error", "unknown adapter error"),
            "elapsed_s": elapsed,
        }
    verdict, rationale = parse_verdict(result["text"])
    return {
        "model": name,
        "ok": True,
        "verdict": verdict,
        "rationale": rationale,
        "elapsed_s": elapsed,
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
    }


def build_our_context(paths: list[Path], max_chars_per_file: int) -> str:
    """Concatenate destination files with destination labels.

    Each section is preceded by '## DESTINATION: <relative-path>' so the
    model can cite specific destinations in its rationale.
    """
    sections = []
    for p in paths:
        if not p.exists():
            sections.append(f"## DESTINATION: {p} (NOT FOUND)\n")
            continue
        try:
            content = p.read_text(encoding="utf-8")[:max_chars_per_file]
        except Exception as e:
            sections.append(f"## DESTINATION: {p} (READ ERROR: {e})\n")
            continue
        # Use a label that's human-readable but not full Windows path
        try:
            rel = p.relative_to(Path.home() / ".claude")
            label = f".claude/{rel.as_posix()}"
        except ValueError:
            try:
                rel = p.relative_to(Path.home() / "Documents")
                label = f"Documents/{rel.as_posix()}"
            except ValueError:
                label = str(p)
        sections.append(f"## DESTINATION: {label}\n\n{content}\n")
    return "\n---\n".join(sections)


def main() -> int:
    p = argparse.ArgumentParser(description="Multi-model SKIP verification (architecture-wide)")
    p.add_argument("--technique-card", required=True,
                   help="Step 2.7 technique card content (or path to a .md file containing it)")
    p.add_argument("--community", required=True, type=Path,
                   help="Path to community SKILL.md")
    p.add_argument("--ours", action="append", type=Path, default=[],
                   help="Path to one of our destination files. Repeat for each plausible destination "
                        "(skill SKILL.md, rule file, topic file, memory file, references file). "
                        "Minimum 1, recommended 2-4.")
    p.add_argument("--max-chars-per-file", type=int, default=12000,
                   help="Truncate each destination file body to N chars (default 12000)")
    p.add_argument("--max-community-chars", type=int, default=20000,
                   help="Truncate community SKILL.md to N chars (default 20000)")
    args = p.parse_args()

    if not args.ours:
        print(json.dumps({"error": "at least one --ours destination file required"}))
        return 30
    if not args.community.exists():
        print(json.dumps({"error": f"community file not found: {args.community}"}))
        return 30
    missing_ours = [str(p) for p in args.ours if not p.exists()]
    if len(missing_ours) == len(args.ours):
        print(json.dumps({
            "error": "no --ours destination file exists on disk",
            "not_found": missing_ours,
            "hint": "check the --ours paths for typos; refusing to dispatch model calls against an empty architecture context",
        }))
        return 30

    # technique-card can be a literal string or a path
    tc_path = Path(args.technique_card)
    if tc_path.exists() and tc_path.is_file():
        technique_card = tc_path.read_text(encoding="utf-8", errors="replace")[:4000]
    else:
        technique_card = args.technique_card[:4000]

    community_text = args.community.read_text(encoding="utf-8", errors="replace")[: args.max_community_chars]
    our_context = build_our_context(args.ours, args.max_chars_per_file)

    prompt = PROMPT_TEMPLATE.format(
        technique_card=technique_card,
        community=community_text,
        our_context=our_context,
    )

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(call_model, "grok-4.20-reasoning", xai_adapter, prompt): "grok",
            ex.submit(call_model, "gpt-5.5-pro", openai_adapter, prompt): "gpt",
        }
        results = []
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: r["model"])
    grok_v = next((r["verdict"] for r in results if "grok" in r["model"]), "ERROR")
    gpt_v = next((r["verdict"] for r in results if "gpt" in r["model"]), "ERROR")

    # Quorum logic: SKIP is safe ONLY if at least one external model
    # explicitly says CONFIRMED-COVERED. Anything else — partial errors,
    # parse errors, ambiguity, or both errored — abstains to REVIEW-NEEDED
    # or ABSTAIN. Prior bug: the catch-all `else` defaulted to
    # SKIP-CONFIRMED on partial failure (e.g., one ERROR + one
    # PARSE-ERROR), which silently broke the asymmetric-evidentiary-burden
    # protection. Now: any unverified verdict must be treated as
    # ABSTAIN, not as a positive skip signal.
    confirmed = sum(1 for r in results if r["verdict"] == "CONFIRMED-COVERED")
    gap_or_amb = sum(1 for r in results if r["verdict"] in ("GAP-EXISTS", "AMBIGUOUS"))
    # PARSE-ERROR counts as a model failure (the verdict couldn't be read),
    # same as a plain ERROR. Both block a positive SKIP-CONFIRMED.
    all_errored = all(r["verdict"] in ("ERROR", "PARSE-ERROR") for r in results)

    if all_errored:
        decision = "ABSTAIN"
        exit_code = 20
    elif confirmed >= 1:
        decision = "SKIP-CONFIRMED"
        exit_code = 0
    elif gap_or_amb >= 2:
        decision = "REVIEW-NEEDED"
        exit_code = 10
    else:
        # At least one model errored AND no model returned a positive
        # CONFIRMED-COVERED — we can't claim coverage. Abstain.
        decision = "ABSTAIN"
        exit_code = 20

    out = {
        "technique_card_preview": technique_card[:200],
        "community_file": str(args.community),
        "our_destinations": [str(p) for p in args.ours],
        "decision": decision,
        "grok_verdict": grok_v,
        "gpt_verdict": gpt_v,
        "models": results,
    }
    print(json.dumps(out, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
