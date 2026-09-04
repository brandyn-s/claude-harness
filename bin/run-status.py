#!/usr/bin/env python3
"""run-status — a durable status surface for long-running background work.

WHY (2026-06-25 session self-audit): a 3-day / 12-compaction session logged
~30 "What is the status?" turns because background runs (oracle harnesses,
terraform applies, measurement jobs, deploy monitors) had no queryable status —
every check was a fresh poll the user had to drive. This gives every background
run a tiny, durable, single-file status surface so "status" is one file-read.

CONVENTION
  A run lives under  runs/<id>/  (repo-relative + gitignored, NOT /tmp — /tmp is
  purged at the macOS date rollover; durable runs need a durable path). The run
  writes ONE status.json and, on completion, a .done or .fail marker:

    runs/<id>/status.json   {id, phase, detail, pct, updated_ts, started_ts}
    runs/<id>/.done         (touched on success; body = final one-line summary)
    runs/<id>/.fail         (touched on failure; body = the failing reason)

  A monitor distinguishes COMPLETE / FAILED / RUNNING / STALE by FILE STATE,
  never by pid-liveness (a hung run keeps its pid; a finished run's pid is gone) —
  see worktree-by-default's durability-triad lesson.

USAGE (from a background run / monitor script)
  run-status.py start  <id> [--detail "..."] [--task-id T] [--log P] [--artifact P]
  run-status.py update <id> --phase P [--pct N] [--detail "..."]
  run-status.py done   <id> [--summary "..."] (--verify-cmd C | --verified-by S | --force)
  run-status.py fail   <id> [--reason "..."] [--exit-code N]

DURABLE RECEIPTS (2026-07-26 audit, Phase 1)
  `start` captures execution IDENTITY so a run is auditable after it ends:
  cwd, pid, git toplevel/branch/HEAD, and whether it ran in a worktree. It also
  records the task id and the log/artifact paths, i.e. WHERE the evidence lives.
  A background operation whose cwd/worktree is unrecoverable cannot be audited,
  which is what the audit found.

  `done` REFUSES to write `.done` without evidence. A `.done` marker is a
  VERIFIED-SUCCESS claim, never a "we stopped looping" claim -- the same
  summary-as-success defect the workflow journals exhibited (a run reported
  completed while its children produced nothing). Supply exactly one of:
    --verify-cmd "<cmd>"    run it now; nonzero exit writes .fail instead
    --verified-by "<what>"  explicit attestation, recorded in the receipt
    --force                 record success but mark it UNVERIFIED in the receipt
  This mirrors `durable_run.success_marker`, which already had the gate.

  `terminal_state` is written explicitly by done/fail and starts as null. A
  reader must never infer success from the absence of a failure marker.

USAGE (to read — the /status skill or a human)
  run-status.py show <id>            # one-line status of a run
  run-status.py list                 # every run under runs/, newest first, with state

Timestamps are passed via the OS clock here (a CLI, not a workflow script, so
Date.now-equivalent is allowed — unlike the workflow engine).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _runs_root() -> Path:
    # repo-relative by default; CLAUDE_RUNS_DIR overrides (tests, alt repos).
    return Path(os.environ.get("CLAUDE_RUNS_DIR", "runs"))


def _run_dir(run_id: str) -> Path:
    d = _runs_root() / run_id
    return d


def _status_path(run_id: str) -> Path:
    return _run_dir(run_id) / "status.json"


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _read_status(run_id: str) -> dict:
    p = _status_path(run_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(run_id: str, data: dict) -> None:
    d = _run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    # atomic-ish: write temp then replace, so a concurrent reader never sees a
    # half-written file.
    tmp = _status_path(run_id).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(_status_path(run_id))


def _state_of(run_id: str) -> str:
    d = _run_dir(run_id)
    if (d / ".fail").exists():
        return "FAILED"
    if (d / ".done").exists():
        return "DONE"
    st = _read_status(run_id)
    if not st:
        return "UNKNOWN"
    # STALE: status.json hasn't advanced in > stale_after (default 15 min) and no
    # marker — the run may be wedged. The reader decides; we just label.
    age = _now() - st.get("updated_ts", 0)
    return "STALE" if age > float(os.environ.get("CLAUDE_RUN_STALE_SEC", "900")) else "RUNNING"


def _identity() -> dict:
    """Capture WHERE a run executed.

    A status line without execution identity cannot be audited after the fact: the
    2026-07-26 audit found background operations whose cwd/worktree was unrecoverable,
    so "did this run touch the right tree?" was unanswerable. Recorded at start
    because a later cwd change (or a removed worktree) destroys the evidence.
    """
    cwd = os.getcwd()
    ident = {"cwd": cwd, "pid": os.getpid()}
    # Resolve the git worktree/branch/HEAD without shelling out on every update.
    try:
        import subprocess

        def g(*args):
            p = subprocess.run(
                ["git", "-C", cwd, *args], capture_output=True, check=False, timeout=15
            )
            if p.returncode != 0:
                return None
            return p.stdout.decode("utf-8", "replace").strip()

        ident["git_toplevel"] = g("rev-parse", "--show-toplevel")
        ident["git_branch"] = g("rev-parse", "--abbrev-ref", "HEAD")
        ident["git_head"] = g("rev-parse", "HEAD")
        # A worktree's common dir differs from its git dir; that distinction is what
        # tells you a run executed in an isolated worktree rather than the main tree.
        gitdir = g("rev-parse", "--absolute-git-dir")
        common = g("rev-parse", "--path-format=absolute", "--git-common-dir")
        ident["is_worktree"] = bool(gitdir and common and gitdir != common)
    except Exception:  # noqa: S110, BLE001 -- fail-open: identity capture must never fail a run
        # Identity capture must never fail a run.
        pass
    return ident


def cmd_start(a) -> int:
    now = _now()
    st = {
        "id": a.id, "phase": a.phase or "start", "detail": a.detail or "",
        "pct": a.pct, "started_ts": now, "updated_ts": now,
        "started_iso": _iso(now), "updated_iso": _iso(now),
        # --- receipt fields (2026-07-26 audit, Phase 1) ---
        "identity": _identity(),
        "task_id": getattr(a, "task_id", None),
        "log_path": getattr(a, "log", None),
        "artifact_path": getattr(a, "artifact", None),
        # Terminal truth starts UNKNOWN and is only ever set by done/fail. A reader
        # must never infer success from the absence of a failure.
        "terminal_state": None,
        "exit_code": None,
        "verifier": None,
    }
    _write_status(a.id, st)
    print(f"started run {a.id}")
    return 0


def cmd_update(a) -> int:
    st = _read_status(a.id)
    if not st:
        # update on a never-started run: create it (forgiving — a monitor may
        # update before an explicit start).
        st = {"id": a.id, "started_ts": _now(), "started_iso": _iso(_now())}
    now = _now()
    if a.phase is not None:
        st["phase"] = a.phase
    if a.detail is not None:
        st["detail"] = a.detail
    if a.pct is not None:
        st["pct"] = a.pct
    st["updated_ts"] = now
    st["updated_iso"] = _iso(now)
    _write_status(a.id, st)
    print(f"updated run {a.id}: phase={st.get('phase')} pct={st.get('pct')}")
    return 0


def _finalize(
    run_id: str,
    marker: str,
    body: str,
    *,
    exit_code=None,
    verifier=None,
) -> None:
    st = _read_status(run_id)
    now = _now()
    st.setdefault("id", run_id)
    st["phase"] = "done" if marker == ".done" else "failed"
    st["final"] = body
    st["updated_ts"] = now
    st["updated_iso"] = _iso(now)
    # Terminal truth is recorded explicitly, never inferred by a reader.
    st["terminal_state"] = "completed_success" if marker == ".done" else "failed"
    st["exit_code"] = exit_code
    st["verifier"] = verifier
    st["finished_ts"] = now
    st["finished_iso"] = _iso(now)
    _write_status(run_id, st)
    (_run_dir(run_id) / marker).write_text((body or "") + "\n", encoding="utf-8")


def cmd_done(a) -> int:
    """Mark a run successful -- but ONLY with a verification receipt.

    A `.done` marker is a VERIFIED-SUCCESS claim, never a "we stopped looping"
    claim. This mirrors `durable_run.success_marker`, which already refuses to
    write `.done` on a falsy verification; before 2026-07-26 this CLI had no such
    gate, so any caller could assert success with no evidence -- the same
    summary-as-success defect the workflow journals exhibited.

    Provide evidence one of two ways:
      --verified-by "<what proved it>"   an explicit human/tool attestation
      --verify-cmd "<shell command>"     run it now; nonzero exit => .fail
    `--force` records success with an explicit unverified marker, so the absence
    of evidence is visible in the receipt rather than silent.
    """
    verify_cmd = getattr(a, "verify_cmd", None)
    verified_by = getattr(a, "verified_by", None)
    force = getattr(a, "force", False)

    if verify_cmd:
        import subprocess

        proc = subprocess.run(verify_cmd, shell=True, capture_output=True, check=False)
        rc = proc.returncode
        tail = proc.stdout.decode("utf-8", "replace").strip().splitlines()[-5:]
        verifier = {
            "kind": "command",
            "command": verify_cmd,
            "exit_code": rc,
            "output_tail": tail,
            "passed": rc == 0,
        }
        if rc != 0:
            _finalize(
                a.id,
                ".fail",
                f"verification FAILED (rc={rc}): {verify_cmd}",
                exit_code=rc,
                verifier=verifier,
            )
            print(f"run {a.id} FAILED — verification command exited {rc}; .done withheld")
            return 1
        _finalize(
            a.id, ".done", a.summary or "completed", exit_code=0, verifier=verifier
        )
        print(f"run {a.id} DONE (verified by command)")
        return 0

    if verified_by:
        verifier = {"kind": "attestation", "detail": verified_by, "passed": True}
        _finalize(a.id, ".done", a.summary or "completed", verifier=verifier)
        print(f"run {a.id} DONE (verified: {verified_by})")
        return 0

    if force:
        verifier = {"kind": "unverified", "detail": "--force", "passed": None}
        _finalize(a.id, ".done", a.summary or "completed", verifier=verifier)
        print(f"run {a.id} DONE (UNVERIFIED — recorded via --force)")
        return 0

    print(
        f"refusing to mark run {a.id} DONE without evidence.\n"
        "  supply --verify-cmd '<cmd>' or --verified-by '<what proved it>',\n"
        "  or --force to record an explicitly unverified success.",
        file=sys.stderr,
    )
    return 2


def cmd_fail(a) -> int:
    _finalize(
        a.id,
        ".fail",
        a.reason or "failed",
        exit_code=getattr(a, "exit_code", None),
    )
    print(f"run {a.id} FAILED")
    return 0


def _fmt_run(run_id: str) -> str:
    state = _state_of(run_id)
    st = _read_status(run_id)
    phase = st.get("phase", "?")
    pct = st.get("pct")
    pcts = f" {pct}%" if isinstance(pct, (int, float)) else ""
    detail = st.get("detail", "") or st.get("final", "")
    upd = st.get("updated_iso", "?")
    return f"[{state:7}] {run_id}  phase={phase}{pcts}  upd={upd}  {detail[:80]}"


def cmd_show(a) -> int:
    if not _run_dir(a.id).exists():
        print(f"no such run: {a.id}", file=sys.stderr)
        return 1
    print(_fmt_run(a.id))
    return 0


def cmd_list(_a) -> int:
    root = _runs_root()
    if not root.exists():
        print("(no runs/ dir)")
        return 0
    runs = [p.name for p in root.iterdir() if p.is_dir()]
    # newest first by status.json mtime
    def _mtime(rid: str) -> float:
        p = _status_path(rid)
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    runs.sort(key=_mtime, reverse=True)
    if not runs:
        print("(no runs)")
        return 0
    for rid in runs:
        print(_fmt_run(rid))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="durable run-status surface")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("start"); sp.add_argument("id"); sp.add_argument("--phase"); sp.add_argument("--detail"); sp.add_argument("--pct", type=int)
    # Receipt fields (2026-07-26 audit, Phase 1): identity + where the evidence lives.
    sp.add_argument("--task-id", dest="task_id", help="orchestrator task/agent id, if any")
    sp.add_argument("--log", help="path to the run's durable log")
    sp.add_argument("--artifact", help="path to the run's primary output artifact")
    sp.set_defaults(fn=cmd_start)

    sp = sub.add_parser("update"); sp.add_argument("id"); sp.add_argument("--phase"); sp.add_argument("--detail"); sp.add_argument("--pct", type=int); sp.set_defaults(fn=cmd_update)

    sp = sub.add_parser("done"); sp.add_argument("id"); sp.add_argument("--summary")
    # `.done` is a VERIFIED-SUCCESS claim; one of these is required.
    sp.add_argument("--verify-cmd", dest="verify_cmd",
                    help="shell command that must exit 0 for success to be recorded")
    sp.add_argument("--verified-by", dest="verified_by",
                    help="explicit attestation of what proved success")
    sp.add_argument("--force", action="store_true",
                    help="record success WITHOUT evidence (marked unverified in the receipt)")
    sp.set_defaults(fn=cmd_done)

    sp = sub.add_parser("fail"); sp.add_argument("id"); sp.add_argument("--reason")
    sp.add_argument("--exit-code", dest="exit_code", type=int, help="process exit code")
    sp.set_defaults(fn=cmd_fail)
    sp = sub.add_parser("show"); sp.add_argument("id"); sp.set_defaults(fn=cmd_show)
    sp = sub.add_parser("list"); sp.set_defaults(fn=cmd_list)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
