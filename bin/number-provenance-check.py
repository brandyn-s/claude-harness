#!/usr/bin/env python3
"""Number-provenance gate — every quantity in a deliverable must trace to a
saved measurement, not to interpolation between measured points.

Why this exists: on 2026-08-02 a production deploy plan asserted
"$N/day -> ~5 of 96 people touched" as a measured blast radius. The
blast-radius script had probed candidate caps of 500..20000 CENTS ($5..$200)
and never tested $50000 ($500). The figure was interpolated from the $200 row,
shipped into the plan AND into the option text of a decision the user acted on,
and the measured answer was 13 of 96 -- 2.6x off. An adversarial reviewer
caught it; no gate did.

The ambient rule already existed. `rules/grading-discipline.md` carries
"NAME THE COUNT'S PROVENANCE BEFORE ITS FIRST USE", authored four hours
earlier in the same session by the same author who then violated it. That is
the whole argument for a mechanical gate: the guard was loaded, in context,
and self-authored, and it did not fire. A rule asks the author to remember; a
gate does not.

WHAT IT CHECKS

  A. UNTRACED QUANTITY (HARD when --strict) -- a currency amount, an "N of M",
     or a percentage in the deliverable that appears in NO cited evidence file.
  B. INTERPOLATION TELL (HARD when --strict) -- an approximation marker ("~",
     "about", "roughly", "approximately") attached to a quantity. A measured
     number does not need a hedge; the hedge is the tell that a value was
     estimated between known points. This is the shape that shipped.
  C. UNCITED DELIVERABLE (ADVISORY) -- no evidence files given at all, so
     nothing is checkable.

WHAT IT DELIBERATELY DOES NOT CHECK

  Dates, version strings, counts inside fenced code blocks, and quantities in
  lines marked as a target/threshold/proposal rather than a measurement.
  A cap you are PROPOSING ($N/day) is not a measurement claim; the claim is
  the blast radius attached to it. Over-flagging makes a gate decorative --
  the <10% block-rate bar in `verify-effectiveness.md` applies to this gate too.

Exit 1 on any HARD finding under --strict; 0 otherwise.

Usage:
  python3 bin/number-provenance-check.py PLAN.md --evidence run1.json run2.txt
  python3 bin/number-provenance-check.py PLAN.md --evidence *.json --strict
  python3 bin/number-provenance-check.py PLAN.md --evidence e.json --json
"""
import argparse
import json
import pathlib
import re
import sys

# A quantity worth tracing. Deliberately narrow -- see "does not check".
CURRENCY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
N_OF_M = re.compile(r"\b(\d+)\s+of\s+(\d+)\b")
PERCENT = re.compile(r"\b(\d+(?:\.\d+)?)\s?%")

# An approximation marker immediately preceding a quantity is the interpolation tell.
HEDGE = re.compile(
    r"(~|\babout\b|\broughly\b|\bapproximately\b|\bapprox\.?\b)\s*"
    r"(\$\s?[\d,]+(?:\.\d+)?|\d+\s+of\s+\d+|\d+(?:\.\d+)?\s?%)",
    re.IGNORECASE,
)

# Lines that RETRACT or QUOTE a prior wrong claim. A doc that records its own
# corrections must be able to name the wrong number; without this the checker gets
# LOUDER as the corpus gets more honest, which is the unsatisfiable-alarm shape.
RETRACTION = re.compile(
    r"\b(v\d+ (said|asserted|claimed)|was interpolated|never measured|"
    r"NOT measured|fabricated|superseded|previously|incorrectly|"
    r"\*\*false\*\*|retract)\b",
    re.IGNORECASE,
)

# Lines that are proposals/targets, not measurement claims.
PROPOSAL = re.compile(
    r"\b(propose|proposed|target|threshold|set to|cap of|register|candidate|"
    r"recommend|would be|budget of|sized|ceiling)\b",
    re.IGNORECASE,
)


def strip_code(text: str) -> str:
    """Blank fenced blocks and inline code so examples never trip the gate."""
    text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def norm(tok: str) -> str:
    """Compare numbers by value, not by formatting: 1,610,000 == 1610000."""
    return tok.replace(",", "").rstrip("0").rstrip(".") if "." in tok else tok.replace(",", "")


def evidence_values(paths):
    """Every numeric token appearing anywhere in the cited evidence."""
    vals, missing = set(), []
    for raw in paths:
        p = pathlib.Path(raw)
        if not p.is_file():
            missing.append(str(p))
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", t):
            vals.add(norm(m.group(0)))
            # a cents-denominated measurement covers its dollar rendering
            try:
                n = float(m.group(0).replace(",", ""))
                if n >= 100 and n == int(n):
                    vals.add(norm(f"{int(n) // 100}"))
                    vals.add(norm(f"{n / 100:.2f}"))
            except ValueError:
                pass
    return vals, missing


def check(deliverable: pathlib.Path, evidence_paths):
    text = deliverable.read_text(encoding="utf-8", errors="replace")
    scan = strip_code(text)
    ev, missing_ev = evidence_values(evidence_paths)
    findings = []

    if not evidence_paths:
        findings.append({
            "severity": "ADVISORY", "check": "uncited-deliverable", "line": 0,
            "detail": "no --evidence given; nothing is traceable",
        })

    for i, line in enumerate(scan.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith(("|---", "#")):
            continue
        if RETRACTION.search(line):
            continue          # a documented correction may quote the wrong figure
        proposal = bool(PROPOSAL.search(line))

        for m in HEDGE.finditer(line):
            findings.append({
                "severity": "HARD", "check": "interpolation-tell", "line": i,
                "detail": f"hedged quantity {m.group(0).strip()!r} — a measured "
                          f"number needs no approximation marker",
                "text": line.strip()[:150],
            })

        if proposal:
            continue  # a proposed value is not a measurement claim

        for m in N_OF_M.finditer(line):
            for tok in (m.group(1), m.group(2)):
                if norm(tok) not in ev:
                    findings.append({
                        "severity": "HARD", "check": "untraced-quantity", "line": i,
                        "detail": f"{m.group(0)!r}: {tok} not in cited evidence",
                        "text": line.strip()[:150],
                    })
                    break
        for m in CURRENCY.finditer(line):
            if norm(m.group(1)) not in ev:
                findings.append({
                    "severity": "HARD", "check": "untraced-quantity", "line": i,
                    "detail": f"${m.group(1)} not in cited evidence",
                    "text": line.strip()[:150],
                })
        for m in PERCENT.finditer(line):
            if norm(m.group(1)) not in ev:
                findings.append({
                    "severity": "HARD", "check": "untraced-quantity", "line": i,
                    "detail": f"{m.group(1)}% not in cited evidence",
                    "text": line.strip()[:150],
                })

    for mp in missing_ev:
        findings.append({
            "severity": "HARD", "check": "missing-evidence-file", "line": 0,
            "detail": f"cited evidence not found: {mp}",
        })
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deliverable")
    ap.add_argument("--evidence", nargs="*", default=[],
                    help="measurement artifacts every quantity must trace to")
    ap.add_argument("--strict", action="store_true", help="exit 1 on HARD findings")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()

    d = pathlib.Path(a.deliverable)
    if not d.is_file():
        print(f"deliverable not found: {d}", file=sys.stderr)
        return 2

    # HARD GUARD (2026-08-24): a mis-called gate must fail loud, not report a
    # plausible verdict. Measured incident: `--evidence .` (a directory) counted
    # as one unreadable "file", every quantity read as untraced, and two earlier
    # invocations were read as passes because $? was clobbered. If evidence was
    # requested, every path must exist and be a file, and at least one must be
    # readable — otherwise the caller made an instrumentation error (exit 2),
    # which is not the same verdict as "the deliverable failed" (exit 1).
    if a.evidence:
        bad = [e for e in a.evidence if not pathlib.Path(e).is_file()]
        if bad:
            for e in bad:
                kind = "directory" if pathlib.Path(e).is_dir() else "missing"
                print(f"evidence path is not a readable file ({kind}): {e}",
                      file=sys.stderr)
            print("refusing to grade against broken evidence — fix the call "
                  "(pass a FILE LIST; in zsh use ${=VAR} to split)", file=sys.stderr)
            return 2

    f = check(d, a.evidence)
    hard = [x for x in f if x["severity"] == "HARD"]

    if a.as_json:
        print(json.dumps({"deliverable": str(d), "evidence": a.evidence,
                          "findings": f, "hard": len(hard)}, indent=1))
    else:
        print(f"NUMBER PROVENANCE — {d.name}")
        print(f"  evidence files: {len(a.evidence)}   findings: {len(f)} "
              f"({len(hard)} HARD)\n")
        for x in f:
            loc = f"L{x['line']}" if x["line"] else "--"
            print(f"  [{x['severity']:8}] {x['check']:22} {loc:>6}  {x['detail']}")
            if x.get("text"):
                print(f"             > {x['text']}")
        if not f:
            print("  every quantity traces to cited evidence.")

    return 1 if (hard and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
