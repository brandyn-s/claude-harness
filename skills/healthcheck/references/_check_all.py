#!/usr/bin/env python3
"""Orchestrator — run every healthcheck check, auto-stamp staleness, print the matrix.

Runs Check 0 first; if it WARNs (stale checkout) EVERY downstream row is
auto-stamped `[POSSIBLY STALE]` and a banner is prepended — so stamping is
mechanical, not model-dependent (the SKILL.md previously relied on the model
remembering to stamp each row). When stale, drift/manifest FAILs are
re-labelled WIP-FAIL (they usually clear after `git pull --ff-only` +
committing local WIP) instead of dragging the verdict to a hard UNHEALTHY.

Helpers are resolved RELATIVE TO THIS FILE (so the orchestrator and its sibling
_check_*.py run as a set whether invoked from ~/.claude or a worktree); they
internally inspect the live ~/.claude data.

The hook-test pytest (Check 1) is the long pole — it runs as a BACKGROUND
subprocess while checks 1b-11 execute, with a 30s heartbeat to stderr, and
uses pytest-xdist (`-n auto --dist loadfile`) when importable. The Hooks row
reports measured elapsed seconds so the SKILL.md runtime claims stay honest.

Usage:  python3 _check_all.py [--no-hooks] [--exit-zero]
  --no-hooks   skip Check 1 pytest (the long pole); everything else <1 min.
  --exit-zero  always exit 0 once the report prints (for background/cron
               callers where a nonzero exit reads as "tool crashed" rather
               than "verdict: unhealthy"). The verdict line still prints.

Exit 0 = HEALTHY, 1 = HEALTHY-with-warnings, 2 = UNHEALTHY (real FAIL).
Progress prints to stderr; the result matrix prints to stdout.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime

REF = os.path.dirname(os.path.abspath(__file__))   # this skill's references/ dir
H = os.path.expanduser("~/.claude")
HOME = os.path.expanduser("~")
AUDIT = f"{H}/skills/audit-architecture/references/doc_accuracy_audit.py"
SCRIPTS = f"{H}/scripts"
PROJ = os.environ.get("CLAUDE_PROJECT_ID", "")

# Repo-state-vs-docs/contract gate tests: these assert that the COMMITTED TREE
# is self-consistent (ARCHITECTURE.md matches settings.json, the model-runtime
# contract matches resolution, the local candidate qualifies for release) — not
# that any hook BEHAVES wrongly. On a stale/diverged checkout with in-flight
# WIP they fail by construction, so under staleness they are labeled (WIP)
# instead of driving a hard UNHEALTHY. 2026-08-22: all 4 real failures on a
# WIP tree were this shape, but the old pattern matched only 2 of them.
DRIFT_TEST_RE = re.compile(
    r"architecture_drift|drift_check|release_qualification|architecture_does_not_claim",
    re.IGNORECASE)

# Hard cap on the background pytest. The serial suite measured ~840s on
# 2026-08-22 (1,528 tests); the old 900s cap left almost no headroom.
HOOK_PYTEST_TIMEOUT = 1800


def is_wip_failure(test_id):
    """True if a failing pytest node id is a repo-consistency (drift-gate) test."""
    return bool(DRIFT_TEST_RE.search(test_id))


# pytest-xdist was MEASURED and REJECTED for this suite (2026-08-22 A/B):
# `-n auto --dist loadfile` gave 805s vs ~840s serial (~4%, bounded by the
# largest test file; sys-time dominated) AND manufactured a new failure
# (test_session_end receipt test — cross-worker shared-path interference).
# Do not re-add without a fresh A/B whose failure set matches serial exactly.


def _memory_md_path():
    """Best-effort path to the auto-memory MEMORY.md the doc-accuracy audit reads."""
    if PROJ:
        p = f"{H}/projects/{PROJ}/memory/MEMORY.md"
        if os.path.exists(p):
            return p
    try:
        import glob
        cands = glob.glob(f"{H}/projects/*/memory/MEMORY.md")
        return max(cands, key=os.path.getmtime) if cands else None
    except OSError:
        return None


def mtime_hms(path):
    """HH:MM:SS mtime stamp, or None. Stamped beside results whose input is a
    live-mutable file, so a later reader can tell 'state changed since the
    check ran' from 'checker disagreement' (2026-08-22: a concurrent session
    edited MEMORY.md mid-run; 6 reported issues were gone 30 min later)."""
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%H:%M:%S")
    except (OSError, TypeError):
        return None


def run(cmd, timeout=240, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:  # noqa: BLE001 - orchestrator must never crash mid-run
        return -1, "", str(e)


def first_line(s, default=""):
    for ln in s.splitlines():
        if ln.strip():
            return ln.strip()
    return default


def strip_prefix(line):
    """Drop a leading 'Label: ' and a leading 'PASS/WARN/FAIL — ' a helper prints,
    so the orchestrator's own status column isn't duplicated."""
    line = re.sub(r"^[A-Za-z][\w +\-/]*:\s*", "", line, count=1)
    line = re.sub(r"^(PASS|WARN|FAIL)\s*[—-]+\s*", "", line)
    return line.strip()


def cap(out):
    return strip_prefix(first_line(out))


def progress(msg):
    print(msg, file=sys.stderr, flush=True)


# --- inline check: local-only hooks (Check 5d, augments the Paths row) ----
# Config (Check 2) and Targets (Check 8) live in their own helpers
# (_check_config.py / _check_targets.py) and are subprocessed in main() like
# every other check, keeping this orchestrator a thin dispatcher.

def check_local_only_hooks():
    def cmds(path):
        out = set()
        if not os.path.exists(path):
            return out
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return out
        for regs in d.get("hooks", {}).values():
            if isinstance(regs, list):
                for reg in regs:
                    for h in reg.get("hooks", []):
                        command = h.get("command", "")
                        args = h.get("args", [])
                        arg_text = (
                            [arg for arg in args if isinstance(arg, str)]
                            if isinstance(args, list) else []
                        )
                        text = " ".join([
                            command if isinstance(command, str) else "",
                            *arg_text,
                        ])
                        for m in re.findall(r"[\w./-]+\.py", text):
                            out.add(os.path.basename(m))
        return out
    main = cmds(f"{H}/settings.json")
    local = cmds(f"{H}/settings.local.json")
    return sorted(local - main)


def check_drift_and_memory():
    """Run doc_accuracy_audit once → derive Check 6 (drift) and Check 4 (memory)."""
    _, out, _ = run(["python3", AUDIT], timeout=120)
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return ("WARN", "could not run doc-accuracy scanner"), ("WARN", "could not run scanner")
    drift_issues = (
        data.get("architecture_md", {}).get("issues", 0)
        + data.get("claude_md", {}).get("issues", 0)
        + data.get("orphan_hooks", {}).get("issues", 0)
    )
    drift = ("PASS", "counts match, no phantoms") if not drift_issues \
        else ("WARN", f"{drift_issues} doc-accuracy issue(s)")
    mem = data.get("memory_md", {})
    mi = mem.get("issues", 0)
    memory = ("PASS", f"{mem.get('links', '?')} links resolve, {mem.get('lines', '?')} lines") \
        if not mi else ("WARN", f"{mi} issue(s)")
    return drift, memory


def parse_pytest(out):
    mf = re.search(r"(\d+) failed", out)
    mp = re.search(r"(\d+) passed", out)
    failed = int(mf[1]) if mf else 0
    passed = int(mp[1]) if mp else 0
    fails = [ln.split()[1] for ln in out.splitlines()
             if ln.startswith("FAILED ") and len(ln.split()) > 1]
    return passed, failed, fails


def main():
    no_hooks = "--no-hooks" in sys.argv
    exit_zero = "--exit-zero" in sys.argv
    results = []  # (label, status, msg)
    wip_fail = []  # FAILs that are drift/manifest WIP-type (only down-weighted when stale)

    progress("[0/11] freshness…")
    rc, out, _ = run(["python3", f"{REF}/_check_freshness.py"])
    stale = rc == 1
    results.append(("Freshness", "PASS" if rc == 0 else "WARN",
                    strip_prefix(first_line(out, "freshness indeterminate"))))

    # Check 1 pytest is the long pole (measured 840s serial / far less under
    # xdist on 2026-08-22) — start it in the BACKGROUND and run checks 1b-11
    # while it works; join with a heartbeat after Check 11.
    hooks_proc = None
    hooks_log = None
    hooks_start = 0.0
    if not no_hooks:
        progress("[1/11] hook tests → background; checks 2-11 run meanwhile…")
        hooks_log = tempfile.NamedTemporaryFile(
            mode="w+", suffix=".pytest.log", delete=False, encoding="utf-8")
        hooks_start = time.monotonic()
        try:
            hooks_proc = subprocess.Popen(
                [sys.executable, "-m", "pytest", "test-hooks/", "--tb=line", "-q"],
                cwd=f"{H}/hooks", stdout=hooks_log, stderr=subprocess.STDOUT, text=True)
        except OSError as e:
            results.append(("Hooks", "WARN", f"could not start pytest: {e}"))
    else:
        results.append(("Hooks", "WARN", "skipped (--no-hooks)"))

    progress("[1b] hook coverage + error handling…")
    rc, out, _ = run(["python3", f"{REF}/_check_hooks_aux.py"])
    results.append(("Hook-aux", "PASS" if rc == 0 else "WARN", cap(out)))

    progress("[2/11] config…")
    rc, out, _ = run(["python3", f"{REF}/_check_config.py"])
    results.append(("Config", "PASS" if rc == 0 else "FAIL", cap(out)))

    progress("[3/11] skills…")
    rc, out, _ = run(["python3", f"{REF}/_check_skills.py"])
    results.append(("Skills", {0: "PASS", 1: "WARN"}.get(rc, "FAIL"), cap(out)))

    progress("[4+6] memory + drift (doc-accuracy)…")
    drift, memory = check_drift_and_memory()
    # MEMORY.md is live-mutable by concurrent sessions — stamp the input mtime
    # so a later reader can tell "state moved" from "checker disagreement".
    ts = mtime_hms(_memory_md_path())
    if ts:
        memory = (memory[0], f"{memory[1]} [MEMORY.md mtime {ts}]")
    results.append(("Memory", *memory))

    progress("[5/11] paths…")
    rc, out, _ = run(["python3", f"{REF}/check_paths.py"])
    msg = cap(out)
    lo = check_local_only_hooks()
    if lo:
        msg += f"; {len(lo)} local-only hook(s) (#50243): {', '.join(lo)}"
    results.append(("Paths", "PASS" if rc == 0 else "FAIL", msg))

    results.append(("Drift", *drift))

    progress("[7/11] routing…")
    rc, out, _ = run(["python3", f"{REF}/_check_routing.py"])
    results.append(("Routing", "PASS" if rc == 0 else "WARN", cap(out)))

    progress("[8/11] targets…")
    rc, out, _ = run(["python3", f"{REF}/_check_targets.py"])
    results.append(("Targets", "PASS" if rc == 0 else "WARN", cap(out)))

    progress("[9/11] orphans…")
    rc, out, _ = run(["python3", f"{REF}/_check_orphans.py"])
    results.append(("Orphans", "PASS" if rc == 0 else "WARN", cap(out)))

    progress("[10/11] manifest…")
    rc, out, _ = run(["python3", f"{REF}/_check_manifest.py"])
    m_status = {0: "PASS", 1: "WARN"}.get(rc, "FAIL")
    results.append(("Manifest", m_status, cap(out)))
    if m_status == "FAIL" and stale:
        wip_fail.append("Manifest")

    progress("[11/11] indexes…")
    rc, out, _ = run(["python3", f"{SCRIPTS}/verify-indexes.py"])
    results.append(("Indexes", "PASS" if rc == 0 else "FAIL", cap(out)))

    # ---- join the background pytest (heartbeat every 30s) -------------------
    if hooks_proc is not None and hooks_log is not None:
        while True:
            try:
                hooks_proc.wait(timeout=30)
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.monotonic() - hooks_start)
                if elapsed >= HOOK_PYTEST_TIMEOUT:
                    hooks_proc.kill()
                    hooks_proc.wait()
                    break
                progress(f"  … hook tests still running ({elapsed}s elapsed)")
        elapsed = int(time.monotonic() - hooks_start)
        hooks_log.flush()
        hooks_log.seek(0)
        pyout = hooks_log.read()
        hooks_log.close()
        passed, failed, fails = parse_pytest(pyout)
        # KEEP the log whenever it carries diagnostic value, and DELETE it only
        # on a clean pass. It used to be unlinked unconditionally while the row
        # showed only the first 4 failures with no count — so enumerating a
        # 14-failure run required re-running the whole ~7min suite from scratch
        # (measured 2026-08-30). The log is the cheap artifact; the suite is not.
        keep_log = failed > 0 or (passed == 0 and failed == 0)
        if not keep_log:
            try:
                os.unlink(hooks_log.name)
            except OSError:
                pass
        if passed == 0 and failed == 0:
            row = ("Hooks", "WARN",
                   f"pytest did not run / collected 0 tests ({elapsed}s); "
                   f"log: {hooks_log.name}")
        elif failed == 0:
            row = ("Hooks", "PASS", f"{passed} tests passed in {elapsed}s")
        else:
            only_drift = bool(fails) and all(is_wip_failure(f) for f in fails)
            shown = fails[:4]
            more = len(fails) - len(shown)
            listed = ", ".join(shown)
            if more > 0:
                # Say the list is partial. A silently truncated list reads as
                # complete, which is how a 14-failure run got triaged as 4.
                listed += f", +{more} more (see log)"
            msg = f"{passed} passed, {failed} failed in {elapsed}s: {listed}"
            if only_drift:
                msg += " (drift gate — clears after committing local WIP / reconcile)"
                wip_fail.append("Hooks")
            msg += f"\n           full pytest log: {hooks_log.name}"
            row = ("Hooks", "FAIL", msg)
        results.insert(1, row)  # display position: right after Freshness

    # ---- verdict -----------------------------------------------------------
    fails = [lbl for lbl, st, _ in results if st == "FAIL"]
    warns = [lbl for lbl, st, _ in results if st == "WARN"]
    real_fails = [f for f in fails if not (stale and f in wip_fail)]

    stamp = " [POSSIBLY STALE]" if stale else ""
    print(f"=== Architecture Health Check ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
    if stale:
        fr = next(m for lbl, _, m in results if lbl == "Freshness")
        print(f"⚠ STALE CHECKOUT — {fr}.")
        print("   All findings below may reflect stale state; FAILs tagged "
              "(WIP) usually clear after reconciling with origin/main + "
              "committing local WIP (see Check 0's recovery lines).\n")
    width = max(len(lbl) for lbl, _, _ in results)
    for lbl, st, msg in results:
        tag = stamp if lbl != "Freshness" else ""
        wip = " (WIP)" if (stale and lbl in wip_fail) else ""
        print(f"{lbl:<{width}}  {st}{wip}{tag} — {msg}")

    print()
    if real_fails:
        print(f"Overall: UNHEALTHY — {len(real_fails)} check(s) failed: {', '.join(real_fails)}")
        code = 2
    elif fails and stale:
        print("Overall: HEALTHY-with-warnings (the only FAIL is WIP/stale — "
              "reconcile to main + re-run to confirm)")
        code = 1
    elif warns:
        print(f"Overall: HEALTHY (with warnings) — {len(warns)} warning(s)")
        code = 1
    else:
        print("Overall: HEALTHY")
        code = 0
    return 0 if exit_zero else code


if __name__ == "__main__":
    sys.exit(main())
