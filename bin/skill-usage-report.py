#!/usr/bin/env python3
"""Which skills are actually invoked, and what the listing costs for the ones that are not.

The skill listing is 3.1x oversubscribed on a 200K model (README §Author-workstation
profile): `skillListingBudgetFraction` 3% is 6,000 tokens against an 18,687-token
listing. Truncation is silent -- the skills at the end of the alphabet stop being
routable -- so the choice of which skills to mark `name-only` in `skillOverrides`
should come from invocation frequency, not from taste. This tool measures it.

INPUT   a directory of Claude Code transcripts (~/.claude/projects, or a backup of
        it), walked recursively for *.jsonl. Two invocation signals per skill:
          slash     <command-name>/name</command-name> in a user turn
          auto      a Skill tool_use whose input.skill is the name
        plus the sessions each skill appears in and its first/last date. Nothing
        but names, counts and dates is read out of a transcript.
OUTPUT  per skill: invocations, sessions, dates, its listing cost (chars and the
        chars/4 token proxy of `name: description + when_to_use` cut at 1,536),
        whether settings.json already lists it name-only, and its family
        (FAMILIES below: the parameterisable groups the README names).
        The budget line: full listing tokens vs the 3% budget on 200K, before and
        after the proposed overrides.
        --propose-overrides prints a `skillOverrides` block: every skill with zero
        invocations in the window that belongs to a family, keeping the family's
        most-used member listed. Skills outside a family are reported, not proposed --
        an unused standalone skill is a deletion candidate, which is a different
        decision (docs/skill-cap-decisions.md).

USAGE
  python3 bin/skill-usage-report.py --root ~/.claude/projects
  python3 bin/skill-usage-report.py --root ~/claude-transcript-backups/2026-09-06 --json out.json
  python3 bin/skill-usage-report.py --root DIR --since 2026-07-01 --propose-overrides
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("skill_description_eval", REPO / "bin" / "skill-description-eval.py")
_sde = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _sde
_spec.loader.exec_module(_sde)

#: The parameterisable families the README names (§Optional plugin bundles / skill listing).
FAMILIES = {
    "gather": re.compile(r"^gather(-|$)"),
    "scout": re.compile(r"^scout"),
    "audit": re.compile(r"^audit(-|$)"),
    "capture": re.compile(r"^(mega-)?capture$"),
    "distill": re.compile(r"^(mega-)?distill$"),
    "retro": re.compile(r"^retro(spective)?$"),
    "superplan": re.compile(r"^super(plan|goal)(-loop|-status)?$"),
}
BUDGET_FRACTION = 0.03
CONTEXT_TOKENS = 200_000
SLASH_RE = re.compile(r"<command-name>/?([a-z][a-z0-9-]+)</command-name>")
AUTO_RE = re.compile(r'"name"\s*:\s*"Skill"[^}]{0,400}?"skill"\s*:\s*"([a-z][a-z0-9-]+)"')
TS_RE = re.compile(r'"timestamp"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def family_of(name: str) -> str | None:
    for fam, rx in FAMILIES.items():
        if rx.search(name):
            return fam
    return None


def _scan_file(path: str) -> dict:
    """Counts only: {slash: Counter, auto: Counter, date: str|None}."""
    slash, auto = Counter(), Counter()
    first_date = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if first_date is None:
                    m = TS_RE.search(line)
                    if m:
                        first_date = m.group(1)
                if "<command-name>" in line:
                    for m in SLASH_RE.finditer(line):
                        slash[m.group(1)] += 1
                if '"Skill"' in line:
                    for m in AUTO_RE.finditer(line):
                        auto[m.group(1)] += 1
    except OSError:
        pass
    return {"path": path, "slash": dict(slash), "auto": dict(auto), "date": first_date}


def _pooled_map(fn, items, chunksize):
    """Map `fn` over `items`: parallel for large inputs, serial otherwise.

    An unbounded ``ProcessPoolExecutor()`` spawns one worker per core; on a busy
    machine a reaped worker raises ``BrokenProcessPool`` and kills the whole run
    (seen on Python 3.14 running the full suite). Cap the workers the way
    ``bin/replay-script-content-guard.py`` does, skip the pool for small inputs
    (test fixtures, small corpora), and fall back to serial if it still breaks.
    """
    items = list(items)
    workers = max(1, min(8, os.cpu_count() or 2))
    if len(items) <= 2 * workers:
        return [fn(x) for x in items]
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(fn, items, chunksize=chunksize))
    except BrokenProcessPool:
        return [fn(x) for x in items]


def scan(root: Path, since: str | None) -> tuple[dict, int, int]:
    files = [str(p) for p in root.rglob("*.jsonl")]
    per_skill: dict[str, dict] = defaultdict(lambda: {"slash": 0, "auto": 0, "sessions": set(), "first": None, "last": None})
    sessions_scanned = 0
    for res in _pooled_map(_scan_file, files, 16):
        date = res["date"]
        if since and date and date < since:
            continue
        sessions_scanned += 1
        for kind in ("slash", "auto"):
            for name, n in res[kind].items():
                row = per_skill[name]
                row[kind] += n
                row["sessions"].add(res["path"])
                if date:
                    row["first"] = min(row["first"] or date, date)
                    row["last"] = max(row["last"] or date, date)
    return per_skill, len(files), sessions_scanned


def load_overrides(settings_path: Path) -> dict:
    try:
        return dict(json.loads(settings_path.read_text(encoding="utf-8")).get("skillOverrides") or {})
    except (OSError, ValueError):
        return {}


def build(root: Path, since: str | None, settings_path: Path, skills_dir: Path) -> dict:
    usage, n_files, n_sessions = scan(root, since)
    overrides = load_overrides(settings_path)
    skills = _sde.load_skills(skills_dir)
    rows = []
    for s in skills:
        u = usage.get(s["name"], {"slash": 0, "auto": 0, "sessions": set(), "first": None, "last": None})
        listing_chars = len(f"{s['name']}: {s['listing']}")
        name_only = overrides.get(s["name"]) == "name-only" or not s["model_visible"]
        rows.append({
            "skill": s["name"], "family": family_of(s["name"]),
            "slash": u["slash"], "auto": u["auto"], "invocations": u["slash"] + u["auto"],
            "sessions": len(u["sessions"]), "first": u["first"], "last": u["last"],
            "listing_chars": listing_chars, "listing_tokens": listing_chars // 4,
            "name_only": name_only, "model_visible": s["model_visible"],
        })
    unknown = sorted(n for n in usage if n not in {s["name"] for s in skills})
    # budget
    def tokens(name_only_set: set[str]) -> int:
        return sum((len(r["skill"]) + 2) // 4 + 1 if r["skill"] in name_only_set or not r["model_visible"]
                   else r["listing_tokens"] for r in rows)
    current_name_only = {r["skill"] for r in rows if r["name_only"]}
    # proposal: zero-invocation family members, keeping each family's most-used member listed
    proposed = set(current_name_only)
    by_family: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["family"]:
            by_family[r["family"]].append(r)
    for fam, members in by_family.items():
        keep = max(members, key=lambda r: (r["invocations"], r["sessions"], r["skill"]))
        for r in members:
            if r is not keep and r["invocations"] == 0:
                proposed.add(r["skill"])
    budget = int(CONTEXT_TOKENS * BUDGET_FRACTION)
    unused_standalone = sorted(r["skill"] for r in rows if r["invocations"] == 0 and not r["family"] and not r["name_only"])
    return {
        "root": str(root), "since": since, "transcripts": n_files, "sessions_in_window": n_sessions,
        "skills": sorted(rows, key=lambda r: (-r["invocations"], r["skill"])),
        "unknown_skill_names_seen": unknown,
        "budget": {"tokens": budget, "listing_now": tokens(current_name_only), "listing_after_proposal": tokens(proposed),
                   "name_only_now": sorted(current_name_only), "name_only_proposed": sorted(proposed)},
        "proposed_overrides": {name: "name-only" for name in sorted(proposed)},
        "unused_standalone_skills": unused_standalone,
    }


def render(rep: dict, propose: bool) -> str:
    out = [f"skill usage over {rep['transcripts']} transcripts ({rep['sessions_in_window']} in window"
           f"{', since ' + rep['since'] if rep['since'] else ''}) under {rep['root']}", ""]
    out.append(f"{'skill':<34}{'family':<10}{'slash':>6}{'auto':>6}{'sess':>6}  {'first':<11}{'last':<11}{'list tok':>9}  name-only")
    for r in rep["skills"]:
        out.append(f"{r['skill']:<34}{(r['family'] or '-'):<10}{r['slash']:>6}{r['auto']:>6}{r['sessions']:>6}  "
                   f"{(r['first'] or '-'):<11}{(r['last'] or '-'):<11}{r['listing_tokens']:>9}  {'yes' if r['name_only'] else ''}")
    b = rep["budget"]
    out.append("")
    out.append(f"listing budget {b['tokens']:,} tokens (3% of 200K); listing now ≈ {b['listing_now']:,} tokens "
               f"({b['listing_now'] / b['tokens']:.1f}x); after the proposal ≈ {b['listing_after_proposal']:,} "
               f"({b['listing_after_proposal'] / b['tokens']:.1f}x)   [chars/4 proxy]")
    zero = [r["skill"] for r in rep["skills"] if r["invocations"] == 0]
    out.append(f"skills with zero invocations in the window: {len(zero)} of {len(rep['skills'])}")
    if rep["unused_standalone_skills"]:
        out.append(f"  standalone (not proposed; deletion is a separate decision): {', '.join(rep['unused_standalone_skills'])}")
    if rep["unknown_skill_names_seen"]:
        out.append(f"names invoked that are not skills in this tree: {', '.join(rep['unknown_skill_names_seen'][:20])}")
    if propose:
        out.append("")
        out.append('"skillOverrides": ' + json.dumps(rep["proposed_overrides"], indent=2))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, help="transcript directory (recursive)")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD: ignore transcripts that start earlier")
    ap.add_argument("--settings", default=str(REPO / "settings.json"), help="settings.json with skillOverrides")
    ap.add_argument("--skills", default=str(REPO / "skills"))
    ap.add_argument("--json", default=None, help="write the full report here")
    ap.add_argument("--propose-overrides", action="store_true")
    args = ap.parse_args()
    root = Path(os.path.expanduser(args.root))
    if not root.is_dir():
        print(f"skill-usage-report: {root} is not a directory", file=sys.stderr)
        return 2
    if args.since:
        dt.datetime.strptime(args.since, "%Y-%m-%d")
    rep = build(root, args.since, Path(args.settings), Path(args.skills))
    print(render(rep, args.propose_overrides))
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
