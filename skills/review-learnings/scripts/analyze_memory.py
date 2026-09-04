#!/usr/bin/env python3
"""review-learnings/analyze_memory.py — deterministic mechanical analysis for
the /review-learnings skill (the agent-memory counterpart of garden/analyze.py).

Performs the NON-judgment parts of a memory audit and emits a single JSON
report to a temp path. The skill (LLM) consumes the JSON and applies the
judgment parts: correctness review, promotion decisions, cross-topic merge
choices, lossy-compression cost-benefit.

Why this exists: /review-learnings was a 16-step prose procedure with no
deterministic substrate — the same gap /garden had before analyze.py, and the
same failure mode (checks silently skipped or inconsistently applied across
runs). Everything countable is computed here; the skill never re-derives
counts by hand.

Usage:
    python3 analyze_memory.py [TOPICS_DIR] [--preflight]
    (TOPICS_DIR defaults to ~/.claude/agent-memory/topics)

--preflight additionally runs the Step 15b contention/divergence classification
(git fetch, behind-count, per-file SAFE/DEFER verdicts) and embeds it under the
"preflight" key. Requires TOPICS_DIR to be inside a git checkout.

Output: prints the JSON report path on stdout (last line). Stderr carries a
one-line summary.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Entry header: "### [tag] [category] Title (YYYY-MM-DD)" — date optional.
ENTRY_RE = re.compile(r"^### (?P<rest>.+)$", re.MULTILINE)
# Tags are ONLY the leading bracketed tokens of the title. Bracketed text
# later in the title (`--log[-failed]`, `argument-hint: "[X]"`) is prose,
# not a tag — a whole-title scan manufactured phantom tags (2026-08-22).
LEADING_TAGS_RE = re.compile(r"^\s*((?:\[[^\]]+\]\s*|PROMOTE-CANDIDATE\s*)+)")
TAG_TOKEN_RE = re.compile(r"\[([^\]]+)\]")
# Trailing date group; tolerates a dual-date form like
# "(2026-04-01, resolved by 2026-07-03)" — age is from the FIRST (opened) date.
DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})(?:[,;][^)]*)?\)\s*$")
DEEP_REF_RE = re.compile(r"^> Deep reference:\s*(.+)$", re.MULTILINE)

STALE_OBSERVED_DAYS = 30   # skill's prune threshold per SKILL.md Step 9
OVERSIZED_BYTES = 20_000   # flag unless the file declares an auto-managed cap
CAP_NOTICE_RE = re.compile(r"max \d+ entries|oldest pruned|auto-managed", re.IGNORECASE)

# A prior audit's explicit decision to retain an entry. Step 14 must honor
# these instead of re-proposing removal (check-before-change).
KEEP_DECISION_RE = re.compile(
    r"kept for historical record|no action needed|\[keep\]|keep decision",
    re.IGNORECASE)

# Transcript-prose markers inside an [auto-captured] entry: the capture hook
# grabbed mid-reasoning assistant text, not a durable fact (2026-08-22 audit:
# 14/14 flagged entries were fragments like "Let me write the … entry.").
JUNK_MARKERS = ("let me ", "source:  agent (session", "source: agent (session")

BODY_SCAN_CHARS = 2_000    # how much of each entry body the detectors read


def norm_title(rest: str) -> str:
    """Strip leading tags + trailing date so duplicate detection compares titles."""
    m = LEADING_TAGS_RE.match(rest)
    t = rest[m.end():] if m else rest
    t = DATE_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def leading_tags(rest: str) -> list:
    """Bracketed tokens at the START of the entry title only."""
    m = LEADING_TAGS_RE.match(rest)
    return TAG_TOKEN_RE.findall(m.group(1)) if m else []


def iter_entries(content: str):
    """Yield (header_text, body_text) per ### entry; body capped for scanning."""
    matches = list(ENTRY_RE.finditer(content))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        yield m.group("rest"), content[m.end():end][:BODY_SCAN_CHARS]


def scan_producer_mentions(root: Path, filename: str) -> list:
    """Find hook/settings lines mentioning a cap-notice file, so the skill can
    judge whether the declared producer is still wired (writer vs mere reader)."""
    mentions = []
    targets = []
    hooks = root / "hooks"
    if hooks.is_dir():
        targets.extend(sorted(hooks.rglob("*.py")))
    settings = root / "settings.json"
    if settings.is_file():
        targets.append(settings)
    for t in targets:
        try:
            for n, line in enumerate(
                    t.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if filename in line:
                    mentions.append({
                        "file": str(t.relative_to(root)), "line": n,
                        "text": line.strip()[:120],
                        "writer_hint": bool(re.search(
                            r"write|open\(|>>|append", line, re.IGNORECASE)),
                    })
                    if len(mentions) >= 20:
                        return mentions
        except OSError:
            continue
    return mentions


def analyze(topics_dir):
    topics = Path(topics_dir)
    files = sorted(topics.glob("*.md"))
    today = datetime.date.today()
    repo_root = topics.parent.parent  # ~/.claude for the canonical layout

    inventory = {}
    stale_observed, tombstones, promote_candidates, fixed_entries = [], [], [], []
    auto_captured, version_tags, oversized, mixed_format = [], [], [], []
    stale_deep_refs, large_reference_files, cap_notice_files = [], [], []
    titles_seen = {}  # norm title -> [(file, raw)]

    for f in files:
        content = f.read_text(encoding="utf-8", errors="replace")
        tag_counts = {}
        header_count = 0
        tagged_headers = 0
        for e, body in iter_entries(content):
            header_count += 1
            tags = leading_tags(e)
            if tags or e.lstrip().startswith("PROMOTE-CANDIDATE"):
                tagged_headers += 1
            for tag in tags:
                base = tag.split(":", 1)[0]
                tag_counts[base] = tag_counts.get(base, 0) + 1
                if tag.startswith(("workaround:", "until:", "experimental:")):
                    version_tags.append({"file": f.name, "tag": tag, "entry": e[:90]})
            titles_seen.setdefault(norm_title(e), []).append((f.name, e[:90]))

            d = DATE_RE.search(e)
            age = None
            if d:
                try:
                    age = (today - datetime.date.fromisoformat(d.group(1))).days
                except ValueError:
                    sys.stderr.write(
                        f"warning: {f.name}: invalid date '{d.group(1)}' in entry "
                        f"'{e[:60]}' - treated as undated\n")
            row = {"file": f.name, "entry": e[:90], "age_days": age}
            keep = bool(KEEP_DECISION_RE.search(body))
            if "[observed]" in e and age is not None and age > STALE_OBSERVED_DAYS:
                stale_observed.append(row)
            if "[promoted]" in e:
                tombstones.append(dict(row, keep_decision=keep))
            if "PROMOTE-CANDIDATE" in e:
                promote_candidates.append(row)
            if "[FIXED]" in e:
                fixed_entries.append(dict(row, keep_decision=keep))
            if "[auto-captured]" in e:
                low = (e + "\n" + body).lower()
                junk = [m for m in JUNK_MARKERS if m in low]
                auto_captured.append(dict(row, junk_markers=junk))

        # Bullet-style entries at top level alongside ### entries → mixed format
        bullet_entries = re.findall(r"^- \[(?:observed|confirmed|promoted)\]", content, re.MULTILINE)
        if tagged_headers and bullet_entries:
            mixed_format.append({"file": f.name, "headers": tagged_headers,
                                 "bullets": len(bullet_entries)})

        # Format classification: tagged ### entries = entry-format; a file of
        # structured prose sections (airlock.md, kaggle.md, azure-automation.md)
        # is a reference guide, not an empty entry file.
        if tagged_headers and bullet_entries:
            fmt = "mixed"
        elif tagged_headers:
            fmt = "entry-format"
        else:
            fmt = "reference-guide"

        for m in DEEP_REF_RE.finditer(content):
            ref = m.group(1).strip().strip("`")
            candidates = [Path(os.path.expanduser(ref)),
                          Path.home() / "Documents" / ref,
                          topics.parent / ref]
            if not any(c.exists() for c in candidates):
                stale_deep_refs.append({"file": f.name, "ref": ref})

        size = len(content)
        has_cap_notice = bool(CAP_NOTICE_RE.search(content[:600]))
        if has_cap_notice:
            cap_notice_files.append({
                "file": f.name, "bytes": size,
                "producer_mentions": scan_producer_mentions(repo_root, f.name),
            })
        if size > OVERSIZED_BYTES and not has_cap_notice:
            row = {"file": f.name, "bytes": size, "entries": header_count,
                   "format": fmt}
            # Reference guides are size-expected; report them separately so the
            # oversized list means "entry file that may need a sub-topic split".
            (large_reference_files if fmt == "reference-guide" else oversized).append(row)

        inventory[f.name] = {"bytes": size, "entries": header_count,
                             "tagged_entries": tagged_headers, "format": fmt,
                             "tags": tag_counts}

    duplicate_titles = [
        {"title": t, "locations": locs}
        for t, locs in sorted(titles_seen.items())
        if len(locs) > 1 and t
    ]

    return {
        "generated": today.isoformat(),
        "topics_dir": str(topics),
        "inventory": inventory,
        "totals": {
            "files": len(files),
            "entries": sum(v["entries"] for v in inventory.values()),
            "bytes": sum(v["bytes"] for v in inventory.values()),
        },
        "stale_observed": sorted(stale_observed, key=lambda r: -(r["age_days"] or 0)),
        "promoted_tombstones": tombstones,
        "promote_candidates": promote_candidates,
        "fixed_entries": fixed_entries,
        "auto_captured": auto_captured,
        "duplicate_titles": duplicate_titles,
        "stale_deep_references": stale_deep_refs,
        "version_tags": version_tags,
        "oversized_files": sorted(oversized, key=lambda r: -r["bytes"]),
        "large_reference_files": sorted(large_reference_files, key=lambda r: -r["bytes"]),
        "cap_notice_files": cap_notice_files,
        "mixed_format": mixed_format,
    }


def preflight(topics_dir):
    """Step 15b contention/divergence classification, mechanized.

    Returns per-tracked-topic-file verdicts:
      SAFE            clean vs HEAD and vs origin/main → editable (in a worktree)
      DEFER_DIRTY     dirty with concurrent work → do not edit
      DEFER_DIVERGED  differs between HEAD and origin/main → local base is stale
      DEFER_UNTRACKED another session may be mid-creation → do not race it
    """
    topics = Path(topics_dir).resolve()

    def git(*args, cwd=None, timeout=60):
        return subprocess.run(["git", "-C", str(cwd or topics), *args],
                              capture_output=True, text=True, timeout=timeout)

    top = git("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return {"available": False, "error": top.stderr.strip()[:200]}
    root = Path(top.stdout.strip())
    rel = topics.relative_to(root).as_posix()

    fetched = git("fetch", "origin", "main", "--quiet", cwd=root, timeout=120).returncode == 0
    behind_p = git("rev-list", "--count", "HEAD..origin/main", cwd=root)
    behind = int(behind_p.stdout.strip()) if behind_p.returncode == 0 else None

    status = git("status", "--porcelain", "--", rel, cwd=root).stdout.splitlines()
    dirty = {line[3:].strip() for line in status if line[:2].strip() and not line.startswith("??")}
    untracked = {line[3:].strip() for line in status if line.startswith("??")}
    diverged_p = git("diff", "--name-only", "HEAD", "origin/main", "--", rel, cwd=root)
    diverged = set(diverged_p.stdout.splitlines()) if diverged_p.returncode == 0 else set()
    tracked = git("ls-files", "--", rel, cwd=root).stdout.splitlines()

    files = {}
    for t in tracked:
        name = Path(t).name
        if t in dirty:
            files[name] = "DEFER_DIRTY"
        elif t in diverged:
            files[name] = "DEFER_DIVERGED"
        else:
            files[name] = "SAFE"
    for u in untracked:
        files[Path(u).name] = "DEFER_UNTRACKED"

    markers = root / ".session-active"
    sessions = sorted(p.name for p in markers.iterdir()) if markers.is_dir() else []
    return {
        "available": True,
        "repo_root": str(root),
        "fetched": fetched,
        "behind_origin_main": behind,
        "files": files,
        "safe_count": sum(1 for v in files.values() if v == "SAFE"),
        "deferred_count": sum(1 for v in files.values() if v != "SAFE"),
        "live_session_markers": sessions,
    }


def main():
    args = [a for a in sys.argv[1:] if a != "--preflight"]
    want_preflight = "--preflight" in sys.argv[1:]
    topics_dir = args[0] if args else os.path.expanduser(
        "~/.claude/agent-memory/topics")
    if not os.path.isdir(topics_dir):
        sys.stderr.write(f"ERROR: topics dir not found: {topics_dir}\n")
        sys.exit(1)
    report = analyze(topics_dir)
    if want_preflight:
        report["preflight"] = preflight(topics_dir)
    out = os.path.join(tempfile.gettempdir(),
                       f"memory_report_{report['generated']}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    t = report["totals"]
    kept_fixed = sum(1 for r in report["fixed_entries"] if r.get("keep_decision"))
    junk_auto = sum(1 for r in report["auto_captured"] if r.get("junk_markers"))
    line = (
        f"memory analyze: {t['files']} files, {t['entries']} entries, {t['bytes']:,}B | "
        f"{len(report['stale_observed'])} stale-observed, "
        f"{len(report['promoted_tombstones'])} tombstones, "
        f"{len(report['promote_candidates'])} promote-candidates, "
        f"{len(report['fixed_entries'])} fixed ({kept_fixed} kept), "
        f"{len(report['auto_captured'])} auto-captured ({junk_auto} junk-marked), "
        f"{len(report['duplicate_titles'])} dup-titles, "
        f"{len(report['stale_deep_references'])} stale-deep-refs, "
        f"{len(report['oversized_files'])} oversized, "
        f"{len(report['large_reference_files'])} large-reference, "
        f"{len(report['mixed_format'])} mixed-format")
    pf = report.get("preflight")
    if pf:
        if pf.get("available"):
            line += (f" | preflight: {pf['behind_origin_main']} behind, "
                     f"{pf['safe_count']} SAFE / {pf['deferred_count']} deferred")
        else:
            line += " | preflight: unavailable"
    sys.stderr.write(line + "\n")
    print(out)


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>")
        sys.exit(0)
    main()
