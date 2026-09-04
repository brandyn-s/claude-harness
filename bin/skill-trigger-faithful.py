#!/usr/bin/env python3
"""Faithful trigger check: does Claude Code itself invoke the skill for the request?

bin/skill-description-eval.py measures routing with a PROXY: one API call that sees
only the skill listing and must name a skill. The runtime is different in three
ways the proxy cannot see: the model has tools (it can answer without a skill), it
sees the whole system prompt, and invoking a skill is a `Skill` tool_use it may or
may not choose. This driver measures the real thing for a sample of skills by
running `claude -p "<request>"` and reading the stream for a Skill tool_use naming
the expected skill.

Faithfulness and isolation:
  * A project directory whose `.claude/skills/<name>` symlinks EVERY model-visible
    skill in this repo, so the routing table the model sees is the realistic one.
  * `--setting-sources project` so the user's ~/.claude settings, hooks, plugins
    and skills are NOT loaded (the stream is checked for hook events: must be 0);
    `--strict-mcp-config` so no MCP server is started; `--no-session-persistence`
    so nothing is written under ~/.claude/projects.
  * Plan mode and `--max-turns N` bound each run; the Skill tool_use, if any, is
    in the first assistant turn.
  * ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are removed from the child's
    environment: these runs bill the owner's Claude Code subscription, and the
    key can neither be used nor leaked. The stream's `total_cost_usd` is the
    API-equivalent price, recorded for scale only.

Sample (deterministic, from the low-effort proxy report): the N model-visible
skills with the lowest proxy recall (ties: fewer hits, then name) and N skills
with perfect proxy recall that captured nobody else's requests, taken evenly
across the alphabetical list. Skills hidden from the model (`disable-model-
invocation: true`) are excluded and listed: nothing can trigger them.

Usage:
  bin/skill-trigger-faithful.py run --dry-run --project /tmp/faithful \\
      --sample-from skills/_shared/description-eval/results-2026-09-04.json \\
      --proxy low=skills/_shared/description-eval/results-2026-09-04.json \\
      --proxy xhigh=skills/_shared/description-eval/results-2026-09-04-xhigh.json
  ... same without --dry-run, plus --out skills/_shared/description-eval/faithful-<date>.json
  bin/skill-trigger-faithful.py parse stream.jsonl      # inspect one saved stream

Deterministic tests (no claude binary needed): scripts/test_skill_trigger_faithful.py.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / "skills"
EVAL_DIR = SKILLS_DIR / "_shared" / "description-eval"
CORPUS_PATH = EVAL_DIR / "corpus.json"

DEFAULT_MODEL = "claude-fable-5-1"      # the model the proxy routed with; the owner's setting is the same id
DEFAULT_MAX_TURNS = 2
DEFAULT_MAX_RUNS = 30
DEFAULT_TIMEOUT_S = 420
DEFAULT_BUDGET_USD = 3.0                # per-run --max-budget-usd safety net (subscription-billed, notional)
SKILL_TOOL_NAMES = {"Skill", "SlashCommand"}
OK_RESULT_SUBTYPES = {"success", "error_max_turns"}   # hitting --max-turns is expected, not a failure
STOP_AFTER_CONSECUTIVE_FAILURES = 2
SECRET_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _load_sde():
    spec = importlib.util.spec_from_file_location("skill_description_eval", REPO / "bin" / "skill-description-eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- sample

SAMPLE_RULE = ("{weakest} model-visible skills with the lowest proxy recall in {source} (ties: fewer hits, then "
               "name) and {strong} skills with perfect proxy recall that captured no other skill's request, "
               "taken evenly across the alphabetical list; skills hidden from the model are excluded")


def select_sample(per_skill: dict, visible: set[str], weakest: int = 5, strong: int = 5,
                  source: str = "the low-effort run") -> dict:
    def recall(name):
        value = per_skill[name].get("recall")
        return 2.0 if value is None else value

    candidates = sorted((n for n in per_skill if n in visible),
                        key=lambda n: (recall(n), per_skill[n].get("hits", 0), n))
    weak = candidates[:weakest]
    clean = sorted(n for n in candidates if n not in weak and recall(n) == 1.0 and per_skill[n].get("captured", 0) == 0)
    if strong <= 0 or not clean:
        strong_pick = []
    elif strong >= len(clean):
        strong_pick = clean
    elif strong == 1:
        strong_pick = [clean[0]]
    else:
        strong_pick = [clean[round(i * (len(clean) - 1) / (strong - 1))] for i in range(strong)]
    return {
        "weakest": weak, "strong": strong_pick,
        "excluded_not_visible": sorted(n for n in per_skill if n not in visible),
        "rule": SAMPLE_RULE.format(weakest=weakest, strong=strong, source=source),
    }


# --------------------------------------------------------------------------- claude

def resolve_claude(explicit: str | None = None) -> str:
    """The real binary (PATH lookup); a shell alias or function is not visible here."""
    path = explicit or shutil.which("claude")
    if not path:
        raise SystemExit("error: `claude` not found on PATH; pass --claude-bin")
    return path


def redact_home(path: str) -> str:
    """Record paths without the owner's home directory (the results file is committed)."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if home and path.startswith(home + os.sep) else path


def claude_version(claude_bin: str) -> str:
    try:
        out = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return out.strip().splitlines()[-1] if out.strip() else "unknown"


def build_command(claude_bin: str, request: str, model: str, max_turns: int, budget_usd: float) -> list[str]:
    if request.startswith("-"):
        raise ValueError("request must not start with '-' (it would parse as an option)")
    return [
        claude_bin, "-p", request,
        "--output-format", "stream-json", "--verbose",
        "--max-turns", str(max_turns),
        "--permission-mode", "plan",
        "--setting-sources", "project",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--include-hook-events",
        "--model", model,
        "--max-budget-usd", f"{budget_usd:.2f}",
    ]


def subprocess_env(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    for key in SECRET_ENV:
        env.pop(key, None)
    return env


# --------------------------------------------------------------------------- stream

def normalize_skill(tool_input: dict) -> str:
    raw = str(tool_input.get("skill") or tool_input.get("command") or tool_input.get("name") or "").strip()
    raw = raw.split()[0] if raw else ""
    raw = raw.lstrip("/")
    if ":" in raw:                       # plugin-namespaced `plugin:skill`
        raw = raw.rsplit(":", 1)[-1]
    return raw


def parse_stream(lines) -> dict:
    """stream-json -> what the trigger check needs. Tolerates blank and non-JSON lines."""
    rec = {"init": None, "skill_calls": [], "tool_calls": [], "hook_events": [], "result": None,
           "assistant_text_chars": 0, "events": 0, "malformed": 0}
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            rec["malformed"] += 1
            continue
        if not isinstance(event, dict):
            rec["malformed"] += 1
            continue
        rec["events"] += 1
        kind = event.get("type")
        if kind == "system":
            subtype = str(event.get("subtype") or "")
            if subtype == "init":
                rec["init"] = {
                    "model": event.get("model"), "permissionMode": event.get("permissionMode"),
                    "claude_code_version": event.get("claude_code_version"), "apiKeySource": event.get("apiKeySource"),
                    "tools": list(event.get("tools") or []),
                    "slash_commands": list(event.get("slash_commands") or []),
                    "skills": list(event.get("skills") or []),
                    "mcp_servers": len(event.get("mcp_servers") or []),
                    "agents": len(event.get("agents") or []),
                    "plugins": len(event.get("plugins") or []),
                }
            elif subtype.startswith("hook"):
                rec["hook_events"].append({"subtype": subtype,
                                           "hook_event": event.get("hook_event") or event.get("hook_event_name"),
                                           "hook_name": event.get("hook_name")})
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = block.get("name")
                    rec["tool_calls"].append(name)
                    if name in SKILL_TOOL_NAMES:
                        rec["skill_calls"].append(normalize_skill(block.get("input") or {}))
                elif block.get("type") == "text":
                    rec["assistant_text_chars"] += len(block.get("text") or "")
        elif kind == "result":
            rec["result"] = {k: event.get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms",
                                                          "total_cost_usd", "stop_reason")}
            rec["result"]["permission_denials"] = len(event.get("permission_denials") or [])
    return rec


def run_failed(record: dict) -> bool:
    """A run that produced no result event, or an unexpected result subtype, failed.
    Reaching --max-turns is the expected end of a run that kept working."""
    result = record.get("result")
    return result is None or result.get("subtype") not in OK_RESULT_SUBTYPES


# --------------------------------------------------------------------------- project

def setup_project(project: Path, visible: list[dict], skills_dir: Path = SKILLS_DIR) -> dict:
    """`.claude/skills/<name>` -> repo skills/<name> for every model-visible skill; stale links removed."""
    skills_root = project / ".claude" / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    wanted = {s["name"] for s in visible}
    linked, removed = [], []
    for entry in list(skills_root.iterdir()):
        if entry.name not in wanted and entry.is_symlink():
            entry.unlink()
            removed.append(entry.name)
    for skill in visible:
        link = skills_root / skill["name"]
        target = (skills_dir / skill["name"]).resolve()
        if link.is_symlink():
            if link.resolve() == target:
                linked.append(skill["name"])
                continue
            link.unlink()
        elif link.exists():
            raise SystemExit(f"error: {link} exists and is not a symlink; refusing to replace it")
        link.symlink_to(target, target_is_directory=True)
        linked.append(skill["name"])
    return {"project": str(project), "skills_linked": len(linked), "stale_links_removed": removed,
            "settings_json_present": (project / ".claude" / "settings.json").exists(),
            "claude_md_present": (project / "CLAUDE.md").exists()}


# --------------------------------------------------------------------------- runs

def run_one(item: dict, cmd: list[str], cwd: Path, env: dict, timeout_s: int, stream_dir: Path,
            resume: bool = False) -> dict:
    """Run `claude -p` for one request, or with resume=True re-parse an already saved
    stream (a smoke run's session is then counted, not billed twice)."""
    started = time.time()
    stream_path = stream_dir / f"{item['id']}.jsonl"
    resumed = resume and stream_path.exists() and stream_path.stat().st_size > 0
    if resumed:
        stdout, stderr, exit_code, timed_out = stream_path.read_text(encoding="utf-8"), "", None, False
    else:
        try:
            proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout_s)
            stdout, stderr, exit_code, timed_out = proc.stdout, proc.stderr, proc.returncode, False
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            exit_code, timed_out = 124, True
        stream_path.write_text(stdout, encoding="utf-8")
    parsed = parse_stream(stdout.splitlines())
    init = parsed["init"] or {}
    listed = None
    if init:
        names = set(init.get("skills") or []) | {c.lstrip("/") for c in init.get("slash_commands") or []}
        listed = item["expected"] in names
    record = {
        "id": item["id"], "expected": item["expected"], "request": item["request"],
        "triggered": item["expected"] in parsed["skill_calls"],
        "skill_calls": parsed["skill_calls"], "tool_calls": parsed["tool_calls"],
        "hook_events": len(parsed["hook_events"]), "hook_event_samples": parsed["hook_events"][:5],
        "expected_listed_in_init": listed,
        "init": {k: init.get(k) for k in ("model", "permissionMode", "claude_code_version", "apiKeySource",
                                            "mcp_servers", "agents", "plugins")} if init else None,
        "init_counts": {"tools": len(init.get("tools") or []), "slash_commands": len(init.get("slash_commands") or []),
                        "skills": len(init.get("skills") or [])} if init else None,
        "skill_tool_available": ("Skill" in (init.get("tools") or [])) if init else None,
        "result": parsed["result"], "events": parsed["events"], "malformed_lines": parsed["malformed"],
        "exit_code": exit_code, "timed_out": timed_out, "elapsed_s": round(time.time() - started, 1),
        "resumed_from_saved_stream": resumed,
        "stderr_tail": stderr[-600:], "stream": str(stream_path),
    }
    record["failed"] = run_failed(record)
    return record


def plan_items(corpus: dict, sample: dict) -> list[dict]:
    wanted = sample["weakest"] + sample["strong"]
    by_skill = {}
    for item in corpus["items"]:
        if item["kind"] == "positive" and item["expected"] in wanted:
            by_skill.setdefault(item["expected"], []).append(item)
    items = []
    for name in wanted:
        items += sorted(by_skill.get(name, []), key=lambda i: i["id"])
    return items


def summarize(runs: list[dict], sample: dict, proxies: list[dict]) -> dict:
    """Per-skill proxy-vs-faithful table and item-level agreement with the last proxy."""
    labels = [p["label"] for p in proxies]
    by_skill: dict[str, list[dict]] = {}
    for run in runs:
        by_skill.setdefault(run["expected"], []).append(run)
    per_skill = []
    for group in ("weakest", "strong"):
        for name in sample[group]:
            mine = by_skill.get(name, [])
            proxy_hits = {}
            for proxy in proxies:
                row = ((proxy["results"].get("report") or {}).get("per_skill") or {}).get(name)
                proxy_hits[proxy["label"]] = row["hits"] if row else None
            per_skill.append({
                "skill": name, "group": group, "positives": len(mine),
                "faithful_hits": sum(1 for r in mine if r["triggered"]),
                "failed_runs": sum(1 for r in mine if r["failed"]),
                "proxy_hits": proxy_hits,
                "other_skills_fired": sorted({c for r in mine for c in r["skill_calls"] if c and c != name}),
            })
    agreement = {"proxy_label": labels[-1] if labels else None, "n": 0, "both_hit": 0, "both_miss": 0,
                 "proxy_only": 0, "faithful_only": 0, "rate": 0.0}
    if proxies:
        ref = {r["id"]: r for r in proxies[-1]["results"]["routes"]}
        for run in runs:
            route = ref.get(run["id"])
            if route is None:
                continue
            proxy_hit, faithful_hit = route["answer"] == run["expected"], run["triggered"]
            agreement["n"] += 1
            key = ("both_hit" if proxy_hit and faithful_hit else "both_miss" if not proxy_hit and not faithful_hit
                   else "proxy_only" if proxy_hit else "faithful_only")
            agreement[key] += 1
        if agreement["n"]:
            agreement["rate"] = round((agreement["both_hit"] + agreement["both_miss"]) / agreement["n"], 4)
    misses = [{"id": r["id"], "expected": r["expected"], "skill_calls": r["skill_calls"], "request": r["request"],
               "failed": r["failed"]} for r in runs if not r["triggered"]]
    first_tool: dict[str, int] = {}
    for r in runs:
        if not r["triggered"]:
            tool = (r.get("tool_calls") or ["none"])[0] or "none"
            first_tool[tool] = first_tool.get(tool, 0) + 1
    return {"proxy_labels": labels, "per_skill": per_skill, "agreement": agreement, "misses": misses,
            "miss_first_tool": first_tool,
            "faithful_hits": sum(1 for r in runs if r["triggered"]), "runs": len(runs)}


def _parse_proxy(spec: str) -> dict:
    label, _, path = spec.partition("=")
    if not path:
        raise argparse.ArgumentTypeError("--proxy expects label=path/to/results.json")
    results = json.loads(Path(path).read_text(encoding="utf-8"))
    if "report" not in results:
        raise argparse.ArgumentTypeError(f"{path} has no report section; run `skill-description-eval.py report` first")
    return {"label": label, "path": path, "results": results}


def cmd_run(args) -> int:
    sde = _load_sde()
    skills = sde.load_skills(args.skills_dir)
    visible = sde.visible_skills(skills)
    visible_names = {s["name"] for s in visible}
    source = json.loads(Path(args.sample_from).read_text(encoding="utf-8"))
    per_skill = (source.get("report") or {}).get("per_skill")
    if not per_skill:
        log("error: --sample-from has no report.per_skill; run `skill-description-eval.py report` on it first")
        return 2
    sample = select_sample(per_skill, visible_names, args.weakest, args.strong, source=Path(args.sample_from).name)
    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    items = plan_items(corpus, sample)[:args.max_runs]
    claude_bin = args.claude_bin or shutil.which("claude") or "claude"
    commands = {i["id"]: build_command(claude_bin, i["request"], args.model, args.max_turns, args.budget_usd)
                for i in items}

    log(f"sample: weakest={sample['weakest']} strong={sample['strong']} "
        f"excluded(hidden)={sample['excluded_not_visible']}")
    log(f"{len(items)} runs planned (cap {args.max_runs}); project {args.project}; model {args.model}; "
        f"max-turns {args.max_turns}; concurrency {args.concurrency}")
    if args.dry_run:
        print(json.dumps({
            "dry_run": True, "sample": sample, "project": str(args.project), "claude_bin": claude_bin,
            "env_removed": [k for k in SECRET_ENV if k in os.environ],
            "runs": [{"id": i["id"], "expected": i["expected"], "request": i["request"], "argv": commands[i["id"]]}
                     for i in items],
        }, indent=2))
        return 0

    claude_bin = resolve_claude(args.claude_bin)
    version = claude_version(claude_bin)
    project = Path(args.project)
    setup = setup_project(project, visible, args.skills_dir)
    stream_dir = Path(args.stream_dir) if args.stream_dir else project / "streams"
    stream_dir.mkdir(parents=True, exist_ok=True)
    env = subprocess_env()
    log(f"claude {version} at {claude_bin}; {setup['skills_linked']} skills linked; streams -> {stream_dir}")

    runs: list[dict] = []
    lock = Lock()
    consecutive_failures = 0
    stopped_early = None
    started = datetime.now(timezone.utc)

    def execute(item):
        return run_one(item, commands[item["id"]], project, env, args.timeout, stream_dir, resume=args.resume)

    # Sequential batches of `concurrency`: the stop rule is checked between batches so a
    # repeatedly failing setup cannot burn the whole sample.
    for start in range(0, len(items), max(1, args.concurrency)):
        batch = items[start:start + max(1, args.concurrency)]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {pool.submit(execute, item): item for item in batch}
            batch_records = []
            for future in as_completed(futures):
                record = future.result()
                batch_records.append(record)
                with lock:
                    runs.append(record)
                status = "HIT " if record["triggered"] else ("FAIL" if record["failed"] else "miss")
                log(f"  {status} {record['id']:<32} skill_calls={record['skill_calls']} "
                    f"turns={(record['result'] or {}).get('num_turns')} subtype={(record['result'] or {}).get('subtype')} "
                    f"hooks={record['hook_events']} {record['elapsed_s']}s")
                if record["failed"]:
                    log(f"       stderr: {record['stderr_tail'][-300:]!r}")
        for record in sorted(batch_records, key=lambda r: r["id"]):
            consecutive_failures = consecutive_failures + 1 if record["failed"] else 0
        if consecutive_failures >= STOP_AFTER_CONSECUTIVE_FAILURES:
            stopped_early = (f"stopped after {consecutive_failures} consecutive failed runs "
                             f"({len(runs)}/{len(items)} done)")
            log(stopped_early)
            break

    runs.sort(key=lambda r: r["id"])
    proxies = args.proxy or []
    summary = summarize(runs, sample, proxies)
    finished = datetime.now(timezone.utc)
    out = {
        "meta": {
            "date": started.date().isoformat(), "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "claude_version": version, "claude_bin": redact_home(claude_bin), "model": args.model,
            "max_turns": args.max_turns,
            "permission_mode": "plan", "setting_sources": "project", "project": str(project), "setup": setup,
            "argv_template": build_command("claude", "<request>", args.model, args.max_turns, args.budget_usd),
            "env_removed": list(SECRET_ENV), "sample_rule": sample["rule"], "corpus": str(args.corpus),
            "sample_from": str(args.sample_from), "proxies": [{"label": p["label"], "path": p["path"],
                                                               "effort": p["results"]["meta"].get("effort")}
                                                              for p in proxies],
            "runs": len(runs), "planned": len(items), "errors": sum(1 for r in runs if r["failed"]),
            "resumed_from_saved_streams": sum(1 for r in runs if r["resumed_from_saved_stream"]),
            "stopped_early": stopped_early,
            "hook_events_total": sum(r["hook_events"] for r in runs),
            "skill_tool_available_in_all_runs": all(r["skill_tool_available"] for r in runs if r["init"]) if runs else None,
            "expected_listed_in_all_runs": all(r["expected_listed_in_init"] for r in runs if r["init"]) if runs else None,
            "notional_cost_usd": round(sum((r["result"] or {}).get("total_cost_usd") or 0.0 for r in runs), 4),
            "billing": "owner's Claude Code subscription (API key removed from the environment)",
        },
        "sample": sample, "runs": runs, "summary": summary,
    }
    out_path = Path(args.out) if args.out else EVAL_DIR / f"faithful-{out['meta']['date']}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"wrote {out_path}: {summary['faithful_hits']}/{summary['runs']} triggered, "
        f"{out['meta']['errors']} failed, hooks fired {out['meta']['hook_events_total']}")
    return 1 if stopped_early else 0


def cmd_parse(args) -> int:
    parsed = parse_stream(Path(args.stream).read_text(encoding="utf-8").splitlines())
    if parsed["init"]:
        parsed["init"]["tools"] = len(parsed["init"]["tools"])
        parsed["init"]["slash_commands"] = len(parsed["init"]["slash_commands"])
        parsed["init"]["skills"] = len(parsed["init"]["skills"])
    print(json.dumps(parsed, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run the sampled requests through `claude -p` and record Skill tool_uses")
    p.add_argument("--project", type=Path, required=True, help="scratch project dir (created; .claude/skills symlinked)")
    p.add_argument("--sample-from", required=True, help="results-*.json with a report section (the low-effort run)")
    p.add_argument("--corpus", default=str(CORPUS_PATH))
    p.add_argument("--proxy", action="append", type=_parse_proxy, metavar="LABEL=RESULTS",
                   help="proxy results to compare against, repeatable; the last one anchors item agreement")
    p.add_argument("--weakest", type=int, default=5)
    p.add_argument("--strong", type=int, default=5)
    p.add_argument("--max-runs", type=int, default=DEFAULT_MAX_RUNS)
    p.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD, help="per-run --max-budget-usd")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="per-run wall clock (s)")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--claude-bin", default=None)
    p.add_argument("--stream-dir", default=None, help="where raw streams go (default <project>/streams)")
    p.add_argument("--out", default=None, help="default skills/_shared/description-eval/faithful-<date>.json")
    p.add_argument("--dry-run", action="store_true", help="print the sample and exact argv; run nothing")
    p.add_argument("--resume", action="store_true",
                   help="reuse a saved <stream-dir>/<id>.jsonl instead of running that request again")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("parse", help="parse one saved stream-json file")
    p.add_argument("stream")
    p.set_defaults(func=cmd_parse)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
