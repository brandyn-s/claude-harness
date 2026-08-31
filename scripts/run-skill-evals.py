#!/usr/bin/env python3
"""Deterministic skill-eval runner.

Discovers `tests/<skill-name>/*.yaml` files, runs the `deterministic:` block
of each against the live SKILL.md and bundled artifacts, and reports
pass/fail. Designed to run in CI — no LLM API calls, no network.

The qualitative blocks (must_happen, must_not_happen, output_contains, guards)
require LLM-judge scoring and are NOT run here — they're documented expectations
for future LLM-driven evals.

Deterministic assertion types (declarative):
  frontmatter_equals:    "key": "value"           # frontmatter[key] == value
  frontmatter_contains:  "key": "substring"        # substring in str(frontmatter[key])
  frontmatter_matches:   "key": "regex"            # re.search(regex, frontmatter[key])
  body_contains:         "substring"               # substring in body
  body_not_contains:     "substring"               # substring NOT in body
  body_matches:          "regex"                   # re.search(regex, body)
  ref_resolves:          "filename.md"             # references/filename.md exists
  script_exists:         "path/relative/to/skill"  # file exists in skill dir
  script_runs:           "scripts/foo.py --help"   # cmd exits 0 (from skill dir)
  tests_count:           ">=N"                     # tests/<skill>/ has ≥N files
  references_resolve:    true                      # ALL refs in SKILL.md exist
  examples_count:        ">=N"                     # ≥N example markers in body

Schema in each YAML file:
  deterministic:
    - <assertion-type>: <value>
    - <assertion-type>:
        key: ...

Exit codes:
  0    all evals passed
  1    one or more evals failed
  2    runner error (malformed eval file, etc.)

Usage:
    python3 scripts/run-skill-evals.py                  # run all evals
    python3 scripts/run-skill-evals.py --skill capture  # run one skill's evals
    python3 scripts/run-skill-evals.py --json
"""
import argparse, json, operator, re, subprocess, sys, yaml
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None, text
    try:
        return yaml.safe_load(m.group(1)), text[m.end():]
    except yaml.YAMLError:
        return None, text


def cmp_count(actual, spec):
    """Compare an integer against a spec like '>=3', '<=5', '==2', or bare int."""
    spec = str(spec).strip()
    m = re.match(r"^(<=|>=|<|>|==|=)?\s*(\d+)$", spec)
    if not m:
        return False
    op_sym = m.group(1) or "=="
    n = int(m.group(2))
    ops = {"==": operator.eq, "=": operator.eq, "<=": operator.le,
           ">=": operator.ge, "<": operator.lt, ">": operator.gt}
    return ops[op_sym](actual, n)


def run_assertion(atype, aval, skill_dir, fm, body, body_no_code):
    """Run one assertion. Return (ok: bool, message: str)."""
    refs_dir = skill_dir / "references"

    if atype == "frontmatter_equals":
        for k, v in aval.items():
            if fm.get(k) != v:
                return False, f"frontmatter[{k!r}] != {v!r}; got {fm.get(k)!r}"
        return True, "ok"

    if atype == "frontmatter_contains":
        for k, sub in aval.items():
            val = str(fm.get(k, ""))
            if sub not in val:
                return False, f"frontmatter[{k!r}] missing substring {sub!r}"
        return True, "ok"

    if atype == "frontmatter_matches":
        for k, rex in aval.items():
            val = str(fm.get(k, ""))
            if not re.search(rex, val):
                return False, f"frontmatter[{k!r}] does not match /{rex}/"
        return True, "ok"

    if atype == "body_contains":
        if isinstance(aval, str):
            aval = [aval]
        for sub in aval:
            if sub not in body:
                return False, f"body missing {sub!r}"
        return True, "ok"

    if atype == "body_not_contains":
        if isinstance(aval, str):
            aval = [aval]
        for sub in aval:
            if sub in body:
                return False, f"body unexpectedly contains {sub!r}"
        return True, "ok"

    if atype == "body_matches":
        if isinstance(aval, str):
            aval = [aval]
        for rex in aval:
            if not re.search(rex, body):
                return False, f"body does not match /{rex}/"
        return True, "ok"

    if atype == "ref_resolves":
        if isinstance(aval, str):
            aval = [aval]
        for fname in aval:
            if not (refs_dir / fname).is_file():
                return False, f"references/{fname} does not exist"
        return True, "ok"

    if atype == "script_exists":
        if isinstance(aval, str):
            aval = [aval]
        for path in aval:
            if not (skill_dir / path).is_file():
                return False, f"{path} does not exist in skill dir"
        return True, "ok"

    if atype == "script_runs":
        cmd = aval if isinstance(aval, str) else aval.get("cmd", "")
        timeout = (aval if isinstance(aval, dict) else {}).get("timeout", 30)
        expect = (aval if isinstance(aval, dict) else {}).get("expect_exit", 0)
        try:
            r = subprocess.run(cmd, shell=True, cwd=skill_dir, capture_output=True,
                               timeout=timeout, text=True)
            if r.returncode != expect:
                return False, f"{cmd!r} exited {r.returncode} (expected {expect}); stderr={r.stderr[:200]!r}"
            return True, "ok"
        except subprocess.TimeoutExpired:
            return False, f"{cmd!r} timed out after {timeout}s"

    if atype == "tests_count":
        tests_dir = REPO_ROOT / "tests" / skill_dir.name
        if not tests_dir.is_dir():
            return False, "tests/<skill>/ dir missing"
        n = sum(1 for f in tests_dir.iterdir() if f.is_file() and f.suffix in (".yaml", ".yml", ".json", ".md"))
        ok = cmp_count(n, aval)
        return ok, f"tests count={n}, want {aval}"

    if atype == "references_resolve":
        # Reuse the validator's sibling-aware logic
        REF = re.compile(r"(?:`|\(|\s)references/([a-z0-9_/-]+\.md)")
        refs = set(REF.findall(body_no_code))
        existing = set()
        if refs_dir.exists():
            for f in refs_dir.rglob("*"):
                if f.is_file():
                    existing.add(str(f.relative_to(refs_dir)).replace("\\", "/"))
        sib_re = re.compile(r"`([a-z][a-z0-9_-]*)/references/[a-z0-9_-]+\.md`")
        sib_names = set(sib_re.findall(body_no_code))
        local_refs = set(refs)
        for r in list(local_refs):
            for ss in sib_names:
                if r.startswith(ss + "/"):
                    local_refs.discard(r); break
            for ss in sib_names:
                if re.search(re.escape(ss) + "/" + re.escape(r), body_no_code):
                    local_refs.discard(r); break
        missing = [r for r in local_refs if r not in existing]
        if missing:
            return False, f"missing refs: {missing[:5]}"
        return True, "ok"

    if atype == "examples_count":
        # Count Example/Eval markers (uses validator-aligned patterns)
        skill_cmd = "/" + skill_dir.name
        n = 0
        n += len(re.findall(r"(?:^|\n)#{1,3}\s+(?:Eval|Example|Test|Case|Worked|Scenario)\b", body, re.I))
        n += len(re.findall(r"\*\*(?:Eval|Example|Test|Case|Worked|Scenario)[^*]*\*\*", body, re.I))
        n += len(re.findall(r"^>\s*(?:User|Operator|You):\s*/", body, re.MULTILINE))
        invocation_lines = {line for line in body.splitlines() if skill_cmd in line}
        n += len(invocation_lines)
        ok = cmp_count(n, aval)
        return ok, f"examples count={n}, want {aval}"

    return False, f"unknown assertion type {atype!r}"


def run_eval_file(eval_file, skill_dir):
    """Run all deterministic assertions in one eval YAML file."""
    try:
        data = yaml.safe_load(eval_file.read_text(encoding='utf-8'))
    except yaml.YAMLError as e:
        return [{"file": str(eval_file), "name": "<parse-error>", "ok": False, "msg": str(e)}]

    if not data or not isinstance(data, dict):
        return [{"file": str(eval_file), "name": "<empty>", "ok": False, "msg": "empty or invalid YAML"}]

    detbox = data.get("deterministic")
    if not detbox:
        return []  # qualitative-only eval; skip silently

    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(encoding='utf-8')
    fm, body = parse_frontmatter(text)
    body_no_code = re.sub(r"```.*?```", "", body, flags=re.DOTALL)

    results = []
    name = data.get("name", eval_file.stem)
    for i, item in enumerate(detbox):
        if not isinstance(item, dict) or len(item) != 1:
            results.append({"file": str(eval_file), "name": f"{name}#{i}",
                            "ok": False, "msg": f"malformed assertion: {item!r}"})
            continue
        atype, aval = next(iter(item.items()))
        ok, msg = run_assertion(atype, aval, skill_dir, fm, body, body_no_code)
        results.append({"file": eval_file.name, "name": f"{name}/{atype}", "ok": ok, "msg": msg})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", help="Run evals for one skill only")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="Show all assertions, not just failures")
    args = ap.parse_args()

    skills_root = REPO_ROOT / "skills"
    tests_root = REPO_ROOT / "tests"
    all_results = []
    skills_tested = 0

    for tests_dir in sorted(tests_root.iterdir()):
        if not tests_dir.is_dir():
            continue
        skill_name = tests_dir.name
        if args.skill and skill_name != args.skill:
            continue
        skill_dir = skills_root / skill_name
        if not (skill_dir / "SKILL.md").is_file():
            continue

        eval_files = sorted(list(tests_dir.glob("*.yaml")) + list(tests_dir.glob("*.yml")))
        if not eval_files:
            continue
        had_deterministic = False
        for ef in eval_files:
            results = run_eval_file(ef, skill_dir)
            if results:
                had_deterministic = True
                for r in results:
                    r["skill"] = skill_name
                    all_results.append(r)
        if had_deterministic:
            skills_tested += 1

    if args.json:
        print(json.dumps(all_results, indent=2))
        return

    fails = [r for r in all_results if not r["ok"]]
    if fails or args.verbose:
        for r in (all_results if args.verbose else fails):
            mark = "✓" if r["ok"] else "✗"
            print(f"  {mark} [{r['skill']:<25} {r['file']:<35}] {r['name']}: {r['msg']}")
        print()

    if not all_results:
        print("No deterministic evals found. Add `deterministic:` blocks to tests/<skill>/*.yaml.")
        sys.exit(0)

    print(f"=== Skill-eval summary ===")
    print(f"  Skills with deterministic evals: {skills_tested}")
    print(f"  Total assertions: {len(all_results)}")
    print(f"  Passing: {len(all_results) - len(fails)}")
    print(f"  Failing: {len(fails)}")

    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
