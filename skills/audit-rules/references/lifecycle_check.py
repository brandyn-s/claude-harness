"""
Step 3b: post-promotion lifecycle measurement.

For each rule promotion in the last N days (default 30), compare violation
rate in the 14 days BEFORE the promotion vs the 14 days AFTER. Flag
promotions where the rate didn't drop at least 30% relative.

A "promotion commit" is detected by matching the commit subject against a
regex that covers the conventional-commit shapes we use:
    feat(<scope>): embed ...
    feat(<scope>): promote ...
    feat(<scope>): skill-enforced ...
    chore(<scope>): promote ...  (and 'chore' variants of the above)

Usage:
  lifecycle_check.py                # last 30 days
  lifecycle_check.py --days 60      # custom window
  lifecycle_check.py --json
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

HERE = Path(__file__).resolve().parent
SCAN_SCRIPT = HERE / "scan_violations.py"

CONVENTIONAL_PREFIX = re.compile(
    r"^(?:feat|chore|fix|distill)\(([^)]*)\):\s+",
    re.IGNORECASE,
)
PROMOTION_VERB = re.compile(
    # Match both stem (hook-enforce, skill-enforce) and past-tense
    # (hook-enforced, skill-enforced) verb forms; the prior pattern
    # missed `hook-enforced` entirely, silently dropping every
    # past-tense promotion commit from lifecycle measurement.
    r"\b(embed|promote|skill-enforce[d]?|hook-enforce[d]?)\b",
    re.IGNORECASE,
)
RULE_NAME = re.compile(r"\b([a-z][a-z0-9-]+(?:-[a-z0-9]+){1,})\b")
COMMON_WORDS = {
    # Both the stem and past-tense forms are common-word noise — the
    # rule-name extractor must drop both so the verb doesn't leak as
    # the rule name being measured.
    "skill-enforce", "skill-enforced",
    "hook-enforce", "hook-enforced",
    "audit-rules", "verify-effectiveness",
    "diagnose-before-fix", "verify-before-assuming", "check-before-change",
}

# Scanner detector names — kebab-case identifiers that scan_violations.py
# emits via tracker.record(). The lifecycle check measures rate change
# against these. Kept in sync with V1-V8 in scan_violations.py.
SCANNER_DETECTOR_NAMES = {
    "encoding-missing-open",
    "git-commit-no-branch-check",
    "inline-python-c",
    "missing-stdout-reconfigure",
    "str-replace-crlf-risk",
    "websearch-webfetch-used",
    "curl-verbose-with-auth",
    "pip-install-upgrade-all",
}


def _real_rule_names():
    """Build positive allowlist of rule names from disk.

    Returns the union of:
      - basenames of rules/*.md (canonical rule files), without .md
      - scanner detector names (the strings the lifecycle script can actually
        measure rate change for)

    Without this allowlist, the kebab-case extractor picks up any hyphenated
    token in commit bodies — "snapshot-aware", "high-rate", "no-merges" —
    and treats them as rule names, producing INCONCLUSIVE verdicts on every
    promotion. (2026-05-26 audit-rules run surfaced this as silent inert
    feedback loop.)
    """
    names = set(SCANNER_DETECTOR_NAMES)
    try:
        rules_dir = Path(__file__).resolve().parents[3] / "rules"
        if rules_dir.is_dir():
            for f in rules_dir.glob("*.md"):
                names.add(f.stem)
    except Exception:
        # If we can't enumerate the rules dir, fall back to scanner names
        # only — the script still runs, but the allowlist is narrower.
        pass
    return names


REAL_RULE_NAMES = _real_rule_names()


def _is_promotion(subject):
    """Return (matches, body_without_scope) so callers can search the body
    for rule names without picking up the conventional-commit scope."""
    m = CONVENTIONAL_PREFIX.match(subject)
    if not m:
        return False, subject
    body = subject[m.end():]
    return bool(PROMOTION_VERB.search(body)), body


# Back-compat alias for tests that imported the original name.
PROMOTION_SUBJECT = re.compile(
    CONVENTIONAL_PREFIX.pattern + r".*?" + PROMOTION_VERB.pattern,
    re.IGNORECASE,
)


def git_log_promotions(days, repo_root):
    """Return [(date, short_sha, subject, candidate_rule_names)] from git log."""
    cmd = [
        "git", "-C", str(repo_root), "log",
        f"--since={days} days ago",
        "--pretty=format:%ci|%h|%s",
        "--no-merges",
    ]
    try:
        out = subprocess.check_output(cmd, encoding="utf-8", errors="replace")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"ERROR: git log failed ({e})", file=sys.stderr)
        return []
    entries = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        iso_date, sha, subject = parts
        matched, body = _is_promotion(subject)
        if not matched:
            continue
        # Date arrives as "YYYY-MM-DD HH:MM:SS +ZZZZ"; we want the day.
        try:
            commit_dt = datetime.strptime(iso_date.split()[0], "%Y-%m-%d")
        except ValueError:
            continue
        # Search the post-scope body only, so we don't pick up `bulk-api-script`
        # (the scope) instead of `str-replace-crlf-risk` (the rule).
        # Allowlist against real rule names + scanner detector names — without
        # this, hyphenated noise tokens ("snapshot-aware", "high-rate") leak
        # through and produce INCONCLUSIVE verdicts on every promotion.
        candidates = [
            name for name in RULE_NAME.findall(body)
            if name not in COMMON_WORDS
            and "-" in name
            and name in REAL_RULE_NAMES
        ]
        entries.append((commit_dt, sha, subject.strip(), candidates))
    return entries


def scan_window(since_dt, before_dt, rule_name):
    """Invoke scan_violations.py for a window, return session_rate_pct or None."""
    args = [
        sys.executable, str(SCAN_SCRIPT),
        "--since", since_dt.strftime("%Y-%m-%d"),
        "--before", before_dt.strftime("%Y-%m-%d"),
        "--rule", rule_name,
        "--json",
    ]
    try:
        # Suppress scanner stderr in --json mode so error chatter from the
        # scan (e.g., "no transcript dirs") doesn't bleed past our wrapper
        # and confuse JSON-parsing callers.
        out = subprocess.check_output(args, encoding="utf-8",
                                       stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        return None, f"scanner failed: {e}"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None, "scanner output not JSON"
    sessions = data.get("sessions_scanned", 0)
    if sessions == 0:
        return None, "no sessions in window"
    entry = data.get("violations", {}).get(rule_name)
    if not entry:
        return 0.0, None
    return float(entry.get("session_rate_pct", 0.0)), None


def assess(pre_rate, post_rate):
    """Return ('OK', 'INEFFECTIVE', 'INCONCLUSIVE')."""
    if pre_rate is None or post_rate is None:
        return "INCONCLUSIVE"
    if pre_rate <= 0:
        return "INCONCLUSIVE"
    drop = (pre_rate - post_rate) / pre_rate
    if drop >= 0.30:
        return "OK"
    return "INEFFECTIVE"


def main():
    parser = argparse.ArgumentParser(description="Post-promotion lifecycle check")
    parser.add_argument("--days", type=int, default=30, help="Window for git log")
    parser.add_argument("--window", type=int, default=14, help="Pre/post compare window (days)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    promos = git_log_promotions(args.days, repo_root)

    if not promos:
        msg = f"No promotion commits in last {args.days} days."
        if args.json:
            print(json.dumps({"promotions": [], "message": msg}))
        else:
            print(msg)
        return

    results = []
    for commit_dt, sha, subject, candidates in promos:
        rule = candidates[0] if candidates else None
        if not rule:
            results.append({
                "sha": sha, "date": commit_dt.date().isoformat(),
                "subject": subject, "rule": None,
                "verdict": "SKIP (no rule name inferred)",
            })
            continue
        pre_since = commit_dt - timedelta(days=args.window)
        post_before = commit_dt + timedelta(days=args.window)
        pre_rate, pre_err = scan_window(pre_since, commit_dt, rule)
        post_rate, post_err = scan_window(commit_dt, post_before, rule)
        verdict = assess(pre_rate, post_rate)
        results.append({
            "sha": sha,
            "date": commit_dt.date().isoformat(),
            "subject": subject,
            "rule": rule,
            "pre_rate_pct": pre_rate,
            "post_rate_pct": post_rate,
            "pre_error": pre_err,
            "post_error": post_err,
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps({"promotions": results}, indent=2))
        return

    print(f"Promotion commits in last {args.days} days: {len(results)}")
    print(f"\n{'Date':<12s} {'SHA':<10s} {'Rule':<35s} {'Pre%':>6s} {'Post%':>6s}  Verdict")
    print("-" * 88)
    for r in results:
        pre = f"{r['pre_rate_pct']:.1f}" if r.get("pre_rate_pct") is not None else "—"
        post = f"{r['post_rate_pct']:.1f}" if r.get("post_rate_pct") is not None else "—"
        rule = r.get("rule") or "(?)"
        print(f"{r['date']:<12s} {r['sha']:<10s} {rule:<35s} {pre:>6s} {post:>6s}  {r['verdict']}")


if __name__ == "__main__":
    main()
