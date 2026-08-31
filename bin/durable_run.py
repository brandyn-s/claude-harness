#!/usr/bin/env python3
"""durable_run — a shared library for DURABLE, SELF-HEALING, LOUD-ERROR long-running operations.

WHY THIS EXISTS
  Across this codebase ~100 scripts re-implement pieces of "run a long job that survives crashes" by hand —
  each subtly wrong. The 2026-06-22/23 Phase-F batch arc alone hit FOUR distinct failures, every one a facet of
  doing this by hand: (1) a crash at 48% restarted from zero (no checkpoint); (2) a self-healing driver wrote a
  false success marker on a FAILED job (terminal != success); (3) a fixed resource name collided with a prior
  failed attempt and a retry loop burned attempts on a DETERMINISTIC error; (4) a monitor false-alarmed on an
  orphaned resource via a fuzzy name match. Plus the recurring silent-error classes: `except: return None`
  swallowing an auth-expiry into false-negatives, and a bare `json.loads(subprocess.stdout)` crashing opaquely
  on an empty transient response.

  This module makes the CORRECT behavior the DEFAULT — imported, not re-typed:
    DURABLE      — Checkpoint(): cursor persisted per unit of work; resume skips completed work.
    SELF-HEALING — heal(): retry ONLY transient errors (classified), with backoff; deterministic errors fail
                   loud immediately (retrying them never clears). Success markers gate on VERIFIED success.
    LOUD ERRORS  — fail_loud()/DurableError: every failure is a STRUCTURED record (operation, location, exact
                   exception, transient|deterministic class, action taken, resume cursor) written to a .errors
                   log AND stderr. No silent failures, no swallowed exceptions, no bare json.loads. Diagnosis
                   becomes a READ, not a guess.

  Design requirements are the 6 distilled in the Phase-F flaw log / task #6:
    (1) checkpoint/resume  (2) is_transient classifier  (3) success-gated markers
    (4) collision-proof names (unique_name)  (5) monitor-by-exact-id (caller passes the arn)
    (6) loud/explicit/detailed structured errors — no silent failure anywhere.

USAGE (sketch)
    from durable_run import Checkpoint, heal, run_json, success_marker, unique_name, ErrorLog

    errlog = ErrorLog(workdir / "run.errors.jsonl")
    ckpt = Checkpoint(workdir / "progress.json")                 # durable cursor
    for i in range(ckpt.cursor(), n_batches):                    # resume from last checkpoint
        rows = heal(lambda: run_json([...aws cli...]),           # self-heal transients; loud on deterministic
                    stage="pull", item=f"batch{i}", errlog=errlog, cursor=i)
        ...process...
        ckpt.advance(i + 1, extra={"recno": recno})              # checkpoint AFTER each unit
    name = unique_name("phasef-job", attempt=ckpt.get("attempt", 0) + 1)   # collision-proof resource name
    success_marker(workdir / "run.DONE", verified=lambda: all_chunks_completed())  # gated on REAL success

Dependency-free (stdlib only) so any instrument can import it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

__all__ = ["DurableError", "classify", "is_transient", "fail_loud", "heal", "Checkpoint",
           "run_json", "run_text", "success_marker", "unique_name", "ErrorLog",
           "InstrumentUnsound", "assert_instrument_sound"]

# ─────────────────────────── error classification ───────────────────────────
# TRANSIENT = the world hiccuped and will recover on retry (network, throttle, 5xx, empty response, timeout).
# DETERMINISTIC = re-running the SAME call changes nothing (validation, auth-conflict, not-found, parse error).
# AUTH-EXPIRY = deterministic-UNTIL an out-of-band action (re-login); retry is futile AND a silent swallow turns
#               every subsequent call into a false-negative — so it fails LOUD and is never retried.
_TRANSIENT_MARKERS = (
    "connection was closed", "could not connect", "connection reset", "connection aborted",
    "timed out", "timeout", "throttl", "rate exceeded", "too many requests", "slow down", "slowdown",
    "503", "502", "500", "504", "529", "service unavailable", "internalfailure", "internalservererror",
    "temporarily unavailable", "endpointconnectionerror", "read timed out", "empty response", "try again",
)
_AUTH_EXPIRY_MARKERS = (
    "expiredtoken", "tokenretrievalerror", "the security token included in the request is invalid",
    "expired", "sso session", "getsessiontoken", "credential", "unauthorized",
)
_DETERMINISTIC_MARKERS = (
    "conflictexception", "validationexception", "accessdenied", "access denied", "not authorized",
    "resourcenotfound", "no such", "does not exist", "invalid", "400", "404", "409",
    "could not validate", "jsondecodeerror", "expecting value", "schema",
)


def classify(exc: BaseException) -> str:
    """'transient' | 'auth-expiry' | 'deterministic'. Defaults to 'deterministic' (fail-fast) when unknown —
    a wrong 'transient' guess burns retries; a wrong 'deterministic' guess fails loud (the cheaper mistake)."""
    s = f"{type(exc).__name__}: {exc}".lower()
    # auth-expiry first: an expired token reads like 'unauthorized' but must NOT retry-loop AND must NOT swallow
    if "expired" in s and any(m in s for m in _AUTH_EXPIRY_MARKERS):
        return "auth-expiry"
    if any(m in s for m in _TRANSIENT_MARKERS):
        return "transient"
    if any(m in s for m in _DETERMINISTIC_MARKERS):
        return "deterministic"
    return "deterministic"


def is_transient(exc: BaseException) -> bool:
    return classify(exc) == "transient"


# ─────────────────────────── loud structured errors ───────────────────────────
class DurableError(Exception):
    """A failure carrying full diagnostic context so the cause is a READ, not a guess."""

    def __init__(self, stage, item, exc, klass, action):
        self.stage, self.item, self.exc, self.klass, self.action = stage, item, exc, klass, action
        super().__init__(f"[{stage}/{item}] {klass.upper()}: {type(exc).__name__}: {str(exc)[:300]} — {action}")


class ErrorLog:
    """Append-only structured error log. Each entry is one JSON object — greppable, not a prose blob."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, stage, item, exc, klass, action, cursor=None):
        rec = {
            "stage": stage, "item": str(item), "error_class": klass,
            "exc_type": type(exc).__name__, "exc_msg": str(exc)[:500],
            "action": action, "cursor": cursor,
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:],
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        return rec


def fail_loud(stage, item, exc, action="aborting", cursor=None, errlog: "ErrorLog | None" = None) -> DurableError:
    """Emit a LOUD, EXPLICIT, DETAILED error to stderr (+ the error log if given) and return a DurableError to
    raise. NEVER swallow — a failure must announce itself with everything needed to diagnose it on sight."""
    klass = classify(exc)
    de = DurableError(stage, item, exc, klass, action)
    banner = (f"\n{'=' * 78}\n"
              f"  DURABLE-RUN FAILURE  ·  stage={stage}  item={item}  class={klass.upper()}\n"
              f"  {type(exc).__name__}: {str(exc)[:400]}\n"
              f"  action: {action}" + (f"  ·  resume-cursor: {cursor}" if cursor is not None else "") + "\n"
              f"{'=' * 78}")
    print(banner, file=sys.stderr, flush=True)
    if errlog is not None:
        errlog.record(stage, item, exc, klass, action, cursor)
    return de


# ─────────────────────────── self-healing retry ───────────────────────────
def heal(fn, stage="op", item="-", max_tries=6, base_wait=4, errlog: "ErrorLog | None" = None, cursor=None):
    """Run fn(); retry ONLY transient errors (classified) with linear backoff. Deterministic/auth-expiry errors
    fail LOUD immediately — retrying them is futile and hides the real problem. Returns fn()'s result; raises
    DurableError on exhaustion or on a non-transient error.

    Fixes: (a) the name-collision that burned 8 retries on a deterministic ConflictException; (b) the auth-expiry
    a swallow-and-continue turned into silent false-negatives; (c) the bare json.loads that crashed opaquely."""
    last = None
    for attempt in range(1, max_tries + 1):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised loud; nothing is swallowed
            klass = classify(exc)
            last = exc
            if klass != "transient":
                raise fail_loud(stage, item, exc,
                                action=(f"{klass} error — NOT retried (retry is futile); fix required"
                                        + (" (re-auth out-of-band)" if klass == "auth-expiry" else "")),
                                cursor=cursor, errlog=errlog)
            wait = min(base_wait * attempt, 120)
            print(f"[heal:{stage}/{item}] transient attempt {attempt}/{max_tries}: "
                  f"{type(exc).__name__}: {str(exc)[:120]} — retry in {wait}s", file=sys.stderr, flush=True)
            if errlog is not None:
                errlog.record(stage, item, exc, "transient", f"retry {attempt}/{max_tries} in {wait}s", cursor)
            time.sleep(wait)
    raise fail_loud(stage, item, last or RuntimeError("unknown"),
                    action=f"exhausted {max_tries} transient retries", cursor=cursor, errlog=errlog)


# ─────────────────────────── durable checkpoint ───────────────────────────
class Checkpoint:
    """A persisted cursor for resumable work. Write the cursor AFTER each completed unit; on restart resume from
    cursor(). A crash/sleep costs at most the in-flight unit, never the whole run."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = {}
        if self.path.exists():
            try:
                self._state = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                # a corrupt checkpoint is LOUD, never silently ignored — a silent reset = redo-from-zero surprise
                print(f"[checkpoint] WARNING: {self.path} unreadable — treating as cursor 0 "
                      f"(prior run killed mid-write?)", file=sys.stderr, flush=True)

    def cursor(self) -> int:
        return int(self._state.get("cursor", 0))

    def get(self, key, default=None):
        return self._state.get(key, default)

    def advance(self, cursor: int, extra: "dict | None" = None):
        self._state["cursor"] = int(cursor)
        if extra:
            self._state.update(extra)
        # write to a temp sibling then atomic-replace, so a kill mid-write can't corrupt the live checkpoint
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state), encoding="utf-8")
        tmp.replace(self.path)


# ─────────────────────────── collision-proof resource names ───────────────────────────
def unique_name(base: str, attempt: int, chunk: "int | None" = None) -> str:
    """Build a collision-proof resource name. A FAILED prior attempt HOLDS its name, so a re-submit with the
    same name fails ConflictException forever — bump `attempt`. Format: base[-cNNN]-aNN (charset-safe: dashes
    + alphanum only, no underscores, since some services restrict the name charset)."""
    parts = [base]
    if chunk is not None:
        parts.append(f"c{chunk:03d}")
    parts.append(f"a{attempt:02d}")
    return "-".join(parts)


# ─────────────────────────── loud subprocess JSON (no bare json.loads) ───────────────────────────
def run_text(cmd, timeout=300) -> str:
    """Run a subprocess, return stdout. Raises a LOUD error on non-zero exit with the FULL stderr — never the
    silent '.stdout on a failed call' trap."""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"subprocess exit {p.returncode}: {(p.stderr or p.stdout)[:400]}")
    return p.stdout


def run_json(cmd, timeout=300):
    """Run a subprocess and parse stdout as JSON — LOUDLY. Empty stdout → 'empty response' (classify→transient,
    so heal() retries it); non-zero exit or non-empty-unparseable → deterministic (surfaced with the head of what
    we got). This is the fix for the bare `json.loads(subprocess.run(...).stdout)` that crashed opaquely on a
    transient empty response."""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        raise RuntimeError(f"subprocess exit {p.returncode}: {(p.stderr or '')[:300]}")  # → deterministic
    if not out:
        raise RuntimeError("empty response")  # → transient → heal() retries
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSONDecodeError (non-empty, unparseable): {str(e)[:80]} | head={out[:120]!r}")


# ─────────────────────────── success-gated completion marker ───────────────────────────
def success_marker(path: Path, verified, payload: str = "complete\n"):
    """Write a DONE marker ONLY if verified() is truthy. A .done marker is a VERIFIED-SUCCESS claim, never a
    'we stopped looping' claim. If verified() is falsy → write a .fail sibling + raise LOUD. Fixes the driver
    that wrote .DONE on a FAILED job and fetched zero."""
    path = Path(path)
    try:
        ok = bool(verified())
    except BaseException as exc:  # noqa: BLE001
        raise fail_loud("finalize", path.name, exc, action="success-verification raised — NOT writing .done")
    if not ok:
        fail = path.parent / (path.name + ".fail")
        fail.write_text("success verification FAILED — run did not complete successfully\n", encoding="utf-8")
        raise DurableError("finalize", path.name, RuntimeError("success verification returned falsy"),
                           "deterministic", f".fail written ({fail.name}); .done withheld")
    path.write_text(payload, encoding="utf-8")
    print(f"[durable] {path.name} written — VERIFIED success.", flush=True)


# ─────────────────────────── measurement-validity gate ───────────────────────────
class InstrumentUnsound(Exception):
    """An instrument failed its known-answer check — its measurements are NOT trustworthy until fixed."""


def assert_instrument_sound(measure, known_cases, *, label="instrument", errlog: "ErrorLog | None" = None):
    """Before trusting ANY measurement, prove the instrument returns the KNOWN answer on inputs whose answer you
    already know. Raises InstrumentUnsound (loud, detailed) if any known case fails — so a wrong-instrument
    number can NEVER be published as a finding.

    THE FAILURE THIS PREVENTS (2026-06-22 E2): a corroboration measurement returned 4.8% that LOOKED like a real
    precision number but was an instrument artifact (the harness fed the judge a 42-char excerpt, stripping the
    context the real measurement needs). The save was MANUAL — noticing a per-family pattern, then running the
    instrument on 5 known-positives (all flipped on the full input), proving the instrument, not the system, was
    wrong. This gate makes that known-positive check MANDATORY + automatic instead of a lucky catch.

    Args:
      measure: callable(case_input) -> measured_value. The instrument under test.
      known_cases: list of (input, expected) — inputs whose correct output you KNOW a priori (known-positives
                   AND known-negatives; include both — a detector that flags everything passes a positives-only
                   check). At least one of each is strongly recommended; a positives-only or negatives-only set
                   is accepted but WARNED (it can't catch the opposite failure mode).
      label: name for the instrument (in error messages).
      errlog: optional ErrorLog to record a failure.

    Returns: the list of (input, expected, got, ok) results on success (all ok). Raises InstrumentUnsound on any
    mismatch, naming every failing case — the loud, detailed signal that the instrument (not the data) is the
    problem, so you fix the instrument before measuring real targets."""
    if not known_cases:
        raise InstrumentUnsound(f"[{label}] no known_cases provided — cannot prove the instrument; refusing to "
                                f"certify it sound (a measurement with no known-answer check is unverified).")
    results, failures = [], []
    expecteds = {bool(e) if isinstance(e, bool) else e for (_, e) in known_cases}
    for i, (inp, expected) in enumerate(known_cases):
        try:
            got = measure(inp)
        except BaseException as exc:  # noqa: BLE001 — surfaced loud below
            got = exc
        ok = (not isinstance(got, BaseException)) and (got == expected)
        results.append((inp, expected, got, ok))
        if not ok:
            shown = f"{type(got).__name__}: {got}" if isinstance(got, BaseException) else repr(got)
            failures.append(f"  case[{i}]: expected={expected!r} got={shown[:120]}")
    # warn (don't fail) on a one-sided known set — it can't catch the opposite failure mode
    one_sided = len(expecteds) < 2
    if one_sided:
        print(f"[{label}] WARNING: known_cases are one-sided (all expected={expecteds}); this check can prove the "
              f"instrument handles that class but NOT the opposite (a flag-everything / flag-nothing instrument "
              f"would still pass). Add known cases of the other class.", file=sys.stderr, flush=True)
    if failures:
        msg = (f"[{label}] INSTRUMENT UNSOUND — {len(failures)}/{len(known_cases)} known cases failed; the "
               f"instrument does NOT return the known answer, so its measurements on REAL targets are NOT "
               f"trustworthy. Fix the instrument before measuring:\n" + "\n".join(failures))
        print(f"\n{'=' * 78}\n  {msg}\n{'=' * 78}", file=sys.stderr, flush=True)
        if errlog is not None:
            errlog.record(label, "known-answer-check", InstrumentUnsound(msg), "deterministic",
                          "instrument failed known cases — measurement withheld")
        raise InstrumentUnsound(msg)
    print(f"[{label}] instrument sound: {len(known_cases)}/{len(known_cases)} known cases pass"
          + (" (one-sided — see warning)" if one_sided else " (both classes covered)"), flush=True)
    return results


# ─────────────────────────── self-test (run directly) ───────────────────────────
def _self_test():
    import tempfile
    ok = True

    def check(cond, label):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}: {label}")
        ok = ok and cond

    # classification
    check(classify(RuntimeError("Connection was closed before we received a valid response")) == "transient", "transient: connection closed")
    check(classify(RuntimeError("ConflictException: name in use")) == "deterministic", "deterministic: conflict")
    check(classify(RuntimeError("ExpiredToken: token expired")) == "auth-expiry", "auth-expiry: expired token")
    check(classify(ValueError("Could not validate ListBucket permissions")) == "deterministic", "deterministic: validate")
    # heal: deterministic fails fast (1 try), transient retries then succeeds
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("timed out")  # transient
        return "ok"
    check(heal(flaky, stage="t", item="flaky", base_wait=0) == "ok" and calls["n"] == 3, "heal retries transient to success")
    det = {"n": 0}

    def deterministic():
        det["n"] += 1
        raise RuntimeError("ValidationException")
    try:
        heal(deterministic, stage="t", item="det", base_wait=0)
        check(False, "heal raises on deterministic")
    except DurableError:
        check(det["n"] == 1, "heal does NOT retry deterministic (1 call only)")
    # checkpoint resume
    with tempfile.TemporaryDirectory() as d:
        cp = Checkpoint(Path(d) / "p.json")
        check(cp.cursor() == 0, "fresh checkpoint cursor 0")
        cp.advance(5, {"recno": 100})
        cp2 = Checkpoint(Path(d) / "p.json")
        check(cp2.cursor() == 5 and cp2.get("recno") == 100, "checkpoint resumes cursor + extra")
        # success marker gating
        try:
            success_marker(Path(d) / "x.DONE", verified=lambda: False)
            check(False, "success_marker raises on falsy verify")
        except DurableError:
            check((Path(d) / "x.DONE.fail").exists() and not (Path(d) / "x.DONE").exists(),
                  "falsy verify → .fail written, .DONE withheld")
        success_marker(Path(d) / "y.DONE", verified=lambda: True)
        check((Path(d) / "y.DONE").exists(), "truthy verify → .DONE written")
    # unique_name
    check(unique_name("job", attempt=1, chunk=0) == "job-c000-a01", "unique_name format")
    check(unique_name("job", 2, 0) != unique_name("job", 1, 0), "unique_name differs per attempt")
    # assert_instrument_sound: a SOUND instrument (correct on both classes) passes
    sound = assert_instrument_sound(lambda x: x > 5, [(9, True), (2, False)], label="gt5")
    check(all(r[3] for r in sound), "sound instrument passes known-answer check")
    # an UNSOUND instrument (the E2 shape: returns False on a known-positive) raises InstrumentUnsound
    try:
        assert_instrument_sound(lambda x: False, [(9, True), (2, False)], label="broken")  # known-positive fails
        check(False, "unsound instrument raises")
    except InstrumentUnsound:
        check(True, "unsound instrument raises InstrumentUnsound (known-positive failed → measurement withheld)")
    # empty known_cases → refuses to certify
    try:
        assert_instrument_sound(lambda x: True, [], label="empty")
        check(False, "empty known_cases raises")
    except InstrumentUnsound:
        check(True, "empty known_cases → refuses to certify (no proof)")
    # an instrument that raises on a case is treated as a failure, not a crash
    try:
        assert_instrument_sound(lambda x: 1 / 0, [(1, True), (2, False)], label="raiser")
        check(False, "raising instrument raises InstrumentUnsound")
    except InstrumentUnsound:
        check(True, "instrument that raises mid-case → unsound, surfaced (not an uncaught crash)")
    print(f"\nself_test: {'ALL PASS' if ok else 'FAILURES ABOVE'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if _self_test() else 1)
