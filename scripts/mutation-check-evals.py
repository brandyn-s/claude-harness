#!/usr/bin/env python3
"""Anti-tautology gate for skill eval fixtures.

A deterministic assertion that CANNOT FAIL is worse than no assertion: it makes CI
green and the coverage number look complete while gating nothing. `body_contains:
"## Examples"` passes on nearly every skill in the corpus — it is coverage theater.

This tool proves each assertion can bite. For every assertion in
`tests/<skill>/*.yaml` it:

  1. snapshots the file it will mutate (SKILL.md, a reference, or a script),
  2. MUTATES it so the pinned contract is genuinely violated,
  3. re-runs `run-skill-evals.py --skill <skill>` and checks the assertion FAILED,
  4. restores the snapshot and re-verifies the suite is green again.

An assertion that still passes after its pinned thing was broken is reported as
TAUTOLOGICAL. Exit code is non-zero if any tautological assertion is found, so this
can gate CI or a backfill wave.

Mutation strategy per assertion type:
  body_contains / frontmatter_contains / body_matches / frontmatter_matches
      -> delete the pinned substring (or, for regex, the first literal run in it)
  body_not_contains
      -> INSERT the forbidden substring
  frontmatter_equals
      -> corrupt that frontmatter value
  ref_resolves / references_resolve / script_exists / script_runs
      -> temporarily move the referenced file aside
  examples_count / tests_count
      -> not mutated (counting assertions; see --skip-count). Reported as SKIPPED
         rather than silently claimed verified.

Restoration is via try/finally and re-verified, so an interrupted run cannot leave a
skill file broken. Snapshots go to a temp dir, never into the repo.

Usage:
    python3 scripts/mutation-check-evals.py --skill supergoal
    python3 scripts/mutation-check-evals.py --all
    python3 scripts/mutation-check-evals.py --skill retro --json
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "scripts" / "run-skill-evals.py"

COUNT_TYPES = {"examples_count", "tests_count"}
FILE_MOVE_TYPES = {"ref_resolves", "references_resolve", "script_exists", "script_runs"}


def run_runner(skill):
    """Run the eval harness for one skill. Return (n_fail, n_total)."""
    r = subprocess.run(
        [sys.executable, str(RUNNER), "--skill", skill, "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    try:
        results = json.loads(r.stdout)
    except json.JSONDecodeError:
        return (-1, -1)
    fails = sum(1 for x in results if not x.get("ok"))
    return (fails, len(results))


def first_literal(rex):
    """Extract the longest literal run from a regex, for deletion-based mutation."""
    parts = re.split(r"[\\\[\]\(\)\.\*\+\?\|\^\$\{\}]", rex)
    parts = [p for p in parts if len(p) >= 4]
    return max(parts, key=len) if parts else None


def mutate_text(path, atype, aval):
    """Mutate `path` so the assertion is violated. Return (ok, description)."""
    text = path.read_text(encoding="utf-8")

    def strings_of(v):
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, dict):
            return [str(x) for x in v.values()]
        return []

    # NOTE: every substring mutation must remove **ALL** occurrences, not just the
    # first. A `contains` assertion is satisfied by ANY occurrence, so a
    # replace(..., 1) leaves it passing and the assertion is wrongly reported
    # TAUTOLOGICAL. This bit on the first run: retro pins "10+ turns" (2
    # occurrences) and "/distill" (8) — both were false-positived until the
    # mutator switched to replace-all.
    if atype in ("body_contains", "frontmatter_contains"):
        for s in strings_of(aval):
            if s in text:
                n = text.count(s)
                path.write_text(text.replace(s, "__MUTATED__"), encoding="utf-8", newline="")
                return True, f"deleted {s[:44]!r} (x{n})"
        return False, "no pinned substring found to delete"

    if atype in ("body_matches", "frontmatter_matches"):
        for rex in strings_of(aval):
            lit = first_literal(rex)
            if lit and lit in text:
                n = text.count(lit)
                path.write_text(text.replace(lit, "__MUTATED__"), encoding="utf-8", newline="")
                return True, f"deleted literal {lit[:36]!r} (x{n}) from /{rex[:30]}/"
            m = re.search(rex, text)
            if m and m.group(0):
                path.write_text(text.replace(m.group(0), "__MUTATED__"), encoding="utf-8", newline="")
                return True, f"deleted regex match {m.group(0)[:40]!r}"
        return False, "regex did not match; cannot mutate"

    if atype == "body_not_contains":
        strs = strings_of(aval)
        if not strs:
            return False, "nothing to insert"
        path.write_text(text + f"\n\n{strs[0]}\n", encoding="utf-8", newline="")
        return True, f"INSERTED forbidden {strs[0][:50]!r}"

    if atype == "frontmatter_equals":
        if isinstance(aval, dict):
            for k in aval:
                m = re.search(rf"^({re.escape(k)}:\s*)(.+)$", text, re.MULTILINE)
                if m:
                    path.write_text(
                        text[:m.start(2)] + "__MUTATED__" + text[m.end(2):],
                        encoding="utf-8", newline="")
                    return True, f"corrupted frontmatter[{k}]"
        return False, "frontmatter key not found"

    return False, f"no mutation strategy for {atype}"


def resolve_move_targets(atype, aval, skill_dir):
    """Files to move aside so a resolve/exists assertion breaks."""
    out = []
    vals = aval if isinstance(aval, list) else [aval]
    if atype == "references_resolve":
        refs = skill_dir / "references"
        if refs.is_dir():
            md = sorted(refs.glob("*.md"))
            if md:
                out.append(md[0])
        return out
    for v in vals:
        if v is True:
            continue
        v = str(v)
        if atype == "ref_resolves":
            out.append(skill_dir / "references" / v)
        elif atype == "script_exists":
            out.append(skill_dir / v)
        elif atype == "script_runs":
            tok = v.split()
            for t in tok:
                if t.endswith(".py") or t.endswith(".sh"):
                    out.append(skill_dir / t)
                    break
    return [p for p in out if p.exists()]


def check_skill(skill, snapdir):
    skill_dir = REPO_ROOT / "skills" / skill
    tests_dir = REPO_ROOT / "tests" / skill
    skill_md = skill_dir / "SKILL.md"
    findings = []

    base_fail, base_total = run_runner(skill)
    if base_fail != 0:
        return [{"skill": skill, "assertion": "<baseline>", "verdict": "BASELINE_NOT_GREEN",
                 "detail": f"{base_fail} of {base_total} already failing — fix before mutating"}]

    for ef in sorted(list(tests_dir.glob("*.yaml")) + list(tests_dir.glob("*.yml"))):
        doc = yaml.safe_load(ef.read_text(encoding="utf-8")) or {}
        det = doc.get("deterministic") or []
        if not isinstance(det, list):
            findings.append({"skill": skill, "assertion": f"{ef.name}:<deterministic>",
                             "verdict": "MALFORMED",
                             "detail": "deterministic: is a MAPPING not a LIST — duplicate keys "
                                       "silently collapse and assertions are lost"})
            continue
        for i, item in enumerate(det):
            if not isinstance(item, dict) or len(item) != 1:
                findings.append({"skill": skill, "assertion": f"{ef.name}#{i}",
                                 "verdict": "MALFORMED",
                                 "detail": f"needs exactly 1 key, got {list(item) if isinstance(item, dict) else type(item).__name__}"})
                continue
            atype, aval = next(iter(item.items()))
            label = f"{ef.name}#{i} {atype}"

            if atype in COUNT_TYPES:
                findings.append({"skill": skill, "assertion": label, "verdict": "SKIPPED",
                                 "detail": "counting assertion — not mutation-checked"})
                continue

            moved = []
            snap = None
            try:
                if atype in FILE_MOVE_TYPES:
                    targets = resolve_move_targets(atype, aval, skill_dir)
                    if not targets:
                        findings.append({"skill": skill, "assertion": label,
                                         "verdict": "SKIPPED",
                                         "detail": "could not resolve a file to move aside"})
                        continue
                    for t in targets[:1]:
                        dest = Path(snapdir) / f"moved_{t.name}"
                        shutil.move(str(t), str(dest))
                        moved.append((t, dest))
                    desc = f"moved aside {moved[0][0].name}"
                else:
                    snap = Path(snapdir) / f"{skill}_SKILL.md.bak"
                    shutil.copy2(skill_md, snap)
                    ok, desc = mutate_text(skill_md, atype, aval)
                    if not ok:
                        findings.append({"skill": skill, "assertion": label,
                                         "verdict": "UNMUTATABLE", "detail": desc})
                        continue

                nfail, _ = run_runner(skill)
                if nfail > 0:
                    verdict, detail = "BITES", desc
                else:
                    verdict, detail = "TAUTOLOGICAL", f"still passed after: {desc}"
                findings.append({"skill": skill, "assertion": label,
                                 "verdict": verdict, "detail": detail})
            finally:
                for src, dest in moved:
                    shutil.move(str(dest), str(src))
                if snap and snap.exists():
                    shutil.copy2(snap, skill_md)
                    snap.unlink()

    post_fail, _ = run_runner(skill)
    if post_fail != 0:
        findings.append({"skill": skill, "assertion": "<restore>", "verdict": "RESTORE_FAILED",
                         "detail": f"{post_fail} failing after restore — INSPECT {skill_md}"})
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", action="append", help="skill name (repeatable)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tests_root = REPO_ROOT / "tests"
    if args.all:
        skills = [d.name for d in sorted(tests_root.iterdir())
                  if d.is_dir() and (REPO_ROOT / "skills" / d.name / "SKILL.md").is_file()
                  and (list(d.glob("*.yaml")) or list(d.glob("*.yml")))]
    elif args.skill:
        skills = args.skill
    else:
        ap.error("pass --skill NAME or --all")

    all_findings = []
    with tempfile.TemporaryDirectory(prefix="evalmut-") as snapdir:
        for s in skills:
            all_findings.extend(check_skill(s, snapdir))

    if args.json:
        json.dump(all_findings, sys.stdout, indent=2)
        print()
    else:
        by = {}
        for f in all_findings:
            by.setdefault(f["verdict"], []).append(f)
        for f in all_findings:
            mark = {"BITES": "✓", "TAUTOLOGICAL": "✗", "SKIPPED": "–",
                    "UNMUTATABLE": "?", "MALFORMED": "✗",
                    "BASELINE_NOT_GREEN": "!", "RESTORE_FAILED": "!"}.get(f["verdict"], "?")
            print(f"  {mark} [{f['skill']:<16}] {f['assertion']:<34} {f['verdict']:<18} {f['detail'][:70]}")
        print("\n=== Mutation summary ===")
        for k in ("BITES", "TAUTOLOGICAL", "MALFORMED", "SKIPPED", "UNMUTATABLE",
                  "BASELINE_NOT_GREEN", "RESTORE_FAILED"):
            if by.get(k):
                print(f"  {k:<20} {len(by[k])}")

    bad = [f for f in all_findings
           if f["verdict"] in ("TAUTOLOGICAL", "MALFORMED", "RESTORE_FAILED",
                               "BASELINE_NOT_GREEN")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
