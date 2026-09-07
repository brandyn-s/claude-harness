#!/usr/bin/env python3
"""Does the Codex install run the posture codex/config.toml.patch describes?

codex/config.toml.patch is applied by hand, and nothing verified it. This reads
~/.codex/config.toml (and, with --project, a repository's .codex/config.toml
overrides) and compares the four keys that ARE the posture:

    approval_policy               on-request      (never = the model asks nobody)
    sandbox_mode                  workspace-write (danger-full-access = no boundary)
    approvals_reviewer            auto_review     (a reviewer model handles routine approvals)
    [sandbox_workspace_write]
    network_access                false           (per project, flip to true where a task needs it)

Profiles ([profiles.<name>]) are checked too: a safe default with an unsafe profile
one flag away is the posture the flag selects. Exit 1 when approval_policy or
sandbox_mode drift (those are the enforcement layer); the other two are reported.
Exit 2 when the file is missing or unreadable. Nothing is written.

Key names were current for the 0.15x line in September 2026; `codex --version`
and the config reference for the installed version decide whether they still are.

USAGE
    python3 bin/codex-posture-check.py                       # ~/.codex/config.toml
    python3 bin/codex-posture-check.py --config PATH
    python3 bin/codex-posture-check.py --project ~/src/repo  # also that repo's .codex/config.toml
    python3 bin/codex-posture-check.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:  # 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 hosts
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None

EXPECTED = {
    "approval_policy": ("on-request", "hard"),
    "sandbox_mode": ("workspace-write", "hard"),
    "approvals_reviewer": ("auto_review", "soft"),
    "sandbox_workspace_write.network_access": (False, "soft"),
}
UNSAFE = {"approval_policy": {"never"}, "sandbox_mode": {"danger-full-access"}}


def _minimal_toml(text: str) -> dict:
    """Enough TOML for a posture check: [tables], dotted tables, scalar keys
    (strings, booleans, integers). Arrays and inline tables are skipped."""
    root: dict = {}
    table = root
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith('"') else raw.strip()
        if not line:
            continue
        m = re.match(r"^\[\[?([A-Za-z0-9_.\-\"']+)\]\]?$", line)
        if m:
            table = root
            for part in [p.strip().strip('"').strip("'") for p in m.group(1).split(".")]:
                table = table.setdefault(part, {})
            continue
        m = re.match(r"""^([A-Za-z0-9_\-"']+)\s*=\s*(.+)$""", line)
        if not m:
            continue
        key = m.group(1).strip('"').strip("'")
        val = m.group(2).strip()
        if val.startswith(("[", "{")):
            continue
        if val in ("true", "false"):
            table[key] = val == "true"
        elif re.fullmatch(r"-?\d+", val):
            table[key] = int(val)
        elif len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            table[key] = val[1:-1]
        else:
            table[key] = val
    return root


def load_toml(path: Path) -> dict:
    data = path.read_bytes()
    if _toml is not None:
        return _toml.loads(data.decode("utf-8"))
    return _minimal_toml(data.decode("utf-8", errors="replace"))


def _get(cfg: dict, dotted: str):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def judge(cfg: dict, label: str) -> list[dict]:
    rows = []
    for key, (want, weight) in EXPECTED.items():
        have = _get(cfg, key)
        if have is None:
            verdict = "unset (Codex default applies; set it explicitly)" if weight == "hard" else "unset"
            ok = weight != "hard"
        elif have == want:
            verdict, ok = "ok", True
        elif key in UNSAFE and have in UNSAFE[key]:
            verdict, ok = "UNSAFE", False
        else:
            verdict, ok = "differs", weight != "hard"
        rows.append({"scope": label, "key": key, "have": have, "want": want, "weight": weight, "verdict": verdict, "ok": ok})
    return rows


def check(config: Path, project: Path | None) -> dict:
    cfg = load_toml(config)
    rows = judge(cfg, "user")
    profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    for name, prof in profiles.items():
        if isinstance(prof, dict) and any(k in prof for k in ("approval_policy", "sandbox_mode", "approvals_reviewer")):
            merged = {**{k: v for k, v in cfg.items() if k != "profiles"}, **prof}
            rows += [r for r in judge(merged, f"profile {name}") if r["key"] != "sandbox_workspace_write.network_access"]
    project_rows = []
    if project is not None:
        pc = project / ".codex" / "config.toml"
        if pc.is_file():
            over = load_toml(pc)
            merged = {**cfg, **{k: v for k, v in over.items() if k != "sandbox_workspace_write"}}
            if "sandbox_workspace_write" in over:
                merged["sandbox_workspace_write"] = {**(cfg.get("sandbox_workspace_write") or {}), **over["sandbox_workspace_write"]}
            project_rows = judge(merged, f"project {project.name}")
            for r in project_rows:
                if r["key"] == "sandbox_workspace_write.network_access" and r["have"] is True:
                    r["verdict"], r["ok"] = "ok (per-project network, the documented override)", True
    hard_fail = any(not r["ok"] and r["weight"] == "hard" for r in rows + project_rows)
    return {"config": str(config), "project": str(project) if project else None, "rows": rows + project_rows,
            "aligned": not hard_fail and all(r["ok"] for r in rows + project_rows), "hard_fail": hard_fail,
            "parser": "tomllib" if _toml is not None else "minimal"}


def render(res: dict) -> str:
    out = [f"codex posture: {res['config']}" + (f"  (+ {res['project']}/.codex/config.toml)" if res["project"] else "")
           + f"   [parser: {res['parser']}]", ""]
    out.append(f"{'scope':<22}{'key':<42}{'have':<22}{'want':<18}verdict")
    for r in res["rows"]:
        out.append(f"{r['scope']:<22}{r['key']:<42}{str(r['have']):<22}{str(r['want']):<18}{r['verdict']}")
    out.append("")
    if res["hard_fail"]:
        out.append("DRIFT: the enforcement layer is not the documented posture. Apply codex/config.toml.patch "
                   "(approval_policy, sandbox_mode) and re-run; verify key names against `codex --version`'s config reference.")
    elif res["aligned"]:
        out.append("OK: Codex runs the posture codex/config.toml.patch describes.")
    else:
        out.append("OK with notes: enforcement keys match; the reviewer or network setting differs from the patch (advisory).")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=os.path.expanduser("~/.codex/config.toml"))
    ap.add_argument("--project", default=None, help="a repository whose .codex/config.toml overrides should be checked too")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    config = Path(os.path.expanduser(args.config))
    if not config.is_file():
        print(f"codex-posture-check: {config} not found (Codex not installed, or a different CODEX_HOME)", file=sys.stderr)
        return 2
    try:
        res = check(config, Path(os.path.expanduser(args.project)) if args.project else None)
    except Exception as exc:  # noqa: BLE001 -- a config we cannot parse is a finding, not a crash
        print(f"codex-posture-check: cannot read {config}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2, sort_keys=True) if args.json else render(res))
    return 1 if res["hard_fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
