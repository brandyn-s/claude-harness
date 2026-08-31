"""
Post-hoc factuality validator for /roundtable transcripts.

Extracts verifiable claims (citations, version numbers, named studies,
quantitative claims with sources) from main-phase agent outputs and
checks each via Tavily web search. Tags each [OK] / [WARN] / [FAIL]:

  [OK]   — at least 2 search results corroborate the claim
  [WARN] — 1 or 0 supporting results; check manually
  [FAIL] — search ran but returned no results matching the claim

Complements `audit_concessions.py` (procedural rigor) by adding
content rigor: catches fabricated citations or numeric claims that
round-by-round critique didn't flag.

Usage:
    python3 validate_claims.py <run-dir>
    python3 validate_claims.py <run-dir> --rounds 3,4,5 --max-claims-per-record 5
    python3 validate_claims.py <run-dir> --strict   # exit 1 if any [FAIL]

Requires TAVILY_API_KEY. Cost: ~$0.005 per claim. Default 5
claims/record × 3 agents × 3 main rounds ≈ 45 claims ≈ $0.25/run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import requests  # type: ignore
except ImportError:
    print("ERROR: requests not installed. pip install requests", file=sys.stderr)
    sys.exit(2)

# ──────────────────────────────────────────────────────────────────────
# Claim extraction heuristics — sentences containing one of these signals
# are candidates for verification.
# ──────────────────────────────────────────────────────────────────────

# arXiv / DOI / paper citation
CITATION_PATTERNS = [
    re.compile(r"\barXiv:\s*\d{4}\.\d{4,5}\b", re.IGNORECASE),
    re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE),
    re.compile(r"\b(?:[A-Z][a-z]+\s+et\s+al\.?\s+(?:\(?\d{4}\)?))", re.IGNORECASE),
    re.compile(r"\(([A-Z][a-z]+(?:\s+&\s+[A-Z][a-z]+)?,?\s+\d{4})\)"),
]
# Quantitative claim with a possibly-verifiable subject
QUANT_PATTERNS = [
    re.compile(r"\b\d+(?:\.\d+)?\s*%"),
    re.compile(r"\b(?:reported|measured|observed|found|showed)\s+\d+", re.IGNORECASE),
    re.compile(r"\$\d[\d,]*(?:\.\d+)?[KMB]?"),
]
# Software/version reference
VERSION_PATTERNS = [
    re.compile(r"\b(?:v|version\s+)?\d+\.\d+(?:\.\d+)?\b"),
]
# Quoted statement (potentially fabricated)
QUOTE_PATTERN = re.compile(r'"([^"\n]{30,200})"')

# Sentence splitter — tolerates list bullets and code fences
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# Skip lines that are clearly not factual claims
SKIP_LINE_PATTERN = re.compile(
    r"^(\s*[-*]\s*)?(\*\*)?(Falsifier|Response|Critique|Confidence|Verdict)(\*\*)?:",
    re.IGNORECASE,
)


def extract_claims(text: str, max_claims: int = 5) -> list[str]:
    """Extract up to max_claims candidate claims from text."""
    claims: list[str] = []
    seen: set[str] = set()

    # Group consecutive non-skip lines into paragraphs so cross-line
    # sentences don't get truncated by the line splitter
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if (not stripped) or SKIP_LINE_PATTERN.match(line) or \
                stripped.startswith(("```", "#", "|", ">", "-", "*")):
            if buf:
                paragraphs.append(" ".join(buf))
                buf = []
            continue
        buf.append(stripped)
    if buf:
        paragraphs.append(" ".join(buf))

    for paragraph in paragraphs:
        for sentence in SENTENCE_SPLIT.split(paragraph):
            sentence = sentence.strip()
            if len(sentence) < 30 or len(sentence) > 400:
                continue
            # Score the sentence by how many verification signals it has
            score = 0
            for p in CITATION_PATTERNS:
                if p.search(sentence):
                    score += 3
                    break
            for p in QUANT_PATTERNS:
                if p.search(sentence):
                    score += 2
                    break
            if QUOTE_PATTERN.search(sentence):
                score += 2
            for p in VERSION_PATTERNS:
                if p.search(sentence) and re.search(r"\b(v|version)\b", sentence, re.IGNORECASE):
                    score += 1
                    break
            if score == 0:
                continue
            key = sentence[:80].lower()
            if key in seen:
                continue
            seen.add(key)
            claims.append(sentence)
            if len(claims) >= max_claims:
                return claims
    return claims


# ──────────────────────────────────────────────────────────────────────
# Tavily search
# ──────────────────────────────────────────────────────────────────────

TAVILY_URL = "https://api.tavily.com/search"


def tavily_search(claim: str, api_key: str) -> dict:
    """Run a Tavily search for the claim and return the raw response."""
    payload = {
        "api_key": api_key,
        "query": claim[:380],  # Tavily caps query length
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": False,
    }
    try:
        r = requests.post(TAVILY_URL, json=payload, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"error": str(e), "results": []}


def grade_claim(claim: str, response: dict) -> tuple[str, str]:
    """Return (verdict, rationale) for a claim given Tavily response."""
    if response.get("error"):
        return "WARN", f"search error: {response['error']}"
    results = response.get("results", []) or []
    n = len(results)
    if n == 0:
        return "FAIL", "no search results"
    # Look for substring overlap between claim tokens and result content
    tokens = {
        t.lower()
        for t in re.findall(r"\b[A-Za-z][A-Za-z0-9]{4,}\b", claim)
        if t.lower() not in {"about", "after", "before", "their", "there", "where", "which", "while", "would", "could", "should"}
    }
    if not tokens:
        return "WARN", f"{n} results but no distinctive tokens to check"
    matched = 0
    for r in results[:5]:
        content = (r.get("content") or "") + " " + (r.get("title") or "")
        content_lower = content.lower()
        hits = sum(1 for t in tokens if t in content_lower)
        if hits >= max(2, len(tokens) // 4):
            matched += 1
    if matched >= 2:
        return "OK", f"{matched}/{n} results corroborate"
    if matched == 1:
        return "WARN", f"only 1/{n} results match — verify manually"
    return "FAIL", f"{n} results but none corroborate"


# ──────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────


def validate_transcript(
    transcript_path: Path,
    api_key: str,
    rounds: list[int],
    max_claims_per_record: int,
) -> list[dict]:
    out: list[dict] = []
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("ok"):
                continue
            if rec.get("phase") != "main":
                continue
            if rec.get("round") not in rounds:
                continue
            text = rec.get("text", "")
            claims = extract_claims(text, max_claims=max_claims_per_record)
            for claim in claims:
                response = tavily_search(claim, api_key)
                verdict, rationale = grade_claim(claim, response)
                out.append({
                    "round": rec["round"],
                    "agent": rec["agent"],
                    "verdict": verdict,
                    "rationale": rationale,
                    "claim": claim,
                })
                print(f"[{verdict}] R{rec['round']} {rec['agent']}: {claim[:100]}...",
                      file=sys.stderr)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Path to /roundtable run directory")
    parser.add_argument("--rounds", default="3,4,5",
                        help="Comma-separated rounds to validate (default: 3,4,5)")
    parser.add_argument("--max-claims-per-record", type=int, default=5,
                        help="Max claims to extract per (round, agent) record")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 if any claim is FAIL")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write JSON report to PATH (default: stdout)")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import keychain
    for line in keychain.load_keys(["TAVILY_API_KEY"]):
        print(f"KEY: {line}", file=sys.stderr)
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("ERROR: no TAVILY_API_KEY resolved from env or Keychain", file=sys.stderr)
        return 2

    rounds = [int(r.strip()) for r in args.rounds.split(",") if r.strip()]

    candidates = [
        args.run_dir / "transcript.jsonl",
        args.run_dir / "results" / "transcript.jsonl",
    ]
    transcript_path = next((c for c in candidates if c.exists()), None)
    if transcript_path is None:
        print(f"transcript.jsonl not found in {args.run_dir} or {args.run_dir}/results",
              file=sys.stderr)
        return 2

    results = validate_transcript(
        transcript_path, api_key, rounds, args.max_claims_per_record
    )

    n_total = len(results)
    n_ok = sum(1 for r in results if r["verdict"] == "OK")
    n_warn = sum(1 for r in results if r["verdict"] == "WARN")
    n_fail = sum(1 for r in results if r["verdict"] == "FAIL")
    summary = {
        "transcript": str(transcript_path),
        "rounds_checked": rounds,
        "n_claims": n_total,
        "n_ok": n_ok,
        "n_warn": n_warn,
        "n_fail": n_fail,
        "claims": results,
    }

    output = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Report saved to {args.out}", file=sys.stderr)
    else:
        print(output)

    print(f"\n{n_total} claims checked: {n_ok} OK, {n_warn} WARN, {n_fail} FAIL",
          file=sys.stderr)

    if args.strict and n_fail > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
