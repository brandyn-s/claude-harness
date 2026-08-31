#!/usr/bin/env python3
"""insecure-defaults oracle / verifier — components 2 + 8 of the harness framework.

Runs the per-finding verification suite deterministically (no LLM in the
loop) and emits structured verdicts. This is the Tier-1+2 oracle that
replaces prose-driven "trust the grep hit" verification.

Stratification:
  finding_locates      — Tier 1 (file:line still contains the claimed pattern)
  fail_open_classify   — Tier 1 (regex-driven classification: `or "x"` / `|| 'x'`
                         / `unwrap_or` / `getenv(..., default)` -> fail-open;
                         bare `env['KEY']` / no fallback -> fail-secure)
  not_test_fixture     — Tier 1 (path-exclusion against test/example dirs)
  startup_probe        — Tier 2 (subprocess: try to import/run without the env;
                         observe whether code crashes [fail-secure] or runs
                         with default [fail-open]). Optional, opt-in per finding.

What this script does NOT do (intentionally):
  exploitability       — requires understanding what the secret is *used for*
                         (signing JWTs vs. encrypting at rest vs. CSRF token).
  fix recommendations  — separate concern; report shape is already in SKILL.md.

Usage:
    verify_defaults.py <findings.json> [--root DIR] [--ndjson PATH] [--strict] [--json]

findings.json shape:
    {
      "report_id": "mcp-payment-2026-05-30",
      "findings": [
        {
          "id": "jwt-secret-fallback",
          "file": "src/auth/jwt.ts",
          "line": 15,
          "pattern": "process\\.env\\.JWT_SECRET\\s*\\|\\|\\s*['\"]",
          "claim": "fail_open",          // expected verdict
          "env_var": "JWT_SECRET",        // for startup_probe
          "probe_cmd": null               // optional: shell to run without env var
        }
      ]
    }

Exit codes:
    0   all required checks passed
    1   one or more checks failed
    2   runner error (bad args, malformed spec)
"""
import argparse, json, os, re, shlex, subprocess, sys
from datetime import datetime
from pathlib import Path


# Patterns that signal a fallback / fail-open shape. If one of these is present
# near the env var read, classify as fail-open. Order matters (more specific first).
FAIL_OPEN_HINTS = [
    re.compile(r"\.unwrap_or[a-z_]*\("),            # Rust env::var().unwrap_or("default")
    re.compile(r"\.get\([^)]*,\s*['\"][^'\"]+['\"]\)"),  # python os.environ.get("X", "default")
    re.compile(r"getenv\([^)]*,\s*['\"][^'\"]+['\"]\)"),
    re.compile(r"\|\|\s*['\"][^'\"]+['\"]"),        # JS || 'default'
    re.compile(r"\bor\s+['\"][^'\"]+['\"]"),         # Python `or "default"`
    re.compile(r"ENV\.fetch\([^)]*\)\s*\{"),         # Ruby ENV.fetch with block default
    re.compile(r"default\s*[:=]\s*['\"][^'\"]+['\"]"),
    re.compile(r"default\s*=\s*\".+\";", re.DOTALL),  # Nix mkOption { default = "..."; }
]

# Patterns that signal a fail-secure shape (no fallback; crash-on-missing).
FAIL_SECURE_HINTS = [
    re.compile(r"\.expect\(\""),                    # Rust env::var().expect("KEY required")
    re.compile(r"throw\s+new\s+Error"),
    re.compile(r"raise\s+(KeyError|ValueError|RuntimeError|EnvironmentError)"),
    re.compile(r"sys\.exit\("),
    re.compile(r"process\.exit\("),
    re.compile(r"panic!\("),
]

TEST_PATH_HINTS = [
    re.compile(r"(^|/)tests?(/|$)"),
    re.compile(r"(^|/)spec(/|$)"),
    re.compile(r"(^|/)__tests__(/|$)"),
    re.compile(r"(^|/)examples?(/|$)"),
    re.compile(r"(^|/)fixtures?(/|$)"),
    re.compile(r"\.example$"),
    re.compile(r"\.sample$"),
    re.compile(r"\.template$"),
    re.compile(r"(^|/)\.claude/worktrees(/|$)"),
    re.compile(r"(^|/)\.git/worktrees(/|$)"),
]


def emit(record, ndjson_handle):
    if ndjson_handle is None:
        return
    ndjson_handle.write(json.dumps(record) + "\n")


def _now():
    return os.environ.get("DEFAULTS_RUN_ID") or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def check_finding_locates(finding, root, ndjson):
    """Tier 1: the claimed file:line still contains the claimed pattern."""
    record = {"run_id": _now(), "check": "finding_locates",
              "id": finding["id"], "file": finding["file"], "line": finding["line"]}
    path = Path(root) / finding["file"]
    if not path.is_file():
        record["passed"] = False
        record["reason"] = f"file not found: {path}"
        emit(record, ndjson)
        return False
    try:
        line = path.read_text(encoding="utf-8", errors="replace").splitlines()[finding["line"] - 1]
    except IndexError:
        record["passed"] = False
        record["reason"] = f"line {finding['line']} out of range"
        emit(record, ndjson)
        return False
    pattern = finding.get("pattern", "")
    if not pattern:
        record["passed"] = True
        record["reason"] = "no pattern provided; locate check skipped"
        emit(record, ndjson)
        return True
    try:
        match = bool(re.search(pattern, line))
    except re.error as e:
        record["passed"] = False
        record["reason"] = f"finding regex compile error: {e}"
        emit(record, ndjson)
        return False
    record["passed"] = match
    if not match:
        record["reason"] = f"pattern not present at {path}:{finding['line']}"
        record["line_content"] = line[:200]
    emit(record, ndjson)
    return match


def classify_fail_open(finding, root, ndjson):
    """Tier 1: read +/- 3 lines around the finding; classify as fail-open or fail-secure."""
    record = {"run_id": _now(), "check": "fail_open_classify", "id": finding["id"]}
    path = Path(root) / finding["file"]
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, FileNotFoundError) as e:
        record["passed"] = False
        record["reason"] = f"could not read file: {e}"
        emit(record, ndjson)
        return None
    lineno = finding["line"]
    window = "\n".join(lines[max(0, lineno - 4): lineno + 3])
    fail_open = any(p.search(window) for p in FAIL_OPEN_HINTS)
    fail_secure = any(p.search(window) for p in FAIL_SECURE_HINTS)
    if fail_open and not fail_secure:
        verdict = "fail_open"
    elif fail_secure and not fail_open:
        verdict = "fail_secure"
    elif fail_open and fail_secure:
        verdict = "ambiguous"
    else:
        verdict = "no_fallback_pattern"
    record["verdict"] = verdict
    claim = finding.get("claim")
    if claim:
        record["passed"] = verdict == claim
        if not record["passed"]:
            record["reason"] = f"claim={claim} verdict={verdict}"
    else:
        record["passed"] = True
        record["reason"] = "no claim provided; classification advisory only"
    emit(record, ndjson)
    return verdict


def check_not_test_fixture(finding, ndjson):
    """Tier 1: exclude findings in test / example / worktree paths."""
    record = {"run_id": _now(), "check": "not_test_fixture", "id": finding["id"], "file": finding["file"]}
    f = finding["file"]
    hit = next((p.pattern for p in TEST_PATH_HINTS if p.search(f)), None)
    if hit:
        record["passed"] = False
        record["reason"] = f"path matches test/example exclusion: {hit}"
        emit(record, ndjson)
        return False
    record["passed"] = True
    emit(record, ndjson)
    return True


def startup_probe(finding, root, ndjson):
    """Tier 2: run `probe_cmd` with the env var cleared. Observe whether it
    crashes (fail-secure) or starts (fail-open). Opt-in per finding.
    """
    record = {"run_id": _now(), "check": "startup_probe", "id": finding["id"]}
    probe = finding.get("probe_cmd")
    env_var = finding.get("env_var")
    if not probe:
        record["passed"] = True
        record["reason"] = "no probe_cmd; sandbox executor skipped"
        emit(record, ndjson)
        return None
    env = {k: v for k, v in os.environ.items() if k != env_var}
    try:
        # SECURITY: probe_cmd comes from findings.json (possibly model-authored),
        # so it must never reach a shell — shell=True here was an arbitrary-command-
        # execution hole (a probe_cmd of "x && rm -rf y" would run the rm). Accept an
        # argv list directly, or shlex-split a string, and run with shell=False so
        # shell metacharacters (&&, ;, |, $(), backticks) are inert literal args.
        argv = probe if isinstance(probe, list) else shlex.split(probe)
        r = subprocess.run(argv, shell=False, cwd=root, env=env,
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            record["verdict"] = "fail_open"
            record["passed"] = True
            record["reason"] = f"probe succeeded without {env_var} — fail-open confirmed"
        else:
            record["verdict"] = "fail_secure"
            record["passed"] = True
            record["reason"] = f"probe crashed without {env_var} — fail-secure confirmed"
        record["stderr_tail"] = (r.stderr or "")[-200:]
    except subprocess.TimeoutExpired:
        record["passed"] = False
        record["reason"] = "probe timed out after 15s"
    except Exception as e:
        record["passed"] = False
        record["reason"] = f"probe error: {e}"
    emit(record, ndjson)
    return record.get("verdict")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("findings", help="Path to findings.json")
    ap.add_argument("--root", default=".", help="Codebase root (default: cwd)")
    ap.add_argument("--ndjson", help="Optional NDJSON event-log path")
    ap.add_argument("--strict", action="store_true", help="Fail on any check failure")
    ap.add_argument("--json", action="store_true", help="Emit summary JSON to stdout")
    args = ap.parse_args()

    spec_path = Path(args.findings)
    if not spec_path.is_file():
        print(f"ERROR: findings file not found: {spec_path}", file=sys.stderr)
        return 2
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: malformed findings json: {e}", file=sys.stderr)
        return 2
    if not isinstance(spec, dict) or not isinstance(spec.get("findings", []), list):
        print("ERROR: malformed findings spec: top level must be an object with a 'findings' list", file=sys.stderr)
        print("hint: see the findings.json shape in this script's docstring", file=sys.stderr)
        return 2
    for i, finding in enumerate(spec.get("findings", [])):
        if (not isinstance(finding, dict) or "id" not in finding
                or not isinstance(finding.get("file"), str)
                or not isinstance(finding.get("line"), int)):
            print(f"ERROR: malformed finding at index {i}: each finding needs 'id', a string 'file', and an integer 'line'", file=sys.stderr)
            print("hint: see the findings.json shape in this script's docstring", file=sys.stderr)
            return 2

    try:
        ndjson = open(args.ndjson, "a", encoding="utf-8") if args.ndjson else None
    except OSError as e:
        print(f"ERROR: cannot open --ndjson log path: {e}", file=sys.stderr)
        print("hint: ensure the parent directory exists and is writable", file=sys.stderr)
        return 2
    try:
        results = {"report_id": spec.get("report_id", "?"), "findings": []}
        all_passed = True
        for finding in spec.get("findings", []):
            located = check_finding_locates(finding, args.root, ndjson)
            not_fixture = check_not_test_fixture(finding, ndjson)
            verdict = classify_fail_open(finding, args.root, ndjson) if located else None
            probe_verdict = startup_probe(finding, args.root, ndjson) if located else None
            # The security determination must GATE the run, not just be reported.
            # When a finding declares an expected `claim`, a *definite opposite*
            # static classification OR dynamic-probe verdict fails it. (Previously
            # per_pass = located and not_fixture only, so a finding claiming
            # fail_secure on code that classified fail_open still passed — the
            # verdict was computed, logged, then discarded.) "ambiguous" /
            # "no_fallback_pattern" are NOT contradictions: they mean the regex
            # classifier couldn't decide, and it has known blind spots (JS `??`,
            # multi-line fallbacks) — don't fail the build on classifier weakness,
            # only on a clear opposite verdict.
            claim = finding.get("claim")
            definite = {"fail_open", "fail_secure"}
            classify_contradicts = bool(claim) and verdict in definite and verdict != claim
            probe_contradicts = bool(claim) and probe_verdict in definite and probe_verdict != claim
            per_pass = located and not_fixture and not classify_contradicts and not probe_contradicts
            if not per_pass:
                all_passed = False
            results["findings"].append({
                "id": finding["id"], "located": located, "is_production_path": not_fixture,
                "static_verdict": verdict, "probe_verdict": probe_verdict,
                "classify_contradicts": classify_contradicts,
                "probe_contradicts": probe_contradicts, "passed": per_pass,
            })
        results["all_passed"] = all_passed
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Report {results['report_id']}: {'PASS' if all_passed else 'FAIL'}")
            for f in results["findings"]:
                print(f"  {f['id']}: located={f['located']} prod_path={f['is_production_path']} "
                      f"static={f.get('static_verdict')} probe={f.get('probe_verdict')}")
        return 0 if all_passed or not args.strict else 1
    finally:
        if ndjson:
            ndjson.close()


if __name__ == "__main__":
    sys.exit(main())
