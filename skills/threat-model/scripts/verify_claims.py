#!/usr/bin/env python3
"""threat-model oracle / verifier — components 2 + 8 of the harness framework.

Runs the threat-model verification suite deterministically (no LLM in the
loop) and emits structured per-claim verdicts. This is the Tier-1+2 oracle
that grounds the model in actual code.

Stratification:
  structure_check     — Tier 1 (4 required sections present)
  file_refs_resolve   — Tier 1 (every `path/to/file.ext` reference points
                        to a file that actually exists)
  surface_attribution — Tier 1 (each attack surface in Section 3 has a
                        mitigations bullet block and >= 1 attacker story)
  calls_edge_probe    — Tier 2 (deterministic source grounding: each
                        claimed edge's endpoint symbols are searched in the
                        source root. GROUNDED = symbol present — a necessary
                        condition for the edge, NOT proof of the specific
                        A->B edge; UNSUBSTANTIATED = symbol absent -> fail;
                        MANUAL = pattern too ambiguous to search. Cypher
                        intents are still emitted so an orchestrator with
                        code-graph can run the stronger graph query.)

What this script does NOT do (intentionally):
  attacker-story authorship  — the prose belongs to Claude.
  severity calibration        — Section 4 is descriptive, not verifiable.
  fix recommendations         — out of scope per SKILL.md.

Usage:
    verify_claims.py <threat-model.md> [--claims claims.json] [--root DIR]
                     [--ndjson PATH] [--strict] [--json] [--project NAME]

claims.json (optional) shape:
    {
      "model_id": "mcp-payment-2026-05-30",
      "claims": [
        {
          "id": "tool-args-cross-mcp-boundary",
          "kind": "calls_across",
          "from_pattern": ".*Handler.*",
          "to_pattern": ".*execute.*",
          "boundary": "mcp_client_server"
        }
      ]
    }

Exit codes (--strict mode):
    0   all required checks passed
    1   one or more required checks failed
    2   runner error

Exit codes (without --strict):
    0   checks run (passed or failed)
    2   runner error
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_SECTIONS = [
    re.compile(r"^##\s+(Section\s+)?1[.\s:]?\s*Overview", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+(Section\s+)?2[.\s:]?\s*Trust\s*Boundaries", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+(Section\s+)?3[.\s:]?\s*Attack\s*Surface", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^##\s+(Section\s+)?4[.\s:]?\s*Criticality", re.IGNORECASE | re.MULTILINE),
]

# Conservative file-reference detector: backtick-quoted paths with a slash
# AND a known source extension. Reduces false hits on prose like `auth.md`.
FILE_REF_RE = re.compile(
    r"`([A-Za-z0-9_./\-]+/[A-Za-z0-9_.\-]+\.(?:rs|py|ts|tsx|js|jsx|go|java|c|cpp|h|hpp|nix|yaml|yml|toml|md|sh))`"
)

# Bare path mentions (`src/foo/bar.rs`) inside parentheses. More permissive.
PAREN_FILE_RE = re.compile(
    r"\(([A-Za-z0-9_./\-]+\.(?:rs|py|ts|tsx|js|jsx|go|java|c|cpp|h|hpp|nix))(?::\d+)?\)"
)


def emit(record, ndjson_handle):
    if ndjson_handle is None:
        return
    ndjson_handle.write(json.dumps(record) + "\n")


def _now():
    return os.environ.get("THREAT_RUN_ID") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _searchable_token(pattern):
    """Extract a literal identifier token from a qualified_name regex so it
    can be searched in source, or None if the pattern is too ambiguous to
    ground deterministically (-> MANUAL, never a false FAIL)."""
    if not pattern:
        return None
    cleaned = re.sub(r"\(\?i\)|\\b|[\^\$\(\)\|\[\]\{\}\?\+\*\.]", " ", pattern)
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", cleaned)
    return max(toks, key=len) if toks else None


# Code extensions the grounding search scans. Deliberately EXCLUDES .md /
# .json so the search never self-matches the threat-model or the claims.json
# (which contain the symbol names as prose/spec, not as code definitions).
_SOURCE_INCLUDES = ("*.rs", "*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.go",
                    "*.java", "*.c", "*.cpp", "*.h", "*.hpp", "*.nix")


def _search_count(token, root):
    """Count SOURCE matches for a literal token under root (deterministic
    necessary-condition check). Returns (count, sample_line); count is None
    when grep is unavailable or errors (-> inconclusive, not a failure).
    Restricted to code extensions so it can't self-match the model/claims."""
    try:
        r = subprocess.run(
            ["grep", "-rIn", "--fixed-strings"]
            + [f"--include={g}" for g in _SOURCE_INCLUDES]
            + ["--", token, str(root)],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, "grep-unavailable"
    if r.returncode >= 2:
        return None, f"grep-error rc={r.returncode}"
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return len(lines), (lines[0][:160] if lines else "")


def check_structure(text, ndjson):
    record = {"run_id": _now(), "check": "structure_check"}
    missing = []
    for i, rx in enumerate(REQUIRED_SECTIONS, start=1):
        if not rx.search(text):
            missing.append(i)
    record["passed"] = not missing
    record["missing_sections"] = missing
    if missing:
        record["reason"] = f"missing section(s): {missing}"
    emit(record, ndjson)
    return record["passed"]


def check_file_refs(text, root, ndjson):
    record = {"run_id": _now(), "check": "file_refs_resolve"}
    refs = set()
    for rx in (FILE_REF_RE, PAREN_FILE_RE):
        for m in rx.findall(text):
            refs.add(m)
    missing = []
    for ref in refs:
        p = Path(root) / ref
        if not p.is_file() and not p.is_dir():
            missing.append(ref)
    record["n_refs"] = len(refs)
    record["n_missing"] = len(missing)
    record["passed"] = not missing
    if missing:
        record["reason"] = f"{len(missing)} reference(s) do not resolve: {sorted(missing)[:10]}"
    emit(record, ndjson)
    return record["passed"]


def check_surface_attribution(text, ndjson):
    """Every Section-3 surface heading should be followed by both a Mitigations
    bullet block and an Attacker stories bullet block before the next heading."""
    record = {"run_id": _now(), "check": "surface_attribution"}
    # Locate Section 3 boundaries
    m3 = re.search(r"^##\s+(Section\s+)?3[.\s:]?\s*Attack\s*Surface.*?$",
                   text, re.IGNORECASE | re.MULTILINE)
    m4 = re.search(r"^##\s+(Section\s+)?4[.\s:]?\s*Criticality",
                   text, re.IGNORECASE | re.MULTILINE)
    if not m3:
        record["passed"] = False
        record["reason"] = "no Section 3 found"
        emit(record, ndjson)
        return False
    s3_end = m4.start() if m4 else len(text)
    section3 = text[m3.end():s3_end]

    headings = list(re.finditer(r"^###\s+.+$", section3, re.MULTILINE))
    if not headings:
        record["passed"] = False
        record["reason"] = "Section 3 has no `###` surface subsections"
        emit(record, ndjson)
        return False

    issues = []
    for i, h in enumerate(headings):
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(section3)
        block = section3[start:end]
        if not re.search(r"\*\*Mitigations\*\*", block, re.IGNORECASE):
            issues.append(f"{h.group(0).strip()}: missing Mitigations")
        if not re.search(r"\*\*Attacker\s+stories\*\*", block, re.IGNORECASE):
            issues.append(f"{h.group(0).strip()}: missing Attacker stories")
    record["n_surfaces"] = len(headings)
    record["n_issues"] = len(issues)
    record["passed"] = not issues
    if issues:
        record["issues"] = issues[:10]
        record["reason"] = f"{len(issues)} surface attribution issue(s)"
    emit(record, ndjson)
    return record["passed"]


def probe_calls_edges(claims_path, project, root, ndjson):
    """Tier 2: each claimed cross-boundary edge ("X CALLS Y" / "uses Y") is
    grounded DETERMINISTICALLY against the source tree — its endpoint symbols
    are searched under ``root``. Verdict semantics (written down, per the
    oracle discipline):

      GROUNDED        every searchable endpoint symbol is present in source —
                      a NECESSARY condition for the edge. NOT proof the
                      specific A->B edge exists; that needs a call graph.
      UNSUBSTANTIATED a searchable endpoint symbol is ABSENT from the whole
                      source root — the claimed edge cannot be grounded;
                      the claim is unverified and the probe FAILS.
      MANUAL          the pattern is too regex-ambiguous to search (or grep
                      was unavailable) — the harness makes no claim; a human
                      must verify. Does NOT fail the probe.

    A Cypher *intent* is still emitted per claim so an orchestrator that has
    code-graph indexed can run the stronger graph query (generate-and-filter:
    cheap grep grounding gates here; the graph query is the optional upgrade).
    """
    record = {"run_id": _now(), "check": "calls_edge_probe"}
    if not claims_path:
        record["passed"] = True
        record["reason"] = "no claims.json provided; calls-edge probe skipped"
        emit(record, ndjson)
        return True
    try:
        spec = json.loads(Path(claims_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError) as e:
        record["passed"] = False
        record["reason"] = f"could not load claims: {e}"
        emit(record, ndjson)
        return False

    n_emitted = grounded = unsubstantiated = manual = 0
    unsub_ids = []
    for c in spec.get("claims", []):
        kind = c.get("kind", "calls_across")
        # 1) emit the code-graph intent (optional orchestrator upgrade)
        intent = {
            "run_id": _now(), "check": "calls_edge_intent",
            "claim_id": c.get("id"),
            "kind": kind,
            "project": project,
            "from_pattern": c.get("from_pattern"),
            "to_pattern": c.get("to_pattern"),
            "boundary": c.get("boundary"),
        }
        if kind == "calls_across":
            intent["cypher"] = (
                "MATCH (a)-[r:CALLS|HTTP_CALLS]->(b) "
                f"WHERE a.qualified_name =~ '(?i){c.get('from_pattern', '.*')}' "
                f"AND b.qualified_name =~ '(?i){c.get('to_pattern', '.*')}' "
                "RETURN a.name, b.name, r.confidence LIMIT 30"
            )
        elif kind == "usage":
            intent["cypher"] = (
                "MATCH (a)-[r:USAGE]->(b) "
                f"WHERE b.name =~ '(?i){c.get('to_pattern', '.*')}' "
                "RETURN a.name, a.file_path, b.name LIMIT 30"
            )
        emit(intent, ndjson)
        n_emitted += 1

        # 2) deterministic source grounding (the actual verdict). usage claims
        # have only a callee (to_pattern); calls_across has both endpoints.
        endpoints = [c.get("to_pattern")]
        if kind != "usage":
            endpoints.append(c.get("from_pattern"))
        details = []
        any_absent = any_present = any_inconclusive = False
        for pat in [p for p in endpoints if p]:
            tok = _searchable_token(pat)
            if tok is None:
                any_inconclusive = True
                details.append({"pattern": pat, "token": None, "matches": None})
                continue
            cnt, sample = _search_count(tok, root)
            details.append({"pattern": pat, "token": tok, "matches": cnt, "sample": sample})
            if cnt is None:
                any_inconclusive = True
            elif cnt == 0:
                any_absent = True
            else:
                any_present = True
        if any_absent:
            verdict = "UNSUBSTANTIATED"
            unsubstantiated += 1
            unsub_ids.append(c.get("id"))
        elif any_present:
            verdict = "GROUNDED"
            grounded += 1
        else:
            verdict = "MANUAL"
            manual += 1
        emit({"run_id": _now(), "check": "calls_edge_grounding",
              "claim_id": c.get("id"), "kind": kind,
              "verdict": verdict, "endpoints": details}, ndjson)

    passed = unsubstantiated == 0
    record["n_claims_emitted"] = n_emitted
    record["grounded"] = grounded
    record["unsubstantiated"] = unsubstantiated
    record["manual"] = manual
    record["unsubstantiated_ids"] = unsub_ids
    record["passed"] = passed
    record["reason"] = (
        f"deterministic source grounding under {root}: {grounded} grounded, "
        f"{unsubstantiated} unsubstantiated, {manual} manual (human-required). "
        f"GROUNDED = endpoint symbol present (necessary condition, not proof "
        f"of the specific edge); code-graph intents emitted for the stronger "
        f"graph query."
    )
    emit(record, ndjson)
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("threat_model", help="Path to threat-model.md")
    ap.add_argument("--claims", help="Optional claims.json for code-graph probes")
    ap.add_argument("--root", default=".", help="Codebase root for file-ref resolution")
    ap.add_argument("--project", default=None, help="Project name for code-graph queries")
    ap.add_argument("--ndjson", help="Optional NDJSON event-log path")
    ap.add_argument("--strict", action="store_true", help="Fail on any check failure")
    ap.add_argument("--json", action="store_true", help="Emit summary JSON to stdout")
    args = ap.parse_args()

    tm_path = Path(args.threat_model)
    if not tm_path.is_file():
        print(f"ERROR: threat-model not found: {tm_path}", file=sys.stderr)
        return 2
    text = tm_path.read_text(encoding="utf-8")
    ndjson = open(args.ndjson, "a", encoding="utf-8") if args.ndjson else None
    try:
        results = {
            "model_path": str(tm_path),
            "structure": check_structure(text, ndjson),
            "file_refs": check_file_refs(text, args.root, ndjson),
            "attribution": check_surface_attribution(text, ndjson),
            "calls_edges": probe_calls_edges(args.claims, args.project, args.root, ndjson),
        }
        results["all_passed"] = all(results[k] for k in ("structure", "file_refs", "attribution", "calls_edges"))
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Threat-model {tm_path}: {'PASS' if results['all_passed'] else 'FAIL'}")
            for k in ("structure", "file_refs", "attribution", "calls_edges"):
                print(f"  {k}: {'pass' if results[k] else 'FAIL'}")
        return 0 if results["all_passed"] or not args.strict else 1
    finally:
        if ndjson:
            ndjson.close()


if __name__ == "__main__":
    sys.exit(main())
