#!/usr/bin/env python3
"""Measurement gate for hooks/script-content-guard.py (spec: hooks/staged/
script-file-bypasses-bash-guards.spec.md, "Measurement gate before install").

Replays every Write / Edit / MultiEdit the model made in the local Claude Code
transcript corpus, keeps the script-like targets (.sh/.bash/.zsh/.ksh/.py or a
shell/python shebang), runs the guard's own scan over each body, and reports:

  * how many script writes there were (raw, and unique by content hash)
  * how many the guard would have fired on, by check family
  * the fire rate against the spec's >10 %-is-too-broad gate
  * how many env-var-diagnostic hits predate the 2026-08-12 incident -- the
    spec's FALSIFIER: if none do, the incident is n=1 and `advise` is the
    correct default strength, not `block`

Prints tags, paths and dates only -- never file contents -- so the report can be
committed. Read-only; touches nothing under ~/.claude except to read.

    python3 bin/replay-script-content-guard.py                 # ~/.claude/projects
    python3 bin/replay-script-content-guard.py --root <dir>    # another projects dir
    python3 bin/replay-script-content-guard.py --json out.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "script-content-guard.py"
INCIDENT_DATE = "2026-08-12"
TAG_RE_PREFIX = "["
_TOOL_MARKERS = ("\"Write\"", "\"Edit\"", "\"MultiEdit\"")


def _load_hook():
    spec = importlib.util.spec_from_file_location("script_content_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iter_writes(path: Path):
    """Yield (timestamp, tool_name, file_path, text) for every write-like tool_use."""
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            # Cheap pre-filter: only assistant lines that mention a write-like tool
            # are worth a json.loads (the corpus is gigabytes; parsing every line is
            # what made the first run too slow to finish in one sitting).
            if '"assistant"' not in line or not any(t in line for t in _TOOL_MARKERS):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            ts = str(obj.get("timestamp") or "")[:10]
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name")
                inp = block.get("input") or {}
                if not isinstance(inp, dict):
                    continue
                fp = str(inp.get("file_path") or "")
                if name == "Write":
                    yield ts, name, fp, str(inp.get("content") or "")
                elif name == "Edit":
                    yield ts, name, fp, str(inp.get("new_string") or "")
                elif name == "MultiEdit":
                    for e in inp.get("edits") or []:
                        if isinstance(e, dict):
                            yield ts, name, fp, str(e.get("new_string") or "")


def _scan_file(path_str: str) -> dict:
    """Per-file worker (runs in a subprocess): returns counts, never contents."""
    hook = _load_hook()
    out = {"script_writes": 0, "unique": [], "by_ext": {}, "by_tag": {}, "fires": []}
    for ts, tool, fp, text in _iter_writes(Path(path_str)):
        if not hook.is_script_like(fp, text):
            continue
        out["script_writes"] += 1
        ext = Path(fp).suffix.lower() or "<shebang>"
        out["by_ext"][ext] = out["by_ext"].get(ext, 0) + 1
        out["unique"].append(hashlib.sha256((fp + "\0" + text).encode("utf-8", "replace")).hexdigest())
        findings = hook.scan_script(text, fp)
        if findings:
            reason = findings[0][1]
            tag = reason.split("]", 1)[0] + "]" if reason.startswith(TAG_RE_PREFIX) else "[unknown]"
            out["by_tag"][tag] = out["by_tag"].get(tag, 0) + 1
            # reason text carries the matched SHAPE (never file contents beyond the
            # matched construct), truncated for the report
            out["fires"].append((ts, tag, fp, tool, findings[0][0], reason[:200]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--json", help="write the machine-readable report here")
    ap.add_argument("--gate", type=float, default=10.0, help="fire-rate %% above which the predicate is too broad")
    args = ap.parse_args()

    os.environ["CLAUDE_SCRIPT_CONTENT_GUARD"] = "block"
    _load_hook()  # fail fast here if the hook or the guard cannot import

    root = Path(args.root)
    files = sorted(root.glob("*/*.jsonl")) + sorted(root.glob("*/*/*.jsonl"))
    sessions = 0
    script_writes = 0
    unique = set()
    fires = []          # (date, tag, path, tool, line, reason)
    by_tag = collections.Counter()
    by_ext = collections.Counter()
    import concurrent.futures as cf
    workers = max(1, min(8, (os.cpu_count() or 2)))
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_scan_file, [str(f) for f in files], chunksize=8):
            sessions += 1
            script_writes += result["script_writes"]
            unique.update(result["unique"])
            for ext, n in result["by_ext"].items():
                by_ext[ext] += n
            for tag, n in result["by_tag"].items():
                by_tag[tag] += n
            fires.extend(tuple(x) for x in result["fires"])

    rate = (100.0 * len(fires) / script_writes) if script_writes else 0.0
    pre_incident_diag = [x for x in fires if x[1] == "[env-var-diagnostic-guard]" and x[0] and x[0] < INCIDENT_DATE]
    fires_by_ext = collections.Counter((Path(x[2]).suffix.lower() or "<shebang>") for x in fires)
    diag_total = by_tag.get("[env-var-diagnostic-guard]", 0)

    report = {
        "root": str(root),
        "sessions_scanned": sessions,
        "script_writes": script_writes,
        "script_writes_unique": len(unique),
        "by_extension": dict(by_ext),
        "fires": len(fires),
        "fire_rate_pct": round(rate, 2),
        "gate_pct": args.gate,
        "too_broad": rate > args.gate,
        "fires_by_check": dict(by_tag),
        "fires_by_extension": dict(fires_by_ext),
        "env_var_diagnostic_fires": diag_total,
        "env_var_diagnostic_fires_before_incident": len(pre_incident_diag),
        "falsifier_n_equals_1": diag_total <= 1,
        "recommended_default": "block" if (rate <= args.gate and diag_total > 1) else "advise",
        "fire_list": [{"date": d, "check": t, "path": p, "tool": tool, "line": ln, "reason": r}
                      for d, t, p, tool, ln, r in sorted(fires)],
    }
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"sessions scanned            {sessions}")
    print(f"script-like writes          {script_writes}  (unique {len(unique)})  {dict(by_ext)}")
    print(f"guard fires                 {len(fires)}  ->  {rate:.2f}%  (gate {args.gate}%: {'TOO BROAD' if report['too_broad'] else 'ok'})")
    for tag, n in by_tag.most_common():
        print(f"   {n:5d}  {tag}")
    print(f"fires by extension          {dict(fires_by_ext)}")
    print(f"env-var-diagnostic fires    {diag_total}, before {INCIDENT_DATE}: {len(pre_incident_diag)}")
    print(f"recommended default         {report['recommended_default']}")
    for d, t, p, tool, ln, _r in sorted(fires)[:40]:
        print(f"   {d}  {t:32s} {tool:9s} {p}:{ln}")
    if len(fires) > 40:
        print(f"   ... {len(fires) - 40} more (see --json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
